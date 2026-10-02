/* Public static assets only. Never cache session-dependent pages or APIs. */
const CACHE_NAME = 'gamearena-v4';
const OFFLINE_URL = '/static/offline.html';
const MAX_ENTRIES = 80;
const APP_SHELL = [OFFLINE_URL, '/static/manifest.json', '/static/icons/icon-192.png', '/static/icons/icon-512.png'];
self.addEventListener('install', event => event.waitUntil(caches.open(CACHE_NAME).then(cache => cache.addAll(APP_SHELL)).then(() => self.skipWaiting())));
self.addEventListener('activate', event => event.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(key => key.startsWith('gamearena-') && key !== CACHE_NAME).map(key => caches.delete(key)))).then(() => self.clients.claim())));
function isCacheableStaticAsset(url) {
  return url.origin === self.location.origin && url.pathname.startsWith('/static/') && !url.pathname.endsWith('/sw.js') && !url.pathname.endsWith('/manifest.json') && /\.(?:css|js|mjs|png|jpe?g|webp|avif|gif|svg|ico|woff2?|ttf|otf)$/i.test(url.pathname);
}
async function storeAsset(request, response) {
  const cache = await caches.open(CACHE_NAME);
  await cache.put(request, response);
  const keys = await cache.keys();
  const removable = keys.filter(key => !APP_SHELL.includes(new URL(key.url).pathname));
  while (removable.length > MAX_ENTRIES) await cache.delete(removable.shift());
}
self.addEventListener('fetch', event => {
  const request = event.request;
  if (request.method !== 'GET') return;
  const url = new URL(request.url);
  if (request.mode === 'navigate' && url.origin === self.location.origin) {
    event.respondWith(fetch(request).catch(() => caches.match(OFFLINE_URL)));
    return;
  }
  if (!isCacheableStaticAsset(url)) return;
  // Register lifetime work synchronously so a cached response cannot terminate
  // the worker before its refresh has finished.
  const network = fetch(request);
  event.waitUntil(network.then(response => response.ok ? storeAsset(request, response.clone()) : undefined).catch(() => {}));
  event.respondWith(caches.match(request).then(cached => cached || network));
});
