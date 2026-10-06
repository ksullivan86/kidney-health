/* Kidney Diet Log — demo API: settings and keys (twin of the settings and key routes in
   app/auth/me.py and app/auth/admin_api.py, over app/settings_store.py and app/credentials.py).

   Values live in memory, with the precedence of js/engine/settings.js (env lock > own value >
   instance value > default). The demo "server" locks one key the way an environment variable
   would: OFF_ENABLED=true, because its barcode lookups answer from three products recorded from Open
   Food Facts (js/mock/barcode.js) and never contact Open Food Facts; each person still has to agree
   (food.off_consent) as on a real server. Keys are write-only
   as on the server: only "set", the last four characters of a key of 20 or more characters and
   the time are kept, never the key itself, and the demo never contacts USDA (no key test). */
(() => {
  'use strict';
  const KH = window.KH;
  const M = KH.mock;
  const S = KH.settings;
  const { route, MockApi, fail } = M;

  const DEMO_ENV = { OFF_ENABLED: 'true' };
  const LAST4_MIN_LENGTH = 20;
  const PROVIDERS = { usda: { label: 'USDA FoodData Central', prefix: 'providers.usda' } };

  function validateApiKey(value) {
    if (typeof value !== 'string') return 'the key must be text';
    if (value.length < 8 || value.length > 512) return 'the key must be 8 to 512 characters long';
    for (const ch of value) { const c = ch.codePointAt(0); if (c < 33 || c > 126) return 'the key must be printable ASCII without spaces'; }
    return null;
  }

  Object.assign(MockApi.prototype, {
    _settingsState() {
      if (!this._settings) this._settings = { env: { ...DEMO_ENV }, instance: {}, users: {}, own: {}, shared: null };
      return this._settings;
    },
    _settingsCtx(userId) {
      const st = this._settingsState();
      return { env: st.env, instance: st.instance, user: userId == null ? null : (st.users[userId] || {}) };
    },
    _effectiveSetting(key, userId) { return S.effective(S.BY_KEY[key], this._settingsCtx(userId)); },
    _settingDef(key) {
      const def = S.BY_KEY[key];
      if (!def) fail(400, `unknown setting '${key}'`);
      return def;
    },
    // PATCH bodies: validate every key first, then write all (settings_store.update_user / update_instance).
    _patchSettings(body, { admin, userId }) {
      if (!M.isDict(body)) fail(400, 'Input should be a valid dictionary');
      const st = this._settingsState();
      const writes = [];
      for (const [key, value] of Object.entries(body)) {
        const def = this._settingDef(key);
        if (admin ? !S.adminEditable(def) : !S.userEditable(def)) fail(403, admin ? `${key} is a personal setting` : `${key} can only be changed by an admin`);
        if (def.env && st.env[def.env] != null && String(st.env[def.env]).trim() !== '') fail(409, `${key} is set by the server (${def.env})`, { locked_by_env: def.env });
        if (value === null) { writes.push([key, null]); continue; }
        const r = S.validate(def, value);
        if (r.error) fail(400, `${key}: ${r.error}`);
        writes.push([key, r.value]);
      }
      const changed = [];
      for (const [key, value] of writes) {
        const target = admin ? st.instance : (st.users[userId] || (st.users[userId] = {}));
        const old = this._effectiveSetting(key, admin ? null : userId).value;
        if (value === null) delete target[key]; else target[key] = value;
        const now = this._effectiveSetting(key, admin ? null : userId).value;
        if (JSON.stringify(old) !== JSON.stringify(now)) changed.push([key, old, now]);
      }
      return changed;
    },
    _ownKey(userId, provider) { return (this._settingsState().own[userId] || {})[provider] || null; },
    _keyStatus(secret) {
      if (!secret) return { set: false };
      const out = { set: true, updated_at: secret.updated_at };
      if (secret.last4) out.last4 = secret.last4;
      return out;
    },
    // me.key_item: what a person sees about a provider's keys.
    _keyItem(user, provider) {
      const p = PROVIDERS[provider];
      const val = (name) => this._effectiveSetting(`${p.prefix}.${name}`, null).value;
      const allowed = !!val('user_keys_allowed');
      const own = this._keyStatus(this._ownKey(user.id, provider));
      const sharedSet = !!this._settingsState().shared;
      const sharedOn = sharedSet && !!val('shared_enabled') && !!user.can_use_shared;
      const limit = Number(val('daily_limit_per_user')) || 0;
      const remaining = limit ? limit : null; // the demo makes no lookups, so nothing is used today
      let effective = 'none';
      if (allowed && own.set) effective = 'own';
      else if (sharedOn && (remaining == null || remaining > 0)) effective = 'shared';
      return { provider, label: p.label, own, shared: { available: sharedOn, remaining_today: remaining, daily_limit: limit || null },
        user_keys_allowed: allowed, effective };
    },
    _sharedItem(provider) {
      const secret = this._settingsState().shared;
      const shared = this._keyStatus(secret);
      if (shared.set) Object.assign(shared, { source: 'db', locked: false });
      return { provider, label: PROVIDERS[provider].label, shared };
    },
    _readKeyBody(body) {
      if (!M.isDict(body)) fail(400, 'Field required');
      if (!Object.prototype.hasOwnProperty.call(body, 'api_key')) fail(400, 'api_key: Field required');
      const key = body.api_key;
      if (typeof key !== 'string') fail(400, 'api_key: Input should be a valid string');
      if (!key) fail(400, 'api_key: Value should have at least 1 item after validation, not 0');
      const problem = validateApiKey(key);
      if (problem) fail(400, `api_key: ${problem}`, { field: 'api_key' });
      // Keep only what the server keeps in clear: the hint and the time. The key itself is dropped here.
      return { last4: key.length >= LAST4_MIN_LENGTH ? key.slice(-4) : null, updated_at: this._stamp() };
    },
  });

  const provider = (id) => {
    const slug = decodeURIComponent(id);
    if (!PROVIDERS[slug]) fail(404, `unknown provider '${slug.slice(0, 40)}'`);
    return slug;
  };

  // ---- /api/me/settings, /api/me/keys
  route('GET', '/api/me/settings', function () {
    const u = this._currentUser();
    return { settings: S.userView(this._settingsCtx(u.id)) };
  });
  route('PATCH', '/api/me/settings', function ({ body }) {
    const u = this._currentUser();
    this._patchSettings(body, { admin: false, userId: u.id });
    return { settings: S.userView(this._settingsCtx(u.id)) };
  });
  route('GET', '/api/me/keys', function () {
    const u = this._currentUser();
    return { providers: Object.keys(PROVIDERS).map((p) => this._keyItem(u, p)) };
  });
  route('PUT', /^\/api\/me\/keys\/([^/]+)$/, function ({ id, body }) {
    const u = this._currentUser();
    this._requireRecent();
    const slug = provider(id);
    if (!this._effectiveSetting(`${PROVIDERS[slug].prefix}.user_keys_allowed`, null).value) fail(403, 'Your admin has turned off personal keys for this provider.');
    const secret = this._readKeyBody(body);
    const st = this._settingsState();
    (st.own[u.id] || (st.own[u.id] = {}))[slug] = secret;
    this._audit(u.id, 'secret.set', 'secret', slug, { provider: slug, scope: 'user' });
    return this._keyItem(u, slug); // no "test": the demo never contacts USDA
  });
  route('DELETE', /^\/api\/me\/keys\/([^/]+)$/, function ({ id }) {
    const u = this._currentUser();
    this._requireRecent();
    const slug = provider(id);
    const own = this._settingsState().own[u.id];
    if (own && own[slug]) { delete own[slug]; this._audit(u.id, 'secret.removed', 'secret', slug, { provider: slug, scope: 'user' }); }
    return null;
  });

  // ---- /api/admin/settings, /api/admin/keys
  route('GET', '/api/admin/settings', function () {
    this._requireAdmin();
    return { settings: S.adminView(this._settingsCtx(null)) };
  });
  route('PATCH', '/api/admin/settings', function ({ body }) {
    const admin = this._requireAdmin();
    this._requireRecent();
    const changed = this._patchSettings(body, { admin: true, userId: null });
    for (const [key, old, now] of changed) this._audit(admin.id, 'settings.changed', 'setting', key, { key, old, new: now });
    return { settings: S.adminView(this._settingsCtx(null)) };
  });
  route('GET', '/api/admin/keys', function () {
    this._requireAdmin();
    return { providers: Object.keys(PROVIDERS).map((p) => this._sharedItem(p)) };
  });
  route('PUT', /^\/api\/admin\/keys\/([^/]+)$/, function ({ id, body }) {
    const admin = this._requireAdmin();
    this._requireRecent();
    const slug = provider(id);
    this._settingsState().shared = this._readKeyBody(body);
    this._audit(admin.id, 'secret.set', 'secret', slug, { provider: slug, scope: 'shared' });
    return this._sharedItem(slug);
  });
  route('DELETE', /^\/api\/admin\/keys\/([^/]+)$/, function ({ id }) {
    const admin = this._requireAdmin();
    this._requireRecent();
    const slug = provider(id);
    if (this._settingsState().shared) {
      this._settingsState().shared = null;
      this._audit(admin.id, 'secret.removed', 'secret', slug, { provider: slug, scope: 'shared' });
    }
    return null;
  });

  Object.assign(M, { DEMO_ENV, validateApiKey });
})();
