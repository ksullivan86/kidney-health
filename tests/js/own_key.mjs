#!/usr/bin/env node
// The person's own AI key on the iPhone app (the owner, 2026-11-25; design note 39 §6.5; js/mock/ai.js). A stand-in for the iPhone
// app answers the bridge like the app would (ownAIStatus, ownAI, the iPhone's own model, and a fake of the paired server's gateway),
// with a stand-in provider behind ownAI. Checks: it works with no server ever set up; the order (server, own key, iPhone, none);
// which tasks reach the own key; the photo switch; never a lab report task; never the profile's name or birth month in a request;
// the server's prefilter cards before asking; the server's checks on every answer, malformed ones too; the consent sheet; the dry
// run; "Use only this iPhone's AI". pytest (tests/test_phone_own_key.py) runs it. Exits 1 on any mismatch.
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
const plain = (v) => JSON.parse(JSON.stringify(v));
let checks = 0;
const ok = (fn, label) => { checks += 1; try { fn(); } catch (e) { e.message = `${label}: ${e.message}`; throw e; } };
const fails = (promise, code, test = () => true) => assert.rejects(promise, (e) => e.status === code && test(e));

const NAME = 'Robin Quillfeather';
const BIRTH = '1971-03';
const OPENAI = { ok: true, set: true, provider: 'openai', label: 'OpenAI', host: 'api.openai.com', model: 'gpt-6-luna', photos: false };
const routeView = (feature, available) => ({ feature, available, route: 'local', consent: { host: 'ai.home.lan', skip_preview: true } });
const serverStatus = (on) => ({
  enabled: true, opted_in: true, available: true, reason: null, message: null, provider: { label: 'Home AI', host: 'ai.home.lan' },
  consent: { text: { host: 'ai.home.lan', skip_preview: true }, photos: null, chat: null, labs: null, voice: null },
  routing: { mode: 'routed' }, policy_version: 'p1', daily_limit: 30, remaining_today: 29,
  routes: Object.fromEntries(['photos', 'meal_ideas', 'describe', 'chat', 'labs', 'recipes'].map((f) => [f, routeView(f, on.includes(f))])),
  features: { next_meal: false, parse_meal: on.includes('describe'), label: false, plate: false, chat: false, voice: false, lab_report: false,
    lab_report_text: false, recipes: false, recipe_steps: false },
});
const about = { json: { account: 'acct-1', api_version: 1, features: { sync: false, usda_search: true, barcodes: true, ai: { enabled: true } } } };

