"""Cookidoo integration: local snapshots and individually verified writes.

No blanket clearing of shopping lists; credentials are used only for initial
login. Rotated tokens are encrypted with the existing NAS integration key.
"""
import asyncio
from contextlib import asynccontextmanager
from dataclasses import asdict, replace
from datetime import date, datetime, timedelta
import hashlib
from html import escape
import json
import logging
import re
import threading
import time
from typing import Literal

import aiohttp
from cookidoo_api import Cookidoo
from cookidoo_api.types import CookidooAuthData, CookidooConfig, CookidooLocalizationConfig
from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field, SecretStr
from integrations import dump, TZ

for name in ('cookidoo_api.cookidoo', 'cookidoo_api.well_known', 'cookidoo_api.helpers'):
    logging.getLogger(name).disabled = True

SCHEMA = '''
CREATE TABLE IF NOT EXISTS meal_cache(key TEXT PRIMARY KEY, value TEXT NOT NULL, updated REAL NOT NULL);
CREATE TABLE IF NOT EXISTS meal_operations(id TEXT PRIMARY KEY, actor TEXT NOT NULL REFERENCES users(id), payload TEXT NOT NULL, state TEXT NOT NULL, message TEXT NOT NULL DEFAULT '', created REAL NOT NULL);
'''


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


async def snapshot(client, start):
    days = {}
    for anchor in (start, start + timedelta(days=6)):
        for day in await client.get_recipes_in_calendar_week(anchor):
            parsed = date.fromisoformat(day.id)
            if start <= parsed <= start + timedelta(days=6):
                days[day.id] = {'day': day.id, 'recipes': [recipe(r) for r in day.recipes], 'custom_ids': day.customer_recipe_ids}
    for offset in range(7):
        day = str(start + timedelta(days=offset))
        days.setdefault(day, {'day': day, 'recipes': [], 'custom_ids': []})
    shopping_recipes = [{**recipe(r), 'ingredient_ids': sorted(i.id for i in r.ingredients)} for r in await client.get_shopping_list_recipes()]
    ingredients = [asdict(i) for i in await client.get_ingredient_items()]
    additional = [asdict(i) for i in await client.get_additional_items()]
    for items in (shopping_recipes, ingredients, additional):
        if len({i['id'] for i in items}) != len(items):
            raise ValueError('Ambiguous IDs')
        items.sort(key=lambda i: i['id'])
    for day in days.values():
        day['recipes'].sort(key=lambda r: r['id'])
        day['custom_ids'].sort()
    return {'start': str(start), 'days': sorted(days.values(), key=lambda d: d['day']), 'shopping_recipes': shopping_recipes, 'ingredients': ingredients, 'additional': additional}


