const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');

// Voucher PDFs open in the in-app viewer (data-pdf), never as a plain link
// that replaces the home-screen app without a way back.
test('voucher links open in the in-app viewer', () => {
  for (const file of ['static/vouchers.js', 'static/offline.js']) {
    const source = fs.readFileSync(file, 'utf8');
    const links = [...source.matchAll(/<a [^>]*\/api\/vouchers\/[^>]*>/g)].map(m => m[0]);
    assert.ok(links.length, file);
    for (const link of links) {
      assert.match(link, /data-pdf=/, file);
      assert.doesNotMatch(link, /target="_blank"/, file);
    }
  }
  assert.match(fs.readFileSync('static/index.html', 'utf8'), /pdf-viewer\.js/);
});
