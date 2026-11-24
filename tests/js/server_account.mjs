#!/usr/bin/env node
// Device mode, design note 39 step 8: saved meals both ways, and the profile, targets, account settings and food preferences that
// come from the person's server (js/mock/server_changes.js, js/mock/server_account.js, js/views/server_review.js).
//
//   node tests/js/server_account.mjs           without a server: nothing changes (the phone owns everything, as before)
//   node tests/js/server_account.mjs --relay   the real server: each bridge request is written to stdout as one line "@@ {json}"
//                                              and its answer read from stdin (tests/test_server_account_phone.py carries it to
//                                              the real routes through the app's allow-list, and plays the web app).
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
async function rejects(promise, status, re, label) {
  checks += 1;
  try { await promise; } catch (e) {
    try { assert.equal(e.status, status); if (re) assert.match(String(e.detail || e.message), re); } catch (x) { x.message = `${label}: ${x.message}`; throw x; }
    return;
  }
  throw new Error(`${label}: it went through`);
}

async function page({ bridge }) {
  const KH = loadDemo({ navigator: { userAgent: 'node', onLine: true, storage: {} }, globals: { KDL_PREVIEW: true, KDL_DEVICE: true },
    extra: ['js/views/server_review.js'] });
  KH.mock.instance = new KH.mock.MockApi({ foodsData: JSON.parse(FOODS), seed: false });
  const db = createFakeIndexedDB();
  KH.mock.local._useIndexedDB(db.page(new KH.constructor.constructor(`return ${CLONE_SRC}`)()));
  await KH.mock.local.boot();
  const global = new KH.constructor.constructor('return globalThis')();
  global.webkit = { messageHandlers: { bridge: { postMessage: async (req) => bridge(plain(req)) } } };
  return { KH, api: KH.mock.instance, S: KH.mock.serverSync, C: KH.mock.serverChanges, A: KH.mock.serverApi, P: KH.mock.serverAccount };
}
async function syncNow(p) { p.A.forget(); await p.S.sendNow(); return p.C.status(); }
const builtin = (api, name) => api._foods.find((f) => f.source === 'builtin' && f.name.toLowerCase().startsWith(name));
const mealBy = (api, name) => api._templates.filter((t) => t.name === name);

// ---------------------------------------------------------------------------------------------------------------- no server
async function alone() {
  const p = await page({ bridge: (req) => (req.kind === 'serverInfo' ? { ok: true, paired: false } : { error: 'not_paired' }) });
  const { api } = p;
  await api.request('PUT', '/api/profile', { name: 'Sam', ckd_stage: '4' });
  ok(() => assert.equal(api._profileView().ckd_stage, '4'), 'A1 not paired: the profile is changed on the phone');
  await api.request('PATCH', '/api/me/settings', { 'user.units.weight': 'lb' });
  ok(() => assert.equal(api._effectiveSetting('user.units.weight', api._currentUser().id).value, 'lb'), 'A1 and the settings');
  ok(() => assert.equal(p.P.active(), false), 'A1 nothing from a server');
  ok(() => assert.equal(p.KH.serverReview.count(), 0), 'A1 nothing to review');
  await p.S.sendNow();
  ok(() => assert.equal(api._serverAccount, undefined), 'A1 nothing kept for a server');
}

