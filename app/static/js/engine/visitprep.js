/* Kidney Diet Log — Visit prep: what the one-page summary is made of (ARCHITECTURE.md "Visit prep").

   Pure functions, no DOM, no I/O; js/views/visit.js draws what they return. Nothing here does any arithmetic on the person's
   food log: the averages, targets, percentages, days over and counts come from `GET /api/log/summary` (app/periods.py
   summarize_period, the same numbers as Trends) and are only picked, ordered and worded. The labs are the rows of
   `GET /api/labs`; the symptoms are grouped by js/engine/symptoms.js (`KH.symptomRules.summarise`), as in Trends.

   * PERIODS: last 2 weeks, 4 weeks (the default) and 3 months, as days ending today.
   * averageRows(summary): sodium, potassium, phosphorus, protein and fluid (when a target is set), each with the server's
     average per logged day, target, percent of target, days over, level and the counts of days and foods that do not list
     the value. A value some foods do not list is never shown as a plain number or as 0: it is "at least" (≥) or, when
     nothing was listed at all, "Not listed" (the rule Trends and Today follow; ARCHITECTURE.md "Foods and log changes").
   * labRows(labs, order): the newest result of each test, the one before it and an arrow for how the newest compares
     (↑ higher, ↓ lower, → the same). The arrow says nothing about whether that is good or bad.
   * bodyPage(...): the weight and blood pressure section (note 10 §4.6) from the person's own weights and readings
     (GET /api/body/weights, /blood-pressure, /summary): the latest weight, the change over six months (KH.bodyRules.sixMonthChange),
     on hemodialysis the gains between the last sessions (sessionGains, up to 6, against the alarm when one is set), the 7-day and 30-day
     blood pressure averages (readingsWindow: the same rule as the server's week), how many readings were at or above the goal, and
     the readings the handbook points to (the server's `flag`). Plain arithmetic on the person's own rows; no interpretation.
   * The person's own questions: kept in the page's memory only (never stored, never sent). cleanQuestion / addQuestion.
   * CHECKLIST: the "What to do" list of handbook/docs/living/appointments.md, word for word (tests/test_visit_prep_ui.py
     checks each line against the page).

   Exposes KH.visitPrep = { PERIODS, DEFAULT_DAYS, NUTRIENT_ORDER, CHECKLIST, CHECKLIST_HREF, TREND_ARROW, TREND_WORDS,
   MAX_QUESTIONS, MAX_QUESTION_LENGTH, BODY_SESSION_ROWS, BODY_MONTH_DAYS, periodRange, averageText, averageRows, labRows, sessionGains,
   readingsWindow, bodyPage, cleanQuestion, addQuestion }. */
