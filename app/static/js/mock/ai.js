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

   DEVICE MODE WITH A SERVER (design note 39 §6, plan step 4; D2 and D3). When the phone is paired with a token "both ways"
   (js/mock/server_api.js), each feature picks its AI by one rule, worked out each time:
     1. the server's AI, when the server answers and its GET /api/ai/status says the feature is available for this person;
     2. else the iPhone's own AI, for the two features it has (describe a meal, the text of a lab report page);
     3. else the feature's way without AI, as before.
   The setting "Use only this iPhone's AI" (kept with the log, GET and PUT /api/device/ai-choice) skips step 1. Only a failure moves
   on: the server could not be reached, or answered 503 (not available) or 404 (AI off there, as if not registered). Every other
   answer is shown as it is: a safety answer (treating a low, get help now, ask your care team) is never asked anywhere else, a
   consent question (409) opens the same consent sheet as the web app, a daily limit (429) is the server's.
   Lab report text and photos go only to the server's lab routes, which run only on its local AI, or to the iPhone's own model. They
   are never put in any other request and never fall back to a cloud model. The server's foods in an answer are kept on this phone
   and named by its own ids (M.serverApi.localize); an idea that names a food this phone does not have is left out. Ask (the chat)
   stays off on the phone for now: the server's assistant can save to the log on the server, which reaches the phone only with
   two-way sync (note 39 step 6).
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
    const [ss, dev] = await Promise.all([serverStatus(api, { fresh: true }), deviceStatus(api)]);
    const S = KH.mock.serverApi;
    const known = S ? S.status() : null;
    const where = whereEach(ss, dev);
    const serverAi = Object.values(where).includes('server');
    return {
      ...OFF_VIEW(), enabled: st.available || serverAi, settings: prefs(api), user_keys_allowed: false, daily_limit: null, remaining_today: null,
      routing: st.available ? { mode: 'routed', features: Object.keys(ROUTES).map((f) => routeView(f, true, null)) } : null,
      device: { available: st.available, reason: st.reason, message: st.reason ? UNAVAILABLE[st.reason] : null, provider: summary() },
      // Note 39 §6.1: the server's AI, when a token both ways is paired; and the person's choice to use only this iPhone's.
      phone: { server: known && known.state === 'both' ? known.server : null, both_ways: !!(known && known.state === 'both'),
        device_only: choiceOf(api).device_only, server_ai: serverAi, where, labels: { ...ROUTES } },
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
    // The same switch on the server, when its AI may be used: only opt_in, nothing else of the person's AI settings.
    const send = typeof changes.opt_in === 'boolean' && KH.mock.serverApi && !choiceOf(this).device_only;
    const told = send ? KH.mock.serverApi.offers('ai').then((yes) => (yes ? KH.mock.serverApi.call('PATCH', '/api/me/ai', { body: { opt_in: changes.opt_in } }) : null))
      : Promise.resolve(null);
    return told.then(() => { forgetServer(); return meView(this); });
  });
  // The iPhone's own AI as GET /api/ai/status shows it, or null when this iPhone has none.
  async function deviceStatus(api) {
    return aiStatus().then((st) => {
      if (!st.available) return null; // as a server with AI off
      const optedIn = !!prefs(api).opt_in;
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
  }

  // ---------------------------------------------------------------------------
  // Device mode with a server: the choice of AI (note 39 §6.1)
  // ---------------------------------------------------------------------------
  const FEATURE_ROUTE = { next_meal: 'meal_ideas', parse_meal: 'describe', label: 'photos', plate: 'photos', chat: 'chat', voice: 'chat',
    lab_report: 'labs', lab_report_text: 'labs', recipes: 'recipes', recipe_steps: 'recipes' };
  const NOT_ON_PHONE = new Set(['chat']); // Ask stays off on the phone until two-way sync (see the top)
  const SERVER_GONE = 'Your server could not be reached, so this AI feature is not available right now. Try again later.';
  const STATUS_TTL_MS = 30000;
  const choiceOf = (api) => ({ device_only: false, ...(api._aiPhone || {}) });
  let serverSeen = null; // { at, status } of the server's GET /api/ai/status, for the feature routes
  function forgetServer() { serverSeen = null; }
  // The server's AI status for this person, or null when its AI is not to be used now.
  async function serverStatus(api, { fresh = false } = {}) {
    const S = KH.mock.serverApi;
    if (!S || choiceOf(api).device_only) return null;
    if (!fresh && serverSeen && Date.now() - serverSeen.at < STATUS_TTL_MS) return serverSeen.status;
    let status = null;
    if (await S.offers('ai')) {
      const res = await S.call('GET', '/api/ai/status');
      if (res.status === 200 && isDict(res.json) && res.json.enabled !== false) status = res.json;
    }
    serverSeen = { at: Date.now(), status };
    return status;
  }
  // Step 1 of the rule: does the server run this feature route for this person now?
  function serverRuns(ss, featureRoute) {
    if (!ss || NOT_ON_PHONE.has(featureRoute) || ss.opted_in === false) return false;
    const r = ss.routes && ss.routes[featureRoute];
    return isDict(r) && r.available === true;
  }
  // One feature through the server. { value } with its answer (kept foods named by this phone's ids), or { skip } when the next
  // step of the rule must run: { skip: 'unreachable' } or { skip: 'not_available' }. Any other answer is thrown as the server's.
  async function viaServer(api, featureRoute, method, path, opts = {}) {
    const ss = await serverStatus(api);
    if (!serverRuns(ss, featureRoute)) return { skip: 'not_available' };
    const res = await KH.mock.serverApi.call(method, path, opts);
    if (res.offline || res.error) { forgetServer(); return { skip: 'unreachable' }; }
    if (res.status === 503 || res.status === 404) { forgetServer(); return { skip: 'not_available' }; }
    if (res.status >= 200 && res.status < 300) return { value: KH.mock.serverApi.localize(api, res.json) };
    return KH.mock.serverApi.failWith(res);
  }
  // A body for the server: nothing that names this phone's own rows (the server's ids differ until two-way sync).
  function forServer(body) {
    if (!isDict(body)) return body;
    const out = { ...body };
    for (const k of Object.keys(out)) if (/(^|_)food_ids?$/.test(k)) delete out[k];
    return out;
  }
  const query = (qp) => (qp('dry_run') === 'true' ? '?dry_run=true' : '');
  // Where each feature runs now, for Settings: 'server', 'iphone' or null.
  function whereEach(ss, dev) {
    const out = {};
    for (const f of Object.keys(ROUTES)) {
      out[f] = serverRuns(ss, f) ? 'server' : dev && dev.routes[f] && dev.routes[f].available ? 'iphone' : null;
    }
    return out;
  }
  // GET /api/ai/status in device mode: the server's view for the features it runs, the iPhone's for the rest.
  async function mergedStatus(api) {
    const [ss, dev] = await Promise.all([serverStatus(api, { fresh: true }), deviceStatus(api)]);
    const runs = (f) => serverRuns(ss, f);
    if (!ss || !Object.keys(ROUTES).some(runs)) {
      if (!dev) fail(404, 'Not Found'); // no AI anywhere: as a server with AI off
      return dev;
    }
    const routes = {};
    for (const f of Object.keys(ROUTES)) {
      routes[f] = runs(f) ? { ...ss.routes[f], runs_on_phone: 'server' } : dev ? dev.routes[f] : routeView(f, false, 'feature_off');
    }
    const features = {};
    for (const [k, f] of Object.entries(FEATURE_ROUTE)) {
      features[k] = runs(f) ? !!(ss.features && ss.features[k]) : !!(dev && dev.features[k]);
    }
    features.voice = false; // the phone does not send recordings
    const consent = {};
    for (const purpose of ['text', 'photos', 'chat', 'labs', 'voice']) {
      const served = Object.keys(ROUTES).some((f) => PURPOSE[f] === purpose && runs(f));
      consent[purpose] = served ? (ss.consent || {})[purpose] || null : dev ? dev.consent[purpose] || null : null;
    }
    const available = Object.values(features).some(Boolean);
    return {
      ...ss, enabled: true, opted_in: true, available, reason: available ? null : ss.reason, message: available ? null : ss.message,
      routes, features, consent, voice: null, device: true, server: KH.mock.serverApi.status() ? KH.mock.serverApi.status().server : null,
      remaining_today: ss.remaining_today == null ? null : ss.remaining_today,
    };
  }

  route('GET', '/api/ai/status', function () {
    if (!device()) fail(404, 'Not Found');
    return mergedStatus(this);
  });
  // "Use only this iPhone's AI" (note 39 §6.1): a setting of this phone, kept with the log, never sent to the server.
  route('GET', '/api/device/ai-choice', function () {
    if (!device()) fail(404, 'Not Found');
    return choiceOf(this);
  });
  route('PUT', '/api/device/ai-choice', function ({ body }) {
    if (!device()) fail(404, 'Not Found');
    if (!isDict(body) || typeof body.device_only !== 'boolean') KH.mock.failFields(['device_only: Input should be a valid boolean']);
    this._aiPhone = { device_only: body.device_only };
    forgetServer();
    return choiceOf(this);
  });
  // Consent to the server's AI provider (the same sheet as the web app): only for the server, whose consent it is.
  route('POST', '/api/ai/consent', function ({ body }) {
    if (!device()) fail(404, 'Not Found');
    return serverStatus(this).then(async (ss) => {
      if (!ss) fail(404, 'Not Found');
      const res = await KH.mock.serverApi.call('POST', '/api/ai/consent', { body });
      forgetServer();
      if (res.offline || res.error) fail(503, SERVER_GONE, { reason: 'server_unreachable' });
      if (res.status >= 200 && res.status < 300) return res.json;
      return KH.mock.serverApi.failWith(res);
    });
  });
  // Meal ideas and AI recipes: the server's AI only (the iPhone's model has neither).
  for (const [path, featureRoute] of [['/api/ai/next-meal', 'meal_ideas'], ['/api/ai/recipes', 'recipes']]) {
    route('POST', path, function ({ body, qp }) {
      if (!device()) fail(404, 'Not Found');
      return viaServer(this, featureRoute, 'POST', `${path}${query(qp)}`, { body: forServer(body) }).then((got) => {
        if (got.value !== undefined) return got.value;
        if (got.skip === 'unreachable') fail(503, SERVER_GONE, { reason: 'server_unreachable' });
        return fail(404, 'Not Found'); // no AI for this feature: its way without AI
      });
    });
  }
  // Photos (a label, a plate, a lab report page): the server's AI only, the photo as the JPEG the page made (no location data).
  for (const [path, featureRoute] of [['/api/vision/label', 'photos'], ['/api/vision/plate', 'photos'], ['/api/ai/read-lab-report', 'labs']]) {
    route('POST', path, function ({ body, qp }) {
      if (!device()) fail(404, 'Not Found');
      if (!body || typeof body.arrayBuffer !== 'function') fail(415, 'Send the photo as a JPEG (Content-Type: image/jpeg).', { reason: 'not_jpeg' });
      return KH.mock.serverApi.base64(body).then((jpeg) => viaServer(this, featureRoute, 'POST', `${path}${query(qp)}`, { jpeg })).then((got) => {
        if (got.value !== undefined) return got.value;
        if (got.skip === 'unreachable') fail(503, SERVER_GONE, { reason: 'server_unreachable' });
        return fail(404, 'Not Found');
      });
    });
  }
  // Describe a meal (app/ai/routes.py parse_meal; app/ai/features.py prepare_parse_meal), device mode only.
  route('POST', '/api/ai/parse-meal', function ({ body, qp }) {
    if (!device()) fail(404, 'Not Found');
    const c = new Check(body); // ParseMealBody
    extraKeys(c, body, ['text', 'meal', 'date']);
    c.str('text', { required: true, min: 1, max: 300, nullable: false });
    c.choice('meal', ['breakfast', 'lunch', 'dinner', 'snack'], { nullable: true });
    c.str('date');
    const b = c.done();
    // Note 39 §6.1: the server's AI first. Its own prefilter answers a low or a red flag; that answer is shown as it is.
    return viaServer(this, 'describe', 'POST', `/api/ai/parse-meal${query(qp)}`, { body }).then((got) => {
      if (got.value !== undefined) return got.value;
      return parseMealOnDevice(this, b, qp);
    });
  });
  function parseMealOnDevice(api, b, qp) {
    const cards = J().prefilter(b.text, api._guidancePrefs().hypo_dose_g); // G7, G8, G2/G3: the AI is not asked
    if (cards) return cards;
    const dry = qp('dry_run') === 'true';
    return ready(api).then(async () => {
      const text = J().dataPayload(J().parseMealData(b.text));
      if (dry) return dryRun('parse_meal', 'parse_meal', text);
      const got = await ask('parse_meal', text);
      if (got.verdict) return answer('parse_meal', got.verdict);
      const checked = J().checkParseMeal(got.answer);
      if (!checked.ok) return answer('parse_meal', { status: 'error', reason: 'schema', message: ERROR_TEXT.schema });
      const keep = ['id', 'name', 'brand', 'category', 'source', 'serving_desc', 'serving_g', 'nutrients', 'flags', 'warnings', 'kidney_rating'];
      const search = (words) => api._searchFoods(words, null, null, 3).map((f) => Object.fromEntries(keep.map((k) => [k, f[k] === undefined ? null : f[k]])));
      return answer('parse_meal', J().judgeParseMeal(checked.answer, search, checked.malformed));
    });
  }

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
    if (device()) {
      // Note 39 §6.2: only the server's lab route (local AI only), or the iPhone's own model. Never any other AI.
      return viaServer(this, 'labs', 'POST', `/api/ai/read-lab-report-text${query(qp)}`, { body: { text: body.text, page } }).then((got) => {
        if (got.value !== undefined) return got.value;
        return readLabTextOnDevice(this, text, page, qp('dry_run') === 'true');
      });
    }
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
  // Settings → AI features sets the phone's own choice through this (the route above, so the log is saved after it).
  const setOnly = (deviceOnly) => KH.mock.instance.request('PUT', '/api/device/ai-choice', { device_only: !!deviceOnly });
  KH.mock.aiDevice = { PROVIDER, UNAVAILABLE, MAX_DEVICE_TEXT, setOnly, forgetServer };
})();
