'use strict';
// Nanny planning, hours and monthly statement. Uses helpers from app.js
// (api, dialog, submitForm, esc, fmt, icon, names, toast, load, state, month).

let nannyState = null;
let nannyLoading = false;

const nannyStates = {
  wish: ['Wunsch', 'gray'],
  requested: ['Angefragt', 'amber'],
  confirmed: ['Bestätigt', 'green'],
  declined: ['Nanny kann nicht', 'red'],
  cancelled: ['Abgesagt', 'red'],
};

const euro = cents => (cents / 100).toLocaleString('de-DE', {style: 'currency', currency: 'EUR'});
const hoursText = minutes => (minutes / 60).toLocaleString('de-DE', {maximumFractionDigits: 2}) + ' Std.';
const nannyDay = day => fmt(day, {weekday: 'short', day: 'numeric', month: 'short'});

async function loadNanny() {
  if (nannyLoading) return;
  nannyLoading = true;
  try {
    nannyState = await api('/nanny?month=' + month);
    if (view === 'nanny' && state) render();
  } catch (error) {
    toast(error.message);
  } finally {
    nannyLoading = false;
  }
}

function nannyForDay(day) {
  return (state?.nanny || []).filter(shift => shift.day === day);
}

// Hint on the pickup slot: on nanny days the parent picks up earlier (decision O-04).
function nannyPickupHint(day) {
  const shifts = nannyForDay(day).filter(shift => shift.state !== 'wish');
  if (!shifts.length) return '';
  return `<span class="nanny-hint">Nanny ab ${esc(shifts[0].start)} · früher abholen</span>`;
}

function whatsappLink(text) {
  const phone = (nannyState?.settings.phone || '').replace(/[^0-9]/g, '');
  return 'https://wa.me/' + phone + '?text=' + encodeURIComponent(text);
}

function shiftLine(shift) {
  return `${fmt(shift.day, {weekday: 'long', day: 'numeric', month: 'long'})}, ${shift.start}–${shift.end} Uhr`;
}

function requestText(shifts) {
  const greeting = `Hallo ${nannyState.settings.name},`;
  if (shifts.length === 1) {
    return `${greeting}\nhättest du am ${shiftLine(shifts[0])} Zeit für Lina?\nViele Grüße\n${names[state.user]}`;
  }
  return `${greeting}\nhättest du an diesen Terminen Zeit für Lina?\n${shifts.map(s => '– ' + shiftLine(s)).join('\n')}\nViele Grüße\n${names[state.user]}`;
}

function cancelText(shift) {
  return `Hallo ${nannyState.settings.name},\nleider müssen wir den Termin am ${shiftLine(shift)} absagen.\nViele Grüße\n${names[state.user]}`;
}

function pickupOwner(day) {
  const slot = state.appointments.find(a => a.day === day && a.kind === 'pickup');
  return slot?.owner ? names[slot.owner] : null;
}

function shiftActions(shift, locked) {
  if (locked) return '';
  const id = shift.id;
  const past = shift.day <= nannyState.today;
  const buttons = {
    wish: [
      `<button class="btn primary" data-nanny-request="${id}">WhatsApp-Anfrage</button>`,
      `<button class="btn" data-nanny-confirm="${id}">Schon zugesagt</button>`,
      `<button class="btn ghost" data-nanny-edit="${id}">Ändern</button>`,
      `<button class="btn ghost danger" data-nanny-cancel="${id}">Streichen</button>`,
    ],
    requested: [
      `<button class="btn green" data-nanny-confirm="${id}">Zusage eintragen</button>`,
      `<button class="btn" data-nanny-decline="${id}">Nanny kann nicht</button>`,
      `<button class="btn ghost" data-nanny-request="${id}">Erneut schreiben</button>`,
      `<button class="btn ghost danger" data-nanny-cancel="${id}">Absagen</button>`,
    ],
    confirmed: [
      past ? `<button class="btn" data-nanny-correct="${id}">Tatsächliche Zeit</button>` : '',
      `<button class="btn ghost danger" data-nanny-cancel="${id}">Absagen</button>`,
    ],
  }[shift.state] || [];
  return buttons.length ? `<div class="actions">${buttons.join('')}</div>` : '';
}

