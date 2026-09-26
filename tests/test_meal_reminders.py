"""Reminders for meal planning and shopping (E-02)."""
from datetime import datetime, timedelta
import json
from pathlib import Path
import tempfile
import time
import unittest

from app import create_app
from integrations import TZ
from meal_reminders import MealReminders

START = '2026-10-03'  # Saturday; Thursday before is 2026-10-01.


def snapshot(planned=0, on_list=(), days_recipes=None):
    days = []
    for i in range(7):
        day = str(datetime(2026, 10, 3).date() + timedelta(days=i))
        recipes = [{'id': f'r{i}', 'name': f'Gericht {i}'}] if i < planned else []
        days.append({'day': day, 'recipes': recipes, 'custom_ids': []})
    return {'start': START, 'days': days,
            'shopping_recipes': [{'id': r, 'name': r, 'ingredient_ids': []} for r in on_list],
            'ingredients': [], 'additional': []}


class MealReminderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = create_app(Path(self.tmp.name) / 'family.sqlite', demo=True)
        self.db = self.app.state.db
        with self.db() as conn:
            conn.execute("DELETE FROM tasks")
            conn.execute("INSERT INTO integration_secrets VALUES('cookidoo','x')")
        self.reminders = MealReminders(self.db, demo=False)

    def tearDown(self):
        self.tmp.cleanup()

    def cache(self, value):
        with self.db() as conn:
            conn.execute('INSERT OR REPLACE INTO meal_cache VALUES(?,?,?)', ('week:' + START, json.dumps(value), time.time()))

    def at(self, day, hour):
        return datetime(2026, 10, day, hour, 0, tzinfo=TZ)

    def tasks(self):
        with self.db() as conn:
            return [dict(r) for r in conn.execute('SELECT title,state,owner,due FROM tasks ORDER BY id')]

    def test_thursday_planning_task_once_and_closed_when_week_is_planned(self):
        self.cache(snapshot(planned=3))
        self.reminders.periodic(self.at(1, 8))   # Thursday before 9
        self.reminders.periodic(datetime(2026, 9, 30, 12, tzinfo=TZ))  # Wednesday
        self.assertEqual(self.tasks(), [])
        self.reminders.periodic(self.at(1, 9))
        self.reminders.periodic(self.at(1, 15))
        tasks = self.tasks()
        self.assertEqual(len(tasks), 1)
        self.assertEqual((tasks[0]['title'], tasks[0]['owner'], tasks[0]['state']), ('Essen planen', 'tobi', 'open'))
        self.assertTrue(tasks[0]['due'].startswith('2026-10-02T12:00'))
        self.cache(snapshot(planned=7))
        self.reminders.periodic(self.at(1, 16))
        self.assertEqual(self.tasks()[0]['state'], 'superseded')

    def test_no_planning_task_when_week_is_complete(self):
        self.cache(snapshot(planned=7, on_list=[f'r{i}' for i in range(7)]))
        self.reminders.periodic(self.at(1, 10))
        self.reminders.periodic(self.at(2, 10))
        self.assertEqual(self.tasks(), [])

    def test_friday_shopping_task_and_auto_close_after_week_change(self):
        self.cache(snapshot(planned=7, on_list=['r99']))
        self.reminders.periodic(self.at(2, 9))
        tasks = self.tasks()
        self.assertEqual([t['title'] for t in tasks], ['Einkaufsliste vorbereiten'])
        self.assertTrue(tasks[0]['due'].startswith('2026-10-02T17:00'))
        self.cache(snapshot(planned=7, on_list=[f'r{i}' for i in range(7)]))
        self.reminders.periodic(self.at(2, 11))
        self.assertEqual(self.tasks()[0]['state'], 'superseded')

    def test_already_shopped_week_needs_no_list_preparation(self):
        self.cache(snapshot(planned=7, on_list=['r99']))
        with self.db() as conn:
            conn.execute("INSERT INTO metadata VALUES('meal_shopped:2026-10-03','{}')")
        self.reminders.periodic(self.at(2, 9))
        self.assertEqual(self.tasks(), [])

    def test_marking_shopped_closes_open_list_task(self):
        self.cache(snapshot(planned=7, on_list=['r99']))
        self.reminders.periodic(self.at(2, 9))
        with self.db() as conn:
            conn.execute("INSERT INTO metadata VALUES('meal_shopped:2026-10-03','{}')")
        self.reminders.periodic(self.at(2, 10))
        self.assertEqual(self.tasks()[0]['state'], 'superseded')

    def test_completed_task_is_not_recreated(self):
        self.reminders.periodic(self.at(1, 9))  # no snapshot yet: still reminds
        with self.db() as conn:
            conn.execute("UPDATE tasks SET state='done'")
        self.reminders.periodic(self.at(1, 12))
        self.assertEqual([t['state'] for t in self.tasks()], ['done'])

    def test_nothing_without_cookidoo_or_in_demo(self):
        with self.db() as conn:
            conn.execute("DELETE FROM integration_secrets")
        self.reminders.periodic(self.at(1, 9))
        MealReminders(self.db, demo=True).periodic(self.at(2, 9))
        self.assertEqual(self.tasks(), [])


if __name__ == '__main__':
    unittest.main()
