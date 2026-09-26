"""Durable calendar reconciliation, notification inbox and Web Push.

Only this installation's explicitly mapped event IDs are accessed. Network calls
never hold a database transaction. One application worker is required.
"""
import base64
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import threading
import time
from urllib.parse import quote, urlencode, urlparse
from zoneinfo import ZoneInfo

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
import httpx
from pydantic import BaseModel, Field
from pywebpush import webpush, WebPushException

TZ = ZoneInfo('Europe/Berlin')
PEOPLE = {'tobi': 'Tobi', 'britta': 'Britta'}


def dump(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def notify(conn, owner, dedupe, title, body, urgent=True, instant=None):
    instant = instant or datetime.now(TZ)
    send = instant
    if not urgent and (instant.hour >= 21 or instant.hour < 7):
        send = (instant + timedelta(days=instant.hour >= 21)).replace(hour=7, minute=0, second=0, microsecond=0)
    row = conn.execute('INSERT OR IGNORE INTO notifications(owner,dedupe,title,body,urgent,created,not_before) VALUES(?,?,?,?,?,?,?)',
                       (owner, dedupe, title, body, int(urgent), instant.isoformat(), send.timestamp()))
    if row.rowcount:
        conn.execute('INSERT INTO push_deliveries(notification_id,subscription_id) SELECT ?,id FROM push_subscriptions WHERE owner=? AND active=1', (row.lastrowid, owner))


def event_body(row, tentative, installation):
    return {'summary': ('[Vorläufig] ' if tentative else '') + 'Lina ' + ('bringen' if row['kind'] == 'bring' else 'abholen') + ' · ' + PEOPLE[row['owner']],
            'description': 'Family OS · ' + ('Zustimmung der anderen Person steht aus.' if tentative else 'Gemeinsam bestätigt. Arbeitskalender separat aktualisieren.'),
            'start': {'dateTime': datetime.fromisoformat(row['day'] + 'T' + row['start']).replace(tzinfo=TZ).isoformat(), 'timeZone': 'Europe/Berlin'},
            'end': {'dateTime': datetime.fromisoformat(row['day'] + 'T' + row['end']).replace(tzinfo=TZ).isoformat(), 'timeZone': 'Europe/Berlin'},
            'status': 'tentative' if tentative else 'confirmed', 'transparency': 'transparent' if tentative else 'opaque',
            'reminders': {'useDefault': False}, 'extendedProperties': {'private': {'familyOS': installation}}}


def nanny_event_body(row, name, installation):
    """Nanny shift in the shared calendar: requested = tentative, confirmed = fixed.

    Wishes are not sent; the parents keep them local until they ask the nanny.
    The parents are not blocked by the event (they still pick Lina up earlier).
    """
    tentative = row['state'] == 'requested'
    who = 'Nanny' if not name or name == 'Nanny' else 'Nanny ' + name
    description = ('Family OS · Bei der Nanny angefragt, Zusage steht noch aus.' if tentative
                   else 'Family OS · Von der Nanny bestätigt. Lina an diesem Tag früher abholen; Übergabe zuhause zu Beginn.')
    return {'summary': ('[Vorläufig] ' if tentative else '') + who + ' · Lina',
            'description': description,
            'start': {'dateTime': datetime.fromisoformat(row['day'] + 'T' + row['start']).replace(tzinfo=TZ).isoformat(), 'timeZone': 'Europe/Berlin'},
            'end': {'dateTime': datetime.fromisoformat(row['day'] + 'T' + row['end']).replace(tzinfo=TZ).isoformat(), 'timeZone': 'Europe/Berlin'},
            'status': 'tentative' if tentative else 'confirmed', 'transparency': 'transparent',
            'reminders': {'useDefault': False}, 'extendedProperties': {'private': {'familyOS': installation}}}


def matches(remote, desired):
    if not remote or not desired or remote.get('status') == 'cancelled':
        return False
    desired = json.loads(desired) if isinstance(desired, str) else desired
    # Google can normalize offsets/time zones. Compare the represented instants.
    for key in ('start', 'end'):
        try:
            if datetime.fromisoformat(remote[key]['dateTime']) != datetime.fromisoformat(desired[key]['dateTime']):
                return False
        except (KeyError, ValueError):
            return False
    return all(remote.get(k) == desired[k] for k in ('summary', 'description', 'status', 'transparency', 'reminders', 'extendedProperties')) and not remote.get('attendees')


class CalendarReview(BaseModel):
    key: str = Field(pattern=r'^(slot|proposal|nanny)-[0-9]+$')
    etag: str | None = Field(default=None, max_length=512)
    desired: str | None = Field(default=None, max_length=8192)


class Subscription(BaseModel):
    endpoint: str = Field(max_length=4096)
    keys: dict[str, str]


def validate_subscription(data):
    try:
        parsed = urlparse(data.endpoint)
        port = parsed.port
    except ValueError:
        raise HTTPException(422, 'Ungültige Push-Adresse.')
    host = parsed.hostname or ''
    allowed = host == 'web.push.apple.com' or host.endswith('.push.apple.com') or host in ('fcm.googleapis.com', 'updates.push.services.mozilla.com')
    if parsed.scheme != 'https' or not allowed or port not in (None, 443) or parsed.username or parsed.password or parsed.fragment:
        raise HTTPException(422, 'Dieser Push-Dienst wird nicht unterstützt.')
    try:
        if any(len(value) > 200 for value in data.keys.values()):
            raise ValueError()
        auth = base64.urlsafe_b64decode(data.keys['auth'] + '===')
        point = base64.urlsafe_b64decode(data.keys['p256dh'] + '===')
        if len(auth) != 16 or len(point) != 65:
            raise ValueError()
        ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), point)
    except (KeyError, ValueError):
        raise HTTPException(422, 'Ungültige Push-Schlüssel.')


