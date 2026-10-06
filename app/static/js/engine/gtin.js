/* Kidney Diet Log — barcode numbers (GTINs): the browser twin of app/gtin.py (note 03 R2, F6).

   Pure functions, no DOM, no I/O. Used by js/scan.js for instant feedback on typed digits (the check
   digit, store barcodes for weighed food, books, magazines and coupons) before anything is sent, and by
   the demo API (js/mock/barcode.js) to answer POST /api/foods/barcode exactly as the server does. The
   server stays the authority: it normalises every code again.

   Parity: tests/data/barcode_vectors.json (tests/data/gen_barcode_vectors.py, from app/gtin.py) is
   replayed by `node tests/js/run_vectors.mjs`; messages are word for word the server's.

   Exposes KH.gtin = { PY_SPACE, FORMATS, GtinError, checkDigit, hasValidCheckDigit, expandUpce, normalize, isGtin8,
   classify, offCode, usdaCandidates, CLASS_MESSAGES }. */
(() => {
  'use strict';
  const root = typeof window !== 'undefined' ? window : globalThis;
  const KH = root.KH || (root.KH = {});

  // Formats a client may report (the BarcodeDetector names; "unknown" for typed digits).
  const FORMATS = ['ean_13', 'ean_8', 'upc_a', 'upc_e', 'unknown'];
  const ALLOWED_LENGTHS = [8, 12, 13, 14];
  // Typed codes are often grouped ("4 006381 333931", "0-49000-02891-1"): spaces and hyphens separate.
  // PY_SPACE is Python's \s for str (Unicode whitespace): JS's \s lacks U+001C–U+001F and U+0085 and adds
  // U+FEFF, so the class is spelled out (js/engine/textclean.js uses the same set).
  const PY_SPACE = '\\t\\n\\v\\f\\r \\u001c-\\u001f\\u0085\\u00a0\\u1680\\u2000-\\u200a\\u2028\\u2029\\u202f\\u205f\\u3000';
  const SEPARATORS = new RegExp(`[${PY_SPACE}-]+`, 'g');
  const DIGITS = /^[0-9]+$/;

  // app/barcode.py CLASS_MESSAGES: why a valid code is not looked up (400 detail, reason = the class).
  const CLASS_MESSAGES = {
    restricted: 'This is a store barcode for a weighed or in-store item (deli, meat, produce). It is only unique '
      + 'inside one shop, so it is not looked up. Enter the food from its label instead.',
    isbn: "This is a book's barcode (ISBN), not a food.",
    issn: "This is a magazine's barcode (ISSN), not a food.",
    coupon: 'This is a coupon or receipt barcode, not a food.',
    reserved: 'This barcode uses a number range that is not given to products.',
  };

  // A code that cannot be a GTIN. `reason` is "format" or "check_digit".
  class GtinError extends Error {
    constructor(reason, message) { super(message); this.name = 'GtinError'; this.reason = reason; }
  }

  // The GS1 mod-10 check digit for `body` (all digits except the check digit).
  function checkDigit(body) {
    if (!body || !DIGITS.test(body)) throw new Error('body must be a non-empty string of digits');
    let total = 0;
    for (let i = 0; i < body.length; i += 1) {
      const digit = body.charCodeAt(body.length - 1 - i) - 48;
      total += digit * (i % 2 === 0 ? 3 : 1);
    }
    return (10 - (total % 10)) % 10;
  }
  function hasValidCheckDigit(code) {
    return typeof code === 'string' && code.length >= 2 && DIGITS.test(code) && checkDigit(code.slice(0, -1)) === Number(code[code.length - 1]);
  }

  // An 8-digit UPC-E (number system, six digits, check digit) as its 12-digit UPC-A.
  function expandUpce(code) {
    if (typeof code !== 'string' || code.length !== 8 || !DIGITS.test(code)) throw new GtinError('format', 'A UPC-E code has 8 digits.');
    const system = code[0], d = code.slice(1, 7), check = code[7];
    if (system !== '0' && system !== '1') throw new GtinError('format', 'A UPC-E code starts with 0 or 1.');
    const last = d[5];
    let middle;
    if ('012'.includes(last)) middle = d.slice(0, 2) + last + '0000' + d.slice(2, 5);
    else if (last === '3') middle = d.slice(0, 3) + '00000' + d.slice(3, 5);
    else if (last === '4') middle = d.slice(0, 4) + '00000' + d[4];
    else middle = d.slice(0, 5) + '0000' + last;
    return system + middle + check;
  }

  // The GTIN-14 for `code`, or throws GtinError (same rules and messages as app/gtin.py normalize()).
  function normalize(code, fmt = null) {
    if (typeof code !== 'string') throw new GtinError('format', 'The barcode must be text made of digits.');
    let digits = code.replace(SEPARATORS, '');
    if (!digits || !DIGITS.test(digits)) throw new GtinError('format', 'A barcode is made of digits only.');
    if (!ALLOWED_LENGTHS.includes(digits.length)) throw new GtinError('format', 'A product barcode has 8, 12, 13 or 14 digits.');
    if (digits.length === 8 && fmt === 'upc_e') digits = expandUpce(digits);
    if (!hasValidCheckDigit(digits)) {
      throw new GtinError('check_digit', 'The last digit of this barcode does not match the others. Check the number and try again.');
    }
    return digits.padStart(14, '0');
  }

  function isGtin8(gtin14) { return gtin14.startsWith('000000'); }

  // "retail" for a product code that may be looked up; otherwise why not.
  function classify(gtin14) {
    if (typeof gtin14 !== 'string' || gtin14.length !== 14 || !DIGITS.test(gtin14)) throw new Error('classify() takes a GTIN-14');
    if (gtin14[0] === '9') return 'restricted'; // variable-measure trade item
    const gtin13 = gtin14.slice(1);
    if (gtin13.startsWith('00000')) { // the GTIN-8 range: judged by the GS1-8 prefix
      const prefix8 = Number(gtin13.slice(5, 8));
      if (prefix8 <= 99 || (prefix8 >= 200 && prefix8 <= 299)) return 'restricted';
      if (prefix8 >= 977) return 'reserved';
      return 'retail';
    }
    const prefix = Number(gtin13.slice(0, 3));
    if ((prefix >= 20 && prefix <= 29) || (prefix >= 40 && prefix <= 49) || (prefix >= 200 && prefix <= 299)) return 'restricted';
    if (prefix >= 50 && prefix <= 59) return 'coupon';
    if (prefix === 977) return 'issn';
    if (prefix === 978 || prefix === 979) return 'isbn';
    if (prefix >= 980) return 'coupon';
    return 'retail';
  }

  // The code Open Food Facts uses: 8 digits for a GTIN-8, 13 for EAN-13/UPC-A, 14 otherwise.
  function offCode(gtin14) {
    if (isGtin8(gtin14)) return gtin14.slice(6);
    return gtin14[0] === '0' ? gtin14.slice(1) : gtin14;
  }
  function usdaCandidates(gtin14) {
    const forms = [];
    if (gtin14.startsWith('00')) forms.push(gtin14.slice(2));
    if (gtin14.startsWith('0')) forms.push(gtin14.slice(1));
    forms.push(gtin14);
    return forms;
  }

  KH.gtin = { PY_SPACE, FORMATS, GtinError, CLASS_MESSAGES, checkDigit, hasValidCheckDigit, expandUpce, normalize, isGtin8, classify, offCode, usdaCandidates };
})();
