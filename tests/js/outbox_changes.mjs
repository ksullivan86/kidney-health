#!/usr/bin/env node
// The outbox's queue logic for edits and deletes of log entries (ARCHITECTURE.md "Offline edits and deletes"), run in Node
// against the demo API as the "server": js/offline.js and js/core.js are loaded into the demo's V8 context (the DOM is a
// no-op stand-in, see tests/js/demo_loader.mjs) and the browser going offline is `navigator.onLine = false`.
//
//   node tests/js/outbox_changes.mjs        # exit 0 when every check passes
//
// What it pins: an edit or delete made offline waits and shows in the day; one item per entry (a second edit joins the
// first, a delete replaces it); the edit of an entry that was created offline rewrites the queued create and its delete
// removes it without any request; replay sends If-Match; a 412 keeps the change as a conflict (nothing sent, nothing
// overwritten) until "Keep the saved one" or "Use mine"; a 404 drops the change; a "mark eaten" queued first never makes
// a conflict of a later edit; the profile and targets still need a connection. Python runs this file from
// tests/test_outbox_changes.py. The card itself is drawn in Chromium (tools/e2e/device.py).
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
  const quick = (over = {}) => api.handle('POST', '/api/log/quick', { date, meal: 'lunch', name: 'Oat bar', serving_desc: '1 bar', serving_g: 40,
    nutrients: { calories_kcal: 160, protein_g: 3, carbs_g: 24, potassium_mg: 150, phosphorus_mg: 80, sodium_mg: 90 }, servings: 1, ...over });
  // What the server holds for an entry now (undefined when it is gone).
  const stored = (id) => { const row = api._entry(id); return row ? api._entryView(row) : undefined; };
  const calls = [];
  const seen = {}; // the If-Match each request carried (the last one for a path)
  const handle = api.handle.bind(api);
  api.handle = (method, path, body, headers) => { calls.push(`${method} ${path}`); seen[`${method} ${path}`] = headers ? headers['If-Match'] : undefined; return handle(method, path, body, headers); };
  try {
    await run({ KH, api, nav, date, quick, stored, calls, seen });
  } catch (e) {
    checks += 1;
    failures.push({ label: `${name}: threw`, got: String((e && e.stack) || e), want: 'no exception' });
  }
}
const refused = async (promise) => { try { await promise; return null; } catch (e) { return e; } };

await scenario('an edit made offline waits, shows in the day and is applied once when the server is back', async ({ KH, api, nav, date, quick, stored, seen }) => {
  const a = quick();
  await KH.api.day(date); // the device saves its copy of the day
  nav.onLine = false;
  const res = await KH.api.updateEntry(a.id, { servings: 2, note: 'bigger' }, a);
  expect('queued: the answer is the entry as it will look', [res.id, res.servings, res.note, res.pending, res.version], [a.id, 2, 'bigger', true, a.version]);
  expect('queued: the server is untouched', [stored(a.id).servings, stored(a.id).note], [1, null]);
  expect('queued: the badge counts it as a change', KH.offline.counts(), { pending: 1, failed: 0, conflict: 0, changes: 1 });
  const day = await KH.api.day(date);
  expect('queued: the day shows the new amount, marked waiting, with new totals', [day.entries.map((e) => [e.id, e.servings, e.pending]), day.totals.calories_kcal],
    [[[a.id, 2, true]], 320]);
  const item = (await KH.offline.items())[0];
  expect('queued: the item carries the version the edit was made on and the entry it was made on',
    [item.kind, item.method, item.path, item.entry_id, item.version, item.base.servings], ['edit', 'PUT', `/api/log/${a.id}`, a.id, a.version, 1]);
  nav.onLine = true;
  const r = await KH.offline.syncNow();
  expect('sync: one change sent', [r.sent, r.failed, r.conflicts, r.gone], [1, 0, 0, 0]);
  expect('sync: with If-Match, the version the edit was made on', seen[`PUT /api/log/${a.id}`], `"${a.version}"`);
  expect('sync: the server has the edit', [stored(a.id).servings, stored(a.id).note], [2, 'bigger']);
  expect('sync: nothing waits', [(await KH.offline.items()).length, KH.offline.counts()], [0, { pending: 0, failed: 0, conflict: 0, changes: 0 }]);
});

