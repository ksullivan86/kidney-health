/* Kidney Diet Log — your own list app: Settings → Shopping list app, and Plan → Shopping list → Send (design note 30;
   app/list_sync/api.py).

   * KH.listSync.render(body) fills the Settings section and answers whether it should show: false while the server has the
     feature off (GET /api/list-sync answers enabled: false then).
   * The key is write-only: the box is empty, and "Saved" shows that one is kept. A new address or app needs the key again.
   * Test checks the address and key and lists the person's lists; with more than one, the person picks one.
   * KH.listSync.planButton(button) shows "Send to <app>" on Plan when a list app is set up; KH.listSync.openSend() opens the
     sheet that shows the exact lines first (foods ticked on this phone start unticked), then sends the ticked ones.
   * The demo shows a sample Grocy (js/mock/lists.js) and never leaves the page.

   All text goes in with h() children (textContent), never as HTML. */
(() => {
  'use strict';
  const KH = window.KH;
  const { h, $, clear, request, toast, toastError, sheets } = KH;
  const { MOCK } = KH.flags;

  const A = {
    get: () => request('GET', '/api/list-sync', undefined, { noQueue: true }),
    put: (body) => request('PUT', '/api/list-sync', body, { noQueue: true }),
    remove: () => request('DELETE', '/api/list-sync', undefined, { noQueue: true }),
    test: () => request('POST', '/api/list-sync/test', undefined, { noQueue: true }),
    preview: (start, end) => request('POST', '/api/list-sync/preview', { start, end }, { noQueue: true }),
    send: (start, end, foodIds) => request('POST', '/api/list-sync/send', { start, end, food_ids: foodIds }, { noQueue: true }),
  };

  const INTRO = 'Send the Plan\'s shopping list to your own Grocy, KitchenOwl or Mealie. Only the foods\' names and amounts are sent, '
    + 'nothing else about you.';
  const TEST_ACCOUNT = 'Test accounts cannot send the list to a list app. Sign in with your own account to set yours up.';
  const NO_HOME = 'A list app on your home network works only when your server\'s admin allows its address. On the internet, use https.';
  const ERRORS = {
    unreachable: 'The list app did not answer. Check the address, and that this server can reach it.',
    blocked: 'This server does not connect to that address. A home address works only when your admin allows it.',
    redirect: 'The list app sent the app on to another address. Enter the address it sends you to.',
    auth: 'The list app did not accept the key. Check it, or make a new one.',
    not_found: 'The list app has no such page. Check the address, and that it is the right app.',
    app_error: 'The list app gave an answer the app could not read.',
    no_key: 'The key can no longer be read on this server. Enter it again.',
    timeout: 'The list app took too long to answer. Try again later.',
  };

  let cached = null; // the last GET /api/list-sync
  let cachedAt = 0;
  async function status(fresh = false) {
    if (!fresh && cached && Date.now() - cachedAt < 60000) return cached;
    cached = await A.get();
    cachedAt = Date.now();
    return cached;
  }
  const appOf = (res, id) => (res.apps || []).find((a) => a.id === id) || { id, name: id, key_name: 'Key', key_help: '' };
  function whenText(iso) {
    const d = new Date(iso);
    if (!iso || Number.isNaN(d.getTime())) return '';
    return d.toLocaleString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });
  }
  const items = (n) => `${n} ${n === 1 ? 'item' : 'items'}`;

  // ---------------------------------------------------------------------------
  // Settings → Shopping list app
  // ---------------------------------------------------------------------------
  let drawSeq = 0;
  async function render(body, focusSel = null) {
    const ticket = ++drawSeq;
    let res;
    try { res = await status(true); } catch (err) {
      if (ticket !== drawSeq) return true;
      if (err && err.status === 404) { clear(body); return false; }
      clear(body).append(h('p', { class: 'form-error' }, `Could not load this: ${(err && (err.detail || err.message)) || 'unknown error'}`));
      return true;
    }
    if (ticket !== drawSeq) return true;
    if (!res.enabled) { clear(body); return false; }
    const parts = [h('p', {}, INTRO)];
    if (!res.can_use) {
      parts.push(h('p', { class: 'hint', id: 'set-lists-test' }, TEST_ACCOUNT));
      clear(body).append(...parts);
      return true;
    }
    const c = res.connection;
    if (c) parts.push(statusBlock(res, c));
    parts.push(form(body, res, c));
    if (MOCK) parts.push(h('p', { class: 'hint', id: 'set-lists-demo' }, 'This is a sample. The demo never contacts a list app.'));
    clear(body).append(...parts);
    if (focusSel) { const el = $(focusSel, body); if (el) el.focus(); }
    return true;
  }

  function statusBlock(res, c) {
    const app = appOf(res, c.app);
    const box = h('div', { id: 'set-lists-status' });
    box.append(h('p', { class: 'setting-status' }, h('span', { class: `state-pill ${c.last_test_error ? 'off' : 'on'}` }, c.last_test_error ? 'Check it' : 'Set up'),
      ' ', `${app.name} at ${c.base_url}. `, c.list_name ? `List: ${c.list_name}.` : 'No list chosen yet: press Test.'));
    const lines = [];
    if (c.last_test_at) lines.push(c.last_test_error ? `Last test ${whenText(c.last_test_at)}: it did not work.` : `Last test ${whenText(c.last_test_at)}: it worked.`);
    if (c.last_sent_at) lines.push(`Last sent ${whenText(c.last_sent_at)}: ${items(c.last_sent_count || 0)}.`);
    if (lines.length) box.append(h('p', { class: 'hint' }, lines.join(' ')));
    if (c.last_test_error && ERRORS[c.last_test_error]) box.append(h('p', { class: 'hint', id: 'set-lists-error' }, ERRORS[c.last_test_error]));
    return box;
  }

  function form(body, res, c) {
    const appSel = h('select', { id: 'set-lists-app' }, ...(res.apps || []).map((a) => h('option', { value: a.id }, a.name)));
    appSel.value = c ? c.app : 'grocy';
    const url = h('input', { id: 'set-lists-url', type: 'url', inputmode: 'url', maxlength: 500, autocomplete: 'off', spellcheck: 'false',
      placeholder: 'https://grocy.example.com', value: c ? c.base_url : '', 'aria-describedby': 'set-lists-url-hint' });
    const key = h('input', { id: 'set-lists-key', type: 'password', maxlength: 4096, autocomplete: 'off', spellcheck: 'false',
      placeholder: c && c.key_set ? 'Saved. Type a new one to change it.' : '', 'aria-describedby': 'set-lists-key-hint' });
    const keyLabel = h('label', { for: 'set-lists-key' }, appOf(res, appSel.value).key_name);
    const keyHint = h('span', { class: 'hint', id: 'set-lists-key-hint' }, `${appOf(res, appSel.value).key_help} It is kept locked on this server and never shown again.`);
    appSel.addEventListener('change', () => {
      const a = appOf(res, appSel.value);
      keyLabel.textContent = a.key_name;
      keyHint.textContent = `${a.key_help} It is kept locked on this server and never shown again.`;
    });
    const save = h('button', { class: 'btn primary', type: 'button', id: 'set-lists-save' }, c ? 'Save changes' : 'Save');
    save.addEventListener('click', async () => {
      const body1 = { app: appSel.value, base_url: url.value.trim() };
      if (key.value) body1.key = key.value;
      save.disabled = true;
      try {
        await A.put(body1);
        key.value = '';
        toast('Saved. Press Test to check it and choose a list.', 'ok');
        await render(body, '#set-lists-test-btn');
      } catch (err) { if (!err.handled) toastError(err); } finally { save.disabled = false; }
    });
    const fields = h('div', { class: 'form-grid' },
      h('div', { class: 'field' }, h('label', { for: 'set-lists-app' }, 'List app'), appSel),
      h('div', { class: 'field' }, h('label', { for: 'set-lists-url' }, 'Address'), url,
        h('span', { class: 'hint', id: 'set-lists-url-hint' }, res.private_hosts ? 'Its web address, as you open it in a browser.' : `Its web address, as you open it in a browser. ${NO_HOME}`)),
      h('div', { class: 'field span-2' }, keyLabel, key, keyHint));
    const actions = h('div', { class: 'settings-actions' }, save);
    const result = h('div', { id: 'set-lists-result', 'aria-live': 'polite' });
    if (c) {
      const test = h('button', { class: 'btn secondary', type: 'button', id: 'set-lists-test-btn' }, 'Test');
      test.addEventListener('click', () => runTest(body, res, c, test, result));
      const rm = h('button', { class: 'btn secondary', type: 'button', id: 'set-lists-remove' }, 'Remove');
      rm.addEventListener('click', () => confirmRemove(body, result, actions, rm, appOf(res, c.app)));
      actions.append(test, rm);
    }
    return h('div', {}, fields, actions, result);
  }

  async function runTest(body, res, c, btn, result) {
    btn.disabled = true;
    try {
      const out = await A.test();
      cached = null;
      if (!out.ok) { clear(result).append(h('p', { class: 'form-error' }, out.message || ERRORS[out.error] || 'The test did not work.')); return; }
      const conn = out.connection;
      if (conn.list_id && out.lists.length <= 1) {
        toast(`It works. The list is sent to “${conn.list_name}”.`, 'ok');
        await render(body, '#set-lists-test-btn');
        return;
      }
      if (!out.lists.length) { clear(result).append(h('p', { class: 'form-error' }, 'It works, but there is no shopping list in the app yet. Make one there, then press Test again.')); return; }
      const sel = h('select', { id: 'set-lists-choose' }, ...out.lists.map((l) => h('option', { value: l.id }, l.name)));
      if (conn.list_id) sel.value = conn.list_id;
      const use = h('button', { class: 'btn primary', type: 'button', id: 'set-lists-use' }, 'Use this list');
      use.addEventListener('click', async () => {
        use.disabled = true;
        const chosen = out.lists.find((l) => l.id === sel.value);
        try {
          await A.put({ app: c.app, base_url: c.base_url, list_id: chosen.id, list_name: chosen.name });
          cached = null;
          toast(`The list is sent to “${chosen.name}”.`, 'ok');
          await render(body, '#set-lists-test-btn');
        } catch (err) { use.disabled = false; if (!err.handled) toastError(err); }
      });
      clear(result).append(h('div', { class: 'field' }, h('label', { for: 'set-lists-choose' }, 'It works. Which list should the foods go to?'), sel),
        h('div', { class: 'settings-actions' }, use));
      sel.focus();
    } catch (err) { if (!err.handled) toastError(err); } finally { btn.disabled = false; }
  }

  function confirmRemove(body, host, actions, trigger, app) {
    const yes = h('button', { class: 'btn danger-solid', type: 'button', id: 'set-lists-remove-yes' }, 'Remove');
    const no = h('button', { class: 'btn secondary', type: 'button' }, 'Keep it');
    no.addEventListener('click', () => { clear(host); actions.hidden = false; trigger.focus(); });
    yes.addEventListener('click', async () => {
      yes.disabled = true;
      try { await A.remove(); cached = null; toast(`${app.name} is removed. Its address and key are deleted here.`, 'ok'); await render(body); } catch (err) { yes.disabled = false; if (!err.handled) toastError(err); }
    });
    actions.hidden = true;
    clear(host).append(h('div', { class: 'device-consent', role: 'group', 'aria-labelledby': 'set-lists-remove-h' },
      h('h4', { id: 'set-lists-remove-h' }, `Remove ${app.name}?`),
      h('p', {}, 'This server forgets its address and your key. Nothing is changed in the list app.'),
      h('div', { class: 'settings-actions' }, no, yes)));
    no.focus();
  }

  // ---------------------------------------------------------------------------
  // Plan → Shopping list → Send
  // ---------------------------------------------------------------------------
  /** Show the Send button when a list app is set up (it says the app's name). */
  async function planButton(btn, hasItems) {
    if (!btn) return;
    if (!hasItems) { btn.hidden = true; return; }
    try {
      const res = await status();
      const c = res && res.enabled && res.can_use ? res.connection : null;
      btn.hidden = !c;
      if (c) btn.textContent = `Send to ${appOf(res, c.app).name}`;
    } catch (e) { btn.hidden = true; }
  }

  const dlg = $('#sheet-list-send');
  if (dlg) sheets.setup(dlg);
  const send = { start: null, end: null, boxes: [], busy: false };
  /** Open the sheet: the exact lines, each with a box; `checks` are the foods ticked on this phone (they start unticked). */
  async function openSend({ start, end, checks, trigger }) {
    const bodyEl = clear($('#list-send-body'));
    const go = $('#list-send-go');
    go.disabled = true;
    send.start = start; send.end = end; send.boxes = [];
    $('#sheet-list-send-title').textContent = 'Send to your list app';
    $('#sheet-list-send-sub').textContent = '';
    bodyEl.append(h('p', { class: 'muted' }, 'Loading…'));
    sheets.open(dlg, trigger, $('[data-close]', dlg));
    let p;
    try { p = await A.preview(start, end); } catch (err) {
      clear(bodyEl).append(h('p', { class: 'form-error' }, (err && (err.detail || err.message)) || 'Could not load the list.'));
      return;
    }
    $('#sheet-list-send-title').textContent = `Send to ${p.app_name}`;
    $('#sheet-list-send-sub').textContent = p.list_name ? `List: ${p.list_name}` : '';
    clear(bodyEl);
    if (!p.ready) { bodyEl.append(h('p', { class: 'form-error', id: 'list-send-nolist' }, 'Choose a list first: press Test in Settings → Shopping list app.')); return; }
    if (!p.items.length) { bodyEl.append(h('p', { class: 'empty-state' }, 'Nothing is planned in this week, so there is nothing to send.')); return; }
    bodyEl.append(h('p', {}, `These lines go to ${p.app_name}, one item each: the food's name and amount. Nothing else about you is sent. `
      + 'Untick what you already have.'));
    if (p.last_sent_at) bodyEl.append(h('p', { class: 'hint', id: 'list-send-last' }, `You last sent the list ${whenText(p.last_sent_at)}: ${items(p.last_sent_count || 0)}. Sending again adds them again.`));
    const ul = h('ul', { class: 'list shopping-list', id: 'list-send-items', 'aria-label': 'Lines to send' });
    p.items.forEach((it, i) => {
      const id = `list-send-${i}`;
      const cb = h('input', { type: 'checkbox', id, checked: checks && checks.has(it.food_id) ? null : true });
      cb.addEventListener('change', countSelected);
      send.boxes.push({ cb, food_id: it.food_id });
      ul.append(h('li', { class: 'shop-item' }, h('label', { class: 'check shop-check', for: id }, cb, h('span', { class: 'check-text' }, it.text))));
    });
    bodyEl.append(ul);
    countSelected();
  }
  function countSelected() {
    const n = send.boxes.filter((b) => b.cb.checked).length;
    const go = $('#list-send-go');
    go.disabled = !n;
    go.textContent = n ? `Send ${items(n)}` : 'Send';
  }
  if (dlg) {
    sheets.onSubmit($('#list-send-form'), async (e) => {
      e.preventDefault();
      if (send.busy) return;
      const ids = send.boxes.filter((b) => b.cb.checked).map((b) => b.food_id);
      if (!ids.length) return;
      send.busy = true; $('#list-send-go').disabled = true;
      try {
        const out = await A.send(send.start, send.end, ids);
        cached = null;
        if (out.error) toast(`${out.sent ? `Sent ${items(out.sent)}, then it stopped. ` : ''}${out.message || ERRORS[out.error] || 'Sending did not work.'}`, 'error');
        else { dlg.close(); toast(`Sent ${items(out.sent)} to your list.`, 'ok'); }
      } catch (err) { if (!err.handled) toastError(err); } finally { send.busy = false; countSelected(); }
    });
  }

  KH.listSync = { render, status, planButton, openSend, ERRORS };
})();
