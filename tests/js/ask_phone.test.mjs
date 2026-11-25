// Runs the real js/views/ask.js on a fake page as the iPhone app (KH.flags.MOCK and DEVICE): the tab is always there, the demo's
// text never shows, the screen says why Ask cannot run in each case, the conversation appears when the server offers Ask, the save
// line says the assistant always asks first, and a save an older server made at once has no Undo.
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import test from 'node:test';
import { makePage, settle } from './fake_page.mjs';

const source = readFileSync(new URL('../../app/static/js/views/ask.js', import.meta.url), 'utf8');

function setup(status) {
  const page = makePage();
  const { $ } = page;
  const tab = page.h('button', { id: 'tab-ask', hidden: true });
  page.document.body.append(tab);
  const now = { st: status };
  const KH = {
    h: page.h, $, clear: page.clear, state: { view: 'ask' }, flags: { MOCK: true, DEVICE: true }, views: {},
    toastError() {}, router: { register() {}, show() {} },
    ai: {
      status: async () => now.st,
      withConsent: async (purpose, run) => run(),
      api: { chat: async () => now.reply },
      cardEl: () => page.h('div', {}), refreshDayCaches() {},
    },
  };
  const context = vm.createContext({ window: { KH, crypto: globalThis.crypto }, document: page.document, console, setTimeout, clearTimeout });
  vm.runInContext(source, context, { filename: 'ask.js' });
  return { page, $, KH, now, tab };
}
const off = (why) => ({ enabled: false, phone: { both_ways: why !== 'not_paired', ask: why, photos: why } });
const on = () => ({ enabled: true, available: true, features: { chat: true, voice: false }, trust: { setting: 'ask', allowed: false, effective: 'ask', phone: true },
  routes: { chat: { text: 'Runs on your local AI (ai.home.lan).' } }, phone: { ask: null } });

const WORDS = {
  not_paired: /Ask uses your Kidney Health server's AI\. Your own AI key and this iPhone's own AI help with describing a meal on the Add screen, but Ask needs the server, because it reads your log there\. If you have a Kidney Health server, connect this iPhone/,
  not_both_ways: /only sends your log/,
  offline: /could not be reached/,
  device_only: /only this iPhone's AI/,
  not_synced: /syncs both ways/,
  not_opted_in: /AI features are off for you on your server/,
  server_off: /Your server has Ask off/,
};

for (const [why, words] of Object.entries(WORDS)) {
  test(`the phone says why Ask cannot run: ${why}`, async () => {
    const s = setup(off(why));
    await s.KH.views.ask.show();
    assert.equal(s.tab.hidden, false, 'the tab is there on the phone');
    const demo = s.$('#ask-demo');
    assert.equal(demo.hidden, false);
    assert.match(demo.textContent, words);
    assert.doesNotMatch(demo.textContent, /installed app|preview/, 'never the web demo\'s text');
    assert.equal(s.$('#ask-composer').hidden, true, 'nothing to type into');
  });
}

test('the server has Ask on: the conversation, the server\'s words for where it runs, and "always asks"', async () => {
  const s = setup(off('server_off'));
  await s.KH.views.ask.show();
  s.now.st = on();
  await s.KH.views.ask.show();
  assert.equal(s.$('#ask-demo').hidden, true);
  assert.equal(s.$('#ask-composer').hidden, false);
  assert.match(s.$('#ask-where').textContent, /local AI/);
  assert.match(s.$('#ask-trust-line').textContent, /always asks before it saves/);
  assert.equal(s.$('#ask-trust-actions').children.length, 0, 'no way to trust it on the phone');
});

test('a save an older server made at once has no Undo on the phone', async () => {
  const s = setup(on());
  await s.KH.views.ask.show();
  s.now.reply = { kind: 'answer', text: 'Logged.', cards: [], numbers: [], notes: [], trust: 'always', pending_save: null, questions: [],
    saved: [{ tool: 'log_food', date: '2026-11-25', meal: 'lunch', status: 'eaten', items: [{ name: 'Apple', servings: 1, grams: null }], undo: null, on_server: true, numbers: [] }] };
  s.$('#ask-input').value = 'log an apple';
  await s.KH.views.ask.send();
  await settle();
  const text = s.page.text(s.$('#ask-thread'));
  assert.match(text, /Saved on your server\. It comes to this iPhone with the next sync/);
  assert.doesNotMatch(text, /Undo/);
});
