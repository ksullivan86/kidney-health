/* Kidney Diet Log — demo API: reminders by phone notification (twin of app/reminders.py, design note 35).

   The demo answers like a server with reminders on, and never sends anything: there is no push key, a device is a placeholder,
   and "Send a test" answers demo: true so the page says no notification was sent. Same routes, shapes, limits and words as the
   server; the loop that sends reminders does not exist here. */
(() => {
  'use strict';
  const KH = window.KH;
  const M = KH.mock;
  const { route, MockApi, fail } = M;

  const MAX_REMINDERS = 10;
  const MAX_DEVICES = 5;
  const KINDS = ['log_meal', 'plan_tomorrow', 'weigh_in'];
  const MEALS = ['breakfast', 'lunch', 'dinner', 'snack'];
  const KIND_LABELS = { log_meal: 'Log a meal', plan_tomorrow: 'Plan tomorrow', weigh_in: 'Log your weight' };
  const TEXTS = {
    safety: "Reminders are a convenience. Do not rely on them for low blood sugar; use your CGM's alerts.",
    too_many_reminders: `You have ${MAX_REMINDERS} reminders, the most there can be. Remove one first.`,
    too_many_devices: `Notifications are on for ${MAX_DEVICES} devices, the most there can be. Remove one first.`,
    no_devices: 'Turn on notifications on this device first.',
    bad_endpoint: "This browser's push service is not one this server sends to. Try Safari, Chrome, Edge or Firefox.",
    bad_time: 'Enter a time such as 12:30.',
    bad_days: 'Choose at least one day.',
    bad_zone: 'That time zone is not known. Reload the page and try again.',
    meal_needed: 'Choose which meal.',
    meal_not_here: 'Only a meal reminder has a meal.',
  };
  const TIME_RE = /^([01]\d|2[0-3]):([0-5]\d)$/;
  const ZONE_RE = /^[A-Za-z][A-Za-z0-9_+\-/]{0,63}$/;
  const PUSH_HOSTS = ['fcm.googleapis.com', 'updates.push.services.mozilla.com'];
  const PUSH_SUFFIXES = ['.push.apple.com', '.notify.windows.com'];

  function knownPushHost(endpoint) {
    let u;
    try { u = new URL(String(endpoint || '')); } catch (e) { return false; }
    if (u.protocol !== 'https:' || u.username || u.password || (u.port && u.port !== '443') || u.hash) return false;
    const host = u.hostname.toLowerCase();
    return PUSH_HOSTS.includes(host) || PUSH_SUFFIXES.some((s) => host.endsWith(s) && host.length > s.length);
  }
  function knownZone(name) {
    if (!name) return true;
    if (!ZONE_RE.test(name)) return false;
    try { new Intl.DateTimeFormat('en-US', { timeZone: name }); return true; } catch (e) { return false; }
  }
  function check(kind, meal, time, days, zone) {
    if (!KINDS.includes(kind)) fail(400, "kind: Input should be 'log_meal', 'plan_tomorrow' or 'weigh_in'");
    if (meal != null && !MEALS.includes(meal)) fail(400, "meal: Input should be 'breakfast', 'lunch', 'dinner' or 'snack'");
    if (kind === 'log_meal' && meal == null) fail(400, TEXTS.meal_needed, { field: 'meal' });
    if (kind !== 'log_meal' && meal != null) fail(400, TEXTS.meal_not_here, { field: 'meal' });
    if (typeof time !== 'string' || !TIME_RE.test(time)) fail(400, TEXTS.bad_time, { field: 'time' });
    if (!Number.isInteger(days) || days < 1 || days > 127) fail(400, TEXTS.bad_days, { field: 'days' });
    if (typeof zone !== 'string' || !knownZone(zone)) fail(400, TEXTS.bad_zone, { field: 'time_zone' });
  }
  const view = (r) => ({ id: r.id, kind: r.kind, meal: r.meal, time: r.time, days: r.days, time_zone: r.time_zone, enabled: r.enabled,
    created_at: r.created_at, last_sent_on: r.last_sent_on });
  const deviceView = (d) => ({ id: d.id, endpoint_hash: d.endpoint_hash, user_agent: d.user_agent, created_at: d.created_at,
    last_ok_at: d.last_ok_at, last_error: d.last_error });

  Object.assign(MockApi.prototype, {
    _remindersState() {
      if (!this._reminders) this._reminders = { reminders: [], devices: [], nextId: 1, nextDevice: 1 };
      return this._reminders;
    },
    _remindersExport() { return this._remindersState().reminders.map(view); },
    _reminderOf(id) {
      const r = this._remindersState().reminders.find((x) => x.id === Number(id));
      if (!r) fail(404, 'Not Found');
      return r;
    },
  });

  route('GET', '/api/reminders', function () {
    this._currentUser();
    const st = this._remindersState();
    return { enabled: true, can_use: true, public_key: null, max_reminders: MAX_REMINDERS, max_devices: MAX_DEVICES, safety: TEXTS.safety,
      kinds: KINDS.map((k) => ({ kind: k, label: KIND_LABELS[k], meals: k === 'log_meal' ? MEALS.slice() : [] })),
      reminders: st.reminders.slice().sort((a, b) => (a.time < b.time ? -1 : a.time > b.time ? 1 : a.id - b.id)).map(view),
      devices: st.devices.map(deviceView) };
  });
  route('POST', '/api/reminders', function ({ body }) {
    const u = this._currentUser();
    const b = body || {};
    const days = b.days === undefined ? 127 : b.days;
    const zone = b.time_zone === undefined ? '' : b.time_zone;
    check(b.kind, b.meal == null ? null : b.meal, b.time, days, zone);
    const st = this._remindersState();
    if (st.reminders.length >= MAX_REMINDERS) fail(409, TEXTS.too_many_reminders);
    const r = { id: st.nextId++, kind: b.kind, meal: b.meal == null ? null : b.meal, time: b.time, days, time_zone: zone,
      enabled: b.enabled === undefined ? true : !!b.enabled, created_at: this._stamp(), last_sent_on: null };
    st.reminders.push(r);
    this._audit(u.id, 'reminder.set', 'reminder', r.id, { kind: r.kind, new: true });
    return view(r);
  });
  route('PATCH', '/api/reminders/{id}', function ({ id, body }) {
    const u = this._currentUser();
    const r = this._reminderOf(id);
    const b = body || {};
    const kind = b.kind != null ? b.kind : r.kind;
    const meal = 'meal' in b ? b.meal : (kind === 'log_meal' ? r.meal : null);
    const time = b.time != null ? b.time : r.time;
    const days = b.days != null ? b.days : r.days;
    const zone = b.time_zone != null ? b.time_zone : r.time_zone;
    check(kind, meal, time, days, zone);
    if (time !== r.time || days !== r.days || zone !== r.time_zone) r.last_sent_on = null;
    Object.assign(r, { kind, meal, time, days, time_zone: zone, enabled: b.enabled != null ? !!b.enabled : r.enabled });
    this._audit(u.id, 'reminder.set', 'reminder', r.id, { kind, new: false });
    return view(r);
  });
  route('DELETE', '/api/reminders/{id}', function ({ id }) {
    const u = this._currentUser();
    const r = this._reminderOf(id);
    const st = this._remindersState();
    st.reminders = st.reminders.filter((x) => x !== r);
    this._audit(u.id, 'reminder.removed', 'reminder', r.id, { kind: r.kind });
    return null;
  });
  route('POST', '/api/reminders/subscriptions', function ({ body, header }) {
    const u = this._currentUser();
    const b = body || {};
    if (!knownPushHost(b.endpoint)) fail(400, TEXTS.bad_endpoint, { field: 'endpoint' });
    const st = this._remindersState();
    const same = st.devices.find((d) => d.endpoint === b.endpoint);
    if (same) return deviceView(same);
    if (st.devices.length >= MAX_DEVICES) fail(409, TEXTS.too_many_devices);
    const d = { id: st.nextDevice++, endpoint: b.endpoint, endpoint_hash: `demo${String(st.nextDevice).padStart(28, '0')}`,
      user_agent: (header && header('user-agent')) || navigator.userAgent || null, created_at: this._stamp(), last_ok_at: null, last_error: null };
    st.devices.push(d);
    this._audit(u.id, 'reminder.device_added', 'push_subscription', d.id, {});
    return deviceView(d);
  });
  route('DELETE', '/api/reminders/subscriptions/{id}', function ({ id }) {
    const u = this._currentUser();
    const st = this._remindersState();
    const d = st.devices.find((x) => x.id === Number(id));
    if (!d) fail(404, 'Not Found');
    st.devices = st.devices.filter((x) => x !== d);
    this._audit(u.id, 'reminder.device_removed', 'push_subscription', d.id, { via: 'person' });
    return null;
  });
  route('POST', '/api/reminders/test', function () {
    this._currentUser();
    const st = this._remindersState();
    if (!st.devices.length) fail(409, TEXTS.no_devices);
    return { devices: st.devices.length, sent: 0, failed: 0, removed: 0, demo: true }; // the demo never sends anything
  });

  Object.assign(M, { REMINDER_TEXTS: TEXTS, knownPushHost });
})();
