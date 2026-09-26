"""Contract and failure tests with a deterministic Cookidoo stand-in, never live writes."""
import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace as Row
import tempfile
import unittest
from uuid import uuid4
from unittest.mock import patch

from fastapi.testclient import TestClient
from app import create_app
from meals import Change, Connection, Meals, revision, snapshot
from cookidoo_api.types import CookidooAuthData


@dataclass
class Item:
    id: str
    name: str
    is_owned: bool = False
    description: str = ''


class Remote:
    def __init__(self):
        self.days = {}
        self.ingredients = [Item('old', 'Vorrat', True, '200 g')]
        self.additional = [Item('own', 'Frühstück <script>', False)]
        self.recipes = [Row(id='r1', name='Alt', ingredients=[Row(id='old')])]
        self.calls = []
        self.fail_after_write = False
        self.lose_custom = False

    async def get_recipes_in_calendar_week(self, anchor):
        monday = anchor - timedelta(days=anchor.weekday())
        return [Row(id=str(monday+timedelta(days=i)), recipes=deepcopy(self.days.get(str(monday+timedelta(days=i)), [])), customer_recipe_ids=[]) for i in range(7)]

    async def get_shopping_list_recipes(self): return deepcopy(self.recipes)
    async def get_ingredient_items(self): return deepcopy(self.ingredients)
    async def get_additional_items(self): return deepcopy(self.additional)

    def written(self, action):
        self.calls.append(action)
        if self.lose_custom: self.additional = []
        if self.fail_after_write: raise TimeoutError('secret must not appear in response')

    async def add_recipes_to_calendar(self, day, ids):
        self.days.setdefault(str(day), []).extend(Row(id=i, name='Linsen', total_time=2100) for i in ids)
        self.written('plan_add')

    async def remove_recipe_from_calendar(self, day, rid):
        self.days[str(day)] = [r for r in self.days[str(day)] if r.id != rid]
        self.written('plan_remove')

    async def add_ingredient_items_for_recipes(self, ids):
        self.recipes.extend(Row(id=i, name='Linsen', ingredients=[Row(id=i+'-ingredient')]) for i in ids)
        self.ingredients.extend(Item(i+'-ingredient', 'Linsen') for i in ids)
        self.written('ingredients_add')

    async def remove_ingredient_items_for_recipes(self, ids):
        removed = {i.id for r in self.recipes if r.id in ids for i in r.ingredients}
        self.recipes = [r for r in self.recipes if r.id not in ids]
        retained = {i.id for r in self.recipes for i in r.ingredients}
        self.ingredients = [i for i in self.ingredients if i.id not in removed-retained]
        self.written('ingredients_remove')

    async def edit_ingredient_items_ownership(self, items):
        self.ingredients = [next((n for n in items if n.id == i.id), i) for i in self.ingredients]
        self.written('check_ingredient')

    async def edit_additional_items_ownership(self, items):
        self.additional = [next((n for n in items if n.id == i.id), i) for i in self.additional]
        self.written('check_additional')

    async def add_additional_items(self, names):
        self.additional.extend(Item(str(uuid4()), n) for n in names)
        self.written('additional_add')


class MealTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = create_app(Path(self.tmp.name)/'family.sqlite', demo=True)
        self.meals = self.app.state.meals
        self.meals.demo = False  # Keep demo identity, exercise the real integration routes with a fake API.
        self.remote = Remote()
        @asynccontextmanager
        async def adapter(credentials=None): yield self.remote
        self.meals.adapter = adapter
        self.client = TestClient(self.app, base_url='http://127.0.0.1:8765', headers={'Origin':'http://127.0.0.1:8765', 'X-Family-Request':'1'})
        self.client.post('/api/login', json={'user':'tobi'})
        self.start = '2026-10-31'  # Saturday across a month boundary and two Cookidoo weeks.
        self.sync()

    def tearDown(self):
        self.client.close()
        self.tmp.cleanup()

    def sync(self):
        response = self.client.post('/api/meals/sync', json={'start':self.start})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def payload(self, action='plan_add', **fields):
        data = {'id':str(uuid4()), 'start':self.start, 'revision':self.client.get('/api/meals', params={'start':self.start}).json()['revision'], 'action':action}
        data.update(fields)
        if action.startswith('plan_'): data.setdefault('day', self.start); data.setdefault('recipe_id', 'r2')
        return data

    def change(self, action='plan_add', **fields):
        response = self.client.post('/api/meals/change', json=self.payload(action, **fields))
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_week_has_exactly_seven_days_across_month_and_provider_weeks(self):
        self.remote.days['2026-11-06'] = [Row(id='r3', name='Freitag', total_time=600)]
        s = self.sync()['snapshot']
        self.assertEqual([d['day'] for d in s['days']], ['2026-10-31','2026-11-01','2026-11-02','2026-11-03','2026-11-04','2026-11-05','2026-11-06'])
        self.assertEqual(s['days'][-1]['recipes'][0]['id'], 'r3')
        self.assertEqual(self.client.get('/api/meals?start=2026-11-01').status_code, 422)

    def test_duplicate_ids_load_without_losing_quantities_or_checked_states(self):
        self.remote.ingredients.extend([Item('old', 'Vorrat', False, '300 g'), Item('old', 'Vorrat', True, '200 g')])
        self.remote.additional.append(Item('own', 'Anderer Artikel', True))
        self.remote.recipes.append(deepcopy(self.remote.recipes[0]))
        result = self.sync()
        s = result['snapshot']
        self.assertEqual(len(s['ingredients']), 3)
        self.assertEqual(len(s['additional']), 2)
        self.assertEqual(len(s['shopping_recipes']), 2)
        self.assertEqual(s['duplicate_ids'], {'ingredients':['old'], 'additional':['own'], 'shopping_recipes':['r1']})
        self.assertEqual(sum(i['is_owned'] for i in s['ingredients']), 2)
        self.remote.ingredients.reverse()
        self.remote.additional.reverse()
        self.assertEqual(result['revision'], self.sync()['revision'])
        exported = self.client.get('/api/meals/shopping.html').text
        self.assertEqual(exported.count('200 g'), 2)
        self.assertIn('300 g', exported)

    def test_ambiguous_items_cannot_be_written_but_other_operations_work(self):
        self.remote.ingredients.append(Item('old', 'Weiterer Vorrat', False, '300 g'))
        self.sync()
        for action, fields in [('check_ingredient', {'item_id':'old','owned':False}), ('ingredients_remove', {'recipe_id':'r1'})]:
            response = self.client.post('/api/meals/change', json=self.payload(action, **fields))
            self.assertEqual(response.status_code, 409)
        self.assertEqual(self.remote.calls, [])
        self.change()  # Calendar planning does not depend on ingredient ID uniqueness.
        self.assertEqual(self.client.post('/api/meals/change', json=self.payload('ingredients_add',recipe_id='r2')).status_code, 409)
        self.change('check_additional', item_id='own', owned=True)
        self.change('additional_add', name='Brot')
        self.assertEqual(len(self.remote.ingredients), 2)

    def test_ambiguous_custom_item_cannot_be_checked(self):
        self.remote.additional.append(deepcopy(self.remote.additional[0]))
        self.sync()
        response = self.client.post('/api/meals/change', json=self.payload('check_additional',item_id='own',owned=True))
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.remote.calls, [])

    def test_plan_add_retry_is_idempotent_and_remove_preserves_shopping(self):
        p = self.payload()
        for _ in range(2): self.assertEqual(self.client.post('/api/meals/change', json=p).status_code, 200)
        self.assertEqual(self.remote.calls, ['plan_add'])
        self.change('plan_remove')
        self.assertEqual(len(self.remote.ingredients), 1)
        self.assertTrue(self.remote.ingredients[0].is_owned)
        self.assertEqual(len(self.remote.additional), 1)

    def test_stale_revision_stops_before_remote_write(self):
        p = self.payload()
        self.remote.additional.append(Item('outside', 'Extern'))
        self.assertEqual(self.client.post('/api/meals/change', json=p).status_code, 409)
        self.assertEqual(self.remote.calls, [])
        self.assertEqual(len(self.client.get('/api/meals?start='+self.start).json()['snapshot']['additional']), 2)

    def test_occupied_day_cannot_be_silently_overwritten(self):
        self.change()
        self.assertEqual(self.client.post('/api/meals/change', json=self.payload(recipe_id='r3')).status_code, 409)
        self.assertEqual(self.remote.calls, ['plan_add'])

    def test_lost_response_blocks_retry_and_review_does_not_replay(self):
        p = self.payload()
        self.remote.fail_after_write = True
        r = self.client.post('/api/meals/change', json=p)
        self.assertEqual(r.status_code, 502)
        self.assertNotIn('secret', r.text)
        self.assertEqual(self.client.post('/api/meals/change', json=p).status_code, 409)
        self.assertEqual(self.client.post('/api/meals/change', json=self.payload('additional_add', name='Neu')).status_code, 409)
        self.assertEqual(self.remote.calls, ['plan_add'])
        self.remote.fail_after_write = False
        self.assertEqual(self.client.post('/api/meals/review/'+p['id'], json={}).status_code, 200)
        self.assertEqual(self.remote.calls, ['plan_add'])
        self.change('additional_add', name='Neu')

    def test_ingredient_add_remove_preserves_own_items_and_checked_flags(self):
        self.change()
        self.change('ingredients_add', recipe_id='r2')
        self.assertTrue(self.remote.ingredients[0].is_owned)
        self.assertEqual(self.remote.additional[0].id, 'own')
        self.change('ingredients_remove', recipe_id='r2')
        self.assertEqual([i.id for i in self.remote.ingredients], ['old'])
        self.assertEqual([r.id for r in self.remote.recipes], ['r1'])

    def test_unplanned_ingredients_are_rejected_without_write(self):
        self.assertEqual(self.client.post('/api/meals/change', json=self.payload('ingredients_add', recipe_id='r2')).status_code, 409)
        self.assertEqual(self.remote.calls, [])

    def test_unrelated_data_loss_is_detected_and_requires_review(self):
        self.remote.lose_custom = True
        r = self.client.post('/api/meals/change', json=self.payload())
        self.assertEqual(r.status_code, 502)
        self.assertEqual(self.client.get('/api/meals?start='+self.start).json()['reviews'][0]['state'], 'review')

    def test_checkmarks_and_custom_articles_are_targeted(self):
        self.change('check_ingredient', item_id='old', owned=False)
        self.assertFalse(self.remote.ingredients[0].is_owned)
        self.change('check_additional', item_id='own', owned=True)
        self.assertTrue(self.remote.additional[0].is_owned)
        self.change('additional_add', name=' Brot ')
        self.assertEqual([i.name for i in self.remote.additional], ['Frühstück <script>', 'Brot'])

    def test_restart_converts_inflight_write_to_review(self):
        with self.app.state.db() as c:
            c.execute("INSERT INTO meal_operations VALUES(?, 'tobi', '{}', 'sending', '', 0)", (str(uuid4()),))
        restarted = Meals(self.app.state.integrations)
        self.assertEqual(restarted.status(date.fromisoformat(self.start))['reviews'][0]['state'], 'review')

    def test_download_is_authenticated_and_escapes_names(self):
        r = self.client.get('/api/meals/shopping.html')
        self.assertEqual(r.status_code, 200)
        self.assertIn('&lt;script&gt;', r.text)
        self.assertNotIn('<script>', r.text)
        self.assertIn('attachment;', r.headers['content-disposition'])
        self.client.post('/api/logout', json={})
        self.assertEqual(self.client.get('/api/meals?start='+self.start).status_code, 401)
        self.assertEqual(self.client.get('/api/meals/shopping.html').status_code, 401)

    def test_only_tobi_connects_and_demo_cannot_write(self):
        self.client.post('/api/login', json={'user':'britta'})
        self.assertEqual(self.client.post('/api/meals/connect', json={'email':'test@example.org','password':'example'}).status_code, 403)
        self.meals.demo = True
        self.assertEqual(self.client.post('/api/meals/sync', json={'start':self.start}).status_code, 409)
        self.assertEqual(self.client.post('/api/meals/change', json=self.payload()).status_code, 409)

    def test_reusing_operation_id_with_different_payload_is_rejected(self):
        p = self.payload()
        self.assertEqual(self.client.post('/api/meals/change', json=p).status_code, 200)
        p['recipe_id'] = 'r3'
        self.assertEqual(self.client.post('/api/meals/change', json=p).status_code, 409)

    def test_parallel_operation_is_busy_without_another_write(self):
        self.meals.lock.acquire()
        try: self.assertEqual(self.client.post('/api/meals/change', json=self.payload()).status_code, 409)
        finally: self.meals.lock.release()
        self.assertEqual(self.remote.calls, [])

    def test_account_switch_rejected_before_login(self):
        with self.app.state.db() as c: c.execute("INSERT INTO metadata VALUES('cookidoo_account','previous')")
        async def run():
            async with self.meals.client(Connection(email='other@example.org',password='example')): self.fail('Unexpected connection')
        with self.assertRaises(Exception) as error: asyncio.run(run())
        self.assertEqual(error.exception.status_code, 409)

    def test_credentials_are_not_persisted_and_tokens_are_encrypted_and_restored(self):
        from cryptography.fernet import Fernet
        self.app.state.integrations.cipher = Fernet(Fernet.generate_key())
        captured = []
        class AuthAPI:
            def __init__(self, session, cfg, on_auth_data_update):
                captured.append(cfg)
                self.callback = on_auth_data_update
                self.auth_data = None
            async def login(self):
                self.auth_data = CookidooAuthData('test-access', 'test-refresh', 9999999999)
                self.callback(self.auth_data)
            def apply_auth_data(self, auth): self.auth_data = auth
        async def exercise():
            async with self.meals.client(Connection(email='test@example.org', password='test-password')): pass
            async with self.meals.client() as api:
                self.assertEqual(api.auth_data.refresh_token, 'test-refresh')
                api.auth_data = CookidooAuthData('new-access', 'new-refresh', 9999999999)
        with patch('meals.Cookidoo', AuthAPI): asyncio.run(exercise())
        self.assertEqual(captured[0].password, 'test-password')
        self.assertEqual(captured[1].password, '')
        with self.app.state.db() as c:
            stored = str([tuple(r) for r in c.execute('SELECT * FROM integration_secrets')]) + str([tuple(r) for r in c.execute('SELECT * FROM metadata')])
        for secret in ('test-password', 'test@example.org', 'new-access', 'new-refresh'):
            self.assertNotIn(secret, stored)
        self.assertEqual(self.app.state.integrations.secret('cookidoo')['refresh_token'], 'new-refresh')

    def test_removing_recipe_preserves_ingredients_shared_with_another_recipe(self):
        self.remote.recipes.append(Row(id='r2', name='Teilt Zutaten', ingredients=[Row(id='old')]))
        self.sync()
        self.change('ingredients_remove', recipe_id='r2')
        self.assertEqual([i.id for i in self.remote.ingredients], ['old'])
        self.assertTrue(self.remote.ingredients[0].is_owned)

    def test_timeout_marks_inflight_uncertain(self):
        async def operation():
            with self.app.state.db() as c:
                c.execute("INSERT INTO meal_operations VALUES(?, 'tobi', '{}', 'sending', '', 0)", (str(uuid4()),))
            raise TimeoutError()
        with self.assertRaises(Exception): self.meals.run(operation())
        self.assertEqual(self.meals.status(date.fromisoformat(self.start))['reviews'][0]['state'], 'review')

    def test_login_is_separate_from_initial_snapshot(self):
        from unittest.mock import AsyncMock
        with patch('meals.snapshot', new_callable=AsyncMock) as read:
            response = self.client.post('/api/meals/connect', json={'email':'test@example.org','password':'example'})
        self.assertEqual(response.status_code, 200)
        read.assert_not_awaited()

    def test_auth_diagnostic_is_safe_and_available_after_proxy_replaces_response(self):
        from cookidoo_api.exceptions import CookidooAuthException
        @asynccontextmanager
        async def unavailable(credentials=None):
            self.meals.progress('login')
            raise CookidooAuthException('provider body: private@example.org password=secret refresh_token=secret')
            yield
        self.meals.adapter = unavailable
        with self.assertLogs('uvicorn.error.family_os.cookidoo', level='INFO') as logged:
            response = self.client.post('/api/meals/connect', json={'email':'private@example.org','password':'secret'})
        self.assertEqual(response.status_code, 502)
        state = self.client.get('/api/meals?start='+self.start).json()
        self.assertEqual(state['diagnostic']['category'], 'authentication')
        self.assertEqual(state['diagnostic']['phase'], 'login')
        self.assertIn(state['diagnostic']['id'], response.json()['detail'])
        self.assertIn(state['diagnostic']['id'], '\n'.join(logged.output))
        for secret in ('private@example.org', 'password=', 'refresh_token=', 'secret', 'provider body'):
            self.assertNotIn(secret, str(state)+response.text+str(logged.output))

    def test_login_http_status_extracted_without_logging_provider_text(self):
        from cookidoo_api.exceptions import CookidooAuthException
        async def fail():
            self.meals.progress('login')
            raise CookidooAuthException('Login flow failed: could not reach login page (status 403).')
        with self.assertLogs('uvicorn.error.family_os.cookidoo'), self.assertRaises(Exception):
            self.meals.run(fail())
        self.assertEqual(self.meals.status(date.fromisoformat(self.start))['diagnostic']['upstream_status'], 403)

    def test_wrapped_dns_error_and_success_clears_stale_diagnostic(self):
        import socket
        from cookidoo_api.exceptions import CookidooRequestException
        async def fail():
            self.meals.progress('login')
            try: raise socket.gaierror('hostname-with-private-data')
            except socket.gaierror as error: raise CookidooRequestException('provider body') from error
        with self.assertLogs('uvicorn.error.family_os.cookidoo'), self.assertRaises(Exception):
            self.meals.run(fail())
        self.assertEqual(self.meals.status(date.fromisoformat(self.start))['diagnostic']['category'], 'dns')
        self.sync()
        self.assertIsNone(self.meals.status(date.fromisoformat(self.start))['error'])

    def test_whole_operation_has_bounded_timeout_and_retains_write_review(self):
        async def slow():
            self.meals.progress('write')
            with self.app.state.db() as c:
                c.execute("INSERT INTO meal_operations VALUES(?, 'tobi', '{}', 'sending', '', 0)", (str(uuid4()),))
            await asyncio.sleep(1)
        with patch('meals.REQUEST_TIMEOUT', .01), self.assertLogs('uvicorn.error.family_os.cookidoo'), self.assertRaises(Exception):
            self.meals.run(slow())
        state = self.meals.status(date.fromisoformat(self.start))
        self.assertEqual(state['diagnostic']['category'], 'timeout')
        self.assertEqual(state['reviews'][0]['state'], 'review')


if __name__ == '__main__': unittest.main()
