"""Nanny planning, hours and monthly statement (requirements N-01 to N-07).

Lifecycle of a shift:

    wish ──request──▶ requested ──confirm──▶ confirmed ──cancel(paid?)──▶ cancelled
      │                   │  └────decline──▶ declined
      └──confirm──────────┘ (agreed directly)
      wish/requested ──cancel──▶ cancelled (never paid)

* The nanny is contacted by the parents via WhatsApp. Family OS only prepares
  the message text; sending it never changes a state (N-02, N-03).
* Planned times are billed unless a correction was recorded (decision O-04).
* Cancelled confirmed shifts are billed only if marked as paid (decision O-04).
* A closed month is frozen with its hourly rate. It can be reopened until it is
  marked as transferred. The statement contains wages only, no Minijob levies.
* Tobi maintains hours and billing (N-05) and receives the related tasks.
"""
from datetime import date, datetime, timedelta
import calendar
import json
from typing import Literal

from fastapi import HTTPException, Request
from pydantic import BaseModel, Field

from integrations import TZ, PEOPLE, notify

BILLING_OWNER = 'tobi'
DEFAULT_RATE_CENTS = 2000
TIME = r'^([01]\d|2[0-3]):[0-5]\d$'
BILLABLE_SQL = "(state='confirmed' OR (state='cancelled' AND paid_cancel=1))"


def now():
    return datetime.now(TZ).isoformat(timespec='seconds')


def minutes(start, end):
    h1, m1 = map(int, start.split(':'))
    h2, m2 = map(int, end.split(':'))
    return (h2 * 60 + m2) - (h1 * 60 + m1)


def month_of(day):
    return str(day)[:7]


def month_range(month):
    try:
        first = date.fromisoformat(month + '-01')
    except ValueError:
        raise HTTPException(422, 'Ungültiger Monat.')
    return first, first.replace(day=calendar.monthrange(first.year, first.month)[1])


def amount_cents(total_minutes, rate_cents):
    # Round half up to full cents.
    return (total_minutes * rate_cents * 2 + 60) // 120


MONTHS = ['Januar', 'Februar', 'März', 'April', 'Mai', 'Juni', 'Juli', 'August', 'September', 'Oktober', 'November', 'Dezember']


def month_label(month):
    return f'{MONTHS[int(month[5:7]) - 1]} {month[:4]}'


def label(row):
    day = date.fromisoformat(row['day'])
    weekdays = ['Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa', 'So']
    return f"{weekdays[day.weekday()]} {day.strftime('%d.%m.')} {row['start']}–{row['end']}"


class ShiftInput(BaseModel):
    day: date
    start: str = Field(default='16:00', pattern=TIME)
    end: str = Field(default='18:00', pattern=TIME)
    note: str = Field(default='', max_length=300)


class BatchInput(BaseModel):
    days: list[date] = Field(min_length=1, max_length=23)
    start: str = Field(default='16:00', pattern=TIME)
    end: str = Field(default='18:00', pattern=TIME)
    note: str = Field(default='', max_length=300)


class Answer(BaseModel):
    id: int
    version: int = Field(ge=1)
    answer: Literal['confirm', 'decline']


class AnswerInput(BaseModel):
    items: list[Answer] = Field(min_length=1, max_length=31)


class ShiftEdit(ShiftInput):
    version: int = Field(ge=1)


class Transition(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=31)
    versions: list[int] = Field(min_length=1, max_length=31)
    action: Literal['request', 'confirm', 'decline', 'cancel']
    paid: bool | None = None


class Correction(BaseModel):
    version: int = Field(ge=1)
    actual_start: str | None = Field(default=None, pattern=TIME)
    actual_end: str | None = Field(default=None, pattern=TIME)
    note: str = Field(default='', max_length=300)