await scenario('a delete made offline hides the entry and removes it once when the server is back', async ({ KH, api, nav, date, quick, stored }) => {
  const a = quick();
  const b = quick({ name: 'Apple', meal: 'snack' });
  await KH.api.day(date);
  nav.onLine = false;
  const res = await KH.api.deleteEntry(a.id, a);
  expect('queued: a pending marker, not a 204', res, { pending: true });
  const day = await KH.api.day(date);
  expect('queued: the day no longer lists it and its totals are worked out again', [day.entries.map((e) => e.id), day.totals.calories_kcal], [[b.id], 160]);
  expect('queued: the server still has it', !!stored(a.id), true);
  nav.onLine = true;
  const r = await KH.offline.syncNow();
  expect('sync: deleted on the server', [r.sent, !!stored(a.id), !!stored(b.id)], [1, false, true]);
});

await scenario('one change waits per entry: a second edit joins the first, a delete replaces it', async ({ KH, nav, date, quick, stored }) => {
  const a = quick();
  await KH.api.day(date);
  nav.onLine = false;
  await KH.api.updateEntry(a.id, { servings: 2 }, a);
  const view = await KH.api.updateEntry(a.id, { note: 'twice', meal: 'dinner' }, { ...a, servings: 2 }); // the second edit is made on what the first left
  expect('joined: one item with both edits', (await KH.offline.items()).map((i) => [i.kind, i.body, i.version]), [['edit', { servings: 2, note: 'twice', meal: 'dinner' }, a.version]]);
  expect('joined: the answer shows both', [view.servings, view.note, view.meal], [2, 'twice', 'dinner']);
  const gone = await KH.api.deleteEntry(a.id, a);
  expect('replaced: the edit became the delete', [gone, (await KH.offline.items()).map((i) => [i.kind, i.method, i.body, i.version])], [{ pending: true }, [['delete', 'DELETE', null, a.version]]]);
  const again = await refused(KH.api.updateEntry(a.id, { note: 'too late' }, a));
  expect('a deleted entry cannot be edited', again && again.detail, 'This entry no longer exists');
  nav.onLine = true;
  expect('sync: one delete sent', (await KH.offline.syncNow()).sent, 1);
  expect('sync: gone', stored(a.id), undefined);
});

await scenario('an entry created offline: editing rewrites the queued create, deleting removes it with no request', async ({ KH, api, nav, date, calls, stored }) => {
  nav.onLine = false;
  const soup = { date, meal: 'lunch', name: 'Soup', serving_g: 250, nutrients: { calories_kcal: 120, potassium_mg: 300 }, servings: 1 };
  const made = await KH.api.quick(soup);
  expect('created offline: a pending id', String(made.id).startsWith('pending:'), true);
  const view = await KH.api.updateEntry(made.id, { servings: 2, note: 'big bowl', meal: 'dinner', status: 'planned' }, made);
  expect('edited: still one item, still a create', (await KH.offline.items()).map((i) => [i.kind, i.body.servings, i.body.note, i.body.meal, i.body.status]), [['quick', 2, 'big bowl', 'dinner', 'planned']]);
  expect('edited: the answer is the new entry, same id', [view.id, view.servings, view.meal, view.status, view.pending], [made.id, 2, 'dinner', 'planned', true]);
  nav.onLine = true;
  calls.length = 0;
  const r = await KH.offline.syncNow();
  const rows = api._entries.map((e) => [e.servings, e.note, e.meal, e.status]);
  expect('sync: the server got one entry, as edited', [r.sent, rows], [1, [[2, 'big bowl', 'dinner', 'planned']]]);

  nav.onLine = false;
  const other = await KH.api.quick({ ...soup, name: 'Stew' });
  expect('second entry waits', (await KH.offline.items()).length, 1);
  const removed = await KH.api.deleteEntry(other.id, other);
  expect('deleted before it was sent: the answer is a plain 204, nothing waits', [removed, (await KH.offline.items()).length, KH.offline.counts().pending], [null, 0, 0]);
  nav.onLine = true;
  calls.length = 0;
  const idle = await KH.offline.syncNow();
  expect('no request reached the server for it', [idle.sent, calls.filter((c) => c.startsWith('POST') || c.startsWith('DELETE'))], [0, []]);
  expect('and the server never heard of it', api._entries.filter((e) => e.food_name === 'Stew').length, 0);
  expect('an entry that already reached the server cannot be edited as a pending one', (await refused(KH.api.updateEntry(made.id, { servings: 3 }, made))).status, 409);
  expect('the stored entry is as edited', stored(api._entries[0].id).servings, 2);
});

