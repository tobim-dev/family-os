'use strict';
// Lina (lina.py): diapers at home, spare clothes at the nursery, clothing
// needs and sorted-out clothes. Event based, no inventory keeping.

let linaState = null;

const urgencyLabels = {urgent: 'Dringend', season: 'Diese Saison', later: 'Später'};
const destinationLabels = {sell: 'Verkaufen', give: 'Verschenken', keep: 'Aufbewahren'};

async function loadLina() {
  try {
    linaState = await api('/lina');
    if (view === 'lina' && state) render();
  } catch (error) {
    toast(error.message);
  }
}

function diaperHTML(d) {
  const stock = d.stock === null ? '–' : d.stock;
  const low = d.stock !== null && d.stock <= d.settings.threshold;
  const pace = d.pace_days ? `Eine Packung reicht etwa ${String(d.pace_days).replace('.', ',')} Tage.` : 'Nach zwei geöffneten Packungen erscheint eine Schätzung.';
  const until = d.until ? ` Vorrat reicht voraussichtlich bis ${fmt(d.until, {weekday: 'long', day: 'numeric', month: 'long'})}.` : '';
  return `<section class="panel"><div class="panel-head"><div><h2>Windeln zuhause</h2>
      <p>${d.settings.size ? 'Größe ' + esc(d.settings.size) + ' · ' : ''}Die Krippe stellt ihre eigenen.</p></div>
      <span class="status ${low ? 'amber' : 'green'}">${stock} ${d.stock === 1 ? 'Packung' : 'Packungen'}</span></div>
    <div class="panel-body">
      <div class="actions"><button class="btn primary" data-diaper="opened">Neue Packung geöffnet</button>
        <button class="btn" data-diaper="bought">Packungen gekauft</button>
        <button class="btn ghost" data-diaper="set">Vorrat zählen</button>
        <button class="btn ghost" data-diaper-settings>Einstellungen</button></div>
      <p class="small">${pace}${until}</p>
      <p class="small">Ab ${d.settings.threshold} ${d.settings.threshold === 1 ? 'Packung' : 'Packungen'} erhält ${names[d.settings.owner]} die Aufgabe „Windeln kaufen“.</p>
      ${d.stock === null ? '<p class="note">Einmal den aktuellen Vorrat zählen, danach reicht „Neue Packung geöffnet“.</p>' : ''}
    </div></section>`;
}

function linaItemRow(item) {
  const meta = [item.size ? 'Größe ' + esc(item.size) : '', item.urgency ? urgencyLabels[item.urgency] : '',
    item.destination ? destinationLabels[item.destination] : '', names[item.owner]].filter(Boolean).join(' · ');
  const open = item.state === 'open';
  const buttons = open
    ? `<button class="btn" data-lina-item="${item.id}" data-lina-action="done">Erledigt</button>
       ${item.destination === 'sell' ? `<button class="btn ghost" data-vinted="${item.id}">Text für Vinted</button>` : ''}
       <button class="btn ghost" data-lina-item="${item.id}" data-lina-action="drop">Verwerfen</button>`
    : `<button class="btn ghost" data-lina-item="${item.id}" data-lina-action="reopen">Wieder öffnen</button>`;
  return `<div class="list-row"><div class="grow"><div class="row between">
      <b class="${open ? '' : 'done'}">${esc(item.text)}</b>
      ${item.urgency === 'urgent' && open ? '<span class="status red">Dringend</span>' : ''}</div>
    <small>${meta}</small>${item.details ? `<p>${esc(item.details)}</p>` : ''}
    <div class="actions">${buttons}</div></div></div>`;
}

function linaList(list, title, hint, button) {
  const items = linaState.items.filter(i => i.list === list);
  return `<section class="panel"><div class="panel-head"><div><h2>${title}</h2><p>${hint}</p></div>
      <button class="btn" data-lina-new="${list}">${icon('plus')}${button}</button></div>
    ${items.map(linaItemRow).join('') || '<div class="empty-state">Nichts offen.</div>'}</section>`;
}

function linaHTML() {
  if (!linaState) return '<section class="panel"><div class="empty-state">Wird geladen …</div></section>';
  return `<div class="content-grid"><div class="stack">
      ${diaperHTML(linaState.diapers)}
      ${linaList('nursery', 'Wechselkleidung Krippe', 'Was die Krippe braucht. Wer als Nächstes bringt, nimmt es mit.', 'Bedarf notieren')}
      ${linaList('need', 'Kleidung besorgen', 'Britta koordiniert. Nur Dringendes wird zur Aufgabe.', 'Bedarf notieren')}
    </div><aside class="rail">
      ${linaList('sort_out', 'Aussortiert', 'Passt nicht mehr: verkaufen, verschenken oder aufbewahren.', 'Teil notieren')}
      <div class="notice-card"><div class="eyebrow">Ohne Inventur</div><h3>Nur das Nötigste erfassen.</h3>
        <p>Keine Stückzahlen und keine Listen pflegen. Windeln über geöffnete Packungen, Kleidung über konkreten Bedarf.</p></div>
    </aside></div>`;
}

function diaperDialog(kind) {
  if (kind === 'opened') return diaperSave({kind, packs: 1});
  const title = kind === 'bought' ? 'Windeln gekauft' : 'Vorrat zählen';
  const label = kind === 'bought' ? 'Wie viele Packungen?' : 'Ungeöffnete Packungen zuhause';
  dialog(title, 'Windelvorrat zuhause', `<form><div class="field"><label for="dp">${label}</label>
      <input id="dp" name="packs" type="number" min="${kind === 'bought' ? 1 : 0}" max="50" value="${kind === 'bought' ? 1 : 0}" required></div>
    <div class="dialog-footer"><button class="btn primary" type="submit">Speichern</button></div></form>`);
  submitForm(modal.querySelector('form'), async data => {
    await api('/lina/diapers', {kind, packs: Number(data.packs)});
    await loadLina();
  });
}

