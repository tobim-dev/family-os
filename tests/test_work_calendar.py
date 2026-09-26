"""Outlook hand-over for work-calendar tasks (B-17): only add-tasks, correct times."""
from datetime import datetime, timedelta
from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient
from app import create_app
from work_calendar import times


class WorkCalendarTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = create_app(Path(self.tmp.name) / 'family.sqlite', demo=True)
        with self.app.state.db() as conn:
            for table in ('tasks', 'proposals', 'issues', 'appointments', 'day_closures'):
                conn.execute('DELETE FROM ' + table)
            conn.execute("INSERT INTO appointments(id,day,kind,owner,start,end,version) VALUES(1,'2027-03-29','pickup','tobi','15:30','17:30',1)")
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

    def hand_over(self):
        deadline = (datetime.now().astimezone() + timedelta(days=2)).isoformat()
        proposal = self.tobi.post('/api/proposals', json={
            'day': '2027-03-29', 'kind': 'pickup', 'owner': 'britta', 'start': '15:45', 'end': '17:30',
            'expected_version': 1, 'reason': 'Termin', 'deadline': deadline}).json()['id']
        self.assertEqual(self.britta.post(f'/api/proposals/{proposal}/decision', json={'action': 'approve'}).status_code, 200)

    def tasks(self, client):
        return [t for t in client.get('/api/state', params={'month': '2027-03'}).json()['tasks'] if t['state'] == 'open']

    def test_only_the_new_block_gets_outlook_data(self):
        self.hand_over()
        tasks = {t['owner']: t for t in self.tasks(self.tobi)}
        self.assertNotIn('calendar_block', tasks['tobi'])  # remove the old block: manual
        self.assertEqual(tasks['britta']['calendar_block'], {
            'title': 'Lina abholen', 'start_local': '2027-03-29T15:45:00', 'end_local': '2027-03-29T17:30:00',
            'start_utc': '2027-03-29T13:45:00Z', 'end_utc': '2027-03-29T15:30:00Z'})

    def test_no_link_on_confirmed_free_day_or_after_completion(self):
        self.hand_over()
        with self.app.state.db() as conn:
            conn.execute("INSERT INTO day_closures(day,kind,batch,state,creator,created) VALUES('2027-03-29','sick','b','confirmed','tobi','x')")
        self.assertFalse(any('calendar_block' in t for t in self.tasks(self.britta)))

    def test_times_follow_daylight_saving(self):
        self.assertEqual(times('2027-01-11', '07:45'), ('2027-01-11T07:45:00', '2027-01-11T06:45:00Z'))
        self.assertEqual(times('2027-07-12', '07:45'), ('2027-07-12T07:45:00', '2027-07-12T05:45:00Z'))


if __name__ == '__main__':
    unittest.main()
