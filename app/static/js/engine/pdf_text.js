/* Kidney Diet Log — the lines of a PDF page's own text (KH.pdfText; docs/dev/research/36-lab-pdf-text.md §4.1, §4.2, ARCHITECTURE.md
   "Lab report photos" → "Text from a PDF").

   Many lab PDFs are made from text, not scans. js/engine/pdf_pages.js hands this module the items pdf.js finds on a page
   (page.getTextContent(): {str, transform: [a, b, c, d, x, y], width, height}); this module rebuilds the lines a person would read,
   decides whether the page has real text, and leaves out lines that may say who the person is before js/views/lab_photo.js sends the
   lines to POST /api/ai/read-lab-report-text (local AI only). Pure functions: no DOM, no network, the same answer for the same items in
   any order. Tested in Node (tests/js/pdf_text.test.mjs); the server never parses a PDF, so there is no Python twin.

   API (window.KH.pdfText)
     buildLines(items)    → [string]: the page's lines, top to bottom, each left to right
       * items whose str is empty or only spaces are skipped; x = transform[4], y = transform[5] (PDF points, y grows upwards),
         h = height or |transform[3]| (at least 1), w = width (at least 0);
       * sorted by y (top first), then x, then the original index, so the content stream's own order never matters;
       * an item joins the current line when its y is within max(2, 0.5 × the smaller height) of the line's first item;
       * in a line, items go left to right (index on a tie) and are joined with one space when the gap from the end of one to the
         start of the next is more than max(0.5, 0.15 × h) points, directly otherwise;
       * spaces are collapsed, lines trimmed, empty lines dropped; at most LIMITS.MAX_LINES lines.
     hasText(lines)       → true when the lines hold at least LIMITS.MIN_CHARS letters and digits and at least LIMITS.MIN_NUMBER_LINES
                            lines with a digit (a scanned page has none or only a header)
     stripIdentity(lines) → {lines, removed}: the lines without those that may say who the person is (a patient, a name, a date of
                            birth, a record, account or member number, a social security number, an address, a phone or fax number,
                            insurance, a guarantor, an email address). A courtesy, not the guarantee: the guarantee is that the text goes
                            only to the local AI.
     pageText(items)      → {lines, removed, text, chars, hasText, tooLong}: all of the above for one page; `text` is the kept lines joined
                            with line breaks, `tooLong` when it is over LIMITS.MAX_CHARS (that page is then read as a picture)
     LIMITS

   Plain script (no module syntax), loaded by index.html before js/views/lab_photo.js; runs in the page and in Node. */
(function (root) {
  'use strict';
  const KH = root.KH || (root.KH = {});

  const LIMITS = Object.freeze({
    MAX_LINES: 400, // a page
    MAX_CHARS: 20000, // a page's kept text (the server's limit, app/ai/lab_report.py MAX_TEXT_CHARS)
    MIN_CHARS: 50, // letters and digits for a page to count as having text
    MIN_NUMBER_LINES: 2, // lines with a digit, likewise
  });

  const num = (v, fallback) => (typeof v === 'number' && Number.isFinite(v) ? v : fallback);

  function buildLines(items) {
    const kept = [];
    (Array.isArray(items) ? items : []).forEach((item, index) => {
      if (!item || typeof item.str !== 'string' || !item.str.trim()) return;
      const t = Array.isArray(item.transform) ? item.transform : [];
      const h = Math.max(1, Math.abs(num(item.height, 0)) || Math.abs(num(t[3], 0)));
      kept.push({ str: item.str, x: num(t[4], 0), y: num(t[5], 0), h, w: Math.max(0, num(item.width, 0)), index });
    });
    kept.sort((a, b) => (b.y - a.y) || (a.x - b.x) || (a.index - b.index));
    const rows = [];
    let current = null;
    for (const item of kept) {
      if (current && Math.abs(item.y - current.y) <= Math.max(2, 0.5 * Math.min(item.h, current.h))) {
        current.items.push(item);
      } else {
        current = { y: item.y, h: item.h, items: [item] };
        rows.push(current);
      }
    }
    const lines = [];
    for (const row of rows) {
      const parts = row.items.slice().sort((a, b) => (a.x - b.x) || (a.index - b.index));
      let text = '';
      let end = null;
      for (const part of parts) {
        if (end !== null && part.x - end > Math.max(0.5, 0.15 * part.h)) text += ' ';
        text += part.str;
        end = Math.max(end === null ? -Infinity : end, part.x + part.w);
      }
      const line = text.replace(/\s+/g, ' ').trim();
      if (line) lines.push(line);
      if (lines.length >= LIMITS.MAX_LINES) break;
    }
    return lines;
  }

  function hasText(lines) {
    const list = Array.isArray(lines) ? lines : [];
    let chars = 0;
    let numbered = 0;
    for (const line of list) {
      const s = String(line);
      chars += (s.match(/[\p{L}\p{N}]/gu) || []).length;
      if (/\d/.test(s)) numbered += 1;
    }
    return chars >= LIMITS.MIN_CHARS && numbered >= LIMITS.MIN_NUMBER_LINES;
  }

  // A label that says the line is about who the person is. Word boundaries, case ignored; "Name" also catches the "Test Name" header,
  // which costs nothing (it has no result).
  const IDENTITY = new RegExp([
    '\\bpatient\\b', '\\bpt\\s*(?:name|id)\\b', '\\bname\\b', '\\bd\\.?\\s*o\\.?\\s*b\\b', '\\bbirth', '\\bborn\\b', '\\bage\\s*/\\s*sex\\b',
    '\\bmrn\\b', '\\bmedical\\s+record', '\\brecord\\s*(?:no|number|#)', '\\baccount\\b', '\\bacct\\b', '\\bmember\\b', '\\bid\\s*(?:#|no\\b|number\\b)',
    '\\bssn\\b', '\\bsocial\\s+security', '\\baddress\\b', '\\bstreet\\b', '\\bzip\\b', '\\bphone\\b', '\\btel\\b', '\\bfax\\b', '\\bmobile\\b',
    '\\binsurance\\b', '\\bpolicy\\b', '\\bguarantor\\b', '\\bemail\\b', '\\be-mail\\b',
  ].join('|'), 'iu');
  const EMAIL = /[^\s@]+@[^\s@]+\.[^\s@]+/u;

  function stripIdentity(lines) {
    const out = [];
    let removed = 0;
    for (const line of Array.isArray(lines) ? lines : []) {
      if (IDENTITY.test(line) || EMAIL.test(line)) removed += 1;
      else out.push(line);
    }
    return { lines: out, removed };
  }

  function pageText(items) {
    const all = buildLines(items);
    const { lines, removed } = stripIdentity(all);
    const text = lines.join('\n');
    return { lines, removed, text, chars: text.length, hasText: hasText(all), tooLong: text.length > LIMITS.MAX_CHARS };
  }

  KH.pdfText = { buildLines, hasText, stripIdentity, pageText, LIMITS };
})(typeof window !== 'undefined' ? window : globalThis);