function shiftRow(shift, locked) {
  const [label, color] = nannyStates[shift.state];
  const pickup = pickupOwner(shift.day);
  const details = [];
  if (['wish', 'requested', 'confirmed'].includes(shift.state) && pickup) {
    details.push(`Abholung: ${esc(pickup)} · bitte früher abholen`);
  }
  if (shift.actual_start) {
    details.push(`Tatsächlich ${esc(shift.actual_start)}–${esc(shift.actual_end)} · ${esc(shift.correction_note)}`);
  }
  if (shift.state === 'cancelled' && shift.paid_cancel !== null) {
    details.push(shift.paid_cancel ? 'Wird trotz Absage bezahlt' : 'Wird nicht bezahlt');
  }
  if (shift.note) details.push(esc(shift.note));
  return `<div class="list-row nanny-row">
    <div class="nanny-date"><strong>${fmt(shift.day, {day: 'numeric'})}</strong><small>${fmt(shift.day, {weekday: 'short'})}</small></div>
    <div class="grow">
      <div class="row between"><h3>${esc(shift.start)}–${esc(shift.end)} Uhr</h3><span class="status ${color}">${label}</span></div>
      ${details.map(d => `<small class="nanny-detail">${d}</small>`).join('')}
      ${shiftActions(shift, locked)}
    </div>
  </div>`;
}

function statementHTML(statement) {
  const lines = statement.lines.map(line => `<div class="row between nanny-line">
      <span>${nannyDay(line.day)}${line.cancelled_paid ? ' · Ausfall bezahlt' : line.corrected ? ' · korrigiert' : ''}</span>
      <span>${hoursText(line.minutes)}</span>
    </div>`).join('');
  let footer = '';
  if (statement.state === 'open') {
    if (statement.unresolved) {
      footer = `<div class="note">${statement.unresolved === 1 ? 'Ein Termin ist' : statement.unresolved + ' Termine sind'} noch nicht bestätigt oder abgesagt.</div>`;
    } else if (statement.month_over) {
      footer = '<button class="btn primary full" data-nanny-statement="close">Monat abschließen</button>';
    } else {
      footer = '<p class="small">Abschluss ist nach Monatsende möglich.</p>';
    }
  } else if (statement.state === 'closed') {
    footer = `<p class="small">Abgeschlossen ${deadlineText(statement.closed)}</p>
      <div class="actions"><button class="btn green" data-nanny-statement="paid">Als überwiesen markieren</button>
      <button class="btn ghost" data-nanny-statement="reopen">Wieder öffnen</button></div>`;
  } else {
    footer = `<span class="status green">Überwiesen ${deadlineText(statement.paid)}</span>`;
  }
  return `<section class="panel">
    <div class="panel-head"><div><h2>Abrechnung</h2><p>${monthName(month)}</p></div>
      <span class="status ${statement.state === 'open' ? 'gray' : 'green'}">${{open: 'Offen', closed: 'Abgeschlossen', paid: 'Überwiesen'}[statement.state]}</span></div>
    <div class="panel-body">
      <div class="nanny-total"><strong>${euro(statement.amount_cents)}</strong><small>${hoursText(statement.minutes)} × ${euro(statement.rate_cents)}</small></div>
      ${lines || '<p class="small">Noch keine abrechenbaren Termine.</p>'}
      <p class="note">Geplante Zeiten zählen, sofern keine Abweichung eingetragen ist. Nur Lohn, keine Minijob-Abgaben oder Meldungen.</p>
      ${footer}
    </div>
  </section>`;
}

