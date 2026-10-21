#!/usr/bin/env node
// Runs app/static/js/views/ask.js against a tiny fake page and a fake server, and prints what happened as JSON, so pytest
// (tests/test_ask_taste_ui.py) can check the taste card without a browser: what the card says, that nothing is written before
// Remember, the exact requests Remember and Undo make for a food and for a food group, and what the person reads after.
// The helpers the file takes from KH (h, clear, $, router, toastError) are stand-ins with the contract of js/core.js; the
// fake API keeps the person's food preferences and "guidance" setting in memory and records every call it gets.
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..', '..');
const source = readFileSync(join(ROOT, 'app', 'static', 'js', 'views', 'ask.js'), 'utf8');

class Text { constructor(t) { this.nodeType = 3; this.t = t; this.parent = null; } }
class El {
  constructor(tag) { this.nodeType = 1; this.tag = tag; this.attrs = {}; this.children = []; this.handlers = {}; this.textContent = ''; this.disabled = false; this.hidden = false; this.value = ''; this.parent = null; this.focused = false; }
  setAttribute(k, v) { this.attrs[k] = v; }
  append(...kids) { for (const k of kids) { const node = typeof k === 'object' && k && k.nodeType ? k : new Text(String(k)); node.parent = this; this.children.push(node); } }
  addEventListener(type, fn) { (this.handlers[type] ||= []).push(fn); }
  replaceWith(node) { const i = this.parent.children.indexOf(this); node.parent = this.parent; this.parent.children[i] = node; this.parent = null; }
  remove() { if (this.parent) this.parent.children = this.parent.children.filter((c) => c !== this); this.parent = null; }
  focus() { this.focused = true; }
  scrollIntoView() {}
  get lastElementChild() { const kids = this.children.filter((c) => c.nodeType === 1); return kids[kids.length - 1] || null; }
  async click() { for (const fn of this.handlers.click || []) await fn({}); await new Promise((r) => setTimeout(r, 0)); }
}
const h = (tag, attrs, ...kids) => {
  const el = new El(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    el.setAttribute(k, v === true ? '' : String(v));
  }
  const add = (k) => { if (k == null || k === false) return; if (Array.isArray(k)) { k.forEach(add); return; } el.append(k.nodeType ? k : new Text(String(k))); };
  kids.forEach(add);
  return el;
};
const clear = (el) => { el.children = []; return el; };
const text = (el) => (el.nodeType === 3 ? el.t : [el.textContent, ...el.children.map(text)].filter(Boolean).join(' ')).replace(/\s+/g, ' ').trim();
const find = (el, pred, out = []) => { if (el.nodeType === 1) { if (pred(el)) out.push(el); el.children.forEach((c) => find(c, pred, out)); } return out; };
const buttonNamed = (root, label) => find(root, (e) => e.tag === 'button' && text(e) === label)[0];
const sections = (root) => find(root, (e) => e.tag === 'section');

// ---- the fake server -------------------------------------------------------
const server = { foods: {}, guidance: {}, calls: [], fail: null, answers: [], chats: [] };
function resetServer({ foods = {}, guidance = {} } = {}) {
  server.foods = foods;
  server.guidance = { like_categories: [], less_categories: [], exclude_categories: [], carb_tolerance_g: 10, enabled: true, ...guidance };
  server.calls = [];
  server.fail = null;
  server.forgot = 0;
  server.loaded = 0;
}
const note = (name, ...args) => { server.calls.push([name, ...args]); };
const failing = (name) => {
  if (server.fail && server.fail.on === name) { const err = Object.assign(new Error(server.fail.message), { status: server.fail.status, detail: server.fail.message }); throw err; }
};
const api = {
  foodPreferences: async () => { note('GET preferences'); failing('GET preferences'); return { foods: Object.entries(server.foods).map(([id, p]) => ({ food_id: Number(id), preference: p.preference, source: p.source })) }; },
  setFoodPreference: async (id, body) => { note('PUT preference', id, body); failing('PUT preference'); server.foods[id] = { preference: body.preference, source: body.source }; return {}; },
  clearFoodPreference: async (id) => {
    note('DELETE preference', id); failing('DELETE preference');
    if (!(id in server.foods)) throw Object.assign(new Error('food has no preference of yours'), { status: 404 });
    delete server.foods[id]; return null;
  },
  mySettings: async () => { note('GET settings'); failing('GET settings'); return { settings: { guidance: { value: JSON.parse(JSON.stringify(server.guidance)), source: 'user', editable: true } } }; },
  updateMySettings: async (body) => { note('PATCH settings', JSON.parse(JSON.stringify(body))); failing('PATCH settings'); server.guidance = JSON.parse(JSON.stringify(body.guidance)); return {}; },
};
const KH = {
  h, clear, toastError: () => {}, state: { view: 'ask' }, flags: { MOCK: false },
  $: (sel) => elements[sel.slice(1)] || null,
  router: { register: () => {}, show: () => {} },
  views: {},
  api,
  guidance: { forgetAnswers: () => { server.forgot += 1; }, loadPrefs: async () => { server.loaded += 1; } },
  ai: {
    status: async () => ({ features: { chat: true }, trust: { setting: 'ask', allowed: false, effective: 'ask' } }),
    withConsent: async (purpose, run) => run(),
    api: { chat: async (body) => { server.chats.push(body); return server.answers.shift(); } },
    cardEl: () => h('div', {}), refreshDayCaches: () => {},
  },
};
const elements = {};
for (const id of ['ask-thread', 'ask-input', 'ask-send', 'ask-new', 'ask-intro', 'ask-demo', 'ask-composer', 'ask-note', 'ask-live']) elements[id] = new El(id.includes('input') ? 'textarea' : 'div');
const context = vm.createContext({
  window: { KH, crypto: globalThis.crypto }, document: { createTextNode: (t) => new Text(String(t)), contains: () => true },
  console, setTimeout, clearTimeout, Promise, Date, Math, Number, String, Object, Array, Uint8Array,
});
vm.runInContext(source, context, { filename: 'ask.js' });
const Ask = KH.views.ask;

