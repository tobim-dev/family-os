const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

// Runs sw.js with a stand-in network and cache.
function worker(network, stored = {}) {
  const listeners = {};
  const context = vm.createContext({
    URL, Promise, setTimeout, Error,
    self: {location: {origin: 'https://fos.test'}, addEventListener: (name, fn) => { listeners[name] = fn; },
           skipWaiting() {}, clients: {claim() {}}},
    fetch: async request => network(request),
    caches: {match: async key => stored[typeof key === 'string' ? key : new URL(key.url).pathname] || undefined},
  });
  vm.runInContext(fs.readFileSync('static/sw.js', 'utf8'), context);
  return async (url, mode = 'cors', method = 'GET') => {
    let result = null;
    listeners.fetch({request: {url: 'https://fos.test' + url, mode, method}, respondWith: r => { result = r; }});
    return result === null ? 'not handled' : await result;
  };
}

test('navigation falls back to the offline page without connection or on 5xx', async () => {
  const offline = worker(async () => { throw new Error('offline'); }, {'/static/offline.html': 'OFFLINE PAGE'});
  assert.equal(await offline('/', 'navigate'), 'OFFLINE PAGE');
  const proxy = worker(async () => ({status: 502}), {'/static/offline.html': 'OFFLINE PAGE'});
  assert.equal(await proxy('/', 'navigate'), 'OFFLINE PAGE');
  const online = worker(async () => ({status: 200, body: 'APP'}), {'/static/offline.html': 'OFFLINE PAGE'});
  assert.equal((await online('/', 'navigate')).body, 'APP');
});

test('only the offline copy and voucher PDFs are served from the cache', async () => {
  const stored = {'/api/offline': 'COPY', '/api/vouchers/3/pdf': 'PDF', '/api/state': 'MUST NOT BE USED'};
  const offline = worker(async () => { throw new Error('offline'); }, stored);
  assert.equal(await offline('/api/offline'), 'COPY');
  assert.equal(await offline('/api/vouchers/3/pdf'), 'PDF');
  assert.equal(await offline('/api/state?month=2026-10'), 'not handled');
  assert.equal(await offline('/api/offline', 'cors', 'POST'), 'not handled');
});

test('an expired session is shown as such and not replaced by the copy', async () => {
  const expired = worker(async () => ({status: 401}), {'/api/offline': 'COPY'});
  assert.equal((await expired('/api/offline')).status, 401);
});

test('without a saved copy the network error is passed on', async () => {
  const empty = worker(async () => { throw new Error('offline'); });
  await assert.rejects(empty('/api/offline'), /offline/);
});

test('"?direkt" always bypasses the offline copy', async () => {
  const offline = worker(async () => { throw new Error('offline'); }, {'/static/offline.html': 'OFFLINE PAGE'});
  assert.equal(await offline('/?direkt=1', 'navigate'), 'not handled');
});

test('sw.js and offline-sync.js use the same cache name', () => {
  const name = /const OFFLINE_CACHE = '([^']+)'/.exec(fs.readFileSync('static/sw.js', 'utf8'))[1];
  assert.match(fs.readFileSync('static/offline-sync.js', 'utf8'), new RegExp(`OFFLINE_STORE = '${name}'`));
});
