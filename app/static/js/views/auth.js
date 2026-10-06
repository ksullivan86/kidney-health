/* Kidney Diet Log — sign-in screens (note 07 §4.5, §4.17): first-run setup, sign-in, invite
   acceptance, password reset links, the forced new password, sign-out, the re-authentication
   prompt, the "no sign-in" banner and the plain-HTTP / HTTPS-required notes.

   Hash routes: #/login, #/setup, #/invite/<token>, #/reset/<token>. Tokens only ever travel in the
   URL fragment (browsers never send it to the server); the page moves the token out of the
   address bar into memory (and this tab's sessionStorage, so a reload keeps it) as soon as it
   reads it, and forgets it once used.

   KH.auth (hooks the API client in core.js calls; see the comment there):
     boot()                     → true when someone is signed in and the app may start
     onUnauthorized(err)        → the sign-in screen (session ended), then back where the person was
     reauth(err)                → the "Enter your password again" sheet; resolves true when done
     onPasswordChangeRequired() → the new-password screen
     onSetupRequired()          → the setup screen
     signOut()                  → POST /api/auth/logout, then a fresh page (proxy: its logout URL)

   Forms are static markup in index.html (password managers recognise them); errors go to the
   screen's role="alert" region. No HTML strings: DOM built with KH.h / textContent only. */
