#!/usr/bin/env node
// Device mode, design note 39 steps 6 and 7: the phone and the person's server in step both ways (js/mock/server_changes.js).
// A stand-in for the iPhone app's "bridge" answers like the app would. Two servers stand behind it:
//
//   node tests/js/server_changes.mjs           a small fake of app/sync_feed.py (GET and POST /push/v1/changes, POST
//                                              /push/v1/match, GET /push/v1/about, POST /push/v1/sync), for the edge cases:
//                                              receive, the web's edits and deletes, the phone's edits and deletes with base
//                                              versions, conflicts and both answers, gone, refused, 410 and a full resync,
//                                              planned entries sent at once, the first sync with its review, a different
//                                              account, offline, 429, and a low treatment synced like any entry.
//   node tests/js/server_changes.mjs --relay   the real server: each bridge request is written to stdout as one line
//                                              "@@ {json}" and its answer read from stdin (tests/test_server_changes_phone.py
//                                              runs the routes and plays the web app). The page's requests meet the real
//                                              routes, and the versions the phone works out must equal the server's.
// Exits 1 with the failed check on any mismatch.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { createInterface } from 'node:readline';
import { fileURLToPath } from 'node:url';
import { loadDemo } from './demo_loader.mjs';
import { createFakeIndexedDB } from './fake_idb.mjs';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..', '..');
const FOODS = readFileSync(join(ROOT, 'data', 'foods.json'), 'utf8');
const CLONE_SRC = `(function clone(v) {
  if (v === null || typeof v !== 'object') return v;
  const tag = Object.prototype.toString.call(v);
  if (tag === '[object Map]') return new Map([...v].map(([k, x]) => [clone(k), clone(x)]));
  if (tag === '[object Set]') return new Set([...v].map(clone));
  if (Array.isArray(v)) return v.map(clone);
  const o = {}; for (const k of Object.keys(v)) o[k] = clone(v[k]); return o;
})`;
const RELAY = process.argv.includes('--relay');
const day = (n) => { const d = new Date(); d.setDate(d.getDate() + n); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; };
const D = day(-1);
const plain = (v) => JSON.parse(JSON.stringify(v));
let checks = 0;
const ok = (fn, label) => { checks += 1; try { fn(); } catch (e) { e.message = `${label}: ${e.message}`; throw e; } };
const ACCOUNT = 'a'.repeat(32);
const uuid = () => crypto.randomUUID();

