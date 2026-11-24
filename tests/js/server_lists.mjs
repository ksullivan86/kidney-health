#!/usr/bin/env node
// Device mode with a server, design note 39 step 9: recipe pages, Instacart and the list app are the person's own server's, through
// the iPhone app's serverApi bridge (js/mock/lists.js, server_api.js). A stand-in for the iPhone app answers the bridge with a fake
// of the server's gateway. Checks: with no server both ways (none, or a token that only adds) they are off, as on a server with them
// off, and nothing is asked of a server; with one, each goes through the gateway and only while the server offers it; a recipe
// page's lines are matched with the phone's own foods; the server's food ids are shown as the phone's and sent back as the
// server's; the list app is never set up from the phone; an unreachable server is said plainly; pasted ingredients never leave the
// phone. pytest (tests/test_server_services_phone.py) runs it. Exits 1 on any mismatch.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { loadDemo } from './demo_loader.mjs';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..', '..');
const FOODS = JSON.parse(readFileSync(join(ROOT, 'data', 'foods.json'), 'utf8'));
const D = new Date().toISOString().slice(0, 10);
const plain = (v) => JSON.parse(JSON.stringify(v));
let checks = 0;
const ok = (fn, label) => { checks += 1; try { fn(); } catch (e) { e.message = `${label}: ${e.message}`; throw e; } };
const fails = (promise, code, label, test = () => true) => {
  checks += 1;
  return assert.rejects(promise, (e) => e.status === code && test(e), label);
};

// The stand-in app and the fake gateway, as in server_services.mjs: `gw` maps "METHOD /path" to an answer or a function of the
// request; 'offline' is a server that cannot be reached; { http, json } is an answer with that status; anything else a 200.
function page({ paired = true, gw = {} } = {}) {
  const KH = loadDemo({ navigator: { userAgent: 'node', onLine: true, storage: {} }, globals: { KDL_PREVIEW: true, KDL_DEVICE: true } });
  const api = new KH.mock.MockApi({ foodsData: FOODS, seed: false });
  KH.mock.instance = api;
  const global = new KH.constructor.constructor('return globalThis')();
  const log = [];
  global.webkit = { messageHandlers: { bridge: { postMessage: async (req) => {
    log.push(plain(req));
    if (req.kind === 'serverInfo') return paired ? { ok: true, paired: true, server: 'food.example.org' } : { ok: true, paired: false };
    if (req.kind !== 'serverApi') return { error: 'bad_request' };
    if (!paired) return { error: 'not_paired' };
    let a = gw[`${req.method} ${req.path.split('?')[0]}`];
    if (typeof a === 'function') a = a(req);
    if (a === undefined) return { ok: true, status: 404, json: '{"detail":"This is not open to the iPhone app."}' };
    if (a === 'offline') return { error: 'offline' };
    return { ok: true, status: a.http || 200, json: JSON.stringify(a.http || a.json ? a.json : a) };
  } } } };
  const gateway = (path) => log.filter((r) => r.kind === 'serverApi' && r.path.split('?')[0] === path);
  const asked = () => log.filter((r) => r.kind === 'serverApi' && r.path !== '/push/v1/about');
  return { KH, api, log, gateway, asked };
}
const about = (services) => ({ json: { account: 'acct-1', api_version: 1, features: { usda_search: true, barcode: true }, services } });
const ON = { recipe_import: true, instacart: true, list_sync: true };
const food = (api, q) => api.handle('GET', `/api/foods?q=${encodeURIComponent(q)}`).foods[0];
const plan = (api, f, servings = 1) => api.handle('POST', '/api/log', { date: D, meal: 'lunch', food_id: f.id, servings, status: 'planned' });

