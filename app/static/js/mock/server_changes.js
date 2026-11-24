/* Kidney Diet Log — device mode only: the iPhone app and the person's server in step both ways (design note 39 §8, plan steps 6
   and 7; ARCHITECTURE.md "Device mode"; the server side is app/sync_feed.py, guide docs/push.md "The change feed").

   Step 4 (js/mock/server_sync.js) sends the rows made on this phone. With a token "For the iPhone app, both ways" this file adds:
   * Receive: GET /push/v1/changes from the saved cursor until `more` is false. The rows and the new cursor are saved in one save,
     so a run cut short starts again from the old cursor and changes nothing twice. 410 → read everything again (a full resync).
   * Send edits and deletes: POST /push/v1/changes, each with `base`, the server's version the change was made on, and `version`,
     the phone's version after it. Answers per row: done, conflict (nothing was written), gone, refused.
   * The first two-way sync of a phone that already has data (§8.7): POST /push/v1/match renames the phone's rows to the server's
     IDs, then everything is read from cursor 0 and each row the phone also has is compared. What cannot be decided goes to a
     review the person answers. The review never decides: until they choose, the server's copy is shown and the phone's is kept.
   * The account check (§8.8): `account` from GET /push/v1/about is kept with the cursor. A different account, or a different
     server, stops everything until the person chooses: send this iPhone's data there, replace it with the server's, or cancel.
   Note 02's rule holds throughout: another device's change is never overwritten silently. A conflict waits for the person:
   "Keep the saved one" or "Use mine". A low treatment is synced like any other entry; nothing here looks at `purpose`.

   What syncs here: food log entries, the person's own foods, saved meals and recipes (note 39 step 8), lab results (added and
   deleted only), symptoms, weights and blood pressure readings. A phone that synced before step 8 skipped the feed's saved meals:
   it reads the feed once more from the start for them (`meals`, `mcursor`), and a saved meal of this phone with the same name as
   one of the server's, never sent, is matched to it (the same: one row; different: the review). Step 4 sends this phone's saved
   meals only after that (`mealsReady`). The profile, targets and settings come from the server through js/mock/server_account.js.

   The page owns every rule and builds every request; the app only carries it through the `serverApi` bridge message
   (js/mock/server_api.js call(); ios/KidneyHealthCore/Sources/KidneyHealthCore/ServerAPI.swift has the allow-list).

   Saved with the rest of the log (js/mock/persist.js saves every property of the demo API), in `_serverChanges`:
       { v: 1, account: '<about.account>' | null, host: 'food.example.org' | null,
         cursor: '<next>' , first: true once the first two-way sync finished, full: true while everything is read again,
         meals: true once the server's saved meals were read, mcursor: where that reading is,
         rows: { food | entry | meal | lab | symptom | weight | reading: { <client_id>: { b: server version, l?: this phone's version
                 when the two agreed (when it differs from b), r?: the phone's version the server refused (or 'delete'),
                 w?: why } } },
         items: [{ key: 'kind:id', type: 'conflict' | 'differ' | 'deleted_here' | 'deleted_there', kind, id, op?: 'edit' |
                   'delete', server: <row as the feed shows it> | null, sv: its version | null, mine: <this phone's row> | null,
                   name, at }],
         notices: [{ text, at }],            dropped changes ("This entry no longer exists, so your change was dropped")
         ask: null | { account, host, before, cancelled? },   a different account or server waits for the person
         syncedAt, outcome, message, waitUntil }
   A row's ID is its client_id: an entry's own, every other kind's from step 4's queue (`_serverSync.rows[kind][id].c`). No DOM. */
