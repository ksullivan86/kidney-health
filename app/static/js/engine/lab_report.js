/* Kidney Diet Log — the checks the app makes on lab results an AI copied (twin of app/ai/lab_report.py; design notes 36 and 38 §5.6).

   In device mode the iPhone app's own model reads the text of a lab report PDF page, and the page judges its answer with this file,
   as the server does with app/ai/lab_report.py. The model only copies lines ({analyte, value, unit, taken_on}); it never says whether
   a value is normal, high or low and it never decides what is saved. Each copied line:

   1. is dropped (not_in_text) when its number is not written in the page's text (judgeText), and loses its date when that date is
      not written there either;
   2. must name one of the app's own tests (unknown_analyte) and a unit the app knows for it (unknown_unit);
   3. must pass the checks of POST /api/labs: a non-negative number, inside the test's plausible range after conversion
      (out_of_range; KH.kidney.convert is the parity-tested twin of app/units.py);
   4. keeps its date only when the date can mean one day and is not in the future or before 1900; otherwise the person types it.

   The rows are proposed, never saved: saving is the person's tick and the ordinary POST /api/labs/import.
   `today` (YYYY-MM-DD) is the day "the future" starts after (one day of slack, as app/models.py validate_past_date); it defaults
   to this device's date. Plain script, no DOM; needs js/engine/kidney_function.js, textclean.js and aijudge.js first.
   tests/data/ai_device_vectors.json pins it. KH.labReport = { judge, judgeText, parsePrintedDate, cleanPrintedDate, numbersIn, ... } */