// 1. With no server both ways, the three are off, as on a server with them off, and no server is asked.
for (const [label, setup] of [['no server', { paired: false }],
  ['a token that only adds', { gw: { 'GET /push/v1/about': { http: 401, json: { detail: 'Not authenticated' } } } }],
  ['a server without the gateway', { gw: {} }]]) {
  const { api, asked } = page(setup);
  const info = await api.request('GET', '/api/recipe-import');
  ok(() => assert.equal(info.web, false), `${label}: recipe pages are off`);
  await fails(api.request('POST', '/api/recipe-import/page', { url: 'https://recipes.example.com/x' }), 404, `${label}: no page is read`);
  const draft = await api.request('POST', '/api/recipe-import/text', { text: '1 medium banana\n2 cups cooked white rice' });
  ok(() => assert.equal(draft.lines.length, 2), `${label}: pasted ingredients are read on the phone`);
  const instacart = await api.request('GET', '/api/instacart');
  ok(() => assert.equal(instacart.enabled, false), `${label}: Instacart is off`);
  await fails(api.request('POST', '/api/instacart/preview', { start: D, end: D }), 404, `${label}: no Instacart list`);
  await fails(api.request('POST', '/api/instacart/send', { start: D, end: D, food_ids: [1] }), 404, `${label}: nothing sent to Instacart`);
  const lists = await api.request('GET', '/api/list-sync');
  ok(() => assert.deepEqual([lists.enabled, lists.connection], [false, null]), `${label}: no list app`);
  for (const [m, p] of [['POST', '/api/list-sync/preview'], ['POST', '/api/list-sync/send'], ['PUT', '/api/list-sync'], ['DELETE', '/api/list-sync'], ['POST', '/api/list-sync/test']]) {
    await fails(api.request(m, p, { start: D, end: D, food_ids: [1], app: 'grocy', base_url: 'https://x.example', key: 'k' }), 404, `${label}: ${m} ${p}`);
  }
  ok(() => assert.equal(asked().length, 0), `${label}: no server route was asked`);
}

// 2. Recipe pages through the server; its lines matched with the phone's own foods.
{
  const lines = ['1 medium banana', '2 cups cooked white rice', '1 tsp dried thyme'].map((text) => ({ text, amount: null, unit: null, food_text: text,
    matches: [{ food: { id: 9001, name: 'A food of the server', source: 'custom', serving_desc: '1', serving_g: 1, nutrients: {} }, servings: 1 }] }));
  const gw = { 'GET /push/v1/about': about(ON), 'GET /push/v1/api/recipe-import': { web: true, max_lines: 60, estimate: 'x' },
    'POST /push/v1/api/recipe-import/page': (req) => (JSON.parse(req.body).url.includes('blocked')
      ? { http: 422, json: { detail: 'This app does not open pages on a home network or this server\'s own.', code: 'blocked' } }
      : { name: 'Banana rice', servings_made: 2, steps: ['Cook the rice.'], steps_cut: false, lines_cut: false, source_url: JSON.parse(req.body).url,
        lines, notice: 'x', estimate: 'x' }) };
  const { api, gateway, log } = page({ gw });
  const info = await api.request('GET', '/api/recipe-import');
  ok(() => assert.equal(info.web, true), 'the server reads pages');
  const draft = await api.request('POST', '/api/recipe-import/page', { url: 'https://recipes.example.com/banana-rice' });
  ok(() => assert.deepEqual(JSON.parse(gateway('/push/v1/api/recipe-import/page')[0].body), { url: 'https://recipes.example.com/banana-rice' }), 'only the link is sent');
  ok(() => assert.deepEqual(plain([draft.name, draft.servings_made, draft.steps, draft.source_url]), ['Banana rice', 2, ['Cook the rice.'], 'https://recipes.example.com/banana-rice']), 'the page\'s recipe');
  ok(() => assert.deepEqual(plain(draft.lines.map((l) => l.text)), ['1 medium banana', '2 cups cooked white rice', '1 tsp dried thyme']), 'every line');
  const ids = draft.lines.flatMap((l) => l.matches.map((m) => m.food.id));
  ok(() => assert.ok(ids.length && !ids.includes(9001) && ids.every((id) => api._food(id)), 'matched with the phone\'s own foods'));
  ok(() => assert.ok(draft.lines[0].matches[0].food.name.toLowerCase().includes('banana')), 'the banana is a banana');
  await fails(api.request('POST', '/api/recipe-import/page', { url: 'https://blocked.example/x' }), 422, 'the server\'s refusal, in its words',
    (e) => /home network/.test(e.detail) && e.extra && e.extra.code === 'blocked');
  gw['POST /push/v1/api/recipe-import/page'] = 'offline';
  await fails(api.request('POST', '/api/recipe-import/page', { url: 'https://recipes.example.com/x' }), 503, 'an unreachable server is said plainly',
    (e) => /cannot be reached/.test(e.detail));
  const before = log.length;
  await api.request('POST', '/api/recipe-import/text', { text: '1 medium banana' });
  ok(() => assert.equal(log.length, before), 'pasted ingredients never leave the phone');
}

