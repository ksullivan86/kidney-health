/* Kidney Diet Log — the twins of the server's reading of Withings and Whoop answers (app/devices/withings.py
   readings_from_groups, app/devices/whoop.py build_days and build_workouts; design notes 27 and 28).

   The iPhone app with no server (device mode) connects Withings and Whoop with the person's own developer app: the app fetches
   the company's raw JSON and the page reads it here with the server's rules, so a reading or a Whoop day is the same whether it
   came through a server or straight to the phone. Pinned by tests/data/device_map_vectors.json (tests/data/gen_device_map_vectors.py).

   Numbers are read exactly, as the server's Decimal does: a measure is value × 10^unit; kcal = kJ ÷ 4.184 half up; tenths and
   whole numbers half up (away from zero). Times are read to the microsecond.

   KH.deviceMap = { withingsReadings(groups, accountZone) → { readings, left_out },
                    whoopDays(cycles, recoveries, sleeps) → { days, left_out, user_id },
                    whoopWorkouts(records) → { workouts, left_out }, ... }
   A reading is { kind: 'weight' | 'blood_pressure', external_id, date, time, kg?, systolic?, diastolic?, pulse? }; a day and a
   workout have the fields of app/devices/base.py ActivityDay and Workout. No DOM, no network, no storage. */
