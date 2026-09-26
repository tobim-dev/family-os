"""Work-calendar entries per parent, bundled in one task (B-13, B-17, B-18).

Family OS never accesses the work calendars (B-02). It keeps a list of what
each parent still has to add to or remove from their own work calendar and
shows it as exactly one open task "Arbeitskalender aktualisieren" per parent.

Rules (provisional, see ANFORDERUNGEN.md B-18):

* A new entry cancels a pending opposite one for the same appointment: an
  "add" that was never done plus a later "remove" leave nothing to do; a
  "remove" followed by an "add" with the same times as well. A newer "add"
  replaces an older pending "add" (changed times).
* Completing the task completes only the entries the parent has seen
  (``upto`` = highest entry id shown). Newer entries keep the task open.

For "add" entries the page offers links that open a prefilled new event in
Outlook on the parent's own iPhone (B-17). Only title and time are handed over.
"""
from datetime import date, datetime, timezone

from integrations import TZ

TASK_TITLE = 'Arbeitskalender aktualisieren'
TITLES = {'bring': 'Lina bringen', 'pickup': 'Lina abholen'}
WEEKDAYS = ['Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa', 'So']


def now():
    return datetime.now(TZ).isoformat(timespec='seconds')


def times(day, clock):
    local = datetime.fromisoformat(f'{day}T{clock}').replace(tzinfo=TZ)
    return local.strftime('%Y-%m-%dT%H:%M:%S'), local.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def label(item):
    if not item['day']:
        return item['text']
    day = date.fromisoformat(item['day'])
    text = f"{WEEKDAYS[day.weekday()]} {day.strftime('%d.%m.')} {TITLES[item['kind']]}"
    return text + (f" {item['start']}–{item['end']}" if item['start'] and item['end'] else '')


def record(conn, owner, action, slot, start=None, end=None):
    """Note that ``owner`` must add/remove the block of ``slot`` (start/end: block times)."""
    start = start or slot['start']
    end = end or slot['end']
    pending = conn.execute("SELECT * FROM work_calendar_items WHERE owner=? AND appointment_id=? AND state='open' ORDER BY id",
                           (owner, slot['id'])).fetchall()
    for item in pending:
        if action == 'remove' and item['action'] == 'add':
            # Never entered: nothing to remove, nothing to add.
            conn.execute("UPDATE work_calendar_items SET state='cancelled' WHERE id=?", (item['id'],))
            return sync(conn, owner)
        if action == 'add' and item['action'] == 'remove' and (item['start'], item['end']) == (start, end):
            # Back to what is already in the calendar.
            conn.execute("UPDATE work_calendar_items SET state='cancelled' WHERE id=?", (item['id'],))
            return sync(conn, owner)
        if action == item['action'] == 'add':
            conn.execute("UPDATE work_calendar_items SET state='cancelled' WHERE id=?", (item['id'],))
        if action == item['action'] == 'remove' and (item['start'], item['end']) == (start, end):
            return sync(conn, owner)
    conn.execute('INSERT INTO work_calendar_items(owner,appointment_id,action,day,kind,start,end,created) VALUES(?,?,?,?,?,?,?,?)',
                 (owner, slot['id'], action, slot['day'], slot['kind'], start, end, now()))
    return sync(conn, owner)


def open_items(conn, owner):
    return [dict(r) for r in conn.execute("SELECT * FROM work_calendar_items WHERE owner=? AND state='open' "
                                          "ORDER BY day IS NULL, day, kind, action DESC, id", (owner,))]


def task_id(conn, owner):
    row = conn.execute('SELECT value FROM metadata WHERE key=?', ('work_task:' + owner,)).fetchone()
    if not row:
        return None
    task = conn.execute("SELECT id FROM tasks WHERE id=? AND state='open'", (int(row[0]),)).fetchone()
    return task['id'] if task else None


def summary(items):
    adds = [label(i) for i in items if i['action'] == 'add']
    removes = [label(i) for i in items if i['action'] == 'remove']
    parts = []
    if adds:
        parts.append('Eintragen: ' + '; '.join(adds))
    if removes:
        parts.append('Entfernen: ' + '; '.join(removes))
    return '. '.join(parts) + '.'


def sync(conn, owner):
    """Keep exactly one open task per parent while entries are open."""
    items = open_items(conn, owner)
    current = task_id(conn, owner)
    if not items:
        if current:
            conn.execute("UPDATE tasks SET state='superseded' WHERE id=?", (current,))
        return
    due = min(i['created'] for i in items)
    if current:
        conn.execute('UPDATE tasks SET details=?,due=? WHERE id=?', (summary(items), due, current))
        return
    cursor = conn.execute('INSERT INTO tasks(owner,title,details,due,created) VALUES(?,?,?,?,?)',
                          (owner, TASK_TITLE, summary(items), due, now()))
    conn.execute('INSERT OR REPLACE INTO metadata VALUES(?,?)', ('work_task:' + owner, str(cursor.lastrowid)))


def sync_all(conn):
    for (owner,) in conn.execute('SELECT id FROM users').fetchall():
        sync(conn, owner)


def is_work_task(conn, task):
    return task['title'] == TASK_TITLE and task_id(conn, task['owner']) == task['id']


def complete(conn, owner, upto=None):
    """Mark the entries the parent has seen as done; newer ones stay open."""
    limit = upto if upto is not None else 2 ** 62
    conn.execute("UPDATE work_calendar_items SET state='done',done=? WHERE owner=? AND state='open' AND id<=?",
                 (now(), owner, limit))
    sync(conn, owner)


def attach(conn, tasks):
    """Add the open entries (with Outlook data for "add") to each parent's bundled task."""
    for task in tasks:
        if task['state'] != 'open' or not is_work_task(conn, task):
            continue
        entries = []
        for item in open_items(conn, task['owner']):
            entry = {'id': item['id'], 'action': item['action'], 'label': label(item)}
            if item['action'] == 'add' and item['day'] and item['start'] and item['end']:
                start_local, start_utc = times(item['day'], item['start'])
                end_local, end_utc = times(item['day'], item['end'])
                entry['calendar_block'] = {'title': TITLES[item['kind']], 'start_local': start_local, 'end_local': end_local,
                                           'start_utc': start_utc, 'end_utc': end_utc}
            entries.append(entry)
        task['calendar_items'] = entries
    return tasks
