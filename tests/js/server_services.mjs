#!/usr/bin/env node
// Device mode with a server, design note 39 steps 3 and 4: the page uses the person's server's food services and AI through the
// iPhone app's serverApi bridge (js/mock/server_api.js, foods.js, barcode.js, ai.js). A stand-in for the iPhone app answers the
// bridge like the app would, with a fake of the server's gateway (/push/v1/about and /push/v1/api/...), the phone's own food
// services and the iPhone's own AI. Checks: the two kinds of token, food lookups through the server and the fallback to the
// phone's own keys, that no key is sent, the AI's choice (server, then the iPhone, then none), that only an unreachable server
// or a 503/404 moves on, that a safety answer is never asked elsewhere, that lab text goes only to the lab routes, and that the
// server's food ids become the phone's. pytest (tests/test_server_services_phone.py) runs it. Exits 1 on any mismatch.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
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
const D = new Date().toISOString().slice(0, 10);
const plain = (v) => JSON.parse(JSON.stringify(v));
let checks = 0;
const ok = (fn, label) => { checks += 1; try { fn(); } catch (e) { e.message = `${label}: ${e.message}`; throw e; } };
const fails = (promise, code, test = () => true) => assert.rejects(promise, (e) => e.status === code && test(e));

const usdaFood = (id) => ({ id, name: 'Diet Coke, from the server', brand: 'Coca-Cola', category: 'Beverages', source: 'usda', fdc_id: 1458203,
  serving_desc: '1 can (355 mL)', serving_g: 355, nutrients: { calories_kcal: 0, sodium_mg: 40, potassium_mg: null, fluid_ml: 355 },
  flags: ['counts_as_fluid'], kidney_notes: null, hidden: false, gtin: '00049000028911', source_url: 'https://fdc.nal.usda.gov/food-details/1458203',
  source_license: 'CC0-1.0', quality: [], additives: [], ingredients_text: null });
const offFood = (id) => ({ id, name: 'Nutella', brand: 'Ferrero', category: null, source: 'off', fdc_id: null, serving_desc: '100 g', serving_g: 100,
  nutrients: { calories_kcal: 539, sodium_mg: 43, potassium_mg: null }, flags: [], kidney_notes: null, hidden: false, gtin: '03017624010701',
  source_url: 'https://world.openfoodfacts.org/product/3017624010701', source_license: 'ODbL-1.0',
  quality: [{ code: 'crowd_sourced', message: 'x' }], additives: [], ingredients_text: 'sugar, palm oil' });
const routeView = (feature, available) => ({ feature, available, route: 'local', consent: { host: 'ai.home.lan', skip_preview: true } });
const serverStatus = (on) => ({
  enabled: true, opted_in: true, available: true, reason: null, message: null, provider: { label: 'Home AI', host: 'ai.home.lan' },
  consent: { text: { host: 'ai.home.lan', skip_preview: true }, photos: null, chat: null, labs: { host: 'ai.home.lan', skip_preview: true }, voice: null },
  routing: { mode: 'routed' }, policy_version: 'p1', daily_limit: 30, remaining_today: 29,
  routes: Object.fromEntries(['photos', 'meal_ideas', 'describe', 'chat', 'labs', 'recipes'].map((f) => [f, routeView(f, on.includes(f))])),
  features: { next_meal: on.includes('meal_ideas'), parse_meal: on.includes('describe'), label: on.includes('photos'), plate: on.includes('photos'),
    chat: on.includes('chat'), voice: on.includes('chat'), lab_report: on.includes('labs'), lab_report_text: on.includes('labs'),
    recipes: on.includes('recipes'), recipe_steps: false },
});

