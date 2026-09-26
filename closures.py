"""Days without nursery care: closure days, public holidays, vacation, illness.

B-05 / O-02, provisional implementation decision (see ANFORDERUNGEN.md):

* A range of dates is entered as one batch. Only weekdays are stored.
* Like every change to the confirmed plan, the other person confirms the batch
  (B-11). In the joint planning mode it applies directly (B-15).
* A confirmed day keeps its bring/pickup assignments in the database but they
  are suspended: not counted in the monthly distribution, not shown in the
  shared calendar and not part of the evening summary. Each affected parent
  gets a task to update the work calendar (B-13).
* Lifting a confirmed day restores the suspended assignments exactly as they
  were confirmed before. Either parent may lift it; the other is informed.
* The monthly draft leaves such days out.
"""
from datetime import date, datetime, timedelta
import secrets
from typing import Literal

from fastapi import HTTPException, Request
from pydantic import BaseModel, Field

from integrations import TZ, PEOPLE, notify

KINDS = {'closed': 'Krippe geschlossen', 'holiday': 'Feiertag', 'vacation': 'Urlaub', 'sick': 'Lina krank'}
MAX_DAYS = 31
CONFIRMED_DAYS_SQL = "SELECT day FROM day_closures WHERE state='confirmed'"


def now():
    return datetime.now(TZ).isoformat(timespec='seconds')


def span(days):
    first, last = days[0], days[-1]
    if first == last:
        return date.fromisoformat(first).strftime('%d.%m.')
    return date.fromisoformat(first).strftime('%d.%m.') + '–' + date.fromisoformat(last).strftime('%d.%m.')


class ClosureInput(BaseModel):
    start: date
    end: date
    kind: Literal['closed', 'holiday', 'vacation', 'sick']
    note: str = Field(default='', max_length=200)
    planning_session: str | None = Field(default=None, max_length=64)


class ClosureDecision(BaseModel):
    action: Literal['confirm', 'reject', 'withdraw', 'lift']
    planning_session: str | None = Field(default=None, max_length=64)


