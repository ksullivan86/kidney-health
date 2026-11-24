/* Kidney Diet Log — device mode only: the person's own server's food services and AI, through its token gateway (design note 39
   §5 to §7, plan steps 3 and 4; ARCHITECTURE.md "Device mode").

   The page builds every request and reads every answer; the iPhone app only carries it (ios/KidneyHealth/Services/ServerSync.swift),
   to the paired server over HTTPS with the token from its Keychain, and only when the method and path are on its allow-list
   (KidneyHealthCore/ServerAPI.swift). The bridge message:
       { kind: 'serverApi', method, path: '/push/v1/…', body?: '<json>', jpeg?: '<base64>', ifMatch? }
         → { ok, status, json, retryAfter? } or { error: 'not_paired' | 'offline' | 'refused' | 'bad_request' | 'no_app' }
   The token never reaches the page, and no key moves either way: the server's keys stay on the server, the phone's own keys
   (Keys and services) stay in the app.

   Which kind of token is paired comes from GET /push/v1/about (note 39 §5.3), asked at most every few minutes:
       both        200: a token "For the iPhone app, both ways" (scope app:sync). The server's food services and AI may be used.
       add_only    401 or 403: a token that only adds rows, or both ways is off on the server. It keeps working for sending rows.
       old_server  404 or 405: a server without the gateway. Sending rows still works.
       offline     the server could not be reached (asked again after a minute).
       not_paired, no_app, error.
   `about` is read leniently, since the server may grow it: `account`, `api_version`, `changes` (the change feed, at `sync.changes` or
   `features.changes`; js/mock/server_changes.js), and per feature whether it is on, either at the top or under `features`:
   `usda_search` (or `usda`), `barcodes` (or `barcode`), `ai` ({ enabled, routes: { <feature>: { available } } }, the routes of
   GET /api/ai/status); and under `services` (step 9): `recipe_import`, `instacart`, `list_sync`.
   A feature it does not mention is tried; the server answers for itself.
   The AI's choice (server, then the iPhone's own, then none) is in js/mock/ai.js; the food lookups are in foods.js and barcode.js;
   recipe pages, Instacart and the list app in lists.js.
   No DOM, nothing stored but the answer of `about` in memory. */
