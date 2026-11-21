#!/usr/bin/env node
// Device mode (design note 38, step 1): the app inside the iPhone app runs the demo's in-page API with no server. It starts
// empty, keeps its data from the first start with no question, has one signed-in person who is not an admin, and hands a copy of
// the export to the iPhone app after each save (the safety copy). Run against a fake IndexedDB, like demo_local_storage.mjs;
// pytest (tests/test_device_mode.py) runs it. Exits 1 with the failed check on any mismatch.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { loadDemo } from './demo_loader.mjs';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..', '..');
import { createFakeIndexedDB } from './fake_idb.mjs';

const D = new Date().toISOString().slice(0, 10);
const CLONE_SRC = `(function clone(v) {
  if (v === null || typeof v !== 'object') return v;
  const tag = Object.prototype.toString.call(v);
  if (tag === '[object Map]') return new Map([...v].map(([k, x]) => [clone(k), clone(x)]));
  if (tag === '[object Set]') return new Set([...v].map(clone));
  if (Array.isArray(v)) return v.map(clone);
  const o = {}; for (const k of Object.keys(v)) o[k] = clone(v[k]); return o;
})`;

const profile = createFakeIndexedDB();
let asked = 0;
function loadPage({ device = true } = {}) {
  const storage = { persist: async () => { asked += 1; return true; }, persisted: async () => false };
  const KH = loadDemo({ navigator: { userAgent: 'node', onLine: true, storage } });
  KH.flags.PREVIEW = true;
  KH.flags.DEVICE = device;
  const api = KH.mock.start({ seed: !device }) || KH.mock.instance;
  if (KH.mock.instance !== api) KH.mock.instance = api;
  const clone = new KH.constructor.constructor(`return ${CLONE_SRC}`)();
  KH.mock.local._useIndexedDB(profile.page(clone));
  const copies = [];
  const global = new KH.constructor.constructor('return globalThis')();
  global.webkit = { messageHandlers: { safetyCopy: { postMessage: (text) => copies.push(String(text)) } } };
  return { KH, api, local: KH.mock.local, copies };
}
const quick = (name) => ({ date: D, meal: 'lunch', name, serving_desc: '1 bar', serving_g: 40, servings: 1,
  nutrients: { calories_kcal: 160, protein_g: 3, carbs_g: 24, potassium_mg: 150, phosphorus_mg: 80, sodium_mg: 90 } });
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
let checks = 0;
const ok = (fn, label) => { checks += 1; try { fn(); } catch (e) { e.message = `${label}: ${e.message}`; throw e; } };

// 1. The first start on a phone: an empty account, kept at once, one person, and the browser asked to keep the data.
{
  const { api, local } = loadPage();
  ok(() => assert.equal(api._entries.length, 0), 'no sample days');
  ok(() => assert.equal(api._profile.name, ''), 'no sample person');
  const s = await local.boot();
  ok(() => assert.equal(s.on, true), 'kept from the first start, with no question');
  ok(() => assert.equal(asked, 1), 'the browser is asked to keep the data');
  ok(() => assert.equal(profile.read('kdl-demo-local', 'state', 'current').rev, 1), 'the empty account is stored');
  const status = await api.request('GET', '/api/auth/status');
  const user = status.user || status.me || status;
  ok(() => assert.equal(user.username, 'me'), 'the one person');
  ok(() => assert.equal(user.role, 'user'), 'not an admin: there is no server to run');
  ok(() => assert.equal(api._authState().users.length, 1), 'no sample second account');
  ok(() => assert.equal(api._care().mine.length + api._care().people.length + api._care().notes.length, 0), 'no sample Care team');
  ok(() => assert.deepEqual(Object.keys(api._devices().connections), []), 'no sample connected devices');
  ok(() => assert.equal(api._activity().days.length, 0), 'no sample activity');
  ok(() => assert.equal(api._listsState().connection, null), 'no sample list app');
}

// 2. A write is saved, and the safety copy (the export) goes to the iPhone app after the save.
{
  const { api, local, copies } = loadPage();
  await local.boot();
  ok(() => assert.equal(api._entries.length, 0), 'the stored empty account is read back');
  await api.request('POST', '/api/log/quick', quick('Oat bar'));
  await local.flush();
  for (let i = 0; i < 40 && !copies.length; i += 1) await wait(10);
  ok(() => assert.equal(profile.read('kdl-demo-local', 'state', 'current').rev, 2), 'saved after the write');
  ok(() => assert.equal(copies.length, 1), 'one safety copy after one save');
  const doc = JSON.parse(copies[0]);
  ok(() => assert.equal(doc.format, 'kidney-health-export'), 'the copy is the export');
  ok(() => assert.deepEqual(doc.log_entries.map((e) => e.food_name), ['Oat bar']), 'the copy holds the entry');
}

