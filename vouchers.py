"""Shopping vouchers from PAYBACK (G-01 to G-07).

Provisional implementation decisions (O-07, see ANFORDERUNGEN.md):

* The voucher PDF (received by e-mail, G-04) is uploaded once and stored on
  the NAS under ``vouchers/`` in the data folder. There is no mailbox or iCloud
  access. The browser only ever loads the PDF from the NAS after login.
* Remaining value is maintained by hand after paying: "spent X" or "remaining
  is Y". Every change is logged. State follows the folder logic of G-06:
  active (unused), partly used (stays active), used up (archive).
* Reminder (G-02, G-03): Thursday from 9 o'clock Tobi gets the task to check
  PAYBACK offers and buy vouchers by 16:00, so that after about 24 hours plus
  one hour for the e-mail they are ready for Friday evening's shopping.
  Uploading a voucher closes the task. The reminder can be switched off.
  Offers are not fetched automatically (no source agreed, no CAPTCHA
  circumvention, G-07).
"""
from datetime import datetime, timedelta
import os
from pathlib import Path
import re
import secrets
from typing import Literal

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from integrations import TZ, notify

MAX_BYTES = 5 * 1024 * 1024
OWNER = 'tobi'  # checks offers and buys vouchers (G-01)
REMINDER_WEEKDAY = 3  # Thursday
FILE = re.compile(r'[a-f0-9]{32}\.pdf')


def now():
    return datetime.now(TZ).isoformat(timespec='seconds')


def euro(cents):
    return f'{cents // 100},{cents % 100:02d} €'


def status(row):
    if row['remaining_cents'] == 0:
        return 'used'
    return 'partial' if row['remaining_cents'] < row['value_cents'] else 'active'


class UseInput(BaseModel):
    action: Literal['spend', 'set']
    cents: int = Field(ge=0, le=100000)
    version: int


class VoucherSettings(BaseModel):
    reminder: bool


