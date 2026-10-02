"""Stay signed in (A-16): long sessions extended on use, sign out other devices."""
from pathlib import Path
import hashlib
import tempfile
import time
import unittest

from fastapi.testclient import TestClient

from app import create_app, SESSION_SECONDS

BASE = 'http://127.0.0.1:8765'


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = create_app(Path(self.tmp.name) / 'family.sqlite', demo=True)

    def tearDown(self):
        self.tmp.cleanup()

    def client(self, user='tobi'):
        client = TestClient(self.app, base_url=BASE, headers={'Origin': BASE, 'X-Family-Request': '1'})
        response = client.post('/api/login', json={'user': user})
        self.assertEqual(response.status_code, 200)
        return client, response

    def expires(self, client):
        digest = hashlib.sha256(client.cookies['fos_session'].encode()).hexdigest()
        with self.app.state.db() as conn:
            row = conn.execute('SELECT expires FROM sessions WHERE token=?', (digest,)).fetchone()
        return row[0] if row else None

    def set_expires(self, client, value):
        digest = hashlib.sha256(client.cookies['fos_session'].encode()).hexdigest()
        with self.app.state.db() as conn:
            conn.execute('UPDATE sessions SET expires=? WHERE token=?', (value, digest))

    def test_sign_in_lasts_a_year(self):
        client, response = self.client()
        self.assertIn(f'Max-Age={SESSION_SECONDS}', response.headers['set-cookie'])
        self.assertAlmostEqual(self.expires(client), time.time() + SESSION_SECONDS, delta=60)
        client.close()

    def test_use_extends_the_sign_in_at_most_daily(self):
        client, _ = self.client()
        month = time.strftime('%Y-%m')
        fresh = client.get('/api/state', params={'month': month})
        self.assertNotIn('set-cookie', fresh.headers)  # just signed in: nothing to extend
        self.set_expires(client, time.time() + 30 * 86400)
        renewed = client.get('/api/state', params={'month': month})
        self.assertEqual(renewed.status_code, 200)
        self.assertIn(f'Max-Age={SESSION_SECONDS}', renewed.headers['set-cookie'])
        self.assertAlmostEqual(self.expires(client), time.time() + SESSION_SECONDS, delta=60)
        client.close()

    def test_expired_sign_in_is_not_revived(self):
        client, _ = self.client()
        self.set_expires(client, time.time() - 1)
        response = client.get('/api/state', params={'month': time.strftime('%Y-%m')})
        self.assertEqual(response.status_code, 401)
        self.assertNotIn('set-cookie', response.headers)
        self.assertLess(self.expires(client), time.time())
        client.close()

    def test_sign_out_other_devices(self):
        phone, _ = self.client()
        laptop, _ = self.client()
        britta, _ = self.client('britta')
        month = time.strftime('%Y-%m')
        self.assertEqual(phone.get('/api/state', params={'month': month}).json()['sessions'], 2)
        self.assertEqual(phone.post('/api/sessions/revoke-others', json={}).json(), {'revoked': 1})
        self.assertEqual(laptop.get('/api/state', params={'month': month}).status_code, 401)
        self.assertEqual(phone.get('/api/state', params={'month': month}).status_code, 200)
        self.assertEqual(britta.get('/api/state', params={'month': month}).status_code, 200)  # other person untouched
        for client in (phone, laptop, britta):
            client.close()


if __name__ == '__main__':
    unittest.main()
