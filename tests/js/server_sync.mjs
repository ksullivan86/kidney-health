#!/usr/bin/env node
// Device mode, step 4 (design note 38 §5.5): the page's queue of rows for the person's server (js/mock/server_sync.js). A stand-in
// for the iPhone app's "bridge" answers like the app would, with a small fake of POST /push/v1/sync (app/app_sync.py: receipts by
// client_id, counts only, a skipped row is not named). Checks the queue, the client IDs, the batches and their limits, the food
// references, that the sample data is never sent, and each answer (200 with skips, 400 naming a row, 401, 413, 429, offline).
// pytest (tests/test_server_sync_phone.py) runs it. Exits 1 with the failed check on any mismatch.
//
//   node tests/js/server_sync.mjs              the checks
//   node tests/js/server_sync.mjs --dump FILE  also writes one request body the page built, for the pytest round trip
import assert from 'node:assert/strict';
import { readFileSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { loadDemo } from './demo_loader.mjs';
import { createFakeIndexedDB } from './fake_idb.mjs';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..', '..');
const FOODS = readFileSync(join(ROOT, 'data', 'foods.json'), 'utf8'); // the server's built-in list, as the packed app embeds it
const CLONE_SRC = `(function clone(v) {
  if (v === null || typeof v !== 'object') return v;
  const tag = Object.prototype.toString.call(v);
  if (tag === '[object Map]') return new Map([...v].map(([k, x]) => [clone(k), clone(x)]));
  if (tag === '[object Set]') return new Set([...v].map(clone));
  if (Array.isArray(v)) return v.map(clone);
  const o = {}; for (const k of Object.keys(v)) o[k] = clone(v[k]); return o;
})`;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const day = (n) => { const d = new Date(); d.setDate(d.getDate() + n); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; };
const D = day(0);
const plain = (v) => JSON.parse(JSON.stringify(v));
let checks = 0;
const ok = (fn, label) => { checks += 1; try { fn(); } catch (e) { e.message = `${label}: ${e.message}`; throw e; } };

// A fake of the server's sync: receipts per list, a built-in food it may not know, a day cap on symptoms, weights and readings.
function fakeServer({ unknownBuiltin = new Set(), dayCap = Infinity } = {}) {
  const receipts = { foods: new Set(), entries: new Set(), labs: new Set(), symptoms: new Set(), weights: new Set(), readings: new Set() };
  const perDay = new Map();
  const bodies = [];
  function handle(text) {
    const body = JSON.parse(text);
    bodies.push(body);
    const added = { foods: 0, entries: 0, labs: 0, symptoms: 0, weights: 0, readings: 0 };
    const there = { ...added };
    const skipped = { food_not_found: 0, day_full: 0 };
    const rowCount = Object.values(body).reduce((a, l) => a + l.length, 0);
    assert.ok(rowCount >= 1 && rowCount <= 200, `rows in one request: ${rowCount}`);
    assert.ok(Buffer.byteLength(text) <= 256 * 1024, 'at most 256 KiB');
    for (const list of Object.keys(body)) {
      assert.ok(list in receipts, `known list ${list}`);
      for (const row of body[list]) {
        assert.match(row.client_id, UUID);
        if (receipts[list].has(row.client_id)) { there[list] += 1; continue; }
        if (list === 'entries') {
          const ref = row.food;
          const known = ref.client_id ? receipts.foods.has(ref.client_id) : !unknownBuiltin.has(ref.builtin.name);
          if (!known) { skipped.food_not_found += 1; continue; }
        }
        if (list === 'symptoms' || list === 'weights' || list === 'readings') {
          const key = `${list}:${row.date}`;
          if ((perDay.get(key) || 0) >= dayCap) { skipped.day_full += 1; continue; }
          perDay.set(key, (perDay.get(key) || 0) + 1);
        }
        receipts[list].add(row.client_id);
        added[list] += 1;
      }
    }
    return { added, already_there: there, skipped };
  }
  return { receipts, bodies, handle };
}

// A page in device mode with an empty log, kept in a fake IndexedDB (`db` to share it across restarts), and a stand-in app.
async function page({ db = createFakeIndexedDB(), server = fakeServer(), paired = true, script = null } = {}) {
  const KH = loadDemo({ navigator: { userAgent: 'node', onLine: true, storage: {} }, globals: { KDL_PREVIEW: true, KDL_DEVICE: true } });
  KH.mock.instance = new KH.mock.MockApi({ foodsData: JSON.parse(FOODS), seed: false });
  const api = KH.mock.instance;
  KH.mock.local._useIndexedDB(db.page(new KH.constructor.constructor(`return ${CLONE_SRC}`)()));
  await KH.mock.local.boot();
  const global = new KH.constructor.constructor('return globalThis')();
  const asked = [];
  global.webkit = { messageHandlers: { bridge: { postMessage: async (req) => {
    asked.push(req.kind);
    if (req.kind === 'serverInfo') return paired ? { ok: true, paired: true, server: 'food.example.org' } : { ok: true, paired: false, server: null };
    if (script && script[req.kind] && script[req.kind].length) {
      const next = script[req.kind].shift();
      return typeof next === 'function' ? next(req) : next;
    }
    if (req.kind === 'serverSyncCheck') return { ok: true, status: 200, json: '{"ok":true}' };
    if (req.kind === 'serverSync') return { ok: true, status: 200, json: JSON.stringify(server.handle(req.body)) };
    return { error: 'bad_request' };
  } } } };
  return { KH, api: KH.mock.instance || api, S: KH.mock.serverSync, db, server, asked };
}
const food = (name, extra = {}) => ({ name, serving_desc: '1 bowl', serving_g: 150, nutrients: { calories_kcal: 210, potassium_mg: 180 }, ...extra });
async function fill(api) {
  const own = await api.request('POST', '/api/foods', food("Grandma's rice pudding"));
  const builtin = api._foods.find((f) => f.source === 'builtin' && f.fdc_id != null);
  await api.request('POST', '/api/log', { date: D, meal: 'lunch', food_id: own.id, servings: 1 });
  await api.request('POST', '/api/log', { date: D, meal: 'lunch', food_id: builtin.id, grams: 118 });
  await api.request('POST', '/api/log', { date: day(3), meal: 'dinner', food_id: builtin.id, servings: 1, status: 'planned' });
  await api.request('POST', '/api/labs', { analyte: 'potassium', value: 5.1, unit: 'mmol/L', taken_on: D });
  await api.request('POST', '/api/symptoms', { date: D, symptom: 'itching', severity: 2 });
  await api.request('POST', '/api/body/weights', { date: D, time: '07:15', kg: 70.2, context: 'morning' });
  await api.request('POST', '/api/body/blood-pressure', { date: D, time: '07:20', systolic: 122, diastolic: 78, context: 'morning' });
  return { own, builtin };
}

// 1. The queue: every row gets a UUID; foods come first; FoodRef forms; the server's field names; a future planned entry waits.
let dumped = null;
{
  const { api, S } = await page();
  const { own, builtin } = await fill(api);
  S._assignIds(api);
  const batch = S._nextBatch(api);
  const L = plain(batch.lists);
  ok(() => assert.deepEqual(Object.keys(L), ['foods', 'entries', 'labs', 'symptoms', 'weights', 'readings']), 'the lists, foods first');
  ok(() => assert.equal(batch.refs.length, 7), 'seven rows (the planned entry for a later day waits)');
  ok(() => assert.ok(batch.refs.every((r) => UUID.test(r.cid))), 'every row has a UUID');
  ok(() => assert.equal(L.foods[0].source, 'custom'), 'the own food is sent as custom');
  ok(() => assert.equal(L.foods[0].name, own.name));
  ok(() => assert.deepEqual(L.entries[0].food, { client_id: L.foods[0].client_id }), 'an own food by its client_id');
  ok(() => assert.deepEqual(L.entries[1].food, { builtin: { fdc_id: builtin.fdc_id, name: builtin.name } }), 'a built-in food by fdc_id and name');
  ok(() => assert.equal(L.entries[1].grams, 118), 'grams when the entry was by weight');
  ok(() => assert.equal(L.entries[0].servings, 1), 'servings otherwise');
  ok(() => assert.equal(L.entries[0].client_id, api._entries[0].client_id), 'an entry keeps its own client_id (the export carries it)');
  ok(() => assert.deepEqual([L.labs[0].value, L.labs[0].unit], [5.1, 'mmol/L']), 'a lab as it was typed');
  ok(() => assert.ok(!('food_id' in L.entries[0]) && !('id' in L.labs[0]) && !('user_id' in L.symptoms[0]), 'no ids of this phone'));
  ok(() => assert.equal(S._foodRef({ source: 'builtin', fdc_id: null, name: 'Glucose tablets' }).builtin.name, 'Glucose tablets'), 'a built-in food with no fdc_id by name');
  ok(() => assert.deepEqual(plain(S._foodRef({ source: 'builtin', fdc_id: null, name: 'Glucose tablets' })), { builtin: { name: 'Glucose tablets' } }));
  // a USDA food the phone found travels in `foods` with its fdc_id, and the entry names it by client_id
  const usda = api._food(api._insertFood({ source: 'usda', fdc_id: 1458203, name: 'Diet Coke', serving_desc: '1 can', serving_g: 355, nutrients: { sodium_mg: 40 },
    source_url: 'https://fdc.nal.usda.gov/', source_license: 'CC0-1.0' }));
  api._foodLinks().add(usda.id); // as an import from USDA links it
  await api.request('POST', '/api/log', { date: D, meal: 'snack', food_id: usda.id, servings: 1 });
  S._assignIds(api);
  const b2 = plain(S._nextBatch(api));
  const sent = b2.lists.foods.find((f) => f.source === 'usda');
  ok(() => assert.equal(sent.fdc_id, 1458203), 'a USDA food with its fdc_id');
  ok(() => assert.deepEqual(b2.lists.entries[2].food, { client_id: sent.client_id }), 'and the entry names it');
  dumped = b2.lists;
}

// 2. Limits: at most 200 rows and 256 KiB in one request.
{
  const { api, S } = await page();
  for (let i = 0; i < 450; i += 1) api._insertLab(1, { analyte: 'potassium', value: 4 + (i % 10) / 10, entered_value: 4, entered_unit: 'mmol/L' }, day(-(i % 300)), '');
  S._assignIds(api);
  const skip = new Set();
  const sizes = [];
  for (let b = S._nextBatch(api, { skip }); b && b.refs.length; b = S._nextBatch(api, { skip })) {
    sizes.push(b.refs.length);
    for (const r of b.refs) skip.add(`${r.kind}:${r.id}`);
  }
  ok(() => assert.deepEqual(sizes, [200, 200, 50]), 'rows are sent 200 at a time');
  const { api: api2, S: S2 } = await page();
  for (let i = 0; i < 120; i += 1) api2._insertFood({ name: `Soup ${i}`, serving_desc: '1 bowl', serving_g: 250, nutrients: {}, ingredients_text: 'water, salt '.repeat(400) });
  S2._assignIds(api2);
  const big = S2._nextBatch(api2);
  ok(() => assert.ok(big.refs.length < 120 && big.refs.length > 10, `split by size (${big.refs.length})`));
  ok(() => assert.ok(Buffer.byteLength(JSON.stringify(big.lists)) <= 256 * 1024, 'within 256 KiB'));
}

// 3. A full run: checks the token, sends everything, marks it sent; a second run sends nothing; an edit after sending is not sent.
{
  const { api, S, server, asked } = await page();
  await fill(api);
  const s0 = S.status();
  ok(() => assert.equal(s0.waiting, 8), 'eight rows wait (the planned entry too)');
  const s = await S.sendNow();
  ok(() => assert.deepEqual(asked.slice(0, 3), ['serverInfo', 'serverSyncCheck', 'serverSync']), 'the token is checked first');
  ok(() => assert.equal(server.bodies.length, 1), 'one request');
  ok(() => assert.equal(server.receipts.entries.size, 2), 'both entries for today');
  ok(() => assert.equal(s.waiting, 1), 'only the planned entry waits');
  ok(() => assert.equal(s.outcome, 'done'));
  ok(() => assert.ok(s.sentAt), 'when it last sent');
  asked.length = 0;
  const edited = await api.request('PUT', `/api/log/${api._entries[0].id}`, { servings: 2 });
  ok(() => assert.equal(edited.servings, 2), 'the entry was changed on the phone');
  await S.run();
  ok(() => assert.equal(server.bodies.length, 1), 'nothing more is sent: an edit after sending is not sent');
  ok(() => assert.ok(!asked.includes('serverSyncCheck') && !asked.includes('serverSync'), 'and nothing is asked'));
  await api.request('POST', '/api/symptoms', { date: D, symptom: 'cramps', severity: 1 });
  await S.run();
  ok(() => assert.equal(server.bodies.length, 2), 'a new row is sent');
  ok(() => assert.deepEqual(Object.keys(server.bodies[1]), ['symptoms']), 'only the new row');
}

// 3b. One run sends at most MAX_REQUESTS requests; the rest waits for the next run.
{
  const { api, S, server } = await page();
  for (let i = 0; i < 2100; i += 1) api._insertLab(1, { analyte: 'potassium', value: 4, entered_value: 4, entered_unit: 'mmol/L' }, day(-(i % 300)), '');
  let s = await S.sendNow();
  ok(() => assert.equal(server.bodies.length, S.MAX_REQUESTS), 'ten requests in one run');
  ok(() => assert.equal(s.waiting, 100), 'the rest waits');
  s = await S.run();
  ok(() => assert.equal(s.waiting, 0), 'and goes with the next run');
}

// 4. The sample data is never sent.
{
  const { api, S, asked } = await page();
  api._sample = true;
  await fill(api);
  const s = await S.sendNow();
  ok(() => assert.equal(s.sample, true));
  ok(() => assert.equal(s.outcome, 'sample'));
  ok(() => assert.ok(!asked.includes('serverSync') && !asked.includes('serverSyncCheck'), 'nothing is sent or checked'));
}

// 5. Not paired: nothing is sent, and the screen says why.
{
  const { api, S, asked } = await page({ paired: false });
  await fill(api);
  const s = await S.sendNow();
  ok(() => assert.equal(s.outcome, 'not_paired'));
  ok(() => assert.deepEqual(plain(asked), ['serverInfo']));
}

// 6. Skipped rows (counts only): the rows that could have been skipped are tried in smaller groups; the one the server cannot place
//    is tried again in later runs and is stuck after MAX_TRIES; the others are sent and do not wait for it.
{
  const builtinName = (KH) => KH.mock.instance._foods.find((f) => f.source === 'builtin' && f.fdc_id != null && f.id > 5).name;
  const probe = await page();
  const unknown = builtinName(probe.KH);
  const server = fakeServer({ unknownBuiltin: new Set([unknown]) });
  const { api, S } = await page({ server });
  const known = api._foods.find((f) => f.source === 'builtin' && f.fdc_id != null && f.name !== unknown);
  const missing = api._foods.find((f) => f.name === unknown);
  for (let i = 0; i < 3; i += 1) await api.request('POST', '/api/log', { date: D, meal: 'lunch', food_id: known.id, servings: 1 });
  await api.request('POST', '/api/log', { date: D, meal: 'lunch', food_id: missing.id, servings: 1 });
  await api.request('POST', '/api/log', { date: D, meal: 'dinner', food_id: known.id, servings: 1 });
  let s = await S.sendNow();
  ok(() => assert.equal(server.receipts.entries.size, 4), 'the four the server knows are sent');
  ok(() => assert.equal(s.waiting, 1), 'one waits');
  ok(() => assert.equal(s.stuck.length, 0));
  s = await S.sendNow();
  s = await S.sendNow();
  ok(() => assert.equal(s.waiting, 0), 'after three tries it no longer waits');
  ok(() => assert.equal(s.stuck.length, 1), 'it is stuck, and the screen says so');
  ok(() => assert.match(s.stuck[0].text, new RegExp(unknown.slice(0, 10).replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))));
  const before = server.bodies.length;
  await S.sendNow();
  ok(() => assert.equal(server.bodies.length, before, 'a stuck row is not sent again'));
}

