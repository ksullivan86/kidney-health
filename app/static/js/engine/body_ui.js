/* Kidney Diet Log — weight and blood pressure screens: what the views are made of (ARCHITECTURE.md "Weight and blood pressure",
   note 10 §4.6).

   Pure functions, no DOM, no I/O. js/views/body.js (the Today card, the two sheets, the Settings section, the Profile hints) and
   js/views/body_trends.js (the charts and their tables) draw what these return; js/engine/visitprep.js builds the visit prep
   section from the same rows. The numbers themselves are js/engine/body.js (KH.bodyRules, the twin of app/body.py): this file
   only reads what a person types, words what the server answered, and works out where a mark goes on a chart.

   * Entry: weightFromInput / alarmFromInput (a number in the person's unit → kilograms, 0.01 kg, the project's own plausibility
     ranges), readingFromInput / goalFromInput (whole numbers), and the echoes the sheets show before Save ("154.3 lb = 70.0 kg",
     "Top 180, bottom 95") so a typing slip is seen.
   * Words: amounts, gains, the alarm and the goal as sentences, times of day. The app records and shows. It says nothing about a
     cause, a treatment or a medicine, so there is nothing of the kind here.
   * Charts: niceTicks, makeAxes (x by day and time of day, y by value), xLabels, linePath, the series for the weight and the blood
     pressure charts, and the table rows under them (nothing depends on seeing a chart or on colour).
   * weekAverages: the mean of each kind of weight (morning, before dialysis ...) over the last 7 days. Kinds are never mixed.
   * originText: where a stored row came from in words ("from a shortcut (Morning weight)", "from the Health app", "from a file"; nothing for a typed row).

   Tests: tests/js/body_ui_runner.mjs through tests/test_body_ui_numbers.py (against the server's own functions in app/body.py).

   Needs js/engine/rules.js and js/engine/body.js first.
   Exposes KH.bodyUi = { WEIGHT_CONTEXT_LABELS, BP_CONTEXT_LABELS, MONTHS, BP_HINT, GOAL_LIMITS, ALARM_LIMITS, SIX_MONTH_LOOKBACK_DAYS,
   contextChoices, contextLabel, parseNumber, rangeText, weightFromInput, echoWeight, readingFromInput, echoReading, alarmFromInput, goalFromInput, inputNumber, fmtTime,
   amountText, gainText, alarmSentence, goalText, weekSentences, weekAverages, niceTicks, makeAxes, xLabels, linePath, weightSeries,
   readingSeries, domainOf, weightRows, readingRows, originText, profileWeightHint }. */
