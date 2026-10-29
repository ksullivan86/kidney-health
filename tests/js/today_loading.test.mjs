// Exercise the real Today module with deferred API responses and a small DOM stand-in.
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import test from 'node:test';

const source = readFileSync(new URL('../../app/static/js/views/today.js', import.meta.url), 'utf8');

function setup() {
  function element() {
    return {
      children: [], textContent: '', hidden: false, style: {}, nextElementSibling: {},
      append(...children) { this.children.push(...children); },
      addEventListener() {},
    };
  }
  const elements = new Map();
  const $ = (key) => {
    if (!elements.has(key)) elements.set(key, element());
    return elements.get(key);
  };
  const pending = [];
  const errors = [];
  const state = { date: '2026-10-29', day: { date: '2026-10-28' }, dayLoadedFor: '2026-10-28' };
  const KH = {
    $, state, views: {},
    clear(el) { el.children = []; el.textContent = ''; return el; },
    h(tag, attrs, ...children) { return Object.assign(element(), { tag, attrs, children }); },
    toastError: (e) => errors.push(e),
    api: {
      day(date) { return new Promise((resolve, reject) => pending.push({ date, resolve, reject })); },
      summary: async () => ({ nutrients: {} }),
    },
    router: { register() {} },
    rules: {
      MEALS: [], NUT: {}, NUTRIENTS: [{ key: 'protein_g', label: 'Protein' }],
      fmtWithUnit: (v) => `${v} g`,
    },
    ui: { STATUS_ORDER: [], STRIP_KEYS: [], isPlanned: (e) => e.status === 'planned', unknownOf: () => 0, atLeast: (v) => v },
    util: { todayStr: () => '2026-10-29', fmtDateLong: (v) => v, fmtMonthDay: (v) => v, addDays: (v) => v },
  };
  for (const key of ['#alerts', '#projected-alerts', '#status-bars', '#meals', '#totals-all']) {
    $(key).append('previous day data');
  }
  vm.runInNewContext(source, { window: { KH }, console });
  return { $, state, pending, errors, load: KH.views.today.loadDay };
}

const day = (date, protein = 12) => ({ date, entries: [], totals: { protein_g: protein } });

test('a failed date change clears old food and totals; Retry loads the selected day', async () => {
  const s = setup();
  const loading = s.load();
  assert.equal(s.state.day, null);
  assert.equal(s.state.dayLoadedFor, null);
  for (const key of ['#alerts', '#projected-alerts', '#status-bars', '#totals-all']) {
    assert.equal(s.$(key).children.length, 0, key);
  }
  assert.match(JSON.stringify(s.$('#meals').children), /Loading food/);
  assert.equal(s.$('#date-label').textContent, '2026-10-29');
  s.pending[0].reject(new Error('connection lost'));
  await loading;
  assert.match(JSON.stringify(s.$('#meals').children), /could not be loaded/);
  const retry = s.$('#meals').children.find((el) => el.tag === 'button');
  assert.equal(retry.children[0], 'Retry');
  const recovering = retry.attrs.onclick();
  assert.equal(s.pending[1].date, '2026-10-29');
  s.pending[1].resolve(day('2026-10-29'));
  await recovering;
  assert.equal(s.errors.length, 1, s.errors.map((e) => e.stack).join('\n'));
  assert.equal(s.state.dayLoadedFor, '2026-10-29');
  assert.equal(s.state.day.date, '2026-10-29');
  assert.doesNotMatch(JSON.stringify(s.$('#meals').children), /could not be loaded|Retry|Loading food/);
  assert.match(JSON.stringify(s.$('#totals-all').children), /12 g/);
});

for (const outcome of ['resolve', 'reject']) {
  test(`a late ${outcome} from an older date cannot replace the latest result`, async () => {
    const s = setup();
    const older = s.load();
    s.state.date = '2026-10-30';
    const newer = s.load();
    s.pending[1].resolve(day('2026-10-30', 25));
    await newer;
    s.pending[0][outcome](outcome === 'resolve' ? day('2026-10-29') : new Error('late failure'));
    await older;
    assert.equal(s.state.dayLoadedFor, '2026-10-30');
    assert.equal(s.state.day.date, '2026-10-30');
    assert.match(JSON.stringify(s.$('#totals-all').children), /25 g/);
    assert.equal(s.errors.length, 0);
  });
}

test('an old response cannot end the loading state of a newer request', async () => {
  const s = setup();
  const older = s.load();
  s.state.date = '2026-10-30';
  const newer = s.load();
  s.pending[0].resolve(day('2026-10-29'));
  await older;
  assert.equal(s.state.day, null);
  assert.match(JSON.stringify(s.$('#meals').children), /Loading food/);
  s.pending[1].resolve(day('2026-10-30'));
  await newer;
  assert.equal(s.state.dayLoadedFor, '2026-10-30');
});
