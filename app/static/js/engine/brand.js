/* Kidney Diet Log — the brand strings the page uses: the browser's copy of app/brand.py (design note 14, change 3).

   One place for the names and identifying strings that the scripts would otherwise spell out, so a second product changes them here
   and in app/brand.py and does not have to search for them. Every value is what the scripts had before this file existed. The
   names match the Python constants: `name` is NAME, `screenName` is SCREEN_NAME, `csrfHeaderValue` is CSRF_HEADER_VALUE, and so on.
   tests/test_brand.py keeps the shared ones equal and pins every value.

   Compatibility surface (already stored, sent or remembered by something outside this page; do not change on an install in use):
     csrfHeaderValue  the X-Requested-With value the server's CSRF check expects on every unsafe /api request.
     versionHeader    the response header that carries the shell's version (app/pwa.py sets it).
     exportFormat     the "format" of export.json, which the demo writes and reads.
     idbName          the IndexedDB database of the offline copy and the outbox (js/offline.js); only the browser has it.
   Display only: name, screenName, slug, logCsvPrefix.

   Not here, on purpose: the other "kdl-" names (local storage keys, the service worker's cache names, the Web Lock) and the demo's stored
   copy ("kdl-demo-local"), because sw.js and theme-init.js run outside KH and cannot read this file, and those names are in each person's
   browser already. js/engine/settings.js and js/engine/off.js keep their literals as vector-checked twins of the server's settings.

   Loaded last of the engine files, right before js/core.js and so before every script that reads it. Exposes KH.brand = { name, screenName, slug, logCsvPrefix,
   csrfHeaderValue, versionHeader, exportFormat, idbName }. */
(() => {
  'use strict';
  const root = typeof window !== 'undefined' ? window : globalThis;
  const KH = root.KH || (root.KH = {});

  KH.brand = Object.freeze({
    name: 'Kidney Health', // the product's name in the server's words; the server name shown when the server has not told the page one
    screenName: 'Kidney Diet Log', // the name on the screen: the page title and the Visit prep footer
    slug: 'kidney-health', // the start of the export's file name
    logCsvPrefix: 'kidney-log_', // the start of the food log download's file name
    csrfHeaderValue: 'kidney-health',
    versionHeader: 'X-KDL-Version',
    exportFormat: 'kidney-health-export',
    idbName: 'kdl',
  });
})();
