"""Hand-over of a confirmed block to the parent's own Outlook app (B-17).

Family OS never accesses the work calendars (B-02). For a task "Arbeitskalender
aktualisieren" that asks a parent to *add* a block, the app offers links that
open a prefilled new event in Outlook on that parent's own iPhone; the parent
checks and saves it. Only title and time are handed over (B-08 titles), no
names, notes or other family data. Removing or changing an existing block
stays manual.
"""
from datetime import datetime, timezone

from integrations import TZ

TASK_TITLE = 'Arbeitskalender aktualisieren'
TITLES = {'bring': 'Lina bringen', 'pickup': 'Lina abholen'}


def times(day, clock):
    local = datetime.fromisoformat(f'{day}T{clock}').replace(tzinfo=TZ)
    return local.strftime('%Y-%m-%dT%H:%M:%S'), local.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def add_blocks(conn, tasks):
    """Attach ``calendar_block`` to open tasks that ask their owner to add a block."""
    closed = {r[0] for r in conn.execute("SELECT day FROM day_closures WHERE state='confirmed'")}
    for task in tasks:
        if task['title'] != TASK_TITLE or task['state'] != 'open' or not task.get('appointment_id'):
            continue
        slot = conn.execute('SELECT * FROM appointments WHERE id=?', (task['appointment_id'],)).fetchone()
        if not slot or slot['owner'] != task['owner'] or not slot['start'] or not slot['end'] or slot['day'] in closed:
            continue
        start_local, start_utc = times(slot['day'], slot['start'])
        end_local, end_utc = times(slot['day'], slot['end'])
        task['calendar_block'] = {'title': TITLES[slot['kind']], 'start_local': start_local, 'end_local': end_local,
                                  'start_utc': start_utc, 'end_utc': end_utc}
    return tasks