await scenario('a change meets a different entry on the server: kept as a conflict, nothing overwritten', async ({ KH, api, nav, date, quick, stored }) => {
  const a = quick();
  await KH.api.day(date);
  nav.onLine = false;
  await KH.api.updateEntry(a.id, { servings: 2 }, a);
  api.handle('PUT', `/api/log/${a.id}`, { note: 'changed on the phone' }); // the other device saves meanwhile
  const theirs = stored(a.id);
  nav.onLine = true;
  const r = await KH.offline.syncNow();
  expect('sync: nothing sent, one conflict', [r.sent, r.conflicts], [0, 1]);
  expect('the server keeps the other device\'s entry', [stored(a.id).servings, stored(a.id).note, stored(a.id).version], [1, 'changed on the phone', theirs.version]);
  const [item] = await KH.offline.items();
  expect('the item is a conflict holding both sides', [item.state, item.server.note, item.server.version, item.body, item.version], ['conflict', 'changed on the phone', theirs.version, { servings: 2 }, a.version]);
  expect('counts: it needs a decision, and is not retried by itself', KH.offline.counts(), { pending: 0, failed: 0, conflict: 1, changes: 0 });
  expect('a second sync still sends nothing', (await KH.offline.syncNow()).sent, 0);
  const day = await KH.api.day(date);
  expect('Today marks the entry and shows the server\'s version', day.entries.map((e) => [e.servings, e.note, e.pending, e.conflict]), [[1, 'changed on the phone', true, true]]);
  const blocked = await refused(KH.api.updateEntry(a.id, { servings: 3 }, theirs));
  expect('another edit of it waits for the decision', blocked.status, 409);

  await KH.offline.keepSaved(item.client_id);
  expect('Keep the saved one: the change is dropped, the server\'s entry is as it was', [(await KH.offline.items()).length, stored(a.id).servings, stored(a.id).note], [0, 1, 'changed on the phone']);
});

await scenario('"Use mine" sends the change with the version the server has now', async ({ KH, api, nav, date, quick, stored }) => {
  const a = quick();
  await KH.api.day(date);
  nav.onLine = false;
  await KH.api.updateEntry(a.id, { servings: 2 }, a);
  api.handle('PUT', `/api/log/${a.id}`, { note: 'changed on the phone' });
  nav.onLine = true;
  await KH.offline.syncNow();
  const [item] = await KH.offline.items();
  const r = await KH.offline.useMine(item.client_id);
  expect('Use mine: sent, and the person\'s servings are on the server (their decision)', [r.sent, stored(a.id).servings], [1, 2]);
  expect('nothing waits any more', (await KH.offline.items()).length, 0);

  // If the entry changed again after the card was drawn, "Use mine" is a new conflict, never a silent overwrite.
  nav.onLine = false;
  const fresh = stored(a.id);
  await KH.api.updateEntry(a.id, { servings: 4 }, fresh);
  api.handle('PUT', `/api/log/${a.id}`, { note: 'first change' });
  nav.onLine = true;
  await KH.offline.syncNow();
  const [second] = await KH.offline.items();
  api.handle('PUT', `/api/log/${a.id}`, { note: 'second change, after the card was drawn' });
  const again = await KH.offline.useMine(second.client_id);
  expect('Use mine on a card that is out of date: a conflict again', [again.conflicts, stored(a.id).servings, (await KH.offline.items())[0].state], [1, 2, 'conflict']);
  expect('and the card now holds the newest entry', (await KH.offline.items())[0].server.note, 'second change, after the card was drawn');
});

