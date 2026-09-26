from datetime import datetime, timedelta
import json
from pathlib import Path
import tempfile
import unittest
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from app import create_app
from meals import saturday

TZ = ZoneInfo('Europe/Berlin')
BASE = 'http://127.0.0.1:8765'


class WidgetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = create_app(Path(self.tmp.name) / 'family.sqlite', demo=True)
        self.today = datetime.now(TZ).date()
        self.tobi = self.client('tobi')
        self.plain = TestClient(self.app, base_url=BASE)  # like Scriptable: no cookie, no origin

    def tearDown(self):
        self.tobi.close()
        self.plain.close()
        self.tmp.cleanup()

    def client(self, user):
        client = TestClient(self.app, base_url=BASE, headers={'Origin': BASE, 'X-Family-Request': '1'})
        self.assertEqual(client.post('/api/login', json={'user': user}).status_code, 200)
        return client

    def key(self, client=None):
        response = (client or self.tobi).post('/api/widget/key', json={})
        self.assertEqual(response.status_code, 200)
        return response.json()['token']

    def read(self, token):
        return self.plain.get('/api/widget', headers={'Authorization': 'Bearer ' + token})

    def slot(self, day, kind, owner):
        with self.app.state.db() as conn:
            conn.execute('INSERT INTO appointments(day,kind,owner) VALUES(?,?,?) '
                         'ON CONFLICT(day,kind) DO UPDATE SET owner=excluded.owner', (str(day), kind, owner))

    def test_summary_for_today_and_tomorrow(self):
        self.slot(self.today, 'bring', 'tobi')
        self.slot(self.today, 'pickup', 'britta')
        tomorrow = self.today + timedelta(days=1)
        with self.app.state.db() as conn:
            conn.execute("INSERT INTO nanny_shifts(day,start,end,state,creator,created,updated) "
                         "VALUES(?,'16:00','18:00','confirmed','tobi','x','x')", (str(tomorrow),))
            start = saturday(self.today)
            days = [{'day': str(start + timedelta(days=i)), 'recipes': [], 'custom_ids': []} for i in range(7)]
            days[(self.today - start).days]['recipes'] = [{'id': 'r1', 'name': 'Linsencurry'}]
            conn.execute('INSERT OR REPLACE INTO meal_cache VALUES(?,?,?)', ('week:' + str(start), json.dumps({'days': days}), 0))
        response = self.read(self.key())
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['user'], 'Tobi')
        today, next_day = data['days']
        self.assertEqual((today['day'], today['bring'], today['pickup']), (str(self.today), 'Tobi', 'Britta'))
        self.assertEqual(today['dinner'], 'Linsencurry')
        self.assertEqual(next_day['nanny'], ['16:00–18:00'])
        self.assertEqual(response.headers['cache-control'], 'no-store')
        self.assertTrue(self.tobi.get('/api/widget/key').json()['last_used'])

    def test_closure_replaces_ways(self):
        self.slot(self.today, 'bring', 'tobi')
        with self.app.state.db() as conn:
            conn.execute("INSERT INTO day_closures(day,kind,note,batch,state,creator,created) "
                         "VALUES(?,'sick','','b1','confirmed','tobi','x')", (str(self.today),))
        today = self.read(self.key()).json()['days'][0]
        self.assertEqual(today['closure'], 'Lina krank')
        self.assertIsNone(today['bring'])

    def test_key_is_personal_read_only_and_revocable(self):
        self.assertEqual(self.plain.get('/api/widget').status_code, 401)
        self.assertEqual(self.tobi.get('/api/widget').status_code, 401)  # a session cookie is not enough
        old = self.key()
        new = self.key()
        self.assertEqual(self.read(old).status_code, 401)
        self.assertEqual(self.read(new).status_code, 200)
        # The widget key opens nothing else.
        headers = {'Authorization': 'Bearer ' + new}
        self.assertEqual(self.plain.get('/api/state', params={'month': str(self.today)[:7]}, headers=headers).status_code, 401)
        # Britta's key shows Britta's view.
        britta = self.client('britta')
        self.assertEqual(self.read(self.key(britta)).json()['user'], 'Britta')
        britta.close()
        self.assertEqual(self.tobi.post('/api/widget/key/revoke', json={}).status_code, 200)
        self.assertEqual(self.read(new).status_code, 401)
        self.assertFalse(self.tobi.get('/api/widget/key').json()['active'])

    def test_key_creation_needs_login_and_origin(self):
        self.assertEqual(self.plain.post('/api/widget/key', json={}).status_code, 403)
        anonymous = TestClient(self.app, base_url=BASE, headers={'Origin': BASE, 'X-Family-Request': '1'})
        self.assertEqual(anonymous.post('/api/widget/key', json={}).status_code, 401)
        anonymous.close()
        with self.app.state.db() as conn:
            stored = conn.execute("SELECT value FROM metadata WHERE key LIKE 'widget_token:%'").fetchall()
        self.assertEqual(stored, [])


if __name__ == '__main__':
    unittest.main()
