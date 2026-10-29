// Real Today weight/BP loader with deferred reads and a minimal card DOM.
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import test from 'node:test';

const source = readFileSync(new URL('../../app/static/js/views/body.js', import.meta.url), 'utf8');
const start = source.indexOf('  async function loadToday(date)');
const end = source.indexOf('  // ---- the sheets:', start);
assert.ok(start >= 0 && end > start);
const settle = async () => { for (let i = 0; i < 12; i++) await Promise.resolve(); };
function setup(profile = {}) {
  const calls = { weights: [], bp: [], summary: [], profile: [] };
  const read = (key) => new Promise((resolve, reject) => calls[key].push({ resolve, reject }));
  const todayBody = { children: ['old weight, old blood pressure, old alarm'], append(...items) { this.children.push(...items); } };
  const S = { req: 0, shownDate: '2026-10-29', summary: { old: true }, units: 'lb' };
  const state = { profile };
  const clear = (node) => { node.children = []; return node; };
  const renderToday = (weights, readings, summary) => clear(todayBody).append({ weights, readings, summary });
  const context = vm.createContext({
    S, state, todayBody, clear, renderToday, addWeightBtn: {}, addBpBtn: {},
    todayStr: () => '2026-10-29', NEEDS_CONNECTION: 'Connection needed', message: (t) => t,
    h: (tag, attrs, ...children) => ({ tag, attrs, children }),
    KH: { loadProfile: () => read('profile') },
    api: { bodyWeights: () => read('weights'), bloodPressures: () => read('bp'), bodySummary: () => read('summary') },
  });
  vm.runInContext(source.slice(start, end), context);
  const resolve = (i, marker) => {
    calls.weights[i].resolve({ weights: [marker] }); calls.bp[i].resolve({ readings: [marker] });
    calls.summary[i].resolve({ marker, units: 'kg' });
  };
  return { context, S, calls, body: todayBody, resolve, load: (date) => context.loadToday(date) };
}

test('switching dates clears old measurements and alarm before the read resolves', async () => {
  const s = setup(), pending = s.load('2026-10-28');
  assert.match(JSON.stringify(s.body.children), /Loading/);
  assert.doesNotMatch(JSON.stringify(s.body.children), /old weight|old alarm|old blood/);
  assert.equal(s.S.summary, null);
  s.resolve(0, 'yesterday'); await pending;
  assert.match(JSON.stringify(s.body.children), /yesterday/);
});
test('old rows are cleared even while an uncached Profile read is waiting', async () => {
  const s = setup(null), pending = s.load('2026-10-28');
  assert.doesNotMatch(JSON.stringify(s.body.children), /old weight/);
  s.calls.profile[0].resolve({}); await settle();
  s.resolve(0, 'new date'); await pending;
});
test('a genuine failure shows Retry without stale measurements', async () => {
  const s = setup(), pending = s.load('2026-10-28');
  s.calls.weights[0].reject({ status: 500 }); s.calls.bp[0].resolve({ readings: [] }); s.calls.summary[0].resolve({});
  await pending;
  assert.match(JSON.stringify(s.body.children), /could not be loaded|Try again/);
  assert.doesNotMatch(JSON.stringify(s.body.children), /old weight|old alarm/);
  assert.equal(s.S.summary, null);
});
test('a handled failure still leaves a recoverable empty card', async () => {
  const s = setup(), pending = s.load('2026-10-28');
  s.calls.weights[0].reject({ status: 401, handled: true }); s.calls.bp[0].resolve({ readings: [] }); s.calls.summary[0].resolve({});
  await pending;
  assert.match(JSON.stringify(s.body.children), /Try again/);
  assert.doesNotMatch(JSON.stringify(s.body.children), /old weight|Loading/);
});
test('a slow older success cannot replace the newest day', async () => {
  const s = setup(), old = s.load('2026-10-28'), current = s.load('2026-10-29');
  s.resolve(1, 'newest'); await current;
  s.resolve(0, 'old reply'); await old;
  assert.match(JSON.stringify(s.body.children), /newest/);
  assert.doesNotMatch(JSON.stringify(s.body.children), /old reply/);
  assert.equal(s.S.summary.marker, 'newest');
});
test('a slow older failure cannot replace the newest day with an error', async () => {
  const s = setup(), old = s.load('2026-10-28'), current = s.load('2026-10-29');
  s.resolve(1, 'newest'); await current;
  s.calls.weights[0].reject({ status: 500 }); s.calls.bp[0].resolve({ readings: [] }); s.calls.summary[0].resolve({});
  await old;
  assert.match(JSON.stringify(s.body.children), /newest/);
  assert.doesNotMatch(JSON.stringify(s.body.children), /Try again/);
});
test('a future day clears the summary and invalidates an earlier pending read', async () => {
  const s = setup(), old = s.load('2026-10-28');
  await s.load('2026-10-30');
  s.resolve(0, 'old reply'); await old;
  assert.equal(s.S.summary, null);
  assert.match(JSON.stringify(s.body.children), /days that have passed/);
  assert.doesNotMatch(JSON.stringify(s.body.children), /old reply/);
});

const todaySource = readFileSync(new URL('../../app/static/js/views/today.js', import.meta.url), 'utf8');
const loadStart = todaySource.indexOf('  let dayRequest = 0;');
const loadEnd = todaySource.indexOf('  /** The chosen day', loadStart);
assert.ok(loadStart >= 0 && loadEnd > loadStart);
for (const failed of [false, true]) {
  test(`weight/BP starts before food and is not restarted when food ${failed ? 'fails' : 'loads'}`, async () => {
    const calls = [];
    let resolve, reject;
    const context = vm.createContext({
      state: { date: '2026-10-28', dayLoadedFor: null },
      dateInput: {}, dateLabel: {}, backToToday: {}, mealsEl: { style: {} },
      fmtDateLong: (date) => date, todayStr: () => '2026-10-29', loadWeekStrip() {}, console,
      KH: { body: { today: (date) => { calls.push(date); return Promise.resolve(); } } },
      api: { day: () => new Promise((a, b) => { resolve = a; reject = b; }) },
      renderToday() {}, renderUnavailable() {}, toastError() {},
    });
    vm.runInContext(todaySource.slice(loadStart, loadEnd), context);
    const pending = context.loadDay();
    assert.deepEqual(calls, ['2026-10-28']);
    if (failed) reject({ status: 500 }); else resolve({ date: '2026-10-28' });
    await pending;
    assert.deepEqual(calls, ['2026-10-28']);
  });
}