(() => {
  'use strict';
  const root = typeof window !== 'undefined' ? window : globalThis;
  const KH = root.KH || (root.KH = {});

  const PERIODS = [
    { days: 14, label: 'Last 2 weeks', short: '2 weeks' },
    { days: 28, label: 'Last 4 weeks', short: '4 weeks' },
    { days: 90, label: 'Last 3 months', short: '3 months' },
  ];
  const DEFAULT_DAYS = 28;
  // The order of the page: sodium, potassium, phosphorus, protein, then fluid when the person tracks it.
  const NUTRIENT_ORDER = ['sodium_mg', 'potassium_mg', 'phosphorus_mg', 'protein_g', 'fluid_ml'];

  // handbook/docs/living/appointments.md, "What to do" (word for word).
  const CHECKLIST = [
    'A week before: write your top three questions and update your medicine list.',
    "Two days before: export the app's period summary or CSV and download your CGM report.",
    'Bring your home blood pressure and weight readings.',
    'Bring a family member or friend if you can.',
    'At the end: teach-back the plan, and ask for changes in writing.',
    'Afterwards: update your medicine list, targets in the app, and your calendar for the next tests.',
  ];
  const CHECKLIST_HREF = '/learn/living/appointments/';

  const TREND_ARROW = { up: '↑', down: '↓', same: '→' };
  const TREND_WORDS = { up: 'higher than the previous result', down: 'lower than the previous result', same: 'the same as the previous result' };

  const MAX_QUESTIONS = 20;
  const MAX_QUESTION_LENGTH = 300;

  // ---- the period -----------------------------------------------------------------------------------------------------
  // `today` is a YYYY-MM-DD string; addDays is KH.util.addDays (injected so this file stays pure). → { start, end, days }.
  function periodRange(today, days, addDays) {
    return { start: addDays(today, -(days - 1)), end: today, days };
  }

  // ---- the averages (copied from the server's period summary) --------------------------------------------------------
  // How the average reads: "1,820", "≥ 1,820" (some foods do not list the value), "Not listed" (none did), "No entries".
  function averageText(nt, fmt) {
    const unknownDays = Number(nt.unknown_days || 0);
    if (nt.average == null) return 'No entries';
    if (unknownDays > 0 && Number(nt.average) === 0) return 'Not listed';
    return unknownDays > 0 ? `≥ ${fmt(nt.average)}` : fmt(nt.average);
  }

  // → { days, loggedDays, rows: [...], withoutTarget: [labels] }. `rules` is KH.rules (NUT, ASSESSMENT, fmtNum, pct).
  function averageRows(summary, rules) {
    const { NUT, ASSESSMENT, fmtNum, pct } = rules;
    const out = { days: summary.days, loggedDays: summary.logged_days, rows: [], withoutTarget: [] };
    for (const key of NUTRIENT_ORDER) {
      const nt = summary.nutrients && summary.nutrients[key];
      if (!nt) { if (key !== 'fluid_ml') out.withoutTarget.push(NUT[key].label); continue; }
      const unknownDays = Number(nt.unknown_days || 0);
      const unknownEntries = Number(nt.unknown_entries || 0);
      const fmt = (v) => fmtNum(v, key);
      const noneListed = nt.average != null && unknownDays > 0 && Number(nt.average) === 0;
      out.rows.push({
        key, label: NUT[key].label, unit: NUT[key].unit,
        text: averageText(nt, fmt),
        target: fmt(nt.target),
        role: nt.role,
        judged: nt.assessment || ASSESSMENT[key],
        percent: nt.average == null || noneListed ? null : pct(nt.fraction),
        atLeast: unknownDays > 0 && !noneListed && nt.average != null,
        daysOver: Number(nt.days_over || 0),
        // A total that misses values is never "OK" (as in Trends): the server's level, or "unknown" when it says ok.
        level: nt.level ? (unknownDays && nt.level === 'ok' ? 'unknown' : nt.level) : null,
        unknownDays, unknownEntries,
      });
    }
    return out;
  }

  // ---- the lab results -----------------------------------------------------------------------------------------------
  const newestFirst = (a, b) => (a.taken_on < b.taken_on ? 1 : a.taken_on > b.taken_on ? -1 : b.id - a.id);
  function arrow(latest, previous) {
    return latest > previous ? 'up' : latest < previous ? 'down' : 'same';
  }
  // `labs`: the rows of GET /api/labs; `order`: the tests in the order to list them (KH.labs.ANALYTE_ORDER). A test not in
  // `order` is left out. The values are the server's, rounded to the test's shown decimals, in one canonical unit.
  function labRows(labs, order) {
    const rows = [];
    for (const analyte of order) {
      const mine = labs.filter((r) => r.analyte === analyte).sort(newestFirst);
      if (!mine.length) continue;
      const latest = mine[0];
      const previous = mine[1] || null;
      rows.push({ analyte, label: latest.label, latest, previous, trend: previous ? arrow(Number(latest.value), Number(previous.value)) : null });
    }
    return rows;
  }

  // ---- weight and blood pressure (note 10 §4.6) -----------------------------------------------------------------------
  // Uses KH.bodyRules (js/engine/body.js, the twin of app/body.py) for the rules that exist on the server: the six-month change, the
  // order of rows, kilograms to 0.01. The 7-day window is the server's `blood_pressure_week` with another length for the 30-day one.
  const BODY_SESSION_ROWS = 6; // the last sessions listed
  const BODY_MONTH_DAYS = 30;

  // On hemodialysis: for each of the last `limit` weights before dialysis, the gain over the weight it is compared with, the way the
  // server's alarm check compares (app/body.py weight_alarm_check, "between_sessions"): the latest weight after dialysis before it
  // and dated in the 7 days before it; without one, the dry weight in Profile (`dryWeightKg`); without either, no gain.
  // `weights` oldest first (the API's order); `alarm` is { amount_kg, over, days } or null. Newest session first.
  function sessionGains(weights, alarm, dryWeightKg = null, limit = BODY_SESSION_ROWS) {
    const R = KH.bodyRules;
    const rows = [];
    weights.forEach((w, i) => {
      if (w.context !== 'before_dialysis') return;
      const floor = R.shiftDay(w.date, -7);
      const found = weights.slice(0, i).filter((x) => x.context === 'after_dialysis' && x.date >= floor);
      const ref = found.length ? found[found.length - 1] : null;
      const refKg = ref ? ref.kg : (dryWeightKg != null ? Number(dryWeightKg) : null);
      const gain = refKg == null ? null : R.roundKg(w.kg - refKg);
      rows.push({ weight: w, reference: ref, reference_kind: ref ? 'after_dialysis' : (refKg == null ? null : 'dry_weight'), reference_kg: refKg, gain_kg: gain,
        // only a between-sessions alarm is a limit for a gain between sessions
        over_alarm: gain != null && alarm && alarm.amount_kg != null && alarm.over === 'between_sessions' ? gain > alarm.amount_kg : null });
    });
    return rows.slice(-limit).reverse();
  }

  // The readings dated `day` and the `days - 1` days before it: how many, the mean top and bottom number (whole numbers, half up: the
  // server's rule), whether there are too few for a verdict (fewer than 3) and how many have a top number at or above the goal's top
  // number or a bottom number at or above its bottom number ("under 130/80": 130 is not under). `at_or_above` is null with no goal.
  function readingsWindow(readings, day, days, goal) {
    const R = KH.bodyRules;
    const from = R.shiftDay(day, -(days - 1));
    const inside = readings.filter((r) => r.date >= from && r.date <= day);
    const count = inside.length;
    const mean = (key) => (count ? KH.rules.halfUp(inside.reduce((a, r) => a + r[key], 0) / count, 0) : null);
    const hasGoal = !!goal && (goal.systolic != null || goal.diastolic != null);
    const atOrAbove = hasGoal
      ? inside.filter((r) => (goal.systolic != null && r.systolic >= goal.systolic) || (goal.diastolic != null && r.diastolic >= goal.diastolic)).length
      : null;
    return { days, from, to: day, count, systolic: mean('systolic'), diastolic: mean('diastolic'), few: count < 3, at_or_above: atOrAbove };
  }

  // The whole section. `weights` (oldest first, the last 366 days) and `readings` (oldest first, at least the last 30 days and the
  // chosen period) are the lists the API gave; `summary` is GET /api/body/summary?date=today. `periodDays` is the page's period.
  // `dialysis` is the profile's setting, `dryWeightKg` its weight. → { units, empty, latest, sixMonth, sessions, bp }.
  function bodyPage({ weights = [], readings = [], summary = null, today, periodDays, dialysis = 'none', dryWeightKg = null }) {
    const R = KH.bodyRules;
    const units = summary && summary.units ? summary.units : 'lb';
    const sw = summary && summary.weight;
    const goal = summary && summary.bp ? summary.bp.goal : { systolic: null, diastolic: null };
    const alarm = sw && sw.alarm && sw.alarm.amount_kg != null ? { amount_kg: sw.alarm.amount_kg, over: sw.alarm.over, days: sw.alarm.days } : null;
    const latest = sw && sw.latest ? sw.latest : (weights.length ? weights[weights.length - 1] : null);
    // the list up to and including the latest weight, the latest last, whatever the list holds after it
    const upTo = latest ? weights.filter((w) => w.date <= latest.date && w.id !== latest.id).concat([latest]) : [];
    const periodFrom = R.shiftDay(today, -(periodDays - 1));
    const flagged = readings.filter((r) => r.flag && r.date >= periodFrom && r.date <= today).slice().reverse();
    const hd = dialysis === 'hemodialysis';
    return {
      units,
      empty: !latest && !readings.length,
      latest,
      sixMonth: latest ? R.sixMonthChange(upTo) : null,
      sessions: hd ? { alarm, dryWeightKg: dryWeightKg == null ? null : Number(dryWeightKg), rows: sessionGains(weights, alarm, dryWeightKg) } : null,
      bp: {
        goal, periodDays, week: readingsWindow(readings, today, 7, goal), month: readingsWindow(readings, today, BODY_MONTH_DAYS, goal),
        flagged, flag: flagged.length ? flagged[0].flag : null,
      },
    };
  }

  // ---- the person's own questions ------------------------------------------------------------------------------------
  // One line of plain text: control characters and line breaks become spaces, runs of spaces one space, cut at the limit.
  function cleanQuestion(text) {
    return String(text == null ? '' : text).replace(/[\u0000-\u001f\u007f-\u009f\u2028\u2029]+/g, ' ').replace(/\s+/g, ' ').trim().slice(0, MAX_QUESTION_LENGTH).trim();
  }
  // → { list, error }: a new list with the question added at the end, or the same list and the reason it was not.
  function addQuestion(list, text) {
    const q = cleanQuestion(text);
    if (!q) return { list, error: 'Write a question first.' };
    if (list.length >= MAX_QUESTIONS) return { list, error: `A page holds ${MAX_QUESTIONS} questions. Remove one to add another.` };
    if (list.includes(q)) return { list, error: 'That question is already on the list.' };
    return { list: [...list, q], error: '' };
  }

  KH.visitPrep = { PERIODS, DEFAULT_DAYS, NUTRIENT_ORDER, CHECKLIST, CHECKLIST_HREF, TREND_ARROW, TREND_WORDS, MAX_QUESTIONS, MAX_QUESTION_LENGTH,
    BODY_SESSION_ROWS, BODY_MONTH_DAYS, periodRange, averageText, averageRows, labRows, sessionGains, readingsWindow, bodyPage, cleanQuestion, addQuestion };
})();
