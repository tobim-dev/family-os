from datetime import date, datetime, timedelta
from pathlib import Path
import sqlite3
import tempfile
import unittest
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from app import create_app
from migrations import migrate, statements, BASELINE, MIGRATIONS
from nanny import amount_cents

TZ = ZoneInfo('Europe/Berlin')


class NannyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'family.sqlite'
        self.app = create_app(self.path, demo=True)
        with self.app.state.db() as conn:
            conn.execute('DELETE FROM nanny_shifts')
            conn.execute('DELETE FROM tasks')
        self.tobi = self.client('tobi')
        self.britta = self.client('britta')
        self.today = datetime.now(TZ).date()
        self.day = self.today + timedelta(days=3)
        self.last_month = (self.today.replace(day=1) - timedelta(days=1)).strftime('%Y-%m')

    def tearDown(self):
        self.tobi.close()
        self.britta.close()
        self.tmp.cleanup()

    def client(self, user):
        client = TestClient(self.app, base_url='http://127.0.0.1:8765', headers={'Origin': 'http://127.0.0.1:8765', 'X-Family-Request': '1'})
        self.assertEqual(client.post('/api/login', json={'user': user}).status_code, 200)
        return client

    def create(self, client=None, **data):
        body = {'day': str(self.day), 'start': '16:00', 'end': '18:00'}
        body.update(data)
        return (client or self.britta).post('/api/nanny/shifts', json=body)

    def overview(self, month=None):
        return self.tobi.get('/api/nanny', params={'month': month or str(self.day)[:7]}).json()

    def shift(self, shift_id, month=None):
        return next(s for s in self.overview(month)['shifts'] if s['id'] == shift_id)

    def move(self, shift_id, action, client=None, **extra):
        row = self.shift(shift_id)
        return (client or self.tobi).post('/api/nanny/transition', json={'ids': [shift_id], 'versions': [row['version']], 'action': action, **extra})

    def tasks(self, owner='tobi'):
        with self.app.state.db() as conn:
            return [dict(r) for r in conn.execute("SELECT * FROM tasks WHERE owner=? AND state='open'", (owner,))]

    def past_shift(self, month, day=10, state='confirmed', start='16:00', end='18:00', **columns):
        with self.app.state.db() as conn:
            cursor = conn.execute('INSERT INTO nanny_shifts(day,start,end,state,creator,created,updated) VALUES(?,?,?,?,?,?,?)',
                                  (f'{month}-{day:02d}', start, end, state, 'tobi', 'x', 'x'))
            for key, value in columns.items():
                conn.execute(f'UPDATE nanny_shifts SET {key}=? WHERE id=?', (value, cursor.lastrowid))
            return cursor.lastrowid

    def test_wish_creates_task_for_tobi_and_notifies_partner(self):
        response = self.create()
        self.assertEqual(response.status_code, 200)
        [task] = self.tasks()
        self.assertEqual(task['title'], 'Nanny anfragen')
        self.assertTrue(task['details'].startswith(str(self.day)[:7] + ': 1 Wunsch'))
        with self.app.state.db() as conn:
            self.assertTrue(conn.execute("SELECT 1 FROM notifications WHERE owner='tobi' AND dedupe LIKE 'nanny-wish:%'").fetchone())

    def month_days(self, count):
        # Weekdays from tomorrow on within one month; move to next month if needed.
        day = self.today + timedelta(days=1)
        if (day + timedelta(days=count * 2)).month != day.month:
            day = (day.replace(day=1) + timedelta(days=32)).replace(day=1)
        days = []
        while len(days) < count:
            if day.weekday() < 5:
                days.append(str(day))
            day += timedelta(days=1)
        return days

    def test_month_is_planned_in_one_step_with_one_task_and_notice(self):
        days = self.month_days(4)
        response = self.britta.post('/api/nanny/shifts/batch', json={'days': days})
        self.assertEqual(response.status_code, 200)
        ids = response.json()['ids']
        self.assertEqual(len(ids), 4)
        [task] = self.tasks()
        self.assertIn('4 Wünsche', task['details'])
        with self.app.state.db() as conn:
            notices = conn.execute("SELECT body FROM notifications WHERE owner='tobi' AND dedupe LIKE 'nanny-wishes:%'").fetchall()
        self.assertEqual(len(notices), 1)
        # Requesting part of the month keeps the task with the remaining count.
        month = days[0][:7]
        shifts = self.overview(month)['shifts']
        first = shifts[0]
        self.tobi.post('/api/nanny/transition', json={'ids': [first['id']], 'versions': [first['version']], 'action': 'request'})
        [task] = self.tasks()
        self.assertIn('3 Wünsche', task['details'])
        rest = [s for s in self.overview(month)['shifts'] if s['state'] == 'wish']
        self.tobi.post('/api/nanny/transition', json={'ids': [s['id'] for s in rest], 'versions': [s['version'] for s in rest], 'action': 'request'})
        self.assertEqual(self.tasks(), [])

    def test_month_batch_is_atomic_and_single_month(self):
        days = self.month_days(3)
        self.create(day=days[1])
        response = self.britta.post('/api/nanny/shifts/batch', json={'days': days})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(len(self.overview(days[0][:7])['shifts']), 1)
        self.assertEqual(self.britta.post('/api/nanny/shifts/batch', json={'days': [days[0], days[0]]}).status_code, 422)
        other_month = str((date.fromisoformat(days[0]).replace(day=1) + timedelta(days=40)))
        self.assertEqual(self.britta.post('/api/nanny/shifts/batch', json={'days': [days[0], other_month]}).status_code, 422)

    def test_mixed_answer_is_recorded_atomically(self):
        days = self.month_days(3)
        self.britta.post('/api/nanny/shifts/batch', json={'days': days})
        month = days[0][:7]
        shifts = self.overview(month)['shifts']
        self.tobi.post('/api/nanny/transition', json={'ids': [s['id'] for s in shifts], 'versions': [s['version'] for s in shifts], 'action': 'request'})
        shifts = self.overview(month)['shifts']
        items = [{'id': shifts[0]['id'], 'version': shifts[0]['version'], 'answer': 'confirm'},
                 {'id': shifts[1]['id'], 'version': shifts[1]['version'] - 1, 'answer': 'decline'}]
        self.assertEqual(self.tobi.post('/api/nanny/answer', json={'items': items}).status_code, 409)
        self.assertEqual({s['state'] for s in self.overview(month)['shifts']}, {'requested'})
        items[1]['version'] += 1
        response = self.tobi.post('/api/nanny/answer', json={'items': items})
        self.assertEqual(response.json(), {'confirmed': 1, 'declined': 1})
        self.assertEqual([s['state'] for s in self.overview(month)['shifts']], ['confirmed', 'declined', 'requested'])
        with self.app.state.db() as conn:
            body = conn.execute("SELECT body FROM notifications WHERE owner='britta' AND dedupe LIKE 'nanny-answer:%'").fetchone()[0]
        self.assertIn('Kann nicht', body)

    def test_invalid_and_overlapping_wishes_are_rejected(self):
        self.assertEqual(self.create(end='15:00').status_code, 422)
        self.assertEqual(self.create(day=str(self.today - timedelta(days=1))).status_code, 422)
        self.assertEqual(self.create().status_code, 200)
        self.assertEqual(self.create(start='17:00', end='19:00').status_code, 409)
        self.assertEqual(self.create(start='18:00', end='19:00').status_code, 200)

    def test_lifecycle_request_confirm_and_state_view(self):
        shift_id = self.create().json()['id']
        self.assertEqual(self.move(shift_id, 'decline').status_code, 409)
        self.assertEqual(self.move(shift_id, 'request').status_code, 200)
        self.assertEqual(self.tasks(), [])
        self.assertEqual(self.move(shift_id, 'confirm', self.britta).status_code, 200)
        self.assertEqual(self.shift(shift_id)['state'], 'confirmed')
        state = self.tobi.get('/api/state', params={'month': str(self.day)[:7]}).json()
        self.assertEqual([s['id'] for s in state['nanny']], [shift_id])

    def test_stale_version_is_rejected(self):
        shift_id = self.create().json()['id']
        version = self.shift(shift_id)['version']
        self.assertEqual(self.move(shift_id, 'request').status_code, 200)
        response = self.tobi.post('/api/nanny/transition', json={'ids': [shift_id], 'versions': [version], 'action': 'confirm'})
        self.assertEqual(response.status_code, 409)

    def test_only_wishes_can_be_edited(self):
        shift_id = self.create().json()['id']
        row = self.shift(shift_id)
        edit = {'day': str(self.day), 'start': '15:30', 'end': '18:00', 'version': row['version']}
        self.assertEqual(self.tobi.post(f'/api/nanny/shifts/{shift_id}', json=edit).status_code, 200)
        self.assertEqual(self.shift(shift_id)['start'], '15:30')
        self.move(shift_id, 'request')
        edit['version'] = self.shift(shift_id)['version']
        self.assertEqual(self.tobi.post(f'/api/nanny/shifts/{shift_id}', json=edit).status_code, 409)

    def test_cancelling_confirmed_shift_requires_payment_decision(self):
        shift_id = self.create().json()['id']
        self.move(shift_id, 'confirm')
        self.assertEqual(self.move(shift_id, 'cancel').status_code, 422)
        self.assertEqual(self.move(shift_id, 'cancel', paid=True).status_code, 200)
        self.assertEqual(self.shift(shift_id)['paid_cancel'], 1)
        wish = self.create(day=str(self.day + timedelta(days=1))).json()['id']
        self.assertEqual(self.move(wish, 'cancel').status_code, 200)
        self.assertIsNone(self.shift(wish)['paid_cancel'])

    def test_statement_counts_planned_corrected_and_paid_cancellations(self):
        month = self.last_month
        self.past_shift(month, 3)                                                    # 120 min planned
        self.past_shift(month, 4, actual_start='16:10', actual_end='18:25', correction_note='länger')  # 135 min
        self.past_shift(month, 5, state='cancelled', paid_cancel=1)                  # 120 min paid
        self.past_shift(month, 6, state='cancelled', paid_cancel=0)                  # not billed
        self.past_shift(month, 7, state='declined')                                  # not billed
        statement = self.overview(month)['statement']
        self.assertEqual(statement['minutes'], 375)
        self.assertEqual(statement['amount_cents'], 12500)
        self.assertEqual(len(statement['lines']), 3)
        self.assertTrue(statement['month_over'])

    def test_correction_rules(self):
        shift_id = self.create().json()['id']
        self.move(shift_id, 'confirm')
        body = {'version': self.shift(shift_id)['version'], 'actual_start': '16:00', 'actual_end': '18:30', 'note': 'länger'}
        self.assertEqual(self.tobi.post(f'/api/nanny/shifts/{shift_id}/correct', json=body).status_code, 409)  # future
        past = self.past_shift(self.today.strftime('%Y-%m'), self.today.day)
        body['version'] = 1
        self.assertEqual(self.tobi.post(f'/api/nanny/shifts/{past}/correct', json={**body, 'note': ''}).status_code, 422)
        self.assertEqual(self.tobi.post(f'/api/nanny/shifts/{past}/correct', json={**body, 'actual_end': '15:00'}).status_code, 422)
        self.assertEqual(self.tobi.post(f'/api/nanny/shifts/{past}/correct', json=body).status_code, 200)
        reset = {'version': 2, 'actual_start': None, 'actual_end': None, 'note': ''}
        self.assertEqual(self.tobi.post(f'/api/nanny/shifts/{past}/correct', json=reset).status_code, 200)

    def test_close_freeze_reopen_and_pay(self):
        month = self.last_month
        open_request = self.past_shift(month, 3, state='requested')
        self.past_shift(month, 4)
        url = f'/api/nanny/statement/{month}'
        self.assertEqual(self.tobi.post(url, json={'action': 'close'}).status_code, 409)  # unresolved request
        with self.app.state.db() as conn:
            conn.execute("UPDATE nanny_shifts SET state='declined' WHERE id=?", (open_request,))
        self.assertEqual(self.tobi.post(url, json={'action': 'paid'}).status_code, 409)
        self.assertEqual(self.tobi.post(url, json={'action': 'close'}).status_code, 200)
        [transfer] = [t for t in self.tasks() if t['title'] == 'Nanny-Lohn überweisen']
        self.assertIn('40,00 EUR', transfer['details'])
        # Frozen: rate changes do not alter a closed month, shifts are locked.
        self.tobi.post('/api/nanny/settings', json={'name': 'Mia', 'phone': '', 'rate_cents': 2500})
        self.assertEqual(self.overview(month)['statement']['amount_cents'], 4000)
        locked = self.past_shift(month, 12, state='requested')
        self.assertEqual(self.move_raw(locked, 'decline').status_code, 409)
        self.assertEqual(self.tobi.post(url, json={'action': 'reopen'}).status_code, 200)
        self.assertEqual(self.tasks(), [])
        self.assertEqual(self.move_raw(locked, 'decline').status_code, 200)
        self.assertEqual(self.tobi.post(url, json={'action': 'close'}).status_code, 200)
        self.assertEqual(self.overview(month)['statement']['amount_cents'], 5000)
        self.assertEqual(self.tobi.post(url, json={'action': 'paid'}).status_code, 200)
        self.assertEqual(self.overview(month)['statement']['state'], 'paid')
        self.assertEqual(self.tobi.post(url, json={'action': 'reopen'}).status_code, 409)

    def move_raw(self, shift_id, action):
        with self.app.state.db() as conn:
            version = conn.execute('SELECT version FROM nanny_shifts WHERE id=?', (shift_id,)).fetchone()[0]
        return self.tobi.post('/api/nanny/transition', json={'ids': [shift_id], 'versions': [version], 'action': action})

    def test_current_month_cannot_be_closed(self):
        response = self.tobi.post('/api/nanny/statement/' + self.today.strftime('%Y-%m'), json={'action': 'close'})
        self.assertEqual(response.status_code, 409)

    def test_settings_validation(self):
        self.assertEqual(self.tobi.post('/api/nanny/settings', json={'name': 'Mia', 'phone': '+49 170 1234567', 'rate_cents': 2000}).status_code, 200)
        self.assertEqual(self.overview()['settings']['phone'], '+491701234567')
        self.assertEqual(self.tobi.post('/api/nanny/settings', json={'name': 'Mia', 'phone': 'abc', 'rate_cents': 2000}).status_code, 422)
        self.assertEqual(self.tobi.post('/api/nanny/settings', json={'name': 'Mia', 'phone': '', 'rate_cents': 0}).status_code, 422)

    def test_monthly_billing_task_created_once(self):
        month = self.last_month
        self.past_shift(month, 4)
        nanny = self.app.state.nanny
        instant = datetime.combine(self.today.replace(day=1), datetime.min.time(), TZ).replace(hour=9, minute=5)
        nanny.periodic(instant.replace(hour=8))
        self.assertEqual(self.tasks(), [])
        nanny.periodic(instant)
        nanny.periodic(instant + timedelta(hours=2))
        [task] = self.tasks()
        self.assertEqual(task['title'], 'Nanny-Abrechnung')
        self.assertTrue(task['details'].startswith(month))
        self.assertEqual(self.tobi.post(f'/api/nanny/statement/{month}', json={'action': 'close'}).status_code, 200)
        self.assertEqual([t['title'] for t in self.tasks()], ['Nanny-Lohn überweisen'])

    def test_rounding(self):
        self.assertEqual(amount_cents(125, 2000), 4167)
        self.assertEqual(amount_cents(1, 2000), 33)
        self.assertEqual(amount_cents(0, 2000), 0)


class NannyMigrationTests(unittest.TestCase):
    def test_existing_production_data_survives_nanny_migration(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'family.sqlite'
            with sqlite3.connect(path) as conn:
                for statement in statements(BASELINE):
                    conn.execute(statement)
                conn.execute("INSERT INTO users(id,password,totp) VALUES('tobi','x','y')")
                conn.execute("INSERT INTO tasks(owner,title,details,due,created) VALUES('tobi','Arbeitskalender aktualisieren','d','2026-10-01','x')")
                conn.execute('PRAGMA user_version=1')
            conn.close()
            self.assertEqual(migrate(path, MIGRATIONS[:1]), [2])  # the migration under test only
            with sqlite3.connect(path) as conn:
                self.assertEqual(conn.execute('SELECT title,nanny_shift_id FROM tasks').fetchall(), [('Arbeitskalender aktualisieren', None)])
            conn.close()
            self.assertEqual(len(list((Path(tmp) / 'backups').iterdir())), 1)


if __name__ == '__main__':
    unittest.main()