(() => {
  'use strict';
  const KH = window.KH;
  const { h, $, $$, clear, request, state, toast, toastError, router, sheets } = KH;
  const { MOCK } = KH.flags;

  const TITLES = {
    login: 'Sign in',
    setup: 'Set up this server',
    invite: 'Create your account',
    reset: 'Choose a password',
    change: 'Choose a new password',
    proxy: 'Sign in again',
    signedin: 'You are signed in',
  };
  const HASH = { login: '#/login', setup: '#/setup', invite: '#/invite', reset: '#/reset' };
  const TOKEN_KEY = 'kdl-link-token';
  const NOTICE_KEY = 'kdl-next-notice'; // one message for the sign-in screen after a reload
  const TOKEN_RE = /^[A-Za-z0-9._~-]{8,200}$/;

  let appStarted = false;   // KH.app.start() ran (for the person in appUserId)
  let appUserId = null;
  let resumeView = null;    // the view to return to after signing in again
  let linkToken = null;     // { kind: 'invite' | 'reset', token }
  let waitTimer = null;     // 429 countdown on the active submit button

  // ---------------------------------------------------------------------------
  // Small helpers
  // ---------------------------------------------------------------------------
  function status() { return state.authStatus || {}; }
  function instanceName() { return status().instance_name || 'Kidney Health'; }
  function minLength() { return Number(status().password_min_length) || 15; }
  function codePoints(s) { return Array.from(String(s || '')).length; }

  function setupPwToggles(root = document) {
    $$('.pw-toggle', root).forEach((btn) => {
      if (btn.dataset.wired) return;
      btn.dataset.wired = '1';
      btn.setAttribute('aria-label', 'Show password');
      btn.addEventListener('click', () => {
        const input = document.getElementById(btn.getAttribute('aria-controls'));
        if (!input) return;
        const show = input.type === 'password';
        input.type = show ? 'text' : 'password';
        btn.setAttribute('aria-pressed', show ? 'true' : 'false');
        btn.setAttribute('aria-label', show ? 'Hide password' : 'Show password');
        btn.textContent = show ? 'Hide' : 'Show';
        input.focus();
      });
    });
  }
  function hidePasswords(root) {
    $$('.pw-toggle', root).forEach((btn) => {
      const input = document.getElementById(btn.getAttribute('aria-controls'));
      if (input) input.type = 'password';
      btn.setAttribute('aria-pressed', 'false');
      btn.setAttribute('aria-label', 'Show password');
      btn.textContent = 'Show';
    });
  }
  function clearForms() {
    $$('#view-auth input').forEach((i) => {
      if (i.type === 'checkbox') i.checked = false;
      else if (!i.readOnly) i.value = '';
      i.removeAttribute('aria-invalid');
    });
    hidePasswords($('#view-auth'));
  }

  // The error region: a sentence, plus the policy's other reasons when there are several. It sits
  // at the top of the card (role="alert", so screen readers hear it at once); on a phone the field at
  // fault is often further down, so the same reason is also shown under that field (fieldError).
  function setError(message, problems = null) {
    const box = $('#auth-error');
    clear(box);
    if (!message) { clearFieldErrors(); return; }
    box.append(h('p', {}, message));
    const more = (problems || []).filter((p) => p !== message);
    if (more.length) box.append(h('ul', {}, more.map((p) => h('li', {}, p))));
  }
  function clearFieldErrors(root = $('#view-auth')) {
    $$('.field-error', root).forEach((el) => {
      const input = document.getElementById(el.dataset.for || '');
      if (input) {
        const ids = (input.getAttribute('aria-describedby') || '').split(/\s+/).filter((x) => x && x !== el.id);
        if (ids.length) input.setAttribute('aria-describedby', ids.join(' ')); else input.removeAttribute('aria-describedby');
      }
      el.remove();
    });
  }
  // The reason next to the field, linked with aria-describedby (WCAG 3.3.1), so it is in view when the
  // field gets focus.
  function fieldError(input, message, problems = null) {
    if (!input || !message) return;
    const id = `${input.id}-error`;
    const old = document.getElementById(id);
    if (old) old.remove();
    const more = (problems || []).filter((p) => p !== message);
    const el = h('div', { class: 'field-error', id, 'data-for': input.id }, h('p', {}, message),
      more.length ? h('ul', {}, more.map((p) => h('li', {}, p))) : null);
    const anchor = input.closest('.pw-wrap') || input;
    anchor.after(el);
    const ids = (input.getAttribute('aria-describedby') || '').split(/\s+/).filter(Boolean);
    if (!ids.includes(id)) input.setAttribute('aria-describedby', [...ids, id].join(' '));
  }
  // "username: Use 3 to 64 characters…" → "Use 3 to 64 characters…" when the answer names the field.
  function withoutFieldPrefix(detail, field) {
    const text = String(detail || '');
    if (!field || !text.startsWith(`${field}: `)) return text;
    const rest = text.slice(field.length + 2);
    return rest.charAt(0).toUpperCase() + rest.slice(1);
  }
  function setNotice(message) {
    const box = $('#auth-notice');
    clear(box);
    box.hidden = !message;
    if (message) box.append(h('p', {}, message));
  }
  function markInvalid(form, field, message = null, problems = null) {
    $$('input', form).forEach((i) => i.removeAttribute('aria-invalid'));
    clearFieldErrors(form);
    if (!field) return null;
    const map = { username: 'username', password: 'password', new_password: 'password', current_password: 'current', code: 'code', token: null };
    const name = map[field];
    const input = name ? $(`input[name="${name}"]:not([readonly])`, form) || $(`input[autocomplete="new-password"]`, form) : null;
    if (input) {
      input.setAttribute('aria-invalid', 'true');
      fieldError(input, message, problems);
      input.focus();
      // The reason sits under the field: bring both into view, clear of the sticky header.
      const err = document.getElementById(`${input.id}-error`);
      try { (err || input).scrollIntoView({ block: 'center' }); } catch (e) { /* old browsers */ }
    }
    return input;
  }
  // An error that belongs to no field: make sure the alert at the top of the card is on screen.
  function revealError() {
    const box = $('#auth-error');
    const r = box.getBoundingClientRect();
    if (r.top < 64 || r.bottom > window.innerHeight) { try { box.scrollIntoView({ block: 'center' }); } catch (e) { /* old browsers */ } }
  }
  // Show an API error on the current screen. Returns true when it was shown.
  function showApiError(err, form, button) {
    const data = err.data || {};
    if (err.status === 429) {
      const wait = Number(data.retry_after) || 30;
      setError(err.detail || `Too many attempts. Try again in ${wait} seconds.`);
      revealError();
      if (button) countdown(button, wait);
      return true;
    }
    if (data.https_required) {
      // The red note above explains it in full; the alert only says what happened.
      $('#auth-https').hidden = false;
      setError('Not signed in: this address uses plain HTTP. Open the app\'s https:// address.');
      revealError();
      return true;
    }
    const message = withoutFieldPrefix(err.detail, data.field) || 'Something went wrong. Try again.';
    setError(message, data.problems);
    if (!markInvalid(form, data.field, message, data.problems)) revealError();
    return true;
  }
  // After a 429 the button waits out Retry-After (its text counts down; the alert said why once).
  function countdown(button, seconds) {
    clearInterval(waitTimer);
    const label = button.dataset.label || button.textContent;
    button.dataset.label = label;
    let left = Math.max(1, Math.round(seconds));
    button.disabled = true;
    const tick = () => {
      if (left <= 0) { clearInterval(waitTimer); button.disabled = false; button.textContent = label; return; }
      button.textContent = `Wait ${left} s`;
      left -= 1;
    };
    tick();
    waitTimer = setInterval(tick, 1000);
  }
  async function busy(button, fn) {
    if (button.disabled) return;
    const label = button.dataset.label || button.textContent;
    button.dataset.label = label;
    button.disabled = true;
    button.setAttribute('aria-busy', 'true');
    try { await fn(); } finally {
      button.removeAttribute('aria-busy');
      if (button.textContent === label) button.disabled = false; // a countdown keeps it disabled
    }
  }

  function setSignedInChrome(on) {
    $$('[data-signed-in]').forEach((el) => { el.hidden = !on; });
    document.body.classList.toggle('signed-out', !on);
  }
  function applyBanners(st) {
    $('#nologin-banner').hidden = !st.no_login;
  }
  // The plain-HTTP and HTTPS-required notes, and texts that depend on the server's policy.
  function applyStatusNotes(screen) {
    const st = status();
    const accountScreens = ['login', 'invite', 'reset', 'change', 'setup'];
    $('#auth-https').hidden = !(st.https_required && accountScreens.includes(screen) && screen !== 'setup');
    $('#auth-insecure').hidden = !(st.insecure_http && !st.https_required && accountScreens.includes(screen));
    $('#auth-instance').textContent = instanceName();
    const min = minLength();
    $$('#view-auth input[autocomplete="new-password"]').forEach((i) => { i.minLength = min; });
    $$('#view-auth .hint[id$="-password-hint"], #chg-new-hint').forEach((el) => {
      el.textContent = `At least ${min} characters. A short sentence you will remember works well; no symbols needed. A password manager and pasting are fine.`;
    });
    $('#login-demo').hidden = !MOCK;
    const proxy = st.auth_mode === 'proxy';
    $$('.setup-local').forEach((el) => { el.hidden = proxy; });
    $$('.setup-proxy').forEach((el) => { el.hidden = !proxy; });
  }

  // ---------------------------------------------------------------------------
  // Screens
  // ---------------------------------------------------------------------------
  function showScreen(name, { error = '', notice = '', focus = null } = {}) {
    if (router.VIEWS.includes(state.view)) resumeView = state.view;
    state.view = 'auth';
    for (const v of router.VIEWS) { const p = $(`#view-${v}`); if (p) p.hidden = true; }
    $$('dialog[open]').forEach((d) => { try { d.close(); } catch (e) { /* already closed */ } });
    setSignedInChrome(false);
    const view = $('#view-auth');
    view.hidden = false;
    $$('[data-screen]', view).forEach((f) => { f.hidden = f.dataset.screen !== name; });
    $('#auth-title').textContent = TITLES[name] || 'Sign in';
    try { document.title = `${TITLES[name] || 'Sign in'} · ${instanceName()}`; } catch (e) { /* ignore */ }
    applyStatusNotes(name);
    setError(error);
    setNotice(notice);
    if (HASH[name]) { try { if (location.hash !== HASH[name]) history.replaceState(null, '', HASH[name]); } catch (e) { /* sandboxed frame */ } }
    window.scrollTo({ top: 0 });
    const screen = $(`[data-screen="${name}"]`, view);
    setTimeout(() => {
      const target = focus || (screen && $$('input:not([hidden]):not([readonly]), button.auth-submit, a.auth-submit', screen).find((i) => !i.closest('[hidden]') && !i.value));
      if (target) target.focus(); else $('#auth-title').focus();
    }, 0);
  }

  function showLogin(opts = {}) {
    showScreen('login', opts);
    const known = state.me && state.me.username;
    if (known && !$('#login-username').value) $('#login-username').value = known;
  }
  // Proxy mode without a person: either the proxy sent no identity (sign in there again), or it
  // did and this server refuses it (not enabled here, name clash); GET /api/me says which.
  async function showProxyScreen(opts = {}) {
    showScreen('proxy', opts);
    try { await request('GET', '/api/me', undefined, { quiet401: true }); } catch (err) {
      if (err.status === 403 && err.detail) setError(err.detail);
    }
  }
  function showChange(user, opts = {}) {
    $('#chg-username').value = (user && user.username) || '';
    // An admin (for example the owner of a server upgraded from v0.2, whose old APP_PASSWORD is too
    // weak for today's rules) has no "admin" asking: say why instead.
    $('#chg-intro').textContent = user && user.role === 'admin'
      ? "Your current password does not meet this server's password rules (it was set before they applied, or another admin asked for a new one). Choose a new one to continue."
      : 'Your admin asks you to choose a new password before you continue.';
    $('#chg-who').textContent = user && user.username ? `Account: ${user.username}` : '';
    showScreen('change', opts);
  }
  function showSignedIn(user, kind) {
    $('#signedin-msg').textContent = `You are signed in as ${user.display_name || user.username} (${user.username}). `
      + (kind === 'invite' ? 'This invite link creates a new account. To use it, sign out first.' : 'This link sets the password of an account. To use it, sign out first.');
    showScreen('signedin');
    $('#signedin-continue').onclick = () => { forgetLinkToken(); enterApp(user); };
    $('#signedin-signout').onclick = async () => {
      const btn = $('#signedin-signout');
      await busy(btn, async () => {
        const saved = linkToken;
        if (!(await signOut({ stay: true }))) return;
        linkToken = saved;
        await linkScreen(kind);
      });
    };
  }

  // ---------------------------------------------------------------------------
  // Link tokens (#/invite/<token>, #/reset/<token>)
  // ---------------------------------------------------------------------------
  function parseHash() {
    const raw = (() => { try { return location.hash || ''; } catch (e) { return ''; } })();
    let m = /^#\/(invite|reset)\/(.+)$/.exec(raw);
    if (m) return { screen: m[1], token: decodeURIComponent(m[2]) };
    m = /^#\/(login|setup|invite|reset)\/?$/.exec(raw);
    return m ? { screen: m[1] } : null;
  }
  function takeLinkToken(route) {
    if (!route || (route.screen !== 'invite' && route.screen !== 'reset')) return;
    if (route.token != null) {
      linkToken = TOKEN_RE.test(route.token) ? { kind: route.screen, token: route.token } : { kind: route.screen, token: '' };
      try { sessionStorage.setItem(TOKEN_KEY, JSON.stringify(linkToken)); } catch (e) { /* storage unavailable: memory only */ }
      try { history.replaceState(null, '', HASH[route.screen]); } catch (e) { /* sandboxed frame */ }
    } else if (!linkToken) {
      try {
        const t = JSON.parse(sessionStorage.getItem(TOKEN_KEY) || 'null');
        if (t && t.kind === route.screen && typeof t.token === 'string') linkToken = t;
      } catch (e) { /* none kept */ }
    }
  }
  function forgetLinkToken() {
    linkToken = null;
    try { sessionStorage.removeItem(TOKEN_KEY); } catch (e) { /* storage unavailable */ }
  }
  let resetTarget = null; // { username, display_name, new_account } of the open reset/setup link
  function resetIntro(info) {
    if (info && info.new_account) {
      return `Welcome to ${instanceName()}${info.display_name ? `, ${info.display_name}` : ''}. Your admin created an account for you: choose its password. You sign in with the username shown below.`;
    }
    return 'Choose a new password for your account. Every other device signed in to it is signed out.';
  }
  async function linkScreen(kind) {
    if (!linkToken || linkToken.kind !== kind || !linkToken.token) {
      showLogin({ error: 'This link is incomplete or damaged. Open the whole link again, or ask for a new one.' });
      return;
    }
    if (kind === 'invite') $('#register-intro').textContent = `You have been invited to ${instanceName()}. Choose a username and a password for your account.`;
    if (kind === 'reset') {
      // Whose account it is: an admin-created account's person has never seen the username.
      resetTarget = null;
      $('#reset-username').value = '';
      $('#reset-username-field').hidden = true;
      $('#reset-intro').textContent = resetIntro(null);
      try {
        resetTarget = await request('POST', '/api/auth/reset/info', { token: linkToken.token }, { quiet401: true });
      } catch (err) {
        if (err.status === 400) { forgetLinkToken(); showLogin({ error: err.detail || 'This link is not valid any more. Ask your admin for a new one.' }); return; }
        if (err.status === 429) { showLogin({ error: err.detail }); return; }
        // Anything else: the form still works; it just cannot show the name.
      }
      if (resetTarget) {
        $('#reset-username').value = resetTarget.username;
        $('#reset-username-field').hidden = false;
        $('#reset-intro').textContent = resetIntro(resetTarget);
      }
      TITLES.reset = resetTarget && resetTarget.new_account ? 'Set up your account' : 'Choose a password';
    }
    showScreen(kind);
  }

  // ---------------------------------------------------------------------------
  // Entering the app
  // ---------------------------------------------------------------------------
  function enterApp(user, { notice = null } = {}) {
    state.me = user;
    forgetLinkToken();
    clearInterval(waitTimer);
    if (appStarted && appUserId !== user.id) {
      // Another person on this page: start from a clean page so nothing of the previous one stays.
      try { history.replaceState(null, '', '#today'); } catch (e) { /* sandboxed frame */ }
      window.location.reload();
      return;
    }
    clearForms();
    setError('');
    $('#view-auth').hidden = true;
    setSignedInChrome(true);
    try { document.title = 'Kidney Diet Log'; } catch (e) { /* ignore */ }
    if (notice) toast(notice);
    if (!appStarted) {
      appStarted = true;
      appUserId = user.id;
      KH.app.start(resumeView);
    } else {
      router.show(resumeView || 'today');
    }
    if (KH.views.settings && KH.views.settings.onSignedIn) KH.views.settings.onSignedIn(user);
    // The submit button that had focus is hidden now: give the keyboard a place in the app.
    setTimeout(() => {
      const active = document.activeElement;
      if (active && active !== document.body && !active.closest('[hidden]')) return;
      const tab = $(`#tab-${state.view}`);
      const target = tab && !tab.closest('[hidden]') ? tab : $(`#view-${state.view} h2`);
      if (!target) return;
      if (target.tagName === 'H2' && !target.hasAttribute('tabindex')) target.setAttribute('tabindex', '-1');
      try { target.focus({ preventScroll: true }); } catch (e) { /* ignore */ }
    }, 60);
  }
  // A message for the sign-in screen after the page reloads (e.g. "your account was deleted").
  function noticeAfterReload(message) {
    try { sessionStorage.setItem(NOTICE_KEY, String(message)); } catch (e) { /* storage unavailable */ }
  }
  function takeReloadNotice() {
    try {
      const msg = sessionStorage.getItem(NOTICE_KEY);
      sessionStorage.removeItem(NOTICE_KEY);
      return msg || '';
    } catch (e) { return ''; }
  }
  function afterSignIn(user, notice) {
    if (user.must_change_password) { showChange(user, { notice: notice || '' }); return; }
    enterApp(user, { notice });
  }

  // ---------------------------------------------------------------------------
  // Boot
  // ---------------------------------------------------------------------------
  async function loadStatus() {
    const st = await request('GET', '/api/auth/status', undefined, { quiet401: true });
    state.authStatus = st;
    applyBanners(st);
    return st;
  }
  async function boot() {
    setupPwToggles();
    const initial = (() => { try { return location.hash.replace('#', ''); } catch (e) { return ''; } })();
    if (router.VIEWS.includes(initial)) resumeView = initial;
    const route = parseHash();
    takeLinkToken(route);
    let st;
    try { st = await loadStatus(); } catch (err) {
      showLogin({ error: err.status === 0 ? 'Cannot reach the server. Check your connection, then reload the page.' : (err.detail || 'The server did not answer. Reload the page to try again.') });
      return false;
    }
    if (st.setup_required) { showScreen('setup'); return false; }
    if (route && (route.screen === 'invite' || route.screen === 'reset')) {
      if (st.user) { showSignedIn(st.user, route.screen); return false; }
      linkScreen(route.screen);
      return false;
    }
    if (!st.user) {
      const notice = takeReloadNotice();
      if (st.auth_mode === 'proxy') showProxyScreen({ notice });
      else showLogin({ notice });
      return false;
    }
    if (st.user.must_change_password) { showChange(st.user); return false; }
    state.me = st.user;
    appStarted = true;
    appUserId = st.user.id;
    setSignedInChrome(true);
    $('#view-auth').hidden = true;
    return true;
  }

  // ---------------------------------------------------------------------------
  // Form handlers
  // ---------------------------------------------------------------------------
  function newPasswordProblem(pw) {
    const n = codePoints(pw);
    if (n < minLength()) return `Use at least ${minLength()} characters. A short sentence or three or four unrelated words works well.`;
    if (n > 128) return 'Use at most 128 characters.';
    return null;
  }
  function requireFields(form, pairs) {
    for (const [input, message] of pairs) {
      if (!input.value.trim()) {
        setError(message);
        markInvalid(form, null);
        input.setAttribute('aria-invalid', 'true');
        fieldError(input, message);
        input.focus();
        try { input.scrollIntoView({ block: 'center' }); } catch (e) { /* old browsers */ }
        return false;
      }
    }
    return true;
  }

  sheets.onSubmit($('#form-login'), async (e) => {
    e.preventDefault();
    const form = $('#form-login');
    const user = $('#login-username'), pass = $('#login-password');
    if (!requireFields(form, [[user, 'Enter your username.'], [pass, 'Enter your password.']])) return;
    const btn = $('#login-submit');
    await busy(btn, async () => {
      setError('');
      try {
        const res = await request('POST', '/api/auth/login', { username: user.value.trim(), password: pass.value }, { quiet401: true });
        pass.value = '';
        afterSignIn(res.user, res.notice);
      } catch (err) {
        showApiError(err, form, btn);
        if (err.status === 401) { pass.value = ''; pass.focus(); }
      }
    });
  });

  sheets.onSubmit($('#form-setup'), async (e) => {
    e.preventDefault();
    const form = $('#form-setup');
    const proxy = status().auth_mode === 'proxy';
    const code = $('#setup-code');
    const checks = [[code, 'Enter the setup code from the server log.']];
    if (!proxy) checks.push([$('#setup-username'), 'Choose a username.'], [$('#setup-password'), 'Choose a password.']);
    if (!requireFields(form, checks)) return;
    if (!proxy) {
      const problem = newPasswordProblem($('#setup-password').value);
      if (problem) { setError(problem); markInvalid(form, 'password', problem); return; }
    }
    const body = { code: code.value.trim(), off_enabled: $('#setup-off').checked };
    if ($('#setup-display').value.trim()) body.display_name = $('#setup-display').value.trim();
    if (!proxy) { body.username = $('#setup-username').value.trim(); body.password = $('#setup-password').value; }
    const btn = $('#setup-submit');
    await busy(btn, async () => {
      setError('');
      try {
        const res = await request('POST', '/api/auth/setup', body, { quiet401: true });
        await loadStatus().catch(() => null);
        enterApp(res.user, { notice: 'Welcome. Your account is the admin of this server; invite others from Settings → Admin.' });
      } catch (err) {
        if (err.status === 409) { showLogin({ notice: 'This server is already set up. Sign in instead.' }); return; }
        showApiError(err, form, btn);
      }
    });
  });

  sheets.onSubmit($('#form-register'), async (e) => {
    e.preventDefault();
    const form = $('#form-register');
    if (!requireFields(form, [[$('#reg-username'), 'Choose a username.'], [$('#reg-password'), 'Choose a password.']])) return;
    const problem = newPasswordProblem($('#reg-password').value);
    if (problem) { setError(problem); markInvalid(form, 'password', problem); return; }
    const body = { token: linkToken ? linkToken.token : '', username: $('#reg-username').value.trim(), password: $('#reg-password').value };
    if ($('#reg-display').value.trim()) body.display_name = $('#reg-display').value.trim();
    const btn = $('#reg-submit');
    await busy(btn, async () => {
      setError('');
      try {
        const res = await request('POST', '/api/auth/register', body, { quiet401: true });
        enterApp(res.user, { notice: `Welcome to ${instanceName()}. Start with Profile to set your targets.` });
      } catch (err) { showApiError(err, form, btn); }
    });
  });

  sheets.onSubmit($('#form-reset'), async (e) => {
    e.preventDefault();
    const form = $('#form-reset');
    if (!requireFields(form, [[$('#reset-password'), 'Choose a password.']])) return;
    const problem = newPasswordProblem($('#reset-password').value);
    if (problem) { setError(problem); markInvalid(form, 'password', problem); return; }
    const btn = $('#reset-submit');
    await busy(btn, async () => {
      setError('');
      try {
        const res = await request('POST', '/api/auth/reset', { token: linkToken ? linkToken.token : '', password: $('#reset-password').value }, { quiet401: true });
        const fresh = resetTarget && resetTarget.new_account;
        resetTarget = null;
        afterSignIn(res.user, fresh ? `Your account is ready. Next time, sign in as ${res.user.username} with this password.`
          : 'Password saved. Other devices signed in to this account were signed out.');
      } catch (err) { showApiError(err, form, btn); }
    });
  });

  sheets.onSubmit($('#form-change'), async (e) => {
    e.preventDefault();
    const form = $('#form-change');
    if (!requireFields(form, [[$('#chg-current'), 'Enter your current password.'], [$('#chg-new'), 'Choose a new password.']])) return;
    const problem = newPasswordProblem($('#chg-new').value);
    if (problem) { setError(problem); markInvalid(form, 'new_password', problem); return; }
    const btn = $('#chg-submit');
    await busy(btn, async () => {
      setError('');
      try {
        const res = await request('POST', '/api/me/password', { current_password: $('#chg-current').value, new_password: $('#chg-new').value }, { quiet401: true });
        enterApp(res.user, { notice: 'New password saved. Other devices were signed out.' });
      } catch (err) {
        if (err.status === 401) { showLogin({ notice: 'You were signed out. Sign in again.' }); return; }
        showApiError(err, form, btn);
      }
    });
  });
  $('#chg-signout').addEventListener('click', () => signOut());

  // ---------------------------------------------------------------------------
  // Sign-out (note 07 §4.5; note 02 R5: warn about unsynced entries, then clear this device)
  // ---------------------------------------------------------------------------
  async function pendingOfflineCount() {
    try { return KH.offline && typeof KH.offline.pendingCount === 'function' ? Number(await KH.offline.pendingCount()) || 0 : 0; } catch (e) { return 0; }
  }
  // { stay: true } keeps this page (used before opening an invite link); otherwise the page
  // starts fresh. Returns true when signed out.
  async function signOut({ stay = false } = {}) {
    let res = null;
    try {
      res = await request('POST', '/api/auth/logout', undefined, { quiet401: true });
    } catch (err) {
      if (err.status !== 401) { toastError(err); return false; } // 401: the session had already ended
    }
    try { if (KH.offline && typeof KH.offline.purge === 'function') await KH.offline.purge(); } catch (e) { /* best effort */ }
    if (res && res.redirect) { window.location.assign(res.redirect); return true; } // the sign-in proxy's own sign-out page
    if (status().auth_mode === 'proxy') {
      state.me = null;
      showScreen('proxy', { notice: 'You are signed out of this app. Your sign-in proxy may still remember you: sign out there too, especially on a shared device.' });
      return true;
    }
    if (stay || MOCK) {
      // The demo keeps its in-page data (a reload would restart it); state.me stays known so the
      // sign-in screen can offer the same username.
      showLogin({ notice: MOCK ? 'You are signed out of the demo.' : 'You are signed out.' });
      return true;
    }
    try { history.replaceState(null, '', '#/login'); } catch (e) { /* sandboxed frame */ }
    window.location.reload();
    return true;
  }

  // ---------------------------------------------------------------------------
  // Re-authentication sheet (403 reauth_required → password → POST /api/auth/reauth → retry)
  // ---------------------------------------------------------------------------
  const reauthDlg = $('#sheet-reauth');
  sheets.setup(reauthDlg);
  let reauthWaiter = null; // { promise, resolve, done, trigger }
  // The control the person used last: the one that asked for the password is usually disabled
  // while its request waits, so document.activeElement is the page by the time the sheet opens.
  let lastControl = null;
  document.addEventListener('focusin', (e) => { if (e.target instanceof HTMLElement && !reauthDlg.contains(e.target)) lastControl = e.target; });
  document.addEventListener('pointerdown', (e) => {
    const el = e.target instanceof Element ? e.target.closest('button, a, input, select, summary') : null;
    if (el && !reauthDlg.contains(el)) lastControl = el;
  }, true);
  function reauth() {
    if (reauthWaiter) return reauthWaiter.promise; // several requests at once share one prompt
    if (status().auth_mode && status().auth_mode !== 'local') return Promise.resolve(false);
    let resolve;
    const promise = new Promise((r) => { resolve = r; });
    const active = document.activeElement;
    const trigger = active && active !== document.body ? active : lastControl;
    reauthWaiter = { promise, resolve, done: false, trigger };
    $('#reauth-username').value = (state.me && state.me.username) || '';
    $('#reauth-password').value = '';
    clear($('#reauth-error'));
    hidePasswords(reauthDlg);
    $('#reauth-submit').disabled = false;
    sheets.open(reauthDlg, null, $('#reauth-password'));
    reauthDlg._returnFocus = null; // handled below, once the waiting request has settled
    return promise;
  }
  reauthDlg.addEventListener('close', () => {
    const w = reauthWaiter;
    reauthWaiter = null;
    $('#reauth-password').value = '';
    if (!w) return;
    w.resolve(!!w.done);
    // Cancelled: back to the control that asked, once its request has failed and re-enabled it.
    // Done: the action carries on and moves focus itself if it needs to.
    if (!w.done && w.trigger) {
      setTimeout(() => {
        const t = w.trigger;
        if (t && document.contains(t) && !t.disabled && !t.closest('[hidden]')) { try { t.focus(); } catch (e) { /* ignore */ } }
      }, 80);
    } else if (w.done && w.trigger) {
      // Done: the request is retried; once its control is usable again (and nothing else took the
      // focus), put the keyboard back there instead of on the page body.
      const t = w.trigger;
      let tries = 0;
      const back = () => {
        tries += 1;
        const active = document.activeElement;
        if (active && active !== document.body && active !== t) return; // the action moved focus itself
        if (t && document.contains(t) && !t.disabled && !t.closest('[hidden]')) { try { t.focus(); } catch (e) { /* ignore */ } return; }
        if (tries < 100) setTimeout(back, 100);
      };
      setTimeout(back, 80);
    }
  });
  sheets.onSubmit($('#reauth-form'), async (e) => {
    e.preventDefault();
    const pass = $('#reauth-password');
    const errBox = $('#reauth-error');
    if (!pass.value) { clear(errBox); errBox.append(h('p', {}, 'Enter your password.')); pass.focus(); return; }
    const btn = $('#reauth-submit');
    if (btn.disabled) return;
    btn.disabled = true;
    try {
      await request('POST', '/api/auth/reauth', { password: pass.value });
      if (reauthWaiter) reauthWaiter.done = true;
      reauthDlg.close();
    } catch (err) {
      pass.value = '';
      if (err.status === 401) { reauthDlg.close(); return; } // signed out after too many wrong passwords: the sign-in screen is up
      clear(errBox);
      errBox.append(h('p', {}, err.detail || 'That did not work. Try again.'));
      if (err.status === 429) { countdown(btn, Number((err.data || {}).retry_after) || 30); return; }
      pass.focus();
    } finally {
      if (!waitTimer || !btn.textContent.startsWith('Wait')) btn.disabled = false;
    }
  });

  // ---------------------------------------------------------------------------
  // Hooks for the API client
  // ---------------------------------------------------------------------------
  function onUnauthorized() {
    if (state.view === 'auth') return;
    if (status().auth_mode === 'proxy') { showProxyScreen(); return; }
    showLogin({ notice: 'Your session has ended (it expired, or this device was signed out). Sign in again to carry on where you were.' });
  }
  function onPasswordChangeRequired() {
    if (state.view === 'auth') return;
    showChange(state.me, { notice: '' });
  }
  function onSetupRequired() {
    if (state.view === 'auth') return;
    loadStatus().catch(() => null).finally(() => showScreen('setup'));
  }

  // A link pasted into the address bar of a page that is already open.
  window.addEventListener('hashchange', () => {
    const route = parseHash();
    if (!route) return;
    if (route.token != null) {
      takeLinkToken(route);
      if (state.me) { showSignedIn(state.me, route.screen); return; }
      linkScreen(route.screen);
    } else if (route.screen === 'setup' && status().setup_required) showScreen('setup');
  });

  setupPwToggles();
  Object.assign(KH.auth, {
    boot, signOut, reauth, onUnauthorized, onPasswordChangeRequired, onSetupRequired, loadStatus,
    showScreen, setupPwToggles, enterApp, noticeAfterReload,
  });
  KH.views.auth = { showScreen, parseHash };
})();
