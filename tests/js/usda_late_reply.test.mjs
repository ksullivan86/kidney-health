// Runs the real js/views/add.js on a fake page: USDA searches that answer out of order, or after the sheet was closed, must not
// mix their lists or fill a sheet opened since.
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
  const imports = [];
  const toasts = [];
  const noop = () => {};
  const KH = {
    h: page.h, s: page.h, $, $$: page.$$, clear: page.clear, state: { date: '2026-10-29' }, flags: { MOCK: false },
    toast: (msg) => toasts.push(msg), toastError: (e) => toasts.push(`error: ${e.message}`),
    router: { register() {}, show() {} }, confirm: { inline() {} }, forms: { clearFieldErrors() {}, fieldError() {}, splitFieldErrors: () => [] },
    sheets: { setup() {}, onSubmit() {}, open(dlg) { dlg.open = true; } },
    ui: { KEY_NUMBERS: [], ROW_NUMBERS: [], LEVEL_TEXT: {}, ratingIcon: () => null, levelPill: () => null, renderWarnings: noop, selectedMeal: () => 'lunch',
      setMeal: noop, selectedStatus: () => 'eaten', setStatus: noop, scaledNutrients: () => ({}), impactOn: () => [], unknownOf: () => 0,
      atLeast: (v) => v, atLeastWords: (v) => v },
    util: { todayStr: () => '2026-10-29', fmtDateLong: (d) => d, defaultStatusFor: () => 'eaten', defaultMealForNow: () => 'lunch',
      debounce: (fn) => fn, numOrNull: (v) => (v === '' ? null : Number(v)) },
    api: {
      usdaSearch: (q) => { const d = deferred(); searches.push({ q, ...d }); return d.promise; },
      usdaImport: (id) => { const d = deferred(); imports.push({ id, ...d }); return d.promise; },
    },
    views: {},
  };
  const window = { KH };
  const context = vm.createContext({ window, document: page.document, console, setTimeout, clearTimeout, Event: page.Event });
  vm.runInContext(readFileSync(new URL('engine/rules.js', root), 'utf8'), context);
  vm.runInContext(readFileSync(new URL('views/add.js', root), 'utf8'), context, { filename: 'add.js' });
  const dlg = $('#sheet-usda');
  const openSheet = () => $('#btn-usda').fire('click', { currentTarget: $('#btn-usda') });
  const search = (q) => { $('#usda-q').value = q; $('#usda-go').click(); };
  const foods = (...names) => ({ foods: names.map((description, i) => ({ fdc_id: 100 + i, description, data_type: 'Foundation' })) });
  const listed = () => page.find($('#usda-results'), (e) => e.classList.contains('row-title')).map((t) => page.text(t));
  const entryOpen = () => ($('#sheet-entry').open ? page.text($('#sheet-entry-food')) : null);
  return { page, $, KH, dlg, searches, imports, entryOpen, toasts, openSheet, search, foods, listed, status: () => page.text($('#usda-status')) };
}

for (const order of ['newest first', 'oldest first']) {
  test(`two searches that answer ${order} show only the newest list`, async () => {
    const s = setup();
    s.openSheet();
    s.search('apple');
    s.search('apples raw');
    const [older, newer] = s.searches;
    if (order === 'newest first') { newer.resolve(s.foods('Apples, raw')); await settle(); older.resolve(s.foods('Apple pie', 'Apple juice')); }
    else { older.resolve(s.foods('Apple pie', 'Apple juice')); await settle(); newer.resolve(s.foods('Apples, raw')); }
    await settle();
    assert.deepEqual(s.listed(), ['Apples, raw']);
    assert.match(s.status(), /^1 results/);
  });
}

test('an older search that fails does not replace the newer list', async () => {
  const s = setup();
  s.openSheet();
  s.search('apple');
  s.search('apples raw');
  s.searches[1].resolve(s.foods('Apples, raw'));
  await settle();
  s.searches[0].reject(Object.assign(new Error('timed out'), { status: 504 }));
  await settle();
  assert.deepEqual(s.listed(), ['Apples, raw']);
  assert.doesNotMatch(s.status(), /failed/);
});

test('a search from before the sheet was closed does not fill the sheet opened again', async () => {
  const s = setup();
  s.openSheet();
  s.search('apple');
  s.dlg.close();
  s.openSheet();
  s.searches[0].resolve(s.foods('Apple pie'));
  await settle();
  assert.deepEqual(s.listed(), []);
  assert.equal(s.status(), '');
});

test('an import that finishes after the sheet was closed does not open the entry sheet', async () => {
  const s = setup();
  s.openSheet();
  s.search('apple');
  s.searches[0].resolve(s.foods('Apple pie'));
  await settle();
  s.page.find(s.$('#usda-results'), (e) => e.tag === 'button')[0].click();
  s.dlg.close();
  s.imports[0].resolve({ id: 7, name: 'Apple pie' });
  await settle();
  assert.equal(s.entryOpen(), null);
  assert.ok(s.toasts.some((t) => /Imported Apple pie/.test(t)), 'the person is still told the food was imported');
});

test('an import that fails after the sheet was closed still says so', async () => {
  const s = setup();
  s.openSheet();
  s.search('apple');
  s.searches[0].resolve(s.foods('Apple pie'));
  await settle();
  s.page.find(s.$('#usda-results'), (e) => e.tag === 'button')[0].click();
  s.dlg.close();
  s.imports[0].reject(Object.assign(new Error('USDA did not answer'), { status: 502 }));
  await settle();
  assert.equal(s.entryOpen(), null);
  assert.ok(s.toasts.includes('error: USDA did not answer'));
});

test('one search, answered while the sheet is open, lists its foods and an import opens the entry sheet', async () => {
  const s = setup();
  s.openSheet();
  s.search('apple');
  s.searches[0].resolve(s.foods('Apple pie', 'Apple juice'));
  await settle();
  assert.deepEqual(s.listed(), ['Apple pie', 'Apple juice']);
  s.page.find(s.$('#usda-results'), (e) => e.tag === 'button')[1].click();
  s.imports[0].resolve({ id: 8, name: 'Apple juice' });
  await settle();
  assert.match(s.entryOpen(), /^Apple juice/);
});