// 7. A day that is full: the rows of that day are skipped, the rest goes on.
{
  const server = fakeServer({ dayCap: 1 });
  const { api, S } = await page({ server });
  await api.request('POST', '/api/body/weights', { date: D, time: '07:00', kg: 70, context: 'morning' });
  await api.request('POST', '/api/body/weights', { date: D, time: '19:00', kg: 70.5, context: 'other' });
  await api.request('POST', '/api/body/weights', { date: day(-1), time: '07:00', kg: 70.1, context: 'morning' });
  const s = await S.sendNow();
  ok(() => assert.equal(server.receipts.weights.size, 2), 'one weight a day reached the server');
  ok(() => assert.equal(s.waiting, 1), 'the second of today waits');
}

// 8. A 400 naming a row: that row is refused (kept on the phone, never sent again) and the rest is sent.
{
  const server = fakeServer();
  const script = { serverSync: [(req) => {
    const body = JSON.parse(req.body);
    return { ok: true, status: 400, json: JSON.stringify({ detail: 'labs.0.taken_on: must be between the year 2000 and tomorrow', field: 'labs.0.taken_on' }), _rows: body };
  }] };
  const { api, S } = await page({ server, script });
  await fill(api);
  const s = await S.sendNow();
  ok(() => assert.equal(s.refused.length, 1), 'one row refused');
  ok(() => assert.match(s.refused[0].text, /^Lab result/));
  ok(() => assert.match(s.refused[0].why, /taken_on/));
  ok(() => assert.equal(server.receipts.labs.size, 0), 'the refused row was not sent');
  ok(() => assert.equal(server.receipts.entries.size + server.receipts.symptoms.size, 3), 'the rest was sent');
  await S.sendNow();
  ok(() => assert.equal(server.receipts.labs.size, 0), 'and it is never sent again');
}

