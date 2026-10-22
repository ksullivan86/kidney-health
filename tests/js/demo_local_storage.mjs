#!/usr/bin/env node
// "Keep my data in this browser" (app/static/js/mock/persist.js, mock/export.js): the storage layer run against a fake IndexedDB
// (tests/js/fake_idb.mjs) in the demo loaded the way run_vectors.mjs loads it. Exits 1 with the failed check on any mismatch;
// pytest (tests/test_demo_local_storage.py) runs it. Each "page" is a fresh load of every script (a reload), sharing one fake
// browser profile (the databases).
import assert from 'node:assert/strict';
import { loadDemo, newDemo } from './demo_loader.mjs';
import { createFakeIndexedDB } from './fake_idb.mjs';

const D = new Date().toISOString().slice(0, 10);
// A deep copy made inside the page's own realm (what a browser's structured clone gives that page).
const CLONE_SRC = `(function clone(v) {
  if (typeof v === 'function') throw Object.assign(new Error('DataCloneError'), { name: 'DataCloneError' });
  if (v === null || typeof v !== 'object') return v;
  const tag = Object.prototype.toString.call(v); // not instanceof: a value stored by an earlier page comes from another realm
  if (tag === '[object Map]') return new Map([...v].map(([k, x]) => [clone(k), clone(x)]));
  if (tag === '[object Set]') return new Set([...v].map(clone));
  if (Array.isArray(v)) return v.map(clone);
  const o = {}; for (const k of Object.keys(v)) o[k] = clone(v[k]); return o;
})`;

const profile = createFakeIndexedDB(); // one browser profile: its databases are shared by every page below
function loadPage({ preview = true, storage = { persist: async () => true, persisted: async () => false }, indexedDB = 'fake' } = {}) {
  const KH = loadDemo({ navigator: { userAgent: 'node', onLine: true, storage } });
  KH.flags.PREVIEW = preview;
  const api = newDemo(KH);
  const clone = new KH.constructor.constructor(`return ${CLONE_SRC}`)();
  const fake = profile.page(clone);
  if (indexedDB === 'fake') KH.mock.local._useIndexedDB(fake);
  return { KH, api, fake, local: KH.mock.local };
}
const quick = (name) => ({ date: D, meal: 'lunch', name, serving_desc: '1 bar', serving_g: 40, servings: 1,
  nutrients: { calories_kcal: 160, protein_g: 3, carbs_g: 24, potassium_mg: 150, phosphorus_mg: 80, sodium_mg: 90 } });
const names = (api) => Array.from(api._entries, (e) => e.food_name); // an array of this realm, so deepEqual compares plain contents
const stored = () => profile.read('kdl-demo-local', 'state', 'current');
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
let checks = 0;
const ok = (fn, label) => { checks += 1; try { fn(); } catch (e) { e.message = `${label}: ${e.message}`; throw e; } };

// 1. The installed app (not the demo build): nothing is opened, nothing can be turned on.
{
  const { local, fake } = loadPage({ preview: false });
  await local.boot();
  ok(() => assert.equal(fake.calls.opens, 0), 'boot outside the demo build opens no database');
  await assert.rejects(local.enable({ fresh: false }), /only offered in the demo/);
  await assert.rejects(local.probe().then(() => { assert.equal(fake.calls.opens, 0); throw new Error('not rejected'); }), /not rejected/);
  ok(() => assert.equal(local.status().allowed, false), 'not allowed outside the demo build');
  ok(() => assert.equal(local.on(), false));
  ok(() => assert.equal(fake.calls.opens, 0), 'still no database call');
}

// 2. The demo build, never opted in: looking for a saved copy leaves no database behind.
{
  const { local, fake } = loadPage();
  const s = await local.boot();
  ok(() => assert.equal(s.on, false), 'off by default');
  ok(() => assert.equal(profile.databases.size, 0), 'no database was created by looking');
  ok(() => assert.equal(fake.calls.opens, 1));
}

