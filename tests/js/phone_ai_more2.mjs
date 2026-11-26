#!/usr/bin/env node
// AI order, AI swaps and AI day plans on the iPhone (the owner, 2026-11-26; design note 39 §6.6; js/mock/ai.js). A stand-in for the
// iPhone app answers the bridge like the app would: aiStatus and ai (the iPhone's own model), ownAIStatus and ownAI (the person's own
// key), serverInfo and serverApi (a fake of the paired server's gateway). Checks: the modes rerank, swap and plan of
// POST /api/ai/next-meal on the iPhone's model and on the own key, with the server's candidates, data block and judges
// (js/engine/aimeal.js); a low treatment is never sent; swaps and day plans never go to the server; AI order does, and its rows are
// found in this phone's list by name. pytest (tests/test_phone_ai_more2.py) runs it. Exits 1 on any mismatch.
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

const OPENAI = { ok: true, set: true, provider: 'openai', label: 'OpenAI', host: 'api.openai.com', model: 'gpt-6-luna', photos: false };
const OWN_TASKS = ['parse_meal', 'read_label', 'plate', 'next_meal', 'recipes', 'rerank', 'swap', 'plan']; // OwnAI.swift tasks
const PHONE_TASKS = ['parse_meal', 'read_lab_report_text', 'next_meal', 'recipes', 'read_label', 'plate', 'rerank', 'swap', 'plan']; // OnDeviceAI
const TARGETS = { potassium_mg: { max: 3000 }, phosphorus_mg: { max: 1000 }, sodium_mg: { max: 2000 }, carbs_per_meal_g: 60, protein_g: 60,
  fluid_ml: { max: 1500 } };
const D = '2026-11-26';

// The stand-in models answer each task from its data block: AI order names the first and third candidates and a made-up ref, a swap
// picks the second rule swap and a made-up one, a day plan picks option 1 of each meal and a meal that is not in the plan.
const dataOf = (req) => JSON.parse(req.text);
function answerFor(req) {
  const d = dataOf(req);
  if (req.task === 'rerank') {
    return { order: [{ ref: 'f3', reason_codes: ['you_like', 'low_sodium'] }, { ref: 'f1', reason_codes: ['low_potassium'] },
      { ref: 'zz9', reason_codes: ['low_sodium'] }], status: 'ok', refusal: 'none' };
  }
  if (req.task === 'swap') {
    const refs = d.swaps.map((s) => s.ref);
    return { pick: [{ ref: refs[1] || refs[0], reason_codes: ['low_potassium'] }, { ref: 's99', reason_codes: ['low_sodium'] }], status: 'ok', refusal: 'none' };
  }
  if (req.task === 'plan') {
    const picks = Object.entries(d.plan).map(([meal, opts]) => ({ meal, index: Math.min(1, opts.length - 1), reason_codes: ['low_sodium'] }));
    const bad = { meal: picks.length ? picks[0].meal : 'snack', index: 19, reason_codes: ['low_sodium'] }; // not an option: dropped
    return { picks: [...picks.slice(0, 3), bad], status: 'ok', refusal: 'none' };
  }
  return { status: 'ok', items: [] };
}