// ---------------------------------------------------------------------------------------------------------------- the fake server
// Rows in the export's shape by kind and client_id, a change log (one id per write, AUTOINCREMENT-like), tombstones, receipts.
// Versions come from the page's own twin (KH.rowVersions), so a row the fake keeps as the phone sent it has the phone's version.
function fakeServer(KH, { account = ACCOUNT } = {}) {
  const RV = KH.rowVersions;
  const rows = new Map(); // `${kind}:${cid}` → row
  const log = []; // { id, kind, cid, deleted }
  const receipts = new Map(); // `${list}:${cid}` → `${kind}:${cid}` of the row it made or found
  let seq = 0;
  let purgedThrough = 0;
  const calls = [];
  const key = (kind, cid) => `${kind}:${cid}`;
  const touch = (kind, cid, deleted = false) => { seq += 1; log.push({ id: seq, kind, cid, deleted }); };
  const version = (kind, row) => RV.version(kind, row);
  function put(kind, row, { quiet = false } = {}) {
    const cid = row.client_id || uuid();
    rows.set(key(kind, cid), { ...row, client_id: cid });
    if (!quiet) touch(kind, cid);
    return rows.get(key(kind, cid));
  }
  function remove(kind, cid) { rows.delete(key(kind, cid)); touch(kind, cid, true); }
  const get = (kind, cid) => rows.get(key(kind, cid)) || null;
  function feed(after, limit) {
    if (after > 0 && after < purgedThrough) return [410, { detail: 'resync', resync: true }];
    const latest = new Map();
    for (const c of log) if (c.id > after) { latest.delete(key(c.kind, c.cid)); latest.set(key(c.kind, c.cid), c); }
    const all = [...latest.values()].sort((a, b) => a.id - b.id);
    const page = all.slice(0, limit);
    const foods = [];
    const changes = page.map((c) => {
      const row = get(c.kind, c.cid);
      if (c.deleted || !row) return { kind: c.kind, id: c.cid, op: 'delete', version: null };
      if (c.kind === 'entry' && row.food && row.food.client_id) {
        const f = get('food', row.food.client_id);
        if (f && !foods.some((x) => x.ref.client_id === f.client_id)) foods.push({ ref: { client_id: f.client_id }, food: f });
      }
      return { kind: c.kind, id: c.cid, op: 'put', version: version(c.kind, row), row };
    });
    const next = page.length ? page[page.length - 1].id : after;
    return [200, { changes, foods, next: String(next), more: all.length > limit }];
  }
  // The edit as the kind's PUT route applies it (only the fields the tests use).
  function edit(kind, row, fields) {
    const out = { ...row, ...fields };
    if (kind === 'entry') {
      const factor = Number(out.servings) / Number(row.servings);
      if (fields.grams != null) out.servings = Math.round((Number(fields.grams) / (Number(row.grams) / Number(row.servings))) * 1000) / 1000;
      out.nutrients = Object.fromEntries(Object.entries(row.nutrients).map(([k, v]) => [k, v == null ? null : Math.round(v * (fields.grams != null ? out.servings / row.servings : factor) * 10) / 10]));
      if (fields.purpose === 'none') out.purpose = null;
      if (fields.grams == null && fields.servings != null) out.grams = null;
    }
    return out;
  }
  function changesPost(body) {
    const results = [];
    for (const ch of body.changes) {
      const row = get(ch.kind, ch.id);
      if (!row) { results.push({ kind: ch.kind, id: ch.id, status: 'gone' }); continue; }
      const now = version(ch.kind, row);
      if (ch.op === 'edit' && ch.version === now) { results.push({ kind: ch.kind, id: ch.id, status: 'done', version: now }); continue; }
      if (ch.base !== now) { results.push({ kind: ch.kind, id: ch.id, status: 'conflict', version: now, row }); continue; }
      if (ch.kind === 'lab' && ch.op === 'edit') { results.push({ kind: ch.kind, id: ch.id, status: 'refused', detail: 'Lab results can only be added or deleted.' }); continue; }
      if (ch.op === 'delete') { remove(ch.kind, ch.id); results.push({ kind: ch.kind, id: ch.id, status: 'done', version: null }); continue; }
      const next = put(ch.kind, edit(ch.kind, row, ch.fields));
      results.push({ kind: ch.kind, id: ch.id, status: 'done', version: version(ch.kind, next) });
    }
    return { results };
  }
  // POST /push/v1/sync, as app/app_sync.py: receipts by client_id; the row as the server keeps it is `asKept(kind, body)`.
  const LISTS = { foods: 'food', entries: 'entry', labs: 'lab', symptoms: 'symptom', weights: 'weight', readings: 'reading' };
  let asKept = null;
  function sync(body) {
    const added = { foods: 0, entries: 0, labs: 0, symptoms: 0, weights: 0, readings: 0 };
    const there = { ...added };
    for (const [list, items] of Object.entries(body)) {
      for (const item of items) {
        if (receipts.has(`${list}:${item.client_id}`)) { there[list] += 1; continue; }
        const kind = LISTS[list];
        if (kind === 'food' && item.source !== 'custom') { receipts.set(`${list}:${item.client_id}`, null); added[list] += 1; continue; } // a shared food
        put(kind, asKept(kind, item));
        receipts.set(`${list}:${item.client_id}`, key(kind, item.client_id));
        added[list] += 1;
      }
    }
    return { added, already_there: there, skipped: { food_not_found: 0, day_full: 0 } };
  }
  const aliases = new Map(); // a phone ID step 4 sent that matched a row already here → that row's ID
  function match(body) {
    const known = {}; const unknown = {};
    for (const [kind, ids] of Object.entries(body.ids)) {
      known[kind] = {}; unknown[kind] = [];
      for (const id of ids) {
        if (get(kind, id)) known[kind][id] = id;
        else if (aliases.has(key(kind, id))) known[kind][id] = aliases.get(key(kind, id));
        else unknown[kind].push(id);
      }
    }
    return { known, unknown };
  }
  const state = { account, aboutStatus: 200, script: [] };
  function handle(req) {
    calls.push(req.kind === 'serverApi' ? `${req.method} ${req.path.split('?')[0]}` : req.kind);
    if (req.kind === 'serverInfo') return { ok: true, paired: true, server: 'food.example.org' };
    const scripted = state.script.findIndex((s) => s.when(req));
    if (scripted >= 0) { const s = state.script.splice(scripted, 1)[0]; return s.answer; }
    const answer = (status, json, extra = {}) => ({ ok: true, status, json: JSON.stringify(json), ...extra });
    if (req.kind === 'serverSyncCheck') return answer(200, { ok: true });
    if (req.kind === 'serverSync') return answer(200, sync(JSON.parse(req.body)));
    if (req.kind !== 'serverApi') return { error: 'bad_request' };
    const [path, query] = req.path.split('?');
    if (req.method === 'GET' && path === '/push/v1/about') {
      return state.aboutStatus === 200 ? answer(200, { account: state.account, api_version: 1, sync: { gateway: true, changes: true }, features: { changes: true } })
        : answer(state.aboutStatus, { detail: 'Not authenticated' });
    }
    if (req.method === 'GET' && path === '/push/v1/changes') {
      const q = new URLSearchParams(query || '');
      const [status, json] = feed(Number(q.get('after') || 0), Number(q.get('limit') || 500));
      return answer(status, json);
    }
    if (req.method === 'POST' && path === '/push/v1/changes') return answer(200, changesPost(JSON.parse(req.body)));
    if (req.method === 'POST' && path === '/push/v1/match') return answer(200, match(JSON.parse(req.body)));
    return answer(404, { detail: 'Not Found' });
  }
  return {
    rows, log, calls, state, aliases, put, remove, get, edit, version, handle, touch,
    setKept(fn) { asKept = fn; },
    purge() { purgedThrough = seq + 1; for (let i = log.length - 1; i >= 0; i -= 1) if (log[i].deleted) log.splice(i, 1); },
    list(kind) { return [...rows.entries()].filter(([k]) => k.startsWith(`${kind}:`)).map(([, v]) => v); },
  };
}

