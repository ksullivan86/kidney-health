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

   * Saving (assistant step 2, part C; the section "Saving from the chat" below). The assistant may ask to log, plan or
     save something. By default (the person's choice "Ask me before every save") the answer is a card: what the app
     found, the app's totals, and Save as eaten / Save as planned / Cancel. Nothing is saved until Save is pressed, and
     then this page posts the card's body to the app's normal save route (POST /api/log/batch or /api/meals) like any
     other save: the model is not involved in the write. If the person trusted the assistant (Settings → AI ideas) and
     the admin allows it, the server saves at once and the answer shows what was saved with Undo, which deletes
     exactly those rows through the normal DELETE routes. Trust "for this conversation" lives in this page only: it
     ends with New conversation, a reload, or after 12 hours.

   * Tastes (note 09 §4.8; the section "tastes" below). The assistant may propose to remember that the person likes a food or
     food group, wants it less often, does not want it, or wants it forgotten. That is a card ("Remember this for your
     suggestions? Salmon: less often." with Remember and Cancel) whatever the person trusts: the server never writes it, and
     this page applies it only on Remember, through the normal preference route (a food) or the whole "guidance" setting (a
     food group). Undo puts back exactly what was there.

   Rules: no inline scripts or styles (CSP); Enter sends and Shift+Enter makes a new line; every save is the person's
   own press on a card or the person's own choice to trust the assistant, and always undoable. */
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
    if (KH.askVoice) KH.askVoice.sync(available); // js/views/ask-voice.js: the microphone and read aloud follow the same answer
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

  function numbersBlock(groups, title = 'From the app') {
    if (!groups || !groups.length) return null;
    const box = h('section', { class: 'ask-numbers', 'aria-label': title }, h('h3', {}, title));
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

  function answerBubble(answer, entry) {
    const box = h('div', { class: `ask-msg assistant kind-${answer.kind}` });
    const text = () => h('p', { class: 'ask-text' }, who('assistant'), ...textNodes(answer.text || ''));
    if (answer.kind === 'treat_low' || answer.kind === 'get_help_now') {
      // The rule-based cards come first, in full; the model was not asked.
      box.append(h('p', { class: 'ask-text ask-lead' }, who('assistant'), answer.text));
      for (const card of answer.cards || []) box.append(KH.ai.cardEl(card, card.handbook === 'get-help-now'));
    } else if (answer.kind === 'answer' || answer.kind === 'confirm_save') {
      box.append(text());
    } else {
      // withheld, unfinished, error: a plain notice, never styled as an answer
      box.append(h('div', { class: 'settings-note caution ask-notice', role: 'note' }, text()));
    }
    for (const node of savingNodes(answer, entry)) box.append(node);
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
  function body() { return { messages: thread.slice(-MAX_SENT).map((m) => ({ role: m.role, text: m.text })), ...saveFields() }; }

  async function send() {
    if (busy) return;
    const text = els.input.value.trim();
    if (!text) return;
    if (text.length > MAX_CHARS) { toastError({ message: `Messages can be up to ${MAX_CHARS} characters.` }); return; }
    busy = true;
    beginRequest(text);
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
    endRequest(!!answer && !failure, text);
    if (failure && failure.handled) { busy = false; syncControls(); return; } // signed out: the sign-in screen is showing
    if (!answer) {
      // Declined at the consent sheet, or the server refused (busy, out of calls, not available): the question was
      // not answered, so it leaves the conversation and goes back into the box to be sent again.
      // Anything typed while waiting stays, after the question.
      thread.pop();
      els.list.lastElementChild.remove();
      const typed = els.input.value.trim();
      els.input.value = typed ? `${text}\n\n${typed}` : text;
      els.list.append(failure ? problemBubble(failure) : problemBubble({ message: 'Nothing was sent. Ask works only after you agree to send your messages to the AI provider.' }));
    } else {
      const entry = { role: 'assistant', text: answer.text || '' }; // a card may update this once it is used
      els.list.append(answerBubble(answer, entry));
      if (KH.askVoice) KH.askVoice.speak(answer); // reads the checked text aloud when the person asked for that
      thread.push(entry);
      noteServerTrust(answer);
      els.live.textContent = 'Answer received.';
    }
    busy = false;
    syncControls();
    scrollToEnd();
    els.input.focus();
  }

  function newConversation() {
    if (busy) return;
    resetSaving();
    thread.length = 0;
    clear(els.list);
    syncControls();
    els.input.focus();
  }

  // ---------------------------------------------------------------------------
  // Saving from the chat (assistant step 2, part C). Self-contained: the chat code above calls only
  // saveFields, beginRequest/endRequest, noteServerTrust, savingNodes, resetSaving and refreshTrust.
  // ---------------------------------------------------------------------------
  const CONVERSATION_MS = 12 * 3600 * 1000; // trusting "this conversation" ends after 12 hours
  const MEAL_NAME = { breakfast: 'Breakfast', lunch: 'Lunch', dinner: 'Dinner', snack: 'Snack' };

  let trustInfo = { setting: 'ask', allowed: false, effective: 'ask' }; // GET /api/ai/status → trust
  let grantedAt = null; // when the person trusted this conversation (page memory only)
  let grantTimer = null;
  let requestId = null; // the id of the send in progress: a save made in it carries a key made from it
  let failedSend = null; // { text, id }: a send that got no answer; sending the same text again reuses its id

  function newId() {
    const bytes = new Uint8Array(12);
    if (window.crypto && typeof window.crypto.getRandomValues === 'function') window.crypto.getRandomValues(bytes);
    else for (let i = 0; i < bytes.length; i++) bytes[i] = Math.floor(Math.random() * 256);
    return `ask-${Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('')}`; // 28 characters of [a-z0-9-]
  }
  // A send that failed (no answer) may have saved before the answer was lost: sending the same text again keeps its id,
  // so the server saves once.
  function beginRequest(text) { requestId = failedSend && failedSend.text === text ? failedSend.id : newId(); }
  function endRequest(answered, text) { failedSend = answered ? null : { text, id: requestId }; }

  function conversationTrusted() {
    if (grantedAt === null) return false;
    if (Date.now() - grantedAt >= CONVERSATION_MS) { grantedAt = null; return false; }
    return true;
  }
  // Sent with every chat request. The server honours "conversation" only for a person who chose it in Settings and only
  // while the admin allows trusted saves; "always" is the stored choice alone and is never sent.
  function saveFields() {
    const fields = { request_id: requestId };
    if (conversationTrusted() && trustInfo.allowed && trustInfo.setting === 'conversation') fields.trust = 'conversation';
    return fields;
  }
  // The server says which trust it used: if it used less than the page believes, the page stops believing.
  function noteServerTrust(answer) {
    if (grantedAt !== null && answer.trust === 'ask') { grantedAt = null; renderTrust(); }
  }
  function resetSaving() {
    grantedAt = null;
    failedSend = null;
    if (grantTimer) { clearTimeout(grantTimer); grantTimer = null; }
    renderTrust();
  }

  async function refreshTrust() {
    try {
      const st = await KH.ai.status(true);
      if (st && st.trust) trustInfo = st.trust;
    } catch (err) { /* the line keeps what it knew */ }
    if (!trustInfo.allowed || trustInfo.setting !== 'conversation') grantedAt = null; // nothing left to trust
    renderTrust();
  }

  function openTrustSettings() {
    router.show('settings');
    let tries = 0;
    const focus = () => {
      const target = $('#set-ai-trust');
      if (target) { target.setAttribute('tabindex', '-1'); target.scrollIntoView({ block: 'start' }); target.focus({ preventScroll: true }); return; }
      if (++tries < 15) setTimeout(focus, 150);
    };
    setTimeout(focus, 60);
  }

  function renderTrust() {
    const box = $('#ask-trust');
    const line = $('#ask-trust-line');
    const actions = $('#ask-trust-actions');
    if (!box || !line || !actions) return;
    clear(actions);
    if (MOCK) { box.hidden = true; return; }
    const t = trustInfo;
    const chosen = t.setting === 'conversation' || t.setting === 'always';
    const trusted = t.allowed && t.setting === 'conversation' && conversationTrusted();
    if (t.allowed && t.setting === 'always') {
      line.textContent = 'Trusted always: Ask saves food and recipes without asking you. It can pick the wrong food or amount; every save has Undo.';
    } else if (trusted) {
      line.textContent = 'Trusted for this conversation: Ask saves food and recipes without asking you. It can pick the wrong food or amount; every save has Undo.';
    } else if (t.allowed && t.setting === 'conversation') {
      line.textContent = 'Ask asks you before it saves. You can trust it for this conversation.';
    } else if (chosen) {
      line.textContent = 'Your admin turned trusted saves off, so Ask asks you before it saves.';
    } else {
      line.textContent = 'Ask asks you before it saves. Nothing is saved until you press Save.';
    }
    if (t.allowed && t.setting === 'conversation') {
      if (trusted) {
        const stop = h('button', { class: 'btn secondary', type: 'button' }, 'Stop trusting');
        stop.addEventListener('click', () => resetSaving());
        actions.append(stop);
      } else {
        const grant = h('button', { class: 'btn secondary', type: 'button' }, 'Trust it for this conversation');
        grant.addEventListener('click', () => {
          grantedAt = Date.now();
          if (grantTimer) clearTimeout(grantTimer);
          grantTimer = setTimeout(() => { grantTimer = null; renderTrust(); }, CONVERSATION_MS + 1000);
          renderTrust();
        });
        actions.append(grant);
      }
    }
    const change = h('button', { class: 'link-btn', type: 'button' }, 'Change this in Settings');
    change.addEventListener('click', () => openTrustSettings());
    actions.append(change);
    box.hidden = false;
  }

  // ---- the cards -----------------------------------------------------------
  // A save (or an Undo) changes the log: Today, Plan and Trends reload their day when they are shown next.
  function dayChanged() { KH.ai.refreshDayCaches(); }

  function savingNodes(answer, entry) {
    const nodes = [];
    if (answer.pending_save) nodes.push(answer.pending_save.tool === TASTE_TOOL ? tastePendingCard(answer.pending_save, entry) : pendingCard(answer.pending_save, entry));
    if ((answer.saved || []).length) dayChanged(); // a trusted save already happened on the server
    for (const card of answer.saved || []) nodes.push(savedCard(card, entry));
    if ((answer.questions || []).length) nodes.push(questionsBlock(answer.questions));
    return nodes;
  }

  const num = (v) => (Number.isInteger(v) ? String(v) : String(Math.round(v * 100) / 100));
  function amountLine(item) {
    const parts = [];
    if (item.as_asked) parts.push(item.as_asked);
    if (item.servings != null && !(item.as_asked && /servings?$/.test(item.as_asked))) parts.push(`${num(item.servings)} ${item.servings === 1 ? 'serving' : 'servings'}`);
    if (item.grams != null && !(item.as_asked && /\bg$/.test(item.as_asked))) parts.push(`${num(item.grams)} g`);
    return parts.join(' · ');
  }
  function itemList(items) {
    const list = h('ul', { class: 'ask-save-items' });
    for (const item of items || []) {
      list.append(h('li', {},
        h('span', { class: 'ask-save-name' }, item.brand ? `${item.name} (${item.brand})` : item.name),
        h('span', { class: 'ask-save-amount' }, amountLine(item)),
        item.new_food ? h('span', { class: 'hint' }, 'A USDA food: added to your foods when you save.') : null,
        item.counted_as_treating_a_low ? h('span', { class: 'hint' }, 'Counts as treating a low.') : null));
    }
    return list;
  }
  function button(label, cls, fn) {
    const btn = h('button', { class: `btn ${cls}`, type: 'button' }, label);
    btn.addEventListener('click', () => fn(btn));
    return btn;
  }
  // The pressed button goes away with its card: the focus moves to what replaced it, so a keyboard or screen reader user
  // is not left at the top of the page.
  function swap(oldNode, newNode) {
    oldNode.replaceWith(newNode);
    newNode.setAttribute('tabindex', '-1');
    newNode.focus({ preventScroll: true });
  }
  function errorText(err) { return (err && (err.detail || err.message)) || 'Something went wrong. Nothing was changed.'; }

  // What the assistant asked to save, nothing written yet.
  function pendingCard(card, entry) {
    const isLog = card.tool === 'log_food';
    const box = h('section', { class: 'ask-save ask-pending', 'aria-label': isLog ? 'Add to your log?' : 'Save this recipe?' });
    box.append(h('h3', {}, isLog ? 'Add to your log?' : `Save the recipe “${card.name}”?`));
    box.append(itemList(card.items));
    box.append(h('p', { class: 'hint ask-save-meta' }, isLog
      ? `${MEAL_NAME[card.meal] || card.meal} · ${card.date}`
      : `Makes ${num(card.servings_made)} ${card.servings_made === 1 ? 'serving' : 'servings'}`));
    const totals = numbersBlock(card.numbers, 'From the app');
    if (totals) box.append(totals);
    const message = h('p', { class: 'form-error ask-save-error', role: 'alert' });
    const row = h('div', { class: 'ask-save-actions' });
    const all = [];
    const run = async (btn, status) => {
      for (const b of all) b.disabled = true;
      clear(message);
      try {
        const done = await postCard(card, status);
        dayChanged();
        const saved = savedFromPost(card, status, done);
        entry.text = `Saved: ${saved.items.map((i) => i.name).join('; ')}.`;
        swap(box, savedCard(saved, entry));
      } catch (err) {
        if (err && err.handled) return;
        message.textContent = errorText(err);
        for (const b of all) b.disabled = false;
      }
    };
    if (isLog) {
      const asked = card.status === 'planned' ? 'planned' : 'eaten';
      all.push(button('Save as eaten', asked === 'eaten' ? 'primary' : 'secondary', (b) => run(b, 'eaten')),
        button('Save as planned', asked === 'planned' ? 'primary' : 'secondary', (b) => run(b, 'planned')));
    } else {
      all.push(button('Save recipe', 'primary', (b) => run(b, null)));
    }
    all.push(button('Cancel', 'secondary', () => {
      entry.text = 'Not saved: the person cancelled.';
      swap(box, h('p', { class: 'hint ask-save-note', role: 'status' }, 'Not saved.'));
    }));
    row.append(...all);
    box.append(message, row);
    return box;
  }

  // The normal save routes, exactly as any other screen uses them. A USDA food that is not in the person's list yet is
  // added first with the app's import route; the card's own body is posted otherwise unchanged.
  async function postCard(card, status) {
    const api = KH.ai.api;
    const foodIds = new Map();
    for (const fdcId of card.imports || []) foodIds.set(fdcId, (await api.importUsda(fdcId)).id);
    const withFood = ({ fdc_id: fdcId, ...rest }) => ({ ...rest, food_id: fdcId != null && foodIds.has(fdcId) ? foodIds.get(fdcId) : rest.food_id });
    if (card.tool === 'log_food') {
      const res = await api.logBatch(card.payload.entries.map((e) => ({ ...withFood(e), status })));
      return { entries: (res && res.entries) || [] };
    }
    return { meal: await api.createMeal({ ...card.payload, items: card.payload.items.map(withFood) }) };
  }
  // The "Saved" card for a save the person pressed, in the shape the server uses for trusted saves.
  function savedFromPost(card, status, done) {
    if (card.tool === 'log_food') {
      return { tool: 'log_food', date: card.date, meal: card.meal, status, duplicate: false, added_to_foods: [],
        items: done.entries.map((e) => ({ name: e.food_name, servings: e.servings, grams: e.grams, counted_as_treating_a_low: e.purpose === 'hypo' })),
        undo: { entry_ids: done.entries.map((e) => e.id) }, numbers: (card.numbers || []).map((g) => ({ ...g, title: 'Saved' })) };
    }
    return { tool: 'save_recipe', name: done.meal.name, servings_made: card.servings_made, duplicate: false, added_to_foods: [],
      items: card.items.map((i) => ({ name: i.name, servings: i.servings, grams: null })), undo: { meal_id: done.meal.id }, numbers: card.numbers };
  }

  // What was saved, with Undo (deletes exactly these rows through the normal DELETE routes; anyone else's id is a 404).
  function savedCard(card, entry) {
    const isLog = card.tool === 'log_food';
    const box = h('section', { class: 'ask-save ask-saved', 'aria-label': 'Saved' });
    box.append(h('h3', {}, isLog ? `Saved to your log: ${MEAL_NAME[card.meal] || card.meal}, ${card.status}` : `Saved the recipe “${card.name}”`));
    if (card.duplicate) box.append(h('p', { class: 'hint' }, 'This request had already been saved, so nothing was saved again.'));
    box.append(itemList(card.items));
    box.append(h('p', { class: 'hint ask-save-meta' }, isLog ? card.date : `Makes ${num(card.servings_made)} ${card.servings_made === 1 ? 'serving' : 'servings'}`));
    if ((card.added_to_foods || []).length) box.append(h('p', { class: 'hint' }, `Added to your foods: ${card.added_to_foods.join('; ')}. Undo keeps these foods.`));
    const totals = numbersBlock(card.numbers, 'From the app');
    if (totals) box.append(totals);
    const status = h('p', { class: 'hint ask-save-status', role: 'status' });
    const undo = button('Undo', 'secondary', async (btn) => {
      btn.disabled = true;
      clear(status);
      try {
        await undoSave(card);
        dayChanged();
        entry.text = 'The save was undone.';
        swap(box, h('p', { class: 'hint ask-save-note', role: 'status' }, 'Undone. Nothing from this save is left.'));
      } catch (err) {
        if (err && err.handled) return;
        status.textContent = errorText(err);
        btn.disabled = false;
      }
    });
    box.append(h('div', { class: 'ask-save-actions' }, undo), status);
    return box;
  }
  async function undoSave(card) {
    const api = KH.ai.api;
    const gone = (err) => !(err && err.status === 404); // already deleted counts as undone; anything else is an error
    if (card.undo.meal_id != null) {
      try { await api.deleteMeal(card.undo.meal_id); } catch (err) { if (gone(err)) throw err; }
      return;
    }
    let failure = null;
    for (const id of card.undo.entry_ids || []) {
      try { await api.deleteEntry(id); } catch (err) { if (gone(err)) failure = failure || err; }
    }
    if (failure) throw failure;
  }

  // The app could not place something: its own questions, nothing saved.
  function questionsBlock(questions) {
    const box = h('section', { class: 'ask-save ask-questions', 'aria-label': 'Not saved' });
    box.append(h('h3', {}, 'Not saved yet: the app needs to know'));
    const list = h('ul', { class: 'ask-save-items' });
    for (const q of questions) list.append(h('li', {}, q.question));
    box.append(list);
    return box;
  }

  // ---- tastes (note 09 §4.8, decision Q2) ----------------------------------
  // The assistant may propose "remember that I don't like salmon". That is always a card, whatever the person trusts: nothing
  // is written until Remember is pressed, and then this page (not the model) uses the app's normal routes: for a food PUT
  // /api/guidance/preferences/{id} with { preference, source: 'ask' } (DELETE to clear); for a food group it reads the person's
  // current "guidance" setting at that moment, moves only that group between the three lists and saves the whole object
  // (PATCH /api/me/settings). Undo puts back the state that was there when Remember was pressed. The words are the app's own,
  // built here from the card's fixed fields; the model's text is never an action label.
  const TASTE_TOOL = 'set_food_preference';
  const TASTE_WORDS = { like: 'liked', less: 'less often', not_for_me: 'not for me', clear: 'no preference', none: 'not set' };
  const GROUP_WORDS = { ...TASTE_WORDS, not_for_me: 'never suggest' };
  const GROUP_LIST = { like: 'like_categories', less: 'less_categories', not_for_me: 'exclude_categories' };
  const TASTE_NOT_ALLERGY = 'Less often and not for me are about taste. They are not an allergy filter: the app cannot tell whether a food contains an allergen, so check labels.';

  const isGroup = (card) => card.target && card.target.kind === 'group';
  function tasteWords(card, value) {
    if (value === 'neutral') return 'ignoring what the app learned from your log';
    return (isGroup(card) ? GROUP_WORDS : TASTE_WORDS)[value] || String(value);
  }
  function tasteSubject(card) { return isGroup(card) ? `${card.target.name} (food group)` : card.target.name; }
  function tasteLine(card, value) { return `${tasteSubject(card)}: ${tasteWords(card, value)}.`; }

  // The state of one food now: { value: 'none' | 'like' | 'less' | 'not_for_me' | 'neutral', source }.
  async function foodStateNow(foodId) {
    const res = await KH.api.foodPreferences();
    const row = ((res && res.foods) || []).find((f) => f.food_id === foodId);
    return row ? { value: row.preference, source: row.source || 'person' } : { value: 'none', source: null };
  }
  async function writeFood(foodId, state, source) {
    if (state === 'none') {
      try { await KH.api.clearFoodPreference(foodId); } catch (err) { if (!(err && err.status === 404)) throw err; } // already gone is gone
      return;
    }
    await KH.api.setFoodPreference(foodId, { preference: state, source });
  }
  // The person's whole "guidance" setting as it is now. A group is changed by saving this object with only its lists moved.
  async function guidanceNow() {
    const res = await KH.api.mySettings();
    const item = res && res.settings && res.settings.guidance;
    if (!item || !item.value || item.editable === false) throw new Error('Your food group choices could not be read, so nothing was changed.');
    return item.value;
  }
  function groupStateIn(guidance, name) {
    for (const [state, list] of Object.entries(GROUP_LIST)) if ((guidance[list] || []).includes(name)) return state;
    return 'none';
  }
  function withGroupState(guidance, name, state) {
    const next = { ...guidance };
    for (const list of Object.values(GROUP_LIST)) next[list] = (guidance[list] || []).filter((n) => n !== name);
    if (GROUP_LIST[state]) next[GROUP_LIST[state]] = [...next[GROUP_LIST[state]], name];
    return next;
  }
  // A preference changed: the suggestions the other screens remember are out of date.
  function tasteChanged() {
    try {
      if (KH.guidance && KH.guidance.forgetAnswers) KH.guidance.forgetAnswers();
      if (KH.guidance && KH.guidance.loadPrefs) Promise.resolve(KH.guidance.loadPrefs(true)).catch(() => {});
    } catch (err) { /* the other screens refresh themselves on their next load */ }
  }

  // Remember: read the state now, write the new one, and return what was there (Undo puts it back).
  async function rememberTaste(card) {
    if (isGroup(card)) {
      const name = card.target.name;
      const now = await guidanceNow();
      const before = groupStateIn(now, name);
      await KH.api.updateMySettings({ guidance: withGroupState(now, name, card.preference === 'clear' ? 'none' : card.preference) });
      return { state: before, source: null };
    }
    const id = card.target.food_id;
    const before = await foodStateNow(id);
    if (card.preference === 'clear') {
      if (before.value === 'neutral') return before; // "stop using what you learned" is not a taste: nothing to forget, and it stays
      await writeFood(id, 'none', 'ask');
    } else {
      await writeFood(id, card.preference, 'ask'); // the source is the page's own word: this change came from Ask, confirmed by the person
    }
    return { state: before.value, source: before.source };
  }
  async function undoTaste(card, before) {
    if (isGroup(card)) {
      const now = await guidanceNow();
      await KH.api.updateMySettings({ guidance: withGroupState(now, card.target.name, before.state) });
      return;
    }
    await writeFood(card.target.food_id, before.state, before.source || 'person');
  }

  // What the assistant asked to remember, nothing written yet.
  function tastePendingCard(card, entry) {
    const box = h('section', { class: 'ask-save ask-pending ask-taste', 'aria-label': 'Remember this?' });
    box.append(h('h3', {}, 'Remember this for your suggestions?'));
    box.append(h('p', { class: 'ask-save-meta ask-taste-line' }, tasteLine(card, card.preference)));
    box.append(h('p', { class: 'hint ask-save-meta' }, `Now: ${tasteWords(card, card.previous)}.`));
    if (card.preference === 'less' || card.preference === 'not_for_me') box.append(h('p', { class: 'hint ask-save-meta' }, TASTE_NOT_ALLERGY));
    const message = h('p', { class: 'form-error ask-save-error', role: 'alert' });
    const all = [];
    const remember = button('Remember', 'primary', async () => {
      for (const b of all) b.disabled = true;
      clear(message);
      try {
        const before = await rememberTaste(card);
        tasteChanged();
        entry.text = `Remembered: ${tasteLine(card, card.preference)}`;
        swap(box, tasteSavedCard(card, before, entry));
      } catch (err) {
        if (err && err.handled) return;
        message.textContent = errorText(err);
        for (const b of all) b.disabled = false;
      }
    });
    const cancel = button('Cancel', 'secondary', () => {
      entry.text = 'Not remembered: the person cancelled.';
      swap(box, h('p', { class: 'hint ask-save-note', role: 'status' }, 'Not remembered.'));
    });
    all.push(remember, cancel);
    box.append(message, h('div', { class: 'ask-save-actions' }, ...all));
    return box;
  }

  // Remembered, with Undo: puts back exactly what was there before Remember.
  function tasteSavedCard(card, before, entry) {
    const box = h('section', { class: 'ask-save ask-saved ask-taste', 'aria-label': 'Remembered' });
    box.append(h('h3', {}, 'Remembered for your suggestions'));
    box.append(h('p', { class: 'ask-save-meta ask-taste-line' }, tasteLine(card, card.preference)));
    box.append(h('p', { class: 'hint ask-save-meta' }, 'Suggestions use this from now on. It only changes the order of suggestions: your limits and warnings stay as they are.'));
    const status = h('p', { class: 'hint ask-save-status', role: 'status' });
    const undo = button('Undo', 'secondary', async (btn) => {
      btn.disabled = true;
      clear(status);
      try {
        await undoTaste(card, before);
        tasteChanged();
        entry.text = `The change to ${tasteSubject(card)} was undone.`;
        swap(box, h('p', { class: 'hint ask-save-note', role: 'status' }, `Undone. ${tasteSubject(card)} is back to: ${tasteWords(card, before.state)}.`));
      } catch (err) {
        if (err && err.handled) return;
        status.textContent = errorText(err);
        btn.disabled = false;
      }
    });
    box.append(h('div', { class: 'ask-save-actions' }, undo), status);
    return box;
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
    await refreshTrust();
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
    KH.views.ask = { refreshTab, show, newConversation, send, refreshTrust, endTrust: resetSaving };
  }
  init();
})();