class Vouchers:
    def __init__(self, db, directory, demo):
        self.db, self.demo = db, demo
        self.folder = Path(directory) / 'vouchers'

    # --- helpers ---------------------------------------------------------

    @staticmethod
    def audit(conn, actor, action, details):
        conn.execute('INSERT INTO audit(actor,action,details,created) VALUES(?,?,?,?)', (actor, action, details, now()))

    @staticmethod
    def reminder_on(conn):
        row = conn.execute("SELECT value FROM metadata WHERE key='voucher_reminder'").fetchone()
        return row is None or row[0] == '1'

    def voucher(self, conn, voucher_id, version=None):
        row = conn.execute('SELECT * FROM vouchers WHERE id=?', (voucher_id,)).fetchone()
        if not row:
            raise HTTPException(404, 'Gutschein nicht gefunden.')
        if version is not None and row['version'] != version:
            raise HTTPException(409, 'Der Gutschein wurde inzwischen geändert. Bitte neu laden.')
        return row

    def overview(self, conn):
        rows = [dict(r) for r in conn.execute('SELECT * FROM vouchers ORDER BY remaining_cents=0, created DESC LIMIT 200')]
        uses = {}
        for use in conn.execute('SELECT * FROM voucher_uses ORDER BY id DESC LIMIT 500'):
            uses.setdefault(use['voucher_id'], []).append(dict(use))
        for row in rows:
            row['status'] = status(row)
            row['uses'] = uses.get(row['id'], [])[:10]
            del row['file']
        active = [r for r in rows if r['status'] != 'used']
        return {'vouchers': rows, 'available_cents': sum(r['remaining_cents'] for r in active),
                'reminder': self.reminder_on(conn)}

    # --- upload ----------------------------------------------------------

    def store(self, body, filename):
        if not body.startswith(b'%PDF-'):
            raise HTTPException(422, 'Bitte die Gutschein-PDF auswählen.')
        self.folder.mkdir(mode=0o700, exist_ok=True)
        name = secrets.token_hex(16) + '.pdf'
        path = self.folder / name
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'wb') as file:
            file.write(body)
        return name

    # --- background ------------------------------------------------------

    def periodic(self, instant=None):
        if self.demo:
            return
        instant = (instant or datetime.now(TZ)).astimezone(TZ)
        if instant.weekday() != REMINDER_WEEKDAY or not 9 <= instant.hour < 16:
            return
        key = f'voucher_task:{instant.date()}'
        with self.db() as conn:
            if not self.reminder_on(conn) or conn.execute('SELECT 1 FROM metadata WHERE key=?', (key,)).fetchone():
                return
            if not conn.execute('SELECT 1 FROM users WHERE id=?', (OWNER,)).fetchone():
                return
            due = instant.replace(hour=16, minute=0, second=0, microsecond=0)
            details = ('PAYBACK-Aktionen prüfen und Wunschgutscheine kaufen. Umwandlung dauert etwa 24 Stunden, '
                       'die E-Mail etwa eine weitere Stunde: bis 16 Uhr gekauft ist der Gutschein zum Einkauf am '
                       'Freitagabend bereit. Die PDF danach unter Essen & Einkauf ablegen.')
            cursor = conn.execute('INSERT INTO tasks(owner,title,details,due,created) VALUES(?,?,?,?,?)',
                                  (OWNER, 'Gutscheine vorbereiten', details, due.isoformat(), now()))
            conn.execute('INSERT INTO metadata VALUES(?,?)', (key, str(cursor.lastrowid)))
            notify(conn, OWNER, key, 'Gutscheine vorbereiten', 'PAYBACK-Aktionen prüfen; bis 16 Uhr kaufen, damit der Gutschein Freitagabend bereit ist.', False, instant)

    def close_reminder(self, conn):
        """A voucher uploaded in the days before shopping settles this week's task."""
        today = datetime.now(TZ).date()
        for offset in range(0, 3):
            row = conn.execute('SELECT value FROM metadata WHERE key=?', (f'voucher_task:{today - timedelta(days=offset)}',)).fetchone()
            if row:
                conn.execute("UPDATE tasks SET state='done' WHERE id=? AND state='open'", (int(row[0]),))

    # --- routes ----------------------------------------------------------

    def routes(self, app, identity):
        db = self.db

        @app.get('/api/vouchers')
        def overview(request: Request):
            with db() as conn:
                identity(request, conn)
                return self.overview(conn)

        @app.post('/api/vouchers')
        async def upload(request: Request, value_cents: int, store: str = 'Kaufland', note: str = '', filename: str = 'Gutschein.pdf'):
            if not 1 <= value_cents <= 100000:
                raise HTTPException(422, 'Bitte den Gutscheinwert angeben.')
            if len(store) > 60 or len(note) > 200 or len(filename) > 200:
                raise HTTPException(422, 'Angaben zu lang.')
            with db() as conn:
                actor = identity(request, conn)  # before reading any upload data
            length = int(request.headers.get('content-length') or 0)
            if length > MAX_BYTES:
                raise HTTPException(413, 'Die PDF ist größer als 5 MB.')
            body = b''
            async for chunk in request.stream():
                body += chunk
                if len(body) > MAX_BYTES:
                    raise HTTPException(413, 'Die PDF ist größer als 5 MB.')
            name = self.store(body, filename)
            try:
                with db() as conn:
                    cursor = conn.execute('INSERT INTO vouchers(store,value_cents,remaining_cents,note,file,filename,size,uploaded_by,created,updated) '
                                          'VALUES(?,?,?,?,?,?,?,?,?,?)',
                                          (store.strip() or 'Kaufland', value_cents, value_cents, note.strip(), name,
                                           Path(filename).name, len(body), actor, now(), now()))
                    self.audit(conn, actor, 'Gutschein abgelegt', f'{store.strip() or "Kaufland"} · {euro(value_cents)}')
                    self.close_reminder(conn)
                    return {'id': cursor.lastrowid}
            except BaseException:
                (self.folder / name).unlink(missing_ok=True)
                raise

        @app.get('/api/vouchers/{voucher_id}/pdf')
        def pdf(voucher_id: int, request: Request):
            with db() as conn:
                identity(request, conn)
                row = self.voucher(conn, voucher_id)
            if not FILE.fullmatch(row['file']) or not (self.folder / row['file']).exists():
                raise HTTPException(404, 'Die PDF fehlt auf dem NAS. Bitte aus der Sicherung wiederherstellen.')
            return FileResponse(self.folder / row['file'], media_type='application/pdf',
                                headers={'Content-Disposition': 'inline; filename="Gutschein.pdf"'})

        @app.post('/api/vouchers/{voucher_id}/use')
        def use(voucher_id: int, data: UseInput, request: Request):
            with db() as conn:
                actor = identity(request, conn)
                row = self.voucher(conn, voucher_id, data.version)
                after = row['remaining_cents'] - data.cents if data.action == 'spend' else data.cents
                if after < 0:
                    raise HTTPException(422, f"Der Restbetrag ist nur {euro(row['remaining_cents'])}.")
                if after > row['value_cents']:
                    raise HTTPException(422, f"Der Rest kann nicht höher als der Wert ({euro(row['value_cents'])}) sein.")
                if after == row['remaining_cents']:
                    raise HTTPException(422, 'Der Restbetrag bleibt gleich.')
                conn.execute('UPDATE vouchers SET remaining_cents=?,version=version+1,updated=? WHERE id=?', (after, now(), voucher_id))
                conn.execute('INSERT INTO voucher_uses(voucher_id,before_cents,after_cents,actor,created) VALUES(?,?,?,?,?)',
                             (voucher_id, row['remaining_cents'], after, actor, now()))
                self.audit(conn, actor, 'Gutschein verwendet' if after < row['remaining_cents'] else 'Gutschein korrigiert',
                           f"{row['store']}: {euro(row['remaining_cents'])} → {euro(after)}")
                return self.overview(conn)

        @app.post('/api/vouchers/settings')
        def settings(data: VoucherSettings, request: Request):
            with db() as conn:
                actor = identity(request, conn)
                conn.execute("INSERT OR REPLACE INTO metadata VALUES('voucher_reminder',?)", ('1' if data.reminder else '0',))
                self.audit(conn, actor, 'Gutschein-Erinnerung ' + ('eingeschaltet' if data.reminder else 'ausgeschaltet'), 'Donnerstag 9 Uhr')
                return self.overview(conn)
