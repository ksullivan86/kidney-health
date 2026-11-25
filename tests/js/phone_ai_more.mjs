#!/usr/bin/env node
// More on the iPhone's own AI (the owner, 2026-11-25; design note 39 §6.6; js/mock/ai.js). A stand-in for the iPhone app answers the
// bridge like the app would: aiStatus (with or without photos, iOS 27), ai (the iPhone's own model, answers set per test), ownAI
// (the person's own key, with a stand-in provider). No server is paired. Checks: plate and label photos on the iPhone's model with
// the server's checks; the order with the own key; meal ideas and AI recipes on both, with the server's guard (js/engine/aimeal.js);
// the candidate trimming for the iPhone's small model; never a dosing task; never the name or birth month to the own key.
// pytest (tests/test_phone_ai_more.py) runs it. Exits 1 on any mismatch.
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
const OWN_TASKS = ['parse_meal', 'read_label', 'plate', 'next_meal', 'recipes'];
const PHONE_TASKS = ['parse_meal', 'read_lab_report_text', 'next_meal', 'recipes', 'read_label', 'plate'];

// The stand-in app. `iphone`: false, or { photos } (the model runs; photos only on iOS 27). `model(req)` answers { answer } or
// { error } for the iPhone's model; `provider(req)` answers { content } or { error } for the own key.
async function page({ own = null, iphone = { photos: true }, model = null, provider = null } = {}) {
  const db = createFakeIndexedDB();
  const KH = loadDemo({ navigator: { userAgent: 'node', onLine: true, storage: {} }, globals: { KDL_PREVIEW: true, KDL_DEVICE: true } });
  KH.mock.instance = new KH.mock.MockApi({ foodsData: JSON.parse(FOODS), seed: false });
  const api = KH.mock.instance;
  KH.mock.local._useIndexedDB(db.page(new KH.constructor.constructor(`return ${CLONE_SRC}`)()));
  await KH.mock.local.boot();
  Object.assign(api._profile, { name: NAME, birth_month: BIRTH });
  const global = new KH.constructor.constructor('return globalThis')();
  const log = [];
  const state = { own: own ? { ...own } : null, iphone, model, provider };
  global.webkit = { messageHandlers: { bridge: { postMessage: async (req) => {
    log.push(plain(req));
    if (req.kind === 'serverInfo') return { ok: true, paired: false };
    if (req.kind === 'serverApi') return { error: 'not_paired' };
    if (req.kind === 'ownAIStatus') return state.own || { ok: true, set: false };
    if (req.kind === 'ownAI') { // as OwnAI.swift
      if (!OWN_TASKS.includes(req.task)) return { error: 'bad_request', message: 'x' };
      if (!state.own) return { error: 'own_off', message: 'x' };
      if (['read_label', 'plate'].includes(req.task) && !state.own.photos) return { error: 'photos_off', message: 'x' };
      const r = state.provider ? state.provider(req) : { error: 'offline' };
      if (r.error) return { error: r.error, message: `provider: ${r.error}` };
      return { ok: true, content: r.content == null ? '' : r.content, refusal: r.refusal || null, finish: 'stop' };
    }
    if (req.kind === 'aiStatus') {
      return state.iphone ? { ok: true, available: true, reason: null, photos: !!state.iphone.photos } : { ok: true, available: false, reason: 'not_eligible', photos: false };
    }
    if (req.kind === 'ai') { // as OnDeviceAI.swift
      if (!PHONE_TASKS.includes(req.task)) return { error: 'bad_request', message: 'x' };
      if (['read_label', 'plate'].includes(req.task) && !(state.iphone && state.iphone.photos)) return { error: 'photos_unavailable', message: 'x' };
      const r = state.model ? state.model(req) : { error: 'ai_failed' };
      if (r.error) return { error: r.error, message: 'x' };
      return { ok: true, answer: r.answer };
    }
    if (req.kind === 'services') return { ok: true, usda: false, off: false, scan: false };
    return { error: 'bad_request' };
  } } } };
  const sent = (kind) => log.filter((r) => r.kind === kind);
  await api.request('PATCH', '/api/me/ai', { opt_in: true });
  return { KH, api, log, state, sent };
}
const photo = () => new Blob([new Uint8Array([0xff, 0xd8, 0xff, 0xe0, 1, 2, 3])], { type: 'image/jpeg' });
const LABEL = { status: 'ok', product_name: 'Crackers', serving_text: '5 crackers (30 g)', serving_g: 30, basis: 'per_serving',
  per_serving: { calories_kcal: 130, protein_g: 2, fat_g: 4.5, sat_fat_g: null, carbs_g: 21, fiber_g: null, sugar_g: null, sodium_mg: 210,
    potassium_mg: null, phosphorus_mg: null, calcium_mg: null }, salt_g: null,
  percent_dv: { sodium: null, potassium: null, phosphorus: null, calcium: null }, ingredients_text: 'Flour, sodium phosphate', label_style: 'us_nutrition_facts' };
