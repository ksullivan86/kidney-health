// Execute the real Fit sheet with delayed mutations and dialog changes.
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import test from 'node:test';

const source = readFileSync(new URL('../../app/static/js/views/plan.js', import.meta.url), 'utf8');
const start = source.indexOf("  const fitDlg = $('#sheet-fit');");
const end = source.indexOf("  router.register('plan'", start);
assert.ok(start >= 0 && end > start);
// The real helpers from core.js that the sheet uses for "≥" and "at least".
const core = readFileSync(new URL('../../app/static/js/core.js', import.meta.url), 'utf8');
const helper = (name) => {
  const at = core.indexOf(`  function ${name}(`);
  assert.ok(at >= 0, name);
  const line = core.slice(at, core.indexOf('\n', at));
  return line.trimEnd().endsWith('}') ? line : core.slice(at, core.indexOf('\n  }\n', at) + 4);
};
const settle = async () => { for (let i = 0; i < 12; i++) await Promise.resolve(); };
const meal = (id) => ({ id, name: id === 1 ? 'Recipe A' : 'Recipe B', items: [{ food_id: id * 100, servings: 2 }],
  servings_made: 2, steps: null, note: null });
const result = (id) => ({ status: 'fits_after_changes', servings_made: 2,
  before: { per_serving: { carbs_g: id * 20 }, unknown: {}, checks: [] },
  after: { per_serving: { carbs_g: id * 10 }, unknown: {}, checks: [] },
  fitted: { items: [{ food_id: id * 100, servings: 1, name: 'Food', portion_text: '1 serving' }], serving_fraction: 1 },
  changes: [], notes: [] });

function setup({ slowRead = false, slowCache = false } = {}) {
  const nodes = new Map(), calls = { updates: [], creates: [], reads: [], caches: [], confirms: [], toasts: [], errors: [] };
  function element(tag = '', attrs = {}, ...children) {
    const node = { tag, attrs, children: children.flat(Infinity).filter((c) => c != null), handlers: {},
      hidden: false, disabled: false, open: false, value: '',
      append(...kids) { this.children.push(...kids.flat(Infinity)); },
      addEventListener(type, fn) { (this.handlers[type] ||= []).push(fn); },
      close() { this.open = false; for (const fn of this.handlers.close || []) fn({}); },
      fire(type) { return Promise.all((this.handlers[type] || []).map((fn) => fn({ currentTarget: this }))); },
    };
    return node;
  }
  const $ = (selector) => { if (!nodes.has(selector)) nodes.set(selector, element()); return nodes.get(selector); };
  const deferred = (array, details) => new Promise((resolve, reject) => array.push({ ...details, resolve, reject }));
  const context = vm.createContext({
    $, h: element, clear: (node) => { node.children = []; return node; },
    api: { fitRecipe: ({ meal_id }) => slowRead ? deferred(calls.reads, { meal_id }) : Promise.resolve(result(meal_id)),
      updateMeal: (id, body) => deferred(calls.updates, { id, body }), createMeal: (body) => deferred(calls.creates, { body }) },
    KH: { loadMeals: () => slowCache ? deferred(calls.caches, {}) : Promise.resolve([]), ai: {} },
    sheets: { open: (dialog) => { dialog.open = true; } },
    confirm: { inline: (host, trigger, config) => calls.confirms.push(config), dismiss() {} },
    NUT: { carbs_g: { unit: 'g', short: 'C', label: 'Carbohydrate' } },
    fmtNum: (v) => String(v), fmtServings: String, isRecipe: () => true, shownNote: (t) => t.note,
    todayStr: () => '2026-10-29', aiRecipesOn: () => Promise.resolve(false),
    renderSavedMeals() {}, afterAiSave() {},
    toast: (message) => calls.toasts.push(message), toastError: (error) => calls.errors.push(error),
  });
  vm.runInContext(['unknownOf', 'atLeast', 'atLeastWords'].map(helper).join('\n'), context);
  vm.runInContext(source.slice(start, end) + '\nglobalThis.getFit = () => fit;', context);
  const open = async (id) => { context.openFitSheet(meal(id), null); await settle(); };
  const replace = async () => { await $('#fit-replace').fire('click'); return calls.confirms.at(-1); };
  return { $, calls, context, open, replace, close: () => $('#sheet-fit').close(), fit: () => context.getFit() };
}

