#!/usr/bin/env node
// Device mode with a server: notes and suggestions from the person's Care team (design notes 37 and 29; owner, 2026-11-26), from
// js/mock/server_care.js, and Settings → Care team read-only (GET /api/device/care-team).
//
//   node tests/js/server_care.mjs           a stand-in for the iPhone app and the server's gateway: no server (the phone's own
//                                           answer), paired (the server's answer, nothing kept), offline, a token that only adds
//                                           rows, If-Match carried, Add to my plan needs sync both ways
//   node tests/js/server_care.mjs --relay   the real server: each bridge request is written to stdout as one line "@@ {json}" and
//                                           its answer read from stdin (tests/test_server_care_phone.py carries it to the real
//                                           routes through the app's allow-list, and plays the person's Clinician)
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
const plain = (v) => JSON.parse(JSON.stringify(v));
let checks = 0;
const ok = (fn, label) => { checks += 1; try { fn(); } catch (e) { e.message = `${label}: ${e.message}`; throw e; } };
async function rejects(promise, status, re, label) {
  checks += 1;
  try { await promise; } catch (e) {
    try { assert.equal(e.status, status); if (re) assert.match(String(e.detail || e.message), re); } catch (x) { x.message = `${label}: ${x.message}`; throw x; }
    return e;
  }
  throw new Error(`${label}: it went through`);
}

async function page({ bridge, seed = false }) {
  const KH = loadDemo({ navigator: { userAgent: 'node', onLine: true, storage: {} }, globals: { KDL_PREVIEW: true, KDL_DEVICE: true } });
  KH.mock.instance = new KH.mock.MockApi({ foodsData: JSON.parse(FOODS), seed });
  const db = createFakeIndexedDB();
  KH.mock.local._useIndexedDB(db.page(new KH.constructor.constructor(`return ${CLONE_SRC}`)()));
  await KH.mock.local.boot();
  const global = new KH.constructor.constructor('return globalThis')();
  global.webkit = { messageHandlers: { bridge: { postMessage: async (req) => bridge(plain(req)) } } };
  return { KH, api: KH.mock.instance, db, A: KH.mock.serverApi, C: KH.mock.serverChanges, S: KH.mock.serverSync };
}
// Everything the phone keeps: its saved log, and the export (the safety copy holds the same).
function flat(v) { // the page's own Maps and Sets come from another realm: told apart by their tag
  const tag = Object.prototype.toString.call(v);
  if (tag === '[object Map]') return [...v].map(([k, x]) => [flat(k), flat(x)]);
  if (tag === '[object Set]') return [...v].map(flat);
  if (Array.isArray(v)) return v.map(flat);
  if (v && typeof v === 'object') return Object.fromEntries(Object.entries(v).map(([k, x]) => [k, flat(x)]));
  return v;
}
async function kept(p) {
  await p.KH.mock.local.flush();
  const stored = [...p.db.databases.values()].map((d) => flat(d.stores));
  const exp = await p.api.request('GET', '/api/me/export.json');
  return JSON.stringify(stored) + JSON.stringify(exp);
}

const NOTE = { id: 41, from: { name: 'Dee', removed: false }, area: 'labs', date: null, body: 'Bring your lab results to the visit.',
  version: 2, created_at: '2026-11-25T10:00:00.000000Z', edited_at: '2026-11-25T11:00:00.000000Z', read_at: null };
const ABOUT = { account: 'acct-1', api_version: 1, sync: { gateway: true, changes: true },
  care_team: { enabled: true, notes: true, team: [{ name: 'Dee', role: 'clinician', areas: ['labs'] }], on: [{ name: 'Ana', role: 'care_helper' }] } };

