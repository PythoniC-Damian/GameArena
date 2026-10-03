/* Public static assets only. Never cache session-dependent pages or APIs. */
const CACHE_NAME = 'gamearena-v5';
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
self.addEventListener('push', event => {
  let data;
  try { data = event.data.json(); } catch (_) { data = {body:'You have a new GameArena update.'}; }
  let url = '/notifications';
  try { const target = new URL(data.url, self.location.origin); if (target.origin === self.location.origin) url = target.pathname + target.search; } catch (_) {}
  event.waitUntil(self.registration.showNotification(data.title || 'GameArena', {
    body:data.body || 'You have a new update.', icon:'/static/icons/icon-192.png',
    badge:'/static/icons/icon-192.png', tag:`gamearena-${data.id || 'update'}`, data:{url}
  }));
});
self.addEventListener('notificationclick', event => {
  event.notification.close();
  const url = new URL(event.notification.data?.url || '/notifications', self.location.origin);
  if (url.origin !== self.location.origin) return;
  event.waitUntil(self.clients.matchAll({type:'window',includeUncontrolled:true}).then(async clients => {
    const client = clients.find(item => new URL(item.url).origin === self.location.origin);
    if (client) { await client.navigate(url.href); return client.focus(); }
    return self.clients.openWindow(url.href);
  }));
});
