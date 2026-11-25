#!/usr/bin/env node
// Device mode with a server: Ask (the chat) and photos of a meal on the iPhone app (js/mock/ai.js, design note 39). A stand-in for
// the iPhone app answers the bridge with a fake of the server's gateway, as in server_services.mjs. Checks: why Ask or a photo of a
// meal cannot run (GET /api/me/ai → phone.ask, phone.photos) for each kind of pairing; that Ask runs only on the server's AI with
// two-way sync; that the phone always sends trust "ask", so the server saves nothing; that a card's foods become the phone's and
// its Save goes through the phone's own routes once, with the server's client_id; that a card naming a food the phone does not have
// becomes a question; that the server's low and emergency answers pass untouched; that an older server's own save loses Undo and
// asks for a sync; that consent and an unreachable server are the server's answers; and that voice stays off. pytest runs it
// (tests/test_server_ask_phone.py). Exits 1 on any mismatch.
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

const ROUTES = ['photos', 'meal_ideas', 'describe', 'chat', 'labs', 'recipes'];
const serverStatus = (on, extra = {}) => ({
  enabled: true, opted_in: true, available: true, reason: null, message: null, provider: { label: 'Home AI', host: 'ai.home.lan' },
  consent: { text: null, photos: null, chat: { host: 'ai.home.lan', skip_preview: true }, labs: null, voice: null },
  routing: { mode: 'routed' }, policy_version: 'p1', daily_limit: 30, remaining_today: 29,
  routes: Object.fromEntries(ROUTES.map((f) => [f, { feature: f, available: on.includes(f), route: 'local', text: 'Runs on your local AI (ai.home.lan).',
    consent: { host: 'ai.home.lan', skip_preview: true } }])),
  features: { next_meal: false, parse_meal: false, label: on.includes('photos'), plate: on.includes('photos'), chat: on.includes('chat'),
    voice: on.includes('chat'), lab_report: false, lab_report_text: false, recipes: false, recipe_steps: false },
  trust: { setting: 'always', allowed: true, effective: 'always' }, ...extra,
});
const ABOUT = { account: 'acct-1', api_version: 1, sync: { gateway: true, changes: true }, features: { ai: { enabled: true } } };

async function page({ paired = true, gw = {}, synced = true } = {}) {
  const db = createFakeIndexedDB();
  const KH = loadDemo({ navigator: { userAgent: 'node', onLine: true, storage: {} }, globals: { KDL_PREVIEW: true, KDL_DEVICE: true } });
  KH.mock.instance = new KH.mock.MockApi({ foodsData: JSON.parse(FOODS), seed: false });
  const api = KH.mock.instance;
  KH.mock.local._useIndexedDB(db.page(new KH.constructor.constructor(`return ${CLONE_SRC}`)()));
  await KH.mock.local.boot();
  if (synced) api._serverChanges = { ...KH.mock.serverChanges._blank(), account: 'acct-1', host: 'food.example.org', first: true, meals: true };
  const global = new KH.constructor.constructor('return globalThis')();
  const log = [];
  global.webkit = { messageHandlers: { bridge: { postMessage: async (req) => {
    log.push(plain(req));
    if (req.kind === 'serverInfo') return paired ? { ok: true, paired: true, server: 'food.example.org' } : { ok: true, paired: false };
    if (req.kind === 'serverApi') {
      if (!paired) return { error: 'not_paired' };
      let a = gw[`${req.method} ${req.path.split('?')[0]}`];
      if (typeof a === 'function') a = a(req);
      if (a === undefined) return { ok: true, status: 404, json: '{"detail":"Not Found"}' };
      if (a === 'offline') return { error: 'offline' };
      return { ok: true, status: a.http || 200, json: JSON.stringify(a.http ? a.json : a) };
    }
    if (req.kind === 'aiStatus') return { ok: true, available: false, reason: 'not_eligible' }; // this iPhone has no AI of its own
    if (req.kind === 'ai') throw new Error('the iPhone\'s model must not be asked');
    return { error: 'bad_request' };
  } } } };
  const gateway = (path) => log.filter((r) => r.kind === 'serverApi' && r.path.split('?')[0] === path);
  return { KH, api, log, gateway };
}
const chat = (api, text = 'Log an apple for lunch', q = '') => api.request('POST', `/api/ai/chat${q}`,
  { messages: [{ role: 'user', text }], request_id: 'ask-0123456789abcdef01234567' });
const reason = async (api) => { const me = await api.request('GET', '/api/me/ai'); return [me.phone.ask, me.phone.photos]; };

