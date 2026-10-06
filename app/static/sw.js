/* Kidney Diet Log — service worker (template; note 02 R4).

   GET /sw.js (app/pwa.py) serves this file with __VERSION__ replaced by a hash of the static
   files, so every release changes it byte for byte and the browser installs the new worker; the
   page then offers "Update ready · Reload" (js/pwa.js). With PWA_ENABLED=false the server sends a
   kill-switch worker instead.

   Caches ONLY the static shell: personal data never enters Cache Storage. Not intercepted:
   /api/**, /healthz, any non-GET request, other origins, and navigations to anything but the
   app itself: the /learn handbook goes to the network (offline handbook pages are a v0.4 item,
   docs/ROADMAP.md). `?reauth=1` on a navigation goes to the network too, so an auth proxy can
   redirect to its sign-in page.

   SHELL_URLS lists every file index.html loads (tests/test_frontend_shell.py keeps the two in
   step); M2 adds js/offline.js and js/scan.js here when they exist. */
'use strict';

const VERSION = '__VERSION__';
const SHELL = `kdl-shell-${VERSION}`;
const VENDOR = `kdl-vendor-${VERSION}`;
const SHELL_URLS = [
  '/',
  '/theme-init.js',
  '/css/base.css',
  '/css/today.css',
  '/css/add.css',
  '/css/plan.css',
  '/css/trends.css',
  '/css/profile.css',
  '/css/labs.css',
  '/css/settings.css',
  '/css/auth.css',
  '/css/sheets.css',
  '/css/pwa.css',
  '/css/touch.css',
  '/js/engine/rules.js',
  '/js/engine/kidney_function.js',
  '/js/engine/targets.js',
  '/js/engine/settings.js',
  '/js/core.js',
  '/js/learn.js',
  '/js/mock/core.js',
  '/js/mock/foods.js',
  '/js/mock/profile.js',
  '/js/mock/labs.js',
  '/js/mock/log.js',
  '/js/mock/meals.js',
  '/js/mock/auth.js',
  '/js/mock/settings.js',
  '/js/mock/handbook.js',
  '/js/mock/seed.js',
  '/js/views/today.js',
  '/js/views/add.js',
  '/js/views/plan.js',
  '/js/views/trends.js',
  '/js/views/labs.js',
  '/js/views/profile.js',
  '/js/views/auth.js',
  '/js/views/settings.js',
  '/js/pwa.js',
  '/js/main.js',
  '/manifest.webmanifest',
  '/apple-touch-icon.png',
  '/icons/icon.svg',
  '/icons/icon-192.png',
];

self.addEventListener('install', (event) => {
  // No skipWaiting() here: an update waits until the person taps Reload (or every tab closes),
  // so a page never runs half old and half new files.
  event.waitUntil(caches.open(SHELL).then((cache) => cache.addAll(SHELL_URLS.map((u) => new Request(u, { cache: 'reload' })))));
});

self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
    for (const key of await caches.keys()) {
      if (key.startsWith('kdl-') && !key.endsWith(VERSION)) await caches.delete(key);
    }
    await self.clients.claim();
  })());
});

self.addEventListener('message', (event) => {
  // Only this app's own pages (same origin) may ask the worker to activate an update.
  if (event.origin !== self.location.origin) return;
  if (event.data === 'SKIP_WAITING') self.skipWaiting();
});

self.addEventListener('fetch', (event) => {
  const req = event.request;
  const url = new URL(req.url);
  if (req.method !== 'GET' || url.origin !== self.location.origin) return;
  if (url.pathname.startsWith('/api/') || url.pathname === '/healthz') return;
  if (req.mode === 'navigate') {
    if (url.pathname !== '/' && url.pathname !== '/index.html') return; // the handbook etc. go to the network
    if (url.searchParams.has('reauth')) return; // let an auth proxy redirect to its sign-in page
    event.respondWith(caches.match('/', { cacheName: SHELL }).then((cached) => cached || fetch(req)));
    return;
  }
  if (url.pathname.startsWith('/vendor/')) {
    // Vendored decoders (M2 barcode scanning): fetched on first use, then cache-first.
    event.respondWith(caches.open(VENDOR).then(async (cache) => {
      const hit = await cache.match(req);
      if (hit) return hit;
      const res = await fetch(req);
      if (res.ok) cache.put(req, res.clone());
      return res;
    }));
    return;
  }
  if (!SHELL_URLS.includes(url.pathname)) return; // anything else: the network decides
  event.respondWith(caches.match(req, { cacheName: SHELL }).then((cached) => cached || fetch(req)));
});