(() => {
  'use strict';
  const root = typeof window !== 'undefined' ? window : globalThis;
  const KH = root.KH || (root.KH = {});
  const T = KH.textclean;
  const J = KH.aiJudge;
  const K = KH.kidney;

  const MAX_PRINTED_DATE = 40;
  const DROPPED_KEYS = ['unknown_analyte', 'unknown_unit', 'out_of_range'];
  const NOTICE = 'Read by AI from your photo. Check each value against the report before you tick it.';
  const NOT_A_REPORT = 'This does not look like a lab report.';
  const UNREADABLE = 'The report could not be read; try a sharper photo with less glare, cropped to the results table.';
  const NO_RESULTS = 'No result the app knows was found in this photo.';
  const DATE_PROBLEMS = {
    missing: 'No date was read from the photo. Enter the date of the test.',
    ambiguous: 'The date on the report could mean two different days. Enter the date of the test.',
    unreadable: 'The date on the report could not be read. Enter the date of the test.',
    future: 'The date read from the photo is in the future. Enter the date of the test.',
    too_old: 'The date read from the photo is before 1900. Enter the date of the test.',
  };
  const MAX_TEXT_CHARS = 20000;
  const TEXT_NOTICE = 'Read by AI from the text of your PDF. Check each value against the report before you tick it.';
  const TEXT_UNREADABLE = 'The text of this page could not be read as a lab report. Try reading it as a picture.';
  const TEXT_NO_RESULTS = 'No result the app knows was found in this page\'s text.';
  const TEXT_DATE_PROBLEMS = Object.fromEntries(Object.entries(DATE_PROBLEMS).map(([k, v]) => [k, v.replace('from the photo', 'from the page\'s text')]));
  const NOT_IN_TEXT = 'left out because its number is not written in the page\'s text.';
  const MAX_NUTRIENT_VALUE = 1000000; // app/models.py: LabCreate.value le

  const MONTHS = {};
  [['jan', 'january'], ['feb', 'february'], ['mar', 'march'], ['apr', 'april'], ['may'], ['jun', 'june'], ['jul', 'july'],
    ['aug', 'august'], ['sep', 'sept', 'september'], ['oct', 'october'], ['nov', 'november'], ['dec', 'december']]
    .forEach((names, i) => { for (const n of names) MONTHS[n] = i + 1; });
  // app/ai/lab_report.py patterns, verbatim (tests/test_ai_device_vectors.py compares them).
  const SOURCES = {
    SEPARATORS: String.raw`[ /.,:\-]+`,
    DATE_TOKEN: String.raw`^(?:\d{1,4}|\d{1,2}(?:st|nd|rd|th)|t|am|pm)$`,
    YMD: String.raw`^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})(?:[T ,].*)?$`,
    NUMERIC: String.raw`^(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})(?:[T ,].*)?$`,
    DAY_NAME_YEAR: String.raw`^(\d{1,2})(?:st|nd|rd|th)?[ -]([A-Za-z]{3,9})\.?,?[ -](\d{4})(?:[T ,].*)?$`,
    NAME_DAY_YEAR: String.raw`^([A-Za-z]{3,9})\.? (\d{1,2})(?:st|nd|rd|th)?,? (\d{4})(?:[T ,].*)?$`,
    NUMBER: String.raw`(?<![\d.,])\d+(?:[.,]\d+)*(?!\d)`,
    SPACES: String.raw`\s+`,
  };
  const RX = Object.fromEntries(Object.entries(SOURCES).map(([k, v]) => [k, J.pyRe(v, ['SEPARATORS', 'NUMBER', 'SPACES'].includes(k) ? 'g' : '')]));
  const MAX_DATE_TOKENS = 8;
  const DIGITS = /^\p{Nd}+$/u; // str.isdigit() after NFKC
  const pyInt = (text) => Number(J.asciiDigits(text));

  // The date as printed, shown beside the date field; null unless it is made of numbers, month names and / . , : - only.
  function cleanPrintedDate(text) {
    const cleaned = text ? T.cleanText(text, { maxLen: MAX_PRINTED_DATE }) : null;
    if (!cleaned) return null;
    const tokens = cleaned.split(RX.SEPARATORS).filter(Boolean);
    if (!tokens.length || tokens.length > MAX_DATE_TOKENS || !tokens.some((t) => DIGITS.test(t))) return null;
    if (!tokens.every((t) => RX.DATE_TOKEN.test(t.toLowerCase()) || Object.prototype.hasOwnProperty.call(MONTHS, t.toLowerCase()))) return null;
    return cleaned;
  }
  const pad = (n, w) => String(n).padStart(w, '0');
  function calendar(year, month, day) {
    if (!(year >= 1 && year <= 9999 && month >= 1 && month <= 12 && day >= 1)) return [null, 'unreadable'];
    const last = new Date(Date.UTC(2000, month, 0)).getUTCDate(); // days in that month of a leap year
    const leap = (year % 4 === 0 && year % 100 !== 0) || year % 400 === 0;
    if (day > (month === 2 && !leap ? 28 : last)) return [null, 'unreadable'];
    return [`${pad(year, 4)}-${pad(month, 2)}-${pad(day, 2)}`, null];
  }
  // [YYYY-MM-DD, null] for a date that means one day, else [null, problem]: missing, ambiguous or unreadable.
  function parsePrintedDate(text) {
    const printed = cleanPrintedDate(text);
    if (!printed) return [null, !T.pyStrip(text || '') ? 'missing' : 'unreadable'];
    let m = RX.YMD.exec(printed);
    if (m) return calendar(pyInt(m[1]), pyInt(m[2]), pyInt(m[3]));
    m = RX.NUMERIC.exec(printed);
    if (m) {
      const [first, second, year] = [pyInt(m[1]), pyInt(m[2]), pyInt(m[3])];
      if (first > 12 && second <= 12) return calendar(year, second, first);
      if (second > 12 && first <= 12) return calendar(year, first, second);
      if (first === second) return calendar(year, first, second);
      if (first <= 12 && second <= 12) return [null, 'ambiguous'];
      return [null, 'unreadable'];
    }
    m = RX.DAY_NAME_YEAR.exec(printed);
    if (m && Object.prototype.hasOwnProperty.call(MONTHS, m[2].toLowerCase())) return calendar(pyInt(m[3]), MONTHS[m[2].toLowerCase()], pyInt(m[1]));
    m = RX.NAME_DAY_YEAR.exec(printed);
    if (m && Object.prototype.hasOwnProperty.call(MONTHS, m[1].toLowerCase())) return calendar(pyInt(m[3]), MONTHS[m[1].toLowerCase()], pyInt(m[2]));
    return [null, 'unreadable'];
  }
  function localToday() {
    const d = new Date();
    return `${pad(d.getFullYear(), 4)}-${pad(d.getMonth() + 1, 2)}-${pad(d.getDate(), 2)}`;
  }
  function addDay(iso) {
    const d = new Date(`${iso}T00:00:00Z`);
    d.setUTCDate(d.getUTCDate() + 1);
    return d.toISOString().slice(0, 10);
  }
  // The date if it passes the check POST /api/labs makes (not in the future, 1900 or later).
  function checkDate(iso, today) {
    if (iso === null) return [null, null];
    if (iso > addDay(today)) return [null, 'future'];
    if (Number(iso.slice(0, 4)) < 1900) return [null, 'too_old'];
    return [iso, null];
  }
  function plural(n, one, many) { return `${n} ${n === 1 ? one : many}`; }
  function droppedNotes(dropped) {
    const out = [];
    let n = dropped.unknown_analyte || 0;
    if (n) out.push(`${plural(n, 'line was', 'lines were')} not recognised: it is not one of the tests this app keeps.`);
    n = dropped.unknown_unit || 0;
    if (n) out.push(`${plural(n, 'line was', 'lines were')} left out because its unit is not one the app knows for that test.`);
    n = dropped.out_of_range || 0;
    if (n) {
      out.push(`${plural(n, 'line was', 'lines were')} left out because the number is outside the range the app accepts `
        + '(check the number and the unit on the report).');
    }
    return out;
  }
  const isKey = (o, k) => Object.prototype.hasOwnProperty.call(o, k);

  // The model's copied lines as proposed rows (nothing is saved). `answer`: {status, rows: [{analyte, value, unit, taken_on}]}.
  function judge(answer, { dateNotes = DATE_PROBLEMS, today = localToday() } = {}) {
    const dropped = Object.fromEntries(DROPPED_KEYS.map((k) => [k, 0]));
    if (answer.status === 'not_a_lab_report') return { status: 'not_a_lab_report', message: NOT_A_REPORT, rows: [], dropped, dropped_notes: [] };
    if (answer.status === 'unreadable') return { status: 'unreadable', message: UNREADABLE, rows: [], dropped, dropped_notes: [] };
    const rows = [];
    const seen = new Set();
    for (const line of answer.rows) {
      const analyte = T.pyStrip(line.analyte).toLowerCase();
      if (!isKey(K.ANALYTES, analyte)) { dropped.unknown_analyte += 1; continue; }
      let unit;
      try { unit = K.canonicalUnitName(analyte, line.unit); } catch (e) {
        if (!(e instanceof K.UnitError)) throw e;
        dropped.unknown_unit += 1;
        continue;
      }
      let [iso, problem] = parsePrintedDate(line.taken_on);
      let late;
      [iso, late] = checkDate(iso, today);
      problem = late || problem;
      const value = Number(line.value);
      let converted;
      try {
        if (!(Number.isFinite(value) && value >= 0 && value <= MAX_NUTRIENT_VALUE)) throw new K.UnitError('value');
        converted = K.convert(analyte, value, unit);
      } catch (e) {
        if (!(e instanceof K.UnitError)) throw e;
        dropped.out_of_range += 1;
        continue;
      }
      const key = JSON.stringify([analyte, value, unit, iso]);
      if (seen.has(key)) continue; // the same line read twice
      seen.add(key);
      rows.push({
        analyte, label: K.analyteDef(analyte).label, value, unit, display: converted.display, taken_on: iso,
        printed_date: cleanPrintedDate(line.taken_on), date_problem: problem, date_note: problem ? (dateNotes[problem] ?? null) : null,
      });
    }
    const notes = droppedNotes(dropped);
    if (!rows.length) return { status: 'no_results', message: NO_RESULTS, rows: [], dropped, dropped_notes: notes };
    return { status: 'ok', rows, dropped, dropped_notes: notes, notice: NOTICE };
  }

  // Every number written in `text`, read each way it can be read (1,250 is 1250 and 1.25; 1,2 is 1.2 and 12).
  function numbersIn(text) {
    const out = new Set();
    for (const m of String(text).matchAll(RX.NUMBER)) {
      const token = m[0];
      const readings = [token.replace(/,/g, '')];
      if ((token.match(/,/g) || []).length === 1 && !token.includes('.')) readings.push(token.replace(/,/g, '.'));
      for (const reading of readings) if ((reading.match(/\./g) || []).length <= 1) out.add(J.pyFloat(reading));
    }
    return out;
  }
  const foldText = (text) => T.casefold(T.pyStrip(String(text).replace(RX.SPACES, ' ')));

  // The lines the model copied from the text of a PDF page, checked against that text first (design note 36 §4.3).
  function judgeText(answer, text, { today = localToday() } = {}) {
    const written = [...numbersIn(text)];
    const folded = foldText(text);
    const kept = [];
    let notInText = 0;
    for (let line of answer.rows) {
      const value = Number(line.value);
      if (!written.some((n) => Math.abs(value - n) <= 1e-9 * Math.max(1.0, Math.abs(n)))) { notInText += 1; continue; }
      if (line.taken_on !== null && line.taken_on !== undefined && !folded.includes(foldText(line.taken_on))) line = { ...line, taken_on: null };
      kept.push(line);
    }
    const verdict = judge({ ...answer, rows: kept }, { dateNotes: TEXT_DATE_PROBLEMS, today });
    verdict.dropped = { ...verdict.dropped, not_in_text: notInText };
    if (notInText) verdict.dropped_notes = [...verdict.dropped_notes, `${plural(notInText, 'line was', 'lines were')} ${NOT_IN_TEXT}`];
    if (verdict.status === 'unreadable') verdict.message = TEXT_UNREADABLE;
    else if (verdict.status === 'no_results') verdict.message = TEXT_NO_RESULTS;
    else if (verdict.status === 'ok') verdict.notice = TEXT_NOTICE;
    return verdict;
  }

  KH.labReport = {
    SOURCES, DROPPED_KEYS, NOTICE, TEXT_NOTICE, DATE_PROBLEMS, TEXT_DATE_PROBLEMS, MAX_TEXT_CHARS,
    cleanPrintedDate, parsePrintedDate, checkDate, droppedNotes, judge, numbersIn, judgeText,
  };
})();
