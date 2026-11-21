/* Kidney Diet Log — the server's AI checks, in the browser, for the iPhone app's own AI (design note 38 §5.6, step 5).

   In device mode (KH.flags.DEVICE) the page runs the demo's in-page API and Apple's on-device model answers instead of a server's
   AI. The model's answer is untrusted, so the page runs the same pure code the server runs on it. Twins (Python is the reference):

   * features.prefilter: text that may describe a low gets the "Treating a low" card, an emergency the "Get help now" card, and a
     question about insulin, medicine or supplement doses, lab results or a diagnosis the "Ask your care team" card. The AI is never
     asked in those cases. The low check is KH.guidanceEngine.prefilter (js/engine/guidance/hypo.js); this file adds the rest:
     red_flag, medicine_question with chat.dose_reason and chat.lab_words.
   * guard.name_policy: a food name or search term the AI wrote is shown only when it is plain text with no link, markup or
     blocklisted word (the blocklist is KH.aiguard's copy of guard.BLOCKLIST).
   * features.serving_quantity and servings_for, and the describe-a-meal judge (prepare_parse_meal's judge).
   * prompts.clean, prompts.data_block's escaped JSON and features.lab_text_lines: exactly the data the server puts in a prompt.
     The iPhone app fills ai-prompts.json's templates with it (scripts/build_preview.py --device).

   Page only (the server has pydantic for this): checkParseMeal and checkLabReport compare the model's answer with
   schemas.ParseMealAnswer and LabReportAnswer. A top level that does not fit is a failed answer; one item or row that does not fit
   is left out and counted.

   Python's regular expressions are Unicode-aware (\w, \b, \d, \s, ".", "$"); pyRe() turns a Python pattern into a JavaScript one that
   matches the same text. tests/data/ai_device_vectors.json pins this file (tests/js/run_vectors.mjs, tests/test_ai_device_vectors.py).
   Plain script, no DOM; needs js/engine/textclean.js and aiguard.js first. */
