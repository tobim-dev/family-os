'use strict';
let mealState=null,mealStart=null,mealLoading=false;
function mealWeek(value=new Date()){const d=new Date(value);d.setHours(12,0,0,0);d.setDate(d.getDate()-((d.getDay()+1)%7));return iso(d);}
// Recipe previews are served by the NAS (/api/meals/image/…); the browser never
// contacts the Cookidoo CDN. Missing or failed images fall back to a neutral tile.
function recipeImage(src, size = '') {
  const tile = `<div class="recipe-thumb placeholder ${size}" aria-hidden="true">${icon('meal')}</div>`;
  return src ? `<img class="recipe-thumb ${size}" src="${esc(src)}" alt="" loading="lazy" decoding="async">` : tile;
}
globalThis.document?.addEventListener('error', event => {
  const img = event.target;
  if (img?.tagName === 'IMG' && img.classList.contains('recipe-thumb')) {
    const tile = document.createElement('div');
    tile.className = img.className + ' placeholder';
    tile.setAttribute('aria-hidden', 'true');
    tile.innerHTML = icon('meal');
    img.replaceWith(tile);
  }
}, true);
function recipeURL(id){return /^r\d+$/.test(id)?'https://cookidoo.de/recipes/recipe/de-DE/'+id:null;}
async function loadMeals(){if(mealLoading)return;mealLoading=true;try{const vouchers=typeof loadVouchers==='function'?loadVouchers():null;mealState=await api('/meals?start='+mealStart);await vouchers;if(view==='meals'&&state)render();}catch(e){toast(e.message);}finally{mealLoading=false;}}
function mealsHTML(){
  if(!mealState)return '<section class="panel"><div class="empty-state">Essensplanung wird geladen …</div></section>';
  const m=mealState,s=m.snapshot,end=dateObj(mealStart);end.setDate(end.getDate()+6);
  const reviews=m.reviews.map(r=>`<div class="error-banner"><b>Cookidoo-Vorgang prüfen</b><p>${esc(r.message||'Übertragung läuft; bitte abwarten.')}</p>${r.state==='review'?`<button class="btn" data-meal-review="${esc(r.id)}">Ich prüfe den Stand</button>`:''}</div>`).join('');
  const status=m.demo?'Beispielwoche · keine Cookidoo-Verbindung':m.updated?'Letzter Abgleich: '+deadlineText(new Date(m.updated*1000).toISOString()):'Noch kein Abgleich';
  const items=s?[...s.ingredients.map(i=>({...i,group:'ingredient'})),...s.additional.map(i=>({...i,group:'additional'}))]:[];
  const duplicateIds=s?.duplicate_ids||{};
  const ambiguous=i=>(duplicateIds[i.group==='ingredient'?'ingredients':'additional']||[]).includes(i.id);
  const ambiguityNotice=Object.values(duplicateIds).some(ids=>ids.length)?'<div class="note">Cookidoo liefert einige Kennungen mehrfach. Alle Positionen und Mengen bleiben sichtbar. Markierte Artikel bitte direkt in Cookidoo abhaken. Rezeptzutaten lassen sich weiter hinzufügen und entfernen; jede Änderung wird Position für Position nachgezählt.</div>':'';
  const open=items.filter(i=>!i.is_owned),done=items.filter(i=>i.is_owned);
  const itemHTML=i=>`<div class="list-row meal-item"><input type="checkbox" aria-label="${esc(i.name)} als ${i.is_owned?'noch benötigt':'vorhanden oder gekauft'} markieren" data-shop-item="${esc(i.id)}" data-shop-group="${i.group}" ${i.is_owned?'checked':''} ${m.demo||ambiguous(i)?'disabled':''}><div><b class="${i.is_owned?'done':''}">${esc(i.name)}</b><p>${esc(i.description||'Eigener Einkaufsartikel')}</p>${ambiguous(i)?'<small>Mehrfache Kennung · bitte in Cookidoo abhaken</small>':''}</div></div>`;
  return `${reviews}${ambiguityNotice}${m.error?`<div class="error-banner">${esc(m.error)}</div>`:''}<div class="meal-toolbar"><div><b>Samstag bis Freitag</b><p>${fmt(mealStart)} – ${fmt(iso(end))}</p><small>${status}</small></div><div class="actions"><a class="btn" href="#meal-shopping">Zur Einkaufsliste</a><button class="btn" data-meal-week="-7" aria-label="Vorherige Essenswoche">${icon('left')}</button><button class="btn" data-meal-week="7" aria-label="Nächste Essenswoche">${icon('arrow')}</button>${s||m.demo?`<button class="btn primary" data-meal-suggest>${icon('meal')}Woche vorschlagen</button>`:''}${!m.demo&&m.connected?'<button class="btn" data-meal-sync>Mit Cookidoo abgleichen</button>':''}${!m.demo&&state.user==='tobi'?`<button class="btn ${m.connected?'':'primary'}" data-meal-connect>${m.connected?'Zugang erneuern':'Cookidoo verbinden'}</button>`:''}</div></div><div class="content-grid"><div class="stack">${suggestionHTML(m)}<section class="panel"><div class="panel-head"><h2>Was essen wir diese Woche?</h2></div>${s?s.days.map(d=>`<div class="meal-day"><div><strong>${fmt(d.day,{weekday:'long'})}</strong><small>${fmt(d.day,{day:'numeric',month:'short'})}</small></div><div>${d.recipes.map(r=>`<div class="meal-recipe">${recipeImage(m.images?.[r.id])}<div class="meal-recipe-body"><h3>${esc(r.name)}</h3><small>${r.total_time?Math.round(r.total_time/60)+' Min. Gesamtzeit':''}</small><div class="actions">${recipeURL(r.id)?`<a class="btn ghost" href="${recipeURL(r.id)}" target="_blank" rel="noopener noreferrer">In Cookidoo öffnen</a>`:''}${!m.demo?`<button class="btn ghost" data-meal-remove="${esc(r.id)}" data-meal-day="${d.day}">Aus diesem Tag entfernen</button>`:''}</div></div></div>`).join('')}${d.custom_ids.length?'<p class="note">Eigene Cookidoo-Rezepte vorhanden. Bitte direkt in Cookidoo bearbeiten.</p>':''}${!d.recipes.length&&!d.custom_ids.length?`<p class="muted">Noch kein Abendessen geplant.</p>${!m.demo?`<button class="btn" data-meal-search="${d.day}">${icon('plus')}Rezept auswählen</button>`:''}`:''}</div></div>`).join(''):`<div class="empty-state"><b>${m.connected?'Diese Woche wurde noch nicht geladen.':'Verbindet zuerst euren Cookidoo-Zugang.'}</b><p>${m.connected?'Bitte mit Cookidoo abgleichen.':'Danach erscheinen „Meine Woche“ und eure Einkaufsliste hier.'}</p></div>`}</section>${s?`<section class="panel"><div class="panel-head"><h2>Rezepte für den Einkauf</h2></div>${weekSwitchSummary(m)}<div class="panel-body"><p>Für diese Woche geplante Rezepte gezielt hinzufügen. Bereits enthaltene Rezepte werden nicht erneut hinzugefügt.</p>${[...new Map(s.days.flatMap(d=>d.recipes).map(r=>[r.id,r])).values()].map(r=>`<div class="row between meal-shopping-recipe"><span>${esc(r.name)}</span>${s.shopping_recipes.some(x=>x.id===r.id)?'<span class="status">Auf der Einkaufsliste</span>':m.demo?'<span class="status gray">Beispiel</span>':`<button class="btn" data-meal-ingredients="${esc(r.id)}">Zutaten hinzufügen</button>`}</div>`).join('')}</div></section>`:''}</div><aside class="rail">${typeof vouchersPanel==='function'?vouchersPanel():''}<section class="panel"><div class="panel-head"><h2>Euer Rahmen</h2></div><div class="panel-body"><p>Vegetarisch, gerne proteinreich. Unter der Woche möglichst bis 45 Minuten Gesamtzeit. Die üblichen vier Portionen reichen für euch drei.</p><p class="note">Suche und Originalzutaten helfen bei der Auswahl. Suchbegriffe sind keine verlässliche Ernährungskennzeichnung; bitte die vegetarische Eignung prüfen. Portionsmengen werden unverändert aus Cookidoo übernommen.</p></div></section><section class="panel" id="meal-shopping"><div class="panel-head"><h2>Einkaufsliste</h2><span class="status amber">${open.length} offen</span></div>${s?`<div class="panel-body"><div class="actions">${!m.demo?'<button class="btn" data-shop-add>Artikel ergänzen</button>':''}<a class="btn" href="/api/meals/shopping.html" download>Offline-Kopie speichern</a></div><p class="small">${m.demo?'Vorschau mit Beispieldaten.':'Häkchen werden gezielt mit Cookidoo abgeglichen.'} Die Offline-Kopie vor dem Einkauf auf dem iPhone speichern; Änderungen daran bleiben in der Kopie.</p></div>${open.map(itemHTML).join('')||'<div class="empty-state">Aktuell nichts offen.</div>'}${done.length?`<details class="meal-done"><summary>Vorhanden / gekauft (${done.length})</summary>${done.map(itemHTML).join('')}</details>`:''}${s.shopping_recipes.length?`<details class="meal-done"><summary>Enthaltene Rezepte (${s.shopping_recipes.length})</summary>${s.shopping_recipes.map(r=>`<div class="list-row"><div><b>${esc(r.name)}</b>${!m.demo&&/^r\d+$/.test(r.id)?`<div class="actions"><button class="btn ghost" data-shop-remove-recipe="${esc(r.id)}">Diese Rezeptzutaten entfernen</button></div>`:''}</div></div>`).join('')}</details>`:''}`:'<div class="empty-state">Noch keine Einkaufsliste geladen.</div>'}</section></aside></div>`;
}
function mealConnection(){let authenticated=false;dialog('Cookidoo verbinden','Anmeldung bei Cookidoo Deutschland',`<form><p>Die Zugangsdaten werden vom NAS an Cookidoo/Vorwerk übermittelt. Nach der Anmeldung speichert das NAS nur verschlüsselte Zugangstokens. Das Passwort wird nicht dauerhaft gespeichert.</p><div class="field"><label for="cook-email">Cookidoo-E-Mail</label><input id="cook-email" name="email" type="email" required autocomplete="username"></div><div class="field"><label for="cook-password">Cookidoo-Passwort</label><input id="cook-password" name="password" type="password" required autocomplete="current-password" maxlength="512"></div><p class="note">Die Anbindung verwendet die bereits getestete inoffizielle Schnittstelle. Bei einer zusätzlichen Anmeldung oder CAPTCHA bitte direkt Cookidoo verwenden.</p><div class="dialog-footer"><button class="btn primary" type="submit">Verbinden und Planung laden</button></div></form>`);mealSubmit(modal.querySelector('form'),async data=>{if(!authenticated){await api('/meals/connect',data);authenticated=true;modal.querySelector('#cook-password').value='';modal.querySelector('#cook-password').disabled=true;modal.querySelector('#cook-email').disabled=true;}modal.querySelector('[type=submit]').textContent='Angemeldet · Planung wird geladen …';try{return await api('/meals/sync',{start:mealStart});}catch(e){modal.querySelector('[type=submit]').textContent='Planung erneut laden';throw new Error('Die Anmeldung wurde bestätigt, aber die Planung konnte noch nicht geladen werden. '+e.message);}});}
function mealSubmit(form,operation){form.onsubmit=async e=>{e.preventDefault();const b=form.querySelector('[type=submit]');b.disabled=true;try{await operation(Object.fromEntries(new FormData(form)));modal.close();await loadMeals();toast('Mit Cookidoo abgeglichen.');}catch(error){formError(form,error.message);b.disabled=false;await loadMeals();}};}
function mealChangeDialog(title,description,fields){const id=crypto.randomUUID(),rev=mealState.revision,start=mealStart;dialog(title,'Änderung in eurem Cookidoo-Konto',`<form><p>${esc(description)}</p><p class="note">Die Änderung wird anschließend aus Cookidoo zurückgelesen. Der anschließende Abgleich prüft auch, ob eure eigenen Einkaufsartikel erhalten geblieben sind.</p><div class="dialog-footer"><button class="btn primary" type="submit">${fields.action==='ingredients_add'?'Zutaten hinzufügen':fields.action.includes('remove')?'Entfernen':'Speichern'}</button></div></form>`);mealSubmit(modal.querySelector('form'),()=>api('/meals/change',{...fields,id,revision:rev,start}));}
function searchMeals(day){dialog('Abendessen auswählen',fmt(day,{weekday:'long',day:'numeric',month:'long'}),`<form id="recipe-search"><div class="field"><label for="recipe-query">Rezept suchen</label><input id="recipe-query" name="query" value="vegetarisch Linsen" minlength="2" required maxlength="120"></div><div class="field"><label for="recipe-minutes">Maximale Gesamtzeit</label><select id="recipe-minutes" name="max_minutes"><option value="45">45 Minuten</option><option value="60">60 Minuten</option><option value="90">90 Minuten</option></select></div><button class="btn primary" type="submit">In Cookidoo suchen</button></form><p class="note">Zum Beispiel: vegetarisch, Kichererbsen, Tofu oder Linsen. Die Suche kennzeichnet keine garantierte vegetarische Eignung.</p><div id="recipe-results"></div>`);const form=modal.querySelector('form');form.onsubmit=async e=>{e.preventDefault();const b=form.querySelector('button');b.disabled=true;try{const data=Object.fromEntries(new FormData(form));const r=await api('/meals/search',{query:data.query,max_minutes:Number(data.max_minutes)});const box=modal.querySelector('#recipe-results');box.innerHTML=r.recipes.length?r.recipes.filter(r=>/^r\d+$/.test(r.id)).map(r=>`<div class="list-row recipe-hit">${recipeImage(r.image,'small')}<div class="grow"><b>${esc(r.name)}</b>${r.total_time?`<small>${Math.round(r.total_time/60)} Min.</small>`:''}</div><button class="btn" data-select-recipe="${esc(r.id)}">Prüfen</button></div>`).join(''):'<p class="note">Keine Treffer. Bitte einen anderen Suchbegriff versuchen.</p>';box.querySelectorAll('[data-select-recipe]').forEach(b=>b.onclick=()=>chooseMeal(day,b.dataset.selectRecipe));}catch(error){formError(form,error.message);}finally{b.disabled=false;}};}
async function chooseMeal(day,id){try{const r=await api('/meals/recipe/'+id);const requestId=crypto.randomUUID(),rev=mealState.revision,start=mealStart;dialog(esc(r.name),`${r.serving_size} Portionen · ${Math.round(r.total_time/60)} Min. Gesamtzeit`,`${r.image?`<img class="recipe-hero" src="${esc(r.image)}" alt="">`:''}<p>${r.categories.map(esc).join(' · ')}</p><ul class="recipe-ingredients">${r.ingredients.map(i=>`<li>${esc(i.description)} ${esc(i.name)}</li>`).join('')}</ul><p class="note">Bitte vegetarische Eignung und Zeit prüfen. Geplant wird das Originalrezept mit seinen Standardportionen.</p><a class="btn ghost" href="${recipeURL(id)}" target="_blank" rel="noopener noreferrer">Originalrezept öffnen</a><form><div class="dialog-footer"><button class="btn primary" type="submit">Für ${fmt(day,{weekday:'long'})} einplanen</button></div></form>`);mealSubmit(modal.querySelector('form'),()=>api('/meals/change',{id:requestId,revision:rev,start,action:'plan_add',day,recipe_id:id}));}catch(e){toast(e.message);}}
function bindMeals(){
  bindSuggestions();
  if (typeof bindVouchers === 'function') bindVouchers();
  bindWeekSwitch();
  app.querySelectorAll('[data-meal-week]').forEach(b=>b.onclick=async()=>{if(mealLoading)return;const d=dateObj(mealStart);d.setDate(d.getDate()+Number(b.dataset.mealWeek));mealStart=iso(d);mealState=null;render();await loadMeals();if(mealState?.connected&&!mealState.snapshot){try{await api('/meals/sync',{start:mealStart});await loadMeals();}catch(e){toast(e.message);}}});
  app.querySelector('[data-meal-connect]')?.addEventListener('click',mealConnection);
  app.querySelector('[data-meal-sync]')?.addEventListener('click',async e=>{e.currentTarget.disabled=true;try{await api('/meals/sync',{start:mealStart});await loadMeals();toast('Cookidoo-Stand aktualisiert.');}catch(error){toast(error.message);render();}});
  app.querySelectorAll('[data-meal-search]').forEach(b=>b.onclick=()=>searchMeals(b.dataset.mealSearch));
  app.querySelectorAll('[data-meal-remove]').forEach(b=>b.onclick=()=>mealChangeDialog('Rezept aus dem Tag entfernen','Nur diese Rezeptzuordnung wird aus dem gewählten Tag entfernt. Bereits hinzugefügte Einkaufszutaten bleiben erhalten.',{action:'plan_remove',recipe_id:b.dataset.mealRemove,day:b.dataset.mealDay}));
  app.querySelectorAll('[data-meal-ingredients]').forEach(b=>b.onclick=()=>mealChangeDialog('Zutaten zum Einkauf hinzufügen','Die Standardzutaten dieses Rezepts werden ergänzt. Bereits vorhandene Rezeptzutaten und eigene Einkaufsartikel werden nicht geleert.',{action:'ingredients_add',recipe_id:b.dataset.mealIngredients}));
  app.querySelectorAll('[data-shop-remove-recipe]').forEach(b=>b.onclick=()=>mealChangeDialog('Rezeptzutaten entfernen','Die Zutaten dieses Rezepts werden aus der Einkaufsliste entfernt. Bitte prüfen, ob ihr das Rezept noch einkaufen wollt.',{action:'ingredients_remove',recipe_id:b.dataset.shopRemoveRecipe}));
  app.querySelectorAll('[data-shop-item]').forEach(b=>b.onchange=async()=>{const wanted=b.checked;b.disabled=true;try{await api('/meals/change',{id:crypto.randomUUID(),start:mealStart,revision:mealState.revision,action:'check_'+b.dataset.shopGroup,item_id:b.dataset.shopItem,owned:wanted});await loadMeals();}catch(e){b.checked=!wanted;b.disabled=false;toast(e.message);await loadMeals();}});
  app.querySelector('[data-shop-add]')?.addEventListener('click',()=>{const id=crypto.randomUUID(),rev=mealState.revision,start=mealStart;dialog('Einkaufsartikel ergänzen','Für Frühstück, Haushalt oder spontane Wünsche',`<form><div class="field"><label for="shop-name">Artikel</label><input id="shop-name" data-speech name="name" required maxlength="200" placeholder="Zum Beispiel Haferflocken"></div><div class="dialog-footer"><button type="submit" class="btn primary">Zu Cookidoo hinzufügen</button></div></form>`);mealSubmit(modal.querySelector('form'),data=>api('/meals/change',{...data,id,revision:rev,start,action:'additional_add'}));});
  app.querySelectorAll('[data-meal-review]').forEach(b=>b.onclick=()=>{dialog('Unklaren Vorgang prüfen','Bitte zuerst Cookidoo direkt öffnen.',`<p>Prüft dort, ob die gewünschte Änderung angekommen ist und ob die übrigen Einträge stimmen. Dieser Knopf liest den aktuellen Stand neu ein und schließt euren Prüfhinweis. Er wiederholt keine Änderung.</p><form><div class="dialog-footer"><button class="btn primary" type="submit">In Cookidoo geprüft · neu abgleichen</button></div></form>`);mealSubmit(modal.querySelector('form'),()=>api('/meals/review/'+b.dataset.mealReview,{}));});
}

