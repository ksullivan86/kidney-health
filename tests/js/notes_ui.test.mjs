// Runs the real js/views/notes.js on a fake page (design note 37): the words it shows, the Today card, the person's Notes view
// marking each shown note read with the version on screen (a 412 loads the list again), Delete, the writer's view with Edit and
// Withdraw only while unread, Write a note with what is in view filled in, and the Visit prep line that counts the period.
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import test from 'node:test';
import { makePage, deferred, settle } from './fake_page.mjs';

const source = readFileSync(new URL('../../app/static/js/views/notes.js', import.meta.url), 'utf8');

const note = (id, extra = {}) => ({ id, from: { name: 'Dee', removed: false }, area: null, date: null, body: `Note ${id}`, version: 1,
  created_at: '2026-11-10T14:05:00.000000Z', edited_at: null, read_at: null, ...extra });

function setup() {
  const page = makePage();
  const requests = [];
  const shown = [];
  const toasts = [];
  const KH = {
    h: page.h, $: page.$, clear: page.clear, state: { view: 'today' }, flags: { MOCK: false }, views: {},
    util: { parseDate: (s) => { const [y, m, d] = s.split('-').map(Number); return new Date(y, m - 1, d); },
      todayStr: () => '2026-11-12', addDays: (s, n) => { const d = new Date(`${s}T12:00:00Z`); d.setUTCDate(d.getUTCDate() + n); return d.toISOString().slice(0, 10); } },
    request: (method, path, body, opts) => { const d = deferred(); requests.push({ method, path, body, opts, ...d }); return d.promise; },
    toast: (t) => toasts.push(t), toastError() {},
    confirm: { inline: (_box, _btn, o) => o.onConfirm() },
    sheets: { setup() {}, open: (dlg) => { dlg.open = true; } },
    router: { views: {}, register(name, fn) { this.views[name] = fn; }, show(name) { shown.push(name); KH.state.view = name; if (this.views[name]) this.views[name](); },
      openDay(d) { shown.push(`day:${d}`); } },
  };
  page.$('#view-notes');
  page.$('#sheet-note').close = function close() { this.open = false; this.fire('close'); };
  const context = vm.createContext({ window: { KH }, document: page.document, console, setTimeout, clearTimeout });
  vm.runInContext(source, context, { filename: 'notes.js' });
  const next = (method, path) => {
    const r = requests.find((x) => !x.done && x.method === method && x.path === path);
    assert.ok(r, `a ${method} ${path} is waiting (have: ${requests.filter((x) => !x.done).map((x) => `${x.method} ${x.path}`).join(', ')})`);
    r.done = true;
    return r;
  };
  const fail = (status, detail, extra = {}) => Object.assign(new Error(detail), { status, detail, ...extra });
  return { page, KH, N: KH.notes, requests, next, shown, toasts, fail };
}

test('the words: what a note is about, who wrote it, read or not, the Today card and the counter', () => {
  const { N } = setup();
  assert.equal(N.aboutText({ date: null, area: 'labs' }), 'About your lab results');
  assert.equal(N.aboutText({ date: null, area: 'food' }, "Ana's"), "About Ana's food log");
  assert.match(N.aboutText({ date: '2026-11-10', area: 'food' }), /^About Tuesday, Nov 10, 2026, your food log$/);
  assert.equal(N.aboutText({ date: null, area: null }), null);
  assert.equal(N.fromText(note(1)), 'Dee');
  assert.equal(N.fromText(note(1, { from: { name: 'Dee', removed: true } })), 'Dee (account removed)');
  assert.equal(N.readText(note(1)), 'Not read yet');
  assert.match(N.readText(note(1, { read_at: '2026-11-12T09:00:00Z' })), /^Read on Nov 12, 2026$/);
  assert.equal(N.newNotesText(1, ['Dee']), '1 new note from Dee');
  assert.equal(N.newNotesText(2, ['Dee', 'Dee']), '2 new notes from Dee');
  assert.equal(N.newNotesText(2, ['Dee', 'Sam']), '2 new notes from Dee and Sam');
  assert.equal(N.newNotesText(3, ['Dee', 'Sam', 'Lee']), '3 new notes from your Care team');
  assert.equal(N.counterText('abc'), '3 of 1,000 characters');
  assert.equal(N.counterText('😀'), '1 of 1,000 characters');
  assert.equal(N.countInPeriod([note(1), note(2, { created_at: '2026-10-01T00:00:00Z' })], '2026-10-30', '2026-11-12'), 1);
  assert.equal(N.periodText(2), '2 notes from your Care team in this period');
});

