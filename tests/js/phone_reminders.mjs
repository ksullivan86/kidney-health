#!/usr/bin/env node
// Reminders as the iPhone's own notifications (design note 35 §7): the planner against tests/data/phone_reminder_vectors.json, and
// the page in device mode with a stand-in for the iPhone app's "bridge": a reminder that changes, a meal logged today and the
// start of the app each send a fresh plan, and outside device mode nothing is asked. tests/test_phone_reminders.py runs it with
// TZ=UTC. Exits 1 with the failed check on any mismatch.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { loadDemo } from './demo_loader.mjs';
import { createFakeIndexedDB } from './fake_idb.mjs';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..', '..');
const VECTORS = JSON.parse(readFileSync(join(ROOT, 'tests', 'data', 'phone_reminder_vectors.json'), 'utf8'));
const CLONE_SRC = `(function clone(v) {
  if (v === null || typeof v !== 'object') return v;
  if (Array.isArray(v)) return v.map(clone);
  const tag = Object.prototype.toString.call(v);
  if (tag === '[object Map]') return new Map([...v].map(([k, x]) => [clone(k), clone(x)]));
  if (tag === '[object Set]') return new Set([...v].map(clone));
  const o = {}; for (const k of Object.keys(v)) o[k] = clone(v[k]); return o;
})`;
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
let checks = 0;
const ok = (fn, label) => { checks += 1; try { fn(); } catch (e) { e.message = `${label}: ${e.message}`; throw e; } };
const local = (text) => { const [d, t] = text.split('T'); const [y, m, day] = d.split('-').map(Number); const [hh, mm] = t.split(':').map(Number); return new Date(y, m - 1, day, hh, mm); };

// 1. The planner, case by case.
{
  const KH = loadDemo();
  const P = KH.mock.phoneReminders;
  ok(() => assert.equal(P.DAYS_AHEAD, VECTORS.days_ahead), 'days ahead');
  ok(() => assert.equal(P.MAX_PENDING, VECTORS.max_pending), 'at most 60 pending');
  for (const c of VECTORS.cases) {
    const got = JSON.parse(JSON.stringify(P.plan(c.reminders, local(c.now), c.eaten)));
    ok(() => assert.deepEqual(got, c.expect), c.name);
  }
  ok(() => assert.deepEqual({ ...P.SCREENS }, { log_meal: 'add', plan_tomorrow: 'plan', weigh_in: 'today' }), 'the screens of app/reminders.py');
}

// 2. Device mode with a stand-in for the app.
function loadPage({ device = true, permission = 'allowed' } = {}) {
  const KH = loadDemo({ navigator: { userAgent: 'node', onLine: true, storage: { persist: async () => true, persisted: async () => false } },
    globals: device ? { KDL_PREVIEW: true, KDL_DEVICE: true } : { KDL_PREVIEW: true } });
  const api = KH.mock.start({ seed: !device });
  const idb = createFakeIndexedDB();
  KH.mock.local._useIndexedDB(idb.page(new KH.constructor.constructor(`return ${CLONE_SRC}`)()));
  const sent = [];
  const app = { permission };
  const global = new KH.constructor.constructor('return globalThis')();
  global.webkit = { messageHandlers: { safetyCopy: { postMessage() {} }, bridge: { postMessage: async (m) => {
    const msg = JSON.parse(JSON.stringify(m));
    sent.push(msg);
    if (msg.kind !== 'reminders') return { error: 'bad_request' };
    if (msg.action === 'status') return { ok: true, permission: app.permission, pending: 0 };
    if (msg.action === 'allow') { if (app.permission === 'not_asked') app.permission = 'allowed'; return { ok: true, permission: app.permission, pending: 0 }; }
    if (msg.action === 'schedule') return { ok: true, scheduled: app.permission === 'allowed' ? msg.items.length : 0, permission: app.permission };
    if (msg.action === 'test') return app.permission === 'allowed' ? { ok: true } : { error: 'not_allowed', message: 'Turn on notifications on this iPhone first.' };
    return { ok: true };
  } } } };
  return { KH, api, sent, app, P: KH.mock.phoneReminders };
}
const schedules = (sent) => sent.filter((m) => m.kind === 'reminders' && m.action === 'schedule');
async function settle(sent, count) { for (let i = 0; i < 200 && schedules(sent).length < count; i += 1) await wait(10); }