// --- Automatic weekly suggestions -------------------------------------------
// Hard rules are checked on the NAS; Claude (optional) only picks from
// prepared candidates. Nothing is written to Cookidoo without a click here.

let suggesting = false;

function vegLabel(veg) {
  return veg === 'ok' ? 'In Cookidoo als vegetarisch gekennzeichnet' : 'Keine Fleisch- oder Fischzutat gefunden · bitte prüfen';
}

function suggestionHTML(m) {
  const suggestion = m.suggestion;
  if (suggesting) {
    return '<section class="panel suggestion"><div class="empty-state"><b>Vorschlag wird erstellt …</b><p>Cookidoo wird durchsucht und geprüft. Das kann bis zu einer Minute dauern.</p></div></section>';
  }
  if (!suggestion || suggestion.start !== mealStart) return '';
  const planned = new Set((m.snapshot?.days || []).filter(d => d.recipes.length || d.custom_ids.length).map(d => d.day));
  const open = suggestion.days.filter(d => d.recipe && !planned.has(d.day));
  const source = suggestion.source === 'claude' ? 'Ausgewählt mit Claude' : 'Lokal auf dem NAS ausgewählt';
  const rows = suggestion.days.map(d => {
    const done = planned.has(d.day);
    const r = d.recipe;
    const head = `<div><strong>${fmt(d.day, {weekday: 'long'})}</strong><small>bis ${d.max_minutes} Min.</small></div>`;
    if (!r) return `<div class="meal-day">${head}<p class="muted">Kein passender Kandidat gefunden.</p></div>`;
    const facts = [Math.round(r.total_time / 60) + ' Min.', r.protein ? r.protein + ' g Eiweiß' : null].filter(Boolean).join(' · ');
    return `<div class="meal-day ${done ? 'suggestion-done' : ''}">${head}<div class="meal-recipe">${recipeImage(r.image)}<div class="meal-recipe-body">
      <h3>${esc(r.name)}</h3><small>${facts}</small>
      <small class="suggestion-reason">${esc(d.reason || '')}${d.source === 'lokal' && suggestion.source === 'claude' ? ' · vom NAS ergänzt' : ''}</small>
      <small class="suggestion-veg ${r.veg}">${vegLabel(r.veg)}</small>
      <div class="actions">${done ? '<span class="status green">Tag ist geplant</span>'
        : !m.demo ? `<button class="btn green" data-suggest-accept="${d.day}">Übernehmen</button>` : ''}
        ${recipeURL(r.id) ? `<a class="btn ghost" href="${recipeURL(r.id)}" target="_blank" rel="noopener noreferrer">In Cookidoo ansehen</a>` : ''}</div>
    </div></div></div>`;
  }).join('');
  return `<section class="panel suggestion"><div class="panel-head"><div><h2>Vorschlag für diese Woche</h2><p>${source}${suggestion.model ? ' · ' + esc(suggestion.model) : ''}</p></div>
      <span class="status ${suggestion.source === 'claude' ? 'green' : 'gray'}">Vorschlag</span></div>
    ${suggestion.notice ? `<div class="note suggestion-note">${esc(suggestion.notice)}</div>` : ''}
    ${rows}
    <div class="calendar-foot"><small>Noch nichts in Cookidoo geändert. Erst „Übernehmen“ plant das Rezept in „Meine Woche“.</small>
      <div class="actions">${suggestion.sent ? '<button class="btn ghost" data-suggest-sent>Gesendete Daten</button>' : ''}
        <button class="btn" data-meal-suggest>Neu vorschlagen</button>
        ${open.length > 1 && !m.demo ? `<button class="btn green" data-suggest-accept-all>Alle ${open.length} übernehmen</button>` : ''}</div></div>
  </section>`;
}

