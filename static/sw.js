/* GameArena Service Worker
   Provides offline caching and enables installability as a PWA. */

const CACHE_NAME = 'gamearena-v3';

// App shell assets to cache for offline/instant loading
const APP_SHELL = [
  '/static/manifest.json',
  '/static/icons/icon-192.png',
  '/static/icons/icon-512.png',
  '/static/icons/icon-512-maskable.png'
];

// Install: cache the app shell
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then((cache) => cache.addAll(APP_SHELL))
      .then(() => self.skipWaiting())
  );
});

// Activate: clean up old caches
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys
          .filter((key) => key !== CACHE_NAME)
          .map((key) => caches.delete(key))
      )
    ).then(() => self.clients.claim())
  );
});

function isCacheableStaticAsset(url) {
  if (url.origin !== self.location.origin || !url.pathname.startsWith('/static/')) return false;
  if (url.pathname.endsWith('/sw.js') || url.pathname.endsWith('/manifest.json')) return false;
  return /\.(?:css|js|mjs|png|jpe?g|webp|avif|gif|svg|ico|woff2?|ttf|otf)$/i.test(url.pathname);
}

// Fetch: cache only safe, same-origin static assets. HTML pages and APIs may
// vary by session, so they must never enter Cache Storage, which is shared by
// all signed-in users of this browser profile.
self.addEventListener('fetch', (event) => {
  const { request } = event;

  // Only handle GET requests
  if (request.method !== 'GET') return;

  const url = new URL(request.url);

  if (!isCacheableStaticAsset(url)) return;

  // Static assets use stale-while-revalidate.
  event.respondWith(
    caches.match(request).then((cached) => {
      const networkFetch = fetch(request)
        .then((response) => {
          if (response && response.status === 200) {
            const copy = response.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(request, copy));
          }
          return response;
        })
        .catch(() => cached);
      return cached || networkFetch;
    })
  );
});