// 9. 401: stop, keep the queue, say why; no request again within the hour unless the person asks.
{
  const script = { serverSyncCheck: [{ ok: true, status: 401, json: '{"detail":"Not authenticated"}' }] };
  const { api, S, server, asked } = await page({ script });
  await fill(api);
  let s = await S.sendNow();
  ok(() => assert.equal(s.outcome, 'token'));
  ok(() => assert.match(s.message, /For the iPhone app/));
  ok(() => assert.equal(server.bodies.length, 0), 'nothing sent');
  ok(() => assert.equal(s.waiting, 8), 'the queue is kept');
  asked.length = 0;
  await S.run();
  ok(() => assert.ok(!asked.includes('serverSyncCheck'), 'not asked again by itself within the hour'));
  s = await S.sendNow();
  ok(() => assert.equal(s.outcome, 'done'), 'Send now checks again, and sends once the token works');
  ok(() => assert.equal(s.waiting, 1));
}

// 10. 429: wait for Retry-After; 413: send smaller requests; offline: keep the queue.
{
  const script = { serverSync: [{ ok: true, status: 429, json: '{"detail":"Too many requests from this app. Try again later."}', retryAfter: 120 }] };
  const { api, S, server } = await page({ script });
  await fill(api);
  let s = await S.sendNow();
  ok(() => assert.equal(s.outcome, 'wait'));
  ok(() => assert.ok(Date.parse(s.waitUntil) > Date.now() + 100 * 1000, 'waits as long as the server asked'));
  await S.run();
  ok(() => assert.equal(server.bodies.length, 0), 'no request while waiting');
  s = await S.sendNow();
  ok(() => assert.equal(s.waiting, 1), 'Send now does not wait');
}
{
  const script = { serverSync: [{ ok: true, status: 413, json: '{"detail":"Request body too large"}' }] };
  const { api, S, server } = await page({ script });
  await fill(api);
  const s = await S.sendNow();
  ok(() => assert.ok(server.bodies.length >= 2, 'sent in smaller requests'));
  ok(() => assert.ok(server.bodies.every((b) => Object.values(b).reduce((a, l) => a + l.length, 0) <= 3)));
  ok(() => assert.equal(s.waiting, 1));
}
{
  const script = { serverSyncCheck: [{ error: 'offline' }] };
  const { api, S, server } = await page({ script });
  await fill(api);
  const s = await S.sendNow();
  ok(() => assert.equal(s.outcome, 'offline'));
  ok(() => assert.equal(s.waiting, 8));
  ok(() => assert.equal(server.bodies.length, 0));
}

