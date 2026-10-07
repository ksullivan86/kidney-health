/* Kidney Diet Log — meal guidance, part 9 of 9: free text that may describe a low is never sent to AI
   (note 04 G7). Twin of app/guidance/hypo.py, plus the engine's public entry points
   (KH.guidanceEngine.whatFits, findSwaps, hypoOptions, planDay, dayInsights, periodInsights, prefilter).

   The classifier errs on the side of showing the "Treating a low" card: a false alarm costs one tap, a
   missed low could cost far more. Food descriptors ("low-fat", "low sodium", "low-carb") are not a low.
   Python's regular expressions are Unicode-aware (\w, \b, \d); the patterns below spell that out with
   \p{...} classes so the browser matches the same text. Plain script; needs insights.js. */
(function (root) {
  'use strict';
  const KH = root.KH || (root.KH = {});
  const GE = KH.guidanceEngine;
  const { R, M } = GE;

  const W = '[\\p{L}\\p{N}_]'; // Python's \w for str patterns
  const B0 = `(?<!${W})`; // \b before a word character
  const B1 = `(?!${W})`; // \b after a word character
  const D = '\\p{Nd}'; // Python's \d for str patterns
  const SP = '[\\t\\n\\v\\f\\r \\x1c-\\x1f\\x85\\xa0\\u1680\\u2000-\\u200a\\u2028\\u2029\\u202f\\u205f\\u3000]'; // Python's \s

  const NW = '[^\\p{L}\\p{N}_]'; // Python's \W for str patterns

  // Includes past tenses and CGM wording ("sugar dropped", "it crashed", "glucose fell", "need sugar fast").
  const TERMS = new RegExp(`${B0}(hypo${W}*|shak(?:y|ey|ing|es)|sweat(?:y|ing)|trembl${W}*|jitter${W}*|dizzy|light[- ]?headed|faint${W}*|`
    + `blurr${W}* vision|pounding heart|racing heart|treat(?:ing)? a low|going low|feel(?:ing)? low|`
    + `i'?m low|i am low|running low|dropp?ed|dropping|crash(?:ed|ing)|tank(?:ed|ing)|plummet${W}*|`
    + `low (?:blood )?(?:sugar|glucose|bg|bs)|`
    + `(?:sugar|glucose|bg|bs|cgm|reading)s? (?:is |are |was |went |getting |dropped )?(?:low|down|dropping)|`
    + `(?:sugar|glucose|bg|bs|cgm|reading|level|number)s? (?:has |have |is |was |just )?(?:fell|fallen|falling)|`
    + `need(?:s|ed)? (?:some |a |fast )?(?:sugar|glucose|carbs?)(?![- ]?free))${B1}`, 'iu');
  const LOW_WORD = new RegExp(`${B0}low${B1}(?![-${SP.slice(1, -1)}]*(?:fat|sodium|salt|sugar|carb${W}*|cal${W}*|potassium|phosph${W}*|fib(?:er|re)|lactose|`
    + `cholesterol|protein|gi|glycemic|glycaemic|in)${B1})`, 'iu');
  // A glucose word, then up to three linking words ("is", "was at", "cgm says", "reading shows", "is now").
  const LEAD = `(?:glucose|sugar|bg|bs|cgm|reading)${SP}*`
    + `(?:(?:is|was|of|at|:|says|said|reads|read|shows|showed|showing|now|just|only)${SP}*){0,3}`;
  // A number followed by a kitchen or energy unit is an amount, not a reading ("sugar 2 tsp", "rice at 50 g").
  const NOT_A_READING = `(?![.,]?${D})(?!${SP}*(?:(?:tsps?|tbsps?|teaspoons?|tablespoons?|spoons?|cubes?|lumps?|packets?|`
    + `sachets?|cups?|slices?|pieces?|servings?|portions?|bowls?|glass(?:es)?|mugs?|cans?|bottles?|g|grams?|`
    + `kg|oz|lbs?|ml|kcal|cal(?:orie)?s?|min(?:ute)?s?|hours?|hrs?|am|pm|o'?clock)${B1}|%))`;
  const LESS_THAN = new RegExp(`${LEAD}(?:<|under|below|less than)`, 'iu');
  const READING = new RegExp(`${LEAD}(${D}{1,3}(?:[.,]${D})?)${NOT_A_READING}`, 'giu');
  // "I'm at 58", "at 3.2", "down to 61": a bare number in the mg/dL low range (30-69) or a decimal mmol/L
  // value; whole numbers under 30 are left out here ("lunch at 1", "at 12") because they read as times.
  const BARE = new RegExp(`${B0}(?:i'?m|i am|at|down to|only)${SP}+(?:about${SP}+|around${SP}+)?(${D}{1,2}(?:[.,]${D})?)${NOT_A_READING}`,
    'giu');
  // A number with a glucose unit: "3.4 mmol" (low at or under 3.9), "61 mg/dL" (under 70) and a whole
  // "30-69 mg" unless a nutrient is named just before or after it ("60 mg sodium", "sodium 60 mg").
  const WITH_UNIT = new RegExp(`(?<![\\p{Nd}.,])(${D}{1,3}(?:[.,]${D})?)${SP}*(?:(mmol)|(mg${SP}*/${SP}*dl)${B1}|mg${B1})`, 'giu');
  const NUTRIENT = `(?:sodium|potassium|phosph${W}*|calcium|caffeine|salt|iron|magnesium|zinc|vitamin${W}*|`
    + 'na|k|p|ca|fe|mg|mcg)';
  const NUTRIENT_AFTER = new RegExp(`${SP}*(?:of${SP}+)?${NUTRIENT}${B1}`, 'iuy');
  const NUTRIENT_BEFORE = new RegExp(`${B0}${NUTRIENT}${NW}*$`, 'iu');

  const MMOL_LOW = 3.9; // level 1 hypoglycaemia (ADA 2026 §6)
  const MGDL_LOW = 70.0;
  const ND = /^\p{Nd}$/u;

  // Python float() of a string of Unicode decimal digits: each Nd run is 0–9 in order (Unicode stability).
  function digitValue(ch) {
    let cp = ch.codePointAt(0);
    let steps = 0;
    while (steps < 2000 && ND.test(String.fromCodePoint(cp - 1))) { cp -= 1; steps += 1; }
    return steps % 10;
  }
  function pyNumber(text) {
    let out = '';
    for (const ch of text) out += ch === '.' || ch === ',' ? '.' : /[0-9]/.test(ch) ? ch : String(digitValue(ch));
    return Number(out);
  }
  function fold(text) {
    let folded = String(text || '').normalize('NFKC');
    folded = folded.replace(/[\p{Cc}\p{Cf}]/gu, (ch) => (ch === '\n' || ch === '\t' ? ch : ''));
    return folded.replace(/\u2019/g, "'").replace(/\u2018/g, "'");
  }
  function isDecimal(raw) {
    return raw.includes('.') || raw.includes(',');
  }
  // A reading after a glucose word: a decimal or a whole number under 30 is mmol/L (low at or under 3.9),
  // 30-69 is mg/dL.
  function isLowReading(raw) {
    const value = pyNumber(raw);
    if ((isDecimal(raw) || value < 30) && value <= MMOL_LOW) return true; // mmol/L
    return value >= 30 && value < MGDL_LOW; // mg/dL
  }
  function nutrientAfter(text, pos) {
    NUTRIENT_AFTER.lastIndex = pos;
    return NUTRIENT_AFTER.test(text);
  }
  function mentionsLow(text) {
    if (!text) return false;
    const folded = fold(text);
    if (TERMS.test(folded) || LOW_WORD.test(folded) || LESS_THAN.test(folded)) return true;
    for (const match of folded.matchAll(READING)) {
      if (isLowReading(match[1])) return true;
    }
    for (const match of folded.matchAll(BARE)) {
      const raw = match[1];
      const value = pyNumber(raw);
      if ((isDecimal(raw) && value <= MMOL_LOW) || (value >= 30 && value < MGDL_LOW)) return true;
    }
    for (const match of folded.matchAll(WITH_UNIT)) {
      const raw = match[1];
      const value = pyNumber(raw);
      let low;
      if (match[2] !== undefined) low = value <= MMOL_LOW;
      else if (match[3] !== undefined) low = value < MGDL_LOW;
      else {
        const end = match.index + match[0].length;
        low = !isDecimal(raw) && value >= 30 && value < MGDL_LOW && !nutrientAfter(folded, end)
          && !NUTRIENT_BEFORE.test(Array.from(folded.slice(0, match.index)).slice(-24).join('')); // 24 code points, as in Python
      }
      if (low) return true;
    }
    return false;
  }
  function prefilter(text, doseG = R.HYPO_DOSE_G) {
    if (!mentionsLow(text)) return null;
    return { status: 'treating_a_low', card: M.treatingALowCard(doseG), ai_called: false };
  }
  GE.hypo = { mentionsLow, prefilter, fold };

  // ---- public entry points (the same functions the API routes call) ------------------------------
  Object.assign(GE, {
    RULES_VERSION: R.RULES_VERSION,
    makeFood: R.makeFood, makeContext: R.makeContext, dayEntry: R.dayEntry, historyEntry: R.historyEntry,
    mealRoom: GE.budget.mealRoom, roomJson: GE.fits.roomJson,
    whatFits: GE.fits.whatFits, findSwaps: GE.swaps.findSwaps, hypoOptions: GE.swaps.hypoOptions, planDay: GE.planner.planDay,
    dayInsights: GE.insights.dayInsights, periodInsights: GE.insights.periodInsights, periodBounds: GE.insights.periodBounds,
    prefilter, mentionsLow,
  });
})(typeof window !== 'undefined' ? window : globalThis);
