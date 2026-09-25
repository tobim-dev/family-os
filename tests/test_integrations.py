from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from urllib.parse import urlparse, parse_qs
from zoneinfo import ZoneInfo
import httpx
from fastapi.testclient import TestClient
from app import create_app
from integrations import notify, Subscription, validate_subscription
from fastapi import HTTPException

class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.path=Path(self.tmp.name)/'db.sqlite'
        self.app=create_app(self.path,demo=True)
        self.service=self.app.state.integrations
        self.client=TestClient(self.app,base_url='http://127.0.0.1:8765',headers={'Origin':'http://127.0.0.1:8765','X-Family-Request':'1'})
        self.client.post('/api/login',json={'user':'tobi'})
        with self.app.state.db() as c:
            for table in ('tasks','proposals','issues','appointments','audit'):
                c.execute('DELETE FROM '+table)
            c.execute("INSERT INTO appointments VALUES(1,'2027-03-29','bring','tobi','07:45','08:45',1)")
        self.remote={};self.calls=[];self.etag=0
        self.service.google=self.google
        self.service.reconcile()
    def tearDown(self):
        self.client.close();self.tmp.cleanup()
    def google(self,method,eid,body=None,etag=None):
        self.calls.append(method)
        if method=='GET':return httpx.Response(200,json=self.remote[eid]) if eid in self.remote else httpx.Response(404)
        if method=='POST' and eid in self.remote:return httpx.Response(409)
        if method in ('PUT','DELETE') and etag!=self.remote[eid]['etag']:return httpx.Response(412)
        if method=='DELETE':
            del self.remote[eid];return httpx.Response(204)
        self.etag+=1;self.remote[eid]={**body,'etag':str(self.etag)}
        return httpx.Response(200,json=self.remote[eid])
    def target(self,key='slot-1'):
        with self.app.state.db() as c:return dict(c.execute('SELECT * FROM calendar_targets WHERE key=?',(key,)).fetchone())
    def sync(self,key='slot-1'):self.service.sync_one(self.target(key))
    def proposal(self):
        with self.app.state.db() as c:c.execute("INSERT INTO proposals(id,appointment_id,owner,start,end,creator,reason,deadline,base_version,created) VALUES(1,1,'britta','08:00','09:00','tobi','Private Adresse','2027-03-25T19:00:00+01:00',1,'2027-03-01')")
        self.service.reconcile()
    def test_tentative_separate_privacy_and_dst(self):
        self.proposal();self.sync();self.sync('proposal-1')
        self.assertEqual(len(self.remote),2)
        self.assertEqual({b['status'] for b in self.remote.values()},{'tentative','confirmed'})
        self.assertNotIn('Private Adresse',json.dumps(self.remote))
        self.assertIn('+02:00',next(iter(self.remote.values()))['start']['dateTime'])
    def test_lost_insert_response_recovers_after_restart_without_duplicate(self):
        def interrupted(method,*args,**kwargs):
            result=self.google(method,*args,**kwargs)
            if method=='POST':raise TimeoutError()
            return result
        self.service.google=interrupted
        with self.assertRaises(TimeoutError):self.sync()
        self.service=create_app(self.path,demo=True).state.integrations
        self.service.google=self.google;self.sync()
        self.assertEqual(self.target()['state'],'synced');self.assertEqual(self.calls.count('POST'),1)
    def test_external_edit_and_deletion_stop_sync(self):
        self.sync();eid=self.target()['event_id']
        self.remote[eid]['summary']='Extern';self.remote[eid]['etag']='external'
        self.sync();self.sync()
        self.assertEqual(self.target()['state'],'conflict');self.assertNotIn('PUT',self.calls)
        with self.app.state.db() as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM notifications').fetchone()[0],2)
        del self.remote[eid];self.sync()
        self.assertEqual(self.target()['state'],'conflict');self.assertEqual(len(self.remote),0)
    def test_confirmed_replacement_before_tentative_removal(self):
        self.proposal();self.sync();self.sync('proposal-1');eid=self.target('proposal-1')['event_id']
        with self.app.state.db() as c:
            c.execute("UPDATE proposals SET state='accepted'");c.execute("UPDATE appointments SET owner='britta',version=2")
        self.service.reconcile();self.sync('proposal-1');self.assertIn(eid,self.remote)
        self.sync();self.sync('proposal-1');self.assertNotIn(eid,self.remote)
    def test_local_change_during_network_stays_queued(self):
        def changed(method,*args,**kwargs):
            result=self.google(method,*args,**kwargs)
            if method=='POST':
                with self.app.state.db() as c:c.execute("UPDATE appointments SET owner='britta',version=2")
                self.service.reconcile()
            return result
        self.service.google=changed;self.sync();self.assertEqual(self.target()['state'],'queued')
        self.service.google=self.google;self.sync();self.assertEqual(self.target()['state'],'synced')
    def test_notifications_personal_and_read_does_not_approve(self):
        self.client.post('/api/push/test',json={});notice=self.client.get('/api/connections').json()['notifications'][0]
        self.client.post('/api/login',json={'user':'britta'})
        self.client.post(f"/api/notifications/{notice['id']}/read",json={})
        self.assertEqual(self.client.get('/api/connections').json()['notifications'],[])
        self.client.post('/api/login',json={'user':'tobi'})
        self.assertIsNone(self.client.get('/api/connections').json()['notifications'][0]['read_at'])
        self.client.post(f"/api/notifications/{notice['id']}/read",json={})
        self.assertIsNotNone(self.client.get('/api/connections').json()['notifications'][0]['read_at'])
        self.assertEqual(self.target()['state'],'queued')
    def test_quiet_hours_and_dst(self):
        instant=datetime(2027,3,27,23,tzinfo=ZoneInfo('Europe/Berlin'))
        with self.app.state.db() as c:
            notify(c,'tobi','normal','Test','',False,instant);notify(c,'tobi','urgent','Test','',True,instant)
            rows={r['dedupe']:r['not_before'] for r in c.execute('SELECT * FROM notifications')}
        self.assertEqual(datetime.fromtimestamp(rows['normal'],ZoneInfo('Europe/Berlin')).isoformat(),'2027-03-28T07:00:00+02:00')
        self.assertEqual(rows['urgent'],instant.timestamp())
    def test_daily_weekly_deduplication_after_restart(self):
        instant=datetime(2027,3,28,19,tzinfo=ZoneInfo('Europe/Berlin'))
        self.service.summaries(instant)
        create_app(self.path,demo=True).state.integrations.summaries(instant+timedelta(minutes=20))
        with self.app.state.db() as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM notifications').fetchone()[0],4)
    def test_demo_no_external_calls(self):
        with patch('integrations.httpx.request',side_effect=AssertionError()),patch('integrations.webpush',side_effect=AssertionError()):
            self.service.tick();self.assertEqual(self.client.post('/api/google/connect',json={}).status_code,409)
    def test_push_rejects_arbitrary_hosts(self):
        for endpoint in ('http://web.push.apple.com/test','https://127.0.0.1/test','https://web.push.apple.com.evil.test/test','https://evil@web.push.apple.com/test'):
            with self.assertRaises(HTTPException):validate_subscription(Subscription(endpoint=endpoint,keys={}))

    def test_reminders_owned_deduped_without_approval(self):
        self.proposal()
        instant=datetime(2027,3,29,9,tzinfo=ZoneInfo('Europe/Berlin'))
        with self.app.state.db() as c:
            c.execute("INSERT INTO tasks(owner,title,details,due,created) VALUES('tobi','Arbeitskalender aktualisieren','','2027-03-28T10:00:00+02:00','2027-03-28')")
        self.service.summaries(instant);self.service.summaries(instant+timedelta(minutes=2))
        with self.app.state.db() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM notifications').fetchone()[0],2)
            self.assertEqual(c.execute('SELECT state FROM proposals').fetchone()[0],'pending')

class GoogleSetupTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)
        file=self.path/'client.json';file.write_text(json.dumps({'web':{'client_id':'test-id','client_secret':'test-secret'}}))
        self.env=patch.dict('os.environ',{'FOS_GOOGLE_CALENDAR_ID':'shared','FOS_GOOGLE_CLIENT_FILE':str(file)});self.env.start()
        self.app=create_app(self.path/'db.sqlite',demo=False,origin='https://fos.test')
        self.client=TestClient(self.app,base_url='https://fos.test',headers={'Origin':'https://fos.test','X-Family-Request':'1'})
        with self.app.state.db() as c:
            c.execute("INSERT INTO users VALUES('tobi','unused','unused',-1)")
            c.execute('INSERT INTO sessions VALUES(?,?,?)',(hashlib.sha256(b'test-session').hexdigest(),'tobi',time.time()+1000))
        self.client.cookies.set('fos_session','test-session')
    def tearDown(self):self.client.close();self.env.stop();self.tmp.cleanup()
    def start(self):return parse_qs(urlparse(self.client.post('/api/google/connect',json={}).json()['url']).query)
    def test_oauth_single_use_cookie_bound_encrypted(self):
        params=self.start();self.assertIn('code_challenge',params);state=params['state'][0]
        with TestClient(self.app,base_url='https://fos.test') as anonymous:
            self.assertEqual(anonymous.get('/api/google/callback',params={'state':state,'code':'abc'}).status_code,403)
        with patch('integrations.httpx.post',return_value=httpx.Response(200,json={'refresh_token':'sensitive-refresh','access_token':'sensitive-access','expires_in':3600})):
            response=self.client.get('/api/google/callback',params={'state':state,'code':'abc'},follow_redirects=False)
        self.assertEqual(response.status_code,303)
        self.assertEqual(self.client.get('/api/google/callback',params={'state':state,'code':'abc'}).status_code,403)
        with self.app.state.db() as c:self.assertNotIn('sensitive',c.execute('SELECT value FROM integration_secrets').fetchone()[0])
        self.assertEqual(self.app.state.integrations.secret('google')['refresh_token'],'sensitive-refresh')
        self.assertEqual((self.path/'integration.key').stat().st_mode&0o777,0o600)
    def test_logout_invalidates_oauth(self):
        state=self.start()['state'][0];self.client.post('/api/logout',json={})
        self.assertEqual(self.client.get('/api/google/callback',params={'state':state,'code':'abc'}).status_code,403)
    def test_missing_encryption_key_fails_closed(self):
        self.app.state.integrations.save_secret('google',{'refresh_token':'test'});(self.path/'integration.key').unlink()
        with self.assertRaises(RuntimeError):create_app(self.path/'db.sqlite',demo=False,origin='https://fos.test')

    def test_backup_includes_encryption_and_push_keys(self):
        import os, subprocess, sys
        self.app.state.integrations.save_secret('google',{'refresh_token':'test'})
        output=self.path/'backup.sqlite'
        subprocess.run([sys.executable,'manage.py','backup','--output',str(output)],env={**os.environ,'FOS_DB':str(self.path/'db.sqlite')},check=True,capture_output=True)
        self.assertEqual((self.path/'backup.sqlite.keys/integration.key').read_bytes(),(self.path/'integration.key').read_bytes())
        self.assertTrue((self.path/'backup.sqlite.keys/push-private.pem').exists())
        self.assertTrue((self.path/'backup.sqlite.keys/google-client.json').exists())

    def test_push_acceptance_retry_and_expired_subscription(self):
        from pywebpush import WebPushException
        service=self.app.state.integrations
        with self.app.state.db() as c:
            c.execute("INSERT INTO push_subscriptions(owner,endpoint,subscription) VALUES('tobi','https://web.push.apple.com/test','{}')")
            notify(c,'tobi','push-test','Test','Test')
        with patch('integrations.webpush',side_effect=TimeoutError()):service.deliver_push()
        with self.app.state.db() as c:
            row=c.execute('SELECT * FROM push_deliveries').fetchone();self.assertEqual(row['state'],'queued');self.assertGreater(row['next_try'],time.time())
            c.execute('UPDATE push_deliveries SET next_try=0')
        with patch('integrations.webpush',return_value=None):service.deliver_push()
        with self.app.state.db() as c:
            self.assertEqual(c.execute('SELECT state FROM push_deliveries').fetchone()[0],'accepted')
            self.assertIsNone(c.execute('SELECT read_at FROM notifications').fetchone()[0])
            notify(c,'tobi','push-expired','Test','Test')
        with patch('integrations.webpush',side_effect=WebPushException('gone',response=httpx.Response(410))):service.deliver_push()
        with self.app.state.db() as c:self.assertEqual(c.execute('SELECT active FROM push_subscriptions').fetchone()[0],0)

    def test_calendar_restore_requires_review_of_current_state(self):
        service=self.app.state.integrations
        with self.app.state.db() as c:c.execute("INSERT INTO appointments VALUES(1,'2027-03-29','bring','tobi','07:45','08:45',1)")
        service.reconcile()
        with self.app.state.db() as c:
            target=dict(c.execute('SELECT * FROM calendar_targets').fetchone())
            c.execute("UPDATE calendar_targets SET state='conflict',etag='old'")
        remote={**json.loads(target['desired']),'etag':'new','summary':'Extern'}
        service.google=lambda *args,**kwargs:httpx.Response(200,json=remote)
        review=self.client.post('/api/google/review',json={'key':'slot-1'}).json()
        self.assertEqual(review['etag'],'new')
        stale=self.client.post('/api/google/restore',json={'key':'slot-1','etag':'old','desired':review['desired']})
        self.assertEqual(stale.status_code,409)
        success=self.client.post('/api/google/restore',json={'key':'slot-1','etag':review['etag'],'desired':review['desired']})
        self.assertEqual(success.status_code,200)
        with self.app.state.db() as c:
            row=c.execute('SELECT * FROM calendar_targets').fetchone();self.assertEqual(row['state'],'queued');self.assertEqual(row['etag'],'new')

if __name__=='__main__':unittest.main()
