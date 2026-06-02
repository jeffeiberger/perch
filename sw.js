// Perch by Parliament Trucking — Service Worker
const CACHE = 'perch-v4';
const PRECACHE = ['/perch/', '/perch/index.html', '/perch/manifest.json', '/perch/sw.js'];

self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(CACHE).then(c => c.addAll(PRECACHE).catch(() => {}))
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
  const url = e.request.url;

  // Always network for data.json — never cache
  if (url.includes('data.json')) {
    e.respondWith(fetch(e.request));
    return;
  }

  // Network-first for HTML so updates always come through immediately
  if (e.request.destination === 'document' || url.endsWith('.html')) {
    e.respondWith(
      fetch(e.request)
        .then(resp => {
          const clone = resp.clone();
          caches.open(CACHE).then(c => c.put(e.request, clone));
          return resp;
        })
        .catch(() => caches.match(e.request))
    );
    return;
  }

  // Network-first for fonts
  if (url.includes('fonts.gstatic') || url.includes('fonts.googleapis')) {
    e.respondWith(fetch(e.request).catch(() => caches.match(e.request)));
    return;
  }

  // Cache-first for everything else (images, js, css)
  e.respondWith(
    caches.match(e.request).then(cached => cached || fetch(e.request))
  );
});
