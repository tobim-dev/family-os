"""Home-screen widget for iOS via the Scriptable app (A-12).

iOS web apps cannot provide widgets, so a small Scriptable script reads a
compact summary from the NAS. The widget cannot log in with password and
TOTP, therefore each person can create one personal widget key:

* read-only: it only opens ``GET /api/widget``, nothing else accepts it;
* stored as SHA-256 hash only, shown once, replaced by creating a new one,
  revocable at any time in "Verbindungen";
* the summary is minimal: today and tomorrow (bringing, pickup, nanny,
  dinner, days without nursery) and the person's own open items.
"""
from datetime import datetime, timedelta
import hashlib
import hmac
import json
import secrets

from fastapi import HTTPException, Request

from closures import KINDS
from integrations import TZ
from meals import saturday

PEOPLE = {'tobi': 'Tobi', 'britta': 'Britta'}
PREFIX = 'fosw_'


def key(user):
    return 'widget_token:' + user


def digest(token):
    return hashlib.sha256(token.encode()).hexdigest()


class Widget:
    def __init__(self, db):
        self.db = db

    def stored(self, conn, user):
        row = conn.execute('SELECT value FROM metadata WHERE key=?', (key(user),)).fetchone()
        return json.loads(row[0]) if row else None

    def status(self, conn, user):
        entry = self.stored(conn, user)
        if not entry:
            return {'active': False}
        return {'active': True, 'created': entry['created'], 'last_used': entry.get('last_used')}

    def owner(self, conn, request):
        """Person of a valid widget key from the Authorization header."""
        header = request.headers.get('authorization', '')
        token = header[7:].strip() if header.lower().startswith('bearer ') else ''
        if not token.startswith(PREFIX):
            raise HTTPException(401, 'Widget-Schlüssel fehlt oder ist ungültig.')
        for user in PEOPLE:
            entry = self.stored(conn, user)
            if entry and hmac.compare_digest(entry['hash'], digest(token)):
                return user, entry
        raise HTTPException(401, 'Widget-Schlüssel fehlt oder ist ungültig.')

    def day(self, conn, day):
        closure = conn.execute("SELECT kind FROM day_closures WHERE day=? AND state='confirmed'", (str(day),)).fetchone()
        slots = {row['kind']: row['owner'] for row in conn.execute('SELECT kind,owner FROM appointments WHERE day=?', (str(day),))}
        shifts = conn.execute("SELECT start,end FROM nanny_shifts WHERE day=? AND state='confirmed' ORDER BY start", (str(day),)).fetchall()
        result = {'day': str(day), 'closure': KINDS[closure['kind']] if closure else None, 'bring': None, 'pickup': None,
                  'nanny': [f"{s['start']}–{s['end']}" for s in shifts], 'dinner': self.dinner(conn, day)}
        if not closure:
            for kind in ('bring', 'pickup'):
                if kind in slots:
                    result[kind] = PEOPLE.get(slots[kind], 'offen')
        return result

    @staticmethod
    def dinner(conn, day):
        row = conn.execute('SELECT value FROM meal_cache WHERE key=?', ('week:' + str(saturday(day)),)).fetchone()
        if not row:
            return None
        entry = next((d for d in json.loads(row[0])['days'] if d['day'] == str(day)), None)
        if not entry:
            return None
        names = [r['name'] for r in entry['recipes']]
        if entry['custom_ids']:
            names.append('eigenes Rezept')
        return ' · '.join(names) or None

    def summary(self, conn, user, instant):
        today = instant.date()
        tasks = conn.execute("SELECT title FROM tasks WHERE owner=? AND state='open' ORDER BY due,id", (user,)).fetchall()
        approvals = conn.execute("SELECT COUNT(*) FROM proposals WHERE state='pending' AND creator<>?", (user,)).fetchone()[0]
        issues = conn.execute("SELECT COUNT(*) FROM issues WHERE state='open'").fetchone()[0]
        return {'user': PEOPLE[user], 'generated': instant.isoformat(timespec='seconds'),
                'days': [self.day(conn, today), self.day(conn, today + timedelta(days=1))],
                'tasks': len(tasks), 'task_titles': [t['title'] for t in tasks[:3]],
                'approvals': approvals, 'issues': issues}

    def routes(self, app, identity):
        db = self.db

        @app.get('/api/widget')
        def widget(request: Request):
            with db() as conn:
                user, entry = self.owner(conn, request)
                instant = datetime.now(TZ)
                entry['last_used'] = instant.isoformat(timespec='seconds')
                conn.execute('UPDATE metadata SET value=? WHERE key=?', (json.dumps(entry), key(user)))
                return self.summary(conn, user, instant)

        @app.get('/api/widget/key')
        def key_status(request: Request):
            with db() as conn:
                return self.status(conn, identity(request, conn))

        @app.post('/api/widget/key')
        def create_key(request: Request):
            token = PREFIX + secrets.token_urlsafe(32)
            with db() as conn:
                user = identity(request, conn)
                entry = {'hash': digest(token), 'created': datetime.now(TZ).isoformat(timespec='seconds')}
                conn.execute('INSERT OR REPLACE INTO metadata VALUES(?,?)', (key(user), json.dumps(entry)))
                conn.execute('INSERT INTO audit(actor,action,details,created) VALUES(?,?,?,?)',
                             (user, 'Widget-Schlüssel erstellt', 'Ein vorheriger Schlüssel gilt nicht mehr.', entry['created']))
            return {'token': token}

        @app.post('/api/widget/key/revoke')
        def revoke_key(request: Request):
            with db() as conn:
                user = identity(request, conn)
                conn.execute('DELETE FROM metadata WHERE key=?', (key(user),))
                conn.execute('INSERT INTO audit(actor,action,details,created) VALUES(?,?,?,?)',
                             (user, 'Widget-Schlüssel widerrufen', '', datetime.now(TZ).isoformat(timespec='seconds')))
            return {'ok': True}
