'use strict';
// Service worker: push notifications and the read-only offline copy (O-10).
// Only the offline page, the last shopping list (/api/offline) and active
// voucher PDFs are cached. The page script decides what is stored and clears
// it on logout. All other API responses are never cached.

const OFFLINE_CACHE = 'fos-offline-v2';
const SHELL = ['/static/offline.html', '/static/offline.js', '/static/style.css', '/static/favicon.svg'];
// Long enough for a slow start of the NAS; the offline page is for real outages.
const TIMEOUT_MS = 10000;

self.addEventListener('install', event => {
  event.waitUntil(caches.open(OFFLINE_CACHE).then(cache => cache.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', event => {
  event.waitUntil((async () => {
    for (const name of await caches.keys()) {
      if (name.startsWith('fos-offline-') && name !== OFFLINE_CACHE) await caches.delete(name);
    }
    await self.clients.claim();
  })());
});

function cachedCopy(url) {
  return /^\/api\/offline$/.test(url.pathname) || /^\/api\/vouchers\/\d+\/pdf$/.test(url.pathname)
    || SHELL.includes(url.pathname);
}

// Network first. Without a connection, after a timeout or when the reverse
// proxy answers for a stopped NAS (5xx), fall back to the saved copy.
async function networkOr(request, fallback) {
  const cached = () => caches.match(fallback || request, {cacheName: OFFLINE_CACHE, ignoreSearch: true});
  let response;
  try {
    response = await Promise.race([
      fetch(request),
      new Promise((_, reject) => setTimeout(() => reject(new Error('timeout')), TIMEOUT_MS)),
    ]);
  } catch (error) {
    const copy = await cached();
    if (copy) return copy;
    throw error;
  }
  if (response.status >= 500) return (await cached()) || response;
  return response;
}

self.addEventListener('fetch', event => {
  const request = event.request;
  const url = new URL(request.url);
  if (request.method !== 'GET' || url.origin !== self.location.origin) return;
  // Escape hatch from the offline page: "?direkt" always goes to the network.
  if (url.searchParams.has('direkt')) return;
  if (request.mode === 'navigate') {
    event.respondWith(networkOr(request, '/static/offline.html'));
  } else if (cachedCopy(url)) {
    event.respondWith(networkOr(request));
  }
});

self.addEventListener('push', event => {
  let data = {title: 'Family OS', body: 'Eine neue Mitteilung liegt bereit.', tag: 'fos'};
  try { data = {...data, ...event.data.json()}; } catch (_) {}
  event.waitUntil(self.registration.showNotification(data.title,
    {body: data.body, tag: data.tag, icon: '/static/favicon.svg', data: {url: '/'}}));
});

self.addEventListener('notificationclick', event => {
  event.notification.close();
  event.waitUntil((async () => {
    const list = await self.clients.matchAll({type: 'window', includeUncontrolled: true});
    for (const client of list) {
      if (new URL(client.url).origin === self.location.origin) {
        await client.focus();
        return;
      }
    }
    await self.clients.openWindow('/');
  })());
});
