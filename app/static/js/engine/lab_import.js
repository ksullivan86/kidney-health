/* Kidney Diet Log — lab results from a CSV file (v0.3.1; docs/dev/plans/v0.3.1.md item 6).

   The file is read on this device: Lab results → "Import from a spreadsheet" parses it here and shows
   every result before anything is saved, and only the results the person keeps are sent
   (POST /api/labs/import, which converts and checks each one again with the rules of POST /api/labs).
   Columns that are not lab tests (a name, a record number, a doctor) never leave the page.

   The file: a header row, then one row per test date. One column holds the date ("Date", "Taken on",
   "Collected" ...); every column whose header names a test the app knows (app/units.py: "Potassium",
   "K", "Creatinine", "eGFR", "HbA1c" ...) is read, with the unit from the header ("Potassium
   (mmol/L)", "Creatinine [umol/L]") or chosen by the person; a test whose units all mean the same
   (potassium and bicarbonate: mmol/L = mEq/L; cystatin C, eGFR: one unit) needs none. Commas,
   semicolons or tabs separate the columns, quotes follow RFC 4180, empty cells are skipped.

   Nothing is guessed: a value such as "<0.5" or "1,200" (1200 or 1.2?) is listed as not imported with
   the reason, and dates written 03/04/2026 follow the order the person picks (detected when a day is
   above 12). Conversions and plausibility checks are those of js/engine/kidney_function.js, the
   parity-tested twin of app/units.py; tests/data/lab_import_vectors.json pins this file.

   Plain script: needs js/engine/rules.js and js/engine/kidney_function.js first; runs in the page
   (window.KH.labImport) and under Node (tests/js/run_vectors.mjs). No DOM. */