// ---- helpers ---------------------------------------------------------------
const FOOD = 101;
const foodCard = (preference, previous = 'none', previousSource = null, extra = {}) => ({
  tool: 'set_food_preference', target: { kind: 'food', food_id: FOOD, name: 'Salmon, Atlantic, farmed, cooked', category: 'Fish & Seafood' },
  preference, previous, previous_source: previousSource, payload: preference === 'clear' ? null : { preference, source: 'ask' }, ...extra,
});
const groupCard = (preference, previous = 'none') => ({
  tool: 'set_food_preference', target: { kind: 'group', name: 'Fish & Seafood' }, preference, previous, previous_source: null, payload: null,
});
const answerWith = (card, text = 'Nothing has been remembered yet. Check this, then press Remember, or Cancel.') => ({
  feature: 'chat', kind: 'confirm_save', text, cards: [], numbers: [], notes: [], label: null, provider: null, ai_called: true,
  model_calls: 1, tool_calls: 1, prompt_version: 'x', audit_id: 1, trust: 'ask', pending_save: card, saved: [], questions: [],
});
async function say(message, card) {
  server.answers.push(answerWith(card));
  elements['ask-input'].value = message;
  await Ask.send();
  await new Promise((r) => setTimeout(r, 0));
  const bubbles = elements['ask-thread'].children;
  return bubbles[bubbles.length - 1];
}
const card = (bubble) => sections(bubble).find((s) => /ask-taste/.test(s.attrs.class || ''));
const lines = (root) => find(root, (e) => e.tag === 'p' || e.tag === 'h3').map(text);
const buttons = (root) => find(root, (e) => e.tag === 'button').map((b) => ({ label: text(b), disabled: b.disabled }));
const take = () => { const calls = server.calls; server.calls = []; return calls; };

const out = {};

// 1. a food, nothing before it: the card, Remember, Undo (there was nothing before)
resetServer();
let bubble = await say('I do not really like salmon', foodCard('less'));
out.food_pending = { lines: lines(card(bubble)), buttons: buttons(card(bubble)), calls: take(), prefs: { ...server.foods } };
await buttonNamed(card(bubble), 'Remember').click();
out.food_remembered = { calls: take(), prefs: JSON.parse(JSON.stringify(server.foods)), lines: lines(card(bubble) || bubble), buttons: buttons(bubble), forgot: server.forgot, loaded: server.loaded };
await buttonNamed(bubble, 'Undo').click();
out.food_undone = { calls: take(), prefs: JSON.parse(JSON.stringify(server.foods)), lines: lines(bubble), forgot: server.forgot };
// what the model reads on the next turn about this card
server.answers.push({ ...answerWith(null), kind: 'answer', text: 'Okay.', pending_save: null });
elements['ask-input'].value = 'thanks';
await Ask.send();
out.thread_after_undo = server.chats[server.chats.length - 1].messages.map((m) => `${m.role}: ${m.text}`);

// 2. a food that was liked by the person: Undo puts "like" back, from "person"
resetServer({ foods: { [FOOD]: { preference: 'like', source: 'person' } } });
bubble = await say('actually less salmon please', foodCard('less', 'like', 'person'));
take();
await buttonNamed(card(bubble), 'Remember').click();
out.liked_remembered = { calls: take(), prefs: JSON.parse(JSON.stringify(server.foods)) };
await buttonNamed(bubble, 'Undo').click();
out.liked_undone = { calls: take(), prefs: JSON.parse(JSON.stringify(server.foods)) };

