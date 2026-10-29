/* Kidney Diet Log — service worker (template; note 02 R4).

   GET /sw.js (app/pwa.py) serves this file with __VERSION__ replaced by a hash of the static
   files, so every release changes it byte for byte and the browser installs the new worker; the
   page then offers "Update ready · Reload" (js/pwa.js). With PWA_ENABLED=false the server sends a
   kill-switch worker instead.

   Caches ONLY static files: personal data never enters Cache Storage. Not intercepted: /api/**,
   /healthz, any non-GET request, other origins, and navigations to anything but the app itself
   and the handbook. `?reauth=1` on a navigation goes to the network too, so an auth proxy can
   redirect to its sign-in page.

   The patient handbook under /learn (static, the same for everyone; v0.3.1) is network-first: each
   page and file it loads while online is copied into its own cache, kdl-learn-<version>, so pages
   opened before can be read offline. Only plain 200 answers from this server are kept, never a
   redirect to a sign-in page. Offline, a page never opened on this device answers with a short note
   (learnOffline) instead of the browser's error page. A new release starts with an empty copy.

   SHELL_URLS lists every file index.html loads (tests/test_frontend_shell.py keeps the two in
   step), the barcode ponyfill included; its 1 MB WebAssembly reader is cached on first use. The PDF
   reader (js/engine/pdf_pages.js is in the list; the pdf.js library and its worker, two files under
   /vendor/ of about 1.8 MB together, are not) is fetched when the first lab report PDF is picked and
   kept by the same /vendor/ rule below. */
'use strict';

const VERSION = '__VERSION__';
const SHELL = `kdl-shell-${VERSION}`;
const VENDOR = `kdl-vendor-${VERSION}`;
const LEARN = `kdl-learn-${VERSION}`;
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
  '/css/symptoms.css',
  '/css/body.css',
  '/css/visit.css',
  '/css/settings.css',
  '/css/auth.css',
  '/css/sheets.css',
  '/css/pwa.css',
  '/css/ai.css',
  '/css/guidance.css',
  '/css/ask.css',
  '/css/ask-voice.css',
  '/css/device.css',
  '/css/demo-local.css',
  '/css/touch.css',
  '/js/engine/rules.js',
  '/js/engine/apple_health.js',
  '/js/engine/zip.js',
  '/js/engine/kidney_function.js',
  '/js/engine/lab_import.js',
  '/js/engine/fhir_labs.js',
  '/js/engine/ccda_labs.js',
  '/js/engine/pdf_pages.js',
  '/js/engine/menu_link.js',
  '/js/engine/symptoms.js',
  '/js/engine/body.js',
  '/js/engine/visitprep.js',
  '/js/engine/body_ui.js',
  '/js/engine/targets.js',
  '/js/engine/settings.js',
  '/js/engine/textclean.js',
  '/js/engine/aiguard.js',
  '/js/engine/gtin.js',
  '/js/engine/additives.js',
  '/js/engine/off.js',
  '/js/engine/guidance/rules.js',
  '/js/engine/guidance/messages.js',
  '/js/engine/guidance/budget.js',
  '/js/engine/guidance/score.js',
  '/js/engine/guidance/fits.js',
  '/js/engine/guidance/swaps.js',
  '/js/engine/guidance/planner.js',
  '/js/engine/guidance/insights.js',
  '/js/engine/guidance/hypo.js',
  '/js/engine/guidance/recipes.js',
  '/js/engine/brand.js',
  '/js/core.js',
  '/js/learn.js',
  '/js/offline.js',
  '/js/mock/core.js',
  '/js/mock/foods.js',
  '/js/mock/barcode.js',
  '/js/mock/profile.js',
  '/js/mock/labs.js',
  '/js/mock/symptoms.js',
  '/js/mock/body.js',
  '/js/mock/log.js',
  '/js/mock/meals.js',
  '/js/mock/guidance.js',
  '/js/mock/auth.js',
  '/js/mock/settings.js',
  '/js/mock/handbook.js',
  '/js/mock/meta.js',
  '/js/mock/ai.js',
  '/js/mock/export.js',
  '/js/mock/import.js',
  '/js/mock/persist.js',
  '/js/mock/seed.js',
  '/js/views/today.js',
  '/js/views/add.js',
  '/js/views/plan.js',
  '/js/views/menuplan.js',
  '/js/views/trends.js',
  '/js/views/symptoms.js',
  '/js/views/body.js',
  '/js/views/body_trends.js',
  '/js/views/labs.js',
  '/js/views/lab_photo.js',
  '/js/views/lab_fhir.js',
  '/js/views/lab_ccda.js',
  '/js/views/body_import.js',
  '/js/views/visit.js',
  '/js/views/profile.js',
  '/js/views/auth.js',
  '/js/views/settings.js',
  '/js/views/two_step.js',
  '/js/views/passkeys.js',
  '/js/views/sharing.js',
  '/js/views/ai.js',
  '/js/views/ai_routing.js',
  '/js/views/ai_quality.js',
  '/js/views/guidance.js',
  '/js/views/ask.js',
  '/js/views/ask-voice.js',
  '/js/views/demo_local.js',
  '/vendor/barcode-detector-3.2.2/ponyfill.iife.js',
  '/js/scan.js',
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
  // The page asks which release its shell came from, to compare with the server's X-KDL-Version.
  if (event.data === 'VERSION' && event.source) event.source.postMessage({ type: 'kdl-version', version: VERSION });
});