const PLATE = { status: 'ok', items: [{ name: 'Rice', search: 'rice', grams_estimate: 150, confidence: 'medium' },
  { name: 'insulin pen', search: 'pen', grams_estimate: 10, confidence: 'high' }] };
const photoModel = (req) => ({ answer: req.task === 'plate' ? PLATE : req.task === 'read_label' ? LABEL : { status: 'ok', items: [] } });

// 1. Plate and label photos on the iPhone's own model (iOS 27): no server, no own key. The photo stays on the phone.
{
  const { api, sent } = await page({ model: photoModel });
  const me = await api.request('GET', '/api/me/ai');
  ok(() => assert.equal(me.phone.where.photos, 'iphone'), 'photos run on this iPhone');
  const st = await api.request('GET', '/api/ai/status');
  ok(() => assert.deepEqual([st.features.plate, st.features.label, st.features.lab_report], [true, true, false]), 'plate and label, never a lab photo');
  ok(() => assert.equal(st.consent.photos.host, 'this iPhone'), 'nothing to agree to: it does not leave the phone');
  const plate = await api.request('POST', '/api/vision/plate', photo());
  ok(() => assert.equal(plate.provider.label, 'Apple\'s on-device model'));
  ok(() => assert.deepEqual(plain(plate.items.map((i) => i.name)), ['Rice']), 'the server\'s blocklist dropped the insulin pen');
  ok(() => assert.equal(plate.items[0].portion_text, 'about 150 g'));
  ok(() => assert.ok(plate.items[0].candidates.length > 0), 'matched to the phone\'s foods');
  ok(() => assert.match(plate.banner, /do not dose insulin from this alone/));
  ok(() => assert.equal(plate.audit_id, null), 'nothing kept');
  const req = sent('ai').at(-1);
  ok(() => assert.deepEqual(Object.keys(req).sort(), ['jpeg', 'kind', 'task']), 'a task and the JPEG only');
  ok(() => assert.equal(req.jpeg, '/9j/4AECAw=='));
  const label = await api.request('POST', '/api/vision/label', photo());
  ok(() => assert.deepEqual([label.status, label.draft.name, label.draft.serving_g], ['ok', 'Crackers', 30]), 'the label draft');
  ok(() => assert.ok(label.checks.some((c) => c.code === 'potassium_unknown') && label.checks.some((c) => c.code === 'additive:phosphate')));
  await fails(api.request('POST', '/api/ai/read-lab-report', photo()), 404);
  ok(() => assert.ok(sent('ai').every((r) => r.task !== 'lab_report')), 'a lab report photo is not read here');
  const before = sent('ai').length;
  const dry = await api.request('POST', '/api/vision/plate?dry_run=true', photo());
  ok(() => assert.deepEqual([dry.dry_run, dry.provider.local, dry.image_bytes], [true, true, 7]), 'the dry run');
  ok(() => assert.equal(sent('ai').length, before), 'the dry run sends nothing');
}

// 2. Malformed answers and failures from the iPhone's model are the server's errors, never shown raw.
{
  const { api, state } = await page();
  state.model = () => ({ answer: { status: 'ok', items: 'rice' } });
  let got = await api.request('POST', '/api/vision/plate', photo());
  ok(() => assert.deepEqual([got.status, got.reason], ['error', 'schema']), 'the wrong shape');
  state.model = () => ({ error: 'ai_failed' });
  got = await api.request('POST', '/api/vision/plate', photo());
  ok(() => assert.deepEqual([got.status, got.reason], ['error', 'ai_failed']));
  state.model = () => ({ answer: { status: 'no_food', items: [] } });
  got = await api.request('POST', '/api/vision/plate', photo());
  ok(() => assert.equal(got.status, 'no_food'));
}

