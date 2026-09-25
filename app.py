"""Family OS: self-hosted care planning, approvals and personal tasks."""
from contextlib import contextmanager
from datetime import date, datetime, timedelta
import calendar
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import sqlite3
import time
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
import pyotp
from integrations import Integrations, notify

ROOT = Path(__file__).parent
TZ = ZoneInfo('Europe/Berlin')
PEOPLE = {'tobi': 'Tobi', 'britta': 'Britta'}


def now():
    return datetime.now(TZ).isoformat(timespec='seconds')


def password_hash(password, salt=None):
    salt = salt or secrets.token_hex(16)
    value = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()
    return salt + ':' + value


def password_ok(password, stored):
    return hmac.compare_digest(password_hash(password, stored.split(':')[0]), stored)


SCHEMA = '''
PRAGMA foreign_keys=ON;
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
CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
'''


class Login(BaseModel):
    user: Literal['tobi', 'britta']
    password: str = Field(default='', max_length=128)
    code: str = Field(default='', max_length=8)


class ProposalInput(BaseModel):
    day: date
    kind: Literal['bring', 'pickup']
    owner: Literal['tobi', 'britta']
    start: str = Field(pattern=r'^([01]\d|2[0-3]):[0-5]\d$')
    end: str = Field(pattern=r'^([01]\d|2[0-3]):[0-5]\d$')
    expected_version: int = Field(ge=0)
    reason: str = Field(min_length=1, max_length=500)
    deadline: datetime
    issue_id: int | None = Field(default=None, ge=1)


class Decision(BaseModel):
    action: Literal['approve', 'reject', 'withdraw']


class Bulk(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=64)


class IssueInput(BaseModel):
    appointment_id: int | None = Field(default=None, ge=1)
    text: str = Field(min_length=1, max_length=500)
    deadline: datetime


class ResolveInput(BaseModel):
    version: int
    resolution: str = Field(min_length=1, max_length=500)


class MonthInput(BaseModel):
    month: str = Field(pattern=r'^\d{4}-\d{2}$')
    bring_start: str = Field(pattern=r'^([01]\d|2[0-3]):[0-5]\d$')
    bring_end: str = Field(pattern=r'^([01]\d|2[0-3]):[0-5]\d$')
    pickup_start: str = Field(pattern=r'^([01]\d|2[0-3]):[0-5]\d$')
    pickup_end: str = Field(pattern=r'^([01]\d|2[0-3]):[0-5]\d$')


def deadline_value(value):
    if value.tzinfo is None:
        raise HTTPException(422, 'Die Antwortfrist benötigt eine Zeitzone.')
    if value <= datetime.now(TZ):
        raise HTTPException(422, 'Die Antwortfrist muss in der Zukunft liegen.')
    return value.astimezone(TZ).isoformat(timespec='seconds')


def month_bounds(month):
    try:
        first = date.fromisoformat(month + '-01')
        return first, first.replace(day=calendar.monthrange(first.year, first.month)[1])
    except ValueError:
        raise HTTPException(422, 'Ungültiger Monat.')


