"""Nursery dates from letters: special events, early closing, closure days (B-19).

The nursery sends its dates as Word files. The family uploads the file (or
pastes text); the NAS extracts the text in memory, never stores the file,
and suggests dates. Nothing is saved before a person reviews and confirms
the list (B-11, Q-01).

Recognition:
* Claude (if an API key is configured): receives only the letter text after
  the NAS removed e-mail addresses, phone numbers, street addresses, postal
  codes and links (D-02), plus today's date for years that are missing. The
  exact text sent is returned so the family can see what left the NAS.
* Local fallback (demo, no key, limit reached, Claude error): date and time
  patterns per line. Always marked as "bitte prüfen".

Saving:
* event: shown in plan, today card and widget.
* early_close: shown as "Krippe schließt um …". If the pickup that day is
  planned later, the pickup person gets a task; the plan itself is not
  changed without agreement (B-11).
* closed: handed to Closures (pending, the other parent confirms).
"""
from datetime import date, datetime, timedelta
import io
import json
import logging
import os
import re
from typing import Literal
import xml.etree.ElementTree as ET
import zipfile

import httpx
from fastapi import HTTPException, Request
from pydantic import BaseModel, Field

from integrations import TZ, notify

LOG = logging.getLogger('uvicorn.error.family_os.nursery')
API_URL = 'https://api.anthropic.com/v1/messages'
DEFAULT_MODEL = 'claude-haiku-4-5-20251001'
MAX_FILE = 2 * 1024 * 1024
MAX_TEXT = 12000
PEOPLE = {'tobi': 'Tobi', 'britta': 'Britta'}
KIND_LABELS = {'event': 'Veranstaltung', 'early_close': 'Früher Schluss', 'closed': 'Schließtag'}
TIME = r'^([01]\d|2[0-3]):[0-5]\d$'
W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'

MONTHS = {'januar': 1, 'jan': 1, 'februar': 2, 'feb': 2, 'märz': 3, 'maerz': 3, 'mär': 3, 'april': 4, 'apr': 4,
          'mai': 5, 'juni': 6, 'jun': 6, 'juli': 7, 'jul': 7, 'august': 8, 'aug': 8, 'september': 9, 'sep': 9,
          'sept': 9, 'oktober': 10, 'okt': 10, 'november': 11, 'nov': 11, 'dezember': 12, 'dez': 12}

SYSTEM = (
    'Du liest Elternbriefe einer Kinderkrippe und findest Termine, die für die Eltern wichtig sind. '
    'Arten: "veranstaltung" (Fest, Ausflug, Elternabend, Fototermin usw.), "frueher_schluss" (Krippe schließt an '
    'dem Tag früher als üblich; schluss = Uhrzeit), "geschlossen" (Schließtag, Krippe ganz zu; bei Zeiträumen '
    'bis_datum setzen). Datumsangaben ohne Jahr beziehen sich auf den nächsten passenden Termin ab heute. '
    'Uhrzeiten im Format HH:MM. Titel kurz (max. 60 Zeichen), Hinweis nur für Mitbringen/Kleidung/Ablauf '
    '(max. 150 Zeichen). Erfinde nichts; nur Termine, die im Text stehen.'
)
TOOL = {
    'name': 'termine',
    'description': 'Gefundene Krippen-Termine zurückgeben.',
    'input_schema': {
        'type': 'object',
        'properties': {'termine': {'type': 'array', 'items': {
            'type': 'object',
            'properties': {
                'datum': {'type': 'string', 'description': 'YYYY-MM-DD'},
                'bis_datum': {'type': 'string', 'description': 'YYYY-MM-DD, nur bei mehrtägigen Schließzeiten'},
                'art': {'type': 'string', 'enum': ['veranstaltung', 'frueher_schluss', 'geschlossen']},
                'titel': {'type': 'string'},
                'beginn': {'type': 'string', 'description': 'HH:MM'},
                'ende': {'type': 'string', 'description': 'HH:MM'},
                'schluss': {'type': 'string', 'description': 'HH:MM, nur bei frueher_schluss'},
                'hinweis': {'type': 'string'},
            },
            'required': ['datum', 'art', 'titel'],
        }}},
        'required': ['termine'],
    },
}
ART = {'veranstaltung': 'event', 'frueher_schluss': 'early_close', 'geschlossen': 'closed'}