test('the Today card shows only unread notes, and Read opens the Notes view', async () => {
  const s = setup();
  const box = s.page.$('#today-notes');
  s.N.todayCard();
  s.next('GET', '/api/me/notes').resolve({ enabled: true, unread: 0, notes: [note(1, { read_at: 'x' })] });
  await settle();
  assert.equal(box.hidden, true);
  s.N.todayCard();
  s.next('GET', '/api/me/notes').resolve({ enabled: true, unread: 1, notes: [note(2)] });
  await settle();
  assert.equal(box.hidden, false);
  assert.match(s.page.text(box), /1 new note from Dee/);
  s.page.button(box, 'Read').click();
  assert.deepEqual(s.shown, ['notes']);
  s.next('GET', '/api/me/notes').resolve({ enabled: true, unread: 0, notes: [] }); // the Notes view's own list
  await settle();
  s.N.todayCard();
  s.next('GET', '/api/me/notes').resolve({ enabled: false, unread: 0, notes: [] });
  await settle();
  assert.equal(box.hidden, true);
});

test('showing notes marks each unread one read with its version, and a 412 loads the list again', async () => {
  const s = setup();
  s.N.openOwn('today');
  s.next('GET', '/api/me/notes').resolve({ enabled: true, unread: 2, notes: [note(2), note(1, { read_at: '2026-11-11T00:00:00Z' })] });
  await settle();
  const list = s.page.$('#notes-list');
  assert.match(s.page.text(list), /Note 2/);
  assert.match(s.page.text(list), /not a medical record/);
  const read = s.next('POST', '/api/me/notes/2/read');
  assert.equal(read.opts.ifMatch, '1');
  read.reject(s.fail(412, 'This note was changed since you opened it.'));
  await settle();
  s.next('GET', '/api/me/notes').resolve({ enabled: true, unread: 1, notes: [note(2, { version: 2, body: 'Changed text' })] });
  await settle();
  assert.match(s.page.text(list), /Changed text/);
  assert.equal(s.next('POST', '/api/me/notes/2/read').opts.ifMatch, '2');
  assert.ok(s.toasts.some((t) => /changed while it was on screen/.test(t)));
});

test('the person deletes a note, and a note about labs opens Labs', async () => {
  const s = setup();
  s.N.openOwn('settings');
  s.next('GET', '/api/me/notes').resolve({ enabled: true, unread: 0, notes: [note(5, { area: 'labs', read_at: 'x' })] });
  await settle();
  const list = s.page.$('#notes-list');
  s.page.button(list, 'About your lab results').click();
  assert.equal(s.shown.at(-1), 'labs');
  s.page.find(list, (e) => e.tag === 'button' && e.attrs['aria-label'] === 'Delete the note from Dee')[0].click();
  await settle();
  s.next('DELETE', '/api/me/notes/5').resolve(null);
  await settle();
  s.next('GET', '/api/me/notes').resolve({ enabled: true, unread: 0, notes: [] });
  await settle();
  assert.match(s.page.text(list), /No notes from your Care team/);
  assert.equal(s.page.$('#notes-back').textContent, 'Back to Settings');
});

