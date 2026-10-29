// The real Add-a-saved-meal sheet uses recipe servings while retaining the API's pot-scale contract.
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import test from 'node:test';

const source = readFileSync(new URL('../../app/static/js/views/plan.js', import.meta.url), 'utf8');
const start = source.indexOf("  const applyDlg = $('#sheet-apply');");
const end = source.indexOf('  // ---- Save a logged meal', start);
assert.ok(start >= 0 && end > start);
const template = (makes = 4) => ({ id: 1, name: 'Recipe', servings_made: makes, note: null,
  items: [{ food_id: 1, food_name: 'Food', servings: 4, kidney_rating: 'green' }],
  totals: { carbs_g: 80, potassium_mg: 400 }, per_serving: { carbs_g: 80 / (makes || 1), potassium_mg: 400 / (makes || 1) }, unknown: {} });

function setup(t = template()) {
  const nodes = new Map(), calls = [], toasts = [];
  function h(tag = '', attrs = {}, ...children) {
    return { tag, attrs, children: children.flat(Infinity).filter((c) => c != null), value: '', hidden: false, disabled: false, open: false,
      handlers: {}, append(...kids) { this.children.push(...kids); },
      addEventListener(type, fn) { (this.handlers[type] ||= []).push(fn); }, close() { this.open = false; }, focus() {} };
  }
  const $ = (selector) => { if (!nodes.has(selector)) nodes.set(selector, h()); return nodes.get(selector); };
  let submit;
  const state = { meals: [t], date: '2026-10-29', day: null, dayLoadedFor: null, view: 'plan' };
  const context = vm.createContext({ window: { KH: {} }, console });
  vm.runInContext(readFileSync(new URL('../../app/static/js/engine/rules.js', import.meta.url), 'utf8'), context);
  const rules = context.window.KH.rules;
  Object.assign(context, {
    $, h, state, clear: (node) => { node.children = []; return node; }, KH: { loadMeals: async () => state.meals },
    sheets: { setup() {}, onSubmit: (form, handler) => { submit = handler; }, open: (dialog) => { dialog.open = true; } },
    isRecipe: (meal) => meal.servings_made != null && meal.servings_made !== 1,
    api: { applyMeal: async (id, body) => { calls.push({ id, body }); return { entries: [{}] }; } },
    NUT: rules.NUT, KEY_NUMBERS: ['carbs_g', 'potassium_mg'], fmtNum: rules.fmtNum, fmtServings: rules.fmtServings,
    scaledNutrients: rules.scaleNutrients, ratingIcon: () => null, LEVEL_TEXT: {}, MEAL_LABEL: { dinner: 'Dinner' },
    unknownOf: (counts, key) => counts?.[key] || 0, foodsNotListing: (count) => `${count} not listed`,
    atLeast: (text, count) => count ? `≥ ${text}` : text, selectedMeal: () => 'dinner', selectedStatus: () => 'planned',
    setMeal() {}, setStatus() {}, defaultMealForNow: () => 'dinner', defaultStatusFor: () => 'planned',
    todayStr: () => '2026-10-29', fmtDateLong: String, afterLogChange() {}, toast: (text) => toasts.push(text), toastError: (e) => { throw e; },
  });
  vm.runInContext(source.slice(start, end), context);
  return { $, calls, toasts, state, context, open: () => context.openApplySheet({ mealId: 1 }),
    submit: () => submit({ preventDefault() {} }), preview: () => context.updateApplyPreview() };
}
const text = (node) => node == null ? '' : typeof node === 'object' ? node.children.map(text).join(' ') : String(node);
const number = (s, i = 0) => text(s.$('#apply-preview-key').children[i].children.find((n) => n.attrs?.class === 'kn-v'));

test('opening a recipe defaults to one serving in both ingredient and nutrient previews', async () => {
  const s = setup(); await s.open();
  assert.equal(s.$('#apply-scale-label').textContent, 'Servings to add');
  assert.equal(number(s), '20');
  assert.match(s.$('#apply-preview-amount').textContent, /1 serving of this recipe/);
  const amount = s.$('#apply-items').children[0].children.find((n) => n.attrs?.class === 'ci-amt muted');
  assert.equal(text(amount), '1 serving');
  await s.submit(); assert.equal(s.calls[0].body.scale, 0.25);
});
test('two recipe servings preview and submit half of a four-serving pot', async () => {
  const s = setup(); await s.open(); s.$('#apply-scale').value = '2'; s.preview();
  assert.equal(number(s), '40'); await s.submit(); assert.equal(s.calls[0].body.scale, 0.5);
});
test('a three-serving recipe converts one serving without rounding its request fraction', async () => {
  const s = setup(template(3)); await s.open(); await s.submit();
  assert.equal(s.calls[0].body.scale, 1 / 3);
});
test('an ordinary saved meal keeps Scale 1 and sends no unnecessary scale field', async () => {
  const s = setup(template(null)); await s.open();
  assert.equal(s.$('#apply-scale-label').textContent, 'Scale'); assert.equal(number(s), '80');
  await s.submit(); assert.equal(s.calls[0].body.scale, undefined);
});
test('a recipe that makes a quarter serving multiplies by four for one serving', async () => {
  const s = setup(template(0.25)); await s.open();
  assert.equal(number(s), '320'); await s.submit(); assert.equal(s.calls[0].body.scale, 4);
});
test('fractional Makes respects the existing API scale maximum', async () => {
  const s = setup(template(0.25)); await s.open();
  assert.equal(s.$('#apply-scale').max, '25');
  s.$('#apply-scale').value = '25'; await s.submit(); assert.equal(s.calls[0].body.scale, 100);
});
test('too many recipe servings are refused before sending and keep the sheet open', async () => {
  const s = setup(template(0.25)); await s.open(); s.$('#apply-scale').value = '26'; await s.submit();
  assert.equal(s.calls.length, 0); assert.equal(s.$('#sheet-apply').open, true); assert.match(s.toasts[0], /25/);
});
test('switching to an ordinary saved meal resets the label and limit', async () => {
  const s = setup(template(0.25)); await s.open(); s.state.meals[0] = template(null); s.preview();
  assert.equal(s.$('#apply-scale-label').textContent, 'Scale'); assert.equal(s.$('#apply-scale').max, '100');
});
test('partial and wholly missing nutrients keep their qualifiers per recipe serving', async () => {
  const t = template(); t.unknown.potassium_mg = 1;
  const s = setup(t); await s.open(); assert.equal(number(s, 1), '≥ 100');
  t.per_serving.potassium_mg = null; t.totals.potassium_mg = 0; s.preview();
  assert.equal(number(s, 1), 'not listed');
});
test('zero remains invalid and cannot send an apply request', async () => {
  const s = setup(); await s.open(); s.$('#apply-scale').value = '0'; await s.submit();
  assert.equal(s.calls.length, 0);
});