function nannyHTML() {
  if (!nannyState || nannyState.month !== month) {
    return '<section class="panel"><div class="empty-state">Nanny-Planung wird geladen …</div></section>';
  }
  const {shifts, statement, settings} = nannyState;
  const locked = statement.state !== 'open';
  const wishes = shifts.filter(s => s.state === 'wish');
  const active = shifts.filter(s => ['wish', 'requested', 'confirmed'].includes(s.state));
  const closedShifts = shifts.filter(s => !['wish', 'requested', 'confirmed'].includes(s.state));
  const phoneNote = settings.phone ? '' : ' Ohne hinterlegte Nummer wählst du den Chat in WhatsApp selbst.';
  return `<div class="meal-toolbar nanny-toolbar">
      <div><b>${esc(settings.name)}</b><p>Gewöhnlich 16:00–18:00 Uhr · ${euro(settings.rate_cents)} pro Stunde</p></div>
      <div class="actions">
        <button class="btn" data-month="-1" aria-label="Vorheriger Monat">${icon('left')}</button>
        <span class="month-title">${monthName(month)}</span>
        <button class="btn" data-month="1" aria-label="Nächster Monat">${icon('arrow')}</button>
        <button class="btn" data-nanny-settings>Einstellungen</button>
        ${locked ? '' : `<button class="btn primary" data-nanny-new>${icon('plus')}Nanny-Wunsch</button>`}
      </div>
    </div>
    ${locked ? '<div class="note nanny-locked">Dieser Monat ist abgerechnet. Zum Ändern die Abrechnung wieder öffnen.</div>' : ''}
    <div class="content-grid"><div class="stack">
      ${wishes.length > 1 && !locked ? `<div class="planning-banner"><div><b>${wishes.length} Wünsche offen</b><p>Gemeinsam in einer WhatsApp-Nachricht anfragen.${phoneNote}</p></div><button class="btn" data-nanny-request="${wishes.map(s => s.id).join(',')}">Alle anfragen</button></div>` : ''}
      <section class="panel"><div class="panel-head"><div><h2>Nanny-Termine</h2><p>An Nanny-Tagen holt ihr Lina früher ab und übergebt zuhause.</p></div><span class="status gray">${active.length}</span></div>
        ${active.length ? active.map(s => shiftRow(s, locked)).join('') : `<div class="empty-state">${icon('users')}<b>Keine Nanny-Termine geplant.</b><p>Wünsche könnt ihr bei der Monatsplanung gleich mit anlegen.</p></div>`}
      </section>
      ${closedShifts.length ? `<details class="panel meal-done"><summary>Abgesagt (${closedShifts.length})</summary>${closedShifts.map(s => shiftRow(s, true)).join('')}</details>` : ''}
    </div>
    <aside class="rail">${statementHTML(statement)}</aside></div>`;
}

function nannyShift(id) {
  return nannyState.shifts.find(s => s.id === Number(id));
}

function nannyTransition(shifts, action, extra = {}) {
  return api('/nanny/transition', {ids: shifts.map(s => s.id), versions: shifts.map(s => s.version), action, ...extra});
}

async function nannyAfterChange(message) {
  modal.close();
  await load();
  toast(message);
}

function nannyShiftForm(shift) {
  const day = shift?.day || nannyState.today;
  dialog(shift ? 'Nanny-Wunsch ändern' : 'Nanny-Wunsch anlegen', 'Die Nanny wird erst mit der WhatsApp-Anfrage kontaktiert.', `<form>
    <div class="field"><label for="nanny-day">Tag</label><input id="nanny-day" name="day" type="date" required value="${esc(day)}" min="${esc(nannyState.today)}"></div>
    <div class="field-pair">
      <div class="field"><label for="nanny-start">Von</label><input id="nanny-start" name="start" type="time" required value="${esc(shift?.start || '16:00')}"></div>
      <div class="field"><label for="nanny-end">Bis</label><input id="nanny-end" name="end" type="time" required value="${esc(shift?.end || '18:00')}"></div>
    </div>
    <div class="field"><label for="nanny-note">Notiz (optional)</label><input id="nanny-note" name="note" maxlength="300" value="${esc(shift?.note || '')}"></div>
    <p class="note">An diesem Tag holt ihr Lina früher ab, damit die Übergabe zuhause zum Beginn klappt. Tobi erhält die Aufgabe, die Nanny anzufragen.</p>
    <div class="dialog-footer"><button class="btn primary" type="submit">Speichern</button></div>
  </form>`);
  submitForm(modal.querySelector('form'), data => shift
    ? api('/nanny/shifts/' + shift.id, {...data, version: shift.version})
    : api('/nanny/shifts', data));
}

