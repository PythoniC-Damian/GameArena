/* GameArena Service Worker
   Provides offline caching and enables installability as a PWA. */

const CACHE_NAME = 'gamearena-v2';

// App shell assets to cache for offline/instant loading
const APP_SHELL = [
  '/',
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

const PUBLIC_NAVIGATION_PATHS = new Set(['/', '/tournaments', '/leaderboard']);

function isPublicNavigation(url) {
  return PUBLIC_NAVIGATION_PATHS.has(url.pathname) || url.pathname.startsWith('/tournament/');
}

function isSameOriginStaticAsset(url) {
  return url.origin === self.location.origin && url.pathname.startsWith('/static/');
}

// Fetch: cache only public navigation pages and same-origin static assets.
// Authenticated pages, API responses, and payment callbacks must never enter
// Cache Storage: it is not scoped to an individual signed-in user.
self.addEventListener('fetch', (event) => {
  const { request } = event;

  // Only handle GET requests
  if (request.method !== 'GET') return;

  const url = new URL(request.url);

  // For public navigation requests: try network, fall back to cache (offline).
  if (request.mode === 'navigate' && isPublicNavigation(url)) {
    event.respondWith(
      fetch(request)
        .then((response) => {
          if (response && response.ok) {
            const copy = response.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(request, copy));
          }
          return response;
        })
        .catch(() => caches.match(request).then((cached) => cached || caches.match('/')))
    );
    return;
  }

  if (!isSameOriginStaticAsset(url)) return;

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
