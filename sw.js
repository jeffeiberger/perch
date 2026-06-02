// Perch by Parliament Trucking — Service Worker v5
const CACHE = 'perch-v5';

self.addEventListener('install', e => {
  self.skipWaiting();
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.map(k => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', e => {
  const url = e.request.url;

  // Never cache HTML or data.json — always go to network
  if (url.includes('data.json') ||
      e.request.destination === 'document' ||
      url.endsWith('.html')) {
    e.respondWith(fetch(e.request));
    return;
  }

  // Cache-first for fonts and static assets
  e.respondWith(
    caches.match(e.request).then(cached => cached || fetch(e.request))
  );
});