// ---------------------------------------------------------------------------------------------------------------- the page
async function page({ db = createFakeIndexedDB(), bridge } = {}) {
  const KH = loadDemo({ navigator: { userAgent: 'node', onLine: true, storage: {} }, globals: { KDL_PREVIEW: true, KDL_DEVICE: true } });
  KH.mock.instance = new KH.mock.MockApi({ foodsData: JSON.parse(FOODS), seed: false });
  KH.mock.local._useIndexedDB(db.page(new KH.constructor.constructor(`return ${CLONE_SRC}`)()));
  await KH.mock.local.boot();
  const global = new KH.constructor.constructor('return globalThis')();
  global.webkit = { messageHandlers: { bridge: { postMessage: async (req) => bridge(plain(req)) } } };
  return { KH, api: KH.mock.instance, S: KH.mock.serverSync, C: KH.mock.serverChanges, A: KH.mock.serverApi, db };
}
// One full run, as Sync now: the account check, step 4's new rows, then the two-way part.
async function syncNow(p) { p.A.forget(); await p.S.sendNow(); return p.C.status(); }

// The export row of a phone row, as the server keeps what step 4 sent (the fake's stand-in for app/app_sync.py).
function keeper(p) {
  return (kind, item) => {
    const { api } = p;
    const q = api._serverSync.rows;
    const local = kind === 'entry' ? api._entries.find((e) => e.client_id === item.client_id)
      : (kind === 'food' ? api._foods : kind === 'lab' ? api._labs : kind === 'symptom' ? api._symptoms : kind === 'weight' ? api._weights : api._readings)
        .find((r) => q[kind][r.id] && q[kind][r.id].c === item.client_id);
    if (kind === 'entry') { const v = api._entryView(local); delete v.version; delete v.added_by; return { ...v, client_id: item.client_id, food: item.food }; }
    if (kind === 'food') return { ...api._foodView(local), client_id: item.client_id };
    const out = { ...local, client_id: item.client_id };
    delete out.id; delete out.user_id;
    if (kind === 'lab') out.unit = local.entered_unit;
    return out;
  };
}
const builtin = (api, name = 'Banana, raw') => api._foods.find((f) => f.source === 'builtin' && f.name === name) || api._foods.find((f) => f.source === 'builtin' && f.fdc_id != null);
const NUT = (o = {}) => ({ calories_kcal: null, protein_g: null, fat_g: null, sat_fat_g: null, carbs_g: null, fiber_g: null, sugar_g: null, sodium_mg: null,
  potassium_mg: null, phosphorus_mg: null, calcium_mg: null, fluid_ml: null, ...o });
function webEntry(api, extra = {}) {
  const b = builtin(api);
  return { date: D, meal: 'lunch', food_name: b.name, servings: 1, grams: null, note: null, status: 'eaten', nutrients: NUT({ potassium_mg: 422 }), purpose: null,
    created_at: '2026-11-01T08:00:00.000000Z', updated_at: '2026-11-01T08:00:00.000000Z', food: { builtin: { fdc_id: b.fdc_id, name: b.name } }, ...extra };
}
const entryBy = (api, cid) => api._entries.find((e) => e.client_id === cid) || null;

