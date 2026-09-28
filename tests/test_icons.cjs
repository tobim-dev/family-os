const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');

// iOS ignores SVG home-screen icons and fills transparency with black, so the
// apple-touch-icon must be an opaque square PNG (colour type 2 = RGB).
function png(path) {
  const data = fs.readFileSync(path);
  assert.equal(data.subarray(1, 4).toString(), 'PNG', path);
  return {width: data.readUInt32BE(16), height: data.readUInt32BE(20), colorType: data[25]};
}

test('app icons are opaque square PNGs in the expected sizes', () => {
  for (const [name, size] of [['apple-touch-icon', 180], ['icon-192', 192], ['icon-512', 512]]) {
    assert.deepEqual(png(`static/icons/${name}.png`), {width: size, height: size, colorType: 2}, name);
  }
});

test('pages and manifest reference the icons', () => {
  for (const page of ['static/index.html', 'static/offline.html']) {
    assert.match(fs.readFileSync(page, 'utf8'), /rel="apple-touch-icon" href="\/static\/icons\/apple-touch-icon.png"/, page);
  }
  const manifest = JSON.parse(fs.readFileSync('static/manifest.webmanifest', 'utf8'));
  const sources = manifest.icons.map(icon => icon.src);
  assert.ok(sources.includes('/static/icons/icon-192.png') && sources.includes('/static/icons/icon-512.png'));
  assert.ok(manifest.icons.some(icon => icon.purpose === 'maskable'));
});
