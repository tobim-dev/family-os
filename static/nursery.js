'use strict';
// Nursery dates (B-19): special events and early closing, imported from the
// nursery's Word letters (or pasted text) and confirmed before saving.
// Closure days are handed to "Ohne Krippe" (the other parent confirms).

const nurseryKinds = {event: 'Veranstaltung', early_close: 'Früher Schluss', closed: 'Schließtag'};

function nurseryEventsOn(day) {
  return (state.nursery_events || []).filter(e => e.day === day);
}

function nurseryText(e) {
  if (e.kind === 'early_close') return `Krippe schließt ${e.end}`;
  return e.title + (e.start ? ` · ${e.start}` + (e.end ? `–${e.end}` : '') : '');
}

function nurseryBadge(day) {
  return nurseryEventsOn(day).map(e =>
    `<span class="nursery-badge ${e.kind}" title="${esc(e.title)}">${esc(nurseryText(e))}</span>`).join('');
}

function nurseryPanel() {
  const upcoming = (state.nursery_events || []).filter(e => e.day >= state.today);
  const rows = upcoming.map(e => `<div class="list-row"><div class="grow">
      <div class="row between"><b>${esc(e.title)}</b><span class="status ${e.kind === 'early_close' ? 'amber' : 'gray'}">${nurseryKinds[e.kind]}</span></div>
      <p>${fmt(e.day, {weekday: 'short', day: 'numeric', month: 'short'})}${e.kind === 'early_close' ? ` · schließt ${e.end} Uhr`
        : e.start ? ` · ${e.start}${e.end ? '–' + e.end : ''} Uhr` : ''}</p>
      ${e.note ? `<small>${esc(e.note)}</small>` : ''}
      <div class="actions"><button class="btn ghost danger" data-nursery-delete="${e.id}">Entfernen</button></div></div></div>`).join('');
  return `<section class="panel"><div class="panel-head"><h2>Termine der Krippe</h2></div>
    ${rows || '<div class="panel-body"><p class="small">Feste, Ausflüge, früher Schluss. Einfach den Elternbrief als Word-Datei hochladen.</p></div>'}
    <div class="panel-body"><div class="actions">
      <label class="btn primary file-btn">${icon('plus')}Word-Datei hochladen<input type="file" accept=".docx" data-nursery-file hidden></label>
      <button class="btn" data-nursery-paste>Text einfügen</button>
      <button class="btn ghost" data-nursery-new>Einzeln eintragen</button></div></div>
  </section>`;
}

function nurseryRow(item, index) {
  const kinds = Object.entries(nurseryKinds).map(([key, label]) =>
    `<option value="${key}" ${item.kind === key ? 'selected' : ''}>${label}</option>`).join('');
  return `<fieldset class="nursery-item" data-index="${index}">
    <label class="nursery-take"><input type="checkbox" name="take" ${item.existing ? '' : 'checked'}>
      <span>${item.existing ? 'Schon eingetragen' : 'Übernehmen'}</span></label>
    <div class="field-pair nursery-when">
      <div class="field"><label>Art</label><select name="kind">${kinds}</select></div>
      <div class="field"><label>Datum</label><input type="date" name="day" value="${esc(item.day || '')}" required></div>
    </div>
    <div class="field"><label>Titel</label><input name="title" maxlength="80" value="${esc(item.title || '')}" required></div>
    <div class="field-pair" data-for="event">
      <div class="field"><label>Beginn</label><input type="time" name="start" value="${esc(item.start || '')}"></div>
      <div class="field"><label>Ende</label><input type="time" name="end" value="${item.kind === 'event' ? esc(item.end || '') : ''}"></div>
    </div>
    <div class="field" data-for="early_close"><label>Krippe schließt um</label>
      <input type="time" name="close" value="${item.kind === 'early_close' ? esc(item.end || '') : ''}"></div>
    <div class="field" data-for="closed"><label>Bis einschließlich (optional)</label>
      <input type="date" name="until" value="${esc(item.until || '')}"></div>
    <div class="field" data-for="event early_close"><label>Hinweis (optional)</label>
      <input name="note" maxlength="200" value="${esc(item.note || '')}" placeholder="z. B. Tracht mitbringen"></div>
  </fieldset>`;
}

function nurseryToggle(fieldset) {
  const kind = fieldset.querySelector('[name=kind]').value;
  fieldset.querySelectorAll('[data-for]').forEach(el => { el.hidden = !el.dataset.for.split(' ').includes(kind); });
}

function nurseryCollect(form) {
  return [...form.querySelectorAll('.nursery-item')].filter(f => f.querySelector('[name=take]').checked).map(f => {
    const value = name => f.querySelector(`[name=${name}]`).value.trim();
    const kind = value('kind');
    return {
      day: value('day'), kind, title: value('title'), note: kind === 'closed' ? '' : value('note'),
      start: kind === 'event' ? value('start') || null : null,
      end: kind === 'event' ? value('end') || null : kind === 'early_close' ? value('close') || null : null,
      until: kind === 'closed' ? value('until') || null : null,
    };
  });
}

