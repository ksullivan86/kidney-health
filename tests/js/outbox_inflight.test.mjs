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
// treatment is never held back or dropped. An entry sheet opened before the entry reached the server still saves (or deletes),
// on the server's entry and never as a second entry. Discard, Discard all and "Sign out and lose them" while an entry is being
// sent end with it deleted on the server, or name it when that cannot be done. Python runs this file from
// tests/test_outbox_inflight.py.
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
  // hold(what, { refuse: detail }) instead refuses the request (the server takes nothing) when released.
  function hold(what, { refuse = null } = {}) {
    let reached; let open;
    const h = { what, refuse, reached: new Promise((r) => { reached = r; }), gate: new Promise((r) => { open = r; }) };
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
    if (h.refuse) { h.arrive(); await h.gate; throw new KH.mock.ApiError(400, h.refuse); }
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

await scenario('deleted while on its way, and the answer is lost: the delete still reaches the server', async ({ KH, nav, date, food, hold, onServer, calls }) => {
  nav.onLine = false;
  const made = await KH.request('POST', '/api/log', { date, meal: 'lunch', food_id: food.id, servings: 1 });
  nav.onLine = true;
  const h = hold('POST /api/log/batch');
  const run = KH.offline.syncNow();
  await h.reached;
  await KH.api.deleteEntry(made.id, made);
  h.lose();
  await run;
  const [waiting] = await KH.offline.items();
  expect('the delete waits on this device, and the badge counts it', [!!waiting && waiting.deleted, KH.offline.counts().pending], [true, 1]);
  expect('the day does not show it', (await KH.api.day(date)).entries.length, 0);
  calls.length = 0;
  await KH.offline.syncNow();
  expect('sent again, then deleted', calls.filter((c) => !c.startsWith('GET')).map((c) => c.replace(/\d+$/, 'N')), ['POST /api/log/batch', 'DELETE /api/log/N']);
  expect('the server has no entry', onServer().length, 0);
  expect('nothing waits', (await KH.offline.items()).length, 0);
});

await scenario('deleted while on its way, and the server refuses it: nothing is left anywhere', async ({ KH, nav, date, food, hold, onServer }) => {
  nav.onLine = false;
  const made = await KH.request('POST', '/api/log', { date, meal: 'lunch', food_id: food.id, servings: 1 });
  nav.onLine = true;
  const h = hold('POST /api/log/batch', { refuse: 'entries[0]: food not found' });
  const run = KH.offline.syncNow();
  await h.reached;
  await KH.api.deleteEntry(made.id, made);
  h.release();
  await run;
  expect('nothing on the server, nothing waits, nothing "not saved"', [onServer().length, (await KH.offline.items()).length], [0, 0]);
});

await scenario('edited while on its way, and the server refuses it: kept as "not saved" with the edit', async ({ KH, nav, date, food, hold }) => {
  nav.onLine = false;
  const made = await KH.request('POST', '/api/log', { date, meal: 'lunch', food_id: food.id, servings: 1 });
  nav.onLine = true;
  const h = hold('POST /api/log/batch', { refuse: 'entries[0]: food not found' });
  const run = KH.offline.syncNow();
  await h.reached;
  await KH.api.updateEntry(made.id, { servings: 2 }, made);
  h.release();
  await run;
  const items = await KH.offline.items();
  expect('one item, not saved, with the person\'s edit', items.map((i) => [i.state, i.body.servings]), [['failed', 2]]);
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

// ---------------------------------------------------------------------------------------------------------------------------
// The entry sheet was opened on a waiting entry, and the entry reached the server before the person pressed Save.
// The sheet still holds the waiting entry (id "pending:…"); the change goes to the server's entry, never as a second entry.
// ---------------------------------------------------------------------------------------------------------------------------
const sheetBody = (entry, change) => ({ date: entry.date, meal: entry.meal, status: entry.status, note: entry.note, ...change });

await scenario('the sheet is saved after the entry reached the server: the change is made on the server\'s entry', async ({ KH, nav, date, food, calls, onServer }) => {
  nav.onLine = false;
  const made = await KH.request('POST', '/api/log', { date, meal: 'lunch', food_id: food.id, servings: 1 });
  nav.onLine = true;
  await KH.offline.syncNow(); // the entry reaches the server while the sheet is open
  calls.length = 0;
  let saved = null; let error = null;
  try { saved = await KH.api.updateEntry(made.id, sheetBody(made, { note: 'with tea', servings: 2 }), made); } catch (e) { error = e.detail || e.message; }
  expect('saving the open sheet works', error, null);
  expect('the answer is the server\'s entry', saved && [typeof saved.id, saved.note, saved.servings], ['number', 'with tea', 2]);
  expect('sent as an edit of that entry', calls.filter((c) => !c.startsWith('GET')), [`PUT /api/log/${onServer()[0].id}`]);
  expect('one entry on the server, with the change', onServer().map((e) => [e.servings, e.note]), [[2, 'with tea']]);
  expect('nothing waits', (await KH.offline.items()).length, 0);
});

await scenario('the sheet is saved while the follow-up edit is on its way: the save joins it', async ({ KH, nav, date, food, hold, onServer }) => {
  nav.onLine = false;
  const made = await KH.request('POST', '/api/log', { date, meal: 'lunch', food_id: food.id, servings: 1 });
  nav.onLine = true;
  const batch = hold('POST /api/log/batch');
  const put = hold('PUT /api/log/1');
  const run = KH.offline.syncNow();
  await batch.reached;
  const first = await KH.api.updateEntry(made.id, { servings: 2 }, made); // the batch is on its way: the row gets a follow-up edit
  batch.release();
  await put.reached; // the follow-up edit is on its way now
  let error = null;
  try { await KH.api.updateEntry(made.id, sheetBody(first, { note: 'after a walk' }), first); } catch (e) { error = e.detail || e.message; }
  expect('saving the open sheet works', error, null);
  put.release();
  await run;
  await KH.offline.syncNow();
  expect('one entry on the server, with both changes', onServer().map((e) => [e.servings, e.note]), [[2, 'after a walk']]);
  expect('nothing waits, nothing to review', [(await KH.offline.items()).length, KH.offline.counts().conflict], [0, 0]);
});

await scenario('the sheet is saved after the entry reached the server and another device changed it: a conflict card, nothing overwritten', async ({ KH, api, nav, date, food, onServer }) => {
  nav.onLine = false;
  const made = await KH.request('POST', '/api/log', { date, meal: 'lunch', food_id: food.id, servings: 1 });
  nav.onLine = true;
  await KH.offline.syncNow();
  const id = onServer()[0].id;
  api.handle('PUT', `/api/log/${id}`, { note: 'from the tablet' }); // another device
  let error = null;
  try { await KH.api.updateEntry(made.id, sheetBody(made, { servings: 3 }), made); } catch (e) { error = e; }
  expect('the save says it was changed on another device', !!(error && error.conflict), true);
  expect('the server keeps the other device\'s entry', onServer().map((e) => [e.servings, e.note]), [[1, 'from the tablet']]);
  const items = await KH.offline.items();
  expect('the change waits as a card to decide on', items.map((i) => [i.state, i.entry_id, i.body.servings]), [['conflict', id, 3]]);
});

await scenario('the sheet is saved offline after the entry reached the server: queued as an edit with the server\'s version', async ({ KH, nav, date, food, onServer, calls }) => {
  nav.onLine = false;
  const made = await KH.request('POST', '/api/log', { date, meal: 'dinner', food_id: food.id, servings: 1 });
  nav.onLine = true;
  await KH.offline.syncNow();
  const server = onServer()[0];
  nav.onLine = false;
  let saved = null; let error = null;
  try { saved = await KH.api.updateEntry(made.id, sheetBody(made, { meal: 'snack' }), made); } catch (e) { error = e.detail || e.message; }
  expect('saving the open sheet offline works', [error, saved && saved.pending], [null, true]);
  const items = await KH.offline.items();
  expect('one edit of the server\'s entry waits, with its version', items.map((i) => [i.kind, i.entry_id, i.version]), [['edit', server.id, server.version]]);
  nav.onLine = true;
  calls.length = 0;
  await KH.offline.syncNow();
  expect('sent as an edit, never as a second entry', calls.filter((c) => !c.startsWith('GET')), [`PUT /api/log/${server.id}`]);
  expect('one entry on the server, moved to the snack', onServer().map((e) => e.meal), ['snack']);
});

await scenario('the sheet\'s Delete is used after the entry reached the server: the server\'s entry is deleted', async ({ KH, nav, date, food, onServer }) => {
  nav.onLine = false;
  const made = await KH.request('POST', '/api/log', { date, meal: 'lunch', food_id: food.id, servings: 1 });
  nav.onLine = true;
  await KH.offline.syncNow();
  let error = null;
  try { await KH.api.deleteEntry(made.id, made); } catch (e) { error = e.detail || e.message; }
  expect('deleting from the open sheet works', error, null);
  expect('the server has no entry', onServer().length, 0);
  expect('nothing waits', (await KH.offline.items()).length, 0);
});

await scenario('a low treatment\'s sheet saved after it reached the server is changed like any other entry', async ({ KH, nav, date, onServer }) => {
  nav.onLine = false;
  const tablets = await KH.api.quick({ date, meal: 'snack', name: 'Glucose tablets', serving_g: 4, flags: ['hypo_treatment'],
    nutrients: { carbs_g: 4, sugar_g: 4 }, servings: 4 });
  nav.onLine = true;
  await KH.offline.syncNow();
  let error = null;
  try { await KH.api.updateEntry(tablets.id, sheetBody(tablets, { note: '3.4 mmol/L' }), tablets); } catch (e) { error = e.detail || e.message; }
  expect('saving works', error, null);
  expect('the server has the note, still a low treatment', onServer().map((e) => [e.servings, e.note, e.purpose]), [[4, '3.4 mmol/L', 'hypo']]);
});

// ---------------------------------------------------------------------------------------------------------------------------
// Discard in Settings → This device (and "Sign out and lose them") while the entry is being sent: the server may have it
// already, so it ends deleted there, the way a delete made while it is on its way does.
// ---------------------------------------------------------------------------------------------------------------------------
await scenario('discarded in Settings while its batch is on its way: the entry is not left on the server', async ({ KH, nav, date, food, hold, onServer }) => {
  nav.onLine = false;
  const made = await KH.request('POST', '/api/log', { date, meal: 'lunch', food_id: food.id, servings: 1 });
  nav.onLine = true;
  const h = hold('POST /api/log/batch');
  const run = KH.offline.syncNow();
  await h.reached;
  await KH.offline.discard(String(made.id).slice('pending:'.length));
  expect('the day does not show it', (await KH.api.day(date)).entries.length, 0);
  h.release();
  await run;
  await KH.offline.syncNow();
  expect('the server has no entry', onServer().length, 0);
  expect('nothing waits', (await KH.offline.items()).length, 0);
});

await scenario('discarded after its answer was lost, while offline: it waits as a delete and is deleted once back', async ({ KH, nav, date, food, hold, onServer }) => {
  nav.onLine = false;
  const made = await KH.request('POST', '/api/log', { date, meal: 'lunch', food_id: food.id, servings: 1 });
  nav.onLine = true;
  const h = hold('POST /api/log/batch');
  const run = KH.offline.syncNow();
  await h.reached;
  h.lose();
  await run;
  nav.onLine = false;
  await KH.offline.discard(String(made.id).slice('pending:'.length));
  const items = await KH.offline.items();
  expect('it waits as a delete, and is counted', [items.map((i) => !!i.deleted), KH.offline.counts().pending], [[true], 1]);
  nav.onLine = true;
  await KH.offline.syncNow();
  expect('the server has no entry', onServer().length, 0);
  expect('nothing waits', (await KH.offline.items()).length, 0);
});

await scenario('"Discard all" while a batch is on its way: nothing it held is left on the server, and nothing else is sent', async ({ KH, nav, date, food, hold, onServer, calls }) => {
  nav.onLine = false;
  await KH.request('POST', '/api/log', { date, meal: 'lunch', food_id: food.id, servings: 1 });
  await KH.request('POST', '/api/log', { date, meal: 'dinner', food_id: food.id, servings: 2 });
  await KH.api.quick({ date, meal: 'snack', name: 'Soup', serving_g: 250, nutrients: { calories_kcal: 120 }, servings: 1 });
  nav.onLine = true;
  const h = hold('POST /api/log/batch');
  const run = KH.offline.syncNow();
  await h.reached;
  await KH.offline.discardAll();
  h.release();
  await run;
  await KH.offline.syncNow();
  expect('the server has no entry', onServer().length, 0);
  expect('the quick add was never sent', calls.includes('POST /api/log/quick'), false);
  expect('nothing waits', (await KH.offline.items()).length, 0);
});

await scenario('"Sign out and lose them" while a batch is on its way: the entries are deleted on the server first', async ({ KH, nav, date, food, hold, onServer }) => {
  nav.onLine = false;
  await KH.request('POST', '/api/log', { date, meal: 'lunch', food_id: food.id, servings: 1 });
  nav.onLine = true;
  const h = hold('POST /api/log/batch');
  const run = KH.offline.syncNow();
  await h.reached;
  const lose = KH.offline.loseAll();
  h.release();
  await run;
  const left = await lose;
  expect('nothing is left that may be on the server', (left || []).length, 0);
  expect('the server has no entry', onServer().length, 0);
  expect('nothing waits', (await KH.offline.items()).length, 0);
});

await scenario('"Sign out and lose them" when the delete cannot be done: the app says which entry may be on the server', async ({ KH, nav, date, food, hold, onServer }) => {
  await KH.request('GET', '/api/foods?q=apple&limit=1'); // the device has seen the food, so it knows its name
  nav.onLine = false;
  await KH.request('POST', '/api/log', { date, meal: 'lunch', food_id: food.id, servings: 1 });
  await KH.api.quick({ date, meal: 'snack', name: 'Soup', serving_g: 250, nutrients: { calories_kcal: 120 }, servings: 1 });
  nav.onLine = true;
  const h = hold('POST /api/log/batch');
  const run = KH.offline.syncNow();
  await h.reached;
  h.lose(); // the server has the entry, the device never hears
  await run;
  nav.onLine = false;
  const left = await KH.offline.loseAll();
  expect('the entry that may be on the server is named', (left || []).map((i) => i.name), [food.name]);
  expect('the server still has it (it could not be reached)', onServer().length, 1);
  expect('only that one still waits, as a delete', (await KH.offline.items()).map((i) => !!i.deleted), [true]);
});

if (failures.length) {
  for (const f of failures.slice(0, 20)) console.error(`MISMATCH ${f.label}\n   got:  ${JSON.stringify(f.got)}\n   want: ${JSON.stringify(f.want)}`);
  console.error(`\n${failures.length} of ${checks} checks failed (tests/js/outbox_inflight.test.mjs)`);
  process.exit(1);
}
console.log(`outbox in flight: ${checks} checks passed`);
process.exit(0);
