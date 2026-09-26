"""Versioned SQLite schema for Family OS.

The schema version lives in ``PRAGMA user_version``.

* Version 1 is the baseline: the schema as it existed before versioning was
  introduced. Databases created earlier report version 0 but already contain
  (a subset of) these tables. The baseline only uses ``CREATE ... IF NOT
  EXISTS`` and was only ever extended by new tables, so such databases are
  adopted without touching data. Afterwards the column layout is verified.
* Every later change is appended to ``MIGRATIONS`` with the next version
  number. Released migrations are never edited, reordered or removed.
* Each migration runs in its own transaction, together with the version bump.
  Foreign-key enforcement is switched off during the migration (required for
  SQLite table rebuilds) and ``PRAGMA foreign_key_check`` must be clean before
  the commit.
* Before a database with existing data is migrated, a consistent copy is
  written to ``backups/`` next to the database.
* A database with a newer version than this code knows is refused, so an
  image rollback cannot silently run old code against a newer schema.
"""
from datetime import datetime
import os
from pathlib import Path
import sqlite3

BASELINE = '''
CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY, password TEXT NOT NULL, totp TEXT NOT NULL, last_step INTEGER NOT NULL DEFAULT -1);
CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), expires REAL NOT NULL);
CREATE TABLE IF NOT EXISTS attempts(key TEXT PRIMARY KEY, count INTEGER NOT NULL, until REAL NOT NULL);
CREATE TABLE IF NOT EXISTS appointments(id INTEGER PRIMARY KEY, day TEXT NOT NULL, kind TEXT NOT NULL CHECK(kind IN ('bring','pickup')), owner TEXT REFERENCES users(id), start TEXT, end TEXT, version INTEGER NOT NULL DEFAULT 0, UNIQUE(day,kind));
CREATE TABLE IF NOT EXISTS issues(id INTEGER PRIMARY KEY, appointment_id INTEGER REFERENCES appointments(id), text TEXT NOT NULL, owner TEXT NOT NULL REFERENCES users(id), state TEXT NOT NULL DEFAULT 'open', deadline TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1, created TEXT NOT NULL, resolution TEXT);
CREATE TABLE IF NOT EXISTS proposals(id INTEGER PRIMARY KEY, appointment_id INTEGER NOT NULL REFERENCES appointments(id), owner TEXT NOT NULL REFERENCES users(id), start TEXT NOT NULL, end TEXT NOT NULL, creator TEXT NOT NULL REFERENCES users(id), reason TEXT NOT NULL, deadline TEXT NOT NULL, base_version INTEGER NOT NULL, state TEXT NOT NULL DEFAULT 'pending', created TEXT NOT NULL, issue_id INTEGER REFERENCES issues(id));
CREATE UNIQUE INDEX IF NOT EXISTS one_pending_proposal ON proposals(appointment_id) WHERE state='pending';
CREATE TABLE IF NOT EXISTS tasks(id INTEGER PRIMARY KEY, appointment_id INTEGER REFERENCES appointments(id), owner TEXT NOT NULL REFERENCES users(id), title TEXT NOT NULL, details TEXT NOT NULL, due TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'open', created TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY, actor TEXT NOT NULL, action TEXT NOT NULL, details TEXT NOT NULL, created TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS appointments_day ON appointments(day);
CREATE INDEX IF NOT EXISTS tasks_owner_state ON tasks(owner,state);
CREATE TABLE IF NOT EXISTS planning_sessions(id TEXT PRIMARY KEY, session_token TEXT NOT NULL REFERENCES sessions(token) ON DELETE CASCADE, actor TEXT NOT NULL REFERENCES users(id), expires REAL NOT NULL, ended INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS calendar_targets(
 key TEXT PRIMARY KEY, event_id TEXT NOT NULL, desired TEXT, applied TEXT,
 etag TEXT, inflight TEXT, state TEXT NOT NULL DEFAULT 'queued',
 attempts INTEGER NOT NULL DEFAULT 0, next_try REAL NOT NULL DEFAULT 0,
 checked REAL NOT NULL DEFAULT 0, message TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS integration_secrets(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS oauth_states(state TEXT PRIMARY KEY, verifier TEXT NOT NULL, cookie_hash TEXT NOT NULL, session TEXT NOT NULL, expires REAL NOT NULL);
CREATE TABLE IF NOT EXISTS notifications(id INTEGER PRIMARY KEY, owner TEXT NOT NULL REFERENCES users(id), dedupe TEXT NOT NULL UNIQUE, title TEXT NOT NULL, body TEXT NOT NULL, urgent INTEGER NOT NULL, created TEXT NOT NULL, read_at TEXT, not_before REAL NOT NULL);
CREATE TABLE IF NOT EXISTS push_subscriptions(id INTEGER PRIMARY KEY, owner TEXT NOT NULL REFERENCES users(id), endpoint TEXT NOT NULL UNIQUE, subscription TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS push_deliveries(notification_id INTEGER NOT NULL REFERENCES notifications(id), subscription_id INTEGER NOT NULL REFERENCES push_subscriptions(id), state TEXT NOT NULL DEFAULT 'queued', attempts INTEGER NOT NULL DEFAULT 0, next_try REAL NOT NULL DEFAULT 0, PRIMARY KEY(notification_id,subscription_id));

CREATE TABLE IF NOT EXISTS meal_cache(key TEXT PRIMARY KEY, value TEXT NOT NULL, updated REAL NOT NULL);
CREATE TABLE IF NOT EXISTS meal_operations(id TEXT PRIMARY KEY, actor TEXT NOT NULL REFERENCES users(id), payload TEXT NOT NULL, state TEXT NOT NULL, message TEXT NOT NULL DEFAULT '', created REAL NOT NULL);
'''

