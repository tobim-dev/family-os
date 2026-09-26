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

# Append new schema changes here as (version, description, migration).
# ``migration`` is either an SQL script (str) or a callable taking the
# connection. Versions must be consecutive, starting at 2.
MIGRATIONS = []

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
