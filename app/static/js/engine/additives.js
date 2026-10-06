/* Kidney Diet Log — additives that matter for a kidney diet: the browser twin of app/additives.py
   (note 03 R5, F2).

   scan(tags, ingredientsText, name) turns additive tags (Open Food Facts `en:e451i`), an ingredient
   list and a product name into the flags phosphate_additive, potassium_additive and avoid_ckd (a salt
   substitute), the additives found (why a flag was set) and notes. Trace uses (preservatives,
   sweeteners, starch phosphates) give a note only, never a flag. Every text is cleaned first
   (js/engine/textclean.js), so invisible characters cannot hide a word.

   Used by Quick add to show what the server will flag before saving (the server scans again on save),
   and by the demo API (js/mock/foods.js, log.js) so a custom food with an ingredient list gets the
   flags the server would give it. Parity: tests/data/barcode_vectors.json (generated from
   app/additives.py by tests/data/gen_barcode_vectors.py), replayed by `node tests/js/run_vectors.mjs`.

   Exposes KH.additives = { scan, splitCode, classifyCode, displayCode, E_NAMES, NAME_TO_CODE,
   SALT_SUBSTITUTE_NOTE, MAX_INGREDIENTS_CHARS }. Needs js/engine/textclean.js loaded first. */
(() => {
  'use strict';
  const root = typeof window !== 'undefined' ? window : globalThis;
  const KH = root.KH || (root.KH = {});
  const T = KH.textclean;

  // ---- E-number tiers (lower-case codes without the "en:" prefix) ----
  const PHOSPHATE = new Set(['e338', 'e339', 'e340', 'e341', 'e343', 'e450', 'e451', 'e452', 'e541', 'e542']);
  const PHOSPHATE_TRACE = new Set(['e1410', 'e1412', 'e1413', 'e1414', 'e1442', 'e442']);
  const POTASSIUM_BULK = new Set(['e326', 'e332', 'e261', 'e508', 'e501', 'e340', 'e351', 'e336', 'e337', 'e357',
    'e577', 'e622', 'e525', 'e515', 'e402', 'e283', 'e450v', 'e451ii', 'e452ii']);
  const POTASSIUM_TRACE = new Set(['e202', 'e212', 'e224', 'e228', 'e249', 'e252', 'e536', 'e555', 'e522', 'e628', 'e632', 'e950', 'e954iv']);

  // Null-prototype tables: a phrase such as "constructor" must never find an inherited property.
  const E_NAMES = Object.assign(Object.create(null), {
    e338: 'phosphoric acid', e339: 'sodium phosphates', e340: 'potassium phosphates',
    e341: 'calcium phosphates', e343: 'magnesium phosphates', e450: 'diphosphates',
    e450v: 'tetrapotassium diphosphate', e451: 'triphosphates', e451ii: 'pentapotassium triphosphate',
    e452: 'polyphosphates', e452ii: 'potassium polyphosphate', e541: 'sodium aluminium phosphate',
    e542: 'bone phosphate',
    e1410: 'monostarch phosphate', e1412: 'distarch phosphate', e1413: 'phosphated distarch phosphate',
    e1414: 'acetylated distarch phosphate', e1442: 'hydroxypropyl distarch phosphate',
    e442: 'ammonium phosphatides',
    e326: 'potassium lactate', e332: 'potassium citrates', e261: 'potassium acetates',
    e508: 'potassium chloride', e501: 'potassium carbonates', e351: 'potassium malate',
    e336: 'potassium tartrates (cream of tartar)', e337: 'sodium potassium tartrate',
    e357: 'potassium adipate', e577: 'potassium gluconate', e622: 'monopotassium glutamate',
    e525: 'potassium hydroxide', e515: 'potassium sulphates', e402: 'potassium alginate',
    e283: 'potassium propionate',
    e202: 'potassium sorbate', e212: 'potassium benzoate', e224: 'potassium metabisulphite',
    e228: 'potassium hydrogen sulphite', e249: 'potassium nitrite', e252: 'potassium nitrate',
    e536: 'potassium ferrocyanide', e555: 'potassium aluminium silicate',
    e522: 'aluminium potassium sulphate', e628: 'dipotassium guanylate', e632: 'dipotassium inosinate',
    e950: 'acesulfame K', e954iv: 'potassium saccharin',
  });

  // Ingredient-list names → E-code (keys lower-case, single-spaced).
  const NAME_TO_CODE = Object.create(null);
  const names = (list, code) => { for (const n of list) NAME_TO_CODE[n] = code; };
  names(['phosphoric acid'], 'e338');
  names(['sodium phosphate', 'monosodium phosphate', 'disodium phosphate', 'trisodium phosphate'], 'e339');
  names(['potassium phosphate', 'monopotassium phosphate', 'dipotassium phosphate', 'tripotassium phosphate'], 'e340');
  names(['calcium phosphate', 'monocalcium phosphate', 'dicalcium phosphate', 'tricalcium phosphate'], 'e341');
  names(['magnesium phosphate'], 'e343');
  names(['sodium acid pyrophosphate', 'disodium pyrophosphate', 'tetrasodium pyrophosphate', 'sodium pyrophosphate',
    'disodium diphosphate', 'tetrasodium diphosphate'], 'e450');
  names(['tetrapotassium pyrophosphate', 'tetrapotassium diphosphate'], 'e450v');
  names(['sodium triphosphate', 'sodium tripolyphosphate', 'pentasodium triphosphate'], 'e451');
  names(['pentapotassium triphosphate', 'potassium tripolyphosphate'], 'e451ii');
  names(['sodium hexametaphosphate', 'sodium polyphosphate', 'sodium polyphosphates'], 'e452');
  names(['potassium polyphosphate'], 'e452ii');
  names(['sodium aluminum phosphate', 'sodium aluminium phosphate'], 'e541');
  names(['potassium lactate'], 'e326');
  names(['potassium citrate', 'tripotassium citrate', 'monopotassium citrate'], 'e332');
  names(['potassium acetate', 'potassium diacetate'], 'e261');
  names(['potassium chloride'], 'e508');
  names(['potassium carbonate', 'potassium bicarbonate', 'potassium hydrogen carbonate'], 'e501');
  names(['potassium malate'], 'e351');
  names(['cream of tartar', 'potassium bitartrate', 'potassium tartrate', 'dipotassium tartrate'], 'e336');
  names(['potassium sodium tartrate'], 'e337');
  names(['potassium adipate'], 'e357');
  names(['potassium gluconate'], 'e577');
  names(['monopotassium glutamate', 'potassium glutamate'], 'e622');
  names(['potassium hydroxide'], 'e525');
  names(['potassium sulfate', 'potassium sulphate'], 'e515');
  names(['potassium alginate'], 'e402');
  names(['potassium propionate'], 'e283');
  names(['potassium sorbate'], 'e202');
  names(['potassium benzoate'], 'e212');
  names(['potassium metabisulfite', 'potassium metabisulphite'], 'e224');
  names(['potassium bisulfite', 'potassium bisulphite', 'potassium hydrogen sulfite', 'potassium hydrogen sulphite'], 'e228');
  names(['potassium nitrite'], 'e249');
  names(['potassium nitrate'], 'e252');
  names(['potassium ferrocyanide'], 'e536');
  names(['potassium aluminium silicate', 'potassium aluminum silicate'], 'e555');
  names(['dipotassium guanylate'], 'e628');
  names(['dipotassium inosinate'], 'e632');
  names(['acesulfame k', 'acesulfame potassium', 'acesulfame-k', 'acesulfame'], 'e950');
  names(['potassium saccharin'], 'e954iv');

  const SALT_SUBSTITUTE_NOTE = 'AVOID with kidney disease: salt substitutes are potassium chloride and can push blood potassium to '
    + 'dangerous levels; use herbs, lemon or salt-free herb blends (check they are KCl-free).';
  const MAX_TAGS = 200;
  const MAX_INGREDIENTS_CHARS = 4000;
  const MAX_NAME_CHARS = 200;
  const MAX_ADDITIVES = 40;
  const MAX_PHRASE_CHARS = 80;

  function displayCode(code) { return `E${code.slice(1)}`; }

  // ---- Codes from tags and from text ----
  const TAG = /^(?:[a-z]{2,3}:)?(e\d{3,4})([a-z]{0,4})$/;
  // "e451i" → ["e451", "e451i"]; null for anything that is not an E-code.
  function splitCode(code) {
    const m = TAG.exec(T.pyStrip(String(code)).toLowerCase());
    return m ? [m[1], m[1] + m[2]] : null;
  }
  function classifyCode(code) {
    const parts = splitCode(code);
    if (!parts) return [];
    const [base, full] = parts;
    const kinds = [];
    if (PHOSPHATE.has(base) || PHOSPHATE.has(full)) kinds.push('phosphate');
    else if (PHOSPHATE_TRACE.has(base)) kinds.push('phosphate_trace');
    if (POTASSIUM_BULK.has(full) || POTASSIUM_BULK.has(base)) kinds.push('potassium');
    else if (POTASSIUM_TRACE.has(full) || POTASSIUM_TRACE.has(base)) kinds.push('potassium_trace');
    return kinds;
  }
  function codeName(base, full) { return E_NAMES[full] || E_NAMES[base] || displayCode(full); }

  // Python's \s (Unicode whitespace) and \w / isalpha() (Unicode letters) spelled for JavaScript.
  const S = `[${T.PY_SPACE_CLASS}]`;
  const ALPHA = /^\p{L}$/u;
  const TEXT_E = new RegExp(`(?<![a-z0-9])e(?:${S}|-)?(\\d{3,4})(?:${S}*\\(?${S}*(iii|ii|iv|ix|vii|vi|v|i|[a-f])${S}*\\)?)?(?![a-z0-9])`, 'g');
  const PHOSPHATE_WORD = /(?:phosph|fosf)(?:at|or|it|aat)/g;
  const PHOSPHATE_EXCLUDED = ['phosphatid', 'phospholip', 'fosfolip', 'fosfatid'];
  const PHOSPHATE_TRACE_PHRASES = new RegExp(
    `(?:(?:hydroxypropyl(?:ated)?|acetylated|phosphated)${S}+)*(?:di|mono)?(?:${S}|-)?starch${S}+phosphates?`
    + `|riboflavin(?:e)?(?:${S}|-)*(?:5['’]?(?:${S}|-)*)?(?:sodium${S}+)?(?:phosphate|fosfato|phosphat)`
    + `|(?:magnesium${S}+|sodium${S}+)?ascorbyl${S}+(?:phosphate|fosfato|phosphat)`, 'g');
  const K = '(?:mono|di|tri|tetra|penta)?(?:potassium|kalium|potasio|potassio|potássio)';
  const JOINERS = `(?:${S}+(?:sodium|hydrogen|dihydrogen|acid|di|mono|tri))*`;
  const BULK_STEMS = `(?:chlorid|la[ck]ta{1,2}t|citra{1,2}t|(?:di)?aceta{1,2}t|(?:bi)?carbona{1,2}t|hydrogen${S}*carbona{1,2}t`
    + '|(?:tripoly|poly|pyro|hexameta|meta|di|tri)?(?:phosph|fosf)a{1,2}t|mala{1,2}t|(?:bi)?tartra{1,2}t|glucona{1,2}t'
    + '|glutama{1,2}t|hydroxid|sulfa{1,2}t|sulpha{1,2}t|alginaa?t|propiona{1,2}t|adipa{1,2}t)';
  const TRACE_STEMS = '(?:sorba{1,2}t|benzoa{1,2}t|metabisulf|metabisulph|bisulf|bisulph|sulfi|sulphi|nitri|nitra{1,2}t|iodid|iodat'
    + '|jodid|joda{1,2}t|ferrocyan|silica|guanyla|inosina|saccharin)';
  const K_BULK = new RegExp(`(?<![a-z])(${K}${JOINERS}(?:${S}|-)*${BULK_STEMS})[a-z]*`, 'g');
  const K_TRACE = new RegExp(`(?<![a-z])(${K}${JOINERS}(?:${S}|-)*(?:aluminium${S}+|aluminum${S}+)?${TRACE_STEMS})[a-z]*`, 'g');
  const ANION_FIRST_BULK = new RegExp(
    '(?<![a-z])((?:chlor|clor|lact|latt|citr|acet|acét|bicarbon|carbon|pyrophosph|pirofosf|polyphosph|polifosf'
    + `|phosph|fosf|malat|tartr|glucon|glutam|hydrox|idross|hidróx|hidrox|sulfat|sulphat|solfat|algin|propion|adip)[a-zà-ÿ]*`
    + `${S}+(?:de|di|du|d['’]|of)${S}*${K})(?![a-z])`, 'g');
  const ANION_FIRST_TRACE = new RegExp(
    '(?<![a-z])((?:sorb|benzo|metabisulf|metabisolf|nitrit|nitrat|iodur|iodat|iodid|ferrocian|ferrocyan|sulfit|solfit'
    + `|silic|guanil|guanyl|inosin)[a-zà-ÿ]*${S}+(?:de|di|du|d['’]|of)${S}*${K})(?![a-z])`, 'g');
  const ACID_AFTER = new RegExp(`${S}+acid(?![\\p{L}\\p{N}_])`, 'uy');
  const ALUMINIUM_BEFORE = new RegExp(`(?:aluminium|aluminum)${S}*$`);
  const OTHER_BULK = /(?<![a-z])(cream of tartar|salt substitute)(?![a-z])/g;
  const ACESULFAME = new RegExp(`(?<![a-z])(acesulfam(?:e)?(?:(?:${S}|-)*(?:k|potassium))?)(?![a-z])`, 'g');
  const KCL = new RegExp(`^(?:${K}(?:${S}|-)*chlorid[\\p{L}\\p{N}_]*|(?:chlorure|cloruro|cloreto)${S}+(?:de|di)${S}*${K}|e(?:${S}|-)?508|kcl)(?![a-z])`, 'u');
  const SALT_SUBSTITUTE_NAME = new RegExp(
    `(?<![a-z])(?:salt${S}+substitute|salt${S}+replacer|lite${S}+salt|no-?salt(?!(?:${S}|-)+added)|nu(?:${S}|-)?salt|half${S}+salt|lo-?salt)(?![a-z])`);
  const INGREDIENTS_PREFIX = new RegExp(`^${S}*(?:ingredients?|ingrédients|ingredientes|ingredienti|zutaten|ingrediënten)${S}*:${S}*`);
  const CATIONS = new RegExp(
    '(?:(?:mono|di|tri|tetra|penta)?(?:sodium|potassium|calcium|magnesium|ammonium|aluminium|aluminum|ferric|zinc)'
    + `(?:${S}+(?:aluminium|aluminum|acid))?)${S}*$`);

  // The first top-level item of an ingredient list (commas or semicolons outside brackets).
  function firstIngredient(text) {
    const t = text.replace(INGREDIENTS_PREFIX, '');
    let depth = 0;
    for (let i = 0; i < t.length; i += 1) {
      const ch = t[i];
      if ('([{'.includes(ch)) depth += 1;
      else if (')]}'.includes(ch)) depth = Math.max(0, depth - 1);
      else if (',;\n'.includes(ch) && depth === 0) return T.pyStrip(t.slice(0, i), ' .*_');
    }
    return T.pyStrip(t, ' .*_');
  }
  // " ".join(text.split())[:MAX_PHRASE_CHARS]
  function phrase(text) {
    const words = text.split(new RegExp(`${S}+`)).filter(Boolean);
    return T.cpSlice(words.join(' '), 0, MAX_PHRASE_CHARS);
  }
  // The code point that ends just before / starts at UTF-16 index i (str[i-1] / str[i] in Python).
  function cpBefore(text, i) {
    if (i <= 0) return '';
    const lo = text.charCodeAt(i - 1);
    if (lo >= 0xdc00 && lo <= 0xdfff && i >= 2) {
      const hi = text.charCodeAt(i - 2);
      if (hi >= 0xd800 && hi <= 0xdbff) return text.slice(i - 2, i);
    }
    return text[i - 1];
  }
  function cpAt(text, i) { return String.fromCodePoint(text.codePointAt(i)); }
  // remaining[max(0, start - 40):start], counted in code points
  function windowBefore(text, start, n) {
    let i = start;
    for (let k = 0; k < n && i > 0; k += 1) i -= cpBefore(text, i).length;
    return text.slice(i, start);
  }
  function allMatches(re, text) { re.lastIndex = 0; return Array.from(text.matchAll(re)); }

  function scanText(text) {
    const found = [];
    const add = (code, name, kind) => {
      let ph = phrase(name);
      code = code || NAME_TO_CODE[ph] || null;
      if (code != null && classifyCode(code).includes(kind)) {
        const parts = splitCode(code);
        ph = codeName(parts[0], parts[1]); // one name per additive, whether it came from a tag or the text
      }
      found.push({ code, name: ph, kind, source: 'text' });
    };
    // 1. E-numbers written in the list.
    for (const m of allMatches(TEXT_E, text)) {
      const code = `e${m[1]}${m[2] || ''}`;
      const parts = splitCode(code);
      if (!parts) continue;
      const [base, full] = parts;
      for (const kind of classifyCode(code)) add(full in E_NAMES || !(base in E_NAMES) ? full : base, codeName(base, full), kind);
    }
    // 2. Trace phosphates by name, then blanked so step 3 does not read their "phosphate".
    PHOSPHATE_TRACE_PHRASES.lastIndex = 0;
    const remaining = text.replace(PHOSPHATE_TRACE_PHRASES, (m0) => { add(null, m0, 'phosphate_trace'); return ' '.repeat(T.cpLength(m0)); });
    // 3. Phosphate words, except phospholipids and phosphatides.
    for (const m of allMatches(PHOSPHATE_WORD, remaining)) {
      let start = m.index;
      while (start > 0 && ALPHA.test(cpBefore(remaining, start))) start -= cpBefore(remaining, start).length; // the whole word
      let wordEnd = m.index + m[0].length;
      while (wordEnd < remaining.length && ALPHA.test(cpAt(remaining, wordEnd))) wordEnd += cpAt(remaining, wordEnd).length;
      let word = remaining.slice(start, wordEnd);
      if (PHOSPHATE_EXCLUDED.some((ex) => word.includes(ex))) continue;
      if (['phosphoric', 'phosphorique', 'fosforico', 'fosfórico'].includes(word)) {
        ACID_AFTER.lastIndex = wordEnd;
        if (ACID_AFTER.test(remaining)) word += ' acid';
      }
      const cation = CATIONS.exec(windowBefore(remaining, start, 40));
      add(null, cation ? `${T.pyStrip(cation[0])} ${word}` : word, 'phosphate');
    }
    // 4. Potassium salts. Aluminium potassium sulphate (E522) is a trace use, not a sulphate salt.
    for (const m of allMatches(K_BULK, remaining)) {
      if (ALUMINIUM_BEFORE.test(remaining.slice(0, m.index))) add('e522', E_NAMES.e522, 'potassium_trace');
      else add(null, m[0], 'potassium');
    }
    for (const m of allMatches(ANION_FIRST_BULK, remaining)) add(null, m[1], 'potassium');
    for (const m of allMatches(OTHER_BULK, remaining)) add(m[1] === 'cream of tartar' ? 'e336' : null, m[1], 'potassium');
    for (const m of allMatches(K_TRACE, remaining)) add(null, m[0], 'potassium_trace');
    for (const m of allMatches(ANION_FIRST_TRACE, remaining)) add(null, m[1], 'potassium_trace');
    for (const _m of allMatches(ACESULFAME, remaining)) add('e950', 'acesulfame K', 'potassium_trace'); // eslint-disable-line no-unused-vars
    return found;
  }

  function cleanTags(tags) {
    const out = [];
    const list = Array.isArray(tags) ? tags.slice(0, MAX_TAGS) : [];
    for (const tag of list) {
      const cleaned = T.cleanLabel(tag, { maxLen: 40 });
      if (cleaned) out.push(T.casefold(cleaned));
    }
    return out;
  }

  const RANK = { potassium: 0, phosphate: 1, potassium_trace: 2, phosphate_trace: 3 };
  // AdditiveResult.additives: E-codes and, for words without a code, the words.
  function additivesOf(findings) {
    const out = [];
    for (const f of findings) {
      if (f.kind !== 'phosphate' && f.kind !== 'potassium') continue;
      const item = f.code || f.name;
      if (!out.includes(item)) out.push(item);
    }
    return out.slice(0, MAX_ADDITIVES);
  }
  // AdditiveResult.notes: flagged additives first; an additive in two tiers gets one note.
  function notesOf(findings) {
    const byLabel = new Map();
    for (const f of findings) {
      const label = f.code ? `${f.name} (${displayCode(f.code)})` : f.name;
      if (!byLabel.has(label)) byLabel.set(label, []);
      const kinds = byLabel.get(label);
      if (!kinds.includes(f.kind)) kinds.push(f.kind);
    }
    const items = [...byLabel.entries()].map((e, i) => [e, i]);
    items.sort((a, b) => (Math.min(...a[0][1].map((k) => RANK[k])) - Math.min(...b[0][1].map((k) => RANK[k]))) || a[1] - b[1]);
    const out = [];
    for (const [[label, kinds]] of items) {
      const bulk = ['potassium', 'phosphate'].filter((k) => kinds.includes(k));
      if (bulk.length) out.push(`Contains ${label}, a ${bulk.join(' and ')} additive.`);
      else if (kinds.includes('potassium_trace')) out.push(`Contains ${label}: a small amount of potassium (no warning).`);
      else out.push(`Contains ${label}: a small amount of phosphate (no warning).`);
    }
    return out;
  }

  // {flags, findings, kidney_notes, additives, notes} as app/additives.py scan() → AdditiveResult.
  function scan(additivesTags, ingredientsText, name) {
    const findings = [];
    for (const tag of cleanTags(additivesTags)) {
      const parts = splitCode(tag);
      if (!parts) continue;
      const [base, full] = parts;
      for (const kind of classifyCode(full)) {
        const code = full in E_NAMES || !(base in E_NAMES) ? full : base;
        findings.push({ code, name: codeName(base, full), kind, source: 'tag' });
      }
    }
    const text = T.cleanText(ingredientsText, { maxLen: MAX_INGREDIENTS_CHARS, keepNewlines: true });
    const lowered = text ? T.casefold(text) : '';
    if (lowered) findings.push(...scanText(lowered));

    const product = T.casefold(T.cleanLabel(name, { maxLen: MAX_NAME_CHARS }) || '');
    let saltSubstitute = !!(product && SALT_SUBSTITUTE_NAME.test(product));
    if (lowered && KCL.test(firstIngredient(lowered))) saltSubstitute = true;
    if (saltSubstitute && !findings.some((f) => f.kind === 'potassium')) {
      findings.push({ code: 'e508', name: 'potassium chloride (a salt substitute)', kind: 'potassium', source: 'name' });
    }
    // One finding per (code or name, kind).
    const unique = [];
    const seen = new Set();
    for (const f of findings) {
      const key = `${f.code || f.name}\u0000${f.kind}`;
      if (!seen.has(key)) { seen.add(key); unique.push(f); }
    }
    const flags = [];
    if (unique.some((f) => f.kind === 'phosphate')) flags.push('phosphate_additive');
    if (unique.some((f) => f.kind === 'potassium')) flags.push('potassium_additive');
    if (saltSubstitute) flags.push('avoid_ckd');
    return { flags, findings: unique, kidney_notes: saltSubstitute ? SALT_SUBSTITUTE_NOTE : null,
      additives: additivesOf(unique), notes: notesOf(unique) };
  }

  KH.additives = { scan, splitCode, classifyCode, displayCode, E_NAMES, NAME_TO_CODE, SALT_SUBSTITUTE_NOTE, MAX_INGREDIENTS_CHARS };
})();
