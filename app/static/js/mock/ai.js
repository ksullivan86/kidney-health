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
   and named by its own ids (M.serverApi.localize); an idea that names a food this phone does not have is left out.

   ASK ON THE PHONE (the chat, POST /api/ai/chat). Only the server's AI, and only while this phone syncs both ways with it
   (js/mock/server_changes.js active()): the assistant reads the person's log on the server, so the two must be in step. The iPhone's
   own model has no chat. The server runs everything as for the web app: its rules answer a low or an emergency without the model,
   its checks withhold dose talk, its consent sheet is the same. One source of truth for saves: the phone always sends `trust: 'ask'`,
   so the server writes nothing and answers with a card; Save on the card goes through this phone's own routes (POST /api/log/batch,
   /api/meals, a food preference), with the card's foods named by this phone's ids and the server's client_id kept on each entry, and
   step 4 then sends the new rows to the server like any other. A card that names a food this phone does not have becomes a question
   (nothing is saved). An older server that saved at once all the same: its "saved" cards lose Undo (their ids are the server's),
   say so, and a sync brings the rows here. Voice stays off on the phone. GET /api/me/ai → phone.ask and phone.photos say why Ask or
   a photo of a meal cannot run, for the screens' own words.
   THE PERSON'S OWN AI KEY (the owner, 2026-11-25: "if its not connected to the server it should be able to use their own keys";
   design note 39 §6.5). With or without a server, the person may add a key from OpenAI, OpenRouter or Nous Portal in the iPhone
   app (Keys and services). The order is then: the server's AI (as above) → the own key, for describe a meal and, only with the
   person's photo switch on, label and plate photos → the iPhone's own model → no AI. "Use only this iPhone's AI" skips the own key
   too. Only an unreachable provider (or one that is down) moves on; a refusal or a checked answer is shown as it is. The server's
   prefilter runs before the own key is asked, and the server's checks run on its answer (js/engine/aijudge.js). Lab reports never
   go to it, and a request whose data holds the profile's name or birth month is not sent to it (identityIn). The consent sheet
   names the provider and host before the first call; the consent is kept with the log. Ask stays the server's: it reads the log
   there. Nothing about a prompt or a reply is kept.
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
  const ON_DEVICE = ['describe', 'labs', 'meal_ideas', 'recipes']; // and photos on iOS 27 (onDevice below)

  // ---------------------------------------------------------------------------
  // The person's own AI key (owner, 2026-11-25; design note 39 §6.5), with or without a server
  // ---------------------------------------------------------------------------
  // The iPhone app holds the key (Keychain) and talks to the provider's fixed host (ios/.../OwnAI.swift); the page only asks
  // { kind: 'ownAIStatus' } → { ok, set, provider, label, host, model, photos } and { kind: 'ownAI', task, text | jpeg } →
  // { ok, content, refusal } or { error, message }. The app builds the request from the server's own prompts and schemas
  // (ai-prompts.json "own_key") and knows three tasks only. Lab reports never go to it, and the page never sends it anything that
  // holds the person's name or birth month (identityIn below): such a request goes to this iPhone's own model or nowhere.
  const OWN_ID = -1; // the own key's provider id in consent requests (the server's are positive, Apple's model is 0)
  const OWN_ROUTES = ['describe', 'meal_ideas', 'recipes', 'photos']; // photos only with the person's photo switch on
  const OWN_POLICY = { // app/ai/presets.py POLICY_LINES (tests/test_phone_own_key.py compares them)
    openai: 'OpenAI does not use API data for training; it keeps abuse-monitoring logs for up to 30 days.',
    openrouter: 'OpenRouter routes the request only to model providers that do not collect data.',
    nous_portal: 'Nous Research\'s API receives the request; read their privacy policy before agreeing.',
  };
  const OWN_ERROR = 'Your own AI key could not answer. Try again later.';
  const OWN_IDENTITY = 'This has your name or date of birth in it, so it was not sent to your own AI key. Take them out and try again.';
  const OWN_GONE = 'Your AI provider could not be reached, so this AI feature is not available right now. Try again later.';
  async function ownStatus(api) {
    if (choiceOf(api).device_only) return null; // "Use only this iPhone's AI" skips the own key too
    const a = await KH.mock.device.lookup({ kind: 'ownAIStatus' });
    if (!a || a.ok !== true || a.set !== true || !OWN_POLICY[a.provider]) return null;
    return { provider: a.provider, label: String(a.label || ''), host: String(a.host || ''), model: String(a.model || ''), photos: a.photos === true };
  }
  const ownRuns = (own, featureRoute) => !!own && OWN_ROUTES.includes(featureRoute) && (featureRoute !== 'photos' || own.photos);
  function ownSummary(own) {
    return { id: OWN_ID, label: `${own.label} (your own key)`, model: own.model, host: own.host, vision_model: null, scope: 'user',
      kind: 'cloud', policy: OWN_POLICY[own.provider], own_key: true };
  }
  const ownConsents = (api) => ({ ...(api._aiOwnConsent || {}) }); // { purpose: { provider, host, at } }, kept with the log
  function ownConsent(api, own, purpose) {
    const c = ownConsents(api)[purpose];
    return c && c.provider === own.provider && c.host === own.host ? { host: own.host, policy_version: 'own', skip_preview: true, at: c.at } : null;
  }
  function ownConsentRequest(own, purpose) {
    return { provider_id: OWN_ID, provider_label: `${own.label} (your own key)`, host: own.host, purpose, policy: OWN_POLICY[own.provider],
      policy_version: 'own', kind: 'cloud', upstream: null, local: false, own_key: true };
  }
  function ownRouteView(api, feature, own, optedIn) {
    return { feature, label: ROUTES[feature], purpose: PURPOSE[feature], route: 'cloud', role: null, chosen: false, available: optedIn,
      reason: optedIn ? null : 'not_opted_in', message: optedIn ? null : UNAVAILABLE.not_opted_in,
      text: `Goes to ${own.label} (${own.host}) with your own key.`, runs_on: ownSummary(own), runs_on_phone: 'own', fallback: null,
      consent: ownConsent(api, own, PURPOSE[feature]) };
  }
  // Does `text` hold the person's name or birth month? Then it never goes to the own key (CLAUDE.md, the owner's rule).
  const MONTHS = ['january', 'february', 'march', 'april', 'may', 'june', 'july', 'august', 'september', 'october', 'november', 'december'];
  function identityIn(api, text) {
    const p = api._profile || {};
    const folded = String(text || '').normalize('NFKC').toLowerCase();
    const name = typeof p.name === 'string' ? p.name.normalize('NFKC').toLowerCase().trim() : '';
    if (name) {
      if (folded.includes(name)) return true;
      for (const word of name.split(/[^\p{L}\p{N}'-]+/u)) {
        if (word.length >= 3 && new RegExp(`(^|[^\\p{L}\\p{N}])${word.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}($|[^\\p{L}\\p{N}])`, 'u').test(folded)) return true;
      }
    }
    const m = /^(\d{4})-(\d{2})$/.exec(typeof p.birth_month === 'string' ? p.birth_month : '');
    if (m) {
      const [, y, mm] = m;
      const n = String(Number(mm));
      const month = MONTHS[Number(mm) - 1] || '';
      const forms = [`${y}-${mm}`, `${y}/${mm}`, `${mm}/${y}`, `${n}/${y}`, `${mm}-${y}`, `${n}-${y}`, `${mm}.${y}`, `${month} ${y}`,
        `${month.slice(0, 3)} ${y}`];
      if (forms.some((f) => f && folded.includes(f))) return true;
    }
    return false;
  }
  // One task on the own key. { value } with the checked answer, or { skip } when the next step of the order must run: the own key
  // is not set or not for this feature, the provider could not be reached or is down, or the data names the person.
  async function viaOwnKey(api, featureRoute, task, payload, dry, check) {
    const own = await ownStatus(api);
    if (!ownRuns(own, featureRoute)) return { skip: 'not_available' };
    if (typeof payload.text === 'string' && identityIn(api, payload.text)) return { skip: 'identity' };
    if (!prefs(api).opt_in) unavailable('not_opted_in');
    const purpose = PURPOSE[featureRoute];
    if (!ownConsent(api, own, purpose)) {
      fail(409, 'Agree to send this to the AI provider first.', { consent_required: true, consent: ownConsentRequest(own, purpose) });
    }
    if (dry) {
      return { value: { dry_run: true, device: true, own_key: true, feature: task, mode: null, destination: `https://${own.host}`, host: own.host,
        provider: { id: OWN_ID, label: `${own.label} (your own key)`, preset: own.provider, scope: 'user', local: false },
        method: 'POST', headers: { Authorization: 'Bearer [your key, not shown]' }, body: payload.text != null ? { task, data: payload.text } : { task },
        image_bytes: payload.jpeg ? Math.floor((payload.jpeg.length * 3) / 4) : 0, images: [],
        message: `This iPhone sends this to ${own.label} at ${own.host} with your own key, with the app's fixed instructions. Your name and date of birth are never sent.` } };
    }
    const res = await KH.mock.device.lookup({ kind: 'ownAI', task, ...payload });
    if (!res || res.ok !== true) {
      const code = res && res.error;
      if (code === 'offline' || code === 'not_available' || code === 'own_off' || code === 'photos_off' || code === 'no_app') return { skip: 'unreachable' };
      if (code === 'rate_limited') fail(429, res.message || OWN_ERROR, { reason: 'rate_limited' });
      fail(502, (res && res.message) || OWN_ERROR, { reason: code || 'ai_failed', audit_id: null });
    }
    const provider = { id: OWN_ID, label: `${own.label} (your own key)`, model: own.model, host: own.host };
    const done = (verdict) => ({ ...verdict, repaired: false, retried: false, trimmed: 0, feature: task, mode: null, provider,
      prompt_version: J().PROMPT_VERSION, audit_id: null, cached: false, notes: [] });
    if (typeof res.refusal === 'string' && res.refusal) return { value: done({ status: 'refused', message: J().REFUSED_TEXT }) };
    const parsed = J().extractJson(res.content);
    return { value: done(parsed === null ? { status: 'error', reason: 'schema', message: ERROR_TEXT.schema } : check(parsed)) };
  }

  // { available, reason, photos }: photos is whether this iPhone's model can read a photo (iOS 27, OnDeviceVision.swift).
  async function aiStatus() {
    const a = await KH.mock.device.lookup({ kind: 'aiStatus' });
    if (a && a.ok === true) {
      const on = a.available === true;
      return { available: on, reason: on ? null : (UNAVAILABLE[a.reason] ? a.reason : 'not_ready'), photos: on && a.photos === true };
    }
    return { available: false, reason: 'no_app', photos: false };
  }
  // The feature routes this iPhone's own model runs now.
  const onDevice = (st) => (st && st.photos ? [...ON_DEVICE, 'photos'] : ON_DEVICE);
  function unavailable(reason) { fail(503, UNAVAILABLE[reason] || 'AI is not available.', { reason }); }
  function prefs(api) {
    return { opt_in: false, provider: 'auto', share_age_sex: false, preferences: '', trust: 'ask', ...(api._aiPrefs || {}) };
  }
  function summary() {
    return { ...PROVIDER, vision_model: null, scope: 'device', kind: 'on_device', policy: POLICY };
  }
  function routeView(feature, on, reason, here = ON_DEVICE) {
    const available = here.includes(feature) && on;
    return { feature, label: ROUTES[feature], purpose: PURPOSE[feature], route: here.includes(feature) ? 'local' : 'off', role: null,
      chosen: false, available, reason: available ? null : (here.includes(feature) ? reason : 'feature_off'),
      message: available ? null : (here.includes(feature) ? UNAVAILABLE[reason] || null : 'This feature is not in the iPhone app.'),
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
  async function ask(task, text, extra = {}) {
    const res = await KH.mock.device.lookup({ kind: 'ai', task, text, ...extra });
    if (res && res.ok === true) return { answer: res.answer };
    return failed(res);
  }
  async function failed(res) {
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
    const ownKey = dev && dev.own_key ? dev.own_key : null;
    const photosWhy = serverReason(api, ss, 'photos');
    return {
      ...OFF_VIEW(), enabled: st.available || serverAi || !!ownKey, settings: prefs(api), user_keys_allowed: false, daily_limit: null, remaining_today: null,
      routing: dev ? { mode: 'routed', features: Object.keys(ROUTES).map((f) => ({ ...dev.routes[f], available: true })) } : null,
      device: { available: st.available, reason: st.reason, message: st.reason ? UNAVAILABLE[st.reason] : null, provider: summary() },
      // Note 39 §6.1: the server's AI, when a token both ways is paired; and the person's choice to use only this iPhone's.
      phone: { server: known && known.state === 'both' ? known.server : null, both_ways: !!(known && known.state === 'both'),
        device_only: choiceOf(api).device_only, server_ai: serverAi, where, labels: { ...ROUTES }, own_key: ownKey,
        ask: serverReason(api, ss, 'chat'), // why not, or null; the own key has no Ask (it reads the log on the server)
        photos: photosWhy && ownKey && !ownKey.photos ? 'own_photos_off' : photosWhy },
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
  // The own key (above) is part of it: it runs describe a meal, and photos when the person turned that on.
  async function deviceStatus(api) {
    const [st, own] = await Promise.all([aiStatus(), ownStatus(api)]);
    if (!st.available && !own) return null; // as a server with AI off
    const optedIn = !!prefs(api).opt_in;
    const phone = st.available && optedIn;
    const routes = Object.fromEntries(Object.keys(ROUTES).map((f) => [f, ownRuns(own, f) ? ownRouteView(api, f, own, optedIn)
      : routeView(f, phone, st.available ? 'not_opted_in' : st.reason, onDevice(st))]));
    const ownText = ownRuns(own, 'describe') && optedIn;
    const ownPhotos = ownRuns(own, 'photos') && optedIn;
    const phonePhotos = phone && st.photos; // the iPhone's model reads the photo (iOS 27); the own key, when on for photos, goes first
    return {
      enabled: true, opted_in: optedIn, available: optedIn, reason: optedIn ? null : 'not_opted_in',
      message: optedIn ? null : UNAVAILABLE.not_opted_in, provider: own ? ownSummary(own) : summary(),
      consent: { text: ownText ? ownConsent(api, own, 'text') : phone ? { ...CONSENT } : null,
        photos: ownPhotos ? ownConsent(api, own, 'photos') : phonePhotos ? { ...CONSENT } : null,
        chat: null, labs: phone ? { ...CONSENT } : null, voice: null },
      routing: { mode: 'routed' }, routes, policy_version: 'device', daily_limit: null, remaining_today: null,
      features: { next_meal: ownText || phone, parse_meal: ownText || phone, label: ownPhotos || phonePhotos, plate: ownPhotos || phonePhotos, chat: false, voice: false, lab_report: false,
        lab_report_text: phone, recipes: ownText || phone, recipe_steps: false },
      voice: null, trust: { setting: 'ask', allowed: false, effective: 'ask' }, prompt_version: J().PROMPT_VERSION, device: true,
      own_key: own ? { label: own.label, host: own.host, model: own.model, photos: own.photos } : null,
    };
  }

  // ---------------------------------------------------------------------------
  // Device mode with a server: the choice of AI (note 39 §6.1)
  // ---------------------------------------------------------------------------
  const FEATURE_ROUTE = { next_meal: 'meal_ideas', parse_meal: 'describe', label: 'photos', plate: 'photos', chat: 'chat', voice: 'chat',
    lab_report: 'labs', lab_report_text: 'labs', recipes: 'recipes', recipe_steps: 'recipes' };
  // Ask needs this phone in step with the server both ways (see the top).
  const twoWay = () => { try { return !!(KH.mock.serverChanges && KH.mock.serverChanges.active()); } catch (e) { return false; } };
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
    if (!ss || (featureRoute === 'chat' && !twoWay()) || ss.opted_in === false) return false;
    const r = ss.routes && ss.routes[featureRoute];
    return isDict(r) && r.available === true;
  }
  // One feature through the server. { value } with its answer (kept foods named by this phone's ids), or { skip } when the next
  // step of the rule must run: { skip: 'unreachable' } or { skip: 'not_available' }. Any other answer is thrown as the server's.
  // `raw`: the caller names the foods itself (Ask's cards).
  async function viaServer(api, featureRoute, method, path, opts = {}, { raw = false } = {}) {
    const ss = await serverStatus(api);
    if (!serverRuns(ss, featureRoute)) return { skip: 'not_available' };
    const res = await KH.mock.serverApi.call(method, path, opts);
    if (res.offline || res.error) { forgetServer(); return { skip: 'unreachable' }; }
    if (res.status === 503 || res.status === 404) { forgetServer(); return { skip: 'not_available' }; }
    if (res.status >= 200 && res.status < 300) return { value: raw ? res.json : KH.mock.serverApi.localize(api, res.json) };
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
  // Where each feature runs now, for Settings: 'server', 'own' (the person's own AI key), 'iphone' or null.
  function whereEach(ss, dev) {
    const out = {};
    for (const f of Object.keys(ROUTES)) {
      const here = dev && dev.routes[f] && dev.routes[f].available ? dev.routes[f] : null;
      out[f] = serverRuns(ss, f) ? 'server' : here ? (here.runs_on_phone === 'own' ? 'own' : 'iphone') : null;
    }
    return out;
  }
  // Why the server's AI cannot run a feature route for this phone now, or null when it can. The screens say it in their own words.
  function serverReason(api, ss, featureRoute) {
    const S = KH.mock.serverApi;
    const k = S ? S.status() : null;
    if (!k || k.state === 'not_paired' || k.state === 'no_app') return 'not_paired';
    if (k.state === 'add_only' || k.state === 'old_server') return 'not_both_ways';
    if (k.state !== 'both') return 'offline'; // offline, or an answer the app could not use: asked again later
    if (choiceOf(api).device_only) return 'device_only';
    if (featureRoute === 'chat' && !twoWay()) return 'not_synced';
    if (ss && ss.opted_in === false) return 'not_opted_in';
    return serverRuns(ss, featureRoute) ? null : 'server_off';
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
      trust: { setting: 'ask', allowed: false, effective: 'ask', phone: true }, // Ask on the phone always asks before it saves (see the top)
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
    if (isDict(body) && body.provider_id === OWN_ID) { // the person's own key: kept with the log on this phone
      return ownStatus(this).then((own) => {
        if (!own || !['text', 'photos'].includes(body.purpose)) fail(404, 'Not Found');
        const at = new Date().toISOString();
        this._aiOwnConsent = { ...ownConsents(this), [body.purpose]: { provider: own.provider, host: own.host, at } };
        return { provider_id: OWN_ID, purpose: body.purpose, host: own.host, policy_version: 'own', skip_preview: body.skip_preview !== false, at };
      });
    }
    return serverStatus(this).then(async (ss) => {
      if (!ss) fail(404, 'Not Found');
      const res = await KH.mock.serverApi.call('POST', '/api/ai/consent', { body });
      forgetServer();
      if (res.offline || res.error) fail(503, SERVER_GONE, { reason: 'server_unreachable' });
      if (res.status >= 200 && res.status < 300) return res.json;
      return KH.mock.serverApi.failWith(res);
    });
  });
  // Meal ideas and AI recipes (note 39 §6.6): the server's AI first; else the person's own key, then the iPhone's own model, with
  // the server's candidates, data block and checks (twins in js/engine/aimeal.js); else the feature's way without AI.
  for (const [path, featureRoute] of [['/api/ai/next-meal', 'meal_ideas'], ['/api/ai/recipes', 'recipes']]) {
    route('POST', path, function ({ body, qp }) {
      if (!device()) fail(404, 'Not Found');
      const b = featureRoute === 'meal_ideas' ? nextMealBody(body) : recipesBody(body);
      return viaServer(this, featureRoute, 'POST', `${path}${query(qp)}`, { body: forServer(body) }).then((got) => {
        if (got.value !== undefined) return got.value;
        return (featureRoute === 'meal_ideas' ? mealIdeasHere : recipesHere)(this, b, qp('dry_run') === 'true', got.skip);
      });
    });
  }
  // app/ai/routes.py NextMealBody and RecipesBody.
  const MEALS = ['breakfast', 'lunch', 'dinner', 'snack'];
  function excludeIds(c, body) {
    if (!c.has('exclude_food_ids')) { c.out.exclude_food_ids = []; return; }
    const v = body.exclude_food_ids;
    if (!Array.isArray(v)) { c.err('exclude_food_ids', 'Input should be a valid list'); return; }
    if (v.length > 60) { c.err('exclude_food_ids', `List should have at most 60 items after validation, not ${v.length}`); return; }
    v.forEach((x, i) => { if (!(Number.isInteger(x) && x >= 1)) c.err(`exclude_food_ids.${i}`, 'Input should be a valid integer greater than or equal to 1'); });
    c.out.exclude_food_ids = v;
  }
  function nextMealBody(body) {
    const c = new Check(body);
    extraKeys(c, body, ['meal', 'date', 'mode', 'entry_id', 'food_id', 'servings', 'exclude_food_ids']);
    c.choice('meal', MEALS, { required: true });
    c.str('date');
    c.choice('mode', ['ideas', 'rerank', 'swap', 'plan'], { def: 'ideas' });
    for (const k of ['entry_id', 'food_id']) c.num(k, { ge: 1, int: true, maxId: true });
    c.num('servings', { gt: 0, le: 20 });
    excludeIds(c, body);
    return c.done();
  }
  function recipesBody(body) {
    const c = new Check(body);
    extraKeys(c, body, ['mode', 'target', 'meal', 'date', 'dish', 'makes', 'meal_id', 'exclude_food_ids']);
    c.choice('mode', ['suggest', 'change'], { def: 'suggest' });
    c.choice('target', ['meal', 'day'], { def: 'meal' });
    c.choice('meal', MEALS, { nullable: true });
    c.str('date');
    c.choice('dish', Object.keys(KH.aiMeal.DISH_WORD), { nullable: true });
    c.choice('makes', [1, 2, 4, 6], { def: 4 });
    c.num('meal_id', { ge: 1, int: true, maxId: true });
    excludeIds(c, body);
    const b = c.done();
    if (b.mode === 'suggest' && (b.dish == null || b.meal_id != null)) fail(400, 'suggest needs dish (and no meal_id)');
    if (b.mode === 'change' && (b.meal_id == null || b.dish != null)) fail(400, 'change needs meal_id (and no dish)');
    return b;
  }
  // The person block of meal ideas and recipes (prompts.person_block with context.explicit_preferences): the profile's stage,
  // dialysis and diabetes, the AI preferences text, the foods and groups the person marked, age band and sex only with consent.
  function personHere(api) {
    const s = api._guidanceSetting('guidance') || {};
    const rows = [...api._foodPreferences()].map(([id, row], i) => ({ id, i, row }))
      .sort((a, b) => ((b.row.updated_at || b.row.created_at || '') < (a.row.updated_at || a.row.created_at || '') ? -1
        : (b.row.updated_at || b.row.created_at || '') > (a.row.updated_at || a.row.created_at || '') ? 1 : b.i - a.i));
    const names = (kind, setting) => {
      const out = rows.filter((r) => r.row.preference === kind).map((r) => (api._foods.find((f) => f.id === r.id) || {}).name).filter(Boolean);
      for (const g of [...(s[setting] || [])].reverse()) if (!out.includes(g)) out.push(g);
      return out.slice(0, 10);
    };
    const tastes = { likes: names('like', 'like_categories'), less_often: names('less', 'less_categories'),
      not_for_me: names('not_for_me', 'exclude_categories') };
    return KH.aiMeal.personBlock(api._profileView(), prefs(api), KH.util.todayStr(), tastes);
  }
  function guidanceCtx(api, day, options) {
    const ctx = api._guidanceContext(day, options);
    const s = api._guidanceSetting('guidance') || {};
    ctx.prefs.plan_repeat_meals = [...(s.plan_repeat_meals || [])];
    return ctx;
  }
  // How much of the data block each AI takes. The server trims candidates (lowest ranked first) until its estimate of the whole
  // request (characters ÷ 3.5) and the answer fit the provider's prompt budget (features._fits). The own key's providers have the
  // server's cloud budget (32,768 tokens), which the data block never comes near; the cap below only guards against a runaway list.
  // The iPhone's own model has about 4,096 tokens for everything: the rules (about 1,000), the answer's shape and the answer itself
  // (about 1,000) leave about 2,000 tokens, and JSON reads at fewer characters per token than prose, so its data block is cut to
  // 5,000 characters: with the fixed parts that leaves room for about eight candidates. Fewer candidates, the same checks.
  const DATA_CHARS = { own: 80000, iphone: 5000 };
  const CONTEXT_TOO_SMALL = 'The AI provider\'s prompt budget (AI_CONTEXT_TOKENS) is too small for this request.';
  const ONLY_IDEAS_HERE = 'On this iPhone the AI gives meal ideas only. AI order, AI swaps and AI day plans need your server\'s AI.';
  // The phone's AIs for a feature route, in order: the own key, then the iPhone's model. [] when neither can run it.
  async function phoneAis(api, featureRoute) {
    const [own, st] = await Promise.all([ownStatus(api), aiStatus()]);
    const out = [];
    if (ownRuns(own, featureRoute)) out.push({ kind: 'own', own });
    if (st.available) out.push({ kind: 'iphone' });
    return out;
  }
  // Ask one of the phone's AIs a meal ideas or recipe task. build(limit) gives { text, ids, condition, trimmed } with the data block
  // trimmed to `limit` characters, or null when even the smallest list does not fit. Returns { raw } (the model's JSON), { verdict }
  // (a refusal or a failure, in the server's words), { skip } (try the next AI) or a dry run.
  async function askPhoneAi(api, ai, featureRoute, task, build, dry) {
    const req = build(DATA_CHARS[ai.kind]);
    if (ai.kind === 'own') {
      if (!req) return { skip: 'too_small' };
      if (identityIn(api, req.text)) return { skip: 'identity' };
      if (!ownConsent(api, ai.own, 'text')) {
        fail(409, 'Agree to send this to the AI provider first.', { consent_required: true, consent: ownConsentRequest(ai.own, 'text') });
      }
      const provider = { id: OWN_ID, label: `${ai.own.label} (your own key)`, model: ai.own.model, host: ai.own.host };
      if (dry) {
        return { dry: { dry_run: true, device: true, own_key: true, feature: task, mode: null, destination: `https://${ai.own.host}`, host: ai.own.host,
          provider: { id: OWN_ID, label: provider.label, preset: ai.own.provider, scope: 'user', local: false }, method: 'POST',
          headers: { Authorization: 'Bearer [your key, not shown]' }, body: { task, data: req.text, condition: req.condition, ids: req.ids },
          image_bytes: 0, images: [], trimmed_candidates: req.trimmed,
          message: `This iPhone sends this to ${ai.own.label} at ${ai.own.host} with your own key, with the app's fixed instructions. Your name and date of birth are never sent.` } };
      }
      const res = await KH.mock.device.lookup({ kind: 'ownAI', task, text: req.text, condition: req.condition, ids: req.ids });
      if (!res || res.ok !== true) {
        const code = res && res.error;
        if (['offline', 'not_available', 'own_off', 'no_app'].includes(code)) return { skip: 'unreachable' };
        if (code === 'rate_limited') fail(429, res.message || OWN_ERROR, { reason: 'rate_limited' });
        fail(502, (res && res.message) || OWN_ERROR, { reason: code || 'ai_failed', audit_id: null });
      }
      if (typeof res.refusal === 'string' && res.refusal) return { provider, req, verdict: { status: 'refused', message: J().REFUSED_TEXT } };
      const parsed = J().extractJson(res.content);
      return parsed === null ? { provider, req, verdict: { status: 'error', reason: 'schema', message: ERROR_TEXT.schema } } : { provider, req, raw: parsed };
    }
    if (!req) fail(503, CONTEXT_TOO_SMALL, { reason: 'context_too_small' });
    if (dry) return { dry: { ...dryRun(task, task, req.text), body: { kind: 'ai', task, text: req.text, condition: req.condition }, trimmed_candidates: req.trimmed } };
    const got = await ask(task, req.text, { condition: req.condition });
    return got.verdict ? { provider: { ...PROVIDER }, req, verdict: got.verdict } : { provider: { ...PROVIDER }, req, raw: got.answer };
  }
  // The first answer of the phone's AIs, in order (the caller checked there is one).
  function noPhoneAi(serverSkip) {
    if (serverSkip === 'unreachable') fail(503, SERVER_GONE, { reason: 'server_unreachable' });
    fail(404, 'Not Found'); // no AI for this feature: its way without AI
  }
  async function onPhone(api, featureRoute, task, build, dry) {
    const ais = await phoneAis(api, featureRoute);
    if (!prefs(api).opt_in) unavailable('not_opted_in');
    let skipped = null;
    for (const ai of ais) {
      const got = await askPhoneAi(api, ai, featureRoute, task, build, dry);
      if (got.skip) { skipped = got.skip; continue; }
      return got;
    }
    if (skipped === 'identity') fail(503, OWN_IDENTITY, { reason: 'identity' });
    if (skipped === 'too_small') fail(503, CONTEXT_TOO_SMALL, { reason: 'context_too_small' });
    fail(503, OWN_GONE, { reason: 'own_unreachable' });
  }
  const phoneAnswer = (feature, mode, got, verdict, notes) => ({ ...verdict, repaired: false, retried: false, trimmed: got.req.trimmed, feature, mode,
    provider: got.provider, prompt_version: J().PROMPT_VERSION, audit_id: null, cached: false, notes });

  // app/ai/routes.py _prepare_next_meal and features.prepare_next_meal, mode "ideas" only.
  async function mealIdeasHere(api, b, dry, serverSkip) {
    const A = KH.aiMeal;
    if (!(await phoneAis(api, 'meal_ideas')).length) noPhoneAi(serverSkip);
    if (b.mode !== 'ideas') fail(503, ONLY_IDEAS_HERE, { reason: 'not_on_phone' });
    const day = b.date ? b.date : KH.util.todayStr();
    const off = api._guidanceGate();
    if (off) return off;
    const ctx = guidanceCtx(api, day);
    if (!api._guidanceHasTargets(ctx.profile)) return api._guidanceUnavailable('no_targets', KH.guidanceEngine.M.NO_TARGETS);
    const person = personHere(api);
    const condition = A.conditionText(person);
    const full = A.candidatesForAi(ctx, b.meal, new Set(b.exclude_food_ids));
    const mealsLeft = KH.guidanceEngine.budget.openSlots(b.meal, ctx.day);
    let bridge = full;
    const build = (limit) => {
      bridge = full;
      for (let trimmed = 0; ; trimmed += 1) {
        const text = J().dataPayload(A.nextMealContext(bridge, ctx, b.meal, mealsLeft, person));
        if (text.length <= limit) {
          const ids = [...new Set([...bridge.foods.map((f) => f.food_id), ...bridge.meals.flatMap((m) => m.items.map((it) => it.food_id))])].sort((x, y) => x - y);
          return { text, ids, condition, trimmed };
        }
        if (bridge.foods.length <= 1) return null;
        bridge = { ...bridge, foods: bridge.foods.slice(0, -1) }; // lowest ranked first (rule order)
      }
    };
    const got = await onPhone(api, 'meal_ideas', 'next_meal', build, dry);
    if (got.dry) return got.dry;
    let verdict = got.verdict;
    if (!verdict) {
      const checked = A.checkIdeas(got.raw);
      verdict = checked.ok ? A.judgeIdeas(checked.answer, ctx, b.meal, bridge, got.provider.label, got.provider.model)
        : { status: 'error', reason: 'schema', message: ERROR_TEXT.schema };
    }
    if (['dropped_all', 'no_fit', 'error'].includes(verdict.status)) verdict = { ...verdict, fallback: A.fallback(bridge) };
    return phoneAnswer('next_meal', 'ideas', got, verdict, [KH.guidanceEngine.M.DISCLAIMER]);
  }

  // app/ai/routes.py _prepare_recipes and recipes.prepare_recipes, with cooking steps off.
  async function recipesHere(api, b, dry, serverSkip) {
    const A = KH.aiMeal;
    const GE = KH.guidanceEngine;
    if (!(await phoneAis(api, 'recipes')).length) noPhoneAi(serverSkip);
    const day = b.date ? b.date : KH.util.todayStr();
    const off = api._guidanceGate();
    if (off) return off;
    let makes = Number(b.makes);
    let wanted = [];
    let name = null;
    if (b.mode === 'change') {
      const t = api._template(b.meal_id);
      wanted = t.items.map((it) => [Number(it.food_id), Number(it.servings)]);
      makes = Number(t.servings_made || 1);
      name = String(t.name);
    }
    const ctx = guidanceCtx(api, day, { history60: false, savedMeals: false, combos: false });
    if (!api._guidanceHasTargets(ctx.profile)) return api._guidanceUnavailable('no_targets', GE.M.NO_TARGETS);
    const original = wanted.map(([id, q]) => [ctx.foods.get(id), q]);
    if (b.mode === 'change') {
      if (!original.length || original.some(([f]) => f == null)) return { status: 'unavailable', message: 'This recipe has a food that is no longer in your list.', ai_called: false };
      if (original.some(([f]) => f.hypo)) return { status: 'not_sent', message: 'This recipe has a food the app never sends to AI, so it cannot be reworked. Fit to my targets still works without AI.', ai_called: false };
    }
    const meal = b.target === 'day' ? null : (b.meal || GE.nextOpenMeal(ctx));
    const target = { kind: b.target, meal };
    const person = personHere(api);
    const condition = A.conditionText(person);
    const full = A.recipeCandidates(ctx, target, original.map(([f]) => f), new Set(b.exclude_food_ids));
    const forMeal = target.kind === 'meal' && target.meal ? target.meal : full.meal;
    const mealsLeft = target.kind === 'meal' ? GE.budget.openSlots(forMeal, ctx.day) : [];
    const request = b.mode === 'suggest' ? { mode: 'suggest', makes, dish: b.dish } : { mode: 'change', makes };
    const keep = new Set(original.map(([f]) => f.id));
    let bridge = full;
    const build = (limit) => {
      bridge = full;
      for (let trimmed = 0; ; trimmed += 1) {
        const block = b.mode === 'change' ? A.recipeChangeBlock(ctx, bridge, original, makes, target) : null;
        const text = J().dataPayload(A.recipeContext(bridge, ctx, target.kind === 'meal' ? forMeal : 'day', mealsLeft, person, request, block));
        if (text.length <= limit) return { text, ids: bridge.foods.map((f) => f.food_id).sort((x, y) => x - y), condition, trimmed };
        const removable = bridge.foods.map((f, i) => [f, i]).filter(([f]) => !keep.has(Number(f.food_id))).map(([, i]) => i);
        if (removable.length <= 1) return null;
        const foods = [...bridge.foods];
        foods.splice(removable[removable.length - 1], 1); // the lowest-ranked food that is not the recipe's own
        bridge = { ...bridge, foods };
      }
    };
    const got = await onPhone(api, 'recipes', 'recipes', build, dry);
    if (got.dry) return got.dry;
    let verdict = got.verdict;
    if (!verdict) {
      const checked = A.checkRecipes(got.raw);
      verdict = checked.ok ? A.judgeRecipes(checked.answer, ctx, target, bridge, { mode: b.mode, makes, original, name,
        providerLabel: got.provider.label, model: got.provider.model }) : { status: 'error', reason: 'schema', message: ERROR_TEXT.schema };
    }
    return phoneAnswer('recipes', b.mode, got, verdict, [...GE.M.RECIPE_NOTES, GE.M.DISCLAIMER]);
  }
  // Photos (a label, a plate, a lab report page): the server's AI only, the photo as the JPEG the page made (no location data).
  // A label or plate photo then goes to the person's own key, only while their photo switch is on. A lab report photo never does.
  const OWN_PHOTO = {
    '/api/vision/label': ['read_label', () => (raw) => {
      const checked = J().checkLabel(raw);
      return checked.ok ? J().labelDraft(checked.answer) : { status: 'error', reason: 'schema', message: ERROR_TEXT.schema };
    }],
    '/api/vision/plate': ['plate', (api) => (raw) => {
      const checked = J().checkPlate(raw);
      return checked.ok ? J().judgePlate(checked.answer, searchFor(api), checked.malformed) : { status: 'error', reason: 'schema', message: ERROR_TEXT.schema };
    }],
  };
  for (const [path, featureRoute] of [['/api/vision/label', 'photos'], ['/api/vision/plate', 'photos'], ['/api/ai/read-lab-report', 'labs']]) {
    route('POST', path, function ({ body, qp }) {
      if (!device()) fail(404, 'Not Found');
      if (!body || typeof body.arrayBuffer !== 'function') fail(415, 'Send the photo as a JPEG (Content-Type: image/jpeg).', { reason: 'not_jpeg' });
      const toBase64 = KH.mock.serverApi ? KH.mock.serverApi.base64(body) : Promise.reject(new Error('no server api'));
      return toBase64.then(async (jpeg) => {
        let got = await viaServer(this, featureRoute, 'POST', `${path}${query(qp)}`, { jpeg });
        if (got.value !== undefined) return got.value;
        const own = OWN_PHOTO[path]; // never the lab report route
        if (own) {
          const dry = qp('dry_run') === 'true';
          const mine = await viaOwnKey(this, featureRoute, own[0], { jpeg }, dry, own[1](this));
          if (mine.value !== undefined) return mine.value;
          const here = await photoOnDevice(this, own[0], jpeg, dry, own[1](this)); // the iPhone's own model (iOS 27)
          if (here !== null) return here;
          if (mine.skip === 'unreachable') fail(503, OWN_GONE, { reason: 'own_unreachable' });
        }
        if (got.skip === 'unreachable') fail(503, SERVER_GONE, { reason: 'server_unreachable' });
        return fail(404, 'Not Found');
      });
    });
  }
  // A label or plate photo on this iPhone's own model (note 39 §6.6): iOS 27 only. The photo stays on the phone. null when this
  // iPhone's model cannot read photos (the next step of the order runs); else the checked answer, as the server's route gives it.
  async function photoOnDevice(api, task, jpeg, dry, check) {
    const st = await aiStatus();
    if (!st.available || !st.photos) return null;
    if (!prefs(api).opt_in) unavailable('not_opted_in');
    if (dry) {
      return { ...dryRun(task, task, null), body: { kind: 'ai', task, jpeg: `[${jpeg.length} base64 characters]` },
        image_bytes: Math.floor((jpeg.length * 3) / 4) - (jpeg.endsWith('==') ? 2 : jpeg.endsWith('=') ? 1 : 0) };
    }
    const res = await KH.mock.device.lookup({ kind: 'ai', task, jpeg });
    if (res && res.error === 'photos_unavailable') return null;
    const got = res && res.ok === true ? { answer: res.answer } : await failed(res);
    return answer(task, got.verdict || check(got.answer));
  }

  // Ask (app/ai/routes.py chat): the server's AI only, with this phone's rows in step (see the top).
  const ASK_OFF = 'Ask is not available from your server just now.';
  const SEND_FIRST_MS = 5000;
  route('POST', '/api/ai/chat', function ({ body, qp }) {
    if (!device()) fail(404, 'Not Found');
    const dry = qp('dry_run') === 'true';
    const sent = isDict(body) ? { ...body, trust: 'ask' } : body; // the server saves nothing: Save on the card saves here
    // This phone's newest rows go first, so the assistant reads the log the person sees (waited for a few seconds at most).
    const S = KH.mock.serverSync;
    const first = S && !dry && S.status().waiting > 0
      ? Promise.race([S.run().catch(() => null), new Promise((r) => { const t = setTimeout(r, SEND_FIRST_MS); if (t && t.unref) t.unref(); })])
      : Promise.resolve();
    return first.then(() => viaServer(this, 'chat', 'POST', `/api/ai/chat${query(qp)}`, { body: sent }, { raw: true })).then((got) => {
      if (got.value !== undefined) return chatForPhone(this, got.value);
      if (got.skip === 'unreachable') fail(503, SERVER_GONE, { reason: 'server_unreachable' });
      return fail(503, ASK_OFF, { reason: 'not_available' });
    });
  });
  const NOT_HERE = (name) => `"${name}" is not on this iPhone yet, so nothing was saved. Sync this iPhone with your server in Settings → This device, then ask again.`;
  // The server's food (a card item or target: name, brand) as this phone's food id, or null.
  function phoneFood(api, item) {
    if (!isDict(item) || typeof item.name !== 'string') return null;
    return KH.mock.serverApi.foodHere(api, item.name, item.brand == null ? null : item.brand);
  }
  // A card to confirm, with this phone's food ids; { missing } with the names this phone does not have.
  function cardHere(api, card) {
    if (card.tool === 'set_food_preference') {
      const t = card.target;
      if (!isDict(t) || t.kind !== 'food') return { card }; // a food group names no row
      const id = phoneFood(api, t);
      return id == null ? { missing: [t.name] } : { card: { ...card, target: { ...t, food_id: id } } };
    }
    const list = card.tool === 'log_food' ? card.payload && card.payload.entries : card.payload && card.payload.items;
    const items = Array.isArray(card.items) ? card.items : [];
    if (!Array.isArray(list) || list.length !== items.length) return { missing: items.map((i) => i.name) };
    const ids = [];
    const missing = [];
    for (const item of items) {
      if (item.fdc_id != null && item.new_food) { ids.push(null); continue; } // a USDA food: the card's Save adds it first (imports)
      const id = phoneFood(api, item);
      if (id == null) missing.push(item.name);
      ids.push(id);
    }
    if (missing.length) return { missing };
    const named = (row, i) => (ids[i] == null ? { ...row } : { ...row, food_id: ids[i] });
    const payload = card.tool === 'log_food' ? { ...card.payload, entries: list.map(named) } : { ...card.payload, items: list.map(named) };
    return { card: { ...card, items: items.map(named), payload } };
  }
  function chatForPhone(api, answer) {
    if (!isDict(answer) || answer.dry_run || answer.kind === 'treat_low' || answer.kind === 'get_help_now') return answer; // no rows named
    const out = { ...answer, questions: [...(answer.questions || [])] };
    if (isDict(answer.pending_save)) {
      const here = cardHere(api, answer.pending_save);
      out.pending_save = here.card || null;
      for (const name of here.missing || []) out.questions.push({ food: String(name), question: NOT_HERE(String(name)) });
    }
    if ((answer.saved || []).length) { // an older server saved at once: the rows come here with the next sync
      out.saved = answer.saved.map((card) => ({ ...card, undo: null, on_server: true }));
      if (KH.mock.serverSync) KH.mock.serverSync.soon(500);
    }
    return out;
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
      return parseMealHere(this, b, qp);
    });
  });
  // keep: the fields of a matched food the server's judge shows
  const MATCH_KEYS = ['id', 'name', 'brand', 'category', 'source', 'serving_desc', 'serving_g', 'nutrients', 'flags', 'warnings', 'kidney_rating'];
  const searchFor = (api) => (words) => api._searchFoods(words, null, null, 3).map((f) => Object.fromEntries(MATCH_KEYS.map((k) => [k, f[k] === undefined ? null : f[k]])));
  // Step 2 and 3 of the order: the own key, then the iPhone's own model. The server's prefilter runs first: a low, an emergency or
  // a dose question gets the server's card and no AI is asked.
  function parseMealHere(api, b, qp) {
    const cards = J().prefilter(b.text, api._guidancePrefs().hypo_dose_g); // G7, G8, G2/G3: the AI is not asked
    if (cards) return cards;
    const dry = qp('dry_run') === 'true';
    const text = J().dataPayload(J().parseMealData(b.text));
    const check = (raw) => {
      const checked = J().checkParseMeal(raw);
      if (!checked.ok) return { status: 'error', reason: 'schema', message: ERROR_TEXT.schema };
      return J().judgeParseMeal(checked.answer, searchFor(api), checked.malformed);
    };
    return viaOwnKey(api, 'describe', 'parse_meal', { text }, dry, check).then(async (got) => {
      if (got.value !== undefined) return got.value;
      if ((got.skip === 'unreachable' || got.skip === 'identity') && !(await aiStatus()).available) {
        if (got.skip === 'identity') fail(503, OWN_IDENTITY, { reason: 'identity' });
        fail(503, OWN_GONE, { reason: 'own_unreachable' });
      }
      return parseMealOnDevice(api, b, qp);
    });
  }
  function parseMealOnDevice(api, b, qp) {
    const dry = qp('dry_run') === 'true';
    return ready(api).then(async () => {
      const text = J().dataPayload(J().parseMealData(b.text));
      if (dry) return dryRun('parse_meal', 'parse_meal', text);
      const got = await ask('parse_meal', text);
      if (got.verdict) return answer('parse_meal', got.verdict);
      const checked = J().checkParseMeal(got.answer);
      if (!checked.ok) return answer('parse_meal', { status: 'error', reason: 'schema', message: ERROR_TEXT.schema });
      return answer('parse_meal', J().judgeParseMeal(checked.answer, searchFor(api), checked.malformed));
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
