// Runs the real js/views/ask.js on a fake page: a question that gets no answer goes back into the box, without wiping what the
// person typed while they waited.
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import test from 'node:test';
import { makePage, deferred, settle } from './fake_page.mjs';

const source = readFileSync(new URL('../../app/static/js/views/ask.js', import.meta.url), 'utf8');

function setup() {
  const page = makePage();
  const { $ } = page;
  const chats = [];
  const toasts = [];
  const KH = {
    h: page.h, $, clear: page.clear, state: { view: 'ask' }, flags: { MOCK: false }, views: {},
    toastError: (e) => toasts.push(e.message), router: { register() {}, show() {} },
    ai: {
      status: async () => ({ features: { chat: true }, trust: { setting: 'ask', allowed: false, effective: 'ask' } }),
      withConsent: async (purpose, run) => run(),
      api: { chat: (body) => { const d = deferred(); chats.push({ body, ...d }); return d.promise; } },
      cardEl: () => page.h('div', {}), refreshDayCaches() {},
    },
  };
  const context = vm.createContext({ window: { KH, crypto: globalThis.crypto }, document: page.document, console, setTimeout, clearTimeout });
  vm.runInContext(source, context, { filename: 'ask.js' });
  const input = $('#ask-input');
  const send = (text) => { input.value = text; return KH.views.ask.send(); };
  const answer = (text) => ({ kind: 'answer', text, cards: [], numbers: [], notes: [], trust: 'ask', saved: [], questions: [] });
  return { page, $, KH, chats, toasts, input, send, answer, thread: () => page.text($('#ask-thread')) };
}
const busyError = () => Object.assign(new Error('The assistant is busy. Try again in a minute.'), { status: 503, detail: 'The assistant is busy. Try again in a minute.' });

test('a failed send keeps the next question the person typed while waiting', async () => {
  const s = setup();
  const pending = s.send('How much potassium is in a banana?');
  assert.equal(s.input.value, '');
  s.input.value = 'And in an apple?'; // typed while "Thinking…"
  s.chats[0].reject(busyError());
  await pending;
  assert.match(s.input.value, /And in an apple\?/, 'what was typed meanwhile is still there');
  assert.match(s.input.value, /How much potassium is in a banana\?/, 'the unanswered question is back too');
  assert.match(s.thread(), /busy/);
});

test('a failed send with nothing typed meanwhile puts the question back exactly', async () => {
  const s = setup();
  const pending = s.send('How much potassium is in a banana?');
  s.chats[0].reject(busyError());
  await pending;
  assert.equal(s.input.value, 'How much potassium is in a banana?');
});

test('an answered send leaves what was typed meanwhile alone', async () => {
  const s = setup();
  const pending = s.send('How much potassium is in a banana?');
  s.input.value = 'And in an apple?';
  s.chats[0].resolve(s.answer('About 420 mg.'));
  await pending;
  await settle();
  assert.equal(s.input.value, 'And in an apple?');
  assert.match(s.thread(), /About 420 mg/);
});
