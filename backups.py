"""Automatic daily backup of database and keys (Q-01).

* Once per day from FOS_BACKUP_HOUR (default 3 o'clock) a consistent copy of
  the database is written with the SQLite backup API, together with the
  voucher PDFs (``vouchers/``) and the keys
  that are needed to read stored tokens (integration.key, push-private.pem,
  Google client file). A missed run is caught up on the next background tick.
* Each backup is written into a temporary folder, checked with
  ``PRAGMA integrity_check`` and only then renamed to its final date folder.
  An incomplete folder is never counted as a backup.
* The newest FOS_BACKUP_KEEP (default 14) date folders are kept; only folders
  created by this module are removed.
* A failure is shown in the app and sent to Tobi once per day. A new attempt
  follows after one hour. Nothing is reported as successful unless the copy
  passed the integrity check.

The backup folder lives on the NAS. It does not replace a copy to a separate
target (see README.md).
"""
from datetime import datetime, timedelta
import json
import logging
import os
from pathlib import Path
import re
import shutil
import sqlite3
import time

from integrations import TZ, notify

LOG = logging.getLogger('family-os')
FOLDER = re.compile(r'\d{4}-\d{2}-\d{2}')
OWNER = 'tobi'
RETRY_SECONDS = 3600


def env_int(name, default, low, high):
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        return default
    return min(max(value, low), high)


class AutoBackup:
    def __init__(self, db, db_path, directory, demo, client_file=''):
        self.db, self.demo = db, demo
        self.db_path = Path(db_path)
        self.data = Path(directory)
        self.target = Path(os.getenv('FOS_BACKUP_DIR', str(self.data / 'backups' / 'auto')))
        self.keep = env_int('FOS_BACKUP_KEEP', 14, 1, 365)
        self.hour = env_int('FOS_BACKUP_HOUR', 3, 0, 23)
        self.client_file = client_file

    # --- state -----------------------------------------------------------

    def load(self, conn):
        row = conn.execute("SELECT value FROM metadata WHERE key='backup_status'").fetchone()
        return json.loads(row[0]) if row else {}

    def save(self, value):
        with self.db() as conn:
            conn.execute("INSERT OR REPLACE INTO metadata VALUES('backup_status',?)", (json.dumps(value),))

    def status(self, conn):
        value = self.load(conn)
        return {
            'enabled': not self.demo,
            'last_ok': value.get('last_ok'),
            'last_folder': value.get('last_folder'),
            'error': value.get('error'),
            'error_time': value.get('error_time'),
            'keep': self.keep,
            'hour': self.hour,
            'count': len(self.folders()) if not self.demo else 0,
        }

    def folders(self):
        if not self.target.is_dir():
            return []
        return sorted(p for p in self.target.iterdir() if p.is_dir() and FOLDER.fullmatch(p.name))

    # --- schedule --------------------------------------------------------

    def due(self, instant, value):
        if instant.hour < self.hour:
            return False
        if value.get('last_date') == str(instant.date()):
            return False
        return time.time() >= value.get('next_try', 0)

    def periodic(self, instant=None):
        if self.demo:
            return
        instant = (instant or datetime.now(TZ)).astimezone(TZ)
        with self.db() as conn:
            value = self.load(conn)
        if not self.due(instant, value):
            return
        try:
            folder = self.create(instant.date())
        except Exception as error:
            self.failed(instant, value, error)
            return
        removed = self.prune()
        value.update(last_date=str(instant.date()), last_ok=instant.isoformat(timespec='seconds'),
                     last_folder=folder.name, error=None, error_time=None, next_try=0)
        self.save(value)
        LOG.info('Automatische Sicherung erstellt: %s (%d ältere entfernt)', folder.name, removed)

    def failed(self, instant, value, error):
        # No exception text: paths are fine, but keep logs predictable and short.
        reason = type(error).__name__
        LOG.error('Automatische Sicherung fehlgeschlagen: %s', reason)
        value.update(error=self.explain(error), error_time=instant.isoformat(timespec='seconds'),
                     next_try=time.time() + RETRY_SECONDS)
        self.save(value)
        with self.db() as conn:
            if conn.execute('SELECT 1 FROM users WHERE id=?', (OWNER,)).fetchone():
                notify(conn, OWNER, f'backup-failed:{instant.date()}', 'Sicherung fehlgeschlagen',
                       'Die automatische Sicherung konnte nicht erstellt werden. Bitte unter Verbindungen prüfen. '
                       'Ein neuer Versuch folgt in einer Stunde.', False, instant)

    @staticmethod
    def explain(error):
        if isinstance(error, OSError):
            return 'Das Sicherungsverzeichnis ist nicht beschreibbar oder voll.'
        if isinstance(error, sqlite3.Error):
            return 'Die Datenbank konnte nicht konsistent kopiert werden.'
        if isinstance(error, IntegrityError):
            return str(error)
        return 'Unerwarteter Fehler beim Sichern.'

    # --- work ------------------------------------------------------------

    def key_files(self):
        files = [(self.data / 'integration.key', 'integration.key'),
                 (self.data / 'push-private.pem', 'push-private.pem')]
        if self.client_file:
            files.append((Path(self.client_file), 'google-client.json'))
        return [(source, name) for source, name in files if source.exists()]

    def create(self, day):
        self.target.mkdir(mode=0o700, parents=True, exist_ok=True)
        final = self.target / str(day)
        if final.exists():
            return final
        partial = self.target / f'.{day}.partial'
        if partial.exists():
            shutil.rmtree(partial)
        partial.mkdir(mode=0o700)
        try:
            copy = partial / self.db_path.name
            with sqlite3.connect(self.db_path, timeout=30) as source, sqlite3.connect(copy) as target:
                source.backup(target)
            source.close()
            target.close()
            os.chmod(copy, 0o600)
            if self.verify(copy) != 'ok':
                raise IntegrityError('Die Sicherungskopie hat die Integritätsprüfung nicht bestanden.')
            vouchers = self.data / 'vouchers'
            if vouchers.is_dir():
                shutil.copytree(vouchers, partial / 'vouchers')
                os.chmod(partial / 'vouchers', 0o700)
            keys = self.key_files()
            if keys:
                (partial / 'keys').mkdir(mode=0o700)
                for source, name in keys:
                    shutil.copyfile(source, partial / 'keys' / name)
                    os.chmod(partial / 'keys' / name, 0o600)
            partial.rename(final)
        except BaseException:
            shutil.rmtree(partial, ignore_errors=True)
            raise
        return final

    @staticmethod
    def verify(copy):
        conn = sqlite3.connect(copy)
        try:
            return conn.execute('PRAGMA integrity_check').fetchone()[0]
        finally:
            conn.close()

    def prune(self):
        folders = self.folders()
        removed = 0
        for folder in folders[:-self.keep]:
            shutil.rmtree(folder)
            removed += 1
        return removed


class IntegrityError(Exception):
    pass
