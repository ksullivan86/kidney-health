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

  // type: 'bool' | 'int' (min/max) | 'str' (minLength/maxLength, stripped) | 'choice' (options)
  const DEFS = [
    { key: 'audit.retention_days', type: 'int', min: 1, max: 3650, default: 365, scope: 'instance', env: 'AUDIT_RETENTION_DAYS',
      label: 'Keep the activity log for (days)', help: '' },
    { key: 'food.off_consent', type: 'bool', default: false, scope: 'user', env: null,
      label: 'Send barcodes I scan to Open Food Facts',
      help: 'Your own choice, used only when the admin has turned Open Food Facts lookups on.' },
    { key: 'food.off_enabled', type: 'bool', default: false, scope: 'instance', env: 'OFF_ENABLED',
      label: 'Look up barcodes with Open Food Facts',
      help: "Off by default. When on, a barcode that is not in this server's food list is looked up at world.openfoodfacts.org "
        + '(only the barcode number is sent). Product data is under the Open Database License.' },
    { key: 'instance.name', type: 'str', minLength: 1, maxLength: 80, default: 'Kidney Health', scope: 'instance', env: 'INSTANCE_NAME',
      label: 'Server name', help: "Shown on the sign-in page and in the app's title." },
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
    { key: 'ui.theme', type: 'choice', options: ['system', 'light', 'dark'], default: 'system', scope: 'user_default', env: null,
      label: 'Theme', help: '' },
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
        const v = value.trim();
        if (def.minLength != null && v.length < def.minLength) return { error: `String should have at least ${def.minLength} character${def.minLength === 1 ? '' : 's'}` };
        if (def.maxLength != null && v.length > def.maxLength) return { error: `String should have at most ${def.maxLength} characters` };
        return { value: v };
      }
      case 'choice':
        return def.options.includes(value) ? { value } : { error: choiceMessage(def.options) };
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