// The stand-in app and the fake gateway. `gw` maps "METHOD /path" (no query) to an answer or a function of the request; an answer
// 'offline' is a server that could not be reached. { http, json } is an answer with that status; anything else is a 200 with it.
async function page({ paired = true, gw = {}, phone = {} } = {}) {
  const db = createFakeIndexedDB();
  const KH = loadDemo({ navigator: { userAgent: 'node', onLine: true, storage: {} }, globals: { KDL_PREVIEW: true, KDL_DEVICE: true } });
  KH.mock.instance = new KH.mock.MockApi({ foodsData: JSON.parse(FOODS), seed: false });
  const api = KH.mock.instance;
  KH.mock.local._useIndexedDB(db.page(new KH.constructor.constructor(`return ${CLONE_SRC}`)()));
  await KH.mock.local.boot();
  const global = new KH.constructor.constructor('return globalThis')();
  const log = []; // every bridge request
  const own = { usda: true, off: false, aiAvailable: true, ai: null, ...phone };
  global.webkit = { messageHandlers: { bridge: { postMessage: async (req) => {
    log.push(plain(req));
    if (req.kind === 'serverInfo') return paired ? { ok: true, paired: true, server: 'food.example.org' } : { ok: true, paired: false };
    if (req.kind === 'serverApi') {
      if (!paired) return { error: 'not_paired' };
      const key = `${req.method} ${req.path.split('?')[0]}`;
      let a = gw[key];
      if (typeof a === 'function') a = a(req);
      if (a === undefined) return { ok: true, status: 404, json: '{"detail":"Not Found"}' };
      if (a === 'offline') return { error: 'offline' };
      return { ok: true, status: a.http || 200, json: JSON.stringify(a.http || a.json ? a.json : a), ...(a.retryAfter ? { retryAfter: a.retryAfter } : {}) };
    }
    if (req.kind === 'services') return { ok: true, usda: own.usda, off: own.off, scan: false };
    if (req.kind === 'enableOff') { own.off = true; return { ok: true }; }
    if (req.kind === 'usdaSearch') return { ok: true, json: JSON.stringify({ foods: [{ fdcId: 1, description: 'PHONE SEARCH', dataType: 'Foundation', foodNutrients: [] }] }) };
    if (req.kind === 'usdaFood') return { error: 'offline', message: 'x' };
    if (req.kind === 'offProduct') return { error: 'not_found', message: 'x' };
    if (req.kind === 'aiStatus') return { ok: true, available: own.aiAvailable, reason: own.aiAvailable ? null : 'not_eligible' };
    if (req.kind === 'ai') return own.ai || { error: 'ai_failed', message: 'x' };
    return { error: 'bad_request' };
  } } } };
  const sent = (kind) => log.filter((r) => r.kind === kind);
  const gateway = (path) => log.filter((r) => r.kind === 'serverApi' && r.path.split('?')[0] === path);
  return { KH, api, log, own, sent, gateway };
}
const about = { json: { account: 'acct-1', api_version: 1, features: { sync: false, usda_search: true, barcodes: true, ai: { enabled: true } } } };

// 1. The two kinds of token, from GET /push/v1/about; and with no server, nothing is asked of one.
{
  const both = await page({ gw: { 'GET /push/v1/about': about } });
  const k = await both.KH.mock.serverApi.check();
  ok(() => assert.deepEqual([k.state, k.server, k.about.account, k.about.usda, k.about.barcode], ['both', 'food.example.org', 'acct-1', true, true]), 'both ways');
  const addOnly = await page({ gw: { 'GET /push/v1/about': { http: 401, json: { detail: 'Not authenticated' } } } });
  ok(() => assert.equal(addOnly.KH.mock.serverApi.status(), null), 'nothing known before it is asked');
  const kAdd = await addOnly.KH.mock.serverApi.check();
  ok(() => assert.equal(kAdd.state, 'add_only'), 'add only');
  const kOld = await (await page()).KH.mock.serverApi.check();
  ok(() => assert.equal(kOld.state, 'old_server'), 'a server without about');
  const kNone = await (await page({ paired: false })).KH.mock.serverApi.check();
  ok(() => assert.equal(kNone.state, 'not_paired'));
  const kOff = await (await page({ gw: { 'GET /push/v1/about': 'offline' } })).KH.mock.serverApi.check();
  ok(() => assert.equal(kOff.state, 'offline'));
  // the lenient reading: a flag at the top, or under features; one it does not mention is null
  const read = both.KH.mock.serverApi.readAbout;
  ok(() => assert.deepEqual(plain(read({ usda: false, ai: { routes: { describe: { available: true }, labs: false } } })),
    { account: null, version: null, sync: null, usda: false, barcode: null, ai: null, aiRoutes: { describe: true, labs: false } }));
  // an add-only token keeps today's behaviour: USDA with the phone's own key
  await addOnly.api.request('GET', '/api/foods/usda/search?q=rice');
  ok(() => assert.equal(addOnly.sent('usdaSearch').length, 1), 'add only: the phone\'s own USDA key');
  ok(() => assert.equal(addOnly.gateway('/push/v1/api/foods/usda/search').length, 0), 'and nothing through the gateway');
}

