/* Kidney Diet Log — demo API: GET /api/handbook (twin of app/handbook.py's route).

   The preview and demo pages run without a server, so there is no handbook at /learn to link to:
   the demo answers like a server without a built handbook and without HANDBOOK_PUBLIC_URL, and the
   app shows no Learn links (js/learn.js). Signing in is required, as on the server (js/mock/auth.js
   checks every /api route).

   The GitHub Pages demo is the exception (v0.3.1): it sits next to the published handbook, and its
   preview-flag.js (scripts/build_preview.py --pages) sets window.KDL_DEMO_HANDBOOK to where that is,
   relative to the page, and to the server's link table (app/guidance/topics.py APP_LINKS). The demo
   then answers like a server with HANDBOOK_PUBLIC_URL set. */
(() => {
  'use strict';
  const KH = window.KH;
  const { route } = KH.mock;

  function pagesHandbook() {
    const d = window.KDL_DEMO_HANDBOOK;
    if (!d || typeof d.url !== 'string' || !d.links || typeof d.links !== 'object') return null;
    try {
      return { url: new URL(d.url, window.location.href).href, links: d.links };
    } catch (_) {
      return null;
    }
  }

  route('GET', '/api/handbook', function () {
    const pages = pagesHandbook();
    if (pages) return { available: false, url: pages.url, public_url: pages.url, links: pages.links };
    return { available: false, url: null, public_url: null, links: { nutrients: {}, flags: {}, pages: {} } };
  });
})();
