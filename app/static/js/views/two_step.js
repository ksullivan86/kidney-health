/* Kidney Diet Log — Settings → Account → Two-step sign-in (design note 17 §7; app/auth/totp_api.py).

   KH.twoStep.block() returns the part of the Account section that turns two-step sign-in on and off. Turning it on is three
   steps on the page: the QR code (and the same key as text, and a link that opens an authenticator app on a phone), the first
   code from the app, then the ten recovery codes, shown once. The QR code is drawn here as SVG elements from the vendored
   qrcode-generator module (app/static/vendor/README.md), loaded with a dynamic import() the first time, so the secret never goes
   to another site. The routes need a recent password; js/core.js asks for it when the server answers reauth_required.

   Shown only for an account that signs in with a password (Settings hides it for proxy and no-sign-in servers). In the demo
   the routes answer "not available" (js/mock/auth.js) and the block says why. */
(() => {
  'use strict';
  const KH = window.KH;
  const { h, s, $, clear, request, toast, toastError, confirm } = KH;
  const { MOCK } = KH.flags;

  const QR_URL = '/vendor/qrcode-generator-2.0.4/qrcode.mjs';
  const APPS = 'Aegis, 2FAS, Google Authenticator, Microsoft Authenticator, 1Password or Bitwarden';

  const A = {
    status: () => request('GET', '/api/me/totp'),
    setup: () => request('POST', '/api/me/totp/setup'),
    enable: (code) => request('POST', '/api/me/totp/enable', { code }),
    renew: () => request('POST', '/api/me/totp/recovery-codes'),
    off: () => request('DELETE', '/api/me/totp'),
  };

  // ---------------------------------------------------------------------------
  // Pure helpers (tests/js/two_step_runner.mjs)
  // ---------------------------------------------------------------------------
  /** "ABCDEFGH…" → "ABCD EFGH …", as the apps show a key. */
  function groupKey(secret) { return String(secret || '').replace(/\s+/g, '').replace(/(.{4})/g, '$1 ').trim(); }
  /** The text of the downloaded file: what the codes are for, then one code a line. */
  function codesFile(codes, { account = '', server = '' } = {}) {
    return [
      `Recovery codes for ${account || 'your account'}${server ? ` on ${server}` : ''}.`,
      'Each code works once, in place of the code from your authenticator app.',
      'Keep them somewhere safe, away from your phone.',
      '',
      ...codes,
      '',
    ].join('\n');
  }
  /** The modules of a QR code as one SVG path (a 1×1 square per dark module, a 4-module quiet zone). */
  function qrPath(count, isDark, quiet = 4) {
    const parts = [];
    for (let r = 0; r < count; r += 1) {
      for (let c = 0; c < count; c += 1) if (isDark(r, c)) parts.push(`M${c + quiet} ${r + quiet}h1v1h-1z`);
    }
    return parts.join('');
  }
  function leftText(n) {
    if (n === 0) return 'No recovery codes left. Make new ones now.';
    return n === 1 ? '1 recovery code left.' : `${n} recovery codes left.`;
  }

  // ---------------------------------------------------------------------------
  // The QR code
  // ---------------------------------------------------------------------------
  let qrModule = null;
  async function qrSvg(uri, label = 'QR code to scan with your authenticator app') {
    if (!qrModule) qrModule = import(QR_URL).then((m) => m.default);
    const qrcode = await qrModule;
    const qr = qrcode(0, 'M');
    qr.addData(uri, 'Byte');
    qr.make();
    const n = qr.getModuleCount();
    const size = n + 8;
    return s('svg', { class: 'two-step-qr', viewBox: `0 0 ${size} ${size}`, role: 'img', 'aria-label': label, focusable: 'false', 'shape-rendering': 'crispEdges' },
      s('rect', { class: 'qr-light', x: 0, y: 0, width: size, height: size }),
      s('path', { class: 'qr-dark', d: qrPath(n, (r, c) => qr.isDark(r, c)) }));
  }

  // ---------------------------------------------------------------------------
  // The block
  // ---------------------------------------------------------------------------
  function statusMsg() { return h('p', { class: 'status-msg', role: 'status', 'aria-live': 'polite' }); }
  function formError() { return h('div', { class: 'form-error', role: 'alert' }); }
  function showError(box, err) {
    clear(box);
    if (err) box.append(h('p', {}, typeof err === 'string' ? err : (err.detail || err.message || 'Something went wrong. Try again.')));
  }
  function button(label, cls, fn, attrs = {}) {
    const btn = h('button', { class: `btn ${cls}`, type: 'button', ...attrs }, label);
    btn.addEventListener('click', async () => {
      if (btn.disabled) return;
      btn.disabled = true;
      try { await fn(btn); } catch (err) { if (!err.handled) toastError(err); } finally { if (document.contains(btn)) btn.disabled = false; }
    });
    return btn;
  }
  async function copy(text) {
    try { if (navigator.clipboard && window.isSecureContext) { await navigator.clipboard.writeText(text); return true; } } catch (e) { /* fall through */ }
    return false;
  }
  function saveFile(name, text) {
    const url = URL.createObjectURL(new Blob([text], { type: 'text/plain' }));
    const a = h('a', { href: url, download: name, class: 'sr-only' });
    document.body.append(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 60000);
  }

  function block() {
    const body = h('div', { id: 'set-two-step', role: 'region', 'aria-labelledby': 'set-two-step-h' }, h('p', { class: 'muted small' }, 'Loading…'));
    load(body);
    return h('div', { class: 'two-step' }, h('h3', { class: 'settings-subtitle', id: 'set-two-step-h' }, 'Two-step sign-in'), body);
  }

  async function load(body, focusSel = null) {
    let st;
    try { st = await A.status(); } catch (err) {
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
        ? 'The demo has no real sign-in, so it has no two-step sign-in either. On your own server you turn it on here.'
        : 'Your sign-in is handled elsewhere, so two-step sign-in is set up there.'));
      return;
    }
    if (st.enabled) { renderOn(body, st); return; }
    if (st.required) {
      body.append(h('div', { class: 'settings-note caution', role: 'note', id: 'set-two-step-required' },
        h('p', {}, h('strong', {}, 'Your server asks admins to use two-step sign-in. '), 'Turn it on to open Server administration again.')));
    }
    body.append(
      h('p', {}, h('strong', {}, 'Off. '), `With two-step sign-in, signing in needs your password and a 6-digit code from an app on your phone, such as ${APPS}. Someone who learns your password still cannot sign in.`),
      h('div', { class: 'settings-actions' }, button('Turn on two-step sign-in', 'primary', async () => { await startSetup(body); }, { id: 'set-two-step-on' })));
  }

  function renderOn(body, st) {
    const left = Number(st.recovery_codes_left) || 0;
    const since = st.enabled_at ? new Date(st.enabled_at) : null;
    body.append(h('p', {}, h('strong', {}, 'On. '), since && !Number.isNaN(since.getTime()) ? `Since ${since.toLocaleDateString()}. ` : '',
      'Signing in asks for a code from your authenticator app after your password.'));
    body.append(h('p', { class: left <= 2 ? 'two-step-left warn' : 'two-step-left' }, leftText(left)));
    const actions = h('div', { class: 'settings-actions wrap' });
    const out = h('div', { class: 'two-step-out' });
    const renew = h('button', { class: 'btn secondary', type: 'button', id: 'set-two-step-renew' }, 'Make new recovery codes');
    renew.addEventListener('click', () => confirm.inline(actions, renew, {
      message: 'Make 10 new recovery codes? The ones you have now stop working.',
      confirmText: 'Make new codes',
      onConfirm: async () => {
        const res = await A.renew();
        clear(body);
        body.append(codesView(res.recovery_codes, () => load(body, '#set-two-step-renew'), 'New recovery codes'));
        return true;
      },
    }));
    const off = h('button', { class: 'btn danger', type: 'button', id: 'set-two-step-off' }, 'Turn off');
    off.addEventListener('click', () => confirm.inline(actions, off, {
      message: 'Turn off two-step sign-in? Signing in then needs only your password, and your recovery codes stop working.',
      confirmText: 'Turn off',
      onConfirm: async () => {
        await A.off();
        toast('Two-step sign-in is off', 'ok');
        await load(body, '#set-two-step-on');
        return true;
      },
    }));
    actions.append(renew, off);
    body.append(actions, out,
      h('p', { class: 'hint' }, 'New phone? Turn it off and on again with the new phone. Lost your phone and your recovery codes? Your admin can remove two-step sign-in from your account.'));
  }

  async function startSetup(body) {
    let res;
    try { res = await A.setup(); } catch (err) {
      if (err.cancelled) return; // the password prompt was closed
      throw err;
    }
    clear(body);
    const err = formError();
    const qrBox = h('div', { class: 'two-step-qr-box' }, h('p', { class: 'muted small' }, 'Drawing the QR code…'));
    const keyId = 'set-two-step-key';
    // Text, not an input: 39 characters with their spaces do not fit a phone-wide box, and the key must be read whole.
    const key = h('code', { id: keyId, class: 'two-step-key' }, groupKey(res.secret));
    const codeId = 'set-two-step-code';
    const code = h('input', { id: codeId, type: 'text', inputmode: 'numeric', autocomplete: 'one-time-code', autocapitalize: 'none', autocorrect: 'off', spellcheck: 'false', maxlength: 32, class: 'code-input', 'aria-describedby': `${codeId}-hint` });
    const form = h('form', { class: 'settings-form two-step-setup', novalidate: true },
      h('ol', { class: 'two-step-steps' },
        h('li', {}, h('p', {}, `Open your authenticator app (${APPS}) and add an account by scanning this QR code.`), qrBox,
          h('p', { class: 'hint' }, 'On this phone? ', h('a', { href: res.uri, class: 'two-step-open' }, 'Open it in your authenticator app'), '.')),
        h('li', {}, h('p', { id: `${keyId}-label` }, 'Cannot scan it? Type this key in the app instead:'),
          key,
          h('div', { class: 'settings-actions' }, button('Copy key', 'secondary', async () => {
            if (await copy(res.secret)) { toast('Key copied', 'ok'); return; }
            try { window.getSelection().selectAllChildren(key); } catch (e) { /* old browsers */ }
            toast('Select the key and copy it.');
          }, { 'aria-describedby': `${keyId}-label` })),
          h('span', { class: 'hint' }, `Account: ${res.account}. Kind: time-based, 6 digits, every 30 seconds.`)),
        h('li', {}, h('label', { for: codeId }, 'Type the 6-digit code the app shows now'),
          h('div', { class: 'inline-row' }, code, h('button', { class: 'btn primary', type: 'submit', id: 'set-two-step-confirm' }, 'Turn on')),
          h('span', { class: 'hint', id: `${codeId}-hint` }, 'This proves the app has the key. Nothing changes until then.'))),
      err,
      h('div', { class: 'settings-actions' }, button('Cancel', 'secondary', async () => { await A.off(); await load(body, '#set-two-step-on'); })));
    KH.sheets.onSubmit(form, async (e) => {
      e.preventDefault();
      const btn = $('#set-two-step-confirm', form);
      if (btn.disabled) return;
      if (!code.value.trim()) { showError(err, 'Type the code from your app.'); code.focus(); return; }
      btn.disabled = true;
      clear(err);
      try {
        const done = await A.enable(code.value.trim());
        toast(done.signed_out ? 'Two-step sign-in is on. Your other devices were signed out.' : 'Two-step sign-in is on', 'ok');
        clear(body);
        body.append(codesView(done.recovery_codes, () => load(body, '#set-two-step-renew'), 'Two-step sign-in is on. Save your recovery codes'));
      } catch (e2) {
        if (!e2.handled) { showError(err, e2); code.value = ''; code.focus(); }
      } finally { if (document.contains(btn)) btn.disabled = false; }
    });
    body.append(form);
    setTimeout(() => { if (document.contains(code)) code.focus(); }, 30);
    try {
      clear(qrBox).append(await qrSvg(res.uri));
    } catch (e3) {
      clear(qrBox).append(h('p', { class: 'hint' }, 'The QR code could not be drawn here. Type the key below into your app instead.'));
    }
  }

  function codesView(codes, onDone, title) {
    const me = KH.state.me || {};
    const server = (KH.state.authStatus || {}).instance_name || '';
    const text = codesFile(codes, { account: me.username, server });
    return h('div', { class: 'two-step-codes', role: 'group', 'aria-labelledby': 'set-two-step-codes-h' },
      h('p', { id: 'set-two-step-codes-h' }, h('strong', {}, `${title}. `), 'Each code works once, in place of a code from your app, if you lose your phone. They are shown only now.'),
      h('ul', { class: 'recovery-codes' }, codes.map((c) => h('li', {}, h('code', {}, c)))),
      h('div', { class: 'settings-actions wrap' },
        button('Download', 'primary', async () => { saveFile('recovery-codes.txt', text); }, { id: 'set-two-step-download' }),
        button('Copy', 'secondary', async () => { toast(await copy(codes.join('\n')) ? 'Codes copied' : 'Select the codes and copy them.', 'ok'); }),
        button('I saved them', 'secondary', async () => { await onDone(); }, { id: 'set-two-step-done' })),
      h('p', { class: 'hint' }, 'Keep them somewhere safe and away from your phone: in a password manager, or printed at home.'));
  }

  KH.twoStep = { block, groupKey, codesFile, qrPath, qrSvg, leftText, QR_URL }; // qrSvg also draws the iPhone app's pairing code (settings.js)
})();
