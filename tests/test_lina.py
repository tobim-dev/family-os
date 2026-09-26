"""Lina: diapers, spare clothes at the nursery, clothing needs (K-01 to K-07)."""
from datetime import date, datetime, timedelta
from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient
from app import create_app
from integrations import TZ
from lina import Lina


class LinaTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = create_app(Path(self.tmp.name) / 'family.sqlite', demo=True)
        with self.app.state.db() as conn:
            for table in ('lina_items', 'lina_diapers', 'work_calendar_items', 'tasks', 'proposals', 'issues', 'appointments', 'day_closures'):
                conn.execute('DELETE FROM ' + table)
            conn.execute("DELETE FROM metadata WHERE key LIKE 'lina_%' AND key!='lina_seeded'")
        self.tobi = self.client('tobi')
        self.britta = self.client('britta')

    def tearDown(self):
        self.tobi.close()
        self.britta.close()
        self.tmp.cleanup()

    def client(self, user):
        client = TestClient(self.app, base_url='http://127.0.0.1:8765',
                            headers={'Origin': 'http://127.0.0.1:8765', 'X-Family-Request': '1'})
        self.assertEqual(client.post('/api/login', json={'user': user}).status_code, 200)
        return client

    def diaper(self, kind, packs=1, client=None):
        response = (client or self.britta).post('/api/lina/diapers', json={'kind': kind, 'packs': packs})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def tasks(self, title=None):
        with self.app.state.db() as conn:
            rows = conn.execute('SELECT title,owner,state,details,due FROM tasks ORDER BY id').fetchall()
        return [dict(r) for r in rows if title is None or r['title'] == title]

    def test_stock_follows_events_and_low_stock_task_goes_to_shopper(self):
        self.assertIsNone(self.diaper('opened')['stock'])  # unknown until counted
        self.assertEqual(self.tasks(), [])
        self.assertEqual(self.diaper('set', 3)['stock'], 3)
        self.assertEqual(self.diaper('opened')['stock'], 2)
        self.assertEqual(self.tasks(), [])
        self.assertEqual(self.diaper('opened')['stock'], 1)
        [task] = self.tasks('Windeln kaufen')
        self.assertEqual((task['owner'], task['state']), ('tobi', 'open'))
        self.assertIn('noch 1 ungeöffnete Packung', task['details'])
        self.diaper('opened')  # stock 0: no second task
        self.assertEqual(len(self.tasks('Windeln kaufen')), 1)
        self.assertEqual(self.diaper('bought', 4)['stock'], 4)
        self.assertEqual(self.tasks('Windeln kaufen')[0]['state'], 'done')

    def test_settings_change_owner_threshold_and_size(self):
        response = self.tobi.post('/api/lina/diapers/settings', json={'threshold': 2, 'owner': 'britta', 'size': '5'})
        self.assertEqual(response.status_code, 200)
        self.diaper('set', 3)
        self.diaper('opened')
        [task] = self.tasks('Windeln kaufen')
        self.assertEqual(task['owner'], 'britta')
        self.assertIn('Größe 5', task['details'])

    def test_opening_counts_single_packs_only(self):
        self.assertEqual(self.britta.post('/api/lina/diapers', json={'kind': 'opened', 'packs': 3}).status_code, 422)
        self.assertEqual(self.britta.post('/api/lina/diapers', json={'kind': 'bought', 'packs': 0}).status_code, 422)

    def test_pace_and_estimate(self):
        events = [{'kind': 'set', 'packs': 2, 'created': '2026-10-01T08:00:00+02:00'},
                  {'kind': 'opened', 'packs': 1, 'created': '2026-10-01T08:00:00+02:00'},
                  {'kind': 'opened', 'packs': 1, 'created': '2026-10-06T08:00:00+02:00'},
                  {'kind': 'opened', 'packs': 1, 'created': '2026-10-11T08:00:00+02:00'}]
        self.assertEqual(Lina.stock(events), 0)
        self.assertEqual(Lina.pace(events), 5.0)
        self.assertIsNone(Lina.pace(events[:2]))

    def test_nursery_clothes_task_goes_to_next_bringing_parent(self):
        today = datetime.now(TZ).date()
        day = today + timedelta(days=1)
        while day.weekday() > 4:
            day += timedelta(days=1)
        with self.app.state.db() as conn:
            conn.execute("INSERT INTO appointments(day,kind,owner,start,end,version) VALUES(?,'bring','tobi','07:45','08:45',1)", (str(day),))
        response = self.britta.post('/api/lina/items', json={'list': 'nursery', 'text': 'Body und Hose', 'size': '92'})
        self.assertEqual(response.status_code, 200)
        [task] = self.tasks('Wechselkleidung in die Krippe')
        self.assertEqual(task['owner'], 'tobi')
        self.assertIn('Body und Hose (Größe 92)', task['details'])
        self.assertTrue(task['due'].startswith(str(day) + 'T07:45'))

    def test_nursery_clothes_skip_closed_day_and_fall_back_to_britta(self):
        today = datetime.now(TZ).date()
        day = today + timedelta(days=1)
        while day.weekday() > 4:
            day += timedelta(days=1)
        with self.app.state.db() as conn:
            conn.execute("INSERT INTO appointments(day,kind,owner,start,end,version) VALUES(?,'bring','tobi','07:45','08:45',1)", (str(day),))
            conn.execute("INSERT INTO day_closures(day,kind,batch,state,creator,created) VALUES(?,'closed','b','confirmed','tobi','x')", (str(day),))
        self.tobi.post('/api/lina/items', json={'list': 'nursery', 'text': 'Socken'})
        self.assertEqual(self.tasks('Wechselkleidung in die Krippe')[0]['owner'], 'britta')

    def test_clothing_need_only_urgent_creates_task_for_britta(self):
        self.assertEqual(self.tobi.post('/api/lina/items', json={'list': 'need', 'text': 'Jacke'}).status_code, 422)
        self.tobi.post('/api/lina/items', json={'list': 'need', 'text': 'Sommerhut', 'urgency': 'later'})
        self.assertEqual(self.tasks(), [])
        self.tobi.post('/api/lina/items', json={'list': 'need', 'text': 'Gummistiefel', 'size': '24', 'urgency': 'urgent'})
        [task] = self.tasks('Kleidung besorgen')
        self.assertEqual(task['owner'], 'britta')
        items = self.britta.get('/api/lina').json()['items']
        urgent = next(i for i in items if i['text'] == 'Gummistiefel')
        response = self.britta.post(f"/api/lina/items/{urgent['id']}", json={'action': 'done', 'version': urgent['version']})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.tasks('Kleidung besorgen')[0]['state'], 'done')
        stale = self.britta.post(f"/api/lina/items/{urgent['id']}", json={'action': 'reopen', 'version': urgent['version']})
        self.assertEqual(stale.status_code, 409)

    def test_sort_out_needs_destination(self):
        self.assertEqual(self.britta.post('/api/lina/items', json={'list': 'sort_out', 'text': 'Kleid'}).status_code, 422)
        self.assertEqual(self.britta.post('/api/lina/items', json={'list': 'sort_out', 'text': 'Kleid', 'destination': 'sell'}).status_code, 200)
        self.assertEqual(self.tasks(), [])

    def test_proactive_nursery_check_every_four_weeks(self):
        lina = self.app.state.lina
        monday = datetime(2026, 10, 5, 10, tzinfo=TZ)
        lina.periodic(monday.replace(hour=7))
        lina.periodic(monday + timedelta(days=5))  # Saturday
        self.assertEqual(self.tasks(), [])
        lina.periodic(monday)
        lina.periodic(monday + timedelta(hours=2))
        [task] = self.tasks('Wechselkleidung in der Krippe prüfen')
        self.assertEqual(task['owner'], 'britta')
        with self.app.state.db() as conn:
            conn.execute("UPDATE tasks SET state='done'")
        lina.periodic(monday + timedelta(days=14))
        self.assertEqual(len(self.tasks()), 1)
        lina.periodic(monday + timedelta(days=28))
        self.assertEqual(len(self.tasks()), 2)


if __name__ == '__main__':
    unittest.main()
