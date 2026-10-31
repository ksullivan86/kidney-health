/* Kidney Diet Log — the Care team (design notes 19, 25 and 29; app/sharing.py).

   * KH.sharing.block(): Settings → Care team. Invites for you (Accept, Decline), your Care team (the role, What they may do with
     a switch for each thing they may see and do, saved at once, and Remove), what waits
     for an answer (user name invites and links nobody has used, Cancel), Add someone (by user name, or a link shown once with
     Copy link), and the Care teams you are on (Open, Trends, Plan meals for a Care helper, Leave).
   * A link #/share/<code> is taken out of the address bar into memory when the page opens (so a sign-in screen does not lose
     it and it does not stay in the history), and once someone is signed in the share sheet asks "Accept?" before anything is
     saved. Nothing about the link is stored in the browser.
   * KH.sharing.reads(id): the read routes of one share, in the shape js/views/visit.js calls, so the Visit prep page shows the
     other person's summary. KH.sharing.renderDay() draws one day of their food log for the same page.

   Every request is a read except making, changing or ending a share, inviting, and answering an invite or a link; nothing
   here writes to anyone's log (a Care helper plans in js/views/careplan.js). All text goes in with h() children
   (textContent), never as HTML. The demo shows a sample Care team (js/mock/care.js). */