(() => {
  'use strict';
  const KH = (globalThis.KH = globalThis.KH || {});

  // ---------------------------------------------------------------------------
  // Exact decimals: a fraction n / d of BigInts (d > 0)
  // ---------------------------------------------------------------------------
  const big = (v) => BigInt(v);
  const TEN = 10n;
  const pow10 = (k) => TEN ** BigInt(k);
  /** The decimal a JSON number stands for (its shortest form, which is Python's repr too), as a fraction; null if not finite. */
  function fraction(value) {
    if (typeof value !== 'number' || !Number.isFinite(value)) return null;
    const m = /^(-?)(\d+)(?:\.(\d+))?(?:e([+-]?\d+))?$/i.exec(String(value));
    if (!m) return null;
    const digits = big(`${m[2]}${m[3] || ''}`);
    const exp = Number(m[4] || 0) - (m[3] ? m[3].length : 0);
    const n = m[1] ? -digits : digits;
    return exp >= 0 ? { n: n * pow10(exp), d: 1n } : { n, d: pow10(-exp) };
  }
  const cmp = (a, b) => { const x = a.n * b.d; const y = b.n * a.d; return x < y ? -1 : x > y ? 1 : 0; };
  const ofInt = (i) => ({ n: big(i), d: 1n });
  const add = (a, b) => ({ n: a.n * b.d + b.n * a.d, d: a.d * b.d });
  const div = (a, k) => ({ n: a.n, d: a.d * big(k) });
  /** Half up (away from zero) to a whole number of 10^-places, as a BigInt count of that unit. */
  function roundUnits(f, places) {
    const n = f.n * pow10(places);
    const neg = n < 0n;
    const absN = neg ? -n : n;
    const q = absN / f.d;
    const r = absN - q * f.d;
    const out = 2n * r >= f.d ? q + 1n : q;
    return neg ? -out : out;
  }
  const whole = (f) => (f == null ? null : Number(roundUnits(f, 0)));
  const tenth = (f) => (f == null ? null : Number(roundUnits(f, 1)) / 10);
  const isInt = (v) => typeof v === 'number' && Number.isInteger(v);
  const isDict = (v) => v != null && typeof v === 'object' && !Array.isArray(v);
  // Python's bool is a whole number: True == 1 and False == 0 where the server compares with numbers.
  const pyInt = (v) => (v === true ? 1 : v === false ? 0 : v);

  // ---------------------------------------------------------------------------
  // Withings (app/devices/withings.py)
  // ---------------------------------------------------------------------------
  const WEIGHT = 1; const DIASTOLIC = 9; const SYSTOLIC = 10; const PULSE = 11;
  const REAL_MEASURE = 1;
  const TAKEN_ATTRIBS = [0, 2, 5, 7, 8];

  /** value × 10^unit as a fraction, or null for anything that is not two whole numbers in a sensible range. */
  function decodeValue(value, unit) {
    if (!isInt(value) || !isInt(unit)) return null; // booleans are not numbers here (typeof), as the server's check
    if (unit < -12 || unit > 12 || Math.abs(value) > 1e15) return null;
    return unit >= 0 ? { n: big(value) * pow10(unit), d: 1n } : { n: big(value), d: pow10(-unit) };
  }
  const toFloat = (f) => { // the nearest double, as Python's float(Decimal)
    if (f.d === 1n) return Number(f.n);
    const places = String(f.d).length - 1; // d is a power of ten here
    return Number(`${f.n}e-${places}`);
  };

  const ZONE_NAME = /^(UTC|[A-Z][A-Za-z0-9_+-]*(\/[A-Za-z0-9_+-]+)*)$/;
  const formatters = new Map();
  function zoneFormatter(name) {
    if (typeof name !== 'string' || name.length < 1 || name.length > 64 || !ZONE_NAME.test(name)) return null;
    if (formatters.has(name)) return formatters.get(name);
    let f = null;
    try {
      f = new Intl.DateTimeFormat('en-US', { timeZone: name, year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit',
        minute: '2-digit', hourCycle: 'h23' });
    } catch (e) { f = null; }
    formatters.set(name, f);
    return f;
  }
  /** [YYYY-MM-DD, HH:MM] of a Unix time on the person's clock: the zone Withings gives, else the account's, else UTC. */
  function localMoment(epoch, zoneName, fallbackZone) {
    const f = zoneFormatter(zoneName) || zoneFormatter(fallbackZone) || zoneFormatter('UTC');
    const parts = {};
    for (const p of f.formatToParts(new Date(epoch * 1000))) parts[p.type] = p.value;
    const hour = parts.hour === '24' ? '00' : parts.hour;
    return [`${parts.year}-${parts.month}-${parts.day}`, `${hour}:${parts.minute}`];
  }

  /** The weights and blood pressure readings in `measuregrps`, and how many groups or measures were left out. */
  function withingsReadings(groups, accountZone) {
    const out = [];
    let leftOut = 0;
    if (!Array.isArray(groups)) return { readings: out, left_out: 0 };
    for (const group of groups) {
      if (!isDict(group)) { leftOut += 1; continue; }
      const grpid = group.grpid;
      const epoch = group.date;
      const category = pyInt(group.category === undefined ? REAL_MEASURE : group.category);
      const attrib = pyInt(group.attrib === undefined ? 0 : group.attrib);
      if (!isInt(grpid) || grpid <= 0 || !isInt(epoch) || !(epoch > 0 && epoch < 1e11) || category !== REAL_MEASURE
          || !TAKEN_ATTRIBS.includes(attrib)) { leftOut += 1; continue; }
      const values = new Map();
      for (const m of Array.isArray(group.measures) ? group.measures : []) {
        const type = isDict(m) ? pyInt(m.type) : null;
        if ([WEIGHT, DIASTOLIC, SYSTOLIC, PULSE].includes(type)) {
          const v = decodeValue(m.value, m.unit);
          if (v !== null) values.set(type, v);
        }
      }
      if (!values.size) { leftOut += 1; continue; }
      const [day, clock] = localMoment(epoch, group.timezone, accountZone);
      if (values.has(WEIGHT)) out.push({ kind: 'weight', external_id: `${grpid}:weight`, date: day, time: clock, kg: toFloat(values.get(WEIGHT)) });
      if (values.has(SYSTOLIC) && values.has(DIASTOLIC)) {
        out.push({ kind: 'blood_pressure', external_id: `${grpid}:bp`, date: day, time: clock, systolic: whole(values.get(SYSTOLIC)),
          diastolic: whole(values.get(DIASTOLIC)), pulse: values.has(PULSE) ? whole(values.get(PULSE)) : null });
      } else if (!values.has(WEIGHT)) leftOut += 1; // a pulse alone, or half a blood pressure reading
    }
    return { readings: out, left_out: leftOut };
  }

  // ---------------------------------------------------------------------------
  // Whoop (app/devices/whoop.py)
  // ---------------------------------------------------------------------------
  const RANGES = { kcal: [1, 15000], strain: [0, 21], recovery_pct: [0, 100], resting_hr: [20, 250], hrv_ms: [1, 500],
    sleep_minutes: [0, 1440], sleep_performance_pct: [0, 100], workout_minutes: [0, 1440] };
  const SCORED = 'SCORED';
  const DAY_SHIFT_US = 12 * 3600 * 1e6;
  const number = (v) => (typeof v === 'number' ? fraction(v) : null);
  function within(name, f) {
    const [lo, hi] = RANGES[name];
    return f != null && cmp(f, ofInt(lo)) >= 0 && cmp(f, ofInt(hi)) <= 0 ? f : null;
  }
  /** Whole kcal (half up) of a kilojoule figure, or null when it is not a plausible day or workout. */
  function kcalFromKj(kj) {
    const f = number(kj);
    if (f == null) return null;
    const kcal = ofInt(Number(roundUnits({ n: f.n * 1000n, d: f.d * 4184n }, 0)));
    return whole(within('kcal', kcal));
  }

  const ISO = /^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2})(?::(\d{2})(?:[.,](\d{1,6}))?)?)?(Z|[+-]\d{2}:?\d{2})?$/;
  /** A Whoop timestamp (ISO 8601) as microseconds since 1970 (UTC), or null. A time with no zone is UTC. */
  function parseTime(value) {
    if (typeof value !== 'string' || value.length < 10 || value.length > 40) return null;
    const m = ISO.exec(value);
    if (!m) return null;
    const [y, mo, d, h = '0', mi = '0', s = '0', frac = '', zone] = m.slice(1);
    const Y = Number(y); const M = Number(mo); const D = Number(d);
    if (M < 1 || M > 12 || D < 1 || Number(h) > 23 || Number(mi) > 59 || Number(s) > 59) return null;
    const ms = Date.UTC(Y, M - 1, D, Number(h), Number(mi), Number(s));
    const check = new Date(ms);
    if (check.getUTCFullYear() !== Y || check.getUTCMonth() !== M - 1 || check.getUTCDate() !== D) return null;
    if (zone && zone !== 'Z' && !/^[+-]\d{2}:?\d{2}$/.test(zone)) return null;
    let us = ms * 1000 + Number(frac.padEnd(6, '0') || 0);
    if (zone && zone !== 'Z') {
      const z = /^([+-])(\d{2}):?(\d{2})$/.exec(zone);
      const off = (Number(z[2]) * 60 + Number(z[3])) * 60e6;
      if (Number(z[2]) > 23 || Number(z[3]) > 59) return null;
      us -= z[1] === '-' ? -off : off;
    }
    return us;
  }
  /** `+hh:mm`, `-hh:mm` (or with no colon) as an offset in microseconds; 0 (UTC) for anything else. */
  function parseOffset(value) {
    if (typeof value === 'string') {
      const m = /^([+-])(\d{2}):?(\d{2})$/.exec(value.trim());
      if (m) {
        const hours = Number(m[2]); const minutes = Number(m[3]);
        if (hours <= 14 && minutes < 60) { const us = (hours * 60 + minutes) * 60e6; return m[1] === '-' ? -us : us; }
      }
    }
    return 0;
  }
  const pad = (n, w = 2) => String(n).padStart(w, '0');
  function wall(us) { // the UTC fields of a moment given as microseconds
    const d = new Date(Math.floor(us / 1000));
    return { date: `${pad(d.getUTCFullYear(), 4)}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())}`,
      time: `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}` };
  }
  const dayOfCycle = (startUs, offsetUs) => wall(startUs + offsetUs + DAY_SHIFT_US).date;
  function iso(us) {
    const d = new Date(Math.floor(us / 1000));
    const micro = ((us % 1e6) + 1e6) % 1e6;
    return `${pad(d.getUTCFullYear(), 4)}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())}T${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}:${pad(d.getUTCSeconds())}.${pad(micro, 6)}Z`;
  }
  const scored = (r) => (r.score_state === SCORED && isDict(r.score) ? r.score : null);
  const wholeId = (v) => (isInt(v) && v > 0 ? v : null);
  /** A short, plain sport name from Whoop's `sport_name`. */
  function sportLabel(value) {
    if (typeof value !== 'string') return '';
    const text = value.replace(/-/g, ' ').replace(/_/g, ' ').replace(/[^0-9A-Za-z ()/&+'.]+/g, ' ');
    return text.split(/\s+/).filter(Boolean).join(' ').slice(0, 40);
  }

  const DAY_VALUES = ['kcal', 'strain', 'recovery_pct', 'resting_hr', 'hrv_ms', 'sleep_minutes', 'sleep_performance_pct'];
  /** Join cycles with their recovery and sleep into days: { days, left_out, user_id }. */
  function whoopDays(cycles, recoveries, sleeps) {
    let leftOut = 0;
    let userId = null;
    const base = new Map();
    for (const c of Array.isArray(cycles) ? cycles : []) {
      if (!isDict(c)) { leftOut += 1; continue; }
      const cid = wholeId(c.id);
      const start = parseTime(c.start);
      if (cid == null || start == null) { leftOut += 1; continue; }
      if (userId == null && wholeId(c.user_id)) userId = String(c.user_id);
      const zone = parseOffset(c.timezone_offset);
      const score = scored(c) || {};
      base.set(cid, { date: dayOfCycle(start, zone), start, finished: parseTime(c.end) != null, kcal: kcalFromKj(score.kilojoule),
        strain: tenth(within('strain', number(score.strain))) });
      if (!Object.keys(score).length) leftOut += 1; // not scored yet: the next sync looks again
    }
    for (const r of Array.isArray(recoveries) ? recoveries : []) {
      const score = isDict(r) ? scored(r) : null;
      const cid = isDict(r) ? wholeId(r.cycle_id) : null;
      if (score == null || !base.has(cid)) { leftOut += 1; continue; }
      const d = base.get(cid);
      d.recovery_pct = whole(within('recovery_pct', number(score.recovery_score)));
      d.resting_hr = whole(within('resting_hr', number(score.resting_heart_rate)));
      d.hrv_ms = tenth(within('hrv_ms', number(score.hrv_rmssd_milli)));
    }
    for (const s of Array.isArray(sleeps) ? sleeps : []) {
      const score = isDict(s) ? scored(s) : null;
      const cid = isDict(s) ? wholeId(s.cycle_id) : null;
      if (score == null || !base.has(cid) || s.nap === true) { leftOut += 1; continue; }
      const d = base.get(cid);
      const stages = isDict(score.stage_summary) ? score.stage_summary : {};
      const parts = ['total_light_sleep_time_milli', 'total_slow_wave_sleep_time_milli', 'total_rem_sleep_time_milli'].map((k) => number(stages[k]));
      if (parts.every((p) => p != null && cmp(p, ofInt(0)) >= 0)) {
        const asleep = add(div(parts.reduce(add, ofInt(0)), 60000), d._asleep || ofInt(0));
        d._asleep = asleep;
        d.sleep_minutes = whole(within('sleep_minutes', asleep));
      }
      const perf = whole(within('sleep_performance_pct', number(score.sleep_performance_percentage)));
      if (perf != null) d.sleep_performance_pct = perf;
    }
    const byDate = new Map();
    for (const [cid, d] of base) {
      if (!DAY_VALUES.some((k) => d[k] != null)) continue;
      const kept = byDate.get(d.date);
      if (kept === undefined || d.start > kept[1].start) {
        if (kept !== undefined) leftOut += 1;
        byDate.set(d.date, [cid, d]);
      } else leftOut += 1; // two cycles on one date: the one that started later is kept
    }
    const days = [...byDate.values()].sort((a, b) => (a[1].date < b[1].date ? -1 : a[1].date > b[1].date ? 1 : 0)).map(([cid, d]) => ({
      external_id: `cycle:${cid}`, date: d.date, started_at: iso(d.start), finished: d.finished,
      kcal: d.kcal == null ? null : d.kcal, strain: d.strain == null ? null : d.strain, recovery_pct: d.recovery_pct == null ? null : d.recovery_pct,
      resting_hr: d.resting_hr == null ? null : d.resting_hr, hrv_ms: d.hrv_ms == null ? null : d.hrv_ms,
      sleep_minutes: d.sleep_minutes == null ? null : d.sleep_minutes, sleep_performance_pct: d.sleep_performance_pct == null ? null : d.sleep_performance_pct }));
    return { days, left_out: leftOut, user_id: userId };
  }

  const WORKOUT_ID = /^[0-9A-Za-z-]{1,64}$/;
  function whoopWorkouts(records) {
    const out = [];
    let leftOut = 0;
    for (const w of Array.isArray(records) ? records : []) {
      const score = isDict(w) ? scored(w) : null;
      const wid = isDict(w) ? w.id : null;
      const start = isDict(w) ? parseTime(w.start) : null;
      if (score == null || typeof wid !== 'string' || !WORKOUT_ID.test(wid) || start == null) { leftOut += 1; continue; }
      const zone = parseOffset(w.timezone_offset);
      const end = parseTime(w.end);
      let minutes = null;
      if (end != null && end >= start) {
        minutes = whole(within('workout_minutes', { n: big(end - start), d: 60000000n }));
        if (minutes == null) { leftOut += 1; continue; }
      }
      const local = wall(start + zone);
      out.push({ external_id: `workout:${wid.toLowerCase()}`, date: local.date, start_time: local.time,
        end_time: end != null ? wall(end + zone).time : null, minutes, sport: sportLabel(w.sport_name),
        kcal: kcalFromKj(score.kilojoule), strain: tenth(within('strain', number(score.strain))) });
    }
    return { workouts: out, left_out: leftOut };
  }

  KH.deviceMap = { withingsReadings, whoopDays, whoopWorkouts, decodeValue, localMoment, kcalFromKj, parseTime, parseOffset, sportLabel,
    toFloat, iso };
})();
