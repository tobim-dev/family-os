"""Lina: diapers at home, spare clothes at the nursery, clothing needs (K-01 to K-07).

Provisional implementation decisions (O-08, see ANFORDERUNGEN.md):

* Diapers (K-06, K-07): no consumption tracking. Events only: "pack opened",
  "packs bought", "stock set". The stock of unopened packs follows from them.
  When the stock after opening reaches the threshold (default 1 pack) a task
  "Windeln kaufen" goes to the shopper (default Tobi, E-02). Buying closes it.
  The nursery supplies its own diapers; nothing is tracked for it.
* Spare clothes at the nursery (K-04): the staff's request is entered as a
  note. The task goes to the parent who brings Lina on the next nursery day
  (they take the clothes along), otherwise to Britta. Additionally Britta gets
  a task every four weeks to check the spare clothes proactively.
* Clothing needs (K-01 to K-03): free text, optional size, urgency
  (urgent / this season / later). Britta is responsible (K-01). Only urgent
  needs create a task. No sizes or quantities are invented.
* Sorted out (K-02, K-05): what no longer fits, with destination (sell / give
  away / keep). For selling, the app prepares a plain text for Vinted from the
  entered details only; nothing is posted automatically.
"""
from datetime import date, datetime, timedelta
from typing import Literal

from fastapi import HTTPException, Request
from pydantic import BaseModel, Field

from integrations import TZ, PEOPLE, notify

CLOTHING_OWNER = 'britta'      # K-01
DEFAULT_DIAPER_OWNER = 'tobi'  # does the weekly shopping (E-02)
DEFAULT_THRESHOLD = 1
CHECK_EVERY_DAYS = 28
URGENCY = {'urgent': 'dringend', 'season': 'diese Saison', 'later': 'später'}
DESTINATION = {'sell': 'verkaufen', 'give': 'verschenken', 'keep': 'aufbewahren'}


def now():
    return datetime.now(TZ).isoformat(timespec='seconds')


class DiaperInput(BaseModel):
    kind: Literal['opened', 'bought', 'set']
    packs: int = Field(default=1, ge=0, le=50)


class DiaperSettings(BaseModel):
    threshold: int = Field(ge=0, le=10)
    owner: Literal['tobi', 'britta']
    size: str = Field(default='', max_length=40)


class ItemInput(BaseModel):
    list: Literal['need', 'nursery', 'sort_out']
    text: str = Field(min_length=1, max_length=200)
    size: str = Field(default='', max_length=40)
    urgency: Literal['urgent', 'season', 'later'] | None = None
    destination: Literal['sell', 'give', 'keep'] | None = None
    details: str = Field(default='', max_length=1000)


class ItemAction(BaseModel):
    action: Literal['done', 'drop', 'reopen']
    version: int