// 1. Why Ask and a photo of a meal cannot run, for each kind of pairing.
{
  const none = await page({ paired: false });
  const [askNone, photoNone] = await reason(none.api);
  ok(() => assert.deepEqual([askNone, photoNone], ['not_paired', 'not_paired']), 'not paired');
  await fails(chat(none.api), 503, (e) => /not available/.test(e.message || e.detail || ''));
  ok(() => assert.equal(none.gateway('/push/v1/api/ai/chat').length, 0), 'not paired: nothing is sent');

  const addOnly = await page({ gw: { 'GET /push/v1/about': { http: 401, json: { detail: 'Not authenticated' } } } });
  const r2 = await reason(addOnly.api);
  ok(() => assert.deepEqual(r2, ['not_both_ways', 'not_both_ways']), 'a token that only adds rows');

  const offline = await page({ gw: { 'GET /push/v1/about': 'offline' } });
  const rOff = await reason(offline.api);
  ok(() => assert.deepEqual(rOff, ['offline', 'offline']), 'a server that could not be reached');

  const status = { cur: serverStatus(['photos', 'chat']) };
  const gw = { 'GET /push/v1/about': ABOUT, 'GET /push/v1/api/ai/status': () => status.cur };
  const noFeed = await page({ gw, synced: false });
  noFeed.api._serverChanges = { ...noFeed.KH.mock.serverChanges._blank(), account: 'another-account' }; // a different account waits
  const r3 = await reason(noFeed.api);
  ok(() => assert.deepEqual(r3, ['not_synced', null]), 'Ask waits for two-way sync; photos do not need it');
  const st3 = await noFeed.api.request('GET', '/api/ai/status');
  ok(() => assert.deepEqual([st3.features.chat, st3.features.plate], [false, true]), 'not in step: no Ask, but the plate photo');

  const synced = await page({ gw });
  const r4 = await reason(synced.api);
  ok(() => assert.deepEqual(r4, [null, null]), 'both ways, in step, the server offers both');
  status.cur = serverStatus([]);
  synced.KH.mock.aiDevice.forgetServer();
  const r5 = await reason(synced.api);
  ok(() => assert.deepEqual(r5, ['server_off', 'server_off']), 'the server has both off');
  status.cur = serverStatus(['chat', 'photos'], { opted_in: false, available: false, reason: 'not_opted_in' });
  const r6 = await reason(synced.api);
  ok(() => assert.deepEqual(r6, ['not_opted_in', 'not_opted_in']), 'AI features off for the person on the server');
  status.cur = serverStatus(['chat', 'photos']);
  await synced.api.request('PUT', '/api/device/ai-choice', { device_only: true });
  const r7 = await reason(synced.api);
  ok(() => assert.deepEqual(r7, ['device_only', 'device_only']), 'only this iPhone\'s AI');
  await fails(chat(synced.api), 503);
  ok(() => assert.equal(synced.gateway('/push/v1/api/ai/chat').length, 0), 'only this iPhone\'s AI: nothing is sent');
}

