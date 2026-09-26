"""Weekly dinner suggestions (E-05, E-08, O-05).

Hard rules are decided on the NAS, never by an AI:
* vegetarian: ingredient/name keyword check plus Cookidoo category (E-04),
* cooking time per weekday / weekend (E-06),
* no repetition of recipes planned in the previous four weeks,
* protein per portion from Cookidoo nutrition data (E-05).

Optionally Claude picks a varied week from the prepared candidates. Data
minimisation (D-01, D-02): Claude only receives weekday names with a time
limit and, per candidate, an anonymous number, recipe name, minutes, protein
grams and ingredient names. No people, dates, Cookidoo IDs, account data,
history or free-text wishes are sent. The exact payload is stored so the
family can see what left the NAS.

Suggestions are never written to Cookidoo automatically.
"""
import asyncio
from datetime import date, datetime, timedelta
import json
import logging
import os
import random
import time

import httpx
from fastapi import HTTPException

from integrations import TZ

LOG = logging.getLogger('uvicorn.error.family_os.suggestions')
API_URL = 'https://api.anthropic.com/v1/messages'
DEFAULT_MODEL = 'claude-haiku-4-5-20251001'
DEFAULT_MONTHLY_CALLS = 40
DETAIL_TTL = 30 * 86400
MAX_NEW_DETAILS = 24
MAX_CANDIDATES = 30
HISTORY_DAYS = 28
WEEKDAYS = ['Montag', 'Dienstag', 'Mittwoch', 'Donnerstag', 'Freitag', 'Samstag', 'Sonntag']
QUERIES = ['vegetarisch Linsen', 'vegetarisch Kichererbsen', 'Tofu', 'vegetarisch Bohnen', 'Halloumi',
           'vegetarisch Quinoa', 'Feta Gemüse', 'vegetarisch Eier', 'Tempeh', 'vegetarisch Erbsen']

# Keyword check on ingredient names and recipe title. False positives only
# drop a candidate; the recipe dialog still asks to verify suitability.
MEAT_FISH = ['hähnchen', 'hühnchen', 'hühnerbrust', 'hühnerbrühe', 'hühnerfond', 'huhn', 'pute', 'rind', 'kalb', 'schwein',
             'speck', 'schinken', 'hackfleisch', 'gehacktes', 'wurst', 'würstchen', 'salami', 'chorizo', 'bacon', 'pancetta',
             'prosciutto', 'mortadella', 'kassler', 'leber', 'lamm', 'entenbrust', 'entenkeule', 'gänse', 'wildschwein',
             'hirsch', 'kaninchen', 'fleisch', 'lachs', 'thunfisch', 'fisch', 'garnele', 'shrimp', 'krabbe', 'scampi',
             'sardelle', 'sardine', 'anchovis', 'forelle', 'kabeljau', 'seelachs', 'dorsch', 'muschel', 'tintenfisch',
             'calamari', 'gelatine', 'austernsauce', 'worcester', 'sucuk', 'lardo', 'meeresfrüchte']
# Harmless word parts are removed before the check, so "Flammkuchen mit Speck"
# is still caught while "Fleischtomaten" or "Hühnereier" are not.
HARMLESS = ['fleischtomate', 'parmesanrinde', 'zimtrinde', 'brotrinde', 'flamm', 'hühnerei', 'fleischlos', 'ohne fleisch']

SYSTEM = """Du planst Abendessen für eine Woche aus einer festen Liste von Thermomix-Rezepten.
Regeln:
- Wähle ausschließlich IDs aus "kandidaten". Jedes Rezept höchstens einmal.
- Für jeden Tag in "tage" genau ein Rezept, dessen "minuten" höchstens "max_minuten" betragen.
- Nur vegetarische Gerichte: Enthält eine Zutat Fleisch oder Fisch, wähle den Kandidaten nicht.
- Bevorzuge eiweißreiche Gerichte ("eiweiss_g" pro Portion, falls angegeben).
- Sorge für Abwechslung bei Hauptzutat und Küchenstil über die Woche.
- Falls "bereits_geplant" angegeben ist: Diese Gerichte stehen schon fest; wähle etwas mit anderer Hauptzutat.
- Findest du für einen Tag keinen passenden Kandidaten, lass den Tag weg.
Begründe jede Wahl in höchstens zwölf Wörtern auf Deutsch."""

