/* Kidney Diet Log — device mode only: the person's profile, targets, account settings and food preferences come from their server
   (design note 39 §8.1, D5, plan step 8; ARCHITECTURE.md "Device mode"; guide docs/push.md "What the iPhone app does with it").

   With a token both ways (js/mock/server_changes.js `active`), these belong to the server, because a Care team member may set them
   and a stale copy on the phone must never overwrite them (note 02). So:
   * Each sync run reads them through the gateway (at most every few minutes, and at once after Sync now or a change):
       GET /push/v1/api/profile                  the profile and targets: copied into this phone's profile
       GET /push/v1/api/me/settings              the account settings of ACCOUNT_KEYS: copied into this phone's own settings
       GET /push/v1/api/guidance/preferences     the food preferences ("Like", "Less often", "Not for me"), each food found here
                                                 by GET /push/v1/api/foods/{id} (its source and keys) and remembered
     The phone works offline from these copies, as before.
   * A change made on the phone goes straight to the server's own route through the gateway, which checks it as for the web app:
       PUT /api/profile, PATCH /api/me/settings (only ACCOUNT_KEYS), PUT and DELETE /api/guidance/preferences/{food_id} (and the
       older "Not for me" routes). The answer is copied here. Offline, or with the server's answer an error, nothing changes here and
       the screen says so: "This needs a connection to your server." A food the server does not know yet is found by
       GET /push/v1/api/foods?q=… (its name), else the change waits for the next sync.
   * The first time (note 39 §8.7 point 5): when this phone's profile and targets differ from the server's, one card shows both.
     The server's is shown until the person picks: "Keep your server's", or "Keep this iPhone's", which sends this phone's to the
     server. Food preferences only this phone had are sent to the server once, so nothing the person said is lost.
   * This iPhone's own settings stay on the phone: the theme, the camera choice, its Open Food Facts switch, its keys and services,
     the lock. The "OK to repeat" and "Not this meal" marks name rows by this phone's ids, so they stay too.
   On a phone that is not paired both ways, nothing here runs: the phone owns everything, as before.

   Saved with the rest of the log (js/mock/persist.js), in `_serverAccount`:
       { v: 1, account, pulledAt, profile: true once the server's profile was read, prefs: true once the preferences were,
         card: null | { server: <profile fields>, mine: <profile fields>, at }, foodIds: { <server food id>: <this phone's food id> },
         message: null | 'the last problem, in words' }
   No DOM. */