// 2. Ask through the server: trust "ask", the card named by the phone's ids, Save through the phone's routes once.
{
  const reply = { cur: null };
  const gw = { 'GET /push/v1/about': ABOUT, 'GET /push/v1/api/ai/status': () => serverStatus(['chat', 'photos']),
    'POST /push/v1/api/ai/chat': () => reply.cur };
  const { KH, api, gateway } = await page({ gw });
  const st = await api.request('GET', '/api/ai/status');
  ok(() => assert.deepEqual([st.features.chat, st.features.voice, st.trust.effective, st.trust.allowed, st.routes.chat.runs_on_phone],
    [true, false, 'ask', false, 'server']), 'Ask on, voice off, always asks before saving');
  const apple = api._foods.find((f) => f.source === 'builtin' && f.name === 'Apple, raw, with skin');
  const cid = '8c9d2f0e-8b1a-5c3e-9f00-0a1b2c3d4e5f';
  const card = { tool: 'log_food', date: D, meal: 'lunch', status: 'eaten', purpose: null, imports: [],
    items: [{ name: apple.name, brand: null, as_asked: '1 medium', servings: 1, grams: null, food_id: 4242, fdc_id: null, new_food: false, counted_as_treating_a_low: false }],
    numbers: [{ title: 'This adds', rows: [] }],
    payload: { entries: [{ date: D, meal: 'lunch', food_id: 4242, status: 'eaten', client_id: cid, servings: 1 }] } };
  reply.cur = { kind: 'confirm_save', text: 'Here is what I would log.', cards: [], numbers: [], notes: [], trust: 'ask', pending_save: card, saved: [], questions: [] };
  const got = await chat(api);
  const sent = JSON.parse(gateway('/push/v1/api/ai/chat')[0].body);
  ok(() => assert.equal(sent.trust, 'ask'), 'the phone always asks the server for trust "ask"');
  ok(() => assert.deepEqual(Object.keys(sent).sort(), ['messages', 'request_id', 'trust']), 'nothing else is sent');
  ok(() => assert.deepEqual([got.pending_save.items[0].food_id, got.pending_save.payload.entries[0].food_id], [apple.id, apple.id]),
    'the card names the phone\'s food');
  ok(() => assert.equal(got.pending_save.payload.entries[0].client_id, cid), 'the server\'s client_id is kept');
  // Save as eaten: the page posts the card's entries to the phone's own route (js/views/ask.js postCard), twice by mistake
  const entries = got.pending_save.payload.entries.map((e) => ({ ...e, status: 'eaten' }));
  await api.request('POST', '/api/log/batch', { entries });
  await api.request('POST', '/api/log/batch', { entries });
  const rows = api._entries.filter((e) => e.client_id === cid);
  ok(() => assert.equal(rows.length, 1), 'saved once on the phone, with the server\'s client_id (sync sends it up as one row)');
  ok(() => assert.equal(rows[0].food_id, apple.id));
  ok(() => assert.equal(gateway('/push/v1/api/log/batch').length, 0), 'the save did not go to the server\'s log route');

  // a food the phone does not have: a question, nothing to save
  reply.cur = { ...reply.cur, pending_save: { ...card, items: [{ ...card.items[0], name: 'Grandma\'s stew', food_id: 99 }],
    payload: { entries: [{ ...card.payload.entries[0], food_id: 99 }] } } };
  const missing = await chat(api);
  ok(() => assert.equal(missing.pending_save, null), 'no card with another food\'s numbers');
  ok(() => assert.match(missing.questions[0].question, /"Grandma's stew" is not on this iPhone yet/), 'it says why');

  // a new USDA food: its Save imports it first, so the entry keeps no server id
  reply.cur = { ...reply.cur, pending_save: { ...card, imports: [171688], items: [{ ...card.items[0], name: 'Pear, raw', food_id: null, fdc_id: 171688, new_food: true }],
    payload: { entries: [{ ...card.payload.entries[0], food_id: null, fdc_id: 171688 }] } } };
  const usda = await chat(api);
  ok(() => assert.deepEqual([plain(usda.pending_save.imports), usda.pending_save.payload.entries[0].fdc_id, usda.pending_save.payload.entries[0].food_id],
    [[171688], 171688, null]), 'a USDA food is imported on Save');

  // a recipe card
  reply.cur = { ...reply.cur, pending_save: { tool: 'save_recipe', name: 'Apple snack', servings_made: 1, items: [{ ...card.items[0] }], imports: [], numbers: [],
    payload: { name: 'Apple snack', items: [{ food_id: 4242, servings: 1 }], servings_made: 1 } } };
  const recipe = await chat(api);
  ok(() => assert.equal(recipe.pending_save.payload.items[0].food_id, apple.id), 'a recipe card names the phone\'s food');

  // a taste card names the phone's food; a food group names none
  reply.cur = { ...reply.cur, pending_save: { tool: 'set_food_preference', target: { kind: 'food', food_id: 4242, name: apple.name }, preference: 'less', previous: 'none' } };
  const taste = await chat(api);
  ok(() => assert.equal(taste.pending_save.target.food_id, apple.id), 'a taste names the phone\'s food');

  // the server's low and emergency answers pass untouched
  const low = { kind: 'treat_low', text: 'This looks like a low.', cards: [{ title: 'Treating a low', lines: ['Take 15 g of fast sugar now.'] }], numbers: [], notes: [], trust: null, pending_save: null, saved: [], questions: [] };
  reply.cur = low;
  const gotLow = await chat(api, 'my sugar is 55');
  ok(() => assert.deepEqual(plain(gotLow), low), 'a low card is shown as the server gave it');

  // an older server that saved at once: no Undo here (its ids are the server's), and a sync is asked for
  let soon = 0;
  const realSoon = KH.mock.serverSync.soon;
  KH.mock.serverSync.soon = () => { soon += 1; };
  reply.cur = { kind: 'answer', text: 'Logged.', cards: [], numbers: [], notes: [], trust: 'always', pending_save: null, questions: [],
    saved: [{ tool: 'log_food', date: D, meal: 'lunch', status: 'eaten', items: [{ name: apple.name, servings: 1, grams: null }], undo: { entry_ids: [55] }, numbers: [] }] };
  const saved = await chat(api);
  KH.mock.serverSync.soon = realSoon;
  ok(() => assert.deepEqual([saved.saved[0].undo, saved.saved[0].on_server, soon], [null, true, 1]), 'saved on the server: no Undo, a sync follows');

  // consent and limits are the server's answers; an unreachable server says so
  reply.cur = { http: 409, json: { detail: 'Agree first.', consent_required: true, consent: { host: 'ai.home.lan' } } };
  await fails(chat(api), 409, (e) => e.extra.consent_required === true);
  reply.cur = 'offline';
  await fails(chat(api), 503, (e) => /could not be reached/.test(e.message || e.detail || ''));
  // the dry run ("What will be sent?") is the server's
  KH.mock.aiDevice.forgetServer(); KH.mock.serverApi.forget(); // the server is back
  reply.cur = { dry_run: true, feature: 'chat', host: 'ai.home.lan' };
  const dry = await chat(api, 'hi', '?dry_run=true');
  ok(() => assert.equal(dry.dry_run, true));
  ok(() => assert.match(gateway('/push/v1/api/ai/chat').at(-1).path, /\?dry_run=true$/), 'the dry run asks the server');
}

console.log(`server ask: ${checks} checks passed`);
process.exit(0);
