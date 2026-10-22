/* Kidney Diet Log — weights and blood pressure readings from the iPhone Health app's export.xml (docs/dev/research/10-weight-and-blood-pressure.md
   section 4.8, Part C). The person exports from the Health app, unzips the file in the Files app and picks apple_health_export/export.xml.
   This module reads it HERE, on the device, as a stream of text; the import sheet that shows the rows and posts the ones the person keeps
   (to POST /api/body/weights/batch and /api/body/blood-pressure/batch) is a separate file. Nothing is uploaded by this module.

   Why not an XML parser. The file can be hundreds of megabytes (a parser would hold all of it), and it starts with an internal DTD
   (<!DOCTYPE HealthData [ ... ]>), the shape entity-expansion attacks use. So the text is scanned, never parsed: the DTD, the <?xml ?>
   line and every element that is not a <Record start tag are just text that is looked past, and nothing is ever expanded. A <Record
   inside the DTD, a comment or a CDATA block would be read like any other (the person picked the file and sees every row before
   anything is saved).

   What is read
   * <Record followed by a space, tab or line break is a start tag; the tag ends at the first ">" that is not inside a quoted value, and
     has no "<" inside it (a "<" ends a tag early: that tag is counted as unreadable and scanning goes on at the "<"). Self-closing or not,
     inside a <Correlation> or loose: only the start tag is looked at, children (<MetadataEntry>) are text.
   * A tag longer than 8,192 characters (MAX_TAG) is skipped and counted (tagTooLong); its text is thrown away as it streams past.
   * The text a record is cut from is never held beyond one tag: the carry-over buffer between two chunks is the unfinished start of one
     tag (under 8,192 characters) or the last few characters that may begin "<Record ". Whatever the input, it never grows past that.
     (What the scan keeps grows only with the weights and readings it finds, a few hundred bytes each; text cut from a chunk is copied
     first, so a row never keeps a whole chunk alive.)
   * A tag that does not hold the text "HKQuantityTypeIdentifierB" is dropped without being looked at (heart rate, steps, glucose, insulin,
     everything else: CLAUDE.md, no dosing data). Other tags are read by one linear pass over name="value" / name='value' pairs, in any
     order, single or double quotes; only type, unit, value, startDate and sourceName are kept, the first of a repeated name wins.
   * type is compared as written, to exactly one of these three (BodyMassIndex, LeanBodyMass and the like are not them):
       HKQuantityTypeIdentifierBodyMass                 unit kg or lb  -> a weight
       HKQuantityTypeIdentifierBloodPressureSystolic    unit mmHg      together, paired by identical startDate and
       HKQuantityTypeIdentifierBloodPressureDiastolic   unit mmHg      sourceName -> a reading
   * value, startDate and sourceName are decoded: &amp; &lt; &gt; &quot; &apos; and numeric references (&#NN; &#xHH;) to an XML character
     only. Any other "&" (a name such as &nbsp; or a DTD entity, a bare "&", a reference to a control character or a lone surrogate) makes
     the record unusable: skipped and counted (badEntity). Decoding is one pass: "&amp;lt;" becomes "&lt;", never "<". An entity in an
     attribute that is not read (device, creationDate) is never looked at.

   What a row is
   * date, time: from startDate "YYYY-MM-DD HH:MM:SS +HHMM" AS WRITTEN: the wall clock of the person when it was measured, not converted to
     UTC; date "YYYY-MM-DD", time "HH:MM". A startDate in any other form, a day that is not on the calendar, before 1900, or (when the
     caller passes opts.today) more than one day after today (the server's time-zone slack) is unreadable.
   * weight: kg = value, or value x 0.45359237 for lb (1 lb, exactly: note 10 F7), rounded half up to 0.01 with KH.rules.halfUp (the
     project's round-half-up on the decimal digits, the server's rule: 70.005 is 70.01). Context "morning" when the time is 04:00-10:59,
     else "other". Kept when 20 <= kg <= 400 (the note's section 4.1 plausibility range, the project's own choice, not a clinical number).
   * blood pressure reading: a systolic and a diastolic record with identical startDate and sourceName; integer mmHg (a value with a
     fraction is rounded half up). Context "morning" 04:00-10:59, "evening" 17:00-23:59, else "other". Kept when 50 <= systolic <= 300,
     20 <= diastolic <= 200 and systolic > diastolic; pulse is not imported. A systolic or diastolic with no partner is a lone half; if a
     startDate and sourceName holds two different systolic values or two different diastolic values the pairing would be a guess, so
     every half of that group is skipped. Both count as halfPair.
   * The same record twice (type, startDate, value and sourceName all equal: inside a <Correlation> and again loose) is one: the second is
     counted as duplicate.
   * source_key, the de-duplication key (importing the same export twice adds nothing): the first 32 hex characters of the SHA-256 of the
     UTF-8 text
       weight:           HKQuantityTypeIdentifierBodyMass|<startDate>|<value>|<sourceName>
       blood pressure:   BloodPressure|<startDate>|<systolic>/<diastolic>|<sourceName>
     where startDate and each value are the attributes as written (so "154.3" for pounds, not the kilograms), sourceName is decoded, and
     the separators are single "|" and "/" characters, no spaces. Example:
       HKQuantityTypeIdentifierBodyMass|2026-10-19 07:15:00 -0400|154.3|Health
       BloodPressure|2026-10-19 07:20:00 -0400|122/78|Omron Connect
   * sourceName is kept on the row so the sheet can untick readings from a watch (isWatchSource): it is for the page, not for the server.
   Rows come out sorted (date, time, sourceName, the number(s), key text), whatever order the file had them in.

   Result of scan(source, opts)
     {
       weights:  [{date, time, kg, context, source_key, sourceName}],
       readings: [{date, time, systolic, diastolic, context, source_key, sourceName}],
       summary: {
         found:   {weights, readings},   // distinct, readable weights / paired readings, before the plausibility check
         kept:    {weights, readings},   // the rows above
         skipped: {unknownUnit, halfPair, outOfRange, badEntity, tagTooLong, duplicate, unreadable},
         firstDate, lastDate,            // of the kept rows, "YYYY-MM-DD", or null
         sourceNames,                    // the distinct sourceNames of the kept rows, sorted
       },
       stats: {chars, maxCarry},         // characters read; the largest carry-over buffer (never above MAX_TAG)
     }
   skipped counts records of the file, except outOfRange (rows: a reading is two records; a systolic not above its diastolic is out of
   range too) and halfPair (halves). tagTooLong counts tags of any type. unreadable is an unfinished tag at the end of the file, a tag
   cut short by a "<", a missing value, startDate or sourceName, a value that is not a plain number (digits with an optional fraction),
   and a bad startDate. Reasons are checked in this order: unknownUnit, badEntity, unreadable, duplicate, outOfRange (halfPair at the
   end). A unit is compared as written, so "KG" is unknown.

   Also here: filterSince / defaultSince (the review's period: the last 3 months by default), batches (groups of 1,000 for the upload),
   forUpload (rows as the batch routes take them: without sourceName), isWatchSource.

   source_key needs SHA-256: crypto.subtle where the page has it (HTTPS or localhost), else a small pure-JavaScript SHA-256 (a self-hosted
   app on a plain-HTTP address has no crypto.subtle). Both give the same digest; tests/data/apple_health_vectors.json pins them.

   Plain script: needs js/engine/rules.js first (halfUp); runs in the page (window.KH.appleHealth) and under Node
   (tests/js/run_vectors.mjs, tests/js/apple_health_large.mjs). No DOM. All text in a row is for textContent. */