function nannyRequestDialog(ids) {
  const shifts = ids.split(',').map(nannyShift).filter(Boolean);
  const text = requestText(shifts);
  const pending = shifts.filter(s => s.state === 'wish');
  dialog('Nanny per WhatsApp anfragen', `${shifts.length === 1 ? nannyDay(shifts[0].day) : shifts.length + ' Termine'}`, `
    <div class="field"><label for="nanny-text">Nachricht</label><textarea id="nanny-text" readonly rows="6">${esc(text)}</textarea></div>
    <div class="actions"><a class="btn primary" href="${esc(whatsappLink(text))}" target="_blank" rel="noopener noreferrer">In WhatsApp öffnen</a></div>
    <p class="note">Das Öffnen ändert nichts. Nach dem Senden hier als angefragt markieren. Die Zusage trägst du ein, sobald sie antwortet.</p>
    ${pending.length ? '<div class="dialog-footer"><button class="btn green" data-nanny-mark-requested>Nachricht gesendet · als angefragt markieren</button></div>' : ''}
    <div id="nanny-error"></div>`);
  modal.querySelector('[data-nanny-mark-requested]')?.addEventListener('click', async event => {
    event.currentTarget.disabled = true;
    try {
      await nannyTransition(pending, 'request');
      await nannyAfterChange('Als angefragt markiert.');
    } catch (error) {
      const el = modal.querySelector('#nanny-error');
      el.className = 'form-error';
      el.textContent = error.message;
      event.currentTarget.disabled = false;
    }
  });
}

function nannySimpleDialog(shift, action) {
  const texts = {
    confirm: ['Zusage eintragen', 'Die Nanny hat zugesagt. Der Termin wird verbindlich und zählt für die Abrechnung.', 'Zusage speichern', 'green'],
    decline: ['Nanny kann nicht', 'Der Termin entfällt. Für einen anderen Tag bitte einen neuen Wunsch anlegen.', 'Absage speichern', 'primary'],
  }[action];
  dialog(texts[0], shiftLine(shift), `<form><p>${texts[1]}</p><div class="dialog-footer"><button type="submit" class="btn ${texts[3]}">${texts[2]}</button></div></form>`);
  submitForm(modal.querySelector('form'), () => nannyTransition([shift], action));
}

function nannyCancelDialog(shift) {
  const confirmed = shift.state === 'confirmed';
  const informed = shift.state !== 'wish';
  dialog(shift.state === 'wish' ? 'Wunsch streichen' : 'Termin absagen', shiftLine(shift), `<form>
    ${confirmed ? `<fieldset class="field"><legend>Wird der Termin trotzdem bezahlt?</legend>
      <label class="choice"><input type="radio" name="paid" value="1" required> Ja, bezahlen</label>
      <label class="choice"><input type="radio" name="paid" value="0" required> Nein, nicht bezahlen</label></fieldset>` : ''}
    ${informed ? `<p class="note">Bitte die Nanny informieren: <a href="${esc(whatsappLink(cancelText(shift)))}" target="_blank" rel="noopener noreferrer">Absage in WhatsApp öffnen</a></p>` : ''}
    <div class="dialog-footer"><button type="submit" class="btn primary">${shift.state === 'wish' ? 'Streichen' : 'Absage speichern'}</button></div>
  </form>`);
  submitForm(modal.querySelector('form'), data => nannyTransition([shift], 'cancel', confirmed ? {paid: data.paid === '1'} : {}));
}

function nannyCorrectDialog(shift) {
  dialog('Tatsächliche Zeit', shiftLine(shift), `<form>
    <p>Nur eintragen, wenn die Nanny kürzer oder länger da war. Sonst zählt die geplante Zeit.</p>
    <div class="field-pair">
      <div class="field"><label for="actual-start">Von</label><input id="actual-start" name="actual_start" type="time" required value="${esc(shift.actual_start || shift.start)}"></div>
      <div class="field"><label for="actual-end">Bis</label><input id="actual-end" name="actual_end" type="time" required value="${esc(shift.actual_end || shift.end)}"></div>
    </div>
    <div class="field"><label for="correction-note">Grund</label><input id="correction-note" name="note" required maxlength="300" value="${esc(shift.correction_note || '')}" placeholder="Zum Beispiel: Später nach Hause gekommen"></div>
    <div class="dialog-footer">
      ${shift.actual_start ? '<button type="button" class="btn ghost" data-nanny-reset>Wie geplant</button>' : ''}
      <button type="submit" class="btn primary">Speichern</button>
    </div>
  </form>`);
  const form = modal.querySelector('form');
  submitForm(form, data => api(`/nanny/shifts/${shift.id}/correct`, {...data, version: shift.version}));
  modal.querySelector('[data-nanny-reset]')?.addEventListener('click', async () => {
    try {
      await api(`/nanny/shifts/${shift.id}/correct`, {version: shift.version, actual_start: null, actual_end: null, note: ''});
      await nannyAfterChange('Es zählt wieder die geplante Zeit.');
    } catch (error) {
      formError(form, error.message);
    }
  });
}