test('a late Replace for A cannot offer its Undo against recipe B', async () => {
  const s = setup(); await s.open(1);
  const confirm = await s.replace(), pending = confirm.onConfirm();
  s.close(); await s.open(2);
  s.calls.updates[0].resolve({}); await pending;
  assert.equal(s.fit().meal.id, 2);
  assert.equal(s.fit().undo, null);
  await s.context.undoReplace();
  assert.equal(s.calls.updates.length, 1, 'no request can overwrite B with A');
});
test('a changed fit target cannot inherit an Undo from the older result', async () => {
  const s = setup(); await s.open(1);
  const confirm = await s.replace(), pending = confirm.onConfirm();
  s.$('#fit-target').value = 'dinner'; await s.$('#fit-target').fire('change'); await settle();
  s.calls.updates[0].resolve({}); await pending;
  assert.equal(s.fit().undo, null);
});
test('a stale confirmation cannot replace a newly opened recipe', async () => {
  const s = setup(); await s.open(1);
  const confirm = await s.replace();
  s.close(); await s.open(2);
  const pending = confirm.onConfirm(); await settle();
  // Allow the baseline request to finish so the failed assertion reports the wrong mutation.
  if (s.calls.updates.length) s.calls.updates[0].resolve({});
  await pending;
  assert.equal(s.calls.updates.length, 0);
});
test('a late fitted-copy success does not close a newer dialog or describe B carbs', async () => {
  const s = setup(); await s.open(1);
  const pending = s.$('#fit-save').fire('click');
  s.close(); await s.open(2);
  s.calls.creates[0].resolve({ name: 'Recipe A (fitted)' }); await pending;
  assert.equal(s.$('#sheet-fit').open, true);
  assert.match(s.calls.toasts[0], /20 g to 10 g/);
  assert.doesNotMatch(s.calls.toasts[0], /40 g|20 g\.$/);
});
test('closing the dialog invalidates a pending fit read', async () => {
  const s = setup({ slowRead: true }); await s.open(1); s.close();
  s.calls.reads[0].resolve(result(1)); await settle();
  assert.equal(s.fit().result, null);
});
test('normal Replace and Undo write the original recipe id and restore its body', async () => {
  const s = setup(); await s.open(1);
  const confirm = await s.replace(), replaced = confirm.onConfirm();
  s.calls.updates[0].resolve({}); await replaced;
  assert.ok(s.fit().undo);
  const undone = s.context.undoReplace();
  assert.equal(s.calls.updates[1].id, 1);
  assert.equal(s.calls.updates[1].body.name, 'Recipe A');
  assert.equal(s.calls.updates[1].body.items[0].servings, 2);
  s.calls.updates[1].resolve({}); await undone;
  assert.equal(s.fit().undo, null);
});
test('Undo completing after a new dialog opens still describes and restores A', async () => {
  const s = setup(); await s.open(1);
  const confirm = await s.replace(), replaced = confirm.onConfirm();
  s.calls.updates[0].resolve({}); await replaced;
  const undone = s.context.undoReplace();
  s.close(); await s.open(2);
  s.calls.updates[1].resolve({}); await undone;
  assert.equal(s.calls.updates[1].id, 1);
  assert.match(s.calls.toasts.at(-1), /Recipe A/);
  assert.doesNotMatch(s.calls.toasts.at(-1), /Recipe B/);
  assert.equal(s.fit().undo, null);
});
test('a refused Replace keeps retry available without an Undo for a write that failed', async () => {
  const s = setup(); await s.open(1);
  const confirm = await s.replace(), failed = confirm.onConfirm();
  s.calls.updates[0].reject(Error('offline'));
  assert.equal(await failed, false);
  assert.equal(s.fit().undo, null);
  const retry = confirm.onConfirm(); s.calls.updates[1].resolve({});
  assert.equal(await retry, true);
  assert.ok(s.fit().undo);
});
