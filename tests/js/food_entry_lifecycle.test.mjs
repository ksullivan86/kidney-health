// Real entry/Quick add handlers with held reads and writes. No network or storage twin.
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import test from 'node:test';
import { makePage, deferred, settle } from './fake_page.mjs';
const source = readFileSync(new URL('../../app/static/js/views/add.js', import.meta.url), 'utf8');
const begin = source.indexOf("  const entryDlg = $('#sheet-entry');");
const end = source.indexOf("  const usdaDlg =", begin);
assert.ok(begin >= 0 && end > begin);
const food = (id = 1) => ({ id, name: `Food ${id}`, source: 'custom', serving_g: 100, serving_desc: '1 serving',
  nutrients: { calories_kcal: 100, potassium_mg: 20 }, flags: [], kidney_rating: 'green' });
const entry = (id = 1) => ({ id, food_id: id, food_name: `Food ${id}`, date: '2026-11-06', meal: 'lunch',
  servings: 2, grams: null, note: 'Existing note', status: 'eaten', version: `version-${id}`,
  nutrients: { calories_kcal: 200, potassium_mg: 40 }, kidney_rating: 'green' });
function setup({ hypo = false } = {}) {
  const page = makePage(), calls = [], errors = [], notices = [], routes = [], confirms = [], fields = [], changes = [];
  const state = { date: '2026-11-06', view: 'add', day: null, dayLoadedFor: null };
  const queryAll = (sel, scope) => {
    const m = /^(#[\w-]+)\s+(.+)$/.exec(sel);
    if (m) return queryAll(m[2], page.$(m[1]));
    if (sel === 'input:checked') return page.$$('input', scope).filter((el) => el.checked);
    return page.$$(sel, scope);
  };
  const $ = (sel, scope) => sel === 'input:checked' ? queryAll(sel, scope)[0] || null : page.$(sel, scope);
  for (const type of ['entry', 'quick']) {
    const form = page.$(`#${type}-form`); form.tag = 'form'; page.$(`#sheet-${type}`).append(form);
    const ids = type === 'entry' ? ['entry-servings', 'entry-grams', 'entry-note', 'entry-date']
      : ['q-name', 'q-gtin', 'q-serving-desc', 'q-serving-g', 'q-servings', 'q-ingredients'];
    for (const id of ids) {
      const el = page.$(`#${id}`); el.tag = /note|ingredients/.test(id) ? 'textarea' : 'input';
      const field = page.h('div', { class: 'field' }); field.append(el); form.append(field);
    }
    for (const group of ['meal', 'status']) {
      const box = page.$(`#${type}-${group}`); form.append(box);
      for (const value of group === 'meal' ? ['lunch', 'dinner'] : ['eaten', 'planned']) {
        const input = page.h('input'); input.value = value; box.append(input);
      }
    }
    const foot = page.h('div', { class: 'sheet-foot' }); form.append(foot);
    for (const id of type === 'entry' ? ['entry-save', 'entry-delete', 'entry-delete-food'] : ['quick-save']) {
      const button = page.$(`#${id}`); button.tag = 'button'; foot.append(button);
    }
    const close = page.h('button', { 'data-close': true }); close.tag = 'button'; foot.append(close);
    form.reset = () => { for (const el of queryAll('input, textarea', form)) { el.value = ''; el.checked = false; } };
  }
  for (const id of ['quick-nutrients', 'quick-flags']) page.$('#quick-form').append(page.$(`#${id}`));
  const step = page.h('button', { class: 'step-btn' }); step.dataset.step = '1'; page.$('#entry-form').append(step);
  page.$('#sync-badge').tag = 'button'; page.$('#sync-badge').addEventListener('click', () => routes.push('conflicts'));
  const request = (method) => (...args) => { const d = deferred(); calls.push({ method, args, ...d }); return d.promise; };
  const group = (el, value) => { el.value = value; for (const input of queryAll('input', el)) input.checked = input.value === value; };
  const nutrients = [{ key: 'calories_kcal', label: 'Calories', unit: 'kcal' }, { key: 'potassium_mg', label: 'Potassium', unit: 'mg' }];
  const forms = {
    clearFieldErrors() { fields.length = 0; },
    fieldError(el, message) { fields.push({ id: el.id, message }); },
    splitFieldErrors(detail) { const m = /^(\w+):\s*(.*)$/.exec(detail || ''); return m ? [{ field: m[1], message: m[2] }] : []; },
  };
  const KH = { forms, views: { today: { setDate(day) { changes.push(day); state.date = day; }, loadDay() { changes.push('reload'); } } } };
  if (hypo) KH.guidance = { entry: { open() {}, update() {}, isHypo: () => true, renderHypoNote() {}, purpose: () => 'hypo_treatment' } };
  const context = vm.createContext({ ...page, $, $$: queryAll, KH, state, console,
    h(tag, attrs, ...kids) { const el = page.h(tag, attrs, ...kids); if (attrs?.value != null) el.value = String(attrs.value);
      for (const [key, value] of Object.entries(attrs || {})) if (key.startsWith('data-')) el.dataset[key.slice(5)] = value;
      return el; },
    sheets: { setup() {}, open(dlg) { dlg.open = true; }, onSubmit(form, fn) { form.addEventListener('submit', fn); } },
    api: Object.fromEntries(['food', 'addEntry', 'updateEntry', 'deleteEntry', 'deleteFood', 'quick'].map((name) => [name, request(name)])),
    confirm: { inline: (_host, _trigger, options) => confirms.push(options) },
    router: { show(view) { routes.push(view); state.view = view; } },
    toast: (message) => notices.push(message), toastError: (err) => errors.push(err.detail || err.message),
    NUTRIENTS: nutrients, NUT: Object.fromEntries(nutrients.map((n) => [n.key, n])), KEY_NUMBERS: [], FLAGS: [], FLAG: {},
    MEAL_LABEL: { lunch: 'Lunch', dinner: 'Dinner' }, LEVEL_TEXT: {},
    setMeal: group, setStatus: group, selectedMeal: (el) => el.value, selectedStatus: (el) => el.value,
    todayStr: () => '2026-11-06', defaultMealForNow: () => 'lunch', defaultStatusFor: () => 'eaten', fmtDateLong: String,
    fmtNum: String, fmtServings: String, fmtWithUnit: String, levelPill: () => page.h('span'), ratingIcon: () => '',
    scaledNutrients: (values, n) => Object.fromEntries(Object.entries(values || {}).map(([k, value]) => [k, value == null ? null : value * n])),
    evaluateWarnings: () => [], renderWarnings() {}, impactOn: () => [], numOrNull: (value) => value === '' ? null : Number(value),
    runSearch() { changes.push('search'); },
  });
  vm.runInContext(source.slice(begin, end) + '\nglobalThis.openers = {openEntrySheet, openQuick};', context);
  return { ...page, ...context.openers, calls, errors, notices, routes, confirms, fields, changes, state, step,
    async submit(type = 'entry') { page.$(`#${type}-form`).fire('submit'); await settle(); },
    close(type = 'entry') { page.$(`#sheet-${type}`).close(); },
    last(method) { return calls.filter((c) => c.method === method).at(-1); },
    count(method) { return calls.filter((c) => c.method === method).length; },
    async open(mode = 'add', id = 1) { await context.openers.openEntrySheet(mode, { food: food(id), ...(mode === 'edit' ? { entry: entry(id) } : {}) }); },
  };
}
async function startAction(s, action) {
  await s.open(action === 'edit' || action === 'deleteEntry' ? 'edit' : 'add');
  if (action === 'add' || action === 'edit') await s.submit();
  else { s.$(action === 'deleteEntry' ? '#entry-delete' : '#entry-delete-food').click(); s.confirms.at(-1).onConfirm(); await settle(); }
  return s.last({ add: 'addEntry', edit: 'updateEntry', deleteEntry: 'deleteEntry', deleteFood: 'deleteFood' }[action]);
}
for (const action of ['add', 'edit', 'deleteEntry', 'deleteFood']) {
  for (const failure of [false, true]) {
    test(`${action}: late ${failure ? 'failure' : 'success'} leaves another draft and view intact`, async () => {
      const s = setup(), call = await startAction(s, action);
      s.close(); await s.open('add', 2); s.$('#entry-note').value = 'Keep the next draft';
      if (failure) call.reject(new Error('Earlier request failed')); else call.resolve({ food_name: 'Food 1' });
      await settle();
      assert.equal(s.$('#sheet-entry').open, true); assert.equal(s.$('#entry-note').value, 'Keep the next draft');
      assert.deepEqual(s.routes, []); assert.deepEqual(s.errors, []);
      assert.equal(s.notices.includes('An earlier save did not go through. Check it and try again.'), failure); // the earlier failure is still said
      assert.equal(s.$('#entry-save').disabled, false);
    });
  }
}
test('reopening the entry sheet cannot submit a second write before the first settles', async () => {
  const s = setup(); await s.open(); await s.submit(); s.close(); await s.open('edit', 2); await s.submit();
  assert.equal(s.count('addEntry') + s.count('updateEntry'), 1); assert.equal(s.$('#entry-save').disabled, true);
  s.last('addEntry').resolve({ food_name: 'Food 1' }); await settle();
  assert.equal(s.$('#entry-save').disabled, false); await s.submit(); assert.equal(s.count('updateEntry'), 1);
  s.last('updateEntry').resolve({ pending: true }); await settle();
});
for (const failure of [false, true]) {
  test(`Quick add late ${failure ? 'field refusal' : 'save'} preserves the next food draft`, async () => {
    const s = setup(); s.openQuick({ name: 'First food' }); s.$('#qn-calories_kcal').value = '100'; await s.submit('quick');
    const call = s.last('quick'); assert.ok(call); s.close('quick'); s.openQuick({ name: 'Next food' });
    if (failure) call.reject({ status: 400, detail: 'name: Old name refused' }); else call.resolve({ food_name: 'First food', pending: true });
    await settle(); assert.equal(s.$('#sheet-quick').open, true); assert.equal(s.$('#q-name').value, 'Next food');
    assert.deepEqual(s.fields, []); assert.deepEqual(s.errors, []); assert.deepEqual(s.routes, []);
    assert.equal(s.$('#quick-save').disabled, false);
  });
}
for (const failure of [false, true]) {
  test(`an old serving-size ${failure ? 'error' : 'reply'} stays out of the next entry`, async () => {
    const s = setup(), old = s.openEntrySheet('edit', { entry: entry() });
    s.close(); await s.open('add', 2);
    if (failure) s.last('food').reject(new Error('Old lookup failed')); else s.last('food').resolve(food());
    await old; assert.match(s.text(s.$('#sheet-entry-food')), /Food 2/);
    assert.equal(s.$('#entry-grams-hint').textContent, '1 serving = 100 g');
  });
}
test('reopening the same entry object still invalidates its earlier metadata read', async () => {
  const s = setup(), row = entry(), old = s.openEntrySheet('edit', { entry: row });
  s.close(); const current = s.openEntrySheet('edit', { entry: row });
  const reads = s.calls.filter((c) => c.method === 'food');
  reads[1].resolve({ ...food(), name: 'Newest food' }); await current;
  reads[0].resolve({ ...food(), name: 'Old food' }); await old;
  assert.match(s.text(s.$('#sheet-entry-food')), /Newest food/);
});
test('submitted entry values freeze and recover after a current failure', async () => {
  const s = setup(); await s.open(); s.$('#entry-note').value = 'Submitted note'; await s.submit();
  assert.equal(s.$('#entry-note').disabled, true); assert.equal(s.step.disabled, true);
  s.last('addEntry').reject(new Error('Try again')); await settle();
  assert.equal(s.$('#sheet-entry').open, true); assert.equal(s.$('#entry-note').value, 'Submitted note');
  assert.equal(s.$('#entry-note').disabled, false); assert.equal(s.step.disabled, false); assert.deepEqual(s.errors, ['Try again']);
});
test('a food lookup cannot unlock fields or change submitted grams while saving', async () => {
  const s = setup(), reading = s.openEntrySheet('edit', { entry: entry() });
  await s.submit(); s.last('food').resolve(food()); await reading;
  assert.equal(s.$('#entry-grams').disabled, true); assert.equal(s.$('#entry-grams').value, '');
  s.last('updateEntry').reject(new Error('Try again')); await settle();
  assert.equal(s.$('#entry-grams').disabled, false); assert.equal(s.$('#entry-grams').value, '200');
});
test('offline edits keep their base version and omit untouched amounts', async () => {
  const s = setup(); await s.open('edit'); await s.submit(); const call = s.last('updateEntry');
  assert.equal(call.args[0], 1); assert.equal(call.args[2].version, 'version-1');
  assert.equal('servings' in call.args[1], false); assert.equal('grams' in call.args[1], false);
  call.resolve({ pending: true }); await settle(); assert.equal(s.$('#sheet-entry').open, false);
  assert.ok(s.notices.some((n) => n.startsWith('Saved on this device')));
});
test('an active offline conflict still opens its review card', async () => {
  const s = setup(); await s.open('edit'); await s.submit(); s.last('updateEntry').reject({ conflict: true, message: 'Needs review' });
  await settle(); assert.equal(s.$('#sheet-entry').open, false); assert.ok(s.routes.includes('conflicts'));
});
test('a late offline conflict does not close the next draft or navigate away', async () => {
  const s = setup(); await s.open('edit'); await s.submit(); s.close(); await s.open('add', 2);
  s.last('updateEntry').reject({ conflict: true, message: 'Needs review' }); await settle();
  assert.equal(s.$('#sheet-entry').open, true); assert.deepEqual(s.routes, []);
});
test('low-treatment logging still sends its purpose normally', async () => {
  const s = setup({ hypo: true }); await s.open(); await s.submit();
  assert.equal(s.last('addEntry').args[0].purpose, 'hypo_treatment');
  s.last('addEntry').resolve({ food_name: 'Food 1' }); await settle(); assert.equal(s.$('#sheet-entry').open, false);
});
test('a failed offline edit keeps an unavailable grams field disabled', async () => {
  const s = setup(); await s.openEntrySheet('edit', { entry: { ...entry(), food_id: null } });
  await s.submit(); s.last('updateEntry').reject(new Error('Try again')); await settle();
  assert.equal(s.$('#entry-grams').disabled, true);
  assert.equal(s.$('#entry-grams-hint').textContent, 'Serving size unavailable offline');
});
for (const changedDay of [false, true]) {
  test(`an edit date ${changedDay ? 'does not replace a newer page date' : 'still moves the active view when requested'}`, async () => {
    const s = setup(); await s.open('edit'); s.$('#entry-date').value = '2026-11-05'; await s.submit();
    if (changedDay) s.state.date = '2026-11-07';
    s.last('updateEntry').resolve({}); await settle();
    assert.equal(s.state.date, changedDay ? '2026-11-07' : '2026-11-05');
  });
}
