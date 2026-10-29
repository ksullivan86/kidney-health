#!/usr/bin/env node
// A change made while the outbox is sending (ARCHITECTURE.md "Offline edits and deletes", "Changes made while a send is on
// its way"). The real js/offline.js and js/core.js run in the demo's V8 context (tests/js/demo_loader.mjs) with the demo API as
// the server. A held request is applied by the server at once (it got the body), but its answer only comes back when the test
// lets it go: that is the moment a person can still edit or delete the entry on this device.
//
//   node tests/js/outbox_inflight.test.mjs        # exit 0 when every check passes
//
// What it pins: an entry made offline and edited (or deleted) while its batch, or its quick add, is on its way ends up on the
// server as the person left it; a second edit of an entry while the first edit's PUT is on its way is applied too; an answer
// that is lost after the server got the entry, and an edit made before it is sent again, still ends with the edit; a low
// treatment is never held back or dropped. Python runs this file from tests/test_outbox_inflight.py.
import { isDeepStrictEqual } from 'node:util';
import { loadDemo, newDemo } from './demo_loader.mjs';

let checks = 0;
const failures = [];
const plain = (v) => JSON.parse(JSON.stringify(v === undefined ? null : v));
function expect(label, got, want) {
  checks += 1;
  if (!isDeepStrictEqual(plain(got), plain(want))) failures.push({ label, got: plain(got), want: plain(want) });
}

async function scenario(name, run) {
  const nav = { userAgent: 'node', onLine: true };
  const KH = loadDemo({ extra: ['js/offline.js'], navigator: nav });
  const api = newDemo(KH);
  api._entries = []; api._nextEntryId = 1;
  KH.state.me = { id: 1, username: 'demo' };
  const date = KH.util.todayStr();
  const food = api.handle('GET', '/api/foods?q=apple&limit=1').foods[0];
  const calls = [];
  // hold('POST /api/log/batch') → { reached, release(), lose() }: the next such request is applied by the server now and
  // answered when released (or answered with a 503 by lose(): the server has it, the device never hears).
  const holds = [];
  function hold(what) {
    let reached; let open;
    const h = { what, reached: new Promise((r) => { reached = r; }), gate: new Promise((r) => { open = r; }) };
    h.arrive = reached;
    h.release = () => open('answer');
    h.lose = () => open('lose');
    holds.push(h);
    return h;
  }
  const request = api.request.bind(api);
  api.request = async (method, path, body, headers) => {
    calls.push(`${method} ${path}`);
    const at = holds.findIndex((h) => h.what === `${method} ${path}`);
    if (at < 0) return request(method, path, body, headers);
    const [h] = holds.splice(at, 1);
    const sent = body === undefined ? undefined : JSON.parse(JSON.stringify(body)); // what went over the wire
    const res = api.handle(method, path, sent, headers);
    h.arrive();
    if ((await h.gate) === 'lose') throw new KH.mock.ApiError(503, 'the answer was lost');
    return res == null ? res : JSON.parse(JSON.stringify(res));
  };
  const onServer = () => api._entries.map((row) => api._entryView(row));
  try {
    await run({ KH, api, nav, date, food, hold, calls, onServer });
  } catch (e) {
    checks += 1;
    failures.push({ label: `${name}: threw`, got: String((e && e.stack) || e), want: 'no exception' });
  }
}

await scenario('an entry made offline and edited while its batch is on its way', async ({ KH, nav, date, food, hold, onServer }) => {
  nav.onLine = false;
  const made = await KH.request('POST', '/api/log', { date, meal: 'lunch', food_id: food.id, servings: 1 });
  expect('made offline: a waiting entry', String(made.id).startsWith('pending:'), true);
  nav.onLine = true;
  const h = hold('POST /api/log/batch');
  const run = KH.offline.syncNow();
  await h.reached;
  const edited = await KH.api.updateEntry(made.id, { servings: 3, note: 'more' }, made);
  expect('the edit is taken while the batch is on its way', [edited.servings, edited.note, edited.pending], [3, 'more', true]);
  h.release();
  await run;
  await KH.offline.syncNow();
  expect('the server has one entry, as the person left it', onServer().map((e) => [e.food_id, e.servings, e.note]), [[food.id, 3, 'more']]);
  expect('nothing waits', (await KH.offline.items()).length, 0);
});