class Integrations:
    def __init__(self, db, directory, demo, origin):
        self.db, self.demo, self.origin = db, demo, origin.rstrip('/')
        self.directory = Path(directory)
        self.calendar = os.getenv('FOS_GOOGLE_CALENDAR_ID', '').strip()
        self.client_file = os.getenv('FOS_GOOGLE_CLIENT_FILE', '')
        self.stop = threading.Event()
        self.periodic = []  # callables run on every background tick
        self.backups = None  # AutoBackup, set by create_app
        self.speech = None  # Speech, set by create_app
        self.lock = threading.Lock()
        with db() as conn:
            conn.execute("INSERT OR IGNORE INTO metadata VALUES('installation',?)", (secrets.token_hex(16),))
            self.installation = conn.execute("SELECT value FROM metadata WHERE key='installation'").fetchone()[0]
            old = conn.execute("SELECT value FROM metadata WHERE key='calendar_id'").fetchone()
            if old and old[0] != self.calendar:
                raise RuntimeError('Kalender-ID wurde geändert. Erst bestehende Zuordnung kontrolliert migrieren; kein stiller Kalenderwechsel erlaubt.')
        self.cipher = None
        if not demo:
            keyfile = self.directory / 'integration.key'
            if not keyfile.exists():
                with db() as conn:
                    if conn.execute('SELECT 1 FROM integration_secrets LIMIT 1').fetchone():
                        raise RuntimeError('integration.key fehlt. Schlüssel aus der Sicherung wiederherstellen.')
                fd = os.open(keyfile, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, 'wb') as file:
                    file.write(Fernet.generate_key())
            self.cipher = Fernet(keyfile.read_bytes())
            self.vapid_file = self.directory / 'push-private.pem'
            if not self.vapid_file.exists():
                key = ec.generate_private_key(ec.SECP256R1())
                fd = os.open(self.vapid_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, 'wb') as file:
                    file.write(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
            key = serialization.load_pem_private_key(self.vapid_file.read_bytes(), password=None)
            self.push_public = base64.urlsafe_b64encode(key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)).rstrip(b'=').decode()
        else:
            self.push_public = None

    def credentials(self):
        if not self.client_file or not self.calendar:
            raise HTTPException(409, 'Google-Zugang und Gemeinschaftskalender-ID müssen zuerst auf dem NAS eingerichtet werden.')
        try:
            data = json.loads(Path(self.client_file).read_text())['web']
            return {k: data[k] for k in ('client_id', 'client_secret')}
        except (OSError, ValueError, KeyError):
            raise HTTPException(409, 'Google-Zugangsdatei fehlt oder ist ungültig.')

    def secret(self, name):
        with self.db() as conn:
            row = conn.execute('SELECT value FROM integration_secrets WHERE key=?', (name,)).fetchone()
        return json.loads(self.cipher.decrypt(row[0].encode())) if row else None

    def save_secret(self, name, data):
        encrypted = self.cipher.encrypt(dump(data).encode()).decode()
        with self.db() as conn:
            conn.execute('INSERT OR REPLACE INTO integration_secrets VALUES(?,?)', (name, encrypted))

    def access_token(self):
        token = self.secret('google')
        if not token:
            raise RuntimeError('Google noch nicht verbunden.')
        if token.get('expires_at', 0) > time.time() + 60:
            return token['access_token']
        response = httpx.post('https://oauth2.googleapis.com/token', data={**self.credentials(), 'grant_type': 'refresh_token', 'refresh_token': token['refresh_token']}, timeout=15)
        if response.status_code != 200:
            raise RuntimeError('Google-Zugang erneuern oder Verbindung prüfen.')
        new = response.json()
        token.update(access_token=new['access_token'], expires_at=time.time() + new['expires_in'])
        self.save_secret('google', token)
        return token['access_token']

    def google(self, method, event_id, body=None, etag=None):
        url = 'https://www.googleapis.com/calendar/v3/calendars/' + quote(self.calendar, safe='') + '/events'
        if method != 'POST':
            url += '/' + event_id
        headers = {'Authorization': 'Bearer ' + self.access_token()}
        if etag:
            headers['If-Match'] = etag
        return httpx.request(method, url, json=body, headers=headers, params={'sendUpdates': 'none'}, timeout=15, follow_redirects=False)

    def reconcile(self):
        with self.db() as conn:
            desired = {}
            # Days without nursery care suspend their assignments (closures.py).
            closed = "SELECT day FROM day_closures WHERE state='confirmed'"
            for row in conn.execute(f'SELECT * FROM appointments WHERE owner IS NOT NULL AND day NOT IN ({closed})'):
                desired['slot-' + str(row['id'])] = dump(event_body(row, False, self.installation))
            for row in conn.execute(f"SELECT p.*,a.day,a.kind FROM proposals p JOIN appointments a ON a.id=p.appointment_id WHERE p.state='pending' AND a.day NOT IN ({closed})"):
                desired['proposal-' + str(row['id'])] = dump(event_body(row, True, self.installation))
            name = conn.execute("SELECT value FROM metadata WHERE key='nanny_name'").fetchone()
            for row in conn.execute("SELECT * FROM nanny_shifts WHERE state IN ('requested','confirmed')"):
                desired['nanny-' + str(row['id'])] = dump(nanny_event_body(row, name[0] if name else '', self.installation))
            existing = {r['key']: dict(r) for r in conn.execute('SELECT * FROM calendar_targets')}
            for key in desired.keys() | existing.keys():
                body = desired.get(key)
                if key not in existing:
                    eid = hashlib.sha256((self.installation + key).encode()).hexdigest()
                    conn.execute('INSERT INTO calendar_targets(key,event_id,desired) VALUES(?,?,?)', (key, eid, body))
                elif body != existing[key]['desired']:
                    conn.execute("UPDATE calendar_targets SET desired=?,state=CASE WHEN state='conflict' THEN state ELSE 'queued' END,next_try=0 WHERE key=?", (body, key))

    def sync_one(self, target):
        key, desired = target['key'], target['desired']
        # A confirmed replacement must reach Google before its tentative event is removed.
        if desired is None and key.startswith('proposal-'):
            with self.db() as conn:
                proposal = conn.execute('SELECT * FROM proposals WHERE id=?', (int(key.split('-')[1]),)).fetchone()
                if proposal and proposal['state'] == 'accepted':
                    final = conn.execute('SELECT * FROM calendar_targets WHERE key=?', ('slot-' + str(proposal['appointment_id']),)).fetchone()
                    if not final or final['state'] != 'synced' or final['applied'] != final['desired']:
                        return
        if not desired and not target['etag'] and not target['inflight']:
            self.synced(key, None, None)
            return
        response = self.google('GET', target['event_id'])
        if response.status_code not in (200, 404, 410):
            raise RuntimeError('Google ist nicht erreichbar oder der Kalenderzugriff wurde verweigert.')
        remote = response.json() if response.status_code == 200 else None
        absent = remote is None or remote.get('status') == 'cancelled'
        if absent and target['etag'] and not (target['inflight'] == 'null'):
            self.conflict(key, 'Der Eintrag wurde in Google gelöscht. Bitte gemeinsam prüfen.')
            return
        if not absent:
            owned = remote.get('extendedProperties', {}).get('private', {}).get('familyOS') == self.installation
            if not owned:
                self.conflict(key, 'Die Kennzeichnung des Google-Eintrags stimmt nicht mehr überein.')
                return
            recovered = target['inflight'] and target['inflight'] != 'null' and matches(remote, target['inflight'])
            if remote.get('etag') != target['etag'] and not recovered:
                self.conflict(key, 'Der Eintrag wurde außerhalb des Family OS geändert. Bitte gemeinsam prüfen.')
                return
            if matches(remote, desired):
                self.synced(key, desired, remote['etag'])
                return
        if absent and not desired:
            self.synced(key, None, None)
            return
        with self.db() as conn:
            conn.execute('UPDATE calendar_targets SET inflight=? WHERE key=?', (desired or 'null', key))
        if not desired:
            result = self.google('DELETE', target['event_id'], etag=remote['etag'])
        elif absent:
            result = self.google('POST', target['event_id'], {'id': target['event_id'], **json.loads(desired)})
        else:
            result = self.google('PUT', target['event_id'], json.loads(desired), remote['etag'])
        if result.status_code in (409, 412):
            self.conflict(key, 'Google hat eine gleichzeitige Änderung erkannt. Bitte prüfen.')
            return
        if result.status_code not in (200, 201, 204):
            raise RuntimeError('Google hat die Übertragung noch nicht bestätigt.')
        self.synced(key, desired, result.json().get('etag') if desired else None)

    def synced(self, key, applied, etag):
        with self.db() as conn:
            conn.execute("UPDATE calendar_targets SET applied=?,etag=?,inflight=NULL,state=CASE WHEN desired IS ? THEN 'synced' ELSE 'queued' END,attempts=0,next_try=0,checked=?,message='' WHERE key=?", (applied, etag, applied, time.time(), key))

    def conflict(self, key, message):
        with self.db() as conn:
            was = conn.execute('SELECT state FROM calendar_targets WHERE key=?', (key,)).fetchone()
            conn.execute("UPDATE calendar_targets SET state='conflict',message=?,checked=? WHERE key=?", (message, time.time(), key))
            if was and was['state'] == 'conflict':
                return
            conflict_id = secrets.token_hex(8)
            for owner in PEOPLE:
                if conn.execute('SELECT 1 FROM users WHERE id=?', (owner,)).fetchone():
                    notify(conn, owner, 'calendar-conflict:' + key + ':' + conflict_id + ':' + owner, 'Kalender bitte prüfen', 'Ein Family-OS-Termin wurde in Google verändert. Die Übertragung ist angehalten.')

    def summaries(self, instant=None):
        instant = (instant or datetime.now(TZ)).astimezone(TZ)
        if 9 <= instant.hour < 21:
            self.reminders(instant)
        if not 19 <= instant.hour < 21:
            return
        with self.db() as conn:
            for user in conn.execute('SELECT id FROM users'):
                owner = user[0]
                periods = [('day', instant.date() + timedelta(days=1), 1)]
                if instant.weekday() == 6:
                    periods.append(('week', instant.date() + timedelta(days=1), 7))
                for kind, start, days in periods:
                    end = start + timedelta(days=days - 1)
                    slots = conn.execute("SELECT day,kind,start,end FROM appointments WHERE owner=? AND day BETWEEN ? AND ? AND day NOT IN (SELECT day FROM day_closures WHERE state='confirmed') ORDER BY day,start", (owner, str(start), str(end))).fetchall()
                    tasks = conn.execute("SELECT COUNT(*) FROM tasks WHERE owner=? AND state='open' AND substr(due,1,10)<=?", (owner, str(end))).fetchone()[0]
                    pending = conn.execute("SELECT COUNT(*) FROM proposals WHERE creator!=? AND state='pending'", (owner,)).fetchone()[0]
                    nanny = conn.execute("SELECT day,start,end FROM nanny_shifts WHERE state='confirmed' AND day BETWEEN ? AND ? ORDER BY day,start", (str(start), str(end))).fetchall()
                    nanny_text = (' Nanny: ' + '; '.join(f"{datetime.fromisoformat(r['day']).strftime('%d.%m.')} {r['start']}–{r['end']}" for r in nanny) + ' (früher abholen).') if nanny else ''
                    notify(conn, owner, f'{kind}:{start}:{owner}', 'Dein nächster Tag' if kind == 'day' else 'Deine nächste Woche',
                           f"{len(slots)} bestätigte Wege: " + ('; '.join(f"{datetime.fromisoformat(r['day']).strftime('%d.%m.')} {'Bringen' if r['kind']=='bring' else 'Abholen'} {r['start']}–{r['end']}" for r in slots) or 'keine') + '.' + nanny_text + f' {tasks} fällige Aufgaben · {pending} Vorschläge warten auf dich.', False, instant)

    def reminders(self, instant):
        with self.db() as conn:
            for user in conn.execute('SELECT id FROM users'):
                owner = user[0]
                tasks = conn.execute("SELECT COUNT(*) FROM tasks WHERE owner=? AND state='open' AND julianday(due)<=julianday(?)", (owner, instant.isoformat())).fetchone()[0]
                issues = conn.execute("SELECT COUNT(*) FROM issues WHERE owner=? AND state='open' AND julianday(deadline)<=julianday(?)", (owner, instant.isoformat())).fetchone()[0]
                pending = conn.execute("SELECT COUNT(*) FROM proposals WHERE creator!=? AND state='pending' AND julianday(deadline)<=julianday(?)", (owner, instant.isoformat())).fetchone()[0]
                if tasks + issues + pending:
                    notify(conn, owner, f'reminder:{instant.date()}:{owner}', 'Noch offen für dich', f'{tasks} fällige Aufgaben · {issues} Klärungspunkte mit erreichter Frist · {pending} ausstehende Entscheidungen. Die bisherige Planung bleibt gültig.', False, instant)

    def deliver_push(self):
        if self.demo:
            return
        with self.db() as conn:
            conn.execute("UPDATE push_deliveries SET state='stale' WHERE state='queued' AND notification_id IN (SELECT id FROM notifications WHERE read_at IS NOT NULL OR created<?)", ((datetime.now(TZ)-timedelta(days=1)).isoformat(),))
            rows = [dict(r) for r in conn.execute("SELECT d.*,n.title,n.body,n.urgent,n.created,s.subscription FROM push_deliveries d JOIN notifications n ON n.id=d.notification_id JOIN push_subscriptions s ON s.id=d.subscription_id WHERE d.state='queued' AND d.next_try<=? AND n.not_before<=? AND s.active=1 ORDER BY n.urgent DESC,n.id LIMIT 8", (time.time(), time.time()))]
        for row in rows:
            if self.stop.is_set():
                break
            # Delivery accepted by a push service is not proof of display or reading.
            try:
                subscription = json.loads(row['subscription'])
                webpush(subscription_info=subscription, data=dump({'title': row['title'], 'body': row['body'], 'tag': 'fos-' + str(row['notification_id'])}),
                        vapid_private_key=str(self.vapid_file), vapid_claims={'sub': self.origin}, ttl=86400, timeout=10,
                        headers={'Urgency': 'high' if row['urgent'] else 'normal'})
                with self.db() as conn:
                    conn.execute("UPDATE push_deliveries SET state='accepted' WHERE notification_id=? AND subscription_id=?", (row['notification_id'], row['subscription_id']))
            except Exception as error:
                expired = isinstance(error, WebPushException) and error.response is not None and error.response.status_code in (404, 410)
                with self.db() as conn:
                    if expired:
                        conn.execute('UPDATE push_subscriptions SET active=0 WHERE id=?', (row['subscription_id'],))
                    conn.execute('UPDATE push_deliveries SET state=?,attempts=attempts+1,next_try=? WHERE notification_id=? AND subscription_id=?',
                                 ('expired' if expired else 'queued', time.time() + min(3600, 30 * 2 ** min(row['attempts'], 7)), row['notification_id'], row['subscription_id']))

    def tick(self):
        if not self.lock.acquire(blocking=False):
            return
        try:
            self.reconcile()
            self.summaries()
            for hook in self.periodic:
                try:
                    hook()
                except Exception:
                    import logging
                    logging.getLogger('family-os').error('Periodische Aufgabe fehlgeschlagen; erneuter Versuch folgt.')
            if not self.demo and self.secret('google'):
                with self.db() as conn:
                    rows = [dict(r) for r in conn.execute("SELECT * FROM calendar_targets WHERE state!='conflict' AND next_try<=? AND (state!='synced' OR (desired IS NOT NULL AND checked<?)) ORDER BY desired IS NULL,key LIMIT 8", (time.time(), time.time() - 900))]
                for row in rows:
                    if self.stop.is_set():
                        break
                    try:
                        self.sync_one(row)
                    except Exception:
                        with self.db() as conn:
                            conn.execute("UPDATE calendar_targets SET state='error',attempts=attempts+1,next_try=?,message='Übertragung ausstehend. Zugang und Verbindung prüfen; erneuter Versuch folgt automatisch.' WHERE key=?", (time.time() + min(3600, 30 * 2 ** min(row['attempts'], 7)), row['key']))
        finally:
            self.lock.release()

    def run(self):
        while not self.stop.is_set():
            try:
                self.tick()
            except Exception:
                # No exception repr: provider errors can include credentials or endpoint URLs.
                import logging
                logging.getLogger('family-os').error('Hintergrundverarbeitung fehlgeschlagen; erneuter Versuch folgt.')
            self.stop.wait(20)

    def run_push(self):
        while not self.stop.is_set():
            try:
                self.deliver_push()
            except Exception:
                import logging
                logging.getLogger('family-os').error('Push-Verarbeitung fehlgeschlagen; erneuter Versuch folgt.')
            self.stop.wait(5)

    @asynccontextmanager
    async def lifespan(self, app):
        self.stop.clear()
        worker = threading.Thread(target=self.run, name='family-integrations', daemon=True)
        worker.start()
        push_worker = threading.Thread(target=self.run_push, name='family-push', daemon=True)
        push_worker.start()
        meal_worker = threading.Thread(target=self.meals.background, name='family-meals', daemon=True)
        meal_worker.start()
        if self.speech:
            self.speech.start()  # loads (and first time downloads) the model in its own thread
        yield
        self.stop.set()
        import asyncio
        await asyncio.gather(asyncio.to_thread(worker.join, 35), asyncio.to_thread(push_worker.join, 35), asyncio.to_thread(meal_worker.join, 35))

    def status(self, conn, owner):
        connected = bool(conn.execute("SELECT 1 FROM integration_secrets WHERE key='google'").fetchone()) and not self.demo
        targets = [dict(r) for r in conn.execute('SELECT key,state,message,checked FROM calendar_targets WHERE desired IS NOT NULL OR applied IS NOT NULL')]
        notices = [dict(r) for r in conn.execute('SELECT * FROM notifications WHERE owner=? ORDER BY id DESC LIMIT 100', (owner,))]
        devices = conn.execute('SELECT COUNT(*) FROM push_subscriptions WHERE owner=? AND active=1', (owner,)).fetchone()[0]
        accepted = conn.execute("SELECT COUNT(*) FROM push_deliveries d JOIN notifications n ON n.id=d.notification_id WHERE n.owner=? AND d.state='accepted'", (owner,)).fetchone()[0]
        waiting = conn.execute("SELECT COUNT(*) FROM push_deliveries d JOIN notifications n ON n.id=d.notification_id JOIN push_subscriptions s ON s.id=d.subscription_id WHERE n.owner=? AND d.state='queued' AND s.active=1", (owner,)).fetchone()[0]
        return {'google_connected': connected, 'google_configured': bool(self.calendar and self.client_file), 'calendar_targets': targets,
                'notifications': notices, 'push_devices': devices, 'push_accepted': accepted, 'push_waiting': waiting, 'push_public_key': self.push_public,
                'origin': self.origin, 'calendar_kind': 'Bestehender Gemeinschaftskalender',
                'backup': self.backups.status(conn) if self.backups else None,
                'speech': self.speech.status(conn) if self.speech else None}

    def routes(self, app, identity, static):
        @app.get('/api/connections')
        def status(request: Request):
            with self.db() as conn:
                identity(request, conn)
            self.reconcile()
            with self.db() as conn:
                return self.status(conn, identity(request, conn))

        @app.post('/api/google/connect')
        def connect(request: Request):
            with self.db() as conn:
                if identity(request, conn) != 'tobi':
                    raise HTTPException(403, 'Tobi verwaltet die Verbindung.')
            if self.demo:
                raise HTTPException(409, 'Die Demo verbindet keine echten Konten.')
            credentials = self.credentials()
            state, verifier, cookie = secrets.token_urlsafe(32), secrets.token_urlsafe(48), secrets.token_urlsafe(32)
            with self.db() as conn:
                conn.execute('DELETE FROM oauth_states WHERE expires<?', (time.time(),))
                conn.execute('INSERT INTO oauth_states VALUES(?,?,?,?,?)', (state, verifier, hashlib.sha256(cookie.encode()).hexdigest(), hashlib.sha256(request.cookies['fos_session'].encode()).hexdigest(), time.time() + 600))
            challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
            response = JSONResponse({'url': 'https://accounts.google.com/o/oauth2/v2/auth?' + urlencode({'client_id': credentials['client_id'], 'redirect_uri': self.origin + '/api/google/callback', 'response_type': 'code', 'scope': 'https://www.googleapis.com/auth/calendar.events', 'access_type': 'offline', 'prompt': 'consent', 'state': state, 'code_challenge': challenge, 'code_challenge_method': 'S256'})})
            response.set_cookie('fos_oauth', cookie, secure=True, httponly=True, samesite='lax', max_age=600, path='/api/google/callback')
            return response

        @app.get('/api/google/callback')
        def callback(request: Request, state: str = '', code: str = ''):
            if self.demo:
                raise HTTPException(409, 'Keine Kontoverbindung in der Demo.')
            with self.db() as conn:
                row = conn.execute('SELECT * FROM oauth_states WHERE state=? AND expires>?', (state, time.time())).fetchone()
                session = conn.execute("SELECT 1 FROM sessions WHERE token=? AND user_id='tobi' AND expires>?", (row['session'], time.time())).fetchone() if row else None
                if not row or not session or not hmac.compare_digest(row['cookie_hash'], hashlib.sha256(request.cookies.get('fos_oauth', '').encode()).hexdigest()):
                    raise HTTPException(403, 'Verbindungsanfrage abgelaufen oder ungültig. Bitte neu starten.')
                conn.execute('DELETE FROM oauth_states WHERE state=?', (state,))
            if not code:
                raise HTTPException(400, 'Google-Verbindung wurde nicht freigegeben.')
            try:
                result = httpx.post('https://oauth2.googleapis.com/token', data={**self.credentials(), 'grant_type': 'authorization_code', 'code': code, 'code_verifier': row['verifier'], 'redirect_uri': self.origin + '/api/google/callback'}, timeout=15)
                token = result.json()
                if result.status_code != 200 or not token.get('refresh_token'):
                    raise ValueError()
                token['expires_at'] = time.time() + token['expires_in']
                self.save_secret('google', token)
                with self.db() as conn:
                    conn.execute("INSERT OR REPLACE INTO metadata VALUES('calendar_id',?)", (self.calendar,))
            except Exception:
                raise HTTPException(502, 'Google-Verbindung nicht abgeschlossen. Bitte erneut versuchen.')
            response = RedirectResponse('/?connected=google', status_code=303)
            response.delete_cookie('fos_oauth', path='/api/google/callback', secure=True, httponly=True, samesite='lax')
            return response

        def review_target(data, request):
            with self.db() as conn:
                if identity(request, conn) != 'tobi':
                    raise HTTPException(403, 'Tobi verwaltet die Kalenderverbindung.')
                target = conn.execute("SELECT * FROM calendar_targets WHERE key=? AND state='conflict'", (data.key,)).fetchone()
            if self.demo or not target:
                raise HTTPException(409, 'Keine aktuelle Kalenderabweichung gefunden.')
            response = self.google('GET', target['event_id'])
            if response.status_code not in (200, 404, 410):
                raise HTTPException(502, 'Google konnte nicht geprüft werden. Bitte später erneut versuchen.')
            remote = response.json() if response.status_code == 200 else None
            if remote and remote.get('status') == 'cancelled':
                remote = None
            if remote and remote.get('extendedProperties', {}).get('private', {}).get('familyOS') != self.installation:
                raise HTTPException(409, 'Der Eintrag ist nicht mehr eindeutig dieser Anwendung zugeordnet. Bitte die Kennzeichnung im Kalender prüfen; es wird nichts überschrieben.')
            return dict(target), remote

        @app.post('/api/google/review')
        def review(data: CalendarReview, request: Request):
            target, remote = review_target(data, request)
            def label(body):
                if not body:
                    return 'Kein Eintrag vorgesehen'
                return body.get('summary', '') + ' · ' + body.get('start', {}).get('dateTime', '') + ' bis ' + body.get('end', {}).get('dateTime', '')
            return {'etag': remote['etag'] if remote else None, 'desired': target['desired'],
                    'remote_label': label(remote) if remote else 'Eintrag fehlt oder wurde gelöscht',
                    'local_label': label(json.loads(target['desired'])) if target['desired'] else 'Vorläufigen Eintrag entfernen'}

        @app.post('/api/google/restore')
        def restore(data: CalendarReview, request: Request):
            # Serialize conflict resolution with the worker; If-Match still guards Google races.
            if not self.lock.acquire(blocking=False):
                raise HTTPException(409, 'Der Kalender wird gerade geprüft. Bitte kurz warten und erneut versuchen.')
            try:
                self.reconcile()
                target, remote = review_target(data, request)
                if target['desired'] != data.desired or (remote['etag'] if remote else None) != data.etag:
                    raise HTTPException(409, 'Der Stand hat sich geändert. Bitte die Abweichung erneut prüfen.')
                with self.db() as conn:
                    if remote:
                        conn.execute("UPDATE calendar_targets SET etag=?,inflight=NULL,state='queued',next_try=0,message='' WHERE key=?", (remote['etag'], data.key))
                    else:
                        # Google retains tombstones; a new ID is required after confirmed deletion.
                        conn.execute("UPDATE calendar_targets SET event_id=?,etag=NULL,applied=NULL,inflight=NULL,state='queued',next_try=0,message='' WHERE key=?", (secrets.token_hex(32), data.key))
                    conn.execute('INSERT INTO audit(actor,action,details,created) VALUES(?,?,?,?)', ('tobi', 'Kalenderabweichung geprüft', 'Family-OS-Stand erneut zur Übertragung vorgemerkt: ' + data.key, datetime.now(TZ).isoformat()))
                return {'ok': True}
            finally:
                self.lock.release()

        @app.post('/api/notifications/{notice_id}/read')
        def read(notice_id: int, request: Request):
            with self.db() as conn:
                actor = identity(request, conn)
                conn.execute('UPDATE notifications SET read_at=COALESCE(read_at,?) WHERE id=? AND owner=?', (datetime.now(TZ).isoformat(), notice_id, actor))
            return {'ok': True}

        @app.post('/api/push/subscribe')
        def subscribe(data: Subscription, request: Request):
            with self.db() as conn:
                actor = identity(request, conn)
                if self.demo:
                    raise HTTPException(409, 'Die Demo sendet keine Push-Nachrichten.')
                validate_subscription(data)
                old = conn.execute('SELECT owner FROM push_subscriptions WHERE endpoint=?', (data.endpoint,)).fetchone()
                if old and old['owner'] != actor:
                    raise HTTPException(409, 'Dieses Gerät ist für die andere Person registriert. Erst dort deaktivieren.')
                conn.execute('INSERT INTO push_subscriptions(owner,endpoint,subscription) VALUES(?,?,?) ON CONFLICT(endpoint) DO UPDATE SET subscription=excluded.subscription,active=1', (actor, data.endpoint, dump(data.model_dump())))
            return {'ok': True}

        @app.post('/api/push/unsubscribe')
        def unsubscribe(data: Subscription, request: Request):
            with self.db() as conn:
                actor = identity(request, conn)
                conn.execute('DELETE FROM push_deliveries WHERE subscription_id IN (SELECT id FROM push_subscriptions WHERE endpoint=? AND owner=?)', (data.endpoint, actor))
                conn.execute('DELETE FROM push_subscriptions WHERE endpoint=? AND owner=?', (data.endpoint, actor))
            return {'ok': True}

        @app.post('/api/push/test')
        def test(request: Request):
            with self.db() as conn:
                actor = identity(request, conn)
                notify(conn, actor, f'test:{actor}:{int(time.time() // 60)}', 'Family OS ist bereit', 'Deine Testmitteilung. Sie ändert keine Planung.')
            return {'ok': True}

        @app.get('/sw.js')
        def service_worker():
            return FileResponse(static / 'sw.js', media_type='application/javascript', headers={'Service-Worker-Allowed': '/'})