def create_app(db_path=None, demo=None, origin=None):
    demo = os.getenv('FOS_DEMO') == '1' if demo is None else demo
    origin = origin or os.getenv('FOS_ORIGIN', 'http://127.0.0.1:8765' if demo else '')
    if not origin or (not demo and not origin.startswith('https://')):
        raise RuntimeError('FOS_ORIGIN muss für den Regelbetrieb eine HTTPS-Adresse enthalten.')
    if demo and origin not in ('http://127.0.0.1:8765', 'http://localhost:8765'):
        raise RuntimeError('Demomodus ist nur lokal verfügbar.')
    path = Path(db_path or os.getenv('FOS_DB', str(ROOT / 'data' / ('demo.sqlite' if demo else 'family.sqlite'))))
    path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def db():
        conn = sqlite3.connect(path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA foreign_keys=ON')
        try:
            conn.execute('BEGIN IMMEDIATE')
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    with sqlite3.connect(path) as conn:
        conn.executescript(SCHEMA)
        stored = conn.execute("SELECT value FROM metadata WHERE key='mode'").fetchone()
        mode = 'demo' if demo else 'production'
        if stored and stored[0] != mode:
            raise RuntimeError('Demo- und echte Daten benötigen getrennte Datenbanken.')
        conn.execute("INSERT OR IGNORE INTO metadata VALUES('mode',?)", (mode,))
        if demo:
            for user in PEOPLE:
                conn.execute('INSERT OR IGNORE INTO users(id,password,totp) VALUES(?,?,?)', (user, password_hash(secrets.token_hex(24)), pyotp.random_base32()))
    os.chmod(path, 0o600)

    integrations = Integrations(db, path.parent, demo, origin)
    app = FastAPI(title='Family OS', docs_url=None, redoc_url=None, openapi_url=None, lifespan=integrations.lifespan)
    app.state.integrations = integrations
    app.state.db = db
    app.state.demo = demo

    @app.middleware('http')
    async def secure(request, call_next):
        if demo and request.client and request.client.host not in ('127.0.0.1', '::1', 'testclient'):
            return JSONResponse({'detail': 'Die Demo ist nur lokal verfügbar.'}, status_code=403)
        if request.method not in ('GET', 'HEAD', 'OPTIONS'):
            if request.headers.get('origin') != origin or request.headers.get('x-family-request') != '1':
                return JSONResponse({'detail': 'Ungültiger Anfrageursprung.'}, status_code=403)
        response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        return response

    def identity(request, conn):
        token = hashlib.sha256(request.cookies.get('fos_session', '').encode()).hexdigest()
        row = conn.execute('SELECT user_id FROM sessions WHERE token=? AND expires>?', (token, time.time())).fetchone()
        if not row:
            raise HTTPException(401, 'Bitte anmelden.')
        return row['user_id']

    def require_household(conn):
        present = {row[0] for row in conn.execute('SELECT id FROM users')}
        missing = [name for key, name in PEOPLE.items() if key not in present]
        if missing:
            raise HTTPException(409, 'Bitte zuerst das Family-OS-Konto für ' + ' und '.join(missing) + ' auf dem NAS einrichten. Gemeinsame Abstimmungen benötigen beide Konten.')

    def audit(conn, actor, action, details):
        conn.execute('INSERT INTO audit(actor,action,details,created) VALUES(?,?,?,?)', (actor, action, details, now()))

    integrations.routes(app, identity, ROOT / 'static')

    @app.get('/api/config')
    def config():
        return {'demo': demo, 'people': PEOPLE}

    @app.post('/api/login')
    def login(data: Login, request: Request):
        error = None
        with db() as conn:
            key = data.user + ':' + (request.client.host if request.client else '')
            attempt = conn.execute('SELECT * FROM attempts WHERE key=?', (key,)).fetchone()
            if attempt and attempt['until'] > time.time() and attempt['count'] >= 8:
                error = HTTPException(429, 'Zu viele Versuche. Bitte in 15 Minuten erneut versuchen.')
            else:
                row = conn.execute('SELECT * FROM users WHERE id=?', (data.user,)).fetchone()
                step = int(time.time() // 30)
                matched = None
                if row and not demo and password_ok(data.password, row['password']):
                    for candidate in (step - 1, step, step + 1):
                        if candidate > row['last_step'] and hmac.compare_digest(pyotp.TOTP(row['totp']).at(candidate * 30), data.code):
                            matched = candidate
                if row and (demo or matched is not None):
                    if not demo:
                        conn.execute('UPDATE users SET last_step=? WHERE id=?', (matched, data.user))
                    conn.execute('DELETE FROM attempts WHERE key=?', (key,))
                    conn.execute('DELETE FROM sessions WHERE expires<?', (time.time(),))
                    token = secrets.token_urlsafe(32)
                    conn.execute('INSERT INTO sessions VALUES(?,?,?)', (hashlib.sha256(token.encode()).hexdigest(), data.user, time.time() + 43200))
                    audit(conn, data.user, 'Anmeldung', 'Neue Sitzung')
                else:
                    count = attempt['count'] + 1 if attempt and attempt['until'] > time.time() else 1
                    until = attempt['until'] if attempt and attempt['until'] > time.time() else time.time() + 900
                    conn.execute('INSERT OR REPLACE INTO attempts VALUES(?,?,?)', (key, count, until))
                    error = HTTPException(401, 'Anmeldung nicht möglich. Zugangsdaten und neuen Bestätigungscode prüfen.')
        if error:
            raise error
        response = JSONResponse({'user': data.user})
        response.set_cookie('fos_session', token, httponly=True, secure=not demo, samesite='strict', max_age=43200, path='/')
        return response

    @app.post('/api/logout')
    def logout(request: Request):
        with db() as conn:
            conn.execute('DELETE FROM sessions WHERE token=?', (hashlib.sha256(request.cookies.get('fos_session', '').encode()).hexdigest(),))
        response = JSONResponse({'ok': True})
        response.delete_cookie('fos_session', path='/')
        return response

    @app.get('/api/state')
    def state(request: Request, month: str):
        first, last = month_bounds(month)
        with db() as conn:
            user = identity(request, conn)
            appointments = [dict(r) for r in conn.execute('SELECT * FROM appointments WHERE day BETWEEN ? AND ? ORDER BY day,kind', (str(first), str(last)))]
            proposals = [dict(r) for r in conn.execute("SELECT p.*,a.day,a.kind,a.owner AS current_owner FROM proposals p JOIN appointments a ON a.id=p.appointment_id WHERE p.state='pending' ORDER BY p.deadline")]
            issues = [dict(r) for r in conn.execute("SELECT i.*,a.day,a.kind FROM issues i LEFT JOIN appointments a ON a.id=i.appointment_id WHERE i.state='open' ORDER BY i.deadline")]
            tasks = [dict(r) for r in conn.execute("SELECT * FROM tasks WHERE state IN ('open','done') ORDER BY state DESC,due,id DESC LIMIT 200")]
            history = [dict(r) for r in conn.execute('SELECT * FROM audit ORDER BY id DESC LIMIT 30')]
        return {'user': user, 'month': month, 'today': str(datetime.now(TZ).date()), 'appointments': appointments, 'proposals': proposals, 'issues': issues, 'tasks': tasks, 'history': history, 'demo': demo}

    @app.post('/api/proposals')
    def propose(data: ProposalInput, request: Request):
        if data.day.weekday() > 4 or data.end <= data.start or not data.reason.strip():
            raise HTTPException(422, 'Bitte einen Werktag, einen Grund und ein gültiges Zeitfenster wählen.')
        deadline = deadline_value(data.deadline)
        with db() as conn:
            actor = identity(request, conn)
            require_household(conn)
            conn.execute('INSERT OR IGNORE INTO appointments(day,kind) VALUES(?,?)', (str(data.day), data.kind))
            slot = conn.execute('SELECT * FROM appointments WHERE day=? AND kind=?', (str(data.day), data.kind)).fetchone()
            if slot['version'] != data.expected_version:
                raise HTTPException(409, 'Dieser Termin hat sich geändert. Bitte neu laden.')
            if conn.execute("SELECT id FROM proposals WHERE appointment_id=? AND state='pending'", (slot['id'],)).fetchone():
                raise HTTPException(409, 'Für diesen Termin gibt es bereits einen offenen Vorschlag.')
            if slot['owner'] == data.owner and slot['start'] == data.start and slot['end'] == data.end:
                raise HTTPException(422, 'Dieser Vorschlag entspricht bereits der bestätigten Planung.')
            if data.issue_id:
                issue = conn.execute("SELECT * FROM issues WHERE id=? AND state='open'", (data.issue_id,)).fetchone()
                if not issue or issue['appointment_id'] != slot['id']:
                    raise HTTPException(409, 'Der Klärungspunkt passt nicht zu diesem Termin.')
            cursor = conn.execute('INSERT INTO proposals(appointment_id,owner,start,end,creator,reason,deadline,base_version,created,issue_id) VALUES(?,?,?,?,?,?,?,?,?,?)', (slot['id'],data.owner,data.start,data.end,actor,data.reason.strip(),deadline,slot['version'],now(),data.issue_id))
            audit(conn, actor, 'Vorschlag erstellt', f'{data.day}: {"Bringen" if data.kind == "bring" else "Abholen"} → {PEOPLE[data.owner]}')
            notify(conn, 'britta' if actor == 'tobi' else 'tobi', f'proposal:{cursor.lastrowid}', 'Neue Terminabstimmung', f'{data.day}: Ein Betreuungsvorschlag wartet auf deine Zustimmung.')
            return {'id': cursor.lastrowid}

    def approve(conn, actor, proposal_id, send_notice=True):
        proposal = conn.execute('SELECT * FROM proposals WHERE id=?', (proposal_id,)).fetchone()
        if not proposal or proposal['state'] != 'pending':
            raise HTTPException(409, 'Dieser Vorschlag ist nicht mehr offen.')
        if proposal['creator'] == actor:
            raise HTTPException(403, 'Der andere muss deinen Vorschlag bestätigen.')
        slot = conn.execute('SELECT * FROM appointments WHERE id=?', (proposal['appointment_id'],)).fetchone()
        if slot['version'] != proposal['base_version']:
            raise HTTPException(409, 'Die bestätigte Planung hat sich inzwischen geändert.')
        conn.execute('UPDATE appointments SET owner=?,start=?,end=?,version=version+1 WHERE id=?', (proposal['owner'],proposal['start'],proposal['end'],slot['id']))
        conn.execute("UPDATE proposals SET state='accepted' WHERE id=?", (proposal_id,))
        # Replace obsolete pending reminders with the latest required action.
        conn.execute("UPDATE tasks SET state='superseded' WHERE appointment_id=? AND state='open'", (slot['id'],))
        kind = 'Lina bringen' if slot['kind'] == 'bring' else 'Lina abholen'
        for owner in {slot['owner'], proposal['owner']} - {None}:
            details = (f"{slot['day']} · {kind}: {proposal['start']}–{proposal['end']} als abwesend eintragen."
                       if owner == proposal['owner'] else f"{slot['day']} · {kind}: bisherigen Block entfernen; {PEOPLE[proposal['owner']]} übernimmt.")
            conn.execute('INSERT INTO tasks(appointment_id,owner,title,details,due,created) VALUES(?,?,?,?,?,?)', (slot['id'],owner,'Arbeitskalender aktualisieren',details,now(),now()))
        if proposal['issue_id']:
            conn.execute("UPDATE issues SET state='resolved',version=version+1,resolution=? WHERE id=? AND state='open'", ('Gemeinsam bestätigte Neuplanung', proposal['issue_id']))
        if send_notice:
            notify(conn, proposal['creator'], f'approved:{proposal_id}', 'Planung gemeinsam bestätigt', f"{slot['day']}: Betreuung bestätigt. Bitte deine Aufgaben und den Übertragungsstatus prüfen.")
        audit(conn, actor, 'Planung bestätigt', f"{slot['day']} · {kind}: {PEOPLE[proposal['owner']]} übernimmt.")

    @app.post('/api/proposals/{proposal_id}/decision')
    def decide(proposal_id: int, data: Decision, request: Request):
        with db() as conn:
            actor = identity(request, conn)
            proposal = conn.execute("SELECT * FROM proposals WHERE id=? AND state='pending'", (proposal_id,)).fetchone()
            if not proposal:
                raise HTTPException(409, 'Dieser Vorschlag ist nicht mehr offen.')
            if data.action == 'approve':
                approve(conn, actor, proposal_id)
            else:
                if (data.action == 'withdraw') != (proposal['creator'] == actor):
                    raise HTTPException(403, 'Diese Entscheidung steht der anderen Person zu.')
                conn.execute('UPDATE proposals SET state=? WHERE id=?', ('withdrawn' if data.action == 'withdraw' else 'rejected',proposal_id))
                notify(conn, 'britta' if actor == 'tobi' else 'tobi', f'closed:{proposal_id}', 'Vorschlag zurückgezogen' if data.action == 'withdraw' else 'Vorschlag abgelehnt', 'Die bisherige Zuordnung bleibt gültig. Bitte die weitere Planung abstimmen.')
                audit(conn, actor, 'Vorschlag zurückgezogen' if data.action == 'withdraw' else 'Vorschlag abgelehnt', f"Vorschlag {proposal_id}; bisherige Zuordnung bleibt gültig.")
        return {'ok': True}

    @app.post('/api/proposals/approve-batch')
    def approve_batch(data: Bulk, request: Request):
        if len(set(data.ids)) != len(data.ids):
            raise HTTPException(422, 'Doppelte Vorschläge.')
        with db() as conn:
            actor = identity(request, conn)
            for proposal_id in data.ids:
                approve(conn, actor, proposal_id, send_notice=False)
            notify(conn, 'britta' if actor == 'tobi' else 'tobi', 'approved-batch:' + hashlib.sha256(str(sorted(data.ids)).encode()).hexdigest(), 'Planung gemeinsam bestätigt', f'{len(data.ids)} Betreuungsvorschläge wurden bestätigt. Bitte die Aufgaben zur Arbeitskalenderpflege prüfen.')
        return {'ok': True}

    @app.post('/api/month-draft')
    def month_draft(data: MonthInput, request: Request):
        first, last = month_bounds(data.month)
        if data.bring_end <= data.bring_start or data.pickup_end <= data.pickup_start:
            raise HTTPException(422, 'Die Endzeit muss nach der Startzeit liegen.')
        with db() as conn:
            actor = identity(request, conn)
            require_household(conn)
            if conn.execute('SELECT id FROM appointments WHERE day BETWEEN ? AND ?', (str(first), str(last))).fetchone():
                raise HTTPException(409, 'Der Monat enthält bereits Termine. Bitte einzeln ergänzen.')
            created = 0
            day = first
            while day <= last:
                if day.weekday() < 5:
                    for kind in ('bring', 'pickup'):
                        # Alternate responsibilities across days, five each per complete week.
                        owner = 'tobi' if (day.weekday() + (kind == 'pickup')) % 2 == 0 else 'britta'
                        cursor = conn.execute('INSERT INTO appointments(day,kind) VALUES(?,?)', (str(day),kind))
                        start = data.bring_start if kind == 'bring' else data.pickup_start
                        end = data.bring_end if kind == 'bring' else data.pickup_end
                        conn.execute('INSERT INTO proposals(appointment_id,owner,start,end,creator,reason,deadline,base_version,created) VALUES(?,?,?,?,?,?,?,?,?)', (cursor.lastrowid,owner,start,end,actor,'Monatsentwurf – Verfügbarkeit gemeinsam prüfen', (datetime.now(TZ)+timedelta(days=2)).isoformat(),0,now()))
                        created += 1
                day += timedelta(days=1)
            notify(conn, 'britta' if actor == 'tobi' else 'tobi', f'month:{data.month}', 'Monatsentwurf liegt bereit', f'{data.month}: {created} vorläufige Zuordnungen gemeinsam prüfen.')
            audit(conn, actor, 'Monat vorbereitet', f'{data.month} · {created} vorläufige Zuordnungen')
        return {'count': created}

    @app.post('/api/issues')
    def create_issue(data: IssueInput, request: Request):
        if not data.text.strip():
            raise HTTPException(422, 'Bitte den Gesprächsbedarf beschreiben.')
        deadline = deadline_value(data.deadline)
        with db() as conn:
            actor = identity(request, conn)
            require_household(conn)
            if data.appointment_id and not conn.execute('SELECT id FROM appointments WHERE id=?', (data.appointment_id,)).fetchone():
                raise HTTPException(404, 'Termin nicht gefunden.')
            created_issue = conn.execute('INSERT INTO issues(appointment_id,text,owner,deadline,created) VALUES(?,?,?,?,?)', (data.appointment_id,data.text.strip(),actor,deadline,now()))
            notify(conn, 'britta' if actor == 'tobi' else 'tobi', f'issue:{created_issue.lastrowid}', 'Neuer Gesprächsbedarf', PEOPLE[actor] + ' hat einen Klärungspunkt eröffnet. Die bisherige Planung bleibt gültig.')
            audit(conn, actor, 'Klärungspunkt eröffnet', 'Verantwortlich: ' + PEOPLE[actor])
        return {'ok': True}

    @app.post('/api/issues/{issue_id}/resolve')
    def resolve(issue_id: int, data: ResolveInput, request: Request):
        with db() as conn:
            actor = identity(request, conn)
            issue = conn.execute("SELECT * FROM issues WHERE id=? AND state='open'", (issue_id,)).fetchone()
            if not issue or issue['version'] != data.version:
                raise HTTPException(409, 'Der Klärungspunkt hat sich geändert.')
            if actor != issue['owner']:
                raise HTTPException(403, 'Nur die verantwortliche Person kann diesen Klärungspunkt abschließen.')
            if not data.resolution.strip():
                raise HTTPException(422, 'Bitte das Ergebnis festhalten.')
            if conn.execute("SELECT id FROM proposals WHERE issue_id=? AND state='pending'", (issue_id,)).fetchone():
                raise HTTPException(409, 'Zuerst den zugehörigen Änderungsvorschlag entscheiden.')
            conn.execute("UPDATE issues SET state='resolved',version=version+1,resolution=? WHERE id=?", (data.resolution.strip(),issue_id))
            audit(conn, actor, 'Klärungspunkt abgeschlossen', data.resolution.strip())
        return {'ok': True}

    @app.post('/api/tasks/{task_id}/complete')
    def complete(task_id: int, request: Request):
        with db() as conn:
            actor = identity(request, conn)
            task = conn.execute('SELECT * FROM tasks WHERE id=?', (task_id,)).fetchone()
            if not task or task['owner'] != actor:
                raise HTTPException(403, 'Nur eigene Aufgaben können bestätigt werden.')
            if task['state'] != 'open':
                raise HTTPException(409, 'Diese Aufgabe ist nicht mehr offen.')
            conn.execute("UPDATE tasks SET state='done' WHERE id=?", (task_id,))
            audit(conn, actor, 'Aufgabe erledigt', task['title'])
        return {'ok': True}

    @app.get('/health')
    def health():
        return {'ok': True}

    app.mount('/static', StaticFiles(directory=ROOT / 'static'), name='static')

    @app.get('/')
    def index():
        return FileResponse(ROOT / 'static' / 'index.html')

    if demo:
        with db() as conn:
            if not conn.execute("SELECT value FROM metadata WHERE key='seeded'").fetchone():
                today = datetime.now(TZ).date()
                first, last = month_bounds(today.strftime('%Y-%m'))
                day = first
                slots = []
                while day <= last:
                    if day.weekday() < 5:
                        for kind in ('bring','pickup'):
                            owner = 'tobi' if (day.weekday() + (kind == 'pickup')) % 2 == 0 else 'britta'
                            start,end = ('07:45','08:45') if kind == 'bring' else ('15:30','17:30')
                            cur = conn.execute('INSERT INTO appointments(day,kind,owner,start,end,version) VALUES(?,?,?,?,?,1)', (str(day),kind,owner,start,end))
                            if day >= today:
                                slots.append((cur.lastrowid,day,kind,owner,start,end))
                    day += timedelta(days=1)
                if slots:
                    slot = next((s for s in slots if s[2]=='pickup'), slots[0])
                    issue = conn.execute('INSERT INTO issues(appointment_id,text,owner,deadline,created) VALUES(?,?,?,?,?)', (slot[0],'Mein Termin dauert länger. Können wir das Abholen tauschen?','tobi',(datetime.now(TZ)+timedelta(hours=24)).isoformat(),now()))
                    conn.execute('INSERT INTO proposals(appointment_id,owner,start,end,creator,reason,deadline,base_version,created,issue_id) VALUES(?,?,?,?,?,?,?,?,?,?)', (slot[0], 'britta' if slot[3]=='tobi' else 'tobi',slot[4],slot[5],'britta','Können wir diesen Termin tauschen?',(datetime.now(TZ)+timedelta(hours=24)).isoformat(),1,now(),issue.lastrowid))
                conn.execute('INSERT INTO tasks(owner,title,details,due,created) VALUES(?,?,?,?,?)', ('tobi','Arbeitskalender aktualisieren','Beispielaufgabe: bestätigte Bring- und Abholzeiten als abwesend eintragen.',now(),now()))
                audit(conn,'tobi','Beispielplanung angelegt','Demodaten · Zeitfenster sind Beispiele, keine echte Familienplanung.')
                conn.execute("INSERT INTO metadata VALUES('seeded','1')")
    return app