await scenario('an entry made offline and deleted while its batch is on its way', async ({ KH, nav, date, food, hold, onServer }) => {
  nav.onLine = false;
  const made = await KH.request('POST', '/api/log', { date, meal: 'lunch', food_id: food.id, servings: 1 });
  const kept = await KH.request('POST', '/api/log', { date, meal: 'dinner', food_id: food.id, servings: 2 });
  nav.onLine = true;
  const h = hold('POST /api/log/batch');
  const run = KH.offline.syncNow();
  await h.reached;
  const removed = await KH.api.deleteEntry(made.id, made);
  expect('the delete is taken', removed, null);
  const day = await KH.api.day(date);
  expect('while it waits, the day does not show the deleted entry, and shows the other one once',
    day.entries.map((e) => [e.meal, e.servings]), [['dinner', 2]]);
  h.release();
  await run;
  await KH.offline.syncNow();
  expect('the server keeps only the entry that was not deleted', onServer().map((e) => [e.meal, e.servings]), [['dinner', 2]]);
  expect('nothing waits', (await KH.offline.items()).length, 0);
  expect('the kept one is the one made offline', onServer()[0].client_id, String(kept.id).slice('pending:'.length));
});

await scenario('a quick add edited while it is on its way', async ({ KH, nav, date, hold, onServer }) => {
  nav.onLine = false;
  const made = await KH.api.quick({ date, meal: 'snack', name: 'Soup', serving_g: 250, nutrients: { calories_kcal: 120 }, servings: 1 });
  nav.onLine = true;
  const h = hold('POST /api/log/quick');
  const run = KH.offline.syncNow();
  await h.reached;
  await KH.api.updateEntry(made.id, { servings: 2, meal: 'dinner' }, made);
  h.release();
  await run;
  await KH.offline.syncNow();
  expect('the server has the edited quick add', onServer().map((e) => [e.food_name, e.servings, e.meal]), [['Soup', 2, 'dinner']]);
  expect('nothing waits', (await KH.offline.items()).length, 0);
});

await scenario('a quick add deleted while it is on its way', async ({ KH, nav, date, hold, onServer }) => {
  nav.onLine = false;
  const made = await KH.api.quick({ date, meal: 'snack', name: 'Soup', serving_g: 250, nutrients: { calories_kcal: 120 }, servings: 1 });
  nav.onLine = true;
  const h = hold('POST /api/log/quick');
  const run = KH.offline.syncNow();
  await h.reached;
  await KH.api.deleteEntry(made.id, made);
  h.release();
  await run;
  await KH.offline.syncNow();
  expect('the server has no entry left', onServer().length, 0);
  expect('nothing waits', (await KH.offline.items()).length, 0);
});

await scenario('the answer is lost after the server got the entry, and the person edits it before it is sent again', async ({ KH, nav, date, food, hold, onServer, calls }) => {
  nav.onLine = false;
  const made = await KH.request('POST', '/api/log', { date, meal: 'lunch', food_id: food.id, servings: 1 });
  nav.onLine = true;
  const h = hold('POST /api/log/batch');
  const run = KH.offline.syncNow();
  await h.reached;
  h.lose();
  const first = await run;
  expect('the run stops and the entry still waits', [first.stopped, (await KH.offline.items()).length], [true, 1]);
  await KH.api.updateEntry(made.id, { servings: 4 }, made);
  calls.length = 0;
  await KH.offline.syncNow();
  expect('sent again, then the edit', calls.filter((c) => !c.startsWith('GET')), ['POST /api/log/batch', `PUT /api/log/${onServer()[0].id}`]);
  expect('one entry, with the edit', onServer().map((e) => e.servings), [4]);
  expect('nothing waits', (await KH.offline.items()).length, 0);
});

