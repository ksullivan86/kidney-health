/* Kidney Diet Log — demo API: Connected devices (app/devices/api.py, design notes 27 and 28).

   THE DEMO has no server and never leaves the page, so it shows a sample Withings connection and a sample Whoop connection, kept
   in memory only: connected a month ago, synced this morning. The sample person's morning blood pressure readings are marked "from
   Withings" (js/mock/seed.js); the sample Whoop days and workouts are in js/mock/activity.js. Sync now adds nothing; Connect says the
   demo cannot go to the company; Disconnect works on the samples (and can delete what came from that company).

   DEVICE MODE (the iPhone app; owner, 2026-11-26: "Should Withings and Whoop be set up from the phone?" "yes"). No samples. Each
   company is used one of two ways, the server's first:
   * Through the paired server (a token both ways, design note 39): the status, Sync now and Disconnect are the server's own routes
     through its gateway (`GET /api/devices`, `POST /api/devices/{p}/sync`, `DELETE /api/devices/{p}`). Connect asks the app to
     open the server's own page (`{kind: 'serverPage', page: 'devices', provider}`), where the person signs in to their server and
     connects; the readings then reach the phone through the change feed, and the Whoop days through `GET /api/activity`
     (js/mock/activity.js). The server's connection is preferred: while it has the company connected, the phone's own is not used.
   * On this iPhone, with the person's own developer app (its client ID and secret are in the app's Keychain, typed in Keys and
     services; the page never sees them, nor a token). The app signs in (`deviceConnect`), fetches the company's raw answers
     (`deviceFetch`, with `since`, a Unix time) and ends the access (`deviceDisconnect`). The page reads the answers with the
     server's rules (js/engine/device_map.js) and adds what is new with the twins of app/devices/store.py add_readings and
     add_activity: a ledger of every measure seen (so a deleted reading never comes back), the same reading at the same date and
     HH:MM from any source is already there (Apple Health included), a full day is skipped, and a Whoop day seen before has its
     numbers replaced. It syncs when the app opens or comes back (at most every 10 minutes) and on Sync now. Kept with the log in
     `_devicesState.phone[provider]`: { connected_at, last_sync_at, last_success_at, last_error, status, cursor, seen }. */
