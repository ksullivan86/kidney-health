/* Kidney Diet Log — device mode only: sending what the person adds on the phone to their own server (design note 38 §5.5, step 4;
   ARCHITECTURE.md "Device mode"; the route is app/app_sync.py, guide docs/push.md "Sending from the iPhone app").

   The page owns the queue and the rules; the iPhone app only carries the request. The page works out which rows are not yet sent,
   builds the POST /push/v1/sync body exactly as the server checks it, and asks the app through its "bridge" reply handler:
       { kind: 'serverInfo' }                    → { ok, paired, server }            (no network: is a server paired, and its host)
       { kind: 'serverSyncCheck' }               → { ok, status, json, retryAfter? }  (GET /push/v1/sync: may this token send rows?)
       { kind: 'serverSync', body: '<json>' }    → { ok, status, json, retryAfter? }  (POST /push/v1/sync)
   or { error: 'not_paired' | 'offline' | 'refused' | 'bad_request' }. The app posts to the paired server over HTTPS with the token
   from its Keychain. The token never reaches the page.

   What is sent: every row made on this phone that the server has not taken yet: food log entries, the foods they need, the
   person's own foods, lab results, symptoms, weights and blood pressure readings. A row is sent once here; with a token both ways
   its later edits and deletes go through js/mock/server_changes.js (note 39 steps 6 and 7). Never the sample data (`_sample`).
   With a token that only adds, a planned entry waits until its day is over, so marking it eaten is sent; both ways, it is sent at once.

   Saved with the rest of the log (js/mock/persist.js saves every property of the demo API), in `_serverSync`:
       { v: 1, server: 'food.example.org' | null,
         rows: { food | entry | lab | symptom | weight | reading: { <row id>: { c: client_id, s?: 'sent'|'refused'|'stuck',
                                                                                 t?: tries, g?: group, w?: why,
                                                                                 v?: version when sent, d?: 1 } } },
         sentAt, triedAt, outcome, message, status, waitUntil, checkOk, checkedAt }
   `c` is a UUID made once for the row (an entry keeps its own `client_id`, which the export carries). Starting over makes a new
   demo API, so the queue starts again with it. A different server (host) sends everything again; the server's receipts and
   `created_at` checks keep that from adding twice.

   What was sent is remembered (design note 39, plan step 1), so the first two-way sync can tell which side changed a row:
   `v` is the row's version when the server took it: for an entry the server's own entry version (log.entry_version, the
   twin M.entryVersion), for every other kind "b:" and a hash of the row as it was sent, until note 39 step 5 gives each
   kind its own version. `d: 1` marks a sent row deleted on this phone afterwards; the mark is kept until the server has the row deleted too.

   The server answers counts only. A row the server cannot place (a food it does not know, a full day) is "skipped": it is counted,
   not named. Per list, rows sent minus (added + already there) are the skipped ones. When that cannot say which rows they were, the
   rows that could have been skipped are sent again in smaller groups until it can. A row skipped MAX_TRIES times is "stuck": it
   stays on the phone and the screen says so. A 400 that names a row refuses that row (kept on the phone, never sent again) and the
   rest goes on. No DOM. */