// The stand-in app. `provider(req)` is the stand-in provider: { content } (the model's text), { refusal }, or { error } as the app
// answers it. `paired` false: no server was ever set up.
async function page({ paired = false, gw = {}, own = OPENAI, iphone = false, provider = null } = {}) {
  const db = createFakeIndexedDB();
  const KH = loadDemo({ navigator: { userAgent: 'node', onLine: true, storage: {} }, globals: { KDL_PREVIEW: true, KDL_DEVICE: true } });
  KH.mock.instance = new KH.mock.MockApi({ foodsData: JSON.parse(FOODS), seed: false });
  const api = KH.mock.instance;
  KH.mock.local._useIndexedDB(db.page(new KH.constructor.constructor(`return ${CLONE_SRC}`)()));
  await KH.mock.local.boot();
  Object.assign(api._profile, { name: NAME, birth_month: BIRTH });
  const global = new KH.constructor.constructor('return globalThis')();
  const log = [];
  const state = { own: own ? { ...own } : null, iphone, provider };
  global.webkit = { messageHandlers: { bridge: { postMessage: async (req) => {
    log.push(plain(req));
    if (req.kind === 'serverInfo') return paired ? { ok: true, paired: true, server: 'food.example.org' } : { ok: true, paired: false };
    if (req.kind === 'serverApi') {
      if (!paired) return { error: 'not_paired' };
      let a = gw[`${req.method} ${req.path.split('?')[0]}`];
      if (typeof a === 'function') a = a(req);
      if (a === undefined) return { ok: true, status: 404, json: '{"detail":"Not Found"}' };
      if (a === 'offline') return { error: 'offline' };
      return { ok: true, status: a.http || 200, json: JSON.stringify(a.http || a.json ? a.json : a) };
    }
    if (req.kind === 'ownAIStatus') return state.own || { ok: true, set: false };
    if (req.kind === 'ownAI') {
      // as OwnAI.swift: only its three tasks, photos only with the switch on, nothing without a key
      if (!['parse_meal', 'read_label', 'plate'].includes(req.task)) return { error: 'bad_request', message: 'x' };
      if (!state.own) return { error: 'own_off', message: 'x' };
      if (req.task !== 'parse_meal' && !state.own.photos) return { error: 'photos_off', message: 'x' };
      const r = state.provider ? state.provider(req) : { error: 'offline' };
      if (r.error) return { error: r.error, message: `provider: ${r.error}` };
      return { ok: true, content: r.content == null ? '' : r.content, refusal: r.refusal || null, finish: 'stop' };
    }
    if (req.kind === 'aiStatus') return { ok: true, available: state.iphone, reason: state.iphone ? null : 'not_eligible' };
    if (req.kind === 'ai') return { ok: true, answer: req.task === 'parse_meal' ? { status: 'ok', items: [] } : { status: 'ok', rows: [] } };
    if (req.kind === 'services') return { ok: true, usda: false, off: false, scan: false };
    return { error: 'bad_request' };
  } } } };
  const sent = (kind) => log.filter((r) => r.kind === kind);
  return { KH, api, log, state, sent };
}
const meal = (items) => JSON.stringify({ items, status: 'ok' });
const item = (text, search, amount, unit) => ({ text, search, amount, unit });
const parse = (api, text, q = '') => api.request('POST', `/api/ai/parse-meal${q}`, { text, meal: 'lunch' });
const agree = (api, purpose) => api.request('POST', '/api/ai/consent', { provider_id: -1, purpose, skip_preview: true });

// 1. No server ever set up: the own key alone runs describe a meal, with the server's checks; Settings and Ask say so.
const P1 = await page({ provider: () => ({ content: meal([item('2 eggs', 'egg', 2, 'piece'), item('www.x.com', 'rice', 1, 'cup')]) }) });
{
  const { api, sent } = P1;
  let me = await api.request('GET', '/api/me/ai');
  ok(() => assert.equal(me.enabled, true), 'AI features can be turned on with only an own key');
  ok(() => assert.deepEqual([me.phone.where.describe, me.phone.where.photos, me.phone.where.labs, me.phone.where.chat], [null, null, null, null]),
    'nothing runs before the person turns AI on');
  await fails(parse(api, '2 eggs'), 503, (e) => e.extra.reason === 'not_opted_in');
  me = await api.request('PATCH', '/api/me/ai', { opt_in: true });
  ok(() => assert.deepEqual([me.phone.where.describe, me.phone.where.photos, me.phone.where.labs], ['own', null, null]), 'where each feature runs');
  ok(() => assert.deepEqual(plain(me.phone.own_key), { label: 'OpenAI', host: 'api.openai.com', model: 'gpt-6-luna', photos: false }));
  ok(() => assert.equal(me.phone.ask, 'not_paired'), 'Ask stays the server\'s');
  ok(() => assert.equal(me.phone.photos, 'own_photos_off'), 'the photo line says how to turn photos on');
  ok(() => assert.equal(sent('serverApi').length, 0), 'no server was asked anything');
  const st = await api.request('GET', '/api/ai/status');
  ok(() => assert.deepEqual([st.features.parse_meal, st.features.label, st.features.plate, st.features.lab_report_text, st.features.chat, st.features.next_meal],
    [true, false, false, false, false, true]), 'describe a meal and meal ideas (note 39 §6.6); no photos, labs or Ask');
  ok(() => assert.equal(st.routes.describe.runs_on.host, 'api.openai.com'));
  // the consent sheet first, naming the provider and its host
  await fails(parse(api, '2 eggs'), 409, (e) => e.extra.consent_required === true && e.extra.consent.host === 'api.openai.com'
    && e.extra.consent.own_key === true && e.extra.consent.provider_id === -1 && /OpenAI does not use API data/.test(e.extra.consent.policy));
  ok(() => assert.equal(sent('ownAI').length, 0), 'nothing sent before the person agrees');
  const given = await agree(api, 'text');
  ok(() => assert.equal(given.host, 'api.openai.com'));
  const got = await parse(api, '2 eggs and rice');
  ok(() => assert.equal(got.provider.label, 'OpenAI (your own key)'), 'the own key answered');
  ok(() => assert.equal(got.status, 'ok'));
  ok(() => assert.deepEqual(plain(got.items.map((i) => i.text)), ['2 eggs']), 'the server\'s name policy dropped the link');
  ok(() => assert.deepEqual(plain(got.dropped), [{ index: 1, reason: 'text_policy:url' }]));
  ok(() => assert.ok(got.items[0].matches.length > 0), 'matched to the phone\'s foods');
  ok(() => assert.equal(got.audit_id, null), 'nothing kept');
  const req = sent('ownAI')[0];
  ok(() => assert.deepEqual(Object.keys(req).sort(), ['kind', 'task', 'text']), 'a task and its data only');
  ok(() => assert.equal(req.text, P1.KH.aiJudge.dataPayload(P1.KH.aiJudge.parseMealData('2 eggs and rice'))), 'the server\'s data block');
}