class Lina:
    def __init__(self, db, demo):
        self.db, self.demo = db, demo
        if demo:
            self.seed()

    # --- helpers ---------------------------------------------------------

    @staticmethod
    def audit(conn, actor, action, details):
        conn.execute('INSERT INTO audit(actor,action,details,created) VALUES(?,?,?,?)', (actor, action, details, now()))

    @staticmethod
    def settings(conn):
        values = dict(conn.execute("SELECT key,value FROM metadata WHERE key LIKE 'lina_%'").fetchall())
        return {'threshold': int(values.get('lina_diaper_threshold', DEFAULT_THRESHOLD)),
                'owner': values.get('lina_diaper_owner', DEFAULT_DIAPER_OWNER),
                'size': values.get('lina_diaper_size', '')}

    @staticmethod
    def stock(events):
        """Unopened packs; None while no stock was ever set or bought."""
        value = None
        for event in events:
            if event['kind'] == 'set':
                value = event['packs']
            elif event['kind'] == 'bought':
                value = (value or 0) + event['packs']
            elif value is not None:
                value = max(0, value - 1)
        return value

    @staticmethod
    def pace(events):
        """Average days per pack from the last openings (at least two needed)."""
        opened = [datetime.fromisoformat(e['created']) for e in events if e['kind'] == 'opened'][-7:]
        if len(opened) < 2:
            return None
        return round((opened[-1] - opened[0]).total_seconds() / 86400 / (len(opened) - 1), 1)

    def diapers(self, conn):
        events = [dict(r) for r in conn.execute('SELECT * FROM lina_diapers ORDER BY id')]
        stock, pace = self.stock(events), self.pace(events)
        last_opened = next((e['created'] for e in reversed(events) if e['kind'] == 'opened'), None)
        until = None
        if stock is not None and pace and last_opened:
            # The open pack plus the unopened ones, at the observed pace.
            until = str((datetime.fromisoformat(last_opened) + timedelta(days=pace * (stock + 1))).date())
        return {'stock': stock, 'pace_days': pace, 'last_opened': last_opened, 'until': until,
                'settings': self.settings(conn), 'history': events[-8:][::-1]}

    @staticmethod
    def open_task(conn, key):
        row = conn.execute('SELECT value FROM metadata WHERE key=?', (key,)).fetchone()
        if not row:
            return None
        task = conn.execute("SELECT * FROM tasks WHERE id=? AND state='open'", (int(row[0]),)).fetchone()
        return task

    @staticmethod
    def remember_task(conn, key, task_id):
        conn.execute('INSERT OR REPLACE INTO metadata VALUES(?,?)', (key, str(task_id)))

    @staticmethod
    def add_task(conn, owner, title, details, due):
        cursor = conn.execute('INSERT INTO tasks(owner,title,details,due,created) VALUES(?,?,?,?,?)',
                              (owner, title, details, due, now()))
        return cursor.lastrowid

    @staticmethod
    def next_bring(conn, today):
        """Next nursery day after today with its bringing parent (may be None)."""
        closed = {r[0] for r in conn.execute("SELECT day FROM day_closures WHERE state='confirmed'")}
        day = today
        for _ in range(21):
            day += timedelta(days=1)
            if day.weekday() > 4 or str(day) in closed:
                continue
            row = conn.execute("SELECT owner,start FROM appointments WHERE day=? AND kind='bring'", (str(day),)).fetchone()
            return day, (row['owner'] if row and row['owner'] else None), (row['start'] if row and row['start'] else '07:45')
        return None, None, '07:45'

    def item(self, conn, item_id, version=None):
        row = conn.execute('SELECT * FROM lina_items WHERE id=?', (item_id,)).fetchone()
        if not row:
            raise HTTPException(404, 'Eintrag nicht gefunden.')
        if version is not None and row['version'] != version:
            raise HTTPException(409, 'Dieser Eintrag wurde inzwischen geändert. Bitte neu laden.')
        return row

    # --- diapers ---------------------------------------------------------

    def record_diapers(self, conn, actor, data):
        if data.kind == 'opened' and data.packs != 1:
            raise HTTPException(422, 'Bitte jede geöffnete Packung einzeln erfassen.')
        if data.kind == 'bought' and data.packs < 1:
            raise HTTPException(422, 'Bitte mindestens eine gekaufte Packung angeben.')
        conn.execute('INSERT INTO lina_diapers(kind,packs,actor,created) VALUES(?,?,?,?)', (data.kind, data.packs, actor, now()))
        text = {'opened': 'Windelpackung geöffnet', 'bought': f'{data.packs} Windelpackung(en) gekauft',
                'set': f'Windelvorrat auf {data.packs} Packung(en) gesetzt'}[data.kind]
        self.audit(conn, actor, text, 'Lina')
        info = self.diapers(conn)
        settings, stock = info['settings'], info['stock']
        task = self.open_task(conn, 'lina_diaper_task')
        if stock is None:
            return info
        if stock <= settings['threshold'] and not task:
            size = f" (Größe {settings['size']})" if settings['size'] else ''
            details = f'Zuhause noch {stock} ungeöffnete Packung{"" if stock == 1 else "en"}{size}. Beim nächsten Einkauf mitnehmen.'
            task_id = self.add_task(conn, settings['owner'], 'Windeln kaufen', details, now())
            self.remember_task(conn, 'lina_diaper_task', task_id)
            notify(conn, settings['owner'], f'diapers-low:{task_id}', 'Windeln werden knapp', details, False)
        elif stock > settings['threshold'] and task:
            conn.execute("UPDATE tasks SET state='done' WHERE id=?", (task['id'],))
        return info

    # --- items -----------------------------------------------------------

    def create_item(self, conn, actor, data):
        if data.list == 'need' and not data.urgency:
            raise HTTPException(422, 'Bitte angeben, wie dringend es ist.')
        if data.list == 'sort_out' and not data.destination:
            raise HTTPException(422, 'Bitte angeben, was mit dem Teil passieren soll.')
        text, size = data.text.strip(), data.size.strip()
        owner, task_id = CLOTHING_OWNER, None
        label = text + (f' (Größe {size})' if size else '')
        if data.list == 'nursery':
            day, bringer, start = self.next_bring(conn, datetime.now(TZ).date())
            owner = bringer or CLOTHING_OWNER
            due = datetime.combine(day, datetime.strptime(start, '%H:%M').time(), TZ).isoformat() if day else now()
            when = f"am {day.strftime('%d.%m.')} beim Bringen" if day and bringer else 'beim nächsten Bringen'
            task_id = self.add_task(conn, owner, 'Wechselkleidung in die Krippe', f'{label} {when} mitgeben.', due)
            notify(conn, owner, f'nursery-clothes:{task_id}', 'Wechselkleidung für die Krippe', f'{label} {when} mitgeben.', False)
        elif data.list == 'need' and data.urgency == 'urgent':
            due = (datetime.now(TZ) + timedelta(days=2)).isoformat(timespec='seconds')
            task_id = self.add_task(conn, owner, 'Kleidung besorgen', f'{label} · dringend.', due)
            if actor != owner:
                notify(conn, owner, f'clothing-urgent:{task_id}', 'Kleidung dringend', f'{PEOPLE[actor]}: {label} wird dringend gebraucht.', False)
        cursor = conn.execute('INSERT INTO lina_items(list,text,size,urgency,destination,details,owner,creator,task_id,created,updated) '
                              'VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                              (data.list, text, size, data.urgency if data.list == 'need' else None,
                               data.destination if data.list == 'sort_out' else None, data.details.strip(),
                               owner, actor, task_id, now(), now()))
        self.audit(conn, actor, {'need': 'Kleidungsbedarf notiert', 'nursery': 'Wechselkleidung angefragt',
                                 'sort_out': 'Kleidung aussortiert'}[data.list], label)
        return cursor.lastrowid

    def change_item(self, conn, actor, item_id, data):
        row = self.item(conn, item_id, data.version)
        target = {'done': 'done', 'drop': 'dropped', 'reopen': 'open'}[data.action]
        if (data.action == 'reopen') == (row['state'] == 'open'):
            raise HTTPException(409, 'Dieser Schritt passt nicht zum aktuellen Stand. Bitte neu laden.')
        conn.execute('UPDATE lina_items SET state=?,version=version+1,updated=? WHERE id=?', (target, now(), item_id))
        if row['task_id'] and data.action != 'reopen':
            conn.execute("UPDATE tasks SET state=? WHERE id=? AND state='open'",
                         ('done' if data.action == 'done' else 'superseded', row['task_id']))
        self.audit(conn, actor, {'done': 'Erledigt', 'drop': 'Verworfen', 'reopen': 'Wieder geöffnet'}[data.action], row['text'])

    # --- background ------------------------------------------------------

    def periodic(self, instant=None):
        """Every four weeks: Britta checks the spare clothes at the nursery (K-04)."""
        instant = (instant or datetime.now(TZ)).astimezone(TZ)
        if instant.weekday() > 4 or not 9 <= instant.hour < 20:
            return
        with self.db() as conn:
            if not conn.execute('SELECT 1 FROM users WHERE id=?', (CLOTHING_OWNER,)).fetchone():
                return
            row = conn.execute("SELECT value FROM metadata WHERE key='lina_nursery_check'").fetchone()
            if row and date.fromisoformat(row[0]) + timedelta(days=CHECK_EVERY_DAYS) > instant.date():
                return
            if self.open_task(conn, 'lina_nursery_task'):
                return
            conn.execute("INSERT OR REPLACE INTO metadata VALUES('lina_nursery_check',?)", (str(instant.date()),))
            task_id = self.add_task(conn, CLOTHING_OWNER, 'Wechselkleidung in der Krippe prüfen',
                                    'Passt die Wechselkleidung noch und ist genug da? Fehlendes unter Lina als Wechselkleidung notieren.',
                                    (instant + timedelta(days=3)).isoformat(timespec='seconds'))
            self.remember_task(conn, 'lina_nursery_task', task_id)

    # --- demo ------------------------------------------------------------

    def seed(self):
        with self.db() as conn:
            if conn.execute("SELECT 1 FROM metadata WHERE key='lina_seeded'").fetchone():
                return
            if not conn.execute("SELECT 1 FROM users WHERE id='britta'").fetchone():
                return
            start = datetime.now(TZ) - timedelta(days=12)
            events = [('set', 4, 0), ('opened', 1, 1), ('opened', 1, 6), ('opened', 1, 11)]
            for kind, packs, offset in events:
                conn.execute('INSERT INTO lina_diapers(kind,packs,actor,created) VALUES(?,?,?,?)',
                             (kind, packs, 'britta', (start + timedelta(days=offset)).isoformat(timespec='seconds')))
            conn.execute("INSERT INTO lina_items(list,text,size,urgency,owner,creator,created,updated) "
                         "VALUES('need','Matschhose','98','season','britta','britta',?,?)", (now(), now()))
            conn.execute("INSERT INTO lina_items(list,text,size,destination,details,owner,creator,created,updated) "
                         "VALUES('sort_out','Sommerkleid gelb','86','sell','Kaum getragen.','britta','britta',?,?)", (now(), now()))
            conn.execute("INSERT INTO metadata VALUES('lina_seeded','1')")

    # --- routes ----------------------------------------------------------

    def routes(self, app, identity):
        db = self.db

        @app.get('/api/lina')
        def overview(request: Request):
            with db() as conn:
                identity(request, conn)
                items = [dict(r) for r in conn.execute(
                    "SELECT * FROM lina_items WHERE state='open' OR updated>=? ORDER BY state!='open',list,"
                    "CASE urgency WHEN 'urgent' THEN 0 WHEN 'season' THEN 1 ELSE 2 END,id DESC",
                    ((datetime.now(TZ) - timedelta(days=30)).isoformat(),))]
                return {'diapers': self.diapers(conn), 'items': items, 'clothing_owner': CLOTHING_OWNER}

        @app.post('/api/lina/diapers')
        def diapers(data: DiaperInput, request: Request):
            with db() as conn:
                actor = identity(request, conn)
                return self.record_diapers(conn, actor, data)

        @app.post('/api/lina/diapers/settings')
        def diaper_settings(data: DiaperSettings, request: Request):
            with db() as conn:
                actor = identity(request, conn)
                for key, value in (('threshold', data.threshold), ('owner', data.owner), ('size', data.size.strip())):
                    conn.execute('INSERT OR REPLACE INTO metadata VALUES(?,?)', ('lina_diaper_' + key, str(value)))
                self.audit(conn, actor, 'Windel-Einstellungen geändert', f'Nachkauf ab {data.threshold} Packung(en) · {PEOPLE[data.owner]}')
                return self.diapers(conn)

        @app.post('/api/lina/items')
        def create(data: ItemInput, request: Request):
            with db() as conn:
                actor = identity(request, conn)
                return {'id': self.create_item(conn, actor, data)}

        @app.post('/api/lina/items/{item_id}')
        def change(item_id: int, data: ItemAction, request: Request):
            with db() as conn:
                actor = identity(request, conn)
                self.change_item(conn, actor, item_id, data)
            return {'ok': True}
