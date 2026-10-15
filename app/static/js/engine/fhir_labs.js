/* Kidney Diet Log — lab results from Apple Health clinical records (FHIR JSON files; docs/ROADMAP.md "Lab results from Apple Health
   clinical records", ARCHITECTURE.md "Lab results from Apple Health clinical records").

   A person who linked their health system in the iPhone Health app can choose "Export All Health Data": the zip holds
   apple_health_export/clinical-records/, one FHIR JSON resource per file. Lab results → "Import from Apple Health" reads the
   files the person picks HERE, on the device: nothing is uploaded. This module turns the file contents into the same kind of rows
   as the CSV import (js/engine/lab_import.js), the page shows them in the same review table, and only the rows the person keeps are
   sent, through POST /api/labs/import (KH.views.labs.saveImported). No file, no name, no patient or provider detail leaves the page.

   What is read (and nothing else is looked at, so a patient name or id in a file is never touched):
   * resourceType "Observation", or "Bundle" whose entries are Observations; every other record is counted as "not a lab result";
   * status final, amended or corrected;
   * code.coding[] with system http://loinc.org, mapped to the app's own tests (app/units.py) by the table below; any other code is
     skipped and counted;
   * valueQuantity.value (a single number: a comparator such as "<" is refused) with its unit (UCUM code or the unit text), converted
     and range-checked only by js/engine/kidney_function.js (the parity-tested twin of app/units.py): a unit the app does not know
     for that test is refused, never guessed;
   * the day from effectiveDateTime, else effectiveInstant, else effectivePeriod.start, else issued: a date alone is used as written;
     a time with a time zone is shown as the calendar day on this device; a month or a year alone, a future day (as the server:
     more than one day ahead) or a day before 1900 is refused;
   * the same test, day and shown value collapse to one row; rows the person already has are marked (the server skips them too).

   Limits against huge or hostile files: at most 2,000 files per pick and 1 MB each (checked before a file is read), JSON.parse in
   try/catch, a depth and node-count check, at most 5,000 entries per Bundle, 50,000 records per pick, 1,000 rows shown (the most
   recent; POST /api/labs/import takes 1 to 1,000) and 100 listed refusals; counts stay exact. Nothing is evaluated; only fixed
   paths of a record are read; all text is for textContent.

   LOINC codes. Each one is a code of the LOINC release 2.82 whose long common name was looked up on 2026-10-15 (tx.fhir.org
   CodeSystem/$lookup and the NLM Clinical Tables LOINC search); the code's own page is https://loinc.org/<code> (for example
   https://loinc.org/2823-3). LOINC® is a registered trademark of Regenstrief Institute, Inc.; the codes and names are used under the
   LOINC licence (https://loinc.org/license/). Only the specimens "Serum or Plasma" and LOINC's own "Serum, Plasma or Blood" are
   read; whole, venous and arterial blood (blood gas), urine and 24-hour specimens, the race-specific and MDRD eGFR codes and the
   paediatric formulas are not (the app cannot tell which of a race pair applies; it uses CKD-EPI 2021). A new code is added here
   only after the same lookup, and tests/test_fhir_labs.py checks that every analyte and unit exists in app/units.py.

   Plain script: needs js/engine/rules.js and js/engine/kidney_function.js first; runs in the page (window.KH.fhirLabs) and under Node
   (tests/js/run_vectors.mjs, tests/data/fhir_labs_vectors.json). No DOM. */
