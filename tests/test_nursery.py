"""Nursery dates from letters (B-19)."""
import asyncio
from datetime import date, datetime, timedelta
import io
import json
from pathlib import Path
import tempfile
import unittest
import zipfile
from zoneinfo import ZoneInfo

import httpx
from fastapi.testclient import TestClient

from app import create_app
import nursery
from nursery import docx_text, local_items, redact

TZ = ZoneInfo('Europe/Berlin')
BASE = 'http://127.0.0.1:8765'


def docx(paragraphs, rows=()):
    """Minimal .docx with paragraphs and one table."""
    ns = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    body = ''.join(f'<w:p><w:r><w:t>{p}</w:t></w:r></w:p>' for p in paragraphs)
    if rows:
        body += '<w:tbl>' + ''.join('<w:tr>' + ''.join(f'<w:tc><w:p><w:r><w:t>{c}</w:t></w:r></w:p></w:tc>' for c in row)
                                    + '</w:tr>' for row in rows) + '</w:tbl>'
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        archive.writestr('word/document.xml', f'<w:document {ns}><w:body>{body}</w:body></w:document>')
    return buffer.getvalue()


class TextTests(unittest.TestCase):
    def test_docx_paragraphs_and_table_rows(self):
        data = docx(['Liebe Eltern,', 'am Freitag feiern wir Mini-Wiesn.'], [['02.10.', 'Mini-Wiesn', '9–11 Uhr']])
        self.assertEqual(docx_text(data), 'Liebe Eltern,\nam Freitag feiern wir Mini-Wiesn.\n02.10. | Mini-Wiesn | 9–11 Uhr')

    def test_old_doc_or_garbage_is_rejected(self):
        with self.assertRaises(Exception) as context:
            docx_text(b'\xd0\xcf\x11\xe0 not a zip')
        self.assertIn('.docx', context.exception.detail)

    def test_redaction_keeps_dates_and_removes_contacts(self):
        text = ('Mini-Wiesn am 02.10. um 9:00 Uhr. Fragen an kita@example.org oder 089 1234567, '
                'Musterstraße 12, 80331 München, www.example.org')
        cleaned = redact(text)
        self.assertIn('02.10.', cleaned)
        self.assertIn('9:00', cleaned)
        for secret in ('kita@example.org', '1234567', 'Musterstraße 12', '80331', 'www.example.org'):
            self.assertNotIn(secret, cleaned)

    def test_local_recognition(self):
        today = date(2026, 9, 28)
        text = ('Fr, 02.10. Mini-Wiesn 9:00 - 11:00 Uhr, bitte Tracht mitbringen\n'
                'Am 23.10. schließt die Krippe bereits um 14:00 Uhr\n'
                '24.12. - 31.12. Krippe geschlossen\n'
                'Laternenfest am 11. November 17 Uhr\n'
                'Ohne Datum: allgemeiner Hinweis')
        items = local_items(text, today)
        kinds = [(i['day'], i['kind']) for i in items]
        self.assertIn(('2026-10-02', 'event'), kinds)
        self.assertIn(('2026-10-23', 'early_close'), kinds)
        self.assertIn(('2026-12-24', 'closed'), kinds)
        self.assertIn(('2026-11-11', 'event'), kinds)
        wiesn = next(i for i in items if i['day'] == '2026-10-02')
        self.assertEqual((wiesn['start'], wiesn['end']), ('09:00', '11:00'))
        self.assertIn('Mini-Wiesn', wiesn['title'])
        self.assertEqual(next(i for i in items if i['kind'] == 'early_close')['end'], '14:00')
        self.assertEqual(next(i for i in items if i['kind'] == 'closed')['until'], '2026-12-31')

    def test_dates_without_year_roll_into_next_year(self):
        items = local_items('08.01. Neujahrsfrühstück', date(2026, 9, 28))
        self.assertEqual(items[0]['day'], '2027-01-08')


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = create_app(Path(self.tmp.name) / 'family.sqlite', demo=True)
        self.today = datetime.now(TZ).date()
        self.tobi = self.client('tobi')

    def tearDown(self):
        self.tobi.close()
        self.tmp.cleanup()

    def client(self, user):
        client = TestClient(self.app, base_url=BASE, headers={'Origin': BASE, 'X-Family-Request': '1'})
        self.assertEqual(client.post('/api/login', json={'user': user}).status_code, 200)
        return client

    def next_weekday(self, offset=3):
        day = self.today + timedelta(days=offset)
        while day.weekday() > 4:
            day += timedelta(days=1)
        return day

    def test_upload_suggests_without_saving(self):
        day = self.next_weekday()
        data = docx([f'{day.strftime("%d.%m.%Y")} Mini-Wiesn 9:00 - 11:00 Uhr'])
        response = self.tobi.post('/api/nursery/import/docx', content=data,
                                  headers={'Content-Type': 'application/octet-stream'})
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result['source'], 'local')  # demo never calls Claude
        self.assertEqual(result['items'][0]['day'], str(day))
        with self.app.state.db() as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM nursery_events').fetchone()[0], 0)

    def test_upload_needs_login_and_size_limit(self):
        anonymous = TestClient(self.app, base_url=BASE, headers={'Origin': BASE, 'X-Family-Request': '1'})
        self.assertEqual(anonymous.post('/api/nursery/import/docx', content=docx(['x'])).status_code, 401)
        anonymous.close()
        big = b'0' * (nursery.MAX_FILE + 1)
        self.assertEqual(self.tobi.post('/api/nursery/import/docx', content=big).status_code, 413)

    def test_saving_event_early_close_and_closed_day(self):
        early = self.next_weekday(4)
        closed = self.next_weekday(8)
        with self.app.state.db() as conn:
            conn.execute("INSERT INTO appointments(day,kind,owner,start,end) VALUES(?,'pickup','britta','15:30','17:30') "
                         "ON CONFLICT(day,kind) DO UPDATE SET owner='britta',start='15:30',end='17:30'", (str(early),))
        items = [{'day': str(self.today), 'kind': 'event', 'title': 'Mini-Wiesn', 'start': '09:00', 'end': '11:00', 'note': 'Tracht'},
                 {'day': str(early), 'kind': 'early_close', 'title': 'Teamtag', 'end': '14:00'},
                 {'day': str(closed), 'kind': 'closed', 'title': 'Schließtag'}]
        response = self.tobi.post('/api/nursery/events', json={'items': items, 'source': 'import'})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {'saved': 2, 'closed': 1, 'tasks': ['Britta']})
        with self.app.state.db() as conn:
            task = conn.execute("SELECT owner,title FROM tasks WHERE title LIKE 'Abholung früher%'").fetchone()
            self.assertEqual(tuple(task), ('britta', 'Abholung früher: Krippe schließt 14:00'))
            closure = conn.execute('SELECT kind,state FROM day_closures WHERE day=?', (str(closed),)).fetchone()
            self.assertEqual(tuple(closure), ('closed', 'pending'))  # the other parent confirms
            notice = conn.execute("SELECT body FROM notifications WHERE owner='britta' AND title='Neue Krippen-Termine'").fetchone()
            self.assertIn('Mini-Wiesn', notice[0])
            # The planned pickup itself is unchanged (B-11).
            self.assertEqual(conn.execute("SELECT start FROM appointments WHERE day=? AND kind='pickup'", (str(early),)).fetchone()[0], '15:30')
        state = self.tobi.get('/api/state', params={'month': str(self.today)[:7]}).json()
        today = state['today_summary']['days'][0]
        self.assertIn('Mini-Wiesn · 09:00', today['nursery'])
        self.assertTrue(any(e['title'] == 'Mini-Wiesn' for e in state['nursery_events']))

    def test_delete_and_validation(self):
        response = self.tobi.post('/api/nursery/events', json={'items': [{'day': str(self.today), 'kind': 'early_close', 'title': 'x'}]})
        self.assertEqual(response.status_code, 422)
        response = self.tobi.post('/api/nursery/events', json={'items': [{'day': str(self.today), 'kind': 'event', 'title': 'Fest',
                                                                            'start': '11:00', 'end': '10:00'}]})
        self.assertEqual(response.status_code, 422)
        self.tobi.post('/api/nursery/events', json={'items': [{'day': str(self.today), 'kind': 'event', 'title': 'Fest'}]})
        with self.app.state.db() as conn:
            event_id = conn.execute('SELECT id FROM nursery_events').fetchone()[0]
        self.assertEqual(self.tobi.post(f'/api/nursery/events/{event_id}/delete', json={}).status_code, 200)
        self.assertEqual(self.tobi.post(f'/api/nursery/events/{event_id}/delete', json={}).status_code, 409)


class ClaudeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = create_app(Path(self.tmp.name) / 'family.sqlite', demo=True)
        self.requests = []

    def tearDown(self):
        self.tmp.cleanup()

    def service(self, handler, calls=40):
        def transport(request):
            self.requests.append(json.loads(request.content))
            return handler(request)
        return nursery.Nursery(self.app.state.db, False, None, api_key='test', monthly_calls=calls,
                               transport=httpx.MockTransport(transport))

    def test_claude_gets_redacted_text_and_results_are_validated(self):
        today = datetime.now(TZ).date()
        good = str(today + timedelta(days=4))
        answer = {'content': [{'type': 'tool_use', 'name': 'termine', 'input': {'termine': [
            {'datum': good, 'art': 'veranstaltung', 'titel': 'Mini-Wiesn', 'beginn': '09:00', 'ende': '11:00', 'hinweis': 'Tracht'},
            {'datum': good, 'art': 'frueher_schluss', 'titel': 'Teamtag', 'schluss': '14:00'},
            {'datum': 'kein Datum', 'art': 'veranstaltung', 'titel': 'kaputt'},
            {'datum': good, 'art': 'party', 'titel': 'unbekannte Art'},
            {'datum': good, 'art': 'frueher_schluss', 'titel': 'ohne Uhrzeit'},
        ]}}], 'usage': {'input_tokens': 500, 'output_tokens': 80}}
        service = self.service(lambda request: httpx.Response(200, json=answer))
        result = asyncio.run(service.analyse('Mini-Wiesn, Rückfragen an kita@example.org oder 089 1234567'))
        self.assertEqual(result['source'], 'claude')
        self.assertEqual([(i['kind'], i['title']) for i in result['items']], [('early_close', 'Teamtag'), ('event', 'Mini-Wiesn')])
        sent = self.requests[0]['messages'][0]['content']
        self.assertNotIn('kita@example.org', sent)
        self.assertNotIn('1234567', sent)
        self.assertIn(str(today), sent)  # for years that are missing in the letter
        self.assertEqual(result['sent'], nursery.redact('Mini-Wiesn, Rückfragen an kita@example.org oder 089 1234567'))
        with self.app.state.db() as conn:
            self.assertEqual(service.usage(conn)['calls'], 1)

    def test_falls_back_to_local_on_error_and_limit(self):
        day = (datetime.now(TZ).date() + timedelta(days=5)).strftime('%d.%m.%Y')
        service = self.service(lambda request: httpx.Response(500))
        result = asyncio.run(service.analyse(f'{day} Laternenfest 17 Uhr'))
        self.assertEqual(result['source'], 'local')
        self.assertIn('nicht erreichbar', result['notice'])
        self.assertEqual(len(result['items']), 1)
        limited = self.service(lambda request: httpx.Response(500), calls=1)
        with self.app.state.db() as conn:
            conn.execute("INSERT OR REPLACE INTO metadata VALUES(?,?)",
                         ('claude_usage:' + datetime.now(TZ).strftime('%Y-%m'), json.dumps({'calls': 1, 'input_tokens': 0, 'output_tokens': 0})))
        self.requests.clear()
        result = asyncio.run(limited.analyse(f'{day} Laternenfest 17 Uhr'))
        self.assertEqual(self.requests, [])
        self.assertIn('Monatslimit', result['notice'])


if __name__ == '__main__':
    unittest.main()
