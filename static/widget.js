'use strict';
// Home-screen widget via Scriptable (A-12): create or revoke the personal
// read-only widget key and copy the ready-made script (key included).

function widgetPanelHTML() {
  return `<section class="panel" data-widget-panel><div class="panel-head"><h2>Widget für den Home-Bildschirm</h2>
      <span class="status" data-widget-status>…</span></div>
    <div class="panel-body"><p>Mit der App „Scriptable“ zeigt ein Widget heute und morgen: Bringen, Abholen, Nanny,
      Abendessen und deine offenen Punkte. Es liest nur und nutzt einen eigenen Schlüssel.</p>
      <p class="small" data-widget-info></p>
      <div class="actions"><button class="btn primary" data-widget-create>Widget einrichten</button>
        <button class="btn" data-widget-revoke hidden>Schlüssel widerrufen</button></div></div></section>`;
}

async function widgetRefresh(panel) {
  try {
    const status = await api('/widget/key');
    const badge = panel.querySelector('[data-widget-status]');
    badge.textContent = status.active ? 'Aktiv' : 'Nicht eingerichtet';
    badge.classList.toggle('amber', !status.active);
    panel.querySelector('[data-widget-info]').textContent = status.active
      ? `Schlüssel seit ${fmt(status.created.slice(0, 10))}` +
        (status.last_used ? `, zuletzt abgerufen ${deadlineText(status.last_used)}.` : ', noch nicht abgerufen.')
      : '';
    panel.querySelector('[data-widget-create]').textContent = status.active ? 'Neuen Schlüssel erstellen' : 'Widget einrichten';
    panel.querySelector('[data-widget-revoke]').hidden = !status.active;
  } catch (error) {
    panel.querySelector('[data-widget-info]').textContent = error.message;
  }
}

async function widgetScript(token) {
  const response = await fetch('/static/scriptable/family-os-widget.js', {cache: 'no-store'});
  if (!response.ok) throw new Error('Die Skriptvorlage konnte nicht geladen werden. Bitte neu laden.');
  const template = await response.text();
  return template.replace('__FOS_ORIGIN__', window.location.origin).replace('__FOS_KEY__', token);
}

function widgetDialog(script) {
  dialog('Widget einrichten', 'Scriptable auf dem iPhone', `<form>
    <ol class="widget-steps">
      <li>„Skript kopieren“ tippen.</li>
      <li>In Scriptable mit „+“ ein neues Skript anlegen, einfügen und „Family OS“ nennen.</li>
      <li>Auf dem Home-Bildschirm ein Scriptable-Widget (klein, mittel oder groß) hinzufügen,
        lange drücken → „Widget bearbeiten“ → Script: „Family OS“.</li>
    </ol>
    <textarea class="widget-script" readonly rows="6" aria-label="Skript">${esc(script)}</textarea>
    <p class="note">Das Skript enthält deinen Schlüssel. Er wird nur jetzt angezeigt. Nicht weitergeben;
      bei Verlust hier widerrufen oder neu erstellen.</p>
    <div class="dialog-footer"><button type="button" class="btn" data-widget-done>Fertig</button>
      <button type="submit" class="btn primary">Skript kopieren</button></div></form>`);
  const form = modal.querySelector('form');
  const area = form.querySelector('textarea');
  form.onsubmit = async event => {
    event.preventDefault();
    try {
      await navigator.clipboard.writeText(script);
      toast('Skript kopiert. Jetzt in Scriptable einfügen.');
    } catch (error) {
      area.focus();
      area.select();
      formError(form, 'Kopieren ging nicht automatisch. Der Text ist markiert – bitte „Kopieren“ wählen.');
    }
  };
  form.querySelector('[data-widget-done]').onclick = () => modal.close();
}

function bindWidget() {
  const panel = app.querySelector('[data-widget-panel]');
  if (!panel) return;
  widgetRefresh(panel);
  panel.querySelector('[data-widget-create]').addEventListener('click', async event => {
    const button = event.currentTarget;
    const replacing = button.textContent.startsWith('Neuen');
    if (replacing && !confirm('Neuen Schlüssel erstellen? Das bisherige Widget zeigt dann nichts mehr an, bis du das neue Skript einfügst.')) return;
    button.disabled = true;
    try {
      const {token} = await api('/widget/key', {});
      widgetDialog(await widgetScript(token));
      widgetRefresh(panel);
    } catch (error) {
      toast(error.message);
    } finally {
      button.disabled = false;
    }
  });
  panel.querySelector('[data-widget-revoke]').addEventListener('click', async () => {
    if (!confirm('Schlüssel widerrufen? Das Widget zeigt danach keine Daten mehr.')) return;
    try {
      await api('/widget/key/revoke', {});
      toast('Widget-Schlüssel widerrufen.');
      widgetRefresh(panel);
    } catch (error) {
      toast(error.message);
    }
  });
}