(() => {
  'use strict';
  const KH = window.KH;
  const M = KH.mock;
  if (!KH.flags || KH.flags.DEVICE !== true || !M) return;

  const KINDS = ['food', 'entry', 'meal', 'lab', 'symptom', 'weight', 'reading'];
  const PAGE = 500; // app/sync_feed.py MAX_PAGE
  const MAX_PAGES = 20; // in one run; the rest follows in a minute
  const MAX_CHANGES = 200; // app/sync_feed.py MAX_CHANGES
  const MAX_BYTES = 256 * 1024 - 2048; // MAX_BODY_BYTES, with room to spare
  const MAX_MATCH = 2000; // MAX_MATCH_IDS
  const MAX_SEND_REQUESTS = 5;
  const EVERY_MS = 15 * 60 * 1000; // while the app is open (note 39 §8.5)
  const ERROR_PAUSE_MS = 5 * 60 * 1000;
  const MAX_NOTICES = 50;
  const VERSION_RE = /^[0-9a-f]{16}$/;
  const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
  const isDict = (v) => v != null && typeof v === 'object' && !Array.isArray(v);
  const RV = () => KH.rowVersions;

  const WHAT = { food: 'food', entry: 'entry', meal: 'saved meal', lab: 'lab result', symptom: 'symptom', weight: 'weight', reading: 'blood pressure reading' };
  const MESSAGES = {
    offline: 'Your server could not be reached. Changes wait on this iPhone and are sent later.',
    token: 'Your server did not accept the token for syncing both ways. Make a token for the iPhone app, both ways, and pair again.',
    old_server: 'Your server cannot sync both ways yet. Ask whoever runs it to update it or to turn on both ways.',
    wait: 'Your server asked the app to wait. It tries again later.',
    error: 'Your server could not sync just now. The app tries again later.',
    unsaved: 'The log could not be saved on this iPhone, so nothing was synced.',
    ask: 'This iPhone is paired with a different server or account. Choose what to do in Settings → This device.',
    done: 'Up to date.',
  };

  const listeners = new Set();
  const emit = () => { for (const fn of [...listeners]) { try { fn(); } catch (e) { /* a view that threw must not stop syncing */ } } };
  let changedRows = 0; // rows this phone took from the server since the views last asked (they reload Today)

  // ---- the saved state ----
  function blank() {
    return { v: 1, account: null, host: null, cursor: '0', first: false, full: false, meals: false, mcursor: '0', rows: Object.fromEntries(KINDS.map((k) => [k, {}])),
      items: [], notices: [], ask: null, syncedAt: null, outcome: null, message: null, waitUntil: null };
  }
  function stateOf(api) {
    if (!isDict(api._serverChanges)) api._serverChanges = blank();
    const st = api._serverChanges;
    if (!isDict(st.rows)) st.rows = {};
    for (const k of KINDS) if (!isDict(st.rows[k])) st.rows[k] = {};
    if (!Array.isArray(st.items)) st.items = [];
    if (!Array.isArray(st.notices)) st.notices = [];
    if (typeof st.cursor !== 'string') st.cursor = '0';
    return st;
  }
  const peek = (api) => (api && isDict(api._serverChanges) ? stateOf(api) : blank());
  function queue(api) { // step 4's saved state (js/mock/server_sync.js)
    if (!M.serverSync) return null;
    if (!api._serverSync) M.serverSync._assignIds(api);
    return api._serverSync;
  }
  const uidOf = (api) => { try { return api._currentUser().id; } catch (e) { return 1; } };
  const iso = (ms = Date.now()) => new Date(ms).toISOString();
  function uuid() {
    try { if (crypto && typeof crypto.randomUUID === 'function') return crypto.randomUUID(); } catch (e) { /* below */ }
    const b = new Uint8Array(16);
    crypto.getRandomValues(b);
    b[6] = (b[6] & 0x0f) | 0x40; b[8] = (b[8] & 0x3f) | 0x80;
    const x = [...b].map((n) => n.toString(16).padStart(2, '0')).join('');
    return `${x.slice(0, 8)}-${x.slice(8, 12)}-${x.slice(12, 16)}-${x.slice(16, 20)}-${x.slice(20)}`;
  }

  // ---- the phone's rows, by client_id ----
  function listOf(api, kind) {
    const uid = uidOf(api);
    if (kind === 'entry') return api._entries || [];
    if (kind === 'food') return (api._foods || []).filter((f) => f.source !== 'builtin');
    if (kind === 'meal') return api._templates || [];
    if (kind === 'lab') return api._labsState ? api._labsState().filter((r) => r.user_id === uid) : [];
    if (kind === 'symptom') return api._symptomsState ? api._symptomsState().filter((r) => r.user_id === uid) : [];
    if (kind === 'weight') return api._weightsOf ? api._weightsOf(uid) : [];
    return api._readingsOf ? api._readingsOf(uid) : [];
  }
  const markOf = (api, kind, row) => { const q = queue(api); return q && q.rows[kind] ? q.rows[kind][row.id] || null : null; };
  function cidOf(api, kind, row) {
    if (kind === 'entry') return row.client_id || null;
    const mark = markOf(api, kind, row);
    return mark && typeof mark.c === 'string' ? mark.c : null;
  }
  // kind → Map(client_id → the phone's row), built once a run and kept current by every change below.
  function indexOf(api, { assign = true } = {}) {
    if (assign && M.serverSync) M.serverSync._assignIds(api);
    const out = {};
    for (const kind of KINDS) {
      const map = new Map();
      for (const row of listOf(api, kind)) { const cid = cidOf(api, kind, row); if (cid) map.set(cid, row); }
      out[kind] = map;
    }
    return out;
  }
  // Whether the person still has the row (an own food deleted while an entry uses it stays, hidden).
  function present(api, kind, row) {
    if (!row) return false;
    if (kind !== 'food') return true;
    if (row.hidden) return false;
    return row.source === 'custom' || api._foodLinks().has(row.id);
  }
  function viewOf(api, kind, row) {
    if (kind === 'entry') return api._entryView(row);
    if (kind === 'food') return api._foodView(row);
    if (kind === 'meal') return api._templateView(row);
    return row;
  }
  function versionOf(api, kind, row) {
    try { return RV().version(kind, viewOf(api, kind, row)); } catch (e) { return null; }
  }

  // ---- the feed's rows as the phone keeps them ----
  // The fields of a server row (the export's shape) that the phone keeps, in the phone's names. Entries name their food separately.
  function shapeOf(kind, row) {
    if (kind === 'entry') {
      return { date: row.date, meal: row.meal, food_name: row.food_name, servings: Number(row.servings), grams: row.grams == null ? null : Number(row.grams),
        note: row.note == null ? null : row.note, status: row.status || 'eaten', nutrients: { ...(row.nutrients || {}) },
        purpose: row.purpose === 'hypo' ? 'hypo' : null };
    }
    if (kind === 'food') {
      return { name: row.name, brand: row.brand || null, category: row.category || null, serving_desc: row.serving_desc, serving_g: Number(row.serving_g),
        nutrients: { ...(row.nutrients || {}) }, flags: [...(row.flags || [])], kidney_notes: row.kidney_notes || null, hidden: !!row.hidden,
        gtin: row.gtin || null, ingredients_text: row.ingredients_text || null, source_url: row.source_url || null, source_license: row.source_license || null };
    }
    if (kind === 'meal') {
      return { name: row.name, note: row.note == null ? null : row.note, meal_hint: row.meal_hint || null,
        servings_made: row.servings_made == null ? null : Number(row.servings_made), steps: Array.isArray(row.steps) && row.steps.length ? [...row.steps] : null,
        source_url: row.source_url || null };
    }
    if (kind === 'lab') {
      return { analyte: row.analyte, value: row.value, entered_value: row.entered_value, entered_unit: row.entered_unit, taken_on: row.taken_on,
        note: row.note == null ? '' : row.note };
    }
    if (kind === 'symptom') return { date: row.date, symptom: row.symptom, label: row.label || '', severity: row.severity, note: row.note || '' };
    if (kind === 'weight') {
      return { date: row.date, time: row.time == null ? null : row.time, kg: row.kg, context: row.context, note: row.note || '',
        source: row.source || 'manual', source_key: row.source_key == null ? null : row.source_key };
    }
    return { date: row.date, time: row.time == null ? null : row.time, systolic: row.systolic, diastolic: row.diastolic,
      pulse: row.pulse == null ? null : row.pulse, context: row.context, note: row.note || '', source: row.source || 'manual',
      source_key: row.source_key == null ? null : row.source_key };
  }
  // The phone's own copy of a row (to show it, and to put it back with "Keep this iPhone's").
  function snapshot(kind, row) {
    const out = JSON.parse(JSON.stringify(row));
    delete out.id; delete out.user_id;
    return out;
  }

  // The phone's food for a feed reference (note 39 "as built": the shape POST /push/v1/sync takes). `foods` is the page's list.
  function resolveFood(ctx, ref, entryRow) {
    const { api, idx } = ctx;
    const record = (pred) => { const f = (ctx.foods || []).find((x) => isDict(x) && isDict(x.ref) && pred(x.ref)); return f && isDict(f.food) ? f.food : null; };
    if (isDict(ref) && typeof ref.client_id === 'string') {
      const here = idx.food.get(ref.client_id);
      if (here) return here;
      const rec = record((r) => r.client_id === ref.client_id);
      if (rec) return insertRow(ctx, 'food', ref.client_id, rec);
    } else if (isDict(ref) && isDict(ref.builtin)) {
      const b = ref.builtin;
      const all = api._foods.filter((f) => f.source === 'builtin');
      const found = (b.fdc_id != null && all.find((f) => f.fdc_id === b.fdc_id)) || all.find((f) => f.name === b.name);
      if (found) return found;
    } else if (isDict(ref) && (isDict(ref.usda) || isDict(ref.off))) {
      const usda = isDict(ref.usda);
      const key = usda ? ref.usda.fdc_id : ref.off.gtin;
      const here = api._foods.find((f) => (usda ? f.source === 'usda' && f.fdc_id === key : f.source === 'off' && f.gtin === key));
      if (here) { api._foodLinks().add(here.id); return here; }
      const rec = record((r) => (usda ? isDict(r.usda) && r.usda.fdc_id === key : isDict(r.off) && r.off.gtin === key));
      if (rec) {
        const row = api._storeServerFood({ ...rec, source: usda ? 'usda' : 'off' });
        markSent(ctx, 'food', row, uuid(), 'server');
        return row;
      }
    }
    // Not known here (a built-in list of another version): a hidden food of the entry's name and values keeps the entry whole.
    const servings = Number(entryRow.servings) || 1;
    const nutrients = {};
    for (const [k, v] of Object.entries(entryRow.nutrients || {})) nutrients[k] = v == null ? null : Number(v) / servings;
    const row = api._food(api._insertFood({ name: String(entryRow.food_name || 'Food'), serving_desc: '1 serving', serving_g: 100, nutrients, hidden: true }));
    markSent(ctx, 'food', row, uuid());
    return row;
  }
  // Step 4's mark for a row that came from the server: it is never sent as new.
  function markSent(ctx, kind, row, cid, from = null) {
    const q = queue(ctx.api);
    if (!q) return;
    const mark = { c: cid, s: 'sent' };
    if (from) mark.f = from; // a USDA or Open Food Facts food the server has: step 4 names it by its own keys
    q.rows[kind][row.id] = mark;
    try { const v = M.serverSync._versionNow(ctx.api, kind, row, mark); if (v) mark.v = v; } catch (e) { /* kept without */ }
  }
  function refreshMark(ctx, kind, row) {
    const mark = markOf(ctx.api, kind, row);
    if (!mark) return;
    mark.s = 'sent'; delete mark.d; delete mark.t; delete mark.g; delete mark.w;
    try { const v = M.serverSync._versionNow(ctx.api, kind, row, mark); if (v) mark.v = v; } catch (e) { /* kept as it was */ }
  }
  // A saved meal's items as the phone keeps them: each food found or kept as the feed names it.
  function mealItems(ctx, server) {
    return (Array.isArray(server.items) ? server.items : []).filter(isDict).map((it) => {
      const food = resolveFood(ctx, it.food, { food_name: it.food_name, servings: it.servings, nutrients: it.nutrients });
      return { food_id: food.id, servings: Number(it.servings) };
    });
  }
  function setFields(ctx, kind, row, server) {
    const shape = shapeOf(kind, server);
    if (kind === 'meal') {
      Object.assign(row, shape, { items: mealItems(ctx, server), updated_at: server.updated_at || ctx.api._stamp() });
      ctx.changed += 1;
      return row;
    }
    if (kind === 'entry') {
      const food = resolveFood(ctx, server.food, server);
      Object.assign(row, shape, { food_id: food.id, updated_at: server.updated_at || ctx.api._stamp() });
    } else if (kind === 'food') {
      Object.assign(row, shape, { updated_at: ctx.api._stamp() });
    } else {
      Object.assign(row, shape);
    }
    ctx.changed += 1;
    return row;
  }
  function insertRow(ctx, kind, cid, server) {
    const { api } = ctx;
    const uid = uidOf(api);
    const s = shapeOf(kind, server);
    let row;
    if (kind === 'entry') {
      const food = resolveFood(ctx, server.food, server);
      row = api._insertEntry({ date: s.date, meal: s.meal, food, servings: s.servings, grams: s.grams, note: s.note, status: s.status,
        createdAt: server.created_at || null, purpose: s.purpose, clientId: cid });
      Object.assign(row, { food_name: s.food_name, nutrients: s.nutrients, updated_at: server.updated_at || row.updated_at });
    } else if (kind === 'food') {
      row = api._food(api._insertFood({ ...s, source: 'custom' }));
      Object.assign(row, { serving_g: s.serving_g, nutrients: s.nutrients });
    } else if (kind === 'meal') {
      row = api._insertTemplate({ name: s.name, note: s.note, items: mealItems(ctx, server), mealHint: s.meal_hint, createdAt: server.created_at || null,
        servingsMade: s.servings_made, steps: s.steps, sourceUrl: s.source_url });
      if (server.updated_at) row.updated_at = server.updated_at;
    } else if (kind === 'lab') {
      row = api._insertLab(uid, { analyte: s.analyte, value: s.value, entered_value: s.entered_value, entered_unit: s.entered_unit }, s.taken_on, s.note,
        server.created_at || null);
    } else if (kind === 'symptom') {
      row = api._insertSymptom(uid, s, server.created_at || null);
    } else if (kind === 'weight') {
      row = api._insertWeight(uid, s, { source: s.source, sourceKey: s.source_key, createdAt: server.created_at || null });
    } else {
      row = api._insertReading(uid, s, { source: s.source, sourceKey: s.source_key, createdAt: server.created_at || null });
    }
    markSent(ctx, kind, row, cid);
    ctx.idx[kind].set(cid, row);
    ctx.changed += 1;
    return row;
  }
  // Removes the phone's row (an own food an entry still uses stays, hidden, as the delete route does), and step 4's mark with it.
  function removeRow(ctx, kind, cid) {
    const { api } = ctx;
    const row = ctx.idx[kind].get(cid);
    if (!row) return;
    const q = queue(api);
    const drop = (list) => { const i = list.indexOf(row); if (i >= 0) list.splice(i, 1); };
    let gone = true;
    if (kind === 'entry') drop(api._entries);
    else if (kind === 'food') {
      if (row.source !== 'custom') { api._foodLinks().delete(row.id); gone = false; } else if (api._foodReferenced(row.id)) { row.hidden = true; gone = false; } else {
        drop(api._foods); api._foodById.delete(row.id);
      }
    } else if (kind === 'meal') drop(api._templates);
    else if (kind === 'lab') drop(api._labsState());
    else if (kind === 'symptom') drop(api._symptomsState());
    else if (kind === 'weight') drop(api._weights);
    else drop(api._readings);
    if (gone) { if (q && q.rows[kind]) delete q.rows[kind][row.id]; ctx.idx[kind].delete(cid); }
    ctx.changed += 1;
  }
  function putBack(ctx, kind, cid, mine) {
    const row = ctx.idx[kind].get(cid);
    if (row) {
      const keep = { id: row.id, user_id: row.user_id, created_at: row.created_at, client_id: row.client_id };
      Object.assign(row, JSON.parse(JSON.stringify(mine)), keep);
      if (kind === 'food') row.hidden = !!mine.hidden;
      ctx.changed += 1;
      return row;
    }
    return null;
  }

  // ---- what the person sees of a row (the review and the conflict card) ----
  function amountText(row) {
    if (row.grams != null) return `${Number(row.grams)} g`;
    const n = Number(row.servings);
    return `${n} ${n === 1 ? 'serving' : 'servings'}`;
  }
  function nameOf(kind, row) {
    if (!row) return `this ${WHAT[kind]}`;
    if (kind === 'entry') return row.food_name || 'this entry';
    if (kind === 'food') return row.name || 'this food';
    if (kind === 'meal') return row.name || 'this saved meal';
    if (kind === 'lab') { const a = KH.kidney && KH.kidney.ANALYTES ? KH.kidney.ANALYTES[row.analyte] : null; return `${(a && a.label) || row.analyte} on ${row.taken_on}`; }
    if (kind === 'symptom') { const n = KH.symptomRules && KH.symptomRules.NAMES ? KH.symptomRules.NAMES[row.symptom] : null; return `${row.label || n || row.symptom} on ${row.date}`; }
    if (kind === 'weight') return `weight on ${row.date}`;
    return `blood pressure on ${row.date}`;
  }
  function lines(kind, row) {
    if (!row) return [];
    const note = (v) => (v ? String(v) : 'None');
    if (kind === 'entry') {
      const meal = KH.rules && KH.rules.MEAL_LABEL ? KH.rules.MEAL_LABEL[row.meal] || row.meal : row.meal;
      return [['Food', row.food_name], ['Day', row.date], ['Meal', meal], ['Amount', amountText(row)], ['Status', row.status === 'planned' ? 'Planned' : 'Eaten'],
        ['Note', note(row.note)]];
    }
    if (kind === 'food') {
      return [['Name', row.name], ['Serving', `${row.serving_desc} (${Number(row.serving_g)} g)`], ['Brand', row.brand || 'None'], ['Notes', note(row.kidney_notes)],
        ['Deleted', row.hidden ? 'Yes' : 'No']];
    }
    if (kind === 'meal') {
      const api = M.instance;
      const foodName = (it) => it.food_name || (api && api._foodById && api._foodById.get(Number(it.food_id)) ? api._foodById.get(Number(it.food_id)).name : 'A food');
      const items = (row.items || []).map((it) => `${foodName(it)} × ${Number(it.servings)}`).join(', ');
      return [['Name', row.name], ['Foods', items || 'None'], ['Servings it makes', row.servings_made == null ? 'Not set' : String(row.servings_made)],
        ['Steps', row.steps && row.steps.length ? String(row.steps.length) : 'None'], ['Note', note(row.note)]];
    }
    if (kind === 'lab') return [['Test', nameOf('lab', row).replace(/ on .*$/, '')], ['Value', `${row.entered_value} ${row.entered_unit || ''}`.trim()], ['Day', row.taken_on], ['Note', note(row.note)]];
    if (kind === 'symptom') {
      const sev = KH.symptomRules && KH.symptomRules.SEVERITY_LABELS ? KH.symptomRules.SEVERITY_LABELS[row.severity] || String(row.severity) : String(row.severity);
      return [['Symptom', nameOf('symptom', row).replace(/ on .*$/, '')], ['How bad', sev], ['Day', row.date], ['Note', note(row.note)]];
    }
    if (kind === 'weight') return [['Day', row.date], ['Time', row.time || 'None'], ['Weight', `${row.kg} kg`], ['Note', note(row.note)]];
    return [['Day', row.date], ['Time', row.time || 'None'], ['Reading', `${row.systolic}/${row.diastolic}`], ['Pulse', row.pulse == null ? 'None' : String(row.pulse)],
      ['Note', note(row.note)]];
  }

  // ---- talking to the server (through js/mock/server_api.js and the app's bridge) ----
  async function save(api) {
    if (typeof M.onWrite === 'function') M.onWrite(api, 'PUT', '/api/device/server-changes');
    if (!M.local || !M.local.on()) return false;
    const s = await M.local.flush();
    return !(s && (s.error || s.conflict));
  }
  function setOutcome(st, outcome, extra = {}) {
    const message = extra.message || MESSAGES[outcome] || null;
    if (st.outcome === outcome && st.message === message) return false;
    st.outcome = outcome; st.message = message;
    return true;
  }
  // An answer that stops the run: sets the outcome and answers true.
  function stopped(st, res) {
    if (res.offline) { setOutcome(st, 'offline'); return true; }
    if (res.error) { setOutcome(st, 'error'); st.waitUntil = iso(Date.now() + ERROR_PAUSE_MS); return true; }
    if (res.status === 401 || res.status === 403) { setOutcome(st, 'token'); return true; }
    if (res.status === 404 || res.status === 405) { setOutcome(st, 'old_server'); st.waitUntil = iso(Date.now() + ERROR_PAUSE_MS); return true; }
    if (res.status === 429) {
      const secs = Math.min(Math.max(Number(res.retryAfter) || 60, 1), 2 * 24 * 3600);
      st.waitUntil = iso(Date.now() + secs * 1000);
      setOutcome(st, 'wait');
      return true;
    }
    if (res.status !== 200 || !isDict(res.json)) { setOutcome(st, 'error'); st.waitUntil = iso(Date.now() + ERROR_PAUSE_MS); return true; }
    return false;
  }

  // ---- the account check (note 39 §8.8) ----
  function hasData(api) {
    return (api._entries || []).length > 0 || KINDS.some((k) => k !== 'entry' && listOf(api, k).some((r) => k !== 'food' || r.source === 'custom'));
  }
  // Before anything is sent: false while a different account or server waits for the person's choice.
  async function gate({ force = false } = {}) {
    const api = M.instance;
    const A = M.serverApi;
    if (!api || api._sample === true || !A) return true;
    const k = await A.check({ force });
    if (!k || k.state !== 'both' || !k.about || !k.about.account) return true; // no two-way sync: step 4 goes on as before
    const st = stateOf(api);
    const account = k.about.account;
    const host = k.server || null;
    if (st.account === account) {
      if (st.ask) { st.ask = null; setOutcome(st, null); await save(api); emit(); }
      if (st.host !== host) { st.host = host; await save(api); } // the same account, a new token or address: go on from the cursor
      return true;
    }
    const before = st.account ? st.host : (st.host || (api._serverSync && api._serverSync.server) || null);
    const differs = st.account ? true : !!(before && before !== host);
    if (!differs || !hasData(api)) { // the first pairing, or nothing on this phone to keep apart
      const keep = st.account ? blank() : st;
      Object.assign(st, keep === st ? {} : keep, { account, host, ask: null });
      await save(api);
      return true;
    }
    if (!st.ask || st.ask.account !== account || st.ask.host !== host) {
      st.ask = { account, host, before };
      setOutcome(st, 'ask');
      await save(api);
      emit();
    }
    return false;
  }
  // The person's answer: 'send' (everything is sent there as new), 'replace' (this phone starts over from the server's data), or
  // 'cancel' (nothing changes; sync stays stopped until the old pairing is back or they choose).
  async function choose(choice) {
    const api = M.instance;
    const st = stateOf(api);
    if (!st.ask) return status();
    const { account, host } = st.ask;
    if (choice === 'cancel') { st.ask.cancelled = true; await save(api); emit(); return status(); }
    if (choice !== 'send' && choice !== 'replace') return status();
    if (choice === 'replace') {
      await save(api); // the safety copy in the Files app is made from this save (js/mock/persist.js)
      const ctx = context(api);
      for (const kind of ['entry', ...KINDS.filter((k) => k !== 'entry')]) for (const cid of [...ctx.idx[kind].keys()]) removeRow(ctx, kind, cid);
      for (const f of api._foods.filter((x) => x.source !== 'builtin')) api._foodLinks().delete(f.id);
      api._entries.splice(0, api._entries.length);
      api._serverSync = M.serverSync._blank();
      api._serverSync.server = host;
    } else {
      const q = queue(api);
      for (const kind of Object.keys(q.rows)) for (const r of Object.values(q.rows[kind])) { delete r.s; delete r.t; delete r.g; delete r.w; delete r.v; delete r.d; }
      Object.assign(q, { server: host, sentAt: null, checkOk: false, checkedAt: null, waitUntil: null });
    }
    api._serverChanges = Object.assign(blank(), { account, host });
    changedRows += 1;
    await save(api);
    emit();
    if (M.serverSync) M.serverSync.soon(500);
    return status();
  }

  // ---- one run ----
  function context(api) { return { api, st: stateOf(api), idx: indexOf(api), foods: [], changed: 0 }; }
  const keyOf = (kind, id) => `${kind}:${id}`;
  const itemOf = (st, kind, id) => st.items.find((x) => x.key === keyOf(kind, id)) || null;
  function addItem(ctx, item) {
    const { st } = ctx;
    const key = keyOf(item.kind, item.id);
    const i = st.items.findIndex((x) => x.key === key);
    const full = { key, at: iso(), ...item };
    if (i >= 0) st.items[i] = full; else st.items.push(full);
    ctx.changed += 1;
  }
  function dropItem(st, kind, id) { st.items = st.items.filter((x) => x.key !== keyOf(kind, id)); }
  function notice(ctx, text) {
    ctx.st.notices.push({ text, at: iso() });
    if (ctx.st.notices.length > MAX_NOTICES) ctx.st.notices.splice(0, ctx.st.notices.length - MAX_NOTICES);
    ctx.changed += 1;
  }
  const dropped = (kind, name) => `This ${WHAT[kind]} no longer exists, so your change was dropped: ${name}.`;
  function agree(ctx, kind, cid, version, row) {
    const lv = row ? versionOf(ctx.api, kind, row) : null;
    const rs = { b: version };
    if (lv && lv !== version) rs.l = lv;
    ctx.st.rows[kind][cid] = rs;
    if (row) refreshMark(ctx, kind, row);
  }
  function takeServer(ctx, kind, cid, server, version) {
    const here = ctx.idx[kind].get(cid);
    const row = here ? setFields(ctx, kind, here, server) : insertRow(ctx, kind, cid, server);
    agree(ctx, kind, cid, version, row);
    return row;
  }

  // One change of the feed. `first`: the first two-way sync (§8.7), for rows this phone has no agreed version of yet.
  // A saved meal of this phone, never sent, with the same name as the server's new one: it becomes that row (§8.7: the same
  // version is one row; a different one goes to the review). Saved meals did not sync before note 39 step 8.
  function matchMealByName(ctx, c) {
    const { api, st, idx } = ctx;
    if (idx.meal.has(c.id)) return;
    const name = String(c.row.name || '').trim().toLowerCase();
    const q = queue(api);
    for (const [cid, t] of idx.meal) {
      if (String(t.name || '').trim().toLowerCase() !== name || st.rows.meal[cid] || itemOf(st, 'meal', cid)) continue;
      const mark = markOf(api, 'meal', t);
      if (!mark || mark.s) continue; // sent, refused or stuck: not this phone's unsent copy
      mark.c = c.id;
      idx.meal.delete(cid); idx.meal.set(c.id, t);
      if (q) ctx.changed += 1;
      return;
    }
  }
  function applyChange(ctx, c, { first = false, seen = null, only = null } = {}) {
    const { api, st, idx } = ctx;
    const kind = c.kind;
    if (!KINDS.includes(kind) || typeof c.id !== 'string' || !UUID_RE.test(c.id)) return;
    if (only && kind !== only) return; // reading the feed again for saved meals alone
    if (seen) seen.add(keyOf(kind, c.id));
    const put = c.op === 'put';
    if (put && (!isDict(c.row) || !VERSION_RE.test(String(c.version)))) return;
    if (put && kind === 'meal' && !st.rows.meal[c.id]) matchMealByName(ctx, c);
    const row = idx[kind].get(c.id) || null;
    const here = present(api, kind, row);
    const rs = st.rows[kind][c.id] || null;
    const item = itemOf(st, kind, c.id);
    const lv = here ? versionOf(api, kind, row) : null;

    if (item) { // a row that waits for the person: keep it waiting, with the server's latest copy
      if (put) {
        item.server = c.row; item.sv = c.version;
        if (item.type === 'differ' || item.type === 'deleted_here') takeServer(ctx, kind, c.id, c.row, c.version);
        ctx.changed += 1;
        return;
      }
      if (item.type === 'conflict') {
        if (item.op === 'edit') { notice(ctx, dropped(kind, item.name)); removeRow(ctx, kind, c.id); }
        dropItem(st, kind, c.id);
      } else if (item.type === 'differ') {
        if (item.mine && row) putBack(ctx, kind, c.id, item.mine);
        addItem(ctx, { type: 'deleted_there', kind, id: c.id, server: null, sv: null, mine: item.mine, name: item.name });
      } else if (item.type === 'deleted_here') {
        removeRow(ctx, kind, c.id);
        dropItem(st, kind, c.id);
      }
      delete st.rows[kind][c.id];
      ctx.changed += 1;
      return;
    }

    if (!rs) { // no agreed version yet (§8.7, and a row step 4 just sent): compare with what step 1 remembered when it was sent
      const mark = row ? markOf(api, kind, row) : null;
      const sent = mark && mark.s === 'sent' && mark.v ? mark : null;
      const phoneChanged = () => (here ? M.serverSync._versionNow(api, kind, row, mark) !== sent.v : true);
      if (put) {
        if (!row && deletedHere(api, kind, c.id)) {
          forgetMark(api, kind, c.id);
          if (!first) { st.rows[kind][c.id] = { b: c.version }; ctx.changed += 1; return; } // deleted here since step 4 sent it: the delete is sent
          takeServer(ctx, kind, c.id, c.row, c.version); // the first sync: the server's copy is shown until the person chooses
          addItem(ctx, { type: 'deleted_here', kind, id: c.id, server: c.row, sv: c.version, mine: null, name: nameOf(kind, c.row) });
          return;
        }
        if (!row) { takeServer(ctx, kind, c.id, c.row, c.version); return; }
        if (!here) { // deleted on this phone after it was sent: the server's copy is shown until the person chooses
          const mine = snapshot(kind, row);
          takeServer(ctx, kind, c.id, c.row, c.version);
          addItem(ctx, { type: 'deleted_here', kind, id: c.id, server: c.row, sv: c.version, mine, name: nameOf(kind, c.row) });
          return;
        }
        if (lv === c.version) { agree(ctx, kind, c.id, c.version, row); return; }
        if (sent) {
          const serverChanged = kind === 'entry' || kind === 'meal' ? c.version !== sent.v
            : M.serverSync._versionNow(api, kind, { ...row, ...shapeOf(kind, c.row), created_at: row.created_at }, mark) !== sent.v;
          const mineChanged = phoneChanged();
          if (mineChanged && !serverChanged) { st.rows[kind][c.id] = { b: c.version }; ctx.changed += 1; return; } // sent as an edit
          if (!mineChanged && serverChanged) { takeServer(ctx, kind, c.id, c.row, c.version); return; }
        }
        const mine = snapshot(kind, row);
        takeServer(ctx, kind, c.id, c.row, c.version);
        addItem(ctx, { type: 'differ', kind, id: c.id, server: c.row, sv: c.version, mine, name: nameOf(kind, c.row) });
        return;
      }
      if (!row || !here) { if (row) removeRow(ctx, kind, c.id); forgetMark(api, kind, c.id); return; }
      if (sent && !phoneChanged()) { removeRow(ctx, kind, c.id); return; }
      addItem(ctx, { type: 'deleted_there', kind, id: c.id, server: null, sv: null, mine: snapshot(kind, row), name: nameOf(kind, row) });
      return;
    }

    const pending = !here || lv !== (rs.l || rs.b);
    if (put) {
      if (c.version === rs.b) { // the server has what the phone agreed on: a waiting change goes out as it is
        if (!pending && here && lv !== c.version) takeServer(ctx, kind, c.id, c.row, c.version); // the server's way of saving it
        return;
      }
      if (!pending) { takeServer(ctx, kind, c.id, c.row, c.version); return; }
      if (here && lv === c.version) { agree(ctx, kind, c.id, c.version, row); return; } // the same change on both sides
      addItem(ctx, { type: 'conflict', kind, id: c.id, op: here ? 'edit' : 'delete', server: c.row, sv: c.version, mine: here ? snapshot(kind, row) : null,
        name: nameOf(kind, here ? row : c.row) });
      return;
    }
    if (row && here && pending) notice(ctx, dropped(kind, nameOf(kind, row)));
    if (row) removeRow(ctx, kind, c.id);
    delete st.rows[kind][c.id];
    ctx.changed += 1;
  }

  // POST /push/v1/match: the server's ID for each of the phone's rows; the phone takes it (§8.2, §8.7).
  async function match(ctx) {
    const { api, idx } = ctx;
    const ids = [];
    for (const kind of KINDS) for (const cid of idx[kind].keys()) ids.push([kind, cid]);
    for (let i = 0; i < ids.length; i += MAX_MATCH) {
      const body = { ids: {} };
      for (const [kind, cid] of ids.slice(i, i + MAX_MATCH)) (body.ids[kind] = body.ids[kind] || []).push(cid);
      const res = await M.serverApi.call('POST', '/push/v1/match', { body });
      if (stopped(ctx.st, res)) return false;
      const known = isDict(res.json.known) ? res.json.known : {};
      for (const kind of KINDS) {
        for (const [mine, theirs] of Object.entries(isDict(known[kind]) ? known[kind] : {})) {
          if (mine === theirs || typeof theirs !== 'string' || !UUID_RE.test(theirs)) continue;
          const row = idx[kind].get(mine);
          if (!row) continue;
          const other = idx[kind].get(theirs);
          if (other && versionOf(api, kind, other) === versionOf(api, kind, row)) { removeRow(ctx, kind, mine); continue; } // one row each
          if (other) continue; // two different rows here: both stay; this one keeps its own ID
          if (kind === 'entry') row.client_id = theirs;
          const mark = markOf(api, kind, row);
          if (mark) mark.c = theirs;
          idx[kind].delete(mine); idx[kind].set(theirs, row);
          ctx.changed += 1;
        }
      }
    }
    return true;
  }

  // Reads the feed from the saved cursor. `mode`: 'first' (§8.7), 'full' (after 410: rows not in the answer are gone), 'meals'
  // (once, from the start, for the saved meals a phone skipped before note 39 step 8) or 'steady'.
  async function receive(ctx, mode) {
    const { api, st } = ctx;
    const seen = mode === 'full' ? new Set() : null;
    let after = mode === 'steady' ? st.cursor : '0';
    if (mode === 'first') after = st.cursor; // a first sync cut short goes on from where it was
    if (mode === 'meals') after = typeof st.mcursor === 'string' ? st.mcursor : '0';
    for (let page = 0; page < MAX_PAGES; page += 1) {
      const res = await M.serverApi.call('GET', `/push/v1/changes?after=${encodeURIComponent(after)}&limit=${PAGE}`);
      if (!res.offline && !res.error && res.status === 410) {
        if (mode === 'full') { setOutcome(st, 'error'); return false; }
        if (mode === 'meals') { st.meals = true; st.full = true; st.cursor = '0'; await save(api); return receive(ctx, 'full'); }
        st.full = true; st.cursor = '0';
        await save(api);
        return receive(ctx, 'full');
      }
      if (stopped(st, res)) return false;
      const answer = res.json;
      const changes = Array.isArray(answer.changes) ? answer.changes : [];
      ctx.foods = Array.isArray(answer.foods) ? answer.foods : [];
      for (const c of changes) if (isDict(c)) applyChange(ctx, c, { first: mode === 'first' || mode === 'meals', seen, only: mode === 'meals' ? 'meal' : null });
      if (typeof answer.next === 'string' && /^(0|[1-9][0-9]{0,18})$/.test(answer.next)) after = answer.next;
      if (mode === 'meals') st.mcursor = after;
      else if (mode !== 'full') st.cursor = after; // the rows and the cursor in one save
      if (mode === 'meals' && !answer.more) st.meals = true;
      st.syncedAt = iso();
      if (!(await save(api))) { setOutcome(st, 'unsaved'); return false; }
      if (ctx.changed) { changedRows += ctx.changed; ctx.changed = 0; emit(); }
      if (!answer.more) {
        if (mode === 'full') {
          for (const kind of KINDS) {
            for (const cid of Object.keys(st.rows[kind])) {
              if (!seen.has(keyOf(kind, cid))) applyChange(ctx, { kind, id: cid, op: 'delete', version: null });
            }
          }
          st.full = false; st.cursor = after;
          await save(api);
        }
        return true;
      }
    }
    if (M.serverSync) M.serverSync.soon(60 * 1000); // more than one run's worth: the rest follows in a minute
    return true;
  }

  // ---- sending edits and deletes (step 7) ----
  function editBody(api, kind, row) {
    if (kind === 'meal') { // each food named as the server knows it; null while one still waits to be sent (step 4 sends it first)
      const refs = [];
      for (const it of row.items || []) {
        const r = M.serverSync._refOf(api, api._foodById.get(Number(it.food_id)));
        if (!r.ref) return null;
        refs.push(r.ref);
      }
      return M.serverSync._mealFields(row, refs);
    }
    if (kind === 'entry') {
      const out = { date: row.date, meal: row.meal, status: row.status || 'eaten', note: row.note == null ? null : row.note, purpose: row.purpose === 'hypo' ? 'hypo' : 'none' };
      if (row.grams != null) out.grams = row.grams; else out.servings = row.servings;
      return out;
    }
    if (kind === 'food') {
      const nutrients = {};
      for (const [k, v] of Object.entries(row.nutrients || {})) if (v != null) nutrients[k] = v;
      return { name: row.name, brand: row.brand || null, category: row.category || null, serving_desc: row.serving_desc, serving_g: row.serving_g, nutrients,
        flags: [...(row.flags || [])], kidney_notes: row.kidney_notes || null, gtin: row.gtin || null, ingredients_text: row.ingredients_text || null };
    }
    if (kind === 'symptom') return { date: row.date, symptom: row.symptom, severity: row.severity, label: row.label || '', note: row.note || '' };
    if (kind === 'weight') return { date: row.date, time: row.time || null, kg: row.kg, context: row.context, note: row.note || '' };
    return { date: row.date, time: row.time || null, systolic: row.systolic, diastolic: row.diastolic, pulse: row.pulse == null ? null : row.pulse,
      context: row.context, note: row.note || '' };
  }
  // The changes that wait: [{ change, lv }] (lv: the phone's version, null for a delete).
  function waiting(ctx) {
    const { api, st, idx } = ctx;
    const out = [];
    for (const kind of KINDS) {
      for (const [cid, rs] of Object.entries(st.rows[kind])) {
        if (itemOf(st, kind, cid) || !rs || !VERSION_RE.test(String(rs.b))) continue;
        const row = idx[kind].get(cid);
        if (!present(api, kind, row)) {
          if (rs.r === 'delete') continue;
          out.push({ change: { kind, id: cid, op: 'delete', base: rs.b }, lv: null });
          continue;
        }
        const lv = versionOf(api, kind, row);
        if (!lv || lv === (rs.l || rs.b) || rs.r === lv) continue;
        if (kind === 'lab') { rs.l = lv; continue; } // lab results are only added and deleted
        const fields = editBody(api, kind, row);
        if (!fields) continue; // a saved meal whose new food waits to be sent
        const change = { kind, id: cid, op: 'edit', base: rs.b, fields };
        if (VERSION_RE.test(lv)) change.version = lv;
        out.push({ change, lv });
      }
    }
    return out;
  }
  async function send(ctx) {
    const { api, st, idx } = ctx;
    for (let n = 0; n < MAX_SEND_REQUESTS; n += 1) {
      const all = waiting(ctx);
      if (!all.length) return true;
      const batch = [];
      let size = 16;
      for (const w of all) {
        const b = new TextEncoder().encode(JSON.stringify(w.change)).length + 1;
        if (batch.length >= MAX_CHANGES || size + b > MAX_BYTES) break;
        batch.push(w); size += b;
      }
      if (!batch.length) { const w = all[0]; st.rows[w.change.kind][w.change.id].r = w.lv || 'delete'; st.rows[w.change.kind][w.change.id].w = 'It is too large to send.'; continue; }
      const res = await M.serverApi.call('POST', '/push/v1/changes', { body: { changes: batch.map((w) => w.change) } });
      if (stopped(st, res)) return false;
      const results = Array.isArray(res.json.results) ? res.json.results : [];
      batch.forEach((w, i) => {
        const r = isDict(results[i]) && results[i].id === w.change.id ? results[i] : results.find((x) => isDict(x) && x.id === w.change.id && x.kind === w.change.kind);
        const { kind, id, op } = w.change;
        const rs = st.rows[kind][id];
        const row = idx[kind].get(id);
        if (!r || !rs) return;
        if (r.status === 'done') {
          if (op === 'delete') { delete st.rows[kind][id]; if (row && !present(api, kind, row)) removeRow(ctx, kind, id); else if (!row) forgetMark(api, kind, id); }
          else { st.rows[kind][id] = r.version && VERSION_RE.test(r.version) ? (r.version === w.lv ? { b: r.version } : { b: r.version, l: w.lv }) : rs; if (row) refreshMark(ctx, kind, row); }
          ctx.changed += 1;
        } else if (r.status === 'conflict' && isDict(r.row)) {
          addItem(ctx, { type: 'conflict', kind, id, op, server: r.row, sv: r.version, mine: row && op === 'edit' ? snapshot(kind, row) : null,
            name: nameOf(kind, op === 'edit' && row ? row : r.row) });
        } else if (r.status === 'gone') {
          if (op === 'edit') { notice(ctx, dropped(kind, nameOf(kind, row))); removeRow(ctx, kind, id); } else forgetMark(api, kind, id);
          delete st.rows[kind][id];
          ctx.changed += 1;
        } else if (r.status === 'refused') {
          rs.r = op === 'delete' ? 'delete' : w.lv; rs.w = String(r.detail || 'Your server refused it.').slice(0, 300);
          ctx.changed += 1;
        }
      });
      if (!(await save(api))) { setOutcome(st, 'unsaved'); return false; }
      if (ctx.changed) { changedRows += ctx.changed; ctx.changed = 0; emit(); }
    }
    return true;
  }
  // Step 4's mark of a row deleted on this phone after it was sent.
  function deletedHere(api, kind, cid) {
    const q = queue(api);
    return !!(q && q.rows[kind] && Object.values(q.rows[kind]).some((m) => m && m.c === cid && m.d === 1));
  }
  // Forgets that mark once the server has the row deleted too (or the row came back from the server).
  function forgetMark(api, kind, cid) {
    const q = queue(api);
    if (!q || !q.rows[kind]) return;
    for (const [id, mark] of Object.entries(q.rows[kind])) if (mark && mark.c === cid && mark.d === 1) delete q.rows[kind][id];
  }

  // Whether this phone syncs both ways now: a token both ways, a server with the feed, the same account, nothing to ask.
  function active(api = M.instance) {
    const A = M.serverApi;
    const k = A ? A.status() : null;
    if (!api || api._sample === true || !k || k.state !== 'both' || !k.about || !k.about.account || k.about.sync === false
      || k.about.changes === false) return false;
    const st = peek(api);
    return !st.ask && st.account === k.about.account;
  }

  // After step 4 sent the new rows: the first sync, or send the waiting changes, then read the feed (note 39 §8.5).
  let running = false;
  async function afterSend({ force = false } = {}) {
    const api = M.instance;
    if (running || !api || !M.local || !M.local.on() || !active(api)) return status();
    const st = stateOf(api);
    if (!force && st.waitUntil && Date.now() < Date.parse(st.waitUntil)) return status();
    running = true; emit();
    try {
      st.waitUntil = null;
      const ctx = context(api);
      if (!st.first) {
        if (!(await match(ctx))) return status();
        if (ctx.changed && !(await save(api))) { setOutcome(st, 'unsaved'); return status(); }
        if (!(await receive(ctx, 'first'))) return status();
        st.first = true; st.meals = true;
        await save(api);
      }
      if (!st.meals) { // a phone that synced before note 39 step 8: the server's saved meals, once
        if (!(await receive(ctx, 'meals'))) return status();
        await save(api);
        if (st.meals && M.serverSync) M.serverSync.soon(1000); // this phone's own saved meals are sent next
      }
      if (!(await send(ctx))) return status();
      if (!(await receive(ctx, st.full ? 'full' : 'steady'))) return status();
      setOutcome(st, 'done');
      await save(api);
    } catch (e) {
      setOutcome(st, 'error');
    } finally {
      running = false;
      emit();
    }
    return status();
  }

  // ---- the person's choices on a card ----
  // 'server': "Keep the saved one" / "Keep your server's" / "Keep it" / "Delete it here".
  // 'mine': "Use mine" / "Keep this iPhone's" / "Delete it there".
  async function decide(key, choice) {
    const api = M.instance;
    const st = stateOf(api);
    const item = st.items.find((x) => x.key === key);
    if (!item || (choice !== 'server' && choice !== 'mine')) return status();
    const ctx = context(api);
    const { kind, id } = item;
    if (choice === 'server') {
      if (item.type === 'deleted_there') { removeRow(ctx, kind, id); delete st.rows[kind][id]; } else if (item.server) takeServer(ctx, kind, id, item.server, item.sv);
    } else if (item.type === 'deleted_there') { // sent again as a new row, with a new ID (the old one is spent on the server)
      const row = ctx.idx[kind].get(id);
      if (row) {
        if (kind === 'food') row.hidden = false;
        if (kind === 'entry') row.client_id = uuid();
        const q = queue(api);
        if (q && q.rows[kind]) q.rows[kind][row.id] = kind === 'entry' ? { c: row.client_id } : { c: uuid() };
      }
      delete st.rows[kind][id];
    } else if (item.type === 'conflict') {
      st.rows[kind][id] = { b: item.sv };
    } else if (item.type === 'differ') {
      if (item.mine) putBack(ctx, kind, id, item.mine);
      st.rows[kind][id] = { b: item.sv };
    } else if (item.type === 'deleted_here') {
      removeRow(ctx, kind, id);
      st.rows[kind][id] = { b: item.sv };
    }
    dropItem(st, kind, id);
    changedRows += 1;
    await save(api);
    emit();
    if (M.serverSync) M.serverSync.soon(1000);
    return status();
  }
  async function clearNotices() {
    const api = M.instance;
    const st = stateOf(api);
    st.notices = [];
    await save(api);
    emit();
  }

  // What the screen shows (Settings → This device → Your server).
  function status() {
    const api = M.instance;
    const st = peek(api);
    const out = { active: active(api), running, account: st.account, host: st.host, first: !!st.first, syncedAt: st.syncedAt, outcome: st.outcome,
      message: st.message || (st.outcome ? MESSAGES[st.outcome] : null), ask: st.ask ? { ...st.ask } : null, waiting: 0, refused: [],
      items: st.items.map((x) => ({ key: x.key, type: x.type, kind: x.kind, op: x.op || null, name: x.name, what: WHAT[x.kind],
        server: lines(x.kind, x.server), mine: lines(x.kind, x.mine) })),
      notices: st.notices.map((n) => n.text), review: st.items.length };
    if (!api || !out.active) return out;
    try {
      const ctx = { api, st, idx: indexOf(api, { assign: false }), foods: [], changed: 0 }; // drawing changes nothing
      out.waiting = waiting(ctx).length;
      for (const kind of KINDS) {
        for (const [cid, rs] of Object.entries(st.rows[kind])) {
          if (rs && rs.r) out.refused.push({ text: `${WHAT[kind][0].toUpperCase()}${WHAT[kind].slice(1)}: ${nameOf(kind, ctx.idx[kind].get(cid))}`, why: rs.w || '' });
        }
      }
    } catch (e) { /* the counts wait for the next draw */ }
    return out;
  }
  // The views ask whether rows came from the server since they last drew (Today reloads its day).
  function takeChanged() { const n = changedRows; changedRows = 0; return n; }
  // Step 4 sends this phone's saved meals only once the server's were read (above).
  function mealsReady(api = M.instance) { return active(api) && peek(api).meals === true; }
  // Whether a row waits for the person in the review (Today marks such an entry "needs review", design note 39 §8.6).
  function needsReview(kind, id) {
    const api = M.instance;
    if (!api || !id || !isDict(api._serverChanges) || !Array.isArray(api._serverChanges.items)) return false;
    return api._serverChanges.items.some((x) => x.key === keyOf(kind, String(id)));
  }

  // Every 15 minutes while the app is open (and step 4's own times: after a save, at the front, at the start).
  try {
    const t = setInterval(() => { if (active() && M.serverSync) M.serverSync.run(); }, EVERY_MS);
    if (t && typeof t.unref === 'function') t.unref();
  } catch (e) { /* no timers */ }

  M.serverChanges = {
    KINDS, PAGE, MAX_CHANGES, EVERY_MS,
    gate, afterSend, active, status, decide, choose, clearNotices, takeChanged, mealsReady, needsReview,
    _touched() { changedRows += 1; emit(); }, // js/mock/server_account.js copied the server's profile or settings: the views redraw
    subscribe(fn) { listeners.add(fn); return () => listeners.delete(fn); },
    // for the tests: the pure parts
    _blank: blank, _applyChange: (api, c, opts) => { const ctx = context(api); ctx.foods = (opts && opts.foods) || []; applyChange(ctx, c, opts || {}); return ctx; },
    _waiting: (api) => waiting(context(api)).map((w) => w.change), _editBody: editBody, _lines: lines, _versionOf: versionOf,
  };
})();