TOOL = {
    'name': 'wochenplan',
    'description': 'Gibt die Auswahl je Tag zurück.',
    'input_schema': {
        'type': 'object',
        'properties': {'auswahl': {'type': 'array', 'items': {
            'type': 'object',
            'properties': {'tag': {'type': 'string'}, 'id': {'type': 'string'}, 'grund': {'type': 'string'}},
            'required': ['tag', 'id', 'grund']}}},
        'required': ['auswahl'],
    },
}


def vegetarian(detail):
    """Return 'ok' (labelled vegetarian), 'likely' (no meat/fish found) or 'no'."""
    for text in [detail['name']] + detail['ingredients']:
        lowered = text.lower()
        for part in HARMLESS:
            lowered = lowered.replace(part, ' ')
        if any(word in lowered for word in MEAT_FISH):
            return 'no'
    labels = ' '.join(detail['categories']).lower()
    return 'ok' if 'vegetar' in labels or 'vegan' in labels else 'likely'


def protein_of(nutrition_groups):
    for group in nutrition_groups or []:
        for entry in getattr(group, 'recipe_nutritions', []) or []:
            for value in getattr(entry, 'nutritions', []) or []:
                kind = (getattr(value, 'type', '') or '').lower()
                if 'protein' in kind or 'eiweiß' in kind or 'eiweiss' in kind:
                    try:
                        return round(float(value.number))
                    except (TypeError, ValueError):
                        return None
    return None


def local_plan(slots, candidates, taken=()):
    """Greedy fallback: protein first, then variety of the search topic."""
    ranked = sorted(candidates, key=lambda c: (-(c['protein'] or 0), c['veg'] != 'ok', random.random()))
    used, topics, result = set(taken), [], {}
    for slot in slots:
        options = [c for c in ranked if c['id'] not in used and c['minutes'] and c['minutes'] <= slot['max_minutes']]
        fresh = [c for c in options if c['topic'] not in topics[-2:]] or options
        if fresh:
            choice = fresh[0]
            used.add(choice['id'])
            topics.append(choice['topic'])
            protein = f", {choice['protein']} g Eiweiß" if choice['protein'] else ''
            result[slot['day']] = {'id': choice['id'], 'reason': f"{choice['minutes']} Min.{protein}", 'source': 'lokal'}
    return result