await scenario('only what the person changed is kept, so "Use mine" never rewrites a field they did not touch', async ({ KH, api, nav, date, quick, stored }) => {
  const a = quick({ note: 'original' });
  await KH.api.day(date);
  nav.onLine = false;
  // What the entry sheet sends: the meal, day, status and note whatever was changed, and the amount once it was touched.
  const sheet = { meal: a.meal, note: a.note, status: a.status, date: a.date, servings: 2, grams: null };
  await KH.api.updateEntry(a.id, sheet, a);
  const [item] = await KH.offline.items();
  expect('queued: the amount only', item.body, { servings: 2, grams: null });
  const again = await KH.api.updateEntry(a.id, { meal: a.meal, note: 'original', status: 'eaten', date: a.date }, { ...a, servings: 2 });
  expect('a save that changes nothing queues nothing and leaves the waiting change as it is', [(await KH.offline.items()).map((i) => i.body), again.servings], [[{ servings: 2, grams: null }], 2]);
  api.handle('PUT', `/api/log/${a.id}`, { note: 'written on the phone' }); // another device, another field
  nav.onLine = true;
  const r = await KH.offline.syncNow();
  expect('the other device changed the entry: a conflict, as ever', [r.sent, r.conflicts], [0, 1]);
  const done = await KH.offline.useMine((await KH.offline.items())[0].client_id);
  expect('Use mine puts back the amount and leaves the note the other device wrote', [done.sent, stored(a.id).servings, stored(a.id).note], [1, 2, 'written on the phone']);

  nav.onLine = false;
  const fresh = stored(a.id);
  const none = await KH.api.updateEntry(a.id, { meal: fresh.meal, note: fresh.note, status: fresh.status, date: fresh.date }, fresh);
  expect('nothing changed, nothing waits', [(await KH.offline.items()).length, none.pending], [0, false]);
  const moved = await KH.api.updateEntry(a.id, { meal: 'dinner', note: fresh.note, status: 'planned', date: fresh.date, purpose: 'none' }, fresh);
  expect('a meal and a status change are kept, an unchanged purpose is not', [(await KH.offline.items())[0].body, moved.meal, moved.status], [{ meal: 'dinner', status: 'planned' }, 'dinner', 'planned']);
});

await scenario('a delete that meets a changed entry is a conflict too', async ({ KH, api, nav, date, quick, stored }) => {
  const a = quick();
  await KH.api.day(date);
  nav.onLine = false;
  await KH.api.deleteEntry(a.id, a);
  api.handle('PUT', `/api/log/${a.id}`, { servings: 3 });
  nav.onLine = true;
  const r = await KH.offline.syncNow();
  expect('the entry is still there', [r.conflicts, stored(a.id).servings], [1, 3]);
  const [item] = await KH.offline.items();
  const done = await KH.offline.useMine(item.client_id);
  expect('Use mine on a delete deletes it', [done.sent, stored(a.id)], [1, undefined]);
});