// 3. Instacart through the server: the server's lines shown with the phone's ids, sent back with the server's.
{
  const sentBodies = [];
  const gw = { 'GET /push/v1/about': about(ON), 'GET /push/v1/api/instacart': { enabled: true, max_items: 200 } };
  const { api, gateway } = page({ gw });
  const banana = food(api, 'banana');
  plan(api, banana, 2);
  gw['POST /push/v1/api/instacart/preview'] = { title: 'Shopping list', items: [
    { food_id: 501, name: banana.name, amount: '2 servings', text: `${banana.name}: 2 servings` },
    { food_id: 502, name: 'Planned in the web app only', amount: '1 serving', text: 'Planned in the web app only: 1 serving' }] };
  gw['POST /push/v1/api/instacart/send'] = (req) => { sentBodies.push(JSON.parse(req.body)); return { url: 'https://customers.instacart.com/store/shopping_lists/1', items: 2, error: null, message: null }; };
  const status = await api.request('GET', '/api/instacart');
  ok(() => assert.equal(status.enabled, true), 'on, as the server says');
  const preview = await api.request('POST', '/api/instacart/preview', { start: D, end: D });
  ok(() => assert.deepEqual(plain(preview.items.map((i) => i.food_id)), [banana.id, -2]), 'the phone\'s ids; a line not planned here has none');
  const out = await api.request('POST', '/api/instacart/send', { start: D, end: D, food_ids: [banana.id, -2] });
  ok(() => assert.deepEqual(sentBodies[0], { start: D, end: D, food_ids: [501, 502] }), 'sent with the server\'s ids');
  ok(() => assert.equal(out.url, 'https://customers.instacart.com/store/shopping_lists/1'), 'the server\'s link');
  ok(() => assert.equal(gateway('/push/v1/api/instacart/send').length, 1), 'one send');
  // the server has Instacart off
  const off = page({ gw: { 'GET /push/v1/about': about({ ...ON, instacart: false }), 'GET /push/v1/api/instacart': { enabled: true, max_items: 200 } } });
  const offStatus = await off.api.request('GET', '/api/instacart');
  ok(() => assert.equal(offStatus.enabled, false), 'off on the server: off here');
  ok(() => assert.equal(off.gateway('/push/v1/api/instacart').length, 0), 'and not asked');
  // the server cannot be reached: the button stays hidden
  const away = page({ gw: { 'GET /push/v1/about': about(ON), 'GET /push/v1/api/instacart': 'offline' } });
  const awayStatus = await away.api.request('GET', '/api/instacart');
  ok(() => assert.equal(awayStatus.enabled, false), 'unreachable: off');
}

// 4. The list app through the server: what is set up there, sent from the phone; never set up from it.
{
  const sentBodies = [];
  const connection = { app: 'grocy', base_url: 'https://lists.example.com', list_id: '7', list_name: 'Shop', key_set: true,
    last_test_at: null, last_test_error: null, last_sent_at: null, last_sent_count: null };
  const gw = { 'GET /push/v1/about': about(ON), 'GET /push/v1/api/list-sync': { enabled: true, can_use: true, private_hosts: false, apps: [], connection },
    'POST /push/v1/api/list-sync/preview': { app: 'grocy', app_name: 'Grocy', list_name: 'Shop', ready: true, last_sent_at: null, last_sent_count: null,
      items: [{ food_id: 777, name: 'Rice, white, cooked', amount: '1 serving', text: 'Rice: 1 serving' }] },
    'POST /push/v1/api/list-sync/send': (req) => { sentBodies.push(JSON.parse(req.body)); return { sent: 1, error: null, message: null, connection }; } };
  const { api, gateway } = page({ gw });
  const rice = food(api, 'rice white cooked');
  plan(api, rice);
  const status = await api.request('GET', '/api/list-sync');
  ok(() => assert.deepEqual([status.enabled, status.connection.list_name], [true, 'Shop']), 'the server\'s list app');
  const preview = await api.request('POST', '/api/list-sync/preview', { start: D, end: D });
  const here = preview.items[0].food_id;
  ok(() => assert.ok(here === rice.id || here === -1), 'shown with the phone\'s id, or none');
  const out = await api.request('POST', '/api/list-sync/send', { start: D, end: D, food_ids: [here] });
  ok(() => assert.deepEqual([out.sent, sentBodies[0].food_ids], [1, [777]]), 'sent with the server\'s id');
  for (const [m, p] of [['PUT', '/api/list-sync'], ['DELETE', '/api/list-sync'], ['POST', '/api/list-sync/test']]) {
    await fails(api.request(m, p, { app: 'grocy', base_url: 'https://x.example', key: 'k' }), 404, `${m} ${p}: set up in the web app`);
  }
  ok(() => assert.equal(gateway('/push/v1/api/list-sync/test').length + gateway('/push/v1/api/list-sync').filter((r) => r.method !== 'GET').length, 0),
    'never asked of the server');
}

console.log(`server lists: ${checks} checks passed`);
process.exit(0);