(() => {
  'use strict';
  const root = typeof window !== 'undefined' ? window : globalThis;
  const KH = root.KH || (root.KH = {});
  const T = KH.textclean;

  // ---------------------------------------------------------------------------
  // Python regular expressions
  // ---------------------------------------------------------------------------
  const W = '\\p{L}\\p{N}_'; // Python's \w for str patterns (inside a class)
  const SYNTAX = '^$\\.*+?()[]{}|/';
  // A Python `re` pattern (str, no inline flags) as a JavaScript RegExp with the 'u' flag. `flags`: 'i' (re.IGNORECASE), 'g'.
  function pyRe(source, flags = '') {
    let out = '';
    let inClass = false;
    for (let i = 0; i < source.length; i += 1) {
      const ch = source[i];
      if (ch === '\\') {
        i += 1;
        const nx = source[i];
        if (nx === 'w') out += inClass ? W : `[${W}]`;
        else if (nx === 'W' && !inClass) out += `[^${W}]`;
        else if (nx === 'd') out += '\\p{Nd}';
        else if (nx === 'D' && !inClass) out += '\\P{Nd}';
        else if (nx === 's') out += inClass ? T.PY_SPACE_CLASS : `[${T.PY_SPACE_CLASS}]`;
        else if (nx === 'S' && !inClass) out += `[^${T.PY_SPACE_CLASS}]`;
        else if (nx === 'b' && !inClass) out += `(?:(?<=[${W}])(?![${W}])|(?<![${W}])(?=[${W}]))`;
        else if ('WDSb'.includes(nx)) throw new Error(`pyRe: \\${nx} inside a class is not supported`);
        else if (/[A-Za-z0-9]/.test(nx)) out += `\\${nx}`; // \n, \t, \x41, \u00e9
        else if (SYNTAX.includes(nx) || (inClass && nx === '-')) out += `\\${nx}`;
        else out += nx; // an escaped character that needs none in JavaScript ("\ ", "\'", "\-" outside a class)
        continue;
      }
      if (inClass) {
        if (ch === ']') inClass = false;
        out += ch;
        continue;
      }
      if (ch === '[') {
        inClass = true;
        out += ch;
        if (source[i + 1] === '^') { out += '^'; i += 1; }
        if (source[i + 1] === ']') { out += '\\]'; i += 1; } // a ] first in a class is a literal in Python
        continue;
      }
      if (ch === '.') out += '[^\\n]';
      else if (ch === '$') out += '(?=\\n?$)'; // the end, or before a newline at the end
      else if (ch === '(' && source.startsWith('(?P<', i)) { out += '(?<'; i += 3; }
      else out += ch;
    }
    return new RegExp(out, `${flags}u`);
  }
  // Python float()/int() of a string of Unicode decimal digits (with an optional "." part): each Nd run is 0–9 in order.
  const ND = /^\p{Nd}$/u;
  function digitValue(ch) {
    let cp = ch.codePointAt(0);
    let steps = 0;
    while (steps < 2000 && ND.test(String.fromCodePoint(cp - 1))) { cp -= 1; steps += 1; }
    return steps % 10;
  }
  function asciiDigits(text) {
    let out = '';
    for (const ch of text) out += /[0-9]/.test(ch) || !ND.test(ch) ? ch : String(digitValue(ch));
    return out;
  }
  function pyFloat(text) {
    const s = asciiDigits(T.pyStrip(String(text)));
    if (!/^[+-]?(?:\d+\.?\d*|\.\d+)$/.test(s)) throw new Error(`could not convert string to float: '${text}'`);
    return Number(s);
  }
  // Python's round() of a float to a whole number: half to even.
  function roundHalfEven(x) {
    const r = Math.round(x);
    return Math.abs(x % 1) === 0.5 ? 2 * Math.round(x / 2) : r;
  }
  function cpLength(text) { return Array.from(text).length; }
  const isDict = (v) => v !== null && typeof v === 'object' && !Array.isArray(v);

  // ---------------------------------------------------------------------------
  // The checks before anything goes to the AI (features.prefilter; G7, G8, G2/G3)
  // ---------------------------------------------------------------------------
  // app/ai/features.py, app/ai/chat.py and app/ai/guard.py patterns, verbatim (tests/test_ai_device_vectors.py compares them).
  const SOURCES = {
    RED_FLAG: String.raw`\b(chest (?:pain|pressure|tight\w*)|palpitations?|heart (?:racing|pounding)|can'?t breathe|cannot breathe|short(?:ness)? of breath|trouble breathing|struggling to breathe|confus\w*|faint\w*|passed out|collaps\w*|muscle weakness|(?:sudden|severe) weakness|seizures?|unconscious|can'?t wake|cannot wake|slurred speech|face droop\w*|stroke)`,
    SUPPLEMENT_AMOUNT: String.raw`\bhow (?:much|many)\b[^.?!]*\b(?:supplements?|vitamins?|capsules?)\b|\b(?:supplements?|vitamins?)\b[^.?!]*\bhow (?:much|many)\b`,
    DIAGNOSE: String.raw`\bdiagnos\w*`,
    INSULIN: String.raw`\b(?:insulin\w*|bolus\w*|basal\w*|inject\w*|syringes?|sliding scale|correction (?:factor|dose|bolus|insulin|ratio)|sensitivity factor|(?:carb(?:ohydrate)?s?|insulin)\s*(?:to|:|/)\s*(?:carb(?:ohydrate)?s?|insulin)|(?:carb(?:ohydrate)?|insulin)s?[- ]ratios?|i:?c ratio|icr|isf)\b`,
    DOSE: String.raw`\b(?:dos(?:e|es|ed|ing|age)|overdos\w*)\b|\b\d+(?:\.\d+)?\s*(?:units|iu)\b`,
    MEDICINE_NAME: String.raw`\b(?:sevelamer|lanthanum|calcium acetate|patiromer|zirconium|renvela|renagel|fosrenol|velphoro|auryxia|phoslo|phoslyra|lokelma|veltassa|kayexalate|xphozah|tenapanor|sucroferric|ferric citrate)\b`,
    SKIP_MEDICINE: String.raw`\b(?:skip|skipp(?:ing|ed)|miss(?:ing|ed)?|delay(?:ing|ed)?|postpon(?:e|ing|ed)|hold(?:ing)? off(?: on)?|put(?:ting)? off|withhold(?:ing)?|forget(?:ting)? to take)\b(?:\W+\w+){0,3}?\W+(?:insulin|medicines?|medications?|meds|binders?|pills?|tablets?|doses?|shots?|injections?|treatment)\b`,
    CHANGE_MEDICINE: String.raw`\b(?:adjust|chang|increas|decreas|reduc|rais|lower|doubl|halv|stop|start|titrat)\w*\s+(?:taking\s+)?(?:your|the)\s+(?:insulin|medicines?|medications?|meds|binders?|pills?|tablets?)\b`,
    LOW_CONTEXT: String.raw`\b(?:hypo\w*|low[- ]blood[- ](?:sugar|glucose)|low[- ]glucose|(?:blood[- ])?(?:sugar|glucose)(?:\s+(?:is|are|was|gets?|goes|go|drops?|falls?|being|running|stays?))*\s+(?:too |very |a bit |really |getting )?low|treat\w*\s+(?:a |an |your |the |that |this )?(?:low|hypo)s?|(?:you|i|they|he|she)(?:'re|\s+are|\s+am|\s+feel|\s+felt|\s+went|\s+go|\s+get)\s+(?:a bit |very |too |really )?low(?!\s+(?:on|in|of)\b))\b`,
    RESTRICT: String.raw`\b(?:avoid\w*|don'?t|do not|doesn'?t|never|skip\w*|delay\w*|wait\w*|hold(?:ing)? off|postpon\w*|instead of|rather than|stay away|not (?:advised|recommended|safe|allowed|ok|okay|wise|a good idea|worth)|too (?:high|much)|limit\w*|careful\w*|caution\w*|no need|only (?:if|after|when)|unless|without|before (?:you |eating|drinking|having|treating)|check with|ask (?:your|the) (?:care|doctor|nurse|team)|first (?:check|ask|call))\b`,
    SENTENCE: String.raw`[^.!?;\n]+`,
    LAB_WORDS: String.raw`\b(?:e?gfr|creatinine|a1c|hba1c|(?:glyc(?:at)?ed )?h(?:a)?emoglobin a1c|blood potassium|serum potassium|lab results?|lab values?|lab tests?|labs|blood tests?|blood work|bloodwork|urine tests?|acr|uacr)\b`,
    URL: String.raw`(https?://|www\.|\b[a-z0-9-]+\.(?:com|net|org|io|ru|cn|xyz|info|biz|app|dev|me)\b)`,
    EMAIL: String.raw`\b[^\s@]+@[^\s@]+\.[a-z]{2,}\b`,
    MARKUP: String.raw`[<>{}\[\]\\` + '`' + String.raw`|]`,
    LEADING: String.raw`^\s*(\d+(?:\.\d+)?|\d+\s*/\s*\d+|½|¼|¾|⅓|⅔)\s*(.*)$`,
  };
  const FLAGS = { SENTENCE: 'g', MARKUP: '', LEADING: '' }; // the rest are re.IGNORECASE
  const RX = Object.fromEntries(Object.entries(SOURCES).map(([name, src]) => [name, pyRe(src, name in FLAGS ? FLAGS[name] : 'i')]));
  const BLOCKLIST = pyRe(KH.aiguard.BLOCKLIST_SOURCE, 'i');

  const RED_FLAG_CARD = {
    title: 'Get help now',
    lines: [
      'Call 911 (or your local emergency number: 112 in the EU, 999 in the UK, 000 in Australia) now for chest '
        + 'pain, sudden breathlessness, fainting or collapse, sudden severe weakness, a seizure, new confusion or '
        + 'someone you cannot wake.',
      'If glucose may be low, treat the low first: potassium never delays treating a low.',
      'For anything else that worries you, call your care team today.',
      'The app\'s AI was not asked: it does not answer questions about symptoms.',
    ],
    handbook: 'get-help-now',
    url: '/learn/get-help-now/',
  };
  const MEDICINE_CARD = {
    title: 'Ask your care team',
    lines: [
      'This app does not answer questions about insulin, medicine or supplement doses, lab results or what a symptom means. '
        + 'The AI was not asked.',
      'Your care team can answer this. To log the meal, describe only the food, for example "two eggs and toast".',
    ],
    handbook: 'medicines/your-medicine-list',
    url: '/learn/medicines/your-medicine-list/',
  };

  const fold = (text) => KH.aiguard.fold(text);
  const matchable = (text) => fold(text).replace(/\u2019/g, "'").replace(/\u2018/g, "'");
  // chat.dose_reason
  function doseReason(text) {
    const folded = matchable(text);
    for (const [code, name] of [['insulin', 'INSULIN'], ['dose', 'DOSE'], ['medicine_name', 'MEDICINE_NAME'],
      ['skip_medicine', 'SKIP_MEDICINE'], ['change_medicine', 'CHANGE_MEDICINE']]) {
      if (RX[name].test(folded)) return code;
    }
    for (const m of folded.matchAll(RX.SENTENCE)) {
      if (RX.LOW_CONTEXT.test(m[0]) && RX.RESTRICT.test(m[0])) return 'low_treatment';
    }
    return null;
  }
  function labWords(text) { return RX.LAB_WORDS.test(fold(text)); }
  // features.medicine_question
  function medicineQuestion(text) {
    if (!text) return null;
    const code = doseReason(text);
    if (code) return code;
    const folded = fold(text);
    if (RX.SUPPLEMENT_AMOUNT.test(folded)) return 'supplement';
    if (labWords(text)) return 'lab';
    if (RX.DIAGNOSE.test(folded)) return 'diagnose';
    return null;
  }
  function redFlag(text) { return !!text && RX.RED_FLAG.test(fold(text || '')); }
  // features.prefilter: the cards to show instead of calling the AI, or null.
  function prefilter(text, doseG) {
    const cards = [];
    if (redFlag(text)) cards.push(JSON.parse(JSON.stringify(RED_FLAG_CARD)));
    const low = KH.guidanceEngine.prefilter(text, doseG);
    if (low) cards.push(low.card);
    if (cards.length) return { status: redFlag(text) ? 'red_flag' : 'treating_a_low', cards, ai_called: false };
    if (medicineQuestion(text)) return { status: 'medicine_question', cards: [JSON.parse(JSON.stringify(MEDICINE_CARD))], ai_called: false };
    return null;
  }

  // ---------------------------------------------------------------------------
  // What the AI wrote: guard.name_policy
  // ---------------------------------------------------------------------------
  // [clean text, null] or [null, reason] with reason empty, url, markup or blocklist:<term>.
  function namePolicy(text, limit = 80) {
    const cleaned = T.cleanText(text, { maxLen: limit });
    if (!cleaned) return [null, 'empty'];
    const folded = fold(cleaned);
    if (RX.URL.test(folded) || RX.EMAIL.test(folded)) return [null, 'url'];
    if (RX.MARKUP.test(folded)) return [null, 'markup'];
    const m = BLOCKLIST.exec(fold(folded));
    if (m) return [null, `blocklist:${m[1].toLowerCase()}`];
    return [T.pyStrip(folded), null];
  }

  // ---------------------------------------------------------------------------
  // Describe a meal: amounts as servings (features.serving_quantity, servings_for)
  // ---------------------------------------------------------------------------
  const UNIT_GRAMS = { g: 1.0, oz: 28.3495 };
  const UNIT_WORDS = {
    cup: ['cup', 'cups'], tbsp: ['tbsp', 'tablespoon', 'tablespoons', 'tbs'], tsp: ['tsp', 'teaspoon', 'teaspoons'],
    slice: ['slice', 'slices'], piece: ['piece', 'pieces', 'medium', 'large', 'small', 'each', 'whole'],
    fl_oz: ['fl oz', 'fl. oz', 'fluid ounce', 'fluid ounces'], ml: ['ml', 'milliliter', 'millilitre'],
  };
  const FRACTIONS = { '½': 0.5, '¼': 0.25, '¾': 0.75, '⅓': 1 / 3, '⅔': 2 / 3 };
  // "1/2 cup (79 g)" -> [0.5, "cup (79 g)"]; null when it does not start with a number.
  function servingQuantity(servingDesc) {
    const m = RX.LEADING.exec(servingDesc || '');
    if (!m) return null;
    const raw = m[1].replace(/ /g, '');
    const rest = m[2].toLowerCase();
    let qty;
    if (Object.prototype.hasOwnProperty.call(FRACTIONS, raw)) qty = FRACTIONS[raw];
    else if (raw.includes('/')) {
      const [num, den] = raw.split('/');
      qty = pyFloat(den) ? pyFloat(num) / pyFloat(den) : 0.0;
    } else qty = pyFloat(raw);
    return qty > 0 ? [qty, rest] : null;
  }
  // Servings of `food` for an amount, only when the food's serving supports the unit.
  function servingsFor(amount, unit, food) {
    if (amount == null || amount <= 0) return null;
    let servings;
    if (unit === 'serving') servings = amount;
    else if (Object.prototype.hasOwnProperty.call(UNIT_GRAMS, unit)) {
      const grams = Number(food.serving_g || 0.0);
      if (grams <= 0) return null;
      servings = (amount * UNIT_GRAMS[unit]) / grams;
    } else if (Object.prototype.hasOwnProperty.call(UNIT_WORDS, unit)) {
      const quantity = servingQuantity(String(food.serving_desc || ''));
      if (quantity === null) return null;
      const [qty, rest] = quantity;
      if (!UNIT_WORDS[unit].some((word) => rest.startsWith(word))) return null;
      servings = amount / qty;
    } else return null;
    if (!(servings >= 0.05 && servings <= 20)) return null;
    return roundHalfEven(servings * 4) / 4 || 0.25;
  }

  // ---------------------------------------------------------------------------
  // The data in a prompt (prompts.clean, prompts.data_block, features.lab_text_lines)
  // ---------------------------------------------------------------------------
  const UNTRUSTED_NAME_CHARS = 80;
  const PARSE_TEXT_CHARS = 300;
  const MAX_LAB_TEXT_CHARS = 20000; // lab_report.MAX_TEXT_CHARS
  function clean(text, limit = UNTRUSTED_NAME_CHARS) { return T.cleanText(text, { maxLen: limit }) || ''; }
  // json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
  function pyJson(value) {
    if (Array.isArray(value)) return `[${value.map(pyJson).join(',')}]`;
    if (isDict(value)) return `{${Object.keys(value).sort().map((k) => `${JSON.stringify(k)}:${pyJson(value[k])}`).join(',')}}`;
    return JSON.stringify(value);
  }
  // prompts.escape_data: "<", ">" and "&" as JSON escapes, so the data block cannot be closed from inside.
  function escapeData(text) { return text.replace(/&/g, '\\u0026').replace(/</g, '\\u003c').replace(/>/g, '\\u003e'); }
  // What goes between "<data>\n" and "\n</data>" (the iPhone app puts it where ai-prompts.json's template says {text}).
  function dataPayload(data) { return escapeData(pyJson(data)); }
  // Python's str.splitlines()
  const LINE_SPLIT = /\r\n|[\n\r\v\f\x1c\x1d\x1e\x85\u2028\u2029]/;
  function labTextLines(text) {
    const lines = [];
    const parts = String(text).split(LINE_SPLIT);
    if (parts.length && parts[parts.length - 1] === '') parts.pop(); // splitlines() gives no empty last line
    for (const raw of parts) {
      const line = T.cleanText(raw, { maxLen: MAX_LAB_TEXT_CHARS });
      if (line) lines.push(line);
    }
    return lines;
  }
  const parseMealData = (text) => ({ text: clean(text, PARSE_TEXT_CHARS) });

  // ---------------------------------------------------------------------------
  // The model's answer (schemas.ParseMealAnswer, LabReportAnswer) and the describe-a-meal judge
  // ---------------------------------------------------------------------------
  const UNITS = ['serving', 'g', 'ml', 'cup', 'tbsp', 'tsp', 'slice', 'piece', 'oz', 'fl_oz', 'none'];
  const MAX_PARSE_ITEMS = 8;
  const MAX_TEXT_CHARS = 300; // schemas.MAX_TEXT_CHARS
  const MAX_NAME_CHARS = 80;
  const MAX_LAB_ROWS = 60;
  const MAX_LAB_TEXT = 120;
  const sameKeys = (o, keys) => isDict(o) && Object.keys(o).length === keys.length && keys.every((k) => Object.prototype.hasOwnProperty.call(o, k));
  const isNumber = (v) => typeof v === 'number' && Number.isFinite(v);
  const shortText = (v, max) => typeof v === 'string' && cpLength(v) <= max;

  // { ok: true, answer: {status, items}, malformed: [index...] } or { ok: false } when the answer's shape does not fit.
  function checkParseMeal(raw) {
    if (!sameKeys(raw, ['status', 'items']) || !['ok', 'refused'].includes(raw.status) || !Array.isArray(raw.items)
      || raw.items.length > MAX_PARSE_ITEMS) return { ok: false };
    const malformed = [];
    raw.items.forEach((it, index) => {
      const good = sameKeys(it, ['text', 'search', 'amount', 'unit']) && shortText(it.text, MAX_TEXT_CHARS) && shortText(it.search, MAX_TEXT_CHARS)
        && (it.amount === null || (isNumber(it.amount) && it.amount >= 0 && it.amount <= 1000000)) && UNITS.includes(it.unit);
      if (!good) malformed.push(index);
    });
    return { ok: true, answer: { status: raw.status, items: raw.items }, malformed };
  }
  // { ok: true, answer: {status, rows}, malformed: n } or { ok: false }.
  function checkLabReport(raw) {
    if (!sameKeys(raw, ['status', 'rows']) || !['ok', 'not_a_lab_report', 'unreadable'].includes(raw.status) || !Array.isArray(raw.rows)
      || raw.rows.length > MAX_LAB_ROWS) return { ok: false };
    const rows = raw.rows.filter((r) => sameKeys(r, ['analyte', 'value', 'unit', 'taken_on']) && shortText(r.analyte, MAX_LAB_TEXT)
      && isNumber(r.value) && shortText(r.unit, MAX_LAB_TEXT) && (r.taken_on === null || shortText(r.taken_on, MAX_LAB_TEXT)));
    return { ok: true, answer: { status: raw.status, rows }, malformed: raw.rows.length - rows.length };
  }

  const PROMPT_VERSION = '2026-11-12.1'; // prompts.PROMPT_VERSION: the prompts in ai-prompts.json and the checks in this file
  const REFUSED_TEXT = 'This is outside what the app\'s AI helps with. Your care team can answer it.'; // guard.REFUSED_TEXT
  const PARSE_NOTICE = 'AI split your text into foods; pick the right match for each one. Nothing is logged until you add it.';
  // prepare_parse_meal's judge. `search(query)` is the person's own food search; `malformed` the indexes checkParseMeal left out.
  function judgeParseMeal(answer, search, malformed = []) {
    if (answer.status === 'refused') return { status: 'refused', message: REFUSED_TEXT, items: [], dropped: [] };
    const items = [], dropped = [];
    answer.items.forEach((item, index) => {
      if (malformed.includes(index)) { dropped.push({ index, reason: 'malformed_item' }); return; }
      const [labelText, why] = namePolicy(item.text, MAX_NAME_CHARS);
      const [query, why2] = namePolicy(item.search, MAX_NAME_CHARS);
      if (labelText === null || query === null) { dropped.push({ index, reason: `text_policy:${why || why2}` }); return; }
      const matches = search(query).slice(0, 3).map((food) => ({ food, servings: servingsFor(item.amount, item.unit, food) }));
      items.push({ text: labelText, search: query, amount: item.amount, unit: item.unit, matches });
    });
    return { status: 'ok', items, dropped, notice: PARSE_NOTICE };
  }

  KH.aiJudge = {
    pyRe, pyFloat, asciiDigits, roundHalfEven, SOURCES, RED_FLAG_CARD, MEDICINE_CARD, doseReason, labWords, medicineQuestion, redFlag, prefilter,
    namePolicy, servingQuantity, servingsFor, clean, pyJson, escapeData, dataPayload, labTextLines, parseMealData,
    UNITS, PARSE_TEXT_CHARS, MAX_LAB_TEXT_CHARS, MAX_PARSE_ITEMS, MAX_LAB_ROWS, PROMPT_VERSION, checkParseMeal, checkLabReport, judgeParseMeal, REFUSED_TEXT, PARSE_NOTICE,
  };
})();