def work_calendar_items(conn):
    """Version 6: one bundled work-calendar task per person.

    Open per-appointment tasks "Arbeitskalender aktualisieren" become entries of
    the new table; the tasks themselves are closed. The application recreates
    one open task per person with all entries on start (work_calendar.py).
    """
    conn.execute('''CREATE TABLE work_calendar_items(
 id INTEGER PRIMARY KEY,
 owner TEXT NOT NULL REFERENCES users(id),
 appointment_id INTEGER REFERENCES appointments(id),
 action TEXT NOT NULL CHECK(action IN ('add','remove')),
 day TEXT,
 kind TEXT CHECK(kind IN ('bring','pickup')),
 start TEXT,
 end TEXT,
 text TEXT NOT NULL DEFAULT '',
 state TEXT NOT NULL DEFAULT 'open' CHECK(state IN ('open','done','cancelled')),
 created TEXT NOT NULL,
 done TEXT)''')
    conn.execute('CREATE INDEX work_calendar_items_owner ON work_calendar_items(owner,state)')
    tasks = conn.execute("SELECT id,appointment_id,owner,details,created FROM tasks "
                         "WHERE title='Arbeitskalender aktualisieren' AND state='open' ORDER BY id").fetchall()
    for task_id, appointment_id, owner, details, created in tasks:
        slot = None
        if appointment_id:
            slot = conn.execute('SELECT day,kind,owner,start,end FROM appointments WHERE id=?', (appointment_id,)).fetchone()
        if slot and slot[2] == owner and slot[3] and slot[4]:
            values = (owner, appointment_id, 'add', slot[0], slot[1], slot[3], slot[4], details)
        elif slot:
            values = (owner, appointment_id, 'remove', slot[0], slot[1], None, None, details)
        else:
            action = 'remove' if 'entfernen' in details else 'add'
            values = (owner, None, action, None, None, None, None, details)
        conn.execute('INSERT INTO work_calendar_items(owner,appointment_id,action,day,kind,start,end,text,created) '
                     'VALUES(?,?,?,?,?,?,?,?,?)', (*values, created))
        conn.execute("UPDATE tasks SET state='superseded' WHERE id=?", (task_id,))


