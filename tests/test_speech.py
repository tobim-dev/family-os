"""Local speech-to-text (A-01, A-02, O-09) with a stand-in model; the audio decoding is real."""
import io
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace as Row
from unittest.mock import patch

import av
import numpy as np
from fastapi.testclient import TestClient
from faster_whisper.audio import decode_audio

from app import create_app
from speech import Speech, clean


def mp4_audio(seconds=2.0):
    """AAC in MP4, the format Safari records on the iPhone."""
    buffer = io.BytesIO()
    container = av.open(buffer, 'w', format='mp4')
    stream = container.add_stream('aac', rate=48000)
    stream.layout = 'mono'
    samples = (0.2 * np.sin(2 * np.pi * 220 * np.arange(int(48000 * seconds)) / 48000)).astype(np.float32)
    for start in range(0, len(samples), 1024):
        frame = av.AudioFrame.from_ndarray(samples[start:start + 1024].reshape(1, -1), format='fltp', layout='mono')
        frame.sample_rate = 48000
        for packet in stream.encode(frame):
            container.mux(packet)
    for packet in stream.encode():
        container.mux(packet)
    container.close()
    return buffer.getvalue()


def segment(text, no_speech=0.1, logprob=-0.2):
    return Row(text=text, no_speech_prob=no_speech, avg_logprob=logprob)


class FakeModel:
    """Decodes the uploaded audio for real, then returns prepared segments."""
    def __init__(self, segments):
        self.segments = segments
        self.seen = []

    def transcribe(self, audio, **options):
        self.options = options
        decoded = decode_audio(audio)
        self.seen.append(len(decoded) / 16000)
        return iter(self.segments), Row(duration=len(decoded) / 16000)


class SpeechTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.app = create_app(self.dir / 'family.sqlite', demo=True)
        self.speech = self.app.state.speech
        self.speech.demo, self.speech.enabled, self.speech.state = False, True, 'ready'
        self.model = FakeModel([segment(' Lina braucht neue '), segment('Gummistiefel in Größe 24.')])
        self.speech.model = self.model
        self.client = TestClient(self.app, base_url='http://127.0.0.1:8765',
                                 headers={'Origin': 'http://127.0.0.1:8765', 'X-Family-Request': '1'})
        self.client.post('/api/login', json={'user': 'britta'})

    def tearDown(self):
        self.client.close()
        self.tmp.cleanup()

    def send(self, body=None, kind='audio/mp4', client=None):
        return (client or self.client).post('/api/speech', content=mp4_audio() if body is None else body,
                                            headers={'Content-Type': kind})

    def files(self):
        return sorted(p.relative_to(self.dir) for p in self.dir.rglob('*') if p.is_file() and 'sqlite' not in p.name)

    def test_iphone_recording_becomes_german_text_without_leaving_traces(self):
        before = self.files()
        response = self.send()
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['text'], 'Lina braucht neue Gummistiefel in Größe 24.')
        self.assertAlmostEqual(self.model.seen[0], 2.0, delta=0.1)
        self.assertEqual(self.model.options['language'], 'de')
        self.assertTrue(self.model.options['vad_filter'])
        self.assertEqual(self.files(), before)  # nothing written to disk (A-02)
        with self.app.state.db() as conn:
            dump = '\n'.join(conn.iterdump())
        self.assertNotIn('Gummistiefel', dump)  # only measurements are stored
        last = self.client.get('/api/connections').json()['speech']['last']
        self.assertAlmostEqual(last['audio_seconds'], 2.0, delta=0.1)

    def test_login_is_checked_before_reading_audio(self):
        anonymous = TestClient(self.app, base_url='http://127.0.0.1:8765',
                               headers={'Origin': 'http://127.0.0.1:8765', 'X-Family-Request': '1'})
        self.assertEqual(self.send(client=anonymous).status_code, 401)
        self.assertEqual(self.model.seen, [])
        anonymous.close()

    def test_rejects_unknown_format_and_oversize(self):
        self.assertEqual(self.send(kind='application/pdf').status_code, 415)
        self.assertEqual(self.send(body=b'x' * (10 * 1024 * 1024 + 1)).status_code, 413)
        self.assertEqual(self.model.seen, [])

    def test_phantom_text_on_silence_is_not_offered(self):
        self.model.segments = [segment('Untertitel im Auftrag des ZDF, 2021'), segment('Musik', no_speech=0.9, logprob=-1.5)]
        response = self.send()
        self.assertEqual(response.status_code, 422)
        self.assertIn('keine Sprache erkannt', response.json()['detail'])

    def test_broken_audio_fails_clearly_and_next_request_works(self):
        response = self.send(body=b'not audio at all')
        self.assertEqual(response.status_code, 422)
        self.assertIn('nicht umgewandelt', response.json()['detail'])
        self.assertFalse(self.speech.lock.locked())
        self.assertEqual(self.send().status_code, 200)

    def test_not_ready_off_and_demo_are_explained(self):
        self.speech.state = 'loading'
        self.assertEqual(self.send().status_code, 503)
        self.speech.state, self.speech.message = 'error', 'Modell fehlt.'
        self.assertEqual(self.send().json()['detail'], 'Modell fehlt.')
        self.speech.enabled = False
        self.assertEqual(self.send().status_code, 409)
        self.speech.demo = True
        self.assertIn('Demo', self.send().json()['detail'])

    def test_prepare_reports_download_failure_and_success(self):
        speech = Speech(self.app.state.db, self.dir, demo=False)
        with patch.object(Speech, 'load_model', side_effect=OSError('network')):
            speech.prepare()
        self.assertEqual(speech.state, 'error')
        self.assertIn('huggingface.co', speech.message)
        with patch.object(Speech, 'load_model', return_value=self.model):
            speech.prepare()
        self.assertEqual((speech.state, speech.model), ('ready', self.model))

    def test_model_can_be_switched_off(self):
        with patch.dict('os.environ', {'FOS_SPEECH_MODEL': 'off'}):
            speech = Speech(self.app.state.db, self.dir, demo=False)
        self.assertEqual(speech.state, 'off')
        speech.start()  # no thread, no download
        self.assertIsNone(speech.model)


class CleanTests(unittest.TestCase):
    def test_keeps_confident_text_and_drops_phantoms(self):
        segments = [segment('Bitte Windeln kaufen.'), segment('Vielen Dank fürs Zuschauen!'),
                    segment('Untertitelung des ZDF für funk, 2017'), segment('unsicher', no_speech=0.8, logprob=-1.2),
                    segment('  und   Milch. ')]
        self.assertEqual(clean(segments), 'Bitte Windeln kaufen. und Milch.')

    def test_uncertain_only_when_both_signals_agree(self):
        self.assertEqual(clean([segment('leise gesprochen', no_speech=0.7, logprob=-0.5)]), 'leise gesprochen')


if __name__ == '__main__':
    unittest.main()