function suggestDialog() {
  const ai = mealState.ai || {};
  const used = ai.usage?.calls || 0;
  dialog('Woche vorschlagen', 'Vegetarisch, gern eiweißreich, ohne Wiederholung der letzten vier Wochen', `<form>
    <div class="field-pair">
      <div class="field"><label for="sg-week">Mo–Fr höchstens</label><select id="sg-week" name="weekday_minutes">${[30, 45, 60].map(v => `<option value="${v}" ${v === 45 ? 'selected' : ''}>${v} Minuten</option>`).join('')}</select></div>
      <div class="field"><label for="sg-weekend">Sa/So höchstens</label><select id="sg-weekend" name="weekend_minutes">${[45, 60, 90, 120].map(v => `<option value="${v}" ${v === 90 ? 'selected' : ''}>${v} Minuten</option>`).join('')}</select></div>
    </div>
    <div class="field"><label for="sg-wishes">Lust auf … (optional)</label><input id="sg-wishes" name="wishes" maxlength="120" placeholder="z. B. Kürbis, Pasta"><small>Nur als Cookidoo-Suchbegriffe, wird nicht an Claude gesendet.</small></div>
    <label class="choice"><input type="checkbox" name="use_ai" ${ai.ai_available ? 'checked' : 'disabled'}> Mit Claude eine abwechslungsreiche Woche auswählen</label>
    <p class="note">${ai.ai_available
      ? `An Claude gehen nur Wochentag und Zeitgrenze sowie je Kandidat eine anonyme Nummer, Rezeptname, Minuten, Eiweiß und Zutatennamen. Keine Namen, Daten, Konten oder Verläufe. Diesen Monat: ${used} von ${ai.monthly_calls} Anfragen.`
      : 'Kein Claude-Schlüssel hinterlegt: Der NAS wählt lokal nach Eiweiß und Abwechslung aus.'}</p>
    <div class="dialog-footer"><button class="btn primary" type="submit">Vorschlag erstellen</button></div>
  </form>`);
  const form = modal.querySelector('form');
  form.onsubmit = async event => {
    event.preventDefault();
    const data = Object.fromEntries(new FormData(form));
    modal.close();
    suggesting = true;
    render();
    try {
      const result = await api('/meals/suggest', {start: mealStart, weekday_minutes: Number(data.weekday_minutes),
        weekend_minutes: Number(data.weekend_minutes), wishes: data.wishes || '', use_ai: data.use_ai === 'on'});
      mealState = {...mealState, suggestion: result};
      toast(result.source === 'claude' ? 'Vorschlag mit Claude erstellt.' : 'Vorschlag erstellt.');
    } catch (error) {
      toast(error.message);
    } finally {
      suggesting = false;
      await loadMeals();
      render();
    }
  };
}

