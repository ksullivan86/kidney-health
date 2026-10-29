// Run the real symptom and body Trends views across source switches and failed reads.
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
const text = (node) => typeof node === 'string' ? node : (node?.children || []).map(text).join('');

function setup(kind) {
  const elements = new Map();
  const element = (tag = '', attrs = {}, ...children) => ({
    tag, attrs, children: children.flat(Infinity).filter((v) => v != null), clientWidth: 700,
    append(...nodes) { this.children.push(...nodes.flat(Infinity).filter((v) => v != null)); }, addEventListener() {},
  });
  const $ = (id) => {
    if (!elements.has(id)) elements.set(id, element());
    return elements.get(id);
  };
  const KH = {
    $, h: element, s: element, state: { profile: { dialysis: 'none' }, view: 'trends' }, api: {}, ui: {},
    sheets: { setup() {}, onSubmit() {} },
    clear(node) { node.children = []; return node; },
    util: { fmtDateShort: (d) => d, fmtMonthDay: (d) => d, daysBetween: () => 6 },
  };
  const context = vm.createContext({ window: { KH, addEventListener() {} }, console });
  for (const file of ['engine/rules.js', 'engine/symptoms.js', 'engine/body.js', 'engine/visitprep.js', 'engine/body_ui.js',
    `views/${kind === 'body' ? 'body_trends' : 'symptoms'}.js`]) {
    vm.runInContext(readFileSync(new URL(file, root), 'utf8'), context);
  }
  const body = $(kind === 'body' ? '#body-trends-body' : '#symptoms-trends-body');
  body.append('previous person data');
  const show = (source) => kind === 'body'
    ? KH.bodyTrends.show('2026-10-23', '2026-10-29', source)
    : KH.symptoms.trends('2026-10-23', '2026-10-29', source);
  const source = (name, queue, areas = [kind]) => ({ name, areas, reads: {
    profile: async () => ({}),
    bodyWeights: () => queue.shift().promise,
    bloodPressures: async () => ({ readings: [] }),
    bodySummary: async () => ({ units: 'kg' }),
    symptoms: () => queue.shift().promise,
  } });
  return { KH, body, show, source, empty: kind === 'body' ? { weights: [] } : { symptoms: [] } };
}

for (const kind of ['body', 'symptoms']) {
  test(`${kind}: switch clears old data and Retry recovers, including a handled error`, async () => {
    const s = setup(kind);
    const first = deferred(), second = deferred();
    const src = s.source('Ana', [first, second]);
    const pending = s.show(src);
    assert.doesNotMatch(text(s.body), /previous person data/);
    assert.match(text(s.body), /Loading/);
    first.reject({ handled: true, status: 401 });
    await pending;
    assert.doesNotMatch(text(s.body), /Loading|previous person data/);
    const retry = s.body.children.find((node) => node.tag === 'button');
    assert.equal(text(retry), 'Retry');
    const recovery = retry.attrs.onclick();
    second.resolve(s.empty);
    await recovery;
    assert.match(text(s.body), /No /);
    assert.doesNotMatch(text(s.body), /Retry|Loading/);
  });

  for (const outcome of ['resolve', 'reject']) {
    test(`${kind}: an old ${outcome} cannot replace the next person's loading or results`, async () => {
      const s = setup(kind);
      const first = deferred(), second = deferred();
      const old = s.show(s.source('Ana', [first]));
      const current = s.show(s.source('Sam', [second]));
      first[outcome](outcome === 'resolve' ? s.empty : Error('old connection failed'));
      await old;
      assert.match(text(s.body), /Loading/);
      second.resolve(s.empty);
      await current;
      assert.match(text(s.body), /No /);
      assert.doesNotMatch(text(s.body), /Retry|Loading/);
    });
  }

  test(`${kind}: an unshared area cannot keep the previous person's content`, async () => {
    const s = setup(kind);
    await s.show(s.source('Ana', [], []));
    assert.match(text(s.body), /Ana has not shared/);
    assert.doesNotMatch(text(s.body), /previous person data|Loading/);
  });
}

test('body: a resize cannot redraw cached charts from the previous person', async () => {
  const s = setup('body');
  const first = deferred(), second = deferred();
  const old = s.show(s.source('Ana', [first]));
  first.resolve({ weights: [{ id: 1, date: '2026-10-29', time: '09:00', kg: 71, context: 'morning' }] });
  await old;
  assert.match(text(s.body), /71\.0/);
  const current = s.show(s.source('Sam', [second]));
  s.KH.bodyTrends.render();
  assert.match(text(s.body), /Loading/);
  assert.doesNotMatch(text(s.body), /71\.0/);
  second.resolve({ weights: [] });
  await current;
});
