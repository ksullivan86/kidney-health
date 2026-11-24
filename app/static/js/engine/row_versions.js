/* Kidney Diet Log — versions for every synced kind: the browser twin of app/row_versions.py (design note 39 §8.3).

   A version is FNV-1a (64 bit) over the canonical text of what the person sees of a row, so the same content has the same
   version on the phone, in the web app and on the server. An entry's is note 02's (app/log.py entry_version); every other
   kind's text starts with the kind's name and follows its own field list. The input is the row as the API, the export or
   the change feed shows it. Written without TextEncoder so it also runs where the page has none.

   Pure, no I/O. Parity: tests/data/row_version_vectors.json (tests/data/gen_row_version_vectors.py), replayed by
   `node tests/js/run_vectors.mjs`. Exposes KH.rowVersions = { version, matches, canonicalText, KINDS, FIELDS, ITEM_FIELDS,
   ENTRY_FIELDS, NUTRIENT_KEYS }. */
(() => {
  'use strict';
  const root = typeof window !== 'undefined' ? window : globalThis;
  const KH = root.KH || (root.KH = {});

  // app/nutrients.py NUTRIENT_KEYS, in registry order.
  const NUTRIENT_KEYS = ['calories_kcal', 'protein_g', 'fat_g', 'sat_fat_g', 'carbs_g', 'fiber_g', 'sugar_g', 'sodium_mg',
    'potassium_mg', 'phosphorus_mg', 'calcium_mg', 'fluid_ml'];
  const KINDS = ['food', 'entry', 'meal', 'lab', 'symptom', 'weight', 'reading'];
  const ENTRY_FIELDS = ['date', 'meal', 'food_name', 'servings', 'grams', 'note', 'status', 'purpose'];
  const FIELDS = {
    food: ['name', 'brand', 'category', 'serving_desc', 'serving_g', 'gtin', 'kidney_notes', 'ingredients_text', 'hidden', 'flags'],
    meal: ['name', 'note', 'meal_hint', 'servings_made', 'source_url', 'steps', 'items'],
    lab: ['analyte', 'entered_value', 'entered_unit', 'taken_on', 'note'],
    symptom: ['date', 'symptom', 'label', 'severity', 'note'],
    weight: ['date', 'time', 'kg', 'context', 'note'],
    reading: ['date', 'time', 'systolic', 'diastolic', 'pulse', 'context', 'note'],
  };
  const ITEM_FIELDS = ['food_name', 'servings'];
  const EMPTY_NOTE_KINDS = new Set(['lab', 'symptom', 'weight', 'reading']);
  const FNV_OFFSET = 0xcbf29ce484222325n, FNV_PRIME = 0x100000001b3n, FNV_MASK = 0xffffffffffffffffn;

  function utf8(text) {
    const out = [];
    for (const ch of String(text)) {
      const c = ch.codePointAt(0);
      if (c < 0x80) out.push(c);
      else if (c < 0x800) out.push(0xc0 | (c >> 6), 0x80 | (c & 63));
      else if (c < 0x10000) out.push(0xe0 | (c >> 12), 0x80 | ((c >> 6) & 63), 0x80 | (c & 63));
      else out.push(0xf0 | (c >> 18), 0x80 | ((c >> 12) & 63), 0x80 | ((c >> 6) & 63), 0x80 | (c & 63));
    }
    return out;
  }
  // log._version_piece: "~" for none, "n<number>;" for a number, "s<UTF-8 bytes>:<text>" for text. A true/false is the
  // number 1 or 0, and a list is its length then each element (row_versions._piece).
  function piece(value) {
    if (value == null) return '~';
    if (typeof value === 'boolean') return piece(value ? 1 : 0);
    if (Array.isArray(value)) return piece(value.length) + value.map(piece).join('');
    if (typeof value === 'string') return `s${utf8(value).length}:${value}`;
    return `n${String(Number(value))};`;
  }
  function fnv(text) {
    let digest = FNV_OFFSET;
    for (const byte of utf8(text)) digest = ((digest ^ BigInt(byte)) * FNV_PRIME) & FNV_MASK;
    return digest.toString(16).padStart(16, '0');
  }
  const codeOrder = (a, b) => (a < b ? -1 : a > b ? 1 : 0); // Python's sorted() on text: by code unit here, the same for these keys

  function canonicalText(kind, row) {
    if (kind === 'entry') {
      const nutrients = row.nutrients || {};
      return ENTRY_FIELDS.map((name) => piece(row[name])).join('') + NUTRIENT_KEYS.map((key) => piece(nutrients[key])).join('');
    }
    if (!FIELDS[kind]) throw new Error(`unknown kind ${kind}`);
    let text = piece(kind);
    for (const name of FIELDS[kind]) {
      let value = row[name];
      if ((name === 'note' && EMPTY_NOTE_KINDS.has(kind)) || name === 'label') value = value == null ? '' : value;
      else if (name === 'flags') value = (value || []).map(String).sort(codeOrder);
      else if (name === 'steps') value = (value || []).map(String);
      else if (name === 'items') value = (value || []).map((item) => ITEM_FIELDS.map((f) => (item[f] === undefined ? null : item[f])));
      text += piece(value === undefined ? null : value);
    }
    if (kind === 'food') {
      const nutrients = row.nutrients || {};
      text += NUTRIENT_KEYS.map((key) => piece(nutrients[key] === undefined ? null : nutrients[key])).join('');
    }
    return text;
  }
  function version(kind, row) { return fnv(canonicalText(kind, row)); }

  // log.version_matches: RFC 9110 strong comparison of an If-Match header (null = none sent) with a row's version.
  function matches(header, current) {
    if (header == null) return true;
    for (let tag of String(header).split(',')) {
      tag = tag.trim();
      if (tag === '*') return true;
      if (tag.startsWith('W/') || tag.startsWith('w/')) continue;
      if (tag.replace(/^"+|"+$/g, '') === current) return true;
    }
    return false;
  }

  KH.rowVersions = { version, matches, canonicalText, KINDS, FIELDS, ITEM_FIELDS, ENTRY_FIELDS, NUTRIENT_KEYS };
})();