async function acceptSuggestion(days) {
  const byDay = Object.fromEntries(mealState.suggestion.days.map(d => [d.day, d]));
  let done = 0;
  for (const day of days) {
    try {
      // Each write re-reads Cookidoo and uses the latest revision (parallel-change protection).
      mealState = await api('/meals/change', {id: crypto.randomUUID(), revision: mealState.revision, start: mealStart,
        action: 'plan_add', day, recipe_id: byDay[day].recipe.id});
      done++;
    } catch (error) {
      toast(`${fmt(day, {weekday: 'long'})}: ${error.message}`);
      break;
    }
  }
  await loadMeals();
  render();
  if (done) toast(done === 1 ? 'Rezept in Cookidoo eingeplant.' : `${done} Rezepte in Cookidoo eingeplant.`);
}

function bindSuggestions() {
  app.querySelectorAll('[data-meal-suggest]').forEach(b => { b.onclick = suggestDialog; });
  app.querySelectorAll('[data-suggest-accept]').forEach(b => {
    b.onclick = () => { b.disabled = true; acceptSuggestion([b.dataset.suggestAccept]); };
  });
  const all = app.querySelector('[data-suggest-accept-all]');
  if (all) {
    all.onclick = () => {
      const planned = new Set(mealState.snapshot.days.filter(d => d.recipes.length || d.custom_ids.length).map(d => d.day));
      const days = mealState.suggestion.days.filter(d => d.recipe && !planned.has(d.day)).map(d => d.day);
      dialog('Alle Vorschläge übernehmen', `${days.length} Abende in Cookidoo „Meine Woche“`, `<form>
        <p>Die Rezepte werden nacheinander eingeplant. Jeder Schritt prüft vorher den aktuellen Cookidoo-Stand; bei einer Abweichung wird angehalten.</p>
        <div class="dialog-footer"><button class="btn green" type="submit">Übernehmen</button></div></form>`);
      modal.querySelector('form').onsubmit = event => { event.preventDefault(); modal.close(); acceptSuggestion(days); };
    };
  }
  app.querySelector('[data-suggest-sent]')?.addEventListener('click', () => {
    dialog('An Claude gesendete Daten', 'Genau dieser Inhalt hat den NAS verlassen', `<pre class="sent-data">${esc(JSON.stringify(mealState.suggestion.sent, null, 2))}</pre>`);
  });
}