async function page({ own = null, iphone = true, model = (req) => ({ answer: answerFor(req) }), provider = null, gw = null } = {}) {
  const db = createFakeIndexedDB();
  const KH = loadDemo({ navigator: { userAgent: 'node', onLine: true, storage: {} }, globals: { KDL_PREVIEW: true, KDL_DEVICE: true } });
  KH.mock.instance = new KH.mock.MockApi({ foodsData: JSON.parse(FOODS), seed: false });
  const api = KH.mock.instance;
  KH.mock.local._useIndexedDB(db.page(new KH.constructor.constructor(`return ${CLONE_SRC}`)()));
  await KH.mock.local.boot();
  Object.assign(api._profile, { name: 'Robin Quillfeather', birth_month: '1971-03', targets: TARGETS, ckd_stage: '4', diabetes: 'type1',
    ckd_stage_chosen: true, diabetes_chosen: true });
  const global = new KH.constructor.constructor('return globalThis')();
  const log = [];
  const state = { own: own ? { ...own } : null, iphone, model, provider, gw };
  global.webkit = { messageHandlers: { bridge: { postMessage: async (req) => {
    log.push(plain(req));
    if (req.kind === 'serverInfo') return state.gw ? { ok: true, paired: true, server: 'food.example.org' } : { ok: true, paired: false };
    if (req.kind === 'serverApi') {
      if (!state.gw) return { error: 'not_paired' };
      let a = state.gw[`${req.method} ${req.path.split('?')[0]}`];
      if (typeof a === 'function') a = a(req);
      if (a === undefined) return { ok: true, status: 404, json: '{"detail":"Not Found"}' };
      return { ok: true, status: 200, json: JSON.stringify(a) };
    }
    if (req.kind === 'ownAIStatus') return state.own || { ok: true, set: false };
    if (req.kind === 'ownAI') {
      state.ownKeys = Object.keys(req).sort(); // as the app gets them: a key that is there, even undefined, is there
      if (!OWN_TASKS.includes(req.task)) return { error: 'bad_request', message: 'x' };
      const r = state.provider ? state.provider(req) : { error: 'offline' };
      if (r.error) return { error: r.error, message: `provider: ${r.error}` };
      return { ok: true, content: r.content, refusal: null, finish: 'stop' };
    }
    if (req.kind === 'aiStatus') return state.iphone ? { ok: true, available: true, reason: null, photos: false } : { ok: true, available: false, reason: 'not_eligible', photos: false };
    if (req.kind === 'ai') {
      if (!PHONE_TASKS.includes(req.task)) return { error: 'bad_request', message: 'x' };
      const r = state.model(req);
      return r.error ? { error: r.error, message: 'x' } : { ok: true, answer: r.answer };
    }
    if (req.kind === 'services') return { ok: true, usda: false, off: false, scan: false };
    return { error: 'bad_request' };
  } } } };
  const sent = (kind) => log.filter((r) => r.kind === kind);
  const gateway = (path) => log.filter((r) => r.kind === 'serverApi' && r.path.split('?')[0] === path);
  await api.request('PATCH', '/api/me/ai', { opt_in: true });
  return { KH, api, log, state, sent, gateway };
}
const food = (api, name) => { const f = api._foods.find((x) => x.name === name); assert.ok(f, name); return f; };
const GLUCOSE = 'Glucose tablet (4 g carb)';
const POTATO = 'Potato, baked, with skin';

// 1. AI order on the iPhone's own model: the task, its data block (no ids: the answer names refs), the server's judge.
{
  const { api, sent } = await page();
  const st = await api.request('GET', '/api/ai/status');
  ok(() => assert.deepEqual(plain(st.swap_plan), { available: true, label: 'Apple\'s on-device model', stays: true }), 'swaps and plans: this iPhone');
  const got = await api.request('POST', '/api/ai/next-meal', { meal: 'dinner', date: D, mode: 'rerank' });
  const req = sent('ai').at(-1);
  ok(() => assert.equal(req.task, 'rerank'), 'the rerank task');
  ok(() => assert.deepEqual(Object.keys(req).sort(), ['condition', 'kind', 'task', 'text']), 'a condition, no ids');
  ok(() => assert.ok(req.text.length <= 5000, `${req.text.length}`), 'the data block fits the iPhone model');
  ok(() => assert.ok(got.trimmed > 0), 'trimmed, as the server trims AI order');
  ok(() => assert.deepEqual([got.status, got.mode, got.feature], ['ok', 'rerank', 'next_meal']));
  ok(() => assert.deepEqual(plain(got.order.map((o) => [o.ref, o.ai_rank])), [['f3', 1], ['f1', 2]]), 'the AI\'s order for real refs');
  ok(() => assert.deepEqual(plain(got.dropped), [{ index: 2, reason: 'not_a_candidate' }]), 'a made-up ref is dropped');
  ok(() => assert.ok(!got.order[0].reason_codes.includes('you_like')), 'a false "you like" claim is removed');
  ok(() => assert.ok(got.order.every((o) => typeof o.name === 'string' && Number.isInteger(o.food_id))));
  const ids = new Set(dataOf(req).candidates.map((c) => c.id));
  ok(() => assert.ok([...got.order, ...got.rest].every((o) => ids.has(o.food_id))), 'only candidates the model was shown');
  ok(() => assert.equal(got.provider.label, 'Apple\'s on-device model'));
  ok(() => assert.equal(got.audit_id, null), 'nothing kept');
  ok(() => assert.ok(!req.text.toLowerCase().includes('robin')), 'never the name');
  const before = sent('ai').length;
  const dry = await api.request('POST', '/api/ai/next-meal?dry_run=true', { meal: 'dinner', date: D, mode: 'rerank' });
  ok(() => assert.deepEqual([dry.dry_run, dry.mode, dry.feature, sent('ai').length], [true, 'rerank', 'next_meal', before]), 'the dry run sends nothing');
  await fails(api.request('POST', '/api/ai/next-meal', { meal: 'dinner', mode: 'rerank', exclude_food_ids: [1] }), 400);
}