// 2. The server's prefilter answers a low, an emergency and a dose question: the own key is never asked.
{
  const { api, sent } = P1;
  const before = sent('ownAI').length;
  for (const [text, status] of [['my sugar is 55, what should I eat', 'treating_a_low'], ['chest pain after lunch', 'red_flag'],
    ['how much insulin for this pasta', 'medicine_question']]) {
    const got = await parse(api, text);
    ok(() => assert.equal(got.status, status), text);
  }
  ok(() => assert.equal(sent('ownAI').length, before), 'not asked');
}

// 3. Answers that are not what was asked for: a refusal, no JSON, a wrong shape, code fences.
{
  const { api, state } = P1;
  state.provider = () => ({ refusal: 'I cannot help with that.' });
  let got = await parse(api, 'pasta');
  ok(() => assert.deepEqual([got.status, got.message], ['refused', P1.KH.aiJudge.REFUSED_TEXT]), 'a refusal is the server\'s text');
  state.provider = () => ({ content: 'Sure! You had pasta.' });
  got = await parse(api, 'pasta');
  ok(() => assert.deepEqual([got.status, got.reason], ['error', 'schema']), 'no JSON');
  state.provider = () => ({ content: '{"items": "pasta", "status": "ok"}' });
  got = await parse(api, 'pasta');
  ok(() => assert.deepEqual([got.status, got.reason], ['error', 'schema']), 'the wrong shape');
  state.provider = () => ({ content: '```json\n' + meal([item('pasta', 'pasta', 1, 'cup'), { text: 'x' }]) + '\n```' });
  got = await parse(api, 'pasta');
  ok(() => assert.deepEqual(plain(got.dropped), [{ index: 1, reason: 'malformed_item' }]), 'a bad item is left out and counted');
  state.provider = () => ({ error: 'key_refused' });
  await fails(parse(api, 'pasta'), 502, (e) => e.extra.reason === 'key_refused');
  state.provider = () => ({ error: 'rate_limited' });
  await fails(parse(api, 'pasta'), 429);
}

// 4. The name or birth month is never sent: the request goes to this iPhone's model, or nowhere.
{
  const { api, state, sent } = P1;
  state.provider = () => ({ content: meal([]) });
  const before = sent('ownAI').length;
  for (const text of ['toast for robin', `${NAME} had eggs`, 'cake for my birthday 1971-03', 'birthday cake 03/1971', 'cake march 1971']) {
    await fails(parse(api, text), 503, (e) => e.extra.reason === 'identity');
  }
  ok(() => assert.equal(sent('ownAI').length, before), 'not sent to the own key');
  state.iphone = true;
  const got = await parse(api, 'toast for Robin');
  ok(() => assert.equal(got.provider.label, 'Apple\'s on-device model'), 'the iPhone\'s own model instead');
  state.iphone = false;
}

