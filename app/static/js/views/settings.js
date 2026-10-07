/* Kidney Diet Log — Settings view (note 07 §4.17; note 02 R10 for This device).

   Sections: Account (name, password, signed-in devices, export, delete, sign out), Preferences
   (theme, week start, units), Food data (USDA key, Open Food Facts), AI ideas (filled by M2),
   This device (install, offline, storage; completed by js/pwa.js in the installed app), Admin
   (admins only: people and invites, server settings, shared keys, usage, activity, about this
   server) and About & privacy.

   Every setting shows where its value comes from (env lock / your choice / admin / default) and
   whether it is locked. Keys are write-only: the page never receives a key and never shows one;
   a new key goes from an empty password field straight to PUT and the field is cleared.

   Opened from the header gear and from Profile (#settings). Labels, help texts and choices of
   the settings come from js/engine/settings.js (the twin of app/settings_registry.py). In the
   demo and the preview the same requests go to js/mock/auth.js and js/mock/settings.js. */
(() => {
  'use strict';
  const KH = window.KH;
  const { h, s, $, $$, clear, api, request, download, state, toast, toastError, router, sheets, confirm } = KH;
  const { MOCK, PREVIEW } = KH.flags;
  const REG = KH.settings;

  // Kept equal to APP_VERSION in app/main.py (tests/test_settings_ui.py).
  const APP_VERSION = '0.3.0';

  const A = {
    sessions: () => request('GET', '/api/me/sessions'),
    revokeSession: (id) => request('DELETE', `/api/me/sessions/${encodeURIComponent(id)}`),
    revokeOthers: () => request('POST', '/api/me/sessions/revoke-others'),
    changePassword: (b) => request('POST', '/api/me/password', b),
    deleteMe: (b) => request('DELETE', '/api/me', b),
    activity: () => request('GET', '/api/me/activity?limit=20'),
    users: () => request('GET', '/api/admin/users'),
    createUser: (b) => request('POST', '/api/admin/users', b),
    updateUser: (id, b) => request('PATCH', `/api/admin/users/${id}`, b),
    deleteUser: (id, b) => request('DELETE', `/api/admin/users/${id}`, b),
    resetLink: (id) => request('POST', `/api/admin/users/${id}/reset-link`),
    revokeResetLink: (id) => request('DELETE', `/api/admin/users/${id}/reset-link`),
    revokeUser: (id) => request('POST', `/api/admin/users/${id}/revoke-sessions`),
    invites: () => request('GET', '/api/admin/invites'),
    createInvite: (b) => request('POST', '/api/admin/invites', b),
    deleteInvite: (id) => request('DELETE', `/api/admin/invites/${encodeURIComponent(id)}`),
    adminSettings: () => request('GET', '/api/admin/settings'),
    updateAdminSettings: (b) => request('PATCH', '/api/admin/settings', b),
    adminKeys: () => request('GET', '/api/admin/keys'),
    setAdminKey: (p, b) => request('PUT', `/api/admin/keys/${encodeURIComponent(p)}`, b),
    deleteAdminKey: (p) => request('DELETE', `/api/admin/keys/${encodeURIComponent(p)}`),
    usage: () => request('GET', '/api/admin/usage?days=30'),
    audit: (before) => request('GET', `/api/admin/audit?limit=30${before ? `&before=${before}` : ''}`),
    about: () => request('GET', '/api/admin/about'),
  };

  // Last answers, so one part can re-render without fetching everything again.
  const cache = { mySettings: null, myKeys: null, users: null, adminSettings: null };
  let seq = 0;
  const uid = (p) => `${p}-${++seq}`;

  // ---------------------------------------------------------------------------
  // Formatting
  // ---------------------------------------------------------------------------
  function toDate(iso) { const d = new Date(iso); return Number.isNaN(d.getTime()) ? null : d; }
  function fmtDate(iso) {
    const d = toDate(iso); if (!d) return '';
    const opts = { month: 'short', day: 'numeric' };
    if (d.getFullYear() !== new Date().getFullYear()) opts.year = 'numeric';
    return d.toLocaleDateString('en-US', opts);
  }
  function fmtDateTime(iso) {
    const d = toDate(iso); if (!d) return '';
    return `${fmtDate(iso)}, ${d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' })}`;
  }
  function relTime(iso) {
    const d = toDate(iso); if (!d) return '';
    const sec = Math.round((Date.now() - d.getTime()) / 1000);
    if (sec < 90) return 'just now';
    if (sec < 3600) return `${Math.round(sec / 60)} min ago`;
    if (sec < 86400) return `${Math.round(sec / 3600)} h ago`;
    const days = Math.round(sec / 86400);
    return days === 1 ? 'yesterday' : days < 30 ? `${days} days ago` : fmtDate(iso);
  }
  function fmtBytes(n) {
    if (!Number.isFinite(n)) return '';
    if (n < 1024 * 1024) return `${Math.max(1, Math.round(n / 1024))} KB`;
    if (n < 1024 ** 3) return `${(n / 1024 / 1024).toFixed(1)} MB`;
    return `${(n / 1024 ** 3).toFixed(1)} GB`;
  }
  function deviceName(ua) {
    const u = String(ua || '');
    if (!u) return 'Unknown device';
    const os = /iPhone/.test(u) ? 'iPhone' : /iPad/.test(u) ? 'iPad' : /Android/.test(u) ? 'Android' : /Windows/.test(u) ? 'Windows'
      : /Mac OS X|Macintosh/.test(u) ? 'Mac' : /CrOS/.test(u) ? 'ChromeOS' : /Linux/.test(u) ? 'Linux' : '';
    const br = /Edg\//.test(u) ? 'Edge' : /OPR\//.test(u) ? 'Opera' : /Firefox\/|FxiOS/.test(u) ? 'Firefox' : /CriOS|Chrome\//.test(u) ? 'Chrome'
      : /Safari\//.test(u) ? 'Safari' : /curl|python|httpx/i.test(u) ? 'A script' : 'Browser';
    return os ? `${br} on ${os}` : br;
  }
  const ROLE_LABEL = { admin: 'Admin', user: 'Member' };
  const STATUS_LABEL = { active: 'Active', disabled: 'Disabled', locked: 'Locked', pending_setup: 'Waiting for a password' };

  // ---------------------------------------------------------------------------
  // Small building blocks
  // ---------------------------------------------------------------------------
  function lockIcon() {
    return s('svg', { class: 'lock-icon', viewBox: '0 0 24 24', 'aria-hidden': 'true', focusable: 'false' },
      s('rect', { x: 5, y: 10.5, width: 14, height: 10, rx: 2, fill: 'none', stroke: 'currentColor', 'stroke-width': 2 }),
      s('path', { d: 'M8 10.5V8a4 4 0 0 1 8 0v2.5', fill: 'none', stroke: 'currentColor', 'stroke-width': 2 }));
  }
  // "Set by the server (OFF_ENABLED)" / "Your choice" / "Set by your admin" / "Default".
  function sourceText(source, env, { admin = false } = {}) {
    if (source === 'env') return `Set by the server (${env || 'environment'}), locked`;
    if (admin && source === 'instance') return 'Set here';
    if (admin && source === 'default') return 'App default';
    return REG.SOURCE_LABEL[source] || source || '';
  }
  function sourceLine(source, env, opts = {}) {
    const el = h('span', { class: `setting-source src-${source || 'default'}`, id: opts.id || null });
    if (source === 'env') el.append(lockIcon());
    el.append(h('span', {}, sourceText(source, env, opts)));
    return el;
  }
  function kv(rows) {
    return h('dl', { class: 'kv' }, rows.filter(Boolean).map(([k, v]) => h('div', { class: 'kv-row' }, h('dt', {}, k), h('dd', {}, v))));
  }
  function statusMsg(id) { return h('p', { class: 'status-msg', id, role: 'status', 'aria-live': 'polite' }); }
  function formError() { return h('div', { class: 'form-error', role: 'alert' }); }
  function showFormError(box, err) {
    clear(box);
    if (!err) return;
    const message = typeof err === 'string' ? err : (err.detail || err.message || 'Something went wrong');
    box.append(h('p', {}, message));
    const more = ((err.data && err.data.problems) || []).filter((p) => p !== message);
    if (more.length) box.append(h('ul', {}, more.map((p) => h('li', {}, p))));
  }
  function note(kind, ...children) { return h('div', { class: `settings-note ${kind}`, role: 'note' }, ...children); }
  function subtitle(text, id) { return h('h3', { class: 'settings-subtitle', id: id || null }, text); }
  function failed(err) {
    if (err && err.cancelled) return h('p', { class: 'muted small' }, 'Not loaded: the password prompt was closed.');
    return h('p', { class: 'form-error' }, `Could not load this: ${(err && (err.detail || err.message)) || 'unknown error'}`);
  }
  function loading() { return h('p', { class: 'muted small' }, 'Loading…'); }
  // A button that runs fn once at a time; errors become a toast unless already handled.
  function action(label, cls, fn, attrs = {}) {
    const btn = h('button', { class: `btn ${cls}`, type: 'button', ...attrs }, label);
    btn.addEventListener('click', async () => {
      if (btn.disabled) return;
      btn.disabled = true;
      try { await fn(btn); } catch (err) { if (!err.handled) toastError(err); } finally { if (document.contains(btn)) btn.disabled = false; }
    });
    return btn;
  }
  function pwField(id, label, autocomplete, hint) {
    const hintId = hint ? `${id}-hint` : null;
    return h('div', { class: 'field' },
      h('label', { for: id }, label),
      h('div', { class: 'pw-wrap' },
        h('input', { id, type: 'password', autocomplete, autocapitalize: 'none', autocorrect: 'off', spellcheck: 'false', maxlength: autocomplete === 'new-password' ? 128 : 1024, 'aria-describedby': hintId }),
        h('button', { class: 'pw-toggle', type: 'button', 'aria-controls': id, 'aria-pressed': 'false' }, 'Show')),
      hint ? h('span', { class: 'hint', id: hintId }, hint) : null);
  }
  function minPw() { return Number((state.authStatus || {}).password_min_length) || 15; }
  function newPwHint() { return `At least ${minPw()} characters. A short sentence works well; no symbols needed.`; }
  function newPwProblem(pw) {
    const n = Array.from(pw).length;
    if (n < minPw()) return `Use at least ${minPw()} characters. A short sentence or three or four unrelated words works well.`;
    if (n > 128) return 'Use at most 128 characters.';
    return null;
  }
  async function copyText(text, input) {
    // A frame without clipboard-write would reject (and log an error): check the policy first,
    // as the CSV sheet does, then fall back to selecting the text.
    const policy = document.permissionsPolicy || document.featurePolicy;
    let allowed = true;
    try { allowed = !policy || typeof policy.allowsFeature !== 'function' || policy.allowsFeature('clipboard-write'); } catch (e) { allowed = true; }
    try { if (allowed && navigator.clipboard && window.isSecureContext) { await navigator.clipboard.writeText(text); return true; } } catch (e) { /* fall back */ }
    try { input.focus(); input.select(); if (document.execCommand && document.execCommand('copy')) return true; } catch (e) { /* fall back */ }
    try { input.focus(); input.select(); } catch (e) { /* ignore */ }
    return false;
  }
  // A link shown once (invite, account setup, password reset), with Copy.
  function linkBox(url, lines) {
    const id = uid('link');
    const input = h('input', { id, type: 'text', class: 'link-input', readonly: true, value: url, spellcheck: 'false', autocomplete: 'off' });
    const copy = action('Copy link', 'primary', async () => {
      if (await copyText(url, input)) toast('Link copied', 'ok');
      else toast('Select the link and copy it (Ctrl+C, or touch and hold on a phone).');
    });
    const box = h('div', { class: 'link-box', role: 'group', 'aria-label': 'Link to send' },
      h('label', { for: id, class: 'label' }, 'Link (shown only now)'),
      h('div', { class: 'link-row' }, input, copy),
      lines.map((t) => h('p', { class: 'hint' }, t)),
      MOCK ? h('p', { class: 'hint' }, 'Demo: this is an example link; it does not open anything.') : null);
    setTimeout(() => { if (document.contains(input)) { input.focus(); input.select(); } }, 30);
    return box;
  }
  function selectEl(id, options, value, attrs = {}) {
    return h('select', { id, ...attrs }, options.map(([v, label]) => {
      const o = h('option', { value: v }, label);
      if (String(v) === String(value)) o.selected = true;
      return o;
    }));
  }

  // ---------------------------------------------------------------------------
  // Key widget (note 07 §4.17), the same for a person's own key and the shared key
  // ---------------------------------------------------------------------------
  function validateKeyText(value) {
    if (value.length < 8 || value.length > 512) return 'The key must be 8 to 512 characters long.';
    for (const ch of value) { const c = ch.codePointAt(0); if (c < 33 || c > 126) return 'The key must be printable ASCII without spaces. Copy it again without spaces or line breaks.'; }
    return null;
  }
  function keyStateText(st) {
    if (!st || !st.set) return 'Not set';
    if (st.status === 'unreadable') return 'Please enter your key again: the server can no longer read the stored key.';
    const parts = ['Set'];
    if (st.last4) parts.push(`ends in ${st.last4}`);
    if (st.updated_at) parts.push(`updated ${fmtDate(st.updated_at)}`);
    return parts.join(' · ');
  }
  function testResultText(result, providerLabel) {
    if (result === 'ok') return `Key saved and working: ${providerLabel} accepted it.`;
    if (result === 'rejected') return `Saved, but ${providerLabel} rejected this key. Copy it again and replace it, or remove it.`;
    if (result === 'unreachable') return `Saved. ${providerLabel} could not be reached to check the key; it will be tried on your next lookup.`;
    return MOCK ? 'Saved. The demo never contacts USDA, so the key was not checked.' : 'Saved. The key was not checked.';
  }
  // opts: { name, providerLabel, status, locked, lockedText, disabledText, removeText, message, onSave(key, test),
  //         onSaved(result, message) (re-renders the widget, passing `message` on), onRemove() }
  function keyWidget(opts) {
    const idBase = uid('key');
    const st = opts.status || { set: false };
    const wrap = h('div', { class: 'key-widget', role: 'group', 'aria-labelledby': `${idBase}-name` });
    const stateLine = h('p', { class: `key-state${st.status === 'unreadable' ? ' warn' : ''}`, id: `${idBase}-state` }, keyStateText(st));
    wrap.append(h('div', { class: 'key-head' }, h('span', { class: 'key-name', id: `${idBase}-name` }, opts.name), stateLine));
    if (opts.locked) {
      wrap.append(h('p', { class: 'setting-source src-env' }, lockIcon(), h('span', {}, opts.lockedText || 'Set by the server, locked')));
      return wrap;
    }
    if (opts.disabledText) { wrap.append(h('p', { class: 'hint' }, opts.disabledText)); return wrap; }
    const msg = statusMsg(`${idBase}-msg`);
    if (opts.message) msg.textContent = opts.message;
    const err = formError();
    const actions = h('div', { class: 'key-actions' });
    const inputId = `${idBase}-input`;
    const input = h('input', { id: inputId, type: 'password', autocomplete: 'off', autocapitalize: 'none', autocorrect: 'off', spellcheck: 'false',
      maxlength: 512, 'aria-describedby': `${inputId}-hint`, class: 'key-input' });
    const editor = h('div', { class: 'key-editor', hidden: true },
      h('div', { class: 'field' },
        h('label', { for: inputId }, st.set ? 'New key' : 'Key'),
        h('div', { class: 'pw-wrap' }, input, h('button', { class: 'pw-toggle', type: 'button', 'aria-controls': inputId, 'aria-pressed': 'false' }, 'Show')),
        h('span', { class: 'hint', id: `${inputId}-hint` }, 'Paste the key. It is stored encrypted on the server and never shown again, to you or anyone else.')),
      err);
    const close = () => { input.value = ''; input.type = 'password'; editor.hidden = true; actions.hidden = false; clear(err); };
    const save = async (test, btn) => {
      const value = input.value.trim();
      const problem = value ? validateKeyText(value) : 'Paste the key first.';
      if (problem) { showFormError(err, problem); input.focus(); return; }
      clear(err);
      btn.textContent = test ? 'Testing…' : 'Saving…';
      try {
        const res = await opts.onSave(value, test);
        input.value = '';
        msg.textContent = test || (res && res.test) ? testResultText(res && res.test, opts.providerLabel) : 'Key saved.';
        if (opts.onSaved) await opts.onSaved(res, msg.textContent);
      } catch (e) {
        btn.textContent = test ? 'Test and save' : 'Save';
        if (e.cancelled) return;
        showFormError(err, e);
        input.focus();
      }
    };
    const testBtn = action('Test and save', 'primary', (b) => save(true, b));
    const saveBtn = action('Save', 'secondary', (b) => save(false, b));
    const cancelBtn = h('button', { class: 'btn secondary', type: 'button' }, 'Cancel');
    cancelBtn.addEventListener('click', () => { close(); (actions.querySelector('button') || stateLine).focus(); });
    editor.append(h('div', { class: 'key-editor-actions' }, testBtn, saveBtn, cancelBtn));
    input.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); testBtn.click(); } });
    const open = h('button', { class: 'btn secondary', type: 'button' }, st.set ? 'Replace' : (opts.addText || 'Add a key'));
    open.addEventListener('click', () => { editor.hidden = false; actions.hidden = true; clear(msg); input.focus(); });
    actions.append(open);
    if (st.set) {
      const remove = h('button', { class: 'btn danger', type: 'button' }, 'Remove');
      remove.addEventListener('click', () => confirm.inline(actions, remove, {
        message: opts.removeText || `Remove this ${opts.providerLabel} key?`,
        confirmText: 'Remove',
        onConfirm: async () => { await opts.onRemove('Key removed.'); return true; },
      }));
      actions.append(remove);
    }
    wrap.append(actions, editor, msg);
    KH.auth.setupPwToggles(wrap);
    return wrap;
  }

  // ---------------------------------------------------------------------------
  // Section: Account
  // ---------------------------------------------------------------------------
  function authMode() { return (state.authStatus || {}).auth_mode || 'local'; }
  function hasLocalPassword() { return authMode() === 'local' && state.me && state.me.auth_source === 'local'; }

  function renderAccount() {
    const me = state.me;
    const body = $('#set-account-body');
    clear(body);
    if (!me) return;
    const none = authMode() === 'none';
    if (none) {
      body.append(note('danger', h('p', {}, h('strong', {}, 'No sign-in. '), 'This server runs without accounts (AUTH_MODE=none): anyone who can open this page can see and change this data. Your admin can turn sign-in on (docs/accounts.md).')));
    }
    body.append(kv([
      ['Username', me.username],
      ['Role', ROLE_LABEL[me.role] || me.role],
      ['Signs in with', none ? 'No sign-in' : me.auth_source === 'proxy' ? 'Your sign-in proxy' : 'Username and password'],
      me.created_at ? ['Account created', fmtDate(me.created_at)] : null,
    ]));

    // Name
    const nameId = 'set-display-name';
    const nameInput = h('input', { id: nameId, type: 'text', maxlength: 80, autocomplete: 'nickname', 'aria-describedby': `${nameId}-hint` });
    nameInput.value = me.display_name || '';
    const nameMsg = statusMsg('set-name-msg');
    const nameForm = h('form', { class: 'settings-form', novalidate: true },
      h('div', { class: 'field' },
        h('label', { for: nameId }, 'Your name'),
        h('div', { class: 'inline-row' }, nameInput, h('button', { class: 'btn secondary', type: 'submit' }, 'Save name')),
        h('span', { class: 'hint', id: `${nameId}-hint` }, 'Shown in the app and to your admin. Optional.')),
      nameMsg);
    sheets.onSubmit(nameForm, async (e) => {
      e.preventDefault();
      const btn = $('button[type="submit"]', nameForm);
      if (btn.disabled) return;
      btn.disabled = true;
      try {
        state.me = await api.updateMe({ display_name: nameInput.value.trim() });
        nameMsg.textContent = 'Name saved.';
        renderWho();
      } catch (err) { if (!err.handled) toastError(err); } finally { btn.disabled = false; }
    });
    body.append(nameForm);

    if (hasLocalPassword()) body.append(passwordForm(me));

    body.append(subtitle('Signed-in devices', 'set-devices-h'), h('div', { id: 'set-devices', 'aria-labelledby': 'set-devices-h', role: 'region' }, loading()));
    body.append(subtitle('Your data', 'set-data-h'), dataBlock(me));
    body.append(activityBlock());
    if (!none) {
      const out = action('Sign out', 'secondary', async () => { await KH.auth.signOut(); }, { id: 'set-signout' });
      body.append(h('div', { class: 'settings-actions signout-row' }, out,
        h('span', { class: 'hint' }, authMode() === 'proxy' ? 'Signs you out of this app; your sign-in proxy may keep you signed in there.' : 'On a shared computer, sign out when you finish.')));
    }
    loadDevices();
  }

  function passwordForm(me) {
    const err = formError();
    const form = h('form', { class: 'settings-form', id: 'set-password-form', novalidate: true },
      h('input', { type: 'text', name: 'username', autocomplete: 'username', value: me.username, readonly: true, hidden: true }),
      pwField('set-pw-current', 'Current password', 'current-password'),
      pwField('set-pw-new', 'New password', 'new-password', newPwHint()),
      err,
      h('div', { class: 'settings-actions' }, h('button', { class: 'btn primary', type: 'submit', id: 'set-pw-save' }, 'Save new password')),
      h('p', { class: 'hint' }, 'Changing your password signs out every other device. Forgot it? Ask your admin for a reset link.'));
    const details = h('details', { class: 'settings-details', id: 'set-password' }, h('summary', {}, 'Change password'), form);
    KH.auth.setupPwToggles(form);
    sheets.onSubmit(form, async (e) => {
      e.preventDefault();
      const cur = $('#set-pw-current'), nw = $('#set-pw-new');
      const btn = $('#set-pw-save');
      if (btn.disabled) return;
      if (!cur.value) { showFormError(err, 'Enter your current password.'); cur.focus(); return; }
      const problem = newPwProblem(nw.value);
      if (problem) { showFormError(err, problem); nw.focus(); return; }
      btn.disabled = true;
      clear(err);
      try {
        const res = await A.changePassword({ current_password: cur.value, new_password: nw.value });
        state.me = res.user;
        cur.value = ''; nw.value = '';
        details.open = false;
        toast('Password changed. Other devices were signed out.', 'ok');
        loadDevices();
      } catch (e2) {
        if (!e2.handled) { showFormError(err, e2); (e2.data && e2.data.field === 'current_password' ? cur : nw).focus(); }
      } finally { btn.disabled = false; }
    });
    return details;
  }

  async function loadDevices() {
    const box = $('#set-devices');
    if (!box) return;
    let res;
    try { res = await A.sessions(); } catch (err) { if (document.contains(box)) { clear(box); box.append(failed(err)); } return; }
    if (!document.contains(box)) return;
    clear(box);
    const list = res.sessions || [];
    if (!list.length) {
      box.append(h('p', { class: 'muted small' }, authMode() === 'proxy' ? 'Your sign-in proxy handles sign-in, so the app keeps no devices to list.'
        : authMode() === 'none' ? 'This server has no sign-in, so there are no devices to list.' : 'No devices.'));
      return;
    }
    const ul = h('ul', { class: 'list device-list' });
    for (const sn of list) {
      const btn = sn.current
        ? action('Sign out', 'secondary', async () => { await KH.auth.signOut(); }, { 'aria-label': 'Sign out of this device' })
        : action('Sign out', 'secondary', async () => {
          await A.revokeSession(sn.id);
          toast(`Signed out ${deviceName(sn.user_agent)}`, 'ok');
          await loadDevices();
          const again = $('#set-devices button'); if (again) again.focus();
        }, { 'aria-label': `Sign out ${deviceName(sn.user_agent)}, last active ${relTime(sn.last_seen_at)}` });
      ul.append(h('li', { class: 'device' },
        h('div', { class: 'device-main' },
          h('span', { class: 'row-title' }, deviceName(sn.user_agent), sn.current ? h('span', { class: 'badge this-device' }, 'This device') : null),
          h('span', { class: 'row-sub' }, [`Last active ${relTime(sn.last_seen_at)}`, `signed in ${fmtDate(sn.created_at)}`, sn.ip_prefix ? `network ${sn.ip_prefix}` : null].filter(Boolean).join(' · '))),
        btn));
    }
    box.append(ul);
    if (list.some((x) => !x.current)) {
      box.append(h('div', { class: 'settings-actions' }, action('Sign out everywhere else', 'secondary', async () => {
        const r = await A.revokeOthers();
        toast(r.revoked === 1 ? 'Signed out 1 other device' : `Signed out ${r.revoked} other devices`, 'ok');
        await loadDevices();
        const again = $('#set-devices button'); if (again) again.focus(); // this button is gone now
      }, { id: 'set-revoke-others' })));
    }
    box.append(h('p', { class: 'hint' }, 'Do not recognise a device? Sign it out, then change your password.'));
  }

  function dataBlock(me) {
    const wrap = h('div', { class: 'data-block' });
    const msg = statusMsg('set-export-msg');
    wrap.append(h('p', {}, 'Download everything you have entered: a .zip with export.json and spreadsheet (CSV) files for your log, foods, saved meals and settings. It holds no passwords, sessions or keys.'));
    wrap.append(h('div', { class: 'settings-actions' }, action('Export my data (.zip)', 'secondary', async () => {
      if (MOCK) { msg.textContent = 'In the installed app this downloads a .zip of your data. The preview has no server, so there is nothing to download.'; return; }
      msg.textContent = 'Preparing your export…';
      try {
        const res = await download('/api/me/export.zip', `kidney-health-${me.username}.zip`);
        msg.textContent = `Saved ${res.name} (${fmtBytes(res.bytes)}). Keep it somewhere private: it holds your health data.`;
      } catch (err) { msg.textContent = ''; throw err; }
    }, { id: 'set-export' })), msg);

    // Delete the account (not in AUTH_MODE=none: every request is user 1 there, which must stay)
    if (authMode() === 'none') {
      wrap.append(h('p', { class: 'hint', id: 'set-delete-none' }, 'This server runs without sign-in, so there is no personal account to delete. Remove entries one by one, or ask whoever runs the server.'));
      return wrap;
    }
    const err = formError();
    const confirmId = 'set-delete-confirm';
    const local = hasLocalPassword();
    const form = h('form', { class: 'settings-form', novalidate: true },
      h('p', {}, 'Deletes your account and everything in it: your log, custom foods, saved meals, profile, settings and keys. This cannot be undone. Export your data first if you want a copy.'),
      local ? h('input', { type: 'text', name: 'username', autocomplete: 'username', value: me.username, readonly: true, hidden: true }) : null,
      local ? pwField('set-delete-password', 'Your password', 'current-password') : null,
      h('div', { class: 'field' }, h('label', { for: confirmId }, 'Type DELETE to confirm'),
        h('input', { id: confirmId, type: 'text', autocomplete: 'off', autocapitalize: 'characters', spellcheck: 'false', maxlength: 20 })),
      err,
      h('div', { class: 'settings-actions' }, h('button', { class: 'btn danger-solid', type: 'submit', id: 'set-delete-save' }, 'Delete my account')));
    KH.auth.setupPwToggles(form);
    sheets.onSubmit(form, async (e) => {
      e.preventDefault();
      const btn = $('#set-delete-save');
      if (btn.disabled) return;
      const typed = $(`#${confirmId}`).value.trim();
      const pw = local ? $('#set-delete-password').value : null;
      if (local && !pw) { showFormError(err, 'Enter your password.'); $('#set-delete-password').focus(); return; }
      if (typed !== 'DELETE') { showFormError(err, 'Type DELETE (in capitals) to confirm.'); $(`#${confirmId}`).focus(); return; }
      btn.disabled = true;
      clear(err);
      try {
        await A.deleteMe(local ? { password: pw, confirm: typed } : { confirm: typed });
        if (MOCK) { KH.auth.showScreen('login', { notice: 'The demo account was deleted. Reload the page to start the demo again.' }); return; }
        // The page reloads (the server sent Clear-Site-Data); the sign-in screen then says what happened.
        KH.auth.noticeAfterReload('Your account and all of its data were deleted from this server.');
        try { history.replaceState(null, '', '#/login'); } catch (e3) { /* sandboxed frame */ }
        window.location.reload();
      } catch (e2) {
        if (!e2.handled) showFormError(err, e2);
        if (local) $('#set-delete-password').value = '';
      } finally { btn.disabled = false; }
    });
    wrap.append(h('details', { class: 'settings-details danger-zone', id: 'set-delete' }, h('summary', {}, 'Delete my account'), form));
    return wrap;
  }

  const ACTION_LABEL = {
    'setup.completed': 'Server set up', 'login.succeeded': 'Signed in', 'login.failed': 'Wrong password entered', 'user.locked': 'Account locked',
    'user.invited': 'Invite or account created', 'invite.revoked': 'Invite revoked', 'user.registered': 'Account registered',
    'user.created_by_proxy': 'Account created by the sign-in proxy', 'user.role_changed': 'Role changed', 'user.disabled': 'Account disabled',
    'user.enabled': 'Account enabled', 'user.deleted': 'Account deleted', 'user.updated': 'Account updated', 'user.reset_link_issued': 'Password reset link created',
    'user.reset_link_revoked': 'Password reset link revoked',
    'user.password_changed': 'Password changed', 'user.must_change_password': 'New password required', 'sessions.revoked': 'Devices signed out',
    'session.revoked_reauth': 'Signed out after wrong passwords', 'proxy.username_conflict': 'Sign-in proxy name clash', 'settings.changed': 'Setting changed',
    'secret.set': 'Key saved', 'secret.removed': 'Key removed', 'ai_provider.changed': 'AI provider changed', 'export.created': 'Data exported',
    'account.deleted': 'Account deleted', 'secret_key.rotated': 'Secret key rotated', 'backup.created': 'Backup created',
  };
  function eventDetail(ev) {
    const d = ev.details || {};
    if (ev.action === 'settings.changed') return `${(REG.BY_KEY[d.key] || {}).label || d.key}: ${JSON.stringify(d.old)} → ${JSON.stringify(d.new)}`;
    if (ev.action === 'secret.set' || ev.action === 'secret.removed') return `${d.provider || ev.target_id} (${d.scope === 'shared' ? 'shared key' : 'own key'})`;
    if (ev.action === 'sessions.revoked' && d.count != null) return d.count === 1 ? '1 device' : `${d.count} devices`;
    if (ev.action === 'user.role_changed') return `${ROLE_LABEL[d.old] || d.old} → ${ROLE_LABEL[d.new] || d.new}`;
    if (ev.action === 'login.failed' && d.via === 'reauth') return 'when asked for the password again';
    if (ev.action === 'user.password_changed' && d.via) return { self: 'by the person', admin_reset_link: 'with an admin reset link', reset_link: 'with a reset link', account_setup: 'first password' }[d.via] || '';
    if (d.links_revoked) return d.links_revoked === 1 ? '1 open link revoked' : `${d.links_revoked} open links revoked`;
    return '';
  }
  // Whose account an admin action concerned (the audit row keeps ids only). A deleted account keeps its number.
  function accountName(id) {
    const u = (cache.users || []).find((x) => x.id === Number(id));
    if (u) return u.display_name ? `${u.display_name} (${u.username})` : u.username;
    return cache.users ? `deleted user #${id}` : `user #${id}`;
  }
  function targetOf(ev) {
    if (ev.target_type !== 'user' || ev.target_id == null || String(ev.actor_user_id) === String(ev.target_id)) return null;
    if (ev.actor_user_id == null) return null; // shown as "account …" in place of the actor
    return accountName(ev.target_id);
  }
  function activityBlock() {
    const list = h('ul', { class: 'activity-list' }, h('li', { class: 'muted small' }, 'Loading…'));
    const details = h('details', { class: 'settings-details', id: 'set-activity' }, h('summary', {}, 'Recent sign-in activity'), list,
      h('p', { class: 'hint' }, 'Sign-ins, password and key changes and exports on your account, newest first, including anything an admin did to it.'));
    let loaded = false;
    details.addEventListener('toggle', async () => {
      if (!details.open || loaded) return;
      loaded = true;
      try {
        const res = await A.activity();
        clear(list);
        if (!res.events.length) list.append(h('li', { class: 'muted small' }, 'Nothing yet.'));
        const me = state.me ? state.me.id : null;
        for (const ev of res.events) {
          const extra = eventDetail(ev);
          // Only events about this account are listed; one an admin did to it says so.
          const byAdmin = ev.actor_user_id != null && ev.actor_user_id !== me ? ' · by an admin' : '';
          list.append(h('li', {}, h('span', { class: 'act-what' }, ACTION_LABEL[ev.action] || ev.action, extra || byAdmin ? h('span', { class: 'muted' }, `${extra ? ` · ${extra}` : ''}${byAdmin}`) : null),
            h('span', { class: 'act-when muted small' }, `${fmtDateTime(ev.at)}${ev.ip_prefix ? ` · ${ev.ip_prefix}` : ''}`)));
        }
      } catch (err) { loaded = false; clear(list); list.append(h('li', {}, failed(err))); }
    });
    return details;
  }

  // ---------------------------------------------------------------------------
  // Section: Preferences (theme is also saved to the account: ui.theme, scope user_default)
  // ---------------------------------------------------------------------------
  const themeToServer = (mode) => (mode === 'light' || mode === 'dark' ? mode : 'system');
  const themeFromServer = (v) => (v === 'light' || v === 'dark' ? v : 'auto');
  function renderThemeSource() {
    const el = $('#set-theme-source');
    clear(el);
    const item = cache.mySettings && cache.mySettings['ui.theme'];
    if (!item) return;
    el.className = `setting-source src-${item.source}`;
    if (item.source === 'env') el.append(lockIcon());
    el.append(h('span', {}, `${sourceText(item.source, null)}. Saved to your account, so your other devices follow.`));
    $('#set-theme').disabled = item.editable === false;
  }
  let themeSaveTimer = null;
  function saveTheme() {
    if (!state.me || state.view === 'auth') return;
    clearTimeout(themeSaveTimer);
    themeSaveTimer = setTimeout(async () => {
      try {
        const res = await api.updateMySettings({ 'ui.theme': themeToServer(KH.theme.stored()) });
        cache.mySettings = res.settings;
        renderThemeSource();
      } catch (err) { if (!err.handled) console.warn('Theme not saved to the account:', err.detail || err); }
    }, 500);
  }
  $('#set-theme').addEventListener('change', saveTheme);
  $('#theme-toggle').addEventListener('click', saveTheme);
  $('#set-week-start').addEventListener('change', async (e) => {
    const sel = e.target;
    const msg = $('#set-prefs-status');
    sel.disabled = true;
    try {
      state.profile = await api.saveProfile({ week_start: sel.value === 'sunday' ? 'sunday' : 'monday' });
      state.plan = null; state.planStart = null; state.shopping = null;
      msg.textContent = `Weeks now start on ${sel.value === 'sunday' ? 'Sunday' : 'Monday'}.`;
    } catch (err) { if (!err.handled) toastError(err); sel.value = (state.profile && state.profile.week_start) || 'monday'; } finally { sel.disabled = false; }
  });
  // Lab units (user.units.labs, note 05 §4.9): the unit the Labs view offers first.
  function renderLabUnits() {
    const sel = $('#set-lab-units');
    const src = clear($('#set-lab-units-source'));
    const item = cache.mySettings && !(cache.mySettings instanceof Error) ? cache.mySettings['user.units.labs'] : null;
    if (!item) return;
    sel.value = item.value === 'si' ? 'si' : 'us';
    sel.disabled = item.editable === false;
    src.className = `setting-source src-${item.source}`;
    if (item.source === 'env') src.append(lockIcon());
    src.append(h('span', {}, sourceText(item.source, null)));
  }
  $('#set-lab-units').addEventListener('change', async (e) => {
    const sel = e.target;
    const msg = $('#set-prefs-status');
    sel.disabled = true;
    try {
      const res = await api.updateMySettings({ 'user.units.labs': sel.value });
      cache.mySettings = res.settings;
      msg.textContent = sel.value === 'si' ? 'Lab results now offer SI units first.' : 'Lab results now offer US units first.';
    } catch (err) { if (!err.handled) toastError(err); } finally { sel.disabled = false; renderLabUnits(); }
  });
  function renderPrefs() {
    renderLabUnits();
    $('#set-theme').value = KH.theme.stored();
    $('#set-week-start').value = state.profile && state.profile.week_start === 'sunday' ? 'sunday' : 'monday';
    clear($('#set-prefs-status'));
    renderThemeSource();
  }

  // ---------------------------------------------------------------------------
  // Section: Food data
  // ---------------------------------------------------------------------------
  function usdaStatusText(item) {
    if (item.effective === 'own') return 'Lookups use your own key.';
    const sh = item.shared || {};
    if (item.effective === 'shared') {
      return sh.daily_limit ? `Using the shared key from your admin (${sh.remaining_today} of ${sh.daily_limit} lookups left today).` : 'Using the shared key from your admin (no daily limit).';
    }
    if (sh.available && sh.daily_limit && sh.remaining_today === 0) return "Today's shared lookups are used up. Add your own key, or try again tomorrow.";
    return item.user_keys_allowed ? 'No key yet: ask your admin to share one, or add your own below.' : 'No key yet: ask your admin to share one.';
  }
  function renderFood(keyMessage = null) {
    const body = $('#set-food-body');
    clear(body);
    // USDA
    body.append(subtitle('USDA FoodData Central', 'set-usda-h'),
      h('p', { class: 'hint' }, 'Search hundreds of thousands of foods, including branded products, from the U.S. Department of Agriculture. The server looks them up for you.'));
    const keys = cache.myKeys;
    if (keys instanceof Error) body.append(failed(keys));
    else if (!keys) body.append(loading());
    else {
      for (const item of keys.providers || []) {
        if (item.provider !== 'usda') continue;
        body.append(h('p', { class: `setting-status eff-${item.effective}`, id: 'set-usda-status' }, usdaStatusText(item)));
        body.append(keyWidget({
          name: 'Your own key',
          providerLabel: 'USDA',
          status: item.own,
          addText: 'Add your own key',
          disabledText: item.user_keys_allowed ? null : 'Your admin has turned off personal keys for USDA.',
          removeText: 'Remove your USDA key? Lookups then use the shared key, if your admin shares one.',
          message: keyMessage,
          onSave: (key, test) => api.setMyKey('usda', { api_key: key, test }),
          onSaved: async (res, text) => { await refreshMyKeys(text); },
          onRemove: async (text) => { await api.deleteMyKey('usda'); await refreshMyKeys(text); },
        }));
        body.append(h('p', { class: 'hint' }, 'A free key from api.data.gov (sign up with your email) allows 1,000 lookups an hour. Your own key is used first; the app never switches you to the shared key when yours stops working.'));
      }
    }
    // Scanning: start the camera when the Scan sheet opens (note 03 R10, "Prefer live camera")
    const settings = cache.mySettings;
    if (settings && !(settings instanceof Error) && settings['food.scan_prefer_camera']) {
      body.append(subtitle('Scanning', 'set-scan-h'));
      const item = settings['food.scan_prefer_camera'];
      const def = REG.BY_KEY['food.scan_prefer_camera'];
      const id = 'set-scan-camera';
      const box = h('input', { type: 'checkbox', id, 'aria-describedby': `${id}-help ${id}-src` });
      box.checked = item.value !== false;
      box.disabled = item.editable === false;
      const msg = statusMsg(`${id}-msg`);
      box.addEventListener('change', async () => {
        box.disabled = true;
        try {
          const res = await api.updateMySettings({ 'food.scan_prefer_camera': box.checked });
          cache.mySettings = res.settings;
          msg.textContent = box.checked ? 'Saved: Scan starts the camera.' : 'Saved: Scan waits for you to choose the camera, a photo or typing.';
          const src = $(`#${id}-src`); if (src) src.replaceWith(sourceLine(res.settings['food.scan_prefer_camera'].source, null, { id: `${id}-src` }));
        } catch (err) { box.checked = !box.checked; if (!err.handled) toastError(err); } finally { box.disabled = cache.mySettings['food.scan_prefer_camera'].editable === false; }
      });
      body.append(h('div', { class: 'setting-row' },
        h('label', { class: 'check', for: id }, box, h('span', { class: 'check-text' }, def ? def.label : 'Start the camera when I open Scan',
          h('span', { class: 'hint', id: `${id}-help` }, 'Only on a secure (HTTPS) address, where the browser allows the camera. The browser asks first, and the camera stops when you close Scan.'))),
        sourceLine(item.source, null, { id: `${id}-src` }), msg));
    }
    // Open Food Facts
    body.append(subtitle('Barcode lookups: Open Food Facts', 'set-off-h'));
    if (settings instanceof Error) body.append(failed(settings));
    else if (!settings) body.append(loading());
    else if (settings['food.off_consent']) {
      const item = settings['food.off_consent'];
      const def = REG.BY_KEY['food.off_consent'];
      const id = 'set-off-consent';
      const box = h('input', { type: 'checkbox', id, 'aria-describedby': `${id}-help ${id}-src` });
      box.checked = item.value === true;
      box.disabled = item.editable === false;
      const msg = statusMsg(`${id}-msg`);
      box.addEventListener('change', async () => {
        box.disabled = true;
        try {
          const res = await api.updateMySettings({ 'food.off_consent': box.checked });
          cache.mySettings = res.settings;
          msg.textContent = box.checked ? 'Saved: barcodes you scan may be sent to Open Food Facts.' : 'Saved: barcodes you scan stay on this server.';
          const src = $(`#${id}-src`); if (src) src.replaceWith(sourceLine(res.settings['food.off_consent'].source, null, { id: `${id}-src` }));
        } catch (err) { box.checked = !box.checked; if (!err.handled) toastError(err); } finally { box.disabled = cache.mySettings['food.off_consent'].editable === false; }
      });
      body.append(h('div', { class: 'setting-row' },
        h('label', { class: 'check', for: id }, box, h('span', { class: 'check-text' }, def ? def.label : 'Send barcodes I scan to Open Food Facts',
          h('span', { class: 'hint', id: `${id}-help` }, 'Only the barcode number is sent, and only for products this server does not know yet. It works when your admin has turned Open Food Facts lookups on.'))),
        sourceLine(item.source, null, { id: `${id}-src` }), msg));
    }
    const offAdmin = cache.adminSettings && !(cache.adminSettings instanceof Error) && cache.adminSettings['food.off_enabled'];
    if (offAdmin) {
      const why = offAdmin.locked_by_env ? `Set by the server (${offAdmin.locked_by_env}), locked.`
        : offAdmin.source === 'instance' ? 'An admin chose this (or the first-run setup did).' : 'That is the app default.';
      body.append(h('p', { class: 'setting-status', id: 'set-off-server' }, `On this server Open Food Facts lookups are ${offAdmin.value ? 'on' : 'off'}. ${why}`,
        offAdmin.locked_by_env ? null : ' Change it in Admin → Server settings.'));
    }
    body.append(h('p', { class: 'hint' }, 'Product data from Open Food Facts is © Open Food Facts contributors, under the Open Database License (ODbL). USDA FoodData Central data is in the public domain.'));
    if (MOCK) {
      body.append(h('p', { class: 'hint' }, 'The demo never contacts USDA or Open Food Facts. Its barcode lookups answer from three sample products '
        + 'recorded from Open Food Facts: Diet Coke (049000028911), Kraft Macaroni & Cheese (021000658831) and Nutella (3017624010701). '
        + 'In the installed app the server asks Open Food Facts for any product barcode.'));
    }
  }
  async function refreshMyKeys(message = null) {
    try { cache.myKeys = await api.myKeys(); } catch (err) { cache.myKeys = err; }
    renderFood(message);
    // Keep the keyboard in the widget it just used.
    const btn = $('#set-food-body .key-actions button');
    if (message && btn) btn.focus();
  }

  // ---------------------------------------------------------------------------
  // Section: AI ideas (M2 fills #set-ai-slot)
  // ---------------------------------------------------------------------------
  function renderAi() {
    const body = $('#set-ai-body');
    if ($('#set-ai-slot', body) && body.dataset.filled) return; // M2 owns the slot once it renders
    clear(body);
    body.append(h('p', { class: 'setting-status' }, h('span', { class: 'state-pill off' }, 'Not configured')),
      h('p', {}, 'Optional AI help (meal ideas, reading a nutrition label from a photo) is not set up on this server. Nothing you log is sent to an AI service.'),
      h('div', { id: 'set-ai-slot' }));
  }

  // ---------------------------------------------------------------------------
  // Section: This device (note 02 R10)
  // ---------------------------------------------------------------------------
  const OFFLINE_TEXT = {
    ready: 'Yes: the app opens without a connection',
    installing: 'Getting ready…',
    insecure: 'No: offline use needs HTTPS',
    unsupported: 'Not in this browser',
    off: 'Not yet: reload the page once',
  };
  // Renders can overlap: Settings opens one, and js/pwa.js asks for another when the first visit's offline
  // copy becomes ready (it can say so twice in a row: ready, then in control). Each render builds
  // into a detached fragment and only the newest one, after all of its awaits, replaces the section, so the
  // rows never appear twice and the ids (#set-clear-device, #set-outbox, #set-outbox-h) stay unique.
  let deviceRender = 0;
  let deviceStop = null; // stops the shown outbox list's live updates when a newer render replaces it
  async function renderDevice() {
    const body = $('#set-device-body');
    const ticket = ++deviceRender;
    const out = document.createDocumentFragment();
    const stops = [];
    const show = () => {
      if (ticket !== deviceRender) { for (const stop of stops) stop(); return false; } // a newer render owns the section
      if (deviceStop) deviceStop();
      deviceStop = () => { for (const stop of stops) stop(); };
      body.replaceChildren(out);
      return true;
    };
    if (!KH.pwa || MOCK) {
      out.append(kv([['This app', PREVIEW ? 'A preview inside this page' : 'Demo mode (?mock=1)'], ['App version', APP_VERSION]]),
        h('p', {}, 'In the installed app this section shows whether the app is on your home screen and works offline, how much it stores on this device, and how to install it. The preview stores nothing on this device.'));
      // The outbox works against the demo too: while the browser is offline, entries wait in this page (js/offline.js).
      if (KH.offline) stops.push(await KH.offline.renderDevice(out));
      show();
      return;
    }
    const st = await KH.pwa.deviceStatus();
    // isSecureContext is also true on http://localhost, which is not encrypted: ask the address.
    const https = (() => { try { return window.location.protocol === 'https:'; } catch (e) { return false; } })();
    const storage = st.storage ? `${fmtBytes(st.storage.usage)} of about ${fmtBytes(st.storage.quota)}` : null;
    out.append(kv([
      ['This app', st.installed ? 'Installed: it opens from your home screen' : 'Not installed: it runs in the browser'],
      ['Works offline', OFFLINE_TEXT[st.offline] || st.offline],
      storage ? ['Storage used', `${storage}${st.persisted === true ? ' · kept by the browser' : st.persisted === false ? ' · the browser may clear it when space runs low' : ''}`] : null,
      ['Connection', https ? 'Encrypted (HTTPS)' : st.secure ? 'Not encrypted (plain HTTP on this computer; offline use still works)' : 'Not encrypted (plain HTTP)'],
      ['App version', st.updateReady ? `${APP_VERSION} (an update is ready: use Reload)` : APP_VERSION],
    ]));
    if (!st.secure) out.append(note('caution', h('p', {}, 'Offline use and the live camera need HTTPS. Your admin can set it up with docs/https.md.')));
    // Entries waiting to sync, with Sync now, Retry, Discard (js/offline.js, note 02 R5).
    if (KH.offline) stops.push(await KH.offline.renderDevice(out));
    const row = h('div', { class: 'settings-actions' });
    const clearBtn = h('button', { class: 'btn secondary', type: 'button', id: 'set-clear-device' }, 'Clear offline data on this device');
    clearBtn.addEventListener('click', async () => {
      const waiting = KH.offline ? Number(await KH.offline.pendingCount()) || 0 : 0;
      confirm.inline(row, clearBtn, {
        message: waiting
          ? `Remove the app's offline copy from this device? ${waiting} ${waiting === 1 ? 'entry has' : 'entries have'} not reached your server and will be lost. Your log on the server stays.`
          : "Remove the app's offline copy from this device? Your log stays on the server; the app downloads itself again next time.",
        confirmText: waiting ? 'Clear and lose them' : 'Clear',
        onConfirm: async () => {
          if (KH.offline) await KH.offline.purge();
          await KH.pwa.clearOfflineData();
          toast('Offline data cleared on this device', 'ok');
          await renderDevice();
          return true;
        },
      });
    });
    row.append(clearBtn);
    out.append(row);
    if (!show()) return;
    KH.pwa.renderInstallPanel();
    // Opened straight to #settings: the app may become ready for offline use a moment later; show
    // the new state then instead of a stale "Not yet" (js/pwa.js says when; subscribed once).
    if (!deviceWatch && typeof KH.pwa.onStateChange === 'function') {
      deviceWatch = KH.pwa.onStateChange(() => { if (state.view === 'settings') renderDevice().catch(() => null); });
    }
  }
  let deviceWatch = null;

  // ---------------------------------------------------------------------------
  // Section: Admin
  // ---------------------------------------------------------------------------
  const isAdmin = () => !!(state.me && state.me.role === 'admin');
  function renderAdminFrame() {
    const sec = $('#set-admin');
    sec.hidden = !isAdmin();
    const body = $('#set-admin-body');
    clear(body);
    if (!isAdmin()) return;
    const none = authMode() === 'none';
    body.append(h('p', { class: 'hint' }, 'Admins manage accounts and server settings. There is no page here to read anyone else’s log, foods or keys.'));
    if (!none) body.append(subtitle('People', 'set-people-h'), h('div', { id: 'set-people' }, loading()));
    body.append(subtitle('Server settings', 'set-server-h'), h('div', { id: 'set-server' }, loading()));
    body.append(subtitle('Shared keys', 'set-shared-h'), h('div', { id: 'set-shared' }, loading()));
    body.append(subtitle('Usage, last 30 days', 'set-usage-h'), h('div', { id: 'set-usage' }, loading()));
    body.append(subtitle('Activity log', 'set-audit-h'), h('div', { id: 'set-audit' }, loading()));
    body.append(subtitle('About this server', 'set-server-about-h'), h('div', { id: 'set-server-about' }, loading()));
    adminSettingsReady = loadServerSettings();
    peopleReady = none ? Promise.resolve() : loadPeople();
    loadSharedKeys();
    loadUsage();
    loadAudit();
    loadServerAbout();
  }

  // ---- People: accounts and invites
  let adminSettingsReady = Promise.resolve();
  let peopleReady = Promise.resolve(); // the activity log names accounts from the people list
  async function loadPeople(focusSel) {
    const box = $('#set-people');
    if (!box) return;
    let users, invites;
    try { [users, invites] = await Promise.all([A.users(), A.invites()]); } catch (err) { clear(box); box.append(failed(err)); return; }
    await adminSettingsReady.catch(() => null); // the invite form needs registration.mode and the link lifetime
    cache.users = users.users;
    if (!document.contains(box)) return;
    clear(box);
    const st = state.authStatus || {};
    if (st.insecure_http) {
      box.append(note('caution', h('p', {}, h('strong', {}, 'This server is on plain HTTP. '),
        'With more than one account, signing in over plain HTTP is turned off, because anyone on the network could read passwords. Set up HTTPS (docs/https.md) before you invite someone.')));
    }
    const ul = h('ul', { class: 'list user-list', 'aria-labelledby': 'set-people-h' });
    for (const u of users.users) ul.append(userRow(u));
    box.append(ul);
    box.append(inviteBlock(invites.invites || []));
    if (focusSel) { const el = $(focusSel); if (el) el.focus(); }
  }
  function userRow(u) {
    const self = state.me && u.id === state.me.id;
    const badges = [h('span', { class: `badge role-${u.role}` }, ROLE_LABEL[u.role] || u.role)];
    if (u.status !== 'active') badges.push(h('span', { class: `badge status-${u.status}` }, STATUS_LABEL[u.status] || u.status));
    if (self) badges.push(h('span', { class: 'badge this-device' }, 'You'));
    const sub = [u.last_login_at ? `Last signed in ${relTime(u.last_login_at)}` : 'Never signed in', `joined ${fmtDate(u.created_at)}`,
      u.auth_source === 'proxy' ? 'signs in through the proxy' : null].filter(Boolean).join(' · ');
    const link = u.reset_link;
    const linkText = link ? `${u.status === 'pending_setup' ? 'Setup link' : 'Password reset link'} open until ${fmtDateTime(link.expires_at)}`
      + `${link.created_by != null ? `, created by ${state.me && link.created_by === state.me.id ? 'you' : accountName(link.created_by)}` : ', created with the command line'}` : null;
    const li = h('li', { class: 'user-row', id: `user-${u.id}` },
      h('div', { class: 'user-main' },
        h('span', { class: 'row-title' }, u.display_name || u.username, u.display_name ? h('span', { class: 'muted' }, ` (${u.username})`) : null),
        h('span', { class: 'user-badges' }, badges),
        h('span', { class: 'row-sub' }, sub),
        linkText ? h('span', { class: 'row-sub open-link' }, linkText) : null));
    if (self && link && link.created_by !== state.me.id) {
      li.append(note('caution', h('p', {}, h('strong', {}, 'Someone created a password reset link for your account. '),
        'Whoever holds it can set your password and sign in as you. If you did not ask for it, revoke it under Manage.')));
    }
    li.append(userManage(u, self));
    return li;
  }
  function userManage(u, self) {
    const name = u.display_name || u.username;
    const err = formError();
    const out = h('div', { class: 'user-out' });
    const panel = h('div', { class: 'user-manage-body' });
    const done = async (message) => { toast(message, 'ok'); await loadPeople(`#user-${u.id} summary`); };
    const patch = async (b, message) => {
      clear(err);
      try { await A.updateUser(u.id, b); await done(message); } catch (e) { if (!e.handled) showFormError(err, e); }
    };
    // Role
    const roleId = uid('role');
    const roleSel = selectEl(roleId, [['user', 'Member'], ['admin', 'Admin']], u.role);
    panel.append(h('div', { class: 'field' }, h('label', { for: roleId }, 'Role'),
      h('div', { class: 'inline-row' }, roleSel, action('Save role', 'secondary', async () => {
        if (roleSel.value === u.role) return;
        await patch({ role: roleSel.value }, `${name} is now ${ROLE_LABEL[roleSel.value].toLowerCase() === 'admin' ? 'an admin' : 'a member'}`);
      })),
      h('span', { class: 'hint' }, 'Admins manage people and server settings. Changing the role signs the person out.')));
    // Shared keys
    const sharedId = uid('shared');
    const shared = h('input', { type: 'checkbox', id: sharedId });
    shared.checked = !!u.can_use_shared;
    shared.addEventListener('change', async () => {
      shared.disabled = true;
      await patch({ can_use_shared: shared.checked }, shared.checked ? `${name} can use the shared keys` : `${name} no longer uses the shared keys`);
    });
    panel.append(h('label', { class: 'check', for: sharedId }, shared, h('span', { class: 'check-text' }, 'Can use the shared keys (USDA)')));
    // Actions
    const actions = h('div', { class: 'settings-actions wrap' });
    const authLocal = authMode() === 'local' && u.auth_source === 'local';
    if (authLocal && u.status !== 'disabled') {
      actions.append(action('Create a password reset link', 'secondary', async () => {
        const r = await A.resetLink(u.id);
        clear(out);
        out.append(linkBox(r.url, [`Send it to ${name} yourself. It works once, for 24 hours (until ${fmtDateTime(r.expires_at)}), and also unlocks a locked account. Their username is ${u.username}.`,
          'Anyone with this link can set the password and sign in as this person, so send it only to them.']));
      }));
    }
    if (u.reset_link) {
      actions.append(action(u.status === 'pending_setup' ? 'Revoke the setup link' : 'Revoke the reset link', 'secondary', async () => {
        await A.revokeResetLink(u.id);
        await done('Link revoked: it no longer works');
      }));
    }
    if (authLocal && u.has_password && !u.must_change_password && u.status === 'active') {
      actions.append(action('Require a new password', 'secondary', async () => { await patch({ must_change_password: true }, `${name} must choose a new password at the next sign-in`); }));
    }
    actions.append(action(self ? 'Sign out all my devices' : 'Sign out of all devices', 'secondary', async () => {
      const r = await A.revokeUser(u.id);
      toast(r.revoked === 1 ? 'Signed out 1 device' : `Signed out ${r.revoked} devices`, 'ok');
      if (self) { await KH.auth.signOut(); return; } // this device too: show the sign-in screen now
      await loadPeople();
    }));
    if (!self && u.status === 'active') {
      const dis = h('button', { class: 'btn danger', type: 'button' }, 'Disable account');
      dis.addEventListener('click', () => confirm.inline(actions, dis, {
        message: `Disable ${name}? They are signed out and cannot sign in until you enable the account again. Their data stays.`,
        confirmText: 'Disable',
        onConfirm: async () => { await A.updateUser(u.id, { status: 'disabled' }); await done(`${name} is disabled`); return true; },
      }));
      actions.append(dis);
    } else if (u.status === 'disabled') {
      actions.append(action('Enable account', 'secondary', async () => { await patch({ status: 'active' }, `${name} is enabled again`); }));
    } else if (u.status === 'pending_setup' || u.status === 'locked') {
      panel.append(h('p', { class: 'hint' }, u.status === 'locked' ? 'Locked after too many wrong passwords: a reset link unlocks it.' : 'Waiting for the person to choose a password with their setup link. Create a new link if theirs has expired.'));
    }
    panel.append(actions, out, err);
    // Delete
    if (!self) {
      const confirmId = uid('del');
      const delErr = formError();
      const delForm = h('form', { class: 'settings-form', novalidate: true },
        h('p', {}, `Deletes ${name}'s account and everything in it (log, foods, saved meals, profile, settings, keys). This cannot be undone.`),
        h('div', { class: 'field' }, h('label', { for: confirmId }, `Type ${u.username} to confirm`),
          h('input', { id: confirmId, type: 'text', autocomplete: 'off', autocapitalize: 'none', spellcheck: 'false', maxlength: 255 })),
        delErr,
        h('div', { class: 'settings-actions' }, h('button', { class: 'btn danger-solid', type: 'submit' }, 'Delete account')));
      sheets.onSubmit(delForm, async (e) => {
        e.preventDefault();
        const btn = $('button[type="submit"]', delForm);
        if (btn.disabled) return;
        btn.disabled = true;
        clear(delErr);
        try { await A.deleteUser(u.id, { confirm_username: $(`#${confirmId}`).value.trim() }); toast(`${name}'s account was deleted`, 'ok'); await loadPeople('#set-people-h'); } catch (e2) { if (!e2.handled) showFormError(delErr, e2); } finally { btn.disabled = false; }
      });
      panel.append(h('details', { class: 'settings-details danger-zone' }, h('summary', {}, 'Delete account'), delForm));
    }
    return h('details', { class: 'user-manage' }, h('summary', { 'aria-label': `Manage ${name}` }, 'Manage'), panel);
  }

  function inviteBlock(invites) {
    const wrap = h('div', { class: 'invite-block' });
    const mode = cache.adminSettings && !(cache.adminSettings instanceof Error) && cache.adminSettings['registration.mode']
      ? cache.adminSettings['registration.mode'].value : (state.authStatus || {}).registration;
    const proxy = authMode() === 'proxy';
    const ttlDefault = cache.adminSettings && !(cache.adminSettings instanceof Error) && cache.adminSettings['registration.invite_ttl_days']
      ? cache.adminSettings['registration.invite_ttl_days'].value : 7;
    // Invite (local mode, unless registration is closed)
    if (!proxy && mode !== 'closed') {
      const err = formError();
      const out = h('div', { class: 'invite-out' });
      const roleId = 'set-invite-role', noteId = 'set-invite-note', daysId = 'set-invite-days';
      const days = h('input', { id: daysId, type: 'number', inputmode: 'numeric', min: 1, max: 90, step: 1 });
      days.value = String(ttlDefault);
      days.addEventListener('input', () => { days.dataset.touched = '1'; });
      const form = h('form', { class: 'settings-form invite-form', novalidate: true },
        h('div', { class: 'form-grid' },
          h('div', { class: 'field' }, h('label', { for: roleId }, 'Role'), selectEl(roleId, [['user', 'Member'], ['admin', 'Admin']], 'user')),
          h('div', { class: 'field' }, h('label', { for: daysId }, 'Link works for (days)'), days),
          h('div', { class: 'field span-2' }, h('label', { for: noteId }, 'Note (only admins see it)'),
            h('input', { id: noteId, type: 'text', maxlength: 200, placeholder: 'e.g. For Dad' }))),
        err,
        h('div', { class: 'settings-actions' }, h('button', { class: 'btn primary', type: 'submit', id: 'set-invite-create' }, 'Create invite link')),
        out);
      sheets.onSubmit(form, async (e) => {
        e.preventDefault();
        const btn = $('#set-invite-create');
        if (btn.disabled) return;
        const n = Number(days.value);
        if (!Number.isInteger(n) || n < 1 || n > 90) { showFormError(err, 'Choose 1 to 90 days.'); days.focus(); return; }
        btn.disabled = true;
        clear(err);
        try {
          // Untouched: the server applies "Invite links expire after (days)" itself.
          const body = days.dataset.touched ? { role: $(`#${roleId}`).value, ttl_days: n } : { role: $(`#${roleId}`).value };
          const noteText = $(`#${noteId}`).value.trim();
          if (noteText) body.note = noteText;
          const r = await A.createInvite(body);
          $(`#${noteId}`).value = '';
          clear(out);
          out.append(linkBox(r.url, [`Send it to the person yourself (a message or email). It works once and expires ${fmtDateTime(r.expires_at)}.`,
            'They open it, choose a username and a password, and are signed in. You will not see this link again.']));
          refreshInviteList();
        } catch (e2) { if (!e2.handled) showFormError(err, e2); } finally { btn.disabled = false; }
      });
      wrap.append(h('details', { class: 'settings-details', open: true, id: 'set-invite' }, h('summary', {}, 'Invite someone'), form));
    }
    // Create an account directly (closed mode: the only way; proxy mode: pre-create the proxy name)
    {
      const err = formError();
      const out = h('div', { class: 'invite-out' });
      const userId = 'set-new-username', nameId = 'set-new-name', roleId = 'set-new-role';
      const form = h('form', { class: 'settings-form', novalidate: true },
        h('p', { class: 'hint' }, proxy ? 'Add the name your sign-in proxy sends for the person; they can then open the app through the proxy.'
          : 'Creates the account now and gives you a one-time link where the person chooses their password.'),
        h('div', { class: 'form-grid' },
          h('div', { class: 'field' }, h('label', { for: userId }, proxy ? 'Name sent by the proxy' : 'Username'),
            h('input', { id: userId, type: 'text', autocomplete: 'off', autocapitalize: 'none', spellcheck: 'false', maxlength: 255 })),
          h('div', { class: 'field' }, h('label', { for: roleId }, 'Role'), selectEl(roleId, [['user', 'Member'], ['admin', 'Admin']], 'user')),
          h('div', { class: 'field span-2' }, h('label', { for: nameId }, 'Their name (optional)'), h('input', { id: nameId, type: 'text', maxlength: 80 }))),
        err,
        h('div', { class: 'settings-actions' }, h('button', { class: 'btn secondary', type: 'submit', id: 'set-new-create' }, 'Create account')),
        out);
      sheets.onSubmit(form, async (e) => {
        e.preventDefault();
        const btn = $('#set-new-create');
        if (btn.disabled) return;
        const username = $(`#${userId}`).value.trim();
        if (!username) { showFormError(err, 'Enter a username.'); $(`#${userId}`).focus(); return; }
        btn.disabled = true;
        clear(err);
        try {
          const b = { username, role: $(`#${roleId}`).value };
          if ($(`#${nameId}`).value.trim()) b.display_name = $(`#${nameId}`).value.trim();
          const r = await A.createUser(b);
          $(`#${userId}`).value = ''; $(`#${nameId}`).value = '';
          clear(out);
          if (r.setup_url) {
            out.append(linkBox(r.setup_url, [`Send it to ${r.user.display_name || r.user.username} yourself, with their username: ${r.user.username}. It works once and expires ${fmtDateTime(r.expires_at)}.`,
              'The page it opens shows the username too, so their password manager saves both.']));
          }
          else out.append(h('p', { class: 'status-msg' }, `${r.user.username} can now open the app through the sign-in proxy.`));
          const keep = out;
          await loadPeople();
          const again = $('#set-create-account');
          if (again && keep.childNodes.length) { again.open = true; const o = $('.invite-out', again); if (o) o.replaceWith(keep); }
        } catch (e2) { if (!e2.handled) showFormError(err, e2); } finally { btn.disabled = false; }
      });
      wrap.append(h('details', { class: 'settings-details', id: 'set-create-account', open: mode === 'closed' || proxy }, h('summary', {}, proxy ? 'Add a person' : 'Create an account yourself'), form));
    }
    // Invite list
    if (!proxy) {
      const list = h('ul', { class: 'list invite-list', id: 'set-invite-list', 'aria-label': 'Invites' });
      fillInviteList(list, invites, mode === 'closed');
      wrap.append(h('h4', { class: 'settings-minor', id: 'set-invites-h', tabindex: '-1' }, 'Invites'), list);
      if (mode === 'closed' && invites.some((i) => i.state === 'open')) {
        wrap.append(h('p', { class: 'hint' }, 'Registration is closed, so open invite links do not work at the moment. They work again if you switch Registration back to invite links (Server settings) before they expire; revoke any you no longer want.'));
      }
    }
    return wrap;
  }
  function fillInviteList(list, invites, paused = false) {
    clear(list);
    if (!invites.length) { list.append(h('li', { class: 'muted small empty-state' }, 'No invites yet.')); return; }
    for (const inv of invites.slice(0, 15)) {
      const what = `${ROLE_LABEL[inv.role] || inv.role} invite${inv.note ? ` · ${inv.note}` : ''}`;
      const when = inv.state === 'open' ? `expires ${fmtDateTime(inv.expires_at)}` : inv.state === 'used' ? `used ${fmtDate(inv.used_at)}` : `expired ${fmtDate(inv.expires_at)}`;
      const stateText = inv.state === 'open' ? (paused ? 'Paused: registration is closed' : 'Open') : inv.state === 'used' ? 'Used' : 'Expired';
      const li = h('li', { class: `invite inv-${inv.state}${paused && inv.state === 'open' ? ' inv-paused' : ''}` },
        h('div', { class: 'device-main' }, h('span', { class: 'row-title' }, what), h('span', { class: 'row-sub' }, `${stateText} · created ${fmtDate(inv.created_at)} · ${when}`)));
      if (inv.state === 'open') {
        li.append(action('Revoke', 'secondary', async () => {
          await A.deleteInvite(inv.id);
          toast('Invite revoked: the link no longer works', 'ok');
          await refreshInviteList(paused);
          // The button is gone: keep the keyboard in the list.
          const next = $('#set-invite-list button') || $('#set-invites-h');
          if (next) next.focus();
        }, { 'aria-label': `Revoke ${what}` }));
      }
      list.append(li);
    }
  }
  async function refreshInviteList(paused = false) {
    const list = $('#set-invite-list');
    if (!list) return;
    try { fillInviteList(list, (await A.invites()).invites || [], paused); } catch (err) { clear(list); list.append(h('li', {}, failed(err))); }
  }

  // ---- Server settings (instance keys; env locks are read-only)
  const GROUPS = [
    ['Sign-in and registration', ['instance.name', 'registration.mode', 'registration.invite_ttl_days']],
    ['Food data', ['food.off_enabled', 'food.off_contact', 'food.off_rate_per_minute', 'food.barcode_negative_ttl_hours', 'food.usda_branded_barcode',
      'providers.usda.shared_enabled', 'providers.usda.user_keys_allowed', 'providers.usda.daily_limit_per_user']],
    ['Default for everyone', ['ui.theme', 'user.units.labs']],
    ['Personalised targets and lab results', ['targets.lab_rules_enabled', 'targets.default_activity', 'targets.lab_fresh_days.potassium',
      'targets.lab_fresh_days.phosphate', 'targets.lab_fresh_days.albumin', 'targets.lab_fresh_days.bicarbonate']],
    ['Meal guidance', ['guidance.enabled', 'guidance.pool_per_role', 'guidance.beam_width']],
    // The master switch first: Settings → AI ideas sends admins here to turn it on.
    ['Optional AI', ['ai.enabled', 'ai.user_keys_allowed', 'ai.allow_user_base_url', 'ai.shared_daily_limit', 'ai.max_concurrency',
      'ai.vision_plate_enabled', 'ai.vision_allow_agent', 'ai.audit_retention_days']],
    ['Activity log', ['audit.retention_days']],
  ];
  const CHOICE_LABEL = {
    'registration.mode': { invite: 'Invite links (recommended)', closed: 'Closed: admins create accounts', open: 'Open: anyone who can reach the page (HTTPS only)' },
    'ui.theme': { system: 'Match each device', light: 'Light', dark: 'Dark' },
    'user.units.labs': { us: 'US: mg/dL, g/dL, mg/g, %', si: 'SI: mmol/L, µmol/L, g/L, mg/mmol, mmol/mol' },
    'targets.default_activity': { inactive: 'Inactive', low_active: 'Low active', active: 'Active', very_active: 'Very active' },
  };
  function valueText(key, value) {
    const def = REG.BY_KEY[key];
    if (CHOICE_LABEL[key] && CHOICE_LABEL[key][value]) return CHOICE_LABEL[key][value];
    if (def && def.type === 'bool') return value ? 'On' : 'Off';
    if (value && typeof value === 'object') return JSON.stringify(value);
    return String(value);
  }
  async function loadServerSettings() {
    try { cache.adminSettings = (await A.adminSettings()).settings; } catch (err) { cache.adminSettings = err; }
    renderServerSettings();
    renderFood(); // the Open Food Facts line shows the server's switch to admins
  }
  function renderServerSettings(focusId) {
    const box = $('#set-server');
    if (!box) return;
    clear(box);
    const all = cache.adminSettings;
    if (all instanceof Error) { box.append(failed(all)); return; }
    if (!all) { box.append(loading()); return; }
    box.append(h('p', { class: 'hint' }, 'Each setting shows where its value comes from. "Set by the server" means an environment variable fixes it; change it in the server configuration and restart.'));
    const seen = new Set();
    const groups = GROUPS.map(([title, keys]) => [title, keys.filter((k) => all[k])]);
    const other = Object.keys(all).filter((k) => !GROUPS.some(([, keys]) => keys.includes(k)));
    if (other.length) groups.push(['Other', other]);
    for (const [title, keys] of groups) {
      if (!keys.length) continue;
      const list = h('div', { class: 'setting-list' });
      for (const key of keys) { seen.add(key); list.append(settingRow(key, all[key])); }
      box.append(h('h4', { class: 'settings-minor' }, title), list);
    }
    if (focusId) { const el = document.getElementById(focusId); if (el) el.focus(); }
  }
  function settingRow(key, item) {
    const def = REG.BY_KEY[key] || { key, label: key, help: '', type: typeof item.value === 'boolean' ? 'bool' : typeof item.value === 'number' ? 'int' : typeof item.value === 'string' ? 'str' : 'object' };
    const id = `adm-${key.replace(/[^a-z0-9]+/gi, '-')}`;
    const locked = !!item.locked_by_env;
    const err = formError();
    const helpId = def.help ? `${id}-help` : null;
    const srcId = `${id}-src`;
    const described = [helpId, srcId].filter(Boolean).join(' ');
    const save = async (value, control) => {
      clear(err);
      try {
        const res = await A.updateAdminSettings({ [key]: value });
        cache.adminSettings = res.settings;
        toast(value === null ? `${def.label}: back to the default` : `${def.label}: saved`, 'ok');
        renderServerSettings(control ? control.id : id);
        renderFood();
        // An AI switch changes Settings → AI ideas above and the Add view's AI buttons: ask again, now.
        if (key.startsWith('ai.') && KH.ai) {
          if (typeof KH.ai.forget === 'function') KH.ai.forget();
          KH.ai.renderSettings().catch((e2) => console.warn('AI settings:', e2));
          if (typeof KH.ai.renderAddSlot === 'function') KH.ai.renderAddSlot().catch((e2) => console.warn('AI buttons:', e2));
        }
        if (key === 'registration.mode' || key === 'instance.name' || key === 'registration.invite_ttl_days') {
          KH.auth.loadStatus().then(() => { renderAbout(); renderWho(); }).catch(() => null);
          loadPeople();
        }
      } catch (e) {
        if (e.cancelled) { renderServerSettings(); return; }
        if (!e.handled) showFormError(err, e);
      }
    };
    let control;
    const row = h('div', { class: `setting-item${locked ? ' locked' : ''}`, id: `${id}-row` });
    if (def.type === 'bool') {
      control = h('input', { type: 'checkbox', id, 'aria-describedby': described });
      control.checked = item.value === true;
      control.disabled = locked;
      control.addEventListener('change', () => { control.disabled = true; save(control.checked, control); });
      row.append(h('label', { class: 'check', for: id }, control, h('span', { class: 'check-text' }, def.label, def.help ? h('span', { class: 'hint', id: helpId }, def.help) : null)));
    } else if (def.type === 'choice') {
      control = selectEl(id, def.options.map((o) => [o, (CHOICE_LABEL[key] || {})[o] || o]), item.value, { 'aria-describedby': described });
      control.disabled = locked;
      control.addEventListener('change', () => { control.disabled = true; save(control.value, control); });
      row.append(h('div', { class: 'field' }, h('label', { for: id }, def.label), control, def.help ? h('span', { class: 'hint', id: helpId }, def.help) : null));
    } else if (def.type === 'int' || def.type === 'str') {
      control = h('input', def.type === 'int'
        ? { id, type: 'number', inputmode: 'numeric', min: def.min, max: def.max, step: 1, 'aria-describedby': described }
        : { id, type: 'text', maxlength: def.maxLength || 200, 'aria-describedby': described });
      control.value = String(item.value);
      control.disabled = locked;
      const saveBtn = h('button', { class: 'btn secondary', type: 'button', hidden: locked }, 'Save');
      const submit = () => {
        const raw = control.value.trim();
        if (def.type === 'int') {
          const n = Number(raw);
          if (raw === '' || !Number.isInteger(n)) { showFormError(err, 'Enter a whole number.'); control.focus(); return; }
          const r = REG.validate(def, n);
          if (r.error) { showFormError(err, r.error.replace('Input should be', 'The value should be')); control.focus(); return; }
          save(n, control);
        } else {
          const r = REG.validate(def, raw);
          if (r.error) { showFormError(err, r.error.replace('String should have', 'Use')); control.focus(); return; }
          save(r.value, control);
        }
      };
      saveBtn.addEventListener('click', submit);
      control.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); submit(); } });
      row.append(h('div', { class: 'field' }, h('label', { for: id }, def.label), h('div', { class: 'inline-row' }, control, saveBtn),
        def.help ? h('span', { class: 'hint', id: helpId }, def.help) : null));
    } else {
      row.append(h('div', { class: 'field' }, h('span', { class: 'label' }, def.label || key), h('span', { class: 'muted small' }, valueText(key, item.value))));
    }
    const src = sourceLine(item.source, item.locked_by_env, { admin: true, id: srcId });
    const tail = h('div', { class: 'setting-tail' }, src);
    if (!locked && item.source === 'instance') {
      const reset = h('button', { class: 'link-btn', type: 'button' }, 'Use the default');
      reset.setAttribute('aria-label', `${def.label}: use the default (${valueText(key, def.default)})`);
      reset.addEventListener('click', () => save(null, null));
      tail.append(reset);
    }
    row.append(tail, err);
    return row;
  }

  // ---- Shared keys
  async function loadSharedKeys(message = null) {
    const box = $('#set-shared');
    if (!box) return;
    let res;
    try { res = await A.adminKeys(); } catch (err) { clear(box); box.append(failed(err)); return; }
    clear(box);
    const none = authMode() === 'none';
    for (const p of res.providers || []) {
      const st = p.shared || { set: false };
      box.append(keyWidget({
        name: `${p.label}: shared key`,
        providerLabel: p.provider === 'usda' ? 'USDA' : p.label,
        status: st,
        locked: st.locked,
        lockedText: `Set by the server (${p.provider === 'usda' ? 'USDA_API_KEY' : 'environment'}), locked. Change it in the server configuration.`,
        disabledText: none ? 'Shared keys cannot be changed while the server runs without sign-in (AUTH_MODE=none).' : null,
        removeText: `Remove the shared ${p.label} key? People without their own key can no longer look foods up there.`,
        message,
        onSave: (key, test) => A.setAdminKey(p.provider, { api_key: key, test }),
        onSaved: async (res, text) => { await loadSharedKeys(text); await refreshMyKeys(); const b = $('#set-shared .key-actions button'); if (b) b.focus(); },
        onRemove: async (text) => { await A.deleteAdminKey(p.provider); await loadSharedKeys(text); await refreshMyKeys(); const b = $('#set-shared .key-actions button'); if (b) b.focus(); },
      }));
    }
    box.append(h('p', { class: 'hint' }, 'People without a key of their own use the shared key, up to the daily limit in Server settings. Nobody can read a key back once saved, admins included.'));
  }

  // ---- Usage
  async function loadUsage() {
    const box = $('#set-usage');
    if (!box) return;
    let res;
    try { res = await A.usage(); } catch (err) { clear(box); box.append(failed(err)); return; }
    clear(box);
    if (!res.usage.length) { box.append(h('p', { class: 'muted small' }, 'No lookups through the server’s providers in the last 30 days.')); return; }
    box.append(h('ul', { class: 'list usage-list' }, res.usage.map((u) => h('li', { class: 'usage' },
      h('span', {}, u.username || `user ${u.user_id}`), h('span', { class: 'muted small' }, `${u.provider} · ${u.key_scope === 'shared' ? 'shared key' : 'own key'}`),
      h('span', { class: 'tabular' }, `${u.requests} ${u.requests === 1 ? 'request' : 'requests'}`)))),
    h('p', { class: 'hint' }, 'Counts only: the server does not record what was looked up.'));
  }

  // ---- Audit log
  async function loadAudit(before = null) {
    const box = $('#set-audit');
    if (!box) return;
    let res;
    try { res = await A.audit(before); } catch (err) { clear(box); box.append(failed(err)); return; }
    await peopleReady.catch(() => null);
    let list = $('#set-audit-list');
    if (!before || !list) { clear(box); list = h('ul', { class: 'activity-list', id: 'set-audit-list' }); box.append(list); }
    const more = $('#set-audit-more');
    if (more) more.remove();
    if (!before && !res.events.length) list.append(h('li', { class: 'muted small' }, 'Nothing recorded yet.'));
    for (const ev of res.events) {
      // No actor: a failed sign-in or a server action; say whose account it concerned.
      const who = ev.actor_user_id != null ? accountName(ev.actor_user_id)
        : ev.target_type === 'user' && ev.target_id != null ? `account ${accountName(ev.target_id)}` : 'server';
      const target = targetOf(ev);
      const extra = [target, eventDetail(ev)].filter(Boolean).map((x) => ` · ${x}`).join('');
      list.append(h('li', {}, h('span', { class: 'act-what' }, ACTION_LABEL[ev.action] || ev.action, extra ? h('span', { class: 'muted' }, extra) : null),
        h('span', { class: 'act-when muted small' }, `${fmtDateTime(ev.at)} · by ${who}${ev.ip_prefix ? ` · ${ev.ip_prefix}` : ''}`)));
    }
    if (res.events.length >= 30) {
      const last = res.events[res.events.length - 1].id;
      box.append(h('div', { class: 'settings-actions', id: 'set-audit-more' }, action('Show older', 'secondary', async () => { await loadAudit(last); })));
    }
  }

  // ---- About this server
  async function loadServerAbout() {
    const box = $('#set-server-about');
    if (!box) return;
    let a;
    try { a = await A.about(); } catch (err) { clear(box); box.append(failed(err)); return; }
    clear(box);
    const sk = a.secret_key || {};
    const secrets = sk.secrets || {};
    const proxy = a.proxy || {};
    box.append(kv([
      ['Server version', a.version],
      ['Database schema', String(a.schema_version)],
      ['Sign-in', { local: 'Usernames and passwords', proxy: 'Sign-in proxy', none: 'No sign-in (AUTH_MODE=none)' }[a.auth_mode] || a.auth_mode],
      ['Accounts', `${a.accounts.active} active of ${a.accounts.total}`],
      ['HTTPS', a.https ? 'Yes' : 'No: see docs/https.md'],
      ['Public address', a.public_url || 'Not set: links use the address you opened (PUBLIC_URL)'],
      ['Secret key', sk.source === 'auto' ? 'Generated on the data volume' : sk.source === 'env' ? 'From SECRET_KEY' : sk.source === 'file' ? 'From SECRET_KEY_FILE' : String(sk.source || '')],
      ['Stored keys', `${secrets.current || 0} current${secrets.older_key ? `, ${secrets.older_key} under an older key` : ''}${secrets.unreadable ? `, ${secrets.unreadable} unreadable` : ''}`],
      proxy.ignored_identity_headers ? ['Identity headers ignored', `${proxy.ignored_identity_headers} from untrusted peers (check TRUSTED_PROXIES)`] : null,
      ['Last backup', a.last_backup_at ? fmtDateTime(a.last_backup_at) : 'None recorded (python -m app.admin backup)'],
      a.pre_v3_backup ? ['Pre-v0.3 backup', `${a.pre_v3_backup.path} (${fmtBytes(a.pre_v3_backup.bytes)}), deleted after ${fmtDate(a.pre_v3_backup.deleted_after)}`] : null,
    ]));
    if (sk.warning) box.append(note('caution', h('p', {}, sk.warning)));
    if (secrets.unreadable) box.append(note('caution', h('p', {}, 'Some stored keys can no longer be read (the secret key changed). Ask the people concerned to enter their keys again.')));
  }

  // ---------------------------------------------------------------------------
  // Section: About & privacy
  // ---------------------------------------------------------------------------
  function renderAbout() {
    const body = $('#set-about-body');
    clear(body);
    body.append(
      kv([['App version', APP_VERSION], ['Server', (state.authStatus || {}).instance_name || 'Kidney Health']]),
      subtitle('What is stored, and who can see it'),
      h('ul', { class: 'about-list' },
        h('li', {}, 'Your log, foods, saved meals, profile, targets and settings are stored on this server, not on the internet. Your account sees only its own data.'),
        h('li', {}, 'The person who runs this server can technically read all data on it. An admin can also create a password reset link for any account and sign in as that person; the activity log records it, and you are told at your next sign-in.'),
        h('li', {}, 'Keys are stored encrypted and are never shown again. Your export (Account → Your data) holds everything about you except passwords, sessions and keys.'),
        h('li', {}, 'This device keeps the app itself and, for offline use, a copy of your recent days, your profile and the foods you have seen, plus entries waiting to sync. Signing out clears it (it asks first when something has not synced).')),
      subtitle('Not medical advice'),
      h('p', {}, 'Targets and limits in this app must come from your nephrologist or renal dietitian, and insulin decisions from your diabetes care team. Food warnings are general renal-diet conventions, not a prescription.'),
      subtitle('Learn: the patient handbook'),
      handbookAbout(),
      subtitle('Data sources'),
      dataSources(),
      subtitle('Licences'),
      h('ul', { class: 'about-list' },
        h('li', {}, 'App code: PolyForm Noncommercial License 1.0.0.'),
        h('li', {}, 'Handbook text: Creative Commons Attribution-NonCommercial-ShareAlike 4.0 (CC BY-NC-SA 4.0).'),
        h('li', {}, 'Food data from USDA FoodData Central: public domain (U.S. government work; CC0 1.0).'),
        h('li', {}, 'Product data from Open Food Facts (when lookups are on): © Open Food Facts contributors, under the Open Database License (ODbL) 1.0; the app shows no product images.'),
        h('li', {}, 'Barcode reader used on devices without a built-in one: barcode-detector 3.2.2 and zxing-wasm 3.1.3 (MIT), built on ZXing-C++ (Apache License 2.0).')));
  }

  // Note 03 R11: the Open Food Facts notice (ODbL §4.3), how this app changes that data (§4.6: the mapping code), the
  // USDA citation. External links open in a new tab, as user navigation.
  function dataSources() {
    // Links to other sites open in a new tab; the preview's sandboxed frame cannot, so it shows the address (KH.scan.newTab).
    const ext = (href, text) => (KH.scan ? KH.scan.newTab(href, text)
      : h('a', { href, target: '_blank', rel: 'noopener noreferrer' }, text, h('span', { class: 'sr-only' }, ' (opens in a new tab)')));
    const O = KH.off;
    return h('ul', { class: 'about-list' },
      h('li', {}, 'Contains information from ', ext(O ? O.HOME_URL : 'https://world.openfoodfacts.org', 'Open Food Facts'),
        ', which is made available here under the ', ext(O ? O.LICENSE_URL : 'https://opendatacommons.org/licenses/odbl/1-0/', 'Open Database License (ODbL)'),
        '. How this app changes that data (serving sizes, sodium from salt, additive flags, quality notes): ',
        ext(O ? O.METHOD_URL : 'https://github.com/ksullivan86/kidney-health/blob/main/app/off.py', 'app/off.py'), '.'),
      h('li', {}, 'U.S. Department of Agriculture, Agricultural Research Service. FoodData Central, ',
        ext('https://fdc.nal.usda.gov/', 'fdc.nal.usda.gov'), ' (SR Legacy for the built-in foods; Branded Foods for barcodes and imports).'),
      h('li', {}, 'Barcodes are read on your device; only the number goes to this server, which asks Open Food Facts (when your admin has turned it on and you agreed) and USDA (when a key is set up).'));
  }

  // Where the handbook is (js/learn.js asks the server): this server's copy at /learn, the public copy,
  // or neither. Same window for the handbook itself, a new tab for the public copy next to it.
  function handbookAbout() {
    const L = KH.learn;
    const url = L ? L.href('') : null;
    const intro = h('p', {}, 'What to eat at each stage, lab results explained, treating a low, sick days, and when to get help now: '
      + 'written for people with kidney disease and type 1 diabetes and their families, with sources. Education, not medical advice.');
    if (!url) {
      return h('div', {}, intro, h('p', { class: 'hint' }, MOCK
        ? 'The handbook is not part of this demo; the installed app serves it at /learn.'
        : 'This server has no copy of the handbook and no public copy is set (your admin can set HANDBOOK_PUBLIC_URL).'));
    }
    const items = [h('li', {}, h('a', { href: url }, 'Open the handbook'),
      L.available() ? ' (served by this server, so it works without internet)' : ' (the public copy)')];
    const pub = L.publicUrl();
    if (L.available() && pub) {
      items.push(h('li', {}, 'Public copy to share: ',
        h('a', { href: pub, target: '_blank', rel: 'noopener' }, pub, h('span', { class: 'sr-only' }, ' (opens in a new tab)'))));
    }
    return h('div', {}, intro, h('ul', { class: 'about-list' }, items));
  }

  // ---------------------------------------------------------------------------
  // The view
  // ---------------------------------------------------------------------------
  function renderWho() {
    const me = state.me;
    $('#settings-who').textContent = me ? `Signed in as ${me.display_name ? `${me.display_name} (${me.username})` : me.username}${me.role === 'admin' ? ' · admin' : ''}` : '';
  }
  function renderNav() {
    const nav = $('#settings-nav');
    clear(nav);
    for (const sec of $$('.settings-section')) {
      if (sec.hidden) continue;
      const btn = h('button', { class: 'chip nav-chip', type: 'button' }, sec.dataset.title);
      btn.addEventListener('click', () => {
        const head = $('h2', sec);
        sec.scrollIntoView({ block: 'start', behavior: 'smooth' });
        if (head) { head.setAttribute('tabindex', '-1'); head.focus({ preventScroll: true }); }
      });
      nav.append(h('li', {}, btn));
    }
  }
  async function load() {
    if (!state.me) return;
    renderWho();
    $('#set-admin').hidden = !isAdmin();
    renderNav();
    renderAccount();
    renderPrefs();
    if (KH.guidance) KH.guidance.renderSettings().catch((err) => console.warn('Meal guidance settings:', err)); // js/views/guidance.js
    renderAi();
    renderAbout();
    cache.myKeys = null;
    renderFood();
    renderDevice().catch((err) => console.warn(err));
    renderAdminFrame();
    const [settings, keys] = await Promise.allSettled([api.mySettings(), api.myKeys()]);
    cache.mySettings = settings.status === 'fulfilled' ? settings.value.settings : settings.reason;
    cache.myKeys = keys.status === 'fulfilled' ? keys.value : keys.reason;
    renderThemeSource();
    renderLabUnits();
    renderFood();
    if (!state.profile) { try { await KH.loadProfile(); renderPrefs(); } catch (e) { /* Preferences shows Monday */ } }
  }
  // After sign-in: apply the theme saved to the account (an admin default counts too).
  async function onSignedIn() {
    try {
      const res = await api.mySettings();
      cache.mySettings = res.settings;
      const t = res.settings['ui.theme'];
      if (t && t.source !== 'default') {
        const mode = themeFromServer(t.value);
        if (mode !== KH.theme.stored()) KH.theme.apply(mode);
      }
    } catch (e) { /* keep this device's theme */ }
  }

  $('#settings-open').addEventListener('click', () => router.show('settings'));
  router.register('settings', () => {
    load().catch(toastError);
    setTimeout(() => { const t = $('#settings-title'); if (t && state.view === 'settings') t.focus({ preventScroll: true }); }, 0);
  });
  KH.views.settings = { load, onSignedIn, keyWidget, APP_VERSION };
})();
