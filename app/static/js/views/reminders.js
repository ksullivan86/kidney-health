/* Kidney Diet Log — Settings → Reminders: a phone notification at a time you choose (design note 35; app/reminders.py).

   * KH.reminders.render(body) fills the Settings section and answers whether it should show: false while the server has it off
     (GET /api/reminders answers enabled: false then).
   * "Turn on notifications on this device" asks for permission only from that tap. On iPhone and iPad it works only in the app
     opened from the Home Screen, so a Safari tab gets a short how-to instead of the button.
   * The page knows "this device" by comparing SHA-256 of its own subscription's endpoint with each device's endpoint_hash; the
     server never sends the endpoint back.
   * Reminders are a convenience. The block says not to rely on them for low blood sugar, and there is no reminder about lows,
     insulin, medicines or glucose.
   * The demo (js/mock/reminders.js) never asks the browser for a subscription and never sends anything.

   All text goes in with h() children (textContent), never as HTML. */
(() => {
  'use strict';
  const KH = window.KH;
  const { h, $, clear, request, toast, toastError } = KH;
  const { MOCK } = KH.flags;

  const A = {
    get: () => request('GET', '/api/reminders', undefined, { noQueue: true }),
    add: (body) => request('POST', '/api/reminders', body, { noQueue: true }),
    change: (id, body) => request('PATCH', `/api/reminders/${encodeURIComponent(id)}`, body, { noQueue: true }),
    remove: (id) => request('DELETE', `/api/reminders/${encodeURIComponent(id)}`, undefined, { noQueue: true }),
    addDevice: (sub) => request('POST', '/api/reminders/subscriptions', sub, { noQueue: true }),
    removeDevice: (id) => request('DELETE', `/api/reminders/subscriptions/${encodeURIComponent(id)}`, undefined, { noQueue: true }),
    test: () => request('POST', '/api/reminders/test', undefined, { noQueue: true }),
  };

  const INTRO = 'Get a notification at a time you choose: to log a meal, plan tomorrow or log your weight.';
  const SAFETY = "Reminders are a convenience. Do not rely on them for low blood sugar; use your CGM's alerts.";
  const TEST_ACCOUNT = 'Test accounts cannot use reminders. Sign in with your own account to set yours up.';
  const IOS_HOME = 'On iPhone and iPad, notifications work only in the app on your Home Screen. In Safari, tap Share, then Add to Home Screen. Open the app from there and come back here.';
  const NO_PUSH = 'This browser cannot show notifications from this app.';
  const BLOCKED = 'Notifications are blocked for this site. Allow them in your browser or phone settings, then come back here.';
  const DAY_NAMES = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']; // bit 0 is Monday, as on the server
  const DAY_LONG = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];
  const WHAT = [ // [value, label, kind, meal]
    ['log_meal:breakfast', 'Log breakfast', 'log_meal', 'breakfast'],
    ['log_meal:lunch', 'Log lunch', 'log_meal', 'lunch'],
    ['log_meal:dinner', 'Log dinner', 'log_meal', 'dinner'],
    ['log_meal:snack', 'Log a snack', 'log_meal', 'snack'],
    ['plan_tomorrow', 'Plan tomorrow', 'plan_tomorrow', null],
    ['weigh_in', 'Log your weight', 'weigh_in', null],
  ];
  const ERRORS = {
    gone: 'This device stopped taking notifications.',
    blocked: 'The server could not reach this device\'s push service.',
    timeout: 'The push service took too long to answer.',
    unreachable: 'The push service did not answer.',
    auth: 'The push service did not accept this server. Turn notifications off and on again on this device.',
    rejected: 'The push service did not take the message.',
    busy: 'The push service was busy.',
    bad_answer: 'The push service gave an odd answer.',
  };

  // ---------------------------------------------------------------------------
  // Small helpers
  // ---------------------------------------------------------------------------
  const whatOf = (r) => WHAT.find((w) => w[2] === r.kind && (w[3] || null) === (r.meal || null)) || [r.kind, r.kind, r.kind, r.meal];
  function daysText(days) {
    if (days === 127) return 'Every day';
    if (days === 31) return 'Weekdays';
    if (days === 96) return 'Weekends';
    return DAY_NAMES.filter((_, i) => days & (1 << i)).join(', ');
  }
  function timeText(t) {
    const [hh, mm] = String(t || '').split(':').map(Number);
    if (!Number.isFinite(hh) || !Number.isFinite(mm)) return t || '';
    const d = new Date(2000, 0, 1, hh, mm);
    return d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
  }
  function dateText(iso) {
    const d = new Date(iso);
    return !iso || Number.isNaN(d.getTime()) ? '' : d.toLocaleDateString([], { month: 'short', day: 'numeric', year: 'numeric' });
  }
  function zone() {
    try { return Intl.DateTimeFormat().resolvedOptions().timeZone || ''; } catch (e) { return ''; }
  }
  function deviceName(ua) { return KH.deviceName ? KH.deviceName(ua) : (ua ? 'Browser' : 'Unknown device'); }
  function isIOS() {
    const ua = navigator.userAgent || '';
    return /iPhone|iPad|iPod/.test(ua) || (/Macintosh/.test(ua) && navigator.maxTouchPoints > 1);
  }
  function standalone() {
    try { return window.matchMedia('(display-mode: standalone)').matches || window.navigator.standalone === true; } catch (e) { return false; }
  }
  function pushSupported() { return 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window; }
  function keyBytes(b64) {
    const text = String(b64).replace(/-/g, '+').replace(/_/g, '/');
    const raw = atob(text + '='.repeat((4 - (text.length % 4)) % 4));
    return Uint8Array.from(raw, (c) => c.charCodeAt(0));
  }
  async function sha32(text) {
    const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text));
    return Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, '0')).join('').slice(0, 32);
  }
  async function registration() {
    if (!('serviceWorker' in navigator)) return null;
    try { return (await navigator.serviceWorker.getRegistration()) || null; } catch (e) { return null; }
  }
  async function currentSubscription() {
    const reg = await registration();
    if (!reg || !reg.pushManager) return null;
    try { return await reg.pushManager.getSubscription(); } catch (e) { return null; }
  }

  // ---------------------------------------------------------------------------
  // Settings → Reminders
  // ---------------------------------------------------------------------------
  let drawSeq = 0;
  let demoDevice = null; // the demo's "this device" (no real subscription in the demo)

  async function render(body, focusSel = null) {
    const ticket = ++drawSeq;
    let res;
    try { res = await A.get(); } catch (err) {
      if (ticket !== drawSeq) return true;
      if (err && err.status === 404) { clear(body); return false; }
      clear(body).append(h('p', { class: 'form-error' }, `Could not load this: ${(err && (err.detail || err.message)) || 'unknown error'}`));
      return true;
    }
    if (ticket !== drawSeq) return true;
    if (!res.enabled) { clear(body); return false; }
    const parts = [h('p', {}, INTRO), h('div', { class: 'settings-note caution', role: 'note', id: 'set-reminders-safety' }, h('p', {}, res.safety || SAFETY))];
    if (!res.can_use) {
      parts.push(h('p', { class: 'hint', id: 'set-reminders-test-account' }, TEST_ACCOUNT));
      clear(body).append(...parts);
      return true;
    }
    const here = await thisDevice(res);
    if (ticket !== drawSeq) return true;
    parts.push(h('h3', { class: 'settings-subtitle', id: 'set-reminders-device-h' }, 'This device'), deviceBlock(body, res, here));
    parts.push(h('h3', { class: 'settings-subtitle', id: 'set-reminders-list-h' }, 'Your reminders'), listBlock(body, res));
    parts.push(h('h3', { class: 'settings-subtitle', id: 'set-reminders-devices-h' }, 'Devices with notifications on'), devicesBlock(body, res, here));
    if (MOCK) parts.push(h('p', { class: 'hint', id: 'set-reminders-demo' }, 'This is a sample. The demo never sends a notification.'));
    clear(body).append(...parts);
    if (focusSel) { const el = $(focusSel, body); if (el) el.focus(); }
    return true;
  }

  /** { sub, device }: this browser's subscription (null when none) and the server's row for it (null when it has none). */
  async function thisDevice(res) {
    if (MOCK) return { sub: null, device: (res.devices || []).find((d) => d.id === demoDevice) || null };
    const sub = await currentSubscription();
    if (!sub) return { sub: null, device: null };
    let hash = '';
    try { hash = await sha32(sub.endpoint); } catch (e) { hash = ''; }
    return { sub, device: (res.devices || []).find((d) => d.endpoint_hash === hash) || null };
  }

  function deviceBlock(body, res, here) {
    const box = h('div', { id: 'set-reminders-device', role: 'region', 'aria-labelledby': 'set-reminders-device-h' });
    const msg = h('p', { class: 'status-msg', id: 'set-reminders-device-msg', role: 'status', 'aria-live': 'polite' });
    if (here.device) {
      const off = h('button', { class: 'btn secondary', type: 'button', id: 'set-reminders-off' }, 'Turn off on this device');
      off.addEventListener('click', () => turnOff(body, here, off, msg));
      const test = h('button', { class: 'btn secondary', type: 'button', id: 'set-reminders-test' }, 'Send a test');
      test.addEventListener('click', () => sendTest(test, msg));
      box.append(h('p', { class: 'setting-status' }, h('span', { class: 'state-pill on' }, 'On'), ' Notifications are on for this device.'),
        h('div', { class: 'settings-actions' }, test, off), msg);
      return box;
    }
    if (!MOCK && isIOS() && !standalone()) { box.append(h('p', { class: 'hint', id: 'set-reminders-ios' }, IOS_HOME)); return box; }
    if (!MOCK && !pushSupported()) { box.append(h('p', { class: 'hint', id: 'set-reminders-unsupported' }, NO_PUSH)); return box; }
    if (!MOCK && Notification.permission === 'denied') { box.append(h('p', { class: 'hint', id: 'set-reminders-blocked' }, BLOCKED)); return box; }
    const on = h('button', { class: 'btn primary', type: 'button', id: 'set-reminders-on' }, 'Turn on notifications on this device');
    on.addEventListener('click', () => turnOn(body, res, here, on, msg));
    box.append(h('p', { class: 'hint' }, 'Your browser asks you to allow notifications. Each phone or computer is turned on by itself.'),
      h('div', { class: 'settings-actions' }, on), msg);
    if ((res.devices || []).length) {
      const test = h('button', { class: 'btn secondary', type: 'button', id: 'set-reminders-test' }, 'Send a test');
      test.addEventListener('click', () => sendTest(test, msg));
      box.querySelector('.settings-actions').append(test);
    }
    return box;
  }

  async function turnOn(body, res, here, btn, msg) {
    if (btn.disabled) return;
    btn.disabled = true;
    try {
      if (MOCK) {
        const fake = { endpoint: `https://web.push.apple.com/demo-${Date.now()}`, keys: { p256dh: 'BDemoKeyNotUsed', auth: 'demo' } };
        demoDevice = (await A.addDevice(fake)).id;
        toast('Demo: notifications count as on. Nothing is ever sent.', 'ok');
        await render(body, '#set-reminders-test');
        return;
      }
      // The permission prompt comes only from this tap.
      const permission = await Notification.requestPermission();
      if (permission !== 'granted') { msg.textContent = permission === 'denied' ? BLOCKED : 'Notifications were not allowed. Tap the button again to try.'; return; }
      const reg = await registration();
      if (!reg || !reg.pushManager) { msg.textContent = NO_PUSH; return; }
      let sub = here.sub || await reg.pushManager.getSubscription();
      if (!sub) sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: keyBytes(res.public_key) });
      await A.addDevice(sub.toJSON());
      toast('Notifications are on for this device.', 'ok');
      await render(body, '#set-reminders-test');
    } catch (err) {
      if (err && err.status) { if (!err.handled) toastError(err); } else msg.textContent = `Could not turn notifications on: ${(err && err.message) || 'unknown error'}`;
    } finally { if (document.contains(btn)) btn.disabled = false; }
  }

  async function turnOff(body, here, btn, msg) {
    if (btn.disabled) return;
    btn.disabled = true;
    try {
      if (here.device) await A.removeDevice(here.device.id);
      if (MOCK) demoDevice = null;
      if (here.sub) { try { await here.sub.unsubscribe(); } catch (e) { /* the server forgot it already */ } }
      toast('Notifications are off for this device.', 'ok');
      await render(body, '#set-reminders-on');
    } catch (err) { if (!err.handled) toastError(err); msg.textContent = ''; } finally { if (document.contains(btn)) btn.disabled = false; }
  }

  async function sendTest(btn, msg) {
    if (btn.disabled) return;
    btn.disabled = true;
    try {
      const out = await A.test();
      if (out.demo) msg.textContent = 'Demo: no notification was sent.';
      else if (out.sent) msg.textContent = out.sent === 1 ? 'Sent to 1 device. It may take a minute to arrive.' : `Sent to ${out.sent} devices. It may take a minute to arrive.`;
      else msg.textContent = 'It could not be sent. See the devices below.';
    } catch (err) { if (!err.handled) toastError(err); } finally { if (document.contains(btn)) btn.disabled = false; }
  }

  // ---- the list of reminders ----
  function listBlock(body, res) {
    const box = h('div', { id: 'set-reminders-list', role: 'region', 'aria-labelledby': 'set-reminders-list-h' });
    const list = res.reminders || [];
    if (!list.length) box.append(h('p', { class: 'muted small' }, 'No reminders yet.'));
    const ul = h('ul', { class: 'list device-list' });
    for (const r of list) {
      const what = whatOf(r)[1];
      const edit = h('button', { class: 'btn secondary', type: 'button', 'aria-label': `Change ${what} at ${timeText(r.time)}` }, 'Change');
      const rm = h('button', { class: 'btn secondary', type: 'button', 'aria-label': `Remove ${what} at ${timeText(r.time)}` }, 'Remove');
      const li = h('li', { class: 'device' },
        h('div', { class: 'device-main' },
          h('span', { class: 'row-title' }, `${timeText(r.time)} · ${what}`, r.enabled ? null : h('span', { class: 'badge' }, 'Off')),
          h('span', { class: 'row-sub' }, daysText(r.days))),
        h('div', { class: 'settings-actions' }, edit, rm));
      edit.addEventListener('click', () => { li.after(form(body, res, r)); edit.disabled = true; const f = $('#set-reminder-what'); if (f) f.focus(); });
      rm.addEventListener('click', async () => {
        rm.disabled = true;
        try { await A.remove(r.id); toast('Reminder removed.', 'ok'); await render(body, '#set-reminders-add'); } catch (err) { rm.disabled = false; if (!err.handled) toastError(err); }
      });
      ul.append(li);
    }
    if (list.length) box.append(ul);
    if (list.length < (res.max_reminders || 10)) {
      const add = h('button', { class: 'btn secondary', type: 'button', id: 'set-reminders-add' }, 'Add a reminder');
      add.addEventListener('click', () => { add.hidden = true; add.after(form(body, res, null)); $('#set-reminder-what').focus(); });
      box.append(h('div', { class: 'settings-actions' }, add));
    } else box.append(h('p', { class: 'hint' }, `You have ${res.max_reminders} reminders, the most there can be.`));
    return box;
  }

  function form(body, res, r) {
    const what = h('select', { id: 'set-reminder-what' }, ...WHAT.map((w) => h('option', { value: w[0] }, w[1])));
    what.value = r ? whatOf(r)[0] : 'log_meal:lunch';
    const time = h('input', { id: 'set-reminder-time', type: 'time', required: true, value: r ? r.time : '12:00' });
    const days = r ? r.days : 127;
    const boxes = DAY_NAMES.map((name, i) => {
      const cb = h('input', { type: 'checkbox', id: `set-reminder-day-${i}`, 'aria-label': DAY_LONG[i] });
      cb.checked = !!(days & (1 << i));
      return h('label', { class: 'reminder-check', for: `set-reminder-day-${i}` }, cb, ` ${name}`);
    });
    const enabled = h('input', { type: 'checkbox', id: 'set-reminder-enabled' });
    enabled.checked = r ? r.enabled : true;
    const err = h('div', { class: 'form-error', role: 'alert' });
    const save = h('button', { class: 'btn primary', type: 'submit', id: 'set-reminder-save' }, r ? 'Save changes' : 'Save reminder');
    const cancel = h('button', { class: 'btn secondary', type: 'button' }, 'Cancel');
    const f = h('form', { class: 'settings-form reminder-form', id: 'set-reminder-form', novalidate: true },
      h('div', { class: 'field' }, h('label', { for: 'set-reminder-what' }, 'Remind me to'), what),
      h('div', { class: 'field' }, h('label', { for: 'set-reminder-time' }, 'At'), time,
        h('span', { class: 'hint' }, 'In this device\'s time zone.')),
      h('fieldset', { class: 'field reminder-days' }, h('legend', {}, 'On these days'), h('div', { class: 'reminder-day-list' }, ...boxes)),
      h('div', { class: 'field' }, h('label', { class: 'reminder-check', for: 'set-reminder-enabled' }, enabled, ' On')),
      err, h('div', { class: 'settings-actions' }, save, cancel));
    cancel.addEventListener('click', () => render(body, r ? null : '#set-reminders-add'));
    f.addEventListener('submit', async (e) => {
      e.preventDefault();
      if (save.disabled) return;
      clear(err);
      const mask = boxes.reduce((m, label, i) => (label.querySelector('input').checked ? m | (1 << i) : m), 0);
      if (!/^([01]\d|2[0-3]):[0-5]\d$/.test(time.value)) { err.append(h('p', {}, 'Enter a time such as 12:30.')); time.focus(); return; }
      if (!mask) { err.append(h('p', {}, 'Choose at least one day.')); return; }
      const w = WHAT.find((x) => x[0] === what.value) || WHAT[1];
      const payload = { kind: w[2], meal: w[3], time: time.value, days: mask, time_zone: zone(), enabled: enabled.checked };
      save.disabled = true;
      try {
        if (r) await A.change(r.id, payload); else await A.add(payload);
        toast(r ? 'Reminder saved.' : 'Reminder added.', 'ok');
        await render(body, '#set-reminders-add');
      } catch (e2) {
        save.disabled = false;
        if (!e2.handled) err.append(h('p', {}, (e2 && (e2.detail || e2.message)) || 'Something went wrong'));
      }
    });
    return f;
  }

  // ---- the devices ----
  function devicesBlock(body, res, here) {
    const box = h('div', { id: 'set-reminders-devices', role: 'region', 'aria-labelledby': 'set-reminders-devices-h' });
    const list = res.devices || [];
    if (!list.length) { box.append(h('p', { class: 'muted small' }, 'None yet. Reminders go to each device you turn on here.')); return box; }
    const ul = h('ul', { class: 'list device-list' });
    for (const d of list) {
      const mine = here.device && here.device.id === d.id;
      const name = deviceName(d.user_agent);
      const rm = h('button', { class: 'btn secondary', type: 'button', 'aria-label': `Remove ${name}` }, 'Remove');
      rm.addEventListener('click', async () => {
        if (mine) { await turnOff(body, here, rm, h('p', {})); return; }
        rm.disabled = true;
        try { await A.removeDevice(d.id); toast(`${name} gets no more reminders.`, 'ok'); await render(body); } catch (err) { rm.disabled = false; if (!err.handled) toastError(err); }
      });
      const sub = [`Added ${dateText(d.created_at)}`, d.last_ok_at ? `last sent ${dateText(d.last_ok_at)}` : null].filter(Boolean).join(' · ');
      ul.append(h('li', { class: 'device' },
        h('div', { class: 'device-main' },
          h('span', { class: 'row-title' }, name, mine ? h('span', { class: 'badge this-device' }, 'This device') : null),
          h('span', { class: 'row-sub' }, sub),
          d.last_error ? h('span', { class: 'row-sub form-error' }, ERRORS[d.last_error] || 'The last send did not work.') : null),
        rm));
    }
    box.append(ul);
    return box;
  }

  KH.reminders = { render, daysText, ERRORS, SAFETY };
})();
