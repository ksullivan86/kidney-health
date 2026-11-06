import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import test from 'node:test';
import { makePage, deferred, settle } from './fake_page.mjs';

function setup() {
  const page = makePage();
  const calls = [], searches = [], saves = [], toasts = [], callbacks = [];
  const KH = {
    ...page,
    h(tag, attrs, ...children) {
      const el = page.h(tag, attrs, ...children);
      if (attrs?.value != null) el.value = String(attrs.value);
      if (attrs?.checked) el.checked = true;
      return el;
    },
    rules: { NUT: {}, NUTRIENTS: [], fmtNum: String, evaluateWarnings: () => [] },
    ui: { KEY_NUMBERS: [], ratingIcon: () => null, renderWarnings() {} },
    util: { debounce: (fn) => fn },
    recipeImport: { recipeServings: () => 1 },
    request(method, path, body) { const d = deferred(); calls.push({ method, path, body, ...d }); return d.promise; },
    api: {
      foods(body) { const d = deferred(); searches.push({ body, ...d }); return d.promise; },
      createMeal(body) { const d = deferred(); saves.push({ body, ...d }); return d.promise; },
    },
    toast: (msg) => toasts.push(msg), toastError: (err) => toasts.push(err.message),
    sheets: { setup() {}, open(el) { el.showModal(); }, onSubmit(form, fn) { form.addEventListener('submit', fn); } },
  };
  vm.runInNewContext(readFileSync(new URL('../../app/static/js/views/recipe_import.js', import.meta.url), 'utf8'),
    { window: { KH }, document: page.document, console, setTimeout, clearTimeout });
  const $ = page.$;
  const dlg = $('#sheet-recipe-import');
  const open = (label = 'original') => KH.recipeImportView.open({ onSaved: (meal) => callbacks.push([label, meal.name]) });
  const source = async (label) => { const p = open(label); calls.at(-1).resolve({ web: true }); await p; };
  const submit = () => $('#recipe-import-form').fire('submit');
  const food = (id, name) => ({ id, name, serving_desc: '1 cup', serving_g: 100, nutrients: {}, flags: [], warnings: [] });
  const draft = (name = 'Rice dish') => ({ name, servings_made: 2, steps: [], notice: 'Check every line.', estimate: 'Estimates.',
    source_url: null, lines: [1, 2].map((id) => ({ text: `Ingredient ${id}`, matches: [{ food: food(id, `Food ${id}`), servings: 1 }] })) });
  const read = () => { $('#ri-text').value = '1 cup rice'; submit(); };
  const review = async () => { await source(); read(); calls.at(-1).resolve(draft()); await settle(); };
  const check = () => { for (const id of [1, 2]) { const cb = $(`#ri-ok-${id - 1}`); cb.checked = true; cb.fire('change'); } };
  const search = (i, word) => {
    const sel = $(`#ri-food-${i}`); sel.value = 'search'; sel.fire('change');
    const input = $(`#ri-search-${i}`); input.value = word; input.fire('keydown', { key: 'Enter' });
    return input.parent.querySelector('ul');
  };
  return { page, $, dlg, calls, searches, saves, toasts, callbacks, open, source, submit, food, draft, read, review, check, search };
}

test('an older capability answer cannot reset the newer source form', async () => {
  const s = setup(); const a = s.open('A'); const b = s.open('B');
  s.calls[1].resolve({ web: true }); await b;
  s.$('#ri-text').value = 'New ingredients';
  s.calls[0].resolve({ web: false }); await a;
  assert.equal(s.$('#ri-text').value, 'New ingredients');
  assert.ok(s.$('#ri-url').isConnected);
});

test('capabilities load in an open sheet that the person can cancel', async () => {
  const s = setup(); const p = s.open();
  assert.equal(s.dlg.open, true);
  s.dlg.close(); s.calls[0].resolve({ web: true }); await p;
  assert.equal(s.dlg.open, false);
});

for (const kind of ['page', 'text']) {
  test(`a late ${kind} draft does not replace a reopened source form`, async () => {
    const s = setup(); await s.source();
    if (kind === 'page') { s.$('#ri-url').value = 'https://recipes.example/one'; s.$('#ri-read-page').click(); }
    else s.read();
    const old = s.calls.at(-1);
    s.dlg.close(); await s.source('new'); s.$('#ri-text').value = 'Keep this typing';
    old.resolve(s.draft('Old recipe')); await settle();
    assert.equal(s.$('#ri-text').value, 'Keep this typing');
    assert.ok(s.$('#ri-text').isConnected);
    assert.doesNotMatch(s.page.text(s.$('#recipe-import-body')), /Old recipe|Check every line/);
  });
}