function nurseryReview(result, source) {
  const items = result.items.length ? result.items : [];
  const origin = result.source === 'claude'
    ? `Von Claude erkannt – bitte prüfen.`
    : 'Automatisch erkannt – bitte prüfen und ergänzen.';
  dialog('Krippen-Termine prüfen', source === 'manual' ? 'Termin eintragen' : `${items.length} gefunden · ${origin}`, `<form>
    ${result.notice ? `<p class="note">${esc(result.notice)}</p>` : ''}
    ${items.length || source === 'manual' ? '' : '<p class="note">Im Text wurde kein Datum gefunden. Du kannst einen Termin einzeln eintragen.</p>'}
    <div class="nursery-list">${(source === 'manual' ? [{kind: 'event', day: state.today}] : items).map(nurseryRow).join('')}</div>
    <p class="small">Schließtage landen unter „Ohne Krippe“ und gelten erst nach Bestätigung der anderen Person.
      Schließt die Krippe früher als eure geplante Abholung, bekommt die abholende Person eine Aufgabe.</p>
    ${result.sent ? `<details class="sent"><summary>Was an Claude ging</summary><pre>${esc(result.sent)}</pre></details>` : ''}
    <div class="dialog-footer"><button type="submit" class="btn primary">Übernehmen</button></div></form>`);
  const form = modal.querySelector('form');
  form.querySelectorAll('.nursery-item').forEach(fieldset => {
    nurseryToggle(fieldset);
    fieldset.querySelector('[name=kind]').addEventListener('change', () => nurseryToggle(fieldset));
  });
  form.onsubmit = async event => {
    event.preventDefault();
    const chosen = nurseryCollect(form);
    if (!chosen.length) return formError(form, 'Bitte mindestens einen Termin auswählen.');
    const button = form.querySelector('[type=submit]');
    button.disabled = true;
    try {
      const saved = await api('/nursery/events', {items: chosen, source: source === 'manual' ? 'manual' : 'import'});
      modal.close();
      await load();
      const parts = [];
      if (saved.saved) parts.push(`${saved.saved} ${saved.saved === 1 ? 'Termin' : 'Termine'} eingetragen`);
      if (saved.closed) parts.push(`${saved.closed} Schließzeit zur Bestätigung`);
      if (saved.tasks.length) parts.push('Aufgabe zur früheren Abholung für ' + saved.tasks.join(' und '));
      toast(parts.join(' · ') + '.');
    } catch (error) {
      formError(form, error.message);
      button.disabled = false;
    }
  };
}

async function nurseryUpload(file) {
  if (!file) return;
  if (!/\.docx$/i.test(file.name)) return toast('Bitte eine Word-Datei im Format .docx wählen. Ältere .doc-Dateien in Word als .docx speichern.');
  toast('Elternbrief wird gelesen …');
  try {
    const response = await fetch('/api/nursery/import/docx', {method: 'POST', body: file,
      headers: {'Content-Type': 'application/octet-stream', 'X-Family-Request': '1'}});
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || `Die Datei konnte nicht gelesen werden (HTTP ${response.status}).`);
    nurseryReview(data, 'import');
  } catch (error) {
    toast(error.message);
  }
}

function nurseryPasteDialog() {
  dialog('Text einfügen', 'Zum Beispiel aus einer E-Mail der Krippe', `<form>
    <div class="field"><label for="nursery-text">Text</label>
      <textarea id="nursery-text" name="text" rows="8" required minlength="10"></textarea></div>
    <div class="dialog-footer"><button type="submit" class="btn primary">Termine finden</button></div></form>`);
  const form = modal.querySelector('form');
  form.onsubmit = async event => {
    event.preventDefault();
    const button = form.querySelector('[type=submit]');
    button.disabled = true;
    try {
      const result = await api('/nursery/import/text', {text: form.text.value});
      modal.close();
      nurseryReview(result, 'import');
    } catch (error) {
      formError(form, error.message);
      button.disabled = false;
    }
  };
}

function bindNursery() {
  app.querySelector('[data-nursery-file]')?.addEventListener('change', event => {
    nurseryUpload(event.target.files[0]);
    event.target.value = '';
  });
  app.querySelector('[data-nursery-paste]')?.addEventListener('click', nurseryPasteDialog);
  app.querySelector('[data-nursery-new]')?.addEventListener('click', () => nurseryReview({items: []}, 'manual'));
  app.querySelectorAll('[data-nursery-delete]').forEach(button => button.addEventListener('click', async () => {
    if (!confirm('Diesen Krippen-Termin entfernen?')) return;
    try {
      await api(`/nursery/events/${button.dataset.nurseryDelete}/delete`, {});
      await load();
      toast('Termin entfernt.');
    } catch (error) {
      toast(error.message);
    }
  }));
}