// --- Guided week change of the shopping list (E-09, E-10, E-16) -------------
// The server prepares the preview (week_switch); nothing changes before the
// click. Cookidoo removes ingredients per recipe only. Each step is a single
// verified change with a fresh revision; the first failure stops the run.

function weekSwitchSummary(m) {
  const plan = m.week_switch;
  if (m.demo || !plan || plan.start !== mealStart) return '';
  if (!plan.remove.length && !plan.add.length) {
    return '<div class="panel-body week-switch"><span class="status green">Einkaufsliste passt zu dieser Woche</span></div>';
  }
  const parts = [];
  if (plan.remove.length) parts.push(`${plan.remove.length} ${plan.remove.length === 1 ? 'altes Rezept' : 'alte Rezepte'} entfernen`);
  if (plan.add.length) parts.push(`${plan.add.length} ${plan.add.length === 1 ? 'Rezept' : 'Rezepte'} hinzufügen`);
  return `<div class="panel-body week-switch">
    <p><b>Wochenwechsel:</b> ${parts.join(' · ')}. Eigene Artikel bleiben unverändert.</p>
    <div class="actions"><button class="btn primary" data-week-switch>Einkaufsliste für diese Woche vorbereiten</button></div>
  </div>`;
}

function weekSwitchChoice(name, recipe, detail) {
  return `<label class="choice switch-choice"><input type="checkbox" name="${name}" value="${esc(recipe.id)}" checked>
    <span><b>${esc(recipe.name)}</b>${detail ? `<small>${detail}</small>` : ''}</span></label>`;
}

