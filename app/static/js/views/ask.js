/* Kidney Diet Log — the Ask screen (#ask; docs/assistant.md, ARCHITECTURE.md "Ask chat").

   * A sixth tab, shown only while the server says the chat is available (GET /api/ai/status → features.chat:
     AI on and set up, the person opted in, and the admin switch "Ask" on). In the demo and the preview the tab
     is there too, with a note that the chat works in the installed app with an AI provider: the demo never
     contacts a provider and has no mock answers.
   * The conversation lives in this page only (the server stores no transcript): "New conversation", reloading
     or signing out forgets it. Each send posts the last 20 messages to POST /api/ai/chat.
   * Every answer is the server's checked answer: its text is set with textContent, never as HTML; a low or an
     emergency gets the rule-based card without any AI call (kind treat_low / get_help_now); a withheld or
     unfinished answer says so and still shows "From the app", the tools' own figures.
   * The first send asks for consent (purpose "chat") with the shared sheet of js/views/ai.js, including
     "What will be sent?".

   Rules: no inline scripts or styles (CSP); Enter sends and Shift+Enter makes a new line; nothing is saved or
   logged from here (the assistant has no saving tools in the app). */
(() => {
  'use strict';
  const KH = window.KH;
  const { $, h, clear, toastError, router, state } = KH;
  const { MOCK } = KH.flags;

  const MAX_SENT = 20; // the server's limit on the messages of one request
  const MAX_CHARS = 2000;
  const NOTE_LINE = 'Answers come from an AI model; every number is the app\'s own. Not medical advice.';
  const DEMO_TEXT = 'Ask works in the installed app, with an AI provider your admin sets up. This preview has no assistant, so there is nothing to ask here.';
  const LEARN_PATH = /\/learn\/[A-Za-z0-9_\-/#]*[A-Za-z0-9_\-/#]/g;

  const thread = []; // what the server gets back as `messages`: { role: 'user' | 'assistant', text }
  let busy = false;

  const els = {};
  function grab() {
    for (const [key, id] of Object.entries({ list: 'ask-thread', input: 'ask-input', send: 'ask-send', fresh: 'ask-new', intro: 'ask-intro',
      demo: 'ask-demo', composer: 'ask-composer', note: 'ask-note', live: 'ask-live' })) els[key] = $(`#${id}`);
  }

  // ---------------------------------------------------------------------------
  // The tab: shown only while the chat is available
  // ---------------------------------------------------------------------------
  async function refreshTab() {
    const tab = $('#tab-ask');
    if (!tab) return false;
    if (MOCK) { tab.hidden = false; return true; }
    let available = false;
    try {
      const st = await KH.ai.status();
      available = !!(st && st.features && st.features.chat);
    } catch (err) { /* the tab stays out of the way when the status cannot be read */ }
    tab.hidden = !available;
    if (!available && state.view === 'ask') router.show('today');
    return available;
  }

  // ---------------------------------------------------------------------------
  // Rendering (textContent only)
  // ---------------------------------------------------------------------------
  // Plain text with the app's own handbook paths (/learn/…) as links; everything else stays text.
  function textNodes(text) {
    const out = [];
    let last = 0;
    for (const match of text.matchAll(LEARN_PATH)) {
      const href = KH.learn ? KH.learn.href(match[0]) : null;
      if (match.index > last) out.push(document.createTextNode(text.slice(last, match.index)));
      if (href) out.push(h('a', { class: 'learn-more ask-link', href, target: '_blank', rel: 'noopener' }, match[0]));
      else out.push(document.createTextNode(match[0]));
      last = match.index + match[0].length;
    }
    if (last < text.length) out.push(document.createTextNode(text.slice(last)));
    return out;
  }

  function who(role) { return h('span', { class: 'sr-only' }, role === 'user' ? 'You: ' : 'Assistant: '); }

  function userBubble(text) {
    return h('div', { class: 'ask-msg user' }, h('p', { class: 'ask-text' }, who('user'), text));
  }

  function numbersBlock(groups) {
    if (!groups || !groups.length) return null;
    const box = h('section', { class: 'ask-numbers', 'aria-label': 'From the app' }, h('h3', {}, 'From the app'));
    for (const group of groups) {
      box.append(h('h4', {}, group.title));
      const dl = h('dl', { class: 'ask-kv' });
      for (const row of group.rows) {
        dl.append(h('div', { class: 'ask-kv-row' }, h('dt', {}, row.label),
          h('dd', {}, h('span', { class: 'ask-value' }, row.value), row.detail ? h('span', { class: 'ask-detail' }, row.detail) : null)));
      }
      box.append(dl);
    }
    return box;
  }

  function answerBubble(answer) {
    const box = h('div', { class: `ask-msg assistant kind-${answer.kind}` });
    const text = () => h('p', { class: 'ask-text' }, who('assistant'), ...textNodes(answer.text || ''));
    if (answer.kind === 'treat_low' || answer.kind === 'get_help_now') {
      // The rule-based cards come first, in full; the model was not asked.
      box.append(h('p', { class: 'ask-text ask-lead' }, who('assistant'), answer.text));
      for (const card of answer.cards || []) box.append(KH.ai.cardEl(card, card.handbook === 'get-help-now'));
    } else if (answer.kind === 'answer') {
      box.append(text());
    } else {
      // withheld, unfinished, error: a plain notice, never styled as an answer
      box.append(h('div', { class: 'settings-note caution ask-notice', role: 'note' }, text()));
    }
    for (const note of answer.notes || []) box.append(h('p', { class: 'hint ask-note-line' }, note));
    const numbers = numbersBlock(answer.numbers);
    if (numbers) box.append(numbers);
    if (answer.label && answer.label.notice && answer.kind === 'answer') box.append(h('p', { class: 'hint ask-label' }, answer.label.notice));
    return box;
  }

  function problemBubble(err) {
    const text = (err && (err.detail || err.message)) || 'Something went wrong. Try again.';
    return h('div', { class: 'ask-msg assistant kind-error' }, h('div', { class: 'settings-note caution ask-notice', role: 'note' }, h('p', { class: 'ask-text' }, who('assistant'), text)));
  }

  function scrollToEnd() {
    const last = els.list.lastElementChild;
    if (last && last.scrollIntoView) last.scrollIntoView({ block: 'nearest' });
  }

  function syncControls() {
    els.send.disabled = busy;
    els.fresh.hidden = thread.length === 0 || busy;
    els.intro.hidden = thread.length > 0;
  }

  // ---------------------------------------------------------------------------
  // Sending
  // ---------------------------------------------------------------------------
  function body() { return { messages: thread.slice(-MAX_SENT).map((m) => ({ role: m.role, text: m.text })) }; }

  async function send() {
    if (busy) return;
    const text = els.input.value.trim();
    if (!text) return;
    if (text.length > MAX_CHARS) { toastError({ message: `Messages can be up to ${MAX_CHARS} characters.` }); return; }
    busy = true;
    thread.push({ role: 'user', text });
    els.input.value = '';
    els.list.append(userBubble(text));
    const thinking = h('div', { class: 'ask-msg assistant thinking', 'aria-hidden': 'true' }, h('p', { class: 'ask-text' }, 'Thinking…'));
    els.list.append(thinking);
    els.live.textContent = 'Thinking…';
    syncControls();
    scrollToEnd();
    let answer = null;
    let failure = null;
    try {
      answer = await KH.ai.withConsent('chat', () => KH.ai.api.chat(body()), () => KH.ai.api.chat(body(), true), els.send);
    } catch (err) {
      failure = err;
    }
    thinking.remove();
    els.live.textContent = '';
    if (failure && failure.handled) { busy = false; syncControls(); return; } // signed out: the sign-in screen is showing
    if (!answer) {
      // Declined at the consent sheet, or the server refused (busy, out of calls, not available): the question was
      // not answered, so it leaves the conversation and goes back into the box to be sent again.
      thread.pop();
      els.list.lastElementChild.remove();
      els.input.value = text;
      els.list.append(failure ? problemBubble(failure) : problemBubble({ message: 'Nothing was sent. Ask works only after you agree to send your messages to the AI provider.' }));
    } else {
      els.list.append(answerBubble(answer));
      thread.push({ role: 'assistant', text: answer.text || '' });
      els.live.textContent = 'Answer received.';
    }
    busy = false;
    syncControls();
    scrollToEnd();
    els.input.focus();
  }

  function newConversation() {
    if (busy) return;
    thread.length = 0;
    clear(els.list);
    syncControls();
    els.input.focus();
  }

  // ---------------------------------------------------------------------------
  // Wiring
  // ---------------------------------------------------------------------------
  async function show() {
    if (MOCK) {
      els.demo.textContent = DEMO_TEXT;
      els.demo.hidden = false;
      els.composer.hidden = true;
      els.note.hidden = true;
      els.fresh.hidden = true;
      els.intro.hidden = true;
      return;
    }
    const available = await refreshTab();
    if (!available) return;
    syncControls();
    els.input.focus({ preventScroll: true });
  }

  function init() {
    grab();
    if (!els.list) return;
    els.note.textContent = NOTE_LINE;
    els.send.addEventListener('click', () => send());
    els.fresh.addEventListener('click', () => newConversation());
    els.input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); send(); }
    });
    router.register('ask', () => show());
    KH.views.ask = { refreshTab, show, newConversation, send };
  }
  init();
})();
