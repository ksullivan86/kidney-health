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

console.log(`phone AI more: ${checks} checks passed`);
process.exit(0);