// 2. AI swaps: by a food not logged yet and by a planned entry; a low treatment never goes to any AI.
{
  const { api, sent } = await page();
  const potato = food(api, POTATO);
  const got = await api.request('POST', '/api/ai/next-meal', { meal: 'dinner', date: D, mode: 'swap', food_id: potato.id, servings: 2 });
  const req = sent('ai').at(-1);
  const data = dataOf(req);
  ok(() => assert.equal(req.task, 'swap'));
  ok(() => assert.deepEqual([data.planned_item.name, data.planned_item.quarters], [POTATO, 8]), 'the planned item');
  ok(() => assert.ok(data.swap_reason.includes('potassium_mg'), JSON.stringify(data.swap_reason)), 'why it is swapped');
  ok(() => assert.ok(data.swaps.length > 1 && data.swaps.every((s) => /^s\d+$/.test(s.ref))), 'the rule swaps');
  ok(() => assert.ok(req.text.length <= 5000));
  ok(() => assert.equal(got.status, 'ok', JSON.stringify(got)));
  ok(() => assert.deepEqual(plain(got.pick.map((p) => p.ref)), [data.swaps[1].ref]), 'only a rule swap');
  ok(() => assert.deepEqual(plain(got.dropped), [{ index: 1, reason: 'not_a_candidate' }]));
  ok(() => assert.ok(got.pick[0].checked === true && typeof got.pick[0].why === 'string' && got.pick[0].servings > 0));
  // a planned entry: its own meal, and it is left out of the day
  const entry = await api.request('POST', '/api/log', { date: D, meal: 'lunch', food_id: potato.id, servings: 1, status: 'planned' });
  const byEntry = await api.request('POST', '/api/ai/next-meal', { meal: 'dinner', date: D, mode: 'swap', entry_id: entry.id });
  ok(() => assert.equal(dataOf(sent('ai').at(-1)).meal, 'lunch'), 'the entry\'s meal');
  ok(() => assert.equal(byEntry.status, 'ok'));
  await fails(api.request('POST', '/api/ai/next-meal', { meal: 'dinner', mode: 'swap', entry_id: 987654 }), 404);
  await fails(api.request('POST', '/api/ai/next-meal', { meal: 'dinner', mode: 'swap' }), 400);
  await fails(api.request('POST', '/api/ai/next-meal', { meal: 'dinner', mode: 'swap', entry_id: entry.id, food_id: potato.id }), 400);
  // a low treatment: the rule card, and nothing is asked
  const n = sent('ai').length;
  const low = await api.request('POST', '/api/ai/next-meal', { meal: 'snack', date: D, mode: 'swap', food_id: food(api, GLUCOSE).id, servings: 1 });
  ok(() => assert.deepEqual([low.status, low.ai_called], ['treating_a_low', false]), 'a low treatment is never sent');
  ok(() => assert.equal(low.cards.length, 1), 'the rule card for treating a low');
  const juice = await api.request('POST', '/api/log', { date: D, meal: 'snack', food_id: food(api, 'Orange juice').id, servings: 1, status: 'eaten', purpose: 'hypo' });
  const low2 = await api.request('POST', '/api/ai/next-meal', { meal: 'snack', date: D, mode: 'swap', entry_id: juice.id });
  ok(() => assert.equal(low2.status, 'treating_a_low'), 'an entry that treated a low is never sent either');
  ok(() => assert.equal(sent('ai').length, n), 'the model was not asked');
}

