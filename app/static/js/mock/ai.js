/* Kidney Diet Log — demo API: the optional AI (twin of app/ai/routes.py and app/vision.py as seen from a
   server where AI is switched off).

   The preview and demo pages never contact an AI provider (ARCHITECTURE.md "Frontend modules": AI
   answers "available in the installed app"). So the demo answers like a server with ai.enabled off:
   GET /api/me/ai says so, and every /api/ai/* and /api/vision/* route is 404, exactly as the server
   answers while AI is off, except POST /api/ai/read-lab-report-text, which answers a fixed example (below). Signing in is required, as on the server (js/mock/auth.js checks every /api
   route). */
(() => {
  'use strict';
  const KH = window.KH;
  const { route, fail } = KH.mock;

  route('GET', '/api/me/ai', function () {
    return {
      enabled: false,
      settings: { opt_in: false, provider: 'auto', share_age_sex: false, preferences: '', trust: 'ask' },
      chat_enabled: false,
      trusted_saves_allowed: false,
      user_keys_allowed: true,
      allow_user_base_url: false,
      own: null,
      shared: [],
      routing: null,
      route_choice: null, // design note 32: null while AI is off, as on the server
      presets: [],
      consents: [],
      daily_limit: 30,
      remaining_today: 30,
    };
  });
  // Choosing the server's local or cloud AI (design note 32): with AI off the server refuses it.
  route('PUT', '/api/me/ai/route-choice', function () { fail(403, 'Your admin has not let you choose which of the server\'s AIs you use.'); });
  /* The one exception (design note 36 §4.4): reading the text of a lab report PDF answers with a FIXED EXAMPLE, so the demo can show the
     review table. Nothing is sent anywhere and nothing is read from the file: the rows are always these three, in the shape the server's
     judge gives (tests/test_lab_text_demo.py runs app/ai/lab_report.py on the same lines and compares). The notice says so. The body is
     checked like the server's: text 1 to 20,000 characters, page 1 to 50. */
  const LAB_TEXT_EXAMPLE = /* lab-text-example */ {
    status: 'ok',
    rows: [
      { analyte: 'potassium', label: 'Potassium', value: 4.6, unit: 'mmol/L', display: '4.6 mmol/L', taken_on: '2026-10-07', printed_date: '2026-10-07', date_problem: null, date_note: null },
      { analyte: 'phosphate', label: 'Phosphate', value: 3.4, unit: 'mg/dL', display: '3.4 mg/dL', taken_on: '2026-10-07', printed_date: '2026-10-07', date_problem: null, date_note: null },
      { analyte: 'egfr', label: 'eGFR (reported by the lab)', value: 61, unit: 'mL/min/1.73 m²', display: '61 mL/min/1.73 m²', taken_on: '2026-10-07', printed_date: '2026-10-07', date_problem: null, date_note: null },
    ],
    dropped: { unknown_analyte: 0, unknown_unit: 0, out_of_range: 0, not_in_text: 0 },
    dropped_notes: [],
  } /* end-lab-text-example */;
  const LAB_TEXT_DEMO_NOTICE = 'This is the demo: nothing was sent to an AI. These rows are a fixed example, not read from your file.';
  route('POST', '/api/ai/read-lab-report-text', function ({ body, qp }) {
    const text = body && typeof body.text === 'string' ? body.text.trim() : '';
    if (!text) fail(400, 'text: String should have at least 1 character');
    if (text.length > 20000) fail(400, 'text: String should have at most 20000 characters');
    const page = body.page === undefined || body.page === null ? null : body.page;
    if (page !== null && !(Number.isInteger(page) && page >= 1 && page <= 50)) fail(400, 'page: Input should be a whole number from 1 to 50');
    if (qp('dry_run') === 'true') {
      return { dry_run: true, demo: true, feature: 'read_lab_report_text', message: LAB_TEXT_DEMO_NOTICE };
    }
    return { ...JSON.parse(JSON.stringify(LAB_TEXT_EXAMPLE)), notice: LAB_TEXT_DEMO_NOTICE, demo: true, page, feature: 'read_lab_report_text' };
  });
  route('*', /^\/api\/(?:ai|vision)\//, function () { fail(404, 'Not Found'); });
})();
