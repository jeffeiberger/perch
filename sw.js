const CACHE = 'coldchain-v2';
const PRECACHE = ['/', '/index.html', '/manifest.json', '/sw.js'];

self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(CACHE).then(c => c.addAll(PRECACHE))
  );
  self.skipWaiting();
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', e => {
  // Never cache data.json — always fetch fresh
  if (e.request.url.includes('data.json')) {
    e.respondWith(fetch(e.request));
    return;
  }
  // Network-first for fonts
  if (e.request.url.includes('fonts.gstatic')) {
    e.respondWith(fetch(e.request).catch(() => caches.match(e.request)));
    return;
  }
  // Cache-first for everything else (app shell)
  e.respondWith(
    caches.match(e.request).then(cached => cached || fetch(e.request))
  );
});
