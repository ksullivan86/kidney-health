// The demo's twin of notes from the Care team (js/mock/care.js; app/care_notes.py, design note 37), run in Node: Dee's unread note
// for you, reading it with the version shown (412 after an edit, 428 without one), deleting it, Ana's share writing a note, the
// text check, the area and day checks, Edit and Withdraw only while unread, and the export. The pure parts are also replayed
// against tests/data/care_vectors.json by tests/js/run_vectors.mjs.
import assert from 'node:assert/strict';
import test from 'node:test';
import { loadDemo, newDemo } from './demo_loader.mjs';

function demo() {
  const KH = loadDemo();
  const api = newDemo(KH);
  const call = (method, path, body, headers) => {
    try { return { status: 200, body: JSON.parse(JSON.stringify(api.handle(method, path, body, headers) ?? null)) }; } catch (e) {
      return { status: e.status || 500, detail: e.detail || String(e), extra: e.extra ? JSON.parse(JSON.stringify(e.extra)) : null };
    }
  };
  return { KH, api, call };
}

test('Dee, a Clinician, has one unread note for you; you read it with its version and can delete it', () => {
  const { call } = demo();
  const team = call('GET', '/api/me/shares').body;
  assert.equal(team.notes, true);
  const dee = team.sharing.find((s) => s.name === 'Dee');
  assert.equal(dee.role, 'clinician');
  assert.equal(dee.last_viewed_area, 'labs');
  const mine = call('GET', '/api/me/notes').body;
  assert.equal(mine.enabled, true);
  assert.equal(mine.unread, 1);
  const n = mine.notes[0];
  assert.deepEqual(n.from, { name: 'Dee', removed: false });
  assert.equal(n.area, 'food');
  assert.equal(call('POST', `/api/me/notes/${n.id}/read`).status, 428);
  assert.equal(call('POST', `/api/me/notes/${n.id}/read`, undefined, { 'If-Match': '"9"' }).status, 412);
  assert.equal(call('POST', `/api/me/notes/${n.id}/read`, undefined, { 'If-Match': `"${n.version}"` }).status, 200);
  assert.equal(call('GET', '/api/me/notes').body.unread, 0);
  const exported = call('GET', '/api/me/export.json').body.care_notes;
  assert.deepEqual(Object.keys(exported[0]).sort(), ['area', 'body', 'created_at', 'date', 'edited_at', 'from', 'read_at']);
  assert.equal(call('DELETE', `/api/me/notes/${n.id}`).status, 200);
  assert.equal(call('DELETE', `/api/me/notes/${n.id}`).status, 404);
  assert.deepEqual(call('GET', '/api/me/notes').body.notes, []);
});

test('you write a note for Ana: the checks, and Edit and Withdraw while unread', () => {
  const { call } = demo();
  const ana = call('GET', '/api/shared').body.people.find((p) => p.name === 'Ana');
  assert.equal(ana.may_note, true);
  const refused = call('POST', `/api/shared/${ana.id}/notes`, { body: 'Take 2 units of insulin' });
  assert.equal(refused.status, 400);
  assert.equal(refused.detail, 'Notes cannot be about lows, insulin or doses. Talk to Ana directly about those.');
  assert.equal(call('POST', `/api/shared/${ana.id}/notes`, { body: 'About labs', area: 'labs' }).status, 400); // Ana shares food only
  assert.equal(call('POST', `/api/shared/${ana.id}/notes`, { body: 'Far back', date: '2020-01-01' }).status, 400);
  assert.equal(call('POST', `/api/shared/${ana.id}/notes`, { body: 'x', extra: 1 }).status, 400);
  const sent = call('POST', `/api/shared/${ana.id}/notes`, { body: '  Rice worked well with dinner.  ', area: 'food' });
  assert.equal(sent.status, 200);
  assert.equal(sent.body.body, 'Rice worked well with dinner.');
  assert.equal(call('PUT', `/api/shared/${ana.id}/notes/${sent.body.id}`, { body: 'Again' }).status, 428);
  const edited = call('PUT', `/api/shared/${ana.id}/notes/${sent.body.id}`, { body: 'Rice and carrots worked well.' }, { 'If-Match': '"1"' });
  assert.equal(edited.body.version, 2);
  assert.equal(call('PUT', `/api/shared/${ana.id}/notes/${sent.body.id}`, { body: 'Old' }, { 'If-Match': '"1"' }).status, 412);
  const list = call('GET', `/api/shared/${ana.id}/notes`).body.notes;
  assert.equal(list[0].read_at, null);
  assert.equal(call('DELETE', `/api/shared/${ana.id}/notes/${sent.body.id}`, undefined, { 'If-Match': '"2"' }).status, 200);
  assert.deepEqual(call('GET', `/api/shared/${ana.id}/notes`).body.notes, []);
  // Your own notes list never shows what you wrote for Ana
  assert.ok(call('GET', '/api/me/notes').body.notes.every((n) => n.from.name === 'Dee'));
  // a Viewer you just joined cannot write notes: the one 404
  const lee = call('POST', '/api/shared/invites/4/accept').body;
  assert.equal(call('POST', `/api/shared/${lee.id}/notes`, { body: 'Hello' }).status, 404);
  assert.equal(call('GET', `/api/shared/${lee.id}/notes`).status, 404);
});

test('ten notes a day for one person, counting withdrawn ones', () => {
  const { call } = demo();
  for (let i = 0; i < 10; i += 1) {
    const r = call('POST', '/api/shared/3/notes', { body: `Note ${i}` });
    assert.equal(r.status, 200);
    if (i === 0) assert.equal(call('DELETE', `/api/shared/3/notes/${r.body.id}`).status, 200);
  }
  const r = call('POST', '/api/shared/3/notes', { body: 'Eleven' });
  assert.equal(r.status, 429);
  assert.match(r.detail, /^You have written 10 notes for Ana in the last 24 hours/);
});
