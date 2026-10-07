/* Kidney Diet Log — meal guidance, part 2 of 9: every user-facing sentence and the number and portion
   formatting they use, plus the handbook topics and the tips table. The browser twin of
   app/guidance/messages.py and app/guidance/topics.py (note 06 §4.9, §4.15; note 08 §4.10).

   Wording rules (F6; note 04 G2/G3): plain English, active voice, nutrient names spelled out, whole
   numbers (mg and mL as integers with thousands separators, grams to one decimal below 10 g), every
   qualitative word with its number; never "safe", insulin, doses, medicines or lab values. Change the
   texts in the Python modules first (tests/guidance/test_messages.py lints them), regenerate the
   vectors, then copy them here. Plain script; needs js/engine/rules.js and guidance/rules.js. */
(function (root) {
  'use strict';
  const KH = root.KH || (root.KH = {});
  const GE = KH.guidanceEngine;
  const R = GE.R;
  const { NUT, halfUp } = KH.rules;

  const DISCLAIMER = 'Suggestions compare foods with the targets your care team set. They are not medical advice.';
  const AI_FALLBACK = "The AI ideas did not fit your targets today, so these are the app's own.";
  const NO_TARGETS = 'Set your targets in Profile first; guidance compares foods with the targets your care team gave you.';
  const DISABLED = 'Meal guidance is switched off on this server.';
  const NEEDS_CONNECTION = 'Guidance needs a connection to your server.';

  const GLYPH = { 0: '', 1: '¼', 2: '½', 3: '¾' };
  const FRACTION_WORD = new Map([[0.75, 'Three-quarter'], [0.5, 'Half'], [0.25, 'Quarter']]);
  const SIZE_WORD = new Map([[1.0, 'full'], [0.75, 'three-quarter'], [0.5, 'half']]);
  const NUTRIENT_WORD = { potassium_mg: 'potassium', phosphorus_mg: 'phosphorus', sodium_mg: 'sodium', fluid_ml: 'fluid',
    carbs_g: 'carbs', protein_g: 'protein', calories_kcal: 'calories' };
  function unitOf(key) { return NUT[key] ? NUT[key].unit : 'g'; }

  // ---- numbers -----------------------------------------------------------------------------------
  function whole(value) {
    const r = halfUp(Number(value), 0);
    return r === 0 ? 0 : r; // int(): no negative zero
  }
  function commas(n) {
    const neg = n < 0;
    const digits = String(Math.abs(n));
    return (neg ? '-' : '') + digits.replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  }
  function fmtInt(value) { return value == null ? '?' : commas(whole(value)); }
  function fmtG(value) {
    if (value == null) return '?';
    const one = halfUp(Number(value), 1);
    if (Math.abs(one) < 10) {
      const text = (one < 0 || Object.is(one, -0) ? '-' : '') + Math.abs(one).toFixed(1);
      return text.endsWith('.0') ? text.slice(0, -2) : text;
    }
    return commas(whole(value));
  }
  function fmtAmount(key, value) { return unitOf(key) === 'g' ? fmtG(value) : fmtInt(value); }
  function withUnit(key, value) { return `${fmtAmount(key, value)} ${NUT[key].unit}`; }
  function pct(fraction) { return whole(fraction * 100.0); }
  function joinAnd(parts) {
    const p = parts.filter((x) => x);
    if (!p.length) return '';
    if (p.length === 1) return p[0];
    return `${p.slice(0, -1).join(', ')} and ${p[p.length - 1]}`;
  }
  function capitalise(text) {
    if (!text) return text;
    const first = String.fromCodePoint(text.codePointAt(0));
    return first.toUpperCase() + text.slice(first.length);
  }

  // ---- portions ----------------------------------------------------------------------------------
  function fmtServings(servings) {
    const quarters = servings * 4.0;
    const q = R.jsRound(quarters);
    if (Math.abs(quarters - q) < 1e-9 && q > 0) {
      const wholePart = Math.floor(q / 4), rest = q % 4;
      const head = wholePart ? String(wholePart) : '';
      return (head + GLYPH[rest]) || '0';
    }
    let text = R.roundTo(servings, 2).toFixed(2);
    text = text.replace(/0+$/, '').replace(/\.$/, '');
    return text;
  }
  function shortServing(servingDesc) {
    const s = String(servingDesc || '');
    const short = s.replace(/\s*\([^()]*\)\s*$/u, '').trim();
    return short || s.trim();
  }
  function portionText(servings, servingDesc) { return `${fmtServings(servings)} × ${servingDesc}`; }
  function portionShort(servings, servingDesc) { return `${fmtServings(servings)} × ${shortServing(servingDesc)}`; }
  function fractionWord(fraction) { return FRACTION_WORD.has(fraction) ? FRACTION_WORD.get(fraction) : fmtServings(fraction); }
  function sizeWord(scale) { return SIZE_WORD.has(scale) ? SIZE_WORD.get(scale) : fmtServings(scale); }
  // Python's str.split() whitespace (no U+FEFF, but the C0 separators and U+0085).
  const PY_SPACE = /[\t\n\v\f\r \x1c-\x1f\x85\xa0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+/u;
  function safeName(name) {
    let text = String(name == null ? '' : name).split(PY_SPACE).filter((w) => w).join(' ');
    const chars = Array.from(text);
    if (chars.length > R.MAX_NAME_CHARS) text = `${chars.slice(0, R.MAX_NAME_CHARS - 1).join('').replace(/[\t\n\v\f\r \x1c-\x1f\x85\xa0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+$/u, '')}\u2026`;
    return text || 'this food';
  }

  // ---- what fits now -----------------------------------------------------------------------------
  function fitText(amounts, tracked, carbsFirst) {
    const parts = [];
    if (carbsFirst) parts.push(`${fmtG(amounts[R.CARBS] || 0.0)} g carbs`);
    for (const key of [R.K, R.P, R.NA, R.FLUID]) {
      if (!tracked.includes(key)) continue;
      const value = amounts[key];
      const label = NUTRIENT_WORD[key];
      parts.push(value != null ? `${fmtAmount(key, value)} ${NUT[key].unit} ${label}` : `${label} not listed`);
    }
    return parts.length ? `Fits: ${parts.join(' · ')}` : 'Fits your targets for this meal';
  }
  const REASONS = {
    adds_missing_group: (v) => `Adds the ${v.group} this ${v.meal} is missing`,
    fills_carbs: (v) => `Brings ${v.meal} to ${v.after} of your ${v.goal} g carbs`,
    low_potassium: (v) => `Low in potassium (${v.k} mg)`,
    low_phosphorus: (v) => `Low in phosphorus (${v.p} mg)`,
    protein_quality: (v) => `${v.protein} g protein with little phosphorus (${v.ratio} mg per g)`,
    you_eat_often: () => 'You often have this',
    free_food: (v) => `Almost no carbs (${v.carbs} g)`,
    half_portion: (v) => `A half portion fits; a full one would use more ${v.nutrient} than is left for ${v.meal}`,
    unknown: (v) => `${v.Nutrient} is not listed for this food; check the label`,
  };
  function reasonText(code, values = {}) { return REASONS[code](values); }
  function roomLine(meal, room) {
    const parts = [];
    for (const key of [R.K, R.P, R.NA, R.FLUID]) {
      const item = room[key];
      if (R.isDict(item)) parts.push(`${fmtAmount(key, Number(item.room))} ${NUT[key].unit} ${NUTRIENT_WORD[key]}`);
    }
    const carbs = room[R.CARBS];
    if (R.isDict(carbs)) {
      const gap = Number(carbs.gap), goal = Number(carbs.goal);
      if (gap > 0) parts.push(`${fmtG(gap)} g carbs to reach ${fmtG(goal)} g`);
      else parts.push(`carbs at your ${fmtG(goal)} g goal`);
    }
    return parts.length ? `Left for ${meal}: ${parts.join(' · ')}` : `No targets limit ${meal}`;
  }
  function noFitText(meal, key, room, closest = '') {
    const unit = unitOf(key);
    const text = `Nothing in your foods fits ${meal} within today's ${NUTRIENT_WORD[key] || key} room (${fmtAmount(key, room)} ${unit} left).`;
    return `${text} ${closest}`.trim();
  }
  function savedMealNote(scale, carbs, gap, goal, meal, limiting) {
    const head = `Fits at ${sizeWord(scale)} size`;
    let detail;
    if (goal != null) {
      const diff = carbs - gap;
      if (Math.abs(diff) < 0.05) detail = `${fmtG(carbs)} g carbs, at your ${fmtG(goal)} g goal`;
      else detail = `${fmtG(carbs)} g carbs, ${fmtG(Math.abs(diff))} g ${diff < 0 ? 'under' : 'over'} your ${fmtG(goal)} g goal`;
    } else detail = `${fmtG(carbs)} g carbs`;
    let text = `${head} (${detail})`;
    if (limiting != null && scale < 1.0) {
      const [key, room, basis] = limiting;
      const period = basis === 'week_average' ? "this week's" : "today's";
      text += `: ${period} ${NUTRIENT_WORD[key]} leaves ${withUnit(key, room)} for ${meal}`;
    }
    return `${text}.`;
  }

  // ---- swaps -------------------------------------------------------------------------------------
  function lessList(deltas, keys) {
    const out = [];
    for (const key of keys) {
      const d = deltas[key];
      if (d == null) continue;
      out.push(`${fmtAmount(key, Math.abs(d))} ${NUT[key].unit} ${d <= 0 ? 'less' : 'more'} ${NUTRIENT_WORD[key]}`);
    }
    return out;
  }
  function swapText(match, name, servings, servingDesc, neu, old, deltas, triggerKeys) {
    const head = `${safeName(name)} (${portionShort(servings, servingDesc)})`;
    const less = joinAnd(lessList(deltas, triggerKeys));
    if (match === 'carbs') return `${head}: about the same carbs (${fmtG(neu[R.CARBS] || 0.0)} g vs ${fmtG(old[R.CARBS] || 0.0)} g)${less ? ` and ${less}` : ''}`;
    if (match === 'protein') return `${head}: about the same protein (${fmtG(neu[R.PROTEIN] || 0.0)} g vs ${fmtG(old[R.PROTEIN] || 0.0)} g)${less ? `, ${less}` : ''}`;
    return less ? `${head}: ${less}` : head;
  }
  function swapAvoidText(name, servings, servingDesc, neu, original) {
    return `${safeName(name)} (${portionShort(servings, servingDesc)}): ${fmtG(neu[R.CARBS] || 0.0)} g carbs and `
      + `${fmtAmount(R.K, neu[R.K])} mg potassium, without the warning that ${safeName(original)} has`;
  }
  function swapHypoText(name, servings, servingDesc, carbs, k) {
    return `For your next low: ${safeName(name)} (${portionShort(servings, servingDesc)}) gives ${fmtG(carbs)} g carbs `
      + `with ${fmtAmount(R.K, k)} mg potassium`;
  }
  function portionOptionText(fraction, carbs, amounts, keys) {
    const parts = [`${fmtG(carbs)} g carbs`, ...keys.map((k) => `${fmtAmount(k, amounts[k])} ${NUT[k].unit} ${NUTRIENT_WORD[k]}`)];
    return `${fractionWord(fraction)} portion: ${joinAnd(parts)}. The carbs change, so count the new amount.`;
  }

  // ---- plan --------------------------------------------------------------------------------------
  function planWhyCarbs(carbs, goal, meal, gap, tolerance) {
    const left = gap;
    let goalText = `your ${fmtG(goal)} g ${meal} goal`;
    if (left <= 0) return `${fmtG(carbs)} g carbs: ${goalText} is already reached`;
    if (Math.abs(left - goal) >= 0.05) goalText = `the ${fmtG(left)} g left of ${goalText}`;
    const diff = carbs - left;
    if (Math.abs(diff) <= tolerance + 1e-9) return `${fmtG(carbs)} g carbs, close to ${goalText}`;
    return `${fmtG(carbs)} g carbs, ${fmtG(Math.abs(diff))} g ${diff < 0 ? 'under' : 'over'} ${goalText}`;
  }
  function planWhyRoom(used, room, meal, key = R.K) {
    return `Uses ${fmtAmount(key, used)} of the ${fmtAmount(key, room)} ${NUT[key].unit} ${NUTRIENT_WORD[key]} left for ${meal}`;
  }
  function usualMealName(meal, shortNames) { return `Your usual ${meal}: ${joinAnd([...shortNames])}`; }
  function energyNoteText(kcal, goal) {
    return `This plan has about ${fmtInt(kcal)} kcal of your ${fmtInt(goal)} kcal goal. Close the gap with fat, such `
      + 'as olive oil or unsalted butter on food, or a measured extra starch, not with more meat, which adds '
      + 'protein and phosphorus.';
  }
  function partialText(meal, key) {
    return `This ${meal} plan was cut back, but today's ${NUTRIENT_WORD[key]} would still go over your limit; `
      + 'choose a smaller portion or a different food.';
  }

  // ---- treating a low (note 04 G7; handbook t1d/treating-a-low) -----------------------------------
  function treatingALowCard(doseG) {
    const dose = fmtG(Number(doseG));
    return {
      title: 'Treating a low',
      lines: [
        `If your glucose is below 70 mg/dL (3.9 mmol/L), take ${dose} g of fast carbs now. Glucose tablets are `
          + 'the best choice on a kidney diet; potassium never delays treating a low.',
        `Check again in 15 minutes. If you are still below 70 mg/dL, take another ${dose} g.`,
        'Skip chocolate, milk or peanut butter for the first treatment: fat slows the rise in glucose, and '
          + 'protein does not raise it.',
        'If someone cannot swallow safely, do not give food or drink: use their emergency glucagon if they '
          + 'have it and call your emergency number.',
        'Log the treatment afterwards and tick "Used to treat a low". It counts toward potassium, but never '
          + 'toward your meal carbs.',
      ],
      handbook: 'treating-a-low',
      url: '/learn/t1d/treating-a-low/',
    };
  }

  // ---- topics.py: handbook pages and tips ---------------------------------------------------------
  const LEARN_PREFIX = '/learn/';
  const PAGES = [
    ['potassium', 'eat/potassium', 'Potassium'],
    ['potassium-leaching', 'eat/potassium-leaching', 'Potassium leaching'],
    ['phosphorus', 'eat/phosphorus', 'Phosphorus'],
    ['phosphate-additives', 'eat/phosphate-additives', 'Phosphate additives'],
    ['sodium', 'eat/sodium', 'Sodium'],
    ['fluid', 'eat/fluid', 'Fluid'],
    ['protein', 'eat/protein', 'Protein'],
    ['eating-enough', 'eat/eating-enough', 'Eating enough'],
    ['carb-counting', 'eat/carb-counting', 'Carb counting on a kidney diet'],
    ['treating-a-low', 't1d/treating-a-low', 'Treating a low'],
    ['dialysis-days', 'eat/dialysis-days', 'Dialysis days'],
    ['label-reading', 'eat/label-reading', 'Reading food labels'],
    ['eating-out', 'eat/eating-out', 'Eating out'],
    ['portions', 'eat/portions', 'Portions'],
    ['sick-days', 't1d/sick-days', 'Sick days with type 1 diabetes and CKD'],
    ['get-help-now', 'get-help-now', 'Get help now'],
    ['blood-potassium', 'labs/blood-potassium', 'Blood potassium'],
    ['targets-and-warnings', 'app/targets-and-warnings', 'Targets and warnings'],
    ['guidance', 'app/guidance', 'Meal guidance'],
  ];
  const TOPIC_PAGES = Object.fromEntries(PAGES.map(([slug, path, title]) => [slug, { slug, title, url: `${LEARN_PREFIX}${path}/` }]));
  const NUTRIENT_TOPIC = { potassium_mg: 'potassium', phosphorus_mg: 'phosphorus', sodium_mg: 'sodium', fluid_ml: 'fluid',
    protein_g: 'protein', carbs_g: 'carb-counting', calories_kcal: 'eating-enough' };
  function page(slug) {
    const p = TOPIC_PAGES[slug];
    if (!p) throw new Error(`unknown handbook topic ${slug}`);
    return { ...p };
  }
  function pages(...slugs) { return slugs.map(page); }
  function tip(code, when, slug, text) { return { code, when, slug, text }; }
  const TIPS = [
    tip('potassium_leaching', 'potassium_not_ok', 'potassium-leaching',
      "Potassium is at {pct} % of today's limit. Peeling, cutting small and boiling potatoes, sweet potatoes, "
      + 'carrots, beets or winter squash in plenty of water removes about half of their potassium.'),
    tip('phosphate_additives', 'phosphorus_week_not_ok', 'phosphate-additives',
      "This week's phosphorus is at {pct} % of your allowance. Phosphate additives (look for \"phos\" in the "
      + 'ingredient list) are almost fully absorbed, so foods without them help most.'),
    tip('hidden_sodium', 'sodium_caution', 'sodium',
      "Sodium is at {pct} % of today's limit. Most sodium comes from packaged and restaurant food, not the salt "
      + 'shaker; herbs, spices, lemon and vinegar add flavour without it.'),
    tip('fluid_dialysis', 'fluid_caution_dialysis', 'fluid',
      "Fluid is at {pct} % of today's allowance. Soup, ice, ice cream, sherbet and gelatin count as fluid too; "
      + 'drinking from a small cup and sipping slowly helps.'),
    tip('add_protein', 'dialysis_protein_low', 'protein',
      'Protein so far is {value} g of your {min} g minimum. On dialysis your body needs more protein, so add a '
      + 'protein portion such as egg, chicken or fish.'),
    tip('free_foods', 'meal_carbs_done', 'carb-counting',
      '{Meal} already has {carbs} g of your {goal} g carbs. Foods with 5 g of carbs or less, such as green beans, '
      + 'cucumber or lettuce, add almost nothing.'),
  ];
  const LEACHING_TIP = tip('leaching', 'swap_leaching_vegetable', 'potassium-leaching',
    'Peeling, cutting small and boiling in plenty of water removes about half of the potassium from potatoes, sweet '
    + 'potatoes, yams, carrots, beets and winter squash; baking, roasting and frying remove none.');
  const ADDITIVES_TIP = tip('additives', 'swap_phosphate_additive', 'phosphate-additives',
    'This food has phosphate additives, which are almost fully absorbed. A smaller portion does not change that; '
    + 'a food without "phos" in its ingredient list does.');
  const HYPO_TIP = tip('treating_a_low', 'swap_hypo', 'treating-a-low',
    'Treat a low first with {dose} g of fast carbs; potassium never delays treatment. These ideas are for choosing '
    + 'what to keep at hand next time.');
  const ALL_TIPS = [...TIPS, LEACHING_TIP, ADDITIVES_TIP, HYPO_TIP];
  // str.format(**values) for the {name} placeholders the tips use.
  function format(template, values) {
    return template.replace(/\{(\w+)\}/g, (m, name) => {
      if (!(name in values)) throw new Error(`missing value ${name} for ${template}`);
      return String(values[name]);
    });
  }
  function tipJson(t, values = {}) {
    return { code: t.code, text: format(t.text, values), handbook: t.slug, url: TOPIC_PAGES[t.slug].url };
  }

  GE.M = {
    DISCLAIMER, AI_FALLBACK, NO_TARGETS, DISABLED, NEEDS_CONNECTION, NUTRIENT_WORD,
    whole, fmtInt, fmtG, fmtAmount, withUnit, pct, joinAnd, capitalise, fmtServings, shortServing, portionText, portionShort,
    fractionWord, sizeWord, safeName, fitText, reasonText, roomLine, noFitText, savedMealNote, swapText, swapAvoidText,
    swapHypoText, portionOptionText, planWhyCarbs, planWhyRoom, usualMealName, energyNoteText, partialText, treatingALowCard,
  };
  GE.T = { LEARN_PREFIX, TOPIC_PAGES, NUTRIENT_TOPIC, TIPS, LEACHING_TIP, ADDITIVES_TIP, HYPO_TIP, ALL_TIPS, page, pages, tipJson, format };
})(typeof window !== 'undefined' ? window : globalThis);
