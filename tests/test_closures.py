"""Days without nursery care (B-05, O-02): confirmation, suspension, draft, calendar."""
from datetime import date, datetime, timedelta
from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient
from app import create_app
from integrations import TZ


class ClosureTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = create_app(Path(self.tmp.name) / 'family.sqlite', demo=True)
        with self.app.state.db() as conn:
            for table in ('work_calendar_items', 'tasks', 'proposals', 'issues', 'appointments', 'audit', 'nanny_shifts', 'calendar_targets'):
                conn.execute('DELETE FROM ' + table)
        self.tobi = self.client('tobi')
        self.britta = self.client('britta')
        # A Monday far enough in the future, with Tuesday and Wednesday.
        self.monday = date.today() + timedelta(days=14)
        while self.monday.weekday() != 0:
            self.monday += timedelta(days=1)
        self.days = [str(self.monday + timedelta(days=i)) for i in range(3)]
        with self.app.state.db() as conn:
            for i, day in enumerate(self.days):
                conn.execute("INSERT INTO appointments(day,kind,owner,start,end,version) VALUES(?,'bring',?,'07:45','08:45',1)",
                             (day, 'tobi' if i % 2 == 0 else 'britta'))
                conn.execute("INSERT INTO appointments(day,kind,owner,start,end,version) VALUES(?,'pickup','britta','15:30','17:30',1)", (day,))

    def tearDown(self):
        self.tobi.close()
        self.britta.close()
        self.tmp.cleanup()

    def client(self, user):
        client = TestClient(self.app, base_url='http://127.0.0.1:8765',
                            headers={'Origin': 'http://127.0.0.1:8765', 'X-Family-Request': '1'})
        self.assertEqual(client.post('/api/login', json={'user': user}).status_code, 200)
        return client

    def enter(self, client=None, start=None, end=None, kind='closed', **extra):
        body = {'start': start or self.days[1], 'end': end or self.days[1], 'kind': kind, **extra}
        return (client or self.tobi).post('/api/closures', json=body)

    def decide(self, batch, action, client=None, **extra):
        return (client or self.britta).post(f'/api/closures/{batch}/decision', json={'action': action, **extra})

    def rows(self, sql, *args):
        with self.app.state.db() as conn:
            return [tuple(r) for r in conn.execute(sql, args)]

    def calendar_keys(self):
        self.app.state.integrations.reconcile()
        return {r[0] for r in self.rows("SELECT key FROM calendar_targets WHERE desired IS NOT NULL")}

    def test_needs_confirmation_by_the_other_person(self):
        before = self.calendar_keys()
        batch = self.enter().json()['batch']
        self.assertEqual(self.calendar_keys(), before)  # pending: plan unchanged
        self.assertEqual(self.decide(batch, 'confirm', self.tobi).status_code, 403)
        self.assertEqual(len(self.rows("SELECT 1 FROM notifications WHERE owner='britta' AND dedupe LIKE 'closure:%'")), 1)
        self.assertEqual(self.decide(batch, 'confirm').status_code, 200)
        self.assertEqual(self.rows('SELECT state FROM day_closures'), [('confirmed',)])
        # Both parents with assignments that day get a work-calendar task.
        tasks = self.rows("SELECT owner,details FROM tasks WHERE title='Arbeitskalender aktualisieren' ORDER BY owner")
        self.assertEqual([t[0] for t in tasks], ['britta'])
        self.assertIn('Entfernen:', tasks[0][1])
        self.assertEqual(len(self.calendar_keys()), len(before) - 2)

    def test_lifting_restores_the_confirmed_plan(self):
        batch = self.enter(start=self.days[0], end=self.days[2]).json()['batch']
        self.decide(batch, 'confirm')
        self.assertEqual(self.calendar_keys(), set())
        self.assertEqual(self.decide(batch, 'lift', self.tobi).status_code, 200)
        self.assertEqual(len(self.calendar_keys()), 6)
        self.assertEqual(self.rows('SELECT owner FROM appointments WHERE day=? AND kind=?', self.days[0], 'bring'), [('tobi',)])
        # Nobody had removed the blocks yet: removal and re-entry cancel out (B-18).
        self.assertEqual(self.rows("SELECT owner FROM tasks WHERE state='open' AND title='Arbeitskalender aktualisieren'"), [])

    def test_lifting_after_removal_asks_to_enter_again(self):
        batch = self.enter(start=self.days[0], end=self.days[0]).json()['batch']
        self.decide(batch, 'confirm')
        for client in (self.tobi, self.britta):
            [task] = [t for t in client.get('/api/state', params={'month': self.days[0][:7]}).json()['tasks']
                      if t['state'] == 'open' and t['title'] == 'Arbeitskalender aktualisieren' and t['owner'] in ('tobi', 'britta')
                      and t['owner'] == ('tobi' if client is self.tobi else 'britta')]
            self.assertEqual(client.post(f"/api/tasks/{task['id']}/complete", json={}).status_code, 200)
        self.decide(batch, 'lift', self.tobi)
        restored = self.rows("SELECT owner,details FROM tasks WHERE state='open' AND title='Arbeitskalender aktualisieren' ORDER BY owner")
        self.assertEqual([r[0] for r in restored], ['britta', 'tobi'])
        self.assertTrue(all(r[1].startswith('Eintragen:') for r in restored))

    def test_reject_and_withdraw_leave_the_plan(self):
        batch = self.enter().json()['batch']
        self.assertEqual(self.decide(batch, 'withdraw').status_code, 403)
        self.assertEqual(self.decide(batch, 'reject').status_code, 200)
        self.assertEqual(self.rows('SELECT * FROM day_closures'), [])
        batch = self.enter(kind='sick').json()['batch']
        self.assertEqual(self.decide(batch, 'withdraw', self.tobi).status_code, 200)
        self.assertEqual(self.rows("SELECT * FROM tasks"), [])

    def test_joint_mode_applies_directly(self):
        mode = self.tobi.post('/api/planning/start', json={}).json()['id']
        self.assertEqual(self.enter(kind='vacation', planning_session=mode).status_code, 200)
        self.assertEqual(self.rows('SELECT state,kind FROM day_closures'), [('confirmed', 'vacation')])

    def test_only_weekdays_overlaps_and_limits(self):
        saturday = self.monday - timedelta(days=2)
        response = self.enter(start=str(saturday), end=str(self.monday + timedelta(days=1)), kind='vacation')
        self.assertEqual(response.json()['days'], 2)
        self.assertEqual(self.enter(start=self.days[1], end=self.days[2]).status_code, 409)
        self.assertEqual(self.enter(start=str(saturday), end=str(saturday)).status_code, 422)
        self.assertEqual(self.enter(start=self.days[0], end=str(self.monday + timedelta(days=40))).status_code, 422)
        self.assertEqual(self.enter(start=self.days[2], end=self.days[0]).status_code, 422)

    def test_no_new_proposal_on_a_confirmed_free_day(self):
        batch = self.enter(kind='holiday').json()['batch']
        self.decide(batch, 'confirm')
        deadline = (datetime.now().astimezone() + timedelta(days=2)).isoformat()
        response = self.tobi.post('/api/proposals', json={'day': self.days[1], 'kind': 'bring', 'owner': 'britta', 'start': '07:45',
                                                          'end': '08:45', 'expected_version': 1, 'reason': 'x', 'deadline': deadline})
        self.assertEqual(response.status_code, 409)

    def test_month_draft_skips_free_days_and_state_lists_them(self):
        next_month = (self.monday.replace(day=1) + timedelta(days=40)).replace(day=1)
        first_weekday = next_month
        while first_weekday.weekday() > 4:
            first_weekday += timedelta(days=1)
        self.enter(start=str(first_weekday), end=str(first_weekday))  # pending counts too
        month = next_month.strftime('%Y-%m')
        body = {'month': month, 'bring_start': '07:45', 'bring_end': '08:45', 'pickup_start': '15:30', 'pickup_end': '17:30'}
        self.assertEqual(self.tobi.post('/api/month-draft', json=body).status_code, 200)
        drafted = {r[0] for r in self.rows('SELECT day FROM appointments WHERE day LIKE ?', month + '%')}
        self.assertNotIn(str(first_weekday), drafted)
        listed = self.britta.get('/api/state', params={'month': self.monday.strftime('%Y-%m')}).json()['closures']
        self.assertEqual([c['day'] for c in listed], [str(first_weekday)])  # pending shown in any month

    def test_evening_summary_leaves_out_free_days(self):
        batch = self.enter(start=self.days[0], end=self.days[0]).json()['batch']
        self.decide(batch, 'confirm')
        evening = datetime.combine(self.monday - timedelta(days=1), datetime.min.time()).replace(hour=19, tzinfo=TZ)
        self.app.state.integrations.summaries(evening)
        body = self.rows("SELECT body FROM notifications WHERE owner='tobi' AND dedupe LIKE 'day:%'")[0][0]
        self.assertTrue(body.startswith('0 bestätigte Wege'))


if __name__ == '__main__':
    unittest.main()