// 2. USDA through the server; the food it found is kept on the phone; the phone's own key only when the server cannot help.
{
  const gw = { 'GET /push/v1/about': about,
    'GET /push/v1/api/foods/usda/search': { foods: [{ fdc_id: 1458203, name: 'Diet Coke', data_type: 'Branded' }] },
    'POST /push/v1/api/foods/usda/import': (req) => usdaFood(JSON.parse(req.body).fdc_id === 1458203 ? 9001 : 0) };
  const { api, sent, gateway, log } = await page({ gw });
  const found = await api.request('GET', '/api/foods/usda/search?q=diet coke');
  ok(() => assert.deepEqual(plain(found.foods), [{ fdc_id: 1458203, name: 'Diet Coke', data_type: 'Branded' }]), 'the server\'s answer');
  ok(() => assert.equal(gateway('/push/v1/api/foods/usda/search')[0].path, '/push/v1/api/foods/usda/search?q=diet%20coke'), 'the words, encoded');
  ok(() => assert.equal(sent('usdaSearch').length, 0), 'the phone\'s own key is not used');
  const food = await api.request('POST', '/api/foods/usda/import', { fdc_id: 1458203 });
  ok(() => assert.notEqual(food.id, 9001), 'named by the phone\'s own id');
  ok(() => assert.deepEqual([food.source, food.fdc_id, food.name, food.gtin], ['usda', 1458203, 'Diet Coke, from the server', '00049000028911']), 'kept as the server sent it');
  ok(() => assert.ok(api._foodLinks().has(food.id)), 'linked to the person, so it is in their foods and works offline');
  const again = await api.request('POST', '/api/foods/usda/import', { fdc_id: 1458203 });
  ok(() => assert.equal(again.id, food.id), 'one row per fdc_id');
  await api.request('POST', '/api/log', { date: D, meal: 'lunch', food_id: food.id, servings: 1 }); // it can be logged
  ok(() => assert.ok(log.every((r) => !/key|khd_/i.test(JSON.stringify(r.body || ''))), 'no key in any request'));
  // the server has no USDA key (503), or cannot be reached: the phone's own key
  gw['GET /push/v1/api/foods/usda/search'] = { http: 503, json: { detail: 'USDA_API_KEY not configured' } };
  await api.request('GET', '/api/foods/usda/search?q=rice');
  ok(() => assert.equal(sent('usdaSearch').length, 1), 'a 503: the phone\'s own key');
  gw['GET /push/v1/api/foods/usda/search'] = 'offline';
  await api.request('GET', '/api/foods/usda/search?q=rice');
  ok(() => assert.equal(sent('usdaSearch').length, 2), 'offline: the phone\'s own key');
  // a refusal of the server's is the person's answer, not a reason to ask elsewhere
  const p2 = await page({ gw: { ...gw, 'GET /push/v1/api/foods/usda/search': { http: 429, json: { detail: 'Too many USDA lookups.' }, retryAfter: 60 } } });
  await fails(p2.api.request('GET', '/api/foods/usda/search?q=rice'), 429, (e) => e.extra.retry_after === 60);
  ok(() => assert.equal(p2.sent('usdaSearch').length, 0), 'a 429 is shown, not sent elsewhere');
  // about says the server has no USDA search: not asked
  const p3 = await page({ gw: { 'GET /push/v1/about': { json: { account: 'a', features: { usda_search: false } } } } });
  await p3.api.request('GET', '/api/foods/usda/search?q=rice');
  ok(() => assert.deepEqual([p3.gateway('/push/v1/api/foods/usda/search').length, p3.sent('usdaSearch').length], [0, 1]), 'about said no');
}

