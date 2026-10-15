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
   * The person's own questions: kept in the page's memory only (never stored, never sent). cleanQuestion / addQuestion.
   * CHECKLIST: the "What to do" list of handbook/docs/living/appointments.md, word for word (tests/test_visit_prep_ui.py
     checks each line against the page).

   Exposes KH.visitPrep = { PERIODS, DEFAULT_DAYS, NUTRIENT_ORDER, CHECKLIST, CHECKLIST_HREF, TREND_ARROW, TREND_WORDS,
   MAX_QUESTIONS, MAX_QUESTION_LENGTH, periodRange, averageText, averageRows, labRows, cleanQuestion, addQuestion }. */
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
    periodRange, averageText, averageRows, labRows, cleanQuestion, addQuestion };
})();
