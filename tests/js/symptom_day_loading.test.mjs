// Run the real Today Symptoms loader with controlled replies and a small card DOM.
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import test from 'node:test';

const source = readFileSync(new URL('../../app/static/js/views/symptoms.js', import.meta.url), 'utf8');
const start = source.indexOf('  async function loadToday(date)');
const end = source.indexOf('  // ---- the sheet', start);
assert.ok(start >= 0 && end > start);
function setup() {
  const calls = [], body = { children: ['old symptom and old handbook block'], append(...nodes) { this.children.push(...nodes); } };
  const clear = (node) => { node.children = []; return node; };
  const context = vm.createContext({
    todayBody: body, clear, addBtn: {}, todayStr: () => '2026-10-29', message: (text) => text,
    h: (tag, attrs, ...children) => ({ tag, attrs, children }),
    renderToday: (rows) => clear(body).append(...rows),
    api: { symptoms: (date) => new Promise((resolve, reject) => calls.push({ date, resolve, reject })) },
  });
  vm.runInContext('let todayReq = 0; let shownDate = null;\n' + source.slice(start, end), context);
  return { body, calls, load: (date) => context.loadToday(date) };
}
test('a pending new date clears the old symptoms and handbook block immediately', async () => {
  const s = setup(), pending = s.load('2026-10-28');
  assert.match(JSON.stringify(s.body.children), /Loading/);
  assert.doesNotMatch(JSON.stringify(s.body.children), /old symptom|old handbook/);
  s.calls[0].resolve({ symptoms: ['new day'] }); await pending;
  assert.match(JSON.stringify(s.body.children), /new day/);
});
for (const handled of [false, true]) {
  test(`a ${handled ? 'handled' : 'genuine'} failure clears old content and offers a working retry`, async () => {
    const s = setup(), pending = s.load('2026-10-28');
    s.calls[0].reject({ status: 500, handled }); await pending;
    assert.doesNotMatch(JSON.stringify(s.body.children), /old symptom|old handbook|Loading/);
    const retry = s.body.children.find((node) => node.tag === 'button');
    assert.ok(retry, 'Try again remains available');
    const retried = retry.attrs.onclick();
    assert.equal(s.calls[1].date, '2026-10-28');
    s.calls[1].resolve({ symptoms: ['recovered'] }); await retried;
    assert.match(JSON.stringify(s.body.children), /recovered/);
  });
}
test('an older successful response cannot replace the latest day', async () => {
  const s = setup(), old = s.load('2026-10-28'), latest = s.load('2026-10-29');
  s.calls[1].resolve({ symptoms: ['latest day'] }); await latest;
  s.calls[0].resolve({ symptoms: ['old reply'] }); await old;
  assert.match(JSON.stringify(s.body.children), /latest day/);
  assert.doesNotMatch(JSON.stringify(s.body.children), /old reply/);
});
test('an older failure cannot clear a successful latest day', async () => {
  const s = setup(), old = s.load('2026-10-28'), latest = s.load('2026-10-29');
  s.calls[1].resolve({ symptoms: ['latest day'] }); await latest;
  s.calls[0].reject({ status: 500 }); await old;
  assert.match(JSON.stringify(s.body.children), /latest day/);
  assert.doesNotMatch(JSON.stringify(s.body.children), /Try again/);
});
test('moving to a future day clears the card and invalidates a pending reply', async () => {
  const s = setup(), old = s.load('2026-10-28');
  await s.load('2026-10-30');
  s.calls[0].resolve({ symptoms: ['old reply'] }); await old;
  assert.match(JSON.stringify(s.body.children), /days that have passed/);
  assert.doesNotMatch(JSON.stringify(s.body.children), /old reply/);
});

const todaySource = readFileSync(new URL('../../app/static/js/views/today.js', import.meta.url), 'utf8');
const loadStart = todaySource.indexOf('  let dayRequest = 0;');
const loadEnd = todaySource.indexOf('  /** The chosen day', loadStart);
assert.ok(loadStart >= 0 && loadEnd > loadStart);
for (const failed of [false, true]) {
  test(`Symptoms starts before the food read and is not restarted when food ${failed ? 'fails' : 'loads'}`, async () => {
    const calls = [];
    let resolve, reject;
    const context = vm.createContext({
      state: { date: '2026-10-28', dayLoadedFor: null },
      dateInput: {}, dateLabel: {}, backToToday: {}, mealsEl: { style: {} },
      fmtDateLong: (date) => date, todayStr: () => '2026-10-29', loadWeekStrip() {}, console,
      KH: { symptoms: { today: (date) => { calls.push(date); return Promise.resolve(); } } },
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
