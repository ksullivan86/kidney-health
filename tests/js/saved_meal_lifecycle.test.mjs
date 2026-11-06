import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import test from 'node:test';
import { makePage, deferred, settle } from './fake_page.mjs';

const source = readFileSync(new URL('../../app/static/js/views/plan.js', import.meta.url), 'utf8');
const start = source.indexOf('  // ---- Copy day sheet');
const end = source.indexOf('  // ---- Fit to my targets', start);
assert.ok(start > 0 && end > start);
const dish = (id = 1) => ({ id, name: `Meal ${id}`, items: [{ food_id: id, food_name: 'Apple', servings: 1, nutrients: {}, kidney_rating: 'green' }], totals: {} });
const food = { id: 3, name: 'Banana', nutrients: {}, kidney_rating: 'green' };

function setup() {
  const page = makePage(), calls = [], errors = [], notices = [], changes = [], pendingLoads = [], deletes = [], timers = [];
  for (const [form, names] of Object.entries({
    meal: ['name', 'note', 'makes', 'source', 'steps', 'hint', 'search', 'search-results', 'items', 'save', 'delete'],
    savemeal: ['name', 'note', 'save'], apply: ['meal-id', 'date', 'scale', 'meal', 'status', 'save'],
    copy: ['from', 'to', 'include', 'status', 'save'],
  })) {
    for (const name of names) {
      const el = page.$(`#${form}-${name}`);
      el.tag = ['save', 'delete'].includes(name) ? 'button' : name === 'steps' ? 'textarea' : ['hint', 'meal-id', 'meal', 'status'].includes(name) ? 'select' : name === 'items' || name === 'search-results' ? 'ul' : 'input';
      page.$(`#${form}-form`).append(el);
    }
  }
  const request = (method) => (...args) => { const d = deferred(); calls.push({ method, args, ...d }); return d.promise; };
  const sheets = { setup() {}, open(dlg) { dlg.open = true; }, onSubmit(form, fn) { form.addEventListener('submit', fn); } };
  const state = { meals: [dish(), dish(2)], view: 'plan', date: '2026-11-06' };
  const context = vm.createContext({ ...page,
    $$: (selector, scope) => selector.startsWith('#copy-meals') ? [{ checked: true, value: 'lunch' }] : page.$$(selector, scope),
    h(tag, attrs, ...children) { const el = page.h(tag, attrs, ...children); if (attrs?.value != null) el.value = String(attrs.value); return el; },
    sheets, state, api: Object.fromEntries(['foods', 'createMeal', 'updateMeal', 'mealFromLog', 'applyMeal', 'copyDay'].map((n) => [n, request(n)])),
    KH: { loadMeals() { return pendingLoads.length ? pendingLoads.shift().promise : Promise.resolve(); }, invalidateMeals() {}, views: { add: { renderSavedShortcuts() {} } } },
    NUTRIENTS: [], KEY_NUMBERS: [], MEAL_LABEL: { lunch: 'Lunch', dinner: 'Dinner' }, MEALS: ['breakfast', 'lunch', 'dinner', 'snack'], addDays: () => '2026-11-07',
    shownNote: (t) => t.note, isRecipe: (t) => t.servings_made != null && t.servings_made !== 1,
    toast: (m) => notices.push(m), toastError: (e) => errors.push(e.message),
    ratingIcon: () => '', closeIcon: () => '', plusIcon: () => '', fmtServings: String, fmtDateLong: String,
    todayStr: () => '2026-11-06', defaultMealForNow: () => 'lunch', defaultStatusFor: () => 'eaten',
    setMeal: (el, value) => { el.value = value; }, selectedMeal: (el) => el.value,
    setStatus: (el, value) => { el.value = value; }, selectedStatus: (el) => el.value,
    scaledNutrients: () => ({}), isPlanned: () => false, afterLogChange: (...args) => changes.push(args), renderSavedMeals() {},
    debounce: (fn) => () => timers.push(fn),
    confirmDeleteSavedMeal: (t, host, trigger, after) => deletes.push({ t, after }),
  });
  vm.runInContext(source.slice(start, end) + '\nglobalThis.fns = {openMealEditor, runMealSearch, openSaveMealSheet, openApplySheet, openCopySheet};', context);
  const submit = async (form) => { page.$(`#${form}-form`).fire('submit'); await settle(); };
  return { ...page, ...context.fns, calls, errors, notices, state, changes, pendingLoads, deletes, timers, submit,
    close(form) { page.$(`#sheet-${form}`).close(); },
    last(method) { return calls.filter((c) => c.method === method).at(-1); },
    count(method) { return calls.filter((c) => c.method === method).length; },
  };
}

