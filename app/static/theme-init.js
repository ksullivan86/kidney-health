/* Kidney Diet Log — apply the stored light/dark choice before first paint to avoid a flash.
   Loaded from the document head (it was an inline script; the CSP allows none). Storage may be
   unavailable (private mode, sandboxed frame), so every access stays inside try/catch. */
try {
  var t = localStorage.getItem('kdl-theme');
  if (t === 'light' || t === 'dark') document.documentElement.setAttribute('data-theme', t);
} catch (e) {}