self.addEventListener('fetch', (event) => {
  const req = event.request;
  const url = new URL(req.url);
  if (req.method !== 'GET' || url.origin !== self.location.origin) return;
  if (url.pathname.startsWith('/api/') || url.pathname === '/healthz') return;
  if (url.pathname === '/learn' || url.pathname.startsWith('/learn/')) {
    event.respondWith(fromLearn(event));
    return;
  }
  if (req.mode === 'navigate') {
    if (url.pathname !== '/' && url.pathname !== '/index.html') return; // anything else goes to the network
    if (url.searchParams.has('reauth')) return; // let an auth proxy redirect to its sign-in page
    event.respondWith(caches.match('/', { cacheName: SHELL }).then((cached) => cached || fetch(req)));
    return;
  }
  if (url.pathname.startsWith('/vendor/')) {
    // Vendored third-party code (barcode scanning, PDF lab reports): the ponyfill comes with the shell; the 1 MB
    // WebAssembly reader is fetched on the first scan that needs it, and pdf.js and its worker (about 1.8 MB, module
    // script and module Worker requests, same origin) on the first PDF; then kept in the vendor cache (cache-first,
    // both caches). No second rule: the one prefix covers every vendored folder.
    event.respondWith(caches.open(VENDOR).then(async (cache) => {
      const hit = (await cache.match(req)) || (await caches.match(req, { cacheName: SHELL }));
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

// The handbook (/learn): the network first, keeping a copy of every plain 200 answer for reading offline.
async function fromLearn(event) {
  const req = event.request;
  try {
    const res = await fetch(req);
    if (res.status === 200 && res.type === 'basic' && !res.redirected) {
      const copy = res.clone();
      const saved = caches.open(LEARN).then((cache) => cache.put(req, copy)).catch(() => null);
      try { event.waitUntil(saved); } catch (e) { /* a browser that refuses a late waitUntil still gets the page */ }
    }
    return res;
  } catch (err) {
    // Offline (or the server is down): the copy kept from an earlier visit. A search-highlight link
    // (?h=potassium) opens the same page.
    const hit = await caches.match(req, { cacheName: LEARN, ignoreSearch: req.mode === 'navigate' });
    if (hit) return hit;
    if (req.mode === 'navigate') return learnOffline();
    throw err;
  }
}

// A handbook page never opened on this device, while offline: a short note with no script or style.
function learnOffline() {
  const html = '<!doctype html><html lang="en"><head><meta charset="utf-8">'
    + '<meta name="viewport" content="width=device-width, initial-scale=1"><meta name="color-scheme" content="light dark">'
    + '<title>Not saved for offline reading</title></head><body>'
    + '<h1>This handbook page is not saved on this device</h1>'
    + '<p>You are offline, or the server cannot be reached. Handbook pages you have opened before on this device can be read offline; this one has not been opened here yet.</p>'
    + '<p><a href="/learn/">Handbook start page</a> &middot; <a href="/">Back to the food log</a></p>'
    + '</body></html>';
  return new Response(html, {
    status: 503,
    statusText: 'Offline',
    headers: {
      'Content-Type': 'text/html; charset=utf-8',
      'Content-Security-Policy': "default-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
      'Cache-Control': 'no-store',
      'X-Content-Type-Options': 'nosniff',
    },
  });
}
