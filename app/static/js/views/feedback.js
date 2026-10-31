/* Kidney Diet Log — Send feedback and the admin's Test accounts and Feedback parts (design note 26; app/feedback.py).

   * Test accounts (Me.test_account) see a Send feedback button in the header on every screen (js/views/auth.js shows it). The
     sheet asks what they were trying to do (started with the screen's name), what happened, whether the screen was useful, and
     "this looked wrong or unsafe". Only what they typed is sent, with the screen's name; the server adds the app version and
     the time. Nothing is copied in: no screenshot, no numbers from the log. Below the form: what they sent before.
   * Server administration → Test accounts: the state of tester and tester-helper, why they could not be made (if so), and
     Reset test accounts. → Feedback: what testers sent, filtered (open, done, all; only "wrong or unsafe"), Mark done, Export
     CSV and Delete done.

   Not in the demo or the preview (index.html loads this file with data-preview="omit"; js/views/settings.js leaves the
   admin parts out with ?mock=1): the demo has no accounts of its own. All text goes in with h() children (textContent). */
(() => {
  'use strict';
  const KH = window.KH;
  const { h, $, clear, request, download, toast, toastError, confirm, sheets, state } = KH;

  // The name of each screen, as its tab or title says it.
  const SCREEN = { today: 'Today', add: 'Add', plan: 'Plan', trends: 'Trends', ask: 'Ask AI', profile: 'Profile', labs: 'Lab results',
    visit: 'Visit prep', settings: 'Settings', admin: 'Server administration' };
  const USEFUL = { yes: 'Useful', somewhat: 'A little', no: 'Not useful' };
  const STATUS = { active: 'On', disabled: 'Off', locked: 'Locked', pending_setup: 'Not set up' };

  const A = {
    mine: () => request('GET', '/api/feedback'),
    send: (body) => request('POST', '/api/feedback', body),
    status: () => request('GET', '/api/admin/test-accounts'),
    reset: () => request('POST', '/api/admin/test-accounts/reset'),
    list: (stateName, unsafe) => request('GET', `/api/admin/feedback?state=${encodeURIComponent(stateName)}${unsafe ? '&unsafe=true' : ''}`),
    mark: (id, done) => request('PATCH', `/api/admin/feedback/${encodeURIComponent(id)}`, { done }),
    deleteDone: () => request('DELETE', '/api/admin/feedback/done'),
  };

  const screenName = () => SCREEN[state.view] || 'Other';
  const when = (iso) => { try { return new Date(iso).toLocaleString(); } catch (e) { return iso; } };

  function itemView(f, { admin = false, onMark = null } = {}) {
    const head = [admin ? `${f.username} · ` : '', `${f.screen} · ${when(f.created_at)}`, f.done ? ' · done' : ''].join('');
    const tags = [f.useful ? USEFUL[f.useful] : null, f.unsafe ? 'Looked wrong or unsafe' : null, admin ? `app ${f.app_version}` : null]
      .filter(Boolean).join(' · ');
    const li = h('li', { class: 'feedback-item' },
      h('span', { class: 'row-title' }, head),
      f.trying ? h('p', {}, h('strong', {}, 'Trying to: '), f.trying) : null,
      f.happened ? h('p', {}, h('strong', {}, 'What happened: '), f.happened) : null,
      tags ? h('span', { class: 'row-sub' }, tags) : null);
    if (onMark) {
      const btn = h('button', { class: 'btn secondary small', type: 'button' }, f.done ? 'Open again' : 'Mark done');
      btn.addEventListener('click', () => onMark(f, btn));
      li.append(h('div', { class: 'settings-actions' }, btn));
    }
    return li;
  }

  // ---- The tester: the sheet

  async function renderMine() {
    const box = clear($('#feedback-mine'));
    let res;
    try { res = await A.mine(); } catch (err) { box.append(h('p', { class: 'hint' }, 'What you sent could not be loaded.')); return; }
    if (!res.feedback.length) { box.append(h('p', { class: 'hint' }, 'Nothing yet.')); return; }
    box.append(h('ul', { class: 'feedback-list' }, res.feedback.slice(0, 20).map((f) => itemView(f))));
  }

  function open(trigger) {
    const dlg = $('#sheet-feedback');
    if (!dlg || !(state.me && state.me.test_account)) return;
    const screen = screenName();
    dlg.dataset.screen = screen;
    $('#feedback-screen').textContent = `About the ${screen} screen.`;
    const trying = $('#feedback-trying');
    trying.value = `${screen}: `;
    $('#feedback-happened').value = '';
    for (const r of dlg.querySelectorAll('input[name="fuseful"]')) r.checked = false;
    $('#feedback-unsafe').checked = false;
    clear($('#feedback-error'));
    $('#feedback-send').disabled = false;
    sheets.open(dlg, trigger, trying);
    setTimeout(() => { try { trying.setSelectionRange(trying.value.length, trying.value.length); } catch (e) { /* ignore */ } }, 40);
    renderMine();
  }

  async function send(e) {
    e.preventDefault();
    const dlg = $('#sheet-feedback');
    const btn = $('#feedback-send');
    if (btn.disabled) return;
    const err = clear($('#feedback-error'));
    const screen = dlg.dataset.screen || screenName();
    let trying = $('#feedback-trying').value.trim();
    if (trying === `${screen}:`) trying = ''; // only the screen's name: nothing was typed
    const happened = $('#feedback-happened').value.trim();
    if (!trying && !happened) { err.append(h('p', {}, 'Say what you were trying to do or what happened.')); $('#feedback-happened').focus(); return; }
    const useful = (dlg.querySelector('input[name="fuseful"]:checked') || {}).value || null;
    btn.disabled = true;
    try {
      await A.send({ screen, trying, happened, useful, unsafe: $('#feedback-unsafe').checked });
      dlg.close();
      toast('Thank you. Your feedback was sent.', 'ok');
    } catch (ex) {
      if (!ex.handled) err.append(h('p', {}, ex.detail || ex.message || 'It was not sent. Try again.'));
    } finally {
      btn.disabled = false;
    }
  }

  function setup() {
    const dlg = $('#sheet-feedback');
    const btn = $('#feedback-open');
    if (!dlg || !btn) return;
    sheets.setup(dlg);
    sheets.onSubmit($('#feedback-form'), send);
    btn.addEventListener('click', () => open(btn));
  }

  // ---- Admins: Server administration → Test accounts and Feedback

  let filter = { state: 'open', unsafe: false };

  async function renderTesters() {
    const box = $('#set-testers');
    if (!box) return;
    let st;
    try { st = await A.status(); } catch (err) { clear(box).append(h('p', { class: 'hint' }, err.detail || 'Could not load.')); return; }
    if (!document.contains(box)) return;
    clear(box);
    box.append(h('p', { class: 'hint' }, 'Two accounts for people who test the app on this server: tester (the sample person Sam) and '
      + 'tester-helper (a Care helper on Sam’s Care team). They share one password, from the file TEST_ACCOUNT_PASSWORD_FILE. '
      + 'They are never admins and never see anyone else. The walk-through for testers is docs/test-the-full-app.md.'));
    if (!st.enabled) {
      box.append(h('p', {}, 'Test accounts are off. Turn them on in Server settings → Test accounts (or TEST_ACCOUNT_ENABLED).'));
      return;
    }
    if (st.problem) box.append(h('div', { class: 'form-error', role: 'alert' }, h('p', {}, st.problem)));
    if (st.accounts.length) {
      box.append(h('ul', { class: 'list' }, st.accounts.map((a) => h('li', {},
        h('span', { class: 'row-title' }, a.username),
        h('span', { class: 'row-sub' }, `${STATUS[a.status] || a.status} · ${a.last_login_at ? `last signed in ${when(a.last_login_at)}` : 'never signed in'}`)))));
    }
    box.append(h('p', { class: 'hint' }, `The server’s AI is ${st.ai ? 'on' : 'off'} for test accounts (Server settings → Test accounts).`));
    const reset = h('button', { class: 'btn secondary', type: 'button', id: 'testers-reset' }, 'Reset test accounts');
    const actions = h('div', { class: 'settings-actions' }, reset);
    reset.addEventListener('click', () => confirm.inline(actions, reset, {
      message: 'Delete everything tester and tester-helper did and start them again with Sam’s sample data? They are signed out. The feedback stays.',
      confirmText: 'Reset',
      onConfirm: async () => {
        await A.reset();
        toast('Test accounts reset. They start again from the sample data.', 'ok');
        renderTesters();
        return true;
      },
    }));
    box.append(actions);
  }

  async function renderFeedback() {
    const box = $('#set-feedback');
    if (!box) return;
    let res;
    try { res = await A.list(filter.state, filter.unsafe); } catch (err) { clear(box).append(h('p', { class: 'hint' }, err.detail || 'Could not load.')); return; }
    if (!document.contains(box)) return;
    clear(box);
    const c = res.counts;
    box.append(h('p', { class: 'hint' }, `What testers sent with Send feedback: ${c.open} open, ${c.done} done`
      + `${c.unsafe_open ? `, ${c.unsafe_open} open marked “wrong or unsafe”` : ''}. Only what they typed is kept, with the screen, the app version and the time.`));
    const pick = h('select', { id: 'feedback-filter', 'aria-label': 'Show' },
      [['open', 'Open'], ['done', 'Done'], ['all', 'All']].map(([v, t]) => h('option', { value: v }, t)));
    pick.value = filter.state;
    pick.addEventListener('change', () => { filter = { ...filter, state: pick.value }; renderFeedback(); });
    const unsafe = h('input', { type: 'checkbox', id: 'feedback-filter-unsafe' });
    unsafe.checked = filter.unsafe;
    unsafe.addEventListener('change', () => { filter = { ...filter, unsafe: unsafe.checked }; renderFeedback(); });
    const csv = h('button', { class: 'btn secondary small', type: 'button', id: 'feedback-export' }, 'Export CSV');
    csv.addEventListener('click', () => download(`/api/admin/feedback.csv?state=${encodeURIComponent(filter.state)}${filter.unsafe ? '&unsafe=true' : ''}`,
      'feedback.csv').catch(toastError));
    const tidy = h('button', { class: 'btn secondary small', type: 'button', id: 'feedback-delete-done' }, 'Delete done');
    const filters = h('div', { class: 'feedback-filters' }, h('label', { for: 'feedback-filter' }, 'Show'), pick,
      h('label', { class: 'check', for: 'feedback-filter-unsafe' }, unsafe, h('span', { class: 'check-text' }, 'Only “wrong or unsafe”')), csv, tidy);
    tidy.addEventListener('click', () => confirm.inline(filters, tidy, {
      message: 'Delete every item marked done? Export it first if you want to keep it.',
      onConfirm: async () => { const r = await A.deleteDone(); toast(`${r.deleted} deleted.`, 'ok'); renderFeedback(); return true; },
    }));
    box.append(filters);
    if (!res.feedback.length) { box.append(h('p', { class: 'hint' }, 'Nothing here.')); return; }
    const onMark = async (f, btn) => {
      btn.disabled = true;
      try { await A.mark(f.id, !f.done); renderFeedback(); } catch (err) { btn.disabled = false; if (!err.handled) toastError(err); }
    };
    box.append(h('ul', { class: 'feedback-list', 'aria-labelledby': 'set-feedback-h' }, res.feedback.map((f) => itemView(f, { admin: true, onMark }))));
  }

  function loadAdmin() {
    renderTesters().catch((err) => console.warn('Test accounts:', err));
    renderFeedback().catch((err) => console.warn('Feedback:', err));
  }

  setup();
  KH.feedback = { open, loadAdmin, SCREEN };
})();