class MealSuggestions:
    def __init__(self, meals, api_key=None, model=None, monthly_calls=None, transport=None):
        self.meals, self.db = meals, meals.db
        self.api_key = api_key if api_key is not None else os.getenv('FOS_ANTHROPIC_API_KEY', '').strip()
        self.model = model or os.getenv('FOS_CLAUDE_MODEL', '').strip() or DEFAULT_MODEL
        self.monthly_calls = monthly_calls or int(os.getenv('FOS_CLAUDE_MONTHLY_CALLS', DEFAULT_MONTHLY_CALLS))
        self.transport = transport

    # --- bookkeeping -----------------------------------------------------

    def usage(self, conn=None):
        key = 'claude_usage:' + datetime.now(TZ).strftime('%Y-%m')
        def read(c):
            row = c.execute('SELECT value FROM metadata WHERE key=?', (key,)).fetchone()
            return json.loads(row[0]) if row else {'calls': 0, 'input_tokens': 0, 'output_tokens': 0}
        if conn is not None:
            return read(conn)
        with self.db() as c:
            return read(c)

    def record_usage(self, usage):
        key = 'claude_usage:' + datetime.now(TZ).strftime('%Y-%m')
        with self.db() as conn:
            current = self.usage(conn)
            current['calls'] += 1
            current['input_tokens'] += int(usage.get('input_tokens', 0))
            current['output_tokens'] += int(usage.get('output_tokens', 0))
            conn.execute('INSERT OR REPLACE INTO metadata VALUES(?,?)', (key, json.dumps(current)))

    def info(self):
        usage = self.usage()
        return {'ai_available': bool(self.api_key) and not self.meals.demo, 'model': self.model,
                'monthly_calls': self.monthly_calls, 'usage': usage}

    def stored(self, start):
        with self.db() as conn:
            row = conn.execute('SELECT value FROM meal_cache WHERE key=?', ('suggestion:' + str(start),)).fetchone()
        return json.loads(row[0]) if row else None

    # --- candidates ------------------------------------------------------

    def history(self, start):
        """Recipe IDs planned in the four weeks before this week (local only)."""
        ids = set()
        with self.db() as conn:
            rows = conn.execute("SELECT key,value FROM meal_cache WHERE key LIKE 'week:%'").fetchall()
        for key, value in rows:
            try:
                week = date.fromisoformat(key[5:])
            except ValueError:
                continue
            if start - timedelta(days=HISTORY_DAYS) <= week < start:
                ids.update(r['id'] for d in json.loads(value)['days'] for r in d['recipes'])
        return ids

    def cached_detail(self, rid):
        with self.db() as conn:
            row = conn.execute('SELECT value,updated FROM meal_cache WHERE key=?', ('recipe:' + rid,)).fetchone()
        if row and time.time() - row['updated'] < DETAIL_TTL:
            return json.loads(row['value'])
        return None

    async def detail(self, api, rid, semaphore):
        cached = self.cached_detail(rid)
        if cached:
            return cached
        async with semaphore:
            r = await api.get_recipe_details(rid)
        detail = {'id': r.id, 'name': r.name, 'minutes': round((r.total_time or 0) / 60) or None,
                  'ingredients': sorted({i.name for i in r.ingredients if i.name})[:25],
                  'categories': [c.name for c in r.categories], 'protein': protein_of(r.nutrition_groups)}
        with self.db() as conn:
            conn.execute('INSERT OR REPLACE INTO meal_cache VALUES(?,?,?)', ('recipe:' + rid, json.dumps(detail, ensure_ascii=False), time.time()))
        self.meals.images.remember({r.id: getattr(r, 'thumbnail', None)})
        return detail

    async def candidates(self, api, start, max_minutes, wishes, planned):
        excluded = self.history(start) | planned
        queries = [w for w in wishes if w][:3] + random.sample(QUERIES, 5)
        hits, topics = [], {}
        self.meals.progress('suggest_search')
        for query in queries:
            found = await api.search_recipes(query=query, languages='de', total_time=max_minutes * 60, page_size=12)
            self.meals.images.remember({r.id: getattr(r, 'thumbnail', None) for r in found.recipes})
            for r in found.recipes:
                if r.id.startswith('r') and r.id not in excluded and r.id not in topics:
                    topics[r.id] = query
                    hits.append(r.id)
        random.shuffle(hits)
        # Prefer recipes whose details are cached; fetch a bounded number of new ones.
        cached = [rid for rid in hits if self.cached_detail(rid)]
        fresh = [rid for rid in hits if rid not in cached][:MAX_NEW_DETAILS]
        self.meals.progress('suggest_details')
        semaphore = asyncio.Semaphore(4)
        details = await asyncio.gather(*(self.detail(api, rid, semaphore) for rid in (cached + fresh)[:MAX_CANDIDATES + MAX_NEW_DETAILS]),
                                       return_exceptions=True)
        result = []
        for item in details:
            if isinstance(item, Exception) or not item.get('minutes'):
                continue
            veg = vegetarian(item)
            if veg == 'no' or item['minutes'] > max_minutes:
                continue
            result.append({**item, 'veg': veg, 'topic': topics.get(item['id'], '')})
        return result[:MAX_CANDIDATES]

    # --- Claude ----------------------------------------------------------

    async def ask_claude(self, slots, candidates, fixed=()):
        aliases = {f'k{i + 1}': c for i, c in enumerate(candidates)}
        payload = {
            'tage': [{'tag': slot['label'], 'max_minuten': slot['max_minutes']} for slot in slots],
            # Only recipe names of the other days (single-day re-suggestion), nothing else.
            **({'bereits_geplant': list(fixed)} if fixed else {}),
            'kandidaten': [{'id': alias, 'name': c['name'], 'minuten': c['minutes'],
                            **({'eiweiss_g': c['protein']} if c['protein'] else {}), 'zutaten': c['ingredients'][:15]}
                           for alias, c in aliases.items()],
        }
        body = {'model': self.model, 'max_tokens': 1024, 'system': SYSTEM, 'tools': [TOOL],
                'tool_choice': {'type': 'tool', 'name': 'wochenplan'},
                'messages': [{'role': 'user', 'content': json.dumps(payload, ensure_ascii=False)}]}
        headers = {'x-api-key': self.api_key, 'anthropic-version': '2023-06-01', 'content-type': 'application/json'}
        async with httpx.AsyncClient(timeout=40, transport=self.transport) as client:
            response = await client.post(API_URL, json=body, headers=headers)
        if response.status_code != 200:
            raise RuntimeError(f'Claude HTTP {response.status_code}')
        data = response.json()
        self.record_usage(data.get('usage', {}))
        block = next((b for b in data.get('content', []) if b.get('type') == 'tool_use'), None)
        if not block:
            raise RuntimeError('Claude-Antwort ohne Auswahl')
        by_label = {slot['label']: slot for slot in slots}
        result, used = {}, set()
        for choice in block.get('input', {}).get('auswahl', []):
            slot = by_label.get(choice.get('tag'))
            candidate = aliases.get(choice.get('id'))
            # Local validation: the AI can only choose, never override hard rules.
            if not slot or not candidate or slot['day'] in result or candidate['id'] in used:
                continue
            if candidate['minutes'] > slot['max_minutes'] or vegetarian(candidate) == 'no':
                continue
            used.add(candidate['id'])
            result[slot['day']] = {'id': candidate['id'], 'reason': str(choice.get('grund', ''))[:120], 'source': 'claude'}
        return result, payload

    # --- orchestration ---------------------------------------------------

    async def suggest(self, start, weekday_minutes, weekend_minutes, wishes, use_ai):
        snapshot = self.meals.status(start)['snapshot']
        if not snapshot:
            raise HTTPException(409, 'Bitte die Woche zuerst mit Cookidoo abgleichen.')
        planned_days = {d['day'] for d in snapshot['days'] if d['recipes'] or d['custom_ids']}
        planned_ids = {r['id'] for d in snapshot['days'] for r in d['recipes']}
        slots = []
        for offset in range(7):
            day = start + timedelta(days=offset)
            if str(day) in planned_days:
                continue
            weekend = day.weekday() >= 5
            slots.append({'day': str(day), 'label': WEEKDAYS[day.weekday()], 'max_minutes': weekend_minutes if weekend else weekday_minutes})
        if not slots:
            raise HTTPException(409, 'Für diese Woche ist bereits jeder Abend geplant.')
        async with self.meals.adapter() as api:
            candidates = await self.candidates(api, start, max(weekday_minutes, weekend_minutes), wishes, planned_ids)
        if not candidates:
            raise HTTPException(502, 'Cookidoo lieferte keine passenden vegetarischen Kandidaten. Bitte andere Wünsche oder längere Kochzeiten versuchen.')
        by_id = {c['id']: c for c in candidates}
        choices, sent, notice, source = {}, None, '', 'lokal'
        if use_ai:
            if not self.api_key:
                notice = 'Kein Claude-Schlüssel hinterlegt; lokaler Vorschlag.'
            elif self.usage()['calls'] >= self.monthly_calls:
                notice = f'Monatliches Limit von {self.monthly_calls} Claude-Vorschlägen erreicht; lokaler Vorschlag.'
            else:
                self.meals.progress('suggest_claude')
                try:
                    choices, sent = await self.ask_claude(slots, candidates)
                    source = 'claude'
                except Exception as error:
                    LOG.warning('Claude-Vorschlag fehlgeschlagen reason=%s', type(error).__name__)
                    notice = 'Claude war nicht erreichbar oder antwortete ungültig; lokaler Vorschlag.'
        missing = [slot for slot in slots if slot['day'] not in choices]
        if missing:
            choices.update(local_plan(missing, candidates, taken={c['id'] for c in choices.values()}))
            if source == 'claude':
                notice = notice or 'Einzelne Tage hat der NAS ergänzt, weil Claude keinen passenden Kandidaten gewählt hat.'
        images = self.meals.images.available(list(by_id))
        days = []
        for slot in slots:
            choice = choices.get(slot['day'])
            if not choice:
                days.append({'day': slot['day'], 'max_minutes': slot['max_minutes'], 'recipe': None})
                continue
            c = by_id[choice['id']]
            days.append({'day': slot['day'], 'max_minutes': slot['max_minutes'], 'reason': choice['reason'], 'source': choice['source'],
                         'recipe': {'id': c['id'], 'name': c['name'], 'total_time': c['minutes'] * 60, 'protein': c['protein'],
                                    'veg': c['veg'], 'image': images.get(c['id'])}})
        result = {'start': str(start), 'created': time.time(), 'source': source, 'notice': notice, 'sent': sent,
                  'model': self.model if source == 'claude' else None, 'days': days,
                  # Local only: candidate pool and wishes for re-suggesting single days.
                  'pool': [c['id'] for c in candidates], 'topics': {c['id']: c['topic'] for c in candidates},
                  'wishes': wishes, 'rejected': []}
        with self.db() as conn:
            conn.execute('INSERT OR REPLACE INTO meal_cache VALUES(?,?,?)', ('suggestion:' + str(start), json.dumps(result, ensure_ascii=False), time.time()))
        return result

    # --- single day ------------------------------------------------------

    def save(self, start, suggestion):
        with self.db() as conn:
            conn.execute('INSERT OR REPLACE INTO meal_cache VALUES(?,?,?)',
                         ('suggestion:' + str(start), json.dumps(suggestion, ensure_ascii=False), time.time()))

    def pool(self, suggestion, slot, excluded):
        """Remaining candidates from the week's pool (details cached on the NAS)."""
        result = []
        for rid in suggestion.get('pool', []):
            detail = self.cached_detail(rid)
            if not detail or rid in excluded or not detail.get('minutes') or detail['minutes'] > slot['max_minutes']:
                continue
            veg = vegetarian(detail)
            if veg != 'no':
                result.append({**detail, 'veg': veg, 'topic': suggestion.get('topics', {}).get(rid, '')})
        return result

    async def suggest_day(self, start, day, use_ai):
        """Replace the suggestion for one day (E-19). Other days stay unchanged."""
        suggestion = self.stored(start)
        entry = next((d for d in (suggestion or {}).get('days', []) if d['day'] == day), None)
        if not entry:
            raise HTTPException(409, 'Für diesen Tag gibt es keinen Vorschlag. Bitte zuerst die Woche vorschlagen lassen.')
        snapshot = self.meals.status(start)['snapshot']
        if snapshot and any(d['day'] == day and (d['recipes'] or d['custom_ids']) for d in snapshot['days']):
            raise HTTPException(409, 'Dieser Tag ist bereits in Cookidoo geplant.')
        weekday = date.fromisoformat(day).weekday()
        slot = {'day': day, 'label': WEEKDAYS[weekday], 'max_minutes': entry['max_minutes']}
        others = [d for d in suggestion['days'] if d['day'] != day and d.get('recipe')]
        rejected = set(suggestion.get('rejected', []))
        if entry.get('recipe'):
            rejected.add(entry['recipe']['id'])
        planned = {r['id'] for d in (snapshot or {}).get('days', []) for r in d['recipes']}
        excluded = rejected | planned | {d['recipe']['id'] for d in others} | self.history(start)
        candidates = self.pool(suggestion, slot, excluded)
        if not candidates:
            # Pool used up: search Cookidoo again (same wishes, this day's time limit).
            async with self.meals.adapter() as api:
                candidates = await self.candidates(api, start, slot['max_minutes'], suggestion.get('wishes', []), excluded)
            candidates = [c for c in candidates if c['id'] not in excluded]
            suggestion['pool'] = list(dict.fromkeys(suggestion.get('pool', []) + [c['id'] for c in candidates]))
            suggestion.setdefault('topics', {}).update({c['id']: c['topic'] for c in candidates})
        if not candidates:
            raise HTTPException(502, 'Kein weiteres passendes Gericht gefunden. Bitte andere Wünsche oder mehr Kochzeit versuchen.')
        choice, sent, notice = None, None, ''
        if use_ai:
            if not self.api_key:
                notice = 'Kein Claude-Schlüssel hinterlegt; lokal ausgewählt.'
            elif self.usage()['calls'] >= self.monthly_calls:
                notice = f'Monatliches Limit von {self.monthly_calls} Claude-Vorschlägen erreicht; lokal ausgewählt.'
            else:
                self.meals.progress('suggest_claude')
                try:
                    picked, sent = await self.ask_claude([slot], candidates[:MAX_CANDIDATES], [d['recipe']['name'] for d in others])
                    choice = picked.get(day)
                    if not choice:
                        notice = 'Claude hat kein passendes Gericht gewählt; lokal ausgewählt.'
                except Exception as error:
                    LOG.warning('Claude-Tagesvorschlag fehlgeschlagen reason=%s', type(error).__name__)
                    notice = 'Claude war nicht erreichbar oder antwortete ungültig; lokal ausgewählt.'
        if not choice:
            choice = local_plan([slot], candidates, taken=excluded).get(day)
        if not choice:
            raise HTTPException(502, 'Kein weiteres passendes Gericht gefunden.')
        c = next(x for x in candidates if x['id'] == choice['id'])
        image = self.meals.images.available([c['id']]).get(c['id'])
        entry.update({'reason': choice['reason'], 'source': choice['source'],
                      'recipe': {'id': c['id'], 'name': c['name'], 'total_time': c['minutes'] * 60, 'protein': c['protein'],
                                 'veg': c['veg'], 'image': image}})
        suggestion['rejected'] = sorted(rejected)
        suggestion['notice'] = notice
        if sent:
            suggestion.setdefault('sent_days', []).append(sent)
        self.save(start, suggestion)
        return suggestion

    def demo_day(self, start, day):
        """Demo: swap one day for another sample dish; no Cookidoo or Claude."""
        suggestion = self.stored(start)
        entry = next((d for d in (suggestion or {}).get('days', []) if d['day'] == day), None)
        if not entry:
            raise HTTPException(409, 'Für diesen Tag gibt es keinen Vorschlag.')
        samples = [('Linsen-Bolognese mit Vollkornspaghetti', 35, 23), ('Tofu-Curry mit Brokkoli', 30, 25),
                   ('Kichererbsen-Spinat-Pfanne', 25, 18), ('Bohnen-Chili sin Carne', 40, 20)]
        used = {d['recipe']['name'] for d in suggestion['days'] if d.get('recipe')} | set(suggestion.get('rejected', []))
        options = [s for s in samples if s[0] not in used and s[1] <= entry['max_minutes']]
        if not options:
            raise HTTPException(409, 'Demo: keine weiteren Beispielgerichte.')
        name, minutes, protein = options[0]
        if entry.get('recipe'):
            suggestion.setdefault('rejected', []).append(entry['recipe']['name'])
        entry.update({'reason': f'{minutes} Min., {protein} g Eiweiß', 'source': 'lokal',
                      'recipe': {'id': 'demo-x' + str(len(used)), 'name': name, 'total_time': minutes * 60,
                                 'protein': protein, 'veg': 'likely', 'image': None}})
        self.save(start, suggestion)
        return suggestion

    def demo(self, start, weekday_minutes, weekend_minutes, planned=()):
        """Local-only preview for the demo; no Cookidoo or Claude calls."""
        samples = [('Rote-Linsen-Dal mit Spinat', 30, 21), ('Kichererbsen-Tikka-Masala', 40, 19), ('Tofu-Gemüse-Pfanne mit Erdnuss', 25, 27),
                   ('Weiße-Bohnen-Eintopf', 45, 18), ('Halloumi-Quinoa-Bowl', 35, 26), ('Spinat-Feta-Quiche', 75, 22), ('Gemüse-Lasagne mit Linsen', 85, 24)]
        days = []
        for offset, (name, minutes, protein) in enumerate(samples):
            day = start + timedelta(days=offset)
            if str(day) in planned:
                continue
            limit = weekend_minutes if day.weekday() >= 5 else weekday_minutes
            days.append({'day': str(day), 'max_minutes': limit, 'reason': f'{minutes} Min., {protein} g Eiweiß', 'source': 'lokal',
                         'recipe': {'id': f'demo-s{offset}', 'name': name, 'total_time': minutes * 60, 'protein': protein, 'veg': 'likely', 'image': None}
                         if minutes <= limit else None})
        return {'start': str(start), 'created': time.time(), 'source': 'lokal', 'notice': 'Demo: Beispielvorschlag ohne Cookidoo und ohne Claude.',
                'sent': None, 'model': None, 'days': days}