# Append new schema changes here as (version, description, migration).
# ``migration`` is either an SQL script (str) or a callable taking the
# connection. Versions must be consecutive, starting at 2.
MIGRATIONS = [
    (2, 'Nanny-Termine und Monatsabrechnung', '''
CREATE TABLE nanny_shifts(
 id INTEGER PRIMARY KEY,
 day TEXT NOT NULL,
 start TEXT NOT NULL,
 end TEXT NOT NULL,
 state TEXT NOT NULL DEFAULT 'wish' CHECK(state IN ('wish','requested','confirmed','declined','cancelled')),
 paid_cancel INTEGER CHECK(paid_cancel IN (0,1)),
 actual_start TEXT,
 actual_end TEXT,
 correction_note TEXT NOT NULL DEFAULT '',
 note TEXT NOT NULL DEFAULT '',
 creator TEXT NOT NULL REFERENCES users(id),
 version INTEGER NOT NULL DEFAULT 1,
 created TEXT NOT NULL,
 updated TEXT NOT NULL);
CREATE INDEX nanny_shifts_day ON nanny_shifts(day);
CREATE TABLE nanny_statements(
 month TEXT PRIMARY KEY,
 rate_cents INTEGER NOT NULL,
 minutes INTEGER NOT NULL,
 amount_cents INTEGER NOT NULL,
 lines TEXT NOT NULL,
 closed_by TEXT NOT NULL REFERENCES users(id),
 closed TEXT NOT NULL,
 paid TEXT,
 paid_by TEXT REFERENCES users(id));
ALTER TABLE tasks ADD COLUMN nanny_shift_id INTEGER REFERENCES nanny_shifts(id);
'''),
    (3, 'Schließtage, Feiertage, Urlaub und Krankheit', '''
CREATE TABLE day_closures(
 id INTEGER PRIMARY KEY,
 day TEXT NOT NULL UNIQUE,
 kind TEXT NOT NULL CHECK(kind IN ('closed','holiday','vacation','sick')),
 note TEXT NOT NULL DEFAULT '',
 batch TEXT NOT NULL,
 state TEXT NOT NULL DEFAULT 'pending' CHECK(state IN ('pending','confirmed')),
 creator TEXT NOT NULL REFERENCES users(id),
 created TEXT NOT NULL,
 confirmed_by TEXT REFERENCES users(id),
 confirmed TEXT);
CREATE INDEX day_closures_batch ON day_closures(batch);
'''),
    (4, 'Lina: Windelvorrat, Kleidung und Wechselkleidung', '''
CREATE TABLE lina_diapers(
 id INTEGER PRIMARY KEY,
 kind TEXT NOT NULL CHECK(kind IN ('opened','bought','set')),
 packs INTEGER NOT NULL DEFAULT 1 CHECK(packs BETWEEN 0 AND 50),
 actor TEXT NOT NULL REFERENCES users(id),
 created TEXT NOT NULL);
CREATE TABLE lina_items(
 id INTEGER PRIMARY KEY,
 list TEXT NOT NULL CHECK(list IN ('need','nursery','sort_out')),
 text TEXT NOT NULL,
 size TEXT NOT NULL DEFAULT '',
 urgency TEXT CHECK(urgency IN ('urgent','season','later')),
 destination TEXT CHECK(destination IN ('sell','give','keep')),
 details TEXT NOT NULL DEFAULT '',
 state TEXT NOT NULL DEFAULT 'open' CHECK(state IN ('open','done','dropped')),
 owner TEXT NOT NULL REFERENCES users(id),
 creator TEXT NOT NULL REFERENCES users(id),
 task_id INTEGER REFERENCES tasks(id),
 version INTEGER NOT NULL DEFAULT 1,
 created TEXT NOT NULL,
 updated TEXT NOT NULL);
CREATE INDEX lina_items_list_state ON lina_items(list,state);
'''),
    (5, 'Einkaufsgutscheine (PDF auf dem NAS, Restbetrag)', '''
CREATE TABLE vouchers(
 id INTEGER PRIMARY KEY,
 store TEXT NOT NULL DEFAULT 'Kaufland',
 value_cents INTEGER NOT NULL CHECK(value_cents > 0),
 remaining_cents INTEGER NOT NULL CHECK(remaining_cents >= 0),
 note TEXT NOT NULL DEFAULT '',
 file TEXT NOT NULL UNIQUE,
 filename TEXT NOT NULL,
 size INTEGER NOT NULL,
 uploaded_by TEXT NOT NULL REFERENCES users(id),
 version INTEGER NOT NULL DEFAULT 1,
 created TEXT NOT NULL,
 updated TEXT NOT NULL,
 CHECK(remaining_cents <= value_cents));
CREATE TABLE voucher_uses(
 id INTEGER PRIMARY KEY,
 voucher_id INTEGER NOT NULL REFERENCES vouchers(id),
 before_cents INTEGER NOT NULL,
 after_cents INTEGER NOT NULL,
 actor TEXT NOT NULL REFERENCES users(id),
 created TEXT NOT NULL);
'''),
    (6, 'Arbeitskalender: Einträge je Person in einer Aufgabe bündeln', work_calendar_items),
]