// 3. AI day plans: one option per meal, the plan rebuilt and checked by the rules.
{
  const { api, sent } = await page();
  const got = await api.request('POST', '/api/ai/next-meal', { meal: 'breakfast', date: D, mode: 'plan' });
  const req = sent('ai').at(-1);
  const data = dataOf(req);
  ok(() => assert.equal(req.task, 'plan'));
  ok(() => assert.ok(Object.keys(data.plan).length >= 2, JSON.stringify(Object.keys(data.plan))), 'the plan\'s meals and options');
  ok(() => assert.ok(Object.values(data.plan).every((opts) => opts.every((o) => Number.isInteger(o.index) && Array.isArray(o.items)))));
  ok(() => assert.ok(req.text.length <= 5000, `${req.text.length}`));
  ok(() => assert.equal(got.status, 'ok', JSON.stringify(got).slice(0, 400)));
  ok(() => assert.deepEqual(Object.keys(got.ai_picks).sort(), Object.keys(data.plan).slice(0, 3).sort()), 'one pick per meal of the plan');
  ok(() => assert.deepEqual(plain(got.dropped), [{ index: Math.min(3, Object.keys(data.plan).length), reason: 'not_a_candidate' }]), 'an option that is not there');
  ok(() => assert.equal(got.plan.status, 'ok'), 'the rules rebuilt the day');
  ok(() => assert.ok(Array.isArray(got.plan.meals) && got.plan.meals.length > 0));
}

// 4. A wrong shape and a refusal: the server's errors, with the rule result instead.
{
  const { api, state } = await page({ model: () => ({ answer: { order: [{ ref: 7, reason_codes: ['low_sodium'] }], status: 'ok', refusal: 'none' } }) });
  let got = await api.request('POST', '/api/ai/next-meal', { meal: 'dinner', date: D, mode: 'rerank' });
  ok(() => assert.deepEqual([got.status, got.reason], ['error', 'schema']), 'a number for a ref');
  ok(() => assert.ok(got.fallback && got.fallback.foods.length > 0));
  state.model = () => ({ answer: { picks: [{ meal: 'lunch', index: '1', reason_codes: ['low_sodium'] }], status: 'ok', refusal: 'none' } });
  got = await api.request('POST', '/api/ai/next-meal', { meal: 'breakfast', date: D, mode: 'plan' });
  ok(() => assert.deepEqual([got.status, got.reason], ['error', 'schema']), 'a text index');
  state.model = () => ({ answer: { pick: [], status: 'refused', refusal: 'outside_scope' } });
  got = await api.request('POST', '/api/ai/next-meal', { meal: 'dinner', date: D, mode: 'swap', food_id: food(api, POTATO).id, servings: 1 });
  ok(() => assert.equal(got.status, 'refused'));
}

// 5. The own key: the three tasks with the person's condition and no ids, after consent; before the iPhone's model.
{
  const { api, sent, state } = await page({ own: OPENAI, provider: (req) => ({ content: JSON.stringify(answerFor(req)) }) });
  await fails(api.request('POST', '/api/ai/next-meal', { meal: 'dinner', date: D, mode: 'rerank' }), 409, (e) => e.extra.consent.host === 'api.openai.com');
  ok(() => assert.equal(sent('ownAI').length, 0), 'nothing sent before the person agrees');
  await api.request('POST', '/api/ai/consent', { provider_id: -1, purpose: 'text', skip_preview: true });
  for (const [mode, extra] of [['rerank', {}], ['swap', { food_id: food(api, POTATO).id, servings: 1 }], ['plan', {}]]) {
    const got = await api.request('POST', '/api/ai/next-meal', { meal: mode === 'plan' ? 'breakfast' : 'dinner', date: D, mode, ...extra });
    const req = sent('ownAI').at(-1);
    ok(() => assert.equal(req.task, mode), `the ${mode} task`);
    ok(() => assert.deepEqual(state.ownKeys, ['condition', 'kind', 'task', 'text']), `${mode}: a condition, no ids`);
    ok(() => assert.equal(req.condition, 'chronic kidney disease (CKD, stage 4) and type 1 diabetes'));
    ok(() => assert.equal(got.provider.label, 'OpenAI (your own key)'));
    ok(() => assert.equal(got.status, 'ok'), `${mode} checked`);
  }
  ok(() => assert.equal(sent('ai').length, 0), 'the own key went first');
  const st = await api.request('GET', '/api/ai/status');
  ok(() => assert.deepEqual(plain(st.swap_plan), { available: true, label: 'OpenAI (your own key)', stays: false }), 'swaps and plans: the own key');
  const bodies = sent('ownAI').map((r) => JSON.stringify(r).toLowerCase());
  for (const needle of ['robin', 'quillfeather', '1971']) ok(() => assert.ok(bodies.every((b) => !b.includes(needle))), `no "${needle}" to the own key`);
}