function weekSwitchDialog() {
  const plan = mealState.week_switch;
  const end = dateObj(mealStart);
  end.setDate(end.getDate() + 6);
  const checkedText = r => r.checked.length
    ? `Abgehakt: ${r.checked.map(esc).join(', ')} · wird mit entfernt`
    : '';
  const removeHTML = plan.remove.length
    ? `<fieldset class="field"><legend>Alte Rezepte entfernen</legend>
        <small>Auf der Liste, aber in dieser Woche nicht geplant. Häkchen weg = Rezept bleibt auf der Liste.</small>
        ${plan.remove.map(r => weekSwitchChoice('remove', r, checkedText(r))).join('')}</fieldset>`
    : '';
  const addHTML = plan.add.length
    ? `<fieldset class="field"><legend>Neu hinzufügen</legend>
        <small>In dieser Woche geplant, Zutaten noch nicht auf der Liste. Standardportionen aus Cookidoo.</small>
        ${plan.add.map(r => weekSwitchChoice('add', r, '')).join('')}</fieldset>`
    : '';
  const keepHTML = plan.keep.length
    ? `<p class="small">Bleibt auf der Liste (in dieser Woche geplant): ${plan.keep.map(r => esc(r.name)).join(', ')}</p>`
    : '';
  const manual = plan.manual.map(r => `<li>${esc(r.name)} · ${esc(r.reason)}</li>`);
  if (plan.custom_planned) {
    manual.push(`<li>${plan.custom_planned} eigene${plan.custom_planned === 1 ? 's' : ''} Cookidoo-Rezept${plan.custom_planned === 1 ? '' : 'e'} in dieser Woche · Zutaten bitte direkt in Cookidoo ergänzen</li>`);
  }
  const manualHTML = manual.length
    ? `<div class="note"><b>Nicht automatisch:</b><ul class="switch-manual">${manual.join('')}</ul></div>`
    : '';
  dialog('Einkaufsliste vorbereiten', `${fmt(mealStart)} – ${fmt(iso(end))}`, `<form>
    ${removeHTML}${addHTML}${keepHTML}${manualHTML}
    <p class="note">Eigene Artikel (${plan.own_items}, davon ${plan.own_checked} abgehakt) bleiben unverändert.
      Zutaten, die ein verbleibendes Rezept ebenfalls braucht, bleiben erhalten. Vor und nach jedem Schritt
      wird Cookidoo gelesen und nachgezählt; bei einer Abweichung hält der Wechsel an.</p>
    <div class="dialog-footer"><button class="btn primary" type="submit">Wochenwechsel starten</button></div>
  </form>`);
  const form = modal.querySelector('form');
  form.onsubmit = async event => {
    event.preventDefault();
    const steps = weekSwitchSteps(new FormData(form), plan);
    if (!steps.length) {
      formError(form, 'Bitte mindestens ein Rezept auswählen.');
      return;
    }
    const button = form.querySelector('[type=submit]');
    button.disabled = true;
    form.querySelectorAll('input').forEach(input => { input.disabled = true; });
    const result = await runWeekSwitch(steps, index => {
      button.textContent = `Schritt ${index + 1} von ${steps.length} …`;
    });
    await loadMeals();
    if (result.error) {
      const done = result.done ? ` ${result.done} von ${steps.length} Schritten sind erledigt.` : '';
      button.textContent = 'Angehalten';
      formError(form, `Angehalten bei „${result.failed.name}“: ${result.error.message}${done} Nach der Prüfung zeigt „Einkaufsliste für diese Woche vorbereiten“ den verbleibenden Rest.`);
      return;
    }
    weekSwitchDone(steps.length);
  };
}

