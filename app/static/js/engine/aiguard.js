/* Kidney Diet Log — the AI guard's blocklist, for display only (twin of app/ai/guard.py fold + BLOCKLIST).

   The server's guard decides what an AI answer may show: text that names insulin, doses, medicines and the
   like never reaches a card (note 04 G2/G10, V6). Settings → AI activity also lists each call's raw answer
   ("What came back", note 04 R9 step 5), which the guard never filtered because the app did not use it as it
   was. This twin hides the same words in that displayed copy (v0.3.0 review L4); the stored row and the
   person's export keep the full text. tests/test_ai_guard_twin.py checks that the pattern and the look-alike
   table are the server's and runs both on the same texts.

   KH.aiguard = { BLOCKLIST_SOURCE, CONFUSABLES, MASK, fold, blocked, maskForDisplay } */
(() => {
  'use strict';
  const KH = (window.KH = window.KH || {});

  // app/ai/guard.py BLOCKLIST.pattern, verbatim (re.IGNORECASE: the 'i' flag; 'u' for Unicode case folding).
  const BLOCKLIST_SOURCE = [
    String.raw`\b(insulin\w*|bolus\w*|basal|units?|ratios?|corrections?|dos(?:e|es|ed|ing|age)|pumps?|binders?|`,
    String.raw`sevelamer|lanthanum|calcium acetate|patiromer|zirconium|supplements?|diagnos\w*|lab results?|`,
    String.raw`safe to eat|unlimited|as much as|don'?t worry|no need to|inject\w*|shots?|pens?|skip(?:s|ped|ping)?|`,
    String.raw`delay(?:s|ed|ing)?|pills?|capsules?|medicines?|medications?|meds|prescri\w*|renvela|renagel|`,
    String.raw`fosrenol|velphoro|auryxia|phoslo|phoslyra|lokelma|veltassa|kayexalate|xphozah|tenapanor|sucroferric|`,
    String.raw`ferric citrate|(?:eat|have|take|drink|add|use)\s+(?:(?:\d+|an?|one|two|three|four|five|some|`,
    String.raw`another)\s+)?(?:extra|more|double)|(?:\d+|one|two|three|four|five|six)\s+(?:extra|more)|`,
    String.raw`double\s+(?:your|the|it|up)|(?:is|are|it'?s|that'?s)\s+(?:fine|ok(?:ay)?|safe))\b`,
  ].join('');
  // app/ai/guard.py _CONFUSABLES: Latin look-alikes from Cyrillic and Greek.
  const CONFUSABLES = {
    'а': 'a', 'е': 'e', 'о': 'o', 'р': 'p', 'с': 'c', 'у': 'y', 'х': 'x', 'і': 'i', 'ј': 'j', 'ѕ': 's', 'ԁ': 'd', 'ո': 'n',
    'ɡ': 'g', 'ι': 'i', 'ο': 'o', 'ν': 'v', 'κ': 'k', 'τ': 't', 'ρ': 'p', 'α': 'a', 'ε': 'e', 'Ι': 'I', 'Ο': 'O', 'Α': 'A',
    'Ε': 'E', 'Β': 'B', 'Ν': 'N', 'Τ': 'T', 'Ρ': 'P', 'К': 'K', 'М': 'M', 'Н': 'H', 'А': 'A', 'Е': 'E', 'О': 'O', 'Р': 'P',
    'С': 'C', 'Т': 'T', 'Х': 'X', 'В': 'B', 'ı': 'i',
  };
  const MASK = '[hidden]';
  const CONTROL = /[\p{Cc}\p{Cf}\p{Cs}]/gu;
  const LOOKALIKE = new RegExp(`[${Object.keys(CONFUSABLES).join('')}]`, 'gu');

  // guard.fold: NFKC, control and format characters removed, look-alikes folded.
  function fold(text) {
    return String(text || '').normalize('NFKC').replace(CONTROL, '').replace(LOOKALIKE, (ch) => CONFUSABLES[ch]);
  }
  // guard.blocked: the first blocklist term in the folded text (lower case), else null.
  function blocked(text) {
    const m = new RegExp(BLOCKLIST_SOURCE, 'iu').exec(fold(text));
    return m ? m[1].toLowerCase() : null;
  }
  // The copy Settings shows: each line folded (so a zero-width space or a look-alike letter cannot hide a word)
  // and every blocklist match replaced by MASK. Line breaks are kept so a JSON answer stays readable.
  function maskForDisplay(text) {
    const re = new RegExp(BLOCKLIST_SOURCE, 'giu');
    return String(text || '').split(/\r\n|\r|\n/).map((line) => fold(line).replace(re, MASK)).join('\n');
  }

  KH.aiguard = { BLOCKLIST_SOURCE, CONFUSABLES, MASK, fold, blocked, maskForDisplay };
})();
