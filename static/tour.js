'use strict';
// Guided tour (A-11): walks through the real views with a small card and
// highlights the relevant button. Offered once per person after login
// (stored on the NAS), restartable via "?" in the header.

const TOUR_STEPS = [
  {view: 'home', title: 'Willkommen bei Family OS',
   text: 'Hier seht ihr auf einen Blick die nächsten Betreuungstage, eure offenen Aufgaben und Vorschläge, die auf eine Zustimmung warten. Dieser Rundgang zeigt dir kurz alle Bereiche.'},
  {view: 'plan', highlight: '.calendar-grid .slot', title: 'Monatsplanung: Bringen & Abholen',
   text: 'Tippe auf einen Weg, um ihn dir oder Tobi vorzuschlagen. Die andere Person bestätigt – vorher ändert sich nichts. Vorläufige Einträge stehen als „[Vorläufig]“ im gemeinsamen Google-Kalender.'},
  {view: 'plan', highlight: '[data-start-planning]', title: 'Gemeinsam auf der Couch planen',
   text: 'Sitzt ihr zusammen, startet „Gemeinsam planen“: Dann gilt jede Zuordnung sofort, ohne einzelne Bestätigung. Der Modus endet nach zwei Stunden von selbst.'},
  {view: 'plan', highlight: '[data-closure-new]', title: 'Tage ohne Krippe',
   text: 'Schließtage, Feiertage, Urlaub oder wenn Lina krank ist: unter „Ohne Krippe“ eintragen. Nach der Bestätigung entfallen Bringen und Abholen an diesen Tagen und zählen nicht zur Verteilung.'},
  {view: 'issues', highlight: '[data-action="new-issue"]', title: 'Klärungspunkte',
   text: 'Passt ein Termin nicht, aber ihr wisst noch keine Lösung? Lege einen Klärungspunkt an. Er zeigt Gesprächsbedarf an, ohne den gültigen Plan zu ändern.'},
  {view: 'tasks', title: 'Aufgaben',
   text: 'Jede Aufgabe hat genau eine verantwortliche Person. „Arbeitskalender aktualisieren“ sammelt alle Termine, die du in deinem Outlook eintragen oder entfernen musst – mit „In Outlook eintragen“ geht das mit einem Tipp.'},
  {view: 'meals', highlight: '[data-meal-suggest]', title: 'Essen & Einkauf',
   text: 'Die Cookidoo-Woche von Samstag bis Freitag. „Woche vorschlagen“ sucht vegetarische, eiweißreiche Gerichte; „Anderes Gericht“ tauscht einzelne Tage. Übernommen wird erst per Klick.'},
  {view: 'meals', highlight: '#meal-shopping', title: 'Einkaufsliste und Gutscheine',
   text: 'Die Einkaufsliste kommt aus Cookidoo. Gutschein-PDFs liegen daneben und sind an der Kasse mit einem Tipp offen. Ohne Netz zeigt das iPhone die zuletzt gespeicherte Liste.'},
  {view: 'nanny', title: 'Nanny',
   text: 'Nanny-Wünsche für den Monat anlegen, die Anfrage als fertigen WhatsApp-Text verschicken und Zu- oder Absagen eintragen. Bestätigte Termine stehen im Kalender; Tobi kümmert sich um die Abrechnung.'},
  {view: 'lina', highlight: '[data-lina-new="nursery"]', title: 'Lina',
   text: 'Windeln: nur „Neue Packung geöffnet“ tippen, bei knappem Vorrat entsteht eine Einkaufsaufgabe. Meldet die Krippe Bedarf an Wechselkleidung, notiere ihn hier – wer als Nächstes bringt, nimmt es mit. Kleidungsbedarf und Aussortiertes koordinierst du.'},
  {view: 'notifications', title: 'Mitteilungen',
   text: 'Neue Abstimmungen kommen sofort, abends um 19 Uhr eine Übersicht für morgen, sonntags für die Woche.'},
  {view: 'connections', highlight: '[data-enable-push]', title: 'Aufs iPhone holen',
   text: 'In Safari „Teilen → Zum Home-Bildschirm“ wählen und Family OS von dort öffnen. Dann hier „Auf diesem Gerät aktivieren“ für Mitteilungen. In fast jedem Eingabefeld gibt es außerdem „Sprechen“. Wer mag, richtet hier auch ein Widget für den Home-Bildschirm ein (App „Scriptable“).'},
  {view: 'home', title: 'Fertig!',
   text: 'Das war der Überblick. Den Rundgang findest du jederzeit wieder über das „?“ oben rechts.'},
];

