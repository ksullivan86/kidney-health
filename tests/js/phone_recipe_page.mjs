#!/usr/bin/env node
// A recipe page read on the iPhone with no server (owner, 2026-11-26; design note 30 §3; js/mock/lists.js). A stand-in for the iPhone
// app answers the bridge: `services` says it reads pages, `fetchRecipePage` answers a page's HTML, and `serverApi` is a fake of the
// paired server's gateway. Checks: with no server the sheet offers the link and the phone reads the page; only the link goes to the
// app; the recipe is read with the twin of the server's parser and its lines matched with the phone's own foods; the app's refusals
// are said in the server's words (the phone's for a few); a script in the page never runs; an older app without the kind keeps
// pasting only; a paired server that reads pages still does, and when it cannot be reached the phone reads the page instead.
// pytest (tests/test_phone_recipe_import.py) runs it. Exits 1 on any mismatch.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { loadDemo } from './demo_loader.mjs';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..', '..');
const FOODS = JSON.parse(readFileSync(join(ROOT, 'data', 'foods.json'), 'utf8'));
const plain = (v) => JSON.parse(JSON.stringify(v));
let checks = 0;
const ok = (fn, label) => { checks += 1; try { fn(); } catch (e) { e.message = `${label}: ${e.message}`; throw e; } };
const fails = (promise, code, label, test = () => true) => {
  checks += 1;
  return assert.rejects(promise, (e) => e.status === code && test(e), label);
};

const RECIPE = { '@context': 'https://schema.org', '@type': 'Recipe', name: 'Banana rice &amp; thyme', recipeYield: '2 servings',
  recipeIngredient: ['1 medium banana', '2 cups cooked white rice', '1 tsp dried thyme'],
  recipeInstructions: [{ '@type': 'HowToStep', text: 'Cook the rice.' }, { '@type': 'HowToStep', text: 'Slice the banana on top.' }] };
const PAGE = '<!DOCTYPE html><html><head><title>Banana rice</title>'
  + '<script>globalThis.pageScriptRan = true;</script>'
  + `<script type="application/ld+json">${JSON.stringify({ '@context': 'https://schema.org', '@graph': [{ '@type': 'WebSite' }, RECIPE] })}</script>`
  + '</head><body><img src="x" onerror="globalThis.pageScriptRan = true"><h1>Banana rice</h1></body></html>';

// `app`: what the stand-in app answers for fetchRecipePage (a function of the request, or an answer); `services`: its services
// answer; `paired` and `gw` as in server_lists.mjs.
function page({ paired = false, gw = {}, app = { ok: true, html: PAGE }, services = { ok: true, usda: false, off: false, scan: false, recipePage: true } } = {}) {
  const KH = loadDemo({ navigator: { userAgent: 'node', onLine: true, storage: {} }, globals: { KDL_PREVIEW: true, KDL_DEVICE: true } });
  const api = new KH.mock.MockApi({ foodsData: FOODS, seed: false });
  KH.mock.instance = api;
  const global = new KH.constructor.constructor('return globalThis')();
  const log = [];
  global.webkit = { messageHandlers: { bridge: { postMessage: async (req) => {
    log.push(plain(req));
    if (req.kind === 'services') return services;
    if (req.kind === 'fetchRecipePage') return typeof app === 'function' ? app(req) : app;
    if (req.kind === 'serverInfo') return paired ? { ok: true, paired: true, server: 'food.example.org' } : { ok: true, paired: false };
    if (req.kind !== 'serverApi') return { error: 'bad_request' };
    if (!paired) return { error: 'not_paired' };
    let a = gw[`${req.method} ${req.path.split('?')[0]}`];
    if (typeof a === 'function') a = a(req);
    if (a === undefined) return { ok: true, status: 404, json: '{"detail":"This is not open to the iPhone app."}' };
    if (a === 'offline') return { error: 'offline' };
    return { ok: true, status: a.http || 200, json: JSON.stringify(a.http || a.json ? a.json : a) };
  } } } };
  const kinds = (kind) => log.filter((r) => r.kind === kind);
  const server = () => log.filter((r) => r.kind === 'serverApi' && r.path !== '/push/v1/about');
  return { KH, api, log, kinds, server, global };
}
const about = (services) => ({ json: { account: 'acct-1', api_version: 1, features: { usda_search: true, barcode: true }, services } });
const URL1 = 'https://recipes.example.com/banana-rice';

