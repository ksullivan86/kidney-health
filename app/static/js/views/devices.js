/* Kidney Diet Log — Settings → Connected devices (design note 27; app/devices/api.py).

   * KH.devices.render(body) fills the section and answers whether it should show: false while the server has the feature off
     (GET /api/devices is 404 then), so Settings hides the section.
   * Connect: a short "before you connect" box says what is fetched and that nothing about the person is sent; Continue asks the
     server for the Withings address and goes there. Withings sends the browser back to the server, which sends it on to
     "#/devices/<word>/<provider>". That address is taken out of the bar when the page opens (KH.devices.takeResult) and, once
     someone is signed in, Settings opens at this section with the sentence for the word (KH.devices.openPending). After
     "connected" the first sync runs at once.
   * Sync now, and Disconnect with "Also delete the readings that came from Withings" (edited readings stay).
   * The demo shows a sample Withings connection (js/mock/devices.js) and never leaves the page.

   All text goes in with h() children (textContent), never as HTML. */
(() => {
  'use strict';
  const KH = window.KH;
  const { h, $, clear, request, toast, toastError, state } = KH;
  const { MOCK } = KH.flags;

  const A = {
    list: () => request('GET', '/api/devices', undefined, { noQueue: true }),
    start: (p) => request('POST', `/api/devices/${encodeURIComponent(p)}/start`, undefined, { noQueue: true }),
    sync: (p) => request('POST', `/api/devices/${encodeURIComponent(p)}/sync`, undefined, { noQueue: true }),
    remove: (p, alsoReadings) => request('DELETE', `/api/devices/${encodeURIComponent(p)}${alsoReadings ? '?delete_readings=true' : ''}`, undefined, { noQueue: true }),
  };

  const INTRO = 'Connect a Withings scale or blood pressure monitor. This server then fetches your readings from Withings every few '
    + 'hours and adds them to Weight and blood pressure, marked "from Withings".';
  const NOT_SET_UP = 'Withings is not set up on this server yet.';
  const NOT_SET_UP_ADMIN = 'Withings is not set up on this server yet. Register a free Withings developer app, then set WITHINGS_ENABLED, '
    + 'WITHINGS_CLIENT_ID and WITHINGS_CLIENT_SECRET_FILE (see docs/devices.md).';
  const TEST_ACCOUNT = 'Test accounts cannot connect a device. Sign in with your own account to connect yours.';
  const ERRORS = {
    auth: 'Withings no longer lets this server read your data. Connect again to carry on.',
    rate_limited: 'Withings asked this server to slow down. It tries again in an hour.',
    unreachable: 'Withings could not be reached at the last try. The server tries again later.',
    provider_error: 'Withings did not answer as expected at the last try. The server tries again later.',
  };
  const RESULTS = {
    connected: { ok: true, text: 'Withings is connected. Fetching your readings now.' },
    cancelled: { text: 'Nothing was connected: you said no at Withings.' },
    expired: { text: 'That took too long, or the link was already used. Press Connect Withings again.' },
    wrong_account: { text: 'You came back on another device or as someone else. Start again from this device.' },
    scope: { text: 'Withings did not let this server read your measurements. Connect again and allow it.' },
    taken: { text: 'This Withings account is already connected to someone else on this server.' },
    test_account: { text: TEST_ACCOUNT },
    unavailable: { text: 'Withings could not be reached. Try again in a few minutes.' },
    failed: { text: 'Connecting to Withings did not work. Try again.' },
  };
  const RESULT_RE = /^#\/devices\/([a-z_]{1,30})\/([a-z]{1,20})$/;

  const isAdmin = () => !!(state.me && state.me.role === 'admin');
  function whenText(iso) {
    const d = new Date(iso);
    if (!iso || Number.isNaN(d.getTime())) return '';
    return d.toLocaleString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });
  }
  const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;
  function countsText(c) {
    if (!c) return '';
    return `${plural(c.weights || 0, 'weight', 'weights')} and ${plural(c.readings || 0, 'blood pressure reading', 'blood pressure readings')}`;
  }
  /** The words after a sync: what was added, or that nothing was new. */
  function syncText(result) {
    if (!result || !result.added) return '';
    const n = (result.added.weights || 0) + (result.added.readings || 0);
    return n ? `Added ${countsText(result.added)}.` : 'Nothing new from Withings.';
  }
  function statusText(provider) {
    const c = provider.connection;
    if (!c) return '';
    if (c.status === 'needs_reconnect') return `${provider.name} needs you to connect again.`;
    const last = c.last_success_at ? `Last sync ${whenText(c.last_success_at)}.` : 'Not synced yet.';
    return `Connected. ${last} ${countsText(c.imported)} came from ${provider.name}.`;
  }
  function whatText(provider) {
    const what = provider.what || [];
    return what.length > 1 ? `${what.slice(0, -1).join(', ')} and ${what[what.length - 1]}` : (what[0] || '');
  }

  // ---------------------------------------------------------------------------
  // Drawing
  // ---------------------------------------------------------------------------
  let drawSeq = 0;
  /** Fill `body`; resolves to false when the feature is off on this server (the section should hide). */
  async function render(body, focusSel = null) {
    const ticket = ++drawSeq;
    let res;
    try { res = await A.list(); } catch (err) {
      if (ticket !== drawSeq) return true;
      if (err && err.status === 404) { clear(body); return false; }
      clear(body).append(h('p', { class: 'form-error' }, `Could not load this: ${(err && (err.detail || err.message)) || 'unknown error'}`));
      return true;
    }
    if (ticket !== drawSeq) return true;
    const parts = [h('p', {}, INTRO)];
    if (!res.can_connect) parts.push(h('p', { class: 'hint', id: 'set-devices-test' }, TEST_ACCOUNT));
    for (const provider of res.providers || []) parts.push(providerBlock(body, res, provider));
    if (MOCK) parts.push(h('p', { class: 'hint', id: 'set-devices-demo' }, 'This is a sample. The demo never contacts Withings.'));
    clear(body).append(...parts);
    if (focusSel) { const el = $(focusSel, body); if (el) el.focus(); }
    return true;
  }

  function providerBlock(body, res, provider) {
    const id = provider.id;
    const box = h('div', { class: 'device-provider', id: `set-devices-${id}` }, h('h3', { class: 'settings-subtitle' }, provider.name));
    if (!provider.available) {
      box.append(h('p', { class: 'hint', id: `set-devices-${id}-off` }, isAdmin() ? NOT_SET_UP_ADMIN : NOT_SET_UP));
      return box;
    }
    const c = provider.connection;
    if (c) {
      box.append(h('p', { class: 'setting-status', id: `set-devices-${id}-status` },
        h('span', { class: `state-pill ${c.status === 'active' ? 'on' : 'off'}` }, c.status === 'active' ? 'Connected' : 'Connect again'), ' ',
        statusText(provider)));
      if (c.status === 'active' && c.last_error && ERRORS[c.last_error]) box.append(h('p', { class: 'hint', id: `set-devices-${id}-error` }, ERRORS[c.last_error]));
    }
    const actions = h('div', { class: 'settings-actions' });
    const consentHost = h('div', { class: 'device-consent-host' });
    const canConnect = res.can_connect && (!c || c.status !== 'active');
    if (canConnect) {
      const label = c ? 'Connect again' : `Connect ${provider.name}`;
      const btn = h('button', { class: 'btn primary', type: 'button', id: `set-devices-${id}-connect` }, label);
      btn.addEventListener('click', () => showConsent(consentHost, actions, btn, provider));
      actions.append(btn);
    }
    if (c && c.status === 'active') {
      const btn = h('button', { class: 'btn secondary', type: 'button', id: `set-devices-${id}-sync` }, 'Sync now');
      btn.addEventListener('click', async () => {
        btn.disabled = true;
        try {
          const out = await A.sync(id);
          if (out.error) toast(ERRORS[out.error] || 'The sync did not work. The server tries again later.', 'error');
          else toast(syncText(out.result), 'ok');
          await render(body, `#set-devices-${id}-sync`);
        } catch (err) { if (!err.handled) toastError(err); } finally { btn.disabled = false; }
      });
      actions.append(btn);
    }
    if (c) {
      const btn = h('button', { class: 'btn secondary', type: 'button', id: `set-devices-${id}-disconnect` }, 'Disconnect');
      btn.addEventListener('click', () => showDisconnect(body, consentHost, actions, btn, provider));
      actions.append(btn);
    }
    box.append(actions, consentHost);
    return box;
  }

  /** What connecting means, before the person leaves for Withings. */
  function showConsent(host, actions, trigger, provider) {
    const go = h('button', { class: 'btn primary', type: 'button', id: `set-devices-${provider.id}-go` }, `Continue to ${provider.name}`);
    const cancel = h('button', { class: 'btn secondary', type: 'button' }, 'Cancel');
    const close = () => { clear(host); actions.hidden = false; trigger.focus(); };
    cancel.addEventListener('click', close);
    go.addEventListener('click', async () => {
      go.disabled = true;
      try {
        const out = await A.start(provider.id);
        window.location.assign(out.url);
      } catch (err) { go.disabled = false; if (!err.handled) toastError(err); }
    });
    actions.hidden = true;
    clear(host).append(h('div', { class: 'device-consent', role: 'group', 'aria-labelledby': `set-devices-${provider.id}-consent-h` },
      h('h4', { id: `set-devices-${provider.id}-consent-h` }, 'Before you connect'),
      h('p', {}, `You sign in at ${provider.name} and say yes there. This server then fetches your ${whatText(provider)} from ${provider.name} every few hours.`),
      h('p', {}, `Nothing about you is sent to ${provider.name}: the server only signs in and reads. It never changes a reading you typed.`),
      h('p', {}, 'You can disconnect at any time here.'),
      h('div', { class: 'settings-actions' }, cancel, go)));
    go.focus();
  }

  function showDisconnect(body, host, actions, trigger, provider) {
    const tickId = `set-devices-${provider.id}-also`;
    const tick = h('input', { type: 'checkbox', id: tickId });
    const yes = h('button', { class: 'btn danger-solid', type: 'button', id: `set-devices-${provider.id}-confirm` }, 'Disconnect');
    const no = h('button', { class: 'btn secondary', type: 'button' }, 'Keep connected');
    const close = () => { clear(host); actions.hidden = false; trigger.focus(); };
    no.addEventListener('click', close);
    yes.addEventListener('click', async () => {
      yes.disabled = true;
      try {
        const out = await A.remove(provider.id, tick.checked);
        const removed = out.removed || {};
        const n = (removed.weights || 0) + (removed.readings || 0);
        toast(`${provider.name} is disconnected.${n ? ` Deleted ${countsText(removed)}.` : ''}`, 'ok');
        await render(body);
      } catch (err) { yes.disabled = false; if (!err.handled) toastError(err); }
    });
    actions.hidden = true;
    clear(host).append(h('div', { class: 'device-consent', role: 'group', 'aria-labelledby': `set-devices-${provider.id}-off-h` },
      h('h4', { id: `set-devices-${provider.id}-off-h` }, `Disconnect ${provider.name}?`),
      h('p', {}, `The server stops fetching and forgets its sign-in to ${provider.name}. Readings already here stay, unless you tick the box.`),
      h('label', { class: 'check', for: tickId }, tick, ` Also delete the readings that came from ${provider.name} (readings you edited stay)`),
      h('div', { class: 'settings-actions' }, no, yes)));
    no.focus();
  }

  // ---------------------------------------------------------------------------
  // Back from the provider: #/devices/<word>/<provider>
  // ---------------------------------------------------------------------------
  let pending = null;
  function takeResult() {
    let hash = '';
    try { hash = location.hash || ''; } catch (e) { return false; }
    if (!hash.startsWith('#/devices/')) return false;
    const m = RESULT_RE.exec(hash);
    pending = m && RESULTS[m[1]] ? { word: m[1], provider: m[2] } : { word: 'failed', provider: 'withings' };
    try { history.replaceState(null, '', `${location.pathname}${location.search}#settings`); } catch (e) { /* sandboxed frame */ }
    return true;
  }
  /** Once someone is signed in: open Settings at this section and say how it went; after "connected", sync at once. */
  async function openPending() {
    if (!pending || !KH.router) return;
    const { word, provider } = pending;
    pending = null;
    const r = RESULTS[word];
    KH.router.show('settings');
    toast(r.text, r.ok ? 'ok' : 'error');
    const sec = $('#set-devices');
    const body = $('#set-devices-body');
    if (!sec || !body) return;
    const reveal = (shown) => {
      sec.hidden = !shown;
      if (!shown || state.view !== 'settings') return;
      sec.scrollIntoView({ block: 'start' });
      const head = $('h2', sec);
      if (head) { head.setAttribute('tabindex', '-1'); head.focus({ preventScroll: true }); }
    };
    if (word !== 'connected') { reveal(await render(body)); return; }
    try {
      const out = await A.sync(provider);
      if (out && out.result) toast(`Withings is connected. ${syncText(out.result)}`, 'ok');
    } catch (err) { /* the server syncs again within a few hours; the section shows the state */ }
    reveal(await render(body));
  }

  takeResult(); // the address the page was opened with, before any sign-in screen rewrites it

  KH.devices = { render, takeResult, openPending, statusText, syncText, countsText, RESULTS, ERRORS, INTRO };
})();