// 3. Barcodes through the server: its consent question, the food kept on the phone, and offline.
{
  let consentOnServer = false;
  const gw = { 'GET /push/v1/about': about,
    'POST /push/v1/api/foods/barcode': () => (consentOnServer
      ? { food: offFood(4242), gtin: '03017624010701', source: 'off', attribution: null, attributions: [{ text: '© Open Food Facts contributors' }], quality: [] }
      : { http: 503, json: { detail: 'To look this barcode up, turn on …', reason: 'off_consent_required', gtin: '03017624010701' } }),
    'PATCH /push/v1/api/me/settings': (req) => { consentOnServer = JSON.parse(req.body)['food.off_consent'] === true; return { settings: {} }; } };
  const { api, sent, gateway } = await page({ gw });
  const scan = () => api.request('POST', '/api/foods/barcode', { code: '3017624010701', format: 'ean_13' });
  await fails(scan(), 503, (e) => e.extra.reason === 'off_consent_required');
  ok(() => assert.equal(gateway('/push/v1/api/me/settings').length, 0), 'nothing is agreed for the person');
  await api.request('PATCH', '/api/me/settings', { 'food.off_consent': true });
  const got = await scan();
  ok(() => assert.deepEqual(JSON.parse(gateway('/push/v1/api/me/settings')[0].body), { 'food.off_consent': true }), 'their answer goes to the server, alone');
  ok(() => assert.deepEqual([got.source, got.food.name, got.food.gtin], ['off', 'Nutella', '03017624010701']), 'the server\'s product');
  ok(() => assert.notEqual(got.food.id, 4242), 'named by the phone\'s own id');
  ok(() => assert.equal(sent('offProduct').length + sent('enableOff').length, 0), 'the phone itself asked nobody');
  const local = await scan();
  ok(() => assert.equal(local.food.id, got.food.id), 'next time the phone has it');
  ok(() => assert.equal(gateway('/push/v1/api/foods/barcode').length, 3), 'and does not ask the server again');
  // offline, with the phone's own Open Food Facts off: say so; on: the phone looks it up itself
  const p2 = await page({ gw: { 'GET /push/v1/about': about, 'POST /push/v1/api/foods/barcode': 'offline' } });
  await fails(p2.api.request('POST', '/api/foods/barcode', { code: '5000159407236', format: 'ean_13' }), 502, (e) => /server can be reached/.test(e.detail));
  ok(() => assert.equal(p2.sent('offProduct').length, 0), 'offline: no lookup the person did not turn on');
  const p3 = await page({ gw: { 'GET /push/v1/about': about, 'POST /push/v1/api/foods/barcode': 'offline' }, phone: { off: true } });
  await fails(p3.api.request('POST', '/api/foods/barcode', { code: '5000159407236', format: 'ean_13' }), 404);
  ok(() => assert.equal(p3.sent('offProduct').length, 1), 'offline: the phone\'s own Open Food Facts, which the person turned on');
}