// ---------------------------------------------------------------------------------------------------------------- the real server
function relay() {
  const rl = createInterface({ input: process.stdin });
  const waiting = [];
  rl.on('line', (line) => { const next = waiting.shift(); if (next) next(JSON.parse(line)); });
  return (msg) => new Promise((resolve) => { waiting.push(resolve); process.stdout.write(`@@ ${JSON.stringify(msg)}\n`); });
}
async function realRuns() {
  const ask = relay();
  const web = async (method, path, json) => (await ask({ web: { method, path, json } }));
  let offline = false;
  const p = await page({ bridge: (req) => (offline && req.kind === 'serverApi' ? { error: 'offline' } : ask({ bridge: req })) });
  const { api, C, P, KH } = p;
  const RV = KH.rowVersions;
  const uid = api._currentUser().id;
  const setting = (key) => api._effectiveSetting(key, uid).value;

  // Before pairing, this phone has its own profile, a saved meal also on the server, one only here (with its own food), and a
  // "Not for me" food. The server has its own profile, set by a Care team member, a saved meal of its own and a liked food.
  const banana = builtin(api, 'banana');
  const apple = builtin(api, 'apple');
  await api.request('PUT', '/api/profile', { name: 'Sam', ckd_stage: '4', diabetes: 'type1', targets: { potassium_mg: { min: null, max: 2500 } } });
  const pudding = await api.request('POST', '/api/foods', { name: 'Rice pudding', serving_desc: '1 bowl', serving_g: 150, nutrients: { potassium_mg: 180 } });
  await api.request('POST', '/api/meals', { name: 'Usual breakfast', items: [{ food_id: banana.id, servings: 1 }] });
  await api.request('POST', '/api/meals', { name: 'Pudding night', items: [{ food_id: pudding.id, servings: 1 }], servings_made: 2, steps: ['Warm it'] });
  await api.request('PUT', `/api/guidance/preferences/${banana.id}`, { preference: 'not_for_me' });

  const webFood = async (q) => { const j = (await web('GET', `/api/foods?q=${encodeURIComponent(q)}`)).json; return (j.foods || j)[0]; };
  const wBanana = await webFood('banana');
  const wApple = await webFood('apple');
  await web('PUT', '/api/profile', { name: 'Sam', ckd_stage: '3b', diabetes: 'type1', targets: { potassium_mg: { min: null, max: 2000 } } });
  await web('POST', '/api/meals', { name: 'Usual breakfast', items: [{ food_id: wBanana.id, servings: 1 }] });
  const soup = (await web('POST', '/api/meals', { name: 'Web soup', items: [{ food_id: wApple.id, servings: 2 }], meal_hint: 'lunch' })).json;
  await web('PATCH', '/api/me/settings', { 'user.units.weight': 'lb', 'body.bp_goal': { systolic: 125, diastolic: 80 } });
  await web('PUT', `/api/guidance/preferences/${wApple.id}`, { preference: 'like' });

  // S1. The first sync: saved meals both ways, the profile and settings from the server, the §8.7 card.
  let st = await syncNow(p);
  st = await syncNow(p); // the phone's own saved meals go after the server's were read
  ok(() => assert.equal(st.active, true, JSON.stringify(st)), 'S1 both ways');
  ok(() => assert.equal(mealBy(api, 'Usual breakfast').length, 1), 'S1 the same saved meal on both is one row');
  ok(() => assert.equal(mealBy(api, 'Web soup').length, 1), 'S1 the server\'s saved meal came');
  ok(() => assert.equal(mealBy(api, 'Web soup')[0].meal_hint, 'lunch'), 'S1 with its slot');
  ok(() => assert.equal(mealBy(api, 'Web soup')[0].client_id, soup.client_id || mealBy(api, 'Web soup')[0].client_id), 'S1 one ID');
  const webMeals = (await web('GET', '/api/meals')).json.meals;
  ok(() => assert.deepEqual(webMeals.map((m) => m.name).sort(), ['Pudding night', 'Usual breakfast', 'Web soup']), 'S1 the phone\'s saved meal reached the server');
  const night = webMeals.find((m) => m.name === 'Pudding night');
  ok(() => assert.deepEqual([night.items[0].food_name, night.servings_made, night.steps], ['Rice pudding', 2, ['Warm it']]), 'S1 with its own food and recipe parts');
  ok(() => assert.equal(st.review, 0, JSON.stringify(st.items)), 'S1 the same meal needs no review');
  for (const [cid, rs] of Object.entries(api._serverChanges.rows.meal)) ok(() => assert.equal(rs.l, undefined, cid), 'S1 the phone works out the server\'s version of each saved meal');
  ok(() => assert.equal(api._profileView().ckd_stage, '3b'), 'S1 the server\'s profile is shown');
  ok(() => assert.deepEqual(plain(api._profileView().targets.potassium_mg), { min: null, max: 2000 }), 'S1 and its targets');
  const card = P.status().card;
  ok(() => assert.ok(card && card.mine.ckd_stage === '4' && card.server.ckd_stage === '3b', JSON.stringify(card)), 'S1 the card holds both');
  ok(() => assert.equal(KH.serverReview.count(), 1), 'S1 one to review: the badge');
  ok(() => assert.equal(setting('user.units.weight'), 'lb'), 'S1 the account settings');
  ok(() => assert.deepEqual(plain(setting('body.bp_goal')), { systolic: 125, diastolic: 80 }), 'S1 the blood pressure goal');
  const prefs = api._foodPreferences();
  ok(() => assert.equal((prefs.get(apple.id) || {}).preference, 'like'), 'S1 the server\'s food preference, on the phone\'s food');
  ok(() => assert.equal((prefs.get(banana.id) || {}).preference, 'not_for_me'), 'S1 the phone\'s own is kept');
  const serverPrefs = (await web('GET', '/api/guidance/preferences')).json.foods;
  ok(() => assert.equal(serverPrefs.find((f) => f.food_id === wBanana.id).preference, 'not_for_me'), 'S1 and was sent to the server once');

  // S2. "Keep this iPhone's" sends the phone's profile and targets to the server.
  await P.decide('mine');
  const wp = (await web('GET', '/api/profile')).json;
  ok(() => assert.deepEqual([wp.ckd_stage, wp.targets.potassium_mg && wp.targets.potassium_mg.max], ['4', 2500]), 'S2 the server has the phone\'s');
  ok(() => assert.equal(api._profileView().ckd_stage, '4'), 'S2 and the phone shows it');
  ok(() => assert.equal(P.status().card, null), 'S2 the card is gone');
  ok(() => assert.equal(KH.serverReview.count(), 0), 'S2 nothing to review');

  // S3. Saved meals: the phone's edit reaches the server; the web's edit reaches the phone; both changed: a review card.
  const usual = mealBy(api, 'Usual breakfast')[0];
  await api.request('PUT', `/api/meals/${usual.id}`, { name: 'Usual breakfast', items: [{ food_id: banana.id, servings: 1 }, { food_id: apple.id, servings: 1 }] });
  st = await syncNow(p);
  let wm = (await web('GET', '/api/meals')).json.meals.find((m) => m.name === 'Usual breakfast');
  ok(() => assert.deepEqual(wm.items.map((i) => i.food_name), [banana.name, apple.name]), 'S3 the phone\'s edit is on the server');
  ok(() => assert.equal(RV.version('meal', wm), RV.version('meal', api._templateView(usual))), 'S3 the same version on both');
  await web('PUT', `/api/meals/${soup.id}`, { name: 'Apple soup', items: [{ food_id: wApple.id, servings: 3 }] });
  st = await syncNow(p);
  const soupHere = api._templates.find((t) => t.client_id === mealBy(api, 'Apple soup').map((x) => x.client_id)[0]);
  ok(() => assert.ok(soupHere && soupHere.items[0].servings === 3, 'S3 the web\'s edit is on the phone'), 'S3 received');
  await web('PUT', `/api/meals/${soup.id}`, { name: 'Apple soup', note: 'from the web', items: [{ food_id: wApple.id, servings: 3 }] });
  await api.request('PUT', `/api/meals/${soupHere.id}`, { name: 'Apple soup', items: [{ food_id: apple.id, servings: 4 }] });
  st = await syncNow(p);
  ok(() => assert.deepEqual(plain(st.items.map((x) => [x.type, x.kind])), [['conflict', 'meal']]), 'S3 a conflict card for the saved meal');
  ok(() => assert.equal(C.needsReview('meal', soupHere.client_id), true), 'S3 it needs review');
  ok(() => assert.equal(KH.serverReview.count(), 1), 'S3 the badge says 1 to review');
  wm = (await web('GET', `/api/meals/${soup.id}`)).json;
  ok(() => assert.equal(wm.items[0].servings, 3), 'S3 nothing overwritten');
  await C.decide(st.items[0].key, 'mine');
  st = await syncNow(p);
  wm = (await web('GET', `/api/meals/${soup.id}`)).json;
  ok(() => assert.equal(wm.items[0].servings, 4), 'S3 "Use mine" is on the server');
  ok(() => assert.equal(KH.serverReview.count(), 0), 'S3 settled');
  // a delete on the web reaches the phone
  await web('DELETE', `/api/meals/${soup.id}`);
  await syncNow(p);
  ok(() => assert.equal(mealBy(api, 'Apple soup').length, 0), 'S3 the web\'s delete');

  // S4. An entry changed on both sides is marked for review (Today shows "needs review").
  const eWeb = (await web('POST', '/api/log', { date: D, meal: 'lunch', food_id: wBanana.id, servings: 1 })).json;
  await syncNow(p);
  const eHere = api._entries.find((e) => e.client_id === eWeb.client_id);
  await web('PUT', `/api/log/${eWeb.id}`, { note: 'web' });
  await api.request('PUT', `/api/log/${eHere.id}`, { servings: 2 });
  st = await syncNow(p);
  ok(() => assert.equal(KH.serverReview.needsReview('entry', eHere.client_id), true), 'S4 the entry needs review');
  ok(() => assert.equal(KH.serverReview.count(), 1), 'S4 one to review');
  await C.decide(st.items[0].key, 'server');
  await syncNow(p);
  ok(() => assert.equal(KH.serverReview.needsReview('entry', eHere.client_id), false), 'S4 settled');

  // S5. The profile, settings and preferences change on the phone only through the server.
  await api.request('PUT', '/api/profile', { weight_kg: 71.5 });
  const wp5 = (await web('GET', '/api/profile')).json;
  ok(() => assert.equal(wp5.weight_kg, 71.5), 'S5 the profile went to the server');
  await api.request('PATCH', '/api/me/settings', { 'user.units.weight': 'kg', 'ui.theme': 'dark' });
  const ws = (await web('GET', '/api/me/settings')).json.settings;
  ok(() => assert.deepEqual([ws['user.units.weight'].value, ws['ui.theme'].value], ['kg', 'system']), 'S5 the account setting went; this iPhone\'s theme stays here');
  ok(() => assert.deepEqual([setting('user.units.weight'), setting('ui.theme')], ['kg', 'dark']), 'S5 both on the phone');
  const g = setting('guidance');
  await api.request('PATCH', '/api/me/settings', { guidance: { ...g, carb_tolerance_g: 12, repeat_ok_meals: [usual.id] } });
  const wg = (await web('GET', '/api/me/settings')).json.settings.guidance.value;
  ok(() => assert.deepEqual([wg.carb_tolerance_g, wg.repeat_ok_meals], [12, []]), 'S5 the guidance choices went; this phone\'s ids did not');
  await api.request('PUT', `/api/guidance/preferences/${apple.id}`, { preference: 'less' });
  const wpref = (await web('GET', '/api/guidance/preferences')).json.foods.find((f) => f.food_id === wApple.id);
  ok(() => assert.equal(wpref.preference, 'less'), 'S5 the preference went to the server by its id there');
  await api.request('DELETE', `/api/guidance/not-for-me/${banana.id}`);
  const wp6 = (await web('GET', '/api/guidance/preferences')).json.foods;
  ok(() => assert.equal(wp6.some((f) => f.food_id === wBanana.id), false), 'S5 "Not for me" taken off there');
  // offline: nothing changes, and the person is told
  offline = true;
  await rejects(api.request('PUT', '/api/profile', { weight_kg: 90 }), 503, /needs a connection to your server/, 'S5 offline: the profile');
  await rejects(api.request('PATCH', '/api/me/settings', { 'body.weight_alarm': { enabled: true } }), 503, /needs a connection/, 'S5 offline: a setting');
  await rejects(api.request('PUT', `/api/guidance/preferences/${apple.id}`, { preference: 'like' }), 503, /needs a connection/, 'S5 offline: a preference');
  ok(() => assert.equal(api._profileView().weight_kg, 71.5), 'S5 nothing changed on the phone');
  await api.request('PATCH', '/api/me/settings', { 'ui.theme': 'light' });
  ok(() => assert.equal(setting('ui.theme'), 'light'), 'S5 this iPhone\'s own settings still change offline');
  offline = false;

  // S6. A Care team or the web changes a target: it reaches the phone at the next sync.
  await web('PUT', '/api/profile', { targets: { sodium_mg: { min: null, max: 1800 } } });
  await syncNow(p);
  ok(() => assert.deepEqual(plain(api._profileView().targets.sodium_mg), { min: null, max: 1800 }), 'S6 the server\'s new target on the phone');
  await ask({ done: true });
}

if (RELAY) await realRuns(); else await alone();
console.log(`server account${RELAY ? ' (real server)' : ''}: ${checks} checks passed`);
process.exit(0);