(() => {
  'use strict';
  const KH = window.KH;
  const { h, $, clear, request, toast, toastError, confirm, sheets, state } = KH;
  const { MOCK } = KH.flags;

  const AREAS = ['food', 'labs', 'body', 'symptoms', 'activity'];
  const AREA_LABEL = { food: 'food log', labs: 'lab results', body: 'weight and blood pressure', symptoms: 'symptoms',
    activity: 'activity and recovery' };
  const ROLES = ['viewer', 'care_helper', 'caregiver'];
  const ROLE_LABEL = { viewer: 'Viewer', care_helper: 'Care helper', caregiver: 'Caregiver', custom: 'Custom' };
  const ROLE_HINT = { viewer: 'can look at what you choose, and never change anything',
    care_helper: 'can also plan your meals and use your shopping list. They never change what you ate, your targets or your profile',
    caregiver: 'can also log food you ate. They never change your targets, labs, profile or medicines, or a low treatment' };
  // The four "Do" switches of a share (design note 29 §2). A role is a preset over them; any other mix shows as Custom.
  const SWITCHES = ['may_plan', 'may_log', 'may_use_saved_meals', 'may_suggest'];
  const PRESETS = {
    viewer: { may_plan: false, may_log: false, may_use_saved_meals: false, may_suggest: false },
    care_helper: { may_plan: true, may_log: false, may_use_saved_meals: false, may_suggest: false },
    caregiver: { may_plan: true, may_log: true, may_use_saved_meals: false, may_suggest: false },
  };
  const SWITCH_LABEL = { may_plan: 'Plan my meals and use my shopping list', may_log: 'Log food I ate', may_use_saved_meals: 'Use my saved meals',
    may_suggest: 'Suggest meals for me to add' };
  const SWITCH_NOUN = { may_plan: 'planning', may_log: 'logging food', may_use_saved_meals: 'saved meals', may_suggest: 'suggestions' };
  const NEEDS_FOOD = 'Planning, logging, saved meals and suggestions need your food log.';
  // How long a share lasts once accepted (POST /api/me/shares `days`; the server takes 1 to 365).
  const DAY_CHOICES = [['', 'Until I stop it'], ['7', '1 week'], ['30', '30 days'], ['90', '90 days'], ['365', '1 year']];
  const LINK_RE = /^#\/share\/([0-9a-f]{16}\.[A-Za-z0-9_-]{43})$/;
  const INTRO = 'Your Care team is family, a caregiver or a dietitian with an account on this server. A Viewer can look at the '
    + 'parts of your log you choose. A Care helper can also plan your meals and use your shopping list. A Caregiver can also log '
    + 'food you ate. You choose what each person may see and do, and you can change it or stop it at any time. Nobody on your '
    + 'Care team can change your targets, labs, profile or medicines, or a low treatment.';
  const OFF = 'The Care team is off on this server. Your admin can turn it on.';
  const OFF_ADMIN = 'The Care team is off on this server. You can turn it on in Server administration → Server settings → Care team, '
    + 'or with SHARING_ENABLED=true.';
  const BAD_LINK = 'That link does not work. Ask for a new one.';
  const SWITCHED_OFF = 'The Care team is turned off on this server. Ask your admin.';
  const SENT = (name) => `Invite sent to ${name}. If ${name} has an account here, they see it in their Settings → Care team. `
    + 'Nothing changes until they accept.';

  const A = {
    mine: () => request('GET', '/api/me/shares'),
    make: (areas, days, role) => request('POST', '/api/me/shares', { areas, days: days || null, role: role || 'viewer' }),
    invite: (username, areas, days, role) => request('POST', '/api/me/shares/invite', { username, areas, days: days || null, role }),
    cancelInvite: (id) => request('DELETE', `/api/me/shares/invites/${id}`),
    role: (id, role) => request('PUT', `/api/me/shares/${id}/role`, { role }),
    switches: (id, changes) => request('PUT', `/api/me/shares/${id}/switches`, changes),
    end: (id) => request('DELETE', `/api/me/shares/${id}`),
    people: () => request('GET', '/api/shared'),
    stop: (id) => request('DELETE', `/api/shared/${id}`),
    answer: (id, yes) => request('POST', `/api/shared/invites/${id}/${yes ? 'accept' : 'decline'}`),
    info: (code) => request('POST', '/api/shared/info', { code }),
    accept: (code) => request('POST', '/api/shared/accept', { code }),
  };

  /** The reads of share `id`, named as js/core.js names the person's own (KH.api), plus the day and the profile. */
  function reads(id) {
    const base = `/api/shared/${encodeURIComponent(id)}`;
    const qs = KH.util.qs;
    return {
      summary: (start, end) => request('GET', `${base}/log/summary?${qs({ start, end })}`),
      range: (start, end) => request('GET', `${base}/log/range?${qs({ start, end })}`),
      labs: (params = {}) => request('GET', `${base}/labs?${qs(params)}`),
      symptoms: (start, end) => request('GET', `${base}/symptoms?${qs({ start, end })}`),
      bodySummary: (date) => request('GET', `${base}/body/summary?${qs({ date })}`),
      bodyWeights: (start, end) => request('GET', `${base}/body/weights?${qs({ start, end })}`),
      bloodPressures: (start, end) => request('GET', `${base}/body/blood-pressure?${qs({ start, end })}`),
      activity: (start, end) => request('GET', `${base}/activity?${qs({ start, end })}`),
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
  function roleText(role) { return ROLE_LABEL[role] || ROLE_LABEL.viewer; }
  /** sharing.role_of: the role these switches match, or "custom". */
  function roleOf(sw) {
    return ROLES.find((r) => SWITCHES.every((k) => PRESETS[r][k] === !!(sw && sw[k]))) || 'custom';
  }
  /** What a share lets someone do, in words: "may: planning, logging food and suggestions" (null for a Viewer). */
  function doText(s) {
    const names = SWITCHES.filter((k) => s && s[k]).map((k) => SWITCH_NOUN[k]);
    if (!names.length) return null;
    return `may: ${names.length === 1 ? names[0] : `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}`}`;
  }
  /** Whether turning on `switches` (merged over the share) needs the food log added first. */
  function needsFood(s, switches) {
    const merged = { ...s, ...switches };
    return SWITCHES.some((k) => merged[k]) && !(s.areas || []).includes('food');
  }
  /** A helper's changes on the latest day: "changed your plan today: 3 added, 1 removed; logged 2 foods" (null when none). */
  function changesText(c, today) {
    if (!c) return null;
    const when = String(c.day) === today ? 'today' : `on ${fmtDay(c.day)}`;
    const parts = [['added', c.added], ['changed', c.changed], ['removed', c.removed]].filter(([, n]) => n > 0).map(([w, n]) => `${n} ${w}`);
    const out = [];
    if (parts.length) out.push(`changed your plan ${when}: ${parts.join(', ')}`);
    if (c.logged > 0) out.push(`logged ${c.logged} ${c.logged === 1 ? 'food' : 'foods'} you ate ${when}`);
    return out.length ? out.join('; ') : null;
  }
  function sharingLine(s, today) {
    const parts = [roleText(s.role), areasText(s.areas), doText(s), `since ${fmtDay(s.since)}`, untilText(s.until), lastLooked(s.last_viewed_at, today),
      changesText(s.helper_changes, today)].filter(Boolean);
    if (s.active === false) parts.push('their account is turned off');
    return parts.join(' · ');
  }
  function personLine(p) { return [roleText(p.role), areasText(p.areas), doText(p), `since ${fmtDay(p.since)}`, untilText(p.until)].filter(Boolean).join(' · '); }
  function whoText(p) { return p.name && p.name !== p.username ? `${p.name} (${p.username})` : p.username || p.name || ''; }
  /** What joining someone's Care team means, for a link or an invite. */
  function questionText(info) {
    const who = whoText(info);
    const lasts = info.days ? ` It ends by itself after ${info.days} ${info.days === 1 ? 'day' : 'days'}.` : '';
    const what = info.role === 'care_helper'
      ? 'as a Care helper. You can see this and plan their meals and use their shopping list, but not change what they ate, their targets or their profile. '
      : info.role === 'caregiver'
        ? 'as a Caregiver. You can see this, plan their meals, use their shopping list and log food they ate, but not change their targets, their profile or a low treatment. '
        : 'You can look, but not change anything. ';
    const helper = info.role === 'care_helper' || info.role === 'caregiver';
    return `${who} wants to add you to their Care team and share their ${areasText(info.areas)} with you${helper ? ', ' : '. '}${what}`
      + `${who} can stop this at any time, and so can you.${lasts}`;
  }
  /** One entry of a shared day as a line: "Banana, 1 serving (planned, added by Sam)". */
  function entryLine(e) {
    const n = Number(e.servings);
    const amount = e.grams != null ? `${Math.round(Number(e.grams))} g` : `${Number.isFinite(n) ? n : e.servings} ${n === 1 ? 'serving' : 'servings'}`;
    const tags = [e.status === 'planned' ? 'planned' : null, e.purpose === 'hypo' ? 'to treat a low' : null,
      e.added_by ? `added by ${e.added_by}` : null].filter(Boolean);
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

  /** Settings → Care team: the section's body (index.html #set-care holds the heading). */
  function block() {
    const body = h('div', { id: 'set-sharing', role: 'region', 'aria-labelledby': 'set-care-h' }, h('p', { class: 'muted small' }, 'Loading…'));
    load(body);
    return h('div', { class: 'sharing' }, body);
  }

  // Each Sharing block remembers its newest load and the link made there. Only the newest load draws. The new link stays on
  // screen through later loads (Stop sharing, Cancel, a list that could not load) until it is used or cancelled.
  const blocks = new WeakMap();
  async function load(body, made = null, focusSel = null) {
    if (!blocks.has(body)) blocks.set(body, { request: 0, made: null });
    const st = blocks.get(body);
    const req = ++st.request;
    if (made) st.made = made;
    let mine;
    let people = [];
    let invites = [];
    try {
      mine = await A.mine();
      if (mine.enabled) { const got = await A.people(); people = got.people || []; invites = got.invites || []; }
    } catch (err) {
      if (req !== st.request) return;
      clear(body).append(h('p', { class: 'form-error' }, `Could not load this: ${(err && (err.detail || err.message)) || 'unknown error'}`));
      if (st.made) body.append(linkBox(st.made, !!made)); // a new link is never lost because the list could not load
      return;
    }
    if (req !== st.request) return;
    if (st.made && mine.enabled && !mine.codes.some((c) => c.id === st.made.code.id)) st.made = null; // used or cancelled
    render(body, mine, people, invites, st.made, !!made);
    if (focusSel) { const el = $(focusSel, body); if (el) el.focus(); }
  }

  /** The switch is off: a person reads that their admin can turn it on; an admin reads where. */
  function offNote() {
    const admin = state.me && state.me.role === 'admin';
    const p = h('p', { class: 'hint', id: 'set-sharing-off' }, admin ? OFF_ADMIN : OFF);
    if (!admin || !KH.router) return p;
    const open = h('button', { class: 'btn secondary', type: 'button', id: 'set-care-open-admin' }, 'Open Server administration');
    open.addEventListener('click', () => KH.router.show('admin'));
    return h('div', {}, p, h('div', { class: 'settings-actions' }, open));
  }

  function render(body, mine, people, invites, made, fresh) {
    clear(body);
    if (!mine.enabled) { body.append(offNote()); return; }
    body.append(h('p', {}, INTRO));

    if (invites.length) body.append(invitesForMe(body, invites));

    body.append(h('h4', { class: 'settings-minor', id: 'set-care-team-h' }, 'Your Care team'));
    if (!mine.sharing.length) body.append(h('p', { class: 'muted small', id: 'set-sharing-none' }, 'Nobody yet.'));
    else {
      const ul = h('ul', { class: 'list device-list', id: 'set-sharing-list', 'aria-labelledby': 'set-care-team-h' });
      for (const s of mine.sharing) {
        const actions = h('div', { class: 'token-actions' });
        actions.append(roleSelect(body, s, actions));
        const stop = h('button', { class: 'btn secondary', type: 'button', 'aria-label': `Remove ${whoText(s)} from your Care team` }, 'Remove');
        stop.addEventListener('click', () => confirm.inline(actions, stop, {
          message: `Remove ${whoText(s)} from your Care team? They can no longer see any of your data or plan your meals.`,
          confirmText: 'Remove',
          onConfirm: async () => { await A.end(s.id); toast(`${s.name || s.username} is no longer on your Care team`, 'ok'); await load(body, null, '#set-care-invite-name'); return true; },
        }));
        actions.append(stop);
        ul.append(h('li', { class: 'device care-member' }, h('div', { class: 'device-main' }, h('span', { class: 'row-title' }, whoText(s)),
          h('span', { class: 'row-sub' }, sharingLine(s, today()))), actions, switchesBox(body, s)));
      }
      body.append(ul);
    }

    if ((mine.invites || []).length) {
      body.append(h('h4', { class: 'settings-minor', id: 'set-care-waiting-h' }, 'Waiting for an answer'));
      const ul = h('ul', { class: 'list device-list', id: 'set-care-invites', 'aria-labelledby': 'set-care-waiting-h' });
      for (const inv of mine.invites) {
        const cancel = button('Cancel', 'secondary', async () => {
          await A.cancelInvite(inv.id);
          toast('Invite cancelled', 'ok');
          await load(body, null, '#set-care-invite-name');
        }, { 'aria-label': `Cancel the invite to ${inv.username}` });
        ul.append(h('li', { class: 'device' }, h('div', { class: 'device-main' }, h('span', { class: 'row-title' }, inv.username),
          h('span', { class: 'row-sub' }, `${roleText(inv.role)} · ${areasText(inv.areas)} · ${lastsText(inv.days)} · the invite lapses ${fmtDay(inv.expires_at)}`)),
        h('div', { class: 'token-actions' }, cancel)));
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
          h('span', { class: 'row-sub' }, `${roleText(c.role)} · shares ${lastsText(c.days)} · the link works until ${fmtDay(c.expires_at)}`)), h('div', { class: 'token-actions' }, cancel)));
      }
      body.append(ul);
    }

    if (mine.sharing.length >= mine.max) {
      body.append(h('p', { class: 'hint' }, `Your Care team has ${mine.max} people, the most allowed. Remove someone to add another.`));
    } else {
      body.append(inviteForm(body), shareForm(body));
      if (made) body.append(linkBox(made, fresh));
    }

    body.append(h('h4', { class: 'settings-minor', id: 'set-shared-h' }, 'Care teams you are on'));
    if (!people.length) {
      body.append(h('p', { class: 'muted small', id: 'set-shared-none' }, 'You are not on anyone\'s Care team yet. When someone invites you, the invite shows here. '
        + 'When someone sends you a link, open it while you are signed in.'));
    } else {
      const ul = h('ul', { class: 'list device-list', id: 'set-shared-list', 'aria-labelledby': 'set-shared-h' });
      for (const p of people) {
        const actions = h('div', { class: 'token-actions' });
        const open = button('Open', 'primary', () => openShared(p), { 'aria-label': `Open what ${whoText(p)} shares with you` });
        const trends = button('Trends', 'secondary', () => openTrends(p), { 'aria-label': `Open ${whoText(p)}'s trends` });
        const helpLabel = p.may_plan ? 'Plan meals' : p.may_log ? 'Log food' : 'Suggest a meal';
        const plan = KH.carePlan && KH.carePlan.canHelp(p)
          ? button(helpLabel, 'secondary', () => KH.carePlan.open(p), { 'aria-label': `${helpLabel} for ${whoText(p)}` }) : null;
        const stop = h('button', { class: 'btn secondary', type: 'button', 'aria-label': `Leave ${whoText(p)}'s Care team` }, 'Leave');
        stop.addEventListener('click', () => confirm.inline(actions, stop, {
          message: `Leave ${whoText(p)}'s Care team? They would have to invite you again.`,
          confirmText: 'Leave',
          onConfirm: async () => { await A.stop(p.id); toast(`You left ${p.name || p.username}'s Care team`, 'ok'); await load(body, null, '#set-shared-h'); return true; },
        }));
        actions.append(open, trends, plan, stop);
        ul.append(h('li', { class: 'device' }, h('div', { class: 'device-main' }, h('span', { class: 'row-title' }, whoText(p)),
          h('span', { class: 'row-sub' }, personLine(p))), actions));
      }
      body.append(ul);
    }
  }

  /** Invites for the signed-in person, each with Accept and Decline. */
  function invitesForMe(body, invites) {
    const box = h('div', { class: 'care-invites-for-me' }, h('h4', { class: 'settings-minor', id: 'set-care-for-me-h' }, 'Invites for you'));
    const ul = h('ul', { class: 'list device-list', id: 'set-care-for-me', 'aria-labelledby': 'set-care-for-me-h' });
    for (const inv of invites) {
      const yes = button('Accept', 'primary', async () => {
        const person = await A.answer(inv.id, true);
        toast(`You joined ${person.name || person.username}'s Care team`, 'ok');
        await load(body, null, '#set-shared-h');
      }, { 'aria-label': `Accept the invite from ${whoText(inv)}` });
      const no = button('Decline', 'secondary', async () => {
        await A.answer(inv.id, false);
        toast('Invite declined', 'ok');
        await load(body, null, '#set-care-team-h');
      }, { 'aria-label': `Decline the invite from ${whoText(inv)}` });
      ul.append(h('li', { class: 'device' }, h('div', { class: 'device-main' }, h('span', { class: 'row-title' }, whoText(inv)),
        h('span', { class: 'row-sub' }, questionText(inv))), h('div', { class: 'token-actions' }, yes, no)));
    }
    box.append(ul);
    return box;
  }

  /** The role of someone on your Care team, changed in place. A role is a preset of the switches; "Custom" shows when the switches
      match none and is never chosen. A Care helper or Caregiver always sees the food log, so it is added (said first). */
  function roleSelect(body, s, actions) {
    const id = `set-care-role-${s.id}`;
    const select = h('select', { id, 'aria-label': `Role of ${whoText(s)}` }, ...ROLES.map((r) => h('option', { value: r }, ROLE_LABEL[r])),
      h('option', { value: 'custom', disabled: true, hidden: s.role !== 'custom' || null }, ROLE_LABEL.custom));
    select.value = s.role || 'viewer';
    const apply = async (role) => {
      select.disabled = true;
      try {
        const got = await A.role(s.id, role);
        toast(`${s.name || s.username} is now a ${roleText(got.role)}`, 'ok');
        await load(body, null, `#${id}`);
      } catch (err) { select.value = s.role || 'viewer'; if (!err.handled) toastError(err); } finally { if (document.contains(select)) select.disabled = false; }
      return true;
    };
    select.addEventListener('change', () => {
      const role = select.value;
      if (role !== 'viewer' && !(s.areas || []).includes('food')) {
        confirm.inline(actions, select, {
          message: `A ${ROLE_LABEL[role]} sees your food log so they can help with meals. Share your food log with ${whoText(s)} and make them a ${ROLE_LABEL[role]}?`,
          confirmText: `Make ${ROLE_LABEL[role]}`,
          onConfirm: () => apply(role),
          onCancel: () => { select.value = s.role || 'viewer'; },
        });
        return;
      }
      apply(role);
    });
    return select;
  }

  /** What someone on your Care team may see and do: one switch each, saved at once (PUT /api/me/shares/{id}/switches). Turning on
      a "Do" switch while the food log is not shared asks first, then shares it. */
  function switchesBox(body, s) {
    const box = h('details', { class: 'care-switches', id: `set-care-switches-${s.id}` },
      h('summary', {}, `What ${s.name || s.username} may see and do`));
    const save = async (changes, focusId) => {
      try {
        const got = await A.switches(s.id, changes);
        toast(`Saved. ${s.name || s.username} is now ${got.role === 'custom' ? 'on a custom set of switches' : `a ${roleText(got.role)}`}.`, 'ok');
      } catch (err) { if (!err.handled) toastError(err); }
      await load(body, null, `#${focusId}`);
      const again = $(`#set-care-switches-${s.id}`, body);
      if (again) again.open = true;
    };
    const row = (id, label, checked, onChange) => {
      const cb = h('input', { type: 'checkbox', id });
      cb.checked = !!checked;
      cb.addEventListener('change', () => onChange(cb));
      return h('label', { class: 'check', for: id }, cb, ` ${label}`);
    };
    const see = AREAS.map((a) => {
      const id = `set-care-${s.id}-see-${a}`;
      const locked = a === 'food' && SWITCHES.some((k) => s[k]);
      const label = row(id, `My ${AREA_LABEL[a]}`, (s.areas || []).includes(a), (cb) => {
        const areas = AREAS.filter((x) => (x === a ? cb.checked : (s.areas || []).includes(x)));
        if (!areas.length) { cb.checked = true; toast('Leave at least one thing they can see, or remove them from your Care team.'); return; }
        save({ areas }, id);
      });
      if (locked) { const cb = $('input', label); cb.disabled = true; label.append(h('span', { class: 'hint' }, ` (${NEEDS_FOOD.replace(' need your food log.', ' need it')})`)); }
      return label;
    });
    const doRows = SWITCHES.map((k) => {
      const id = `set-care-${s.id}-${k.replace(/_/g, '-')}`;
      const label = row(id, SWITCH_LABEL[k], s[k], (cb) => {
        const change = { [k]: cb.checked };
        if (cb.checked && needsFood(s, change)) {
          confirm.inline(label, cb, {
            message: `${NEEDS_FOOD} Share your food log with ${whoText(s)}?`,
            confirmText: 'Share and turn on',
            tone: 'primary',
            onConfirm: () => { save(change, id); return true; },
            onCancel: () => { cb.checked = false; },
          });
          return;
        }
        save(change, id);
      });
      return label;
    });
    box.append(h('fieldset', {}, h('legend', {}, 'They may see'), see),
      h('fieldset', {}, h('legend', {}, 'They may do'), doRows),
      h('p', { class: 'hint' }, 'Each change is saved at once. Nobody on your Care team can change your targets, labs, profile or medicines, or a low treatment.'));
    return box;
  }

  /** The parts of the form both ways of adding someone use: the role, what they see, how long. `prefix` keeps the ids apart. */
  function choices(prefix) {
    const roleName = `${prefix}-role`;
    const roles = ROLES.map((r) => {
      const radio = h('input', { type: 'radio', name: roleName, id: `${prefix}-role-${r}`, value: r });
      radio.checked = r === 'viewer';
      return h('label', { class: 'check', for: `${prefix}-role-${r}` }, radio, ` ${ROLE_LABEL[r]}: ${ROLE_HINT[r]}`);
    });
    const boxes = AREAS.map((a) => {
      const id = `${prefix}-${a}`;
      const box = h('input', { type: 'checkbox', id, value: a });
      box.checked = true;
      return h('label', { class: 'check', for: id }, box, ` My ${AREA_LABEL[a]}`);
    });
    const lasts = h('select', { id: `${prefix}-days` }, ...DAY_CHOICES.map(([v, label]) => h('option', { value: v }, label)));
    const nodes = [h('fieldset', {}, h('legend', {}, 'Role'), roles), h('fieldset', {}, h('legend', {}, 'What they can see'), boxes),
      h('label', { class: 'label', for: `${prefix}-days` }, 'For how long'), lasts];
    const read = (form) => {
      const role = (ROLES.find((r) => $(`#${prefix}-role-${r}`, form).checked)) || 'viewer';
      const areas = AREAS.filter((a) => $(`#${prefix}-${a}`, form).checked);
      return { role, areas: role !== 'viewer' && !areas.includes('food') ? ['food', ...areas] : areas, days: Number(lasts.value) || null };
    };
    return { nodes, read };
  }

  /** Add someone who already has an account here, by user name. The answer is the same whether or not the name is an account. */
  function inviteForm(body) {
    const err = h('div', { class: 'form-error', role: 'alert' });
    const done = h('p', { class: 'hint', id: 'set-care-sent', role: 'status' });
    const name = h('input', { id: 'set-care-invite-name', type: 'text', autocomplete: 'off', autocapitalize: 'none', spellcheck: 'false', maxlength: 255 });
    const c = choices('set-care');
    const send = h('button', { class: 'btn primary', type: 'submit', id: 'set-care-invite' }, 'Send invite');
    const form = h('form', { class: 'settings-form sharing-form', id: 'set-care-invite-form', novalidate: true },
      h('h4', { class: 'settings-minor' }, 'Add someone'),
      h('label', { class: 'label', for: 'set-care-invite-name' }, 'Their user name on this server'), name, ...c.nodes,
      h('span', { class: 'hint' }, 'They see your invite in their Settings → Care team. Nothing changes until they accept.'),
      h('div', { class: 'settings-actions' }, send), done, err);
    sheets.onSubmit(form, async (e) => {
      e.preventDefault();
      if (send.disabled) return;
      clear(err); done.textContent = '';
      const username = name.value.trim();
      const { role, areas, days } = c.read(form);
      if (!username) { err.append(h('p', {}, 'Type their user name.')); return; }
      if (!areas.length) { err.append(h('p', {}, 'Tick at least one thing they can see.')); return; }
      send.disabled = true;
      try {
        const inv = await A.invite(username, areas, days, role);
        await load(body, null, '#set-care-invite-name');
        const again = $('#set-care-sent', body);
        if (again) again.textContent = SENT(inv.username);
      } catch (e2) {
        if (e2.cancelled || e2.handled) return;
        err.append(h('p', {}, e2.detail || e2.message || 'No invite was sent. Try again.'));
      } finally { if (document.contains(send)) send.disabled = false; }
    });
    return form;
  }

  /** For someone without a user name you know: a link shown once. */
  function shareForm(body) {
    const err = h('div', { class: 'form-error', role: 'alert' });
    const c = choices('set-share');
    const make = h('button', { class: 'btn secondary', type: 'submit', id: 'set-sharing-make' }, 'Make a link');
    const form = h('form', { class: 'settings-form sharing-form', id: 'set-share-form', novalidate: true },
      h('details', { class: 'care-link' }, h('summary', {}, 'Make a link instead'),
        ...c.nodes,
        h('span', { class: 'hint' }, 'You get a link to send them. It works once, for 7 days. They need their own account on this server.'),
        h('div', { class: 'settings-actions' }, make), err));
    sheets.onSubmit(form, async (e) => {
      e.preventDefault();
      if (make.disabled) return;
      clear(err);
      const { role, areas, days } = c.read(form);
      if (!areas.length) { err.append(h('p', {}, 'Tick at least one thing to share.')); return; }
      make.disabled = true;
      try {
        const made = await A.make(areas, days, role);
        await load(body, made);
      } catch (e2) {
        if (e2.cancelled || e2.handled) return;
        err.append(h('p', {}, e2.detail || e2.message || 'No link was made. Try again.'));
      } finally { if (document.contains(make)) make.disabled = false; }
    });
    return form;
  }

  /** The new link with Copy link. `fresh`: it was just made, so the link gets the focus. */
  function linkBox(made, fresh) {
    const id = 'set-share-link';
    const input = h('input', { id, type: 'text', class: 'link-input', readonly: true, value: made.link, spellcheck: 'false', autocomplete: 'off' });
    const copy = button('Copy link', 'primary', async () => {
      try { await navigator.clipboard.writeText(made.link); toast('Link copied', 'ok'); } catch (e) {
        input.focus(); input.select();
        toast('Select the link and copy it (Ctrl+C, or touch and hold on a phone).');
      }
    });
    if (fresh) setTimeout(() => { if (document.contains(input)) { input.focus(); input.select(); } }, 30);
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
  /** The person's Trends charts, read-only (js/views/trends.js shared mode). */
  function openTrends(person) {
    if (KH.views.trends && KH.views.trends.openShared) KH.views.trends.openShared({ ...person, reads: reads(person.id) });
  }

  /** One day of a shared food log into `box`: the entries by meal and the day's totals against the targets. */
  const dayRequests = new WeakMap();
  async function renderDay(box, rd, date) {
    const request = {};
    dayRequests.set(box, request);
    clear(box).append(h('p', { class: 'muted' }, 'Loading…'));
    let day;
    try { day = await rd.day(date); } catch (err) {
      if (dayRequests.get(box) !== request) return;
      clear(box).append(h('p', { class: 'visit-note visit-problem' }, `This day could not be loaded${err && err.detail ? ` (${err.detail})` : ''}.`),
        h('button', { class: 'btn secondary', type: 'button', onclick: () => renderDay(box, rd, date) }, 'Retry'));
      return;
    }
    if (dayRequests.get(box) !== request) return;
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
  let questionRequest = 0;
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
    const req = ++questionRequest;
    const current = () => req === questionRequest && dlg.open;
    const text = clear($('#share-question'));
    const problem = $('#share-error');
    clear(problem); problem.hidden = true;
    const accept = $('#share-accept');
    delete accept.dataset.code;
    accept.hidden = true;
    accept.disabled = false;
    const fail = (err) => {
      text.textContent = '';
      problem.hidden = false;
      clear(problem).append(h('p', {}, !err ? BAD_LINK : err.status === 404 && err.detail === 'Not Found' ? SWITCHED_OFF : err.detail || BAD_LINK));
      accept.hidden = true;
    };
    text.textContent = 'Checking the link…';
    sheets.open(dlg, null, $('[data-close]', dlg));
    let info;
    try { info = code ? await A.info(code) : null; } catch (err) { if (current() && !err.handled) fail(err); return; }
    if (!current()) return;
    if (!info) { fail(null); return; }
    text.textContent = questionText(info);
    accept.dataset.code = code;
    accept.hidden = false;
    setTimeout(() => { if (current()) accept.focus(); }, 30);
  }

  function setupSheet() {
    const dlg = $('#sheet-share');
    if (!dlg) return;
    sheets.setup(dlg);
    const accept = $('#share-accept');
    accept.addEventListener('click', async () => {
      const code = accept.dataset.code;
      const req = questionRequest;
      const current = () => req === questionRequest && dlg.open && accept.dataset.code === code;
      if (!code || accept.disabled || accept.hidden || !dlg.open) return;
      accept.disabled = true;
      try {
        const person = await A.accept(code);
        if (!current()) return;
        delete accept.dataset.code;
        dlg.close();
        toast(`You joined ${person.name || person.username}'s Care team as a ${roleText(person.role)}`, 'ok');
        openShared(person);
      } catch (err) {
        if (!current() || err.handled) return;
        const problem = $('#share-error');
        problem.hidden = false;
        clear(problem).append(h('p', {}, err.detail || BAD_LINK));
      } finally { if (req === questionRequest) accept.disabled = false; }
    });
    dlg.addEventListener('close', () => {
      if (dlg.open) return; // a queued close event can arrive after this dialog has reopened
      ++questionRequest;
      delete accept.dataset.code;
      accept.hidden = true;
    });
  }

  // A link followed while the app is already open: take it, and ask once someone is signed in.
  window.addEventListener('hashchange', () => {
    if (!takeLink()) return;
    if (state.me && state.view !== 'auth') openPending().catch((e) => console.warn('Share link:', e));
  });
  takeLink(); // the link the page was opened with: kept before any sign-in screen rewrites the address
  setupSheet();

  KH.sharing = { block, reads, renderDay, openShared, openPending, takeLink, areasText, lastLooked, lastsText, sharingLine, personLine, whoText,
    questionText, entryLine, roleText, roleOf, doText, needsFood, changesText, people: A.people, AREAS, AREA_LABEL, ROLES, ROLE_LABEL, SWITCHES, PRESETS };
})();