// 5. A provider that cannot be reached: this iPhone's model if it has one, else the feature's way without AI.
{
  const { api, state, sent } = P1;
  state.provider = () => ({ error: 'offline' });
  await fails(parse(api, 'pasta'), 503, (e) => e.extra.reason === 'own_unreachable');
  state.iphone = true;
  state.provider = () => ({ error: 'not_available' });
  const got = await parse(api, 'pasta');
  ok(() => assert.equal(got.provider.label, 'Apple\'s on-device model'), 'moved on to the iPhone');
  ok(() => assert.equal(sent('ai').at(-1).task, 'parse_meal'));
  state.iphone = false;
}

// 6. The dry run shows where it goes and sends nothing.
{
  const { api, sent } = P1;
  const before = sent('ownAI').length;
  const dry = await parse(api, '2 eggs', '?dry_run=true');
  ok(() => assert.deepEqual([dry.dry_run, dry.own_key, dry.host, dry.provider.local], [true, true, 'api.openai.com', false]));
  ok(() => assert.ok(!JSON.stringify(dry).includes('sk-')), 'never a key');
  ok(() => assert.equal(sent('ownAI').length, before));
}

// 7. Photos: only with the person's switch on, after the photo consent; read with the server's label and plate checks.
{
  const { api, state, sent } = P1;
  const photo = () => new Blob([new Uint8Array([0xff, 0xd8, 0xff, 0xe0, 1, 2, 3])], { type: 'image/jpeg' });
  await fails(api.request('POST', '/api/vision/label', photo()), 404);
  ok(() => assert.equal(sent('ownAI').filter((r) => r.jpeg).length, 0), 'switch off: no photo sent');
  state.own.photos = true;
  const me = await api.request('GET', '/api/me/ai');
  ok(() => assert.deepEqual([me.phone.where.photos, me.phone.photos], ['own', 'not_paired']));
  await fails(api.request('POST', '/api/vision/label', photo()), 409, (e) => e.extra.consent.purpose === 'photos');
  await agree(api, 'photos');
  const label = { status: 'ok', product_name: 'Crackers', serving_text: '5 crackers (30 g)', serving_g: 30, basis: 'per_serving',
    per_serving: { calories_kcal: 130, protein_g: 2, fat_g: 4.5, sat_fat_g: null, carbs_g: 21, fiber_g: null, sugar_g: null, sodium_mg: 210,
      potassium_mg: null, phosphorus_mg: null, calcium_mg: null }, salt_g: null,
    percent_dv: { sodium: null, potassium: null, phosphorus: null, calcium: null }, ingredients_text: 'Flour, sodium phosphate', label_style: 'us_nutrition_facts' };
  state.provider = (req) => ({ content: req.task === 'read_label' ? JSON.stringify(label) : JSON.stringify({ status: 'ok', items: [
    { name: 'Rice', search: 'rice', grams_estimate: 150, confidence: 'medium' }, { name: 'insulin pen', search: 'pen', grams_estimate: 10, confidence: 'high' }] }) });
  const read = await api.request('POST', '/api/vision/label', photo());
  ok(() => assert.deepEqual([read.status, read.draft.name, read.draft.serving_g], ['ok', 'Crackers', 30]), 'the label draft');
  ok(() => assert.ok(read.checks.some((c) => c.code === 'potassium_unknown') && read.checks.some((c) => c.code === 'additive:phosphate')));
  ok(() => assert.equal(sent('ownAI').at(-1).jpeg, '/9j/4AECAw=='), 'the JPEG, in base64');
  const plate = await api.request('POST', '/api/vision/plate', photo());
  ok(() => assert.deepEqual(plain(plate.items.map((i) => i.name)), ['Rice']), 'the blocklist dropped the insulin pen');
  ok(() => assert.equal(plate.items[0].portion_text, 'about 150 g'));
  ok(() => assert.match(plate.banner, /do not dose insulin from this alone/));
}