// 3. The next start reads the log back.
{
  const { api, local } = loadPage();
  const s = await local.boot();
  ok(() => assert.equal(s.on, true), 'still kept');
  ok(() => assert.deepEqual(Array.from(api._entries, (e) => e.food_name), ['Oat bar']), 'the entry survived the restart');
}

// 4. Outside device mode the online demo is unchanged: a fresh browser keeps nothing until the person asks.
{
  const other = createFakeIndexedDB();
  const KH = loadDemo({ navigator: { userAgent: 'node', onLine: true, storage: {} } });
  KH.flags.PREVIEW = true;
  KH.mock.start();
  KH.mock.local._useIndexedDB(other.page(new KH.constructor.constructor(`return ${CLONE_SRC}`)()));
  const s = await KH.mock.local.boot();
  ok(() => assert.equal(s.on, false), 'the demo still asks first');
  ok(() => assert.equal(other.databases.size, 0), 'and stores nothing by itself');
  ok(() => assert.ok(KH.mock.instance._entries.length > 0), 'the demo still has its sample person');
}

// 5. Apple Health rows from the iPhone app (window.KHDevice.addBody, step 3): added through the batch routes, saved before the
//    answer, and a row already in the log is skipped the second time.
{
  const fresh = createFakeIndexedDB();
  const KH = loadDemo({ navigator: { userAgent: 'node', onLine: true, storage: {} }, globals: { KDL_PREVIEW: true, KDL_DEVICE: true } });
  ok(() => assert.equal(KH.flags.DEVICE, true), 'core.js reads the device flag');
  const api = KH.mock.start({ seed: false });
  KH.mock.local._useIndexedDB(fresh.page(new KH.constructor.constructor(`return ${CLONE_SRC}`)()));
  await KH.mock.local.boot();
  const global = new KH.constructor.constructor('return globalThis')();
  ok(() => assert.equal(typeof global.KHDevice.addBody, 'function'), 'the bridge is there in device mode');
  const rows = JSON.stringify({
    weights: [{ date: D, time: '07:30', kg: 70.25, context: 'morning', source: 'apple_health', source_key: 'a'.repeat(32) }],
    readings: [{ date: D, time: '07:35', systolic: 128, diastolic: 82, context: 'morning', source: 'apple_health', source_key: 'b'.repeat(32) }],
  });
  const first = JSON.parse(await global.KHDevice.addBody(rows));
  ok(() => assert.deepEqual(first, { added: { weights: 1, readings: 1 }, skipped: { weights: 0, readings: 0 } }), 'both rows added');
  ok(() => assert.equal(fresh.read('kdl-demo-local', 'state', 'current').rev, 2), 'saved before the answer');
  const again = JSON.parse(await global.KHDevice.addBody(rows));
  ok(() => assert.deepEqual(again, { added: { weights: 0, readings: 0 }, skipped: { weights: 1, readings: 1 } }), 'the same rows are skipped');
  const bad = JSON.parse(await global.KHDevice.addBody(JSON.stringify({ weights: [{ date: D, kg: 'x', context: 'morning', source_key: 'c'.repeat(32) }] })));
  ok(() => assert.equal(bad.status, 400), 'a row the server would refuse is refused');
  ok(() => assert.equal(api._entries.length, 0), 'no food entries were touched');
}

// 6. Outside device mode there is no bridge.
{
  const KH = loadDemo({ navigator: { userAgent: 'node', onLine: true, storage: {} }, globals: { KDL_PREVIEW: true } });
  const global = new KH.constructor.constructor('return globalThis')();
  ok(() => assert.equal(global.KHDevice, undefined), 'no KHDevice in the online demo');
  ok(() => assert.equal(KH.mock.device, undefined), 'no lookups in the online demo');
}