// 3. Before iOS 27 (no photos on the model): no photo features, the photo line says why; describe a meal still runs here.
{
  const { api } = await page({ iphone: { photos: false }, model: photoModel });
  const st = await api.request('GET', '/api/ai/status');
  ok(() => assert.deepEqual([st.features.plate, st.features.label, st.features.parse_meal], [false, false, true]));
  await fails(api.request('POST', '/api/vision/plate', photo()), 404);
  const me = await api.request('GET', '/api/me/ai');
  ok(() => assert.equal(me.phone.where.photos, null));
}

// 4. The order with the own key: its photo switch on, it goes first; when it cannot be reached, the iPhone's model reads the photo.
{
  const { api, state, sent } = await page({ own: { ...OPENAI, photos: true }, model: photoModel,
    provider: () => ({ content: JSON.stringify({ status: 'ok', items: [{ name: 'Pasta', search: 'pasta', grams_estimate: 200, confidence: 'high' }] }) }) });
  await api.request('POST', '/api/ai/consent', { provider_id: -1, purpose: 'photos', skip_preview: true });
  let got = await api.request('POST', '/api/vision/plate', photo());
  ok(() => assert.equal(got.provider.label, 'OpenAI (your own key)'), 'the own key first');
  state.provider = () => ({ error: 'offline' });
  got = await api.request('POST', '/api/vision/plate', photo());
  ok(() => assert.equal(got.provider.label, 'Apple\'s on-device model'), 'then this iPhone');
  state.iphone = { photos: false };
  await fails(api.request('POST', '/api/vision/plate', photo()), 503, (e) => e.extra.reason === 'own_unreachable');
  ok(() => assert.ok(sent('ownAI').every((r) => r.task !== 'read_lab_report_text')));
}

// Meal ideas and AI recipes (step 2). The stand-in models answer with the ids they were given, plus one made-up id.
const TARGETS = { potassium_mg: { max: 3000 }, phosphorus_mg: { max: 1000 }, sodium_mg: { max: 2000 }, carbs_per_meal_g: 60, protein_g: 60,
  fluid_ml: { max: 1500 } };
const candidatesOf = (req) => JSON.parse(req.text).candidates;
const ideasFrom = (req) => {
  const c = candidatesOf(req);
  return { ideas: [{ theme: 'hearty', items: [{ food_id: c[0].id, quarters: 4 }, { food_id: c[1].id, quarters: 2 }], reason_codes: ['you_like', 'low_sodium'],
    handbook: ['potassium', 'http://x'] }, { theme: 'light', items: [{ food_id: 987654321, quarters: 4 }], reason_codes: ['low_sodium'], handbook: [] }],
  status: 'ok', refusal: 'none' };
};
const recipesFrom = (req) => {
  const c = candidatesOf(req).filter((f) => !f.flags.includes('processed'));
  return { recipes: [{ dish: 'stew', theme: 'hearty', ingredients: [{ food_id: c[0].id, quarters: 4 }, { food_id: c[1].id, quarters: 4 }, { food_id: c[2].id, quarters: 4 }],
    steps: ['Simmer for 20 minutes.'], reason_codes: ['adds_protein'] }], status: 'ok', refusal: 'none' };
};
const mealModel = (req) => ({ answer: req.task === 'next_meal' ? ideasFrom(req) : req.task === 'recipes' ? recipesFrom(req) : photoModel(req).answer });
const ideasBody = { meal: 'dinner', mode: 'ideas' };
async function withTargets(opts) {
  const P = await page(opts);
  Object.assign(P.api._profile, { targets: TARGETS, ckd_stage: '4', diabetes: 'type1', ckd_stage_chosen: true, diabetes_chosen: true });
  return P;
}