async function fakeRuns() {
  // 1. Receive into an empty phone: every kind, the foods an entry uses, saved meals left for step 8; the cursor is saved.
  {
    let server;
    const p = await page({ bridge: (req) => server.handle(req) });
    server = fakeServer(p.KH);
    server.setKept(keeper(p));
    const own = server.put('food', { name: 'Pudding', brand: null, category: null, source: 'custom', fdc_id: null, serving_desc: '1 bowl', serving_g: 150,
      nutrients: NUT({ potassium_mg: 180, fluid_ml: 0 }), flags: [], kidney_notes: null, hidden: false, gtin: null, source_url: null, source_license: null,
      quality: [], additives: [], ingredients_text: null });
    const e1 = server.put('entry', webEntry(p.api));
    const e2 = server.put('entry', webEntry(p.api, { food_name: 'Pudding', nutrients: NUT({ potassium_mg: 180, fluid_ml: 0 }), food: { client_id: own.client_id }, meal: 'dinner' }));
    const hypo = server.put('entry', webEntry(p.api, { meal: 'snack', purpose: 'hypo', food_name: 'Glucose tablets' }));
    server.put('lab', { analyte: 'potassium', value: 5.1, unit: 'mmol/L', entered_value: 5.1, entered_unit: 'mmol/L', taken_on: D, note: '', created_at: '2026-11-01T08:00:00Z' });
    server.put('symptom', { date: D, symptom: 'itching', label: '', severity: 2, note: '', created_at: '2026-11-01T08:00:00Z' });
    server.put('weight', { date: D, time: '07:15', kg: 70.2, context: 'morning', note: '', source: 'manual', source_key: null, created_at: 'x', updated_at: 'x' });
    server.put('reading', { date: D, time: '07:20', systolic: 122, diastolic: 78, pulse: null, context: 'morning', note: '', source: 'manual', source_key: null });
    server.touch('meal', uuid()); // a saved meal: left for step 8
    const s = await syncNow(p);
    const { api } = p;
    ok(() => assert.equal(s.active, true, 'both ways'), 'active');
    ok(() => assert.equal(api._entries.length, 3, 'three entries'), 'entries');
    ok(() => assert.equal(entryBy(api, e2.client_id).food_id, api._foods.find((f) => f.name === 'Pudding').id), 'the entry names the food from `foods`');
    ok(() => assert.equal(entryBy(api, e1.client_id).food_id, builtin(api).id), 'a built-in food by fdc_id');
    ok(() => assert.equal(entryBy(api, hypo.client_id).purpose, 'hypo'), 'a low treatment comes through like any entry');
    ok(() => assert.equal(api._labs.length + api._symptoms.length + api._weights.length + api._readings.length, 4), 'one of each other kind');
    for (const [kind, map] of Object.entries(api._serverChanges.rows)) {
      for (const [cid, rs] of Object.entries(map)) {
        ok(() => assert.equal(rs.b, server.version(kind, server.get(kind, cid)), `${kind} ${cid}`), 'the agreed version is the server\'s');
        ok(() => assert.equal(rs.l, undefined, `${kind}: the phone works out the same version`), 'same version');
      }
    }
    ok(() => assert.equal(api._serverChanges.cursor, String(server.log[server.log.length - 1].id)), 'the cursor is saved (the saved meal was read and skipped)');
    ok(() => assert.equal(api._serverChanges.first, true), 'the first sync is done');
    ok(() => assert.equal(s.review, 0), 'nothing to review');
    ok(() => assert.ok(!server.calls.includes('serverSync'), 'nothing new to send from the phone'), 'no step 4 request');
    ok(() => assert.ok(!server.calls.includes('POST /push/v1/match'), 'an empty phone has no IDs to match'), 'no match');
    ok(() => assert.equal(api._serverSync.rows.entry[entryBy(api, e1.client_id).id].s, 'sent'), 'a row from the server is never sent back as new');
    // a second run reads from the cursor and changes nothing
    server.calls.length = 0;
    const rev = (await p.KH.mock.local.status()).savedAt;
    await syncNow(p);
    ok(() => assert.ok(!server.calls.includes('POST /push/v1/match') && !server.calls.includes('POST /push/v1/changes'), 'no match and nothing to send'), 'quiet');
    ok(() => assert.ok(server.calls.includes('GET /push/v1/changes'), 'the feed is read'), 'feed');
    ok(() => assert.equal(api._entries.length, 3), 'nothing twice');
    void rev;

    // 2. The web app's edits and deletes reach the phone.
    server.put('entry', { ...server.get('entry', e1.client_id), servings: 2, nutrients: NUT({ potassium_mg: 844 }) });
    const sym = server.list('symptom')[0];
    server.remove('symptom', sym.client_id);
    await syncNow(p);
    ok(() => assert.equal(entryBy(api, e1.client_id).servings, 2, 'the web edit'), 'web edit');
    ok(() => assert.equal(api._symptoms.length, 0, 'the web delete'), 'web delete');
    ok(() => assert.equal(api._serverChanges.rows.symptom[sym.client_id], undefined, 'forgotten'), 'forgotten');

    // 3. The phone's edits and deletes reach the server, with the version they were made on.
    const row = entryBy(api, e1.client_id);
    const base = api._serverChanges.rows.entry[e1.client_id].b;
    await api.request('PUT', `/api/log/${row.id}`, { servings: 3, note: 'big bowl' });
    const w = api._weights[0];
    await api.request('PUT', `/api/body/weights/${w.id}`, { date: w.date, time: w.time, kg: 70.6, context: 'morning', note: '' });
    const waitingNow = p.C._waiting(api);
    ok(() => assert.deepEqual(plain(waitingNow.map((c) => [c.kind, c.op]).sort()), [['entry', 'edit'], ['weight', 'edit']]), 'two edits wait');
    const entryChange = waitingNow.find((c) => c.kind === 'entry');
    ok(() => assert.equal(entryChange.base, base, 'base: the version it was made on'), 'base');
    ok(() => assert.deepEqual(plain(entryChange.fields), { date: D, meal: 'lunch', status: 'eaten', note: 'big bowl', purpose: 'none', servings: 3 }), 'LogUpdate fields');
    ok(() => assert.equal(entryChange.version, p.C._versionOf(api, 'entry', row)), 'and the phone\'s version after it');
    ok(() => assert.equal(p.C.status().waiting, 2), 'Settings counts them');
    await syncNow(p);
    ok(() => assert.equal(server.get('entry', e1.client_id).servings, 3, 'the server has the phone\'s edit'), 'sent');
    ok(() => assert.equal(server.get('weight', w ? server.list('weight')[0].client_id : '').kg, 70.6), 'the weight too');
    ok(() => assert.equal(p.C._waiting(api).length, 0, 'nothing waits'), 'nothing waits');
    ok(() => assert.equal(p.C.status().review, 0), 'no conflict');

    // 4. Both changed the same entry: a conflict card; nothing is overwritten; "Use mine" sends again on the server's version.
    server.put('entry', { ...server.get('entry', e1.client_id), note: 'from the web' });
    await api.request('PUT', `/api/log/${row.id}`, { servings: 4 });
    let st = await syncNow(p);
    ok(() => assert.equal(st.review, 1, 'one to review'), 'conflict');
    ok(() => assert.equal(st.items[0].type, 'conflict'), 'a conflict');
    ok(() => assert.equal(server.get('entry', e1.client_id).servings, 3, 'the server kept its copy'), 'not overwritten');
    ok(() => assert.equal(entryBy(api, e1.client_id).servings, 4, 'the phone kept the person\'s change'), 'kept mine');
    ok(() => assert.deepEqual(plain(st.items[0].server.find((l) => l[0] === 'Note')), ['Note', 'from the web']), 'the server\'s side');
    ok(() => assert.deepEqual(plain(st.items[0].mine.find((l) => l[0] === 'Amount')), ['Amount', '4 servings']), 'the phone\'s side');
    server.calls.length = 0;
    await syncNow(p);
    ok(() => assert.ok(!server.calls.includes('POST /push/v1/changes'), 'a row under review is not sent'), 'held');
    await p.C.decide(st.items[0].key, 'mine');
    st = await syncNow(p);
    ok(() => assert.equal(server.get('entry', e1.client_id).servings, 4, '"Use mine" sent it on the server\'s version'), 'use mine');
    ok(() => assert.equal(st.review, 0), 'settled');
    // and "Keep the saved one"
    server.put('entry', { ...server.get('entry', e1.client_id), note: 'web again' });
    await api.request('PUT', `/api/log/${row.id}`, { servings: 5 });
    st = await syncNow(p);
    await p.C.decide(st.items[0].key, 'server');
    st = await syncNow(p);
    ok(() => assert.equal(entryBy(api, e1.client_id).note, 'web again', '"Keep the saved one" shows the server\'s'), 'keep saved');
    ok(() => assert.equal(entryBy(api, e1.client_id).servings, 4), 'the phone\'s change is dropped');
    ok(() => assert.equal(server.get('entry', e1.client_id).note, 'web again'), 'the server is unchanged');
    ok(() => assert.equal(p.C._waiting(api).length, 0), 'nothing waits');

    // 5. A delete on the phone reaches the server; a delete of a row changed on the web is a conflict ("Delete <name>").
    const lab = api._labs[0];
    await api.request('DELETE', `/api/labs/${lab.id}`);
    await api.request('DELETE', `/api/log/${entryBy(api, hypo.client_id).id}`);
    server.put('entry', { ...server.get('entry', hypo.client_id), note: 'web' });
    st = await syncNow(p);
    ok(() => assert.equal(server.list('lab').length, 0, 'the lab result is deleted on the server'), 'delete sent');
    ok(() => assert.ok(server.get('entry', hypo.client_id), 'the changed entry is not deleted'), 'not deleted');
    ok(() => assert.deepEqual([st.items[0].type, st.items[0].op], ['conflict', 'delete']), 'a delete conflict');
    await p.C.decide(st.items[0].key, 'mine');
    await syncNow(p);
    ok(() => assert.equal(server.get('entry', hypo.client_id), null, '"Use mine" deletes it'), 'delete mine');

    // 6. An edit of a row deleted elsewhere is dropped and the person is told.
    await api.request('PUT', `/api/log/${entryBy(api, e2.client_id).id}`, { servings: 2 });
    server.remove('entry', e2.client_id);
    st = await syncNow(p);
    ok(() => assert.equal(entryBy(api, e2.client_id), null, 'gone from the phone'), 'gone');
    ok(() => assert.match(st.notices[0], /^This entry no longer exists, so your change was dropped: Pudding\.$/), 'the notice');
    await p.C.clearNotices();
    ok(() => assert.equal(p.C.status().notices.length, 0), 'cleared');

    // 7. A change the server refuses stays on the phone, is listed, and is not sent again until it changes.
    const rd = api._readings[0];
    await api.request('PUT', `/api/body/blood-pressure/${rd.id}`, { date: rd.date, time: rd.time, systolic: 130, diastolic: 80, context: 'morning', note: '' });
    server.state.script.push({ when: (r) => r.path === '/push/v1/changes' && r.method === 'POST',
      answer: { ok: true, status: 200, json: JSON.stringify({ results: [{ kind: 'reading', id: server.list('reading')[0].client_id, status: 'refused', detail: 'fields.date: not valid' }] }) } });
    st = await syncNow(p);
    ok(() => assert.equal(st.refused.length, 1, 'listed'), 'refused');
    ok(() => assert.match(st.refused[0].why, /not valid/), 'with why');
    server.calls.length = 0;
    await syncNow(p);
    ok(() => assert.ok(!server.calls.includes('POST /push/v1/changes'), 'not sent again'), 'not again');

    // 8. 410: a cursor older than the tombstones kept: everything is read again, and rows the server no longer has go.
    const wcid = server.list('weight')[0].client_id;
    server.remove('weight', wcid);
    server.put('symptom', { date: D, symptom: 'cramps', label: '', severity: 1, note: '', created_at: 'x' });
    server.purge();
    st = await syncNow(p);
    ok(() => assert.equal(api._weights.length, 0, 'the weight deleted on the server is gone after the full resync'), '410 resync');
    ok(() => assert.equal(api._symptoms.length, 1, 'and the new symptom arrived'), 'resync adds');
    ok(() => assert.equal(api._serverChanges.full, false), 'the resync finished');
    ok(() => assert.notEqual(api._serverChanges.cursor, '0'), 'with a new cursor');

    // 9. Both ways, a planned entry for a later day is sent at once.
    const planned = await api.request('POST', '/api/log', { date: day(3), meal: 'dinner', food_id: builtin(api).id, servings: 1, status: 'planned' });
    await syncNow(p);
    const pcid = api._entry(planned.id).client_id;
    ok(() => assert.ok(server.get('entry', pcid), 'the planned entry reached the server'), 'planned at once');
    ok(() => assert.equal(api._serverChanges.rows.entry[pcid].b, server.version('entry', server.get('entry', pcid))), 'and agreed');

    // 10. Offline and 429: nothing is lost, the run stops and says so.
    server.state.script.push({ when: (r) => r.path.startsWith('/push/v1/changes'), answer: { error: 'offline' } });
    await api.request('PUT', `/api/log/${row.id}`, { servings: 6 });
    st = await syncNow(p);
    ok(() => assert.equal(st.outcome, 'offline'), 'offline');
    ok(() => assert.equal(p.C._waiting(api).length, 1, 'the edit still waits'), 'kept');
    server.state.script.push({ when: (r) => r.path.startsWith('/push/v1/changes'), answer: { ok: true, status: 429, json: '{"detail":"Too many"}', retryAfter: 120 } });
    st = await syncNow(p);
    ok(() => assert.equal(st.outcome, 'wait'), '429');
    ok(() => assert.ok(Date.parse(api._serverChanges.waitUntil) > Date.now() + 100000), 'waits as asked');
    await p.C.afterSend({ force: true });
    ok(() => assert.equal(server.get('entry', e1.client_id).servings, 6, 'Sync now goes at once'), 'force');

    // 11. A restart keeps the cursor, the agreed versions and the review.
    const again = await page({ db: p.db, bridge: (req) => server.handle(req) });
    ok(() => assert.equal(again.api._serverChanges.cursor, api._serverChanges.cursor), 'the cursor survives a restart');
    ok(() => assert.deepEqual(plain(again.api._serverChanges.rows), plain(api._serverChanges.rows)), 'the versions too');
  }

  // 12. The first two-way sync of a phone that already has data (step 4 sent it with a token that only adds), §8.7.
  {
    let server;
    const p = await page({ bridge: (req) => server.handle(req) });
    server = fakeServer(p.KH);
    server.setKept(keeper(p));
    server.state.aboutStatus = 401; // a token that only adds
    const { api } = p;
    const b = builtin(api);
    const mk = (servings) => api.request('POST', '/api/log', { date: D, meal: 'lunch', food_id: b.id, servings });
    const [a, bb, c, dd] = [await mk(1), await mk(2), await mk(3), await mk(4)];
    const sym = await api.request('POST', '/api/symptoms', { date: D, symptom: 'itching', severity: 2 });
    const sym2 = await api.request('POST', '/api/symptoms', { date: D, symptom: 'cramps', severity: 1 });
    await syncNow(p);
    ok(() => assert.equal(server.list('entry').length, 4, 'step 4 sent the rows'), 'one way first');
    ok(() => assert.equal(api._serverChanges, undefined), 'no two-way state with a token that only adds');
    const [ca, cb, cc, cd] = [a, bb, c, dd].map((x) => api._entry(x.id).client_id);
    // then, on both sides:
    await api.request('PUT', `/api/log/${a.id}`, { servings: 1.5 }); // only the phone
    server.put('entry', server.edit('entry', server.get('entry', cb), { servings: 2.5 })); // only the server
    await api.request('PUT', `/api/log/${c.id}`, { servings: 3.5 }); // both
    server.put('entry', server.edit('entry', server.get('entry', cc), { servings: 3.25 }));
    await api.request('DELETE', `/api/symptoms/${sym.id}`); // deleted on the phone after it was sent
    const symCid = server.list('symptom').find((r) => r.symptom === 'itching').client_id;
    server.remove('entry', cd); // deleted on the server, unchanged on the phone
    // a row step 4 sent that matched one already on the server: the server knows it by another ID
    const sym2cid = api._serverSync.rows.symptom[sym2.id].c;
    const other = uuid();
    const kept = server.get('symptom', sym2cid);
    server.rows.delete(`symptom:${sym2cid}`);
    server.put('symptom', { ...kept, client_id: other });
    server.aliases.set(`symptom:${sym2cid}`, other);
    server.state.aboutStatus = 200; // the new token, both ways
    const st = await syncNow(p);
    ok(() => assert.equal(server.get('entry', ca).servings, 1.5, 'only the phone changed it: the phone\'s edit is sent'), 'phone wins');
    ok(() => assert.equal(api._entries.find((e) => e.id === bb.id).servings, 2.5, 'only the server changed it: the phone takes it'), 'server wins');
    ok(() => assert.equal(api._entries.find((e) => e.id === dd.id), undefined, 'deleted on the server, unchanged here: deleted here'), 'delete follows');
    ok(() => assert.equal(api._serverSync.rows.symptom[sym2.id].c, other, 'match renamed the phone\'s copy'), 'renamed');
    ok(() => assert.equal(api._symptoms.filter((r) => r.symptom === 'cramps').length, 1, 'one row each'), 'one row');
    const types = st.items.map((x) => x.type).sort();
    ok(() => assert.deepEqual(plain(types), ['deleted_here', 'differ']), 'the review: both changed, and deleted on this iPhone');
    const differ = st.items.find((x) => x.type === 'differ');
    ok(() => assert.equal(api._entries.find((e) => e.id === c.id).servings, 3.25, 'until the person chooses, the server\'s copy is shown'), 'server shown');
    ok(() => assert.deepEqual(plain(differ.mine.find((l) => l[0] === 'Amount')), ['Amount', '3.5 servings']), 'and the phone\'s is kept');
    ok(() => assert.equal(api._symptoms.filter((r) => r.symptom === 'itching').length, 1, 'the deleted row is shown again until the person chooses'), 'shown');
    await p.C.decide(differ.key, 'mine'); // Keep this iPhone's
    await p.C.decide(st.items.find((x) => x.type === 'deleted_here').key, 'mine'); // Delete it there
    const after = await syncNow(p);
    ok(() => assert.equal(server.get('entry', cc).servings, 3.5, '"Keep this iPhone\'s" is sent'), 'keep iphone');
    ok(() => assert.equal(server.get('symptom', symCid), null, '"Delete it there" deletes it on the server'), 'delete there');
    ok(() => assert.equal(after.review, 0), 'the review is done');
  }

  // 13. A different account: nothing is sent until the person chooses; then each choice.
  for (const choice of ['cancel', 'send', 'replace']) {
    let server;
    const p = await page({ bridge: (req) => server.handle(req) });
    server = fakeServer(p.KH);
    server.setKept(keeper(p));
    const { api } = p;
    await api.request('POST', '/api/log', { date: D, meal: 'lunch', food_id: builtin(api).id, servings: 1 });
    await syncNow(p);
    ok(() => assert.equal(api._serverChanges.account, ACCOUNT), 'the account is kept with the cursor');
    const theirs = server.put('entry', webEntry(api, { meal: 'dinner' }));
    server.state.account = 'b'.repeat(32);
    await api.request('POST', '/api/log', { date: D, meal: 'snack', food_id: builtin(api).id, servings: 1 });
    server.calls.length = 0;
    let st = await syncNow(p);
    ok(() => assert.ok(st.ask && st.ask.host === 'food.example.org', 'asks'), `${choice}: asks`);
    ok(() => assert.ok(!server.calls.some((c) => c === 'serverSync' || c.startsWith('POST') || c.startsWith('GET /push/v1/changes')), 'nothing is sent or read'), 'nothing moves');
    p.S._assignIds(api);
    ok(() => assert.equal(p.S._nextBatch(api).refs.length, 1, 'the new entry waits'), 'waits');
    await p.C.choose(choice);
    st = await syncNow(p);
    if (choice === 'cancel') {
      ok(() => assert.ok(st.ask && st.ask.cancelled, 'still stopped'), 'cancel');
      ok(() => assert.equal(server.list('entry').length, 2, 'nothing sent'), 'cancel sends nothing');
    } else if (choice === 'send') {
      ok(() => assert.equal(st.ask, null), 'answered');
      ok(() => assert.equal(server.list('entry').length, 3, 'the new entry is sent there'), 'send');
      ok(() => assert.equal(api._entries.length, 3, 'and the server\'s entry came to the phone'), 'send receives');
      ok(() => assert.equal(api._serverChanges.account, 'b'.repeat(32)), 'the new account is kept');
    } else {
      ok(() => assert.equal(api._entries.length, 2, 'the phone holds the server\'s data only'), 'replace');
      ok(() => assert.ok(entryBy(api, theirs.client_id), 'the server\'s entry'), 'replace receives');
      ok(() => assert.equal(server.list('entry').length, 2, 'the phone\'s unsent entry was not sent'), 'replace sends nothing');
    }
  }
}

