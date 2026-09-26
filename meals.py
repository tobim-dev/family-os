"""Cookidoo integration: local snapshots and individually verified writes.

No blanket clearing of shopping lists; credentials are used only for initial
login. Rotated tokens are encrypted with the existing NAS integration key.
"""
import asyncio
from contextlib import asynccontextmanager
from collections import Counter
from dataclasses import asdict, replace
from datetime import date, datetime, timedelta
import hashlib
from html import escape
import json
import logging
import re
import threading
import time
import socket
import ssl
from uuid import uuid4
from typing import Literal

import aiohttp
from cookidoo_api import Cookidoo
from cookidoo_api.exceptions import CookidooAuthException, CookidooParseException, CookidooRequestException
from cookidoo_api.types import CookidooAuthData, CookidooConfig, CookidooLocalizationConfig
from fastapi import HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field, SecretStr
from integrations import dump, TZ
from recipe_images import RecipeImages
from meal_suggestions import MealSuggestions
import shopping_week

for name in ('cookidoo_api.cookidoo', 'cookidoo_api.well_known', 'cookidoo_api.helpers'):
    logging.getLogger(name).disabled = True

LOG = logging.getLogger('uvicorn.error.family_os.cookidoo')
REQUEST_TIMEOUT = 45


def saturday(value):
    return value - timedelta(days=(value.weekday() - 5) % 7)


def week_start(value):
    try:
        parsed = date.fromisoformat(value)
        if parsed.weekday() != 5:
            raise ValueError()
        return parsed
    except ValueError:
        raise HTTPException(422, 'Bitte eine Woche von Samstag bis Freitag wählen.')


def revision(snapshot):
    return hashlib.sha256(dump(snapshot).encode()).hexdigest()


def recipe(row):
    return {'id': row.id, 'name': row.name, 'total_time': getattr(row, 'total_time', None)}


async def snapshot(client, start, progress=lambda stage: None, images=None):
    # Preview image URLs are collected separately so they never change the
    # revision that protects writes against parallel changes.
    def keep(row):
        if images is not None and getattr(row, 'thumbnail', None):
            images[row.id] = row.thumbnail
        return recipe(row)

    days = {}
    progress('calendar')
    for anchor in (start, start + timedelta(days=6)):
        for day in await client.get_recipes_in_calendar_week(anchor):
            parsed = date.fromisoformat(day.id)
            if start <= parsed <= start + timedelta(days=6):
                days[day.id] = {'day': day.id, 'recipes': [keep(r) for r in day.recipes], 'custom_ids': day.customer_recipe_ids}
    for offset in range(7):
        day = str(start + timedelta(days=offset))
        days.setdefault(day, {'day': day, 'recipes': [], 'custom_ids': []})
    progress('shopping_recipes')
    shopping_recipes = [{**keep(r), 'ingredient_ids': sorted(i.id for i in r.ingredients)} for r in await client.get_shopping_list_recipes()]
    progress('ingredients')
    ingredients = [asdict(i) for i in await client.get_ingredient_items()]
    progress('additional_items')
    additional = [asdict(i) for i in await client.get_additional_items()]
    # Provider IDs are not necessarily unique in flattened recipe ingredients.
    # Preserve every occurrence and quantity; never silently merge by ID.
    duplicates = {}
    for group, items in (('shopping_recipes', shopping_recipes), ('ingredients', ingredients), ('additional', additional)):
        duplicates[group] = sorted(key for key, count in Counter(i['id'] for i in items).items() if count > 1)
        items.sort(key=lambda i: (i['id'], dump(i)))
    for day in days.values():
        day['recipes'].sort(key=lambda r: r['id'])
        day['custom_ids'].sort()
    return {'start': str(start), 'days': sorted(days.values(), key=lambda d: d['day']), 'shopping_recipes': shopping_recipes, 'ingredients': ingredients, 'additional': additional, 'duplicate_ids': duplicates}