LATEST = 1 + len(MIGRATIONS)


class MigrationError(RuntimeError):
    pass


def statements(script):
    """Split an SQL script into complete statements (trigger-aware)."""
    buffer = ''
    for part in script.split(';'):
        buffer += part + ';'
        if sqlite3.complete_statement(buffer):
            if buffer.strip(' \t\r\n;'):
                yield buffer.strip()
            buffer = ''
    if buffer.strip(' \t\r\n;'):
        raise MigrationError('Unvollständige SQL-Anweisung in Migration.')


def run(conn, migration):
    if callable(migration):
        migration(conn)
    else:
        for statement in statements(migration):
            conn.execute(statement)


def version(conn):
    return conn.execute('PRAGMA user_version').fetchone()[0]


def columns(conn):
    tables = [row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    return {table: [row[1] for row in conn.execute(f'PRAGMA table_info("{table}")')] for table in tables}


def expected_baseline():
    with sqlite3.connect(':memory:') as conn:
        for statement in statements(BASELINE):
            conn.execute(statement)
        return columns(conn)


def has_data(conn):
    tables = [row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    return any(conn.execute(f'SELECT 1 FROM "{table}" LIMIT 1').fetchone() for table in tables)


def backup(conn, path, current, target):
    directory = Path(path).parent / 'backups'
    directory.mkdir(mode=0o700, exist_ok=True)
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    output = directory / f'pre-migration-v{current}-v{target}-{stamp}.sqlite'
    with sqlite3.connect(output) as copy:
        conn.backup(copy)
    copy.close()
    os.chmod(output, 0o600)
    return output


def migrate(path, migrations=None):
    """Bring the database at ``path`` to the latest schema version.

    Returns the list of versions that were applied (empty if up to date).
    """
    migrations = MIGRATIONS if migrations is None else migrations
    latest = 1 + len(migrations)
    for offset, (number, _description, _migration) in enumerate(migrations):
        if number != offset + 2:
            raise MigrationError('Migrationen müssen fortlaufend ab Version 2 nummeriert sein.')
    applied = []
    conn = sqlite3.connect(path, timeout=10, isolation_level=None)
    try:
        current = version(conn)
        if current > latest:
            raise MigrationError(
                f'Die Datenbank hat Schema-Version {current}, diese Anwendung kennt nur bis {latest}. '
                'Bitte die neuere Family-OS-Version verwenden oder eine passende Sicherung einspielen.')
        if current == 0:
            conn.execute('BEGIN IMMEDIATE')
            try:
                expected = expected_baseline()
                # Existing tables must match exactly before anything is created ...
                wrong = sorted(table for table, names in columns(conn).items() if table in expected and names != expected[table])
                if wrong:
                    raise MigrationError('Unerwarteter Tabellenaufbau in bestehender Datenbank: ' + ', '.join(wrong))
                for statement in statements(BASELINE):
                    conn.execute(statement)
                # ... and afterwards every baseline table must be present.
                if any(columns(conn).get(table) != names for table, names in expected.items()):
                    raise MigrationError('Basisschema konnte nicht vollständig angelegt werden.')
                conn.execute('PRAGMA user_version=1')
                conn.execute('COMMIT')
            except BaseException:
                conn.execute('ROLLBACK')
                raise
            applied.append(1)
            current = 1
        pending = [m for m in migrations if m[0] > current]
        if pending and has_data(conn):
            backup(conn, path, current, latest)
        for number, description, migration in pending:
            conn.execute('PRAGMA foreign_keys=OFF')
            conn.execute('BEGIN IMMEDIATE')
            try:
                run(conn, migration)
                problems = conn.execute('PRAGMA foreign_key_check').fetchall()
                if problems:
                    raise MigrationError(f'Migration {number} ({description}) verletzt Fremdschlüssel: {problems[:5]}')
                conn.execute(f'PRAGMA user_version={int(number)}')
                conn.execute('COMMIT')
            except BaseException:
                conn.execute('ROLLBACK')
                raise
            finally:
                conn.execute('PRAGMA foreign_keys=ON')
            applied.append(number)
    finally:
        conn.close()
    return applied