(function (root) {
  'use strict';
  const KH = root.KH || (root.KH = {});
  const K = KH.kidney;

  const MAX_CHARS = 1024 * 1024; // the file limit (1 MB); the page checks the file size before reading it
  const MAX_ROWS = 1000; // data rows
  const MAX_RESULTS = 1000; // results in one POST /api/labs/import

  // Header names per test (compared lowercased, spaces collapsed); each test's label and key count too.
  const ALIASES = {
    potassium: ['k', 'k+', 'serum potassium', 'potassium, serum', 'plasma potassium'],
    phosphate: ['phosphorus', 'phos', 'po4', 'serum phosphate', 'serum phosphorus', 'phosphorus, serum', 'inorganic phosphate'],
    albumin: ['albumin', 'serum albumin', 'albumin, serum', 'alb'],
    bicarbonate: ['bicarbonate', 'co2', 'total co2', 'tco2', 'hco3', 'carbon dioxide', 'serum bicarbonate'],
    uacr: ['acr', 'albumin/creatinine ratio', 'albumin-to-creatinine ratio', 'albumin creatinine ratio', 'urine acr',
      'urine albumin/creatinine ratio', 'microalbumin/creatinine ratio'],
    creatinine: ['creatinine', 'creat', 'serum creatinine', 'creatinine, serum', 'scr'],
    cystatin_c: ['cystatin', 'cys c', 'cysc', 'cystatin-c'],
    egfr: ['gfr', 'estimated gfr', 'egfr (ckd-epi)'],
    a1c: ['hba1c', 'hemoglobin a1c', 'haemoglobin a1c', 'glycated hemoglobin', 'glycated haemoglobin', 'glycohemoglobin'],
  };
  const DATE_HEADERS = ['date', 'taken on', 'taken_on', 'test date', 'date of test', 'collected', 'collection date', 'collected on',
    'result date', 'sample date', 'specimen date', 'drawn', 'date drawn'];

  const tidy = (s) => String(s == null ? '' : s).replace(/^\uFEFF/, '').trim().replace(/\s+/g, ' ');
  const norm = (s) => tidy(s).toLowerCase();

  const NAMES = new Map();
  for (const a of K.ANALYTE_KEYS) {
    for (const name of [a, K.ANALYTES[a].label, ...(ALIASES[a] || [])]) NAMES.set(norm(name), a);
  }

  // ---------------------------------------------------------------------------
  // CSV (RFC 4180 quotes; comma, semicolon or tab, whichever the header row uses most)
  // ---------------------------------------------------------------------------
  function detectDelimiter(text) {
    const counts = { ',': 0, ';': 0, '\t': 0 };
    let quoted = false;
    for (const c of text) {
      if (c === '"') quoted = !quoted;
      else if (!quoted && (c === '\n' || c === '\r')) break;
      else if (!quoted && c in counts) counts[c] += 1;
    }
    let best = ',';
    for (const d of [';', '\t']) if (counts[d] > counts[best]) best = d;
    return best;
  }

  // Records in file order (blank ones kept, so a record's number is its row in a spreadsheet).
  function parseCsv(text) {
    const s = String(text).replace(/^\uFEFF/, '');
    const delimiter = detectDelimiter(s);
    const records = [];
    let row = [];
    let field = '';
    let quoted = false;
    let i = 0;
    while (i < s.length) {
      const c = s[i];
      if (quoted) {
        if (c === '"') {
          if (s[i + 1] === '"') { field += '"'; i += 2; continue; }
          quoted = false;
        } else field += c;
        i += 1;
        continue;
      }
      if (c === '"' && field.trim() === '') { quoted = true; field = ''; i += 1; continue; }
      if (c === delimiter) { row.push(field); field = ''; i += 1; continue; }
      if (c === '\n' || c === '\r') {
        row.push(field);
        records.push(row);
        row = [];
        field = '';
        i += c === '\r' && s[i + 1] === '\n' ? 2 : 1;
        continue;
      }
      field += c;
      i += 1;
    }
    if (field !== '' || row.length) { row.push(field); records.push(row); }
    return { delimiter, records, unclosedQuote: quoted };
  }

  // ---------------------------------------------------------------------------
  // Headers
  // ---------------------------------------------------------------------------
  // A test column: {analyte, unit (as written, or null)}; null when the header names no test.
  function matchHeader(header) {
    const whole = norm(header);
    if (NAMES.has(whole)) return { analyte: NAMES.get(whole), unit: null };
    const m = /^(.*?)\s*[([]\s*([^)\]]*?)\s*[)\]]$/.exec(tidy(header));
    if (m && NAMES.has(norm(m[1]))) return { analyte: NAMES.get(norm(m[1])), unit: m[2] || null };
    return null;
  }
  function isDateHeader(header) { return DATE_HEADERS.includes(norm(header)); }

  // Every accepted unit of the analyte converts the same way (mmol/L = mEq/L), or there is only one.
  function oneMeaning(analyte) {
    const convs = Object.values(K.ANALYTES[analyte].units);
    return convs.every((c) => c.mul === convs[0].mul && c.div === convs[0].div && c.add === convs[0].add);
  }

  // ---------------------------------------------------------------------------
  // Cells
  // ---------------------------------------------------------------------------
  const quote = (text) => `“${text}”`;

  // {value} | {empty: true} | {problem}
  function parseValue(raw) {
    const text = String(raw == null ? '' : raw).trim();
    if (!text) return { empty: true };
    if (/^[<>≤≥]/.test(text)) return { problem: `${quote(text)} is not a single number (a result above or below what the lab measures)` };
    if (/^\+?\d+(\.\d+)?$/.test(text)) return { value: Number(text.replace('+', '')) };
    if (/^\d+,\d{1,2}$/.test(text)) return { value: Number(text.replace(',', '.')) }; // a decimal comma: "4,6"
    // Thousands separators: "1,200.5" and "1,234,567" can only be one number; "1,200" could be 1200 or 1.2.
    if (/^\d{1,3}(,\d{3})+\.\d+$/.test(text) || /^\d{1,3}(,\d{3}){2,}$/.test(text)) return { value: Number(text.replace(/,/g, '')) };
    if (/^\d{1,3},\d{3}$/.test(text)) {
      return { problem: `${quote(text)} could be ${text.replace(',', '')} or ${Number(text.replace(',', '.'))}: write it without the comma, or with a point for decimals` };
    }
    if (/^-\s*\d/.test(text)) return { problem: `${quote(text)} is below zero` };
    return { problem: `${quote(text)} is not a number` };
  }

  function isoOf(y, m, d) { return `${String(y).padStart(4, '0')}-${String(m).padStart(2, '0')}-${String(d).padStart(2, '0')}`; }

  // The parts of a date cell: {iso: [y, m, d]} or {slash: [a, b, y]} (order chosen later) or {problem}.
  function dateParts(raw) {
    const text = String(raw == null ? '' : raw).trim();
    if (!text) return { problem: 'no date' };
    let m = /^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})(?:[T ].*)?$/.exec(text);
    if (m) return { iso: [Number(m[1]), Number(m[2]), Number(m[3])] };
    m = /^(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})(?:[T ,].*)?$/.exec(text);
    if (m) return { slash: [Number(m[1]), Number(m[2]), Number(m[3])] };
    return { problem: `${quote(text)} is not a date the app can read: use YYYY-MM-DD, or day and month with a four-digit year` };
  }

  // YYYY-MM-DD, or {problem}: a real calendar date, not before 1900, not after tomorrow (time-zone slack,
  // as the server allows).
  function checkDate(y, m, d, today) {
    if (m < 1 || m > 12 || d < 1 || d > 31) return { problem: 'not a real date' };
    const iso = isoOf(y, m, d);
    if (K.parseIsoDate(iso).error) return { problem: 'not a real date' };
    if (y < 1900) return { problem: 'before 1900' };
    if (today && K.dayNumber(iso) > K.dayNumber(today) + 1) return { problem: 'in the future' };
    return { iso };
  }

  // ---------------------------------------------------------------------------
  // The whole file
  // ---------------------------------------------------------------------------
  /* analyse(text, {today, units: {column index: unit}, dateOrder: 'mdy' | 'dmy', existing: [{analyte, taken_on, value}]})
     → {
       problem,      // why nothing can be imported (no header, no date column, no test column, too big), or null
       delimiter, rows,
       dateColumn,   // index of the date column, or null
       slashDates,   // some dates are written like 03/04/2026 (the person picks the order)
       dateOrder,    // 'mdy' | 'dmy' | null: the order used
       dateOrderDetected, // true when a day above 12 settled it (dateOrder is then fixed)
       columns: [{index, header, analyte, label, unit, units, needsUnit, problem}],
       ignored: [header, ...],  // columns that are not read
       results: [{row, column, analyte, label, taken_on, text, value, unit, display, saved, problem}],
     }
     A result with a problem is listed but cannot be imported; `saved` marks one already in `existing`
     (the same test, date and shown value). */
  function analyse(text, opts = {}) {
    const today = opts.today || null;
    const chosenUnits = opts.units || {};
    const out = { problem: null, delimiter: ',', rows: 0, dateColumn: null, slashDates: false, dateOrder: null, dateOrderDetected: false,
      columns: [], ignored: [], results: [] };
    const s = String(text == null ? '' : text);
    if (s.length > MAX_CHARS) { out.problem = 'The file is larger than 1 MB. Split it into smaller files.'; return out; }
    const parsed = parseCsv(s);
    out.delimiter = parsed.delimiter;
    if (parsed.unclosedQuote) { out.problem = 'The file has a quoted value that never ends, so it cannot be read. Save it again as CSV.'; return out; }
    const records = parsed.records.map((cells, i) => ({ row: i + 1, cells })).filter((r) => r.cells.some((c) => c.trim() !== ''));
    if (!records.length) { out.problem = 'The file is empty.'; return out; }
    const [head, ...data] = records;
    out.rows = data.length;
    if (data.length > MAX_ROWS) { out.problem = `The file has ${data.length} rows; the app reads up to ${MAX_ROWS} at a time. Split it into smaller files.`; return out; }

    head.cells.forEach((header, index) => {
      if (out.dateColumn == null && isDateHeader(header)) { out.dateColumn = index; return; }
      const match = matchHeader(header);
      if (!match) { if (header.trim()) out.ignored.push(header.trim()); return; }
      const a = K.ANALYTES[match.analyte];
      const col = { index, header: header.trim(), analyte: a.key, label: a.label, unit: null, units: Object.keys(a.units), needsUnit: false, problem: null };
      const chosen = Object.prototype.hasOwnProperty.call(chosenUnits, index) ? chosenUnits[index] : null;
      try {
        if (chosen) col.unit = K.canonicalUnitName(a.key, chosen);
        else if (match.unit) col.unit = K.canonicalUnitName(a.key, match.unit);
        else if (oneMeaning(a.key)) col.unit = a.canonical_unit;
      } catch (e) {
        if (!(e instanceof K.UnitError)) throw e;
        col.problem = `The unit ${quote(chosen || match.unit)} is not one the app knows for ${a.label.toLowerCase()}. Choose the unit printed on your report.`;
      }
      if (!col.unit) col.needsUnit = true;
      out.columns.push(col);
    });
    if (out.dateColumn == null) { out.problem = 'No date column: name the column with the test dates "Date".'; return out; }
    if (!out.columns.length) { out.problem = 'No column names a lab test the app knows, for example "Potassium (mmol/L)" or "Creatinine (umol/L)".'; return out; }

    // Dates: the order of 03/04/2026 comes from a day above 12, else from the person's choice.
    const dates = data.map((r) => dateParts(r.cells[out.dateColumn]));
    const slash = dates.filter((d) => d.slash);
    out.slashDates = slash.length > 0;
    if (out.slashDates) {
      const dmy = slash.some((d) => d.slash[0] > 12);
      const mdy = slash.some((d) => d.slash[1] > 12);
      if (dmy && mdy) { out.problem = 'The dates mix day/month and month/day orders. Write them as YYYY-MM-DD.'; return out; }
      out.dateOrderDetected = dmy || mdy;
      out.dateOrder = dmy ? 'dmy' : mdy ? 'mdy' : (opts.dateOrder === 'dmy' ? 'dmy' : 'mdy');
    }

    const seen = new Map();
    const existing = new Set((opts.existing || []).map((r) => {
      try { return `${r.analyte}|${r.taken_on}|${K.formatValue(r.analyte, r.value)}`; } catch (e) { return ''; }
    }));
    data.forEach((r, i) => {
      const d = dates[i];
      let taken = null;
      let dateProblem = d.problem || null;
      if (!dateProblem) {
        const [y, m, day] = d.iso ? d.iso : out.dateOrder === 'dmy' ? [d.slash[2], d.slash[1], d.slash[0]] : [d.slash[2], d.slash[0], d.slash[1]];
        const checked = checkDate(y, m, day, today);
        if (checked.problem) dateProblem = `date ${quote(String(r.cells[out.dateColumn]).trim())}: ${checked.problem}`;
        else taken = checked.iso;
      } else if (d.problem === 'no date') dateProblem = 'no date in this row';
      for (const col of out.columns) {
        if (col.needsUnit) continue;
        const cell = r.cells[col.index];
        const v = parseValue(cell);
        if (v.empty) continue;
        const res = { row: r.row, column: col.index, analyte: col.analyte, label: col.label, taken_on: taken, text: String(cell).trim(),
          value: v.value === undefined ? null : v.value, unit: col.unit, display: null, saved: false, problem: null };
        if (dateProblem) res.problem = dateProblem;
        else if (v.problem) res.problem = v.problem;
        else {
          try {
            const c = K.convert(col.analyte, v.value, col.unit);
            res.display = c.display;
            const key = `${col.analyte}|${taken}|${K.formatValue(col.analyte, c.value)}`;
            if (seen.has(key)) res.problem = `the same result is in row ${seen.get(key)}`;
            else {
              seen.set(key, r.row);
              res.saved = existing.has(key);
            }
          } catch (e) {
            if (!(e instanceof K.UnitError)) throw e;
            res.problem = e.message;
          }
        }
        out.results.push(res);
      }
    });
    return out;
  }

  // The body of POST /api/labs/import for the results the person kept (the value and unit as written: the
  // server converts and checks again).
  function requestBody(results) {
    return { results: results.map((r) => ({ analyte: r.analyte, value: r.value, unit: r.unit, taken_on: r.taken_on })) };
  }

  KH.labImport = { MAX_CHARS, MAX_ROWS, MAX_RESULTS, ALIASES, DATE_HEADERS, parseCsv, detectDelimiter, matchHeader, parseValue, dateParts, analyse, requestBody };
})(typeof window !== 'undefined' ? window : globalThis);
