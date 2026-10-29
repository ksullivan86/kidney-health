// Runs Settings → Account → Signed-in devices of app/static/js/views/settings.js (loadDevices, cut out between passwordForm and
// the data block, like tests/js/admin_frame.test.mjs) on a fake page: a slow older load that answers after a device was signed
// out must not show that device again. Only the newest load draws.
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import test from 'node:test';
import { makePage, deferred, settle } from './fake_page.mjs';

const source = readFileSync(new URL('../../app/static/js/views/settings.js', import.meta.url), 'utf8');
const marker = '    return details;\n  }\n';
const start = source.indexOf(marker, source.indexOf('  function passwordForm(')) + marker.length;
const end = source.indexOf('  // The online demo keeps its data in this browser');
assert.ok(start > marker.length && end > start, 'the signed-in devices markers are in settings.js');
const code = source.slice(start, end);

const laptop = { id: 'a', current: true, user_agent: 'Laptop', last_seen_at: '2026-10-29T10:00:00Z', created_at: '2026-10-01T10:00:00Z' };
const phone = { id: 'b', current: false, user_agent: 'Phone', last_seen_at: '2026-10-28T10:00:00Z', created_at: '2026-10-02T10:00:00Z' };

function setup() {
  const page = makePage();
  const { $, h } = page;
  const reads = [];
  const revokes = [];
  const action = (label, cls, fn, attrs = {}) => {
    const btn = h('button', { class: `btn ${cls}`, type: 'button', ...attrs }, label);
    btn.addEventListener('click', () => fn(btn));
    return btn;
  };
  const context = vm.createContext({
    h, clear: page.clear, $, document: page.document, toast() {}, action, authMode: () => 'local', KH: { auth: { signOut() {} } },
    failed: (err) => h('p', { class: 'form-error' }, `Could not load this: ${err.message}`),
    deviceName: (ua) => ua, relTime: (t) => t, fmtDate: (t) => t,
    A: {
      sessions: () => { const d = deferred(); reads.push(d); return d.promise; },
      revokeSession: (id) => { const d = deferred(); revokes.push({ id, ...d }); return d.promise; },
      revokeOthers: () => Promise.resolve({ revoked: 0 }),
    },
    console, Promise,
  });
  vm.runInContext(`${code}\nglobalThis.loadDevices = loadDevices;`, context);
  const box = $('#set-devices');
  const shown = () => page.find(box, (e) => e.classList.contains('row-title')).map((e) => page.text(e).replace('This device', '').trim());
  return { page, box, context, reads, revokes, shown };
}

test('a slow older load that answers after a device was signed out does not show it again', async () => {
  const s = setup();
  s.context.loadDevices();
  s.reads[0].resolve({ sessions: [laptop, phone] });
  await settle();
  assert.deepEqual(s.shown(), ['Laptop', 'Phone']);
  s.context.loadDevices(); // for example after changing the password: this read is slow
  s.page.find(s.box, (e) => e.tag === 'button' && /Sign out Phone/.test(e.attrs['aria-label'] || ''))[0].click();
  await settle();
  s.revokes[0].resolve(null);
  await settle();
  s.reads[2].resolve({ sessions: [laptop] });
  await settle();
  assert.deepEqual(s.shown(), ['Laptop']);
  s.reads[1].resolve({ sessions: [laptop, phone] });
  await settle();
  assert.deepEqual(s.shown(), ['Laptop'], 'the signed-out phone does not come back');
});

for (const order of ['newest first', 'oldest first']) {
  test(`two loads answered ${order} show the newest list`, async () => {
    const s = setup();
    s.context.loadDevices();
    s.context.loadDevices();
    const [older, newer] = s.reads;
    if (order === 'newest first') { newer.resolve({ sessions: [laptop] }); await settle(); older.resolve({ sessions: [laptop, phone] }); }
    else { older.resolve({ sessions: [laptop, phone] }); await settle(); newer.resolve({ sessions: [laptop] }); }
    await settle();
    assert.deepEqual(s.shown(), ['Laptop']);
  });
}

test('an older load that fails after the newer one drew does not replace the list', async () => {
  const s = setup();
  s.context.loadDevices();
  s.context.loadDevices();
  s.reads[1].resolve({ sessions: [laptop, phone] });
  await settle();
  s.reads[0].reject(new Error('Timed out'));
  await settle();
  assert.deepEqual(s.shown(), ['Laptop', 'Phone']);
  assert.doesNotMatch(s.page.text(s.box), /Could not load/);
});

test('the newest load that fails says so', async () => {
  const s = setup();
  s.context.loadDevices();
  s.reads[0].reject(new Error('Network down'));
  await settle();
  assert.match(s.page.text(s.box), /Could not load this: Network down/);
});