class Closures:
    def __init__(self, db):
        self.db = db

    @staticmethod
    def other(actor):
        return 'britta' if actor == 'tobi' else 'tobi'

    @staticmethod
    def audit(conn, actor, action, details):
        conn.execute('INSERT INTO audit(actor,action,details,created) VALUES(?,?,?,?)', (actor, action, details, now()))

    def batch(self, conn, batch_id):
        rows = conn.execute('SELECT * FROM day_closures WHERE batch=? ORDER BY day', (batch_id,)).fetchall()
        if not rows:
            raise HTTPException(409, 'Diese Eintragung besteht nicht mehr. Bitte neu laden.')
        return rows

    def calendar_tasks(self, conn, days, suspended):
        """Tell each affected parent to adjust the work calendar (B-13)."""
        marks = ','.join('?' * len(days))
        rows = conn.execute(f'SELECT * FROM appointments WHERE owner IS NOT NULL AND day IN ({marks}) ORDER BY day,kind',
                            days).fetchall()
        for owner in sorted({r['owner'] for r in rows}):
            own = [r for r in rows if r['owner'] == owner]
            listing = '; '.join(f"{date.fromisoformat(r['day']).strftime('%d.%m.')} "
                                f"{'Bringen' if r['kind'] == 'bring' else 'Abholen'} {r['start']}–{r['end']}" for r in own)
            action = 'Blöcke entfernen, sie entfallen' if suspended else 'Blöcke wieder eintragen, sie gelten wieder'
            conn.execute('INSERT INTO tasks(owner,title,details,due,created) VALUES(?,?,?,?,?)',
                         (owner, 'Arbeitskalender aktualisieren', f'{action}: {listing}.', now(), now()))

    def confirm(self, conn, actor, rows):
        days = [r['day'] for r in rows]
        conn.execute("UPDATE day_closures SET state='confirmed',confirmed_by=?,confirmed=? WHERE batch=?",
                     (actor, now(), rows[0]['batch']))
        self.calendar_tasks(conn, days, suspended=True)

    # --- routes ----------------------------------------------------------

    def routes(self, app, identity, validate_planning, require_household):
        db = self.db

        @app.post('/api/closures')
        def create(data: ClosureInput, request: Request):
            if data.end < data.start or (data.end - data.start).days >= MAX_DAYS:
                raise HTTPException(422, f'Bitte einen Zeitraum von höchstens {MAX_DAYS} Tagen wählen.')
            days = [str(data.start + timedelta(days=i)) for i in range((data.end - data.start).days + 1)
                    if (data.start + timedelta(days=i)).weekday() < 5]
            if not days:
                raise HTTPException(422, 'Der Zeitraum enthält keinen Werktag.')
            with db() as conn:
                actor = identity(request, conn)
                require_household(conn)
                joint = validate_planning(conn, request, data.planning_session)
                marks = ','.join('?' * len(days))
                taken = conn.execute(f'SELECT day FROM day_closures WHERE day IN ({marks})', days).fetchall()
                if taken:
                    raise HTTPException(409, 'Für ' + span([r[0] for r in taken]) + ' ist bereits etwas eingetragen.')
                batch_id = secrets.token_hex(8)
                for day in days:
                    conn.execute('INSERT INTO day_closures(day,kind,note,batch,creator,created) VALUES(?,?,?,?,?,?)',
                                 (day, data.kind, data.note.strip(), batch_id, actor, now()))
                label = f'{KINDS[data.kind]} {span(days)}'
                self.audit(conn, actor, 'Betreuungsfreie Tage eingetragen', label)
                if joint:
                    self.confirm(conn, actor, self.batch(conn, batch_id))
                    self.audit(conn, actor, 'In gemeinsamer Planung bestätigt', label)
                else:
                    notify(conn, self.other(actor), f'closure:{batch_id}', 'Betreuungsfreie Tage bestätigen',
                           f'{label}: Bitte bestätigen. Bis dahin gilt die bisherige Planung.')
                return {'batch': batch_id, 'days': len(days)}

        @app.post('/api/closures/{batch_id}/decision')
        def decide(batch_id: str, data: ClosureDecision, request: Request):
            with db() as conn:
                actor = identity(request, conn)
                rows = self.batch(conn, batch_id)
                first = rows[0]
                days = [r['day'] for r in rows]
                label = f"{KINDS[first['kind']]} {span(days)}"
                if data.action == 'lift':
                    if first['state'] != 'confirmed':
                        raise HTTPException(409, 'Nur bestätigte Tage können aufgehoben werden.')
                    conn.execute('DELETE FROM day_closures WHERE batch=?', (batch_id,))
                    self.calendar_tasks(conn, days, suspended=False)
                    notify(conn, self.other(actor), f'closure-lifted:{batch_id}', 'Betreuungsfreie Tage aufgehoben',
                           f'{label}: Die zuvor bestätigte Planung gilt wieder.')
                    self.audit(conn, actor, 'Betreuungsfreie Tage aufgehoben', label)
                    return {'ok': True}
                if first['state'] != 'pending':
                    raise HTTPException(409, 'Diese Tage sind bereits bestätigt.')
                if data.action == 'confirm':
                    joint = validate_planning(conn, request, data.planning_session)
                    if first['creator'] == actor and not joint:
                        raise HTTPException(403, 'Die andere Person bestätigt deine Eintragung.')
                    self.confirm(conn, actor, rows)
                    notify(conn, first['creator'], f'closure-confirmed:{batch_id}', 'Betreuungsfreie Tage bestätigt',
                           f'{label}: bestätigt. Bitte deine Aufgaben zum Arbeitskalender prüfen.')
                    self.audit(conn, actor, 'Betreuungsfreie Tage bestätigt', label)
                    return {'ok': True}
                if (data.action == 'withdraw') != (first['creator'] == actor):
                    raise HTTPException(403, 'Diese Entscheidung steht der anderen Person zu.')
                conn.execute('DELETE FROM day_closures WHERE batch=?', (batch_id,))
                if data.action == 'reject':
                    notify(conn, first['creator'], f'closure-rejected:{batch_id}', 'Betreuungsfreie Tage abgelehnt',
                           f'{label}: nicht bestätigt. Die bisherige Planung bleibt gültig.')
                self.audit(conn, actor, 'Eintragung zurückgezogen' if data.action == 'withdraw' else 'Eintragung abgelehnt', label)
                return {'ok': True}

    def listing(self, conn, first, last):
        # Pending entries are always listed so the other person sees them in any month.
        rows = conn.execute("SELECT day,kind,note,batch,state,creator FROM day_closures WHERE day BETWEEN ? AND ? "
                            "OR state='pending' ORDER BY day", (str(first), str(last))).fetchall()
        return [dict(r) for r in rows]
