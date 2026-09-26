"""Read-only offline copy (E-13, V-01, O-10): what the iPhone may store."""
import json
from pathlib import Path
import tempfile
import time
import unittest

from fastapi.testclient import TestClient
from app import create_app


class OfflineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = create_app(Path(self.tmp.name) / 'family.sqlite', demo=True)
        self.client = TestClient(self.app, base_url='http://127.0.0.1:8765',
                                 headers={'Origin': 'http://127.0.0.1:8765', 'X-Family-Request': '1'})

    def tearDown(self):
        self.client.close()
        self.tmp.cleanup()

    def test_requires_login(self):
        self.assertEqual(self.client.get('/api/offline').status_code, 401)

    def test_contains_shopping_list_and_only_active_vouchers(self):
        shopping = {'start': '2026-10-03', 'days': [], 'duplicate_ids': {},
                    'shopping_recipes': [{'id': 'r1', 'name': 'Linsen-Dal', 'ingredient_ids': ['a']}],
                    'ingredients': [{'id': 'a', 'name': 'Rote Linsen', 'description': '200 g', 'is_owned': False}],
                    'additional': [{'id': 'o', 'name': 'Brot', 'is_owned': True}]}
        with self.app.state.db() as conn:
            conn.execute("INSERT OR REPLACE INTO meal_cache VALUES('shopping',?,?)", (json.dumps(shopping), 1790000000.0))
            for remaining, name in ((1260, 'a'), (0, 'b')):
                conn.execute('INSERT INTO vouchers(value_cents,remaining_cents,file,filename,size,uploaded_by,created,updated) '
                             "VALUES(2500,?,?,'x.pdf',1,'tobi',?,?)", (remaining, name * 32 + '.pdf', time.time(), time.time()))
        self.client.post('/api/login', json={'user': 'tobi'})
        data = self.client.get('/api/offline').json()
        self.assertEqual(data['shopping_updated'], 1790000000.0)
        self.assertEqual(data['recipes'], ['Linsen-Dal'])
        self.assertEqual(data['items'], [
            {'name': 'Rote Linsen', 'description': '200 g', 'owned': False, 'own': False},
            {'name': 'Brot', 'description': '', 'owned': True, 'own': True}])
        self.assertEqual([v['remaining_cents'] for v in data['vouchers']], [1260])
        self.assertNotIn('file', data['vouchers'][0])

    def test_offline_page_and_worker_are_served(self):
        self.assertIn('Einkauf offline', self.client.get('/static/offline.html').text)
        worker = self.client.get('/sw.js')
        self.assertEqual(worker.headers['service-worker-allowed'], '/')
        self.assertIn('fos-offline-v2', worker.text)


if __name__ == '__main__':
    unittest.main()