await scenario('a 404 means the entry is gone: the change is dropped', async ({ KH, api, nav, date, quick }) => {
  const a = quick();
  const b = quick({ name: 'Apple' });
  await KH.api.day(date);
  nav.onLine = false;
  await KH.api.updateEntry(a.id, { servings: 2 }, a);
  await KH.api.deleteEntry(b.id, b);
  api.handle('DELETE', `/api/log/${a.id}`); // gone on the other device
  api.handle('DELETE', `/api/log/${b.id}`);
  nav.onLine = true;
  const r = await KH.offline.syncNow();
  expect('both dropped, none kept, none failed', [r.gone, r.failed, r.conflicts, (await KH.offline.items()).length], [2, 0, 0, 0]);
});

await scenario('a "mark eaten" queued first does not make a conflict of the edit made after it', async ({ KH, api, nav, date, quick, stored }) => {
  const a = quick({ status: 'planned' });
  await KH.api.day(date);
  nav.onLine = false;
  await KH.api.markEaten({ date });
  const seen = (await KH.api.day(date)).entries[0];
  expect('the day shows it eaten', [seen.status, seen.pending, seen.version], ['eaten', true, a.version]);
  await KH.api.updateEntry(a.id, { servings: 2 }, seen); // made on the day as shown: eaten, the version the server gave when planned
  nav.onLine = true;
  const r = await KH.offline.syncNow();
  expect('both applied, no conflict', [r.conflicts, r.failed, stored(a.id).status, stored(a.id).servings, (await KH.offline.items()).length], [0, 0, 'eaten', 2, 0]);

  // The same with the edit queued before the mark.
  const b = quick({ status: 'planned', name: 'Pear' });
  await KH.api.day(date);
  nav.onLine = false;
  await KH.api.updateEntry(b.id, { note: 'ripe' }, b);
  await KH.api.markEaten({ date });
  nav.onLine = true;
  const again = await KH.offline.syncNow();
  expect('edit then mark: both applied', [again.conflicts, stored(b.id).status, stored(b.id).note], [0, 'eaten', 'ripe']);

  // An edit that joins one that waits before a mark goes after the mark (the person did it last).
  const c = quick({ status: 'planned', name: 'Plum' });
  await KH.api.day(date);
  nav.onLine = false;
  await KH.api.updateEntry(c.id, { note: 'one' }, c);
  await KH.api.markEaten({ date });
  const eaten = (await KH.api.day(date)).entries.find((e) => e.id === c.id);
  await KH.api.updateEntry(c.id, { status: 'planned' }, eaten);
  nav.onLine = true;
  const last = await KH.offline.syncNow();
  expect('edit, mark, edit back to planned: the last word is the person\'s', [last.conflicts, stored(c.id).status, stored(c.id).note], [0, 'planned', 'one']);
});

await scenario('an edit made online while a change waits joins the queue, so the order holds', async ({ KH, api, nav, date, quick, stored }) => {
  const a = quick();
  await KH.api.day(date);
  nav.onLine = false;
  await KH.api.updateEntry(a.id, { servings: 2 }, a);
  nav.onLine = true; // back, but the sync has not run yet
  await KH.api.updateEntry(a.id, { note: 'online' }, a);
  expect('one item holds both', (await KH.offline.items()).map((i) => i.body), [{ servings: 2, note: 'online' }]);
  await KH.offline.syncNow();
  expect('applied once', [stored(a.id).servings, stored(a.id).note], [2, 'online']);
});

await scenario('online: a stale edit is refused with a 412, kept as a conflict, and nothing is overwritten', async ({ KH, api, date, quick, stored }) => {
  const a = quick();
  await KH.api.day(date);
  api.handle('PUT', `/api/log/${a.id}`, { servings: 3 }); // the other device
  const err = await refused(KH.api.updateEntry(a.id, { note: 'mine' }, a));
  expect('refused, and told so', [err.status, err.conflict, /another device/.test(err.detail)], [412, true, true]);
  expect('the server has only the other device\'s change', [stored(a.id).servings, stored(a.id).note], [3, null]);
  const [item] = await KH.offline.items();
  expect('the person\'s change is kept next to the server\'s entry', [item.state, item.body, item.server.servings], ['conflict', { note: 'mine' }, 3]);
  const del = await refused(KH.api.deleteEntry(a.id, a));
  expect('a delete of it waits for the decision too', del.status, 409);
});

