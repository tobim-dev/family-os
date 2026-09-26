'use strict';
// "In Outlook eintragen" (work_calendar.py, B-17): opens a prefilled new event
// in the parent's own Outlook. Family OS never reads the work calendar.
// Two variants until tested on the iPhones: the Outlook app (ms-outlook://)
// and Outlook on the web as fallback.

// Spaces as %20 and times unencoded, like the examples known to work with
// Outlook ("+" can end up literally in the subject).
function outlookQuery(params) {
  return Object.entries(params).map(([key, value]) => {
    const text = /^[\d:TZ-]+$/.test(value) ? value : encodeURIComponent(value);
    return key + '=' + text;
  }).join('&');
}

function outlookLinks(block) {
  const app = 'ms-outlook://events/new?' + outlookQuery({
    title: block.title, start: block.start_local, end: block.end_local});
  const web = 'https://outlook.office.com/calendar/deeplink/compose?' + outlookQuery({
    path: '/calendar/action/compose', rru: 'addevent', subject: block.title,
    startdt: block.start_utc, enddt: block.end_utc});
  return {app, web};
}

// The bundled work-calendar task (B-18): every entry with "eintragen" or
// "entfernen"; entries to add get the Outlook buttons for their owner.
function outlookActions(task) {
  if (!task.calendar_items) return '';
  const own = task.owner === state.user;
  const rows = task.calendar_items.map(item => {
    const links = own && item.calendar_block ? outlookLinks(item.calendar_block) : null;
    return `<li class="work-entry ${item.action}"><span class="status ${item.action === 'add' ? 'green' : 'amber'}">${item.action === 'add' ? 'Eintragen' : 'Entfernen'}</span>
      <span>${esc(item.label)}</span>
      ${links ? `<span class="work-links"><a class="btn primary" href="${esc(links.app)}">In Outlook eintragen</a>
        <a class="btn ghost" href="${esc(links.web)}" target="_blank" rel="noopener noreferrer">Im Web</a></span>` : ''}</li>`;
  }).join('');
  const hint = own && task.calendar_items.some(i => i.calendar_block)
    ? '<small>Vor dem Speichern „Anzeigen als: Abwesend“ wählen. Wenn alles angepasst ist, die Aufgabe einmal abhaken.</small>' : '';
  return `<ul class="work-entries">${rows}</ul>${hint}`;
}

function workCalendarUpto(task) {
  return task.calendar_items ? {upto: Math.max(0, ...task.calendar_items.map(i => i.id))} : {};
}