(() => {
  'use strict';
  const KH = window.KH;
  const M = KH.mock;
  const { route, MockApi, fail } = M;
  const DEVICE = !!(KH.flags && KH.flags.DEVICE === true);
  const HOUR_MS = 3600000;
  const iso = (hoursAgo) => new Date(Date.now() - hoursAgo * HOUR_MS).toISOString();
  const PROVIDERS = [
    { id: 'withings', name: 'Withings', what: ['weight', 'blood pressure', 'pulse'] },
    { id: 'whoop', name: 'Whoop', what: ['calories burned', 'strain', 'recovery', 'resting heart rate', 'heart rate variability (HRV)', 'sleep', 'workouts'] },
  ];
  const BY_ID = Object.fromEntries(PROVIDERS.map((p) => [p.id, p]));
  const sample = () => ({ status: 'active', connected_at: iso(24 * 30), last_sync_at: iso(3), last_success_at: iso(3), last_error: null });
  const isDict = (v) => v != null && typeof v === 'object' && !Array.isArray(v);
  const truthy = (v) => ['true', '1'].includes(v);

  Object.assign(MockApi.prototype, {
    _devices() {
      if (!this._devicesState) this._devicesState = { connections: this._sample === true && !DEVICE ? { withings: sample(), whoop: sample() } : {} };
      return this._devicesState;
    },
    _deviceCounts(userId, providerId) {
      const weights = this._weightsOf(userId).filter((r) => r.source === providerId).length;
      const readings = this._readingsOf(userId).filter((r) => r.source === providerId).length;
      const act = providerId === 'whoop' && this._activity ? this._activity() : { days: [], workouts: [] };
      return { weights, readings, days: act.days.filter((d) => d.source === providerId).length,
        workouts: act.workouts.filter((w) => w.source === providerId).length };
    },
    _deviceView(userId, providerId) {
      const c = this._devices().connections[providerId];
      if (!c) return null;
      return { ...c, imported: this._deviceCounts(userId, providerId) };
    },
    _deviceProvider(id) {
      if (!BY_ID[id]) fail(404, 'Not Found');
      return BY_ID[id];
    },
    // Removes what came from a company (Disconnect with "Also delete"): the rows still marked with it, and its days and workouts.
    _deleteDeviceRows(user, id) {
      const removed = { weights: 0, readings: 0, days: 0, workouts: 0 };
      for (const r of this._weightsOf(user.id).filter((x) => x.source === id)) { this._deleteWeight(user, r.id); removed.weights += 1; }
      for (const r of this._readingsOf(user.id).filter((x) => x.source === id)) { this._deleteReading(user, r.id); removed.readings += 1; }
      if (id === 'whoop' && this._activity) {
        const act = this._activity();
        removed.days = act.days.filter((d) => d.source === id).length;
        removed.workouts = act.workouts.filter((w) => w.source === id).length;
        act.days = act.days.filter((d) => d.source !== id);
        act.workouts = act.workouts.filter((w) => w.source !== id);
      }
      return removed;
    },

    // ---- the twins of app/devices/store.py (device mode, the phone's own connection) ----
    // add_readings: add what the person does not have yet and note every measure in `seen`. Answers { added, already_there, skipped }.
    _addDeviceReadings(user, provider, readings, seen) {
      const L = KH.bodyRules.LIMITS;
      const roundKg = KH.bodyRules.roundKg;
      const added = { weights: 0, readings: 0 };
      let there = 0; let skipped = 0;
      const unique = new Map();
      for (const r of readings) if (!unique.has(r.external_id)) unique.set(r.external_id, r); // a group listed twice across pages
      const fresh = [...unique.values()].filter((r) => !seen[r.external_id]);
      const weights = this._weightsOf(user.id);
      const bps = this._readingsOf(user.id);
      const wmarks = new Set(weights.filter((w) => w.time).map((w) => `${w.date}|${w.time}|${roundKg(w.kg)}`));
      const rmarks = new Set(bps.filter((b) => b.time).map((b) => `${b.date}|${b.time}|${b.systolic}|${b.diastolic}`));
      const keys = new Set([...weights, ...bps].map((r) => r.source_key).filter(Boolean));
      const perDay = (rows) => { const m = new Map(); for (const r of rows) m.set(r.date, (m.get(r.date) || 0) + 1); return m; };
      const wday = perDay(weights);
      const rday = perDay(bps);
      const minutes = (time) => Number(time.slice(0, 2)) * 60 + Number(time.slice(3, 5));
      const contextOf = (kind, time) => KH.appleHealth.contextOf(kind, minutes(time));
      const at = this._stamp();
      for (const r of fresh) {
        const key = `${provider}:${r.external_id}`;
        if (r.kind === 'weight') {
          let data = null;
          try { data = this._weightBody({ date: r.date, time: r.time, kg: r.kg, context: contextOf('weight', r.time) }); } catch (e) { data = null; }
          if (!data) skipped += 1;
          else {
            const mark = `${data.date}|${data.time}|${roundKg(data.kg)}`;
            if (keys.has(key) || wmarks.has(mark)) there += 1;
            else if ((wday.get(data.date) || 0) >= L.max_weights_per_day) skipped += 1;
            else {
              this._insertWeight(user.id, data, { source: provider, sourceKey: key, createdAt: at });
              wmarks.add(mark); keys.add(key); wday.set(data.date, (wday.get(data.date) || 0) + 1); added.weights += 1;
            }
          }
        } else if (r.kind === 'blood_pressure') {
          const body = { date: r.date, time: r.time, systolic: r.systolic, diastolic: r.diastolic, pulse: r.pulse, context: contextOf('reading', r.time) };
          let data = null;
          try { data = this._readingBody(body); } catch (e) { // a pulse out of range drops the pulse, not the reading
            try { data = this._readingBody({ ...body, pulse: null }); } catch (e2) { data = null; }
          }
          if (!data) skipped += 1;
          else {
            const mark = `${data.date}|${data.time}|${data.systolic}|${data.diastolic}`;
            if (keys.has(key) || rmarks.has(mark)) there += 1;
            else if ((rday.get(data.date) || 0) >= L.max_readings_per_day) skipped += 1;
            else {
              this._insertReading(user.id, data, { source: provider, sourceKey: key, createdAt: at });
              rmarks.add(mark); keys.add(key); rday.set(data.date, (rday.get(data.date) || 0) + 1); added.readings += 1;
            }
          }
        } else skipped += 1;
        seen[r.external_id] = 1;
      }
      return { added, already_there: there + (unique.size - fresh.length), skipped };
    },
    // add_activity: a day or workout seen before has its numbers replaced while its row is still there; a deleted one stays deleted;
    // days after tomorrow are skipped. Answers { days, workouts, updated, skipped }.
    _addDeviceActivity(provider, days, workouts, today, seen) {
      const counts = { days: 0, workouts: 0, updated: 0, skipped: 0 };
      const st = this._activity();
      const latest = KH.util.addDays(today, 1);
      const DAY_FIELDS = ['kcal', 'strain', 'recovery_pct', 'resting_hr', 'hrv_ms', 'sleep_minutes', 'sleep_performance_pct'];
      const WORKOUT_FIELDS = ['date', 'start_time', 'end_time', 'minutes', 'sport', 'kcal', 'strain'];
      const copy = (to, from, fields) => { for (const f of fields) to[f] = from[f] == null ? null : from[f]; };
      for (const d of days) {
        if (d.date > latest) { counts.skipped += 1; continue; }
        const key = `${provider}:${d.external_id}`;
        if (seen[d.external_id]) {
          const row = st.days.find((x) => x.source_key === key);
          if (row) { copy(row, d, DAY_FIELDS); row.finished = d.finished; row.started_at = d.started_at; counts.updated += 1; } else counts.skipped += 1;
          continue;
        }
        const there = st.days.find((x) => x.date === d.date && x.source === provider);
        if (!there) {
          const row = { date: d.date, source: provider, source_key: key, finished: d.finished, started_at: d.started_at };
          copy(row, d, DAY_FIELDS);
          st.days.push(row);
          st.days.sort((a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : 0));
          counts.days += 1;
        } else if ((there.started_at || '') < d.started_at) { // two Whoop days on one date: the one that started later is kept
          there.source_key = key; copy(there, d, DAY_FIELDS); there.finished = d.finished; there.started_at = d.started_at;
          counts.updated += 1;
        } else counts.skipped += 1;
        seen[d.external_id] = 1;
      }
      for (const w of workouts) {
        if (w.date > latest) { counts.skipped += 1; continue; }
        const key = `${provider}:${w.external_id}`;
        if (seen[w.external_id]) {
          const row = st.workouts.find((x) => x.source_key === key);
          if (row) { copy(row, w, WORKOUT_FIELDS); counts.updated += 1; } else counts.skipped += 1;
          continue;
        }
        const row = { source: provider, source_key: key };
        copy(row, w, WORKOUT_FIELDS);
        st.workouts.push(row);
        counts.workouts += 1;
        seen[w.external_id] = 1;
      }
      return counts;
    },
  });

  // ---------------------------------------------------------------------------
  // The demo's routes, and device mode's
  // ---------------------------------------------------------------------------
  route('GET', '/api/devices', function () {
    const user = this._currentUser();
    if (DEVICE) return phone.list(this, user);
    return { enabled: true, can_connect: true, sync_hours: 4,
      providers: PROVIDERS.map((p) => ({ ...p, available: true, connection: this._deviceView(user.id, p.id) })) };
  });
  route('POST', /^\/api\/devices\/([a-z]+)\/start$/, function ({ ids }) {
    const user = this._currentUser();
    const p = this._deviceProvider(ids[0]);
    if (DEVICE) return phone.start(this, user, p);
    return fail(400, `The demo cannot go to ${p.name}. On your own server, this takes you to ${p.name} to say yes.`);
  });
  route('POST', /^\/api\/devices\/([a-z]+)\/sync$/, function ({ ids }) {
    const user = this._currentUser();
    const p = this._deviceProvider(ids[0]);
    if (DEVICE) return phone.syncNow(this, user, p);
    const c = this._devices().connections[ids[0]];
    if (!c) fail(404, 'Not Found');
    c.last_sync_at = c.last_success_at = new Date().toISOString();
    return { connection: this._deviceView(user.id, ids[0]),
      result: { added: { weights: 0, readings: 0, days: 0, workouts: 0 }, already_there: 0, skipped: 0, left_out: 0, updated: 0 }, error: null };
  });
  route('DELETE', /^\/api\/devices\/([a-z]+)$/, function ({ ids, qp }) {
    const user = this._currentUser();
    const id = ids[0];
    const p = this._deviceProvider(id);
    if (DEVICE) return phone.disconnect(this, user, p, truthy(qp('delete_readings')));
    const st = this._devices();
    if (!st.connections[id]) fail(404, 'Not Found');
    st.connections[id] = null;
    const removed = truthy(qp('delete_readings')) ? this._deleteDeviceRows(user, id) : { weights: 0, readings: 0, days: 0, workouts: 0 };
    return { removed, revoked: false };
  });
  // Device mode: sync the phone's own connections that are due (the app opened or came back). Never in the demo.
  route('POST', '/api/device/devices/sync-due', function () {
    const user = this._currentUser();
    if (!DEVICE) fail(404, 'Not Found');
    return phone.syncDue(this, user);
  });

  // ---------------------------------------------------------------------------
  // Device mode
  // ---------------------------------------------------------------------------
  const SYNC_NOW_MIN_MS = 10 * 60 * 1000; // as the server's SYNC_NOW_MIN_S
  const FIRST_DAYS = { withings: 365, whoop: 90 }; // how far back the first sync reaches (withings.py, whoop.py FIRST_DAYS)
  const OVERLAP_S = 3 * 86400; // Whoop: later syncs look again at the last 3 days
  const UNREACHABLE = 'Your server cannot be reached right now. Try again when this iPhone is online.';
  const ERROR_WORDS = { auth: 'auth', rate_limited: 'rate_limited', offline: 'unreachable', unreachable: 'unreachable', scope: 'scope',
    provider_error: 'provider_error' };
  const CONNECT_ERRORS = {
    cancelled: 'Nothing was connected: the sign-in was closed.',
    state: 'That sign-in did not come back from the one this iPhone started. Try again.',
    scope: '{name} did not let this iPhone read what it needs. Connect again and allow it.',
    no_app: 'Add your {name} developer app first: Settings → This device → Apple Health and server → Keys and services.',
    offline: '{name} could not be reached. Try again when this iPhone is online.',
    refused: '{name} did not accept the sign-in. Check the client ID and secret in Keys and services, then try again.',
    busy: 'A sign-in is already open. Finish it or close it first.',
  };
  const said = (text, name) => String(text).split('{name}').join(name);

  async function ask(request) {
    let handler = null;
    try { handler = window.webkit.messageHandlers.bridge; } catch (e) { handler = null; }
    if (!handler) return { error: 'no_app' };
    try {
      const answer = await handler.postMessage(request);
      return isDict(answer) ? answer : { error: 'bad_answer' };
    } catch (e) {
      return { error: 'bridge' };
    }
  }

  const phone = {
    state(api) {
      const st = api._devices();
      if (!isDict(st.phone)) st.phone = {};
      return st.phone;
    },
    // The server's GET /api/devices, or null when there is no server both ways, it cannot be reached, or it has devices off.
    async server() {
      const S = M.serverApi;
      if (!S || !(await S.offers('devices'))) return null;
      const res = await S.call('GET', '/api/devices');
      if (res.offline || res.error || res.status !== 200 || !isDict(res.json) || res.json.enabled !== true) return null;
      return res.json;
    },
    // What the app says about this iPhone's own developer apps (never a secret or a token).
    async own() {
      const res = await ask({ kind: 'deviceStatus' });
      return res.ok && isDict(res.providers) ? res : { providers: {}, relay: null };
    },
    phoneView(api, user, id) {
      const c = phone.state(api)[id];
      if (!isDict(c) || !c.connected_at) return null;
      return { status: c.status || 'active', connected_at: c.connected_at, last_sync_at: c.last_sync_at || null,
        last_success_at: c.last_success_at || null, last_error: c.last_error || null, imported: api._deviceCounts(user.id, id) };
    },
    async list(api, user) {
      const [server, own] = await Promise.all([phone.server(), phone.own()]);
      const status = M.serverApi ? M.serverApi.status() : null;
      const providers = PROVIDERS.map((p) => {
        const theirs = server && Array.isArray(server.providers) ? server.providers.find((x) => x && x.id === p.id) : null;
        const serverOn = !!(theirs && theirs.available);
        const serverConn = theirs && isDict(theirs.connection) ? theirs.connection : null;
        const app = !!(isDict(own.providers[p.id]) && own.providers[p.id].app);
        const mine = phone.phoneView(api, user, p.id);
        const where = serverConn ? 'server' : mine ? 'phone' : null;
        return { ...p, available: serverOn || app || !!mine, connection: serverConn || mine, where,
          connect_via: serverOn ? 'server' : app ? 'phone' : null, server: server ? { available: serverOn } : null,
          phone: { app, connection: mine } };
      });
      return { enabled: true, can_connect: !server || server.can_connect !== false, sync_hours: server ? server.sync_hours : 0,
        device: { server: status && status.state === 'both' ? status.server : null, reachable: !!server, relay: own.relay || null },
        providers };
    },
    async start(api, user, p) {
      const view = (await phone.list(api, user)).providers.find((x) => x.id === p.id);
      if (view.connect_via === 'server') {
        const res = await ask({ kind: 'serverPage', page: 'devices', provider: p.id });
        if (res.error === 'not_paired') fail(409, 'This iPhone is not paired with a server.');
        if (res.error) fail(503, UNREACHABLE);
        return { url: null, opened: 'server' };
      }
      if (view.connect_via !== 'phone') fail(409, said(CONNECT_ERRORS.no_app, p.name));
      const res = await ask({ kind: 'deviceConnect', provider: p.id });
      if (!res.ok) fail(res.error === 'cancelled' ? 400 : 409, said(CONNECT_ERRORS[res.error] || 'Connecting to {name} did not work. Try again.', p.name));
      const st = phone.state(api);
      const before = isDict(st[p.id]) ? st[p.id] : {};
      st[p.id] = { connected_at: new Date().toISOString(), status: 'active', last_sync_at: null, last_success_at: null, last_error: null,
        cursor: null, seen: isDict(before.seen) ? before.seen : {} }; // the ledger stays: a deleted reading never comes back
      const out = await phone.run(api, user, p.id);
      return { url: null, opened: 'phone', result: out.result, error: out.error };
    },
    // One sync of the phone's own connection: fetch since the cursor, read the answer with the server's rules, add what is new.
    async run(api, user, id) {
      const c = phone.state(api)[id];
      const now = Date.now();
      const nowS = Math.floor(now / 1000);
      const cursor = c.cursor != null && /^\d+$/.test(String(c.cursor)) ? Number(c.cursor) : null;
      const since = id === 'whoop' ? (cursor != null ? cursor - OVERLAP_S : nowS - FIRST_DAYS.whoop * 86400)
        : (cursor != null ? cursor : nowS - FIRST_DAYS.withings * 86400);
      c.last_sync_at = new Date(now).toISOString();
      const res = await ask({ kind: 'deviceFetch', provider: id, since: Math.max(0, since) });
      let doc = null;
      if (res.ok && typeof res.json === 'string') { try { doc = JSON.parse(res.json); } catch (e) { doc = null; } }
      if (!res.ok || !isDict(doc)) {
        const code = ERROR_WORDS[res.error] || 'provider_error';
        c.last_error = code;
        if (res.error === 'auth' || res.error === 'not_connected') c.status = 'needs_reconnect';
        return { result: null, error: code };
      }
      const D = KH.deviceMap;
      const seen = isDict(c.seen) ? c.seen : (c.seen = {});
      let result;
      if (id === 'withings') {
        const pages = Array.isArray(doc.pages) ? doc.pages : [];
        const readings = [];
        let leftOut = 0;
        let next = null;
        for (const body of pages) {
          if (!isDict(body)) continue;
          const got = D.withingsReadings(body.measuregrps, body.timezone);
          readings.push(...got.readings);
          leftOut += got.left_out;
          if (next == null && Number.isInteger(body.updatetime) && body.updatetime > 0) next = body.updatetime;
        }
        const out = api._addDeviceReadings(user, id, readings, seen);
        result = { added: { ...out.added, days: 0, workouts: 0 }, already_there: out.already_there, skipped: out.skipped, left_out: leftOut, updated: 0 };
        c.cursor = String(next != null ? next : (Number.isInteger(res.now) ? res.now : nowS));
      } else {
        const days = D.whoopDays(doc.cycles, doc.recoveries, doc.sleeps);
        const workouts = D.whoopWorkouts(doc.workouts);
        const out = api._addDeviceActivity(id, days.days, workouts.workouts, KH.util.todayStr(), seen);
        result = { added: { weights: 0, readings: 0, days: out.days, workouts: out.workouts }, already_there: 0, skipped: out.skipped,
          left_out: days.left_out + workouts.left_out, updated: out.updated };
        c.cursor = String(Number.isInteger(res.now) ? res.now : nowS);
      }
      c.last_success_at = new Date(now).toISOString();
      c.last_error = null;
      c.status = 'active';
      return { result, error: null };
    },
    async syncNow(api, user, p) {
      const view = (await phone.list(api, user)).providers.find((x) => x.id === p.id);
      if (view.where === 'server') {
        const res = await M.serverApi.call('POST', `/api/devices/${p.id}/sync`);
        if (res.offline) fail(503, UNREACHABLE);
        if (res.error || res.status !== 200) M.serverApi.failWith(res.error ? { status: 503, json: { detail: UNREACHABLE } } : res);
        return res.json;
      }
      const c = phone.state(api)[p.id];
      if (!view.phone.connection || !isDict(c)) fail(404, 'Not Found');
      if (c.status === 'needs_reconnect') fail(409, `${p.name} needs you to connect again before it can sync.`);
      const last = c.last_sync_at ? Date.parse(c.last_sync_at) : NaN;
      if (Number.isFinite(last) && Date.now() - last < SYNC_NOW_MIN_MS) {
        fail(429, 'It synced a few minutes ago. Try again in a few minutes.', { retry_after: Math.ceil((SYNC_NOW_MIN_MS - (Date.now() - last)) / 1000) });
      }
      const out = await phone.run(api, user, p.id);
      return { connection: phone.phoneView(api, user, p.id), result: out.result, error: out.error };
    },
    // When the app opens or comes back: each of the phone's own connections not synced in the last 10 minutes, unless the server
    // has that company connected (its readings come through sync then).
    async syncDue(api, user) {
      const st = phone.state(api);
      const ids = Object.keys(st).filter((id) => BY_ID[id] && isDict(st[id]) && st[id].connected_at && st[id].status !== 'needs_reconnect');
      if (!ids.length) return { synced: [] };
      const server = await phone.server();
      const synced = [];
      for (const id of ids) {
        const theirs = server && Array.isArray(server.providers) ? server.providers.find((x) => x && x.id === id) : null;
        if (theirs && isDict(theirs.connection) && theirs.connection.status === 'active') continue;
        const last = st[id].last_sync_at ? Date.parse(st[id].last_sync_at) : NaN;
        if (Number.isFinite(last) && Date.now() - last < SYNC_NOW_MIN_MS) continue;
        const out = await phone.run(api, user, id);
        synced.push({ provider: id, result: out.result, error: out.error });
      }
      return { synced };
    },
    async disconnect(api, user, p, alsoRows) {
      const view = (await phone.list(api, user)).providers.find((x) => x.id === p.id);
      if (view.where === 'server') {
        const res = await M.serverApi.call('DELETE', `/api/devices/${p.id}${alsoRows ? '?delete_readings=true' : ''}`);
        if (res.offline) fail(503, UNREACHABLE);
        if (res.error || res.status !== 200) M.serverApi.failWith(res.error ? { status: 503, json: { detail: UNREACHABLE } } : res);
        return res.json;
      }
      const st = phone.state(api);
      if (!view.phone.connection) fail(404, 'Not Found');
      const res = await ask({ kind: 'deviceDisconnect', provider: p.id }); // the tokens are deleted on the phone whatever the company says
      const before = st[p.id];
      const removed = alsoRows ? api._deleteDeviceRows(user, p.id) : { weights: 0, readings: 0, days: 0, workouts: 0 };
      st[p.id] = alsoRows ? null : { seen: isDict(before) && isDict(before.seen) ? before.seen : {} }; // with the rows, the ledger goes too
      return { removed, revoked: res.revoked === true };
    },
  };

  // When the app opens or comes back to the front: the phone's own connections sync (through the in-page API, so the log is saved).
  if (DEVICE && typeof document !== 'undefined') {
    let running = false;
    const due = async () => {
      if (running || !M.local || !M.local.on() || !KH.state || !KH.state.me) return;
      running = true;
      try {
        const out = await KH.request('POST', '/api/device/devices/sync-due', undefined, { noQueue: true });
        const added = (out && out.synced ? out.synced : []).reduce((n, s) => n + (s.result ? Object.values(s.result.added).reduce((a, b) => a + b, 0) : 0), 0);
        if (added && typeof KH.toast === 'function') {
          const parts = out.synced.filter((s) => s.result).map((s) => `${BY_ID[s.provider].name}`);
          KH.toast(`New data from ${parts.join(' and ')}.`);
        }
      } catch (e) { /* tried again next time the app comes back */ } finally { running = false; }
    };
    const kick = () => { setTimeout(due, 2000); };
    try { document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible') kick(); }); } catch (e) { /* no document */ }
    let tries = 0; // the first time: once someone is signed in and the stored log was read back (at most a minute of looking)
    const first = setInterval(() => {
      tries += 1;
      if (tries > 120) clearInterval(first);
      else if (KH.state && KH.state.me && M.local && M.local.on()) { clearInterval(first); kick(); }
    }, 500);
    if (first && typeof first.unref === 'function') first.unref(); // under Node (the tests) it never keeps the process alive
  }

  M.phoneDevices = phone;
})();