function weekSwitchSteps(data, plan) {
  const names = Object.fromEntries([...plan.remove, ...plan.add].map(r => [r.id, r.name]));
  // Remove first, so shared ingredients are counted against the new week only.
  return [
    ...data.getAll('remove').map(id => ({action: 'ingredients_remove', id, name: names[id]})),
    ...data.getAll('add').map(id => ({action: 'ingredients_add', id, name: names[id]})),
  ];
}

async function runWeekSwitch(steps, onStep = () => {}) {
  for (const [index, step] of steps.entries()) {
    onStep(index, step);
    try {
      // Every step re-reads Cookidoo and uses the latest revision.
      mealState = await api('/meals/change', {id: crypto.randomUUID(), revision: mealState.revision,
        start: mealStart, action: step.action, recipe_id: step.id});
    } catch (error) {
      return {done: index, failed: step, error};
    }
  }
  return {done: steps.length};
}

function weekSwitchDone(count) {
  dialog('Einkaufsliste vorbereitet', `${count} ${count === 1 ? 'Änderung' : 'Änderungen'} in Cookidoo bestätigt`, `
    <p>Nächster Schritt: Vorräte zuhause durchgehen und alles abhaken, was schon da ist. Übrig bleibt, was ihr einkaufen müsst.</p>
    <div class="dialog-footer"><a class="btn primary" href="#meal-shopping" data-close-to-list>Zur Einkaufsliste</a></div>`);
  modal.querySelector('[data-close-to-list]').onclick = () => modal.close();
  toast('Einkaufsliste für diese Woche vorbereitet.');
}

function bindWeekSwitch() {
  app.querySelector('[data-week-switch]')?.addEventListener('click', weekSwitchDialog);
}