test('a new opening can read ingredients while the previous request waits', async () => {
  const s = setup(); await s.source(); s.read(); const old = s.calls.at(-1);
  s.dlg.close(); await s.source('new'); s.read(); const fresh = s.calls.at(-1);
  assert.notEqual(old, fresh);
  fresh.resolve(s.draft('New recipe')); await settle();
  old.resolve(s.draft('Old recipe')); await settle();
  assert.equal(s.$('#ri-review-name').value, 'New recipe');
});

test('a late parse error does not put an error or button label over a new review', async () => {
  const s = setup(); await s.source(); s.read(); const old = s.calls.at(-1);
  s.dlg.close(); await s.source('new');
  // A source form must be independently usable while the old parse waits.
  s.read(); s.calls.at(-1).resolve(s.draft('New recipe')); await settle();
  old.reject(new Error('Old parse failed')); await settle();
  assert.deepEqual(s.toasts, []);
  assert.equal(s.$('#ri-review-name').value, 'New recipe');
  assert.doesNotMatch(s.page.text(s.$('#recipe-import-go')), /Read ingredients/);
});

test('a parse failure in the current sheet preserves typing and allows a retry', async () => {
  const s = setup(); await s.source(); s.read();
  s.calls.at(-1).reject(new Error('Try again')); await settle();
  assert.equal(s.$('#ri-text').value, '1 cup rice');
  assert.equal(s.$('#recipe-import-go').disabled, false);
  s.submit(); s.calls.at(-1).resolve(s.draft()); await settle();
  assert.equal(s.$('#ri-review-name').value, 'Rice dish');
});

test('a save finishing after reopening closes nothing and calls only its original callback', async () => {
  const s = setup(); await s.review(); s.check(); s.submit();
  const old = s.saves[0]; s.dlg.close(); await s.source('new');
  s.$('#ri-text').value = 'Keep this typing';
  old.resolve({ id: 10, name: 'Rice dish' }); await settle();
  assert.equal(s.dlg.open, true);
  assert.equal(s.$('#ri-text').value, 'Keep this typing');
  assert.deepEqual(s.callbacks, [['original', 'Rice dish']]);
});

test('an old save failure cannot change the new sheet or release its pending read', async () => {
  const s = setup(); await s.review(); s.check(); s.submit(); const old = s.saves[0];
  s.dlg.close(); await s.source('new'); s.read();
  old.reject(new Error('Old save failed')); await settle();
  assert.deepEqual(s.toasts, []);
  assert.equal(s.$('#recipe-import-go').disabled, true);
  assert.match(s.page.text(s.$('#recipe-import-go')), /Reading/);
  s.calls.at(-1).resolve(s.draft()); await settle();
});

test('a current save failure keeps checked choices and supports retry', async () => {
  const s = setup(); await s.review(); s.check(); s.submit();
  s.saves[0].reject(new Error('Save failed')); await settle();
  assert.equal(s.dlg.open, true);
  assert.equal(s.$('#ri-review-name').value, 'Rice dish');
  assert.equal(s.$('#recipe-import-go').disabled, false);
  s.submit(); assert.equal(s.saves.length, 2);
  s.saves[1].resolve({ id: 10, name: 'Rice dish' }); await settle();
  assert.equal(s.dlg.open, false);
});

test('review edits cannot enable a second save while the first waits', async () => {
  const s = setup(); await s.review(); s.check(); s.submit();
  s.$('#ri-review-name').fire('input');
  assert.equal(s.$('#recipe-import-go').disabled, true);
  assert.equal(s.$('#recipe-import-back').disabled, true);
  s.saves[0].resolve({ id: 10, name: 'Rice dish' }); await settle();
});

test('independent ingredient searches can finish in either order', async () => {
  const s = setup(); await s.review();
  const first = s.search(0, 'rice'); const second = s.search(1, 'apple');
  s.searches[1].resolve({ foods: [s.food(4, 'Apples')] }); await settle();
  s.searches[0].resolve({ foods: [s.food(3, 'White rice')] }); await settle();
  assert.match(s.page.text(first), /White rice/);
  assert.match(s.page.text(second), /Apples/);
});

test('search errors from an abandoned ingredient choice stay silent', async () => {
  const s = setup(); await s.review(); s.search(0, 'rice');
  const select = s.$('#ri-food-0'); select.value = '0'; select.fire('change');
  s.searches[0].reject(new Error('Old search failed')); await settle();
  assert.deepEqual(s.toasts, []);
});

test('a failed search in a current ingredient still says so', async () => {
  const s = setup(); await s.review(); s.search(0, 'rice');
  s.searches[0].reject(new Error('Search failed')); await settle();
  assert.deepEqual(s.toasts, ['Search failed']);
});
