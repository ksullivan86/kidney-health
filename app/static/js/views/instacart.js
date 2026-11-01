/* Kidney Diet Log — Plan → Shopping list → Open in Instacart (design note 33; app/instacart.py).

   * KH.instacart.planButton(button, hasItems) shows the button while the server has Instacart on (GET /api/instacart answers
     enabled: false otherwise) and the week has foods.
   * KH.instacart.open() opens the sheet: the exact lines first, a box for each (foods ticked on this phone start unticked), and
     the sentence that Instacart is another company with its own terms and privacy policy. The person presses Send each time.
   * The server asks Instacart for the page and answers its link; this page never calls Instacart itself. The link opens in a new
     tab and is also shown to press, because a browser may block a tab opened after a wait. Only an https:// link is used.
   * The demo answers a placeholder that does not leave the page, and says nothing was sent.

   All text goes in with h() children (textContent), never as HTML. */
(() => {
  'use strict';
  const KH = window.KH;
  const { h, $, clear, request, toastError, sheets } = KH;
  const { MOCK } = KH.flags;

  const A = {
    get: () => request('GET', '/api/instacart', undefined, { noQueue: true }),
    preview: (start, end) => request('POST', '/api/instacart/preview', { start, end }, { noQueue: true }),
    send: (start, end, foodIds) => request('POST', '/api/instacart/send', { start, end, food_ids: foodIds }, { noQueue: true }),
  };
  const WHAT = 'These lines go to Instacart: each food\'s name and amount. Nothing else about you is sent. Untick what you already have.';
  const TERMS = 'Instacart is another company. Its own terms and privacy policy apply when you use its page. You choose a store, '
    + 'check the items and pay there, not in this app.';
  const ERRORS = {
    unreachable: 'Instacart did not answer. Try again later.',
    blocked: 'This server could not reach Instacart. Ask the person who runs it to check its network.',
    auth: 'Instacart did not accept this server\'s key. Ask the person who runs the server to check it.',
    rejected: 'Instacart did not accept the list. Try again with fewer foods, or later.',
    busy: 'Instacart is busy. Try again in a few minutes.',
    bad_answer: 'Instacart gave an answer the app could not use. Try again later.',
    timeout: 'Instacart took too long to answer. Try again later.',
  };

  let cached = null; // the last GET /api/instacart
  let cachedAt = 0;
  async function status() {
    if (cached && Date.now() - cachedAt < 60000) return cached;
    cached = await A.get();
    cachedAt = Date.now();
    return cached;
  }
  const items = (n) => `${n} ${n === 1 ? 'item' : 'items'}`;

  /** Show "Open in Instacart" while the server has it on and the week has foods. */
  async function planButton(btn, hasItems) {
    if (!btn) return;
    if (!hasItems) { btn.hidden = true; return; }
    try { const res = await status(); btn.hidden = !(res && res.enabled); } catch (e) { btn.hidden = true; }
  }

  const dlg = $('#sheet-instacart');
  if (dlg) sheets.setup(dlg);
  const st = { start: null, end: null, boxes: [], busy: false, done: false };

  function goButton() { return $('#instacart-go'); }
  function countSelected() {
    const go = goButton();
    if (st.done) { go.hidden = true; return; }
    const n = st.boxes.filter((b) => b.cb.checked).length;
    go.hidden = false;
    go.disabled = !n || st.busy;
    go.textContent = n ? `Send ${items(n)} to Instacart` : 'Send to Instacart';
  }

  /** Open the sheet for a week of the Plan; `checks` are the foods ticked on this phone (they start unticked). */
  async function open({ start, end, checks, trigger }) {
    const body = clear($('#instacart-body'));
    st.start = start; st.end = end; st.boxes = []; st.done = false; st.busy = false;
    const go = goButton();
    go.hidden = false; go.disabled = true; go.textContent = 'Send to Instacart';
    $('#instacart-cancel').textContent = 'Cancel';
    body.append(h('p', { class: 'muted' }, 'Loading…'));
    sheets.open(dlg, trigger, $('[data-close]', dlg));
    let p;
    try { p = await A.preview(start, end); } catch (err) {
      clear(body).append(h('p', { class: 'form-error' }, (err && (err.detail || err.message)) || 'Could not load the list.'));
      return;
    }
    clear(body);
    if (!p.items.length) { body.append(h('p', { class: 'empty-state' }, 'Nothing is planned in this week, so there is nothing to send.')); return; }
    body.append(h('p', { id: 'instacart-what' }, WHAT), h('p', { class: 'hint', id: 'instacart-terms' }, TERMS));
    const ul = h('ul', { class: 'list shopping-list', id: 'instacart-items', 'aria-label': 'Lines to send to Instacart' });
    p.items.forEach((it, i) => {
      const id = `instacart-${i}`;
      const cb = h('input', { type: 'checkbox', id, checked: checks && checks.has(it.food_id) ? null : true });
      cb.addEventListener('change', countSelected);
      st.boxes.push({ cb, food_id: it.food_id });
      ul.append(h('li', { class: 'shop-item' }, h('label', { class: 'check shop-check', for: id }, cb, h('span', { class: 'check-text' }, it.text))));
    });
    body.append(ul, h('div', { id: 'instacart-result', 'aria-live': 'polite' }));
    countSelected();
  }

  function showReady(url, n) {
    st.done = true;
    countSelected();
    $('#instacart-cancel').textContent = 'Close';
    const body = clear($('#instacart-body'));
    if (MOCK || !/^https:\/\//i.test(url || '')) {
      body.append(h('p', { id: 'instacart-demo' }, `This is the demo, so nothing was sent. On a server, Instacart's page with these ${items(n)} opens now in a new tab.`));
      return;
    }
    body.append(h('p', {}, `Your list of ${items(n)} is ready at Instacart. Choose a store there and check each item.`),
      h('p', {}, h('a', { class: 'btn primary', id: 'instacart-open', href: url, target: '_blank', rel: 'noopener noreferrer', referrerpolicy: 'no-referrer' },
        'Open the list at Instacart', h('span', { class: 'sr-only' }, ' (opens in a new tab)'))),
      h('p', { class: 'hint' }, 'If no new tab opened, press the button. The link works for 7 days. This app does not keep it.'));
    try { window.open(url, '_blank', 'noopener,noreferrer'); } catch (e) { /* blocked: the button is there */ }
    const link = $('#instacart-open');
    if (link) link.focus();
  }

  if (dlg) {
    sheets.onSubmit($('#instacart-form'), async (e) => {
      e.preventDefault();
      if (st.busy || st.done) return;
      const ids = st.boxes.filter((b) => b.cb.checked).map((b) => b.food_id);
      if (!ids.length) return;
      st.busy = true; countSelected();
      const result = $('#instacart-result');
      try {
        const out = await A.send(st.start, st.end, ids);
        if (out.error || !out.url) {
          if (result) clear(result).append(h('p', { class: 'form-error', id: 'instacart-error' }, out.message || ERRORS[out.error] || 'Sending did not work.'));
        } else {
          st.busy = false;
          showReady(out.url, out.items);
        }
      } catch (err) { if (!err.handled) toastError(err); } finally { st.busy = false; countSelected(); }
    });
  }

  KH.instacart = { status, planButton, open, ERRORS };
})();
