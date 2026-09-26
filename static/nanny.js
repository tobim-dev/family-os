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

function nannyMonthName(value) {
  return new Date(value.slice(0, 7) + '-01T12:00:00').toLocaleDateString('de-DE', {month: 'long'});
}

function requestText(shifts) {
  const greeting = `Hallo ${nannyState.settings.name},`;
  const signature = `Viele Grüße\n${names[state.user]}`;
  if (shifts.length === 1) {
    return `${greeting}\nhättest du am ${shiftLine(shifts[0])} Zeit für Lina?\n${signature}`;
  }
  const sorted = [...shifts].sort((a, b) => (a.day + a.start).localeCompare(b.day + b.start));
  const months = [...new Set(sorted.map(s => nannyMonthName(s.day)))];
  return `${greeting}\nfür ${months.join(' und ')} hätten wir gern diese Termine für Lina:\n`
    + sorted.map(s => '– ' + shiftLine(s)).join('\n')
    + `\nPasst dir das? Sag gern Bescheid, falls einzelne Tage nicht gehen.\n${signature}`;
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
      `<button class="btn" data-nanny-request="${id}">Einzeln anfragen</button>`,
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

// Minijob im Privathaushalt (minijob.py, N-12): transfer to the nanny and the
// levies the Minijob-Zentrale collects twice a year.
function percentText(rate) {
  return (rate / 100).toLocaleString('de-DE', {maximumFractionDigits: 2}) + ' %';
}

function minijobHTML(statement) {
  const m = statement.minijob;
  if (!m) return '';
  const total = m.levies.reduce((sum, l) => sum + l.rate, 0);
  const rows = m.levies.map(l => `<div class="row between nanny-line"><span>${esc(l.label)} · ${percentText(l.rate)}</span><span>${euro(l.cents)}</span></div>`).join('');
  const deductions = m.deductions.map(d => `<div class="row between nanny-line"><span>− ${esc(d.label)}</span><span>${euro(d.cents)}</span></div>`).join('');
  const half = statement.half_year;
  const status = m.rv_exempt ? 'Von der Rentenversicherung befreit' : 'Rentenversicherungspflichtig';
  return `<div class="minijob">
      <div class="row between minijob-payout"><span>Überweisen an ${esc(nannyState.settings.name)}</span><strong>${euro(m.payout)}</strong></div>
      ${deductions}
      <div class="row between minijob-levy"><span>Abgaben an die Minijob-Zentrale</span><strong>${euro(m.collected)}</strong></div>
      <details class="minijob-details"><summary>Zusammensetzung (${percentText(total)} vom Lohn)</summary>${rows}
        <p class="small">${status} · Pauschsteuer ${m.tax_by_employer ? 'tragt ihr' : 'trägt die Nanny'}.
        <button class="btn ghost" data-nanny-levies>Sätze anpassen</button></p></details>
      <div class="row between nanny-line"><span>Kosten für euch insgesamt</span><span>${euro(m.family_total)}</span></div>
      ${m.over_limit ? `<div class="error-banner">Über der Minijob-Grenze von ${euro(m.limit_cents)} im Monat. Bitte prüfen; ein gelegentliches Überschreiten ist nur begrenzt erlaubt.</div>` : ''}
      ${m.estimated ? '<p class="small">Vor Einführung der Abgabenberechnung abgeschlossen: mit den aktuellen Sätzen geschätzt.</p>' : ''}
      ${half ? `<p class="small">${esc(half.months)}: bisher ${euro(half.gross)} Lohn bis ${esc(half.until)}. Die Minijob-Zentrale zieht dafür ${half.collection} etwa ${euro(half.collected)} ein (Lastschrift, maßgeblich ist ihr Bescheid).</p>` : ''}
    </div>`;
}

function nannyLevyDialog() {
  const s = nannyState.levies;
  const labels = {kv: 'Krankenversicherung', rv: 'Rentenversicherung', tax: 'Pauschsteuer', u1: 'Umlage U1 (Krankheit)',
                  u2: 'Umlage U2 (Mutterschaft)', uv: 'Unfallversicherung'};
  const fields = Object.entries(labels).map(([key, label]) => `<div class="field"><label for="lv-${key}">${label} in %</label>
    <input id="lv-${key}" name="${key}" type="number" min="0" max="30" step="0.01" required value="${(s.rates[key] / 100).toFixed(2)}"></div>`).join('');
  dialog('Minijob-Abgaben', `Minijob im Privathaushalt · Sätze ${s.year}`, `<form>
    <div class="field-pair">${fields}</div>
    <div class="field"><label for="lv-limit">Minijob-Grenze pro Monat in Euro</label><input id="lv-limit" name="limit" type="number" min="100" max="2000" step="1" value="${s.limit_cents / 100}"></div>
    <label class="choice"><input type="checkbox" name="rv_exempt" ${s.rv_exempt ? 'checked' : ''}> Nanny ist von der Rentenversicherung befreit</label>
    <label class="choice"><input type="checkbox" name="tax_by_employer" ${s.tax_by_employer ? 'checked' : ''}> Pauschsteuer tragen wir</label>
    <p class="note">Die Sätze ändern sich meist zum Jahreswechsel; bitte mit dem Beitragsbescheid oder dem Haushaltsscheck-Rechner der Minijob-Zentrale abgleichen. Abgeschlossene Monate behalten ihre Werte.</p>
    <div class="dialog-footer"><button class="btn primary" type="submit">Speichern</button></div></form>`);
  submitForm(modal.querySelector('form'), async data => {
    const rates = Object.fromEntries(Object.keys(labels).map(key => [key, Math.round(Number(data[key]) * 100)]));
    await api('/nanny/levies', {rates, rv_exempt: data.rv_exempt === 'on', tax_by_employer: data.tax_by_employer === 'on',
                                limit_cents: Math.round(Number(data.limit) * 100)});
    await loadNanny();
  });
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
      ${minijobHTML(statement)}
      <p class="note">Geplante Zeiten zählen, sofern keine Abweichung eingetragen ist.</p>
      ${footer}
    </div>
  </section>`;
}

function monthBanners(wishes, requested, locked, phoneNote) {
  if (locked) return '';
  let html = '';
  if (wishes.length) {
    html += `<div class="planning-banner"><div><b>${wishes.length === 1 ? 'Ein Wunsch' : wishes.length + ' Wünsche'} für ${monthName(month)} noch nicht angefragt</b>
      <p>Alle Termine des Monats in einer WhatsApp-Nachricht an die Nanny.${phoneNote}</p></div>
      <button class="btn primary" data-nanny-request="${wishes.map(s => s.id).join(',')}">Monatsnachricht senden</button></div>`;
  }
  if (requested.length) {
    html += `<div class="planning-banner nanny-answer-banner"><div><b>${requested.length === 1 ? 'Ein Termin wartet' : requested.length + ' Termine warten'} auf Antwort</b>
      <p>Hat die Nanny geantwortet? Zusagen und Absagen gesammelt eintragen.</p></div>
      <button class="btn green" data-nanny-answer>Antwort eintragen</button></div>`;
  }
  return html;
}

function nannyHTML() {
  if (!nannyState || nannyState.month !== month) {
    return '<section class="panel"><div class="empty-state">Nanny-Planung wird geladen …</div></section>';
  }
  const {shifts, statement, settings} = nannyState;
  const locked = statement.state !== 'open';
  const wishes = shifts.filter(s => s.state === 'wish');
  const requested = shifts.filter(s => s.state === 'requested');
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
        ${locked ? '' : `<button class="btn" data-nanny-new>${icon('plus')}Einzeltermin</button>
        <button class="btn primary" data-nanny-plan>${icon('calendar')}Monat planen</button>
        ${month + '-01' <= nannyState.today ? `<button class="btn" data-nanny-past>${icon('check')}Nachtragen</button>` : ''}`}
      </div>
    </div>
    ${locked ? '<div class="note nanny-locked">Dieser Monat ist abgerechnet. Zum Ändern die Abrechnung wieder öffnen.</div>' : ''}
    <div class="content-grid"><div class="stack">
      ${monthBanners(wishes, requested, locked, phoneNote)}
      <section class="panel"><div class="panel-head"><div><h2>Nanny-Termine</h2><p>An Nanny-Tagen holt ihr Lina früher ab und übergebt zuhause.</p></div><span class="status gray">${active.length}</span></div>
        ${active.length ? active.map(s => shiftRow(s, locked)).join('') : `<div class="empty-state">${icon('users')}<b>Keine Nanny-Termine geplant.</b><p>Wünsche könnt ihr bei der Monatsplanung gleich mit anlegen.</p></div>`}
      </section>
      ${closedShifts.length ? `<details class="panel meal-done"><summary>Abgesagt (${closedShifts.length})</summary>${closedShifts.map(s => shiftRow(s, true)).join('')}</details>` : ''}
    </div>
    <aside class="rail">${statementHTML(statement)}</aside></div>`;
}

function nannyPlanDialog() {
  const first = dateObj(month + '-01');
  const last = new Date(first.getFullYear(), first.getMonth() + 1, 0);
  const taken = new Set(nannyState.shifts.filter(s => ['wish', 'requested', 'confirmed'].includes(s.state)).map(s => s.day));
  const weeks = [];
  for (let d = new Date(first); d <= last; d.setDate(d.getDate() + 1)) {
    if (d.getDay() === 0 || d.getDay() === 6) continue;
    const day = iso(d);
    if (!weeks.length || d.getDay() === 1) weeks.push([]);
    weeks[weeks.length - 1].push(day);
  }
  const dayBox = day => {
    const past = day < nannyState.today;
    const planned = taken.has(day);
    const pickup = pickupOwner(day);
    return `<label class="nanny-pick ${planned ? 'planned' : ''} ${past ? 'past' : ''}">
      <input type="checkbox" name="day" value="${day}" ${planned ? 'checked disabled' : past ? 'disabled' : ''}>
      <span><b>${fmt(day, {weekday: 'short'})} ${fmt(day, {day: 'numeric'})}.</b>
      <small>${planned ? 'geplant' : pickup ? 'Abholung ' + esc(pickup) : '&nbsp;'}</small></span>
    </label>`;
  };
  const free = weeks.flat().filter(day => day >= nannyState.today && !taken.has(day));
  dialog('Nanny-Monat planen', monthName(month), free.length ? `<form>
    <p>Tage auswählen, an denen ihr die Nanny braucht. Danach geht alles in einer WhatsApp-Nachricht raus.</p>
    <div class="nanny-weeks">${weeks.map((week, index) => `<div class="nanny-week">${index === 0 ? '<span aria-hidden="true"></span>'.repeat((dateObj(week[0]).getDay() + 6) % 7) : ''}${week.map(dayBox).join('')}</div>`).join('')}</div>
    <div class="field-pair">
      <div class="field"><label for="plan-start">Von</label><input id="plan-start" name="start" type="time" required value="16:00"></div>
      <div class="field"><label for="plan-end">Bis</label><input id="plan-end" name="end" type="time" required value="18:00"></div>
    </div>
    <p class="note">Gilt für alle ausgewählten Tage; einzelne Zeiten lassen sich danach ändern. An diesen Tagen holt ihr Lina früher ab.</p>
    <div class="dialog-footer"><button class="btn primary" type="submit">Wünsche speichern und Nachricht vorbereiten</button></div>
  </form>` : '<p class="note">In diesem Monat sind keine freien Werktage mehr übrig.</p>');
  const form = modal.querySelector('form');
  if (!form) return;
  form.onsubmit = async event => {
    event.preventDefault();
    const days = [...form.querySelectorAll('input[name=day]:checked:not(:disabled)')].map(input => input.value);
    if (!days.length) return formError(form, 'Bitte mindestens einen Tag auswählen.');
    const button = form.querySelector('[type=submit]');
    button.disabled = true;
    try {
      await api('/nanny/shifts/batch', {days, start: form.start.value, end: form.end.value});
      modal.close();
      await load();
      const wishes = nannyState.shifts.filter(s => s.state === 'wish');
      if (wishes.length) nannyRequestDialog(wishes.map(s => s.id).join(','));
    } catch (error) {
      formError(form, error.message);
      button.disabled = false;
    }
  };
}

// Shifts that already took place (N-13): stored as confirmed right away,
// without a WhatsApp request, so they count for the statement.
function nannyPastDialog() {
  const first = dateObj(month + '-01');
  const last = new Date(first.getFullYear(), first.getMonth() + 1, 0);
  const taken = new Set(nannyState.shifts.filter(s => ['wish', 'requested', 'confirmed'].includes(s.state)).map(s => s.day));
  const weeks = [];
  for (let d = new Date(first); d <= last; d.setDate(d.getDate() + 1)) {
    if (!weeks.length || d.getDay() === 1) weeks.push([]);
    weeks[weeks.length - 1].push(iso(d));
  }
  const dayBox = day => {
    const future = day > nannyState.today;
    const planned = taken.has(day);
    return `<label class="nanny-pick ${planned ? 'planned' : ''} ${future ? 'past' : ''}">
      <input type="checkbox" name="day" value="${day}" ${planned ? 'checked disabled' : future ? 'disabled' : ''}>
      <span><b>${fmt(day, {weekday: 'short'})} ${fmt(day, {day: 'numeric'})}.</b><small>${planned ? 'vorhanden' : '&nbsp;'}</small></span>
    </label>`;
  };
  const lead = (dateObj(weeks[0][0]).getDay() + 6) % 7;
  dialog('Nanny-Termine nachtragen', monthName(month), `<form>
    <p>Tage auswählen, an denen die Nanny schon da war. Sie werden direkt als bestätigt gespeichert und zählen für die Abrechnung.</p>
    <div class="nanny-weeks nanny-weeks-full">${weeks.map((week, index) => `<div class="nanny-week">${index === 0 ? '<span aria-hidden="true"></span>'.repeat(lead) : ''}${week.map(dayBox).join('')}</div>`).join('')}</div>
    <div class="field-pair">
      <div class="field"><label for="past-start">Von</label><input id="past-start" name="start" type="time" required value="16:00"></div>
      <div class="field"><label for="past-end">Bis</label><input id="past-end" name="end" type="time" required value="18:00"></div>
    </div>
    <div class="field"><label for="past-note">Notiz (optional)</label><input id="past-note" name="note" maxlength="300" data-speech placeholder="z. B. aus dem Kalender nachgetragen"></div>
    <p class="note">Gilt für alle ausgewählten Tage; abweichende Zeiten danach einzeln korrigieren. Die andere Person wird informiert.</p>
    <div class="dialog-footer"><button class="btn primary" type="submit">Nachtragen</button></div>
  </form>`);
  const form = modal.querySelector('form');
  form.onsubmit = async event => {
    event.preventDefault();
    const days = [...form.querySelectorAll('input[name=day]:checked:not(:disabled)')].map(input => input.value);
    if (!days.length) return formError(form, 'Bitte mindestens einen Tag auswählen.');
    const button = form.querySelector('[type=submit]');
    button.disabled = true;
    try {
      await api('/nanny/shifts/past', {days, start: form.start.value, end: form.end.value, note: form.note.value});
      modal.close();
      await load();
      toast(days.length === 1 ? 'Termin nachgetragen.' : `${days.length} Termine nachgetragen.`);
    } catch (error) {
      formError(form, error.message);
      button.disabled = false;
    }
  };
}

function nannyAnswerDialog() {
  const requested = nannyState.shifts.filter(s => s.state === 'requested');
  dialog('Antwort der Nanny eintragen', monthName(month), `<form>
    <div class="actions nanny-answer-all"><button type="button" class="btn" data-answer-all="confirm">Alle zugesagt</button></div>
    ${requested.map(s => `<fieldset class="nanny-answer" data-id="${s.id}" data-version="${s.version}">
      <legend>${esc(shiftLine(s))}</legend>
      <label class="choice"><input type="radio" name="a${s.id}" value="confirm"> Kommt</label>
      <label class="choice"><input type="radio" name="a${s.id}" value="decline"> Kann nicht</label>
      <label class="choice"><input type="radio" name="a${s.id}" value="" checked> Noch offen</label>
    </fieldset>`).join('')}
    <div class="dialog-footer"><button type="submit" class="btn green">Antwort speichern</button></div>
  </form>`);
  const form = modal.querySelector('form');
  form.querySelector('[data-answer-all]').onclick = () => {
    form.querySelectorAll('input[value=confirm]').forEach(input => { input.checked = true; });
  };
  submitForm(form, () => {
    const items = [...form.querySelectorAll('.nanny-answer')].map(set => ({
      id: Number(set.dataset.id), version: Number(set.dataset.version),
      answer: set.querySelector('input:checked')?.value || '',
    })).filter(item => item.answer);
    if (!items.length) throw new Error('Bitte mindestens eine Antwort auswählen.');
    return api('/nanny/answer', {items});
  });
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
  dialog(shifts.length > 1 ? 'Monatsnachricht an die Nanny' : 'Nanny per WhatsApp anfragen', `${shifts.length === 1 ? nannyDay(shifts[0].day) : shifts.length + ' Termine · ' + monthName(month)}`, `
    <div class="field"><label for="nanny-text">Nachricht</label><textarea id="nanny-text" readonly rows="${Math.min(14, shifts.length + 5)}">${esc(text)}</textarea></div>
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
    close: ['Monat abschließen', `${hoursText(statement.minutes)} · Überweisung ${euro(statement.minijob.payout)}. Lohn und Abgaben werden festgehalten, die Termine dieses Monats gesperrt. Tobi erhält die Aufgabe zur Überweisung.`, 'Abschließen'],
    paid: ['Überweisung bestätigen', `${euro(statement.minijob.payout)} für ${monthName(month)} überwiesen? Danach ist der Monat endgültig.`, 'Ja, ist überwiesen'],
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
  app.querySelector('[data-nanny-plan]')?.addEventListener('click', nannyPlanDialog);
  app.querySelector('[data-nanny-past]')?.addEventListener('click', nannyPastDialog);
  app.querySelector('[data-nanny-answer]')?.addEventListener('click', nannyAnswerDialog);
  on('[data-nanny-edit]', b => nannyShiftForm(nannyShift(b.dataset.nannyEdit)));
  on('[data-nanny-request]', b => nannyRequestDialog(b.dataset.nannyRequest));
  on('[data-nanny-confirm]', b => nannySimpleDialog(nannyShift(b.dataset.nannyConfirm), 'confirm'));
  on('[data-nanny-decline]', b => nannySimpleDialog(nannyShift(b.dataset.nannyDecline), 'decline'));
  on('[data-nanny-cancel]', b => nannyCancelDialog(nannyShift(b.dataset.nannyCancel)));
  on('[data-nanny-correct]', b => nannyCorrectDialog(nannyShift(b.dataset.nannyCorrect)));
  on('[data-nanny-statement]', b => nannyStatementDialog(b.dataset.nannyStatement));
  app.querySelector('[data-nanny-levies]')?.addEventListener('click', nannyLevyDialog);
}