(() => {
  'use strict';
  const KH = window.KH;
  const M = KH.mock;
  if (!KH.flags || KH.flags.DEVICE !== true || !M) return;

  const LISTS = [['foods', 'food'], ['entries', 'entry'], ['labs', 'lab'], ['symptoms', 'symptom'], ['weights', 'weight'], ['readings', 'reading']];
  const KIND_OF = Object.fromEntries(LISTS);
  const LIST_OF = Object.fromEntries(LISTS.map(([l, k]) => [k, l]));
  const MAX_ROWS = 200; // app/app_sync.py MAX_ROWS
  const MAX_BYTES = 256 * 1024 - 2048; // MAX_BODY_BYTES, with room to spare
  const MAX_TRIES = 3; // a row skipped this many times is stuck
  const MAX_REQUESTS = 10; // in one run; the server allows 60 an hour
  const SEND_DELAY_MS = 10000; // after a save
  const CHECK_TTL_MS = 24 * 3600 * 1000; // the token check is asked again after a day
  const RECHECK_MS = 3600 * 1000; // after a refused token, ask again at most once an hour (Send now asks at once)
  const ERROR_PAUSE_MS = 5 * 60 * 1000;
  const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

  const MESSAGES = {
    sample: 'This log holds the sample data, so nothing is sent. Start over with an empty log to send your own.',
    not_paired: 'No server is paired with this app. Pair it in Apple Health and server, with a token made "For the iPhone app".',
    no_app: 'Sending to a server needs the iPhone app.',
    token: 'Your server did not accept the token for sending rows. Make a token "For the iPhone app" in your server\'s Settings → Account → Your data → Phone shortcuts and pair again. A Shortcut\'s token cannot send them, and phone shortcuts may be turned off on the server.',
    old_server: 'Your server cannot take rows from the app yet. Ask the person who runs it to update it.',
    offline: 'Your server could not be reached. The rows wait on this iPhone and are sent later.',
    wait: 'Your server asked the app to wait. It tries again later.',
    error: 'Your server could not take the rows just now. The app tries again later.',
    unsaved: 'The log could not be saved on this iPhone, so nothing was sent.',
    done: 'Up to date.',
  };

  const listeners = new Set();
  let running = false;
  let again = false;
  let timer = null;
  const emit = () => { for (const fn of [...listeners]) { try { fn(); } catch (e) { /* a view that threw must not stop sending */ } } };

  // ---- the saved state ----
  function uuid() {
    try { if (crypto && typeof crypto.randomUUID === 'function') return crypto.randomUUID(); } catch (e) { /* below */ }
    const b = new Uint8Array(16);
    crypto.getRandomValues(b);
    b[6] = (b[6] & 0x0f) | 0x40; b[8] = (b[8] & 0x3f) | 0x80;
    const x = [...b].map((n) => n.toString(16).padStart(2, '0')).join('');
    return `${x.slice(0, 8)}-${x.slice(8, 12)}-${x.slice(12, 16)}-${x.slice(16, 20)}-${x.slice(20)}`;
  }
  function blank() {
    return { v: 1, server: null, rows: { food: {}, entry: {}, lab: {}, symptom: {}, weight: {}, reading: {} }, sentAt: null, triedAt: null,
      outcome: null, message: null, status: null, waitUntil: null, checkOk: false, checkedAt: null };
  }
  function stateOf(api) {
    if (!api._serverSync || typeof api._serverSync !== 'object') api._serverSync = blank();
    const st = api._serverSync;
    for (const [, kind] of LISTS) if (!st.rows[kind] || typeof st.rows[kind] !== 'object') st.rows[kind] = {};
    return st;
  }
  const peek = (api) => (api && api._serverSync && typeof api._serverSync === 'object' ? api._serverSync : blank());
  const done = (r) => !!(r && (r.s === 'sent' || r.s === 'refused' || r.s === 'stuck'));

  function localDay(d = new Date()) {
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  }
  const byId = (a, b) => a.id - b.id;
  function uidOf(api) { try { return api._currentUser().id; } catch (e) { return 1; } }

  // The rows of each kind this phone could send, oldest first. Foods: the person's own foods, and the USDA and Open Food Facts
  // foods an entry uses (a built-in food is named by the entry instead).
  function rowsOf(api) {
    const uid = uidOf(api);
    const entries = (api._entries || []).slice().sort(byId);
    const used = new Set(entries.map((e) => e.food_id));
    const foods = (api._foods || []).filter((f) => (f.source === 'custom' && (!f.hidden || used.has(f.id)))
      || ((f.source === 'usda' || f.source === 'off') && used.has(f.id))).sort(byId);
    return {
      food: foods,
      entry: entries,
      lab: api._labsOf ? api._labsOf(uid).slice().sort(byId) : [],
      symptom: api._symptomsOf ? api._symptomsOf(uid).slice().sort(byId) : [],
      weight: api._weightsOf ? api._weightsOf(uid).slice().sort(byId) : [],
      reading: api._readingsOf ? api._readingsOf(uid).slice().sort(byId) : [],
    };
  }

  // The ids of the rows of a kind still on this phone. A food counts while the person still has it (their own and not deleted, or a
  // USDA or Open Food Facts food still linked), even when no entry uses it any more.
  function presentIds(api, kind, all) {
    if (kind !== 'food') return new Set(all[kind].map((row) => String(row.id)));
    const links = typeof api._foodLinks === 'function' ? api._foodLinks() : new Set();
    return new Set((api._foods || []).filter((f) => !f.hidden && (f.source === 'custom' || links.has(f.id))).map((f) => String(f.id)));
  }

  // Gives every row a client ID and forgets rows deleted before they were sent. True when something changed (save before sending).
  function assignIds(api) {
    const st = stateOf(api);
    const all = rowsOf(api);
    let changed = false;
    for (const [, kind] of LISTS) {
      const map = st.rows[kind];
      const here = new Set();
      const kept = presentIds(api, kind, all);
      for (const row of all[kind]) {
        here.add(String(row.id));
        let r = map[row.id];
        if (!r) { r = {}; map[row.id] = r; changed = true; }
        if (kind === 'entry') {
          if (typeof row.client_id !== 'string' || !UUID_RE.test(row.client_id)) { row.client_id = r.c && UUID_RE.test(r.c) ? r.c : uuid(); changed = true; }
          if (r.c !== row.client_id) { r.c = row.client_id; changed = true; }
        } else if (typeof r.c !== 'string' || !UUID_RE.test(r.c)) { r.c = uuid(); changed = true; }
      }
      for (const id of Object.keys(map)) {
        const r = map[id];
        if (kept.has(id)) { if (r.d === 1) { delete r.d; changed = true; } } // still here, or back again (a USDA food imported again)
        if (here.has(id)) continue;
        if (!done(r)) { delete map[id]; changed = true; } else if (r.s === 'sent' && r.d !== 1 && !kept.has(id)) { r.d = 1; changed = true; }
      }
    }
    return changed;
  }

  // ---- the rows, as POST /push/v1/sync checks them ----
  function compact(o) { for (const k of Object.keys(o)) if (o[k] == null) delete o[k]; return o; }
  function foodBody(f, cid) {
    const nutrients = {};
    for (const [k, v] of Object.entries(f.nutrients || {})) if (v != null) nutrients[k] = v;
    const source = f.source === 'usda' || f.source === 'off' ? f.source : 'custom';
    return compact({ client_id: cid, source, name: f.name, brand: f.brand || null, category: f.category || null, serving_desc: f.serving_desc,
      serving_g: f.serving_g, nutrients, flags: (f.flags || []).length ? [...f.flags] : null, kidney_notes: f.kidney_notes || null,
      gtin: f.gtin || null, ingredients_text: f.ingredients_text || null, fdc_id: source === 'usda' ? f.fdc_id : null,
      source_url: f.source_url || null, source_license: f.source_license || null });
  }
  // FoodRef: a built-in food by its fdc_id (or its name when it has none); any other food by the client ID it is sent with in `foods`.
  function foodRef(food, foodCid) {
    if (food.source === 'builtin') return { builtin: compact({ fdc_id: food.fdc_id == null ? null : food.fdc_id, name: food.name }) };
    return { client_id: foodCid };
  }
  function entryBody(e, cid, ref) {
    const out = { client_id: cid, date: e.date, meal: e.meal, food: ref, status: e.status || 'eaten', purpose: e.purpose === 'hypo' ? 'hypo' : 'none',
      note: e.note || null, created_at: e.created_at || null };
    if (e.grams != null) out.grams = e.grams; else out.servings = e.servings;
    return compact(out);
  }
  function labBody(r, cid) {
    const unit = r.entered_unit || ((KH.kidney && KH.kidney.ANALYTES[r.analyte]) || {}).canonical_unit || '';
    return compact({ client_id: cid, analyte: r.analyte, value: r.entered_value != null ? r.entered_value : r.value, unit, taken_on: r.taken_on,
      note: r.note || '', created_at: r.created_at || null });
  }
  function symptomBody(r, cid) {
    return compact({ client_id: cid, date: r.date, symptom: r.symptom, severity: r.severity, label: r.label || '', note: r.note || '',
      created_at: r.created_at || null });
  }
  function weightBody(r, cid) {
    return compact({ client_id: cid, date: r.date, time: r.time || null, kg: r.kg, context: r.context, note: r.note || '', source_key: r.source_key || null });
  }
  function readingBody(r, cid) {
    return compact({ client_id: cid, date: r.date, time: r.time || null, systolic: r.systolic, diastolic: r.diastolic, pulse: r.pulse == null ? null : r.pulse,
      context: r.context, note: r.note || '', source_key: r.source_key || null });
  }
  const BODY = { lab: labBody, symptom: symptomBody, weight: weightBody, reading: readingBody };

  const enc = new TextEncoder();
  const bytes = (v) => enc.encode(JSON.stringify(v)).length;

  // The version a row is remembered by once sent (see the top). FNV-1a, 64 bit, over the row's JSON with sorted keys.
  const FNV_OFFSET = 0xcbf29ce484222325n, FNV_PRIME = 0x100000001b3n, FNV_MASK = 0xffffffffffffffffn;
  function sorted(v) {
    if (Array.isArray(v)) return v.map(sorted);
    if (v && typeof v === 'object') return Object.fromEntries(Object.keys(v).sort().map((k) => [k, sorted(v[k])]));
    return v;
  }
  function bodyHash(body) {
    let digest = FNV_OFFSET;
    for (const byte of enc.encode(JSON.stringify(sorted(body)))) digest = ((digest ^ BigInt(byte)) * FNV_PRIME) & FNV_MASK;
    return `b:${digest.toString(16).padStart(16, '0')}`;
  }
  function versionOf(api, kind, row, body) {
    if (kind === 'entry') {
      try { return api._entryView(row).version; } catch (e) { return null; }
    }
    return body ? bodyHash(body) : null;
  }
  // The version a row has now, to compare with the one it was sent with (null when it cannot be worked out).
  function versionNow(api, kind, row, r) {
    if (kind === 'entry') return versionOf(api, kind, row, null);
    if (kind === 'food') return bodyHash(foodBody(row, r.c));
    return bodyHash(BODY[kind](row, r.c));
  }

  // The next request: { lists: { foods: [...], ... }, refs: [{ kind, id, cid, maySkip }], probe } or null when nothing is left.
  // `skip`: "kind:id" of rows already given their try in this run. Also refuses entries whose food cannot be sent (sets `changed`).
  function nextBatch(api, { skip = new Set(), maxRows = MAX_ROWS, today = localDay() } = {}) {
    const st = stateOf(api);
    const all = rowsOf(api);
    const foodById = new Map((api._foods || []).map((f) => [f.id, f]));
    const out = { lists: {}, refs: [], probe: false, changed: false, refused: [] };
    const waiting = (kind, row) => { const r = st.rows[kind][row.id]; return r && r.c && !done(r) && !skip.has(`${kind}:${row.id}`) ? r : null; };
    const entryRef = (e) => {
      const food = foodById.get(e.food_id);
      if (!food) return { refuse: 'Its food is no longer on this iPhone.' };
      if (food.source === 'builtin') return { ref: foodRef(food), maySkip: true };
      const fr = st.rows.food[food.id];
      if (!fr || !fr.c) return { hold: true };
      if (fr.s === 'refused' || fr.s === 'stuck') return { refuse: 'Its food could not be sent to your server.' };
      return { ref: foodRef(food, fr.c), food, foodState: fr, maySkip: false };
    };
    const add = (kind, row, body, maySkip) => {
      const list = LIST_OF[kind];
      (out.lists[list] = out.lists[list] || []).push(body);
      out.refs.push({ kind, id: row.id, cid: body.client_id, list, index: out.lists[list].length - 1, maySkip, v: versionOf(api, kind, row, body) });
    };
    const bodyOf = (kind, row, r) => {
      if (kind === 'food') return { body: foodBody(row, r.c), maySkip: false };
      if (kind === 'entry') {
        if (row.status === 'planned' && row.date >= today && !twoWay(api)) return { hold: true }; // both ways: sent at once (note 39 §8.5)
        const ref = entryRef(row);
        if (ref.refuse) { r.s = 'refused'; r.w = ref.refuse; delete r.g; delete r.t; out.changed = true; out.refused.push(row.id); return { hold: true }; }
        if (ref.hold) return { hold: true };
        return { body: entryBody(row, r.c, ref.ref), maySkip: ref.maySkip, needs: ref.foodState && ref.foodState.s !== 'sent' ? ref.food : null };
      }
      return { body: BODY[kind](row, r.c), maySkip: kind !== 'lab' };
    };

    // Rows whose outcome the last answer could not tell apart go first, alone and in smaller groups, until it can.
    for (const [, kind] of LISTS) {
      const unsure = all[kind].filter((row) => { const r = waiting(kind, row); return r && r.g; });
      if (!unsure.length) continue;
      const group = Math.max(1, Math.min(...unsure.map((row) => st.rows[kind][row.id].g)));
      for (const row of unsure.slice(0, group)) {
        const b = bodyOf(kind, row, st.rows[kind][row.id]);
        if (b.body) add(kind, row, b.body, true);
      }
      if (out.refs.length) { out.probe = true; return out; }
    }

    let size = 2 + LISTS.length * 16;
    const placed = new Set();
    for (const [, kind] of LISTS) {
      for (const row of all[kind]) {
        const r = waiting(kind, row);
        if (!r || r.g) continue;
        const b = bodyOf(kind, row, r);
        if (!b.body) continue;
        if (b.needs && !placed.has(b.needs.id)) continue; // its food waits for a later request (or was given its try already)
        const n = bytes(b.body) + 1;
        if (out.refs.length + 1 > maxRows || size + n > MAX_BYTES) {
          if (!out.refs.length) { r.s = 'refused'; r.w = 'It is too large to send.'; out.changed = true; out.refused.push(row.id); continue; }
          return out;
        }
        size += n;
        add(kind, row, b.body, b.maySkip);
        if (kind === 'food') placed.add(row.id);
      }
    }
    return out.refs.length || out.changed ? out : null;
  }

  // What a 200 answer means for each row of the request it answers. Returns the counts added / already there.
  function applyAnswer(api, batch, answer, skip) {
    const st = stateOf(api);
    const added = (answer && answer.added) || {};
    const there = (answer && answer.already_there) || {};
    const take = (ref) => {
      const r = st.rows[ref.kind][ref.id];
      if (!r) return;
      r.s = 'sent'; delete r.t; delete r.g; delete r.w;
      if (ref.v) r.v = ref.v; // the version the server took (note 39 step 1)
    };
    const missed = (ref) => {
      const r = st.rows[ref.kind][ref.id];
      if (!r) return;
      r.t = (r.t || 0) + 1; delete r.g;
      skip.add(`${ref.kind}:${ref.id}`);
      if (r.t >= MAX_TRIES) { r.s = 'stuck'; r.w = ref.kind === 'entry' ? 'Your server does not know its food.' : 'That day is full on your server.'; }
    };
    for (const [list] of LISTS) {
      const refs = batch.refs.filter((x) => x.list === list);
      if (!refs.length) continue;
      const took = (Number(added[list]) || 0) + (Number(there[list]) || 0);
      const skipped = Math.max(0, refs.length - took);
      if (!skipped) { refs.forEach(take); continue; }
      let could = refs.filter((x) => x.maySkip);
      if (!could.length) could = refs; // not expected: the server skips only these kinds
      refs.filter((x) => !could.includes(x)).forEach(take);
      if (skipped >= could.length) { could.forEach(missed); continue; }
      const group = Math.max(1, Math.ceil(could.length / 2));
      for (const ref of could) { const r = st.rows[ref.kind][ref.id]; if (r) r.g = group; }
    }
    return { added: Object.values(added).reduce((a, b) => a + (Number(b) || 0), 0), there: Object.values(there).reduce((a, b) => a + (Number(b) || 0), 0) };
  }

  // A 400 that names a row ("entries.3.date: …"): that row is refused. False when the answer names none.
  function refuseNamed(api, batch, json) {
    const field = json && (json.field || (json.detail && typeof json.detail === 'string' ? json.detail.split(':')[0] : null));
    const m = typeof field === 'string' ? field.match(/^(foods|entries|labs|symptoms|weights|readings)\.(\d+)(?:\.|$)/) : null;
    if (!m) return false;
    const ref = batch.refs.find((x) => x.list === m[1] && x.index === Number(m[2]));
    if (!ref) return false;
    const r = stateOf(api).rows[ref.kind][ref.id];
    r.s = 'refused';
    r.w = String((json && json.detail) || 'Your server refused it.').slice(0, 300);
    delete r.g; delete r.t;
    return true;
  }

  // ---- talking to the app ----
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

  // Saves the log now (the client IDs must be stored before a row carrying one leaves the phone). False when it could not.
  async function save(api) {
    if (typeof M.onWrite === 'function') M.onWrite(api, 'PUT', '/api/device/server-sync');
    if (!M.local || !M.local.on()) return false;
    const s = await M.local.flush();
    return !(s && (s.error || s.conflict));
  }
  function setOutcome(st, outcome, extra = {}) {
    const message = extra.message || MESSAGES[outcome] || null;
    const status = extra.status == null ? null : extra.status;
    if (st.outcome === outcome && st.message === message && st.status === status && !extra.force) return false;
    st.outcome = outcome; st.message = message; st.status = status;
    return true;
  }
  const iso = (ms) => new Date(ms).toISOString();

  // One run: check, then send in requests until nothing is left, a stop answer, or MAX_REQUESTS.
  async function runOnce(force) {
    const api = M.instance;
    if (!api || !M.local || !M.local.on()) return;
    if (api._sample === true) { if (setOutcome(stateOf(api), 'sample')) await save(api); return; }
    const info = await ask({ kind: 'serverInfo' });
    if (info.error === 'no_app') { if (api._serverSync && setOutcome(stateOf(api), 'no_app')) await save(api); return; }
    if (!info.ok || !info.paired) { if (setOutcome(stateOf(api), 'not_paired')) await save(api); return; }
    const st = stateOf(api);
    const server = typeof info.server === 'string' ? info.server.slice(0, 300) : null;
    if (st.server !== server) { // another server: everything is sent there too
      for (const [, kind] of LISTS) for (const r of Object.values(st.rows[kind])) { delete r.s; delete r.t; delete r.g; delete r.w; delete r.v; delete r.d; }
      Object.assign(st, { server, sentAt: null, checkOk: false, checkedAt: null, waitUntil: null });
    }
    const now = Date.now();
    if (!force && st.waitUntil && now < Date.parse(st.waitUntil)) return;
    let changed = assignIds(api);
    const first = nextBatch(api);
    if (first && first.changed) changed = true;
    if (!first || !first.refs.length) {
      if (setOutcome(st, 'done') || changed) await save(api);
      return;
    }
    // May this token send rows? (GET /push/v1/sync, one of the 60 an hour.)
    const checkAge = st.checkedAt ? now - Date.parse(st.checkedAt) : Infinity;
    if (force || !st.checkOk || checkAge > CHECK_TTL_MS) {
      if (!force && !st.checkOk && st.outcome === 'token' && checkAge < RECHECK_MS) { if (changed) await save(api); return; }
      const res = await ask({ kind: 'serverSyncCheck' });
      if (!stop(st, res, parse(res))) {
        if (res.status !== 200) { setOutcome(st, 'error', { status: res.status }); st.waitUntil = iso(Date.now() + ERROR_PAUSE_MS); }
        else { st.checkOk = true; st.checkedAt = iso(Date.now()); }
      }
      if (!st.checkOk) { await save(api); return; }
    }
    if (!(await save(api))) { setOutcome(st, 'unsaved'); emit(); return; }
    const skip = new Set();
    let maxRows = MAX_ROWS;
    let total = { added: 0, there: 0 };
    let stopped = false;
    st.triedAt = iso(Date.now());
    for (let i = 0; i < MAX_REQUESTS; i += 1) {
      const batch = nextBatch(api, { skip, maxRows });
      if (!batch || !batch.refs.length) break;
      const res = await ask({ kind: 'serverSync', body: JSON.stringify(batch.lists) });
      const json = parse(res);
      if (res.ok && res.status === 200 && json) {
        const got = applyAnswer(api, batch, json, skip);
        total = { added: total.added + got.added, there: total.there + got.there };
        st.sentAt = iso(Date.now());
        await save(api);
        emit();
        continue;
      }
      if (res.ok && res.status === 400 && refuseNamed(api, batch, json)) { await save(api); continue; }
      if (res.ok && res.status === 413) {
        if (batch.refs.length > 1) { maxRows = Math.max(1, Math.floor(batch.refs.length / 2)); continue; }
        const r = st.rows[batch.refs[0].kind][batch.refs[0].id];
        r.s = 'refused'; r.w = 'It is too large to send.';
        await save(api);
        continue;
      }
      if (!stop(st, res, json)) { setOutcome(st, 'error', { status: res.status }); st.waitUntil = iso(Date.now() + ERROR_PAUSE_MS); }
      stopped = true;
      break;
    }
    if (!stopped) {
      const left = nextBatch(api, { skip });
      if (left && left.refs.length) soon(60 * 1000); // more than one run's worth: the rest follows in a minute
      const parts = [];
      if (total.added) parts.push(`${total.added} new ${total.added === 1 ? 'row' : 'rows'} sent`);
      if (total.there) parts.push(`${total.there} already there`);
      setOutcome(st, 'done', { message: parts.length ? `${parts.join(', ')}.` : MESSAGES.done });
    }
    await save(api);
  }
  // A stop answer (offline, not paired, the token refused, wait): sets the outcome and answers true. A 200 answers false.
  function stop(st, res, json) {
    if (res.error === 'not_paired') { setOutcome(st, 'not_paired'); return true; }
    if (res.error === 'no_app') { setOutcome(st, 'no_app'); return true; }
    if (res.error === 'offline') { setOutcome(st, 'offline'); return true; }
    if (res.error) { setOutcome(st, 'error'); st.waitUntil = iso(Date.now() + ERROR_PAUSE_MS); return true; }
    if (res.status === 401) { st.checkOk = false; st.checkedAt = iso(Date.now()); setOutcome(st, 'token', { status: 401 }); return true; }
    if (res.status === 404 || res.status === 405) { st.checkOk = false; st.checkedAt = iso(Date.now()); setOutcome(st, 'old_server', { status: res.status }); return true; }
    if (res.status === 429) {
      const secs = Math.min(Math.max(Number(res.retryAfter) || 60, 1), 2 * 24 * 3600);
      st.waitUntil = iso(Date.now() + secs * 1000);
      setOutcome(st, 'wait', { status: 429, message: json && json.detail ? `${json.detail} It tries again later.` : MESSAGES.wait });
      return true;
    }
    return false;
  }

  // Design note 39 (js/mock/server_changes.js): with a token both ways, a different account or server stops everything until the
  // person chooses, and after the new rows are sent the phone sends its edits and deletes and reads the server's changes.
  const both = () => M.serverChanges || null;
  function twoWay(api) { try { return !!(both() && both().active(api)); } catch (e) { return false; } }
  async function run({ force = false } = {}) {
    if (running) { again = true; return status(); }
    running = true; emit();
    try {
      const go = both() ? await both().gate({ force }) : true;
      if (go) {
        await runOnce(force);
        if (both()) await both().afterSend({ force });
      }
    } catch (e) { /* the next run tries again */ } finally { running = false; }
    emit();
    if (again) { again = false; soon(1000); }
    return status();
  }
  function soon(ms = SEND_DELAY_MS) {
    if (timer) clearTimeout(timer);
    timer = setTimeout(() => { timer = null; run(); }, ms);
    if (timer && typeof timer.unref === 'function') timer.unref(); // Node (the tests' page): a waiting send keeps nothing running
  }

  // What the screen shows (Settings → This device → Sending to your server).
  function label(api, kind, row) {
    const day = row.date || row.taken_on || '';
    if (kind === 'food') return `Food: ${row.name}`;
    if (kind === 'entry') return `Food log, ${day}: ${row.food_name}`;
    if (kind === 'lab') return `Lab result, ${day}: ${row.analyte}`;
    if (kind === 'symptom') return `Symptom, ${day}`;
    if (kind === 'weight') return `Weight, ${day}`;
    return `Blood pressure, ${day}`;
  }
  function status() {
    const api = M.instance;
    const st = peek(api);
    const out = { sample: !!(api && api._sample === true), server: st.outcome === 'not_paired' ? null : st.server, waiting: 0, refused: [], stuck: [],
      changedSince: 0, deletedSince: 0, sentAt: st.sentAt, triedAt: st.triedAt,
      outcome: st.outcome, message: st.message || (st.outcome ? MESSAGES[st.outcome] : null), waitUntil: st.waitUntil, running };
    if (!api || out.sample) return out;
    const all = rowsOf(api);
    for (const [, kind] of LISTS) {
      for (const row of all[kind]) {
        const r = (st.rows[kind] || {})[row.id];
        if (!done(r)) out.waiting += 1;
        else if (r.s === 'sent') { if (r.v && r.v !== versionNow(api, kind, row, r)) out.changedSince += 1; }
        else if (r.s === 'refused') out.refused.push({ text: label(api, kind, row), why: r.w || '' });
        else if (r.s === 'stuck') out.stuck.push({ text: label(api, kind, row), why: r.w || '' });
      }
      const kept = presentIds(api, kind, all);
      for (const [id, r] of Object.entries(st.rows[kind] || {})) if (r && r.s === 'sent' && !kept.has(id)) out.deletedSince += 1;
    }
    return out;
  }

  // When: after a save (debounced), when the app comes to the front, and at the start. Only once the log is read back.
  if (M.local && typeof M.local.subscribe === 'function') {
    let lastSaved = null;
    M.local.subscribe((s) => { if (s && s.on && s.savedAt && s.savedAt !== lastSaved) { lastSaved = s.savedAt; soon(); } });
  }
  try {
    if (typeof document !== 'undefined' && document && typeof document.addEventListener === 'function') {
      document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible') soon(1000); });
    }
  } catch (e) { /* no document */ }

  M.serverSync = {
    MAX_ROWS, MAX_BYTES, MAX_TRIES, MAX_REQUESTS, SEND_DELAY_MS,
    run, soon, status, sendNow: () => run({ force: true }),
    subscribe(fn) { listeners.add(fn); return () => listeners.delete(fn); },
    // for the tests: the pure parts
    _assignIds: assignIds, _nextBatch: nextBatch, _applyAnswer: applyAnswer, _refuseNamed: refuseNamed, _foodRef: foodRef, _blank: blank,
    _versionNow: versionNow,
  };
})();
