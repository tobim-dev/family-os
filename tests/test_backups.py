"""Automatic daily backup (backups.py)."""
from datetime import datetime, timedelta
import os
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import patch

from app import create_app
from backups import AutoBackup
from integrations import TZ


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name)
        self.app = create_app(self.path / 'family.sqlite', demo=True)
        self.db = self.app.state.db
        with self.db() as conn:
            conn.execute("INSERT INTO audit(actor,action,details,created) VALUES('tobi','Test','x','now')")
        (self.path / 'integration.key').write_bytes(b'test-key')
        (self.path / 'push-private.pem').write_bytes(b'test-pem')
        self.backup = AutoBackup(self.db, self.path / 'family.sqlite', self.path, demo=False)

    def tearDown(self):
        self.tmp.cleanup()

    def at(self, day, hour):
        return datetime(2026, 10, day, hour, 5, tzinfo=TZ)

    def status(self):
        with self.db() as conn:
            return self.backup.status(conn)

    def test_creates_one_consistent_backup_per_day_after_hour(self):
        self.backup.periodic(self.at(1, 2))
        self.assertEqual(self.backup.folders(), [])
        self.backup.periodic(self.at(1, 3))
        self.backup.periodic(self.at(1, 22))
        folders = self.backup.folders()
        self.assertEqual([f.name for f in folders], ['2026-10-01'])
        copy = folders[0] / 'family.sqlite'
        with sqlite3.connect(copy) as conn:
            self.assertEqual(conn.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
            self.assertEqual(conn.execute("SELECT details FROM audit WHERE action='Test'").fetchone()[0], 'x')
        self.assertEqual((folders[0] / 'keys' / 'integration.key').read_bytes(), b'test-key')
        self.assertEqual(os.stat(copy).st_mode & 0o777, 0o600)
        self.assertEqual(os.stat(folders[0]).st_mode & 0o777, 0o700)
        status = self.status()
        self.assertTrue(status['last_ok'].startswith('2026-10-01T03'))
        self.assertIsNone(status['error'])

    def test_missed_night_is_caught_up_and_old_folders_pruned(self):
        self.backup.keep = 3
        for day in range(1, 7):
            self.backup.periodic(self.at(day, 14))
        self.assertEqual([f.name for f in self.backup.folders()], ['2026-10-04', '2026-10-05', '2026-10-06'])

    def test_foreign_folders_are_never_removed(self):
        self.backup.keep = 1
        self.backup.target.mkdir(parents=True)
        (self.backup.target / 'eigene-kopie').mkdir()
        for day in (1, 2):
            self.backup.periodic(self.at(day, 4))
        self.assertTrue((self.backup.target / 'eigene-kopie').exists())

    def test_failure_is_reported_once_and_retried_after_an_hour(self):
        self.backup.target = self.path / 'blocked'
        self.backup.target.write_text('not a folder')
        self.backup.periodic(self.at(1, 3))
        status = self.status()
        self.assertIsNone(status['last_ok'])
        self.assertIn('nicht beschreibbar', status['error'])
        self.backup.periodic(self.at(1, 3))
        with self.db() as conn:
            notices = conn.execute("SELECT COUNT(*) FROM notifications WHERE dedupe LIKE 'backup-failed:%'").fetchone()[0]
        self.assertEqual(notices, 1)
        # Fixed target: the retry waits one hour, then succeeds and clears the error.
        self.backup.target = self.path / 'auto'
        self.backup.periodic(self.at(1, 4))
        self.assertIsNone(self.status()['last_ok'])
        with patch('backups.time.time', return_value=time.time() + 3601):
            self.backup.periodic(self.at(1, 4))
        status = self.status()
        self.assertIsNotNone(status['last_ok'])
        self.assertIsNone(status['error'])

    def test_failed_integrity_check_leaves_no_folder(self):
        with patch.object(AutoBackup, 'verify', return_value='row 3 missing from index'):
            self.backup.periodic(self.at(1, 3))
        self.assertEqual(self.backup.folders(), [])
        self.assertFalse(any(self.backup.target.glob('.*.partial')))
        self.assertIn('Integritätsprüfung', self.status()['error'])

    def test_demo_never_writes_backups(self):
        demo = AutoBackup(self.db, self.path / 'family.sqlite', self.path, demo=True)
        demo.periodic(self.at(1, 5))
        self.assertFalse((self.path / 'backups' / 'auto').exists())

    def test_status_is_part_of_connections(self):
        from fastapi.testclient import TestClient
        client = TestClient(self.app, base_url='http://127.0.0.1:8765', headers={'Origin': 'http://127.0.0.1:8765', 'X-Family-Request': '1'})
        client.post('/api/login', json={'user': 'britta'})
        backup = client.get('/api/connections').json()['backup']
        self.assertFalse(backup['enabled'])
        client.close()


if __name__ == '__main__':
    unittest.main()
