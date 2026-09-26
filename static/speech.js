'use strict';
// Speech input (speech.py): record in the browser, convert on the NAS, put the
// text into the field for review. Nothing is saved until the form is sent.
// The recording is only held in memory and sent once.

let speechRecording = null;

function speechReady() {
  return connections?.speech?.state === 'ready';
}

function speechFields(root) {
  return [...root.querySelectorAll('textarea:not([readonly]), input[data-speech]')];
}

// Adds a microphone button below every suitable field of a dialog.
function addMics(root) {
  if (!speechReady() || !navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') return;
  for (const field of speechFields(root)) {
    if (field.nextElementSibling?.matches?.('[data-mic]')) continue;
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'btn ghost mic';
    button.dataset.mic = '';
    button.innerHTML = icon('mic') + 'Sprechen';
    button.onclick = () => toggleRecording(button, field);
    field.after(button);
  }
}

function speechType() {
  for (const type of ['audio/mp4', 'audio/webm;codecs=opus', 'audio/webm', 'audio/ogg']) {
    if (MediaRecorder.isTypeSupported?.(type)) return type;
  }
  return '';
}

function speechError(field, message) {
  const form = field.closest('form');
  if (form) formError(form, message); else toast(message);
}

async function toggleRecording(button, field) {
  if (speechRecording) {
    if (speechRecording.button === button) speechRecording.recorder.stop();
    return;
  }
  let stream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({audio: true});
  } catch (error) {
    speechError(field, 'Kein Zugriff auf das Mikrofon. Bitte in den Einstellungen erlauben oder tippen.');
    return;
  }
  const type = speechType();
  const recorder = new MediaRecorder(stream, type ? {mimeType: type} : undefined);
  const chunks = [];
  const started = Date.now();
  const limit = (connections.speech.max_seconds || 120) * 1000;
  const tick = setInterval(() => {
    const seconds = Math.floor((Date.now() - started) / 1000);
    button.innerHTML = `${icon('mic')}Stopp · ${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`;
    if (Date.now() - started >= limit) recorder.stop();
  }, 250);
  speechRecording = {recorder, button};
  button.classList.add('recording');
  recorder.ondataavailable = event => { if (event.data.size) chunks.push(event.data); };
  recorder.onstop = async () => {
    clearInterval(tick);
    stream.getTracks().forEach(track => track.stop());
    button.classList.remove('recording');
    button.disabled = true;
    button.innerHTML = `${icon('mic')}Wird umgewandelt …`;
    try {
      const blob = new Blob(chunks, {type: (recorder.mimeType || type || 'audio/mp4').split(';')[0]});
      chunks.length = 0;
      const text = await sendSpeech(blob);
      field.value = field.value.trim() ? field.value.trim() + ' ' + text : text;
      field.dispatchEvent(new Event('input', {bubbles: true}));
      field.focus();
    } catch (error) {
      speechError(field, error.message);
    } finally {
      speechRecording = null;
      button.disabled = false;
      button.innerHTML = icon('mic') + 'Sprechen';
    }
  };
  recorder.start();
  button.innerHTML = `${icon('mic')}Stopp · 0:00`;
}

async function sendSpeech(blob) {
  const response = await fetch('/api/speech', {method: 'POST', body: blob,
    headers: {'Content-Type': blob.type, 'X-Family-Request': '1'}});
  let data = {};
  try { data = await response.json(); } catch (_) {}
  if (!response.ok) throw new Error(data.detail || `Umwandlung fehlgeschlagen (HTTP ${response.status}).`);
  return data.text;
}

function speechStatusHTML(s) {
  if (!s) return '';
  const labels = {off: 'Ausgeschaltet', waiting: 'Startet', loading: 'Wird vorbereitet', ready: 'Bereit', error: 'Nicht verfügbar'};
  const colors = {ready: 'green', error: 'red', off: 'gray'};
  const last = s.last
    ? `Zuletzt: ${String(s.last.audio_seconds).replace('.', ',')} s Sprache in ${String(s.last.seconds).replace('.', ',')} s umgewandelt.`
    : 'Noch keine Umwandlung.';
  const body = s.state === 'off'
    ? (state.demo ? 'In der Demo gibt es keine Spracherkennung.' : 'Auf dem NAS ausgeschaltet (FOS_SPEECH_MODEL=off).')
    : s.state === 'error' ? `<span class="error-text">${esc(s.message)}</span>`
      : s.state === 'ready' ? `„Sprechen“ erscheint in den Eingabefeldern. ${last}`
        : 'Beim ersten Start wird das Sprachmodell (etwa 1,6 GB) einmalig geladen.';
  return `<section class="panel"><div class="panel-head"><h2>Spracheingabe</h2><span class="status ${colors[s.state] || 'amber'}">${labels[s.state]}</span></div>
    <div class="panel-body"><p class="small">${body}</p>
    <small>Läuft lokal auf dem NAS${s.model ? ' (' + esc(s.model) + ')' : ''}. Aufnahmen werden nur im Arbeitsspeicher umgewandelt und nie gespeichert.</small></div></section>`;
}