{
  const { KH, api, sent, P } = loadPage();
  const now = new Date(2026, 10, 26, 11, 30); // a Thursday
  P._setClock(() => now);
  ok(() => assert.equal(KH.flags.DEVICE, true), 'device mode');
  const early = JSON.parse(JSON.stringify(await P.sync()));
  ok(() => assert.deepEqual(early, { skipped: 'not_ready' }), 'nothing is planned before the log is read back');
  await KH.mock.local.boot();
  await settle(sent, 1);
  ok(() => assert.equal(schedules(sent).length, 1), 'the start sends a plan');
  ok(() => assert.deepEqual(schedules(sent)[0].items, []), 'an empty plan with no reminders');

  const lunch = await api.request('POST', '/api/reminders', { kind: 'log_meal', meal: 'lunch', time: '12:00', days: 127, time_zone: 'UTC' });
  await settle(sent, 2);
  let plan = schedules(sent).at(-1).items;
  ok(() => assert.equal(plan.length, 7), 'a lunch reminder every day for 7 days');
  ok(() => assert.deepEqual(plan[0], { id: `reminder-${lunch.id}-2026-11-26`, at: '2026-11-26T12:00', kind: 'log_meal', meal: 'lunch' }), 'today at noon first');
  ok(() => assert.ok(plan.every((x) => Object.keys(x).sort().join() === 'at,id,kind,meal')), 'only the kind and meal are sent: no words');

  await api.request('POST', '/api/log/quick', { date: '2026-11-26', meal: 'lunch', name: 'Oat bar', serving_desc: '1 bar', serving_g: 40, servings: 1,
    nutrients: { calories_kcal: 160, protein_g: 3, carbs_g: 24, potassium_mg: 150, phosphorus_mg: 80, sodium_mg: 90 } });
  const before = schedules(sent).length;
  await KH.mock.local.flush();
  await settle(sent, before + 1);
  plan = schedules(sent).at(-1).items;
  ok(() => assert.equal(plan.length, 6), 'a save after lunch was logged drops today\'s lunch');
  ok(() => assert.equal(plan[0].at, '2026-11-27T12:00'), 'tomorrow\'s lunch is still planned');

  await api.request('PATCH', `/api/reminders/${lunch.id}`, { enabled: false });
  await settle(sent, before + 2);
  ok(() => assert.deepEqual(schedules(sent).at(-1).items, []), 'a reminder turned off is taken out');
  await api.request('DELETE', `/api/reminders/${lunch.id}`);
  const out = await P.sync();
  ok(() => assert.equal(out.ok, true), 'the app answers the plan');

  const doc = await api.request('GET', '/api/me/export.json');
  ok(() => assert.ok(Array.isArray(doc.reminders)), 'reminders are in the export');
  const st = await P.status();
  ok(() => assert.equal(st.permission, 'allowed'), 'status asks the app');
  const test = await P.test();
  ok(() => assert.equal(test.ok, true), 'a test asks the app');
}

// 3. Asking for permission: a plan follows once allowed.
{
  const { KH, sent, P, app } = loadPage({ permission: 'not_asked' });
  await KH.mock.local.boot();
  await settle(sent, 1);
  const n = schedules(sent).length;
  const out = await P.allow();
  ok(() => assert.equal(out.permission, 'allowed'), 'allowed after asking');
  ok(() => assert.equal(schedules(sent).length, n + 1), 'and planned at once');
  app.permission = 'denied';
  const refused = await P.status();
  ok(() => assert.equal(refused.permission, 'denied'), 'a refusal is reported');
  const noTest = await P.test();
  ok(() => assert.equal(noTest.error, 'not_allowed'), 'no test when not allowed');
}

// 4. Outside device mode nothing is asked, and the demo still works as before.
{
  const { KH, api, sent, P } = loadPage({ device: false });
  ok(() => assert.equal(KH.flags.DEVICE, false), 'the online demo');
  await api.request('POST', '/api/reminders', { kind: 'weigh_in', time: '07:00', days: 127, time_zone: 'UTC' });
  const none = JSON.parse(JSON.stringify(await P.sync()));
  ok(() => assert.deepEqual(none, { skipped: 'not_device' }), 'no plan outside the iPhone app');
  await wait(400);
  ok(() => assert.equal(sent.length, 0), 'the bridge is never asked');
}

console.log(`phone reminders: ${checks} checks passed`);
