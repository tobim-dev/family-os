"""Timely reminders for meal planning and shopping (E-02).

Tobi usually plans on Thursday or Friday noon and shops on Friday evening or
Saturday morning. Provisional implementation decision (see ANFORDERUNGEN.md):

* Thursday from 9 o'clock: task "Essen planen" for the coming week
  (Saturday to Friday) unless all seven evenings are already planned.
  Due Friday 12:00. Closed automatically once the week is fully planned.
* Friday from 9 o'clock: task "Einkaufsliste vorbereiten" for the same week,
  due Friday 17:00. Closed automatically once the guided week change has
  nothing left to do for that week.

Only with a connected Cookidoo account. Each task is created at most once per
week; a task that was completed or closed is never recreated.
"""
from datetime import datetime, timedelta
import json

from integrations import TZ, notify
import shopping_week

OWNER = 'tobi'


def coming_saturday(day):
    return day + timedelta(days=(5 - day.weekday()) % 7)


class MealReminders:
    def __init__(self, db, demo):
        self.db, self.demo = db, demo

    def snapshot(self, conn, start):
        row = conn.execute('SELECT value FROM meal_cache WHERE key=?', ('week:' + str(start),)).fetchone()
        return json.loads(row[0]) if row else None

    @staticmethod
    def planned_days(snapshot):
        if not snapshot:
            return 0
        return sum(1 for d in snapshot['days'] if d['recipes'] or d['custom_ids'])

    @staticmethod
    def list_ready(snapshot):
        if not snapshot:
            return False
        plan = shopping_week.plan(snapshot)
        return not plan['remove'] and not plan['add']

    def task(self, conn, kind, start):
        row = conn.execute('SELECT value FROM metadata WHERE key=?', (f'meal_task:{kind}:{start}',)).fetchone()
        return int(row[0]) if row else None

    def create(self, conn, kind, start, title, details, due, instant):
        cursor = conn.execute('INSERT INTO tasks(owner,title,details,due,created) VALUES(?,?,?,?,?)',
                              (OWNER, title, details, due.isoformat(), instant.isoformat(timespec='seconds')))
        conn.execute('INSERT INTO metadata VALUES(?,?)', (f'meal_task:{kind}:{start}', str(cursor.lastrowid)))
        notify(conn, OWNER, f'meal-{kind}:{start}', title, details, False, instant)

    def close(self, conn, task_id):
        conn.execute("UPDATE tasks SET state='superseded' WHERE id=? AND state='open'", (task_id,))

    def periodic(self, instant=None):
        if self.demo:
            return
        instant = (instant or datetime.now(TZ)).astimezone(TZ)
        today = instant.date()
        start = coming_saturday(today)
        friday = start - timedelta(days=1)
        with self.db() as conn:
            if not conn.execute("SELECT 1 FROM integration_secrets WHERE key='cookidoo'").fetchone():
                return
            if not conn.execute('SELECT 1 FROM users WHERE id=?', (OWNER,)).fetchone():
                return
            snapshot = self.snapshot(conn, start)
            label = f"{start.strftime('%d.%m.')}–{(start + timedelta(days=6)).strftime('%d.%m.')}"

            plan_task = self.task(conn, 'plan', start)
            full = self.planned_days(snapshot) == 7
            if plan_task and full:
                self.close(conn, plan_task)
            elif not plan_task and not full and today.weekday() == 3 and instant.hour >= 9:
                missing = 7 - self.planned_days(snapshot)
                due = datetime.combine(friday, datetime.min.time(), TZ).replace(hour=12)
                self.create(conn, 'plan', start, 'Essen planen',
                            f'Woche {label}: noch {missing} Abende ohne Gericht. „Woche vorschlagen“ hilft dabei.',
                            due, instant)

            shop_task = self.task(conn, 'shop', start)
            ready = self.list_ready(snapshot)
            if shop_task and ready:
                self.close(conn, shop_task)
            elif not shop_task and not ready and today == friday and instant.hour >= 9:
                due = datetime.combine(friday, datetime.min.time(), TZ).replace(hour=17)
                self.create(conn, 'shop', start, 'Einkaufsliste vorbereiten',
                            f'Woche {label}: Einkaufsliste für diese Woche vorbereiten, danach Vorräte durchgehen und abhaken.',
                            due, instant)
