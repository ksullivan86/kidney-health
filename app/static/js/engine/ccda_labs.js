/* Kidney Diet Log — lab results from a patient-portal C-CDA file (docs/ROADMAP.md "Lab results from a patient-portal C-CDA file",
   ARCHITECTURE.md "Lab results from a patient-portal C-CDA file").

   Patient portals (MyChart and others) let a person download a "health summary" or "visit summary" as a C-CDA XML file (HL7 Consolidated
   CDA, Release 2.1). Lab results → "Import from a patient portal file" reads the .xml files the person picks HERE, on the device: nothing
   is uploaded and no XML reaches the server (so the server needs no XML parser, and there is no XML parser on the server to attack). The
   page parses each file with the browser's DOMParser as application/xml (a browser never fetches an external entity or DTD for it); this
   module turns the parsed document into the same kind of rows as the CSV and Apple Health imports (js/engine/lab_import.js,
   js/engine/fhir_labs.js), the page shows them in the same review table, and only the rows the person keeps are sent, through
   POST /api/labs/import (KH.views.labs.saveImported). The LOINC table, the unit handling, the day rule and the counting, collapsing,
   "already saved" marking and 1,000-row cap are those of js/engine/fhir_labs.js (KH.fhirLabs), used, not copied.

   Refused before anything is parsed: a file over 5 MB, more than 20 files in one pick, and any file that contains "<!DOCTYPE" or
   "<!ENTITY" (a real C-CDA has no DTD; the file is refused and counted with that reason, never "cleaned"; the Trusted Types policy
   that hands the text to the parser refuses such a string too, so a missed check here still cannot reach it). A document the parser
   reports as malformed (a parsererror element) is refused too, and so is XML whose root is not a ClinicalDocument.

   What is read (and nothing else is looked at: no name, address, id, author, performer, narrative text or note, so none of it can leak):
   * sections whose templateId root is 2.16.840.1.113883.10.20.22.2.3.1 (Results Section, entries required) or
     2.16.840.1.113883.10.20.22.2.3 (Results Section, entries optional), found under ClinicalDocument/component/structuredBody/component/
     section (and sections nested in sections); every other section is ignored;
   * in such a section, entry/organizer/component/observation or entry/observation whose templateId root is 2.16.840.1.113883.10.20.22.4.2
     (Result Observation; the Result Organizer is 2.16.840.1.113883.10.20.22.4.1); an observation without that templateId is counted as
     "not a lab result";
   * code/@code with @codeSystem 2.16.840.1.113883.6.1 (LOINC), and the same on code/translation, mapped by the cited LOINC table in
     js/engine/fhir_labs.js; any other code is skipped and counted; a nullFlavor code is no code;
   * statusCode/@code "completed" (anything else is skipped and counted);
   * value of xsi:type PQ with @value (one number: "<5" or ">100" is refused, and so is IVL_PQ, a range or limit) and @unit (a UCUM code),
     converted and range-checked only through js/engine/kidney_function.js (the parity-tested twin of app/units.py): a unit the app does not
     know for that test, or no unit, is refused, never guessed; a value with a nullFlavor (the lab left it blank) is skipped and counted;
   * the day from effectiveTime/@value, else effectiveTime/low/@value, an HL7 TS value YYYYMMDD[HHMM[SS[.S]]][+/-ZZZZ], by the rule of the
     FHIR reader (fhirLabs.dayOf): a date alone is used as written; a time with a time zone is shown as the calendar day on this device; a
     month or a year alone, a future day (as the server: more than one day ahead) or a day before 1900 is refused.

   Source of the OIDs (checked 2026-10-15): HL7 C-CDA (https://hl7.org/cda/us/ccda/), templates ResultsSection (2.16.840.1.113883.10.20.22.2.3.1),
   ResultOrganizer (...4.1) and ResultObservation (...4.2); the HL7 CDA Examples IG example "results with lab location"
   (https://build.fhir.org/ig/HL7/CDA-Examples/Binary-results-with-lab-location.html) shows a Results section carrying both ...2.3 and
   ...2.3.1, the section code 30954-2 and LOINC's code system OID 2.16.840.1.113883.6.1. docs/targets-and-labs.md repeats the sources.

   Limits against huge or hostile files: at most 20 files per pick and 5 MB each (checked before a file is read), at most 200,000 elements
   walked and 64 levels deep per file (only the section, entry, organizer and observation elements are walked, never the narrative),
   50,000 observations per pick, 1,000 rows shown (the newest; POST /api/labs/import takes 1 to 1,000) and 100 listed refusals; counts
   stay exact. Nothing is evaluated; only fixed paths of a document are read; all text is for textContent.

   Plain script: needs js/engine/rules.js, js/engine/kidney_function.js and js/engine/fhir_labs.js first; runs in the page
   (window.KH.ccdaLabs, which parses with DOMParser) and under Node (tests/js/run_vectors.mjs, tests/data/ccda_labs_vectors.json, which
   pass tests/js/mini_xml.mjs as `parseXml`). */
