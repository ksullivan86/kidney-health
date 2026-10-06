/* Kidney Diet Log — demo API: GET /api/handbook (twin of app/handbook.py's route).

   The preview and demo pages run without a server, so there is no handbook at /learn to link to:
   the demo answers like a server without a built handbook and without HANDBOOK_PUBLIC_URL, and the
   app shows no Learn links (js/learn.js). Signing in is required, as on the server (js/mock/auth.js
   checks every /api route). */
(() => {
  'use strict';
  const KH = window.KH;
  const { route } = KH.mock;

  route('GET', '/api/handbook', function () {
    return { available: false, url: null, public_url: null, links: { nutrients: {}, flags: {}, pages: {} } };
  });
})();
