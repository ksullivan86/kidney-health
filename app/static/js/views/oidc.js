/* Kidney Diet Log — sign-in with a provider (OpenID Connect): the button on the sign-in page, "Create the account with …" on an invite,
   Settings → Account → Linked sign-in, and "Confirm with …" in the re-auth sheet (design note 24; app/auth/oidc_api.py).

   The browser never talks to the provider itself: it follows the server's redirects. The sign-in button is a plain link to
   /api/auth/oidc/start. Linking, confirming and an invite ask the server for the provider's address (POST … → {url}) and go there.
   The provider sends the browser back to /api/auth/oidc/callback, and the server sends it on to "/" (signed in) or to
   "#/oidc/<word>"; MESSAGES has the sentence for each word (tests/test_oidc.py checks that every word of app/auth/oidc.py RESULTS
   is here). In the demo the server says "not set up", so nothing here shows (js/mock/auth.js). */
(() => {
  'use strict';
  const KH = window.KH;
  const { h, $, clear, request, toast, toastError, confirm, state } = KH;

  const RETURN_KEY = 'kh-oidc-return';

  // What the page says for each result word. {label} is the button's words without "Sign in with".
  const MESSAGES = {
    failed: { text: 'Signing in with {label} did not work. Try again. If it keeps failing, ask your admin to check the server\'s clock and the sign-in settings.' },
    expired: { text: 'That sign-in took too long, or it was finished in another tab. Try again.' },
    cancelled: { text: 'Sign-in was cancelled at {label}. Nothing was changed.' },
    unavailable: { text: 'The server could not reach {label}. Try again later, or sign in with your password.' },
    busy: { text: 'Too many sign-in attempts from here. Wait a few minutes and try again.' },
    no_account: { text: 'There is no account here for that sign-in. Ask your admin for an invite link, or sign in with your password and link {label} in Settings.' },
    domain: { text: 'This server does not let in accounts with that email address. Ask your admin which address to use.' },
    disabled: { text: 'This account is turned off. Ask your admin.' },
    taken: { text: 'That {label} account is already linked to another account here. Sign in to that account, or ask your admin.' },
    name: { text: 'The server could not choose a username for you. Ask your admin for an invite link.' },
    invite: { text: 'This invite link is not valid any more. Ask your admin for a new one.' },
    https: { text: 'Signing in from here needs the app\'s https:// address. Open the app at its usual address and try again.' },
    wrong_account: { text: 'That is not the {label} account linked to you here. Use the one you linked.' },
    linked: { text: 'Linked. You can now sign in with {label}.', ok: true },
    confirmed: { text: 'Confirmed. Do what you were doing again now.', ok: true },
  };

  function shortLabel(label) {
    const text = String(label || '').trim();
    const m = /^sign in with\s+(.+)$/i.exec(text);
    return m ? m[1] : (text || 'single sign-on');
  }
  /** The sentence for a result word ('' for an unknown one). */
  function message(word, label) {
    const item = MESSAGES[word];
    return item ? item.text.replace(/\{label\}/g, shortLabel(label)) : '';
  }
  /** "#/oidc/<word>" → {word, text, ok}, or null. */
  function parseResult(hash) {
    const m = /^#\/oidc\/([a-z_]{1,30})$/.exec(String(hash || ''));
    if (!m || !MESSAGES[m[1]]) return null;
    return { word: m[1], ok: !!MESSAGES[m[1]].ok };
  }
  function status() { return (state && state.authStatus && state.authStatus.oidc) || { enabled: false, label: null }; }
  function enabled() { return !!status().enabled; }

  /** Show or hide the sign-in page's button and the invite page's one. */
  function applyStatus() {
    const st = status();
    const on = !!st.enabled;
    const box = $('#login-oidc');
    if (box) {
      box.hidden = !on;
      const link = $('#login-oidc-btn');
      if (link && on) link.textContent = st.label;
    }
    const inv = $('#register-oidc');
    if (inv) {
      inv.hidden = !on;
      const btn = $('#register-oidc-btn');
      if (btn && on) btn.textContent = `Create the account with ${shortLabel(st.label)}`;
    }
  }

  /** Go to the provider with a {url} the server gave. */
  function go(url, back) {
    try { if (back) sessionStorage.setItem(RETURN_KEY, back); } catch (e) { /* storage unavailable: back to Today */ }
    window.location.assign(url);
  }
  /** Where to go after a link or a confirmation came back (and forget it). */
  function takeReturn() {
    try {
      const v = sessionStorage.getItem(RETURN_KEY);
      sessionStorage.removeItem(RETURN_KEY);
      return v || '';
    } catch (e) { return ''; }
  }

  async function startInvite(token) {
    const res = await request('POST', '/api/auth/oidc/invite', { token }, { quiet401: true });
    go(res.url);
  }

  // ---------------------------------------------------------------------------
  // The re-auth sheet (js/views/auth.js)
  // ---------------------------------------------------------------------------
  async function reauthAvailable() {
    if (!enabled()) return false;
    try {
      const st = await request('GET', '/api/me/oidc');
      return !!(st.enabled && st.links.some((l) => l.current));
    } catch (e) { return false; }
  }
  async function reauth() {
    const res = await request('POST', '/api/auth/reauth/oidc');
    go(res.url, state.view || 'settings');
  }

  // ---------------------------------------------------------------------------
  // Settings → Account → Linked sign-in
  // ---------------------------------------------------------------------------
  function dateText(iso) {
    const d = iso ? new Date(iso) : null;
    return d && !Number.isNaN(d.getTime()) ? d.toLocaleDateString() : '';
  }
  function itemLine(l) {
    const parts = [l.email ? `${l.provider} · ${l.email}` : l.provider, `linked ${dateText(l.created_at)}`];
    if (l.last_used_at) parts.push(`last used ${dateText(l.last_used_at)}`);
    if (!l.current) parts.push('this server no longer uses it');
    return parts.join(' · ');
  }

  function block() {
    const body = h('div', { id: 'set-oidc', role: 'region', 'aria-labelledby': 'set-oidc-h' }, h('p', { class: 'muted small' }, 'Loading…'));
    const wrap = h('div', { class: 'oidc-links', hidden: true }, h('h3', { class: 'settings-subtitle', id: 'set-oidc-h' }, 'Linked sign-in'), body);
    load(wrap, body);
    return wrap;
  }

  async function load(wrap, body) {
    let st;
    try { st = await request('GET', '/api/me/oidc'); } catch (err) {
      wrap.hidden = false;
      clear(body).append(h('p', { class: 'form-error' }, `Could not load this: ${(err && (err.detail || err.message)) || 'unknown error'}`));
      return;
    }
    // Nothing to show on a server without a provider, unless a link is left from before.
    wrap.hidden = !st.available || (!st.enabled && !st.links.length);
    if (wrap.hidden) return;
    render(wrap, body, st);
  }

  function render(wrap, body, st) {
    clear(body);
    const name = shortLabel(st.label);
    body.append(h('p', {}, st.enabled
      ? `Link your ${name} account to sign in with it, without your password here. Your password and passkeys keep working.`
      : 'This server no longer offers sign-in with a provider. You can remove a link that is left.'));
    if (!st.has_password) {
      const pw = $('#set-password-form');
      if (pw) pw.replaceWith(h('p', { class: 'hint', id: 'set-password-none' },
        `You sign in with ${name}, so this account has no password. To have one too, ask your admin for a link to set it.`));
    }
    const list = h('ul', { class: 'passkey-list', id: 'set-oidc-list' });
    for (const l of st.links) list.append(itemView(wrap, body, st, l));
    if (st.links.length) body.append(list);
    else body.append(h('p', { class: 'muted' }, 'Nothing linked yet.'));
    if (st.can_link) {
      const btn = h('button', { class: 'btn primary', type: 'button', id: 'set-oidc-link' }, `Link ${name}`);
      btn.addEventListener('click', async () => {
        if (btn.disabled) return;
        btn.disabled = true;
        try {
          const res = await request('POST', '/api/me/oidc/link');
          go(res.url, 'settings');
        } catch (err) { if (!err.handled && !err.cancelled) toastError(err); } finally { if (document.contains(btn)) btn.disabled = false; }
      });
      body.append(h('div', { class: 'settings-actions' }, btn),
        h('span', { class: 'hint' }, `You go to ${name} to sign in, then come back here.`));
    }
  }

  function itemView(wrap, body, st, l) {
    const actions = h('div', { class: 'settings-actions wrap' });
    const li = h('li', { class: 'passkey-item', 'data-oidc-id': String(l.id) },
      h('div', {}, h('strong', { class: 'passkey-name' }, shortLabel(st.label) === 'single sign-on' ? l.provider : shortLabel(st.label)),
        h('p', { class: 'hint passkey-meta' }, `${itemLine(l)}.`)), actions);
    const remove = h('button', { class: 'btn danger', type: 'button', 'aria-label': `Remove the link to ${l.provider}` }, 'Remove');
    remove.addEventListener('click', () => confirm.inline(actions, remove, {
      message: `Remove this link? You can no longer sign in with ${shortLabel(st.label)} until you link it again.`,
      confirmText: 'Remove',
      onConfirm: async () => {
        await request('DELETE', `/api/me/oidc/${l.id}`);
        toast('Link removed', 'ok');
        await load(wrap, body);
        return true;
      },
    }));
    actions.append(remove);
    return li;
  }

  KH.oidc = { MESSAGES, message, parseResult, shortLabel, applyStatus, enabled, startInvite, reauthAvailable, reauth, takeReturn, block, itemLine };
})();