async function diaperSave(body) {
  try {
    const result = await api('/lina/diapers', body);
    await loadLina();
    await load();
    toast(result.stock !== null && result.stock <= result.settings.threshold
      ? 'Notiert. Windeln stehen jetzt auf der Einkaufsaufgabe.' : 'Notiert.');
  } catch (error) {
    toast(error.message);
  }
}

function diaperSettingsDialog() {
  const s = linaState.diapers.settings;
  dialog('Windeln · Einstellungen', 'Wann und für wen die Einkaufsaufgabe entsteht', `<form>
    <div class="field-pair">
      <div class="field"><label for="dt">Aufgabe ab (Packungen)</label><input id="dt" name="threshold" type="number" min="0" max="10" value="${s.threshold}" required></div>
      <div class="field"><label for="do">Kauft ein</label><select id="do" name="owner">${Object.keys(names).map(p => `<option value="${p}" ${s.owner === p ? 'selected' : ''}>${names[p]}</option>`).join('')}</select></div>
    </div>
    <div class="field"><label for="ds">Größe (optional)</label><input id="ds" name="size" maxlength="40" value="${esc(s.size)}" placeholder="z. B. 5"></div>
    <div class="dialog-footer"><button class="btn primary" type="submit">Speichern</button></div></form>`);
  submitForm(modal.querySelector('form'), async data => {
    await api('/lina/diapers/settings', {threshold: Number(data.threshold), owner: data.owner, size: data.size});
    await loadLina();
  });
}

function itemDialog(list) {
  const titles = {nursery: 'Wechselkleidung für die Krippe', need: 'Kleidungsbedarf', sort_out: 'Aussortiert'};
  const extra = list === 'need'
    ? `<div class="field"><label for="iu">Wie dringend?</label><select id="iu" name="urgency">${Object.entries(urgencyLabels).map(([k, v]) => `<option value="${k}" ${k === 'season' ? 'selected' : ''}>${v}</option>`).join('')}</select></div>`
    : list === 'sort_out'
      ? `<div class="field"><label for="id">Was passiert damit?</label><select id="id" name="destination">${Object.entries(destinationLabels).map(([k, v]) => `<option value="${k}">${v}</option>`).join('')}</select></div>
         <div class="field"><label for="idt">Details (optional)</label><textarea id="idt" name="details" maxlength="1000" placeholder="Marke, Zustand, Besonderheiten"></textarea></div>`
      : '';
  const hint = list === 'nursery' ? '<p class="note">Die Aufgabe geht an die Person, die Lina als Nächstes bringt.</p>'
    : list === 'need' ? '<p class="note">Britta ist verantwortlich. Dringendes wird zur Aufgabe.</p>' : '';
  dialog(titles[list], 'Lina', `<form>
    <div class="field"><label for="it">Was?</label><input id="it" data-speech name="text" required maxlength="200" placeholder="${list === 'nursery' ? 'z. B. Body und Strumpfhose' : 'z. B. Winterjacke'}"></div>
    <div class="field"><label for="is">Größe (optional)</label><input id="is" name="size" maxlength="40"></div>
    ${extra}${hint}
    <div class="dialog-footer"><button class="btn primary" type="submit">Notieren</button></div></form>`);
  submitForm(modal.querySelector('form'), async data => {
    await api('/lina/items', {list, ...data});
    await loadLina();
  });
}

function vintedText(item) {
  // Only what was entered; nothing is invented or posted automatically.
  return [item.text + (item.size ? ` · Größe ${item.size}` : ''), item.details].filter(Boolean).join('\n\n');
}

function vintedDialog(id) {
  const item = linaState.items.find(i => i.id === Number(id));
  dialog('Text für Vinted', 'Zum Kopieren · wird nicht automatisch veröffentlicht', `
    <textarea class="vinted-text" readonly rows="6">${esc(vintedText(item))}</textarea>
    <p class="note">Enthält nur eure Angaben. Fotos und Preis ergänzt ihr direkt in Vinted.</p>
    <div class="dialog-footer"><button class="btn primary" data-copy-vinted>Kopieren</button></div>`);
  modal.querySelector('[data-copy-vinted]').onclick = async () => {
    try {
      await navigator.clipboard.writeText(vintedText(item));
      toast('Kopiert.');
    } catch (error) {
      modal.querySelector('.vinted-text').select();
      toast('Bitte markierten Text kopieren.');
    }
  };
}

function bindLina() {
  app.querySelectorAll('[data-diaper]').forEach(b => { b.onclick = () => diaperDialog(b.dataset.diaper); });
  app.querySelector('[data-diaper-settings]')?.addEventListener('click', diaperSettingsDialog);
  app.querySelectorAll('[data-lina-new]').forEach(b => { b.onclick = () => itemDialog(b.dataset.linaNew); });
  app.querySelectorAll('[data-vinted]').forEach(b => { b.onclick = () => vintedDialog(b.dataset.vinted); });
  app.querySelectorAll('[data-lina-item]').forEach(b => {
    b.onclick = async () => {
      const item = linaState.items.find(i => i.id === Number(b.dataset.linaItem));
      b.disabled = true;
      try {
        await api('/lina/items/' + item.id, {action: b.dataset.linaAction, version: item.version});
        await loadLina();
        await load();
      } catch (error) {
        toast(error.message);
        b.disabled = false;
      }
    };
  });
}
