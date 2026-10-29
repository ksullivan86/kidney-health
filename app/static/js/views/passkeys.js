/* Kidney Diet Log — passkeys: Settings → Account → Passkeys, and "Sign in with a passkey" (design note 18 §6;
   app/auth/passkeys_api.py).

   KH.passkeys.block() returns the part of the Account section that lists, adds, renames and removes passkeys.
   KH.passkeys.signIn() runs a passkey sign-in and resolves to the server's {user, notice}; js/views/auth.js calls it from the
   button under the sign-in form. KH.passkeys.reauth() answers "Enter your password again" with a passkey instead (the re-auth
   sheet shows that button when KH.passkeys.reauthAvailable() says the person has one). The browser's navigator.credentials does the device part: it asks for a fingerprint, face or
   PIN and keeps the private key on the device. This file only turns the server's JSON options into the binary form the
   browser wants, and the browser's answer back into JSON (base64url). Adding and removing need a recent password; js/core.js
   asks for it when the server answers reauth_required.

   Shown only for an account that signs in with a password. In the demo the routes answer "not available" (js/mock/auth.js). */
(() => {
  'use strict';
  const KH = window.KH;
  const { h, $, clear, request, toast, toastError, confirm } = KH;
  const { MOCK } = KH.flags;

  const A = {
    list: () => request('GET', '/api/me/passkeys'),
    options: () => request('POST', '/api/me/passkeys/options'),
    add: (body) => request('POST', '/api/me/passkeys', body),
    rename: (id, name) => request('PATCH', `/api/me/passkeys/${id}`, { name }),
    remove: (id) => request('DELETE', `/api/me/passkeys/${id}`),
  };

  // ---------------------------------------------------------------------------
  // Pure helpers (tests/test_passkeys_ui.py runs them in Node)
  // ---------------------------------------------------------------------------
  function toB64url(buf) {
    const bytes = buf instanceof Uint8Array ? buf : new Uint8Array(buf);
    let bin = '';
    for (let i = 0; i < bytes.length; i += 1) bin += String.fromCharCode(bytes[i]);
    return btoa(bin).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
  }
  function fromB64url(text) {
    const b64 = String(text || '').replace(/-/g, '+').replace(/_/g, '/');
    const bin = atob(b64 + '='.repeat((4 - (b64.length % 4)) % 4));
    const out = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i += 1) out[i] = bin.charCodeAt(i);
    return out;
  }
  /** The server's creation options → what navigator.credentials.create({publicKey}) takes. */
  function creationOptions(pk) {
    return {
      ...pk,
      challenge: fromB64url(pk.challenge),
      user: { ...pk.user, id: fromB64url(pk.user.id) },
      excludeCredentials: (pk.excludeCredentials || []).map((c) => ({ ...c, id: fromB64url(c.id) })),
    };
  }
  /** The server's request options → what navigator.credentials.get({publicKey}) takes. */
  function requestOptions(pk) {
    return { ...pk, challenge: fromB64url(pk.challenge), allowCredentials: (pk.allowCredentials || []).map((c) => ({ ...c, id: fromB64url(c.id) })) };
  }
  /** A new passkey from create() → the JSON the server reads (PublicKeyCredential.toJSON() shape). */
  function registrationJSON(cred) {
    const r = cred.response;
    return { id: cred.id, rawId: toB64url(cred.rawId), type: cred.type,
      response: { clientDataJSON: toB64url(r.clientDataJSON), attestationObject: toB64url(r.attestationObject),
        transports: typeof r.getTransports === 'function' ? r.getTransports() : [] } };
  }
  /** A signed answer from get() → the JSON the server reads. */
  function assertionJSON(cred) {
    const r = cred.response;
    return { id: cred.id, rawId: toB64url(cred.rawId), type: cred.type,
      response: { clientDataJSON: toB64url(r.clientDataJSON), authenticatorData: toB64url(r.authenticatorData),
        signature: toB64url(r.signature), userHandle: r.userHandle && r.userHandle.byteLength ? toB64url(r.userHandle) : null } };
  }
  /** The person's words for an error from the browser's passkey prompt (a DOMException). */
  function deviceMessage(err, adding, reentry = false) {
    const name = err && err.name;
    if (name === 'NotAllowedError' || name === 'AbortError') {
      if (reentry) return 'No passkey was used. Try again, or type your password.';
      return adding ? 'No passkey was saved. The request was cancelled or took too long.'
        : 'No passkey was used. Try again, or sign in with your password.';
    }
    if (name === 'InvalidStateError' && adding) return 'This device already has a passkey for your account.';
    if (name === 'SecurityError') return 'Passkeys do not work on this address. Open the app at its usual https:// address.';
    if (name === 'NotSupportedError') return 'This device cannot make a passkey of a kind this server accepts.';
    return adding ? 'The passkey was not saved. Try again.' : 'The passkey did not work. Try again, or sign in with your password.';
  }
  function supported() {
    return !!(window.PublicKeyCredential && window.isSecureContext && navigator.credentials && navigator.credentials.create);
  }
  function dateText(iso) {
    const d = iso ? new Date(iso) : null;
    return d && !Number.isNaN(d.getTime()) ? d.toLocaleDateString() : '';
  }
  function itemLine(p) {
    const parts = [`Added ${dateText(p.created_at)}`];
    parts.push(p.last_used_at ? `last used ${dateText(p.last_used_at)}` : 'not used yet');
    if (p.backed_up) parts.push('synced to your account in the cloud');
    return `${parts.join(' · ')}.`;
  }

  // ---------------------------------------------------------------------------
  // Signing in (js/views/auth.js)
  // ---------------------------------------------------------------------------
  function deviceError(err, adding, reentry = false) {
    const out = new Error(deviceMessage(err, adding, reentry));
    out.detail = out.message;
    out.device = true;
    return out;
  }
  async function signIn() {
    await stopConditional(); // one WebAuthn request at a time: the autofill one waits, the button asks now
    const opts = await request('POST', '/api/auth/passkey/options', {}, { quiet401: true });
    let cred;
    try {
      cred = await navigator.credentials.get({ publicKey: requestOptions(opts.publicKey) });
    } catch (err) { throw deviceError(err, false); }
    if (!cred) throw deviceError(null, false);
    return request('POST', '/api/auth/passkey', { challenge_id: opts.challenge_id, credential: assertionJSON(cred) }, { quiet401: true });
  }

  // ---------------------------------------------------------------------------
  // Passkeys in the username field's autofill ("conditional mediation", WebAuthn L3; design note 18 §10). The browser lists this
  // server's passkeys under the username field (autocomplete="username webauthn"); picking one signs in as the button does.
  // Nothing shows until the person taps the field, and the password form works as before. The challenge lasts 5 minutes, so a
  // request still waiting is renewed every 4. js/views/auth.js starts it on the sign-in screen and stops it when leaving.
  // ---------------------------------------------------------------------------
  const RENEW_MS = 4 * 60 * 1000;
  let conditional = null; // {controller, timer} of the request waiting in the autofill
  async function conditionalAvailable() {
    if (MOCK || !supported()) return false;
    try {
      const P = window.PublicKeyCredential;
      return !!(P && typeof P.isConditionalMediationAvailable === 'function' && await P.isConditionalMediationAvailable());
    } catch (e) { return false; }
  }
  /** Stop the waiting autofill request; resolves once the browser has let it go. */
  async function stopConditional() {
    const running = conditional;
    conditional = null;
    if (!running) return;
    clearTimeout(running.timer);
    running.controller.abort();
    await new Promise((resolve) => setTimeout(resolve, 0));
  }
  /** Offer passkeys in the autofill. onSignedIn(answer) runs after a passkey was picked and the server took it; onError(err) when
      the server refused it. False when the browser cannot. */
  async function startConditional(onSignedIn, onError) {
    await stopConditional();
    if (!(await conditionalAvailable())) return false;
    const mine = { controller: new AbortController(), timer: null };
    conditional = mine;
    mine.timer = setTimeout(() => { if (conditional === mine) startConditional(onSignedIn, onError); }, RENEW_MS);
    let opts;
    try { opts = await request('POST', '/api/auth/passkey/options', {}, { quiet401: true }); } catch (e) {
      if (conditional === mine) { clearTimeout(mine.timer); conditional = null; }
      return false; // the button and the password still work
    }
    if (conditional !== mine) return false;
    let cred;
    try {
      cred = await navigator.credentials.get({ mediation: 'conditional', publicKey: requestOptions(opts.publicKey), signal: mine.controller.signal });
    } catch (e) { return false; } // stopped, or the browser said no: nothing to show
    if (conditional !== mine || !cred) return false;
    clearTimeout(mine.timer);
    conditional = null;
    try {
      onSignedIn(await request('POST', '/api/auth/passkey', { challenge_id: opts.challenge_id, credential: assertionJSON(cred) }, { quiet401: true }));
    } catch (err) { onError(err); }
    return true;
  }

  // ---------------------------------------------------------------------------
  // A passkey instead of the password when an action asks for it again (js/views/auth.js, the re-auth sheet)
  // ---------------------------------------------------------------------------
  async function reauthAvailable() {
    if (MOCK || !supported()) return false;
    try {
      const st = await A.list();
      return !!(st.available && st.usable && st.passkeys.length);
    } catch (e) { return false; }
  }
  async function reauth() {
    const opts = await request('POST', '/api/auth/reauth/passkey/options');
    let cred;
    try {
      cred = await navigator.credentials.get({ publicKey: requestOptions(opts.publicKey) });
    } catch (err) { throw deviceError(err, false, true); }
    if (!cred) throw deviceError(null, false, true);
    return request('POST', '/api/auth/reauth/passkey', { challenge_id: opts.challenge_id, credential: assertionJSON(cred) });
  }

  // ---------------------------------------------------------------------------
  // The Settings block
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

  function block() {
    const body = h('div', { id: 'set-passkeys', role: 'region', 'aria-labelledby': 'set-passkeys-h' }, h('p', { class: 'muted small' }, 'Loading…'));
    load(body);
    return h('div', { class: 'passkeys' }, h('h3', { class: 'settings-subtitle', id: 'set-passkeys-h' }, 'Passkeys'), body);
  }

  async function load(body, focusSel = null) {
    let st;
    try { st = await A.list(); } catch (err) {
      clear(body).append(h('p', { class: 'form-error' }, `Could not load this: ${(err && (err.detail || err.message)) || 'unknown error'}`));
      return;
    }
    render(body, st);
    if (focusSel) { const el = $(focusSel, body); if (el) el.focus(); }
  }

  function render(body, st) {
    clear(body);
    if (!st.available) {
      body.append(h('p', { class: 'hint' }, MOCK
        ? 'The demo has no real sign-in, so it has no passkeys either. On your own server you add them here.'
        : 'Your sign-in is handled elsewhere, so passkeys are set up there.'));
      return;
    }
    body.append(h('p', {}, 'A passkey lets you sign in with your fingerprint, face or phone PIN instead of your password. '
      + 'It stays on your device and only works on this server, so it cannot be guessed or tricked out of you. Your password keeps working too.'));
    const list = h('ul', { class: 'passkey-list', id: 'set-passkey-list' });
    for (const p of st.passkeys) list.append(itemView(body, p));
    if (st.passkeys.length) body.append(list);
    else body.append(h('p', { class: 'muted' }, 'No passkeys yet.'));

    if (!st.usable) { body.append(h('p', { class: 'hint', id: 'set-passkeys-reason' }, st.reason)); return; }
    if (!supported()) {
      body.append(h('p', { class: 'hint', id: 'set-passkeys-unsupported' }, 'This browser cannot make passkeys here. Passkeys need a recent browser and the app\'s https:// address.'));
      return;
    }
    if (st.passkeys.length >= st.max) {
      body.append(h('p', { class: 'hint' }, `You have ${st.max} passkeys, the most one account can have. Remove one to add another.`));
      return;
    }
    const nameId = 'set-passkey-name';
    const name = h('input', { id: nameId, type: 'text', maxlength: 60, autocomplete: 'off', placeholder: 'For example: My phone' });
    const err = h('div', { class: 'form-error', role: 'alert' });
    const form = h('form', { class: 'settings-form passkey-add', novalidate: true },
      h('label', { for: nameId }, 'Name for the new passkey (optional)'),
      h('div', { class: 'inline-row' }, name, h('button', { class: 'btn primary', type: 'submit', id: 'set-passkey-add' }, 'Add a passkey')),
      h('span', { class: 'hint' }, 'Your device will ask for your fingerprint, face or PIN.'), err);
    KH.sheets.onSubmit(form, async (e) => {
      e.preventDefault();
      const btn = $('#set-passkey-add', form);
      if (btn.disabled) return;
      btn.disabled = true;
      clear(err);
      try {
        await addPasskey(name.value.trim());
        toast('Passkey added', 'ok');
        await load(body, '#set-passkey-add');
      } catch (e2) {
        if (e2.cancelled || e2.handled) return;
        err.append(h('p', {}, e2.detail || e2.message || 'The passkey was not saved. Try again.'));
      } finally { if (document.contains(btn)) btn.disabled = false; }
    });
    body.append(form);
  }

  async function addPasskey(name) {
    const opts = await A.options();
    let cred;
    try {
      cred = await navigator.credentials.create({ publicKey: creationOptions(opts.publicKey) });
    } catch (err) { throw deviceError(err, true); }
    if (!cred) throw deviceError(null, true);
    const body = { challenge_id: opts.challenge_id, credential: registrationJSON(cred) };
    if (name) body.name = name;
    return A.add(body);
  }

  function itemView(body, p) {
    const title = h('strong', { class: 'passkey-name' }, p.name);
    const actions = h('div', { class: 'settings-actions wrap' });
    const li = h('li', { class: 'passkey-item', 'data-passkey-id': String(p.id) },
      h('div', {}, title, h('p', { class: 'hint passkey-meta' }, itemLine(p))), actions);
    const rename = button('Rename', 'secondary', async () => {
      const inputId = `set-passkey-rename-${p.id}`;
      const input = h('input', { id: inputId, type: 'text', maxlength: 60, value: p.name, autocomplete: 'off' });
      const form = h('form', { class: 'inline-row passkey-rename', novalidate: true },
        h('label', { for: inputId, class: 'sr-only' }, 'New name'), input,
        h('button', { class: 'btn primary', type: 'submit' }, 'Save'),
        h('button', { class: 'btn secondary', type: 'button', 'data-cancel': '' }, 'Cancel'));
      clear(actions).append(form);
      $('[data-cancel]', form).addEventListener('click', () => load(body));
      KH.sheets.onSubmit(form, async (e) => {
        e.preventDefault();
        if (!input.value.trim()) { input.focus(); return; }
        try { await A.rename(p.id, input.value.trim()); toast('Name saved', 'ok'); await load(body); } catch (err) { if (!err.handled) toastError(err); }
      });
      input.focus();
      input.select();
    }, { 'aria-label': `Rename ${p.name}` });
    const remove = h('button', { class: 'btn danger', type: 'button', 'aria-label': `Remove ${p.name}` }, 'Remove');
    remove.addEventListener('click', () => confirm.inline(actions, remove, {
      message: `Remove "${p.name}"? That device can no longer sign in with it. Also remove it from the device's password manager.`,
      confirmText: 'Remove',
      onConfirm: async () => {
        await A.remove(p.id);
        toast('Passkey removed', 'ok');
        await load(body, '#set-passkey-add');
        return true;
      },
    }));
    actions.append(rename, remove);
    return li;
  }

  KH.passkeys = { block, signIn, reauth, reauthAvailable, supported, conditionalAvailable, startConditional, stopConditional, toB64url, fromB64url, creationOptions, requestOptions, registrationJSON, assertionJSON, deviceMessage, itemLine };
})();