await scenario('an entry saved before entries had versions is compared with the server before it is changed', async ({ KH, api, nav, date, quick, stored, seen }) => {
  const a = quick();
  const b = quick({ name: 'Apple', meal: 'snack' });
  const c = quick({ name: 'Pear', meal: 'snack' });
  const old = (e) => { const copy = { ...e }; delete copy.version; return copy; }; // a copy this device saved before the upgrade
  await KH.api.day(date);
  nav.onLine = false;
  const view = await KH.api.updateEntry(a.id, { servings: 2 }, old(a));
  await KH.api.updateEntry(b.id, { servings: 3 }, old(b));
  await KH.api.deleteEntry(c.id, old(c));
  expect('queued without a version, as the person saw it', [view.servings, (await KH.offline.items()).map((i) => [i.kind, i.version])], [2, [['edit', null], ['edit', null], ['delete', null]]]);
  api.handle('PUT', `/api/log/${b.id}`, { note: 'changed on the phone' }); // another device
  api.handle('DELETE', `/api/log/${c.id}`);
  const given = stored(a.id).version;
  nav.onLine = true;
  const r = await KH.offline.syncNow();
  expect('the unchanged entry is sent with the version the server gave', [r.sent, stored(a.id).servings, seen[`PUT /api/log/${a.id}`]], [1, 2, `"${given}"`]);
  expect('a changed entry is a conflict, not an overwrite', [r.conflicts, stored(b.id).servings, stored(b.id).note], [1, 1, 'changed on the phone']);
  expect('an entry that is gone is dropped', [r.gone, stored(c.id)], [1, undefined]);
});

await scenario('an edit with the matching version online goes straight to the server', async ({ KH, date, quick, stored, calls }) => {
  const a = quick();
  await KH.api.day(date);
  const res = await KH.api.updateEntry(a.id, { servings: 2 }, a);
  expect('applied now, not queued', [res.servings, res.pending === undefined, (await KH.offline.items()).length, stored(a.id).servings], [2, true, 0, 2]);
  const del = await KH.api.deleteEntry(a.id, res);
  expect('delete with the new version', [del, stored(a.id)], [null, undefined]);
  expect('both went to the server', calls.filter((c) => /PUT|DELETE/.test(c)), [`PUT /api/log/${a.id}`, `DELETE /api/log/${a.id}`]);
});

await scenario('the profile and targets still need a connection', async ({ KH, nav }) => {
  nav.onLine = false;
  const err = await refused(KH.api.saveProfile({ weight_kg: 70 }));
  expect('a profile change is refused with the old message', [err && err.status, /needs a connection/.test(String(err && err.detail))], [0, true]);
  expect('and not queued', (await KH.offline.items()).length, 0);
  const targets = await refused(KH.request('PUT', '/api/profile', { targets: { potassium_mg: 4000 } }));
  expect('targets neither', [targets && targets.status, (await KH.offline.items()).length], [0, 0]);
});

await scenario('an edit without the entry it was made on is not queued (there would be no version to check)', async ({ KH, nav, date, quick }) => {
  const a = quick();
  await KH.api.day(date);
  nav.onLine = false;
  const err = await refused(KH.request('PUT', `/api/log/${a.id}`, { servings: 2 }));
  expect('refused with the connection message', [err && err.status, /needs a connection/.test(String(err && err.detail)), (await KH.offline.items()).length], [0, true, 0]);
});

