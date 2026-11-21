#!/usr/bin/env node
// Device mode (design note 38, step 1): the app inside the iPhone app runs the demo's in-page API with no server. It starts
// empty, keeps its data from the first start with no question, has one signed-in person who is not an admin, and hands a copy of
// the export to the iPhone app after each save (the safety copy). Run against a fake IndexedDB, like demo_local_storage.mjs;
// pytest (tests/test_device_mode.py) runs it. Exits 1 with the failed check on any mismatch.
import assert from 'node:assert/strict';
import { loadDemo } from './demo_loader.mjs';
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

console.log(`device mode: ${checks} checks passed`);
