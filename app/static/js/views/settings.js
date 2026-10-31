/* Kidney Diet Log — Settings view (note 07 §4.17; note 02 R10 for This device).

   Sections: Account (name, password, two-step sign-in from js/views/two_step.js, passkeys from js/views/passkeys.js, signed-in devices, export, delete, sign out), Preferences
   (theme, week start, units), Food data (USDA key, Open Food Facts), AI ideas (filled by M2),
   Assistant access (personal tokens for a chat assistant; only while the admin switch is on, see
   renderAssistant), This device (install, offline, storage; completed by js/pwa.js in the installed
   app), Admin (admins only: a link to Server administration) and About & privacy.

   Server administration (v0.3.1, docs/dev/plans/v0.3.1.md item 3) is its own view (#admin), opened from the
   header shield that only admins see and from Settings → Admin: people and invites, server settings, shared
   keys, usage, activity, about this server, and AI providers (js/views/ai.js). A member who opens #admin gets a
   short note and no request; every /api/admin route checks the role on the server anyway.

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
  const APP_VERSION = '0.18.0';

  const A = {
    sessions: () => request('GET', '/api/me/sessions'),
    revokeSession: (id) => request('DELETE', `/api/me/sessions/${encodeURIComponent(id)}`),
    revokeOthers: () => request('POST', '/api/me/sessions/revoke-others'),
    changePassword: (b) => request('POST', '/api/me/password', b),
    deleteMe: (b) => request('DELETE', '/api/me', b),
    activity: () => request('GET', '/api/me/activity?limit=20'),
    // The file is the person's own export.json; dry_run only counts, nothing is kept (app/data_import.py).
    importData: (body, o) => request('POST', `/api/me/import?${['dry_run', 'merge', 'replace_profile'].filter((k) => o[k]).map((k) => `${k}=1`).join('&')}`, body),
    tokens: () => request('GET', '/api/me/tokens'),
    createToken: (b) => request('POST', '/api/me/tokens', b),
    revokeToken: (id) => request('DELETE', `/api/me/tokens/${encodeURIComponent(id)}`),
    // Phone shortcuts: the device family of the same table (app/push.py, docs/push.md)
    deviceTokens: () => request('GET', '/api/me/tokens?family=device'),
    deleteTokenRows: (id) => request('DELETE', `/api/me/tokens/${encodeURIComponent(id)}/body-rows`),
    users: () => request('GET', '/api/admin/users'),
    createUser: (b) => request('POST', '/api/admin/users', b),
    updateUser: (id, b) => request('PATCH', `/api/admin/users/${id}`, b),
    deleteUser: (id, b) => request('DELETE', `/api/admin/users/${id}`, b),
    resetLink: (id) => request('POST', `/api/admin/users/${id}/reset-link`),
    revokeResetLink: (id) => request('DELETE', `/api/admin/users/${id}/reset-link`),
    revokeUser: (id) => request('POST', `/api/admin/users/${id}/revoke-sessions`),
    revokeUserTokens: (id) => request('POST', `/api/admin/users/${id}/revoke-tokens`),
    removeUserTwoStep: (id) => request('DELETE', `/api/admin/users/${id}/totp`),
    removeUserPasskeys: (id) => request('DELETE', `/api/admin/users/${id}/passkeys`),
    removeUserOidc: (id) => request('DELETE', `/api/admin/users/${id}/oidc`),
    endUserShares: (id) => request('DELETE', `/api/admin/users/${id}/shares`),
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
  // A link shown once (invite, account setup, password reset), with Copy; also an assistant token (opts).
  function linkBox(url, lines, opts = {}) {
    const id = uid('link');
    const input = h('input', { id, type: 'text', class: 'link-input', readonly: true, value: url, spellcheck: 'false', autocomplete: 'off' });
    const copy = action(opts.copy || 'Copy link', 'primary', async () => {
      if (await copyText(url, input)) toast(opts.copied || 'Link copied', 'ok');
      else toast(`Select the ${opts.copy ? 'token' : 'link'} and copy it (Ctrl+C, or touch and hold on a phone).`);
    });
    const box = h('div', { class: 'link-box', role: 'group', 'aria-label': opts.group || 'Link to send' },
      h('label', { for: id, class: 'label' }, opts.label || 'Link (shown only now)'),
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
    if (hasLocalPassword() && KH.twoStep) body.append(KH.twoStep.block()); // js/views/two_step.js (design note 17)
    if (hasLocalPassword() && KH.passkeys) body.append(KH.passkeys.block()); // js/views/passkeys.js (design note 18)
    if (hasLocalPassword() && KH.oidc) body.append(KH.oidc.block()); // js/views/oidc.js (design note 24): hidden without a provider

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

  // Only the newest load draws: a slow older list could show a device that was signed out since.
  let devicesRequest = 0;
  async function loadDevices() {
    const box = $('#set-devices');
    if (!box) return;
    const req = ++devicesRequest;
    let res;
    try { res = await A.sessions(); } catch (err) {
      if (req === devicesRequest && document.contains(box)) { clear(box); box.append(failed(err)); }
      return;
    }
    if (req !== devicesRequest || !document.contains(box)) return;
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

  // The online demo keeps its data in this browser (the person turned it on): export and import then work in the page.
  const keptHere = () => !!(MOCK && KH.demoLocal && KH.demoLocal.on());
  function dataBlock(me) {
    const wrap = h('div', { class: 'data-block' });
    const msg = statusMsg('set-export-msg');
    wrap.append(h('p', {}, 'Download everything you have entered: a .zip with export.json and spreadsheet (CSV) files for your log, foods, saved meals, lab results, symptoms, weights, blood pressure readings and settings. It holds no passwords, sessions or keys.'));
    wrap.append(h('div', { class: 'settings-actions' }, action(MOCK && keptHere() ? 'Export my data (export.json)' : 'Export my data (.zip)', 'secondary', async () => {
      if (MOCK && keptHere()) { // "Keep my data in this browser" is on (the Pages demo, js/views/demo_local.js): the file the zip would hold
        msg.textContent = 'Preparing your export…';
        try {
          const res = await KH.demoLocal.exportFile();
          msg.textContent = `Saved ${res.name} (${fmtBytes(res.bytes)}). Keep it somewhere private: it holds your health data.`;
        } catch (err) { msg.textContent = ''; throw err; }
        return;
      }
      if (MOCK) { msg.textContent = 'In the installed app this downloads a .zip of your data. The preview has no server, so there is nothing to download. In the online demo, turn on Keep my data in this browser to try the export and import here.'; return; }
      msg.textContent = 'Preparing your export…';
      try {
        const res = await download('/api/me/export.zip', `${KH.brand.slug}-${me.username}.zip`);
        msg.textContent = `Saved ${res.name} (${fmtBytes(res.bytes)}). Keep it somewhere private: it holds your health data.`;
      } catch (err) { msg.textContent = ''; throw err; }
    }, { id: 'set-export' })), msg);
    // The online demo only: the way back to the "Keep my data in this browser" sheet once the banner has been dismissed.
    if (MOCK && PREVIEW && KH.demoLocal && KH.demoLocal.open) {
      wrap.append(h('div', { class: 'settings-actions' }, action(keptHere() ? 'Manage the data kept here' : 'Keep my data in this browser', 'secondary',
        async (btn) => KH.demoLocal.open(btn), { id: 'set-demo-local' })));
    }
    wrap.append(importBlock());
    wrap.append(bodyImportBlock());
    wrap.append(pushBlock());

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

  // "Import from Apple Health" (past weights and blood pressure readings from the Health app's export.xml): the page that reads the
  // file is another module's (KH.bodyImport, js/views/body_import.js); with no such module there is no button.
  function bodyImportBlock() {
    const wrap = h('div', { class: 'import-block', id: 'set-body-import' });
    if (!(KH.bodyImport && typeof KH.bodyImport.open === 'function')) { wrap.hidden = true; return wrap; }
    wrap.append(subtitle('Weights and blood pressure from Apple Health', 'set-body-import-h'),
      h('p', {}, 'Bring in past weights and blood pressure readings from the iPhone Health app. The file is read on this device; only the rows you choose are sent to your server.'),
      h('div', { class: 'settings-actions' }, action('Import from Apple Health', 'secondary', async (b) => KH.bodyImport.open(b), { id: 'set-body-import-open' })));
    return wrap;
  }
  // ---------------------------------------------------------------------------
  // Import from a file (POST /api/me/import, app/data_import.py). The file is read in this browser, checked by the
  // server with ?dry_run=1 (nothing is kept), and only imported when the person presses Import. The person chooses the
  // export .zip itself or the export.json inside it: a .zip is opened here, on the device, by KH.zip (js/engine/zip.js,
  // docs/dev/research/11-reading-a-zip-in-the-browser.md), which reads only export.json out of it; nothing else in the
  // .zip is looked at, and the server never sees the archive.
  // ---------------------------------------------------------------------------
  // The server's own limit is MAX_IMPORT_BYTES (16 MiB unless the admin changed it); this only saves a pointless upload.
  const IMPORT_MAX_BYTES = 16 * 1024 * 1024;
  // What the person is told when the .zip cannot be read, by KH.zip's error code (too_big is worded where the size is known).
  const IMPORT_ZIP_UNREADABLE = 'This .zip could not be read (it may be damaged or not finished downloading). Download the export again, or open it on your device and choose the export.json inside it.';
  const IMPORT_ZIP_MESSAGE = {
    missing: 'This .zip has no export.json in it, so it is not an export from this app.',
    ambiguous: 'This .zip holds more than one export.json. Open it and choose the one you want.',
    browser: 'This browser cannot open a .zip here. Open the .zip on your device and choose the export.json inside it.',
  };
  // Parts of an export the import never reads (AI activity, sign-in activity, the account itself): not even sent.
  const IMPORT_NEVER_SENT = ['user', 'ai_audit', 'activity', 'ai_usage', 'ai_consents', 'ai_provider', 'activity_days', 'activity_workouts', 'activity_extra', 'care_suggestions'];
  const IMPORT_KINDS = [
    ['log_entries', 'log entry', 'log entries'],
    ['custom_foods', 'food of yours', 'foods of yours'],
    ['shared_foods_kept_as_own', 'shared food kept as your own copy', 'shared foods kept as your own copies'],
    ['shared_foods_linked', 'shared food linked to you', 'shared foods linked to you'],
    ['meal_templates', 'saved meal', 'saved meals'],
    ['lab_results', 'lab result', 'lab results'],
    ['symptoms', 'symptom', 'symptoms'],
    ['weights', 'weight', 'weights'],
    ['blood_pressures', 'blood pressure reading', 'blood pressure readings'],
    ['food_preferences', 'food preference', 'food preferences'],
    ['settings', 'setting', 'settings'],
  ];
  const IMPORT_SKIP_WHAT = { log_entries: 'Log entry', meal_templates: 'Saved meal', symptoms: 'Symptom', weights: 'Weight', blood_pressures: 'Blood pressure reading',
    food_preferences: 'Food preference', settings: 'Setting' };
  const IMPORT_SKIP_SHOWN = 12;
  const importCount = (n, one, many) => `${n} ${n === 1 ? one : many}`;
  function importLines(counts) {
    const lines = IMPORT_KINDS.filter(([k]) => counts[k] > 0).map(([k, one, many]) => importCount(counts[k], one, many));
    if (counts.profile) lines.push('your profile and targets');
    return lines;
  }
  // "2 log entries, 1 food of yours, 1 saved meal, 0 lab results, 0 symptoms, 0 weights, 0 blood pressure readings" for the sizes of a file or an account.
  function importSizes(r) {
    return [importCount(r.log_entries || 0, 'log entry', 'log entries'), importCount(r.custom_foods || 0, 'food of yours', 'foods of yours'),
      importCount(r.meal_templates || 0, 'saved meal', 'saved meals'), importCount(r.lab_results || 0, 'lab result', 'lab results'),
      importCount(r.symptoms || 0, 'symptom', 'symptoms'), importCount(r.weights || 0, 'weight', 'weights'),
      importCount(r.blood_pressures || 0, 'blood pressure reading', 'blood pressure readings')].join(', ');
  }
  function importBlock() {
    const wrap = h('div', { class: 'import-block', id: 'set-import' }, subtitle('Import from a file', 'set-import-h'));
    wrap.append(h('p', {}, 'Moving to another server, or starting again? Choose the .zip from an export of yours, or the export.json inside it. You see what would be added before anything is changed.'));
    const msg = statusMsg('set-import-msg');
    if (MOCK && !(KH.demoLocal && KH.demoLocal.on())) { // the online demo with "Keep my data in this browser" on imports like a server (js/mock/import.js)
      wrap.append(h('p', { class: 'hint', id: 'set-import-demo' }, 'The preview has no server to import into. In the installed app you choose the export .zip or the export.json here, check what would be added, then import it.'), msg);
      return wrap;
    }
    const fileId = 'set-import-file';
    const input = h('input', { type: 'file', id: fileId, class: 'ai-file', accept: '.zip,.json,application/zip,application/json', 'aria-describedby': 'set-import-hint set-import-msg' });
    const result = h('div', { class: 'import-result', id: 'set-import-result' });
    wrap.append(h('div', { class: 'field' }, h('label', { for: fileId }, 'Your export (.zip or export.json)'), input,
      h('span', { class: 'hint', id: 'set-import-hint' }, `The export.json can be up to ${fmtBytes(IMPORT_MAX_BYTES)}. Passwords, sign-in sessions, assistant tokens and keys are never imported, even if a file has them.`)), msg, result);

    let payload = null; // the parsed file, kept only while the person decides
    const options = { merge: false, replace_profile: false };
    // Forget the file and what was chosen; `keepFile` leaves the file input alone (the person has just picked a new one).
    let latest = 0; // an answer to an older check is dropped
    let opening = null; // the AbortController of a .zip being read, so that a new choice or a Cancel stops it
    const reset = (keepFile) => {
      latest += 1;
      if (opening) { opening.abort(); opening = null; }
      payload = null; options.merge = false; options.replace_profile = false;
      if (!keepFile) input.value = '';
      clear(result);
    };

    async function check(focusId) {
      const mine = ++latest;
      msg.textContent = 'Checking the file…';
      try {
        const res = await A.importData(payload, { ...options, dry_run: true });
        if (mine !== latest) return;
        msg.textContent = '';
        render(res, focusId);
      } catch (err) {
        if (mine !== latest) return;
        clear(result);
        // A closed password prompt forgets the file too, so choosing the same file again fires `change` and checks it again.
        if (err && err.cancelled) reset(false);
        msg.textContent = err && err.cancelled ? 'Not checked: the password prompt was closed.' : '';
        if (!err.handled && !err.cancelled) result.append(h('div', { class: 'form-error', role: 'alert' }, h('p', {}, err.detail || err.message)));
      }
    }
    function option(id, key, label, help, checked) {
      const box = h('input', { type: 'checkbox', id, 'aria-describedby': `${id}-help` });
      box.checked = checked;
      box.addEventListener('change', () => { options[key] = box.checked; check(id); });
      return h('label', { class: 'check', for: id }, box, h('span', { class: 'check-text' }, label, h('span', { class: 'hint', id: `${id}-help` }, help)));
    }
    function list(items) { return h('ul', { class: 'about-list' }, items.map((t) => h('li', {}, t))); }
    function render(res, focusId) {
      clear(result);
      const f = res.file || {};
      const rec = f.records || {};
      const heading = h('h4', { class: 'import-title', tabindex: '-1', id: 'set-import-title' }, 'What this file would add');
      result.append(heading,
        h('p', {}, `Exported ${f.exported_at ? fmtDate(f.exported_at) : 'at an unknown time'}${f.app_version ? ` by version ${f.app_version}` : ''}: ${importSizes(rec)}.`));
      if (res.blocked) {
        const e = res.blocked.existing || {};
        result.append(note('caution', h('p', {}, `This account already has data (${importSizes(e)}), so nothing is imported unless you choose “Add to my existing data”.`)));
      }
      result.append(option('set-import-merge', 'merge', 'Add to my existing data', 'Whatever is already here is left out, so importing the same file again adds nothing.', options.merge));
      if (rec.profile) {
        result.append(option('set-import-profile', 'replace_profile', 'Also replace my profile, targets and settings',
          'Off by default: targets and meal-guidance settings may have been agreed with your care team on this server. Your Open Food Facts and AI choices are never imported.', options.replace_profile));
      }
      if (res.can_import) {
        const lines = importLines(res.counts);
        result.append(h('p', { class: 'import-sub' }, lines.length ? 'Will be added:' : 'Nothing new to add.'));
        if (lines.length) result.append(list(lines));
        const there = IMPORT_KINDS.filter(([k]) => (res.already_there || {})[k] > 0).map(([k, one, many]) => importCount(res.already_there[k], one, many));
        if (there.length) result.append(h('p', { class: 'import-sub' }, 'Already here, so left out:'), list(there));
        const sk = res.skipped || { total: 0, shown: [] };
        if (sk.total) {
          result.append(h('p', { class: 'import-sub', id: 'set-import-skipped-h' }, `${sk.total} ${sk.total === 1 ? 'item' : 'items'} cannot be matched and will be left out:`),
            list(sk.shown.slice(0, IMPORT_SKIP_SHOWN).map((s) => `${IMPORT_SKIP_WHAT[s.kind] || s.kind} ${s.label ? `“${s.label}”` : ''}: ${s.reason}.`)));
          if (sk.total > IMPORT_SKIP_SHOWN) result.append(h('p', { class: 'hint' }, `And ${sk.total - IMPORT_SKIP_SHOWN} more.`));
        }
        if ((res.not_selected || []).length) result.append(h('p', { class: 'hint' }, `Not imported, because you did not choose it: ${res.not_selected.join(' and ')}.`));
      }
      result.append(h('details', { class: 'settings-details', id: 'set-import-never' }, h('summary', {}, 'What is never imported'), list(res.not_imported || [])),
        h('details', { class: 'settings-details', id: 'set-import-rule' }, h('summary', {}, 'How duplicates are handled'), h('p', {}, res.rule || '')));
      const go = action('Import', 'primary', async () => {
        const done = await A.importData(payload, { ...options, dry_run: false });
        const lines = importLines(done.counts);
        const sentence = lines.length ? `Imported ${lines.join(', ')}.` : 'Nothing new was imported.';
        reset();
        msg.textContent = sentence;
        toast(sentence, 'ok');
        // Everything the other views keep is stale now.
        state.dayLoadedFor = null; state.plan = null; state.planStart = null; state.trends = null; state.summary = null; state.shopping = null;
        KH.invalidateSharedCaches();
        if (KH.labs) KH.labs.invalidate();
        try { await KH.loadProfile(true); } catch (e) { /* the next visit loads it */ }
      }, { id: 'set-import-go' });
      go.disabled = !res.can_import;
      const cancel = action('Cancel', 'secondary', async () => { reset(); msg.textContent = 'Nothing was imported.'; }, { id: 'set-import-cancel' });
      result.append(h('div', { class: 'settings-actions' }, go, cancel));
      const target = focusId ? $(`#${focusId}`) : heading;
      if (target) target.focus();
    }

    // The text of the export.json inside a .zip, or null once the reason is on the screen (or the choice has moved on).
    async function textFromZip(file, mine) {
      const zip = KH.zip;
      if (!zip || !zip.supported()) { msg.textContent = IMPORT_ZIP_MESSAGE.browser; return null; }
      msg.textContent = 'Reading the file…';
      const ctrl = new AbortController();
      opening = ctrl;
      let entry = null;
      try {
        const archive = await zip.open(file);
        entry = zip.find(archive, zip.RULES.exportJson);
        return await zip.text(archive, entry, { maxBytes: IMPORT_MAX_BYTES, signal: ctrl.signal });
      } catch (err) {
        if (mine !== latest) return null; // another file was chosen, or Cancel was pressed
        const code = err && err.code;
        msg.textContent = code === 'too_big' && entry
          ? `The export.json in that .zip is ${fmtBytes(entry.size)}; the largest this app imports is ${fmtBytes(IMPORT_MAX_BYTES)}.`
          : IMPORT_ZIP_MESSAGE[code] || IMPORT_ZIP_UNREADABLE;
        return null;
      } finally {
        if (opening === ctrl) opening = null;
      }
    }

    input.addEventListener('change', async () => {
      const file = input.files && input.files[0];
      reset(true);
      msg.textContent = '';
      if (!file) return;
      const mine = latest;
      let doc = null;
      if (/\.zip$/i.test(file.name) || file.type === 'application/zip') {
        const text = await textFromZip(file, mine);
        if (text === null || mine !== latest) return;
        try { doc = JSON.parse(text); } catch (e) { doc = null; }
      } else {
        if (file.size > IMPORT_MAX_BYTES) { msg.textContent = `That file is ${fmtBytes(file.size)}; the largest this app imports is ${fmtBytes(IMPORT_MAX_BYTES)}.`; return; }
        msg.textContent = 'Reading the file…';
        try { doc = JSON.parse(await file.text()); } catch (e) { doc = null; }
        if (mine !== latest) return;
      }
      if (!doc || typeof doc !== 'object' || Array.isArray(doc)) { msg.textContent = 'This is not an export.json file (it is not JSON). Choose the export.json from your export.'; return; }
      for (const key of IMPORT_NEVER_SENT) delete doc[key];
      payload = doc;
      await check(null);
    });
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
    'data.imported': 'Data imported',
    'account.deleted': 'Account deleted', 'secret_key.rotated': 'Secret key rotated', 'backup.created': 'Backup created',
    'api_token.created': 'Assistant token created', 'api_token.revoked': 'Assistant token revoked', 'body.token_rows_deleted': 'Phone shortcut data deleted',
    'assistant.food_logged': 'Assistant saved food', 'assistant.recipe_saved': 'Assistant saved a recipe', 'assistant.preference_set': 'Assistant remembered a taste',
    'ai.trust_changed': 'Trust in the assistant changed',
    'totp.enabled': 'Two-step sign-in turned on', 'totp.disabled': 'Two-step sign-in turned off', 'totp.recovery_codes_renewed': 'New recovery codes made',
    'totp.recovery_code_used': 'Signed in with a recovery code',
    'passkey.added': 'Passkey added', 'passkey.removed': 'Passkey removed', 'passkey.counter_went_back': 'Copied passkey refused',
    'share.code_created': 'Care team link made', 'share.code_cancelled': 'Care team link cancelled', 'share.accepted': 'Someone joined your Care team with a link',
    'share.ended': 'Someone left your Care team', 'share.viewed': 'Someone on your Care team looked at what you share',
    'care.invited': 'Care team invite sent', 'care.invite_cancelled': 'Care team invite cancelled', 'care.invite_answered': 'Someone answered your Care team invite',
    'care.role_changed': 'Care team role changed', 'care.plan_changed': 'Your Care helper changed your plan',
    'care.switches_changed': 'Care team switches changed', 'care.food_logged': 'Someone on your Care team logged food you ate',
    'suggestion.sent': 'A meal suggestion from your Care team', 'suggestion.accepted': 'You added a suggestion to your plan',
    'suggestion.declined': 'You said no thanks to a suggestion', 'suggestion.expired': 'A suggestion expired after 14 days',
    'oidc.linked': 'Sign-in provider linked', 'oidc.unlinked': 'Sign-in provider link removed',
    'device.connected': 'Device connected', 'device.disconnected': 'Device disconnected', 'device.sync_failed': 'Device sync stopped working',
    'activity.extra_on': 'Active-day calories turned on', 'activity.extra_off': 'Active-day calories turned off',
    'test_accounts.created': 'Test account made', 'test_accounts.enabled': 'Test account turned on', 'test_accounts.disabled': 'Test account turned off',
    'test_accounts.reset': 'Test accounts reset',
  };
  // The row's label. Tokens come in two families and the details say which one made or lost a token (phone shortcut tokens: family
  // "device"); a revoke of everything a person had at once (an admin, a password change) names no family and says how many.
  const DEVICE_ACTION_LABEL = { 'api_token.created': 'Phone shortcut token created', 'api_token.revoked': 'Phone shortcut token revoked' };
  function actionLabel(ev) {
    const d = ev.details || {};
    if (d.family === 'device' && DEVICE_ACTION_LABEL[ev.action]) return DEVICE_ACTION_LABEL[ev.action];
    if (ev.action === 'api_token.revoked' && d.count != null) return 'Tokens revoked';
    if (ev.action === 'login.failed' && d.via === 'code') return 'Wrong sign-in code entered';
    if (ev.action === 'login.failed' && d.via === 'passkey') return 'Passkey sign-in failed';
    if (ev.action === 'login.succeeded' && d.via === 'passkey') return 'Signed in with a passkey';
    return ACTION_LABEL[ev.action] || ev.action;
  }
  // The choices of Settings → AI features (js/views/ai.js): the activity list names them the way the choice does.
  // The words of Settings → Meal guidance → Your food preferences (a food group's "Not for me" is "Never suggest" there).
  const TASTE_WORD = { none: 'nothing saved', like: 'more like this', less: 'less often', not_for_me: 'not for me', neutral: 'stop learning' };
  const tasteWord = (value, kind) => (kind === 'group' && value === 'not_for_me' ? 'never suggest' : TASTE_WORD[value] || value);
  const TRUST_NAME = { ask: 'Ask me before every save', conversation: 'Trust it for this conversation', always: 'Trust it always' };
  const TOKEN_REVOKED_WHY = { password_changed: 'password changed', password_reset: 'password reset', account_disabled: 'account disabled',
    account_deleted: 'account deleted', admin: 'revoked by an admin', auth_mode_changed: 'sign-in mode changed' };
  // Connected devices (design note 27): the provider's name and the short error code in words.
  const DEVICE_NAME = { withings: 'Withings', whoop: 'Whoop' };
  const DEVICE_ERROR = { auth: 'it needs you to connect again', rate_limited: 'too many requests, paused for an hour',
    unreachable: 'it could not be reached', provider_error: 'it did not answer as expected', scope: 'it was not allowed to read what it needs',
    account_taken: 'that account is connected to someone else here' };
  function eventDetail(ev) {
    const d = ev.details || {};
    if (ev.action === 'settings.changed') return `${(REG.BY_KEY[d.key] || {}).label || d.key}: ${JSON.stringify(d.old)} → ${JSON.stringify(d.new)}${d.env ? ` (first value from ${d.env})` : ''}`;
    if (ev.action === 'secret.set' || ev.action === 'secret.removed') return `${d.provider || ev.target_id} (${d.scope === 'shared' ? 'shared key' : 'own key'})`;
    if (ev.action === 'sessions.revoked' && d.count != null) return d.count === 1 ? '1 device' : `${d.count} devices`;
    if (ev.action === 'user.role_changed') return `${ROLE_LABEL[d.old] || d.old} → ${ROLE_LABEL[d.new] || d.new}`;
    if (ev.action === 'login.failed' && d.via === 'reauth') return 'when asked for the password again';
    if (ev.action === 'user.password_changed' && d.via) return { self: 'by the person', admin_reset_link: 'with an admin reset link', reset_link: 'with a reset link', account_setup: 'first password' }[d.via] || '';
    if (ev.action === 'api_token.created' && d.expires_in_days === 'never') return 'never expires';
    if (ev.action === 'api_token.created' && d.expires_in_days) return `valid for ${EXPIRY_LABEL[d.expires_in_days] || `${d.expires_in_days} days`}`;
    if (ev.action === 'api_token.revoked') return [d.count > 1 ? `${d.count} tokens` : '', TOKEN_REVOKED_WHY[d.reason] || ''].filter(Boolean).join(', ');
    if (ev.action === 'body.token_rows_deleted') return pushCountsText({ weights: d.weights, readings: d.readings }) || 'nothing was left to delete';
    if (ev.action === 'data.imported') {
      return [[d.log_entries, 'entry', 'entries'], [d.custom_foods, 'food', 'foods'], [d.meal_templates, 'saved meal', 'saved meals'], [d.lab_results, 'lab result', 'lab results'], [d.symptoms, 'symptom', 'symptoms'],
        [d.weights, 'weight', 'weights'], [d.blood_pressures, 'blood pressure reading', 'blood pressure readings']]
        .filter(([n]) => n > 0).map(([n, one, many]) => `${n} ${n === 1 ? one : many}`).join(', ') || 'nothing new';
    }
    if (ev.action === 'assistant.food_logged') return `${d.entries} ${d.entries === 1 ? 'entry' : 'entries'}, ${d.status}, ${d.meal} on ${d.date}, with “${d.via}”`;
    if (ev.action === 'assistant.recipe_saved') return `“${d.name}” (${d.ingredients} ingredients), with “${d.via}”`;
    if (ev.action === 'assistant.preference_set') return `${d.name}: ${tasteWord(d.old, d.kind)} → ${tasteWord(d.new, d.kind)}, with “${d.via}”`;
    if (ev.action === 'ai.trust_changed') return `${TRUST_NAME[d.old] || d.old} → ${TRUST_NAME[d.new] || d.new}`;
    if (ev.action === 'totp.disabled') return { self: 'by the person', admin: 'by an admin', cli: 'with the command line' }[d.via] || '';
    if (ev.action === 'totp.enabled' && d.signed_out) return d.signed_out === 1 ? '1 other device signed out' : `${d.signed_out} other devices signed out`;
    if (ev.action === 'totp.recovery_code_used' && d.left != null) return d.left === 1 ? '1 left' : `${d.left} left`;
    if (ev.action === 'passkey.removed') {
      const how = { self: 'by the person', admin: 'by an admin', cli: 'with the command line' }[d.via] || '';
      return [d.count > 1 ? `${d.count} passkeys` : '', how].filter(Boolean).join(', ');
    }
    if (ev.action === 'passkey.added' && d.synced) return 'synced to a cloud account';
    if (ev.action === 'oidc.linked') return { settings: 'from Settings', email: 'by the same email address', invite: 'with an invite link', signup: 'at the first sign-in' }[d.via] || '';
    if (ev.action === 'oidc.unlinked') return { self: 'by the person', admin: 'by an admin' }[d.via] || '';
    if (ev.action === 'login.failed' && d.via === 'oidc') return 'with the sign-in provider';
    if (ev.action === 'login.succeeded' && d.via === 'oidc') return 'with the sign-in provider';
    if (ev.action === 'device.connected') return DEVICE_NAME[d.provider] || d.provider || '';
    if (ev.action === 'device.disconnected') {
      if (d.provider === 'whoop') {
        const n = (d.deleted_days || 0) + (d.deleted_workouts || 0);
        return ['Whoop', n ? `${d.deleted_days || 0} days and ${d.deleted_workouts || 0} workouts deleted` : 'days and workouts kept'].join(', ');
      }
      const gone = (d.deleted_weights || 0) + (d.deleted_readings || 0);
      return [DEVICE_NAME[d.provider] || d.provider || '', gone ? `${gone === 1 ? '1 reading' : `${gone} readings`} deleted` : 'readings kept'].filter(Boolean).join(', ');
    }
    if (ev.action === 'activity.extra_on') return `${d.share_pct}% of the extra${d.ceiling_kcal != null ? `, at most ${d.ceiling_kcal} kcal a day` : ''}`;
    if (ev.action === 'device.sync_failed') return `${DEVICE_NAME[d.provider] || d.provider || ''}: ${DEVICE_ERROR[d.error] || d.error || ''}`;
    if (ev.action === 'passkey.counter_went_back') return 'a passkey answered like an old copy of itself, so the sign-in was refused';
    if ((ev.action === 'share.code_created' || ev.action === 'share.accepted') && KH.sharing && d.areas) return KH.sharing.areasText(d.areas);
    if (ev.action === 'share.ended') return { owner: 'you removed them', grantee: 'they left', admin: 'an admin ended it', time: 'on the end date you chose' }[d.by] || '';
    if (ev.action === 'care.invite_answered') return d.answer === 'declined' ? 'declined' : `accepted, as a ${KH.sharing ? KH.sharing.roleText(d.role) : d.role}`;
    if (ev.action === 'care.role_changed' || ev.action === 'care.invited') return KH.sharing ? `as a ${KH.sharing.roleText(d.role)}` : '';
    if (ev.action === 'care.switches_changed' && KH.sharing) {
      return [d.role === 'custom' ? 'now a custom set of switches' : `now a ${KH.sharing.roleText(d.role)}`, d.food_added ? 'food log shared' : null].filter(Boolean).join(', ');
    }
    if (ev.action === 'suggestion.accepted' && d.skipped) return `${d.skipped} ${d.skipped === 1 ? 'food was' : 'foods were'} left out`;
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
      h('p', { class: 'hint' }, 'Sign-ins, password, key and assistant token changes and exports on your account, newest first, including anything an admin did to it.'));
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
          list.append(h('li', {}, h('span', { class: 'act-what' }, actionLabel(ev), extra || byAdmin ? h('span', { class: 'muted' }, `${extra ? ` · ${extra}` : ''}${byAdmin}`) : null),
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
        offAdmin.locked_by_env ? null : ' Change it in Server administration → Server settings.'));
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
  // Phone shortcuts (docs/dev/research/12-phone-push-tokens.md §4.4; docs/push.md; app/push.py; the handbook's "From a phone shortcut")
  // ---------------------------------------------------------------------------
  // A block of Settings → Your data, in the style of Assistant access. A device token lets a Shortcut on the person's iPhone add their
  // latest weight and blood pressure to their own log: it can only add, it cannot see the log. The block is always there; while the
  // admin switch push.enabled is off it says "Your admin has not turned this on" (and still lists, revokes and deletes). A new token is
  // in the POST answer only: it is shown once, with Copy and the address to send to, until the block is drawn again. The demo has no
  // server to send to and says so. Every word that came from the server (a token's name) is drawn with textContent through h().
  // push block (begin)
  const PUSH_INTRO = 'A shortcut on your iPhone can send your latest weight and blood pressure here. Its token can only add readings: it cannot see your log.';
  const PUSH_PATH = '/push/v1/body';
  const PUSH_RECIPE = 'The step-by-step recipe is in the handbook: Weight and blood pressure, From a phone shortcut.';
  const pushAddress = () => `${window.location.origin}${PUSH_PATH}`;
  const pushNumber = (n, one, many) => `${n} ${n === 1 ? one : many}`;
  let pushDraw = 0; // an answer to an older draw is dropped
  let unshownDevice = null; // the answer of POST /api/me/tokens until a draw has put it on screen (once)
  let pushFirstAction = null; // the first button of the list, for focus after a revoke
  let pushHost = null; // the block on screen, so that an admin's change of the switch can draw it again
  function takeUnshownDevice() { const made = unshownDevice; unshownDevice = null; return made && made.token ? made : null; }

  // "2 weights and 1 blood pressure reading" for { weights, readings }; '' when both are none.
  function pushCountsText(c) {
    const w = Number(c && c.weights) || 0;
    const r = Number(c && c.readings) || 0;
    return [w ? pushNumber(w, 'weight', 'weights') : '', r ? pushNumber(r, 'blood pressure reading', 'blood pressure readings') : ''].filter(Boolean).join(' and ');
  }
  function pushTokenSub(t) {
    const parts = [`${t.prefix}…`, `created ${fmtDate(t.created_at)}`, t.last_used_at ? `last used ${relTime(t.last_used_at)}` : 'never used'];
    if (t.state === 'revoked') parts.push(`revoked ${fmtDate(t.revoked_at)}`);
    else parts.push(expiryText(t));
    const sent = pushCountsText(t.sent);
    parts.push(sent ? `sent ${sent}` : 'nothing sent that is still in your log');
    return parts.join(' · ');
  }
  // The handbook's recipe: a link where the handbook is served (KH.learn), the plain words where it is not.
  function pushRecipe() {
    const info = KH.learn && typeof KH.learn.info === 'function' ? KH.learn.info() : null;
    const page = info && info.links && info.links.pages && info.links.pages.weight_and_blood_pressure;
    const target = page && KH.learn.href(`${page.path}#from-a-phone-shortcut`);
    if (!target) return h('p', { class: 'hint', id: 'set-push-recipe' }, PUSH_RECIPE);
    return h('p', { class: 'hint', id: 'set-push-recipe' },
      h('a', { class: 'learn-more', href: target, target: '_blank', rel: 'noopener' }, 'How to make the shortcut', h('span', { class: 'sr-only' }, ' (opens in a new tab)')),
      ' — the handbook has the steps for the weight and for the blood pressure.');
  }
  // The QR code that pairs the iPhone app (design note 15 §4.3; app/pairing.py): the server's link with this address and the new
  // token, drawn on this page by the vendored QR module of two-step sign-in. None when the server's address is not https:// and a host.
  const PUSH_PAIR = 'Using the iPhone app? Point the iPhone Camera at this code and tap the link. The app asks you before it saves anything.';
  const PUSH_NO_PAIR = 'The iPhone app needs this server at an https:// address. When it has one, make a new token here to get a QR code for the app.';
  const PUSH_QR_FAILED = 'The QR code could not be drawn here. Type the address and paste the token in the app instead.';
  function pushPairBox(made) {
    const box = h('div', { class: 'pair-box', role: 'group', 'aria-label': 'Pair the iPhone app' }, h('p', { class: 'label' }, 'Pair the iPhone app'));
    if (!made.pair_url) {
      box.append(h('p', { class: 'hint' }, PUSH_NO_PAIR));
      return box;
    }
    const art = h('div', { class: 'pair-qr' }, h('p', { class: 'muted small' }, 'Drawing the QR code…'));
    const draw = KH.twoStep && KH.twoStep.qrSvg ? KH.twoStep.qrSvg(made.pair_url, 'QR code to scan with the iPhone Camera') : Promise.reject(new Error('no QR module'));
    draw.then((svg) => art.replaceChildren(svg), () => art.replaceChildren(h('p', { class: 'hint' }, PUSH_QR_FAILED)));
    box.append(h('p', { class: 'hint' }, PUSH_PAIR), art);
    return box;
  }
  function pushTokenBox(made) {
    const address = linkBox(pushAddress(), ['Send to this address with the header Authorization: Bearer and the token.'],
      { label: 'Address to send to', copy: 'Copy address', copied: 'Address copied', group: 'Address to send to' });
    const box = linkBox(made.token, ['It is shown only now. Paste it into your shortcut.', 'It is not shown again. Revoke it here if it is lost.'],
      { label: `Token for “${made.name}” (shown only now)`, copy: 'Copy token', copied: 'Token copied', group: 'New token' }); // built last: it takes the focus
    return [box, address, pushPairBox(made)];
  }
  function pushTokenList(host, tokens) {
    pushFirstAction = null;
    if (!tokens.length) return h('p', { class: 'muted small', id: 'set-push-none' }, 'No tokens yet.');
    const ul = h('ul', { class: 'list device-list', id: 'set-push-list', 'aria-label': 'Your phone shortcut tokens' });
    for (const t of tokens) {
      const li = h('li', { class: `device token-row${t.state === 'active' ? '' : ' token-ended'}` },
        h('div', { class: 'device-main' }, h('span', { class: 'row-title' }, t.name), h('span', { class: 'row-sub' }, pushTokenSub(t))));
      const actions = h('div', { class: 'token-actions' });
      if (t.state === 'active') {
        const revoke = h('button', { class: 'btn secondary', type: 'button', 'aria-label': `Revoke ${t.name}` }, 'Revoke');
        revoke.addEventListener('click', () => confirm.inline(actions, revoke, {
          message: `Revoke “${t.name}”? A shortcut using it stops working at once. What it already sent stays in your log until you delete it.`,
          confirmText: 'Revoke',
          onConfirm: async () => {
            await A.revokeToken(t.id);
            toast(`Revoked ${t.name}`, 'ok');
            await renderPush(host);
            if (pushFirstAction) pushFirstAction.focus();
            return true;
          },
        }));
        actions.append(revoke);
      }
      const sent = pushCountsText(t.sent);
      if (sent) {
        const del = h('button', { class: 'btn secondary', type: 'button', 'aria-label': `Delete what ${t.name} sent` }, 'Delete what it sent');
        del.addEventListener('click', () => confirm.inline(actions, del, {
          message: `Delete the ${sent} that “${t.name}” sent? Weights and readings you typed or imported yourself stay. This cannot be undone.`,
          confirmText: 'Delete',
          onConfirm: async () => {
            const res = await A.deleteTokenRows(t.id);
            // Today and Trends hold the rows they loaded: forget them
            state.dayLoadedFor = null; state.trends = null; state.summary = null;
            toast(`Deleted ${pushCountsText(res && res.deleted) || 'nothing: it had no rows left'}`, 'ok');
            await renderPush(host);
            if (pushFirstAction) pushFirstAction.focus();
            return true;
          },
        }));
        actions.append(del);
      }
      if (actions.children.length) { li.append(actions); if (!pushFirstAction) pushFirstAction = actions.children[0]; }
      ul.append(li);
    }
    return ul;
  }
  function pushTokenForm(host, res, activeCount) {
    if (activeCount >= res.max_active) {
      return h('p', { class: 'hint', id: 'set-push-full' }, `You have ${res.max_active} active phone shortcut tokens, the most allowed. Revoke one to make another.`);
    }
    const name = h('input', { id: 'set-push-name', type: 'text', maxlength: 60, autocomplete: 'off', spellcheck: 'false', 'aria-describedby': 'set-push-name-hint' });
    const expiry = selectEl('set-push-expiry', (res.expiry_days || []).map((d) => [d, EXPIRY_LABEL[d] || `${d} days`]), res.default_expiry_days);
    const neverHint = expiryWarning(expiry, 'set-push-never');
    const err = formError();
    const create = action('Make token', 'primary', async () => {
      clear(err);
      const text = name.value.trim();
      if (!text) { showFormError(err, 'Give the token a name, for example “Morning weight”.'); name.focus(); return; }
      let made;
      try {
        made = await A.createToken({ name: text, expires_in_days: expiryValue(expiry), family: 'device' }); // a password prompt opens here when it is needed
      } catch (e) {
        if (!e.cancelled && !e.handled) showFormError(err, e);
        return;
      }
      await renderPush(host, made);
    }, { id: 'set-push-create' });
    name.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); create.click(); } });
    return h('div', { class: 'settings-form' },
      h('div', { class: 'field' }, h('label', { for: 'set-push-name' }, 'Name'), name,
        h('span', { class: 'hint', id: 'set-push-name-hint' }, 'For example “Morning weight”, so you know which one to revoke.')),
      h('div', { class: 'field' }, h('label', { for: 'set-push-expiry' }, 'Expires after'), expiry, neverHint),
      h('div', { class: 'settings-actions' }, create),
      err);
  }
  // made: the answer of POST /api/me/tokens (with `token`), shown once at the top of "New token" by whichever draw finishes next.
  async function renderPush(host, made = null) {
    if (made) unshownDevice = made;
    const ticket = ++pushDraw;
    if (MOCK) {
      host.replaceChildren(h('p', {}, PUSH_INTRO),
        h('p', { class: 'hint', id: 'set-push-demo' }, 'The preview has no server to send readings to. In the installed app you make a token here, paste it into a Shortcut on your iPhone, and the Shortcut adds your weight and blood pressure to your own log. Your admin turns it on first.'),
        pushRecipe());
      return;
    }
    let res;
    try { res = await A.deviceTokens(); } catch (err) {
      if (ticket !== pushDraw) return;
      const fresh = takeUnshownDevice();
      host.replaceChildren(failed(err), ...(fresh ? pushTokenBox(fresh) : [])); // a new token is never lost because the list could not load
      return;
    }
    if (ticket !== pushDraw) return;
    const tokens = res.tokens || [];
    const active = tokens.filter((t) => t.state === 'active').length;
    const parts = [h('p', {}, PUSH_INTRO)];
    if (!res.enabled) {
      parts.push(h('p', { class: 'setting-status' }, h('span', { class: 'state-pill off' }, 'Turned off on this server')),
        h('p', { class: 'hint', id: 'set-push-off' }, 'Your admin has not turned this on.'));
      if (active) parts.push(h('p', { class: 'hint' }, 'Your tokens do not work while phone shortcuts are off. You can still revoke them and delete what they sent.'));
      if (isAdmin()) parts.push(h('p', { class: 'hint' }, 'Admins: switch "Let people send weights and blood pressure from a phone shortcut" on in Server administration → Server settings (or PUSH_ENABLED). See docs/push.md.'));
    }
    parts.push(pushRecipe());
    if (tokens.length || res.enabled) parts.push(subtitle('Your phone shortcut tokens'), pushTokenList(host, tokens));
    const fresh = takeUnshownDevice();
    if (res.enabled || fresh) parts.push(subtitle('New token', 'set-push-new-h'));
    if (fresh) parts.push(...pushTokenBox(fresh));
    if (res.enabled) parts.push(pushTokenForm(host, res, active));
    host.replaceChildren(...parts);
  }
  function pushBlock() {
    const wrap = h('div', { class: 'import-block push-block', id: 'set-push' }, subtitle('Phone shortcuts', 'set-push-h'));
    const host = h('div', { id: 'set-push-body', role: 'region', 'aria-labelledby': 'set-push-h' }, loading());
    wrap.append(host);
    pushHost = host;
    renderPush(host).catch((e) => console.warn('Phone shortcuts:', e));
    return wrap;
  }
  // push block (end)

  // ---------------------------------------------------------------------------
  // Section: Assistant access (docs/assistant.md; app/auth/api_tokens.py)
  // ---------------------------------------------------------------------------
  // Personal tokens for a chat assistant the person connects. The card shows while the admin switch
  // assistant.enabled is on; while it is off only to admins (where to turn it on) and to a person who still has
  // active tokens (to revoke them). A new token is in the POST answer only: it is shown once, in a box with Copy,
  // until the card is drawn again. The demo makes no tokens and says so.
  const ASSISTANT_INTRO = 'A token lets a chat assistant you connect read your own food log and targets and, only if you allow it '
    + 'when you make the token, also save food and recipes for you and remember your tastes (likes and dislikes). '
    + 'How to connect one is in the app\'s documentation (docs/assistant.md).';
  // What a token may do: every token reads; one made with "Can also save food and recipes" also has assistant:log; one made with
  // "Also let it remember tastes" has assistant:prefs. The two are separate: neither gives the other.
  const canSave = (t) => (t.scopes || []).includes('assistant:log');
  const canTaste = (t) => (t.scopes || []).includes('assistant:prefs');
  function accessWord(t) {
    if (canSave(t) && canTaste(t)) return 'Read, save and tastes';
    if (canTaste(t)) return 'Read and tastes';
    return canSave(t) ? 'Read and save' : 'Read only';
  }
  // "never": a token that lasts until it is removed (design note 24 §13), offered while the server allows it.
  const EXPIRY_LABEL = { 30: '30 days', 90: '90 days', 365: '1 year', never: 'Never (until you remove it)' };
  const NEVER_WARNING = 'This token works until you remove it. Remove a token you no longer use.';
  function expiryValue(select) { return select.value === 'never' ? 'never' : Number(select.value); }
  /** The one-line warning under "Expires after", shown while "Never" is chosen. */
  function expiryWarning(select, id) {
    const hint = h('span', { class: 'hint', id, hidden: select.value !== 'never' }, NEVER_WARNING);
    select.addEventListener('change', () => { hint.hidden = select.value !== 'never'; });
    return hint;
  }
  /** "expires <date>", "expired <date>" or "never expires". */
  function expiryText(t) {
    if (t.never_expires || !t.expires_at) return 'never expires';
    return `${t.state === 'expired' ? 'expired' : 'expires'} ${fmtDate(t.expires_at)}`;
  }
  let assistantRender = 0;
  let unshownToken = null; // the answer of POST /api/me/tokens until a render has put it on screen (once)
  function takeUnshownToken() { const made = unshownToken; unshownToken = null; return made && made.token ? made : null; }
  function tokenBox(made) {
    return linkBox(made.token, ['It is not shown again. Revoke it here if it is lost.'],
      { label: `Token for “${made.name}” (shown only now)`, copy: 'Copy token', copied: 'Token copied', group: 'New token' });
  }
  function tokenSub(t) {
    const parts = [accessWord(t), `${t.prefix}…`, `created ${fmtDate(t.created_at)}`,
      t.last_used_at ? `last used ${relTime(t.last_used_at)}` : 'never used'];
    if (t.state === 'revoked') parts.push(`revoked ${fmtDate(t.revoked_at)}`);
    else parts.push(expiryText(t));
    return parts.join(' · ');
  }
  function focusAssistant() {
    const el = $('#set-assistant-body .token-actions button') || $('#set-token-name') || $('#set-assistant-h');
    if (!el) return;
    if (el.id === 'set-assistant-h') el.setAttribute('tabindex', '-1');
    el.focus();
  }
  function tokenList(tokens) {
    if (!tokens.length) return h('p', { class: 'muted small' }, 'No tokens yet.');
    const ul = h('ul', { class: 'list device-list', 'aria-label': 'Your assistant tokens' });
    for (const t of tokens) {
      const li = h('li', { class: `device token-row${t.state === 'active' ? '' : ' token-ended'}` },
        h('div', { class: 'device-main' }, h('span', { class: 'row-title' }, t.name), h('span', { class: 'row-sub' }, tokenSub(t))));
      if (t.state === 'active') {
        const actions = h('div', { class: 'token-actions' });
        const btn = h('button', { class: 'btn secondary', type: 'button', 'aria-label': `Revoke ${t.name}` }, 'Revoke');
        btn.addEventListener('click', () => confirm.inline(actions, btn, {
          message: `Revoke “${t.name}”? An assistant using it stops working at once.`,
          confirmText: 'Revoke',
          onConfirm: async () => {
            await A.revokeToken(t.id);
            toast(`Revoked ${t.name}`, 'ok');
            await renderAssistant();
            focusAssistant();
            return true;
          },
        }));
        actions.append(btn);
        li.append(actions);
      }
      ul.append(li);
    }
    return ul;
  }
  function newTokenForm(res, activeCount) {
    if (activeCount >= res.max_active) {
      return h('p', { class: 'hint' }, `You have ${res.max_active} active tokens, the most allowed. Revoke one to make another.`);
    }
    const name = h('input', { id: 'set-token-name', type: 'text', maxlength: 60, autocomplete: 'off', spellcheck: 'false', 'aria-describedby': 'set-token-name-hint' });
    const expiry = selectEl('set-token-expiry', (res.expiry_days || []).map((d) => [d, EXPIRY_LABEL[d] || `${d} days`]), res.default_expiry_days);
    const neverHint = expiryWarning(expiry, 'set-token-never');
    const canLog = h('input', { type: 'checkbox', id: 'set-token-can-log', 'aria-describedby': 'set-token-can-log-hint' });
    const canPrefs = h('input', { type: 'checkbox', id: 'set-token-can-prefs', 'aria-describedby': 'set-token-can-prefs-hint' });
    const err = formError();
    const create = action('Create token', 'primary', async () => {
      clear(err);
      const text = name.value.trim();
      if (!text) { showFormError(err, 'Give the token a name, for example the app or device it is for.'); name.focus(); return; }
      let made;
      try {
        made = await A.createToken({ name: text, expires_in_days: expiryValue(expiry), can_log: canLog.checked, can_prefs: canPrefs.checked });
      } catch (e) {
        if (!e.cancelled && !e.handled) showFormError(err, e);
        return;
      }
      await renderAssistant(made);
    }, { id: 'set-token-create' });
    name.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); create.click(); } });
    return h('div', { class: 'settings-form' },
      h('div', { class: 'field' }, h('label', { for: 'set-token-name' }, 'Name'), name,
        h('span', { class: 'hint', id: 'set-token-name-hint' }, 'For example the app or device it is for, so you know which one to revoke.')),
      h('div', { class: 'field' }, h('label', { for: 'set-token-expiry' }, 'Expires after'), expiry, neverHint),
      h('div', { class: 'field' },
        h('label', { class: 'check', for: 'set-token-can-log' }, canLog, h('span', { class: 'check-text' }, 'Can also save food and recipes')),
        h('span', { class: 'hint', id: 'set-token-can-log-hint' }, 'Off: the assistant can only read. On: it can also add entries to your food log and save recipes as saved meals, after it asks you. Each save is listed in your activity.')),
      h('div', { class: 'field' },
        h('label', { class: 'check', for: 'set-token-can-prefs' }, canPrefs, h('span', { class: 'check-text' }, 'Also let it remember tastes (likes and dislikes)')),
        h('span', { class: 'hint', id: 'set-token-can-prefs-hint' }, 'Off: the assistant cannot change your food preferences. On: it can remember that you like a food or kind of food, want it less often or do not want it, and forget one, after it asks you. It cannot change anything about treating a low. You see, change and remove each one in Settings → Meal guidance → Your food preferences, and each change is listed in your activity.')),
      h('div', { class: 'settings-actions' }, create),
      err);
  }
  // made: the answer of POST /api/me/tokens (with `token`). It is shown once, at the top of "New token", by
  // whichever render finishes next (also when the list cannot be loaded), so a new token is never lost.
  async function renderAssistant(made = null) {
    const sec = $('#set-assistant');
    const body = $('#set-assistant-body');
    if (!sec || !body) return;
    if (made) unshownToken = made;
    const ticket = ++assistantRender;
    const show = (visible) => { if (sec.hidden === visible) { sec.hidden = !visible; renderNav(); } };
    if (MOCK) {
      body.replaceChildren(h('p', { class: 'setting-status' }, h('span', { class: 'state-pill off' }, 'Not in the preview')),
        h('p', {}, ASSISTANT_INTRO),
        h('p', { class: 'hint' }, 'Available in the installed app on your own server once the admin turns assistant access on. The demo makes no tokens.'));
      show(true);
      return;
    }
    let res;
    try { res = await A.tokens(); } catch (err) {
      if (ticket !== assistantRender) return;
      const fresh = takeUnshownToken();
      if (!sec.hidden) body.replaceChildren(failed(err), ...(fresh ? [tokenBox(fresh)] : [])); // never a new card just to say it failed
      return;
    }
    if (ticket !== assistantRender) return;
    const tokens = res.tokens || [];
    const active = tokens.filter((t) => t.state === 'active').length;
    if (!res.enabled && !isAdmin() && !active) { takeUnshownToken(); body.replaceChildren(); show(false); return; }
    const parts = [h('p', {}, ASSISTANT_INTRO)];
    if (!res.enabled) {
      parts.push(h('p', { class: 'setting-status' }, h('span', { class: 'state-pill off' }, 'Turned off on this server')));
      if (active) parts.push(h('p', { class: 'hint' }, 'Your tokens do not work while assistant access is off. You can still revoke them.'));
      if (isAdmin()) parts.push(h('p', { class: 'hint' }, 'Admins: switch "Outside AI apps" on in Server administration → Server settings (or ASSISTANT_ENABLED). See docs/assistant.md.'));
    }
    parts.push(subtitle('Your tokens'), tokenList(tokens));
    const fresh = takeUnshownToken();
    if (res.enabled || fresh) parts.push(subtitle('New token', 'set-token-new-h'));
    if (fresh) parts.push(tokenBox(fresh));
    if (res.enabled) parts.push(newTokenForm(res, active));
    body.replaceChildren(...parts);
    show(true);
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
  // auth.require_two_step_admins (design note 17 §10): every admin route answers 403 until this admin turns two-step sign-in on.
  async function adminTwoStepBlocked() {
    const two = await request('GET', '/api/me/totp').catch(() => null);
    return !!(two && two.required && !two.enabled);
  }
  // Two loads can overlap (a second tap on the shield while the first waits): only the newest builds the page, so every part
  // and its id is there once.
  let adminRender = 0;
  async function renderAdminFrame() {
    const ticket = ++adminRender;
    const body = $('#set-admin-body');
    clear(body);
    if (!isAdmin()) {
      body.append(note('info', h('p', {}, 'Server administration is for admins. Ask your admin if your account needs a change.')));
      return;
    }
    const blocked = await adminTwoStepBlocked();
    if (ticket !== adminRender) return; // a newer load builds the page
    if (blocked) {
      clear(body);
      body.append(note('caution', h('p', {}, h('strong', {}, 'This server asks admins to use two-step sign-in. '),
        'Turn it on in Settings → Account → Two-step sign-in, then come back here.')),
      h('div', { class: 'settings-actions' }, h('a', { class: 'btn primary', href: '#settings', id: 'admin-two-step-go' }, 'Open Settings')));
      return;
    }
    const none = authMode() === 'none';
    body.append(h('p', { class: 'hint' }, 'Admins manage accounts and server settings. There is no page here to read anyone else’s log, foods or keys.'));
    if (!none) body.append(subtitle('People', 'set-people-h'), h('div', { id: 'set-people' }, loading()));
    body.append(subtitle('Server settings', 'set-server-h'), h('div', { id: 'set-server' }, loading()));
    body.append(subtitle('Shared keys', 'set-shared-h'), h('div', { id: 'set-shared' }, loading()));
    body.append(subtitle('Usage, last 30 days', 'set-usage-h'), h('div', { id: 'set-usage' }, loading()));
    // Design note 26 (js/views/feedback.js): the test accounts and what testers sent. Not in the demo.
    const testers = !none && !MOCK && KH.feedback;
    if (testers) {
      body.append(subtitle('Test accounts', 'set-testers-h'), h('div', { id: 'set-testers' }, loading()));
      body.append(subtitle('Feedback', 'set-feedback-h'), h('div', { id: 'set-feedback' }, loading()));
    }
    body.append(subtitle('Activity log', 'set-audit-h'), h('div', { id: 'set-audit' }, loading()));
    body.append(subtitle('About this server', 'set-server-about-h'), h('div', { id: 'set-server-about' }, loading()));
    adminSettingsReady = loadServerSettings();
    peopleReady = none ? Promise.resolve() : loadPeople();
    loadSharedKeys();
    loadUsage();
    loadAudit();
    loadServerAbout();
    if (testers) KH.feedback.loadAdmin();
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
    if (u.two_step) badges.push(h('span', { class: 'badge two-step-on' }, 'Two-step sign-in'));
    if (u.passkeys) badges.push(h('span', { class: 'badge passkeys-on' }, u.passkeys === 1 ? '1 passkey' : `${u.passkeys} passkeys`));
    if (u.oidc_links) badges.push(h('span', { class: 'badge passkeys-on' }, 'Linked sign-in'));
    if (u.shares) badges.push(h('span', { class: 'badge shares-on' }, `Care team: ${u.shares}`));
    if (u.test_account) badges.push(h('span', { class: 'badge test-account' }, 'Test account'));
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
  // The instance switches assistant.enabled and push.enabled as the admin's settings list has them (the demo has no such settings).
  function adminSwitchOn(key) {
    const all = cache.adminSettings;
    return !!(all && !(all instanceof Error) && all[key] && all[key].value === true);
  }
  const assistantSwitchOn = () => adminSwitchOn('assistant.enabled');
  const pushSwitchOn = () => adminSwitchOn('push.enabled');
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
    // Role (a test account is never an admin: design note 26)
    const roleId = uid('role');
    const roleSel = selectEl(roleId, [['user', 'Member'], ['admin', 'Admin']], u.role);
    if (u.test_account) roleSel.disabled = true;
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
    // Tokens (docs/assistant.md, docs/push.md): the person's assistant tokens and phone shortcut tokens, ended together. Shown while one of the
    // two admin switches is on and the person has active tokens.
    const tokenCount = (Number(u.assistant_tokens) || 0) + (Number(u.device_tokens) || 0);
    if ((assistantSwitchOn() || pushSwitchOn()) && tokenCount > 0) {
      const rev = h('button', { class: 'btn secondary', type: 'button' }, `Revoke tokens (${tokenCount})`);
      rev.addEventListener('click', () => confirm.inline(actions, rev, {
        message: `Revoke ${tokenCount === 1 ? 'the 1 active token' : `all ${tokenCount} active tokens`} of ${name}? `
          + `Any chat assistant or phone shortcut using ${tokenCount === 1 ? 'it' : 'them'} stops working at once. ${name} can make new ones in Settings.`,
        confirmText: 'Revoke',
        onConfirm: async () => {
          const r = await A.revokeUserTokens(u.id);
          await done(r.revoked === 1 ? `Revoked 1 token of ${name}` : `Revoked ${r.revoked} tokens of ${name}`);
          return true;
        },
      }));
      actions.append(rev);
    }
    // Two-step sign-in (design note 17 §2): for someone who lost both the phone and the recovery codes.
    if (u.two_step) {
      const rm = h('button', { class: 'btn secondary', type: 'button' }, 'Remove two-step sign-in');
      rm.addEventListener('click', () => confirm.inline(actions, rm, {
        message: self ? 'Remove your own two-step sign-in? Signing in then needs only your password.'
          : `Remove two-step sign-in from ${name}? Do this only if ${name} lost both the phone and the recovery codes, and you know it is them asking. `
            + 'They then sign in with the password alone and can turn it on again.',
        confirmText: 'Remove',
        onConfirm: async () => {
          await A.removeUserTwoStep(u.id);
          await done(self ? 'Your two-step sign-in was removed' : `Two-step sign-in removed from ${name}`);
          return true;
        },
      }));
      actions.append(rm);
    }
    // Passkeys (design note 18 §2): for a lost or stolen device.
    if (u.passkeys) {
      const rm = h('button', { class: 'btn secondary', type: 'button' }, 'Remove passkeys');
      rm.addEventListener('click', () => confirm.inline(actions, rm, {
        message: self ? 'Remove all your passkeys? You then sign in with your password.'
          : `Remove all passkeys of ${name}? Do this when a device of theirs is lost or stolen. They sign in with the password and can add new passkeys.`,
        confirmText: 'Remove',
        onConfirm: async () => {
          await A.removeUserPasskeys(u.id);
          await done(self ? 'Your passkeys were removed' : `Passkeys removed from ${name}`);
          return true;
        },
      }));
      actions.append(rm);
    }
    // Linked sign-in (design note 24 §6): for a lost or taken-over provider account.
    if (u.oidc_links) {
      const rm = h('button', { class: 'btn secondary', type: 'button' }, 'Remove linked sign-in');
      rm.addEventListener('click', () => confirm.inline(actions, rm, {
        message: self ? 'Remove your link to the sign-in provider? You then sign in with your password or a passkey.'
          : `Remove the link of ${name} to the sign-in provider? Do this when their provider account is lost or someone else has it. `
            + 'Without a password or passkey they need a reset link from you to get in.',
        confirmText: 'Remove',
        onConfirm: async () => {
          await A.removeUserOidc(u.id);
          await done(self ? 'Your linked sign-in was removed' : `Linked sign-in removed from ${name}`);
          return true;
        },
      }));
      actions.append(rm);
    }
    // The Care team (design notes 19 §5 and 25): when a caregiver relationship has ended badly.
    if (u.shares) {
      const end = h('button', { class: 'btn secondary', type: 'button' }, 'End Care team');
      end.addEventListener('click', () => confirm.inline(actions, end, {
        message: self ? 'End your whole Care team, its links and invites, and every Care team you are on?'
          : `End ${name}'s whole Care team, its links and invites, and every Care team they are on?`,
        confirmText: 'End Care team',
        onConfirm: async () => {
          await A.endUserShares(u.id);
          await done(self ? 'Your Care team was ended' : `Care team ended for ${name}`);
          return true;
        },
      }));
      actions.append(end);
    }
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
        h('div', { class: 'form-grid align-end' },
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
    ['Sign-in and registration', ['instance.name', 'registration.mode', 'registration.invite_ttl_days', 'auth.require_two_step_admins']],
    // Design note 24: who may sign in with the provider (the connection itself is env only: OIDC_ENABLED, OIDC_ISSUER, ...).
    ['Single sign-on', ['auth.oidc.button_label', 'auth.oidc.allow_signup', 'auth.oidc.link_by_email', 'auth.oidc.allowed_domains',
      'auth.oidc.admin_groups']],
    ['Food data', ['food.off_enabled', 'food.off_contact', 'food.off_rate_per_minute', 'food.barcode_negative_ttl_hours', 'food.usda_branded_barcode',
      'providers.usda.shared_enabled', 'providers.usda.user_keys_allowed', 'providers.usda.daily_limit_per_user']],
    ['Default for everyone', ['ui.theme', 'user.units.labs', 'user.units.weight']],
    ['Personalised targets and lab results', ['targets.lab_rules_enabled', 'targets.default_activity', 'targets.lab_fresh_days.potassium',
      'targets.lab_fresh_days.phosphate', 'targets.lab_fresh_days.albumin', 'targets.lab_fresh_days.bicarbonate']],
    ['Meal guidance', ['guidance.enabled', 'guidance.pool_per_role', 'guidance.beam_width', 'guidance.plan_days_max', 'guidance.plan_days_ai_max']],
    // The master switch first: Settings → AI features sends admins here to turn it on.
    ['Optional AI', ['ai.enabled', 'ai.user_keys_allowed', 'ai.allow_user_base_url', 'ai.shared_daily_limit', 'ai.max_concurrency',
      'ai.vision_plate_enabled', 'ai.vision_allow_agent', 'ai.chat_enabled', 'ai.voice_enabled', 'ai.allow_trusted_saves', 'ai.recipe_steps', 'ai.audit_retention_days', 'assistant.enabled']],
    // Drawn by js/views/ai_routing.js in Server administration → AI providers (a provider must be private to be local, so these
    // are not edited one by one here): the list shows a pointer instead of rows.
    ['Which AI each feature uses', ['ai.route.photos', 'ai.route.meal_ideas', 'ai.route.describe', 'ai.route.chat', 'ai.route.labs',
      'ai.route.recipes', 'ai.route.local_provider', 'ai.route.cloud_provider']],
    ['Phone shortcuts', ['push.enabled']],
    ['Tokens for outside apps and phone shortcuts', ['tokens.allow_never_expiring']],
    ['Care team', ['sharing.enabled']],
    ['Connected devices', ['devices.enabled', 'devices.sync_hours']],
    ['Shopping list app and recipe import', ['lists.sync_enabled', 'recipes.import_enabled']],
    // Design note 26: not in the demo (it has no accounts of its own to make).
    ['Test accounts', ['test_accounts.enabled', 'test_accounts.ai']],
    ['Activity log', ['audit.retention_days']],
  ];
  const ROUTING_GROUP = 'Which AI each feature uses';
  const CHOICE_LABEL = {
    'registration.mode': { invite: 'Invite links (recommended)', closed: 'Closed: admins create accounts', open: 'Open: anyone who can reach the page (HTTPS only)' },
    'ui.theme': { system: 'Match each device', light: 'Light', dark: 'Dark' },
    'user.units.labs': { us: 'US: mg/dL, g/dL, mg/g, %', si: 'SI: mmol/L, µmol/L, g/L, mg/mmol, mmol/mol' },
    'user.units.weight': { lb: 'Pounds (lb)', kg: 'Kilograms (kg)' },
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
    const shown = (k) => all[k] && !(MOCK && k.startsWith('test_accounts.')); // the demo has no test accounts (design note 26)
    const groups = GROUPS.map(([title, keys]) => [title, keys.filter(shown)]);
    const other = Object.keys(all).filter((k) => shown(k) && !GROUPS.some(([, keys]) => keys.includes(k)));
    if (other.length) groups.push(['Other', other]);
    for (const [title, keys] of groups) {
      if (!keys.length) continue;
      if (title === ROUTING_GROUP) {
        box.append(h('h4', { class: 'settings-minor' }, title),
          h('p', { class: 'hint' }, 'Set in the AI section below (Which AI does each feature use?): a local AI must be on your own network, and the table says what each choice sends where.'));
        continue;
      }
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
        // An AI switch changes Settings → AI features, the AI providers below and the Add view's AI buttons: ask again, now.
        if (key.startsWith('ai.') && KH.ai) {
          if (typeof KH.ai.forget === 'function') KH.ai.forget();
          KH.ai.renderSettings().catch((e2) => console.warn('AI settings:', e2));
          if (typeof KH.ai.renderAdmin === 'function') KH.ai.renderAdmin().catch((e2) => console.warn('AI providers:', e2));
          if (typeof KH.ai.renderAddSlot === 'function') KH.ai.renderAddSlot().catch((e2) => console.warn('AI buttons:', e2));
        }
        if (key === 'assistant.enabled') {
          renderAssistant().catch((e2) => console.warn('Assistant access:', e2));
          loadPeople(); // "Revoke tokens" shows only while a token switch is on
        }
        if (key === 'push.enabled') {
          if (pushHost) renderPush(pushHost).catch((e2) => console.warn('Phone shortcuts:', e2));
          loadPeople();
        }
        if (key.startsWith('test_accounts.') && KH.feedback) { // the accounts were made, turned on or turned off just now
          loadPeople();
          KH.feedback.loadAdmin();
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
      list.append(h('li', {}, h('span', { class: 'act-what' }, actionLabel(ev), extra ? h('span', { class: 'muted' }, extra) : null),
        h('span', { class: 'act-when muted small' }, `${fmtDateTime(ev.at)} · by ${who}${ev.ip_prefix ? ` · ${ev.ip_prefix}` : ''}`)));
    }
    if (res.events.length >= 30) {
      const last = res.events[res.events.length - 1].id;
      box.append(h('div', { class: 'settings-actions', id: 'set-audit-more' }, action('Show older', 'secondary', async () => { await loadAudit(last); })));
    }
  }

  // A reminder when the last backup is older than a week, or there is none: a backup is the only way back after a lost disk or a
  // bad upgrade. A week is the project's own choice, the most a person should have to type in again.
  const BACKUP_DUE_DAYS = 7; // the server's BACKUP_REMINDER_DAYS default, for a server too old to send it
  function backupDue(lastAt, dueDays = BACKUP_DUE_DAYS, now = Date.now()) {
    if (!dueDays) return null; // BACKUP_REMINDER_DAYS=0: the admin turned this note off
    const days = lastAt ? Math.floor((now - Date.parse(lastAt)) / 86400000) : null;
    if (days != null && days < dueDays) return null;
    const how = KH.learn && typeof KH.learn.href === 'function' ? KH.learn.href('self-hosting/backups/#restore') : null;
    return note('caution', h('p', { id: 'set-backup-due' },
      days == null ? 'No backup has been taken on this server yet. ' : `The last backup is ${days} days old. `,
      'Take one with ', h('code', {}, 'python -m app.admin backup --dir /backups --keep 14'), ' and keep a copy on another machine. ',
      'If your backups run outside the app, end each one with ', h('code', {}, 'python -m app.admin record-backup'), '. ',
      how ? h('a', { class: 'learn-more', href: how, target: '_blank', rel: 'noopener' }, 'How to restore a backup', h('span', { class: 'sr-only' }, ' (opens in a new tab)'))
        : 'The handbook page "Backups" says how to restore one.'));
  }

  // ---- About this server
  function deviceRows(dev) {
    if (!dev) return [];
    const rows = [['Connected devices', dev.enabled ? 'On' : 'Off (DEVICES_ENABLED)']];
    for (const p of dev.providers || []) {
      const people = Object.values(p.connected || {}).reduce((n, x) => n + x, 0);
      const waiting = (p.connected || {}).needs_reconnect || 0;
      rows.push([p.name, p.enabled
        ? `client ${p.client_id || 'not set'}, secret ${p.secret}, return address ${p.redirect_uri || 'needs PUBLIC_URL'}, ${people === 1 ? '1 person' : `${people} people`} connected${waiting ? ` (${waiting} must connect again)` : ''}`
        : `Off (${String(p.id || 'withings').toUpperCase()}_ENABLED)${people ? `, ${people === 1 ? '1 person' : `${people} people`} still connected` : ''}`]);
    }
    return rows;
  }
  async function loadServerAbout() {
    const box = $('#set-server-about');
    if (!box) return;
    let a;
    try { a = await A.about(); } catch (err) { clear(box); box.append(failed(err)); return; }
    clear(box);
    const sk = a.secret_key || {};
    const secrets = sk.secrets || {};
    const proxy = a.proxy || {};
    const oidc = a.oidc || {};
    // Each sign-in provider (design note 24 §10, §13): its connection and whether the server reached it, never its client secret.
    const oidcProviders = Array.isArray(oidc.providers) && oidc.providers.length ? oidc.providers
      : (oidc.enabled ? [{ id: 'default', label: '', issuer: oidc.issuer, client_id: oidc.client_id, secret: oidc.secret, redirect_uri: oidc.redirect_uri, discovery: oidc.discovery }] : []);
    const oidcVar = (p) => (p.id && p.id !== 'default' ? `OIDC_${p.id.toUpperCase()}_` : 'OIDC_');
    const oidcDiscovery = (p) => ({ ok: 'reached', blocked_address: `refused: a private address (${oidcVar(p)}ALLOW_PRIVATE_ISSUER)`, dns_failed: 'its name does not resolve',
      unreachable: 'cannot be reached', issuer_mismatch: `it names another issuer (check ${oidcVar(p)}ISSUER, with or without the slash at the end)` })[p.discovery]
      || (p.discovery ? `not reached yet (${p.discovery})` : 'not asked yet');
    const oidcRows = oidcProviders.map((p) => [`Single sign-on: ${p.label ? KH.oidc.shortLabel(p.label) : p.issuer}`,
      `${p.issuer}, client ${p.client_id}, secret ${p.secret}, return address ${p.redirect_uri}, provider ${oidcDiscovery(p)}`]);
    box.append(kv([
      ['Server version', a.version],
      ['Database schema', String(a.schema_version)],
      ['Sign-in', { local: 'Usernames and passwords', proxy: 'Sign-in proxy', none: 'No sign-in (AUTH_MODE=none)' }[a.auth_mode] || a.auth_mode],
      ['Accounts', `${a.accounts.active} active of ${a.accounts.total}`],
      ['HTTPS', a.https ? 'Yes' : 'No: see docs/https.md'],
      ['Public address', a.public_url || 'Not set: links use the address you opened (PUBLIC_URL)'],
      ['Secret key', sk.source === 'auto' ? 'Generated on the data volume' : sk.source === 'env' ? 'From SECRET_KEY' : sk.source === 'file' ? 'From SECRET_KEY_FILE' : String(sk.source || '')],
      ['Stored keys', `${secrets.current || 0} current${secrets.older_key ? `, ${secrets.older_key} under an older key` : ''}${secrets.unreadable ? `, ${secrets.unreadable} unreadable` : ''}`],
      // Sign-in with a provider (design note 24 §10): the connection, never the client secret.
      ['Single sign-on', oidc.enabled ? `On, ${oidcProviders.length === 1 ? 'one provider' : `${oidcProviders.length} providers`}${oidc.only ? ', the only way in (OIDC_ONLY)' : ''}` : 'Off (OIDC_ENABLED)'],
      ...oidcRows,
      // Connected devices (design note 27): each provider's app, never its client secret.
      ...deviceRows(a.devices),
      proxy.ignored_identity_headers ? ['Identity headers ignored', `${proxy.ignored_identity_headers} from untrusted peers (check TRUSTED_PROXIES)`] : null,
      ['Last backup', a.last_backup_at ? fmtDateTime(a.last_backup_at) : 'None recorded (python -m app.admin backup)'],
      a.pre_v3_backup ? ['Pre-v0.3 backup', `${a.pre_v3_backup.path} (${fmtBytes(a.pre_v3_backup.bytes)}), deleted after ${fmtDate(a.pre_v3_backup.deleted_after)}`] : null,
    ]));
    const due = backupDue(a.last_backup_at, a.backup_reminder_days ?? BACKUP_DUE_DAYS);
    if (due) box.append(due);
    if (sk.warning) box.append(note('caution', h('p', {}, sk.warning)));
    if (oidc.only) {
      box.append(note('caution', h('p', {}, 'Passwords are turned off (OIDC_ONLY): if the sign-in provider is down, nobody can sign in with a password. '
        + 'To get back in, set OIDC_ONLY=false and restart the server (docs/accounts.md).'
        + (oidc.admins_linked === 0 ? ' No admin has linked a provider yet: link yours in Settings → Account before you sign out.' : ''))));
    }
    if (secrets.unreadable) box.append(note('caution', h('p', {}, 'Some stored keys can no longer be read (the secret key changed). Ask the people concerned to enter their keys again.')));
  }

  // ---------------------------------------------------------------------------
  // Section: About & privacy
  // ---------------------------------------------------------------------------
  // A kidney-only profile (diabetes "None", v0.3.1); before the profile is loaded, or before a type is chosen, the
  // app uses type 1.
  const kidneyOnly = () => !!(state.profile && state.profile.diabetes === 'none');
  function renderAbout() {
    const body = $('#set-about-body');
    clear(body);
    body.append(
      kv([['App version', APP_VERSION], ['Server', (state.authStatus || {}).instance_name || KH.brand.name]]),
      subtitle('What is stored, and who can see it'),
      h('ul', { class: 'about-list' },
        h('li', {}, 'Your log, foods, saved meals, profile, targets and settings are stored on this server, not on the internet. Your account sees only its own data.'),
        h('li', {}, 'The person who runs this server can technically read all data on it. An admin can also create a password reset link for any account and sign in as that person; the activity log records it, and you are told at your next sign-in.'),
        h('li', {}, 'Keys are stored encrypted and are never shown again. Your export (Account → Your data) holds everything about you except passwords, sessions and keys.'),
        h('li', {}, 'This device keeps the app itself and the handbook pages you have opened, and, for offline use, a copy of your recent days, your profile and the foods you have seen, plus entries waiting to sync. Signing out clears that copy (it asks first when something has not synced).')),
      subtitle('Not medical advice'),
      h('p', {}, `Targets and limits in this app must come from your nephrologist or renal dietitian${kidneyOnly() ? '' : ', and insulin decisions from your diabetes care team'}. Food warnings are general renal-diet conventions, not a prescription.`),
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
    $('#settings-who').textContent = me ? `Signed in as ${me.display_name ? `${me.display_name} (${me.username})` : me.username}${me.role === 'admin' ? ' · admin' : ''}${me.test_account ? ' · test account' : ''}` : '';
  }
  // Settings → Care team (js/views/sharing.js, design note 25): its own section, near the top. Without sign-in there is one person.
  function renderCare() {
    const sec = $('#set-care');
    if (!sec) return;
    sec.hidden = authMode() === 'none' || !KH.sharing;
    if (!sec.hidden) clear($('#set-care-body')).append(KH.sharing.block());
  }
  // Settings → Connected devices (js/views/devices.js, design note 27): shown only while the server has it on.
  let devicesDraw = 0;
  async function renderConnected() {
    const sec = $('#set-connected'); // not #set-devices: that is Account → Signed-in devices
    if (!sec || !KH.devices) return;
    const ticket = ++devicesDraw;
    const show = await KH.devices.render($('#set-devices-body'));
    if (ticket !== devicesDraw || sec.hidden === !show) return;
    sec.hidden = !show;
    renderNav();
  }
  function renderNav() {
    const nav = $('#settings-nav');
    clear(nav);
    for (const sec of $$('#view-settings .settings-section')) {
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
  // The header shield and Settings → Admin open Server administration; both only for admins (a role can change).
  function syncAdminEntry() {
    const shield = $('#admin-open');
    if (shield) shield.hidden = !isAdmin();
    $('#set-admin-link').hidden = !isAdmin();
  }
  // Server administration: chips that jump to each part, like Settings' section chips.
  function renderAdminNav() {
    const nav = $('#admin-nav');
    clear(nav);
    const heads = [...$$('#set-admin-body > h3.settings-subtitle')];
    if (!$('#set-admin-ai').hidden) heads.push($('#set-admin-ai-h'));
    for (const head of heads) {
      const btn = h('button', { class: 'chip nav-chip', type: 'button' }, head.textContent);
      btn.addEventListener('click', () => {
        head.scrollIntoView({ block: 'start', behavior: 'smooth' });
        head.setAttribute('tabindex', '-1');
        head.focus({ preventScroll: true });
      });
      nav.append(h('li', {}, btn));
    }
  }
  async function loadAdmin() {
    if (!state.me) return;
    syncAdminEntry();
    const me = state.me;
    $('#admin-who').textContent = isAdmin() ? `Signed in as ${me.display_name ? `${me.display_name} (${me.username})` : me.username} · admin` : '';
    $('#set-admin-ai').hidden = !isAdmin(); // js/views/ai.js fills it when the view shows
    await renderAdminFrame();
    renderAdminNav();
  }
  async function load() {
    if (!state.me) return;
    renderWho();
    syncAdminEntry();
    renderCare();
    renderNav();
    renderAccount();
    renderPrefs();
    if (KH.body) KH.body.renderSettings().catch((err) => console.warn('Weight and blood pressure settings:', err)); // js/views/body.js
    if (KH.guidance) KH.guidance.renderSettings().catch((err) => console.warn('Meal guidance settings:', err)); // js/views/guidance.js
    renderAi();
    renderAssistant().catch((err) => console.warn('Assistant access:', err));
    renderConnected().catch((err) => console.warn('Connected devices:', err));
    renderAbout();
    cache.myKeys = null;
    renderFood();
    renderDevice().catch((err) => console.warn(err));
    // Server settings feed Food data's Open Food Facts line: read them for admins even with the admin view closed.
    // An admin the server asks to turn on two-step sign-in first gets 403 there (auth.require_two_step_admins): skip it until then.
    if (isAdmin() && !cache.adminSettings) adminSettingsReady = adminTwoStepBlocked().then((blocked) => (blocked ? null : loadServerSettings()));
    const [settings, keys] = await Promise.allSettled([api.mySettings(), api.myKeys()]);
    cache.mySettings = settings.status === 'fulfilled' ? settings.value.settings : settings.reason;
    cache.myKeys = keys.status === 'fulfilled' ? keys.value : keys.reason;
    renderThemeSource();
    renderLabUnits();
    renderFood();
    if (!state.profile) { try { await KH.loadProfile(); renderPrefs(); if (kidneyOnly()) renderAbout(); } catch (e) { /* Preferences shows Monday */ } }
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
  $('#admin-open').addEventListener('click', () => router.show('admin'));
  $('#set-admin-open').addEventListener('click', () => router.show('admin'));
  router.register('admin', () => {
    loadAdmin().catch(toastError);
    setTimeout(() => { const t = $('#admin-title'); if (t && state.view === 'admin') t.focus({ preventScroll: true }); }, 0);
  });
  /** Open Settings at one section (Profile → Care team uses it). */
  function openSection(id) {
    router.show('settings');
    setTimeout(() => {
      const sec = $(`#${id}`);
      if (!sec || sec.hidden || state.view !== 'settings') return;
      sec.scrollIntoView({ block: 'start' });
      const head = $('h2', sec);
      if (head) { head.setAttribute('tabindex', '-1'); head.focus({ preventScroll: true }); }
    }, 50);
  }
  KH.views.settings = { load, loadAdmin, onSignedIn, keyWidget, openSection, APP_VERSION };
})();
