/* Kidney Diet Log — clean outside text before it is stored, scanned or shown: the browser twin of
   app/textclean.py (note 03 §9 B3).

   NFKC; every Cf (zero-width, soft hyphen, bidi controls, BOM), Cc (control) and Cs (lone surrogate)
   character removed; CR, LF, the Unicode line and paragraph separators, VT, FF and NEL become a line
   break when line breaks are kept (ingredient lists), else a space; TAB a space; NFKC again; runs of
   spaces collapsed, lines trimmed, blank lines dropped; cut to max_len code points (Python counts code
   points, JavaScript strings count UTF-16 units, so the cut walks code points).

   Pure functions. Used by js/engine/additives.js (so a zero-width space inside "phos​phate" cannot hide
   it from the scan in the demo either). Parity: tests/data/barcode_vectors.json. Exposes
   KH.textclean = { cleanText, cleanLabel, casefold, pyStrip, cpSlice, cpLength, isPySpace }. */
(() => {
  'use strict';
  const root = typeof window !== 'undefined' ? window : globalThis;
  const KH = root.KH || (root.KH = {});

  const LINE_BREAKS = new Set(['\n', '\r', ' ', ' ', '\u000b', '\u000c', '\u0085']);
  const REMOVED = /^[\p{Cf}\p{Cc}\p{Cs}]$/u;
  // Python's \s for str (Unicode whitespace); JS's \s differs (no U+001C–U+001F or U+0085, adds U+FEFF).
  const PY_SPACE_CLASS = '\\t\\n\\v\\f\\r \\u001c-\\u001f\\u0085\\u00a0\\u1680\\u2000-\\u200a\\u2028\\u2029\\u202f\\u205f\\u3000';
  const PY_SPACE = new RegExp(`^[${PY_SPACE_CLASS}]$`);
  const HORIZONTAL_SPACE = new RegExp(`[${PY_SPACE_CLASS.replace('\\n', '')}]+`, 'g'); // [^\S\n]+
  const BLANK_LINES = /\n{2,}/g;

  function isPySpace(ch) { return PY_SPACE.test(ch); }
  // str.strip(chars): `chars` null = Python whitespace.
  function pyStrip(text, chars = null) {
    const drop = chars == null ? isPySpace : (ch) => chars.includes(ch);
    const cps = Array.from(text);
    let a = 0, b = cps.length;
    while (a < b && drop(cps[a])) a += 1;
    while (b > a && drop(cps[b - 1])) b -= 1;
    return cps.slice(a, b).join('');
  }
  function cpSlice(text, start, end) { return Array.from(text).slice(start, end).join(''); }
  function cpLength(text) { let n = 0; for (const _ of text) n += 1; return n; } // eslint-disable-line no-unused-vars

  // str.casefold() for the scripts the additive patterns read: toLowerCase() plus the full case folds
  // that differ from lower-casing (ß and ẞ → ss, final sigma, Greek symbol variants). NFKC has already
  // turned ligatures and compatibility letters into plain ones.
  const FOLD_EXTRA = { 'ß': 'ss', 'ẞ': 'ss', 'ς': 'σ', 'ϐ': 'β', 'ϑ': 'θ', 'ϕ': 'φ', 'ϖ': 'π', 'ϰ': 'κ', 'ϱ': 'ρ', 'ϵ': 'ε', 'ẛ': 'ṡ', 'ι': 'ι' };
  function casefold(text) {
    return text.toLowerCase().replace(/[ßẞςϐϑϕϖϰϱϵẛι]/g, (ch) => FOLD_EXTRA[ch] || ch);
  }

  function stripInvisible(text, keepNewlines) {
    let out = '';
    for (const ch of text) {
      if (LINE_BREAKS.has(ch)) out += keepNewlines ? '\n' : ' ';
      else if (ch === '\t') out += ' ';
      else if (REMOVED.test(ch)) continue;
      else out += ch;
    }
    return out;
  }

  // `value` as safe display text, or null when it is not a string or nothing is left.
  function cleanText(value, { maxLen, keepNewlines = false } = {}) {
    if (typeof value !== 'string') return null;
    if (!(maxLen >= 1)) throw new Error('max_len must be at least 1');
    let text = value.normalize('NFKC');
    text = stripInvisible(text, keepNewlines);
    text = text.normalize('NFKC');
    text = text.replace(HORIZONTAL_SPACE, ' ');
    if (keepNewlines) {
      text = text.split('\n').map((line) => pyStrip(line)).join('\n');
      text = pyStrip(text.replace(BLANK_LINES, '\n'), '\n');
    }
    text = pyStrip(cpSlice(pyStrip(text), 0, maxLen));
    return text || null;
  }
  function cleanLabel(value, { maxLen }) { return cleanText(value, { maxLen, keepNewlines: false }); }

  KH.textclean = { cleanText, cleanLabel, casefold, pyStrip, cpSlice, cpLength, isPySpace, PY_SPACE_CLASS };
})();
