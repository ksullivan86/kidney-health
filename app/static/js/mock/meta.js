/* Kidney Diet Log — demo API: GET /api/meta (twin of app/meta.py).

   What the server answers a client that is not the page (the native app of the ROADMAP): its version, the API version, what the signed-in
   person can use now, the nutrient registry and the meal names. The preview and demo pages have no server behind them, so they answer like
   a server with nothing optional switched on: no AI (js/mock/ai.js), no assistant or phone-shortcut tokens (js/mock/auth.js makes none),
   no USDA key, no handbook of their own (js/mock/handbook.js). Open Food Facts follows the demo's own settings, as POST /api/foods/barcode
   does (js/mock/barcode.js): the admin switch and the person's consent. Signing in is required, as on the server (js/mock/auth.js checks
   every /api route).

   API_VERSION is kept equal to app/api_version.py by tests/data/meta_vectors.json (tests/data/gen_meta_vectors.py; node tests/js/run_vectors.mjs),
   which also pins the nutrient list, the meal names and the capability keys to the server's. Nothing reads this route yet: the screens
   still use the lists in js/engine/rules.js and js/core.js (ROADMAP "Open items"). */
(() => {
  'use strict';
  const KH = window.KH;
  const { route } = KH.mock;

  const API_VERSION = 1;

  route('GET', '/api/meta', function () {
    const u = this._currentUser();
    const off = !!this._effectiveSetting('food.off_enabled', null).value && !!this._effectiveSetting('food.off_consent', u.id).value;
    const views = KH.views || {};
    return {
      app_version: views.settings && views.settings.APP_VERSION ? views.settings.APP_VERSION : null,
      api_version: API_VERSION,
      capabilities: {
        ai: false, ai_next_meal: false, ai_parse_meal: false, ai_label: false, ai_plate: false, ai_lab_report: false, ai_recipes: false,
        chat: false, voice: false,
        assistant: false, push: false,
        barcode: off, barcode_off: off, barcode_usda: false,
        handbook: false,
      },
      nutrients: KH.rules.NUTRIENTS.map((n) => ({ key: n.key, label: n.label, unit: n.unit, role: n.role })),
      meals: [...KH.rules.MEAL_KEYS],
    };
  });

  Object.assign(KH.mock, { API_VERSION });
})();
