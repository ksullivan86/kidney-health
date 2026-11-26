/* The way back from Withings or Whoop to the Kidney Health iPhone app (see index.html). Only `code`, `state` and `error` are
   passed on, to the app's own scheme; the address is cleared from the page first. Nothing is stored or sent anywhere else. */
(() => {
  'use strict';
  const given = new URLSearchParams(window.location.search);
  const out = new URLSearchParams();
  for (const name of ['code', 'state', 'error']) {
    const value = given.get(name);
    if (value !== null && value.length <= 512) out.set(name, value);
  }
  try { window.history.replaceState(null, '', window.location.pathname); } catch (e) { /* the app still gets it below */ }
  if (!out.has('state')) return; // not a way back from a sign-in: nothing to hand on
  const target = `kidneyhealth-devices://callback?${out.toString()}`;
  const link = document.getElementById('back');
  if (link) link.setAttribute('href', target);
  window.location.replace(target);
})();
