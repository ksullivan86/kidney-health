/* Kidney Diet Log — read-only sharing (design note 19; app/sharing.py).

   * KH.sharing.block(): Settings → Account → Sharing. Who can see your data (Stop sharing), your links nobody has used yet
     (Cancel), Share with someone (four boxes, then the link once with Copy link), and who shares with you (Open, Stop seeing).
   * A link #/share/<code> is taken out of the address bar into memory when the page opens (so a sign-in screen does not lose
     it and it does not stay in the history), and once someone is signed in the share sheet asks "Accept?" before anything is
     saved. Nothing about the link is stored in the browser.
   * KH.sharing.reads(id): the read routes of one share, in the shape js/views/visit.js calls, so the Visit prep page shows the
     other person's summary. KH.sharing.renderDay() draws one day of their food log for the same page.

   Every request is a read except making or ending a share and accepting a link; nothing here can write to anyone's log. All
   text goes in with h() children (textContent), never as HTML. In the demo the server answers that sharing is off. */
(() => {
  'use strict';
  const KH = window.KH;
  const { h, $, clear, request, toast, toastError, confirm, sheets, state } = KH;
  const { MOCK } = KH.flags;

  const AREAS = ['food', 'labs', 'body', 'symptoms'];
  const AREA_LABEL = { food: 'food log', labs: 'lab results', body: 'weight and blood pressure', symptoms: 'symptoms' };
  // How long a share lasts once accepted (POST /api/me/shares `days`; the server takes 1 to 365).
  const DAY_CHOICES = [['', 'Until I stop it'], ['7', '1 week'], ['30', '30 days'], ['90', '90 days'], ['365', '1 year']];
  const LINK_RE = /^#\/share\/([0-9a-f]{16}\.[A-Za-z0-9_-]{43})$/;
  const INTRO = 'Let a family member, caregiver or dietitian who has an account on this server see parts of your log. '
    + 'They can look, but never change anything. You can stop at any time.';
  const OFF = 'Your admin has not turned on sharing for this server.';
  const DEMO = 'The demo has no other people, so there is nobody to share with. On your own server you share from here.';
  const BAD_LINK = 'That link does not work. Ask for a new one.';
  const SWITCHED_OFF = 'Sharing is turned off on this server. Ask your admin.';

  const A = {
    mine: () => request('GET', '/api/me/shares'),
    make: (areas, days) => request('POST', '/api/me/shares', { areas, days: days || null }),
    end: (id) => request('DELETE', `/api/me/shares/${id}`),
    people: () => request('GET', '/api/shared'),
    stop: (id) => request('DELETE', `/api/shared/${id}`),
    info: (code) => request('POST', '/api/shared/info', { code }),
    accept: (code) => request('POST', '/api/shared/accept', { code }),
  };

  /** The reads of share `id`, named as js/core.js names the person's own (KH.api), plus the day and the profile. */
  function reads(id) {
    const base = `/api/shared/${encodeURIComponent(id)}`;
    const qs = KH.util.qs;
    return {
      summary: (start, end) => request('GET', `${base}/log/summary?${qs({ start, end })}`),
      labs: (params = {}) => request('GET', `${base}/labs?${qs(params)}`),
      symptoms: (start, end) => request('GET', `${base}/symptoms?${qs({ start, end })}`),
      bodySummary: (date) => request('GET', `${base}/body/summary?${qs({ date })}`),
      bodyWeights: (start, end) => request('GET', `${base}/body/weights?${qs({ start, end })}`),
      bloodPressures: (start, end) => request('GET', `${base}/body/blood-pressure?${qs({ start, end })}`),
      day: (date) => request('GET', `${base}/log?${qs({ date })}`),
      profile: () => request('GET', `${base}/profile`),
    };
  }

  // ---------------------------------------------------------------------------
  // Pure helpers (tests/test_sharing_ui.py runs them in Node)
  // ---------------------------------------------------------------------------
  /** ["food", "labs", "symptoms"] → "food log, lab results and symptoms". */
  function areasText(areas) {
    const names = AREAS.filter((a) => (areas || []).includes(a)).map((a) => AREA_LABEL[a]);
    if (names.length <= 1) return names.join('');
    return `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}`;
  }
  function fmtDay(iso) {
    if (!iso) return '';
    const d = new Date(String(iso).length === 10 ? `${iso}T12:00:00` : iso);
    return Number.isNaN(d.getTime()) ? '' : d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
  }
  /** When the other person last looked, in words. `today` is YYYY-MM-DD (UTC, as the server counts views). */
  function lastLooked(iso, today) {
    if (!iso) return 'has not looked yet';
    return String(iso).slice(0, 10) === today ? 'looked today' : `last looked ${fmtDay(iso)}`;
  }
  /** How long a share lasts, in words: "for 30 days" (a link's `days`) or "until Nov 28, 2026" (an accepted share's `until`). */
  function lastsText(days) { return days ? `for ${days} ${days === 1 ? 'day' : 'days'}` : 'until one of you stops it'; }
  function untilText(until) { return until ? `until ${fmtDay(until)}` : null; }
  function sharingLine(s, today) {
    const parts = [areasText(s.areas), `since ${fmtDay(s.since)}`, untilText(s.until), lastLooked(s.last_viewed_at, today)].filter(Boolean);
    if (s.active === false) parts.push('their account is turned off');
    return parts.join(' · ');
  }
  function personLine(p) { return [areasText(p.areas), `since ${fmtDay(p.since)}`, untilText(p.until)].filter(Boolean).join(' · '); }
  function whoText(p) { return p.name && p.name !== p.username ? `${p.name} (${p.username})` : p.username || p.name || ''; }
  function questionText(info) {
    const who = whoText(info);
    const lasts = info.days ? ` It ends by itself after ${info.days} ${info.days === 1 ? 'day' : 'days'}.` : '';
    return `${who} wants to share their ${areasText(info.areas)} with you. You can look, but not change anything. `
      + `${who} can stop this at any time, and so can you.${lasts}`;
  }
  /** One entry of a shared day as a line: "Banana, 1 serving (planned)". */
  function entryLine(e) {
    const n = Number(e.servings);
    const amount = e.grams != null ? `${Math.round(Number(e.grams))} g` : `${Number.isFinite(n) ? n : e.servings} ${n === 1 ? 'serving' : 'servings'}`;
    const tags = [e.status === 'planned' ? 'planned' : null, e.purpose === 'hypo' ? 'to treat a low' : null].filter(Boolean);
    return `${e.food_name}, ${amount}${tags.length ? ` (${tags.join(', ')})` : ''}`;
  }

  // ---------------------------------------------------------------------------
  // Settings → Account → Sharing
  // ---------------------------------------------------------------------------
  function button(label, cls, fn, attrs = {}) {
    const btn = h('button', { class: `btn ${cls}`, type: 'button', ...attrs }, label);
    btn.addEventListener('click', async () => {
      if (btn.disabled) return;
      btn.disabled = true;
      try { await fn(btn); } catch (err) { if (!err.handled && !err.cancelled) toastError(err); } finally { if (document.contains(btn)) btn.disabled = false; }
    });
    return btn;
  }
  const today = () => new Date().toISOString().slice(0, 10);

  function block() {
    const body = h('div', { id: 'set-sharing', role: 'region', 'aria-labelledby': 'set-sharing-h' }, h('p', { class: 'muted small' }, 'Loading…'));
    load(body);
    return h('div', { class: 'sharing' }, h('h3', { class: 'settings-subtitle', id: 'set-sharing-h' }, 'Sharing'), body);
  }

  async function load(body, made = null, focusSel = null) {
    let mine;
    let people = [];
    try {
      mine = await A.mine();
      if (mine.enabled) people = (await A.people()).people || [];
    } catch (err) {
      clear(body).append(h('p', { class: 'form-error' }, `Could not load this: ${(err && (err.detail || err.message)) || 'unknown error'}`));
      if (made) body.append(linkBox(made)); // a new link is never lost because the list could not load
      return;
    }
    render(body, mine, people, made);
    if (focusSel) { const el = $(focusSel, body); if (el) el.focus(); }
  }

  function render(body, mine, people, made) {
    clear(body);
    if (!mine.enabled) { body.append(h('p', { class: 'hint', id: 'set-sharing-off' }, MOCK ? DEMO : OFF)); return; }
    body.append(h('p', {}, INTRO));

    body.append(h('h4', { class: 'settings-minor' }, 'Who can see your data'));
    if (!mine.sharing.length) body.append(h('p', { class: 'muted small', id: 'set-sharing-none' }, 'Nobody yet.'));
    else {
      const ul = h('ul', { class: 'list device-list', id: 'set-sharing-list', 'aria-label': 'People who can see your data' });
      for (const s of mine.sharing) {
        const actions = h('div', { class: 'token-actions' });
        const stop = h('button', { class: 'btn secondary', type: 'button', 'aria-label': `Stop sharing with ${whoText(s)}` }, 'Stop sharing');
        stop.addEventListener('click', () => confirm.inline(actions, stop, {
          message: `Stop sharing with ${whoText(s)}? They can no longer see any of your data.`,
          confirmText: 'Stop sharing',
          onConfirm: async () => { await A.end(s.id); toast(`Stopped sharing with ${s.name || s.username}`, 'ok'); await load(body, null, '#set-sharing-make'); return true; },
        }));
        actions.append(stop);
        ul.append(h('li', { class: 'device' }, h('div', { class: 'device-main' }, h('span', { class: 'row-title' }, whoText(s)),
          h('span', { class: 'row-sub' }, sharingLine(s, today()))), actions));
      }
      body.append(ul);
    }

    if (mine.codes.length) {
      body.append(h('h4', { class: 'settings-minor' }, 'Links nobody has used yet'));
      const ul = h('ul', { class: 'list device-list', id: 'set-sharing-codes', 'aria-label': 'Links nobody has used yet' });
      for (const c of mine.codes) {
        const cancel = button('Cancel', 'secondary', async () => {
          await A.end(c.id);
          toast('Link cancelled', 'ok');
          await load(body, null, '#set-sharing-make');
        }, { 'aria-label': `Cancel the link for your ${areasText(c.areas)}` });
        ul.append(h('li', { class: 'device' }, h('div', { class: 'device-main' }, h('span', { class: 'row-title' }, areasText(c.areas)),
          h('span', { class: 'row-sub' }, `shares ${lastsText(c.days)} · the link works until ${fmtDay(c.expires_at)}`)), h('div', { class: 'token-actions' }, cancel)));
      }
      body.append(ul);
    }

    body.append(shareForm(body, mine));
    if (made) body.append(linkBox(made));

    body.append(h('h4', { class: 'settings-minor', id: 'set-shared-h' }, 'Shared with you'));
    if (!people.length) {
      body.append(h('p', { class: 'muted small', id: 'set-shared-none' }, 'Nobody shares with you yet. When someone sends you a link, open it while you are signed in.'));
    } else {
      const ul = h('ul', { class: 'list device-list', id: 'set-shared-list', 'aria-labelledby': 'set-shared-h' });
      for (const p of people) {
        const actions = h('div', { class: 'token-actions' });
        const open = button('Open', 'primary', () => openShared(p), { 'aria-label': `Open what ${whoText(p)} shares with you` });
        const stop = h('button', { class: 'btn secondary', type: 'button', 'aria-label': `Stop seeing what ${whoText(p)} shares` }, 'Stop seeing');
        stop.addEventListener('click', () => confirm.inline(actions, stop, {
          message: `Stop seeing what ${whoText(p)} shares? They would have to send you a new link.`,
          confirmText: 'Stop seeing',
          onConfirm: async () => { await A.stop(p.id); toast(`You no longer see ${p.name || p.username}'s data`, 'ok'); await load(body, null, '#set-shared-h'); return true; },
        }));
        actions.append(open, stop);
        ul.append(h('li', { class: 'device' }, h('div', { class: 'device-main' }, h('span', { class: 'row-title' }, whoText(p)),
          h('span', { class: 'row-sub' }, personLine(p))), actions));
      }
      body.append(ul);
    }
  }

  function shareForm(body, mine) {
    const err = h('div', { class: 'form-error', role: 'alert' });
    if (mine.sharing.length >= mine.max) {
      return h('p', { class: 'hint' }, `You share with ${mine.max} people, the most allowed. Stop sharing with someone to add another.`);
    }
    const boxes = AREAS.map((a) => {
      const id = `set-share-${a}`;
      const box = h('input', { type: 'checkbox', id, value: a });
      box.checked = true;
      return h('label', { class: 'check', for: id }, box, ` My ${AREA_LABEL[a]}`);
    });
    const lasts = h('select', { id: 'set-share-days' }, ...DAY_CHOICES.map(([v, label]) => h('option', { value: v }, label)));
    const make = h('button', { class: 'btn primary', type: 'submit', id: 'set-sharing-make' }, 'Make a link');
    const form = h('form', { class: 'settings-form sharing-form', novalidate: true },
      h('fieldset', {}, h('legend', {}, 'Share with someone'), boxes),
      h('label', { class: 'label', for: 'set-share-days' }, 'For how long'), lasts,
      h('span', { class: 'hint' }, 'You get a link to send them. It works once, for 7 days. They need their own account on this server.'),
      h('div', { class: 'settings-actions' }, make), err);
    sheets.onSubmit(form, async (e) => {
      e.preventDefault();
      if (make.disabled) return;
      clear(err);
      const areas = AREAS.filter((a) => $(`#set-share-${a}`, form).checked);
      if (!areas.length) { err.append(h('p', {}, 'Tick at least one thing to share.')); return; }
      make.disabled = true;
      try {
        const made = await A.make(areas, Number(lasts.value) || null);
        await load(body, made);
      } catch (e2) {
        if (e2.cancelled || e2.handled) return;
        err.append(h('p', {}, e2.detail || e2.message || 'No link was made. Try again.'));
      } finally { if (document.contains(make)) make.disabled = false; }
    });
    return form;
  }

  function linkBox(made) {
    const id = 'set-share-link';
    const input = h('input', { id, type: 'text', class: 'link-input', readonly: true, value: made.link, spellcheck: 'false', autocomplete: 'off' });
    const copy = button('Copy link', 'primary', async () => {
      try { await navigator.clipboard.writeText(made.link); toast('Link copied', 'ok'); } catch (e) {
        input.focus(); input.select();
        toast('Select the link and copy it (Ctrl+C, or touch and hold on a phone).');
      }
    });
    setTimeout(() => { if (document.contains(input)) { input.focus(); input.select(); } }, 30);
    return h('div', { class: 'link-box', role: 'group', 'aria-label': 'New share link' },
      h('label', { for: id, class: 'label' }, `Link for your ${areasText(made.code.areas)} (shown only now)`),
      h('div', { class: 'link-row' }, input, copy),
      h('p', { class: 'hint' }, `Send it to the person you want to share with. It works once, until ${fmtDay(made.code.expires_at)}. `
        + `Once they accept, you share ${lastsText(made.code.days)}.`),
      h('p', { class: 'hint' }, 'Whoever opens it first while signed in can accept it, so send it only to them.'));
  }

  // ---------------------------------------------------------------------------
  // Opening what someone shares: the Visit prep page, read-only (js/views/visit.js)
  // ---------------------------------------------------------------------------
  function openShared(person) {
    if (KH.views.visit && KH.views.visit.openShared) KH.views.visit.openShared({ ...person, reads: reads(person.id) });
  }

  /** One day of a shared food log into `box`: the entries by meal and the day's totals against the targets. */
  async function renderDay(box, rd, date) {
    clear(box).append(h('p', { class: 'muted' }, 'Loading…'));
    let day;
    try { day = await rd.day(date); } catch (err) {
      clear(box).append(h('p', { class: 'visit-note visit-problem' }, `This day could not be loaded${err && err.detail ? ` (${err.detail})` : ''}.`));
      return;
    }
    clear(box);
    const R = KH.rules;
    if (!day.entries.length) { box.append(h('p', { class: 'visit-note' }, 'Nothing was logged on this day.')); return; }
    for (const m of R.MEALS) {
      const rows = day.entries.filter((e) => e.meal === m.key);
      if (!rows.length) continue;
      box.append(h('p', { class: 'visit-body-sub' }, m.label), h('ul', { class: 'visit-body-list' }, rows.map((e) => h('li', {}, entryLine(e)))));
    }
    const lines = [];
    for (const key of Object.keys(day.status || {})) {
      const st = day.status[key];
      if (!R.NUT[key] || st.target == null) continue;
      const nut = R.NUT[key];
      const value = st.value == null ? 'not listed' : `${st.unknown ? '≥ ' : ''}${R.fmtNum(st.value, key)}`;
      lines.push(h('li', {}, `${nut.label}: `, h('b', {}, value), ` of ${R.fmtNum(st.target, key)} ${nut.unit}`,
        st.level && st.level !== 'ok' ? [' ', KH.ui.levelPill(st.level, KH.ui.LEVEL_TEXT[st.level])] : null));
    }
    if (lines.length) box.append(h('p', { class: 'visit-body-sub' }, 'The day against the targets (food marked eaten)'), h('ul', { class: 'visit-body-list' }, lines));
  }

  // ---------------------------------------------------------------------------
  // A link: #/share/<code>
  // ---------------------------------------------------------------------------
  let pending = null;
  function takeLink() {
    let hash = '';
    try { hash = location.hash || ''; } catch (e) { return false; }
    const m = LINK_RE.exec(hash);
    if (!m && !hash.startsWith('#/share/')) return false;
    pending = m ? m[1] : '';
    try { history.replaceState(null, '', location.pathname + location.search); } catch (e) { /* sandboxed frame */ }
    return true;
  }

  async function openPending() {
    if (pending == null || MOCK) return;
    const code = pending;
    pending = null;
    const dlg = $('#sheet-share');
    if (!dlg) return;
    const text = clear($('#share-question'));
    const problem = $('#share-error');
    clear(problem); problem.hidden = true;
    const accept = $('#share-accept');
    const fail = (err) => {
      text.textContent = '';
      problem.hidden = false;
      clear(problem).append(h('p', {}, !err ? BAD_LINK : err.status === 404 && err.detail === 'Not Found' ? SWITCHED_OFF : err.detail || BAD_LINK));
      accept.hidden = true;
    };
    accept.hidden = false;
    text.textContent = 'Checking the link…';
    sheets.open(dlg, null, $('[data-close]', dlg));
    let info;
    try { info = code ? await A.info(code) : null; } catch (err) { if (!err.handled) fail(err); return; }
    if (!info) { fail(null); return; }
    text.textContent = questionText(info);
    accept.dataset.code = code;
    setTimeout(() => accept.focus(), 30);
  }

  function setupSheet() {
    const dlg = $('#sheet-share');
    if (!dlg) return;
    sheets.setup(dlg);
    const accept = $('#share-accept');
    accept.addEventListener('click', async () => {
      const code = accept.dataset.code;
      if (!code || accept.disabled) return;
      accept.disabled = true;
      try {
        const person = await A.accept(code);
        delete accept.dataset.code;
        dlg.close();
        toast(`You can now see ${person.name || person.username}'s ${areasText(person.areas)}`, 'ok');
        openShared(person);
      } catch (err) {
        if (err.handled) return;
        const problem = $('#share-error');
        problem.hidden = false;
        clear(problem).append(h('p', {}, err.detail || BAD_LINK));
      } finally { accept.disabled = false; }
    });
    dlg.addEventListener('close', () => { delete accept.dataset.code; });
  }

  // A link followed while the app is already open: take it, and ask once someone is signed in.
  window.addEventListener('hashchange', () => {
    if (!takeLink()) return;
    if (state.me && state.view !== 'auth') openPending().catch((e) => console.warn('Share link:', e));
  });
  takeLink(); // the link the page was opened with: kept before any sign-in screen rewrites the address
  setupSheet();

  KH.sharing = { block, reads, renderDay, openShared, openPending, takeLink, areasText, lastLooked, lastsText, sharingLine, personLine, whoText,
    questionText, entryLine, AREAS, AREA_LABEL };
})();
