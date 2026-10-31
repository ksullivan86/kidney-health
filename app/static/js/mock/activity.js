/* Kidney Diet Log — demo API: activity and recovery from Whoop and the active-day calorie extra (app/activity.py, design note 28).

   The demo shows sample Whoop days for the last 45 days and a few workouts, kept in memory only (never saved by "Keep my data
   in this browser"), as if a Whoop strap had been connected. Today's figure is the day so far. The extra setting starts off,
   as on a real server; turned on, Today and "What fits now" use the same numbers as the server (js/engine/activity.js, pinned
   by tests/data/activity_vectors.json). A Care team view never sees it: the sample people share their food log only. */
(() => {
  'use strict';
  const KH = window.KH;
  const M = KH.mock;
  const { route, MockApi, fail } = M;
  const A = KH.activityRules;
  const DAY_COLUMNS = ['date', 'kcal', 'strain', 'recovery_pct', 'resting_hr', 'hrv_ms', 'sleep_minutes', 'sleep_performance_pct', 'finished', 'source'];
  const WORKOUT_COLUMNS = ['date', 'start_time', 'end_time', 'minutes', 'sport', 'kcal', 'strain', 'source'];
  const SAMPLE_DAYS = 45;
  const SPORTS = [['walking', 45, 190, 6.8], ['cycling', 50, 420, 11.2], ['running', 35, 380, 12.4], ['yoga', 40, 120, 4.1]];

  function addDays(day, n) { return KH.util.addDays(day, n); }
  function today() { return KH.util.todayStr(); }

  // The same sample every time: a quiet week pattern with a workout every few days, today the day so far.
  function sampleDays() {
    const t = today();
    const days = [];
    const workouts = [];
    for (let n = SAMPLE_DAYS - 1; n >= 0; n -= 1) {
      const date = addDays(t, -n);
      const sport = n % 3 === 1 ? SPORTS[(n / 3 | 0) % SPORTS.length] : null;
      const quiet = 2150 + ((n * 37) % 160);
      const kcal = n === 0 ? 2780 : quiet + (sport ? sport[2] : 0);
      days.push({ date, kcal, strain: sport ? sport[3] + (n % 4) / 10 : 5.2 + (n % 5) / 10, recovery_pct: 48 + ((n * 13) % 45),
        resting_hr: 58 + (n % 6), hrv_ms: 38 + ((n * 7) % 22) + 0.5, sleep_minutes: 380 + ((n * 11) % 90),
        sleep_performance_pct: 72 + ((n * 5) % 25), finished: n !== 0, source: 'whoop' });
      if (sport) {
        const start = n % 2 ? '07:10' : '18:05';
        const [h, m] = start.split(':').map(Number);
        const endMin = h * 60 + m + sport[1];
        const end = `${String((endMin / 60) | 0).padStart(2, '0')}:${String(endMin % 60).padStart(2, '0')}`;
        workouts.push({ date, start_time: start, end_time: end, minutes: sport[1], sport: sport[0], kcal: sport[2], strain: sport[3], source: 'whoop' });
      }
    }
    workouts.push({ date: t, start_time: '07:30', end_time: '08:20', minutes: 50, sport: 'cycling', kcal: 430, strain: 11.6, source: 'whoop' });
    return { days, workouts };
  }

  Object.assign(MockApi.prototype, {
    _activity() {
      if (!this._activityState) this._activityState = { ...sampleDays(), extra: { enabled: false, share_pct: A.SHARE_DEFAULT, ceiling_kcal: null } };
      return this._activityState;
    },
    _activityView(start, end) {
      const st = this._activity();
      const pick = (row, cols) => Object.fromEntries(cols.map((k) => [k, row[k] === undefined ? null : row[k]]));
      return { start, end,
        days: st.days.filter((d) => d.date >= start && d.date <= end).map((d) => pick(d, DAY_COLUMNS)),
        workouts: st.workouts.filter((w) => w.date >= start && w.date <= end)
          .sort((a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : 0) || (a.start_time < b.start_time ? -1 : a.start_time > b.start_time ? 1 : 0))
          .map((w) => pick(w, WORKOUT_COLUMNS)) };
    },
    // activity.day_extra: the day's targets with the extra on the calorie target, and what Today shows (null: nothing to add).
    // Never inside a Care team view (the sample people do not share the activity area).
    _dayExtra(date, targets) {
      const out = { ...(targets || {}) };
      if (this._inCareWorld) return [out, null];
      const st = this._activity();
      if (!st.extra.enabled || A.baseKcal(out.calories_kcal) == null) return [out, null];
      const day = st.days.find((d) => d.date === date && d.kcal != null);
      if (!day) return [out, null];
      const from = addDays(date, -A.QUIET_WINDOW_DAYS);
      const history = st.days.filter((d) => d.date >= from && d.date < date && d.finished && d.kcal != null).map((d) => d.kcal);
      const info = A.calorieExtra(st.extra, out.calories_kcal, day.kcal, history);
      if (info) out.calories_kcal = A.raised(out.calories_kcal, info.extra_kcal);
      return [out, info];
    },
    _activityExport() {
      const st = this._activity();
      const all = this._activityView('0000-01-01', '9999-12-31');
      return { activity_days: all.days, activity_workouts: all.workouts, activity_extra: { ...st.extra } };
    },
    _activityRange(start, end) {
      const t = today();
      const e = end ? this._dateParam(end, 'end') : t;
      const s = start ? this._dateParam(start, 'start') : addDays(e, -29);
      this._checkRange(s, e);
      return [s, e];
    },
  });

  route('GET', '/api/activity', function ({ qp }) {
    this._currentUser();
    const [s, e] = this._activityRange(qp('start'), qp('end'));
    return { ...this._activityView(s, e), extra: { ...this._activity().extra } };
  });
  route('PUT', '/api/activity/extra', function ({ body }) {
    const user = this._currentUser();
    const b = body || {};
    const errors = [];
    const enabled = b.enabled === undefined ? false : b.enabled;
    if (typeof enabled !== 'boolean') errors.push('enabled: Input should be a valid boolean');
    const share = b.share_pct === undefined ? A.SHARE_DEFAULT : b.share_pct;
    if (!Number.isInteger(share) || share < A.SHARE_MIN || share > A.SHARE_MAX) errors.push(`share_pct: Input should be between ${A.SHARE_MIN} and ${A.SHARE_MAX}`);
    const ceiling = b.ceiling_kcal === undefined ? null : b.ceiling_kcal;
    if (ceiling !== null && (!Number.isInteger(ceiling) || ceiling < A.CEILING_MIN || ceiling > A.CEILING_MAX)) {
      errors.push(`ceiling_kcal: Input should be between ${A.CEILING_MIN} and ${A.CEILING_MAX}`);
    }
    if (errors.length) fail(400, errors.join('; '));
    const st = this._activity();
    const before = { ...st.extra };
    st.extra = { enabled, share_pct: share, ceiling_kcal: ceiling };
    const changed = JSON.stringify(before) !== JSON.stringify(st.extra);
    if (changed && (enabled || before.enabled) && this._audit) {
      this._audit(user.id, enabled ? 'activity.extra_on' : 'activity.extra_off', 'user', user.id, { share_pct: share, ceiling_kcal: ceiling });
    }
    return { ...st.extra };
  });
  route('GET', /^\/api\/shared\/(\d+)\/activity$/, function ({ ids }) {
    this._careShare(ids[0], 'activity'); // the sample people share their food log only
    return fail(404, 'Not shared with you.');
  });

  Object.assign(M, { ACTIVITY_DAY_COLUMNS: DAY_COLUMNS, ACTIVITY_WORKOUT_COLUMNS: WORKOUT_COLUMNS });
})();