(() => {
  'use strict';
  const KH = window.KH;
  const M = KH.mock;
  if (!KH.flags || KH.flags.DEVICE !== true || !M) return;

  const TTL_MS = { both: 5 * 60 * 1000, add_only: 5 * 60 * 1000, old_server: 30 * 60 * 1000, offline: 60 * 1000, error: 60 * 1000,
    not_paired: 15 * 1000, no_app: 60 * 60 * 1000 };
  const isDict = (v) => v != null && typeof v === 'object' && !Array.isArray(v);
  let known = null; // { state, server, about, at }
  let asking = null;
  const listeners = new Set();
  const emit = () => { for (const fn of [...listeners]) { try { fn(); } catch (e) { /* a view that threw must not stop the rest */ } } };

  async function ask(request) {
    let handler = null;
    try { handler = window.webkit.messageHandlers.bridge; } catch (e) { handler = null; }
    if (!handler) return { error: 'no_app' };
    try {
      const answer = await handler.postMessage(request);
      return answer && typeof answer === 'object' ? answer : { error: 'bad_answer' };
    } catch (e) {
      return { error: 'bridge' };
    }
  }
  function parse(answer) {
    if (!answer || typeof answer.json !== 'string' || !answer.json) return null;
    try { return JSON.parse(answer.json); } catch (e) { return null; }
  }

  // What `about` says, in the names this page uses. null for a flag it does not mention.
  function readAbout(json) {
    if (!isDict(json)) return null;
    const f = isDict(json.features) ? json.features : {};
    const pick = (...names) => {
      for (const n of names) {
        const v = n in f ? f[n] : json[n];
        if (typeof v === 'boolean') return v;
        if (isDict(v) && typeof v.enabled === 'boolean') return v.enabled;
        if (isDict(v) && typeof v.available === 'boolean') return v.available;
      }
      return null;
    };
    const ai = isDict(f.ai) ? f.ai : isDict(json.ai) ? json.ai : null;
    let routes = null;
    const raw = ai && isDict(ai.routes) ? ai.routes : null;
    if (raw) {
      routes = {};
      for (const [k, v] of Object.entries(raw)) routes[k] = v === true || (isDict(v) && v.available === true);
    }
    const services = isDict(json.services) ? json.services : {};
    const service = (name) => (typeof services[name] === 'boolean' ? services[name] : null);
    return { account: typeof json.account === 'string' ? json.account.slice(0, 200) : null, version: Number(json.api_version) || null,
      sync: pick('sync'), usda: pick('usda_search', 'usda'), barcode: pick('barcodes', 'barcode'), ai: pick('ai'), aiRoutes: routes,
      recipe: service('recipe_import'), instacart: service('instacart'), listSync: service('list_sync'),
      changes: isDict(json.sync) && typeof json.sync.changes === 'boolean' ? json.sync.changes : pick('changes') }; // the change feed (note 39 step 5)
  }

  function remember(state, server = known ? known.server : null, about = null) {
    const before = known ? known.state : null;
    known = { state, server, about, at: Date.now() };
    if (before !== state) emit();
    return known;
  }

  // What the paired server offers this phone now. `force` asks again whatever the cache says.
  async function check({ force = false } = {}) {
    if (!force && known && Date.now() - known.at < (TTL_MS[known.state] || 60000)) return known;
    if (asking) return asking;
    asking = (async () => {
      const info = await ask({ kind: 'serverInfo' });
      if (info.error === 'no_app') return remember('no_app', null);
      if (!info.ok || !info.paired) return remember('not_paired', null);
      const server = typeof info.server === 'string' ? info.server.slice(0, 300) : null;
      const res = await ask({ kind: 'serverApi', method: 'GET', path: '/push/v1/about' });
      if (res.error === 'offline') return remember('offline', server);
      if (res.error === 'not_paired') return remember('not_paired', null);
      if (res.error) return remember('error', server);
      if (res.status === 200) {
        const about = readAbout(parse(res));
        return about ? remember('both', server, about) : remember('error', server);
      }
      if (res.status === 401 || res.status === 403) return remember('add_only', server);
      if (res.status === 404 || res.status === 405) return remember('old_server', server);
      return remember('error', server);
    })();
    try { return await asking; } finally { asking = null; }
  }
  function forget() { known = null; emit(); }

  // May the page use the server for `what` ('usda', 'barcode', 'ai', 'recipe', 'instacart', 'listSync')? Only with a token both
  // ways; a flag `about` sets to false says no; one it does not mention says yes (the server answers for itself).
  async function offers(what) {
    const k = await check();
    if (k.state !== 'both') return false;
    const flag = k.about ? k.about[what] : null;
    return flag !== false;
  }

  // One request through the gateway. `path` is the /api path (or a /push/v1 path). Answers { status, json, retryAfter } when the
  // server answered, { offline: true } when it could not be reached, or { error } when the app refused or is missing.
  async function call(method, path, { body, jpeg, ifMatch } = {}) {
    const request = { kind: 'serverApi', method, path: path.startsWith('/push/v1/') ? path : `/push/v1${path}` };
    if (body !== undefined) request.body = JSON.stringify(body);
    if (jpeg) request.jpeg = jpeg;
    if (ifMatch) request.ifMatch = ifMatch;
    const res = await ask(request);
    if (res.error === 'offline') { remember('offline'); return { offline: true }; }
    if (res.error) return { error: res.error };
    if (res.status === 401 || res.status === 403) forget(); // the token changed or was revoked: ask `about` again next time
    return { status: res.status, json: parse(res), retryAfter: res.retryAfter || null };
  }

  // The server's error answer as the page's own (its detail and the keys beside it, such as reason, consent or retry_after).
  function failWith(res) {
    const json = isDict(res.json) ? res.json : {};
    const detail = typeof json.detail === 'string' ? json.detail : `Your server answered ${res.status}.`;
    const extra = { ...json };
    delete extra.detail;
    if (res.retryAfter && extra.retry_after == null) extra.retry_after = res.retryAfter;
    M.fail(res.status, detail, Object.keys(extra).length ? extra : null);
  }

  // A photo (a Blob) as base64 for the bridge.
  const B64 = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/';
  async function base64(blob) {
    const b = new Uint8Array(await blob.arrayBuffer());
    const out = [];
    for (let i = 0; i < b.length; i += 3) {
      const n = (b[i] << 16) | ((b[i + 1] || 0) << 8) | (b[i + 2] || 0);
      out.push(B64[(n >> 18) & 63], B64[(n >> 12) & 63], i + 1 < b.length ? B64[(n >> 6) & 63] : '=', i + 2 < b.length ? B64[n & 63] : '=');
    }
    return out.join('');
  }

  // An answer of the server's AI, made safe to use on this phone, whose rows have their own ids until two-way sync (note 39 step 6):
  // * every food the answer carries in full (a Food) is kept on this phone (USDA and Open Food Facts foods as the shared row, the
  //   person's own as their own) and named by its id here;
  // * every other `food_id` is named by the food kept above, else by the one built-in food of that exact name (the built-in list is
  //   the same on both), else by the one food of that name on this phone; else it is not known here;
  // * an id of a row on the server (an entry or a saved meal) is never kept.
  // An idea, recipe or card that names something not known here is left out, so nothing is saved with another food's numbers, and
  // `dropped` says so. A safety answer (a low, a red flag, a medicine question) is never cut: it names no food.
  const FOOD_SOURCES = new Set(['builtin', 'custom', 'usda', 'off']);
  const ROW_IDS = ['entry_id', 'entry_ids', 'meal_id', 'template_id'];
  const SAFETY = new Set(['red_flag', 'treating_a_low', 'medicine_question']);
  const looksLikeFood = (o) => isDict(o) && Number.isInteger(o.id) && typeof o.name === 'string' && FOOD_SOURCES.has(o.source)
    && typeof o.serving_desc === 'string' && isDict(o.nutrients);
  function localize(api, answer) {
    if (!isDict(answer) && !Array.isArray(answer)) return answer;
    const ids = new Map();
    const keep = (v) => {
      if (Array.isArray(v)) { v.forEach(keep); return; }
      if (!isDict(v)) return;
      if (looksLikeFood(v)) {
        const row = api._storeServerFood(v);
        ids.set(v.id, row.id);
        v.id = row.id;
      }
      for (const k of Object.keys(v)) keep(v[k]);
    };
    keep(answer);
    const byName = (name) => {
      if (typeof name !== 'string' || !name) return null;
      const builtin = api._foods.filter((f) => f.source === 'builtin' && !f.hidden && f.name === name);
      if (builtin.length === 1) return builtin[0].id;
      const mine = api._foods.filter((f) => !f.hidden && api._foodVisible(f) && f.name === name);
      return mine.length === 1 ? mine[0].id : null;
    };
    const unknown = new WeakSet();
    const name = (v) => {
      if (Array.isArray(v)) { v.forEach(name); return; }
      if (!isDict(v)) return;
      if (Number.isInteger(v.food_id)) {
        const here = ids.has(v.food_id) ? ids.get(v.food_id) : byName(v.name != null ? v.name : v.food_name);
        if (here == null) { v.food_id = null; unknown.add(v); } else v.food_id = here;
      }
      for (const k of ROW_IDS) if (k in v && v[k] != null) { v[k] = null; unknown.add(v); }
      for (const k of Object.keys(v)) name(v[k]);
    };
    name(answer);
    if (isDict(answer) && SAFETY.has(answer.status)) return answer;
    const holds = (v) => (Array.isArray(v) ? v.some(holds) : isDict(v) && (unknown.has(v) || Object.values(v).some(holds)));
    let left = 0;
    const cut = (v) => { // the outermost list that holds the unknown thing loses that element
      if (Array.isArray(v)) {
        const kept = v.filter((el) => !holds(el));
        left += v.length - kept.length;
        v.splice(0, v.length, ...kept);
        kept.forEach(cut);
        return;
      }
      if (isDict(v)) for (const k of Object.keys(v)) if (k !== 'dropped') cut(v[k]);
    };
    cut(answer);
    if (left && isDict(answer)) {
      if (answer.dropped == null) answer.dropped = [];
      if (Array.isArray(answer.dropped)) for (let i = 0; i < left; i += 1) answer.dropped.push({ reason: 'not_on_this_iphone' });
    }
    return answer;
  }

  M.serverApi = {
    check, offers, call, failWith, forget, readAbout, base64, localize,
    status: () => known,
    subscribe(fn) { listeners.add(fn); return () => listeners.delete(fn); },
  };
})();