// 1. No server: the phone reads the page.
{
  const { api, kinds, server, global } = page();
  const info = await api.request('GET', '/api/recipe-import');
  ok(() => assert.deepEqual([info.web, info.read_on], [true, 'phone']), 'the link box is offered, read on this phone');
  const draft = await api.request('POST', '/api/recipe-import/page', { url: `  ${URL1} ` });
  ok(() => assert.deepEqual(kinds('fetchRecipePage'), [{ kind: 'fetchRecipePage', url: URL1 }]), 'only the link goes to the app');
  ok(() => assert.equal(server().length, 0), 'no server is asked');
  ok(() => assert.deepEqual(plain([draft.name, draft.servings_made, draft.steps, draft.source_url, draft.read_on]),
    ['Banana rice & thyme', 2, ['Cook the rice.', 'Slice the banana on top.'], URL1, 'phone']), 'the page\'s recipe, read here');
  ok(() => assert.deepEqual(plain(draft.lines.map((l) => l.text)), ['1 medium banana', '2 cups cooked white rice', '1 tsp dried thyme']), 'every line');
  ok(() => assert.ok(draft.lines[0].matches.length && draft.lines[0].matches.every((m) => api._food(m.food.id)), 'matched with the phone\'s own foods'));
  ok(() => assert.ok(draft.lines[0].matches[0].food.name.toLowerCase().includes('banana')), 'the banana is a banana');
  ok(() => assert.equal(global.pageScriptRan, undefined), 'nothing on the page runs');
  // the same draft as the server's parser gives for the same page (the recipe part; tests/data/recipe_page_vectors.json pins it)
  ok(() => assert.equal(draft.notice, 'Check each food the app chose, and fix it if it is wrong. Nothing is saved until you press Save.'), 'the notice');
  // pasted ingredients still never leave the phone
  const before = kinds('fetchRecipePage').length + server().length;
  await api.request('POST', '/api/recipe-import/text', { text: '1 medium banana' });
  ok(() => assert.equal(kinds('fetchRecipePage').length + server().length, before), 'pasted ingredients never leave the phone');
}

// 2. The app's refusals, in the server's words (the phone's for a link, a private address, no answer and too many pages).
{
  const L = page().KH.mock.lists;
  const cases = [
    [{ error: 'bad_link' }, 400, L.PHONE_MESSAGES.bad_link, 'bad_link'],
    [{ error: 'blocked' }, 422, 'This iPhone does not open that address. It may be a private or local address.', 'blocked'],
    [{ error: 'timeout' }, 422, L.PAGE_MESSAGES.timeout, 'timeout'],
    [{ error: 'too_large' }, 422, L.PAGE_MESSAGES.too_large, 'too_large'],
    [{ error: 'not_html' }, 422, L.PAGE_MESSAGES.not_html, 'not_html'],
    [{ error: 'http_error' }, 422, L.PAGE_MESSAGES.http_error, 'http_error'],
    [{ error: 'too_many_redirects' }, 422, L.PAGE_MESSAGES.too_many_redirects, 'too_many_redirects'],
    [{ error: 'rate_limited' }, 429, L.PHONE_MESSAGES.rate_limited, 'rate_limited'],
    [{ error: 'something new' }, 422, L.PHONE_MESSAGES.unreachable, 'unreachable'],
    [{ ok: true }, 422, L.PHONE_MESSAGES.unreachable, 'unreachable'],
    [{ ok: true, html: '<html><body>No recipe here.</body></html>' }, 422, L.NO_RECIPE_TEXT, 'no_recipe'],
    [{ ok: true, html: `<script type="application/ld+json">${JSON.stringify({ '@type': 'Recipe', name: 'Empty' })}</script>` }, 422, L.NO_LINES_TEXT, 'no_lines'],
  ];
  for (const [answer, status, words, code] of cases) {
    const { api } = page({ app: answer });
    await fails(api.request('POST', '/api/recipe-import/page', { url: URL1 }), status, `${JSON.stringify(answer).slice(0, 40)} → ${code}`,
      (e) => e.detail === words && e.extra && e.extra.code === code);
  }
  const { api, kinds } = page();
  await fails(api.request('POST', '/api/recipe-import/page', {}), 400, 'a request with no link');
  ok(() => assert.equal(kinds('fetchRecipePage').length, 0), 'and nothing is fetched');
}

