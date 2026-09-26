const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

function context(settings, nanny = []) {
  const ctx = vm.createContext({
    names: {tobi: 'Tobi', britta: 'Britta'},
    state: {user: 'britta', nanny},
    esc: v => String(v).replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c])),
    fmt: (day, options) => new Date(day + 'T12:00:00').toLocaleDateString('de-DE', options),
  });
  vm.runInContext(fs.readFileSync('static/nanny.js', 'utf8'), ctx);
  vm.runInContext(`nannyState = ${JSON.stringify({settings})};`, ctx);
  return ctx;
}

test('WhatsApp link uses digits only and encodes the full request text', () => {
  const ctx = context({name: 'Mia', phone: '+49 170 1234567', rate_cents: 2000});
  const shifts = [{day: '2026-10-06', start: '16:00', end: '18:00'}, {day: '2026-10-08', start: '16:00', end: '17:30'}];
  const text = ctx.requestText(shifts);
  assert.match(text, /^Hallo Mia,/);
  assert.match(text, /für Oktober hätten wir gern diese Termine für Lina:/);
  assert.match(text, /falls einzelne Tage nicht gehen/);
  assert.match(text, /– Dienstag, 6\. Oktober, 16:00–18:00 Uhr/);
  assert.match(text, /– Donnerstag, 8\. Oktober, 16:00–17:30 Uhr/);
  assert.match(text, /Britta$/);
  const link = ctx.whatsappLink(text);
  assert.ok(link.startsWith('https://wa.me/491701234567?text='));
  assert.equal(decodeURIComponent(link.split('?text=')[1]), text);
});

test('without a phone number WhatsApp lets the user choose the chat', () => {
  const ctx = context({name: 'Nanny', phone: '', rate_cents: 2000});
  assert.ok(ctx.whatsappLink('Hallo').startsWith('https://wa.me/?text='));
  assert.match(ctx.cancelText({day: '2026-10-06', start: '16:00', end: '18:00'}), /absagen/);
});

test('pickup hint only for requested or confirmed nanny days', () => {
  const nanny = [{day: '2026-10-06', start: '16:00', state: 'confirmed'}, {day: '2026-10-07', start: '16:00', state: 'wish'}];
  const ctx = context({name: 'Nanny', phone: '', rate_cents: 2000}, nanny);
  assert.match(ctx.nannyPickupHint('2026-10-06'), /Nanny ab 16:00 · früher abholen/);
  assert.equal(ctx.nannyPickupHint('2026-10-07'), '');
  assert.equal(ctx.nannyPickupHint('2026-10-09'), '');
});
