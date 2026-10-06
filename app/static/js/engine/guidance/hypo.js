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

  const TERMS = new RegExp(`${B0}(hypo${W}*|shak(?:y|ey|ing|es)|sweat(?:y|ing)|trembl${W}*|jitter${W}*|dizzy|light[- ]?headed|faint${W}*|`
    + `blurr${W}* vision|pounding heart|racing heart|treat(?:ing)? a low|going low|feel(?:ing)? low|`
    + `i'?m low|i am low|running low|dropping|crashing|low (?:blood )?(?:sugar|glucose|bg|bs)|`
    + `(?:sugar|glucose|bg|bs|cgm|reading)s? (?:is |are |was |went |getting |dropped )?(?:low|down|dropping))${B1}`, 'iu');
  const LOW_WORD = new RegExp(`${B0}low${B1}(?![-${SP.slice(1, -1)}]*(?:fat|sodium|salt|sugar|carb${W}*|cal${W}*|potassium|phosph${W}*|fib(?:er|re)|lactose|`
    + `cholesterol|protein|gi|glycemic|glycaemic|in)${B1})`, 'iu');
  const LESS_THAN = new RegExp(`(?:glucose|sugar|bg|bs|cgm|reading)${SP}*(?:is|was|of|at|:)?${SP}*(?:<|under|below|less than)`, 'iu');
  const READING = new RegExp(`(?:glucose|sugar|bg|bs|cgm|reading)${SP}*(?:is|was|of|at|:)?${SP}*(${D}{1,3}(?:[.,]${D})?)`, 'giu');

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
  function mentionsLow(text) {
    if (!text) return false;
    const folded = fold(text);
    if (TERMS.test(folded) || LOW_WORD.test(folded) || LESS_THAN.test(folded)) return true;
    READING.lastIndex = 0;
    let match;
    while ((match = READING.exec(folded)) !== null) {
      const raw = match[1];
      const value = pyNumber(raw);
      const decimal = raw.includes('.') || raw.includes(',');
      if ((decimal || value < 30) && value <= MMOL_LOW) return true; // mmol/L
      if (value >= 30 && value < MGDL_LOW) return true; // mg/dL
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
