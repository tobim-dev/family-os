'use strict';
// Keeps the read-only offline copy on this device current (sw.js, offline.py).
// Stored: last shopping list and active voucher PDFs. Removed on logout.

const OFFLINE_STORE = 'fos-offline-v1';
const OFFLINE_EVERY_MS = 5 * 60 * 1000;
let offlineSavedAt = 0;

function registerOfflineWorker() {
  if ('serviceWorker' in navigator) navigator.serviceWorker.register('/sw.js').catch(() => {});
}

async function refreshOffline(force = false) {
  if (!('caches' in window) || (!force && Date.now() - offlineSavedAt < OFFLINE_EVERY_MS)) return;
  offlineSavedAt = Date.now();
  try {
    const response = await fetch('/api/offline', {headers: {'X-Family-Request': '1'}});
    if (!response.ok) return;
    const data = await response.json();
    const cache = await caches.open(OFFLINE_STORE);
    await cache.put('/api/offline', new Response(JSON.stringify({...data, saved_at: new Date().toISOString()}),
      {headers: {'Content-Type': 'application/json'}}));
    const wanted = new Set(data.vouchers.map(v => `/api/vouchers/${v.id}/pdf`));
    for (const request of await cache.keys()) {
      const path = new URL(request.url).pathname;
      if (/^\/api\/vouchers\/\d+\/pdf$/.test(path) && !wanted.has(path)) await cache.delete(request);
    }
    for (const path of wanted) {
      if (await cache.match(path)) continue;
      const pdf = await fetch(path);
      if (pdf.ok) await cache.put(path, pdf);
    }
  } catch (error) {
    // Offline or storage full: the previous copy stays as it is.
  }
}

async function clearOffline() {
  offlineSavedAt = 0;
  try {
    if ('caches' in window) await caches.delete(OFFLINE_STORE);
  } catch (error) {
    // Nothing stored.
  }
}
