// Exercise the real AI UI with deferred replies; no AI service or consent is sent anywhere.
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import test from 'node:test';

const root = new URL('../../app/static/js/', import.meta.url);
const text = (node) => typeof node === 'string' ? node : (node?.children || []).map(text).join('');
const all = (node) => !node || typeof node !== 'object' ? [] : [node, ...node.children.flatMap(all)];
const settle = async () => { for (let i = 0; i < 10; i++) await Promise.resolve(); };

function setup() {
  function h(tag, attrs = {}, ...children) {
    const node = { tag, attrs, children: children.flat(Infinity).filter((v) => v != null), handlers: {}, dataset: {},
      disabled: false, hidden: attrs.hidden != null, checked: attrs.checked != null, value: attrs.value || '', id: attrs.id,
      append(...nodes) { this.children.push(...nodes.flat(Infinity).filter((v) => v != null)); },
      setAttribute(k, v) { this.attrs[k] = v; }, removeAttribute(k) { delete this.attrs[k]; },
      addEventListener(kind, fn) { this.handlers[kind] = fn; },
    };
    Object.defineProperty(node, 'textContent', { get() { return text(this); }, set(v) { this.children = [String(v)]; } });
    if (tag === 'select') node.value = (node.children.find((n) => n.attrs.selected != null) || node.children[0])?.value;
    return node;
  }
  const sheet = h('dialog', {}, h('h2', { class: 'sheet-title' }), h('p', { class: 'sheet-sub' }),
    h('div', { class: 'sheet-body' }), h('footer', { class: 'sheet-foot' }));
  const $ = (selector, parent) => {
    if (!parent) return selector === '#sheet-ai' ? sheet : null;
    if (selector.startsWith('.')) return all(parent).find((n) => (n.attrs.class || '').split(' ').includes(selector.slice(1)));
    const name = /name="([^"]+)"/.exec(selector)?.[1];
    return all(parent).find((n) => n.tag === 'input' && n.attrs.name === name && n.checked);
  };
  const calls = [], writes = [];
  const KH = { $, $$: () => [], h, state: { date: '2026-10-29' }, flags: { MOCK: false }, util: { fmtDateLong: (d) => d },
    ui: { ratingIcon: () => null, RATING_LABEL: {} }, sheets: { setup() {}, open() {} }, toast() {}, toastError() {},
    clear(node) { node.children = []; return node; },
  };
  const context = vm.createContext({ window: { KH }, document: { contains: () => true }, console });
  for (const path of ['engine/rules.js', 'views/ai.js']) vm.runInContext(readFileSync(new URL(path, root), 'utf8'), context);
  KH.ai.api.me = async () => ({ enabled: true });
  KH.ai.api.status = async () => ({ enabled: true, consent: { text: { skip_preview: true } } });
  for (const feature of ['nextMeal', 'recipes']) KH.ai.api[feature] = (body) => new Promise((resolve, reject) => calls.push({ body, resolve, reject }));
  KH.ai.api.logBatch = async (entries) => { writes.push(...entries); };
  const ideas = () => {
    const box = h('div');
    const controller = KH.ai.mountIdeas(box, { date: '2026-10-29', meal: 'breakfast' });
    return { box, controller, out: box.children[2], error: box.children[1] };
  };
  const recipes = () => {
    KH.ai.openRecipes({ meal: 'breakfast', date: '2026-10-29' });
    const body = $('.sheet-body', sheet);
    return { box: body, out: all(body).find((n) => n.attrs.class === 'ai-results'),
      error: all(body).find((n) => n.attrs.class === 'form-error') };
  };
  const button = (box, label) => all(box).find((n) => n.tag === 'button' && text(n) === label);
  return { KH, h, calls, writes, ideas, recipes, button };
}

const idea = { title: 'Breakfast answer', why: '', items: [{ food_id: 1, name: 'Food', servings: 1 }],
  totals: {}, after: { carbs_g: { meal_after: 60, goal: 60 } } };