// 8. Lab reports never go to the own key: the text only to this iPhone's model, a photo nowhere here.
{
  const { api, sent, state } = P1;
  const before = sent('ownAI').length;
  await fails(api.request('POST', '/api/ai/read-lab-report-text', { text: 'Potassium 4.6 mmol/L', page: 1 }), 503);
  const photo = new Blob([new Uint8Array([0xff, 0xd8, 0xff, 0xe0, 1])], { type: 'image/jpeg' });
  await fails(api.request('POST', '/api/ai/read-lab-report', photo), 404);
  state.iphone = true;
  const got = await api.request('POST', '/api/ai/read-lab-report-text', { text: 'Potassium 4.6 mmol/L', page: 1 });
  ok(() => assert.equal(got.provider.label, 'Apple\'s on-device model'), 'the iPhone\'s own model, which is local');
  state.iphone = false;
  ok(() => assert.equal(sent('ownAI').length, before), 'never the own key');
  ok(() => assert.ok(sent('ownAI').every((r) => ['parse_meal', 'read_label', 'plate'].includes(r.task))), 'only its three tasks, ever');
}

// 9. No request to the own key ever holds the profile's name or birth month.
{
  const bodies = P1.sent('ownAI').map((r) => JSON.stringify(r).toLowerCase());
  ok(() => assert.ok(bodies.length >= 8, `${bodies.length} requests were made`));
  for (const needle of ['robin', 'quillfeather', '1971', '03/1971', 'march 1971']) {
    ok(() => assert.ok(bodies.every((b) => !b.includes(needle)), needle), `no "${needle}" in any own-key request`);
  }
}

// 10. "Use only this iPhone's AI" skips the own key too.
{
  const { api, KH, sent, state } = P1;
  state.provider = () => ({ content: meal([]) });
  const before = sent('ownAI').length;
  await KH.mock.aiDevice.setOnly(true);
  const me = await api.request('GET', '/api/me/ai');
  ok(() => assert.equal(me.phone.own_key, null));
  await fails(parse(api, 'pasta'), 503);
  ok(() => assert.equal(sent('ownAI').length, before), 'not asked');
  await KH.mock.aiDevice.setOnly(false);
}

// 11. With a server paired both ways: the server first; the own key only when the server cannot be reached or does not offer it.
{
  const ai = { reply: { status: 'ok', items: [], dropped: [], provider: { label: 'Home AI' } } };
  const gw = { 'GET /push/v1/about': about, 'GET /push/v1/api/ai/status': serverStatus(['describe']), 'POST /push/v1/api/ai/parse-meal': () => ai.reply,
    'PATCH /push/v1/api/me/ai': (req) => ({ settings: JSON.parse(req.body) }) };
  const { KH, api, sent } = await page({ paired: true, gw, provider: () => ({ content: meal([]) }) });
  await KH.mock.serverApi.check();
  await api.request('PATCH', '/api/me/ai', { opt_in: true });
  await agree(api, 'text');
  let got = await parse(api, 'pasta');
  ok(() => assert.equal(got.provider.label, 'Home AI'), 'the server\'s AI first');
  ok(() => assert.equal(sent('ownAI').length, 0));
  ai.reply = { status: 'treating_a_low', cards: [{ title: 'Treating a low' }] };
  got = await parse(api, 'pasta');
  ok(() => assert.equal(got.status, 'treating_a_low'), 'a safety answer is shown as it is');
  ok(() => assert.equal(sent('ownAI').length, 0), 'and never asked elsewhere');
  ai.reply = 'offline';
  KH.mock.aiDevice.forgetServer();
  got = await parse(api, 'pasta');
  ok(() => assert.equal(got.provider.label, 'OpenAI (your own key)'), 'unreachable server: the own key');
  const me = await api.request('GET', '/api/me/ai');
  ok(() => assert.equal(me.phone.where.describe, 'own'));
}

console.log(`own AI key: ${checks} checks passed`);
process.exit(0);