// ---------------------------------------------------------------------------------------------------------------- the real server
// Each line "@@ {json}" asks the pytest driver: { bridge: request } → the app's answer; { web: { method, path, json } } → the web app.
function relay() {
  const rl = createInterface({ input: process.stdin });
  const waiting = [];
  rl.on('line', (line) => { const next = waiting.shift(); if (next) next(JSON.parse(line)); });
  return (msg) => new Promise((resolve) => { waiting.push(resolve); process.stdout.write(`@@ ${JSON.stringify(msg)}\n`); });
}
async function realRuns() {
  const ask = relay();
  const web = async (method, path, json) => (await ask({ web: { method, path, json } }));
  const p = await page({ bridge: (req) => ask({ bridge: req }) });
  const { api, C } = p;
  const RV = p.KH.rowVersions;
  // R1. What the web app holds reaches the phone, and the phone works out the server's version for every row.
  const banana = (await web('GET', '/api/foods?q=banana')).json;
  const foodId = (Array.isArray(banana) ? banana : banana.foods)[0].id;
  const own = (await web('POST', '/api/foods', { name: 'Pudding', serving_desc: '1 bowl', serving_g: 150, nutrients: { potassium_mg: 180 } })).json;
  const e1 = (await web('POST', '/api/log', { date: D, meal: 'lunch', food_id: foodId, servings: 1 })).json;
  const e2 = (await web('POST', '/api/log', { date: D, meal: 'dinner', food_id: own.id, grams: 50 })).json;
  await web('POST', '/api/log', { date: D, meal: 'snack', food_id: foodId, servings: 1, purpose: 'hypo' });
  await web('POST', '/api/labs', { analyte: 'potassium', value: 5.1, unit: 'mmol/L', taken_on: D });
  await web('POST', '/api/symptoms', { date: D, symptom: 'itching', severity: 2 });
  await web('POST', '/api/body/weights', { date: D, time: '07:15', kg: 70.2, context: 'morning' });
  await web('POST', '/api/body/blood-pressure', { date: D, time: '07:20', systolic: 122, diastolic: 78, context: 'morning' });
  let st = await syncNow(p);
  ok(() => assert.equal(st.active, true, JSON.stringify(st)), 'R1 both ways');
  ok(() => assert.equal(api._entries.length, 3), 'R1 three entries');
  ok(() => assert.equal(entryBy(api, e2.client_id).food_name, 'Pudding'), 'R1 the own food came with its entry');
  ok(() => assert.equal(entryBy(api, e2.client_id).grams, 50), 'R1 by weight');
  ok(() => assert.equal(entryBy(api, e1.client_id).version === undefined && api._entryView(entryBy(api, e1.client_id)).version, e1.version), 'R1 the entry version');
  for (const [kind, map] of Object.entries(api._serverChanges.rows)) {
    for (const [cid, rs] of Object.entries(map)) ok(() => assert.equal(rs.l, undefined, `${kind} ${cid} ${JSON.stringify(rs)}`), 'R1 the phone\'s version is the server\'s');
  }
  ok(() => assert.equal(Object.keys(api._serverChanges.rows.food).length, 1), 'R1 the own food');
  ok(() => assert.equal(st.review, 0), 'R1 nothing to review');

  // R2. What the phone adds goes up (step 4) and comes back agreed, with no review.
  const b = builtin(api);
  await api.request('POST', '/api/log', { date: D, meal: 'breakfast', food_id: b.id, servings: 2 });
  await api.request('POST', '/api/log', { date: day(2), meal: 'dinner', food_id: b.id, servings: 1, status: 'planned' });
  await api.request('POST', '/api/symptoms', { date: D, symptom: 'cramps', severity: 1, note: 'night' });
  await api.request('POST', '/api/body/weights', { date: D, time: '19:00', kg: 70.9, context: 'other' });
  st = await syncNow(p);
  ok(() => assert.equal(st.review, 0, JSON.stringify(st.items)), 'R2 no review');
  const dayOf = async (d) => (await web('GET', `/api/log?date=${d}`)).json.entries;
  const webEntries = [...(await dayOf(D)), ...(await dayOf(day(2)))];
  ok(() => assert.equal(webEntries.length, 5, JSON.stringify(webEntries.map((e) => e.date))), 'R2 the server has the phone\'s entries, the planned one too');
  ok(() => assert.equal(C._waiting(api).length, 0), 'R2 nothing waits');

  // R3. The phone's edits and deletes reach the server through POST /push/v1/changes.
  const mine = entryBy(api, e1.client_id);
  await api.request('PUT', `/api/log/${mine.id}`, { servings: 2, note: 'second helping' });
  const w = api._weights.find((x) => x.time === '07:15');
  await api.request('PUT', `/api/body/weights/${w.id}`, { date: w.date, time: w.time, kg: 70.4, context: 'morning', note: '' });
  const s0 = api._symptoms.find((x) => x.symptom === 'itching');
  await api.request('DELETE', `/api/symptoms/${s0.id}`);
  st = await syncNow(p);
  const e1now = (await web('GET', `/api/log?date=${D}`)).json;
  const e1row = (Array.isArray(e1now) ? e1now : e1now.entries).find((e) => e.id === e1.id);
  ok(() => assert.deepEqual([e1row.servings, e1row.note], [2, 'second helping']), 'R3 the edit is on the server');
  ok(() => assert.equal(e1row.version, api._entryView(mine).version), 'R3 the same version on both sides');
  const syms = (await web('GET', `/api/symptoms?start=${D}&end=${D}`)).json;
  ok(() => assert.equal((syms.symptoms || syms).filter((x) => x.symptom === 'itching').length, 0), 'R3 the delete is on the server');
  ok(() => assert.equal(C._waiting(api).length, 0, JSON.stringify(C._waiting(api))), 'R3 nothing waits');
  ok(() => assert.equal(st.review, 0), 'R3 no conflict');
  for (const [kind, map] of Object.entries(api._serverChanges.rows)) {
    for (const [cid, rs] of Object.entries(map)) ok(() => assert.equal(rs.l, undefined, `${kind} ${cid}`), 'R3 versions agree after the edits');
  }
  ok(() => assert.equal(RV.version('weight', api._weights.find((x) => x.time === '07:15')), api._serverChanges.rows.weight[Object.keys(api._serverChanges.rows.weight)
    .find((cid) => api._serverSync.rows.weight[w.id].c === cid)].b), 'R3 the weight\'s version');

  // R4. Both changed: a conflict, nothing overwritten; "Use mine" wins on the server's current version.
  await web('PUT', `/api/log/${e1.id}`, { note: 'from the web' });
  await api.request('PUT', `/api/log/${mine.id}`, { servings: 3 });
  st = await syncNow(p);
  ok(() => assert.deepEqual(plain(st.items.map((x) => x.type)), ['conflict']), 'R4 a conflict');
  let server1 = (await web('GET', `/api/log?date=${D}`)).json;
  ok(() => assert.equal((Array.isArray(server1) ? server1 : server1.entries).find((e) => e.id === e1.id).servings, 2), 'R4 not overwritten');
  await C.decide(st.items[0].key, 'mine');
  st = await syncNow(p);
  server1 = (await web('GET', `/api/log?date=${D}`)).json;
  ok(() => assert.equal((Array.isArray(server1) ? server1 : server1.entries).find((e) => e.id === e1.id).servings, 3), 'R4 "Use mine" is on the server');
  ok(() => assert.equal(st.review, 0), 'R4 settled');

  // R5. An edit of an entry deleted on the web is dropped, and said.
  await api.request('PUT', `/api/log/${entryBy(api, e2.client_id).id}`, { grams: 60 });
  await web('DELETE', `/api/log/${e2.id}`);
  st = await syncNow(p);
  ok(() => assert.equal(entryBy(api, e2.client_id), null), 'R5 gone from the phone');
  ok(() => assert.match(st.notices.join(' '), /no longer exists, so your change was dropped/), 'R5 the notice');

  // R6. A different account on the same server asks before anything moves.
  await ask({ token: 'second' });
  await api.request('POST', '/api/log', { date: D, meal: 'snack', food_id: b.id, servings: 1 });
  st = await syncNow(p);
  ok(() => assert.ok(st.ask, 'R6 asks'), 'R6 the question');
  const other = (await ask({ count: 'second' })).entries;
  ok(() => assert.equal(other, 0, 'R6 nothing reached the other account'), 'R6 nothing moved');
  await ask({ done: true });
}

if (RELAY) await realRuns(); else await fakeRuns();
console.log(`server changes${RELAY ? ' (real server)' : ''}: ${checks} checks passed`);
process.exit(0);