(() => {
  'use strict';
  const root = typeof window !== 'undefined' ? window : globalThis;
  const KH = root.KH || (root.KH = {});
  const R = KH.bodyRules;
  const { halfUp } = KH.rules;
  const L = R.LIMITS;

  const WEIGHT_CONTEXT_LABELS = { morning: 'Morning', before_dialysis: 'Before dialysis', after_dialysis: 'After dialysis', other: 'Other' };
  const BP_CONTEXT_LABELS = { morning: 'Morning', evening: 'Evening', before_dialysis: 'Before dialysis', after_dialysis: 'After dialysis', other: 'Other' };
  const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  // The one line of the sheet: MedlinePlus "Measuring Blood Pressure" (note 10 F6, source id MEDLINE-BPM).
  const BP_HINT = 'Rest about 5 minutes first, sit with your feet flat, and put the cuff on your upper arm.';
  // The goal's and the alarm's own limits (app/settings_registry.py; the care team's numbers, the app suggests none).
  const GOAL_LIMITS = { min_systolic: 80, max_systolic: 200, min_diastolic: 40, max_diastolic: 130 };
  const ALARM_LIMITS = { min_kg: 0.2, max_kg: 10, min_days: 1, max_days: 7 };
  // The six-month rule looks at weights dated 182 days before the latest, within 30 days either way (app/body.py SIX_MONTH_DAYS and
  // SIX_MONTH_WINDOW_DAYS): a list from this many days before the latest weight holds every candidate.
  const SIX_MONTH_LOOKBACK_DAYS = 182 + 30;

  const other = (unit) => (unit === 'kg' ? 'lb' : 'kg');
  const plural = (n, one, many) => (n === 1 ? one : many);

  // ---- contexts: when a weight or a reading was taken. The dialysis choices only for a profile on dialysis (and for the row
  // being edited, so its own choice is never lost). `kind` is 'weight' or 'bp'.
  function contextChoices(kind, onDialysis, current = null) {
    const labels = kind === 'bp' ? BP_CONTEXT_LABELS : WEIGHT_CONTEXT_LABELS;
    return Object.keys(labels).filter((k) => onDialysis || current === k || (k !== 'before_dialysis' && k !== 'after_dialysis')).map((k) => [k, labels[k]]);
  }
  const contextLabel = (kind, key) => (kind === 'bp' ? BP_CONTEXT_LABELS : WEIGHT_CONTEXT_LABELS)[key] || key;

  // ---- reading what was typed
  // "154.3" or "154,3" (a comma decimal mark is common) → the number, NaN when it is anything else.
  function parseNumber(text) {
    const t = String(text == null ? '' : text).trim().replace(',', '.');
    return /^(?:\d+(?:\.\d+)?|\.\d+)$/.test(t) ? Number(t) : NaN;
  }
  // "154" → "154", "154.30" → "154.3": a number as a person would write it in a box.
  const inputNumber = (n) => String(Number(n));
  // The limits written in the person's unit so that both ends can be typed: the low end rounded up, the high end down, to one decimal.
  function rangeText(minKg, maxKg, unit) {
    if (unit === 'kg') return `${inputNumber(minKg)} and ${inputNumber(maxKg)} kg`;
    const lo = Math.ceil(halfUp(minKg / R.KG_PER_LB * 10, 6)) / 10;
    const hi = Math.floor(halfUp(maxKg / R.KG_PER_LB * 10, 6)) / 10;
    return `${inputNumber(lo)} and ${inputNumber(hi)} lb`;
  }

  // A weight typed in `unit` → { kg } (stored: kilograms, 0.01) or { error }.
  function weightFromInput(text, unit) {
    const raw = String(text == null ? '' : text).trim();
    if (!raw) return { error: 'Enter your weight.' };
    const n = parseNumber(raw);
    if (!Number.isFinite(n)) return { error: `Enter a number, for example ${unit === 'kg' ? '70.2' : '154.8'}.` };
    const kg = unit === 'kg' ? R.roundKg(n) : R.lbToKg(n);
    if (kg < L.min_kg || kg > L.max_kg) return { error: `Enter a weight between ${rangeText(L.min_kg, L.max_kg, unit)}.` };
    return { kg };
  }
  // "154.3 lb = 70.0 kg": the weight in the unit it was typed and in the other one.
  const echoWeight = (kg, unit) => `${R.formatWeight(kg, unit)} = ${R.formatWeight(kg, other(unit))}`;

  // The three boxes of a reading (strings) → { systolic, diastolic, pulse, errors: { field: message } }.
  function readingFromInput({ systolic = '', diastolic = '', pulse = '' } = {}) {
    const errors = {};
    const whole = (text, field, name, lo, hi, optional) => {
      const t = String(text == null ? '' : text).trim();
      if (!t) { if (!optional) errors[field] = `Enter the ${name}.`; return null; }
      if (!/^\d{1,3}$/.test(t)) { errors[field] = `The ${name} is a whole number, for example ${field === 'systolic' ? 120 : field === 'diastolic' ? 80 : 64}.`; return null; }
      const n = Number(t);
      if (n < lo || n > hi) { errors[field] = `The ${name} is between ${lo} and ${hi}.`; return null; }
      return n;
    };
    const top = whole(systolic, 'systolic', 'top number', L.min_systolic, L.max_systolic, false);
    const bottom = whole(diastolic, 'diastolic', 'bottom number', L.min_diastolic, L.max_diastolic, false);
    const beats = whole(pulse, 'pulse', 'pulse', L.min_pulse, L.max_pulse, true);
    if (top != null && bottom != null && top <= bottom) errors.diastolic = 'The top number must be higher than the bottom number.';
    return { systolic: top, diastolic: bottom, pulse: beats, errors };
  }
  // "Top 180, bottom 95, pulse 64": what the boxes say now, so a slip (1800, 59 for 95) is seen before Save. '' with nothing typed.
  function echoReading(systolic, diastolic, pulse) {
    const digits = (v) => { const t = String(v == null ? '' : v).trim(); return /^\d{1,4}$/.test(t) ? t : ''; };
    const parts = [];
    if (digits(systolic)) parts.push(`Top ${digits(systolic)}`);
    if (digits(diastolic)) parts.push(`${parts.length ? 'bottom' : 'Bottom'} ${digits(diastolic)}`);
    if (digits(pulse)) parts.push(`${parts.length ? 'pulse' : 'Pulse'} ${digits(pulse)}`);
    return parts.join(', ');
  }

  // The weight-gain alarm typed in `unit` (empty = no alarm) → { amount_kg } (null for none) or { error }.
  function alarmFromInput(text, unit) {
    const raw = String(text == null ? '' : text).trim();
    if (!raw) return { amount_kg: null };
    const n = parseNumber(raw);
    if (!Number.isFinite(n)) return { error: `Enter a number, for example ${unit === 'kg' ? '1' : '2.2'}.` };
    const kg = unit === 'kg' ? R.roundKg(n) : R.lbToKg(n);
    if (kg < ALARM_LIMITS.min_kg || kg > ALARM_LIMITS.max_kg) return { error: `Enter a number between ${rangeText(ALARM_LIMITS.min_kg, ALARM_LIMITS.max_kg, unit)}.` };
    return { amount_kg: kg };
  }
  // The goal's two boxes (empty = not set) → { systolic, diastolic, errors }.
  function goalFromInput(systolic, diastolic) {
    const errors = {};
    const one = (text, field, name, lo, hi) => {
      const t = String(text == null ? '' : text).trim();
      if (!t) return null;
      if (!/^\d{1,3}$/.test(t)) { errors[field] = `The ${name} is a whole number.`; return null; }
      const n = Number(t);
      if (n < lo || n > hi) { errors[field] = `The ${name} is between ${lo} and ${hi}.`; return null; }
      return n;
    };
    const top = one(systolic, 'systolic', 'top number', GOAL_LIMITS.min_systolic, GOAL_LIMITS.max_systolic);
    const bottom = one(diastolic, 'diastolic', 'bottom number', GOAL_LIMITS.min_diastolic, GOAL_LIMITS.max_diastolic);
    if (top != null && bottom != null && top <= bottom) errors.diastolic = 'The top number must be higher than the bottom number.';
    return { systolic: top, diastolic: bottom, errors };
  }

  // ---- words
  // "07:15" → "7:15 AM"; null (no time) → ''.
  function fmtTime(time) {
    if (!time) return '';
    const [hh, mm] = String(time).split(':').map(Number);
    return `${hh % 12 || 12}:${String(mm).padStart(2, '0')} ${hh < 12 ? 'AM' : 'PM'}`;
  }
  const amountText = (kg, unit) => R.formatWeight(kg, unit);
  // A change in weight: "up 1.8 lb", "down 0.5 kg", "no change" (one decimal, half up, in the person's unit).
  function gainText(kg, unit) {
    const shown = R.shownWeight(Math.abs(kg), unit);
    if (shown === 0) return 'no change';
    return `${kg > 0 ? 'up' : 'down'} ${shown.toFixed(1)} ${unit}`;
  }
  // "more than 2.2 lb between sessions" / "more than 1.0 kg in 1 day": the alarm as the care team gave it.
  function alarmSentence(alarm, unit) {
    const when = alarm.over === 'between_sessions' ? 'between sessions' : `in ${alarm.days} ${plural(Number(alarm.days), 'day', 'days')}`;
    return `more than ${amountText(alarm.amount_kg, unit)} ${when}`;
  }
  // "under 130/80", "top number under 130", "bottom number under 80", or null with no goal.
  function goalText(goal) {
    const s = goal && goal.systolic != null ? goal.systolic : null;
    const d = goal && goal.diastolic != null ? goal.diastolic : null;
    if (s != null && d != null) return `under ${s}/${d}`;
    if (s != null) return `top number under ${s}`;
    if (d != null) return `bottom number under ${d}`;
    return null;
  }
  // The server's week (summary.bp.week) in plain sentences: how many readings, the averages and, with enough readings and a goal,
  // which average is at or above the goal. → [sentence].
  function weekSentences(week, goal) {
    if (!week || !week.count) return ['No readings in the last 7 days.'];
    const lines = [`Last 7 days: average ${week.systolic}/${week.diastolic} from ${week.count} ${plural(week.count, 'reading', 'readings')}.`];
    const text = goalText(goal);
    if (week.few) { if (text) lines.push(`Only ${week.count} ${plural(week.count, 'reading', 'readings')}, too few to compare with your goal.`); return lines; }
    if (week.above_goal === null || week.above_goal === undefined) return lines;
    const named = [];
    if (week.above && week.above.systolic) named.push(`top number ${week.systolic} is at or above ${goal.systolic}`);
    if (week.above && week.above.diastolic) named.push(`bottom number ${week.diastolic} is at or above ${goal.diastolic}`);
    lines.push(week.above_goal ? `Average ${named.join(' and ')}.` : `The average is under your goal (${text}).`);
    return lines;
  }

  // The mean of each kind of weight over the day and the 6 before it (WEEK_DAYS of app/body.py): never mixing morning with after dialysis.
  // → [{ context, label, count, mean_kg }] in the order of WEIGHT_CONTEXTS, kinds with no weight left out.
  function weekAverages(weights, day) {
    const floor = R.shiftDay(day, -6);
    const out = [];
    for (const context of R.WEIGHT_CONTEXTS) {
      const mine = weights.filter((w) => w.context === context && w.date >= floor && w.date <= day);
      if (!mine.length) continue;
      out.push({ context, label: WEIGHT_CONTEXT_LABELS[context], count: mine.length, mean_kg: R.roundKg(mine.reduce((a, w) => a + w.kg, 0) / mine.length) });
    }
    return out;
  }

  // ---- charts
  // 1, 2, 5 × 10^n: the usual "nice number" for a tick step (Heckbert).
  function niceNum(range, round) {
    const exp = Math.floor(Math.log10(range));
    const f = range / 10 ** exp;
    const nf = round ? (f < 1.5 ? 1 : f < 3 ? 2 : f < 7 ? 5 : 10) : (f <= 1 ? 1 : f <= 2 ? 2 : f <= 5 ? 5 : 10);
    return nf * 10 ** exp;
  }
  // Round tick values to the step's own decimals so 0.1 + 0.2 never shows as 0.30000000000000004.
  const tidy = (v, step) => Number(v.toFixed(Math.max(0, 1 - Math.floor(Math.log10(step)))));
  // → { min, max, step, ticks } covering [min, max] with about `count` ticks.
  function niceTicks(min, max, count = 4) {
    if (!(max > min)) { const pad = Math.max(0.5, Math.abs(min) * 0.01); min -= pad; max += pad; }
    const step = niceNum(niceNum(max - min, false) / Math.max(1, count - 1), true);
    const lo = tidy(Math.floor(min / step + 1e-9) * step, step);
    const hi = tidy(Math.ceil(max / step - 1e-9) * step, step);
    const ticks = [];
    for (let v = lo; v <= hi + step / 2; v += step) ticks.push(tidy(v, step));
    return { min: lo, max: hi, step, ticks };
  }
  const minutes = (time) => {
    if (!time) return 12 * 60; // no time: the middle of the day
    const [hh, mm] = String(time).split(':').map(Number);
    return hh * 60 + mm;
  };
  // Where a mark goes: x by the day and the time of day inside its slot, y by value. `domain` is { min, max } (use niceTicks).
  function makeAxes({ start, end, width, height, padL = 44, padR = 12, padT = 14, padB = 26, domain }) {
    const days = R.daysBetween(start, end) + 1;
    const plotW = Math.max(40, width - padL - padR), plotH = Math.max(40, height - padT - padB);
    const slot = plotW / days;
    const span = domain.max - domain.min || 1;
    return {
      days, plotW, plotH, slot, padL, padR, padT, padB, width, height,
      x: (day, time) => padL + (R.daysBetween(start, day) + minutes(time) / 1440) * slot,
      y: (value) => padT + plotH - ((value - domain.min) / span) * plotH,
    };
  }
  // The labels under the x axis: a day number every so often, and the month under the first label of each month.
  function xLabels(start, end, slot) {
    const every = slot >= 22 ? 1 : slot >= 12 ? 2 : slot >= 8 ? 3 : 5;
    const days = R.daysBetween(start, end) + 1;
    const out = [];
    let month = null;
    for (let i = 0; i < days; i += 1) {
      if ((days - 1 - i) % every !== 0) continue;
      const day = R.shiftDay(start, i);
      const m = Number(day.slice(5, 7));
      out.push({ day, index: i, text: String(Number(day.slice(8, 10))), month: m !== month ? MONTHS[m - 1] : null });
      month = m;
    }
    return out;
  }
  const px = (v) => String(Math.round(v * 10) / 10);
  // "M x,y L x,y ..." through the points ({ x, y } in pixels), in the order given.
  function linePath(points) {
    return points.map((p, i) => `${i ? 'L' : 'M'}${px(p.x)},${px(p.y)}`).join(' ');
  }
  // The weight chart's marks: one per weight, in time order. `value` is in the person's unit (unrounded: a chart does not round).
  function weightSeries(weights, unit) {
    return weights.slice().sort(R.compareRows).map((w) => ({
      id: w.id, date: w.date, time: w.time, kg: w.kg, context: w.context, after: w.context === 'after_dialysis',
      value: unit === 'kg' ? w.kg : w.kg / R.KG_PER_LB,
    }));
  }
  function readingSeries(readings) {
    return readings.slice().sort(R.compareRows).map((r) => ({ id: r.id, date: r.date, time: r.time, systolic: r.systolic, diastolic: r.diastolic, context: r.context, flagged: !!r.flag }));
  }
  // The y range of a chart: every value and the lines drawn with them, as nice ticks.
  function domainOf(values, count = 4) {
    const v = values.filter((x) => Number.isFinite(x));
    return niceTicks(Math.min(...v), Math.max(...v), count);
  }

  // ---- where a row came from, in words: "" for a row the person typed. A phone shortcut's row names its token (`via`, the token's
  // name; null once the token is purged) so the person can see where it came from; the name is the person's own text and is only ever
  // drawn with textContent. (Design note 12 §4.4.)
  function originText(row) {
    const source = row ? row.source : null;
    if (source === 'shortcut') return row.via ? `from a shortcut (${row.via})` : 'from a shortcut';
    if (source === 'apple_health') return 'from the Health app';
    if (source === 'import') return 'from a file';
    return '';
  }

  // ---- the table under each chart
  function weightRows(weights, unit) {
    return weights.slice().sort(R.compareRows).map((w) => ({
      id: w.id, date: w.date, time: fmtTime(w.time), value: R.shownWeight(w.kg, unit).toFixed(1), unit, context: contextLabel('weight', w.context),
      origin: originText(w),
    }));
  }
  function readingRows(readings) {
    return readings.slice().sort(R.compareRows).map((r) => ({
      id: r.id, date: r.date, time: fmtTime(r.time), systolic: r.systolic, diastolic: r.diastolic, pulse: r.pulse == null ? '' : r.pulse,
      context: contextLabel('bp', r.context), flagged: !!r.flag, origin: originText(r),
    }));
  }

  // ---- Profile: the log's weight beside the Profile field. Profile weighs in kilograms; a person who uses pounds also sees them.
  // kind 'latest' (not on dialysis) / 'sixmonth'. `entry` is a weight row, `dateText` its date written out. → the sentence before "Use this".
  function profileWeightHint(kind, entry, dateText, unit) {
    const kg = R.shownWeight(entry.kg, 'kg').toFixed(1);
    const lb = unit === 'lb' ? ` (${R.shownWeight(entry.kg, 'lb').toFixed(1)} lb)` : '';
    return `${kind === 'latest' ? 'Latest in your log' : 'In your log'}: ${kg} kg${lb} on ${dateText}`;
  }

  KH.bodyUi = {
    WEIGHT_CONTEXT_LABELS, BP_CONTEXT_LABELS, MONTHS, BP_HINT, GOAL_LIMITS, ALARM_LIMITS, SIX_MONTH_LOOKBACK_DAYS, contextChoices, contextLabel, parseNumber, rangeText,
    weightFromInput, echoWeight, readingFromInput, echoReading, alarmFromInput, goalFromInput, inputNumber, fmtTime, amountText, gainText,
    alarmSentence, goalText, weekSentences, weekAverages, niceTicks, makeAxes, xLabels, linePath, weightSeries, readingSeries, domainOf,
    weightRows, readingRows, originText, profileWeightHint,
  };
})();