// 4. The AI's choice: the server first, then the iPhone's own, then none. Only unreachable, 503 or 404 moves on.
{
  const ai = { reply: null, status: serverStatus(['describe', 'meal_ideas', 'labs', 'photos', 'chat']) };
  const gw = { 'GET /push/v1/about': about, 'GET /push/v1/api/ai/status': () => ai.status, 'POST /push/v1/api/ai/parse-meal': () => ai.reply,
    'PATCH /push/v1/api/me/ai': (req) => ({ settings: JSON.parse(req.body) }) };
  const { KH, api, sent, gateway } = await page({ gw, phone: { ai: { ok: true, answer: { status: 'ok', items: [] } } } });
  const forget = () => KH.mock.aiDevice.forgetServer();
  const me = await api.request('PATCH', '/api/me/ai', { opt_in: true });
  ok(() => assert.deepEqual(JSON.parse(gateway('/push/v1/api/me/ai')[0].body), { opt_in: true }), 'the AI switch goes to the server too, alone');
  ok(() => assert.deepEqual([me.phone.both_ways, me.phone.where.describe, me.phone.where.labs, me.phone.where.chat], [true, 'server', 'server', null]),
    'Settings: where each feature runs (Ask stays off on the phone)');
  const st = await api.request('GET', '/api/ai/status');
  ok(() => assert.deepEqual([st.features.parse_meal, st.features.next_meal, st.features.label, st.features.chat, st.features.voice],
    [true, true, true, false, false]), 'the server\'s features, without Ask and voice');
  ok(() => assert.equal(st.routes.describe.runs_on_phone, 'server'));
  ok(() => assert.equal(st.consent.text.host, 'ai.home.lan'), 'the server\'s consent');
  const builtin = api._foods.find((f) => f.source === 'builtin' && f.fdc_id != null && /egg/i.test(f.name));
  const serverCopy = { ...api._foodView(builtin), id: 777777 };
  ai.reply = { status: 'ok', feature: 'parse_meal', provider: { label: 'Home AI' }, items: [{ text: '2 eggs', matches: [{ food: serverCopy, servings: 2 }] }], dropped: [] };
  const parse = (text, q = '') => api.request('POST', `/api/ai/parse-meal${q}`, { text, meal: 'lunch' });
  let got = await parse('2 eggs');
  ok(() => assert.equal(got.provider.label, 'Home AI'), 'the server answered');
  ok(() => assert.equal(got.items[0].matches[0].food.id, builtin.id), 'its food is named by the phone\'s id');
  ok(() => assert.equal(sent('ai').length, 0), 'the iPhone\'s model was not asked');
  // a safety answer is shown as it is and never asked anywhere else
  ai.reply = { status: 'treating_a_low', cards: [{ title: 'Treating a low', lines: ['Take 15 g of fast sugar.'] }], ai_called: false };
  got = await parse('my sugar is 55');
  ok(() => assert.deepEqual([got.status, got.cards[0].title], ['treating_a_low', 'Treating a low']), 'the server\'s low card');
  ok(() => assert.equal(sent('ai').length, 0), 'not retried on the iPhone');
  // a consent question, a limit or a failed call is the server's answer
  ai.reply = { http: 409, json: { detail: 'Agree to send this to the AI provider first.', consent_required: true, consent: { host: 'ai.home.lan' } } };
  await fails(parse('2 eggs'), 409, (e) => e.extra.consent_required === true && e.extra.consent.host === 'ai.home.lan');
  ai.reply = { http: 429, json: { detail: 'Today\'s shared AI calls are used up.' }, retryAfter: 600 };
  await fails(parse('2 eggs'), 429);
  ai.reply = { http: 502, json: { detail: 'The AI request failed.', reason: 'ai_failed' } };
  await fails(parse('2 eggs'), 502);
  ok(() => assert.equal(sent('ai').length, 0), 'none of them moved on to the iPhone');
  // not available (503), AI off there (404), or unreachable: the iPhone's own model
  for (const reply of [{ http: 503, json: { detail: 'AI is not available.', reason: 'no_provider' } }, { http: 404, json: { detail: 'Not Found' } }, 'offline']) {
    ai.reply = reply;
    forget();
    got = await parse('2 eggs');
    ok(() => assert.equal(got.provider.label, 'Apple\'s on-device model'), `moved on after ${JSON.stringify(reply).slice(0, 30)}`);
  }
  ok(() => assert.equal(sent('ai').length, 3));
  // the iPhone's own prefilter runs on that path
  ai.reply = 'offline';
  forget();
  got = await parse('my sugar is 55, what should I eat');
  ok(() => assert.equal(got.status, 'treating_a_low'), 'the iPhone path answers a low with the card, the model is not asked');
  ok(() => assert.equal(sent('ai').length, 3));
  // "Use only this iPhone's AI": the server is not asked at all
  ai.reply = { status: 'ok', items: [], provider: { label: 'Home AI' } };
  forget();
  const before = gateway('/push/v1/api/ai/parse-meal').length;
  await KH.mock.aiDevice.setOnly(true);
  const choice = await api.request('GET', '/api/device/ai-choice');
  ok(() => assert.equal(choice.device_only, true), 'the choice is kept');
  got = await parse('2 eggs');
  ok(() => assert.equal(got.provider.label, 'Apple\'s on-device model'), 'only the iPhone');
  ok(() => assert.equal(gateway('/push/v1/api/ai/parse-meal').length, before), 'the server was not asked');
  const st2 = await api.request('GET', '/api/ai/status');
  ok(() => assert.deepEqual([st2.features.next_meal, st2.features.parse_meal], [false, true]), 'only the iPhone\'s features');
  await fails(api.request('POST', '/api/ai/next-meal', { date: D, meal: 'lunch' }), 404);
  await KH.mock.aiDevice.setOnly(false);
  // with no AI on this iPhone and the server unreachable: the feature's way without AI
  const p2 = await page({ gw: { 'GET /push/v1/about': about, 'GET /push/v1/api/ai/status': serverStatus(['meal_ideas']), 'POST /push/v1/api/ai/next-meal': 'offline' },
    phone: { aiAvailable: false } });
  await fails(p2.api.request('POST', '/api/ai/next-meal', { date: D, meal: 'lunch' }), 503, (e) => e.extra.reason === 'server_unreachable');
}

