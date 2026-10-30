// Runs the real js/main.js with a stub KH: the "app did not start" notice (index.html #boot-fail) is hidden for good once a
// screen shows, and shown at once with the reason when boot fails, also when an earlier script left KH missing.
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import test from 'node:test';

const MAIN = readFileSync(new URL('../../app/static/js/main.js', import.meta.url), 'utf8');
const settle = () => new Promise((resolve) => setTimeout(resolve, 0));

function element() {
  const classes = new Set();
  return {
    hidden: false, textContent: '', value: '',
    classList: { add: (c) => classes.add(c), contains: (c) => classes.has(c) },
    addEventListener() {},
  };
}

function run({ KH, bootError } = {}) {
  const els = { 'boot-fail': element(), 'boot-fail-reason': element() };
  els['boot-fail-reason'].textContent = "The app's files did not finish loading. Try reloading.";
  const errors = [];
  const window = { KH };
  if (bootError) window.KDL_BOOT_ERROR = bootError;
  const document = { getElementById: (id) => els[id] || null, title: '' };
  const context = vm.createContext({ window, document, location: { hash: '' }, console: { ...console, error: (...a) => errors.push(a), warn() {} } });
  vm.runInContext(MAIN, context, { filename: 'main.js' });
  const notice = els['boot-fail'];
  return { notice, errors, reason: () => els['boot-fail-reason'].textContent, now: () => notice.classList.contains('boot-fail-now') };
}

function stubKH({ boot = async () => false, show = () => {} } = {}) {
  const any = () => {
    const el = element();
    el.focus = () => {};
    return el;
  };
  return {
    $: any, state: { date: '2026-10-30' }, toastError() {},
    router: { VIEWS: ['today'], show },
    flags: { PREVIEW: false, MOCK: false, MOCK_HD: false },
    theme: { apply() {}, stored: () => null },
    auth: { boot },
    views: {},
    loadProfile: async () => ({}),
  };
}

test('a sign-in screen showing hides the notice for good', async () => {
  const r = run({ KH: stubKH() });
  await settle();
  assert.equal(r.notice.hidden, true);
  assert.equal(r.now(), false);
});

test('the first view showing hides the notice', async () => {
  let shown = '';
  const r = run({ KH: stubKH({ boot: async () => true, show: (v) => { shown = v; } }) });
  await settle();
  await settle();
  assert.equal(shown, 'today');
  assert.equal(r.notice.hidden, true);
});

test('a boot that throws shows the notice at once with the reason', async () => {
  const r = run({ KH: stubKH({ boot: async () => { throw new Error('auth.boot is broken.'); } }) });
  await settle();
  assert.equal(r.notice.hidden, false);
  assert.equal(r.now(), true);
  assert.equal(r.reason(), 'The app could not start: auth.boot is broken. Try reloading.');
  assert.equal(r.errors.length, 1);
});

test('a first view that throws shows the notice too', async () => {
  const r = run({ KH: stubKH({ boot: async () => true, show: () => { throw new Error('view failed'); } }) });
  await settle();
  await settle();
  assert.equal(r.now(), true);
  assert.equal(r.reason(), 'The app could not start: view failed. Try reloading.');
});

test('a missing KH is caught, and the first script error of the page is the reason', () => {
  const plain = run({});
  assert.equal(plain.now(), true);
  assert.equal(plain.reason(), 'The app could not start: a part of the app did not load. Try reloading.');
  const named = run({ bootError: 'Uncaught SyntaxError: Unexpected end of input' });
  assert.equal(named.reason(), 'The app could not start: Uncaught SyntaxError: Unexpected end of input. Try reloading.');
});

test('a long reason is cut short', () => {
  const r = run({ bootError: 'x'.repeat(400) });
  assert.ok(r.reason().length < 220, r.reason());
  assert.ok(r.reason().includes('…'));
});
