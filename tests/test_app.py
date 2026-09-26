from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from pathlib import Path
import tempfile
import time
import unittest
import os
import sqlite3
import subprocess
import sys

from fastapi.testclient import TestClient
import pyotp
from app import create_app, password_hash


class PlanningTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'family.sqlite'
        self.app = create_app(self.path, demo=True)
        with self.app.state.db() as conn:
            for table in ('work_calendar_items','tasks','proposals','issues','appointments','audit'):
                conn.execute('DELETE FROM ' + table)
        self.tobi = self.client('tobi')
        self.britta = self.client('britta')
        self.deadline = (datetime.now().astimezone()+timedelta(days=2)).isoformat()
        self.day = date.today()+timedelta(days=7)
        while self.day.weekday()>4:
            self.day += timedelta(days=1)
        self.month = self.day.strftime('%Y-%m')

    def tearDown(self):
        self.tobi.close()
        self.britta.close()
        self.tmp.cleanup()

    def client(self, user):
        client=TestClient(self.app, base_url='http://127.0.0.1:8765', headers={'Origin':'http://127.0.0.1:8765','X-Family-Request':'1'})
        self.assertEqual(client.post('/api/login',json={'user':user}).status_code,200)
        return client

    def proposal(self, client=None, **overrides):
        data={'day':str(self.day),'kind':'bring','owner':'tobi','start':'07:45','end':'08:45','expected_version':0,'reason':'Gemeinsam prüfen','deadline':self.deadline}
        data.update(overrides)
        return (client or self.tobi).post('/api/proposals',json=data)

    def state(self, client=None):
        return (client or self.tobi).get('/api/state',params={'month':self.month}).json()

    def approve(self, id, client=None):
        return (client or self.britta).post(f'/api/proposals/{id}/decision',json={'action':'approve'})

    def test_two_person_initial_approval_and_personal_task(self):
        p=self.proposal().json()['id']
        self.assertIsNone(self.state()['appointments'][0]['owner'])
        self.assertEqual(self.approve(p,self.tobi).status_code,403)
        self.assertEqual(self.approve(p).status_code,200)
        s=self.state()
        self.assertEqual(s['appointments'][0]['owner'],'tobi')
        self.assertEqual(len(s['tasks']),1)
        self.assertEqual(s['tasks'][0]['owner'],'tobi')
        self.assertEqual(self.britta.post(f"/api/tasks/{s['tasks'][0]['id']}/complete",json={}).status_code,403)
        self.assertEqual(self.tobi.post(f"/api/tasks/{s['tasks'][0]['id']}/complete",json={}).status_code,200)

    def test_change_preserves_current_owner_until_accepted(self):
        self.approve(self.proposal().json()['id'])
        [task]=self.state()['tasks']
        self.assertEqual(self.tobi.post(f"/api/tasks/{task['id']}/complete",json={}).status_code,200)  # block entered
        p=self.proposal(owner='britta',expected_version=1).json()['id']
        self.assertEqual(self.state()['appointments'][0]['owner'],'tobi')
        self.approve(p)
        s=self.state()
        self.assertEqual(s['appointments'][0]['owner'],'britta')
        self.assertEqual({t['owner'] for t in s['tasks'] if t['state']=='open'},{'tobi','britta'})

    def test_reject_and_revised_proposal_require_new_approval(self):
        p=self.proposal().json()['id']
        self.assertEqual(self.britta.post(f'/api/proposals/{p}/decision',json={'action':'reject'}).status_code,200)
        new=self.proposal(owner='britta').json()['id']
        self.assertNotEqual(p,new)
        self.assertEqual(self.approve(p).status_code,409)
        self.assertIsNone(self.state()['appointments'][0]['owner'])
        self.assertEqual(self.approve(new).status_code,200)

    def test_duplicate_pending_proposal_rejected(self):
        self.proposal()
        self.assertEqual(self.proposal(self.britta).status_code,409)

    def test_stale_revision_rejected(self):
        self.approve(self.proposal().json()['id'])
        self.assertEqual(self.proposal(expected_version=0,owner='britta').status_code,409)

    def test_batch_is_atomic(self):
        p=self.proposal().json()['id']
        response=self.britta.post('/api/proposals/approve-batch',json={'ids':[p,999999]})
        self.assertEqual(response.status_code,409)
        self.assertIsNone(self.state()['appointments'][0]['owner'])
        self.assertEqual(self.state()['tasks'],[])

    def test_concurrent_confirmations_produce_one_change(self):
        p=self.proposal().json()['id']
        with ThreadPoolExecutor(2) as pool:
            codes=list(pool.map(lambda _:self.approve(p).status_code,range(2)))
        self.assertEqual(sorted(codes),[200,409])
        self.assertEqual(len(self.state()['tasks']),1)

    def test_issue_owner_and_approved_resolution(self):
        self.approve(self.proposal().json()['id'])
        slot=self.state()['appointments'][0]
        self.tobi.post('/api/issues',json={'appointment_id':slot['id'],'text':'Ich kann nicht','deadline':self.deadline})
        issue=self.state()['issues'][0]
        self.assertEqual(issue['owner'],'tobi')
        self.assertEqual(self.britta.post(f"/api/issues/{issue['id']}/resolve",json={'version':1,'resolution':'Besprochen'}).status_code,403)
        p=self.proposal(owner='britta',expected_version=1,issue_id=issue['id']).json()['id']
        self.approve(p)
        self.assertEqual(self.state()['issues'],[])

    def test_deadline_does_not_approve_automatically(self):
        p=self.proposal().json()['id']
        with self.app.state.db() as conn:
            conn.execute("UPDATE proposals SET deadline='2020-01-01T12:00:00+01:00' WHERE id=?",(p,))
        self.assertIsNone(self.state()['appointments'][0]['owner'])
        self.assertEqual(len(self.state()['proposals']),1)

    def test_restart_preserves_state(self):
        self.approve(self.proposal().json()['id'])
        restarted=create_app(self.path,demo=True)
        with restarted.state.db() as conn:
            self.assertEqual(conn.execute('SELECT owner FROM appointments').fetchone()[0],'tobi')

    def test_backup_contains_consistent_approved_plan(self):
        self.approve(self.proposal().json()['id'])
        output=Path(self.tmp.name)/'backup.sqlite'
        subprocess.run([sys.executable,'manage.py','backup','--output',str(output)],
                       env={**os.environ,'FOS_DB':str(self.path)},check=True,capture_output=True)
        with sqlite3.connect(output) as conn:
            self.assertEqual(conn.execute('PRAGMA integrity_check').fetchone()[0],'ok')
            self.assertEqual(conn.execute('SELECT owner FROM appointments').fetchone()[0],'tobi')
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM tasks').fetchone()[0],1)

    def test_empty_month_draft_balanced_and_not_overwritten(self):
        data={'month':'2027-02','bring_start':'07:45','bring_end':'08:45','pickup_start':'15:30','pickup_end':'17:30'}
        self.assertEqual(self.tobi.post('/api/month-draft',json=data).status_code,200)
        s=self.tobi.get('/api/state?month=2027-02').json()
        proposals=[p for p in s['proposals'] if p['day'].startswith('2027-02')]
        self.assertEqual(len(proposals),40)
        self.assertEqual(sum(p['owner']=='tobi' for p in proposals),20)
        self.assertTrue(all(a['owner'] is None for a in s['appointments']))
        self.assertEqual(self.tobi.post('/api/month-draft',json=data).status_code,409)

    def start_joint(self, client=None):
        response = (client or self.tobi).post('/api/planning/start', json={})
        self.assertEqual(response.status_code, 200)
        return response.json()['id']

    def test_joint_direct_assignment_and_followup_tasks(self):
        mode = self.start_joint()
        response = self.proposal(planning_session=mode)
        self.assertEqual(response.status_code, 200)
        s = self.state()
        self.assertEqual(s['planning']['id'], mode)
        self.assertEqual(s['appointments'][0]['owner'], 'tobi')
        self.assertEqual(s['proposals'], [])
        self.assertEqual(len(s['tasks']), 1)
        self.app.state.integrations.reconcile()
        with self.app.state.db() as conn:
            targets = conn.execute("SELECT key FROM calendar_targets WHERE key NOT LIKE 'nanny-%'").fetchall()
            self.assertEqual([r[0] for r in targets], ['slot-' + str(s['appointments'][0]['id'])])
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM notifications WHERE dedupe LIKE 'proposal:%'").fetchone()[0], 0)
        self.assertEqual(self.proposal(planning_session=mode,owner='britta',expected_version=1).status_code,200)
        # Tobi never entered the block: his add and remove cancel out (B-18).
        self.assertEqual({t['owner'] for t in self.state()['tasks'] if t['state']=='open'}, {'britta'})
        self.assertEqual(self.proposal(planning_session=mode,expected_version=1).status_code,409)

    def test_joint_mode_does_not_apply_to_other_login_or_unmarked_request(self):
        mode = self.start_joint()
        self.assertIsNone(self.state(self.britta)['planning'])
        self.assertEqual(self.proposal(self.britta,planning_session=mode).status_code,409)
        with self.client('tobi') as other:
            self.assertEqual(self.proposal(other,planning_session=mode).status_code,409)
        self.assertEqual(self.proposal().status_code,200)
        self.assertIsNone(self.state()['appointments'][0]['owner'])

    def test_joint_mode_expiry_and_stop_reject_stale_dialogs(self):
        mode = self.start_joint()
        self.assertEqual(self.start_joint(),mode)
        with self.app.state.db() as conn:
            conn.execute('UPDATE planning_sessions SET expires=?',(time.time()-1,))
        self.assertEqual(self.proposal(planning_session=mode).status_code,409)
        self.assertEqual(self.state()['appointments'],[])
        mode = self.start_joint()
        self.tobi.post('/api/planning/stop',json={})
        self.assertEqual(self.proposal(planning_session=mode).status_code,409)
        self.assertIsNone(self.state()['planning'])
        self.assertEqual(self.proposal().status_code,200)
        self.assertIsNone(self.state()['appointments'][0]['owner'])

    def test_joint_mode_logout_revokes_and_restart_preserves_expiry(self):
        mode = self.start_joint()
        restarted = create_app(self.path,demo=True)
        with restarted.state.db() as conn:
            self.assertGreater(conn.execute('SELECT expires FROM planning_sessions WHERE id=?',(mode,)).fetchone()[0],time.time())
        self.tobi.post('/api/logout',json={})
        self.tobi.post('/api/login',json={'user':'tobi'})
        self.assertEqual(self.proposal(planning_session=mode).status_code,409)

    def test_joint_mode_start_does_not_silently_accept_existing_proposals(self):
        pid = self.proposal().json()['id']
        mode = self.start_joint()
        self.assertIsNone(self.state()['appointments'][0]['owner'])
        response = self.tobi.post(f'/api/proposals/{pid}/decision',json={'action':'approve','planning_session':mode})
        self.assertEqual(response.status_code,200)
        self.assertEqual(self.state()['appointments'][0]['owner'],'tobi')

    def test_joint_batch_still_atomic(self):
        pid = self.proposal().json()['id']
        mode = self.start_joint()
        self.assertEqual(self.tobi.post('/api/proposals/approve-batch',json={'ids':[pid,999],'planning_session':mode}).status_code,409)
        self.assertIsNone(self.state()['appointments'][0]['owner'])
        self.assertEqual(self.tobi.post('/api/proposals/approve-batch',json={'ids':[pid],'planning_session':mode}).status_code,200)
        self.assertEqual(self.state()['appointments'][0]['owner'],'tobi')

    def test_auth_csrf_and_input_validation(self):
        anonymous=TestClient(self.app,base_url='http://127.0.0.1:8765')
        self.assertEqual(anonymous.get('/api/state?month=2026-09').status_code,401)
        self.assertEqual(anonymous.post('/api/login',json={'user':'tobi'}).status_code,403)
        self.assertEqual(self.proposal(end='06:00').status_code,422)
        self.assertEqual(self.proposal(deadline='2026-01-01T10:00:00').status_code,422)
        self.assertEqual(self.proposal(reason='   ').status_code,422)
        self.assertEqual(self.proposal(issue_id=0).status_code,422)


class AuthenticationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.path=Path(self.tmp.name)/'production.sqlite'
        self.app=create_app(self.path,demo=False,origin='https://family.test')
        self.secret=pyotp.random_base32()
        with self.app.state.db() as conn:
            conn.execute('INSERT INTO users(id,password,totp) VALUES(?,?,?)',('tobi',password_hash('a-test-password-123'),self.secret))
        self.client=TestClient(self.app,base_url='https://family.test',headers={'Origin':'https://family.test','X-Family-Request':'1'})

    def tearDown(self):
        self.client.close()
        self.tmp.cleanup()

    def login(self,**changes):
        data={'user':'tobi','password':'a-test-password-123','code':pyotp.TOTP(self.secret).now()}
        data.update(changes)
        return self.client.post('/api/login',json=data)

    def test_single_account_planning_fails_cleanly_then_succeeds_with_partner(self):
        self.assertEqual(self.login().status_code, 200)
        day = date.today() + timedelta(days=7)
        while day.weekday() > 4:
            day += timedelta(days=1)
        deadline = (datetime.now().astimezone() + timedelta(days=2)).isoformat()
        data = {'day':str(day),'kind':'bring','owner':'tobi','start':'07:45','end':'08:45','expected_version':0,'reason':'Gemeinsam prüfen','deadline':deadline}
        response = self.client.post('/api/proposals', json=data)
        self.assertEqual(response.status_code, 409)
        self.assertIn('Britta', response.json()['detail'])
        issue = self.client.post('/api/issues', json={'text':'Besprechen','deadline':deadline})
        self.assertEqual(issue.status_code, 409)
        self.assertIn('Britta', issue.json()['detail'])
        month = self.client.post('/api/month-draft', json={'month':'2027-02','bring_start':'07:45','bring_end':'08:45','pickup_start':'15:30','pickup_end':'17:30'})
        self.assertEqual(month.status_code, 409)
        with self.app.state.db() as conn:
            for table in ('work_calendar_items','appointments','proposals','issues','notifications'):
                self.assertEqual(conn.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0], 0)
            conn.execute('INSERT INTO users(id,password,totp) VALUES(?,?,?)', ('britta', password_hash('test-password-123'), pyotp.random_base32()))
        self.assertEqual(self.client.post('/api/proposals', json=data).status_code, 200)
        with self.app.state.db() as conn:
            self.assertEqual(conn.execute('SELECT owner FROM notifications').fetchone()[0], 'britta')
            self.assertEqual(conn.execute('SELECT state FROM proposals').fetchone()[0], 'pending')

    def test_password_and_mfa_required_and_otp_replay_blocked(self):
        self.assertEqual(self.login(code='').status_code,401)
        code=pyotp.TOTP(self.secret).now()
        response=self.login(code=code)
        self.assertEqual(response.status_code,200)
        self.assertIn('Secure',response.headers['set-cookie'])
        self.assertIn('HttpOnly',response.headers['set-cookie'])
        self.assertEqual(self.login(code=code).status_code,401)

    def test_rate_limit_persisted(self):
        for _ in range(8):
            self.assertEqual(self.login(password='wrong').status_code,401)
        self.assertEqual(self.login().status_code,429)

    def test_expired_session_denied(self):
        self.assertEqual(self.login().status_code,200)
        with self.app.state.db() as conn:
            conn.execute('UPDATE sessions SET expires=?',(time.time()-1,))
        self.assertEqual(self.client.get('/api/state?month=2026-09').status_code,401)

    def test_modes_cannot_mix(self):
        with self.assertRaises(RuntimeError):
            create_app(self.path,demo=True)


if __name__=='__main__':
    unittest.main()
