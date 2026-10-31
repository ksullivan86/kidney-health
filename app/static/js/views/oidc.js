/* Kidney Diet Log — sign-in with a provider (OpenID Connect): the buttons on the sign-in page, "Create the account with …" on an
   invite, Settings → Account → Linked sign-in, and "Confirm with …" in the re-auth sheet (design note 24; app/auth/oidc_api.py).

   A server may have up to four providers (note 24 §13, for example Authentik and Google): each gets its own button everywhere, and
   the server's status lists them as {id, label}. The browser never talks to a provider itself: it follows the server's redirects.
   A sign-in button is a plain link to /api/auth/oidc/start (?provider=<id> for all but the first). Linking, confirming and an
   invite ask the server for the provider's address (POST …?provider=<id> → {url}) and go there. The provider sends the browser back
   to the server, which sends it on to "/" (signed in) or to "#/oidc/<word>" (the first provider) or "#/oidc/<word>/<id>" (another);
   MESSAGES has the sentence for each word (tests/test_oidc.py checks that every word of app/auth/oidc.py RESULTS is here).

   With OIDC_ONLY the server says password: 'off' (or 'test_accounts': only the test accounts use a password), and the password
   fields of the sign-in and invite screens are hidden (js/views/auth.js asks passwordMode()). In the demo the server says "not set
   up", so nothing here shows (js/mock/auth.js). */
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
    unavailable: { text: 'The server could not reach {label}. Try again later, or sign in another way.' },
    busy: { text: 'Too many sign-in attempts from here. Wait a few minutes and try again.' },
    full: { text: 'Too many sign-ins started. Try again soon.' },
    no_account: { text: 'There is no account here for that sign-in. Ask your admin for an invite link, or sign in another way and link {label} in Settings.' },
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
  /** "#/oidc/<word>" or "#/oidc/<word>/<provider id>" → {word, ok, provider}, or null. */
  function parseResult(hash) {
    const m = /^#\/oidc\/([a-z_]{1,30})(?:\/([a-z][a-z0-9]{1,19}))?$/.exec(String(hash || ''));
    if (!m || !MESSAGES[m[1]]) return null;
    return { word: m[1], ok: !!MESSAGES[m[1]].ok, provider: m[2] || null };
  }
  function status() { return (state && state.authStatus && state.authStatus.oidc) || { enabled: false, label: null }; }
  function enabled() { return !!status().enabled; }
  /** The providers the server offers, [{id, label}] (a server from before several providers sends only label). */
  function providers() {
    const st = status();
    if (!st.enabled) return [];
    if (Array.isArray(st.providers) && st.providers.length) return st.providers;
    return [{ id: 'default', label: st.label }];
  }
  /** The button words of a provider id (the first provider's for an unknown or missing id). */
  function labelOf(id) {
    const all = providers();
    const found = all.find((p) => p.id === id) || all[0];
    return found ? found.label : status().label;
  }
  /** 'on', 'off' (OIDC_ONLY) or 'test_accounts' (OIDC_ONLY, but the test accounts still use a password). */
  function passwordMode() {
    const st = status();
    return st.enabled && st.password ? st.password : 'on';
  }
  /** The start link of a provider: the first one keeps the plain address, the others add ?provider=. */
  function startHref(id, index) {
    return index === 0 ? 'api/auth/oidc/start' : `api/auth/oidc/start?provider=${encodeURIComponent(id)}`;
  }

  /** Show or hide the sign-in page's buttons and the invite page's ones, one per provider. */
  function applyStatus() {
    const all = providers();
    const on = all.length > 0;
    const box = $('#login-oidc');
    if (box) {
      box.hidden = !on;
      const list = $('#login-oidc-list');
      if (list && on) {
        clear(list);
        all.forEach((p, i) => list.append(h('a', { class: 'btn secondary auth-passkey-btn', id: i === 0 ? 'login-oidc-btn' : `login-oidc-btn-${p.id}`,
          href: startHref(p.id, i), 'data-provider': p.id }, p.label)));
      }
    }
    const inv = $('#register-oidc');
    if (inv) {
      inv.hidden = !on;
      const list = $('#register-oidc-list');
      if (list && on) {
        clear(list);
        all.forEach((p, i) => list.append(h('button', { class: 'btn secondary auth-passkey-btn', type: 'button',
          id: i === 0 ? 'register-oidc-btn' : `register-oidc-btn-${p.id}`, 'data-provider': p.id }, `Create the account with ${shortLabel(p.label)}`)));
      }
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
  function withProvider(path, id) { return id ? `${path}?provider=${encodeURIComponent(id)}` : path; }

  async function startInvite(token, id) {
    const res = await request('POST', withProvider('/api/auth/oidc/invite', id), { token }, { quiet401: true });
    go(res.url);
  }

  // ---------------------------------------------------------------------------
  // The re-auth sheet (js/views/auth.js)
  // ---------------------------------------------------------------------------
  /** The providers this person can confirm with: linked and still in use, [{id, label}]. */
  async function reauthProviders() {
    if (!enabled()) return [];
    try {
      const st = await request('GET', '/api/me/oidc');
      if (!st.enabled) return [];
      const list = Array.isArray(st.providers) ? st.providers : [];
      if (list.length) return list.filter((p) => p.linked).map((p) => ({ id: p.id, label: p.label }));
      return st.links.some((l) => l.current) ? [{ id: null, label: st.label }] : [];
    } catch (e) { return []; }
  }
  async function reauthAvailable() { return (await reauthProviders()).length > 0; }
  async function reauth(id) {
    const res = await request('POST', withProvider('/api/auth/reauth/oidc', id));
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
  /** The heading of a link: the provider's name when the server still uses it, else its host name. */
  function itemName(l, st) {
    const name = l.name || (l.current ? shortLabel(st.label) : '');
    return name && name !== 'single sign-on' ? name : l.provider;
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

  function linkButton(p, first) {
    const name = shortLabel(p.label);
    const btn = h('button', { class: 'btn primary', type: 'button', id: first ? 'set-oidc-link' : `set-oidc-link-${p.id}`, 'data-provider': p.id }, `Link ${name}`);
    btn.addEventListener('click', async () => {
      if (btn.disabled) return;
      btn.disabled = true;
      try {
        const res = await request('POST', withProvider('/api/me/oidc/link', p.id));
        go(res.url, 'settings');
      } catch (err) { if (!err.handled && !err.cancelled) toastError(err); } finally { if (document.contains(btn)) btn.disabled = false; }
    });
    return btn;
  }

  function render(wrap, body, st) {
    clear(body);
    const offered = Array.isArray(st.providers) && st.providers.length ? st.providers
      : (st.enabled ? [{ id: null, label: st.label, linked: !st.can_link }] : []);
    const names = offered.map((p) => shortLabel(p.label));
    const nameList = names.length > 1 ? `${names.slice(0, -1).join(', ')} or ${names[names.length - 1]}` : (names[0] || 'single sign-on');
    body.append(h('p', {}, st.enabled
      ? `Link your ${nameList} account to sign in with it, without your password here. Your password and passkeys keep working.`
      : 'This server no longer offers sign-in with a provider. You can remove a link that is left.'));
    if (!st.has_password) {
      const pw = $('#set-password-form');
      if (pw) pw.replaceWith(h('p', { class: 'hint', id: 'set-password-none' },
        `You sign in with ${nameList}, so this account has no password. To have one too, ask your admin for a link to set it.`));
    }
    const list = h('ul', { class: 'passkey-list', id: 'set-oidc-list' });
    for (const l of st.links) list.append(itemView(wrap, body, st, l));
    if (st.links.length) body.append(list);
    else body.append(h('p', { class: 'muted' }, 'Nothing linked yet.'));
    const toLink = st.can_link ? offered.filter((p) => !p.linked) : [];
    if (toLink.length) {
      const actions = h('div', { class: 'settings-actions wrap' });
      toLink.forEach((p) => actions.append(linkButton(p, offered.indexOf(p) === 0)));
      const where = toLink.length > 1 ? 'that site' : shortLabel(toLink[0].label);
      body.append(actions, h('span', { class: 'hint' }, `You go to ${where} to sign in, then come back here.`));
    }
  }

  function itemView(wrap, body, st, l) {
    const actions = h('div', { class: 'settings-actions wrap' });
    const name = itemName(l, st);
    const li = h('li', { class: 'passkey-item', 'data-oidc-id': String(l.id) },
      h('div', {}, h('strong', { class: 'passkey-name' }, name),
        h('p', { class: 'hint passkey-meta' }, `${itemLine(l)}.`)), actions);
    const remove = h('button', { class: 'btn danger', type: 'button', 'aria-label': `Remove the link to ${name}` }, 'Remove');
    remove.addEventListener('click', () => confirm.inline(actions, remove, {
      message: `Remove this link? You can no longer sign in with ${name} until you link it again.`,
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

  KH.oidc = {
    MESSAGES, message, parseResult, shortLabel, applyStatus, enabled, providers, labelOf, passwordMode, startInvite,
    reauthProviders, reauthAvailable, reauth, takeReturn, block, itemLine,
  };
})();