(function (root) {
  'use strict';
  const KH = root.KH || (root.KH = {});
  const K = KH.kidney;

  const MAX_FILES = 2000; // files in one pick
  const MAX_FILE_BYTES = 1024 * 1024; // 1 MB per file
  const MAX_DEPTH = 40; // nesting of a JSON file (a real Observation is under 15)
  const MAX_NODES = 300000; // values and containers in one file
  const MAX_BUNDLE_ENTRIES = 5000; // entries read from one Bundle
  const MAX_RECORDS = 50000; // records looked at in one pick
  const MAX_COLLECT = 5000; // distinct results held before the newest 1,000 are chosen
  const MAX_RESULTS = 1000; // rows shown and sent: POST /api/labs/import takes 1 to 1,000
  const MAX_PROBLEMS = 100; // refusals listed (the counts stay exact)
  const MAX_CODINGS = 50; // code.coding entries looked at per record
  const MAX_TEXT = 40; // characters of a file's own text (a unit, a name) repeated in a message

  const LOINC_SYSTEM = 'http://loinc.org';
  const UCUM_SYSTEM = 'http://unitsofmeasure.org';
  const OK_STATUS = new Set(['final', 'amended', 'corrected']);

  // ---------------------------------------------------------------------------
  // LOINC → the app's tests. [analyte, code, LOINC long common name, the UCUM unit LOINC gives as its example]
  // Citation for every row: https://loinc.org/<code> (LOINC 2.82).
  // ---------------------------------------------------------------------------
  const LOINC_LIST = [
    ['potassium', '2823-3', 'Potassium [Moles/volume] in Serum or Plasma', 'mmol/L'],
    ['potassium', '77142-8', 'Potassium [Moles/volume] in Serum, Plasma or Blood', 'mmol/L'],
    ['phosphate', '2777-1', 'Phosphate [Mass/volume] in Serum or Plasma', 'mg/dL'],
    ['phosphate', '14879-1', 'Phosphate [Moles/volume] in Serum or Plasma', 'mmol/L'],
    ['albumin', '1751-7', 'Albumin [Mass/volume] in Serum or Plasma', 'g/dL'],
    ['albumin', '61151-7', 'Albumin [Mass/volume] in Serum or Plasma by Bromocresol green (BCG) dye binding method', 'g/dL'],
    ['albumin', '61152-5', 'Albumin [Mass/volume] in Serum or Plasma by Bromocresol purple (BCP) dye binding method', 'g/dL'],
    ['albumin', '77148-5', 'Albumin [Mass/volume] in Serum, Plasma or Blood by Bromocresol purple (BCP) dye binding method', 'g/L'],
    ['bicarbonate', '1963-8', 'Bicarbonate [Moles/volume] in Serum or Plasma', 'mmol/L'],
    ['bicarbonate', '2028-9', 'Carbon dioxide, total [Moles/volume] in Serum or Plasma', 'mmol/L'],
    ['uacr', '9318-7', 'Albumin/Creatinine [Mass Ratio] in Urine', 'ug/mg{creat}'],
    ['uacr', '14959-1', 'Microalbumin/Creatinine [Mass Ratio] in Urine', 'mg/g{creat}'],
    ['uacr', '32294-1', 'Albumin/Creatinine [Ratio] in Urine', 'mg/mmol{creat}'],
    ['uacr', '30000-4', 'Microalbumin/Creatinine [Ratio] in Urine', 'mg/mmol{creat}'],
    ['creatinine', '2160-0', 'Creatinine [Mass/volume] in Serum or Plasma', 'mg/dL'],
    ['creatinine', '14682-9', 'Creatinine [Moles/volume] in Serum or Plasma', 'umol/L'],
    ['creatinine', '77140-2', 'Creatinine [Moles/volume] in Serum, Plasma or Blood', 'umol/L'],
    ['cystatin_c', '33863-2', 'Cystatin C [Mass/volume] in Serum or Plasma', 'mg/L'],
    ['egfr', '98979-8', 'Glomerular filtration rate [Volume Rate/Area] in Serum, Plasma or Blood by Creatinine-based formula (CKD-EPI 2021)/1.73 sq M', 'mL/min/{1.73_m2}'],
    ['egfr', '98980-6', 'Glomerular filtration rate [Volume Rate/Area] in Serum, Plasma or Blood by Creatinine and Cystatin C-based formula (CKD-EPI 2021)/1.73 sq M', 'mL/min/{1.73_m2}'],
    ['egfr', '62238-1', 'Glomerular filtration rate [Volume Rate/Area] in Serum, Plasma or Blood by Creatinine-based formula (CKD-EPI)/1.73 sq M', 'mL/min/{1.73_m2}'],
    ['egfr', '94677-2', 'Glomerular filtration rate [Volume Rate/Area] in Serum, Plasma or Blood by Creatinine and Cystatin C-based formula (CKD-EPI)/1.73 sq M', 'mL/min/{1.73_m2}'],
    ['egfr', '50210-4', 'Glomerular filtration rate [Volume Rate/Area] in Serum, Plasma or Blood by Cystatin C-based formula/1.73 sq M', 'mL/min/{1.73_m2}'],
    ['a1c', '4548-4', 'Hemoglobin A1c/Hemoglobin.total in Blood', '%'],
    ['a1c', '17856-6', 'Hemoglobin A1c/Hemoglobin.total in Blood by HPLC', '%'],
    ['a1c', '4549-2', 'Hemoglobin A1c/Hemoglobin.total in Blood by Electrophoresis', '%'],
  ];
  const BY_CODE = new Map(LOINC_LIST.map(([analyte, code, name, ucum]) => [code, { analyte, code, name, ucum }]));
  const loincUrl = (code) => `https://loinc.org/${code}`;

  // The order of the tests in the Labs view's picker (js/views/labs.js ANALYTE_ORDER); rows of one day are listed in it.
  const ORDER = ['potassium', 'phosphate', 'albumin', 'bicarbonate', 'creatinine', 'cystatin_c', 'egfr', 'uacr', 'a1c'];

  // ---------------------------------------------------------------------------
  // Units
  // ---------------------------------------------------------------------------
  // Spellings of an app unit that K.canonicalUnitName does not already accept. Each is the same unit written another way (a
  // microgram per milligram is a milligram per gram), never a conversion; the key is K.normaliseUnit(text).
  const UNIT_ALIASES = new Map([
    ['ug/mg', 'mg/g'],
    ['mg/gcreat', 'mg/g'],
    ['mg/gcreatinine', 'mg/g'],
    ['mg/mmolcreat', 'mg/mmol'],
    ['mg/mmolcreatinine', 'mg/mmol'],
    ['ml/min/1.73m*2', 'mL/min/1.73 m²'],
    ['ml/min/1.73m**2', 'mL/min/1.73 m²'],
    ['ml/min/1.73m^2', 'mL/min/1.73 m²'],
    ['ml/min/1.73sqm', 'mL/min/1.73 m²'],
  ]);

  // Printable, short text of something a file said, for a message (control and direction characters removed).
  function shown(value) {
    const text = String(value == null ? '' : value).replace(/[\u0000-\u001f\u007f-\u009f​-‏‪-‮⁦-⁩﻿]/g, ' ').replace(/\s+/g, ' ').trim();
    return text.length > MAX_TEXT ? `${text.slice(0, MAX_TEXT)}…` : text;
  }
  const quote = (text) => `“${shown(text)}”`;
  const num = (n) => String(n).replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  const plural = (n, singular, other) => `${num(n)} ${n === 1 ? singular : other}`;

  // The app's spelling of one unit text for one test, or null (UCUM annotations such as {creat} are dropped, and the body-surface
  // annotation {1.73_m2} becomes "1.73 m²").
  function mapUnit(analyte, raw) {
    if (typeof raw !== 'string') return null;
    let s = raw.trim();
    if (!s || s.length > MAX_TEXT) return null;
    s = s.replace(/\{1\.73[_ ]?m2\}/gi, '1.73 m²').replace(/\{[^}]*\}/g, '').trim();
    if (!s) return null;
    const target = UNIT_ALIASES.get(K.normaliseUnit(s)) || s;
    try {
      return K.canonicalUnitName(analyte, target);
    } catch (e) {
      if (!(e instanceof K.UnitError)) throw e;
      return null;
    }
  }

  // {unit} (the app's spelling) or {problem}: the UCUM code and the unit text are both tried; if they name two different units
  // the quantity is refused rather than guessed.
  function unitOf(analyte, q) {
    const tried = [];
    if (typeof q.code === 'string' && q.code.trim() && (q.system === undefined || q.system === UCUM_SYSTEM)) tried.push(q.code);
    if (typeof q.unit === 'string' && q.unit.trim()) tried.push(q.unit);
    const found = new Set();
    for (const t of tried) {
      const u = mapUnit(analyte, t);
      if (u) found.add(u);
    }
    if (found.size === 1) return { unit: [...found][0] };
    const label = K.ANALYTES[analyte].label;
    if (found.size > 1) return { problem: `the unit is written two ways (${tried.map(quote).join(' and ')}) that mean different units for ${label}` };
    if (!tried.length) return { problem: 'no unit is given' };
    return { problem: `the app cannot convert the unit ${quote(tried[tried.length - 1])} for ${label}` };
  }

  // ---------------------------------------------------------------------------
  // Dates
  // ---------------------------------------------------------------------------
  const DATE_RE = /^(\d{4})-(\d{2})-(\d{2})(?:[Tt](\d{2}):(\d{2})(?::(\d{2})(?:\.\d+)?)?([Zz]|[+-]\d{2}:?\d{2})?)?$/;

  // The day a result was taken: {iso: 'YYYY-MM-DD'} or {problem}. `tz` (minutes east of UTC) is for tests; the page leaves it out
  // and the device's own time zone at that moment is used.
  function readDate(raw, today, tz) {
    const text = typeof raw === 'string' ? raw.trim() : '';
    if (!text) return { problem: 'no date' };
    const m = DATE_RE.exec(text);
    if (!m) return { problem: /^\d{4}(-\d{2})?$/.test(text) ? `date ${quote(text)} has no day` : `date ${quote(text)} is not a date the app can read` };
    const [, y, mo, d, hh, mi, ss, zone] = m;
    let iso = `${y}-${mo}-${d}`;
    if (K.parseIsoDate(iso).error) return { problem: `date ${quote(text)} is not a real date` };
    if (Number(y) < 1900) return { problem: `date ${quote(text)} is before 1900` };
    if (hh !== undefined && zone) {
      if (Number(hh) > 23 || Number(mi) > 59 || Number(ss || 0) > 59) return { problem: `date ${quote(text)} is not a real time` };
      const sign = zone[0] === '-' ? -1 : 1;
      const offset = /^[Zz]$/.test(zone) ? 0 : sign * (Number(zone.slice(1, 3)) * 60 + Number(zone.slice(-2)));
      const ms = Date.UTC(Number(y), Number(mo) - 1, Number(d), Number(hh), Number(mi), Number(ss || 0)) - offset * 60000;
      const local = typeof tz === 'number' ? tz : -new Date(ms).getTimezoneOffset();
      iso = new Date(ms + local * 60000).toISOString().slice(0, 10);
      if (iso < '1900-01-01') return { problem: `date ${quote(text)} is before 1900` };
    }
    if (today && K.dayNumber(iso) > K.dayNumber(today) + 1) return { problem: `date ${quote(text)} is in the future` };
    return { iso };
  }

  // The first date field a record has (a field that is there but unusable is not skipped for the next one).
  function dateOf(obs, today, tz) {
    const period = obs.effectivePeriod && typeof obs.effectivePeriod === 'object' ? obs.effectivePeriod.start : undefined;
    for (const v of [obs.effectiveDateTime, obs.effectiveInstant, period, obs.issued]) {
      if (typeof v === 'string' && v.trim()) return readDate(v, today, tz);
    }
    return { problem: 'no date' };
  }

  // ---------------------------------------------------------------------------
  // Shapes
  // ---------------------------------------------------------------------------
  const isObject = (v) => v !== null && typeof v === 'object' && !Array.isArray(v);

  // Depth and size of a parsed file, walked without recursion.
  function withinLimits(doc) {
    const stack = [[doc, 1]];
    let nodes = 0;
    while (stack.length) {
      const [node, depth] = stack.pop();
      nodes += 1;
      if (nodes > MAX_NODES || depth > MAX_DEPTH) return false;
      if (node !== null && typeof node === 'object') {
        for (const child of Array.isArray(node) ? node : Object.values(node)) stack.push([child, depth + 1]);
        if (nodes + stack.length > MAX_NODES) return false; // every stacked value will be counted
      }
    }
    return true;
  }

  // The app's test for a record's code, or null (no LOINC code the table has, or two codes for different tests).
  function analyteOf(code) {
    if (!isObject(code) || !Array.isArray(code.coding)) return null;
    const found = new Set();
    const n = Math.min(code.coding.length, MAX_CODINGS);
    for (let i = 0; i < n; i++) {
      const c = code.coding[i];
      if (isObject(c) && c.system === LOINC_SYSTEM && typeof c.code === 'string') {
        const hit = BY_CODE.get(c.code.trim());
        if (hit) found.add(hit.analyte);
      }
    }
    return found.size === 1 ? [...found][0] : null;
  }

  // ---------------------------------------------------------------------------
  // A pick of files, one file at a time (the page reads each file, hands it over and lets go of its text)
  // ---------------------------------------------------------------------------
  const ZERO = () => ({
    files: 0, read: 0, notJson: 0, tooBig: 0, tooComplex: 0, unreadable: 0, // files
    notLab: 0, observations: 0, unknownCode: 0, wrongStatus: 0, // records
    noValue: 0, notExact: 0, badUnit: 0, badDate: 0, refused: 0, duplicates: 0, leftOut: 0, // tracked tests that were not kept
    found: 0, saved: 0, problemsHidden: 0,
  });

  const tooManyFiles = (n) => `You chose ${num(n)} files; the app reads up to ${num(MAX_FILES)} at a time. Choose fewer files, for example only the Observation files.`;

  /* start({today, existing: [{analyte, taken_on, value}], tzOffsetMinutes}) → {add(file), finish()}
     file: {name, size, text} (a file the page could not read: {name, unreadable: true}; one the page did not read because its size is
     over the limit: {name, size}). finish() → {
       problem,   // why nothing was read (too many files), or null
       counts,    // exact numbers (ZERO above)
       results,   // rows to review, newest day first: {analyte, label, taken_on, value, unit, text, display, saved}
       problems,  // tracked tests that were not kept, up to 100: {analyte, label, taken_on, text, problem, file}
       summary,   // the headline's parts, in words
     } */
  function start(opts = {}) {
    const today = opts.today || null;
    const tz = typeof opts.tzOffsetMinutes === 'number' ? opts.tzOffsetMinutes : null;
    const existing = new Set((opts.existing || []).map((r) => {
      try { return `${r.analyte}|${r.taken_on}|${K.formatValue(r.analyte, r.value)}`; } catch (e) { return ''; }
    }));
    const counts = ZERO();
    const seen = new Set();
    const rows = [];
    const problems = [];
    const seenProblems = new Set();
    let records = 0;
    let tooMany = 0;

    function refuse(analyte, taken_on, text, why, file) {
      const key = `${analyte}|${taken_on || ''}|${text}|${why}`;
      if (seenProblems.has(key)) return; // the same refusal twice is listed once (the counts above stay per record)
      seenProblems.add(key);
      if (problems.length >= MAX_PROBLEMS) { counts.problemsHidden += 1; return; }
      problems.push({ analyte, label: K.ANALYTES[analyte].label, taken_on: taken_on || null, text, problem: why, file });
    }

    function observation(obs, file) {
      if (records >= MAX_RECORDS) { counts.leftOut += 1; return; }
      records += 1;
      counts.observations += 1;
      const analyte = analyteOf(obs.code);
      if (!analyte) { counts.unknownCode += 1; return; }
      if (!OK_STATUS.has(obs.status)) { counts.wrongStatus += 1; return; }
      const label = K.ANALYTES[analyte].label;
      const when = dateOf(obs, today, tz);
      const taken = when.iso || null;
      const q = isObject(obs.valueQuantity) ? obs.valueQuantity : null;
      if (!q || typeof q.value !== 'number' || !Number.isFinite(q.value)) {
        counts.noValue += 1;
        refuse(analyte, taken, '', 'the result is not a single number (it may be text, or missing)', file);
        return;
      }
      const text = `${q.value} ${shown(typeof q.unit === 'string' ? q.unit : q.code)}`.trim();
      if (q.comparator !== undefined && q.comparator !== '=') {
        counts.notExact += 1;
        refuse(analyte, taken, text, `${quote(`${shown(q.comparator)}${q.value}`)} is not a single number (a result above or below what the lab measures)`, file);
        return;
      }
      const unit = unitOf(analyte, q);
      if (unit.problem) { counts.badUnit += 1; refuse(analyte, taken, text, unit.problem, file); return; }
      if (when.problem) { counts.badDate += 1; refuse(analyte, null, `${q.value} ${unit.unit}`, when.problem, file); return; }
      let c;
      try {
        c = K.convert(analyte, q.value, unit.unit);
      } catch (e) {
        if (!(e instanceof K.UnitError)) throw e;
        counts.refused += 1;
        refuse(analyte, taken, `${q.value} ${unit.unit}`, e.message, file);
        return;
      }
      const key = `${analyte}|${taken}|${K.formatValue(analyte, c.value)}`;
      if (seen.has(key)) { counts.duplicates += 1; return; }
      if (rows.length >= MAX_COLLECT) { counts.leftOut += 1; return; }
      seen.add(key);
      rows.push({ key, analyte, label, taken_on: taken, value: q.value, unit: unit.unit, text: `${q.value} ${unit.unit}`, display: c.display, saved: existing.has(key) });
    }

    function document_(doc, file) {
      if (!isObject(doc)) { counts.notLab += 1; return; }
      if (doc.resourceType === 'Observation') { observation(doc, file); return; }
      if (doc.resourceType === 'Bundle') {
        const entries = Array.isArray(doc.entry) ? doc.entry : [];
        const n = Math.min(entries.length, MAX_BUNDLE_ENTRIES);
        counts.leftOut += entries.length - n;
        for (let i = 0; i < n; i++) {
          const resource = isObject(entries[i]) ? entries[i].resource : null;
          if (isObject(resource) && resource.resourceType === 'Observation') observation(resource, file);
          else counts.notLab += 1;
        }
        return;
      }
      counts.notLab += 1;
    }

    function add(f) {
      counts.files += 1;
      if (counts.files > MAX_FILES) { tooMany += 1; return; }
      const file = shown(f && f.name);
      if (!f || f.unreadable) { counts.unreadable += 1; return; }
      const hasText = typeof f.text === 'string';
      const size = typeof f.size === 'number' ? f.size : hasText ? f.text.length : 0;
      if (size > MAX_FILE_BYTES || (hasText && f.text.length > MAX_FILE_BYTES)) { counts.tooBig += 1; return; }
      if (!hasText) { counts.unreadable += 1; return; }
      let doc;
      try {
        doc = JSON.parse(f.text.charCodeAt(0) === 0xFEFF ? f.text.slice(1) : f.text);
      } catch (e) {
        counts.notJson += 1;
        return;
      }
      if (!withinLimits(doc)) { counts.tooComplex += 1; return; }
      counts.read += 1;
      document_(doc, file);
    }

    function finish() {
      const out = { problem: null, counts, results: [], problems, summary: [] };
      if (tooMany) { out.problem = tooManyFiles(counts.files); return out; }
      if (!counts.files) { out.problem = 'No files were chosen.'; return out; }
      rows.sort((a, b) => (a.taken_on === b.taken_on ? ORDER.indexOf(a.analyte) - ORDER.indexOf(b.analyte) || a.value - b.value : a.taken_on < b.taken_on ? 1 : -1));
      const kept = rows.slice(0, MAX_RESULTS);
      counts.leftOut += rows.length - kept.length;
      out.results = kept.map(({ key, ...row }) => row);
      counts.found = out.results.length;
      counts.saved = out.results.filter((r) => r.saved).length;

      const s = out.summary;
      s.push(`${plural(counts.found, 'result', 'results')} found in ${plural(counts.files, 'file', 'files')}`);
      if (counts.saved) s.push(`${num(counts.saved)} already saved`);
      if (counts.notLab) s.push(counts.notLab === 1 ? '1 record that is not a lab result' : `${num(counts.notLab)} records that are not lab results`);
      if (counts.unknownCode) s.push(`${plural(counts.unknownCode, 'result', 'results')} of tests the app does not track`);
      if (counts.wrongStatus) s.push(`${num(counts.wrongStatus)} not final (preliminary, cancelled or entered in error)`);
      if (counts.badUnit) s.push(`${plural(counts.badUnit, 'result', 'results')} in a unit the app cannot convert`);
      if (counts.noValue + counts.notExact) s.push(`${num(counts.noValue + counts.notExact)} without a single number`);
      if (counts.badDate) s.push(`${num(counts.badDate)} without a usable day`);
      if (counts.refused) s.push(`${num(counts.refused)} outside the plausible range`);
      if (counts.duplicates) s.push(`${num(counts.duplicates)} repeated`);
      if (counts.notJson) s.push(`${plural(counts.notJson, 'file', 'files')} that ${counts.notJson === 1 ? 'is' : 'are'} not JSON`);
      if (counts.tooBig) s.push(`${plural(counts.tooBig, 'file', 'files')} over 1 MB`);
      if (counts.tooComplex) s.push(`${plural(counts.tooComplex, 'file', 'files')} too complex to read`);
      if (counts.unreadable) s.push(`${plural(counts.unreadable, 'file', 'files')} that could not be read`);
      if (counts.leftOut) s.push(`${num(counts.leftOut)} left out (the app takes the newest ${num(MAX_RESULTS)} at a time)`);
      return out;
    }

    return { add, finish, counts };
  }

  // All files at once (the vectors and small picks); the page uses start() so that it never holds every file's text.
  function analyse(files, opts = {}) {
    const run = start(opts);
    const list = Array.isArray(files) ? files : [];
    if (list.length > MAX_FILES) {
      run.counts.files = list.length;
      return { problem: tooManyFiles(list.length), counts: run.counts, results: [], problems: [], summary: [] };
    }
    for (const f of list) run.add(f);
    return run.finish();
  }

  KH.fhirLabs = {
    MAX_FILES, MAX_FILE_BYTES, MAX_DEPTH, MAX_NODES, MAX_BUNDLE_ENTRIES, MAX_RECORDS, MAX_COLLECT, MAX_RESULTS, MAX_PROBLEMS,
    LOINC: Object.fromEntries([...BY_CODE]), LOINC_LIST, loincUrl, ORDER, UNIT_ALIASES: Object.fromEntries([...UNIT_ALIASES]),
    mapUnit, unitOf, readDate, dateOf, analyteOf, withinLimits, tooManyFiles, start, analyse,
  };
})(typeof window !== 'undefined' ? window : globalThis);