// 11. A restart keeps the client IDs (they are saved before a row leaves the phone) and what was sent.
{
  const db = createFakeIndexedDB();
  const server = fakeServer();
  const first = await page({ db, server, script: { serverSyncCheck: [{ error: 'offline' }] } });
  await fill(first.api);
  await first.S.sendNow(); // offline: IDs made, nothing sent
  const ids = JSON.stringify(first.api._serverSync.rows);
  const second = await page({ db, server });
  ok(() => assert.equal(JSON.stringify(second.api._serverSync.rows), ids), 'the same client IDs after a restart');
  await second.S.sendNow();
  const third = await page({ db, server });
  ok(() => assert.equal(third.S.status().waiting, 1), 'what was sent stays sent');
  const sentIds = new Set(Object.values(server.receipts).flatMap((s) => [...s]));
  const kept = Object.values(third.api._serverSync.rows).flatMap((m) => Object.values(m).map((r) => r.c));
  ok(() => assert.ok([...sentIds].every((c) => kept.includes(c)), 'the server holds the IDs the phone kept'));
  // starting over: a new log, a new queue
  await third.KH.mock.local.restart({ sample: false });
  const fourth = await page({ db, server });
  ok(() => assert.equal(fourth.api._serverSync, undefined, 'starting over resets the queue'));
}

if (process.argv[2] === '--dump' && process.argv[3]) writeFileSync(process.argv[3], `${JSON.stringify(dumped, null, 1)}\n`);
console.log(`server sync: ${checks} checks passed`);
process.exit(0);