// 7. Food lookups through the iPhone app (step 2): a stand-in for the app's "bridge" answers with recorded fixtures. The barcode
//    route maps Open Food Facts with the server's rules (the stored row equals the demo's recorded Nutella row), asks the
//    server's consent question first and turns the service on once agreed; USDA search and import map with KH.usda.
{
  const fixture = (rel) => JSON.parse(readFileSync(join(ROOT, 'tests', 'fixtures', rel), 'utf8')).body;
  const fresh = createFakeIndexedDB();
  const KH = loadDemo({ navigator: { userAgent: 'node', onLine: true, storage: {} }, globals: { KDL_PREVIEW: true, KDL_DEVICE: true } });
  const api = KH.mock.start({ seed: false });
  KH.mock.local._useIndexedDB(fresh.page(new KH.constructor.constructor(`return ${CLONE_SRC}`)()));
  await KH.mock.local.boot();
  const global = new KH.constructor.constructor('return globalThis')();
  const asked = [];
  let offOn = false;
  global.webkit = { messageHandlers: { bridge: { postMessage: async (req) => {
    asked.push(req.kind);
    if (req.kind === 'services') return { ok: true, off: offOn, usda: true };
    if (req.kind === 'enableOff') { offOn = true; return { ok: true }; }
    if (req.kind === 'offProduct') {
      if (req.code === '3017624010701') return { ok: true, json: JSON.stringify(fixture('off/nutella_v3.4.json')) };
      return { error: 'not_found', message: 'not known' };
    }
    if (req.kind === 'usdaSearch') return { ok: true, json: JSON.stringify(fixture('usda/search_00049000028911.json')) };
    if (req.kind === 'usdaFood') return { ok: true, json: JSON.stringify(fixture('usda/food_1458203.json')) };
    return { error: 'bad_request' };
  } } } };
  await assert.rejects(api.request('POST', '/api/foods/barcode', { code: '3017624010701', format: 'ean_13' }),
    (e) => e.status === 503 && e.extra && e.extra.reason === 'off_consent_required');
  ok(() => assert.equal(offOn, false), 'nothing is sent before the person agrees');
  await api.request('PATCH', '/api/me/settings', { 'food.off_consent': true });
  const found = await api.request('POST', '/api/foods/barcode', { code: '3017624010701', format: 'ean_13' });
  ok(() => assert.equal(offOn, true), 'agreeing in the page turns Open Food Facts on in the app');
  const demoRow = KH.mock.DEMO_PRODUCTS.find((p) => p.code === '3017624010701').row;
  ok(() => assert.equal(found.food.name, demoRow.name), 'the stored row is the server\'s row for this product');
  ok(() => assert.deepEqual(found.food.nutrients, demoRow.nutrients), 'with the server\'s numbers');
  ok(() => assert.equal(found.source, 'off'));
  await assert.rejects(api.request('POST', '/api/foods/barcode', { code: '5000159407236', format: 'ean_13' }), (e) => e.status === 404);
  const search = await api.request('GET', '/api/foods/usda/search?q=diet%20coke');
  ok(() => assert.ok(search.foods.length > 0 && search.foods.every((f) => f.fdc_id > 0)), 'USDA search mapped with the server\'s rules');
  const imported = await api.request('POST', '/api/foods/usda/import', { fdc_id: 1458203 });
  ok(() => assert.equal(imported.source, 'usda'), 'a USDA import is a usda row');
  const again = await api.request('POST', '/api/foods/usda/import', { fdc_id: 1458203 });
  ok(() => assert.equal(again.id, imported.id), 'importing the same food again reuses its row');
}

// 8. The page asks Open Food Facts for the server's fields.
{
  const py = readFileSync(join(ROOT, 'app', 'off.py'), 'utf8');
  const block = py.slice(py.indexOf('FIELDS: tuple[str, ...] = ('), py.indexOf('FIELDS_V35'));
  const serverFields = [...block.matchAll(/"([a-z0-9_]+)"/g)].map((m) => m[1]);
  const KH = loadDemo({ navigator: { userAgent: 'node', onLine: true } });
  ok(() => assert.deepEqual([...KH.off.FIELDS], serverFields), 'KH.off.FIELDS is app/off.py FIELDS');
}

// 9. The first-start setup's state, and starting over with the sample data or an empty log (the setup's answer is kept).
{
  const fresh = createFakeIndexedDB();
  const page = () => {
    const KH = loadDemo({ navigator: { userAgent: 'node', onLine: true, storage: {} }, globals: { KDL_PREVIEW: true, KDL_DEVICE: true } });
    KH.mock.start({ seed: false });
    KH.mock.local._useIndexedDB(fresh.page(new KH.constructor.constructor(`return ${CLONE_SRC}`)()));
    return KH;
  };
  let KH = page();
  await KH.mock.local.boot();
  const s0 = await KH.mock.instance.request('GET', '/api/device/setup');
  ok(() => assert.deepEqual({ ...s0 }, { done: false, sample: false }), 'the setup is not done at the first start');
  await KH.mock.instance.request('PUT', '/api/device/setup', { done: true });
  await KH.mock.local.flush();
  await KH.mock.local.restart({ sample: true });
  KH = page();
  await KH.mock.local.boot();
  ok(() => assert.ok(KH.mock.instance._entries.length > 0 && KH.mock.instance._care().mine.length > 0), 'the sample data after starting over with it');
  const s1 = await KH.mock.instance.request('GET', '/api/device/setup');
  ok(() => assert.deepEqual({ ...s1 }, { done: true, sample: true }), 'the setup stays done');
  await KH.mock.local.restart({ sample: false });
  KH = page();
  await KH.mock.local.boot();
  ok(() => assert.equal(KH.mock.instance._entries.length + KH.mock.instance._care().mine.length, 0), 'an empty log after starting over without it');
  await assert.rejects(KH.mock.instance.request('PUT', '/api/device/setup', { done: 'yes' }), (e) => e.status === 400);
}

console.log(`device mode: ${checks} checks passed`);