// 3. Turn it on keeping the sample data; the browser is asked to keep the data; the copy holds the whole state.
{
  const { local, api, KH } = loadPage();
  await local.boot();
  const res = await local.enable({ fresh: false });
  ok(() => assert.equal(res.reload, false));
  const s = local.status();
  ok(() => assert.equal(s.on, true));
  ok(() => assert.equal(s.persisted, true), 'navigator.storage.persist() answer is kept');
  const rec = stored();
  ok(() => assert.equal(rec.format, 'kidney-health-demo-local'));
  ok(() => assert.equal(rec.schema, 1));
  ok(() => assert.equal(rec.rev, 1));
  ok(() => assert.equal(rec.state._entries.length, api._entries.length), 'the sample days are in the copy');
  ok(() => assert.ok(rec.state._foods.length > 20 && rec.state._foodById.size > 20), 'foods are in the copy');
  ok(() => assert.equal('_guidanceVectors' in rec.state, false), 'derived caches are not saved');
  // a write is saved after the debounce, not before
  await api.request('POST', '/api/log/quick', quick('Oat bar'));
  ok(() => assert.equal(stored().rev, 1), 'not saved at once');
  await wait(KH.mock.local.SAVE_DELAY_MS + 400);
  ok(() => assert.equal(stored().rev, 2), 'saved after the debounce');
  ok(() => assert.ok(stored().state._entries.some((e) => e.food_name === 'Oat bar')));
  // reads do not save
  await api.request('GET', `/api/log?date=${D}`);
  await wait(KH.mock.local.SAVE_DELAY_MS + 300);
  ok(() => assert.equal(stored().rev, 2), 'a read is not a save');
  // many writes in a row are one save
  await api.request('POST', '/api/log/quick', quick('Rice cake'));
  await api.request('POST', '/api/log/quick', quick('Pear'));
  await local.flush();
  ok(() => assert.equal(stored().rev, 3), 'a burst is one save');
  // an import's dry run only asks: it is no reason to save
  const asked = await api.request('POST', '/api/me/import?dry_run=1', { format: 'kidney-health-export', version: 1 });
  ok(() => assert.equal(asked.dry_run, true));
  await local.flush();
  ok(() => assert.equal(stored().rev, 3), 'a dry run is not a save');
  // a refused write (400) saves nothing
  await assert.rejects(api.request('POST', '/api/log/quick', { date: 'x' }));
  await local.flush();
  ok(() => assert.equal(stored().rev, 3), 'a failed write is not saved');
}

// 4. A reload: the copy is read back, the entry added before is still there, and the mode is on.
{
  const { local, api } = loadPage();
  const s = await local.boot();
  ok(() => assert.equal(s.on, true), 'on after reload');
  ok(() => assert.ok(names(api).includes('Oat bar') && names(api).includes('Pear')), 'entries survive the reload');
  ok(() => assert.equal(api._entries.length > 30, true), 'the sample days came back too');
  const day = await api.request('GET', `/api/log?date=${D}`);
  ok(() => assert.ok(day.entries.some((e) => e.food_name === 'Oat bar')));
  // new ids continue where they stopped (no reuse)
  const before = Math.max(...api._entries.map((e) => e.id));
  const made = await api.request('POST', '/api/log/quick', quick('After reload'));
  ok(() => assert.ok(made.id > before));
  await local.flush();
  ok(() => assert.equal(stored().rev, 4));
}

// 5. The export in the server's shape and the import twin are used by the next sections; here the shape of the document.
{
  const { local, api } = loadPage();
  await local.boot();
  const doc = await api.request('GET', '/api/me/export.json');
  ok(() => assert.deepEqual(Object.keys(doc), ['format', 'version', 'exported_at', 'app_version', 'user', 'profile', 'settings', 'log_entries',
    'custom_foods', 'linked_foods', 'meal_templates', 'lab_results', 'symptoms', 'weights', 'blood_pressures', 'ai_audit', 'activity',
    'food_preferences', 'ai_usage', 'ai_consents', 'ai_provider', 'builtin_foods']), 'the export has the server\'s keys in the server\'s order');
  ok(() => assert.equal(doc.format, 'kidney-health-export'));
  ok(() => assert.equal(doc.version, 1));
  ok(() => assert.ok(doc.log_entries.length > 30 && doc.log_entries.every((e) => !('version' in e))), 'entries without the derived version');
  ok(() => assert.ok(doc.builtin_foods.length > 5 && doc.builtin_foods.every((f) => Object.keys(f).join() === 'id,name,fdc_id')));
  ok(() => assert.ok(doc.lab_results.length > 3 && doc.lab_results.every((l) => l.unit)));
  // no password, session, token or key anywhere in it, not even as a field name
  const keys = new Set();
  (function walk(v) { if (Array.isArray(v)) v.forEach(walk); else if (v && typeof v === 'object') for (const [k, x] of Object.entries(v)) { keys.add(k); walk(x); } })(doc);
  ok(() => assert.deepEqual([...keys].filter((k) => /password|secret|api_key|token|session|hash/i.test(k)), []), 'no secret-like field in the export');
  ok(() => assert.ok(!('sessions' in doc) && !('users' in doc)), 'no other person\'s data');
}

// 6. A copy saved by a newer version is not loaded, not overwritten, and the sheet can say why.
{
  const rec = stored();
  profile.write('kdl-demo-local', 'state', 'current', { ...rec, schema: 99, rev: 7 });
  const { local, api } = loadPage();
  const s = await local.boot();
  ok(() => assert.equal(s.on, false));
  ok(() => assert.equal(s.blocked.code, 'newer'));
  ok(() => assert.match(s.blocked.message, /newer version/));
  ok(() => assert.ok(api._entries.length > 0 && !names(api).includes('After reload')), 'the page runs the in-memory sample demo');
  await assert.rejects(local.enable({ fresh: false }), /newer version/);
  await api.request('POST', '/api/log/quick', quick('Not saved'));
  await local.flush();
  ok(() => assert.deepEqual(stored(), { ...rec, schema: 99, rev: 7 }), 'the newer copy is untouched');
  // put the readable copy back for the next sections
  profile.write('kdl-demo-local', 'state', 'current', rec);
}