(function (root) {
  'use strict';
  const KH = root.KH || (root.KH = {});
  const FL = KH.fhirLabs;

  const MAX_FILES = 20; // files in one pick
  const MAX_FILE_BYTES = 5 * 1024 * 1024; // 5 MB per file
  const MAX_ELEMENTS = 200000; // elements walked in one file
  const MAX_DEPTH = 64; // levels walked in one file (a real C-CDA's results are about a dozen deep)
  const MAX_SCAN = 200; // children of one observation looked at when it is read
  const MAX_TRANSLATIONS = 50; // code/translation entries looked at per observation

  const NS_HL7 = 'urn:hl7-org:v3';
  const NS_XSI = 'http://www.w3.org/2001/XMLSchema-instance';
  const LOINC_OID = '2.16.840.1.113883.6.1'; // the code system OID of LOINC
  const RESULTS_SECTION_OIDS = ['2.16.840.1.113883.10.20.22.2.3.1', '2.16.840.1.113883.10.20.22.2.3']; // entries required, entries optional
  const RESULT_ORGANIZER_OID = '2.16.840.1.113883.10.20.22.4.1'; // read through, not required
  const RESULT_OBSERVATION_OID = '2.16.840.1.113883.10.20.22.4.2';
  const RESULTS_SECTION_CODE = '30954-2'; // LOINC "Relevant diagnostic tests and/or laboratory data": the section's own code (not required)

  // A DTD or an entity declaration: refused before the file is parsed.
  const DTD_RE = /<!\s*(?:DOCTYPE|ENTITY)/i;
  // HL7 TS: YYYYMMDD, optionally HHMM[SS[.S+]], optionally a zone +/-ZZZZ.
  const TS_RE = /^(\d{4})(\d{2})(\d{2})(?:(\d{2})(\d{2})(?:(\d{2})(?:\.\d+)?)?)?([+-]\d{4})?$/;
  const NUMBER_RE = /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$/;
  const COMPARATOR_RE = /^[<>≤≥]/;

  // Where the walk goes: the structure down to the sections, and from a results section down to its observations.
  const SECTION_PATH = new Map([['ClinicalDocument', ['component']], ['component', ['structuredBody', 'section']], ['structuredBody', ['component']], ['section', ['component']]]);
  const ENTRY_PATH = new Map([['section', ['entry']], ['entry', ['organizer', 'observation']], ['organizer', ['component']], ['component', ['organizer', 'observation']]]);

  // ---------------------------------------------------------------------------
  // The small part of the DOM that is read (the same in a browser Document and in tests/js/mini_xml.mjs)
  // ---------------------------------------------------------------------------
  const isHl7 = (el) => el.namespaceURI === NS_HL7;

  // The HL7 child elements of `el` called `name`, looking at no more than MAX_SCAN children.
  function kids(el, name) {
    const out = [];
    const list = el.children;
    const n = Math.min(list.length, MAX_SCAN);
    for (let i = 0; i < n; i++) if (list[i].localName === name && isHl7(list[i])) out.push(list[i]);
    return out;
  }
  const kid = (el, name) => kids(el, name)[0] || null;

  // An attribute's text, or null.
  function attr(el, name) {
    const v = el.getAttribute(name);
    return typeof v === 'string' ? v : null;
  }

  function hasTemplate(el, oids) {
    for (const t of kids(el, 'templateId')) {
      const r = attr(t, 'root');
      if (r !== null && oids.includes(r.trim())) return true;
    }
    return false;
  }

  // The xsi:type of a value element without its prefix ("PQ"), or "".
  function xsiType(el) {
    let t = typeof el.getAttributeNS === 'function' ? el.getAttributeNS(NS_XSI, 'type') : null;
    if (!t) t = attr(el, 'xsi:type');
    return typeof t === 'string' ? t.trim().replace(/^.*:/, '') : '';
  }

  /* Trusted Types. The page's CSP has `require-trusted-types-for 'script'`, and the parse method of DOMParser is one of its sinks (for XML
     too): it takes a TrustedHTML, and a plain string throws. This module creates ONE named policy, kh-xml (named in the CSP's
     `trusted-types` list, app/security.py), whose createHTML() accepts only a string without a DOCTYPE or ENTITY and returns it
     unchanged; the result is handed straight to the parser below and goes nowhere else (the policy object stays in this closure). It is
     never a default policy and never allowed twice. Without Trusted Types (an older browser, Node) the string itself is used; if the
     policy cannot be created (a host page whose CSP does not list the name) the string is tried, and the parser's own TypeError, if any,
     makes the file "could not be read". */
  let xmlPolicy = null; // the policy, or false once it could not be created
  function trustedXml(text) {
    const tt = root.trustedTypes;
    if (!tt || typeof tt.createPolicy !== 'function' || xmlPolicy === false) return text;
    if (!xmlPolicy) {
      try {
        xmlPolicy = tt.createPolicy('kh-xml', {
          createHTML: (s) => {
            if (typeof s !== 'string' || DTD_RE.test(s)) throw new TypeError('blocked XML');
            return s;
          },
        });
      } catch (e) {
        xmlPolicy = false;
        return text;
      }
    }
    return xmlPolicy.createHTML(text);
  }

  // The browser's own parser, as an XML document; nothing is fetched for it (no DTD or external entity is ever loaded).
  function browserParse(text) {
    return new root.DOMParser().parseFromString(trustedXml(text), 'application/xml');
  }

  // A parser that could not read the document says so with a parsererror element: Chrome and Safari put one inside the document (the
  // root may be the document they made up), Firefox makes it the root.
  function parseFailed(doc) {
    if (!doc || !doc.documentElement) return true;
    if (doc.documentElement.localName === 'parsererror') return true;
    return typeof doc.getElementsByTagName === 'function' && doc.getElementsByTagName('parsererror').length > 0;
  }

  // ---------------------------------------------------------------------------
  // Codes, days
  // ---------------------------------------------------------------------------
  // The app's test for an observation's code (the code and its translations), or null (no LOINC code the table has, or two codes for
  // different tests).
  function analyteOf(code) {
    if (!code) return null;
    const found = new Set();
    const consider = (el) => {
      const system = attr(el, 'codeSystem');
      const c = attr(el, 'code');
      if (system === null || c === null || system.trim() !== LOINC_OID) return;
      const key = c.trim();
      if (Object.prototype.hasOwnProperty.call(FL.LOINC, key)) found.add(FL.LOINC[key].analyte);
    };
    consider(code);
    const translations = kids(code, 'translation');
    const n = Math.min(translations.length, MAX_TRANSLATIONS);
    for (let i = 0; i < n; i++) consider(translations[i]);
    return found.size === 1 ? [...found][0] : null;
  }

  // An HL7 TS value → {iso} or {problem}. `tz` (minutes east of UTC) is for tests; the page leaves it out.
  function readTs(raw, today, tz) {
    const text = typeof raw === 'string' ? raw.trim() : '';
    if (!text) return { problem: 'no date' };
    const m = TS_RE.exec(text);
    if (!m) return { problem: /^\d{4}(\d{2})?$/.test(text) ? `date ${FL.quote(text)} has no day` : `date ${FL.quote(text)} is not a date the app can read` };
    return FL.dayOf(text, m[1], m[2], m[3], m[4], m[5], m[6], m[7], today, tz);
  }

  // The day of an observation: effectiveTime/@value, else effectiveTime/low/@value.
  function dateOf(obs, today, tz) {
    const t = kid(obs, 'effectiveTime');
    if (!t) return { problem: 'no date' };
    let raw = attr(t, 'value');
    if (raw === null || !raw.trim()) {
      const low = kid(t, 'low');
      raw = low ? attr(low, 'value') : null;
    }
    return readTs(raw, today, tz);
  }

  // ---------------------------------------------------------------------------
  // A pick of files, one file at a time (the page reads each file, hands it over and lets go of its text)
  // ---------------------------------------------------------------------------
  const tooManyFiles = (n) => `You chose ${FL.num(n)} files; the app reads up to ${FL.num(MAX_FILES)} at a time. Choose fewer files, for example only your latest health summary.`;

  /* start({today, existing: [{analyte, taken_on, value}], tzOffsetMinutes, parseXml}) → {add(file), finish(), counts}
     parseXml(text) → a Document (default: the browser's DOMParser as application/xml; tests pass tests/js/mini_xml.mjs).
     file: {name, size, text} (a file the page could not read: {name, unreadable: true}; one the page did not read because its size is
     over the limit: {name, size}). finish() → {
       problem,   // why nothing was read (too many files), or null
       counts,    // exact numbers
       results,   // rows to review, newest day first: {analyte, label, taken_on, value, unit, text, display, saved}
       problems,  // tracked tests that were not kept, up to 100: {analyte, label, taken_on, text, problem, file}
       summary,   // the headline's parts, in words
     } */
  function start(opts = {}) {
    const parseXml = typeof opts.parseXml === 'function' ? opts.parseXml : browserParse;
    if (parseXml === browserParse && typeof root.DOMParser !== 'function') throw new Error('KH.ccdaLabs needs an XML parser: pass parseXml, or run in a browser');
    const col = FL.collector(opts, { tooBig: 0, unreadable: 0, doctype: 0, notXml: 0, notCcda: 0, tooComplex: 0, noResults: 0 });
    const { counts, problems, today, tz, refuse } = col;
    let tooMany = 0;

    // One Result Observation.
    function observation(obs, file) {
      if (!col.record()) return;
      const analyte = analyteOf(kid(obs, 'code'));
      if (!analyte) { counts.unknownCode += 1; return; }
      const status = kid(obs, 'statusCode');
      const code = status ? attr(status, 'code') : null;
      if (code === null || code.trim() !== 'completed') { counts.wrongStatus += 1; return; }
      const when = dateOf(obs, today, tz);
      const taken = when.iso || null;

      const values = kids(obs, 'value');
      if (values.length !== 1) {
        counts.noValue += 1;
        refuse(analyte, taken, '', 'the result is not a single number (it may be text, or missing)', file);
        return;
      }
      const v = values[0];
      const blank = attr(v, 'nullFlavor');
      if (blank !== null) {
        counts.noValue += 1;
        refuse(analyte, taken, '', `the lab left the value blank (nullFlavor ${FL.quote(blank)})`, file);
        return;
      }
      const type = xsiType(v);
      if (type === 'IVL_PQ') {
        counts.notExact += 1;
        refuse(analyte, taken, '', 'the result is a range or a limit, not a single number (a result above or below what the lab measures)', file);
        return;
      }
      const raw = type === 'PQ' ? attr(v, 'value') : null;
      if (raw === null) {
        counts.noValue += 1;
        refuse(analyte, taken, '', 'the result is not a single number (it may be text, or missing)', file);
        return;
      }
      const written = raw.trim();
      const unitText = attr(v, 'unit');
      const text = `${FL.shown(written)} ${FL.shown(unitText)}`.trim();
      if (COMPARATOR_RE.test(written)) {
        counts.notExact += 1;
        refuse(analyte, taken, text, `${FL.quote(written)} is not a single number (a result above or below what the lab measures)`, file);
        return;
      }
      if (!NUMBER_RE.test(written) || !Number.isFinite(Number(written))) {
        counts.noValue += 1;
        refuse(analyte, taken, text, 'the result is not a single number (it may be text, or missing)', file);
        return;
      }
      const number = Number(written);
      const unit = FL.unitOf(analyte, { code: unitText === null ? undefined : unitText });
      if (unit.problem) { counts.badUnit += 1; refuse(analyte, taken, text, unit.problem, file); return; }
      if (when.problem) { counts.badDate += 1; refuse(analyte, null, `${number} ${unit.unit}`, when.problem, file); return; }
      col.keep(analyte, taken, number, unit.unit, file);
    }

    // The sections of a document that are Results sections, or null when the document is too big to walk.
    function resultsSections(documentElement, budget) {
      const found = [];
      const stack = [[documentElement, 0]];
      while (stack.length) {
        const [el, depth] = stack.pop();
        budget.n += 1;
        if (budget.n > MAX_ELEMENTS || depth > MAX_DEPTH) return null;
        if (el.localName === 'section' && hasTemplate(el, RESULTS_SECTION_OIDS)) found.push(el);
        const next = SECTION_PATH.get(el.localName);
        if (!next) continue;
        const list = el.children;
        for (let i = list.length - 1; i >= 0; i--) if (isHl7(list[i]) && next.includes(list[i].localName)) stack.push([list[i], depth + 1]);
      }
      return found;
    }

    // The observations under a Results section's entries, appended to `out` as [element, isResultObservation]; false when the document is
    // too big to walk (then nothing from the file is recorded).
    function observationsOf(section, budget, out) {
      const stack = [[section, 0]];
      while (stack.length) {
        const [el, depth] = stack.pop();
        budget.n += 1;
        if (budget.n > MAX_ELEMENTS || depth > MAX_DEPTH) return false;
        if (el.localName === 'observation') {
          out.push([el, hasTemplate(el, [RESULT_OBSERVATION_OID])]);
          continue; // an observation's own children (comments, ranges) are never walked
        }
        const next = ENTRY_PATH.get(el.localName);
        if (!next) continue;
        const list = el.children;
        for (let i = list.length - 1; i >= 0; i--) if (isHl7(list[i]) && next.includes(list[i].localName)) stack.push([list[i], depth + 1]);
      }
      return true;
    }

    function add(f) {
      counts.files += 1;
      if (counts.files > MAX_FILES) { tooMany += 1; return; }
      const file = FL.shown(f && f.name);
      if (!f || f.unreadable) { counts.unreadable += 1; return; }
      const hasText = typeof f.text === 'string';
      const size = typeof f.size === 'number' ? f.size : hasText ? f.text.length : 0;
      if (size > MAX_FILE_BYTES || (hasText && f.text.length > MAX_FILE_BYTES)) { counts.tooBig += 1; return; }
      if (!hasText) { counts.unreadable += 1; return; }
      const text = f.text.charCodeAt(0) === 0xFEFF ? f.text.slice(1) : f.text;
      if (DTD_RE.test(text)) { counts.doctype += 1; return; } // before anything parses it
      let doc;
      try {
        doc = parseXml(text);
      } catch (e) {
        counts.unreadable += 1; // a parser reports a malformed document as a parsererror, so a throw means it was not allowed to parse
        return;
      }
      if (parseFailed(doc)) { counts.notXml += 1; return; }
      const top = doc.documentElement;
      if (top.localName !== 'ClinicalDocument' || !isHl7(top)) { counts.notCcda += 1; return; }
      const budget = { n: 0 };
      const sections = resultsSections(top, budget);
      if (sections === null) { counts.tooComplex += 1; return; }
      const found = [];
      for (const section of sections) {
        if (!observationsOf(section, budget, found)) { counts.tooComplex += 1; return; }
      }
      counts.read += 1;
      if (!sections.length) { counts.noResults += 1; return; }
      for (const [obs, isResult] of found) {
        if (isResult) observation(obs, file); else counts.notLab += 1;
      }
    }

    function finish() {
      const out = { problem: null, counts, results: [], problems, summary: [] };
      if (tooMany) { out.problem = tooManyFiles(counts.files); return out; }
      if (!counts.files) { out.problem = 'No files were chosen.'; return out; }
      out.results = col.results();
      const n = (count, thing) => FL.plural(count, thing, `${thing}s`);
      const fileParts = [];
      if (counts.doctype) fileParts.push(`${n(counts.doctype, 'file')} refused because ${counts.doctype === 1 ? 'it has' : 'they have'} a DOCTYPE or ENTITY declaration (a real health summary has none)`);
      if (counts.notXml) fileParts.push(`${n(counts.notXml, 'file')} that ${counts.notXml === 1 ? 'is' : 'are'} not valid XML`);
      if (counts.notCcda) fileParts.push(`${n(counts.notCcda, 'XML file')} that ${counts.notCcda === 1 ? 'is' : 'are'} not a C-CDA health summary`);
      if (counts.noResults) fileParts.push(`${FL.plural(counts.noResults, 'health summary', 'health summaries')} without a Results section`);
      if (counts.tooBig) fileParts.push(`${n(counts.tooBig, 'file')} over 5 MB`);
      if (counts.tooComplex) fileParts.push(`${n(counts.tooComplex, 'file')} too complex to read`);
      if (counts.unreadable) fileParts.push(`${n(counts.unreadable, 'file')} that could not be read`);
      out.summary = col.summarize({ wrongStatus: 'not completed (pending, cancelled or on hold)', fileParts });
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

  KH.ccdaLabs = {
    MAX_FILES, MAX_FILE_BYTES, MAX_ELEMENTS, MAX_DEPTH, NS_HL7, LOINC_OID, RESULTS_SECTION_OIDS, RESULT_ORGANIZER_OID, RESULT_OBSERVATION_OID,
    RESULTS_SECTION_CODE, readTs, dateOf, analyteOf, tooManyFiles, start, analyse,
  };
})(typeof window !== 'undefined' ? window : globalThis);
