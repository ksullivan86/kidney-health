/* Kidney Diet Log — apply the stored light/dark choice before first paint to avoid a flash.
   Loaded from the document head (it was an inline script; the CSP allows none). Storage may be
   unavailable (private mode, sandboxed frame), so every access stays inside try/catch. */
try {
  var t = localStorage.getItem('kdl-theme');
  if (t === 'light' || t === 'dark') document.documentElement.setAttribute('data-theme', t);
} catch (e) {}
// The first script error while the page loads, kept for js/main.js: when boot fails, the "app did not start"
// notice (index.html #boot-fail) names it, because later errors are often only a result of it.
try {
  window.addEventListener('error', function (e) {
    if (!window.KDL_BOOT_ERROR && e && e.message) window.KDL_BOOT_ERROR = String(e.message);
  });
} catch (e) {}
