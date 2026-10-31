/* Kidney Diet Log — demo API: Connected devices (app/devices/api.py, design notes 27 and 28).

   The demo has no server and never leaves the page, so it shows a sample Withings connection and a sample Whoop connection,
   kept in memory only (never saved by "Keep my data in this browser"): connected a month ago, synced this morning. The sample
   person's morning blood pressure readings are marked "from Withings" (js/mock/seed.js); the sample Whoop days and workouts are in
   js/mock/activity.js. Sync now adds nothing; Connect says the demo cannot go to the company; Disconnect works on the samples (and
   can delete what came from that company). */
(() => {
  'use strict';
  const KH = window.KH;
  const M = KH.mock;
  const { route, MockApi, fail } = M;
  const HOUR_MS = 3600000;
  const iso = (hoursAgo) => new Date(Date.now() - hoursAgo * HOUR_MS).toISOString();
  const PROVIDERS = [
    { id: 'withings', name: 'Withings', what: ['weight', 'blood pressure', 'pulse'] },
    { id: 'whoop', name: 'Whoop', what: ['calories burned', 'strain', 'recovery', 'resting heart rate', 'heart rate variability (HRV)', 'sleep', 'workouts'] },
  ];
  const BY_ID = Object.fromEntries(PROVIDERS.map((p) => [p.id, p]));
  const sample = () => ({ status: 'active', connected_at: iso(24 * 30), last_sync_at: iso(3), last_success_at: iso(3), last_error: null });

  Object.assign(MockApi.prototype, {
    _devices() {
      if (!this._devicesState) this._devicesState = { connections: { withings: sample(), whoop: sample() } };
      return this._devicesState;
    },
    _deviceView(userId, providerId) {
      const c = this._devices().connections[providerId];
      if (!c) return null;
      const weights = this._weightsOf(userId).filter((r) => r.source === providerId).length;
      const readings = this._readingsOf(userId).filter((r) => r.source === providerId).length;
      const act = providerId === 'whoop' && this._activity ? this._activity() : { days: [], workouts: [] };
      return { ...c, imported: { weights, readings, days: act.days.length, workouts: act.workouts.length } };
    },
    _deviceProvider(id) {
      if (!BY_ID[id]) fail(404, 'Not Found');
      return BY_ID[id];
    },
  });

  route('GET', '/api/devices', function () {
    const user = this._currentUser();
    return { enabled: true, can_connect: true, sync_hours: 4,
      providers: PROVIDERS.map((p) => ({ ...p, available: true, connection: this._deviceView(user.id, p.id) })) };
  });
  route('POST', /^\/api\/devices\/([a-z]+)\/start$/, function ({ ids }) {
    this._currentUser();
    const p = this._deviceProvider(ids[0]);
    fail(400, `The demo cannot go to ${p.name}. On your own server, this takes you to ${p.name} to say yes.`);
  });
  route('POST', /^\/api\/devices\/([a-z]+)\/sync$/, function ({ ids }) {
    const user = this._currentUser();
    this._deviceProvider(ids[0]);
    const c = this._devices().connections[ids[0]];
    if (!c) fail(404, 'Not Found');
    c.last_sync_at = c.last_success_at = new Date().toISOString();
    return { connection: this._deviceView(user.id, ids[0]),
      result: { added: { weights: 0, readings: 0, days: 0, workouts: 0 }, already_there: 0, skipped: 0, left_out: 0, updated: 0 }, error: null };
  });
  route('DELETE', /^\/api\/devices\/([a-z]+)$/, function ({ ids, qp }) {
    const user = this._currentUser();
    const id = ids[0];
    this._deviceProvider(id);
    const st = this._devices();
    if (!st.connections[id]) fail(404, 'Not Found');
    st.connections[id] = null;
    const removed = { weights: 0, readings: 0, days: 0, workouts: 0 };
    if (['true', '1'].includes(qp('delete_readings'))) {
      for (const r of this._weightsOf(user.id).filter((x) => x.source === id)) { this._deleteWeight(user, r.id); removed.weights += 1; }
      for (const r of this._readingsOf(user.id).filter((x) => x.source === id)) { this._deleteReading(user, r.id); removed.readings += 1; }
      if (id === 'whoop' && this._activity) {
        const act = this._activity();
        removed.days = act.days.length; removed.workouts = act.workouts.length;
        act.days = []; act.workouts = [];
      }
    }
    return { removed, revoked: false };
  });
})();