// 3. clear: a DELETE; Undo puts the old row back with its own source
resetServer({ foods: { [FOOD]: { preference: 'not_for_me', source: 'ask' } } });
bubble = await say('forget what I said about salmon', foodCard('clear', 'not_for_me', 'ask'));
take();
await buttonNamed(card(bubble), 'Remember').click();
out.clear_remembered = { calls: take(), prefs: JSON.parse(JSON.stringify(server.foods)) };
await buttonNamed(bubble, 'Undo').click();
out.clear_undone = { calls: take(), prefs: JSON.parse(JSON.stringify(server.foods)) };

// 4. the card is stale: the person changed the food somewhere else after it was shown. Undo goes back to what was there when
// Remember was pressed, not to what the card said.
resetServer({ foods: { [FOOD]: { preference: 'not_for_me', source: 'person' } } });
bubble = await say('less salmon', foodCard('less', 'none'));
take();
await buttonNamed(card(bubble), 'Remember').click();
await buttonNamed(bubble, 'Undo').click();
out.stale_card = { prefs: JSON.parse(JSON.stringify(server.foods)), calls: take() };

// 5. a neutral row is not a taste: clear leaves it alone
resetServer({ foods: { [FOOD]: { preference: 'neutral', source: 'person' } } });
bubble = await say('forget it', foodCard('clear', 'none'));
take();
await buttonNamed(card(bubble), 'Remember').click();
out.neutral_clear = { calls: take(), prefs: JSON.parse(JSON.stringify(server.foods)) };

// 6. Cancel writes nothing
resetServer();
bubble = await say('I do not like salmon', foodCard('not_for_me'));
take();
await buttonNamed(card(bubble), 'Cancel').click();
out.cancelled = { calls: take(), prefs: { ...server.foods }, lines: lines(bubble), cards: sections(bubble).length };

// 7. the server says no (the list is full): the card stays, the buttons come back, the message is the server's
resetServer();
server.fail = { on: 'PUT preference', status: 409, message: 'your food preferences are full (1000 foods); remove one first' };
bubble = await say('I like salmon', foodCard('like'));
take();
await buttonNamed(card(bubble), 'Remember').click();
out.refused = { lines: lines(card(bubble)), buttons: buttons(card(bubble)), prefs: { ...server.foods }, forgot: server.forgot };

// 8. a food group: the whole guidance setting is read now, one group moves, everything else stays; Undo re-reads it
resetServer({ guidance: { like_categories: ['Fruits'], exclude_categories: ['Beverages'], carb_tolerance_g: 12 } });
bubble = await say('I try to eat less fish', groupCard('less'));
out.group_pending = { lines: lines(card(bubble)), calls: take() };
server.guidance.less_categories = ['Sweets & Snacks']; // changed in Settings after the card was shown
await buttonNamed(card(bubble), 'Remember').click();
out.group_remembered = { calls: take(), guidance: JSON.parse(JSON.stringify(server.guidance)), lines: lines(bubble) };
server.guidance.like_categories = ['Fruits', 'Vegetables']; // and again between Remember and Undo
await buttonNamed(bubble, 'Undo').click();
out.group_undone = { calls: take(), guidance: JSON.parse(JSON.stringify(server.guidance)), lines: lines(bubble) };

// 9. a group from "never suggest" to liked; the words for "not for me" on a group are "never suggest"
resetServer({ guidance: { exclude_categories: ['Fish & Seafood'] } });
bubble = await say('fish is fine again', groupCard('like', 'not_for_me'));
out.group_words = lines(card(bubble));
take();
await buttonNamed(card(bubble), 'Remember').click();
out.group_liked = { guidance: JSON.parse(JSON.stringify(server.guidance)) };
await buttonNamed(bubble, 'Undo').click();
out.group_back_to_never = { guidance: JSON.parse(JSON.stringify(server.guidance)) };
resetServer();
bubble = await say('no fish', groupCard('not_for_me'));
out.group_never_words = lines(card(bubble));
// and clearing a group removes it from all three lists
resetServer({ guidance: { less_categories: ['Fish & Seafood'] } });
bubble = await say('forget fish', groupCard('clear', 'less'));
take();
await buttonNamed(card(bubble), 'Remember').click();
out.group_cleared = { guidance: JSON.parse(JSON.stringify(server.guidance)) };

// 10. a setting that cannot be read: nothing is changed
resetServer();
server.fail = { on: 'GET settings', status: 500, message: 'Something went wrong' };
bubble = await say('less fish', groupCard('less'));
take();
await buttonNamed(card(bubble), 'Remember').click();
out.unreadable = { calls: take(), lines: lines(card(bubble)) };

console.log(JSON.stringify(out));