class Connection(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: SecretStr


class SyncInput(BaseModel):
    start: str


class SearchInput(BaseModel):
    query: str = Field(min_length=2, max_length=120)
    max_minutes: int = Field(default=45, ge=5, le=180)


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
        with self.db() as conn:
            conn.executescript(SCHEMA)
            conn.execute("UPDATE meal_operations SET state='review',message='Der Server wurde während der Übertragung neu gestartet. Bitte in Cookidoo prüfen.' WHERE state='sending'")
        self.adapter = self.client

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
                await api.login()
                with self.db() as conn:
                    conn.execute("INSERT OR REPLACE INTO metadata VALUES('cookidoo_account',?)", (account,))
            else:
                token = self.integrations.secret('cookidoo')
                if not token:
                    raise HTTPException(409, 'Bitte zuerst Cookidoo verbinden.')
                api.apply_auth_data(CookidooAuthData(**token))
            try:
                yield api
            finally:
                if api.auth_data:
                    self.integrations.save_secret('cookidoo', asdict(api.auth_data))

    def run(self, coroutine):
        if not self.lock.acquire(blocking=False):
            coroutine.close()
            raise HTTPException(409, 'Cookidoo wird gerade abgeglichen. Bitte kurz warten.')
        try:
            return asyncio.run(asyncio.wait_for(coroutine, timeout=150))
        except HTTPException:
            raise
        except Exception:
            with self.db() as conn:
                conn.execute("UPDATE meal_operations SET state='review',message='Antwort von Cookidoo unklar. Bitte vor einem erneuten Schreibzugriff prüfen.' WHERE state='sending'")
            raise HTTPException(502, 'Cookidoo konnte den Vorgang nicht eindeutig bestätigen. Bitte den Verbindungs- und Übertragungsstatus prüfen.')
        finally:
            self.lock.release()

    def store(self, value):
        with self.db() as conn:
            conn.execute('INSERT OR REPLACE INTO meal_cache VALUES(?,?,?)', ('week:' + value['start'], dump(value), time.time()))
            conn.execute('INSERT OR REPLACE INTO meal_cache VALUES(?,?,?)', ('shopping', dump(value), time.time()))

    def status(self, start):
        with self.db() as conn:
            row = conn.execute('SELECT * FROM meal_cache WHERE key=?', ('week:' + str(start),)).fetchone()
            latest = conn.execute("SELECT * FROM meal_cache WHERE key='shopping'").fetchone()
            error = conn.execute("SELECT value FROM metadata WHERE key='cookidoo_sync_error'").fetchone()
            connected = bool(conn.execute("SELECT 1 FROM integration_secrets WHERE key='cookidoo'").fetchone())
            reviews = [dict(r) for r in conn.execute("SELECT id,state,message,created FROM meal_operations WHERE state IN ('sending','review') ORDER BY created")]
        data = json.loads(row['value']) if row else None
        # A snapshot has one coherent revision; don't splice a newer shopping list into it.
        return {'error': error[0] if error else None, 'connected': connected and not self.demo, 'demo': self.demo, 'snapshot': data, 'revision': revision(data) if data else None,
                'updated': row['updated'] if row else None, 'reviews': reviews,
                'shopping_updated': latest['updated'] if latest else None}

    async def sync(self, start):
        async with self.adapter() as api:
            value = await snapshot(api, start)
            self.store(value)
            return self.status(start)

    async def connect(self, credentials, start):
        async with self.adapter(credentials) as api:
            self.store(await snapshot(api, start))
        return self.status(start)

    async def search(self, data):
        async with self.adapter() as api:
            found = await api.search_recipes(query=data.query.strip(), languages='de', total_time=data.max_minutes * 60, page_size=12)
            return {'recipes': [recipe(r) for r in found.recipes], 'total': found.total}

    async def details(self, rid):
        async with self.adapter() as api:
            r = await api.get_recipe_details(rid)
            return {**recipe(r), 'serving_size': r.serving_size, 'ingredients': [asdict(i) for i in r.ingredients],
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
            if not data.recipe_id:
                raise HTTPException(422, 'Rezept fehlt.')
            exists = any(r['id'] == data.recipe_id for r in before['shopping_recipes'])
            if (data.action == 'ingredients_add') == exists:
                raise HTTPException(409, 'Die Rezeptzutaten sind bereits enthalten.' if exists else 'Die Rezeptzutaten sind nicht mehr enthalten.')
            if data.action == 'ingredients_add' and not any(r['id'] == data.recipe_id for d in before['days'] for r in d['recipes']):
                raise HTTPException(409, 'Bitte das Rezept zuerst für diese Woche planen.')
        elif data.action.startswith('check_'):
            group = 'ingredients' if data.action == 'check_ingredient' else 'additional'
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
            item = next((i for i in items if i.id == data.item_id), None)
            if not item:
                raise ValueError('Item vanished')
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
            # Existing custom items and checked flags on surviving ingredient IDs must remain intact.
            remaining = {i['id']: i for i in after['ingredients']}
            preserved = all(remaining[i['id']] == i for i in before['ingredients'] if i['id'] in remaining)
            if data.action == 'ingredients_add':
                preserved = preserved and all(i['id'] in remaining for i in before['ingredients'])
            if data.action == 'ingredients_remove':
                removed = next(r for r in before['shopping_recipes'] if r['id'] == data.recipe_id)
                others = {iid for r in before['shopping_recipes'] if r['id'] != data.recipe_id for iid in r['ingredient_ids']}
                allowed = set(removed['ingredient_ids']) - others
                preserved = preserved and all(i['id'] in remaining for i in before['ingredients'] if i['id'] not in allowed)
            return preserved and before['additional'] == after['additional'] and all(r in after['shopping_recipes'] for r in before['shopping_recipes'] if r['id'] != data.recipe_id)
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
            before = await snapshot(api, start)
            self.store(before)
            if revision(before) != data.revision:
                raise HTTPException(409, 'Cookidoo wurde zwischenzeitlich geändert. Bitte den aktualisierten Stand laden und erneut auswählen.')
            self.validate_change(data, before)
            with self.db() as conn:
                conn.execute('INSERT INTO meal_operations VALUES(?,?,?,\'sending\',\'\',?)', (data.id, actor, dump(data.model_dump(mode='json')), time.time()))
            try:
                await self.apply(api, data)
                after = await snapshot(api, start)
                self.store(after)
                if not self.effect(data, after, before) or not self.unaffected(data, before, after):
                    raise ValueError('Readback did not match')
            except Exception:
                with self.db() as conn:
                    conn.execute("UPDATE meal_operations SET state='review',message='Ergebnis unklar oder parallele Änderung erkannt. Bitte Cookidoo öffnen und den Stand prüfen; nicht blind wiederholen.' WHERE id=?", (data.id,))
                raise HTTPException(502, 'Cookidoo-Ergebnis muss geprüft werden. Der Vorgang wird nicht automatisch wiederholt.')
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
                result = asyncio.run(asyncio.wait_for(self.sync(week_start(json.loads(row['payload'])['start'])), 150))
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