let tourIndex = -1;

function tourCard() {
  let card = document.querySelector('#tour-card');
  if (!card) {
    card = document.createElement('section');
    card.id = 'tour-card';
    card.className = 'tour-card';
    card.setAttribute('role', 'dialog');
    card.setAttribute('aria-live', 'polite');
    document.body.append(card);
  }
  return card;
}

function tourRefresh() {
  document.querySelectorAll('.tour-highlight').forEach(el => el.classList.remove('tour-highlight'));
  if (tourIndex < 0) return;
  const step = TOUR_STEPS[tourIndex];
  document.querySelectorAll(`[data-view="${step.view}"]`).forEach(el => el.classList.add('tour-highlight'));
  const target = step.highlight && app.querySelector(step.highlight);
  if (target) {
    target.classList.add('tour-highlight');
    target.scrollIntoView({block: 'center', behavior: 'smooth'});
  }
}

async function tourShow(index) {
  tourIndex = index;
  const step = TOUR_STEPS[index];
  if (modal.open) modal.close();
  try {
    await navigate(step.view);
  } catch (error) {
    // Stay on the current view; the explanation still applies.
  }
  const last = index === TOUR_STEPS.length - 1;
  const card = tourCard();
  card.innerHTML = `<div class="row between"><span class="eyebrow">Rundgang · ${index + 1} / ${TOUR_STEPS.length}</span>
      <button class="icon-btn" data-tour-close aria-label="Rundgang beenden">${icon('close')}</button></div>
    <h3>${step.title}</h3><p>${step.text}</p>
    <div class="actions">${index ? '<button class="btn" data-tour-back>Zurück</button>' : ''}
      <button class="btn primary" data-tour-next>${last ? 'Fertig' : 'Weiter'}</button></div>`;
  card.hidden = false;
  card.querySelector('[data-tour-close]').onclick = tourEnd;
  card.querySelector('[data-tour-back]')?.addEventListener('click', () => tourShow(index - 1));
  card.querySelector('[data-tour-next]').onclick = () => (last ? tourEnd() : tourShow(index + 1));
  tourRefresh();
}

function tourEnd() {
  tourIndex = -1;
  const card = document.querySelector('#tour-card');
  if (card) card.hidden = true;
  tourRefresh();
  tourSeen();
}

async function tourSeen() {
  if (state?.tour_seen) return;
  try {
    await api('/tour/seen', {});
    if (state) state.tour_seen = true;
  } catch (error) {
    // Not critical: the offer may show once more.
  }
}

// After login: offer the tour once per person.
function tourOffer() {
  if (!state || state.tour_seen || tourIndex >= 0 || modal.open || tourOffer.shown) return;
  tourOffer.shown = true;
  dialog(`Hallo ${names[state.user]}!`, 'Kurzer Rundgang durch Family OS?', `<form>
    <p>In etwa zwei Minuten zeigt dir Family OS alle Bereiche: Betreuung, Aufgaben, Essen, Nanny und Lina.</p>
    <div class="dialog-footer"><button type="button" class="btn" data-tour-later>Später</button>
      <button type="submit" class="btn primary">Rundgang starten</button></div></form>`);
  const form = modal.querySelector('form');
  form.onsubmit = event => { event.preventDefault(); modal.close(); tourShow(0); };
  modal.querySelector('[data-tour-later]').onclick = () => {
    modal.close();
    tourSeen();
    toast('Den Rundgang findest du jederzeit über „?“ oben rechts.');
  };
}

function bindTour() {
  app.querySelector('[data-tour-start]')?.addEventListener('click', () => tourShow(0));
  tourRefresh();
}