class Settings(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    phone: str = Field(default='', max_length=20, pattern=r'^(\+?[0-9 ]{8,19})?$')
    rate_cents: int = Field(ge=100, le=10000)


class StatementAction(BaseModel):
    action: Literal['close', 'reopen', 'paid']


class Nanny:
    def __init__(self, db, demo):
        self.db, self.demo = db, demo
        if demo:
            self.seed()

    # --- helpers ---------------------------------------------------------

    def audit(self, conn, actor, action, details):
        conn.execute('INSERT INTO audit(actor,action,details,created) VALUES(?,?,?,?)', (actor, action, details, now()))

    def settings(self, conn):
        values = dict(conn.execute("SELECT key,value FROM metadata WHERE key LIKE 'nanny_%'").fetchall())
        return {'name': values.get('nanny_name', 'Nanny'), 'phone': values.get('nanny_phone', ''),
                'rate_cents': int(values.get('nanny_rate_cents', DEFAULT_RATE_CENTS))}

    def closed(self, conn, month):
        return conn.execute('SELECT * FROM nanny_statements WHERE month=?', (month,)).fetchone()

    def require_open_month(self, conn, day):
        if self.closed(conn, month_of(day)):
            raise HTTPException(409, 'Die Nanny-Abrechnung für diesen Monat ist abgeschlossen. Bitte zuerst wieder öffnen.')

    def require_no_clash(self, conn, data, own_id=0):
        clash = conn.execute("SELECT 1 FROM nanny_shifts WHERE day=? AND id!=? AND state IN ('wish','requested','confirmed') AND start<? AND end>?",
                             (str(data.day), own_id, data.end, data.start)).fetchone()
        if clash:
            raise HTTPException(409, 'An diesem Tag gibt es bereits einen überschneidenden Nanny-Termin.')

    def insert_wish(self, conn, actor, day, start, end, note):
        if minutes(start, end) <= 0:
            raise HTTPException(422, 'Das Ende muss nach dem Beginn liegen.')
        self.require_open_month(conn, day)
        if day < datetime.now(TZ).date():
            raise HTTPException(422, 'Neue Nanny-Wünsche bitte für heute oder später anlegen.')
        self.require_no_clash(conn, ShiftInput(day=day, start=start, end=end))
        cursor = conn.execute('INSERT INTO nanny_shifts(day,start,end,note,creator,created,updated) VALUES(?,?,?,?,?,?,?)',
                              (str(day), start, end, note.strip(), actor, now(), now()))
        row = self.shift(conn, cursor.lastrowid)
        self.audit(conn, actor, 'Nanny-Wunsch angelegt', label(row))
        return row

    def sync_request_task(self, conn, month):
        """Keep exactly one open 'Nanny anfragen' task per month while wishes exist."""
        first, last = month_range(month)
        wishes = conn.execute("SELECT COUNT(*) FROM nanny_shifts WHERE day BETWEEN ? AND ? AND state='wish'", (str(first), str(last))).fetchone()[0]
        task = conn.execute("SELECT id FROM tasks WHERE title='Nanny anfragen' AND nanny_shift_id IS NULL AND state='open' AND details LIKE ?",
                            (month + ':%',)).fetchone()
        details = (f'{month}: {wishes} ' + ('Wunsch' if wishes == 1 else 'Wünsche')
                   + f' für {month_label(month)} in einer WhatsApp-Nachricht anfragen und danach als angefragt markieren.')
        if wishes and task:
            conn.execute('UPDATE tasks SET details=? WHERE id=?', (details, task['id']))
        elif wishes:
            conn.execute('INSERT INTO tasks(owner,title,details,due,created) VALUES(?,?,?,?,?)',
                         (BILLING_OWNER, 'Nanny anfragen', details, now(), now()))
        elif task:
            conn.execute("UPDATE tasks SET state='superseded' WHERE id=?", (task['id'],))

    def apply(self, conn, actor, row, action, paid=None):
        allowed = {'request': {'wish'}, 'confirm': {'wish', 'requested'}, 'decline': {'requested'},
                   'cancel': {'wish', 'requested', 'confirmed'}}[action]
        target = {'request': 'requested', 'confirm': 'confirmed', 'decline': 'declined', 'cancel': 'cancelled'}[action]
        if row['state'] not in allowed:
            raise HTTPException(409, f'{label(row)}: Dieser Schritt passt nicht zum aktuellen Stand. Bitte neu laden.')
        self.require_open_month(conn, row['day'])
        if action == 'cancel' and row['state'] == 'confirmed':
            if paid is None:
                raise HTTPException(422, 'Bitte festlegen, ob der abgesagte Termin bezahlt wird.')
            paid = int(paid)
        else:
            paid = None
        conn.execute('UPDATE nanny_shifts SET state=?,paid_cancel=?,version=version+1,updated=? WHERE id=?',
                     (target, paid, now(), row['id']))
        self.close_tasks(conn, row['id'])
        text = {'request': 'Nanny angefragt', 'confirm': 'Nanny-Termin bestätigt', 'decline': 'Nanny kann nicht',
                'cancel': 'Nanny-Termin abgesagt'}[action]
        suffix = '' if paid is None else (' · wird bezahlt' if paid else ' · wird nicht bezahlt')
        self.audit(conn, actor, text, label(row) + suffix)

    def shift(self, conn, shift_id, version=None):
        row = conn.execute('SELECT * FROM nanny_shifts WHERE id=?', (shift_id,)).fetchone()
        if not row:
            raise HTTPException(404, 'Nanny-Termin nicht gefunden.')
        if version is not None and row['version'] != version:
            raise HTTPException(409, 'Dieser Nanny-Termin wurde inzwischen geändert. Bitte neu laden.')
        return row

    def close_tasks(self, conn, shift_id):
        conn.execute("UPDATE tasks SET state='superseded' WHERE nanny_shift_id=? AND state='open'", (shift_id,))

    def other(self, actor):
        return 'britta' if actor == 'tobi' else 'tobi'

    def lines(self, conn, month):
        first, last = month_range(month)
        rows = conn.execute(f'SELECT * FROM nanny_shifts WHERE day BETWEEN ? AND ? AND {BILLABLE_SQL} ORDER BY day,start', (str(first), str(last))).fetchall()
        result = []
        for row in rows:
            corrected = row['state'] == 'confirmed' and row['actual_start'] and row['actual_end']
            start, end = (row['actual_start'], row['actual_end']) if corrected else (row['start'], row['end'])
            result.append({'id': row['id'], 'day': row['day'], 'start': start, 'end': end, 'minutes': minutes(start, end),
                           'planned': f"{row['start']}–{row['end']}", 'corrected': bool(corrected),
                           'cancelled_paid': row['state'] == 'cancelled', 'note': row['correction_note']})
        return result

    def statement(self, conn, month):
        stored = self.closed(conn, month)
        if stored:
            data = dict(stored)
            data['lines'] = json.loads(data['lines'])
            data['state'] = 'paid' if stored['paid'] else 'closed'
            return data
        lines = self.lines(conn, month)
        rate = self.settings(conn)['rate_cents']
        total = sum(line['minutes'] for line in lines)
        first, last = month_range(month)
        unresolved = conn.execute("SELECT COUNT(*) FROM nanny_shifts WHERE day BETWEEN ? AND ? AND state IN ('wish','requested')", (str(first), str(last))).fetchone()[0]
        return {'month': month, 'state': 'open', 'rate_cents': rate, 'minutes': total, 'amount_cents': amount_cents(total, rate),
                'lines': lines, 'unresolved': unresolved, 'month_over': datetime.now(TZ).date() > last}

    # --- background ------------------------------------------------------

    def periodic(self, instant=None):
        """From the 1st of a month (9 o'clock) remind Tobi to settle the previous month."""
        instant = (instant or datetime.now(TZ)).astimezone(TZ)
        if instant.hour < 9:
            return
        previous = month_of(instant.date().replace(day=1) - timedelta(days=1))
        first, last = month_range(previous)
        with self.db() as conn:
            if conn.execute("SELECT 1 FROM metadata WHERE key=?", ('nanny_billing_task:' + previous,)).fetchone():
                return
            if self.closed(conn, previous):
                return
            count = conn.execute(f'SELECT COUNT(*) FROM nanny_shifts WHERE day BETWEEN ? AND ? AND {BILLABLE_SQL}', (str(first), str(last))).fetchone()[0]
            if not count:
                return
            if not conn.execute('SELECT 1 FROM users WHERE id=?', (BILLING_OWNER,)).fetchone():
                return
            conn.execute("INSERT INTO metadata VALUES(?,?)", ('nanny_billing_task:' + previous, instant.isoformat()))
            conn.execute('INSERT INTO tasks(owner,title,details,due,created) VALUES(?,?,?,?,?)',
                         (BILLING_OWNER, 'Nanny-Abrechnung', f'{previous}: {count} Termine prüfen, Abweichungen nachtragen und den Monat abschließen.', instant.isoformat(), now()))
            notify(conn, BILLING_OWNER, 'nanny-billing:' + previous, 'Nanny-Abrechnung', f'{previous}: Stunden prüfen und den Monat abschließen.', False, instant)

    # --- demo ------------------------------------------------------------

    def seed(self):
        with self.db() as conn:
            if conn.execute("SELECT 1 FROM metadata WHERE key='nanny_seeded'").fetchone():
                return
            today = datetime.now(TZ).date()

            def weekday(offset, target):
                day = today + timedelta(days=offset)
                while day.weekday() != target:
                    day += timedelta(days=1)
                return day

            samples = [(weekday(-9, 2), 'confirmed'), (weekday(2, 1), 'requested'), (weekday(6, 3), 'wish')]
            for day, state in samples:
                conn.execute('INSERT INTO nanny_shifts(day,start,end,state,creator,created,updated) VALUES(?,?,?,?,?,?,?)',
                             (str(day), '16:00', '18:00', state, 'tobi', now(), now()))
            conn.execute("INSERT INTO metadata VALUES('nanny_seeded','1')")

    # --- routes ----------------------------------------------------------

    def routes(self, app, identity):
        db = self.db

        @app.get('/api/nanny')
        def overview(request: Request, month: str):
            first, last = month_range(month)
            with db() as conn:
                identity(request, conn)
                shifts = [dict(r) for r in conn.execute('SELECT * FROM nanny_shifts WHERE day BETWEEN ? AND ? ORDER BY day,start', (str(first), str(last)))]
                return {'month': month, 'shifts': shifts, 'statement': self.statement(conn, month), 'settings': self.settings(conn),
                        'billing_owner': BILLING_OWNER, 'today': str(datetime.now(TZ).date())}

        @app.post('/api/nanny/shifts')
        def create(data: ShiftInput, request: Request):
            with db() as conn:
                actor = identity(request, conn)
                row = self.insert_wish(conn, actor, data.day, data.start, data.end, data.note)
                self.sync_request_task(conn, month_of(row['day']))
                notify(conn, self.other(actor), f'nanny-wish:{row["id"]}', 'Neuer Nanny-Wunsch', f'{PEOPLE[actor]} wünscht sich Nanny-Betreuung: {label(row)}.', False)
                return {'id': row['id']}

        @app.post('/api/nanny/shifts/batch')
        def create_month(data: BatchInput, request: Request):
            if len(set(data.days)) != len(data.days):
                raise HTTPException(422, 'Jeder Tag darf nur einmal ausgewählt werden.')
            months = {month_of(day) for day in data.days}
            if len(months) != 1:
                raise HTTPException(422, 'Bitte nur Tage aus einem Monat auswählen.')
            month = months.pop()
            with db() as conn:
                actor = identity(request, conn)
                rows = [self.insert_wish(conn, actor, day, data.start, data.end, data.note) for day in sorted(data.days)]
                self.sync_request_task(conn, month)
                notify(conn, self.other(actor), 'nanny-wishes:' + ','.join(str(r['id']) for r in rows),
                       'Nanny-Wünsche für ' + month_label(month),
                       f'{PEOPLE[actor]} hat {len(rows)} Nanny-Termine geplant: ' + '; '.join(label(r) for r in rows) + '.', False)
                return {'ids': [r['id'] for r in rows]}

        @app.post('/api/nanny/shifts/{shift_id}')
        def edit(shift_id: int, data: ShiftEdit, request: Request):
            if minutes(data.start, data.end) <= 0:
                raise HTTPException(422, 'Das Ende muss nach dem Beginn liegen.')
            with db() as conn:
                actor = identity(request, conn)
                row = self.shift(conn, shift_id, data.version)
                if row['state'] != 'wish':
                    raise HTTPException(409, 'Nur noch nicht angefragte Wünsche lassen sich ändern. Sonst bitte absagen und neu anfragen.')
                self.require_open_month(conn, row['day'])
                self.require_open_month(conn, data.day)
                self.require_no_clash(conn, data, shift_id)
                conn.execute('UPDATE nanny_shifts SET day=?,start=?,end=?,note=?,version=version+1,updated=? WHERE id=?',
                             (str(data.day), data.start, data.end, data.note.strip(), now(), shift_id))
                updated = self.shift(conn, shift_id)
                for month in {month_of(row['day']), month_of(updated['day'])}:
                    self.sync_request_task(conn, month)
                self.audit(conn, actor, 'Nanny-Wunsch geändert', f'{label(row)} → {label(updated)}')
            return {'ok': True}

        @app.post('/api/nanny/transition')
        def transition(data: Transition, request: Request):
            if len(data.ids) != len(data.versions) or len(set(data.ids)) != len(data.ids):
                raise HTTPException(422, 'Ungültige Auswahl.')
            with db() as conn:
                actor = identity(request, conn)
                rows = [self.shift(conn, shift_id, version) for shift_id, version in zip(data.ids, data.versions)]
                for row in rows:
                    self.apply(conn, actor, row, data.action, data.paid)
                for month in {month_of(r['day']) for r in rows}:
                    self.sync_request_task(conn, month)
                if data.action in ('confirm', 'decline', 'cancel'):
                    summary = ', '.join(label(r) for r in rows)
                    title = {'confirm': 'Nanny kommt', 'decline': 'Nanny kann nicht', 'cancel': 'Nanny-Termin abgesagt'}[data.action]
                    key = f'nanny-{data.action}:' + ','.join(f'{r["id"]}.{r["version"]}' for r in rows)
                    notify(conn, self.other(actor), key, title, summary, data.action != 'confirm')
            return {'ok': True}

        @app.post('/api/nanny/answer')
        def answer(data: AnswerInput, request: Request):
            """Record the nanny's reply to a monthly request in one atomic step."""
            if len({item.id for item in data.items}) != len(data.items):
                raise HTTPException(422, 'Jeder Termin darf nur einmal beantwortet werden.')
            with db() as conn:
                actor = identity(request, conn)
                rows = [(self.shift(conn, item.id, item.version), item.answer) for item in data.items]
                for row, reply in rows:
                    if row['state'] != 'requested':
                        raise HTTPException(409, f'{label(row)}: Dieser Termin ist nicht mehr angefragt. Bitte neu laden.')
                    self.apply(conn, actor, row, reply)
                confirmed = [label(r) for r, reply in rows if reply == 'confirm']
                declined = [label(r) for r, reply in rows if reply == 'decline']
                parts = []
                if confirmed:
                    parts.append('Zusage: ' + '; '.join(confirmed))
                if declined:
                    parts.append('Kann nicht: ' + '; '.join(declined))
                key = 'nanny-answer:' + ','.join(f'{r["id"]}.{r["version"]}' for r, _ in rows)
                notify(conn, self.other(actor), key, 'Antwort der Nanny', '. '.join(parts) + '.', bool(declined))
            return {'confirmed': len(confirmed), 'declined': len(declined)}

        @app.post('/api/nanny/shifts/{shift_id}/correct')
        def correct(shift_id: int, data: Correction, request: Request):
            with db() as conn:
                actor = identity(request, conn)
                row = self.shift(conn, shift_id, data.version)
                if row['state'] != 'confirmed':
                    raise HTTPException(409, 'Nur bestätigte Termine haben tatsächliche Zeiten.')
                if row['day'] > str(datetime.now(TZ).date()):
                    raise HTTPException(409, 'Tatsächliche Zeiten bitte erst am Termin oder danach eintragen.')
                self.require_open_month(conn, row['day'])
                if (data.actual_start is None) != (data.actual_end is None):
                    raise HTTPException(422, 'Bitte Beginn und Ende angeben oder beide leer lassen.')
                if data.actual_start and minutes(data.actual_start, data.actual_end) <= 0:
                    raise HTTPException(422, 'Das Ende muss nach dem Beginn liegen.')
                if data.actual_start and not data.note.strip():
                    raise HTTPException(422, 'Bitte kurz den Grund der Abweichung notieren.')
                conn.execute('UPDATE nanny_shifts SET actual_start=?,actual_end=?,correction_note=?,version=version+1,updated=? WHERE id=?',
                             (data.actual_start, data.actual_end, data.note.strip() if data.actual_start else '', now(), shift_id))
                self.audit(conn, actor, 'Nanny-Zeit korrigiert' if data.actual_start else 'Nanny-Korrektur entfernt',
                           label(row) + (f' → tatsächlich {data.actual_start}–{data.actual_end}' if data.actual_start else ' → wie geplant'))
            return {'ok': True}

        @app.post('/api/nanny/settings')
        def save_settings(data: Settings, request: Request):
            with db() as conn:
                actor = identity(request, conn)
                phone = data.phone.replace(' ', '')
                for key, value in (('nanny_name', data.name.strip()), ('nanny_phone', phone), ('nanny_rate_cents', str(data.rate_cents))):
                    conn.execute('INSERT OR REPLACE INTO metadata VALUES(?,?)', (key, value))
                self.audit(conn, actor, 'Nanny-Einstellungen gespeichert', f'Stundensatz {data.rate_cents / 100:.2f} EUR'.replace('.', ','))
            return {'ok': True}

        @app.post('/api/nanny/statement/{month}')
        def statement_action(month: str, data: StatementAction, request: Request):
            first, last = month_range(month)
            with db() as conn:
                actor = identity(request, conn)
                stored = self.closed(conn, month)
                if data.action == 'close':
                    if stored:
                        raise HTTPException(409, 'Dieser Monat ist bereits abgeschlossen.')
                    if datetime.now(TZ).date() <= last:
                        raise HTTPException(409, 'Ein Monat kann erst nach seinem letzten Tag abgeschlossen werden.')
                    preview = self.statement(conn, month)
                    if preview['unresolved']:
                        raise HTTPException(409, f"Noch {preview['unresolved']} Nanny-Termine ohne Bestätigung oder Absage. Bitte zuerst klären.")
                    conn.execute('INSERT INTO nanny_statements(month,rate_cents,minutes,amount_cents,lines,closed_by,closed) VALUES(?,?,?,?,?,?,?)',
                                 (month, preview['rate_cents'], preview['minutes'], preview['amount_cents'], json.dumps(preview['lines'], ensure_ascii=False), actor, now()))
                    conn.execute("UPDATE tasks SET state='superseded' WHERE owner=? AND title='Nanny-Abrechnung' AND state='open' AND details LIKE ?", (BILLING_OWNER, month + ':%'))
                    amount = f"{preview['amount_cents'] / 100:.2f}".replace('.', ',')
                    if preview['amount_cents']:
                        conn.execute('INSERT INTO tasks(owner,title,details,due,created) VALUES(?,?,?,?,?)',
                                     (BILLING_OWNER, 'Nanny-Lohn überweisen', f'{month}: {amount} EUR überweisen und danach in der Abrechnung als überwiesen markieren.', now(), now()))
                    self.audit(conn, actor, 'Nanny-Monat abgeschlossen', f"{month}: {preview['minutes']} Minuten · {amount} EUR")
                elif data.action == 'reopen':
                    if not stored:
                        raise HTTPException(409, 'Dieser Monat ist nicht abgeschlossen.')
                    if stored['paid']:
                        raise HTTPException(409, 'Bereits überwiesene Monate bleiben unverändert.')
                    conn.execute('DELETE FROM nanny_statements WHERE month=?', (month,))
                    conn.execute("UPDATE tasks SET state='superseded' WHERE owner=? AND title='Nanny-Lohn überweisen' AND state='open' AND details LIKE ?", (BILLING_OWNER, month + ':%'))
                    self.audit(conn, actor, 'Nanny-Monat wieder geöffnet', month)
                else:
                    if not stored:
                        raise HTTPException(409, 'Bitte den Monat zuerst abschließen.')
                    if stored['paid']:
                        raise HTTPException(409, 'Dieser Monat ist bereits als überwiesen markiert.')
                    conn.execute('UPDATE nanny_statements SET paid=?,paid_by=? WHERE month=?', (now(), actor, month))
                    conn.execute("UPDATE tasks SET state='done' WHERE owner=? AND title='Nanny-Lohn überweisen' AND state='open' AND details LIKE ?", (BILLING_OWNER, month + ':%'))
                    self.audit(conn, actor, 'Nanny-Lohn überwiesen', month)
            return {'ok': True}