// 6. With a paired server: AI order goes to the server first and its rows are found here by name; swaps and day plans stay on
// this phone; with no AI on the phone they say why.
{
  const statusOn = { enabled: true, opted_in: true, available: true, reason: null, message: null, provider: { label: 'Home AI', host: 'ai.home.lan' },
    consent: { text: { host: 'ai.home.lan', skip_preview: true } }, routing: { mode: 'routed' },
    routes: { meal_ideas: { feature: 'meal_ideas', available: true, route: 'local' } }, features: { next_meal: true } };
  const about = { account: 'acct-1', api_version: 1, features: { sync: false, ai: { enabled: true } } };
  const gw = { 'GET /push/v1/about': about, 'GET /push/v1/api/ai/status': statusOn, 'POST /push/v1/api/ai/next-meal': null };
  const P = await page({ gw, iphone: true });
  const rice = food(P.api, 'Rice, white, long-grain, cooked');
  gw['POST /push/v1/api/ai/next-meal'] = { status: 'ok', feature: 'next_meal', mode: 'rerank', provider: { label: 'Home AI' },
    order: [{ ref: 'f1', food_id: 900001, name: rice.name, ai_rank: 1, reason_codes: ['low_potassium'], why: 'Low in potassium.' },
      { ref: 'f2', food_id: 900002, ai_rank: 2, reason_codes: ['low_sodium'], why: 'x' }],
    rest: [{ ref: 'f3', food_id: 900003, name: 'Not a food here at all' }], dropped: [] };
  await P.KH.mock.serverApi.check();
  const got = await P.api.request('POST', '/api/ai/next-meal', { meal: 'dinner', date: D, mode: 'rerank' });
  ok(() => assert.equal(P.gateway('/push/v1/api/ai/next-meal').length, 1), 'AI order asked the server');
  ok(() => assert.deepEqual(plain(got.order.map((o) => o.food_id)), [rice.id]), 'found here by name; a row without one is left out');
  ok(() => assert.deepEqual(plain(got.rest), []), 'a food this phone does not have is left out');
  ok(() => assert.ok(got.dropped.some((d) => d.reason === 'not_on_this_iphone')));
  const n = P.gateway('/push/v1/api/ai/next-meal').length;
  const swap = await P.api.request('POST', '/api/ai/next-meal', { meal: 'dinner', date: D, mode: 'swap', food_id: food(P.api, POTATO).id, servings: 1 });
  const plan = await P.api.request('POST', '/api/ai/next-meal', { meal: 'breakfast', date: D, mode: 'plan' });
  ok(() => assert.equal(P.gateway('/push/v1/api/ai/next-meal').length, n), 'swaps and day plans are not sent to the server');
  ok(() => assert.deepEqual([swap.provider.label, plan.provider.label], ['Apple\'s on-device model', 'Apple\'s on-device model']));
  P.state.iphone = false;
  const st = await P.api.request('GET', '/api/ai/status');
  ok(() => assert.deepEqual([st.features.next_meal, st.swap_plan.available], [true, false]), 'the server\'s AI, but no swaps or plans here');
  await fails(P.api.request('POST', '/api/ai/next-meal', { meal: 'breakfast', date: D, mode: 'plan' }), 503,
    (e) => e.extra.reason === 'not_on_server' && /own AI key or Apple/.test(e.detail));
}

// 7. The "AI order" bar: What fits says the phone's AI is there, and names it.
{
  const { api } = await page();
  const res = await api.request('GET', `/api/guidance/next-meal?meal=dinner&date=${D}`);
  ok(() => assert.deepEqual(plain(res.ai), { available: true, provider_label: 'Apple\'s on-device model' }), 'the iPhone\'s model');
  const none = await page({ iphone: false });
  const off = await none.api.request('GET', `/api/guidance/next-meal?meal=dinner&date=${D}`);
  ok(() => assert.deepEqual(plain(off.ai), { available: false, provider_label: null }), 'no AI here');
}

console.log(`phone AI more 2: ${checks} checks passed`);
process.exit(0);