// 5. Meal ideas and recipes on the iPhone's own model: the server's candidates, trimmed to fit its small window, and its checks.
{
  const { api, sent, KH } = await withTargets({ model: mealModel });
  const st = await api.request('GET', '/api/ai/status');
  ok(() => assert.deepEqual([st.features.next_meal, st.features.recipes, st.features.recipe_steps], [true, true, false]), 'meal ideas and recipes, no AI steps');
  const me = await api.request('GET', '/api/me/ai');
  ok(() => assert.deepEqual([me.phone.where.meal_ideas, me.phone.where.recipes], ['iphone', 'iphone']));
  const got = await api.request('POST', '/api/ai/next-meal', ideasBody);
  const req = sent('ai').at(-1);
  ok(() => assert.equal(req.task, 'next_meal'));
  ok(() => assert.ok(req.text.length <= 5000, `${req.text.length} characters`), 'the data block fits the iPhone model');
  ok(() => assert.ok(got.trimmed > 0, 'candidates were trimmed'), 'trimmed, as the server trims');
  ok(() => assert.equal(req.condition, 'chronic kidney disease (CKD, stage 4) and type 1 diabetes'), 'one of the server\'s wordings');
  ok(() => assert.deepEqual(Object.keys(req).sort(), ['condition', 'kind', 'task', 'text']));
  ok(() => assert.equal(got.provider.label, 'Apple\'s on-device model'));
  ok(() => assert.equal(got.status, 'ok'));
  ok(() => assert.equal(got.ideas.length, 1), 'the made-up food is dropped');
  ok(() => assert.deepEqual(plain(got.dropped), [{ index: 1, reason: 'not_a_candidate' }]));
  ok(() => assert.ok(!got.ideas[0].reason_codes.includes('you_like')), 'a false "you like" claim is removed');
  ok(() => assert.deepEqual(plain(got.ideas[0].handbook.map((p) => p.slug)), ['potassium']), 'only allowed handbook pages');
  ok(() => assert.equal(got.ideas[0].checked, true));
  ok(() => assert.equal(got.audit_id, null), 'nothing kept');
  const data = JSON.parse(req.text);
  ok(() => assert.deepEqual(Object.keys(data).sort(), ['candidates', 'handbook_pages', 'judged', 'meal', 'meal_budget', 'meals_left', 'person', 'repeat_ok',
    'saved_meals', 'targets', 'today', 'week_avg']), 'the server\'s data block');
  ok(() => assert.equal(data.person.age_band, null), 'no age without consent');
  ok(() => assert.ok(!req.text.toLowerCase().includes('robin')), 'never the name');
  for (const mode of ['rerank', 'swap', 'plan']) {
    await fails(api.request('POST', '/api/ai/next-meal', { meal: 'dinner', mode, food_id: 1, servings: 1 }), 503, (e) => e.extra.reason === 'not_on_phone');
  }
  const recipe = await api.request('POST', '/api/ai/recipes', { mode: 'suggest', dish: 'stew', makes: 4, meal: 'dinner' });
  const rreq = sent('ai').at(-1);
  ok(() => assert.equal(rreq.task, 'recipes'));
  ok(() => assert.ok(rreq.text.length <= 5000));
  ok(() => assert.equal(recipe.feature, 'recipes'));
  ok(() => assert.equal(recipe.status, 'ok', JSON.stringify(recipe.dropped)), 'a checked recipe');
  if (recipe.status === 'ok') {
    ok(() => assert.deepEqual(plain(recipe.recipes[0].steps), []), 'never AI steps on the phone');
    ok(() => assert.equal(recipe.recipes[0].body.steps.length, 0));
    ok(() => assert.equal(recipe.steps_dropped, 1));
  }
  ok(() => assert.deepEqual(plain(recipe.notes), [...KH.guidanceEngine.M.RECIPE_NOTES, KH.guidanceEngine.M.DISCLAIMER]));
  const before = sent('ai').length;
  const dry = await api.request('POST', '/api/ai/next-meal?dry_run=true', ideasBody);
  ok(() => assert.deepEqual([dry.dry_run, dry.provider.local], [true, true]));
  ok(() => assert.equal(sent('ai').length, before), 'the dry run sends nothing');
  await fails(api.request('POST', '/api/ai/recipes', { mode: 'suggest', makes: 4 }), 400);
}

// 6. A wrong answer and a refusal from the iPhone's model: the server's errors and the rule ideas instead.
{
  const { api, state } = await withTargets({ model: () => ({ answer: { ideas: 'pasta', status: 'ok', refusal: 'none' } }) });
  let got = await api.request('POST', '/api/ai/next-meal', ideasBody);
  ok(() => assert.deepEqual([got.status, got.reason], ['error', 'schema']));
  ok(() => assert.ok(got.fallback && got.fallback.foods.length > 0), 'the app\'s own ideas instead');
  state.model = () => ({ answer: { ideas: [], status: 'refused', refusal: 'outside_scope' } });
  got = await api.request('POST', '/api/ai/next-meal', ideasBody);
  ok(() => assert.equal(got.status, 'refused'));
  state.model = () => ({ error: 'ai_failed' });
  got = await api.request('POST', '/api/ai/next-meal', ideasBody);
  ok(() => assert.deepEqual([got.status, got.reason], ['error', 'ai_failed']));
}