for (const field of ['meal', 'date']) {
  test(`ideas discard an old answer when the ${field} changes, including its Add button`, async () => {
    const s = setup(), ui = s.ideas();
    const pending = s.button(ui.box, 'Ask AI for ideas').handlers.click();
    await settle();
    if (field === 'meal') ui.controller.setMeal('dinner'); else ui.controller.setDate('2026-10-30');
    s.calls[0].resolve({ status: 'ok', ideas: [idea] });
    await pending;
    assert.doesNotMatch(text(ui.out), /Breakfast answer|Add to plan/);
    assert.equal(ui.out.attrs['aria-busy'], undefined);
    assert.equal(s.writes.length, 0);
  });
}

test('an old idea error does not appear after changing the selected meal', async () => {
  const s = setup(), ui = s.ideas();
  const pending = s.button(ui.box, 'Ask AI for ideas').handlers.click();
  await settle();
  ui.controller.setMeal('dinner');
  s.calls[0].reject({ detail: 'Old breakfast failure' });
  await pending;
  assert.doesNotMatch(text(ui.error), /Old breakfast failure/);
});

test('unchanged idea answers remain usable and add to their requested meal/date', async () => {
  const s = setup(), ui = s.ideas();
  const pending = s.button(ui.box, 'Ask AI for ideas').handlers.click();
  await settle();
  s.calls[0].resolve({ status: 'ok', ideas: [idea] });
  await pending;
  assert.match(text(ui.out), /Breakfast carbohydrate/);
  await s.button(ui.out, 'Add to plan').handlers.click();
  assert.equal(s.writes[0].meal, 'breakfast');
  assert.equal(s.writes[0].date, '2026-10-29');
});

test('Other ideas and Ask cannot let an older reply overwrite a newer request', async () => {
  const s = setup(), ui = s.ideas();
  const ask = s.button(ui.box, 'Ask AI for ideas');
  const initial = ask.handlers.click();
  await settle();
  s.calls[0].resolve({ status: 'ok', ideas: [idea] });
  await initial;
  const older = s.button(ui.box, 'Other ideas').handlers.click();
  await settle();
  const newer = ask.handlers.click();
  await settle();
  s.calls[1].resolve({ status: 'ok', notes: ['Older choices'] });
  await older;
  assert.equal(ui.out.attrs['aria-busy'], 'true', 'a newer request is still pending');
  s.calls[2].resolve({ status: 'ok', notes: ['Newest choices'] });
  await newer;
  assert.match(text(ui.out), /Newest choices/);
  assert.doesNotMatch(text(ui.out), /Older choices/);
});

for (const field of ['dish', 'makes', 'meal']) {
  test(`recipes discard an old answer after changing ${field}, then accept a fresh one`, async () => {
    const s = setup(), ui = s.recipes();
    const ask = s.button(ui.box, 'Ask AI for recipes');
    const pending = ask.handlers.click();
    await settle();
    if (field === 'meal') {
      const picker = all(ui.box).find((n) => n.tag === 'fieldset');
      for (const n of all(picker).filter((n) => n.tag === 'input')) n.checked = n.value === 'dinner';
      picker.handlers.change();
    } else {
      const input = all(ui.box).find((n) => n.id?.startsWith(`ai-${field}`));
      input.value = field === 'dish' ? 'soup' : '6';
      input.handlers.change();
    }
    s.calls[0].resolve({ status: 'ok', notes: ['Old recipe answer'] });
    await pending;
    assert.doesNotMatch(text(ui.out), /Old recipe answer/);
    assert.equal(ui.out.attrs['aria-busy'], undefined);
    const fresh = ask.handlers.click();
    await settle();
    s.calls[1].resolve({ status: 'ok', notes: ['Current recipe answer'] });
    await fresh;
    assert.match(text(ui.out), /Current recipe answer/);
  });
}
