from pathlib import Path
import sqlite3
import tempfile
import unittest

from app import create_app
import migrations
from migrations import BASELINE, LATEST, MigrationError, migrate, statements


def legacy_database(path, skip=()):
    """Create a database as written before schema versioning (user_version 0)."""
    with sqlite3.connect(path) as conn:
        for statement in statements(BASELINE):
            if not any(name in statement for name in skip):
                conn.execute(statement)
        conn.execute("INSERT INTO users(id,password,totp) VALUES('tobi','x','y')")
        conn.execute("INSERT INTO appointments(day,kind,owner,start,end,version) VALUES('2026-10-05','bring','tobi','07:45','08:45',1)")
        conn.execute("INSERT INTO metadata VALUES('mode','demo')")
    conn.close()


def user_version(path):
    with sqlite3.connect(path) as conn:
        value = conn.execute('PRAGMA user_version').fetchone()[0]
    conn.close()
    return value


def column_names(path, table):
    with sqlite3.connect(path) as conn:
        names = [row[1] for row in conn.execute(f'PRAGMA table_info({table})')]
    conn.close()
    return names


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.path = self.dir / 'family.sqlite'

    def tearDown(self):
        self.tmp.cleanup()

    def backups(self):
        folder = self.dir / 'backups'
        return sorted(folder.iterdir()) if folder.exists() else []

    def test_fresh_database_gets_latest_version(self):
        self.assertEqual(migrate(self.path), list(range(1, LATEST + 1)))
        self.assertEqual(user_version(self.path), LATEST)
        self.assertEqual(migrate(self.path), [])
        self.assertEqual(self.backups(), [])

    def test_existing_unversioned_database_is_adopted_without_data_loss(self):
        legacy_database(self.path)
        self.assertEqual(migrate(self.path)[0], 1)
        with sqlite3.connect(self.path) as conn:
            self.assertEqual(conn.execute('SELECT owner,start FROM appointments').fetchall(), [('tobi', '07:45')])
        conn.close()

    def test_oldest_production_shape_receives_later_tables(self):
        legacy_database(self.path, skip=('planning_sessions', 'meal_cache', 'meal_operations'))
        migrate(self.path)
        self.assertIn('ended', column_names(self.path, 'planning_sessions'))
        self.assertIn('payload', column_names(self.path, 'meal_operations'))

    def test_unexpected_legacy_layout_is_refused_and_left_untouched(self):
        with sqlite3.connect(self.path) as conn:
            conn.execute('CREATE TABLE tasks(id INTEGER PRIMARY KEY, title TEXT)')
        conn.close()
        with self.assertRaises(MigrationError):
            migrate(self.path)
        self.assertEqual(user_version(self.path), 0)
        self.assertEqual(column_names(self.path, 'tasks'), ['id', 'title'])
        self.assertEqual(column_names(self.path, 'users'), [])

    def test_newer_database_is_refused(self):
        migrate(self.path)
        with sqlite3.connect(self.path) as conn:
            conn.execute(f'PRAGMA user_version={LATEST + 1}')
        conn.close()
        with self.assertRaises(MigrationError):
            migrate(self.path)
        with self.assertRaises(MigrationError):
            create_app(self.path, demo=True)

    def test_migration_is_applied_after_backup(self):
        legacy_database(self.path)
        migrate(self.path)
        steps = [(LATEST + 1, 'Notiz an Terminen', 'ALTER TABLE appointments ADD COLUMN note TEXT NOT NULL DEFAULT \'\';')]
        steps = migrations.MIGRATIONS + steps
        self.assertEqual(migrate(self.path, steps), [LATEST + 1])
        self.assertIn('note', column_names(self.path, 'appointments'))
        self.assertEqual(user_version(self.path), LATEST + 1)
        [backup] = [b for b in self.backups() if b.name.startswith(f'pre-migration-v{LATEST}-v{LATEST + 1}-')]
        self.assertEqual(user_version(backup), LATEST)
        self.assertNotIn('note', column_names(backup, 'appointments'))
        self.assertEqual(backup.stat().st_mode & 0o777, 0o600)
        self.assertEqual(migrate(self.path, steps), [])

    def test_failing_migration_rolls_back_completely(self):
        migrate(self.path)

        def broken(conn):
            conn.execute('ALTER TABLE tasks ADD COLUMN extra TEXT')
            raise RuntimeError('Abbruch mitten in der Migration')

        with self.assertRaises(RuntimeError):
            migrate(self.path, migrations.MIGRATIONS + [(LATEST + 1, 'kaputt', broken)])
        self.assertEqual(user_version(self.path), LATEST)
        self.assertNotIn('extra', column_names(self.path, 'tasks'))

    def test_foreign_key_violation_rolls_back(self):
        migrate(self.path)
        step = (LATEST + 1, 'verwaiste Aufgabe', "INSERT INTO tasks(owner,title,details,due,created) VALUES('niemand','t','d','2026-10-01','x');")
        with self.assertRaises(MigrationError):
            migrate(self.path, migrations.MIGRATIONS + [step])
        self.assertEqual(user_version(self.path), LATEST)
        with sqlite3.connect(self.path) as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM tasks').fetchone()[0], 0)
        conn.close()

    def test_table_rebuild_with_foreign_keys(self):
        legacy_database(self.path)
        migrate(self.path)
        rebuild = '''
        CREATE TABLE appointments_new(id INTEGER PRIMARY KEY, day TEXT NOT NULL, kind TEXT NOT NULL CHECK(kind IN ('bring','pickup','nanny')), owner TEXT REFERENCES users(id), start TEXT, end TEXT, version INTEGER NOT NULL DEFAULT 0, UNIQUE(day,kind));
        INSERT INTO appointments_new SELECT * FROM appointments;
        DROP TABLE appointments;
        ALTER TABLE appointments_new RENAME TO appointments;
        CREATE INDEX IF NOT EXISTS appointments_day ON appointments(day);
        '''
        migrate(self.path, migrations.MIGRATIONS + [(LATEST + 1, 'Nanny-Art', rebuild)])
        with sqlite3.connect(self.path) as conn:
            conn.execute("INSERT INTO appointments(day,kind) VALUES('2026-10-06','nanny')")
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM appointments').fetchone()[0], 2)
        conn.close()

    def test_version_numbers_must_be_consecutive(self):
        with self.assertRaises(MigrationError):
            migrate(self.path, [(3, 'Lücke', 'SELECT 1;')])

    def test_closures_migration_keeps_existing_nanny_and_task_data(self):
        legacy_database(self.path)
        migrate(self.path, migrations.MIGRATIONS[:1])  # production state before version 3
        self.assertEqual(user_version(self.path), 2)
        with sqlite3.connect(self.path) as conn:
            conn.execute("INSERT INTO nanny_shifts(day,start,end,state,creator,created,updated) VALUES('2026-10-07','16:00','18:00','confirmed','tobi','x','x')")
            conn.execute("INSERT INTO tasks(owner,title,details,due,created,nanny_shift_id) VALUES('tobi','Nanny anfragen','d','2026-10-01','x',1)")
        conn.close()
        self.assertEqual(migrate(self.path), [3])
        with sqlite3.connect(self.path) as conn:
            self.assertEqual(conn.execute('SELECT day,state FROM nanny_shifts').fetchall(), [('2026-10-07', 'confirmed')])
            self.assertEqual(conn.execute('SELECT title,nanny_shift_id FROM tasks').fetchall(), [('Nanny anfragen', 1)])
            self.assertEqual(conn.execute('SELECT owner FROM appointments').fetchall(), [('tobi',)])
            conn.execute("INSERT INTO day_closures(day,kind,batch,creator,created) VALUES('2026-10-08','closed','b','tobi','x')")
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("INSERT INTO day_closures(day,kind,batch,creator,created) VALUES('2026-10-09','party','b','tobi','x')")
        conn.close()
        self.assertTrue(any(b.name.startswith('pre-migration-v2-v3-') for b in self.backups()))

    def test_statement_splitting_handles_triggers(self):
        script = "CREATE TABLE a(x); CREATE TRIGGER t AFTER INSERT ON a BEGIN UPDATE a SET x=1; END; SELECT 1;"
        self.assertEqual(len(list(statements(script))), 3)


if __name__ == '__main__':
    unittest.main()