function nannySettingsDialog() {
  const s = nannyState.settings;
  dialog('Nanny-Einstellungen', 'Gilt für neue Anfragen und offene Abrechnungen.', `<form>
    <div class="field"><label for="nanny-name">Name</label><input id="nanny-name" name="name" required maxlength="60" value="${esc(s.name)}"></div>
    <div class="field"><label for="nanny-phone">WhatsApp-Nummer (optional)</label><input id="nanny-phone" name="phone" inputmode="tel" maxlength="20" pattern="\\+?[0-9 ]{8,19}" value="${esc(s.phone)}" placeholder="+49 …"><small>Ohne Nummer wählst du den Chat in WhatsApp selbst.</small></div>
    <div class="field"><label for="nanny-rate">Stundenlohn in Euro</label><input id="nanny-rate" name="rate" type="number" min="1" max="100" step="0.01" required value="${(s.rate_cents / 100).toFixed(2)}"></div>
    <p class="note">Bereits abgeschlossene Monate behalten ihren damaligen Stundenlohn.</p>
    <div class="dialog-footer"><button class="btn primary" type="submit">Speichern</button></div>
  </form>`);
  submitForm(modal.querySelector('form'), data => api('/nanny/settings', {
    name: data.name.trim(), phone: data.phone.trim(), rate_cents: Math.round(Number(data.rate) * 100),
  }));
}

function nannyStatementDialog(action) {
  const statement = nannyState.statement;
  const texts = {
    close: ['Monat abschließen', `${hoursText(statement.minutes)} · ${euro(statement.amount_cents)}. Danach sind die Termine dieses Monats gesperrt. Tobi erhält die Aufgabe zur Überweisung.`, 'Abschließen'],
    paid: ['Überweisung bestätigen', `${euro(statement.amount_cents)} für ${monthName(month)} überwiesen? Danach ist der Monat endgültig.`, 'Ja, ist überwiesen'],
    reopen: ['Abrechnung wieder öffnen', 'Die Termine lassen sich dann wieder bearbeiten. Beim erneuten Abschluss gilt der aktuelle Stundenlohn.', 'Wieder öffnen'],
  }[action];
  dialog(texts[0], monthName(month), `<form><p>${texts[1]}</p><div class="dialog-footer"><button type="submit" class="btn ${action === 'reopen' ? '' : 'primary'}">${texts[2]}</button></div></form>`);
  submitForm(modal.querySelector('form'), () => api(`/nanny/statement/${month}`, {action}));
}

function bindNanny() {
  if (view !== 'nanny' || !nannyState) return;
  const on = (selector, handler) => app.querySelectorAll(selector).forEach(button => {
    button.onclick = () => handler(button);
  });
  app.querySelector('[data-nanny-new]')?.addEventListener('click', () => nannyShiftForm(null));
  app.querySelector('[data-nanny-settings]')?.addEventListener('click', nannySettingsDialog);
  on('[data-nanny-edit]', b => nannyShiftForm(nannyShift(b.dataset.nannyEdit)));
  on('[data-nanny-request]', b => nannyRequestDialog(b.dataset.nannyRequest));
  on('[data-nanny-confirm]', b => nannySimpleDialog(nannyShift(b.dataset.nannyConfirm), 'confirm'));
  on('[data-nanny-decline]', b => nannySimpleDialog(nannyShift(b.dataset.nannyDecline), 'decline'));
  on('[data-nanny-cancel]', b => nannyCancelDialog(nannyShift(b.dataset.nannyCancel)));
  on('[data-nanny-correct]', b => nannyCorrectDialog(nannyShift(b.dataset.nannyCorrect)));
  on('[data-nanny-statement]', b => nannyStatementDialog(b.dataset.nannyStatement));
}
