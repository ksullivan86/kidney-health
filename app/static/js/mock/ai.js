/* Kidney Diet Log — demo API: the optional AI (twin of app/ai/routes.py and app/vision.py as seen from a
   server where AI is switched off).

   The preview and demo pages never contact an AI provider (ARCHITECTURE.md "Frontend modules": AI
   answers "available in the installed app"). So the demo answers like a server with ai.enabled off:
   GET /api/me/ai says so, and every /api/ai/* and /api/vision/* route is 404, exactly as the server
   answers while AI is off. Signing in is required, as on the server (js/mock/auth.js checks every /api
   route). */
(() => {
  'use strict';
  const KH = window.KH;
  const { route, fail } = KH.mock;

  route('GET', '/api/me/ai', function () {
    return {
      enabled: false,
      settings: { opt_in: false, provider: 'auto', share_age_sex: false, preferences: '' },
      user_keys_allowed: true,
      allow_user_base_url: false,
      own: null,
      shared: [],
      presets: [],
      consents: [],
      daily_limit: 30,
      remaining_today: 30,
    };
  });
  route('*', /^\/api\/(?:ai|vision)\//, function () { fail(404, 'Not Found'); });
})();