// 3. An older iPhone app without the kind: pasting only, as before.
{
  const { api, kinds } = page({ services: { ok: true, usda: false, off: false, scan: false } });
  const info = await api.request('GET', '/api/recipe-import');
  ok(() => assert.deepEqual([info.web, info.read_on], [false, null]), 'no link box');
  await fails(api.request('POST', '/api/recipe-import/page', { url: URL1 }), 404, 'no page is read');
  ok(() => assert.equal(kinds('fetchRecipePage').length, 0), 'nothing asked of the app');
}

// 4. A paired server that reads pages still does; when it cannot be reached, or has pages off, this phone reads the page.
{
  const serverDraft = (req) => ({ name: 'From the server', servings_made: 2, steps: [], steps_cut: false, lines_cut: false,
    source_url: JSON.parse(req.body).url, lines: [{ text: '1 medium banana', amount: 1, unit: null, food_text: 'banana', note: null, matches: [] }],
    notice: 'x', estimate: 'x' });
  const ON = { 'GET /push/v1/about': about({ recipe_import: true }), 'GET /push/v1/api/recipe-import': { web: true, max_lines: 60, estimate: 'x' },
    'POST /push/v1/api/recipe-import/page': serverDraft };
  {
    const { api, kinds } = page({ paired: true, gw: { ...ON } });
    const info = await api.request('GET', '/api/recipe-import');
    ok(() => assert.deepEqual([info.web, info.read_on], [true, 'server']), 'the server reads pages');
    const draft = await api.request('POST', '/api/recipe-import/page', { url: URL1 });
    ok(() => assert.deepEqual([draft.name, draft.read_on], ['From the server', 'server']), 'read by the server');
    ok(() => assert.equal(kinds('fetchRecipePage').length, 0), 'not fetched by the phone');
  }
  {
    const gw = { ...ON, 'POST /push/v1/api/recipe-import/page': 'offline' };
    const { api, kinds } = page({ paired: true, gw });
    const draft = await api.request('POST', '/api/recipe-import/page', { url: URL1 });
    ok(() => assert.deepEqual([draft.name, draft.read_on], ['Banana rice & thyme', 'phone']), 'the server went away: read on the phone');
    ok(() => assert.equal(kinds('fetchRecipePage').length, 1), 'fetched once by the phone');
  }
  {
    const { api } = page({ paired: true, gw: { 'GET /push/v1/about': 'offline' } });
    const info = await api.request('GET', '/api/recipe-import');
    ok(() => assert.deepEqual([info.web, info.read_on], [true, 'phone']), 'an unreachable server: read on the phone');
    const draft = await api.request('POST', '/api/recipe-import/page', { url: URL1 });
    ok(() => assert.equal(draft.read_on, 'phone'), 'and the page is read here');
  }
  {
    const gw = { ...ON, 'GET /push/v1/api/recipe-import': { web: false, max_lines: 60, estimate: 'x' } };
    const { api, server } = page({ paired: true, gw });
    const info = await api.request('GET', '/api/recipe-import');
    ok(() => assert.deepEqual([info.web, info.read_on], [true, 'phone']), 'pages off on the server: read on the phone');
    await api.request('POST', '/api/recipe-import/page', { url: URL1 });
    ok(() => assert.equal(server().filter((r) => r.method === 'POST').length, 0), 'the server is not asked to read it');
  }
  {
    const gw = { ...ON, 'POST /push/v1/api/recipe-import/page': () => ({ http: 422, json: { detail: 'The page did not answer.', code: 'unreachable' } }) };
    const { api, kinds } = page({ paired: true, gw });
    await fails(api.request('POST', '/api/recipe-import/page', { url: URL1 }), 422, 'the server\'s own refusal stands', (e) => e.extra && e.extra.code === 'unreachable');
    ok(() => assert.equal(kinds('fetchRecipePage').length, 0), 'and the phone does not try again behind it');
  }
}

console.log(`phone recipe page: ${checks} checks passed`);
