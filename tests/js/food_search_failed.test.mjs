// Runs the real js/views/add.js on a fake page: when a search on the Add tab fails, the list must say so under the new search,
// with Retry, and never keep the previous results as if they were the answer.
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import test from 'node:test';
import { makePage, deferred, settle } from './fake_page.mjs';

const root = new URL('../../app/static/js/', import.meta.url);

function setup() {
  const page = makePage();
  const { $ } = page;
  const searches = [];
  const toasts = [];
  const noop = () => {};
  const KH = {
    h: page.h, s: page.h, $, $$: page.$$, clear: page.clear, state: { date: '2026-10-29', category: '' }, flags: { MOCK: false },
    toast: (msg) => toasts.push(msg), toastError: (e) => toasts.push(`error: ${e.message}`),
    router: { register() {}, show() {} }, confirm: { inline() {} }, forms: { clearFieldErrors() {}, fieldError() {}, splitFieldErrors: () => [] },
    sheets: { setup() {}, onSubmit() {}, open(dlg) { dlg.open = true; } },
    ui: { KEY_NUMBERS: [], ROW_NUMBERS: [], LEVEL_TEXT: {}, ratingIcon: () => null, levelPill: () => null, renderWarnings: noop, selectedMeal: () => 'lunch',
      setMeal: noop, selectedStatus: () => 'eaten', setStatus: noop, scaledNutrients: () => ({}), impactOn: () => [], unknownOf: () => 0,
      atLeast: (v) => v, atLeastWords: (v) => v },
    util: { todayStr: () => '2026-10-29', fmtDateLong: (d) => d, defaultStatusFor: () => 'eaten', defaultMealForNow: () => 'lunch',
      debounce: (fn) => fn, numOrNull: (v) => (v === '' ? null : Number(v)) },
    api: { foods: (params) => { const d = deferred(); searches.push({ params, ...d }); return d.promise; } },
    views: {},
  };
  const context = vm.createContext({ window: { KH }, document: page.document, console: { ...console, error() {} }, setTimeout, clearTimeout, Event: page.Event });
  vm.runInContext(readFileSync(new URL('engine/rules.js', root), 'utf8'), context);
  vm.runInContext(readFileSync(new URL('views/add.js', root), 'utf8'), context, { filename: 'add.js' });
  const search = (q) => { $('#food-search').value = q; $('#food-search').fire('keydown', { key: 'Enter' }); };
  const foods = (...names) => ({ foods: names.map((name, i) => ({ id: i + 1, name, serving_desc: '1 cup', nutrients: {}, kidney_rating: 'green' })) });
  const listed = () => page.find($('#food-results'), (e) => e.classList.contains('row-title')).map((t) => page.text(t));
  const retry = () => page.button($('#food-results'), 'Retry');
  const fail = (i) => searches[i].reject(Object.assign(new Error('The server did not answer'), { status: 504 }));
  return { page, $, searches, toasts, search, foods, listed, retry, fail, heading: () => page.text($('#results-heading')),
    count: () => page.text($('#results-count')), results: () => page.text($('#food-results')) };
}

test('a failed search replaces the old results with a note and Retry under the new search', async () => {
  const s = setup();
  s.search('banana');
  s.searches[0].resolve(s.foods('Banana', 'Banana chips'));
  await settle();
  assert.deepEqual(s.listed(), ['Banana', 'Banana chips']);
  s.search('apple');
  s.fail(1);
  await settle();
  assert.deepEqual(s.listed(), [], 'the banana results are gone');
  assert.equal(s.heading(), 'Results for “apple”');
  assert.equal(s.count(), '');
  assert.match(s.results(), /Could not search: The server did not answer/);
  assert.ok(s.retry(), 'Retry is offered');
});

test('Retry runs the search again and shows its answer', async () => {
  const s = setup();
  s.search('apple');
  s.fail(0);
  await settle();
  s.retry().click();
  assert.equal(s.searches.length, 2);
  assert.equal(s.searches[1].params.q, 'apple');
  s.searches[1].resolve(s.foods('Apple, raw'));
  await settle();
  assert.deepEqual(s.listed(), ['Apple, raw']);
  assert.equal(s.retry(), null);
});

test('an older search that fails after a newer one answered does not replace its list', async () => {
  const s = setup();
  s.search('apple');
  s.search('apple raw');
  s.searches[1].resolve(s.foods('Apple, raw'));
  await settle();
  s.fail(0);
  await settle();
  assert.deepEqual(s.listed(), ['Apple, raw']);
  assert.equal(s.heading(), 'Results for “apple raw”');
  assert.equal(s.retry(), null);
});
