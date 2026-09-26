'use strict';
// Offline page: shows the copy saved on this device. Read only.

function offlineEsc(value) {
  return String(value ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
}

function offlineEuro(cents) {
  return (cents / 100).toLocaleString('de-DE', {style: 'currency', currency: 'EUR'});
}

function offlineTime(value) {
  return new Date(value).toLocaleString('de-DE', {weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit'}) + ' Uhr';
}

function offlineRender(data) {
  const open = data.items.filter(i => !i.owned);
  const done = data.items.filter(i => i.owned);
  const row = i => `<div class="list-row"><div><b class="${i.owned ? 'done' : ''}">${offlineEsc(i.name)}</b>
      <p>${offlineEsc(i.description || (i.own ? 'Eigener Artikel' : ''))}</p></div></div>`;
  const vouchers = data.vouchers.map(v => `<div class="list-row"><div class="grow"><b>${offlineEsc(v.store)} · ${offlineEuro(v.remaining_cents)}</b>
      <div class="actions"><a class="btn primary" href="/api/vouchers/${v.id}/pdf">PDF öffnen</a></div></div></div>`).join('');
  return `${data.vouchers.length ? `<section class="panel"><div class="panel-head"><h2>Gutscheine</h2></div>${vouchers}</section>` : ''}
    <section class="panel"><div class="panel-head"><h2>Einkaufsliste</h2><span class="status amber">${open.length} offen</span></div>
      ${open.map(row).join('') || '<div class="empty-state">Nichts offen.</div>'}
      ${done.length ? `<details class="meal-done"><summary>Vorhanden / gekauft (${done.length})</summary>${done.map(row).join('')}</details>` : ''}
    </section>
    <p class="note">Nur zum Lesen. Abhaken bitte in der Cookidoo-App; Family OS gleicht sich danach wieder ab.</p>`;
}

(async () => {
  const stand = document.querySelector('#offline-stand');
  const content = document.querySelector('#offline-content');
  try {
    const response = await fetch('/api/offline');
    if (!response.ok) throw new Error('missing');
    const data = await response.json();
    const source = data.shopping_updated ? 'Einkaufsliste von ' + offlineTime(data.shopping_updated * 1000) : 'Noch keine Einkaufsliste geladen';
    stand.textContent = `${source}${data.saved_at ? ' · auf diesem Gerät gespeichert ' + offlineTime(data.saved_at) : ''}.`;
    content.innerHTML = offlineRender(data);
  } catch (error) {
    stand.textContent = 'Auf diesem Gerät ist noch keine Offline-Kopie gespeichert. Sie entsteht, sobald Family OS einmal mit Verbindung geöffnet war.';
  }
})();

// Why is the offline page shown? Ask the NAS directly (/health is never cached).
async function offlineDiagnose() {
  const box = document.querySelector('#offline-reason');
  const started = Date.now();
  const timeout = new Promise((_, reject) => setTimeout(() => reject(new Error('timeout')), 15000));
  try {
    const response = await Promise.race([fetch('/health?pruefung=' + started, {cache: 'no-store'}), timeout]);
    const seconds = ((Date.now() - started) / 1000).toFixed(1).replace('.', ',');
    if (response.ok) {
      box.textContent = `Der NAS antwortet wieder (in ${seconds} s). „Erneut verbinden“ öffnet Family OS.`;
    } else if ([502, 503, 504].includes(response.status)) {
      box.textContent = `Der Reverse Proxy erreicht den Family-OS-Container nicht (HTTP ${response.status}). `
        + 'Nach einem Update bitte im Reverse Proxy das Ziel des Containers prüfen oder ihn neu starten.';
    } else {
      box.textContent = `Der NAS antwortet mit HTTP ${response.status}.`;
    }
  } catch (error) {
    box.textContent = error.message === 'timeout'
      ? 'Der NAS antwortet nicht innerhalb von 15 Sekunden. Er ist erreichbar, aber überlastet oder startet gerade.'
      : 'Keine Verbindung zum NAS (kein Netz, oder der Reverse Proxy ist nicht erreichbar).';
  }
}

offlineDiagnose();
