/* Kidney Diet Log — demo API: the optional AI (twin of app/ai/routes.py and app/vision.py as seen from a
   server where AI is switched off).

   The preview and demo pages never contact an AI provider (ARCHITECTURE.md "Frontend modules": AI
   answers "available in the installed app"). So the demo answers like a server with ai.enabled off:
   GET /api/me/ai says so, and every /api/ai/* and /api/vision/* route is 404, exactly as the server
   answers while AI is off, except POST /api/ai/read-lab-report-text, which answers a fixed example (below). Signing in is required, as on the server (js/mock/auth.js checks every /api
   route).

   DEVICE MODE (the iPhone app with no server, design note 38 §5.6): Apple's on-device model stands in for the server's AI, for
   two features only: describe a meal (POST /api/ai/parse-meal) and the text of a lab report page (POST /api/ai/read-lab-report-text).
   * The page asks the iPhone app through KH.mock.device.lookup (js/mock/device.js): { kind: 'aiStatus' } answers
     { ok, available, reason }, and { kind: 'ai', task, text } answers { ok, answer } or { error, message }. `text` is the data the
     server puts in its prompt, cleaned and escaped as the server does it (KH.aiJudge.dataPayload); the app puts it into the
     server's own prompt (ai-prompts.json, written by scripts/build_preview.py --device).
   * The model's answer is untrusted: the page checks its shape (KH.aiJudge.checkParseMeal, checkLabReport) and then runs the
     server's checks on it (the twins in js/engine/aijudge.js and lab_report.js). Before anything is asked, the server's prefilter
     runs: a low, an emergency or a dose question gets the server's card and the AI is not asked.
   * The answers have the server's shape, with the on-device model as the provider. Nothing leaves the phone, so there is no
     consent sheet to a host; the person still turns AI features on in Settings (opt_in, kept with the rest of the log).
   * Nothing about the prompt or the reply is stored: there is no AI activity log in device mode (audit_id is null).
   Outside device mode nothing here changes. */
