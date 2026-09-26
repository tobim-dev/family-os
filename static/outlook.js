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

function outlookActions(task) {
  if (!task.calendar_block || task.owner !== state.user) return '';
  const links = outlookLinks(task.calendar_block);
  return `<div class="actions outlook-actions">
      <a class="btn primary" href="${esc(links.app)}">In Outlook eintragen</a>
      <a class="btn ghost" href="${esc(links.web)}" target="_blank" rel="noopener noreferrer">In Outlook im Web</a></div>
    <small>Vor dem Speichern „Anzeigen als: Abwesend“ wählen. Danach diese Aufgabe abhaken.</small>`;
}
