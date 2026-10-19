const CACHE = 'program-flow-static-v3';
const ASSETS = ['/', '/static/style.css', '/static/app.js', '/static/icon.svg', '/static/icon-192.png', '/static/icon-512.png', '/static/fonts/NanumGothic-Regular.woff2', '/static/fonts/NanumGothic-Bold.woff2', '/static/fonts/NanumGothic-ExtraBold.woff2'];
self.addEventListener('install', event => event.waitUntil(caches.open(CACHE).then(cache => cache.addAll(ASSETS))));
self.addEventListener('activate', event => event.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(key => key !== CACHE).map(key => caches.delete(key))))));
self.addEventListener('fetch', event => {
  if (event.request.method !== 'GET' || new URL(event.request.url).pathname.startsWith('/api/')) return;
  event.respondWith(fetch(event.request).catch(() => caches.match(event.request)));
});
