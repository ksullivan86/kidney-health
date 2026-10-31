/* Kidney Diet Log — demo API: Connected devices (app/devices/api.py, design note 27).

   The demo has no server and never leaves the page, so it shows a sample Withings connection, kept in memory only (never saved
   by "Keep my data in this browser"): connected a month ago, synced this morning, with the sample person's morning blood
   pressure readings marked "from Withings" (js/mock/seed.js). Sync now adds nothing; Connect says the demo cannot go to Withings;
   Disconnect works on the sample (and can delete the sample readings from Withings). */
(() => {
  'use strict';
  const KH = window.KH;
  const M = KH.mock;
  const { route, MockApi, fail } = M;
  const HOUR_MS = 3600000;
  const iso = (hoursAgo) => new Date(Date.now() - hoursAgo * HOUR_MS).toISOString();
  const PROVIDER = { id: 'withings', name: 'Withings', what: ['weight', 'blood pressure', 'pulse'] };

  Object.assign(MockApi.prototype, {
    _devices() {
      if (!this._devicesState) {
        this._devicesState = { connection: { status: 'active', connected_at: iso(24 * 30), last_sync_at: iso(3), last_success_at: iso(3), last_error: null } };
      }
      return this._devicesState;
    },
    _deviceView(userId) {
      const c = this._devices().connection;
      if (!c) return null;
      const weights = this._weightsOf(userId).filter((r) => r.source === 'withings').length;
      const readings = this._readingsOf(userId).filter((r) => r.source === 'withings').length;
      return { ...c, imported: { weights, readings } };
    },
  });

  route('GET', '/api/devices', function () {
    const user = this._currentUser();
    return { enabled: true, can_connect: true, sync_hours: 4, providers: [{ ...PROVIDER, available: true, connection: this._deviceView(user.id) }] };
  });
  route('POST', '/api/devices/withings/start', function () {
    this._currentUser();
    fail(400, 'The demo cannot go to Withings. On your own server, this takes you to Withings to say yes.');
  });
  route('POST', '/api/devices/withings/sync', function () {
    const user = this._currentUser();
    const c = this._devices().connection;
    if (!c) fail(404, 'Not Found');
    c.last_sync_at = c.last_success_at = new Date().toISOString();
    return { connection: this._deviceView(user.id), result: { added: { weights: 0, readings: 0 }, already_there: 0, skipped: 0, left_out: 0 }, error: null };
  });
  route('DELETE', '/api/devices/withings', function ({ qp }) {
    const user = this._currentUser();
    const st = this._devices();
    if (!st.connection) fail(404, 'Not Found');
    st.connection = null;
    const removed = { weights: 0, readings: 0 };
    if (['true', '1'].includes(qp('delete_readings'))) {
      for (const r of this._weightsOf(user.id).filter((x) => x.source === 'withings')) { this._deleteWeight(user, r.id); removed.weights += 1; }
      for (const r of this._readingsOf(user.id).filter((x) => x.source === 'withings')) { this._deleteReading(user, r.id); removed.readings += 1; }
    }
    return { removed, revoked: false };
  });
})();