// 7. An unreadable copy is left alone too.
{
  const rec = stored();
  profile.write('kdl-demo-local', 'state', 'current', { hello: 'world' });
  const { local } = loadPage();
  const s = await local.boot();
  ok(() => assert.equal(s.blocked.code, 'unreadable'));
  ok(() => assert.deepEqual(stored(), { hello: 'world' }));
  profile.write('kdl-demo-local', 'state', 'current', rec);
}

// 8. Two tabs: the second one to save finds the copy changed and stops instead of overwriting it.
{
  const a = loadPage(); const b = loadPage();
  await a.local.boot(); await b.local.boot();
  await a.api.request('POST', '/api/log/quick', quick('From tab A'));
  await a.local.flush();
  const winner = stored();
  ok(() => assert.ok(winner.state._entries.some((e) => e.food_name === 'From tab A')));
  await b.api.request('POST', '/api/log/quick', quick('From tab B'));
  const out = await b.local.flush();
  ok(() => assert.equal(out.conflict, true));
  ok(() => assert.match(out.error, /Another tab changed the data/));
  ok(() => assert.deepEqual(stored(), winner), 'tab B did not overwrite tab A');
  await b.api.request('POST', '/api/log/quick', quick('Again from B'));
  await b.local.flush();
  ok(() => assert.deepEqual(stored(), winner), 'and keeps not writing');
}

// 9. A full disk: the error is said, the page keeps working, and the next change tries again.
{
  const { local, api, fake } = loadPage();
  await local.boot();
  fake.failPut = 'QuotaExceededError';
  await api.request('POST', '/api/log/quick', quick('Too big'));
  const out = await local.flush();
  ok(() => assert.match(out.error, /no room left/));
  ok(() => assert.ok(names(api).includes('Too big')), 'the entry is still in the page');
  fake.failPut = null;
  await local.flush();
  ok(() => assert.equal(local.status().error, null));
  ok(() => assert.ok(stored().state._entries.some((e) => e.food_name === 'Too big')), 'saved once there is room');
}

// 10. A browser that refuses IndexedDB (private mode, a sandboxed frame): said plainly, the demo stays in memory.
{
  const { local, api, fake } = loadPage();
  fake.refuse = 'SecurityError';
  const s = await local.boot();
  ok(() => assert.equal(s.on, false));
  ok(() => assert.match(s.unavailable, /does not let this page store data/));
  await assert.rejects(local.enable({ fresh: true }), /does not let this page store data/);
  ok(() => assert.equal(local.on(), false));
  await api.request('POST', '/api/log/quick', quick('In memory'));
  ok(() => assert.ok(names(api).includes('In memory')), 'the demo still works');
  const none = loadPage({ indexedDB: 'none' });
  none.local._useIndexedDB(null);
  const s2 = await none.local.boot();
  ok(() => assert.match(s2.unavailable, /does not let this page store data/), 'no indexedDB at all');
  const p = await none.local.probe();
  ok(() => assert.ok(p.unavailable));
}

// 11. "Stop keeping data here" deletes the stored copy.
{
  const { local } = loadPage();
  await local.boot();
  ok(() => assert.equal(local.on(), true));
  const res = await local.disable();
  ok(() => assert.equal(res.reload, true));
  ok(() => assert.equal(local.on(), false));
  ok(() => assert.equal(profile.databases.size, 0), 'the database is gone');
  const again = loadPage();
  const s = await again.local.boot();
  ok(() => assert.equal(s.on, false), 'a reload starts the sample demo again');
}

// 12. Start from an empty log of one's own: the stored copy holds no sample person, and the account is empty (a fresh server's).
{
  const { local, api } = loadPage();
  await local.boot();
  const res = await local.enable({ fresh: true });
  ok(() => assert.equal(res.reload, true));
  const rec = stored();
  ok(() => assert.equal(rec.state._entries.length, 0));
  ok(() => assert.equal(rec.state._profile.ckd_stage_chosen, false));
  const after = loadPage();
  await after.local.boot();
  const day = await after.api.request('GET', `/api/log?date=${D}`);
  ok(() => assert.equal(day.entries.length, 0));
  await after.api.request('POST', '/api/log/quick', quick('First of mine'));
  await after.local.flush();
  const third = loadPage();
  await third.local.boot();
  ok(() => assert.deepEqual(names(third.api), ['First of mine']));
  await third.local.disable();
  void api;
}

console.log(`demo local storage: ${checks} checks passed`);