// 5. Lab text only to the server's lab route (local AI only) or the iPhone's own model; never anywhere else, never a cloud fallback.
{
  const LAB = 'Potassium 4.6 mmol/L   Collected 2025-10-07';
  let reply = { status: 'ok', rows: [{ analyte: 'potassium', value: 4.6, unit: 'mmol/L' }], dropped: { not_in_text: 0 }, provider: { label: 'Home AI' } };
  const gw = { 'GET /push/v1/about': about, 'GET /push/v1/api/ai/status': serverStatus(['labs', 'describe']),
    'POST /push/v1/api/ai/read-lab-report-text': () => reply };
  const { KH, api, log, sent, gateway } = await page({ gw, phone: { ai: { ok: true, answer: { status: 'ok', rows: [] } } } });
  await api.request('PATCH', '/api/me/ai', { opt_in: true });
  let res = await api.request('POST', '/api/ai/read-lab-report-text', { text: LAB, page: 2 });
  ok(() => assert.equal(res.provider.label, 'Home AI'), 'the server\'s lab route');
  ok(() => assert.deepEqual(JSON.parse(gateway('/push/v1/api/ai/read-lab-report-text')[0].body), { text: LAB, page: 2 }), 'the text and page only');
  reply = { http: 503, json: { detail: 'No local AI.', reason: 'no_local_provider' } };
  KH.mock.aiDevice.forgetServer();
  res = await api.request('POST', '/api/ai/read-lab-report-text', { text: LAB, page: 2 });
  ok(() => assert.equal(res.provider.label, 'Apple\'s on-device model'), 'no local AI on the server: the iPhone\'s own, also local');
  ok(() => assert.equal(sent('ai').at(-1).task, 'read_lab_report_text'));
  const carried = log.filter((r) => JSON.stringify(r).includes('Potassium 4.6'));
  ok(() => assert.ok(carried.every((r) => (r.kind === 'serverApi' && r.path.startsWith('/push/v1/api/ai/read-lab-report-text'))
    || (r.kind === 'ai' && r.task === 'read_lab_report_text')), 'the lab text went nowhere else'));
}

// 6. Meal ideas and photos through the server; its food ids become the phone's; an idea with a food the phone lacks is left out.
{
  const gw = { 'GET /push/v1/about': about, 'GET /push/v1/api/ai/status': serverStatus(['meal_ideas', 'photos']),
    'POST /push/v1/api/ai/next-meal': null, 'POST /push/v1/api/vision/label': { status: 'ok', label: { name: 'Crackers', serving_g: 30 } } };
  const { api, gateway } = await page({ gw });
  const builtin = api._foods.find((f) => f.source === 'builtin' && f.fdc_id != null);
  gw['POST /push/v1/api/ai/next-meal'] = { status: 'ok', feature: 'next_meal', ideas: [
    { title: 'A', items: [{ food_id: 5001, name: builtin.name, servings: 1 }] },
    { title: 'B', items: [{ food_id: 5002, name: builtin.name, servings: 1 }, { food_id: 5003, name: 'Aunt May\'s stew', servings: 1 }] },
  ], dropped: [], entry_id: 99 };
  const got = await api.request('POST', '/api/ai/next-meal', { date: D, meal: 'lunch', mode: 'ideas', exclude_food_ids: [builtin.id] });
  ok(() => assert.deepEqual(plain(got.ideas.map((i) => i.title)), ['A']), 'the idea with a food this phone lacks is left out');
  ok(() => assert.equal(got.ideas[0].items[0].food_id, builtin.id), 'a built-in food is named by the phone\'s id');
  ok(() => assert.deepEqual(plain(got.dropped), [{ reason: 'not_on_this_iphone' }]), 'and the answer says so');
  ok(() => assert.equal(got.entry_id, null), 'no id of a row on the server is kept');
  ok(() => assert.ok(!('exclude_food_ids' in JSON.parse(gateway('/push/v1/api/ai/next-meal')[0].body)), 'the phone\'s own ids are not sent'));
  const photo = new Blob([new Uint8Array([0xff, 0xd8, 0xff, 0xe0, 1, 2, 3])], { type: 'image/jpeg' });
  const label = await api.request('POST', '/api/vision/label', photo);
  ok(() => assert.equal(label.label.name, 'Crackers'), 'a label photo read by the server\'s AI');
  ok(() => assert.equal(gateway('/push/v1/api/vision/label')[0].jpeg, '/9j/4AECAw=='), 'sent as the JPEG, in base64');
}

console.log(`server services: ${checks} checks passed`);
process.exit(0);
