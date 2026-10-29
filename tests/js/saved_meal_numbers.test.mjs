// Render the real Plan view with saved meals and inspect its nutrient text.
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import test from 'node:test';

const root = new URL('../../', import.meta.url);
const read = (path) => readFileSync(new URL(path, root), 'utf8');

async function render(meal) {
  const elements = new Map();
  const el = () => ({ children: [], style: {}, append(...nodes) { this.children.push(...nodes); }, addEventListener() {} });
  const $ = (key) => {
    if (!elements.has(key)) elements.set(key, el());
    return elements.get(key);
  };
  const KH = {
    $, views: {}, keys: {},
    state: { meals: [meal], profile: {}, planStart: '2026-10-26' },
    clear(node) { node.children = []; return node; },
    h(tag, attrs, ...children) { return Object.assign(el(), { tag, attrs, children }); },
    router: { register() {} }, sheets: { setup() {}, onSubmit() {} }, toastError() {},
    loadProfile: async () => {}, loadMeals: async () => [meal],
    api: { range: async () => { throw Error('not needed'); }, shopping: async () => { throw Error('not needed'); } },
    util: { debounce: (fn) => fn, todayStr: () => '2026-10-29', weekStartOf: () => '2026-10-26',
      addDays: (d) => d, fmtRange: () => '', fmtMonthDay: (d) => d },
  };
  const context = vm.createContext({ window: { KH }, console });
  vm.runInContext(read('app/static/js/engine/rules.js'), context);
  // Use the real shared missing-value helpers without booting the API client and router.
  const core = read('app/static/js/core.js');
  vm.runInContext(`(() => { const NUT = window.KH.rules.NUT;
    ${core.slice(core.indexOf('  function unknownOf('), core.indexOf('  function levelPill('))}
    window.KH.ui = { unknownOf, notListed, foodsNotListing, atLeast, atLeastWords,
      ROW_NUMBERS: ['potassium_mg', 'phosphorus_mg', 'sodium_mg'], ratingIcon: () => null, plusIcon: () => null };
  })()`, context);
  vm.runInContext(read('app/static/js/views/plan.js'), context);
  await KH.views.plan.loadPlan();
  const nodes = [];
  function walk(node) {
    if (!node || typeof node !== 'object') return;
    nodes.push(node);
    for (const child of node.children || []) walk(child);
  }
  walk($('#saved-meals'));
  const text = (node) => typeof node === 'string' ? node : (node?.children || []).map(text).join('');
  return nodes.filter((node) => node.attrs?.class?.split(' ').includes('n')).map(text);
}

for (const servings of [null, 1, 4]) {
  test(`saved-meal numbers distinguish missing, partial and known zero (makes ${servings})`, async () => {
    const numbers = await render({
      id: 1, name: 'Test meal', items: [{ servings: 1, food_name: 'Food' }, { servings: 1, food_name: 'Other food' }],
      servings_made: servings, kidney_rating: 'green',
      totals: { potassium_mg: 0, phosphorus_mg: 200, sodium_mg: 0 },
      per_serving: { potassium_mg: null, phosphorus_mg: servings === 4 ? 50 : 200, sodium_mg: 0 },
      unknown: { potassium_mg: 2, phosphorus_mg: 1 },
    });
    assert.equal(numbers[0], 'K not listed');
    assert.equal(numbers[1], `P ≥ ${servings === 4 ? 50 : 200} mg (+ 1 not listed)`);
    assert.equal(numbers[2], 'Na 0 mg');
  });
}

test('complete nonzero values stay exact', async () => {
  const numbers = await render({
    id: 1, name: 'Complete meal', items: [{ servings: 1, food_name: 'Food' }],
    servings_made: null, kidney_rating: 'green', unknown: {},
    totals: { potassium_mg: 300, phosphorus_mg: 150, sodium_mg: 40 },
    per_serving: { potassium_mg: 300, phosphorus_mg: 150, sodium_mg: 40 },
  });
  assert.deepEqual(numbers, ['K 300 mg', 'P 150 mg', 'Na 40 mg']);
});

test('a listed zero plus an unknown value stays a lower bound', async () => {
  const numbers = await render({
    id: 1, name: 'Incomplete meal', items: [{ servings: 1, food_name: 'Food' }, { servings: 1, food_name: 'Other food' }],
    servings_made: null, kidney_rating: 'green', unknown: { sodium_mg: 1 },
    totals: { potassium_mg: 300, phosphorus_mg: 150, sodium_mg: 0 },
    per_serving: { potassium_mg: 300, phosphorus_mg: 150, sodium_mg: 0 },
  });
  assert.equal(numbers[2], 'Na ≥ 0 mg (+ 1 not listed)');
});
