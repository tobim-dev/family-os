"""Local speech-to-text on the NAS (A-01, A-02, decision O-09 of 26.09.2026).

* Whisper (``faster-whisper``, default model ``large-v3-turbo``) runs on the
  CPU inside this container. No audio and no text leave the NAS.
* The model is downloaded once into ``models/`` in the data folder, in a
  background thread after start. Until it is ready the microphone buttons are
  hidden and requests are answered with a clear message.
* The recording only ever exists in memory for the duration of one request.
  It is never written to disk, logged or backed up, and it is discarded in
  every case, including failures (A-02).
* Whisper can invent text on silence or noise. Silence is filtered out (VAD),
  uncertain segments and known phantom phrases are dropped. The text is only
  ever put into the input field for review; saving stays a separate click.
* Only measurements (audio seconds, processing seconds) are stored for the
  status page, never the text.
"""
from datetime import datetime
import io
import json
import logging
import os
from pathlib import Path
import re
import threading
import time

from fastapi import HTTPException, Request
from starlette.concurrency import run_in_threadpool

from integrations import TZ

LOG = logging.getLogger('family-os')
MAX_BYTES = 10 * 1024 * 1024
MAX_SECONDS = 120
AUDIO_TYPES = ('audio/mp4', 'audio/aac', 'audio/x-m4a', 'audio/webm', 'audio/ogg', 'audio/wav', 'audio/x-wav', 'audio/mpeg')

# Typical Whisper hallucinations on silence (German subtitle credits etc.).
PHANTOMS = [re.compile(p, re.I) for p in (
    r'untertitel(ung)? (im auftrag )?(des|der|von) ',
    r'amara\.org',
    r'vielen dank f(ü|u)rs? (zu(hören|schauen)|zusehen)',
    r'danke f(ü|u)rs? (zu(hören|schauen)|zusehen)',
    r'copyright .*(wdr|zdf|ard|swr|ndr)',
    r'^(\W*(musik|applaus|stille)\W*)$',
    r'^\W*$',
)]


def clean(segments):
    """Keep only confident, non-phantom segments; return the joined text."""
    parts = []
    for segment in segments:
        text = segment.text.strip()
        if segment.no_speech_prob > 0.6 and segment.avg_logprob < -1.0:
            continue
        if any(p.search(text) for p in PHANTOMS):
            continue
        parts.append(text)
    return re.sub(r'\s+', ' ', ' '.join(parts)).strip()


