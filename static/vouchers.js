'use strict';
// Shopping vouchers (vouchers.py): PDF stored on the NAS, remaining value kept
// by hand, quick access at the checkout. Shown in "Essen & Einkauf".

let voucherState = null;

const voucherStatus = {active: 'Unbenutzt', partial: 'Teilweise genutzt', used: 'Verbraucht'};

function voucherEuro(cents) {
  return (cents / 100).toLocaleString('de-DE', {style: 'currency', currency: 'EUR'});
}

function parseVoucherEuro(text) {
  const value = Number(String(text).trim().replace(/\s|€/g, '').replace(/\./g, '').replace(',', '.'));
  return Number.isFinite(value) ? Math.round(value * 100) : NaN;
}

async function loadVouchers() {
  try {
    voucherState = await api('/vouchers');
  } catch (error) {
    voucherState = null;
  }
}

function voucherRow(v) {
  const open = v.status !== 'used';
  return `<div class="list-row voucher ${v.status}"><div class="grow">
      <div class="row between"><b>${esc(v.store)} · ${voucherEuro(v.remaining_cents)}</b>
        <span class="status ${v.status === 'active' ? 'green' : v.status === 'partial' ? 'amber' : 'gray'}">${voucherStatus[v.status]}</span></div>
      <small>Wert ${voucherEuro(v.value_cents)} · abgelegt ${deadlineText(v.created)}${v.note ? ' · ' + esc(v.note) : ''}</small>
      <div class="actions"><a class="btn ${open ? 'primary' : 'ghost'}" href="/api/vouchers/${v.id}/pdf" target="_blank" rel="noopener">PDF öffnen</a>
        ${open ? `<button class="btn" data-voucher-use="${v.id}">Eingelöst</button>` : ''}
        <button class="btn ghost" data-voucher-set="${v.id}">Rest korrigieren</button></div>
    </div></div>`;
}

function vouchersPanel() {
  if (!voucherState) return '';
  const open = voucherState.vouchers.filter(v => v.status !== 'used');
  const used = voucherState.vouchers.filter(v => v.status === 'used');
  return `<section class="panel" id="vouchers"><div class="panel-head"><div><h2>Gutscheine</h2>
      <p>Verfügbar: <b>${voucherEuro(voucherState.available_cents)}</b></p></div>
      <button class="btn" data-voucher-new>${icon('plus')}PDF ablegen</button></div>
    ${open.map(voucherRow).join('') || '<div class="empty-state">Kein aktiver Gutschein.</div>'}
    ${used.length ? `<details class="meal-done"><summary>Archiv (${used.length})</summary>${used.map(voucherRow).join('')}</details>` : ''}
    <div class="panel-body"><label class="choice"><input type="checkbox" data-voucher-reminder ${voucherState.reminder ? 'checked' : ''}>
      Donnerstags an PAYBACK-Gutscheine erinnern</label>
      <small>Kauf bis Do 16 Uhr: etwa 24 Stunden Umwandlung plus eine Stunde bis zur E-Mail.</small></div>
  </section>`;
}

function voucherUploadDialog() {
  dialog('Gutschein ablegen', 'Die PDF bleibt auf eurem NAS', `<form>
    <div class="field"><label for="vf">Gutschein-PDF</label><input id="vf" name="file" type="file" accept="application/pdf,.pdf" required></div>
    <div class="field-pair">
      <div class="field"><label for="vv">Wert</label><input id="vv" name="value" inputmode="decimal" required placeholder="z. B. 25,00"></div>
      <div class="field"><label for="vs">Geschäft</label><input id="vs" name="store" maxlength="60" value="Kaufland"></div>
    </div>
    <div class="field"><label for="vn">Notiz (optional)</label><input id="vn" name="note" maxlength="200"></div>
    <div class="dialog-footer"><button class="btn primary" type="submit">Ablegen</button></div></form>`);
  const form = modal.querySelector('form');
  form.onsubmit = async event => {
    event.preventDefault();
    const button = form.querySelector('[type=submit]');
    const file = form.file.files[0];
    const cents = parseVoucherEuro(form.value.value);
    if (!file || !(cents > 0)) return formError(form, 'Bitte PDF und Wert angeben.');
    if (file.size > 5 * 1024 * 1024) return formError(form, 'Die PDF ist größer als 5 MB.');
    button.disabled = true;
    try {
      const query = new URLSearchParams({value_cents: cents, store: form.store.value, note: form.note.value, filename: file.name});
      const response = await fetch('/api/vouchers?' + query, {method: 'POST', body: file,
        headers: {'Content-Type': 'application/pdf', 'X-Family-Request': '1'}});
      if (!response.ok) {
        let detail = 'Ablegen fehlgeschlagen (HTTP ' + response.status + ').';
        try { detail = (await response.json()).detail || detail; } catch (_) {}
        throw new Error(detail);
      }
      modal.close();
      await loadVouchers();
      await load();
      toast('Gutschein abgelegt.');
    } catch (error) {
      formError(form, error.message);
      button.disabled = false;
    }
  };
}

function voucherUseDialog(id, action) {
  const v = voucherState.vouchers.find(x => x.id === Number(id));
  const spend = action === 'spend';
  dialog(spend ? 'Gutschein eingelöst' : 'Restbetrag korrigieren', `${esc(v.store)} · noch ${voucherEuro(v.remaining_cents)}`, `<form>
    <div class="field"><label for="va">${spend ? 'Eingelöster Betrag' : 'Restbetrag laut Kassenbon'}</label>
      <input id="va" name="amount" inputmode="decimal" required value="${spend ? voucherEuro(v.remaining_cents).replace(/\s?€/, '') : ''}"></div>
    <p class="note">${spend ? 'Bei vollem Betrag wandert der Gutschein ins Archiv. Ein Rest bleibt aktiv.' : 'Zum Beispiel wenn der Bon einen anderen Rest nennt.'}</p>
    <div class="dialog-footer"><button class="btn primary" type="submit">Speichern</button></div></form>`);
  submitForm(modal.querySelector('form'), async data => {
    const cents = parseVoucherEuro(data.amount);
    if (!(cents >= 0)) throw new Error('Bitte einen Betrag angeben.');
    voucherState = await api(`/vouchers/${v.id}/use`, {action, cents, version: v.version});
  });
}

function bindVouchers() {
  app.querySelector('[data-voucher-new]')?.addEventListener('click', voucherUploadDialog);
  app.querySelectorAll('[data-voucher-use]').forEach(b => { b.onclick = () => voucherUseDialog(b.dataset.voucherUse, 'spend'); });
  app.querySelectorAll('[data-voucher-set]').forEach(b => { b.onclick = () => voucherUseDialog(b.dataset.voucherSet, 'set'); });
  app.querySelector('[data-voucher-reminder]')?.addEventListener('change', async event => {
    try {
      voucherState = await api('/vouchers/settings', {reminder: event.target.checked});
      toast(event.target.checked ? 'Erinnerung eingeschaltet.' : 'Erinnerung ausgeschaltet.');
    } catch (error) {
      toast(error.message);
      event.target.checked = !event.target.checked;
    }
  });
}