class Connection(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: SecretStr


class SyncInput(BaseModel):
    start: str


class SearchInput(BaseModel):
    query: str = Field(min_length=2, max_length=120)
    max_minutes: int = Field(default=45, ge=5, le=180)


class ShoppedInput(BaseModel):
    start: str
    shopped: bool


class SuggestDayInput(BaseModel):
    start: str
    day: date
    use_ai: bool = False


class SuggestInput(BaseModel):
    start: str
    weekday_minutes: int = Field(default=45, ge=15, le=120)
    weekend_minutes: int = Field(default=90, ge=15, le=240)
    wishes: str = Field(default='', max_length=120)
    use_ai: bool = False


class Change(BaseModel):
    id: str = Field(pattern=r'^[a-f0-9-]{36}$')
    start: str
    revision: str = Field(pattern=r'^[a-f0-9]{64}$')
    action: Literal['plan_add', 'plan_remove', 'ingredients_add', 'ingredients_remove', 'check_ingredient', 'check_additional', 'additional_add']
    recipe_id: str | None = Field(default=None, pattern=r'^r[0-9]+$')
    day: date | None = None
    item_id: str | None = Field(default=None, min_length=1, max_length=512)
    owned: bool | None = None
    name: str | None = Field(default=None, min_length=1, max_length=200)


class Meals:
    def __init__(self, integrations):
        self.integrations = integrations
        self.db, self.demo = integrations.db, integrations.demo
        self.lock = threading.Lock()
        self.phase = 'prepare'
        self.diagnostic_id = None
        self.started = 0
        with self.db() as conn:
            conn.execute("UPDATE meal_operations SET state='review',message='Der Server wurde während der Übertragung neu gestartet. Bitte in Cookidoo prüfen.' WHERE state='sending'")
        self.adapter = self.client
        self.images = RecipeImages(self.db, integrations.directory, self.demo)
        self.suggestions = MealSuggestions(self)

    @asynccontextmanager
    async def client(self, credentials=None):
        account = hashlib.sha256(credentials.email.strip().casefold().encode()).hexdigest() if credentials else None
        if account:
            with self.db() as conn:
                previous = conn.execute("SELECT value FROM metadata WHERE key='cookidoo_account'").fetchone()
            if previous and previous[0] != account:
                raise HTTPException(409, 'Bitte denselben Cookidoo-Zugang verwenden. Ein Kontowechsel benötigt eine getrennte Migration der gespeicherten Planung.')
        async with aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar(unsafe=True), timeout=aiohttp.ClientTimeout(total=35)) as session:
            cfg = CookidooConfig(email=credentials.email.strip() if credentials else '', password=credentials.password.get_secret_value() if credentials else '',
                localization=CookidooLocalizationConfig(country_code='de', language='de-DE', url='https://cookidoo.de/foundation/de-DE'))
            api = Cookidoo(session, cfg=cfg, on_auth_data_update=lambda auth: self.integrations.save_secret('cookidoo', asdict(auth)))
            if credentials:
                self.progress('login')
                await api.login()
                self.progress('save_tokens')
                with self.db() as conn:
                    conn.execute("INSERT OR REPLACE INTO metadata VALUES('cookidoo_account',?)", (account,))
            else:
                self.progress('restore_tokens')
                token = self.integrations.secret('cookidoo')
                if not token:
                    raise HTTPException(409, 'Bitte zuerst Cookidoo verbinden.')
                api.apply_auth_data(CookidooAuthData(**token))
            try:
                yield api
            finally:
                if api.auth_data:
                    self.integrations.save_secret('cookidoo', asdict(api.auth_data))

    def progress(self, phase):
        self.phase = phase

    def diagnose(self, error):
        # Never log exception text, repr, URLs, tracebacks or provider response bodies.
        chain, current = [], error
        while current is not None and len(chain) < 8 and all(current is not e for e in chain):
            chain.append(current)
            current = current.__cause__ or current.__context__
        status = next((e.status for e in chain if isinstance(e, aiohttp.ClientResponseError) and 100 <= e.status <= 599), None)
        for e in chain:
            if isinstance(e, CookidooAuthException):
                match = re.fullmatch(r'(?:Login flow failed: could not reach login page \(status |Token exchange failed \(status )(\d{3})\)\.', str(e))
                if match and 100 <= int(match[1]) <= 599:
                    status = int(match[1])
        if any(isinstance(e, TimeoutError) for e in chain):
            category, hint = 'timeout', 'Cookidoo hat nicht rechtzeitig geantwortet.'
        elif any(isinstance(e, socket.gaierror) for e in chain):
            category, hint = 'dns', 'Das NAS konnte den Cookidoo-Servernamen nicht auflösen. Bitte DNS und Internetverbindung des Containers prüfen.'
        elif any(isinstance(e, (ssl.SSLError, aiohttp.ClientSSLError)) for e in chain):
            category, hint = 'tls', 'Die verschlüsselte Verbindung zu Cookidoo konnte nicht hergestellt werden. Bitte NAS-Uhrzeit und Zertifikatsprüfung prüfen.'
        elif any(isinstance(e, CookidooAuthException) for e in chain):
            category, hint = 'authentication', 'Cookidoo hat die Anmeldung oder Zugangserneuerung nicht bestätigt. Zugang bitte direkt bei Cookidoo prüfen; auch eine zusätzliche Anmeldeprüfung kann die Ursache sein.'
        elif any(isinstance(e, CookidooParseException) for e in chain):
            category, hint = 'response_format', 'Die Cookidoo-Antwort konnte nicht verarbeitet werden. Die Schnittstelle oder Anmeldeseite könnte sich geändert haben.'
        elif any(isinstance(e, (aiohttp.ClientError, CookidooRequestException)) for e in chain):
            category, hint = 'connection', 'Die Verbindung vom NAS zu Cookidoo ist fehlgeschlagen.'
        else:
            category, hint = 'internal', 'Beim Verarbeiten der Cookidoo-Verbindung ist ein interner Fehler aufgetreten.'
        labels = {'login':'Anmeldung', 'save_tokens':'Zugang speichern', 'restore_tokens':'Zugang laden', 'calendar':'Wochenplanung laden', 'shopping_recipes':'Einkaufsrezepte laden', 'ingredients':'Zutaten laden', 'additional_items':'Eigene Artikel laden', 'write':'Änderung übertragen', 'search':'Rezeptsuche', 'details':'Rezept laden', 'prepare':'Vorbereitung'}
        detail = f"{labels.get(self.phase, 'Cookidoo-Abgleich')}: {hint} Diagnose {self.diagnostic_id}."
        if status:
            detail += f' Cookidoo-HTTP-Status: {status}.'
        frame, line = error.__traceback__, None
        while frame is not None:
            if frame.tb_frame.f_code.co_filename == __file__:
                line = frame.tb_lineno
            frame = frame.tb_next
        error_type = type(error).__name__ if type(error) in (ValueError, TypeError, KeyError, AttributeError) else category
        diagnostic = {'source_line':line, 'error_type':error_type, 'id':self.diagnostic_id, 'phase':self.phase, 'category':category, 'upstream_status':status, 'time':datetime.now(TZ).isoformat(), 'detail':detail}
        LOG.error('Cookidoo failed diagnostic=%s phase=%s category=%s error_type=%s source_line=%s upstream_status=%s elapsed_ms=%d', self.diagnostic_id, self.phase, category, error_type, line or '-', status or '-', int((time.monotonic()-self.started)*1000))
        with self.db() as conn:
            conn.execute("INSERT OR REPLACE INTO metadata VALUES('cookidoo_diagnostic',?)", (dump(diagnostic),))
        return detail

    def run(self, coroutine, timeout=None):
        if not self.lock.acquire(blocking=False):
            coroutine.close()
            raise HTTPException(409, 'Cookidoo wird gerade abgeglichen. Bitte kurz warten.')
        self.diagnostic_id, self.started, self.phase = uuid4().hex[:12], time.monotonic(), 'prepare'
        LOG.info('Cookidoo started diagnostic=%s', self.diagnostic_id)
        try:
            result = asyncio.run(asyncio.wait_for(coroutine, timeout=timeout or REQUEST_TIMEOUT))
            with self.db() as conn:
                conn.execute("DELETE FROM metadata WHERE key IN ('cookidoo_diagnostic','cookidoo_sync_error')")
            LOG.info('Cookidoo completed diagnostic=%s elapsed_ms=%d', self.diagnostic_id, int((time.monotonic()-self.started)*1000))
            return result
        except HTTPException:
            LOG.info('Cookidoo stopped diagnostic=%s phase=%s', self.diagnostic_id, self.phase)
            raise
        except Exception as error:
            detail = self.diagnose(error)
            with self.db() as conn:
                conn.execute("UPDATE meal_operations SET state='review',message='Antwort von Cookidoo unklar. Bitte vor einem erneuten Schreibzugriff prüfen.' WHERE state='sending'")
            raise HTTPException(502, detail) from None
        finally:
            self.lock.release()

    def store(self, value, images=None):
        if images:
            self.images.remember(images)
        with self.db() as conn:
            conn.execute('INSERT OR REPLACE INTO meal_cache VALUES(?,?,?)', ('week:' + value['start'], dump(value), time.time()))
            conn.execute('INSERT OR REPLACE INTO meal_cache VALUES(?,?,?)', ('shopping', dump(value), time.time()))

    def status(self, start):
        with self.db() as conn:
            row = conn.execute('SELECT * FROM meal_cache WHERE key=?', ('week:' + str(start),)).fetchone()
            latest = conn.execute("SELECT * FROM meal_cache WHERE key='shopping'").fetchone()
            error = conn.execute("SELECT value FROM metadata WHERE key='cookidoo_sync_error'").fetchone()
            diagnostic = conn.execute("SELECT value FROM metadata WHERE key='cookidoo_diagnostic'").fetchone()
            connected = bool(conn.execute("SELECT 1 FROM integration_secrets WHERE key='cookidoo'").fetchone())
            reviews = [dict(r) for r in conn.execute("SELECT id,state,message,created FROM meal_operations WHERE state IN ('sending','review') ORDER BY created")]
        data = json.loads(row['value']) if row else None
        diagnostic = json.loads(diagnostic[0]) if diagnostic else None
        recipe_ids = [r['id'] for d in data['days'] for r in d['recipes']] + [r['id'] for r in data['shopping_recipes']] if data else []
        # A snapshot has one coherent revision; don't splice a newer shopping list into it.
        return {'diagnostic': diagnostic, 'error': diagnostic['detail'] if diagnostic else error[0] if error else None, 'connected': connected and not self.demo, 'demo': self.demo, 'snapshot': data, 'revision': revision(data) if data else None,
                'updated': row['updated'] if row else None, 'reviews': reviews, 'images': self.images.available(recipe_ids),
                'suggestion': self.suggestions.stored(start), 'ai': self.suggestions.info(),
                'shopped': self.shopped(start),
                'week_switch': shopping_week.plan(data) if data else None,
                'shopping_updated': latest['updated'] if latest else None}

    def shopped(self, start):
        """Marked as already shopped for this week (E-18): who and when, or None."""
        with self.db() as conn:
            row = conn.execute('SELECT value FROM metadata WHERE key=?', ('meal_shopped:' + str(start),)).fetchone()
        return json.loads(row[0]) if row else None

    async def sync(self, start):
        async with self.adapter() as api:
            images = {}
            value = await snapshot(api, start, self.progress, images)
            self.store(value, images)
            return self.status(start)

    async def connect(self, credentials, start):
        # Login and reading the list are separate HTTP requests. A slow first
        # sync must not make a successful login appear to have failed.
        async with self.adapter(credentials):
            pass
        return self.status(start)

    async def search(self, data):
        async with self.adapter() as api:
            self.progress('search')
            found = await api.search_recipes(query=data.query.strip(), languages='de', total_time=data.max_minutes * 60, page_size=12)
            self.images.remember({r.id: getattr(r, 'thumbnail', None) for r in found.recipes})
            images = self.images.available([r.id for r in found.recipes])
            return {'recipes': [{**recipe(r), 'image': images.get(r.id)} for r in found.recipes], 'total': found.total}

    async def details(self, rid):
        async with self.adapter() as api:
            self.progress('details')
            r = await api.get_recipe_details(rid)
            self.images.remember({r.id: getattr(r, 'thumbnail', None)})
            return {**recipe(r), 'image': self.images.available([r.id]).get(r.id), 'serving_size': r.serving_size, 'ingredients': [asdict(i) for i in r.ingredients],
                    'categories': [c.name for c in r.categories], 'nutrition': [asdict(g) for g in r.nutrition_groups]}

    def validate_change(self, data, before):
        if data.action.startswith('plan_'):
            if not data.recipe_id or not data.day or not date.fromisoformat(before['start']) <= data.day <= date.fromisoformat(before['start']) + timedelta(days=6):
                raise HTTPException(422, 'Rezept und Tag müssen zur angezeigten Woche passen.')
            day = next(d for d in before['days'] if d['day'] == str(data.day))
            ids = [r['id'] for r in day['recipes']]
            if data.action == 'plan_add' and (ids or day['custom_ids']):
                raise HTTPException(409, 'Für diesen Tag ist bereits etwas geplant. Bitte zuerst den bestehenden Eintrag prüfen.')
            if data.action == 'plan_remove' and data.recipe_id not in ids:
                raise HTTPException(409, 'Diese Zuordnung besteht nicht mehr.')
        elif data.action.startswith('ingredients_'):
            # Duplicate ingredient IDs are allowed here (O-06): the readback
            # check counts entries per ID instead of matching single items.
            if not data.recipe_id:
                raise HTTPException(422, 'Rezept fehlt.')
            exists = any(r['id'] == data.recipe_id for r in before['shopping_recipes'])
            if (data.action == 'ingredients_add') == exists:
                raise HTTPException(409, 'Die Rezeptzutaten sind bereits enthalten.' if exists else 'Die Rezeptzutaten sind nicht mehr enthalten.')
            if data.action == 'ingredients_add' and not any(r['id'] == data.recipe_id for d in before['days'] for r in d['recipes']):
                raise HTTPException(409, 'Bitte das Rezept zuerst für diese Woche planen.')
        elif data.action.startswith('check_'):
            group = 'ingredients' if data.action == 'check_ingredient' else 'additional'
            if sum(i['id'] == data.item_id for i in before[group]) > 1:
                raise HTTPException(409, 'Diese Kennung gehört zu mehreren Einkaufspositionen. Bitte diesen Artikel direkt in Cookidoo abhaken.')
            if data.owned is None or not any(i['id'] == data.item_id for i in before[group]):
                raise HTTPException(409, 'Der Einkaufsartikel hat sich geändert. Bitte neu laden.')
        elif not data.name or not data.name.strip():
            raise HTTPException(422, 'Bitte einen Einkaufsartikel eingeben.')

    async def apply(self, api, data):
        if data.action == 'plan_add':
            await api.add_recipes_to_calendar(data.day, [data.recipe_id])
        elif data.action == 'plan_remove':
            await api.remove_recipe_from_calendar(data.day, data.recipe_id)
        elif data.action == 'ingredients_add':
            await api.add_ingredient_items_for_recipes([data.recipe_id])
        elif data.action == 'ingredients_remove':
            await api.remove_ingredient_items_for_recipes([data.recipe_id])
        elif data.action == 'additional_add':
            await api.add_additional_items([data.name.strip()])
        else:
            if data.action == 'check_ingredient':
                items = await api.get_ingredient_items()
                method = api.edit_ingredient_items_ownership
            else:
                items = await api.get_additional_items()
                method = api.edit_additional_items_ownership
            matches = [i for i in items if i.id == data.item_id]
            if len(matches) != 1:
                raise ValueError('Item vanished or became ambiguous')
            item = matches[0]
            await method([replace(item, is_owned=data.owned)])

    def effect(self, data, after, before):
        if data.action.startswith('plan_'):
            exists = any(r['id'] == data.recipe_id for d in after['days'] if d['day'] == str(data.day) for r in d['recipes'])
            return exists == (data.action == 'plan_add')
        if data.action.startswith('ingredients_'):
            exists = any(r['id'] == data.recipe_id for r in after['shopping_recipes'])
            return exists == (data.action == 'ingredients_add')
        if data.action.startswith('check_'):
            group = 'ingredients' if data.action == 'check_ingredient' else 'additional'
            return any(i['id'] == data.item_id and i['is_owned'] == data.owned for i in after[group])
        old_ids = {i['id'] for i in before['additional']}
        return any(i['id'] not in old_ids and i['name'] == data.name.strip() for i in after['additional'])

    def unaffected(self, data, before, after):
        if data.action.startswith('plan_'):
            return all(a['custom_ids'] == b['custom_ids'] for a, b in zip(before['days'], after['days'])) and all(before[k] == after[k] for k in ('shopping_recipes', 'ingredients', 'additional')) and all(
                a == b for a, b in zip(before['days'], after['days']) if a['day'] != str(data.day)) and all(
                r in next(d for d in after['days'] if d['day'] == str(data.day))['recipes']
                for d in before['days'] if d['day'] == str(data.day) for r in d['recipes'] if r['id'] != data.recipe_id)
        if before['days'] != after['days']:
            return False
        if data.action.startswith('ingredients_'):
            # Own items, checkmarks and other recipes' positions must remain intact.
            return shopping_week.preserved(data.action, data.recipe_id, before, after)
        group = 'ingredients' if data.action == 'check_ingredient' else 'additional'
        return before['shopping_recipes'] == after['shopping_recipes'] and before['additional' if group == 'ingredients' else 'ingredients'] == after['additional' if group == 'ingredients' else 'ingredients'] and all(
            i in after[group] for i in before[group] if i['id'] != data.item_id)

    async def change(self, data, actor):
        start = week_start(data.start)
        with self.db() as conn:
            old = conn.execute('SELECT * FROM meal_operations WHERE id=?', (data.id,)).fetchone()
            if old:
                if old['payload'] != dump(data.model_dump(mode='json')):
                    raise HTTPException(409, 'Diese Anfragekennung wurde bereits anders verwendet.')
                if old['state'] != 'confirmed':
                    raise HTTPException(409, 'Dieser Vorgang wurde bereits gestartet. Bitte den Übertragungsstatus prüfen.')
            if not old and conn.execute("SELECT 1 FROM meal_operations WHERE state IN ('sending','review')").fetchone():
                raise HTTPException(409, 'Ein früherer Cookidoo-Vorgang ist noch unklar. Bitte zuerst prüfen.')
        if old:
            return self.status(start)
        async with self.adapter() as api:
            images = {}
            before = await snapshot(api, start, self.progress, images)
            self.store(before, images)
            if revision(before) != data.revision:
                raise HTTPException(409, 'Cookidoo wurde zwischenzeitlich geändert. Bitte den aktualisierten Stand laden und erneut auswählen.')
            self.validate_change(data, before)
            with self.db() as conn:
                conn.execute('INSERT INTO meal_operations VALUES(?,?,?,\'sending\',\'\',?)', (data.id, actor, dump(data.model_dump(mode='json')), time.time()))
            try:
                self.progress('write')
                await self.apply(api, data)
                after = await snapshot(api, start, self.progress, images)
                self.store(after, images)
                if not self.effect(data, after, before) or not self.unaffected(data, before, after):
                    raise ValueError('Readback did not match')
            except Exception as error:
                diagnostic = self.diagnose(error)
                with self.db() as conn:
                    conn.execute("UPDATE meal_operations SET state='review',message='Ergebnis unklar oder parallele Änderung erkannt. Bitte Cookidoo öffnen und den Stand prüfen; nicht blind wiederholen.' WHERE id=?", (data.id,))
                raise HTTPException(502, 'Cookidoo-Ergebnis muss geprüft werden. Der Vorgang wird nicht automatisch wiederholt. ' + diagnostic) from None
            with self.db() as conn:
                conn.execute("UPDATE meal_operations SET state='confirmed' WHERE id=?", (data.id,))
                conn.execute('INSERT INTO audit(actor,action,details,created) VALUES(?,?,?,?)', (actor, 'Cookidoo aktualisiert', data.action, datetime.now(TZ).isoformat()))
        return self.status(start)

    def demo_data(self, start):
        value = {'start': str(start), 'days': [{'day':str(start+timedelta(days=i)), 'recipes':[], 'custom_ids':[]} for i in range(7)],
                 'shopping_recipes':[], 'ingredients':[], 'additional':[]}
        demos = [('Linsen-Bolognese', 35), ('Kichererbsen-Curry', 40), ('Spinat-Ricotta-Pasta', 30)]
        for i, (name, minutes) in enumerate(demos):
            value['days'][i]['recipes'] = [{'id': 'demo-' + str(i), 'name': name, 'total_time': minutes*60}]
        value['ingredients'] = [{'id':'demo-lentils','name':'Rote Linsen','description':'200 g','is_owned':False}, {'id':'demo-tomato','name':'Passierte Tomaten','description':'500 g','is_owned':True}]
        value['additional'] = [{'id':'demo-breakfast','name':'Haferflocken fürs Frühstück','is_owned':False}]
        return value

    def background(self):
        stop = self.integrations.stop
        while not stop.is_set():
            if not self.demo:
                with self.db() as conn:
                    connected = conn.execute("SELECT 1 FROM integration_secrets WHERE key='cookidoo'").fetchone()
                    latest = conn.execute("SELECT value FROM meal_cache WHERE key='shopping'").fetchone()
                if connected:
                    start = week_start(json.loads(latest[0])['start']) if latest else saturday(datetime.now(TZ).date())
                    try:
                        self.run(self.sync(start))
                        with self.db() as conn:
                            conn.execute("DELETE FROM metadata WHERE key='cookidoo_sync_error'")
                    except HTTPException as error:
                        if error.status_code != 409:
                            with self.db() as conn:
                                conn.execute("INSERT OR REPLACE INTO metadata VALUES('cookidoo_sync_error','Automatischer Cookidoo-Abgleich fehlgeschlagen. Gespeicherter Stand bleibt verfügbar; bitte Verbindung prüfen.')")
            stop.wait(600)

    def routes(self, app, identity):
        def actor(request, admin=False):
            with self.db() as conn:
                user = identity(request, conn)
            if admin and user != 'tobi':
                raise HTTPException(403, 'Tobi verwaltet die Cookidoo-Verbindung.')
            return user

        def live():
            if self.demo:
                raise HTTPException(409, 'Die Cookidoo-Demo ist eine Vorschau; sie verändert keine echten Rezepte oder Einkaufslisten.')

        @app.get('/api/meals')
        def state(request: Request, start: str):
            actor(request)
            day = week_start(start)
            if self.demo:
                self.store(self.demo_data(day))
            return self.status(day)

        @app.post('/api/meals/connect')
        def connect(data: Connection, request: Request):
            actor(request, True)
            live()
            if not data.password.get_secret_value() or len(data.password.get_secret_value()) > 512:
                raise HTTPException(422, 'Bitte gültige Zugangsdaten eingeben.')
            return self.run(self.connect(data, saturday(datetime.now(TZ).date())))

        @app.post('/api/meals/sync')
        def sync(data: SyncInput, request: Request):
            actor(request)
            live()
            return self.run(self.sync(week_start(data.start)))

        @app.post('/api/meals/search')
        def search(data: SearchInput, request: Request):
            actor(request)
            live()
            return self.run(self.search(data))

        @app.get('/api/meals/recipe/{rid}')
        def detail(rid: str, request: Request):
            actor(request)
            live()
            if not re.fullmatch(r'r[0-9]+', rid):
                raise HTTPException(422, 'Ungültige Cookidoo-Rezept-ID.')
            return self.run(self.details(rid))

        @app.post('/api/meals/suggest')
        def suggest(data: SuggestInput, request: Request):
            actor(request)
            start = week_start(data.start)
            wishes = [w.strip()[:40] for w in data.wishes.split(',') if len(w.strip()) >= 2][:3]
            if self.demo:
                snapshot = self.status(start)['snapshot'] or {'days': []}
                planned = {d['day'] for d in snapshot['days'] if d['recipes'] or d['custom_ids']}
                result = self.suggestions.demo(start, data.weekday_minutes, data.weekend_minutes, planned)
                with self.db() as conn:
                    conn.execute('INSERT OR REPLACE INTO meal_cache VALUES(?,?,?)', ('suggestion:' + str(start), dump(result), time.time()))
                return result
            return self.run(self.suggestions.suggest(start, data.weekday_minutes, data.weekend_minutes, wishes, data.use_ai), timeout=150)

        @app.post('/api/meals/suggest/day')
        def suggest_day(data: SuggestDayInput, request: Request):
            actor(request)
            start = week_start(data.start)
            if self.demo:
                return self.suggestions.demo_day(start, str(data.day))
            return self.run(self.suggestions.suggest_day(start, str(data.day), data.use_ai), timeout=150)

        @app.post('/api/meals/shopped')
        def shopped(data: ShoppedInput, request: Request):
            user = actor(request)
            start = week_start(data.start)
            key = 'meal_shopped:' + str(start)
            with self.db() as conn:
                if data.shopped:
                    conn.execute('INSERT OR REPLACE INTO metadata VALUES(?,?)',
                                 (key, dump({'by': user, 'at': datetime.now(TZ).isoformat(timespec='seconds')})))
                else:
                    conn.execute('DELETE FROM metadata WHERE key=?', (key,))
                conn.execute('INSERT INTO audit(actor,action,details,created) VALUES(?,?,?,?)',
                             (user, 'Für die Woche eingekauft' if data.shopped else 'Einkauf zurückgenommen',
                              f'Woche ab {start.strftime("%d.%m.")}', datetime.now(TZ).isoformat()))
            return self.status(start)

        @app.get('/api/meals/image/{rid}')
        def image(rid: str, request: Request):
            actor(request)
            found = self.images.get(rid)
            if not found:
                raise HTTPException(404, 'Kein Rezeptbild verfügbar.')
            kind, path = found
            return FileResponse(path, media_type=kind, headers={'Cache-Control': 'private, max-age=604800'})

        @app.post('/api/meals/change')
        def change(data: Change, request: Request):
            user = actor(request)
            live()
            return self.run(self.change(data, user))

        @app.post('/api/meals/review/{operation_id}')
        def acknowledge(operation_id: str, request: Request):
            user = actor(request)
            live()
            if not self.lock.acquire(blocking=False):
                raise HTTPException(409, 'Bitte den laufenden Abgleich abwarten.')
            try:
                with self.db() as conn:
                    row = conn.execute("SELECT * FROM meal_operations WHERE id=? AND state='review'", (operation_id,)).fetchone()
                    if not row:
                        raise HTTPException(409, 'Dieser Vorgang benötigt keine Prüfung mehr.')
                # Always read first; acknowledgement never replays the previous write.
                result = asyncio.run(asyncio.wait_for(self.sync(week_start(json.loads(row['payload'])['start'])), REQUEST_TIMEOUT))
                with self.db() as conn:
                    conn.execute("UPDATE meal_operations SET state='reviewed',message='Manuell in Cookidoo geprüft' WHERE id=?", (operation_id,))
                    conn.execute('INSERT INTO audit(actor,action,details,created) VALUES(?,?,?,?)', (user, 'Cookidoo-Vorgang geprüft', operation_id, datetime.now(TZ).isoformat()))
                return {'ok': True}
            except HTTPException:
                raise
            except Exception:
                raise HTTPException(502, 'Cookidoo konnte nicht gelesen werden. Die Prüfung bleibt offen.')
            finally:
                self.lock.release()

        @app.get('/api/meals/shopping.html')
        def shopping_export(request: Request):
            actor(request)
            with self.db() as conn:
                row = conn.execute("SELECT * FROM meal_cache WHERE key='shopping'").fetchone()
            if not row:
                raise HTTPException(409, 'Bitte die Einkaufsliste zuerst laden.')
            data = json.loads(row['value'])
            items = data['ingredients'] + data['additional']
            stamp = datetime.fromtimestamp(row['updated'], TZ).strftime('%d.%m.%Y %H:%M')
            body = ''.join('<li><label><input type="checkbox" '+ ('checked ' if i['is_owned'] else '') + '>' + escape(i.get('description', '')) + ' ' + escape(i['name']) + '</label></li>' for i in items)
            return HTMLResponse('<!doctype html><html lang="de"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Einkaufsliste</title><h1>Einkaufsliste</h1><p>Gespeicherter Stand: '+stamp+' Uhr. Diese Kopie funktioniert ohne NAS. Änderungen hier werden nicht zu Cookidoo übertragen.</p><ul>'+body+'</ul></html>', headers={'Content-Disposition':'attachment; filename="Family-OS-Einkaufsliste.html"'})