// ---------------------------------------------------------------------------------------------------------------- the stand-in
async function standIn() {
  // N1. No server: the phone's own answer, as before (an empty start has no Care team), and Settings leaves the section out.
  {
    const log = [];
    const p = await page({ bridge: (req) => { log.push(req); return req.kind === 'serverInfo' ? { ok: true, paired: false } : { error: 'not_paired' }; } });
    const notes = await p.api.request('GET', '/api/me/notes');
    ok(() => assert.deepEqual(plain(notes), { enabled: true, unread: 0, notes: [] }), 'N1 no server: the phone\'s own empty notes');
    const sgs = await p.api.request('GET', '/api/me/suggestions');
    ok(() => assert.deepEqual(plain(sgs), { enabled: true, suggestions: [] }), 'N1 and suggestions');
    const team = await p.api.request('GET', '/api/device/care-team');
    ok(() => assert.deepEqual(plain(team), { paired: false, state: 'not_paired', server: null, care_team: null }), 'N1 Settings: not paired');
    ok(() => assert.equal(log.filter((r) => r.kind === 'serverApi').length, 0), 'N1 nothing asked of a server');
  }
  // N2. Paired both ways: the server's notes, read with the version shown, deleted; nothing is kept on the phone.
  {
    const log = [];
    let net = 'up';
    const gw = {
      'GET /push/v1/about': () => ({ status: 200, json: ABOUT }),
      'GET /push/v1/api/me/notes': () => ({ status: 200, json: { enabled: true, unread: 1, notes: [NOTE] } }),
      'POST /push/v1/api/me/notes/41/read': (req) => (req.ifMatch === '"2"' ? { status: 204, json: '' }
        : { status: 412, json: { detail: 'This note was changed since you opened it.', current: { ...NOTE, version: 3 } } }),
      'DELETE /push/v1/api/me/notes/41': () => ({ status: 204, json: '' }),
      'GET /push/v1/api/me/suggestions': () => ({ status: 200, json: { enabled: true, suggestions: [{ id: 7, share_id: 1, from_name: 'Jo', date: '2026-11-27',
        meal: 'dinner', items: [{ food_id: 900, name: 'Rice', servings: 1, serving_desc: '1 cup', available: true }], note: null, fit: null,
        created_at: 'x', expires_at: 'y', answer: 'open' }] } }),
      'POST /push/v1/api/me/suggestions/7/decline': () => ({ status: 204, json: '' }),
    };
    const p = await page({ bridge: (req) => {
      log.push(req);
      if (req.kind === 'serverInfo') return { ok: true, paired: true, server: 'kidney.example.org' };
      if (req.kind !== 'serverApi') return { error: 'bad_request' };
      if (net === 'down') return { error: 'offline' };
      if (net === 'add_only') return { ok: true, status: 401, json: '{"detail":"Not authenticated"}' };
      const a = gw[`${req.method} ${req.path.split('?')[0]}`];
      if (!a) return { ok: true, status: 404, json: '{"detail":"Not Found"}' };
      const r = a(req);
      return { ok: true, status: r.status, json: typeof r.json === 'string' ? r.json : JSON.stringify(r.json) };
    } });
    const { api } = p;
    const got = await api.request('GET', '/api/me/notes?before=50&limit=20&x=1');
    ok(() => assert.deepEqual(plain(got.notes), [NOTE]), 'N2 the server\'s notes');
    const asked = log.filter((r) => r.kind === 'serverApi' && r.path.startsWith('/push/v1/api/me/notes'));
    ok(() => assert.equal(asked[0].path, '/push/v1/api/me/notes?before=50&limit=20'), 'N2 only its page goes on (the app takes only those)');
    await rejects(api.request('POST', '/api/me/notes/41/read', undefined, { 'If-Match': '"1"' }), 412, /changed since you opened it/, 'N2 a changed note is 412');
    await api.request('POST', '/api/me/notes/41/read', undefined, { 'If-Match': '"2"' });
    const read = log.filter((r) => r.kind === 'serverApi' && r.path === '/push/v1/api/me/notes/41/read');
    ok(() => assert.deepEqual(read.map((r) => [r.method, r.ifMatch]), [['POST', '"1"'], ['POST', '"2"']]), 'N2 marking read carries the version shown');
    ok(() => assert.equal(read.some((r) => 'body' in r), false), 'N2 with no body');
    await api.request('DELETE', '/api/me/notes/41');
    ok(() => assert.equal(api._care().notes.length, 0), 'N2 nothing kept in the phone\'s Care team');
    const all = await kept(p);
    ok(() => assert.ok(all.includes('"current"') || all.length > 2000, 'the saved log was read'), 'N2 the check reads the saved log');
    ok(() => assert.equal(all.includes(NOTE.body), false), 'N2 no note text in the saved log or the export');
    const sg = await api.request('GET', '/api/me/suggestions');
    ok(() => assert.deepEqual([sg.suggestions.length, sg.suggestions[0].from_name], [1, 'Jo']), 'N2 the server\'s suggestions');
    await api.request('POST', '/api/me/suggestions/7/decline');
    ok(() => assert.equal(log.some((r) => r.path === '/push/v1/api/me/suggestions/7/decline'), true), 'N2 No thanks goes to the server');
    await rejects(api.request('POST', '/api/me/suggestions/7/accept'), 409, /Turn on sync with your server first/, 'N2 Add needs sync both ways on');
    ok(() => assert.equal(log.some((r) => r.path === '/push/v1/api/me/suggestions/7/accept'), false), 'N2 and nothing was sent');
    const team = await api.request('GET', '/api/device/care-team');
    ok(() => assert.deepEqual(plain(team), { paired: true, state: 'both', server: 'kidney.example.org', care_team: ABOUT.care_team }), 'N2 Settings: the Care team');
    // N3. The server cannot be reached: an error that says so, never an old copy.
    net = 'down';
    await rejects(api.request('GET', '/api/me/notes'), 503, /cannot be reached right now/, 'N3 offline: the notes say so');
    await rejects(api.request('GET', '/api/me/suggestions'), 503, /cannot be reached/, 'N3 and the suggestions');
    p.A.forget();
    const off = await api.request('GET', '/api/device/care-team');
    ok(() => assert.deepEqual([off.paired, off.state, off.care_team], [true, 'offline', null]), 'N3 Settings: paired, not reachable');
    // N4. A token that only adds rows: what is needed, in words.
    net = 'add_only';
    p.A.forget();
    await rejects(api.request('GET', '/api/me/notes'), 409, /both ways/, 'N4 add only: a token both ways is needed');
    const addOnly = await api.request('GET', '/api/device/care-team');
    ok(() => assert.equal(addOnly.state, 'add_only'), 'N4 Settings says so too');
  }
  // N5. The source: device mode only, no network or storage of its own, notes never named for the AI.
  const src = readFileSync(join(ROOT, 'app', 'static', 'js', 'mock', 'server_care.js'), 'utf8');
  ok(() => assert.ok(src.includes('KH.flags.DEVICE !== true')), 'N5 device mode only');
  for (const word of ['fetch(', 'XMLHttpRequest', 'localStorage', 'indexedDB', 'innerHTML', '_careState', 'M.ai', 'onWrite']) {
    ok(() => assert.equal(src.includes(word), false, word), `N5 no ${word}`);
  }
  const ai = readFileSync(join(ROOT, 'app', 'static', 'js', 'mock', 'ai.js'), 'utf8');
  ok(() => assert.equal(/serverCare|\/api\/me\/notes|_notes\(/.test(ai), false), 'N5 the AI never reads notes');
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
  let offline = false;
  const p = await page({ bridge: (req) => (offline && req.kind === 'serverApi' ? { error: 'offline' } : ask({ bridge: req })) });
  const { api, KH } = p;
  const clinician = async (what, extra = {}) => ask({ care: { what, ...extra } }); // the person's Clinician, in their own web app

  // R1. The first sync, so Add to my plan can bring its entries here.
  p.A.forget();
  await p.S.sendNow();
  ok(() => assert.equal(p.C.active(api), true, JSON.stringify(p.C.status())), 'R1 sync both ways is on');
  // R2. Settings → Care team, read-only, from the server's about.
  const team = await api.request('GET', '/api/device/care-team');
  ok(() => assert.deepEqual(plain(team.care_team), { enabled: true, notes: true, team: [{ name: 'Dee', role: 'custom', areas: ['food', 'labs'] }], on: [] }),
    'R2 who is on the Care team');
  // R3. A note from Dee: the Today card's count, the list, marked read with the version shown, a 412 after Dee's edit, delete.
  const first = (await clinician('note', { body: 'Your potassium was lower this week.' })).json;
  const second = (await clinician('note', { body: 'Bring your lab results to the visit.', area: 'labs' })).json;
  let mine = await api.request('GET', '/api/me/notes');
  ok(() => assert.deepEqual(plain([mine.enabled, mine.unread, mine.notes.map((n) => n.id)]), [true, 2, [second.id, first.id]]), 'R3 the server\'s notes');
  ok(() => assert.equal(mine.notes[0].from.name, 'Dee'), 'R3 from Dee');
  const edited = (await clinician('edit', { id: first.id, body: 'Your potassium was lower all week.' })).json;
  await rejects(api.request('POST', `/api/me/notes/${first.id}/read`, undefined, { 'If-Match': '"1"' }), 412, /changed/, 'R3 changed since shown: 412');
  await api.request('POST', `/api/me/notes/${first.id}/read`, undefined, { 'If-Match': `"${edited.version}"` });
  mine = await api.request('GET', '/api/me/notes');
  ok(() => assert.equal(mine.unread, 1), 'R3 one read');
  const hers = (await clinician('list')).json.notes;
  ok(() => assert.notEqual(hers.find((n) => n.id === first.id).read_at, null), 'R3 Dee sees "Read on"');
  await api.request('DELETE', `/api/me/notes/${second.id}`);
  const left = (await clinician('list')).json.notes;
  ok(() => assert.deepEqual(left.map((n) => n.id), [first.id]), 'R3 deleted for both');
  const all = await kept(p);
  ok(() => assert.equal(all.includes('potassium was lower'), false), 'R3 no note text kept on the phone');
  // R4. A suggestion: Add to my plan makes the person's own planned entries on the server, which reach this phone at once.
  const sent = (await clinician('suggest', { query: 'apple' })).json;
  const sg = await api.request('GET', '/api/me/suggestions');
  ok(() => assert.deepEqual(plain(sg.suggestions.map((s) => s.id)), [sent.id]), 'R4 the suggestion');
  const before = api._entries.length;
  const res = await api.request('POST', `/api/me/suggestions/${sent.id}/accept`);
  ok(() => assert.equal(res.entries.length + res.waiting, 1, JSON.stringify(res)), 'R4 one planned food added');
  ok(() => assert.equal(api._entries.length, before + 1), 'R4 it is on this phone after the sync');
  ok(() => assert.equal(res.entries[0].status, 'planned'), 'R4 planned');
  ok(() => assert.equal(KH.mock.instance._entryByClientId(res.entries[0].client_id).status, 'planned'), 'R4 the phone\'s own row');
  const no = (await clinician('suggest', { query: 'banana' })).json;
  await api.request('POST', `/api/me/suggestions/${no.id}/decline`);
  const none = await api.request('GET', '/api/me/suggestions');
  ok(() => assert.deepEqual(plain(none.suggestions), []), 'R4 none left');
  const answers = (await clinician('sent')).json.suggestions.map((x) => x.answer);
  ok(() => assert.deepEqual(answers, ['declined', 'accepted']), 'R4 Dee sees the answers');
  // R5. Offline: said plainly.
  offline = true;
  await rejects(api.request('GET', '/api/me/notes'), 503, /cannot be reached/, 'R5 offline');
  offline = false;
  await ask({ done: true });
}

if (RELAY) await realRuns(); else await standIn();
console.log(`server care${RELAY ? ' (real server)' : ''}: ${checks} checks passed`);
process.exit(0);