(() => {
  'use strict';
  const KH = window.KH;
  const { route, fail, Check, isDict } = KH.mock;

  const OFF_VIEW = () => ({
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
  });

  // ---------------------------------------------------------------------------
  // Device mode: Apple's on-device model through the iPhone app
  // ---------------------------------------------------------------------------
  const device = () => !!(KH.flags && KH.flags.DEVICE === true && KH.mock.device);
  const J = () => KH.aiJudge;
  const PROVIDER = { id: 0, label: 'Apple\'s on-device model', model: 'apple-on-device', host: 'this iPhone' };
  const POLICY = 'Runs on this iPhone. Nothing is sent to any company or server.';
  const MAX_DEVICE_TEXT = 8000; // the most the iPhone app hands its model (its 4,096-token window)
  const UNAVAILABLE = { // why the iPhone app's model cannot answer (its aiStatus reasons), and the server's own for opt-in
    not_eligible: 'This iPhone cannot run Apple\'s on-device AI, so the AI features are off. Everything else works.',
    not_enabled: 'Turn on Apple Intelligence in the iPhone\'s Settings to use the AI features.',
    not_ready: 'Apple\'s on-device AI is getting ready on this iPhone. Try again in a while.',
    no_app: 'The AI features need the iPhone app.',
    not_opted_in: 'Turn on AI features in Settings → AI features first.', // app/ai/config.py MESSAGES
  };
  const ERROR_TEXT = { ai_failed: 'The AI request failed.', schema: 'The AI answer could not be used.' }; // app/ai/routes.py
  // app/vision.py says "Read it as a picture instead"; the phone cannot read a picture yet, so it says what can be done here.
  const TOO_LONG = 'This page has more text than the AI on this iPhone can take at once. Enter its results by hand instead.';
  const DRY_NOTE = 'Nothing leaves this iPhone: the app gives this to Apple\'s on-device model, with the app\'s own fixed instructions.';
  const CONSENT = { host: PROVIDER.host, policy_version: 'device', skip_preview: true, at: null }; // nothing is sent: nothing to agree to
  const ROUTES = { photos: 'Photos (labels and plates)', meal_ideas: 'Meal ideas', describe: 'Describe a meal', chat: 'Ask',
    labs: 'Lab report photos', recipes: 'Recipes' }; // app/ai/routing.py LABEL
  const PURPOSE = { photos: 'photos', meal_ideas: 'text', describe: 'text', chat: 'chat', labs: 'labs', recipes: 'text' };
  const ON_DEVICE = ['describe', 'labs'];

  async function aiStatus() {
    const a = await KH.mock.device.lookup({ kind: 'aiStatus' });
    if (a && a.ok === true) return { available: a.available === true, reason: a.available === true ? null : (UNAVAILABLE[a.reason] ? a.reason : 'not_ready') };
    return { available: false, reason: 'no_app' };
  }
  function unavailable(reason) { fail(503, UNAVAILABLE[reason] || 'AI is not available.', { reason }); }
  function prefs(api) {
    return { opt_in: false, provider: 'auto', share_age_sex: false, preferences: '', trust: 'ask', ...(api._aiPrefs || {}) };
  }
  function summary() {
    return { ...PROVIDER, vision_model: null, scope: 'device', kind: 'on_device', policy: POLICY };
  }
  function routeView(feature, on, reason) {
    const available = ON_DEVICE.includes(feature) && on;
    return { feature, label: ROUTES[feature], purpose: PURPOSE[feature], route: ON_DEVICE.includes(feature) ? 'local' : 'off', role: null,
      chosen: false, available, reason: available ? null : (ON_DEVICE.includes(feature) ? reason : 'feature_off'),
      message: available ? null : (ON_DEVICE.includes(feature) ? UNAVAILABLE[reason] || null : 'This feature is not in the iPhone app.'),
      text: available ? 'Runs on this iPhone with Apple\'s on-device model.' : 'Not in the iPhone app.',
      runs_on: available ? summary() : null, fallback: null, consent: available ? { ...CONSENT } : null };
  }
  // Must the call go ahead? 503 with the server's reason when the model cannot answer or the person has not turned AI on.
  async function ready(api) {
    const st = await aiStatus();
    if (!st.available) unavailable(st.reason);
    if (!prefs(api).opt_in) unavailable('not_opted_in');
  }
  function dryRun(feature, task, text) {
    return { dry_run: true, device: true, feature, mode: null, destination: '', host: PROVIDER.host,
      provider: { id: PROVIDER.id, label: PROVIDER.label, preset: 'apple_on_device', scope: 'device', local: true },
      method: '', headers: {}, body: { kind: 'ai', task, text }, image_bytes: 0, images: [], message: DRY_NOTE };
  }
  // routes._answer: the checked answer and where it came from. Nothing is stored, so there is no AI activity row.
  function answer(feature, verdict) {
    return { ...verdict, repaired: false, retried: false, trimmed: 0, feature, mode: null, provider: { ...PROVIDER },
      prompt_version: J().PROMPT_VERSION, audit_id: null, cached: false, notes: [] };
  }
  // Ask the iPhone app's model. { answer } or { verdict } (refused, failed) — 503 when it cannot answer at all.
  async function ask(task, text) {
    const res = await KH.mock.device.lookup({ kind: 'ai', task, text });
    if (res && res.ok === true) return { answer: res.answer };
    const code = res && res.error;
    if (code === 'ai_unavailable') {
      const st = await aiStatus();
      unavailable(st.available ? 'not_ready' : st.reason);
    }
    if (code === 'refused') return { verdict: { status: 'refused', message: J().REFUSED_TEXT } }; // routes._verdict_of
    return { verdict: { status: 'error', reason: 'ai_failed', message: ERROR_TEXT.ai_failed } };
  }
  function extraKeys(c, body, allowed) {
    for (const k of Object.keys(isDict(body) ? body : {})) if (!allowed.includes(k)) c.err(k, 'Extra inputs are not permitted');
  }

  // GET /api/me/ai in device mode: `enabled` is whether the iPhone's model can answer; `device` says why not, in plain words.
  async function meView(api) {
    const st = await aiStatus();
    return {
      ...OFF_VIEW(), enabled: st.available, settings: prefs(api), user_keys_allowed: false, daily_limit: null, remaining_today: null,
      routing: st.available ? { mode: 'routed', features: Object.keys(ROUTES).map((f) => routeView(f, true, null)) } : null,
      device: { available: st.available, reason: st.reason, message: st.reason ? UNAVAILABLE[st.reason] : null, provider: summary() },
    };
  }
  route('GET', '/api/me/ai', function () { return device() ? meView(this) : OFF_VIEW(); });
  // app/ai/routes.py MeAiPatch: in device mode the person turns the AI features on and off here (kept with the log).
  route('PATCH', '/api/me/ai', function ({ body }) {
    if (!device()) fail(404, 'Not Found');
    const c = new Check(body);
    extraKeys(c, body, ['opt_in', 'provider', 'share_age_sex', 'preferences', 'trust']);
    for (const k of ['opt_in', 'share_age_sex']) {
      if (c.has(k) && body[k] !== null && typeof body[k] !== 'boolean') c.err(k, 'Input should be a valid boolean');
      else if (c.has(k) && body[k] !== null) c.out[k] = body[k];
    }
    c.str('provider', { max: 40 });
    if (c.out.provider != null && !/^(auto|own|shared:[1-9][0-9]{0,17})$/.test(c.out.provider)) c.err('provider', 'String should match pattern \'^(auto|own|shared:[1-9][0-9]{0,17})$\'');
    c.str('preferences', { max: 200 });
    c.str('trust');
    if (c.out.trust != null && !/^(ask|conversation|always)$/.test(c.out.trust)) c.err('trust', 'String should match pattern \'^(ask|conversation|always)$\'');
    const b = c.done();
    const changes = Object.fromEntries(Object.entries(b).filter(([, v]) => v !== null && v !== undefined));
    this._aiPrefs = { ...prefs(this), ...changes };
    return meView(this);
  });
  route('GET', '/api/ai/status', function () {
    if (!device()) fail(404, 'Not Found');
    return aiStatus().then((st) => {
      if (!st.available) fail(404, 'Not Found'); // as a server with AI off
      const optedIn = !!prefs(this).opt_in;
      const routes = Object.fromEntries(Object.keys(ROUTES).map((f) => [f, routeView(f, optedIn, 'not_opted_in')]));
      return {
        enabled: true, opted_in: optedIn, available: optedIn, reason: optedIn ? null : 'not_opted_in',
        message: optedIn ? null : UNAVAILABLE.not_opted_in, provider: summary(),
        consent: { text: optedIn ? { ...CONSENT } : null, photos: null, chat: null, labs: optedIn ? { ...CONSENT } : null, voice: null },
        routing: { mode: 'routed' }, routes, policy_version: 'device', daily_limit: null, remaining_today: null,
        features: { next_meal: false, parse_meal: optedIn, label: false, plate: false, chat: false, voice: false, lab_report: false,
          lab_report_text: optedIn, recipes: false, recipe_steps: false },
        voice: null, trust: { setting: 'ask', allowed: false, effective: 'ask' }, prompt_version: J().PROMPT_VERSION, device: true,
      };
    });
  });
  // Describe a meal (app/ai/routes.py parse_meal; app/ai/features.py prepare_parse_meal), device mode only.
  route('POST', '/api/ai/parse-meal', function ({ body, qp }) {
    if (!device()) fail(404, 'Not Found');
    const c = new Check(body); // ParseMealBody
    extraKeys(c, body, ['text', 'meal', 'date']);
    c.str('text', { required: true, min: 1, max: 300, nullable: false });
    c.choice('meal', ['breakfast', 'lunch', 'dinner', 'snack'], { nullable: true });
    c.str('date');
    const b = c.done();
    const cards = J().prefilter(b.text, this._guidancePrefs().hypo_dose_g); // G7, G8, G2/G3: the AI is not asked
    if (cards) return cards;
    const dry = qp('dry_run') === 'true';
    return ready(this).then(async () => {
      const text = J().dataPayload(J().parseMealData(b.text));
      if (dry) return dryRun('parse_meal', 'parse_meal', text);
      const got = await ask('parse_meal', text);
      if (got.verdict) return answer('parse_meal', got.verdict);
      const checked = J().checkParseMeal(got.answer);
      if (!checked.ok) return answer('parse_meal', { status: 'error', reason: 'schema', message: ERROR_TEXT.schema });
      const keep = ['id', 'name', 'brand', 'category', 'source', 'serving_desc', 'serving_g', 'nutrients', 'flags', 'warnings', 'kidney_rating'];
      const search = (query) => this._searchFoods(query, null, null, 3).map((f) => Object.fromEntries(keep.map((k) => [k, f[k] === undefined ? null : f[k]])));
      return answer('parse_meal', J().judgeParseMeal(checked.answer, search, checked.malformed));
    });
  });

  // Choosing the server's local or cloud AI (design note 32): with AI off the server refuses it.
  route('PUT', '/api/me/ai/route-choice', function () { fail(403, 'Your admin has not let you choose which of the server\'s AIs you use.'); });
  /* The one exception (design note 36 §4.4): reading the text of a lab report PDF answers with a FIXED EXAMPLE, so the demo can show the
     review table. Nothing is sent anywhere and nothing is read from the file: the rows are always these three, in the shape the server's
     judge gives (tests/test_lab_text_demo.py runs app/ai/lab_report.py on the same lines and compares). The notice says so. The body is
     checked like the server's: text 1 to 20,000 characters, page 1 to 50. In device mode the iPhone app's model reads the text instead. */
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
  // A row the model wrote in a shape the app cannot check (device mode only: the server's schema check fails the whole answer).
  const malformedNote = (n) => `${n} ${n === 1 ? 'line was' : 'lines were'} left out because the AI wrote ${n === 1 ? 'it' : 'them'} in a way the app could not check.`;
  route('POST', '/api/ai/read-lab-report-text', function ({ body, qp }) {
    const text = body && typeof body.text === 'string' ? body.text.trim() : '';
    if (!text) fail(400, 'text: String should have at least 1 character');
    if (text.length > 20000) fail(400, 'text: String should have at most 20000 characters');
    const page = body.page === undefined || body.page === null ? null : body.page;
    if (page !== null && !(Number.isInteger(page) && page >= 1 && page <= 50)) fail(400, 'page: Input should be a whole number from 1 to 50');
    if (device()) return readLabTextOnDevice(this, text, page, qp('dry_run') === 'true');
    if (qp('dry_run') === 'true') {
      return { dry_run: true, demo: true, feature: 'read_lab_report_text', message: LAB_TEXT_DEMO_NOTICE };
    }
    return { ...JSON.parse(JSON.stringify(LAB_TEXT_EXAMPLE)), notice: LAB_TEXT_DEMO_NOTICE, demo: true, page, feature: 'read_lab_report_text' };
  });
  // app/vision.py read_lab_report_text with app/ai/features.py prepare_read_lab_report_text and lab_report.judge_text.
  async function readLabTextOnDevice(api, text, page, dry) {
    await ready(api);
    const lines = J().labTextLines(text);
    const sent = lines.join('\n');
    const payload = J().dataPayload({ lines });
    if (payload.length > MAX_DEVICE_TEXT) fail(413, TOO_LONG, { reason: 'too_long_for_ai' });
    if (dry) return dryRun('read_lab_report_text', 'read_lab_report_text', payload);
    const got = await ask('read_lab_report_text', payload);
    let verdict = got.verdict;
    if (!verdict) {
      const checked = J().checkLabReport(got.answer);
      if (!checked.ok) verdict = { status: 'error', reason: 'schema', message: ERROR_TEXT.schema };
      else {
        verdict = KH.labReport.judgeText(checked.answer, sent);
        if (checked.malformed) {
          verdict.dropped = { ...verdict.dropped, malformed: checked.malformed };
          verdict.dropped_notes = [...verdict.dropped_notes, malformedNote(checked.malformed)];
        }
      }
    }
    if (verdict.status === 'error') fail(502, verdict.message, { reason: verdict.reason, audit_id: null }); // vision._upstream_error
    const out = answer('read_lab_report_text', verdict);
    if (!out.rows) out.rows = [];
    if (!out.dropped) out.dropped = { ...Object.fromEntries(KH.labReport.DROPPED_KEYS.map((k) => [k, 0])), not_in_text: 0 };
    out.page = page;
    return out;
  }
  route('*', /^\/api\/(?:ai|vision)\//, function () { fail(404, 'Not Found'); });
  KH.mock.aiDevice = { PROVIDER, UNAVAILABLE, MAX_DEVICE_TEXT };
})();