test('the writer sees read or not, and Edit and Withdraw only while unread', async () => {
  const s = setup();
  s.N.openAuthor({ id: 3, name: 'Ana', username: 'ana', areas: ['food', 'labs'] });
  s.next('GET', '/api/shared/3/notes').resolve({ notes: [note(8, { read_at: null }), note(7, { read_at: '2026-11-11T10:00:00Z' })] });
  await settle();
  const list = s.page.$('#notes-list');
  assert.equal(s.page.$('#notes-title').textContent, 'Your notes for Ana');
  const cards = s.page.find(list, (e) => e.tag === 'article');
  assert.match(s.page.text(cards[0]), /Not read yet/);
  assert.ok(s.page.button(cards[0], 'Edit') && s.page.button(cards[0], 'Withdraw'));
  assert.match(s.page.text(cards[1]), /Read on/);
  assert.equal(s.page.button(cards[1], 'Edit'), null);
  assert.equal(s.page.button(cards[1], 'Withdraw'), null);
  s.page.button(cards[0], 'Withdraw').click();
  await settle();
  assert.equal(s.next('DELETE', '/api/shared/3/notes/8').opts.ifMatch, '1');
});

test('Write a note fills in what is in view, sends plain text and says why it was refused', async () => {
  const s = setup();
  const ana = { id: 3, name: 'Ana', areas: ['food'], may_note: true };
  s.N.noteButton('visit-note-actions', 'visit-write-note', ana, () => ({ area: 'food', date: '2026-11-10' }));
  assert.equal(s.page.$('#visit-note-actions').hidden, false);
  s.page.$('#visit-write-note').click();
  assert.equal(s.page.$('#sheet-note').open, true);
  assert.equal(s.page.$('#note-area').value, 'food');
  assert.equal(s.page.$('#note-date').value, '2026-11-10');
  assert.equal(s.page.$('#note-send').textContent, 'Send to Ana');
  assert.match(s.page.$('#note-what').textContent, /not a medical record/);
  s.page.$('#note-send').click();
  assert.match(s.page.$('#note-error').textContent, /Write the note first/);
  s.page.$('#note-body').value = '  Take 2 units  ';
  s.page.$('#note-send').click();
  const sent = s.next('POST', '/api/shared/3/notes');
  assert.deepEqual(JSON.parse(JSON.stringify(sent.body)), { body: 'Take 2 units', area: 'food', date: '2026-11-10' });
  sent.reject(s.fail(400, 'Notes cannot be about lows, insulin or doses. Talk to Ana directly about those.'));
  await settle();
  assert.match(s.page.$('#note-error').textContent, /cannot be about lows/);
  assert.equal(s.page.$('#sheet-note').open, true);
  s.page.$('#note-body').value = 'Rice instead of potato worked well.';
  s.page.$('#note-send').click();
  s.next('POST', '/api/shared/3/notes').resolve(note(9));
  await settle();
  assert.equal(s.page.$('#sheet-note').open, false);
  assert.ok(s.toasts.includes('Note sent to Ana'));
  s.N.noteButton('visit-note-actions', 'visit-write-note', { id: 4, name: 'Kim', may_note: false }, null);
  assert.equal(s.page.$('#visit-note-actions').hidden, true);
});

test('Visit prep: a screen-only line counts the notes of the period, and none on a shared page', async () => {
  const s = setup();
  const line = s.page.$('#visit-notes-line');
  s.N.visitLine({ start: '2026-10-30', end: '2026-11-12' }, false);
  s.next('GET', '/api/me/notes').resolve({ enabled: true, unread: 0, notes: [note(1), note(2), note(3, { created_at: '2026-09-01T00:00:00Z' })] });
  await settle();
  assert.equal(line.hidden, false);
  assert.match(s.page.text(line), /^2 notes from your Care team in this period\. Read them$/);
  await s.N.visitLine({ start: '2026-10-30', end: '2026-11-12' }, true);
  assert.equal(line.hidden, true);
  assert.equal(s.requests.filter((r) => !r.done).length, 0);
});
