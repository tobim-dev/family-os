const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');

// Elements toggled with the hidden attribute must disappear even if their
// class sets a display value (e.g. .btn{display:inline-flex}).
test('hidden attribute wins over display rules', () => {
  const css = fs.readFileSync('static/style.css', 'utf8');
  assert.match(css, /(^|[}\s,])\[hidden\]\{display:none!important\}/);
});
