"""Shopping vouchers (G-01 to G-07): PDF on the NAS, remaining value, reminder."""
from datetime import datetime, timedelta
import os
from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient
from app import create_app
from backups import AutoBackup
from integrations import TZ
from vouchers import Vouchers

PDF = b'%PDF-1.4\n% Gutschein Test\n%%EOF\n'


class VoucherTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.app = create_app(self.dir / 'family.sqlite', demo=True)
        with self.app.state.db() as conn:
            conn.execute('DELETE FROM tasks')
        self.tobi = self.client('tobi')
        self.britta = self.client('britta')

    def tearDown(self):
        self.tobi.close()
        self.britta.close()
        self.tmp.cleanup()

    def client(self, user, login=True):
        client = TestClient(self.app, base_url='http://127.0.0.1:8765',
                            headers={'Origin': 'http://127.0.0.1:8765', 'X-Family-Request': '1'})
        if login:
            self.assertEqual(client.post('/api/login', json={'user': user}).status_code, 200)
        return client

    def upload(self, body=PDF, client=None, value=2500, **params):
        return (client or self.tobi).post('/api/vouchers', params={'value_cents': value, **params}, content=body,
                                          headers={'Content-Type': 'application/pdf'})

    def voucher(self, voucher_id):
        return next(v for v in self.tobi.get('/api/vouchers').json()['vouchers'] if v['id'] == voucher_id)

    def use(self, voucher_id, action, cents, version=None, client=None):
        version = self.voucher(voucher_id)['version'] if version is None else version
        return (client or self.britta).post(f'/api/vouchers/{voucher_id}/use', json={'action': action, 'cents': cents, 'version': version})

    def test_upload_stores_pdf_privately_and_serves_it_only_after_login(self):
        response = self.upload(note='Aktion 10fach', filename='Kaufland 25.pdf')
        self.assertEqual(response.status_code, 200, response.text)
        voucher_id = response.json()['id']
        files = list((self.dir / 'vouchers').iterdir())
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0].read_bytes(), PDF)
        self.assertEqual(os.stat(files[0]).st_mode & 0o777, 0o600)
        self.assertEqual(os.stat(self.dir / 'vouchers').st_mode & 0o777, 0o700)
        pdf = self.britta.get(f'/api/vouchers/{voucher_id}/pdf')
        self.assertEqual((pdf.status_code, pdf.headers['content-type'], pdf.content), (200, 'application/pdf', PDF))
        self.assertEqual(pdf.headers['cache-control'], 'no-store')
        anonymous = self.client('x', login=False)
        self.assertEqual(anonymous.get(f'/api/vouchers/{voucher_id}/pdf').status_code, 401)
        self.assertEqual(self.upload(client=anonymous).status_code, 401)
        self.assertEqual(len(list((self.dir / 'vouchers').iterdir())), 1)
        anonymous.close()
        overview = self.tobi.get('/api/vouchers').json()
        self.assertEqual(overview['available_cents'], 2500)
        self.assertNotIn('file', overview['vouchers'][0])

    def test_rejects_non_pdf_oversize_and_bad_values(self):
        self.assertEqual(self.upload(b'<html>').status_code, 422)
        self.assertEqual(self.upload(PDF + b'x' * (5 * 1024 * 1024)).status_code, 413)
        self.assertEqual(self.upload(value=0).status_code, 422)
        self.assertFalse((self.dir / 'vouchers').exists() and any((self.dir / 'vouchers').iterdir()))

    def test_partial_use_stays_active_and_full_use_goes_to_archive(self):
        voucher_id = self.upload(value=5000).json()['id']
        self.assertEqual(self.use(voucher_id, 'spend', 3210).status_code, 200)
        v = self.voucher(voucher_id)
        self.assertEqual((v['remaining_cents'], v['status']), (1790, 'partial'))
        self.assertEqual(self.use(voucher_id, 'spend', 2000).status_code, 422)
        self.assertEqual(self.use(voucher_id, 'set', 6000).status_code, 422)
        self.assertEqual(self.use(voucher_id, 'spend', 1790).status_code, 200)
        v = self.voucher(voucher_id)
        self.assertEqual((v['remaining_cents'], v['status']), (0, 'used'))
        self.assertEqual([(u['before_cents'], u['after_cents']) for u in v['uses']], [(1790, 0), (5000, 1790)])
        self.assertEqual(self.tobi.get('/api/vouchers').json()['available_cents'], 0)
        # Correction after a wrong entry.
        self.assertEqual(self.use(voucher_id, 'set', 500).status_code, 200)
        self.assertEqual(self.voucher(voucher_id)['status'], 'partial')

    def test_stale_version_is_rejected(self):
        voucher_id = self.upload().json()['id']
        old = self.voucher(voucher_id)['version']
        self.use(voucher_id, 'spend', 100)
        self.assertEqual(self.use(voucher_id, 'spend', 100, version=old).status_code, 409)

    def test_thursday_reminder_once_and_closed_by_upload(self):
        vouchers = Vouchers(self.app.state.db, self.dir, demo=False)
        thursday = datetime.now(TZ).replace(hour=10, minute=0)
        while thursday.weekday() != 3:
            thursday += timedelta(days=1)
        vouchers.periodic(thursday.replace(hour=8))
        vouchers.periodic(thursday - timedelta(days=1))
        vouchers.periodic(thursday.replace(hour=17))
        with self.app.state.db() as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM tasks').fetchone()[0], 0)
        vouchers.periodic(thursday)
        vouchers.periodic(thursday + timedelta(hours=1))
        with self.app.state.db() as conn:
            rows = conn.execute('SELECT owner,title,state,due FROM tasks').fetchall()
            conn.execute('UPDATE metadata SET key=? WHERE key=?', (f'voucher_task:{datetime.now(TZ).date()}', f'voucher_task:{thursday.date()}'))
        self.assertEqual([tuple(r)[:3] for r in rows], [('tobi', 'Gutscheine vorbereiten', 'open')])
        self.assertIn('T16:00', rows[0]['due'])
        self.upload()
        with self.app.state.db() as conn:
            self.assertEqual(conn.execute('SELECT state FROM tasks').fetchone()[0], 'done')

    def test_reminder_can_be_switched_off(self):
        self.assertEqual(self.tobi.post('/api/vouchers/settings', json={'reminder': False}).json()['reminder'], False)
        vouchers = Vouchers(self.app.state.db, self.dir, demo=False)
        thursday = datetime(2026, 10, 1, 10, tzinfo=TZ)
        vouchers.periodic(thursday)
        with self.app.state.db() as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM tasks').fetchone()[0], 0)

    def test_daily_backup_contains_voucher_pdfs(self):
        self.upload()
        backup = AutoBackup(self.app.state.db, self.dir / 'family.sqlite', self.dir, demo=False)
        backup.periodic(datetime(2026, 10, 1, 4, tzinfo=TZ))
        [folder] = backup.folders()
        copies = list((folder / 'vouchers').iterdir())
        self.assertEqual([c.read_bytes() for c in copies], [PDF])


if __name__ == '__main__':
    unittest.main()