(function (root) {
  'use strict';
  const KH = root.KH || (root.KH = {});
  const { halfUp } = KH.rules;

  const MAX_TAG = 8192; // characters of one <Record ...> start tag; a longer one is skipped
  const BATCH_SIZE = 1000; // rows per upload request (the batch routes take 1 to 1,000)
  const PROGRESS_STEP = 10 * 1024 * 1024; // characters between two onProgress calls
  const KG_PER_LB = 0.45359237; // exactly (note 10 F7)
  const RANGES = { kg: [20, 400], systolic: [50, 300], diastolic: [20, 200] }; // note 10 section 4.1: the project's own plausibility ranges

  const TYPE_WEIGHT = 'HKQuantityTypeIdentifierBodyMass';
  const TYPE_SYSTOLIC = 'HKQuantityTypeIdentifierBloodPressureSystolic';
  const TYPE_DIASTOLIC = 'HKQuantityTypeIdentifierBloodPressureDiastolic';
  const TYPE_FILTER = 'HKQuantityTypeIdentifierB'; // every tag without this text is dropped unread

  const LT = 60, GT = 62, DQ = 34, SQ = 39, EQ = 61, SLASH = 47; // character codes
  const OPEN = -1, BROKEN = -2; // findEnd answers other than the index of the ">"

  const NOT_TEXT = 'The Apple Health reader takes text: pipe the file stream through TextDecoderStream, or pass strings.';

  // ---------------------------------------------------------------------------
  // Text helpers
  // ---------------------------------------------------------------------------
  const isSpace = (c) => c === 32 || c === 9 || c === 10 || c === 13;
  const pad2 = (n) => String(n).padStart(2, '0');
  const isLeap = (y) => (y % 4 === 0 && y % 100 !== 0) || y % 400 === 0;
  const daysIn = (y, m) => (m === 2 ? (isLeap(y) ? 29 : 28) : [4, 6, 9, 11].includes(m) ? 30 : 31);

  // A copy of a piece of a big chunk. V8, JavaScriptCore and SpiderMonkey slice a substring without copying it (above a few
  // characters), so a row that kept a sourceName cut from a 64 KiB chunk would keep that whole chunk alive, thousands of times over.
  // The JSON round trip builds a new string of its own in every engine. Only what a row or a table keeps goes through it.
  const detach = (s) => JSON.parse(JSON.stringify(s));

  const NAMED = new Map([['amp', '&'], ['lt', '<'], ['gt', '>'], ['quot', '"'], ['apos', "'"]]);
  // A character reference, or a name reference, or any other "&" (which is then bad). One pass: the output is never read again.
  const ENTITY = /&(?:#x([0-9A-Fa-f]{1,8})|#([0-9]{1,8})|([A-Za-z][A-Za-z0-9]*));|&/g;
  const isXmlChar = (cp) => cp === 9 || cp === 10 || cp === 13 || (cp >= 0x20 && cp <= 0xD7FF) || (cp >= 0xE000 && cp <= 0xFFFD) || (cp >= 0x10000 && cp <= 0x10FFFF);

  // The text with the five XML entities and numeric character references decoded, or null if it holds any other "&".
  function decode(raw) {
    if (raw.indexOf('&') < 0) return raw;
    let bad = false;
    const out = raw.replace(ENTITY, (m, hex, dec, name) => {
      let ch = null;
      if (name !== undefined) ch = NAMED.has(name) ? NAMED.get(name) : null;
      else if (hex !== undefined || dec !== undefined) {
        const cp = hex !== undefined ? parseInt(hex, 16) : parseInt(dec, 10);
        if (isXmlChar(cp)) ch = String.fromCodePoint(cp);
      }
      if (ch === null) { bad = true; return ''; }
      return ch;
    });
    return bad ? null : out;
  }

  // The five attributes this reader looks at, raw (not decoded), from a complete start tag; undefined when absent. One linear pass.
  function attributes(tag) {
    const out = { type: undefined, unit: undefined, value: undefined, startDate: undefined, sourceName: undefined };
    const n = tag.length;
    let p = 7; // after "<Record"
    while (p < n) {
      let c = tag.charCodeAt(p);
      if (isSpace(c) || c === SLASH || c === GT) { p += 1; continue; }
      let q = p;
      while (q < n && !isSpace(c = tag.charCodeAt(q)) && c !== EQ && c !== GT && c !== SLASH && c !== DQ && c !== SQ) q += 1;
      if (q === p) { p += 1; continue; } // a quote or "=" with no name before it
      const name = tag.slice(p, q);
      p = q;
      while (p < n && isSpace(tag.charCodeAt(p))) p += 1;
      if (tag.charCodeAt(p) !== EQ) continue;
      p += 1;
      while (p < n && isSpace(tag.charCodeAt(p))) p += 1;
      c = tag.charCodeAt(p);
      if (c !== DQ && c !== SQ) continue;
      const close = tag.indexOf(c === DQ ? '"' : "'", p + 1);
      if (close < 0) break;
      if ((name === 'type' || name === 'unit' || name === 'value' || name === 'startDate' || name === 'sourceName') && out[name] === undefined) {
        out[name] = tag.slice(p + 1, close);
      }
      p = close + 1;
    }
    return out;
  }

  // ---------------------------------------------------------------------------
  // Dates and contexts
  // ---------------------------------------------------------------------------
  const STAMP = /^(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2}):(\d{2}) [+-](\d{2})(\d{2})$/;
  const dayNumber = (y, m, d) => Date.UTC(y, m - 1, d) / 86400000;

  // {date: 'YYYY-MM-DD', time: 'HH:MM', minutes} from a startDate as written, or null. todayNumber: the day count of the caller's today, or null.
  function readStamp(text, todayNumber) {
    const m = STAMP.exec(text);
    if (!m) return null;
    const y = Number(m[1]), mo = Number(m[2]), d = Number(m[3]), h = Number(m[4]), mi = Number(m[5]);
    if (y < 1900 || mo < 1 || mo > 12 || d < 1 || d > daysIn(y, mo)) return null;
    if (h > 23 || mi > 59 || Number(m[6]) > 59 || Number(m[7]) > 23 || Number(m[8]) > 59) return null;
    if (todayNumber !== null && dayNumber(y, mo, d) > todayNumber + 1) return null;
    return { date: `${m[1]}-${m[2]}-${m[3]}`, time: `${m[4]}:${m[5]}`, minutes: h * 60 + mi };
  }

  // 04:00-10:59 morning; blood pressure only: 17:00-23:59 evening; everything else other.
  function contextOf(kind, minutes) {
    if (minutes >= 240 && minutes <= 659) return 'morning';
    if (kind === 'reading' && minutes >= 1020) return 'evening';
    return 'other';
  }

  const NUMBER = /^\d{1,15}(?:\.\d{1,15})?$/;

  // ---------------------------------------------------------------------------
  // SHA-256 (source_key)
  // ---------------------------------------------------------------------------
  const SHA_K = new Uint32Array([
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5, 0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3,
    0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174, 0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
    0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967, 0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13,
    0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85, 0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
    0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3, 0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208,
    0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
  ]);
  const SHA_H0 = [0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19];

  // The SHA-256 digest (32 bytes) of a Uint8Array, FIPS 180-4, in plain JavaScript.
  function sha256Js(bytes) {
    const H = new Uint32Array(SHA_H0);
    const len = bytes.length;
    const padded = new Uint8Array(((len + 9 + 63) >> 6) << 6);
    padded.set(bytes);
    padded[len] = 0x80;
    const view = new DataView(padded.buffer);
    view.setUint32(padded.length - 8, Math.floor((len * 8) / 4294967296));
    view.setUint32(padded.length - 4, (len * 8) >>> 0);
    const w = new Uint32Array(64);
    for (let off = 0; off < padded.length; off += 64) {
      for (let t = 0; t < 16; t += 1) w[t] = view.getUint32(off + t * 4);
      for (let t = 16; t < 64; t += 1) {
        const x = w[t - 15], y = w[t - 2];
        const s0 = ((x >>> 7) | (x << 25)) ^ ((x >>> 18) | (x << 14)) ^ (x >>> 3);
        const s1 = ((y >>> 17) | (y << 15)) ^ ((y >>> 19) | (y << 13)) ^ (y >>> 10);
        w[t] = w[t - 16] + s0 + w[t - 7] + s1;
      }
      let a = H[0], b = H[1], c = H[2], d = H[3], e = H[4], f = H[5], g = H[6], h = H[7];
      for (let t = 0; t < 64; t += 1) {
        const S1 = ((e >>> 6) | (e << 26)) ^ ((e >>> 11) | (e << 21)) ^ ((e >>> 25) | (e << 7));
        const t1 = (h + S1 + ((e & f) ^ (~e & g)) + SHA_K[t] + w[t]) | 0;
        const S0 = ((a >>> 2) | (a << 30)) ^ ((a >>> 13) | (a << 19)) ^ ((a >>> 22) | (a << 10));
        const t2 = (S0 + ((a & b) ^ (a & c) ^ (b & c))) | 0;
        h = g; g = f; f = e; e = (d + t1) | 0; d = c; c = b; b = a; a = (t1 + t2) | 0;
      }
      H[0] += a; H[1] += b; H[2] += c; H[3] += d; H[4] += e; H[5] += f; H[6] += g; H[7] += h;
    }
    const out = new Uint8Array(32);
    const outView = new DataView(out.buffer);
    for (let i = 0; i < 8; i += 1) outView.setUint32(i * 4, H[i]);
    return out;
  }

  const toHex = (bytes) => Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');

  // The 64 hex characters of the SHA-256 of the UTF-8 bytes of a text: crypto.subtle when the page has it, else sha256Js.
  async function sha256Hex(text) {
    const bytes = new root.TextEncoder().encode(text);
    const subtle = root.crypto && root.crypto.subtle;
    return toHex(subtle ? new Uint8Array(await subtle.digest('SHA-256', bytes)) : sha256Js(bytes));
  }

  // ---------------------------------------------------------------------------
  // The scanner
  // ---------------------------------------------------------------------------
  const SEEK = 0, TAG = 1, SKIP = 2;

  /* A scanner fed text a chunk at a time: push(chunk) for each, then finish() (async: the keys are hashed).
     opts.today: 'YYYY-MM-DD' of the caller; a record dated more than a day after it is unreadable. */
  function createScanner(opts) {
    opts = opts || {};
    let todayNumber = null;
    if (opts.today !== undefined && opts.today !== null) {
      const t = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(opts.today));
      if (!t || Number(t[2]) < 1 || Number(t[2]) > 12 || Number(t[3]) < 1 || Number(t[3]) > daysIn(Number(t[1]), Number(t[2]))) {
        throw new TypeError('today must be a date as YYYY-MM-DD');
      }
      todayNumber = dayNumber(Number(t[1]), Number(t[2]), Number(t[3]));
    }
    const found = { weights: 0, readings: 0 };
    const skipped = { unknownUnit: 0, halfPair: 0, outOfRange: 0, badEntity: 0, tagTooLong: 0, duplicate: 0, unreadable: 0 };
    const weights = []; // rows still to be keyed: {date, time, kg, context, keyText, sourceName}
    const seen = new Set(); // type|startDate|value|sourceName of every record kept so far, for the repeats
    const groups = new Map(); // startDate|sourceName -> the systolic and diastolic values seen there
    const names = new Map(); // sourceName -> the one copy of it that rows share

    const start = /<Record[ \t\r\n]/g;
    let mode = SEEK;
    let carry = ''; // see the header: never more than MAX_TAG characters
    let resume = 0; // TAG: how much of carry has been looked at
    let quote = 0; // TAG and SKIP: the quote character that is open, or 0
    let stopAt = 0; // findEnd's second answer
    let chars = 0;
    let maxCarry = 0;

    // Looks for the end of a tag in s[from, to). Returns the index of its ">", OPEN when the text ran out (quote says whether a quote is
    // open) or BROKEN when a "<" was inside the tag (stopAt is its index).
    function findEnd(s, from, to) {
      let q = quote;
      let p = from;
      for (; p < to; p += 1) {
        const c = s.charCodeAt(p);
        if (q !== 0) {
          if (c === q) q = 0;
          else if (c === LT) { stopAt = p; return BROKEN; }
        } else if (c === GT) {
          quote = 0;
          return p;
        } else if (c === DQ || c === SQ) {
          q = c;
        } else if (c === LT) {
          stopAt = p;
          return BROKEN;
        }
      }
      quote = q;
      return OPEN;
    }

    // One complete start tag.
    function handle(tag) {
      if (tag.indexOf(TYPE_FILTER) < 0) return;
      const a = attributes(tag);
      const kind = a.type === TYPE_WEIGHT ? 'weight' : a.type === TYPE_SYSTOLIC ? 'systolic' : a.type === TYPE_DIASTOLIC ? 'diastolic' : null;
      if (kind === null) return;
      if (kind === 'weight' ? a.unit !== 'kg' && a.unit !== 'lb' : a.unit !== 'mmHg') { skipped.unknownUnit += 1; return; }
      const value = a.value === undefined ? undefined : decode(a.value);
      const startDate = a.startDate === undefined ? undefined : decode(a.startDate);
      const sourceName = a.sourceName === undefined ? undefined : decode(a.sourceName);
      if (value === null || startDate === null || sourceName === null) { skipped.badEntity += 1; return; }
      if (value === undefined || startDate === undefined || sourceName === undefined || !NUMBER.test(value)) { skipped.unreadable += 1; return; }
      const when = readStamp(startDate, todayNumber);
      if (when === null) { skipped.unreadable += 1; return; }
      const keyText = `${a.type}|${startDate}|${value}|${sourceName}`;
      if (seen.has(keyText)) { skipped.duplicate += 1; return; }
      const key = detach(keyText);
      seen.add(key);
      let name = names.get(sourceName);
      if (name === undefined) { name = detach(sourceName); names.set(name, name); }
      if (kind === 'weight') {
        found.weights += 1;
        const kg = halfUp(a.unit === 'kg' ? Number(value) : Number(value) * KG_PER_LB, 2);
        if (!(kg >= RANGES.kg[0] && kg <= RANGES.kg[1])) { skipped.outOfRange += 1; return; }
        weights.push({ date: when.date, time: when.time, kg, context: contextOf('weight', when.minutes), keyText: key, sourceName: name });
        return;
      }
      const groupKey = `${startDate}|${sourceName}`;
      let g = groups.get(groupKey);
      if (g === undefined) {
        g = { startDate: detach(startDate), date: when.date, time: when.time, minutes: when.minutes, sourceName: name, systolic: [], diastolic: [] };
        groups.set(detach(groupKey), g);
      }
      g[kind].push(detach(value));
    }

    function push(chunk) {
      if (typeof chunk !== 'string') throw new TypeError(NOT_TEXT);
      if (chunk === '') return;
      chars += chunk.length;
      const s = carry === '' ? chunk : carry + chunk;
      const n = s.length;
      carry = '';
      let i = 0; // SEEK and SKIP: where to go on in s
      let tagStart = 0; // TAG: where the tag begins in s (0 when it began in an earlier chunk)
      let scanFrom = resume; // TAG: how far into s it has been looked at
      for (;;) {
        if (mode === SEEK) {
          start.lastIndex = i;
          const m = start.exec(s);
          if (m === null) {
            const lt = s.lastIndexOf('<');
            if (lt >= i && lt >= n - 7) carry = s.slice(lt); // "<Record" is 7 characters: the next chunk may complete it
            break;
          }
          tagStart = m.index;
          scanFrom = tagStart + 7;
          quote = 0;
          mode = TAG;
        }
        if (mode === TAG) {
          const limit = Math.min(n, tagStart + MAX_TAG);
          const end = findEnd(s, scanFrom, limit);
          if (end >= 0) {
            handle(s.slice(tagStart, end + 1));
            mode = SEEK;
            i = end + 1;
          } else if (end === BROKEN) {
            skipped.unreadable += 1;
            mode = SEEK;
            i = stopAt;
          } else if (limit - tagStart >= MAX_TAG) {
            skipped.tagTooLong += 1;
            mode = SKIP;
            i = limit;
          } else {
            carry = s.slice(tagStart);
            resume = carry.length;
            break;
          }
          continue;
        }
        const end = findEnd(s, i, n); // SKIP: the rest of a tag that was too long
        if (end >= 0) { mode = SEEK; i = end + 1; continue; }
        if (end === BROKEN) { mode = SEEK; i = stopAt; continue; }
        break;
      }
      if (carry.length > maxCarry) maxCarry = carry.length;
    }

    async function finish() {
      if (mode === TAG) skipped.unreadable += 1; // the file ends inside a tag
      const readings = [];
      for (const g of groups.values()) {
        if (g.systolic.length !== 1 || g.diastolic.length !== 1) { skipped.halfPair += g.systolic.length + g.diastolic.length; continue; }
        found.readings += 1;
        const systolic = halfUp(Number(g.systolic[0]), 0);
        const diastolic = halfUp(Number(g.diastolic[0]), 0);
        if (!(systolic >= RANGES.systolic[0] && systolic <= RANGES.systolic[1] && diastolic >= RANGES.diastolic[0] && diastolic <= RANGES.diastolic[1] && systolic > diastolic)) {
          skipped.outOfRange += 1;
          continue;
        }
        readings.push({
          date: g.date, time: g.time, systolic, diastolic, context: contextOf('reading', g.minutes),
          keyText: `BloodPressure|${g.startDate}|${g.systolic[0]}/${g.diastolic[0]}|${g.sourceName}`, sourceName: g.sourceName,
        });
      }
      // date, time, source, then the number(s), then the key text: a total order, so the rows do not depend on the order of the file
      const cmp = (x, y) => (x < y ? -1 : x > y ? 1 : 0);
      const order = (a, b) => cmp(a.date, b.date) || cmp(a.time, b.time) || cmp(a.sourceName, b.sourceName);
      weights.sort((a, b) => order(a, b) || cmp(a.kg, b.kg) || cmp(a.keyText, b.keyText));
      readings.sort((a, b) => order(a, b) || cmp(a.systolic, b.systolic) || cmp(a.diastolic, b.diastolic) || cmp(a.keyText, b.keyText));
      const rows = weights.concat(readings);
      for (let at = 0; at < rows.length; at += 500) {
        await Promise.all(rows.slice(at, at + 500).map(async (row) => { row.source_key = (await sha256Hex(row.keyText)).slice(0, 32); }));
      }
      const finalWeights = weights.map((r) => ({ date: r.date, time: r.time, kg: r.kg, context: r.context, source_key: r.source_key, sourceName: r.sourceName }));
      const finalReadings = readings.map((r) => ({
        date: r.date, time: r.time, systolic: r.systolic, diastolic: r.diastolic, context: r.context, source_key: r.source_key, sourceName: r.sourceName,
      }));
      const dates = rows.map((r) => r.date).sort();
      return {
        weights: finalWeights,
        readings: finalReadings,
        summary: {
          found: { weights: found.weights, readings: found.readings },
          kept: { weights: finalWeights.length, readings: finalReadings.length },
          skipped: { ...skipped },
          firstDate: dates.length ? dates[0] : null,
          lastDate: dates.length ? dates[dates.length - 1] : null,
          sourceNames: [...new Set(rows.map((r) => r.sourceName))].sort(),
        },
        stats: { chars, maxCarry },
      };
    }

    return { push, finish, chars: () => chars };
  }

  const abortError = () => Object.assign(new Error('The import was cancelled.'), { name: 'AbortError' });

  /* scan(source, opts) -> Promise of the result described in the header.
     source: a ReadableStream of strings (file.stream().pipeThrough(new TextDecoderStream())), an async iterable of strings, an array of
     strings, or one string. A chunk that is not a string is a TypeError.
     opts.today: 'YYYY-MM-DD' (see createScanner). opts.signal: an AbortSignal; aborting rejects with an AbortError after the chunk being
     read, and the stream is cancelled. opts.onProgress({chars}): about every opts.progressEvery (default 10 MiB) characters. */
  async function scan(source, opts) {
    opts = opts || {};
    const scanner = createScanner(opts);
    const signal = opts.signal;
    const every = opts.progressEvery > 0 ? opts.progressEvery : PROGRESS_STEP;
    let reported = 0;
    const take = (chunk) => {
      if (signal && signal.aborted) throw abortError();
      scanner.push(chunk);
      if (typeof opts.onProgress === 'function' && scanner.chars() - reported >= every) {
        reported = scanner.chars();
        opts.onProgress({ chars: reported });
      }
    };
    if (signal && signal.aborted) {
      if (source && typeof source.cancel === 'function') { try { await source.cancel(abortError()); } catch (ignored) { /* nothing to stop */ } }
      throw abortError();
    }
    if (typeof source === 'string') {
      take(source);
    } else if (source && typeof source.getReader === 'function') {
      const reader = source.getReader(); // not "for await": Safari cannot iterate a ReadableStream
      try {
        for (;;) {
          const { done, value } = await reader.read();
          if (done) break;
          take(value);
        }
      } catch (e) {
        try { await reader.cancel(e); } catch (ignored) { /* the stream is already broken */ }
        throw e;
      } finally {
        reader.releaseLock();
      }
    } else if (source && typeof source[Symbol.asyncIterator] === 'function') {
      for await (const chunk of source) take(chunk);
    } else if (source && typeof source[Symbol.iterator] === 'function') {
      for (const chunk of source) take(chunk);
    } else {
      throw new TypeError('The Apple Health reader takes a stream of text, an async iterable of strings, or a string.');
    }
    return scanner.finish();
  }

  // ---------------------------------------------------------------------------
  // After the scan: the review sheet's helpers
  // ---------------------------------------------------------------------------
  const DAY = /^(\d{4})-(\d{2})-(\d{2})$/;
  function readDay(text, what) {
    const m = DAY.exec(typeof text === 'string' ? text : '');
    if (!m || Number(m[2]) < 1 || Number(m[2]) > 12 || Number(m[3]) < 1 || Number(m[3]) > daysIn(Number(m[1]), Number(m[2]))) {
      throw new TypeError(`${what} must be a date as YYYY-MM-DD`);
    }
    return [Number(m[1]), Number(m[2]), Number(m[3])];
  }

  // The day three calendar months before `today` ('YYYY-MM-DD'): the review's default period starts there. A day that month does not
  // have becomes its last day (May 31 -> Feb 28 or 29).
  function defaultSince(today) {
    const [y, m, d] = readDay(today, 'today');
    let year = y;
    let month = m - 3;
    if (month < 1) { month += 12; year -= 1; }
    return `${String(year).padStart(4, '0')}-${pad2(month)}-${pad2(Math.min(d, daysIn(year, month)))}`;
  }

  // The rows dated on or after `since` ('YYYY-MM-DD'); no `since` (null, undefined or '') is everything. A new array; the rows are the same objects.
  function filterSince(rows, since) {
    if (since === null || since === undefined || since === '') return rows.slice();
    readDay(since, 'since');
    return rows.filter((r) => r.date >= since);
  }

  // The rows in groups of `size` (default 1,000, what one upload request takes), oldest first as given; no rows, no groups.
  function batches(rows, size = BATCH_SIZE) {
    if (!Number.isInteger(size) || size < 1) throw new RangeError('size must be a whole number of 1 or more');
    const out = [];
    for (let at = 0; at < rows.length; at += size) out.push(rows.slice(at, at + size));
    return out;
  }

  // Rows as the batch routes take them: the same fields without sourceName (which is for the page only).
  function forUpload(rows) {
    return rows.map(({ sourceName, ...row }) => row);
  }

  // True for a source whose name contains "Watch", any case: its blood pressure readings are the ones note 10 F4 does not recommend.
  function isWatchSource(sourceName) {
    return /watch/i.test(String(sourceName == null ? '' : sourceName));
  }

  KH.appleHealth = {
    MAX_TAG, BATCH_SIZE, PROGRESS_STEP, KG_PER_LB, RANGES, TYPE_WEIGHT, TYPE_SYSTOLIC, TYPE_DIASTOLIC,
    scan, createScanner, defaultSince, filterSince, batches, forUpload, isWatchSource,
    decode, contextOf, sha256Hex, sha256Js,
  };
})(typeof window !== 'undefined' ? window : globalThis);