for (const reject of [false, true]) {
  test(`old editor search ${reject ? 'failure' : 'success'} stays out of a new draft`, async () => {
    const s = setup(); s.openMealEditor(dish()); s.$('#meal-search').value = 'banana';
    const search = s.runMealSearch(); s.close('meal'); s.openMealEditor(dish(2));
    if (reject) s.last('foods').reject(new Error('old search failed'));
    else s.last('foods').resolve({ foods: [food] });
    await search;
    assert.equal(s.text(s.$('#meal-search-results')), ''); assert.deepEqual(s.errors, []);
  });
}
test('typing invalidates an old search before the next debounced request begins', async () => {
  const s = setup(); s.openMealEditor(dish()); s.$('#meal-search').value = 'banana'; const search = s.runMealSearch();
  s.$('#meal-search').value = 'rice'; s.$('#meal-search').fire('input');
  s.last('foods').resolve({ foods: [food] }); await search;
  assert.equal(s.text(s.$('#meal-search-results')), '');
});
test('a detached result cannot add a food to a replacement draft', async () => {
  const s = setup(); s.openMealEditor(dish()); s.$('#meal-search').value = 'banana'; const search = s.runMealSearch();
  s.last('foods').resolve({ foods: [food] }); await search;
  const oldButton = s.$('#meal-search-results').querySelector('button');
  s.close('meal'); s.openMealEditor(dish(2)); oldButton.click();
  assert.doesNotMatch(s.text(s.$('#meal-items')), /Banana/);
});
test('the current search still adds the selected food', async () => {
  const s = setup(); s.openMealEditor(dish()); s.$('#meal-search').value = 'banana'; const search = s.runMealSearch();
  s.last('foods').resolve({ foods: [food] }); await search; s.$('#meal-search-results').querySelector('button').click();
  assert.match(s.text(s.$('#meal-items')), /Banana/);
});

for (const reject of [false, true]) {
  test(`old editor save ${reject ? 'failure' : 'success'} preserves a newly opened draft`, async () => {
    const s = setup(); s.openMealEditor(dish()); await s.submit('meal');
    s.close('meal'); s.openMealEditor(dish(2)); s.$('#meal-name').value = 'New draft';
    await s.submit('meal'); assert.equal(s.count('updateMeal'), 1);
    assert.equal(s.$('#meal-save').disabled, true);
    if (reject) s.last('updateMeal').reject(new Error('old save failed')); else s.last('updateMeal').resolve(dish());
    await settle();
    assert.equal(s.$('#sheet-meal').open, true); assert.equal(s.$('#meal-name').value, 'New draft');
    assert.equal(s.$('#meal-save').disabled, false); assert.deepEqual(s.errors, []);
    assert.equal(s.notices.includes('An earlier save did not go through. Check it and try again.'), reject); // the earlier failure is still said
  });
}
test('saving freezes the submitted editor, rejects duplicates, and a failure restores the draft', async () => {
  const s = setup(); s.openMealEditor(dish()); await s.submit('meal'); await s.submit('meal');
  assert.equal(s.count('updateMeal'), 1); assert.equal(s.$('#meal-name').disabled, true);
  assert.equal(s.$('#meal-search').disabled, true); assert.equal(s.$('#meal-delete').disabled, true);
  s.last('updateMeal').reject(new Error('save failed')); await settle();
  assert.equal(s.$('#sheet-meal').open, true); assert.equal(s.$('#meal-name').value, 'Meal 1');
  assert.equal(s.$('#meal-name').disabled, false); assert.deepEqual(s.errors, ['save failed']);
  await s.submit('meal'); assert.equal(s.count('updateMeal'), 2);
  assert.equal(s.last('updateMeal').args[0], 1); s.last('updateMeal').resolve(dish()); await settle();
  assert.equal(s.$('#sheet-meal').open, false);
});
test('deleting a saved meal cannot close another editor opened while it waited', async () => {
  const s = setup(); s.openMealEditor(dish()); s.$('#meal-delete').click();
  s.close('meal'); s.openMealEditor(dish(2)); s.deletes[0].after();
  assert.equal(s.$('#sheet-meal').open, true);
});

