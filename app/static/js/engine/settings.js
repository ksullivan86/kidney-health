/* Kidney Diet Log — settings registry and precedence: the browser twin of app/settings_registry.py
   and the read side of app/settings_store.py (note 07 §4.11).

   The Settings view uses DEFS for labels, help texts and the choices of each key (the server's
   GET /api/admin/settings sends only values, sources and locks); the demo API (js/mock/settings.js)
   uses the same table and the precedence functions below to answer like the server.

   Precedence: env lock (read-only, source "env") > the person's own value (scopes user and
   user_default) > the instance value > the registry default.

   Parity: tests/data/settings_vectors.json is generated from the Python registry and store
   (tests/data/gen_settings_vectors.py); pytest checks it is current and node
   tests/js/run_vectors.mjs replays it against this file. Plain script, no DOM: it also runs in
   a bare V8 context. */
(() => {
  'use strict';
  const root = typeof window !== 'undefined' ? window : globalThis;
  const KH = root.KH || (root.KH = {});

  // type: 'bool' | 'int' (min/max) | 'str' (minLength/maxLength/pattern, stripped unless strip: false) | 'choice' (options) |
  //       'object' (a pydantic model with extra="forbid": `fields`, each a scalar type above or 'list' of one)
  const DEFS = [
    // Optional AI (note 04 R4, §9 A5–A7; app/settings_registry.py "Note 04"). Providers and keys are rows of
    // ai_providers, never settings: the person's `ai` object has no key field (§9 A6).
    { key: 'ai', type: 'object', model: 'AiPreferences', scope: 'user', env: null,
      default: { opt_in: false, provider: 'auto', share_age_sex: false, preferences: '' },
      fields: [
        { name: 'opt_in', type: 'bool', default: false },
        { name: 'provider', type: 'str', pattern: '^(auto|own|shared:[1-9][0-9]{0,17})$', strip: false, default: 'auto' },
        { name: 'share_age_sex', type: 'bool', default: false },
        { name: 'preferences', type: 'str', maxLength: 200, default: '' },
      ],
      label: 'AI ideas', help: 'opt_in, provider (auto, own or shared:<id>), share_age_sex and preferences (at most 200 characters).' },
    { key: 'ai.allow_user_base_url', type: 'bool', default: false, scope: 'instance', env: 'AI_ALLOW_USER_BASE_URL',
      label: 'People may enter their own AI server address', help: 'Only https on port 443 to public addresses. Off by default; always off when AI_HTTP_PROXY is set.' },
    { key: 'ai.audit_retention_days', type: 'int', min: 0, max: 365, default: 30, scope: 'instance', env: 'AI_AUDIT_RETENTION_DAYS',
      label: 'Keep what was sent to and received from AI for (days)', help: 'Each person sees their own AI activity in Settings. 0 keeps only the time, provider and outcome. Backups keep it until they expire.' },
    { key: 'ai.enabled', type: 'bool', default: false, scope: 'instance', env: 'AI_ENABLED',
      label: 'Optional AI ideas', help: 'Off by default. When on, people who opt in can ask an AI provider you set up for meal ideas and photo help. The rules always run first and check every AI idea; nothing is sent anywhere while this is off.' },
    { key: 'ai.max_concurrency', type: 'int', min: 1, max: 32, default: 2, scope: 'instance', env: 'AI_MAX_CONCURRENCY',
      label: 'AI calls at the same time (whole server)', help: 'Each person has at most one call running. Extra calls are told to try again in a few seconds.' },
    { key: 'ai.shared_daily_limit', type: 'int', min: 0, max: 100000, default: 30, scope: 'instance', env: 'AI_SHARED_DAILY_LIMIT',
      label: 'Shared AI calls per person per day', help: 'Counts meal ideas, described meals, photos and connection tests on shared providers. 0 means unlimited.' },
    { key: 'ai.user_keys_allowed', type: 'bool', default: true, scope: 'instance', env: 'AI_ALLOW_USER_KEYS',
      label: 'People may use their own AI key', help: 'For OpenAI, OpenRouter or Nous Portal. Their key is encrypted and never shown again.' },
    { key: 'ai.vision_allow_agent', type: 'bool', default: false, scope: 'instance', env: 'AI_VISION_ALLOW_AGENT',
      label: 'Allow photos to go to a Hermes agent', help: 'Off by default. Text printed on a package could try to instruct an agent; even when on, the app only uses a Hermes profile whose tool check passes.' },
    { key: 'ai.vision_plate_enabled', type: 'bool', default: false, scope: 'instance', env: 'AI_VISION_PLATE_ENABLED',
      label: 'Plate photos (AI estimate of what is on a plate)', help: 'Off by default. Needs a provider with a vision model. Portion estimates from photos are rough: the app says so on every result and never logs them without a tap.' },
    { key: 'audit.retention_days', type: 'int', min: 1, max: 3650, default: 365, scope: 'instance', env: 'AUDIT_RETENTION_DAYS',
      label: 'Keep the activity log for (days)', help: '' },
    { key: 'food.barcode_negative_ttl_hours', type: 'int', min: 1, max: 720, default: 24, scope: 'instance', env: 'BARCODE_NEGATIVE_TTL_HOURS',
      label: 'Remember barcodes that were not found for (hours)',
      help: 'A barcode that Open Food Facts or USDA did not know is not asked again for this long.' },
    { key: 'food.off_consent', type: 'bool', default: false, scope: 'user', env: null,
      label: 'Send barcodes I scan to Open Food Facts',
      help: 'Your own choice, used only when the admin has turned Open Food Facts lookups on.' },
    { key: 'food.off_contact', type: 'str', minLength: 3, maxLength: 200, pattern: '^[\\x20-\\x27\\x2a-\\x5b\\x5d-\\x7e]+$',
      default: 'https://github.com/ksullivan86/kidney-health', scope: 'instance', env: 'OFF_CONTACT',
      label: 'Contact sent to Open Food Facts',
      help: 'Goes into the User-Agent of every lookup, as Open Food Facts asks of API users. An admin email address is better than '
        + 'the default project address. Letters, digits and punctuation only (no round brackets or backslash).' },
    { key: 'food.off_enabled', type: 'bool', default: false, scope: 'instance', env: 'OFF_ENABLED',
      label: 'Look up barcodes with Open Food Facts',
      help: "Off by default. When on, a barcode that is not in this server's food list is looked up at world.openfoodfacts.org "
        + '(only the barcode number is sent). Product data is under the Open Database License.' },
    { key: 'food.off_rate_per_minute', type: 'int', min: 1, max: 15, default: 10, scope: 'instance', env: 'OFF_RATE_PER_MINUTE',
      label: 'Open Food Facts lookups per minute (whole server)',
      help: 'Open Food Facts allows 15 product lookups a minute from one address and may block an address that sends more. '
        + 'Everyone on this server shares this budget; products already looked up do not count.' },
    { key: 'food.usda_branded_barcode', type: 'bool', default: true, scope: 'instance', env: 'USDA_BRANDED_BARCODE',
      label: 'Also look barcodes up in USDA FoodData Central',
      help: "Uses the person's USDA key or the shared one, when Open Food Facts does not know a product, has no nutrition facts "
        + 'for it, or lacks potassium or sodium for a US product.' },
    // Meal guidance (note 06 §4.14; app/settings_registry.py GuidancePreferences). "Not for me" foods are not here:
    // they are rows of food_preferences (PUT/DELETE /api/guidance/not-for-me/{food_id}).
    { key: 'guidance', type: 'object', model: 'GuidancePreferences', scope: 'user', env: null,
      default: { enabled: true, carb_tolerance_g: 10, hypo_dose_g: 15, exclude_categories: [], show_plan_builder: true, show_insights: true, ai_enrich: false },
      fields: [
        { name: 'enabled', type: 'bool', default: true },
        { name: 'carb_tolerance_g', type: 'int', min: 5, max: 20, default: 10 },
        { name: 'hypo_dose_g', type: 'int', min: 5, max: 30, default: 15 },
        { name: 'exclude_categories', type: 'list', item: { type: 'str', minLength: 1, maxLength: 100 }, maxItems: 50, unique: true, default: [] },
        { name: 'show_plan_builder', type: 'bool', default: true },
        { name: 'show_insights', type: 'bool', default: true },
        { name: 'ai_enrich', type: 'bool', default: false },
      ],
      label: 'Meal guidance preferences', help: 'carb_tolerance_g (5–20) and hypo_dose_g (5–30) come from your diabetes team.' },
    { key: 'guidance.beam_width', type: 'int', min: 1, max: 64, default: 16, scope: 'instance', env: 'GUIDANCE_BEAM_WIDTH',
      label: 'Plan builder: search width', help: 'Partial meals kept at each step. 8 is about 15 % faster and finds slightly worse meals.' },
    { key: 'guidance.enabled', type: 'bool', default: true, scope: 'instance', env: 'GUIDANCE_ENABLED',
      label: 'Meal guidance', help: 'Rule-based suggestions for the next meal, swap ideas, plan-the-day and insights. Works without AI.' },
    { key: 'guidance.pool_per_role', type: 'int', min: 20, max: 2000, default: 200, scope: 'instance', env: 'GUIDANCE_POOL_PER_ROLE',
      label: 'Plan builder: foods considered per role',
      help: 'Lower it (for example to 120) if planning a day is slow on a small server such as a Raspberry Pi 4.' },
    { key: 'instance.name', type: 'str', minLength: 1, maxLength: 80, default: 'Kidney Health', scope: 'instance', env: 'INSTANCE_NAME',
      label: 'Server name', help: 'Shown on the sign-in, invite and password pages, and in Settings under About & privacy.' },
    { key: 'providers.usda.daily_limit_per_user', type: 'int', min: 0, max: 100000, default: 200, scope: 'instance', env: 'USDA_SHARED_DAILY_LIMIT',
      label: 'Shared USDA lookups per person per day', help: '0 means unlimited.' },
    { key: 'providers.usda.shared_enabled', type: 'bool', default: true, scope: 'instance', env: null,
      label: "Share the server's USDA key", help: 'Effective only when a shared key is set.' },
    { key: 'providers.usda.user_keys_allowed', type: 'bool', default: true, scope: 'instance', env: null,
      label: 'People may add their own USDA key', help: '' },
    { key: 'registration.invite_ttl_days', type: 'int', min: 1, max: 90, default: 7, scope: 'instance', env: null,
      label: 'Invite links expire after (days)', help: '' },
    { key: 'registration.mode', type: 'choice', options: ['invite', 'closed', 'open'], default: 'invite', scope: 'instance', env: 'REGISTRATION_MODE',
      label: 'Registration',
      help: 'invite: admins send single-use links. closed: admins create accounts. open: anyone who reaches the page can register (HTTPS required).' },
    // Personalised targets and labs (note 05 §4.9; app/settings_registry.py).
    { key: 'targets.default_activity', type: 'choice', options: ['inactive', 'low_active', 'active', 'very_active'], default: 'inactive', scope: 'instance', env: null,
      label: 'Activity level used until a person chooses theirs', help: 'Used for the calorie estimate (2023 Dietary Reference Intakes).' },
    { key: 'targets.lab_fresh_days.albumin', type: 'int', min: 1, max: 365, default: 180, scope: 'instance', env: null,
      label: 'An albumin result counts for (days)', help: '' },
    { key: 'targets.lab_fresh_days.bicarbonate', type: 'int', min: 1, max: 365, default: 180, scope: 'instance', env: null,
      label: 'A bicarbonate result counts for (days)', help: '' },
    { key: 'targets.lab_fresh_days.phosphate', type: 'int', min: 1, max: 365, default: 90, scope: 'instance', env: null,
      label: 'A phosphate result counts for (days)', help: '' },
    { key: 'targets.lab_fresh_days.potassium', type: 'int', min: 1, max: 365, default: 90, scope: 'instance', env: null,
      label: 'A potassium result counts for (days)', help: '' },
    { key: 'targets.lab_rules_enabled', type: 'bool', default: true, scope: 'instance', env: null,
      label: 'Let lab results change suggested targets',
      help: 'Off: potassium and phosphorus suggestions use the stage defaults and lab notes are left out. The warning for a very high '
        + 'potassium result is always shown. Keep it off on public demo servers until a clinician has reviewed the lab rules.' },
    { key: 'ui.theme', type: 'choice', options: ['system', 'light', 'dark'], default: 'system', scope: 'user_default', env: null,
      label: 'Theme', help: '' },
    { key: 'user.units.labs', type: 'choice', options: ['us', 'si'], default: 'us', scope: 'user_default', env: null,
      label: 'Units for lab results',
      help: 'us: mg/dL (creatinine, phosphate), g/dL (albumin), mg/g (urine albumin), % (HbA1c). si: µmol/L, mmol/L, g/L, mg/mmol, '
        + 'mmol/mol. Only the unit offered first changes; any unit can still be entered.' },
  ];
  const BY_KEY = Object.fromEntries(DEFS.map((d) => [d.key, d]));

  const userEditable = (d) => d.scope === 'user' || d.scope === 'user_default';
  const adminEditable = (d) => d.scope === 'instance' || d.scope === 'user_default';

  // What the UI calls each source (note 07 §4.11; the handbook's "Settings the server locks").
  const SOURCE_LABEL = {
    env: 'Set by the server',
    user: 'Your choice',
    instance: 'Set by your admin',
    default: 'App default',
  };

  function choiceMessage(options) {
    const opts = options.map((o) => `'${o}'`);
    return `Input should be ${opts.length > 1 ? `${opts.slice(0, -1).join(', ')} or ${opts[opts.length - 1]}` : opts[0]}`;
  }
  const BOOL_TRUE = ['1', 'on', 't', 'true', 'y', 'yes'];
  const BOOL_FALSE = ['0', 'off', 'f', 'false', 'n', 'no'];
  // The key's pydantic type in lax mode, as TypeAdapter.validate_python applies it to a JSON value:
  // returns { value } or { error } (the server's InvalidSettingValue text without the "key: " prefix).
  function validate(def, value) {
    switch (def.type) {
      case 'bool': {
        if (typeof value === 'boolean') return { value };
        if (value === 0 || value === 1) return { value: value === 1 };
        if (typeof value === 'number') return { error: Number.isInteger(value) ? 'Input should be a valid boolean, unable to interpret input' : 'Input should be a valid boolean' };
        if (typeof value === 'string') {
          const low = value.trim().toLowerCase();
          if (BOOL_TRUE.includes(low)) return { value: true };
          if (BOOL_FALSE.includes(low)) return { value: false };
          return { error: 'Input should be a valid boolean, unable to interpret input' };
        }
        return { error: 'Input should be a valid boolean' };
      }
      case 'int': {
        let n = value;
        if (typeof value === 'boolean') n = value ? 1 : 0;
        else if (typeof value === 'string') {
          const t = value.trim();
          if (!/^[+-]?\d(?:_?\d)*(?:\.0+)?$/.test(t)) return { error: 'Input should be a valid integer, unable to parse string as an integer' };
          n = Number(t.replace(/_/g, '').replace(/\.0+$/, ''));
        } else if (typeof value !== 'number' || !Number.isFinite(value)) return { error: 'Input should be a valid integer' };
        if (!Number.isInteger(n)) return { error: 'Input should be a valid integer, got a number with a fractional part' };
        if (def.min != null && n < def.min) return { error: `Input should be greater than or equal to ${def.min}` };
        if (def.max != null && n > def.max) return { error: `Input should be less than or equal to ${def.max}` };
        return { value: n };
      }
      case 'str': {
        if (typeof value !== 'string') return { error: 'Input should be a valid string' };
        const v = def.strip === false ? value : value.trim();
        if (def.minLength != null && v.length < def.minLength) return { error: `String should have at least ${def.minLength} character${def.minLength === 1 ? '' : 's'}` };
        if (def.maxLength != null && v.length > def.maxLength) return { error: `String should have at most ${def.maxLength} characters` };
        if (def.pattern != null && !new RegExp(def.pattern).test(v)) return { error: `String should match pattern '${def.pattern}'` };
        return { value: v };
      }
      case 'choice':
        return def.options.includes(value) ? { value } : { error: choiceMessage(def.options) };
      case 'list': {
        if (!Array.isArray(value)) return { error: 'Input should be a valid list' };
        const errors = [];
        let out = [];
        for (const item of value) {
          const r = validate(def.item, item);
          if (r.error) errors.push(r.error); else out.push(r.value);
        }
        if (errors.length) return { error: errors.join('; ') };
        if (def.maxItems != null && out.length > def.maxItems) {
          return { error: `List should have at most ${def.maxItems} item${def.maxItems === 1 ? '' : 's'} after validation, not ${out.length}` };
        }
        if (def.unique) out = out.filter((x, i) => out.indexOf(x) === i);
        return { value: out };
      }
      case 'object': {
        // pydantic: every field's errors in field order, then one per unknown key in input order, joined by "; ".
        if (value == null || typeof value !== 'object' || Array.isArray(value)) {
          return { error: `Input should be a valid dictionary or instance of ${def.model}` };
        }
        const errors = [];
        const out = {};
        for (const f of def.fields) {
          if (!Object.prototype.hasOwnProperty.call(value, f.name)) { out[f.name] = JSON.parse(JSON.stringify(f.default)); continue; }
          const r = validate(f, value[f.name]);
          if (r.error) errors.push(r.error); else out[f.name] = r.value;
        }
        for (const k of Object.keys(value)) if (!def.fields.some((f) => f.name === k)) errors.push('Extra inputs are not permitted');
        return errors.length ? { error: errors.join('; ') } : { value: out };
      }
      default:
        return { value };
    }
  }

  // An env lock's text as the server parses it (validate_strings): "true"/"false"/"1"/"0"/... for
  // bools, digits for ints, the stripped text otherwise. { value } or { error }.
  function parseEnv(def, raw) {
    const t = String(raw).trim();
    if (def.type === 'bool') {
      const low = t.toLowerCase();
      if (BOOL_TRUE.includes(low)) return { value: true };
      if (BOOL_FALSE.includes(low)) return { value: false };
      return { error: 'Input should be a valid boolean, unable to interpret input' };
    }
    if (def.type === 'int') return /^[+-]?\d+$/.test(t) ? validate(def, Number(t)) : { error: 'Input should be a valid integer' };
    return validate(def, t);
  }

  // ctx = { env: {ENV_NAME: text}, instance: {key: value}, user: {key: value} | null }
  // → { value, source, locked, env }
  function effective(def, ctx) {
    const env = (ctx && ctx.env) || {};
    if (def.env && env[def.env] != null && String(env[def.env]).trim() !== '') {
      const parsed = parseEnv(def, env[def.env]);
      if (!parsed.error) return { value: parsed.value, source: 'env', locked: true, env: def.env };
    }
    const user = ctx && ctx.user;
    if (user && userEditable(def) && Object.prototype.hasOwnProperty.call(user, def.key)) {
      const v = validate(def, user[def.key]);
      if (!v.error) return { value: v.value, source: 'user', locked: false, env: def.env || null };
    }
    const inst = (ctx && ctx.instance) || {};
    if (Object.prototype.hasOwnProperty.call(inst, def.key)) {
      const v = validate(def, inst[def.key]);
      if (!v.error) return { value: v.value, source: 'instance', locked: false, env: def.env || null };
    }
    return { value: def.default, source: 'default', locked: false, env: def.env || null };
  }
  // GET /api/me/settings → settings
  function userView(ctx, defs = DEFS) {
    const out = {};
    for (const d of [...defs].sort((a, b) => (a.key < b.key ? -1 : 1))) {
      if (!userEditable(d)) continue;
      const e = effective(d, ctx);
      out[d.key] = { value: e.value, source: e.source, editable: !e.locked };
    }
    return out;
  }
  // GET /api/admin/settings → settings (instance view: no person's own values)
  function adminView(ctx, defs = DEFS) {
    const out = {};
    for (const d of [...defs].sort((a, b) => (a.key < b.key ? -1 : 1))) {
      if (!adminEditable(d)) continue;
      const e = effective(d, { env: ctx && ctx.env, instance: ctx && ctx.instance, user: null });
      out[d.key] = { value: e.value, source: e.source, locked_by_env: e.locked ? d.env : null, scope: d.scope };
    }
    return out;
  }

  KH.settings = { DEFS, BY_KEY, SOURCE_LABEL, userEditable, adminEditable, validate, parseEnv, effective, userView, adminView, choiceMessage };
})();