await scenario('a low treatment is edited and deleted offline like any other entry', async ({ KH, api, nav, date, quick, stored }) => {
  const tablets = quick({ name: 'Glucose tablets', flags: ['hypo_treatment'], servings: 4, nutrients: { carbs_g: 16, sugar_g: 16 }, meal: 'snack' });
  expect('it treated a low', tablets.purpose, 'hypo');
  await KH.api.day(date);
  nav.onLine = false;
  const view = await KH.api.updateEntry(tablets.id, { servings: 2, note: '3.4 mmol/L' }, tablets);
  expect('edited offline, no warning or block of any kind', [view.servings, view.purpose, view.pending, (view.warnings || []).length], [2, 'hypo', true, (tablets.warnings || []).length]);
  const gone = quick({ name: 'Juice', flags: ['hypo_treatment'], servings: 1, nutrients: { carbs_g: 12 }, meal: 'snack' });
  nav.onLine = true;
  await KH.api.day(date);
  nav.onLine = false;
  await KH.api.deleteEntry(gone.id, gone);
  nav.onLine = true;
  const r = await KH.offline.syncNow();
  expect('both reach the server', [r.sent, stored(tablets.id).servings, stored(gone.id)], [2, 2, undefined]);
});

await scenario('what waits belongs to the person who made it', async ({ KH, nav, date, quick }) => {
  const a = quick();
  await KH.api.day(date);
  nav.onLine = false;
  await KH.api.updateEntry(a.id, { servings: 2 }, a);
  KH.state.me = { id: 2, username: 'someone else' };
  expect('another person sees nothing waiting', [(await KH.offline.items()).length, (await KH.offline.pendingCount())], [0, 0]);
  KH.state.me = { id: 1, username: 'demo' };
  expect('the first person still does', await KH.offline.pendingCount(), 1);
  await KH.offline.purge();
  expect('signing out clears the queue', [(await KH.offline.items()).length, KH.offline.counts()], [0, { pending: 0, failed: 0, conflict: 0, changes: 0 }]);
});

await scenario('changes queued in the same millisecond still replay in the order they were made', async ({ KH, nav, date, quick, stored }) => {
  // A fast device (or a CI runner) can queue an edit, a "mark eaten" and a second edit within one millisecond. The outbox
  // replays in created_at order, so the stamps must still rise; a tie used to fall back to the store's random key order.
  const inPage = KH.util.todayStr.constructor; // the Function of the page's own context, to reach its globals
  const RealDate = inPage('return Date')();
  const FIXED = RealDate.now();
  class FrozenDate extends RealDate {
    constructor(...args) { if (args.length) super(...args); else super(FIXED); }
    static now() { return FIXED; }
  }
  inPage('d', 'globalThis.Date = d')(FrozenDate); // every clock read in the page is the same millisecond
  try {
    const c = quick({ status: 'planned', name: 'Plum' });
    await KH.api.day(date);
    nav.onLine = false;
    await KH.api.updateEntry(c.id, { note: 'one' }, c);
    await KH.api.markEaten({ date });
    const eaten = (await KH.api.day(date)).entries.find((e) => e.id === c.id);
    await KH.api.updateEntry(c.id, { status: 'planned' }, eaten);
    const stamps = (await KH.offline.items()).map((i) => i.created_at);
    expect('every queued item has its own, rising stamp', [stamps.length, stamps.every((t, i) => i === 0 || t > stamps[i - 1])], [2, true]);
    nav.onLine = true;
    const last = await KH.offline.syncNow();
    expect('replayed in order: the mark first, then the person\'s last edit', [last.conflicts, stored(c.id).status, stored(c.id).note], [0, 'planned', 'one']);
  } finally {
    inPage('d', 'globalThis.Date = d')(RealDate);
  }
});

if (failures.length) {
  for (const f of failures.slice(0, 20)) console.error(`MISMATCH ${f.label}\n   got:  ${JSON.stringify(f.got)}\n   want: ${JSON.stringify(f.want)}`);
  console.error(`\n${failures.length} of ${checks} checks failed (tests/js/outbox_changes.mjs)`);
  process.exit(1);
}
console.log(`outbox changes: ${checks} checks passed`);
process.exit(0);
