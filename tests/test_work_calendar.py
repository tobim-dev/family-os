"""Work-calendar entries bundled in one task per person (B-13, B-17, B-18)."""
from datetime import datetime, timedelta
from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient
from app import create_app
from work_calendar import times

DAYS = ['2027-03-29', '2027-03-30', '2027-03-31']


class WorkCalendarTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = create_app(Path(self.tmp.name) / 'family.sqlite', demo=True)
        with self.app.state.db() as conn:
            for table in ('work_calendar_items', 'tasks', 'proposals', 'issues', 'appointments', 'day_closures'):
                conn.execute('DELETE FROM ' + table)
        self.tobi, self.britta = self.client('tobi'), self.client('britta')

    def tearDown(self):
        self.tobi.close()
        self.britta.close()
        self.tmp.cleanup()

    def client(self, user):
        client = TestClient(self.app, base_url='http://127.0.0.1:8765',
                            headers={'Origin': 'http://127.0.0.1:8765', 'X-Family-Request': '1'})
        client.post('/api/login', json={'user': user})
        return client

    def assign(self, day, kind, owner, start='07:45', end='08:45'):
        """Tobi proposes, Britta confirms."""
        creator, approver = self.tobi, self.britta
        slot = next((a for a in self.tobi.get('/api/state', params={'month': day[:7]}).json()['appointments']
                     if a['day'] == day and a['kind'] == kind), None)
        deadline = (datetime.now().astimezone() + timedelta(days=2)).isoformat()
        proposal = creator.post('/api/proposals', json={'day': day, 'kind': kind, 'owner': owner, 'start': start, 'end': end,
                                                        'expected_version': slot['version'] if slot else 0,
                                                        'reason': 'Plan', 'deadline': deadline})
        self.assertEqual(proposal.status_code, 200, proposal.text)
        self.assertEqual(approver.post(f"/api/proposals/{proposal.json()['id']}/decision", json={'action': 'approve'}).status_code, 200)

    def work_tasks(self, owner):
        client = self.tobi if owner == 'tobi' else self.britta
        return [t for t in client.get('/api/state', params={'month': '2027-03'}).json()['tasks']
                if t['state'] == 'open' and t['owner'] == owner and t['title'] == 'Arbeitskalender aktualisieren']

    def test_many_confirmations_make_one_task_with_all_entries(self):
        for day in DAYS:
            self.assign(day, 'bring', 'tobi')
        self.assign(DAYS[0], 'pickup', 'tobi', '15:30', '17:30')
        [task] = self.work_tasks('tobi')
        self.assertEqual([i['label'] for i in task['calendar_items']], [
            'Mo 29.03. Lina bringen 07:45–08:45', 'Mo 29.03. Lina abholen 15:30–17:30',
            'Di 30.03. Lina bringen 07:45–08:45', 'Mi 31.03. Lina bringen 07:45–08:45'])
        self.assertTrue(task['details'].startswith('Eintragen: Mo 29.03. Lina bringen'))
        self.assertEqual(task['calendar_items'][0]['calendar_block'], {
            'title': 'Lina bringen', 'start_local': '2027-03-29T07:45:00', 'end_local': '2027-03-29T08:45:00',
            'start_utc': '2027-03-29T05:45:00Z', 'end_utc': '2027-03-29T06:45:00Z'})
        self.assertEqual(self.work_tasks('britta'), [])

    def test_completing_marks_only_seen_entries(self):
        self.assign(DAYS[0], 'bring', 'tobi')
        [task] = self.work_tasks('tobi')
        seen = max(i['id'] for i in task['calendar_items'])
        self.assign(DAYS[1], 'bring', 'tobi')  # arrives while Tobi is looking
        self.assertEqual(self.tobi.post(f"/api/tasks/{task['id']}/complete", json={'upto': seen}).status_code, 200)
        [left] = self.work_tasks('tobi')
        self.assertEqual(left['id'], task['id'])
        self.assertEqual([i['label'] for i in left['calendar_items']], ['Di 30.03. Lina bringen 07:45–08:45'])
        self.assertEqual(self.tobi.post(f"/api/tasks/{task['id']}/complete", json={'upto': seen + 100}).status_code, 200)
        self.assertEqual(self.work_tasks('tobi'), [])
        self.assertEqual(self.britta.post(f"/api/tasks/{task['id']}/complete", json={}).status_code, 403)

    def test_handover_after_entry_gives_remove_and_add(self):
        self.assign(DAYS[0], 'pickup', 'tobi', '15:30', '17:30')
        [task] = self.work_tasks('tobi')
        self.tobi.post(f"/api/tasks/{task['id']}/complete", json={})
        self.assign(DAYS[0], 'pickup', 'britta', '15:45', '17:30')
        [removal] = self.work_tasks('tobi')
        self.assertEqual([(i['action'], i['label']) for i in removal['calendar_items']],
                         [('remove', 'Mo 29.03. Lina abholen 15:30–17:30')])
        self.assertNotIn('calendar_block', removal['calendar_items'][0])  # links only add
        [entry] = self.work_tasks('britta')
        self.assertEqual(entry['calendar_items'][0]['calendar_block']['start_local'], '2027-03-29T15:45:00')

    def test_handover_before_entry_cancels_out(self):
        self.assign(DAYS[0], 'bring', 'tobi')
        self.assign(DAYS[0], 'bring', 'britta')
        self.assertEqual(self.work_tasks('tobi'), [])
        self.assertEqual(len(self.work_tasks('britta')), 1)

    def test_changed_time_replaces_pending_entry(self):
        self.assign(DAYS[0], 'bring', 'tobi')
        self.assign(DAYS[0], 'bring', 'tobi', '08:00', '09:00')
        [task] = self.work_tasks('tobi')
        self.assertEqual([i['label'] for i in task['calendar_items']], ['Mo 29.03. Lina bringen 08:00–09:00'])

    def test_times_follow_daylight_saving(self):
        self.assertEqual(times('2027-01-11', '07:45'), ('2027-01-11T07:45:00', '2027-01-11T06:45:00Z'))
        self.assertEqual(times('2027-07-12', '07:45'), ('2027-07-12T07:45:00', '2027-07-12T05:45:00Z'))


if __name__ == '__main__':
    unittest.main()