for (const reject of [false, true]) {
  test(`old Save as meal ${reject ? 'failure' : 'success'} preserves the new opening`, async () => {
    const s = setup(); s.openSaveMealSheet('2026-11-06', 'lunch', []); s.$('#savemeal-name').value = 'Lunch'; await s.submit('savemeal');
    s.close('savemeal'); s.openSaveMealSheet('2026-12-01', 'dinner', []); s.$('#savemeal-name').value = 'Dinner';
    assert.equal(s.last('mealFromLog').args[0].date, '2026-11-06');
    await s.submit('savemeal'); assert.equal(s.count('mealFromLog'), 1);
    if (reject) s.last('mealFromLog').reject(new Error('old save failed')); else s.last('mealFromLog').resolve(dish());
    await settle(); assert.equal(s.$('#sheet-savemeal').open, true); assert.equal(s.$('#savemeal-name').value, 'Dinner');
    assert.equal(s.$('#savemeal-save').disabled, false); assert.deepEqual(s.errors, []);
    assert.equal(s.notices.includes('An earlier save did not go through. Check it and try again.'), reject); // the earlier failure is still said
  });
}
test('Save as meal freezes fields while saving and restores them after a failure', async () => {
  const s = setup(); s.openSaveMealSheet('2026-11-06', 'lunch', []); s.$('#savemeal-name').value = 'Lunch'; await s.submit('savemeal');
  assert.equal(s.$('#savemeal-name').disabled, true); s.last('mealFromLog').reject(new Error('failed')); await settle();
  assert.equal(s.$('#savemeal-name').disabled, false); assert.equal(s.$('#savemeal-name').value, 'Lunch');
});
test('an old apply reply leaves the new sheet open and does not navigate to the submitted day', async () => {
  const s = setup(); await s.openApplySheet({ mealId: 1, date: '2026-11-06' }); await s.submit('apply');
  s.close('apply'); await s.openApplySheet({ mealId: 2, date: '2026-12-01' }); s.state.view = 'add';
  await s.submit('apply'); assert.equal(s.count('applyMeal'), 1);
  s.last('applyMeal').resolve({ entries: [] }); await settle();
  assert.equal(s.$('#sheet-apply').open, true); assert.equal(s.$('#apply-date').value, '2026-12-01');
  assert.equal(s.changes[0][0], null); assert.equal(s.changes[0][1].goToDay, false);
});
test('an older saved-meal load cannot reopen or replace the latest Add to a day choice', async () => {
  const s = setup(), first = deferred(), next = deferred(); s.pendingLoads.push(first, next);
  const old = s.openApplySheet({ mealId: 1, date: '2026-11-06' }); const current = s.openApplySheet({ mealId: 2, date: '2026-12-01' });
  next.resolve(); await current; first.resolve(); await old;
  assert.equal(s.$('#apply-date').value, '2026-12-01'); assert.equal(s.$('#apply-meal-id').value, '2');
});
test('a queued close event from the former opening does not cancel the next meal load', async () => {
  const s = setup(); await s.openApplySheet({ mealId: 1 });
  s.$('#sheet-apply').open = false; // browsers queue the close event
  const load = deferred(); s.pendingLoads.push(load);
  const next = s.openApplySheet({ mealId: 2, date: '2026-12-01' });
  s.$('#sheet-apply').fire('close'); load.resolve(); await next;
  assert.equal(s.$('#sheet-apply').open, true); assert.equal(s.$('#apply-meal-id').value, '2');
});
test('applying the displayed meal while another opening loads cannot close that next opening', async () => {
  const s = setup(); await s.openApplySheet({ mealId: 1 });
  const load = deferred(); s.pendingLoads.push(load);
  const next = s.openApplySheet({ mealId: 2, date: '2026-12-01' }); await s.submit('apply');
  load.resolve(); await next; s.last('applyMeal').resolve({ entries: [] }); await settle();
  assert.equal(s.$('#sheet-apply').open, true); assert.equal(s.$('#apply-meal-id').value, '2');
});
for (const reject of [false, true]) {
  test(`old Copy day ${reject ? 'failure' : 'success'} preserves the new dates and current day`, async () => {
    const s = setup(); s.openCopySheet({ from: '2026-11-06', to: '2026-11-07' }); await s.submit('copy');
    assert.equal(s.$('#copy-from').disabled, true);
    s.close('copy'); s.openCopySheet({ from: '2026-12-01', to: '2026-12-02' }); await s.submit('copy');
    assert.equal(s.count('copyDay'), 1); assert.equal(s.$('#copy-save').disabled, true);
    if (reject) s.last('copyDay').reject(new Error('old copy failed')); else s.last('copyDay').resolve({ created: 1 });
    await settle(); assert.equal(s.$('#sheet-copy').open, true); assert.equal(s.$('#copy-to').value, '2026-12-02');
    assert.equal(s.$('#copy-save').disabled, false); assert.deepEqual(s.errors, []);
    assert.equal(s.notices.includes('An earlier save did not go through. Check it and try again.'), reject); // the earlier failure is still said
    if (!reject) assert.equal(s.changes[0][0], null);
  });
}
test('Copy day failure keeps the current dates and restores fields for retry', async () => {
  const s = setup(); s.openCopySheet({ from: '2026-11-06', to: '2026-11-07' }); await s.submit('copy');
  s.last('copyDay').reject(new Error('copy failed')); await settle();
  assert.equal(s.$('#sheet-copy').open, true); assert.equal(s.$('#copy-from').disabled, false);
  assert.equal(s.$('#copy-to').value, '2026-11-07'); assert.deepEqual(s.errors, ['copy failed']);
});
test('Add to a day failure restores the current submitted fields', async () => {
  const s = setup(); await s.openApplySheet({ mealId: 1, date: '2026-11-06' }); await s.submit('apply');
  assert.equal(s.$('#apply-date').disabled, true);
  s.last('applyMeal').reject(new Error('apply failed')); await settle();
  assert.equal(s.$('#sheet-apply').open, true); assert.equal(s.$('#apply-date').disabled, false);
  assert.equal(s.$('#apply-date').value, '2026-11-06'); assert.deepEqual(s.errors, ['apply failed']);
});
