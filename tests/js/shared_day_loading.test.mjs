// The real sharing module must keep each shared-day box on its newest response.
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import test from 'node:test';

const root = new URL('../../app/static/js/', import.meta.url);
const read = (path) => readFileSync(new URL(path, root), 'utf8');
const deferred = () => {
  let resolve, reject;
  const promise = new Promise((ok, bad) => { resolve = ok; reject = bad; });
  return { promise, resolve, reject };
};
const text = (node) => typeof node === 'string' ? node : (node?.children || []).map(text).join('');

function setup() {
  const h = (tag, attrs, ...children) => ({
    tag, attrs, children: children.flat(Infinity).filter((v) => v != null), dataset: {}, value: '',
    append(...nodes) { this.children.push(...nodes.flat(Infinity).filter((v) => v != null)); },
    addEventListener() {}, setAttribute() {}, focus() {}, querySelectorAll: () => [],
  });
  const KH = { h, clear(node) { node.children = []; return node; }, $: () => null,
    flags: { MOCK: false }, state: {}, views: {}, sheets: {}, util: {} };
  const context = vm.createContext({ window: { KH, addEventListener() {} }, location: { hash: '' }, console });
  vm.runInContext(read('engine/rules.js'), context);
  vm.runInContext(read('views/sharing.js'), context);
  return { KH, context, h, box: h('div', {}), render: KH.sharing.renderDay };
}

const day = (food) => ({ entries: [{ meal: 'breakfast', food_name: food, servings: 1 }], status: {} });

for (const outcome of ['resolve', 'reject']) {
  test(`a late ${outcome} from an old date cannot replace the selected day's food`, async () => {
    const s = setup();
    const old = deferred(), latest = deferred();
    const first = s.render(s.box, { day: () => old.promise }, '2026-10-28');
    const second = s.render(s.box, { day: () => latest.promise }, '2026-10-29');
    latest.resolve(day('Current food'));
    await second;
    old[outcome](outcome === 'resolve' ? day('Old food') : Error('old failure'));
    await first;
    assert.match(text(s.box), /Current food/);
    assert.doesNotMatch(text(s.box), /Old food|could not be loaded/);
  });
}

test('the previous person cannot replace the next person while their day is loading', async () => {
  const s = setup();
  const old = deferred(), latest = deferred();
  const first = s.render(s.box, { day: () => old.promise }, '2026-10-29');
  const second = s.render(s.box, { day: () => latest.promise }, '2026-10-29');
  old.resolve(day('Other person food'));
  await first;
  assert.match(text(s.box), /Loading/);
  latest.resolve(day('Current person food'));
  await second;
  assert.match(text(s.box), /Current person food/);
  assert.doesNotMatch(text(s.box), /Other person food/);
});

test('Retry repeats the failed person and date and removes the error', async () => {
  const s = setup();
  const dates = [];
  let calls = 0;
  const reads = { day: async (date) => {
    dates.push(date);
    if (++calls === 1) throw Error('no connection');
    return day('Recovered food');
  } };
  await s.render(s.box, reads, '2026-10-29');
  assert.match(text(s.box), /could not be loaded/);
  const retry = s.box.children.find((node) => node.tag === 'button');
  assert.equal(text(retry), 'Retry');
  await retry.attrs.onclick();
  assert.deepEqual(dates, ['2026-10-29', '2026-10-29']);
  assert.match(text(s.box), /Recovered food/);
  assert.doesNotMatch(text(s.box), /Retry|could not be loaded/);
});

test('separate day boxes do not cancel each other', async () => {
  const s = setup();
  const otherBox = s.h('div', {});
  const old = deferred();
  const first = s.render(s.box, { day: () => old.promise }, '2026-10-28');
  await s.render(otherBox, { day: async () => day('Independent food') }, '2026-10-29');
  old.resolve(day('First box food'));
  await first;
  assert.match(text(s.box), /First box food/);
  assert.match(text(otherBox), /Independent food/);
});

test('Visit starts the shared day without waiting for unrelated summary reads', () => {
  const s = setup();
  const elements = new Map();
  s.KH.$ = (id) => {
    if (!elements.has(id)) elements.set(id, s.h('div', {}));
    return elements.get(id);
  };
  const routes = {};
  s.KH.router = { register(name, fn) { routes[name] = fn; }, show(name) { routes[name](); } };
  s.KH.brand = { screenName: 'Test' };
  const addDays = (day, n) => new Date(Date.parse(day + 'T12:00:00Z') + n * 86400000).toISOString().slice(0, 10);
  Object.assign(s.KH.util, { todayStr: () => '2026-10-29', addDays, parseDate: (d) => new Date(d + 'T12:00:00Z') });
  s.KH.ui = {};
  vm.runInContext(read('engine/visitprep.js'), s.context);
  vm.runInContext(read('views/visit.js'), s.context);
  const dates = [];
  s.KH.sharing.renderDay = (_box, _reads, date) => { dates.push(date); };
  const stuck = new Promise(() => {});
  s.KH.views.visit.openShared({ id: 7, name: 'Ana', areas: ['food'], reads: { summary: () => stuck, profile: () => stuck } });
  assert.deepEqual(dates, ['2026-10-29']);
});