await scenario('an entry made offline and sent without changes: one request, nothing more', async ({ KH, nav, date, food, calls, onServer }) => {
  nav.onLine = false;
  await KH.request('POST', '/api/log', { date, meal: 'lunch', food_id: food.id, grams: 123.45 });
  nav.onLine = true;
  calls.length = 0;
  const r = await KH.offline.syncNow();
  expect('one batch, no follow-up', [r.sent, calls.filter((c) => !c.startsWith('GET'))], [1, ['POST /api/log/batch']]);
  expect('the server has it', onServer().length, 1);
});

await scenario('a second edit while the first edit is on its way', async ({ KH, api, nav, date, hold }) => {
  const a = api.handle('POST', '/api/log/quick', { date, meal: 'lunch', name: 'Oat bar', serving_g: 40, nutrients: { calories_kcal: 160 }, servings: 1 });
  await KH.api.day(date);
  nav.onLine = false;
  const first = await KH.api.updateEntry(a.id, { servings: 2 }, a);
  nav.onLine = true;
  const h = hold(`PUT /api/log/${a.id}`);
  const run = KH.offline.syncNow();
  await h.reached;
  await KH.api.updateEntry(a.id, { note: 'after lunch' }, first);
  h.release();
  await run;
  await KH.offline.syncNow();
  const row = api._entryView(api._entry(a.id));
  expect('both edits are on the server', [row.servings, row.note], [2, 'after lunch']);
  expect('nothing waits, nothing to review', [(await KH.offline.items()).length, KH.offline.counts().conflict], [0, 0]);
});

await scenario('a delete while an edit of the same entry is on its way', async ({ KH, api, nav, date, hold }) => {
  const a = api.handle('POST', '/api/log/quick', { date, meal: 'lunch', name: 'Oat bar', serving_g: 40, nutrients: { calories_kcal: 160 }, servings: 1 });
  await KH.api.day(date);
  nav.onLine = false;
  const first = await KH.api.updateEntry(a.id, { servings: 2 }, a);
  nav.onLine = true;
  const h = hold(`PUT /api/log/${a.id}`);
  const run = KH.offline.syncNow();
  await h.reached;
  await KH.api.deleteEntry(a.id, first);
  h.release();
  await run;
  await KH.offline.syncNow();
  expect('the entry is deleted on the server', api._entry(a.id), null);
  expect('nothing waits, nothing to review', [(await KH.offline.items()).length, KH.offline.counts().conflict], [0, 0]);
});

await scenario('a low treatment edited while it is on its way is sent like any other entry', async ({ KH, nav, date, hold, onServer }) => {
  nav.onLine = false;
  const tablets = await KH.api.quick({ date, meal: 'snack', name: 'Glucose tablets', serving_g: 4, flags: ['hypo_treatment'],
    nutrients: { carbs_g: 4, sugar_g: 4 }, servings: 4 });
  nav.onLine = true;
  const h = hold('POST /api/log/quick');
  const run = KH.offline.syncNow();
  await h.reached;
  expect('the low treatment reached the server at the first send', onServer().map((e) => [e.food_name, e.purpose]), [['Glucose tablets', 'hypo']]);
  await KH.api.updateEntry(tablets.id, { servings: 5, note: '3.6 mmol/L' }, tablets);
  h.release();
  await run;
  await KH.offline.syncNow();
  expect('the server has the edit, still a low treatment', onServer().map((e) => [e.servings, e.note, e.purpose]), [[5, '3.6 mmol/L', 'hypo']]);
  expect('nothing waits', (await KH.offline.items()).length, 0);
});

if (failures.length) {
  for (const f of failures.slice(0, 20)) console.error(`MISMATCH ${f.label}\n   got:  ${JSON.stringify(f.got)}\n   want: ${JSON.stringify(f.want)}`);
  console.error(`\n${failures.length} of ${checks} checks failed (tests/js/outbox_inflight.test.mjs)`);
  process.exit(1);
}
console.log(`outbox in flight: ${checks} checks passed`);
process.exit(0);