// 7. The own key: meal ideas and recipes with the full candidate list, its ids, the consent first; it goes before the iPhone.
{
  const { api, sent, state } = await withTargets({ own: OPENAI, model: mealModel,
    provider: (req) => ({ content: JSON.stringify(req.task === 'next_meal' ? ideasFrom(req) : recipesFrom(req)) }) });
  const me = await api.request('GET', '/api/me/ai');
  ok(() => assert.deepEqual([me.phone.where.meal_ideas, me.phone.where.recipes], ['own', 'own']));
  await fails(api.request('POST', '/api/ai/next-meal', ideasBody), 409, (e) => e.extra.consent.host === 'api.openai.com');
  ok(() => assert.equal(sent('ownAI').length, 0), 'nothing sent before the person agrees');
  await api.request('POST', '/api/ai/consent', { provider_id: -1, purpose: 'text', skip_preview: true });
  const got = await api.request('POST', '/api/ai/next-meal', ideasBody);
  const req = sent('ownAI').at(-1);
  ok(() => assert.equal(got.provider.label, 'OpenAI (your own key)'));
  ok(() => assert.equal(got.trimmed, 0), 'the cloud budget takes the whole list');
  ok(() => assert.deepEqual(Object.keys(req).sort(), ['condition', 'ids', 'kind', 'task', 'text']));
  const ids = new Set(candidatesOf(req).map((c) => c.id));
  ok(() => assert.ok([...ids].every((id) => req.ids.includes(id)) && req.ids.every((id, i) => i === 0 || req.ids[i - 1] < id)), 'the candidate ids, sorted');
  ok(() => assert.deepEqual([got.status, got.ideas.length], ['ok', 1]));
  const recipe = await api.request('POST', '/api/ai/recipes', { mode: 'suggest', dish: 'stew', makes: 4 });
  ok(() => assert.equal(recipe.provider.label, 'OpenAI (your own key)'));
  ok(() => assert.equal(sent('ownAI').at(-1).task, 'recipes'));
  // the name in the AI preferences text: never to the own key; the iPhone's model takes it (it stays on the phone)
  await api.request('PATCH', '/api/me/ai', { preferences: 'Robin likes soup' });
  const n = sent('ownAI').length;
  const local = await api.request('POST', '/api/ai/next-meal', ideasBody);
  ok(() => assert.equal(local.provider.label, 'Apple\'s on-device model'), 'the iPhone instead');
  ok(() => assert.equal(sent('ownAI').length, n), 'not sent to the own key');
  state.iphone = false;
  await fails(api.request('POST', '/api/ai/next-meal', ideasBody), 503, (e) => e.extra.reason === 'identity');
  await api.request('PATCH', '/api/me/ai', { preferences: 'likes soup' });
  state.provider = () => ({ error: 'offline' });
  await fails(api.request('POST', '/api/ai/next-meal', ideasBody), 503, (e) => e.extra.reason === 'own_unreachable');
  state.iphone = { photos: false };
  const again = await api.request('POST', '/api/ai/next-meal', ideasBody);
  ok(() => assert.equal(again.provider.label, 'Apple\'s on-device model'), 'unreachable provider: the iPhone');
  const bodies = sent('ownAI').map((r) => JSON.stringify(r).toLowerCase());
  for (const needle of ['robin', 'quillfeather', '1971']) ok(() => assert.ok(bodies.every((b) => !b.includes(needle))), `no "${needle}" to the own key`);
}

// 8. No AI on the phone at all: the features stay off and the routes answer as a server with AI off.
{
  const { api } = await withTargets({ iphone: false });
  await fails(api.request('POST', '/api/ai/next-meal', ideasBody), 404);
  await fails(api.request('POST', '/api/ai/recipes', { mode: 'suggest', dish: 'soup' }), 404);
}

console.log(`phone AI more: ${checks} checks passed`);
process.exit(0);