(() => {
  'use strict';
  const KH = window.KH;
  const M = KH.mock;
  if (!KH.flags || KH.flags.DEVICE !== true || !M) return;

  // The account settings that come from the server (app/settings_registry.py, scope "user"). Every other one stays on the phone.
  const ACCOUNT_KEYS = ['user.units.labs', 'user.units.weight', 'body.weight_alarm', 'body.bp_goal', 'guidance'];
  // Parts of `guidance` that name this phone's rows by their ids here: they stay on the phone and are never sent.
  const LOCAL_GUIDANCE = ['repeat_ok_foods', 'repeat_ok_meals', 'hidden_usual_meals'];
  // The fields of PUT /api/profile (models.ProfileUpdate) that the person edits.
  const PROFILE_FIELDS = ['name', 'weight_kg', 'height_cm', 'ckd_stage', 'dialysis', 'diabetes', 'warn_fraction', 'about_tolerance_pct',
    'dialysis_days', 'week_start', 'targets', 'birth_month', 'sex', 'activity', 'transplant_date', 'frail_or_sarcopenic',
    'weight_6_months_ago_kg', 'pregnant_or_breastfeeding', 'hyperkalemia_history', 'urine_output_ml', 'pd_uf_ml', 'pd_dialysate_kcal'];
  const PULL_EVERY_MS = 5 * 60 * 1000;
  const MAX_LOOKUPS = 40; // foods looked up in one run; the rest follow in the next
  const NEEDS_SERVER = 'This needs a connection to your server.';
  const NOT_THERE_YET = 'This food is not on your server yet. Try again after the next sync.';
  const isDict = (v) => v != null && typeof v === 'object' && !Array.isArray(v);

  const listeners = new Set();
  const emit = () => { for (const fn of [...listeners]) { try { fn(); } catch (e) { /* a view that threw must not stop syncing */ } } };

  function blank() { return { v: 1, account: null, pulledAt: null, profile: false, prefs: false, card: null, foodIds: {}, message: null }; }
  function stateOf(api) {
    if (!isDict(api._serverAccount)) api._serverAccount = blank();
    const st = api._serverAccount;
    if (!isDict(st.foodIds)) st.foodIds = {};
    return st;
  }
  const C = () => M.serverChanges || null;
  function active(api = M.instance) { try { return !!(api && C() && C().active(api)); } catch (e) { return false; } }
  const accountOf = () => { const k = M.serverApi && M.serverApi.status(); return k && k.about ? k.about.account || null : null; };
  const uidOf = (api) => { try { return api._currentUser().id; } catch (e) { return 1; } };
  async function save(api) {
    if (typeof M.onWrite === 'function') M.onWrite(api, 'PUT', '/api/device/server-account');
    if (!M.local || !M.local.on()) return true;
    const s = await M.local.flush();
    return !(s && (s.error || s.conflict));
  }
  // The server's answer, or null with the reason kept for the screen.
  async function get(st, path) {
    const res = await M.serverApi.call('GET', path);
    if (res.offline) { st.message = 'Your server could not be reached. Your profile and settings are the ones it sent last.'; return null; }
    if (res.error || res.status !== 200 || !isDict(res.json)) {
      st.message = res.status === 404 ? 'Your server cannot share your profile and settings with the app yet. Ask whoever runs it to update it.'
        : 'Your server could not send your profile and settings just now. The app tries again later.';
      return null;
    }
    return res.json;
  }

  // ---- the profile and targets ----
  function pick(view) {
    const out = {};
    for (const k of PROFILE_FIELDS) {
      const v = view[k];
      out[k] = v === undefined ? null : JSON.parse(JSON.stringify(v));
    }
    return out;
  }
  function sortedJson(v) {
    if (Array.isArray(v)) return `[${v.map(sortedJson).join(',')}]`;
    if (isDict(v)) return `{${Object.keys(v).sort().map((k) => `${JSON.stringify(k)}:${sortedJson(v[k])}`).join(',')}}`;
    return JSON.stringify(v === undefined ? null : v);
  }
  const same = (a, b) => sortedJson(a) === sortedJson(b);
  // Whether the person set anything in this phone's profile (an untouched one is never worth a question).
  function hasProfile(view) {
    return !!(view.ckd_stage_chosen || view.diabetes_chosen || (view.name && String(view.name).trim()) || view.weight_kg != null
      || Object.keys(view.targets || {}).length);
  }
  function applyProfile(api, server) {
    const p = api._profile;
    for (const k of PROFILE_FIELDS) {
      if (!(k in server)) continue;
      p[k] = k === 'targets' || k === 'dialysis_days' ? JSON.parse(JSON.stringify(server[k] || (k === 'targets' ? {} : []))) : server[k];
    }
    p.ckd_stage_chosen = server.ckd_stage_chosen !== false;
    p.diabetes_chosen = server.diabetes_chosen !== false;
    if (server.updated_at) p.updated_at = server.updated_at;
  }
  // What the phone sends for "Keep this iPhone's": every field, and every target the server has that this phone does not, as null
  // (not tracked), so the server ends up with exactly this phone's targets.
  function profileBody(mine, server) {
    const body = pick(mine);
    const targets = { ...(body.targets || {}) };
    for (const k of Object.keys((server && server.targets) || {})) if (!(k in targets)) targets[k] = null;
    body.targets = targets;
    for (const k of ['name', 'ckd_stage', 'dialysis', 'diabetes', 'warn_fraction', 'week_start']) if (body[k] == null) delete body[k];
    return body;
  }

  // ---- the account settings ----
  function applySettings(api, view) {
    const all = isDict(view.settings) ? view.settings : {};
    const users = api._settingsState().users;
    const uid = uidOf(api);
    const mine = users[uid] || (users[uid] = {});
    for (const key of ACCOUNT_KEYS) {
      const item = all[key];
      if (!isDict(item) || !('value' in item)) continue;
      if (key === 'guidance') {
        const here = isDict(mine.guidance) ? mine.guidance : {};
        const kept = LOCAL_GUIDANCE.filter((f) => Array.isArray(here[f]) && here[f].length);
        if (item.source !== 'user' && !kept.length) { delete mine.guidance; continue; }
        const value = isDict(item.value) ? { ...item.value } : {};
        for (const f of LOCAL_GUIDANCE) value[f] = Array.isArray(here[f]) ? [...here[f]] : [];
        mine.guidance = value;
      } else if (item.source === 'user') mine[key] = JSON.parse(JSON.stringify(item.value));
      else delete mine[key];
    }
  }

  // ---- food preferences: each food by this phone's id ----
  function phoneFoodFor(api, food) {
    if (!isDict(food)) return null;
    const all = api._foods || [];
    const lower = (v) => String(v || '').trim().toLowerCase();
    if (food.source === 'builtin') {
      return (food.fdc_id != null && all.find((f) => f.source === 'builtin' && f.fdc_id === food.fdc_id))
        || all.find((f) => f.source === 'builtin' && f.name === food.name) || null;
    }
    if (food.source === 'usda') return all.find((f) => f.source === 'usda' && f.fdc_id === food.fdc_id) || null;
    if (food.source === 'off') return all.find((f) => f.source === 'off' && f.gtin === food.gtin) || null;
    const own = all.filter((f) => f.source === 'custom' && lower(f.name) === lower(food.name) && lower(f.serving_desc) === lower(food.serving_desc));
    return own.length === 1 ? own[0] : null;
  }
  function phoneIdOf(api, st, serverId) {
    const id = st.foodIds[String(serverId)];
    return id != null && api._foodById && api._foodById.get(Number(id)) ? Number(id) : null;
  }
  function serverIdOf(api, st, phoneId) {
    for (const [sid, pid] of Object.entries(st.foodIds)) if (Number(pid) === Number(phoneId)) return Number(sid);
    return null;
  }
  // The server's id of a food of this phone, asked by name when not known yet. null: not on the server (yet).
  async function findOnServer(api, st, food) {
    const known = serverIdOf(api, st, food.id);
    if (known != null) return known;
    const source = ['builtin', 'usda', 'off', 'custom'].includes(food.source) ? food.source : 'custom';
    const q = String(food.name || '').slice(0, 190);
    if (!q.trim()) return null;
    const res = await M.serverApi.call('GET', `/push/v1/api/foods?q=${encodeURIComponent(q)}&source=${source}&limit=25`);
    if (res.offline) M.fail(503, NEEDS_SERVER);
    if (res.status !== 200 || !isDict(res.json) || !Array.isArray(res.json.foods)) return null;
    for (const f of res.json.foods) {
      if (!isDict(f) || !Number.isInteger(f.id)) continue;
      const here = phoneFoodFor(api, f);
      if (here && here.id === food.id) { st.foodIds[String(f.id)] = food.id; return f.id; }
    }
    return null;
  }
  async function applyPrefs(api, st, list) {
    const prefs = api._foodPreferences();
    const next = new Map();
    let lookups = 0;
    let unknown = 0;
    for (const row of Array.isArray(list.foods) ? list.foods : []) {
      if (!isDict(row) || !Number.isInteger(row.food_id)) continue;
      let pid = phoneIdOf(api, st, row.food_id);
      if (pid == null && lookups < MAX_LOOKUPS) {
        lookups += 1;
        const res = await M.serverApi.call('GET', `/push/v1/api/foods/${row.food_id}`);
        const here = res.status === 200 ? phoneFoodFor(api, res.json) : null;
        if (here) { st.foodIds[String(row.food_id)] = here.id; pid = here.id; }
      }
      if (pid == null) { unknown += 1; continue; }
      next.set(pid, { preference: row.preference, source: row.source || 'person', created_at: row.created_at, updated_at: row.updated_at || row.created_at });
    }
    if (!st.prefs) { // the first time: what only this phone said goes to the server, once
      for (const [pid, row] of prefs) {
        if (next.has(pid)) continue;
        const food = api._foodById.get(Number(pid));
        if (!food) continue;
        let sid = null;
        try { sid = await findOnServer(api, st, food); } catch (e) { return false; }
        if (sid == null) { next.set(pid, row); continue; } // kept here until the food reaches the server
        const res = await M.serverApi.call('PUT', `/push/v1/api/guidance/preferences/${sid}`, { body: { preference: row.preference, source: row.source || 'person' } });
        if (res.offline) return false;
        next.set(pid, row);
      }
    }
    prefs.clear();
    for (const [k, v] of next) prefs.set(k, v);
    if (!unknown) st.prefs = true;
    else if (!st.prefs) st.prefs = true; // foods not on this phone are looked up again next time
    return true;
  }

  // ---- one run (after js/mock/server_changes.js read the feed, so the foods are here) ----
  let running = false;
  async function pull({ force = false } = {}) {
    const api = M.instance;
    if (running || !api || !active(api)) return status();
    const st = stateOf(api);
    const account = accountOf();
    if (st.account !== account) Object.assign(st, blank(), { account });
    if (!force && st.pulledAt && Date.now() - Date.parse(st.pulledAt) < PULL_EVERY_MS) return status();
    running = true;
    try {
      st.message = null;
      const profile = await get(st, '/push/v1/api/profile');
      if (!profile) return status();
      if (!st.profile) {
        const mine = api._profileView();
        if (hasProfile(mine) && !same(pick(mine), pick(profile))) st.card = { server: pick(profile), mine: pick(mine), at: new Date().toISOString() };
        st.profile = true;
      }
      applyProfile(api, profile);
      const settings = await get(st, '/push/v1/api/me/settings');
      if (!settings) return status();
      applySettings(api, settings);
      const prefs = await get(st, '/push/v1/api/guidance/preferences');
      if (!prefs) return status();
      if (!(await applyPrefs(api, st, prefs))) { st.message = 'Your server could not be reached. Your profile and settings are the ones it sent last.'; return status(); }
      st.pulledAt = new Date().toISOString();
    } catch (e) {
      st.message = 'Your server could not send your profile and settings just now. The app tries again later.';
    } finally {
      running = false;
      await save(api);
      if (M.serverChanges) { try { M.serverChanges._touched(); } catch (e) { /* views redraw on their own */ } }
      emit();
    }
    return status();
  }

  // The person's answer on the §8.7 card: 'server' keeps the server's; 'mine' sends this phone's.
  async function decide(choice) {
    const api = M.instance;
    const st = stateOf(api);
    if (!st.card) return status();
    if (choice === 'mine') {
      const res = await M.serverApi.call('PUT', '/push/v1/api/profile', { body: profileBody(st.card.mine, st.card.server) });
      if (res.offline) { st.message = NEEDS_SERVER; emit(); return status(); }
      if (res.status !== 200 || !isDict(res.json)) {
        st.message = isDict(res.json) && typeof res.json.detail === 'string' ? `Your server did not take it: ${res.json.detail}` : 'Your server did not take it.';
        emit();
        return status();
      }
      applyProfile(api, res.json);
    }
    st.card = null;
    st.message = null;
    await save(api);
    if (M.serverChanges) { try { M.serverChanges._touched(); } catch (e) { /* views redraw on their own */ } }
    emit();
    return status();
  }

  function status() {
    const api = M.instance;
    const st = api && isDict(api._serverAccount) ? api._serverAccount : blank();
    return { active: active(api), running, pulledAt: st.pulledAt, message: st.message, card: st.card ? { server: st.card.server, mine: st.card.mine } : null };
  }

  // ---- edits on the phone: through the server only ----
  function needServer() { if (!active()) return false; return true; }
  async function send(method, path, body) {
    const res = await M.serverApi.call(method, path, body === undefined ? {} : { body });
    if (res.offline) M.fail(503, NEEDS_SERVER);
    if (res.error) M.fail(503, NEEDS_SERVER);
    if (res.status < 200 || res.status >= 300) M.serverApi.failWith(res);
    return res.json;
  }
  const local = (r, req, api) => r.handler.call(api, req);
  function wrap(method, pattern, fn) {
    const r = M.routes.find((x) => x.method === method && String(x.pattern) === String(pattern));
    if (!r) return;
    const orig = r.handler;
    r.handler = function (req) {
      if (!needServer()) return orig.call(this, req);
      return fn.call(this, req, { handler: orig });
    };
  }
  async function accountWrite(api, done) { // after a change went through: the copy here is the server's, read again soon
    const st = stateOf(api);
    st.message = null;
    await save(api);
    emit();
    return done;
  }

  // PUT /api/profile
  wrap('PUT', /^\/api\/profile$/, async function (req) {
    const answer = await send('PUT', '/push/v1/api/profile', req.body);
    applyProfile(this, answer);
    return accountWrite(this, this._profileView());
  });
  // PATCH /api/me/settings: the account keys go to the server first; the phone's own keys stay here.
  wrap('PATCH', /^\/api\/me\/settings$/, async function (req, r) {
    const body = isDict(req.body) ? req.body : null;
    const keys = body ? Object.keys(body).filter((k) => ACCOUNT_KEYS.includes(k)) : [];
    if (!keys.length) return local(r, req, this);
    const out = {};
    for (const k of keys) out[k] = body[k];
    if ('guidance' in out && isDict(out.guidance)) { // the server's own "OK to repeat" and "Not this meal" marks are kept as they are there
      const now = await send('GET', '/push/v1/api/me/settings');
      const there = isDict(now) && isDict(now.settings) && isDict(now.settings.guidance) && isDict(now.settings.guidance.value) ? now.settings.guidance.value : {};
      out.guidance = { ...out.guidance };
      for (const f of LOCAL_GUIDANCE) out.guidance[f] = Array.isArray(there[f]) ? there[f] : [];
    }
    await send('PATCH', '/push/v1/api/me/settings', out);
    return accountWrite(this, local(r, req, this));
  });
  // PUT / DELETE /api/guidance/preferences/{food_id} and the older "Not for me" routes: the food by the server's id.
  async function serverFood(api, rawId) {
    const id = Number(decodeURIComponent(rawId));
    const food = Number.isSafeInteger(id) && api._foodById ? api._foodById.get(id) : null;
    if (!food) return null; // the phone's own route answers 404
    const sid = await findOnServer(api, stateOf(api), food);
    if (sid == null) M.fail(409, NOT_THERE_YET);
    return sid;
  }
  wrap('*', /^\/api\/guidance\/preferences\/([^/]+)$/, async function (req, r) {
    if (req.method !== 'PUT' && req.method !== 'DELETE') return local(r, req, this);
    const sid = await serverFood(this, req.id);
    if (sid == null) return local(r, req, this);
    if (req.method === 'PUT') await send('PUT', `/push/v1/api/guidance/preferences/${sid}`, req.body);
    else {
      const res = await M.serverApi.call('DELETE', `/push/v1/api/guidance/preferences/${sid}`);
      if (res.offline || res.error) M.fail(503, NEEDS_SERVER);
      if (res.status !== 204 && res.status !== 404) M.serverApi.failWith(res); // 404: nothing there, as here
    }
    return accountWrite(this, local(r, req, this));
  });
  wrap('*', /^\/api\/guidance\/not-for-me\/([^/]+)$/, async function (req, r) {
    if (req.method !== 'PUT' && req.method !== 'DELETE') return local(r, req, this);
    const sid = await serverFood(this, req.id);
    if (sid == null) return local(r, req, this);
    if (req.method === 'PUT') await send('PUT', `/push/v1/api/guidance/preferences/${sid}`, { preference: 'not_for_me', source: 'person' });
    else {
      const row = this._foodPreferences().get(Number(decodeURIComponent(req.id)));
      if (row && row.preference === 'not_for_me') {
        const res = await M.serverApi.call('DELETE', `/push/v1/api/guidance/preferences/${sid}`);
        if (res.offline || res.error) M.fail(503, NEEDS_SERVER);
        if (res.status !== 204 && res.status !== 404) M.serverApi.failWith(res);
      }
    }
    return accountWrite(this, local(r, req, this));
  });

  M.serverAccount = {
    ACCOUNT_KEYS, LOCAL_GUIDANCE, PROFILE_FIELDS, NEEDS_SERVER,
    pull, decide, status, active,
    subscribe(fn) { listeners.add(fn); return () => listeners.delete(fn); },
    // for the tests: the pure parts
    _blank: blank, _pick: pick, _applyProfile: applyProfile, _applySettings: applySettings, _profileBody: profileBody, _phoneFoodFor: phoneFoodFor,
  };
})();
