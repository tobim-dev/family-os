'use strict';
// Days without nursery care (closures.py): closure days, holidays, vacation,
// illness. Entries need the other person's confirmation (or joint planning).
// Confirmed days suspend their assignments; lifting restores them.

const closureKinds = {closed: 'Krippe geschlossen', holiday: 'Feiertag', vacation: 'Urlaub', sick: 'Lina krank'};

function closureFor(day) {
  return (state.closures || []).find(c => c.day === day);
}

function confirmedClosure(day) {
  const c = closureFor(day);
  return c && c.state === 'confirmed' ? c : null;
}

function closureBadge(day) {
  const c = closureFor(day);
  if (!c) return '';
  const label = closureKinds[c.kind] + (c.state === 'pending' ? ' · offen' : '');
  return `<span class="closure-badge ${c.state}">${esc(label)}</span>`;
}

function closureBatches() {
  const batches = new Map();
  for (const c of state.closures || []) {
    if (!batches.has(c.batch)) batches.set(c.batch, {...c, days: []});
    batches.get(c.batch).days.push(c.day);
  }
  return [...batches.values()];
}

function closureSpan(days) {
  const first = fmt(days[0], {weekday: 'short', day: 'numeric', month: 'short'});
  return days.length === 1 ? first : `${first} – ${fmt(days[days.length - 1], {weekday: 'short', day: 'numeric', month: 'short'})}`;
}

function closureActions(b) {
  if (b.state === 'confirmed') return `<button class="btn ghost" data-closure="${b.batch}" data-closure-action="lift">Aufheben</button>`;
  if (b.creator === state.user && !jointMode()) {
    return `<button class="btn ghost" data-closure="${b.batch}" data-closure-action="withdraw">Zurückziehen</button>`;
  }
  return `<button class="btn primary" data-closure="${b.batch}" data-closure-action="confirm">Bestätigen</button>`
    + (b.creator !== state.user ? `<button class="btn ghost" data-closure="${b.batch}" data-closure-action="reject">Ablehnen</button>` : '');
}

function closuresPanel() {
  const batches = closureBatches();
  const rows = batches.map(b => `<div class="list-row"><div class="grow">
      <div class="row between"><b>${esc(closureKinds[b.kind])}</b>
        <span class="status ${b.state === 'confirmed' ? 'gray' : 'amber'}">${b.state === 'confirmed' ? 'Bestätigt' : 'Wartet auf ' + (b.creator === state.user ? names[b.creator === 'tobi' ? 'britta' : 'tobi'] : 'dich')}</span></div>
      <p>${closureSpan(b.days)} · ${b.days.length} ${b.days.length === 1 ? 'Werktag' : 'Werktage'}</p>
      ${b.note ? `<small>${esc(b.note)}</small>` : ''}
      <div class="actions">${closureActions(b)}</div></div></div>`).join('');
  return `<section class="panel"><div class="panel-head"><h2>Ohne Krippe</h2>
      <button class="btn" data-closure-new>${icon('plus')}Eintragen</button></div>
    ${rows || '<div class="panel-body"><p class="small">Schließtage, Feiertage, Urlaub oder Krankheit. Bestätigte Tage zählen nicht zur Verteilung und entfallen im Kalender.</p></div>'}
  </section>`;
}

function closureDialog() {
  const today = state.today;
  dialog('Tage ohne Krippe eintragen', 'Die andere Person bestätigt die Eintragung.', `<form>
    <div class="field"><label for="cl-kind">Grund</label><select id="cl-kind" name="kind">
      ${Object.entries(closureKinds).map(([k, v]) => `<option value="${k}">${v}</option>`).join('')}</select></div>
    <div class="field-pair">
      <div class="field"><label for="cl-start">Von</label><input id="cl-start" name="start" type="date" required value="${today}"></div>
      <div class="field"><label for="cl-end">Bis</label><input id="cl-end" name="end" type="date" required value="${today}"></div>
    </div>
    <div class="field"><label for="cl-note">Notiz (optional)</label><input id="cl-note" data-speech name="note" maxlength="200" placeholder="z. B. Teamtag der Krippe"></div>
    <p class="note">Nur Montag bis Freitag. ${jointMode() ? 'Gemeinsame Planung: gilt sofort.' : 'Bis zur Bestätigung gilt die bisherige Planung.'}
      Danach entfallen Bringen und Abholen dieser Tage; ihr erhaltet Aufgaben zum Arbeitskalender.</p>
    <div class="dialog-footer"><button class="btn primary" type="submit">Eintragen</button></div></form>`);
  submitForm(modal.querySelector('form'), data => api('/closures', {...data, ...planningFields()}));
}

const closureToasts = {confirm: 'Bestätigt. Aufgaben zum Arbeitskalender wurden angelegt.', reject: 'Abgelehnt. Die Planung bleibt.',
  withdraw: 'Zurückgezogen.', lift: 'Aufgehoben. Die frühere Planung gilt wieder.'};

function closureDecision(batch, action) {
  return api(`/closures/${batch}/decision`, {action, ...planningFields()});
}

function liftDialog(batch) {
  dialog('Wieder normale Betreuungstage?', 'Die zuvor bestätigte Planung gilt dann wieder.', `<form>
    <p>Bringen und Abholen dieser Tage werden wieder aktiv und erscheinen wieder im Kalender.
      Ihr erhaltet Aufgaben, die Blöcke im Arbeitskalender wieder einzutragen.</p>
    <div class="dialog-footer"><button class="btn primary" type="submit">Aufheben</button></div></form>`);
  submitForm(modal.querySelector('form'), () => closureDecision(batch, 'lift'));
}

function bindClosures() {
  app.querySelector('[data-closure-new]')?.addEventListener('click', closureDialog);
  app.querySelectorAll('[data-closure]').forEach(button => {
    button.onclick = async () => {
      const action = button.dataset.closureAction;
      if (action === 'lift') return liftDialog(button.dataset.closure);
      button.disabled = true;
      try {
        await closureDecision(button.dataset.closure, action);
        await load();
        toast(closureToasts[action]);
      } catch (error) {
        toast(error.message);
        button.disabled = false;
      }
    };
  });
}
