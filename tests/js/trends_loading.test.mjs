// Exercise the real Trends module when changing people or periods across failed/late reads.
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import test from 'node:test';

const root = new URL('../../app/static/js/', import.meta.url);
const read = (path) => readFileSync(new URL(path, root), 'utf8');

function setup() {
  const elements = new Map();
  const routes = {};
  const requests = [];
  let routePromise;
  const element = (tag = '', attrs = {}, ...children) => ({
    tag, attrs, children: children.flat(Infinity).filter((v) => v != null), hidden: false, style: {},
    append(...nodes) { this.children.push(...nodes.flat(Infinity).filter((v) => v != null)); },
    addEventListener() {}, setAttribute(k, v) { this.attrs[k] = v; }, closest() { return this; },
  });
  const $ = (id) => {
    if (!elements.has(id)) elements.set(id, element());
    return elements.get(id);
  };
  const reads = (name) => ({
    range: () => new Promise((resolve, reject) => requests.push({ name, resolve, reject })),
    summary: async () => ({ start: '2026-10-16', end: '2026-10-29', days: 14, logged_days: 0, nutrients: {} }),
    exportUrl: () => '/api/log/export.csv',
  });
  const errors = [];
  const KH = {
    $, $$: () => [], h: element, s: element, views: {}, flags: { MOCK: false }, brand: { logCsvPrefix: 'log_' },
    state: { trendsDays: 14, trends: { days: [] }, summary: { previous: true }, view: 'trends' },
    clear(node) { node.children = []; node.textContent = ''; return node; },
    api: reads('own'), toastError: (e) => errors.push(e), sheets: { setup() {} },
    router: { register(name, fn) { routes[name] = fn; }, show(name) { routePromise = routes[name](); } },
    ui: { TREND_ORDER: [] },
    util: { todayStr: () => '2026-10-29', addDays: (d) => d, fmtDateShort: (d) => d, fmtRange: () => 'period' },
  };
  const context = vm.createContext({ window: { KH, addEventListener() {} }, document: { addEventListener() {} }, console });
  vm.runInContext(read('engine/rules.js'), context);
  vm.runInContext(read('views/trends.js'), context);
  for (const id of ['#charts', '#period-body', '#period-interdialytic', '#period-notes']) $(id).append('previous person data');
  $('#period-sub').textContent = 'previous period';
  const shared = (name, areas = ['food']) => {
    KH.views.trends.openShared({ id: name, name, areas, reads: reads(name) });
    return routePromise;
  };
  const text = (node) => typeof node === 'string' ? node : (node?.children || []).map(text).join('');
  return { $, KH, errors, requests, shared, own: () => routes.trends(), text };
}

test('switching to shared Trends clears old data immediately and recovers through Retry', async () => {
  const s = setup();
  const pending = s.shared('Ana');
  for (const id of ['#charts', '#period-body', '#period-interdialytic', '#period-notes']) {
    assert.doesNotMatch(s.text(s.$(id)), /previous person data/, id);
  }
  assert.equal(s.KH.state.summary, null);
  assert.equal(s.$('#chart-tip').hidden, true);
  assert.match(s.$('#trends-title').textContent, /^Ana:/);
  s.requests[0].reject(new Error('connection lost'));
  await pending;
  assert.equal(s.KH.state.trends, null);
  assert.match(s.text(s.$('#charts')), /could not be loaded/);
  assert.match(s.text(s.$('#period-body')), /unavailable/);
  const retry = s.$('#charts').children.find((node) => node.tag === 'button');
  assert.equal(s.text(retry), 'Retry');
  const recovery = retry.attrs.onclick();
  assert.equal(s.requests[1].name, 'Ana');
  s.requests[1].resolve({ days: [] });
  await recovery;
  assert.equal(s.text(s.$('#charts')), 'No targets set yet.');
  assert.doesNotMatch(s.text(s.$('#charts')), /Retry|Loading/);
  assert.ok(s.KH.state.summary);
});

for (const outcome of ['resolve', 'reject']) {
  test(`a late shared ${outcome} cannot replace the viewer's newer Trends`, async () => {
    const s = setup();
    const old = s.shared('Ana');
    const current = s.own();
    s.requests[1].resolve({ days: [] });
    await current;
    s.requests[0][outcome](outcome === 'resolve' ? { days: [] } : new Error('late failure'));
    await old;
    assert.equal(s.text(s.$('#charts')), 'No targets set yet. Set targets in Profile to see trends.');
    assert.equal(s.errors.length, 0);
    assert.equal(s.$('#trends-shared').hidden, true);
  });
}

test('an old response cannot end the loading state of a new person', async () => {
  const s = setup();
  const old = s.shared('Ana');
  const current = s.shared('Sam');
  s.requests[0].resolve({ days: [] });
  await old;
  assert.match(s.text(s.$('#charts')), /Loading/);
  assert.equal(s.KH.state.trends, null);
  s.requests[1].resolve({ days: [] });
  await current;
  assert.match(s.$('#trends-title').textContent, /^Sam:/);
});

test('a person who did not share food leaves no previous summary or chart', async () => {
  const s = setup();
  await s.shared('Ana', ['body']);
  assert.equal(s.requests.length, 0);
  assert.equal(s.KH.state.summary, null);
  assert.match(s.text(s.$('#charts')), /has not shared/);
  assert.doesNotMatch(s.text(s.$('#period-body')), /previous person data/);
});