class Speech:
    def __init__(self, db, directory, demo):
        self.db, self.demo = db, demo
        self.name = os.getenv('FOS_SPEECH_MODEL', 'large-v3-turbo').strip()
        self.enabled = not demo and self.name.lower() != 'off'
        self.models = Path(directory) / 'models'
        self.threads = int(os.getenv('FOS_SPEECH_THREADS', '0') or 0)
        self.model = None
        self.state = 'off' if not self.enabled else 'waiting'
        self.message = ''
        self.lock = threading.Lock()   # one transcription at a time
        self.loading = threading.Lock()

    # --- model -----------------------------------------------------------

    def load_model(self):
        # The container file system is read-only (only /data is writable) and
        # /tmp is small: keep every download and cache below the model folder.
        self.models.mkdir(mode=0o700, exist_ok=True)
        os.environ.setdefault('HF_HOME', str(self.models / 'hf-home'))
        os.environ.setdefault('HF_HUB_DISABLE_TELEMETRY', '1')
        os.environ.setdefault('HF_HUB_DISABLE_XET', '1')
        from faster_whisper import WhisperModel  # heavy import only when used
        return WhisperModel(self.name, device='cpu', compute_type='int8', cpu_threads=self.threads,
                            download_root=str(self.models))

    def prepare(self):
        """Download (first time) and load the model. Safe to call repeatedly."""
        if not self.enabled or self.model is not None:
            return
        if not self.loading.acquire(blocking=False):
            return
        try:
            self.state, self.message = 'loading', ''
            started = time.monotonic()
            self.model = self.load_model()
            self.state = 'ready'
            LOG.info('Spracherkennung bereit (%s, %.0f s)', self.name, time.monotonic() - started)
        except Exception as error:
            self.state = 'error'
            self.message = ('Das Sprachmodell konnte nicht geladen werden. Beim ersten Start muss der Container '
                            'huggingface.co erreichen; danach läuft alles lokal. Neuer Versuch beim nächsten Neustart.')
            LOG.error('Spracherkennung nicht verfügbar: %s', type(error).__name__)
        finally:
            self.loading.release()

    def start(self):
        if self.enabled:
            threading.Thread(target=self.prepare, name='family-speech', daemon=True).start()

    # --- work ------------------------------------------------------------

    def transcribe(self, audio):
        """Return (text, audio_seconds). ``audio`` is an in-memory file."""
        segments, info = self.model.transcribe(
            audio, language='de', beam_size=5, vad_filter=True, condition_on_previous_text=False,
            no_speech_threshold=0.6, log_prob_threshold=-1.0, compression_ratio_threshold=2.4)
        if info.duration > MAX_SECONDS + 1:
            raise HTTPException(413, f'Bitte höchstens {MAX_SECONDS // 60} Minuten am Stück sprechen.')
        return clean(list(segments)), info.duration

    def status(self, conn):
        row = conn.execute("SELECT value FROM metadata WHERE key='speech_last'").fetchone()
        return {'state': self.state, 'model': self.name if self.enabled else None, 'message': self.message,
                'last': json.loads(row[0]) if row else None, 'max_seconds': MAX_SECONDS}

    def remember(self, audio_seconds, seconds):
        value = {'audio_seconds': round(audio_seconds, 1), 'seconds': round(seconds, 1),
                 'time': datetime.now(TZ).isoformat(timespec='seconds')}
        with self.db() as conn:
            conn.execute("INSERT OR REPLACE INTO metadata VALUES('speech_last',?)", (json.dumps(value),))

    # --- routes ----------------------------------------------------------

    def routes(self, app, identity):
        db = self.db

        @app.post('/api/speech')
        async def speech(request: Request):
            with db() as conn:
                identity(request, conn)  # before reading any audio
            if self.demo:
                raise HTTPException(409, 'In der Demo gibt es keine Spracherkennung. Bitte tippen.')
            if not self.enabled:
                raise HTTPException(409, 'Die Spracherkennung ist auf dem NAS ausgeschaltet.')
            if self.state != 'ready':
                raise HTTPException(503, 'Die Spracherkennung wird noch vorbereitet. Bitte gleich noch einmal versuchen oder tippen.'
                                    if self.state in ('waiting', 'loading') else self.message)
            kind = (request.headers.get('content-type') or '').split(';')[0].strip().lower()
            if kind not in AUDIO_TYPES:
                raise HTTPException(415, 'Unbekanntes Tonformat.')
            if int(request.headers.get('content-length') or 0) > MAX_BYTES:
                raise HTTPException(413, 'Die Aufnahme ist zu lang.')
            body = bytearray()
            async for chunk in request.stream():
                body += chunk
                if len(body) > MAX_BYTES:
                    raise HTTPException(413, 'Die Aufnahme ist zu lang.')
            if not self.lock.acquire(timeout=30):
                raise HTTPException(503, 'Gerade läuft eine andere Umwandlung. Bitte gleich noch einmal versuchen.')
            audio = io.BytesIO(body)
            started = time.monotonic()
            try:
                text, duration = await run_in_threadpool(self.transcribe, audio)
            except HTTPException:
                raise
            except Exception as error:
                LOG.error('Umwandlung fehlgeschlagen: %s', type(error).__name__)
                raise HTTPException(422, 'Die Aufnahme konnte nicht umgewandelt werden. Bitte noch einmal sprechen oder tippen.')
            finally:
                # A-02: the recording only existed in memory and is dropped now, success or not.
                audio.close()
                body.clear()
                self.lock.release()
            self.remember(duration, time.monotonic() - started)
            if not text:
                raise HTTPException(422, 'Es wurde keine Sprache erkannt. Bitte noch einmal sprechen oder tippen.')
            return {'text': text}
