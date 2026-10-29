// Exercise the real lab module with reads that straddle a save/profile invalidation.
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import test from 'node:test';

const root = new URL('../../app/static/js/', import.meta.url);
const deferred = () => {
  let resolve, reject;
  const promise = new Promise((ok, bad) => { resolve = ok; reject = bad; });
  return { promise, resolve, reject };
};
const settle = async () => { for (let i = 0; i < 10; i++) await Promise.resolve(); };
const text = (node) => typeof node === 'string' ? node : (node?.children || []).map(text).join('');

function setup() {
  const elements = new Map(), batches = [];
  const h = (tag, attrs = {}, ...children) => {
    const node = { tag, attrs, children: children.flat(Infinity).filter((v) => v != null), value: '',
      append(...nodes) { this.children.push(...nodes.flat(Infinity).filter((v) => v != null)); },
      after() {}, setAttribute() {}, addEventListener() {}, focus() {},
    };
    Object.defineProperty(node, 'childNodes', { get() { return this.children; } });
    return node;
  };
  const $ = (id) => {
    if (!elements.has(id)) elements.set(id, h('div'));
    return elements.get(id);
  };
  const KH = { $, h, state: {}, views: {}, forms: {}, util: { parseDate: (d) => new Date(d + 'T12:00:00Z') },
    sheets: { onSubmit() {} }, router: { register() {} },
    clear(node) { node.children = []; return node; },
    api: {
      labs: () => { const batch = { list: deferred(), kf: deferred() }; batches.push(batch); return batch.list.promise; },
      kidneyFunction: () => batches.at(-1).kf.promise,
    },
  };
  const context = vm.createContext({ window: { KH }, console });
  for (const file of ['engine/rules.js', 'engine/kidney_function.js', 'engine/targets.js', 'views/labs.js']) {
    vm.runInContext(readFileSync(new URL(file, root), 'utf8'), context);
  }
  const resolve = (index, marker) => {
    batches[index].list.resolve({ labs: [{ id: index + 1, analyte: 'potassium', value: 4.8, label: 'Potassium',
      display: marker, taken_on: '2026-10-29' }], alerts: [] });
    batches[index].kf.resolve({ message: marker });
  };
  return { KH, $, batches, resolve, load: KH.labs.load, invalidate: KH.labs.invalidate, refresh: KH.views.labs.refresh };
}

test('concurrent readers share one list/kidney-function read until invalidated', async () => {
  const s = setup();
  const first = s.load(), second = s.load();
  assert.equal(first, second);
  assert.equal(s.batches.length, 1);
  s.resolve(0, 'Current');
  assert.equal((await first).labs[0].display, 'Current');
  await second;
  assert.equal((await s.load()).kf.message, 'Current');
  assert.equal(s.batches.length, 1);
});

for (const outcome of ['resolve', 'reject']) {
  test(`an invalidated old ${outcome} cannot repopulate the cache or return pre-save data`, async () => {
    const s = setup();
    const old = s.load();
    s.invalidate();
    const current = s.load();
    assert.equal(s.batches.length, 2);
    s.resolve(1, 'New result');
    assert.equal((await current).labs[0].display, 'New result');
    if (outcome === 'resolve') s.resolve(0, 'Old result');
    else { s.batches[0].list.reject(Error('old failure')); s.batches[0].kf.resolve({}); }
    assert.equal((await old).labs[0].display, 'New result');
    assert.equal((await s.load()).kf.message, 'New result');
    assert.equal(s.batches.length, 2);
  });
}

test('finishing an invalidated read cannot detach the current in-flight request', async () => {
  const s = setup();
  const old = s.load();
  s.invalidate();
  const current = s.load();
  s.resolve(0, 'Old');
  await settle();
  assert.equal(s.load(), current);
  assert.equal(s.batches.length, 2);
  s.resolve(1, 'New');
  assert.equal((await old).kf.message, 'New');
  await current;
});

test('multiple invalidations converge on the newest result', async () => {
  const s = setup();
  const first = s.load();
  s.invalidate();
  const second = s.load();
  s.invalidate();
  const third = s.load();
  s.resolve(1, 'Middle'); s.resolve(0, 'Old'); s.resolve(2, 'Newest');
  const results = await Promise.all([first, second, third]);
  for (const result of results) assert.equal(result.kf.message, 'Newest');
  assert.equal((await s.load()).labs[0].display, 'Newest');
});

test('a genuine current failure is reported and a later read can retry', async () => {
  const s = setup();
  const failure = s.load();
  s.batches[0].list.reject(Error('current failure')); s.batches[0].kf.resolve({});
  await assert.rejects(failure, /current failure/);
  const retry = s.load();
  assert.equal(s.batches.length, 2);
  s.resolve(1, 'Recovered');
  assert.equal((await retry).kf.message, 'Recovered');
});

test('the Lab results page keeps its fresh result after an older refresh finishes', async () => {
  const s = setup();
  const first = s.refresh();
  s.invalidate();
  const second = s.refresh();
  assert.equal(s.batches.length, 2);
  s.resolve(1, 'New result');
  await second;
  s.resolve(0, 'Old result');
  await first;
  assert.match(text(s.$('#labs-history')), /New result/);
  assert.doesNotMatch(text(s.$('#labs-history')), /Old result/);
  assert.match(text(s.$('#kf-body')), /New result/);
});
