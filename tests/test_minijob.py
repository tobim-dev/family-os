"""Minijob im Privathaushalt: payout and levies (N-12)."""
from datetime import datetime, timedelta
from pathlib import Path
import sqlite3
import tempfile
import unittest

from fastapi.testclient import TestClient
from app import create_app
from integrations import TZ
import minijob
import migrations

CONFIG = {**minijob.DEFAULTS}


class ComputeTests(unittest.TestCase):
    def test_rates_2026_exempt_and_tax_by_family(self):
        result = minijob.compute(20000, CONFIG)  # 200,00 €
        self.assertEqual({l['key']: l['cents'] for l in result['levies']},
                         {'kv': 1000, 'rv': 1000, 'tax': 400, 'u1': 160, 'u2': 44, 'uv': 320})
        self.assertEqual(result['payout'], 20000)          # full wage to the nanny
        self.assertEqual(result['collected'], 2924)        # 14,62 %
        self.assertEqual(result['family_total'], 22924)
        self.assertEqual(result['deductions'], [])
        self.assertFalse(result['over_limit'])

    def test_rounding_half_up_per_component(self):
        result = minijob.compute(17333, CONFIG)
        self.assertEqual([l['cents'] for l in result['levies']], [867, 867, 347, 139, 38, 277])

    def test_without_exemption_and_tax_by_nanny(self):
        config = {**CONFIG, 'rv_exempt': False, 'tax_by_employer': False}
        result = minijob.compute(20000, config)
        self.assertEqual([d['cents'] for d in result['deductions']], [2720, 400])  # 13,6 % and 2 %
        self.assertEqual(result['payout'], 20000 - 2720 - 400)
        self.assertEqual(result['collected'], 2924 + 2720)
        self.assertEqual(result['family_total'], result['payout'] + result['collected'])
        self.assertEqual(result['employer_levies'], 2924 - 400)

    def test_limit_and_half_years(self):
        self.assertTrue(minijob.compute(60301, CONFIG)['over_limit'])
        self.assertFalse(minijob.compute(60300, CONFIG)['over_limit'])
        self.assertEqual(minijob.half_year('2026-03'), (['2026-01', '2026-02', '2026-03', '2026-04', '2026-05', '2026-06'], 'im Juli 2026'))
        self.assertEqual(minijob.half_year('2026-11')[1], 'im Januar 2027')


class StatementTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = create_app(Path(self.tmp.name) / 'family.sqlite', demo=True)
        with self.app.state.db() as conn:
            conn.execute('DELETE FROM nanny_shifts')
            conn.execute('DELETE FROM tasks')
        self.tobi = TestClient(self.app, base_url='http://127.0.0.1:8765', headers={'Origin': 'http://127.0.0.1:8765', 'X-Family-Request': '1'})
        self.tobi.post('/api/login', json={'user': 'tobi'})
        today = datetime.now(TZ).date()
        self.month = (today.replace(day=1) - timedelta(days=1)).strftime('%Y-%m')

    def tearDown(self):
        self.tobi.close()
        self.tmp.cleanup()

    def shift(self, day, start='16:00', end='18:00'):
        with self.app.state.db() as conn:
            conn.execute("INSERT INTO nanny_shifts(day,start,end,state,creator,created,updated) VALUES(?,?,?,'confirmed','tobi','x','x')",
                         (f'{self.month}-{day:02d}', start, end))

    def statement(self):
        return self.tobi.get('/api/nanny', params={'month': self.month}).json()['statement']

    def test_open_month_shows_payout_levies_and_half_year(self):
        for day in (6, 13, 20, 27):
            self.shift(day)
        statement = self.statement()  # 8 h × 20 € = 160 €
        self.assertEqual(statement['amount_cents'], 16000)
        self.assertEqual(statement['minijob']['payout'], 16000)
        self.assertEqual(statement['minijob']['collected'], 2339)  # 14,62 % of 160 € = 23,392
        self.assertEqual(statement['half_year']['gross'], 16000)
        self.assertIn(statement['half_year']['collection'], ('im Juli ' + self.month[:4], 'im Januar ' + str(int(self.month[:4]) + 1)))

    def test_closing_freezes_levies_and_task_names_the_payout(self):
        self.shift(6)
        self.assertEqual(self.tobi.post(f'/api/nanny/statement/{self.month}', json={'action': 'close'}).status_code, 200)
        with self.app.state.db() as conn:
            task = conn.execute("SELECT details FROM tasks WHERE title='Nanny-Lohn überweisen'").fetchone()[0]
        self.assertIn('40,00 EUR', task)
        before = self.statement()['minijob']
        rates = {**minijob.DEFAULTS['rates'], 'u1': 110}
        self.assertEqual(self.tobi.post('/api/nanny/levies', json={'rates': rates}).status_code, 200)
        self.assertEqual(self.statement()['minijob'], before)  # closed month keeps its values
        self.tobi.post(f'/api/nanny/statement/{self.month}', json={'action': 'reopen'})
        self.assertEqual(self.statement()['minijob']['levies'][3]['rate'], 110)

    def test_levy_settings_are_validated(self):
        self.assertEqual(self.tobi.post('/api/nanny/levies', json={'rates': {'kv': 500}}).status_code, 422)
        bad = {**minijob.DEFAULTS['rates'], 'kv': 5000}
        self.assertEqual(self.tobi.post('/api/nanny/levies', json={'rates': bad}).status_code, 422)


class MigrationTests(unittest.TestCase):
    def test_existing_statements_survive_and_are_estimated(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'family.sqlite'
            migrations.migrate(path, migrations.MIGRATIONS[:5])  # production state before version 7
            with sqlite3.connect(path) as conn:
                conn.execute("INSERT INTO users(id,password,totp) VALUES('tobi','x','y')")
                conn.execute("INSERT INTO metadata VALUES('mode','demo')")
                conn.execute("INSERT INTO nanny_statements(month,rate_cents,minutes,amount_cents,lines,closed_by,closed) "
                             "VALUES('2026-08',2000,480,16000,'[]','tobi','2026-09-01')")
            conn.close()
            self.assertEqual(migrations.migrate(path), [7])
            app = create_app(path, demo=True)
            with app.state.db() as conn:
                row = conn.execute("SELECT amount_cents,levies FROM nanny_statements").fetchone()
                self.assertEqual((row[0], row[1]), (16000, None))
                statement = app.state.nanny.statement(conn, '2026-08')
            self.assertTrue(statement['minijob']['estimated'])
            self.assertEqual(statement['minijob']['payout'], 16000)


if __name__ == '__main__':
    unittest.main()