# --- text -----------------------------------------------------------------

def docx_text(data):
    """Paragraphs and table rows of a .docx file as plain text lines."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            info = archive.getinfo('word/document.xml')
            if info.file_size > 20 * 1024 * 1024:
                raise HTTPException(422, 'Die Word-Datei ist zu groß.')
            root = ET.fromstring(archive.read(info))
    except (zipfile.BadZipFile, KeyError, ET.ParseError):
        raise HTTPException(422, 'Das ist keine lesbare Word-Datei (.docx). Ältere .doc-Dateien bitte in Word als .docx speichern.')

    def paragraph(node):
        parts = []
        for element in node.iter():
            if element.tag == W + 't':
                parts.append(element.text or '')
            elif element.tag == W + 'tab':
                parts.append('\t')
            elif element.tag in (W + 'br', W + 'cr'):
                parts.append(' ')
        return ''.join(parts).strip()

    lines = []
    body = root.find(W + 'body')
    for block in (body if body is not None else []):
        if block.tag == W + 'p':
            lines.append(paragraph(block))
        elif block.tag == W + 'tbl':
            for row in block.iter(W + 'tr'):
                cells = [' '.join(filter(None, (paragraph(p) for p in cell.iter(W + 'p')))) for cell in row.findall(W + 'tc')]
                lines.append(' | '.join(c for c in cells if c))
    return '\n'.join(line for line in lines if line)


def redact(text):
    """Remove contact data and addresses before anything leaves the NAS (D-02)."""
    text = re.sub(r'\S+@\S+', '[E-Mail entfernt]', text)
    text = re.sub(r'https?://\S+|www\.\S+', '[Link entfernt]', text)
    text = re.sub(r'(?:\+49|\b0)[\d /()-]{6,}\d', '[Telefon entfernt]', text)
    text = re.sub(r'\b[A-ZÄÖÜ][\wäöüß.-]*(?:straße|strasse|str\.|weg|platz|allee|gasse|ring)\s*\d+\s*[a-z]?\b',
                  '[Adresse entfernt]', text, flags=re.IGNORECASE)
    text = re.sub(r'\b\d{5}\s+[A-ZÄÖÜ][\wäöüß-]+', '[Ort entfernt]', text)
    return text[:MAX_TEXT]


# --- local recognition -----------------------------------------------------

def _year_for(month, day, today):
    candidate = date(today.year, month, day)
    return candidate if candidate >= today - timedelta(days=30) else date(today.year + 1, month, day)


def _dates(line, today):
    found = []
    for match in re.finditer(r'\b(\d{1,2})\.\s?(\d{1,2})\.(\d{2,4})?', line):
        day, month, year = int(match[1]), int(match[2]), match[3]
        try:
            if year:
                year = int(year) + (2000 if len(year) == 2 else 0)
                found.append(date(year, month, day))
            else:
                found.append(_year_for(month, day, today))
        except ValueError:
            continue
    for match in re.finditer(r'\b(\d{1,2})\.\s*(' + '|'.join(sorted(MONTHS, key=len, reverse=True)) + r')\.?(?:\s+(\d{4}))?',
                             line, flags=re.IGNORECASE):
        month = MONTHS[match[2].lower()]
        try:
            found.append(date(int(match[3]), month, int(match[1])) if match[3] else _year_for(month, int(match[1]), today))
        except ValueError:
            continue
    return sorted(set(found))


def _times(line):
    times = []
    for match in re.finditer(r'\b([01]?\d|2[0-3])(?:[:.]([0-5]\d))?\s*(?=Uhr|-|–|bis)', line):
        times.append(f'{int(match[1]):02d}:{match[2] or "00"}')
    for match in re.finditer(r'(?:-|–|bis)\s*([01]?\d|2[0-3])(?:[:.]([0-5]\d))?\s*Uhr', line):
        value = f'{int(match[1]):02d}:{match[2] or "00"}'
        if value not in times:
            times.append(value)
    return times


DATE_TEXT = (r'\b\d{1,2}\.\s?\d{1,2}\.(\d{2,4})?|\b\d{1,2}\.\s*(' + '|'.join(sorted(MONTHS, key=len, reverse=True))
             + r')\.?(\s+\d{4})?')
TIME_TEXT = r'(ab|um|von|bis)?\s*\b([01]?\d|2[0-3])([:.][0-5]\d)?\s*((-|–|bis)\s*([01]?\d|2[0-3])([:.][0-5]\d)?\s*)?Uhr\b'


def _title_and_note(line):
    """Short title without date and times; the rest of the line becomes the note."""
    text = re.sub(DATE_TEXT, ' ', line, flags=re.IGNORECASE)
    text = re.sub(r'\b(Mo|Di|Mi|Do|Fr|Sa|So)(ntag|nstag|ttwoch|nnerstag|eitag|mstag)?\b\.?,?', ' ', text)
    text = re.sub(r'^\s*(-|–|bis)\s*', ' ', text)
    parts = [re.sub(TIME_TEXT, ' ', p, flags=re.IGNORECASE) for p in re.split(r'\s*\|\s*', text)]
    parts = [re.sub(r'\s+', ' ', p).strip(' –-,:;.') for p in parts]
    parts = [re.sub(r'^(am|ab|an|vom)\s+|\s+(bereits|schon|um)$', '', p, flags=re.IGNORECASE) for p in parts]
    parts = [p for p in parts if p]
    if not parts:
        return 'Termin der Krippe', ''
    title, rest = parts[0], parts[1:]
    if re.fullmatch(r'(die )?krippe schließt|schließt die krippe', title, flags=re.IGNORECASE):
        title = 'Krippe schließt früher'
    if not rest and ',' in title:
        title, *rest = [p.strip() for p in title.split(',') if p.strip()]
    return title[:60], ', '.join(rest)[:200]


def local_items(text, today):
    items = []
    for line in text.splitlines():
        days = _dates(line, today)
        if not days:
            continue
        lower = line.lower()
        times = _times(line)
        title, note = _title_and_note(line)
        if 'geschlossen' in lower or 'schließtag' in lower or 'schliesstag' in lower:
            if any(w in lower for w in ('ab ', 'früher', 'frueher', 'bereits um')) and times:
                items.append({'day': str(days[0]), 'kind': 'early_close', 'title': title, 'start': None,
                              'end': times[-1], 'note': note})
            else:
                end = days[-1] if len(days) > 1 and ('bis' in lower or '-' in line or '–' in line) else days[0]
                items.append({'day': str(days[0]), 'until': str(end) if end != days[0] else None, 'kind': 'closed',
                              'title': title, 'start': None, 'end': None, 'note': ''})
        elif any(w in lower for w in ('schließt', 'schliesst', 'früher', 'frueher', 'abholung bis')) and times:
            items.append({'day': str(days[0]), 'kind': 'early_close', 'title': title, 'start': None,
                          'end': times[-1], 'note': note})
        else:
            for day in days[:3]:
                items.append({'day': str(day), 'kind': 'event', 'title': title,
                              'start': times[0] if times else None, 'end': times[1] if len(times) > 1 else None, 'note': note})
    return items


def clean(raw, today):
    """Validate a suggested item; None if unusable."""
    try:
        day = date.fromisoformat(str(raw.get('day', '')))
    except ValueError:
        return None
    if not today - timedelta(days=60) <= day <= today + timedelta(days=400):
        return None
    kind = raw.get('kind')
    if kind not in KIND_LABELS:
        return None

    def time(value):
        return value if isinstance(value, str) and re.match(TIME, value) else None

    until = None
    if kind == 'closed' and raw.get('until'):
        try:
            until = date.fromisoformat(str(raw['until']))
        except ValueError:
            until = None
        if until and not day < until <= day + timedelta(days=31):
            until = None
    item = {'day': str(day), 'until': str(until) if until else None, 'kind': kind,
            'title': str(raw.get('title') or KIND_LABELS[kind]).strip()[:80],
            'start': time(raw.get('start')), 'end': time(raw.get('end')), 'note': str(raw.get('note') or '').strip()[:200]}
    if kind == 'early_close' and not item['end']:
        return None
    return item


# --- input models ----------------------------------------------------------

class TextInput(BaseModel):
    text: str = Field(min_length=10, max_length=50000)


class EventInput(BaseModel):
    day: date
    until: date | None = None
    kind: Literal['event', 'early_close', 'closed']
    title: str = Field(min_length=1, max_length=80)
    start: str | None = Field(default=None, pattern=TIME)
    end: str | None = Field(default=None, pattern=TIME)
    note: str = Field(default='', max_length=200)


class SaveInput(BaseModel):
    items: list[EventInput] = Field(min_length=1, max_length=40)
    source: Literal['manual', 'import'] = 'manual'


class Nursery:
    def __init__(self, db, demo, closures, api_key=None, model=None, monthly_calls=None, transport=None):
        self.db, self.demo, self.closures = db, demo, closures
        self.api_key = api_key if api_key is not None else os.getenv('FOS_ANTHROPIC_API_KEY', '').strip()
        self.model = model or os.getenv('FOS_CLAUDE_MODEL', '').strip() or DEFAULT_MODEL
        self.monthly_calls = monthly_calls or int(os.getenv('FOS_CLAUDE_MONTHLY_CALLS', '40') or 40)
        self.transport = transport

    # Claude usage is shared with the meal suggestions (one monthly limit, O-11).
    def usage(self, conn):
        row = conn.execute('SELECT value FROM metadata WHERE key=?', ('claude_usage:' + datetime.now(TZ).strftime('%Y-%m'),)).fetchone()
        return json.loads(row[0]) if row else {'calls': 0, 'input_tokens': 0, 'output_tokens': 0}

    def record_usage(self, usage):
        key = 'claude_usage:' + datetime.now(TZ).strftime('%Y-%m')
        with self.db() as conn:
            current = self.usage(conn)
            current['calls'] += 1
            current['input_tokens'] += int(usage.get('input_tokens', 0))
            current['output_tokens'] += int(usage.get('output_tokens', 0))
            conn.execute('INSERT OR REPLACE INTO metadata VALUES(?,?)', (key, json.dumps(current)))

    async def ask_claude(self, text, today):
        sent = redact(text)
        body = {'model': self.model, 'max_tokens': 2048, 'system': SYSTEM, 'tools': [TOOL],
                'tool_choice': {'type': 'tool', 'name': 'termine'},
                'messages': [{'role': 'user', 'content': f'Heute ist {today.isoformat()}.\n\nElternbrief:\n{sent}'}]}
        headers = {'x-api-key': self.api_key, 'anthropic-version': '2023-06-01', 'content-type': 'application/json'}
        async with httpx.AsyncClient(timeout=60, transport=self.transport) as client:
            response = await client.post(API_URL, json=body, headers=headers)
        if response.status_code != 200:
            raise RuntimeError(f'Claude HTTP {response.status_code}')
        data = response.json()
        self.record_usage(data.get('usage', {}))
        block = next((b for b in data.get('content', []) if b.get('type') == 'tool_use'), None)
        if not block:
            raise RuntimeError('Claude-Antwort ohne Termine')
        items = []
        for raw in block.get('input', {}).get('termine', []):
            items.append({'day': raw.get('datum'), 'until': raw.get('bis_datum'), 'kind': ART.get(raw.get('art')),
                          'title': raw.get('titel'), 'start': raw.get('beginn'),
                          'end': raw.get('schluss') if raw.get('art') == 'frueher_schluss' else raw.get('ende'),
                          'note': raw.get('hinweis')})
        return items, sent

    async def analyse(self, text):
        today = datetime.now(TZ).date()
        text = text.strip()
        if not text:
            raise HTTPException(422, 'In der Datei steht kein lesbarer Text.')
        source, sent, notice = 'local', None, ''
        items = None
        if self.api_key and not self.demo:
            with self.db() as conn:
                used = self.usage(conn)['calls']
            if used >= self.monthly_calls:
                notice = f'Das Monatslimit von {self.monthly_calls} Claude-Anfragen ist erreicht; lokal erkannt.'
            else:
                try:
                    items, sent = await self.ask_claude(text, today)
                    source = 'claude'
                except (httpx.HTTPError, RuntimeError, ValueError) as error:
                    LOG.warning('Claude für Krippen-Termine nicht verfügbar: %s', error)
                    notice = 'Claude war nicht erreichbar; die Termine wurden lokal erkannt.'
        if items is None:
            items = local_items(text, today)
        cleaned, seen = [], set()
        for raw in items:
            item = clean(raw, today)
            key = item and (item['day'], item['kind'], item['title'].lower())
            if item and key not in seen:
                seen.add(key)
                cleaned.append(item)
        cleaned.sort(key=lambda i: (i['day'], i['kind']))
        with self.db() as conn:
            for item in cleaned:
                item['existing'] = self.existing(conn, item)
        return {'source': source, 'model': self.model if source == 'claude' else None, 'sent': sent,
                'notice': notice, 'items': cleaned}

    @staticmethod
    def existing(conn, item):
        if item['kind'] == 'closed':
            return bool(conn.execute('SELECT 1 FROM day_closures WHERE day=?', (item['day'],)).fetchone())
        return bool(conn.execute("SELECT 1 FROM nursery_events WHERE day=? AND kind=? AND lower(title)=lower(?) AND state='active'",
                                 (item['day'], item['kind'], item['title'])).fetchone())

    # --- saving ------------------------------------------------------------

    @staticmethod
    def label(item):
        day = date.fromisoformat(str(item['day']))
        text = f"{day.strftime('%d.%m.')} {item['title']}"
        if item['kind'] == 'early_close':
            text += f" (schließt {item['end']} Uhr)"
        return text

    def pickup_task(self, conn, actor, event_id, item):
        """Early closing: tell the pickup person if the planned pickup is later (B-11: no silent change)."""
        slot = conn.execute("SELECT owner,start FROM appointments WHERE day=? AND kind='pickup'", (str(item.day),)).fetchone()
        if not slot or not slot['start'] or slot['start'] <= item.end:
            return None
        owner = slot['owner'] or actor
        weekday = ['Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa', 'So'][item.day.weekday()]
        due = datetime.combine(item.day - timedelta(days=1), datetime.min.time(), TZ).replace(hour=18)
        title = 'Abholung früher: Krippe schließt ' + item.end
        details = (f"{weekday} {item.day.strftime('%d.%m.')}: {item.title}. Die Krippe schließt um {item.end} Uhr, "
                   f"geplant ist die Abholung um {slot['start']} Uhr. Bitte die Abholzeit anpassen (Vorschlag im Plan).")
        conn.execute('INSERT INTO tasks(owner,title,details,due,created) VALUES(?,?,?,?,?)',
                     (owner, title, details, due.isoformat(), datetime.now(TZ).isoformat(timespec='seconds')))
        notify(conn, owner, f'nursery-early:{event_id}', title, details, False)
        return owner

    def save(self, conn, actor, data):
        saved, closed, tasks = [], [], []
        for item in sorted(data.items, key=lambda i: i.day):
            if item.kind == 'closed':
                last = item.until if item.until and item.until > item.day else item.day
                if (last - item.day).days > 31:
                    raise HTTPException(422, 'Ein Schließzeitraum darf höchstens 31 Tage lang sein.')
                days = [str(item.day + timedelta(days=i)) for i in range((last - item.day).days + 1)
                        if (item.day + timedelta(days=i)).weekday() < 5]
                if days:
                    self.closures.create_days(conn, actor, days, 'closed', item.title)
                    closed.append(self.label(item.model_dump()))
                continue
            if item.kind == 'early_close' and not item.end:
                raise HTTPException(422, 'Bei frühem Schluss fehlt die Uhrzeit.')
            if item.start and item.end and item.kind == 'event' and item.end <= item.start:
                raise HTTPException(422, f'{item.title}: Das Ende muss nach dem Beginn liegen.')
            cursor = conn.execute('INSERT INTO nursery_events(day,kind,title,start,end,note,source,creator,created) '
                                  'VALUES(?,?,?,?,?,?,?,?,?)',
                                  (str(item.day), item.kind, item.title.strip(), item.start if item.kind == 'event' else None,
                                   item.end, item.note.strip(), data.source, actor, datetime.now(TZ).isoformat(timespec='seconds')))
            saved.append(self.label(item.model_dump()))
            if item.kind == 'early_close':
                owner = self.pickup_task(conn, actor, cursor.lastrowid, item)
                if owner:
                    tasks.append(PEOPLE[owner])
        if saved:
            other = 'britta' if actor == 'tobi' else 'tobi'
            notify(conn, other, 'nursery:' + datetime.now(TZ).isoformat(timespec='seconds'), 'Neue Krippen-Termine',
                   f"{PEOPLE[actor]} hat eingetragen: " + '; '.join(saved) + '.', False)
            conn.execute('INSERT INTO audit(actor,action,details,created) VALUES(?,?,?,?)',
                         (actor, 'Krippen-Termine eingetragen', '; '.join(saved), datetime.now(TZ).isoformat(timespec='seconds')))
        return {'saved': len(saved), 'closed': len(closed), 'tasks': tasks}

    @staticmethod
    def listing(conn, first, last):
        rows = conn.execute("SELECT id,day,kind,title,start,end,note,creator FROM nursery_events "
                            "WHERE state='active' AND day BETWEEN ? AND ? ORDER BY day,start", (str(first), str(last)))
        return [dict(r) for r in rows]

    # --- routes ------------------------------------------------------------

    def routes(self, app, identity):
        db = self.db

        @app.post('/api/nursery/import/docx')
        async def import_docx(request: Request):
            with db() as conn:
                identity(request, conn)
            data = await request.body()
            if not data:
                raise HTTPException(422, 'Bitte eine Word-Datei auswählen.')
            if len(data) > MAX_FILE:
                raise HTTPException(413, 'Die Datei ist größer als 2 MB.')
            # Read in memory only; the file itself is never stored.
            return await self.analyse(docx_text(data))

        @app.post('/api/nursery/import/text')
        async def import_text(data: TextInput, request: Request):
            with db() as conn:
                identity(request, conn)
            return await self.analyse(data.text)

        @app.post('/api/nursery/events')
        def save_events(data: SaveInput, request: Request):
            with db() as conn:
                actor = identity(request, conn)
                return self.save(conn, actor, data)

        @app.post('/api/nursery/events/{event_id}/delete')
        def delete_event(event_id: int, request: Request):
            with db() as conn:
                actor = identity(request, conn)
                row = conn.execute("SELECT * FROM nursery_events WHERE id=? AND state='active'", (event_id,)).fetchone()
                if not row:
                    raise HTTPException(409, 'Dieser Termin besteht nicht mehr. Bitte neu laden.')
                conn.execute("UPDATE nursery_events SET state='deleted' WHERE id=?", (event_id,))
                conn.execute('INSERT INTO audit(actor,action,details,created) VALUES(?,?,?,?)',
                             (actor, 'Krippen-Termin entfernt', self.label(dict(row)), datetime.now(TZ).isoformat(timespec='seconds')))
            return {'ok': True}
