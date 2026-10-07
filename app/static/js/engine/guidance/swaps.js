/* Kidney Diet Log — meal guidance, part 6 of 9: swap ideas and low-treatment options. Twin of
   app/guidance/swaps.py (note 06 §4.6; note 04 G7).

   A swap keeps the person's arithmetic (the same carbs or protein within a tolerance) and lowers every
   triggering nutrient by at least 25 % without creating a new problem. In "hypo" mode only other low
   treatments are offered, at **at least** the person's low-treatment amount (rounded up, never down):
   nothing here limits, delays or shrinks a treatment. Plain script; needs fits.js. */
(function (root) {
  'use strict';
  const KH = root.KH || (root.KH = {});
  const GE = KH.guidanceEngine;
  const { R, M, T } = GE;
  const B = GE.budget;
  const S = GE.score;
  const F = GE.fits;
  const { roundValue, roundNutrients } = KH.rules;

  const RENAL_SWAP_SCORE = { green: 1.5, yellow: 0.5, red: -1.5 };

  function resolveMode(food, purpose) {
    if (purpose === 'hypo') return 'hypo';
    if (food.avoid) return 'avoid';
    return 'normal';
  }
  const amounts = (f, q) => F.scaled(f, q);

  function triggersFor(food, q, room, mode) {
    const a = amounts(food, q);
    const out = [];
    if (mode === 'hypo') {
      const k = a[R.K];
      if (k != null && k > R.HYPO_SWAP_TRIGGER_MG) out.push({ nutrient: R.K, reasons: ['potassium_in_treatment'], value: roundValue(R.K, k), room: null });
      return out;
    }
    if (mode === 'avoid') return [{ nutrient: 'avoid_ckd', reasons: ['avoid_ckd'], value: null, room: null }];
    for (const key of [R.K, R.P, R.NA, R.FLUID]) {
      const v = a[key];
      const reasons = [];
      if (key !== R.FLUID && R.isHigh(key, v)) reasons.push('high_per_portion');
      if (key === R.P && food.additive) reasons.push('phosphate_additive');
      const item = room.nutrients[key];
      if (item != null && v != null && v > item.room + R.NEGLIGIBLE[key]) reasons.push('over_meal_room');
      if (reasons.length) out.push({ nutrient: key, reasons, value: roundValue(key, v), room: item == null ? null : roundValue(key, item.room) });
    }
    return out;
  }

  function matchDimension(food, q, mode, doseG) {
    const carbs = (food.carbs || 0.0) * q;
    const protein = (food.protein || 0.0) * q;
    if (mode === 'hypo') return ['carbs', Math.max(carbs, Number(doseG))];
    if (carbs >= R.SWAP_MATCH_CARBS_MIN_G) return ['carbs', carbs];
    if (protein >= R.SWAP_MATCH_PROTEIN_MIN_G) return ['protein', protein];
    return ['serving', 1.0];
  }

  function candidatePortion(cand, match, target, mode) {
    if (match === 'serving') return 1.0;
    const per = match === 'carbs' ? cand.carbs : cand.protein;
    if (per == null || per <= 0) return null;
    if (mode === 'hypo') {
      const step = R.hypoPortionStep(cand.serving_desc);
      const q = Math.max(step, R.ceilToStep(target / per, step));
      if (q > R.HYPO_PORTION_MAX || q * per < target - 1e-9) return null; // never under-treat
      return q;
    }
    const q = R.clamp(R.roundToQuarter(target / per), R.PORTION_MIN, R.PORTION_MAX);
    const [tolMin, tolFrac] = match === 'carbs' ? R.SWAP_CARB_MATCH : R.SWAP_PROTEIN_MATCH;
    if (Math.abs(q * per - target) > Math.max(tolMin, tolFrac * target)) return null;
    return q;
  }

  function fitsRoom(a, room) {
    for (const key of Object.keys(room.nutrients)) {
      const v = a[key];
      if (v != null && v > room.nutrients[key].room + R.NEGLIGIBLE[key]) return false;
    }
    return true;
  }

  function eligibleSwap(f, original, ctx, mode) {
    if (f.id === original.id || f.hidden || f.avoid || ctx.prefs.exclude_food_ids.has(f.id)) return false;
    if (ctx.prefs.exclude_categories.has(f.category || '')) return false;
    if (mode === 'hypo') return f.hypo;
    if (f.ingredient || f.alcohol || f.supplies) return false;
    if (f.hypo && !original.beverage) return false;
    if (mode === 'avoid') return f.category === original.category;
    return f.category === original.category || f.role === original.role;
  }

  // Swap ideas for food × servings in meal (ctx.day must not contain the entry itself).
  function findSwaps(ctx, meal, food, servings, purpose = null, limit = R.SWAP_MAX, explain = false) {
    const mode = resolveMode(food, purpose);
    const totals = B.dayTotals(ctx.day);
    const room = B.mealRoom(ctx, meal, null, totals);
    const orig = amounts(food, servings);
    const triggers = triggersFor(food, servings, room, mode);
    const base = {
      status: 'ok', rules_version: R.RULES_VERSION, date: ctx.date, meal, mode,
      food: { food_id: food.id, name: food.name, servings, serving_desc: food.serving_desc, nutrients: roundNutrients(orig) },
      triggers, match: null, swaps: [], portion_option: null, tips: [], widened: false, notes: [M.DISCLAIMER],
    };
    const dose = Number(ctx.prefs.hypo_dose_g);
    if (mode === 'hypo') {
      base.card = M.treatingALowCard(dose);
      base.tips.push(T.tipJson(T.HYPO_TIP, { dose: M.fmtG(dose) }));
    }
    if (!triggers.length) { base.reason = 'no_warning'; return base; }
    const [match, target] = matchDimension(food, servings, mode, dose);
    base.match = match;
    const triggerKeys = triggers.map((t) => t.nutrient).filter((k) => R.ROOM_KEYS.includes(k));
    const pTrigger = triggerKeys.includes(R.P);
    const origHigh = {};
    for (const k of R.RENAL_KEYS) origHigh[k] = R.isHigh(k, orig[k]) || (k === R.P && food.additive);
    const habit = S.habitStats(ctx);
    const today = S.todayStats(ctx.day);
    const weights = { ...R.USAGE_WEIGHT, ...room.usage_weight };
    let found = [];
    const rejected = { not_eligible: 0, no_matching_portion: 0, not_lower: 0, phosphate_additive: 0, new_problem: 0 };
    for (const cand of ctx.foods.values()) {
      if (!eligibleSwap(cand, food, ctx, mode)) { rejected.not_eligible += 1; continue; }
      const q = candidatePortion(cand, match, target, mode);
      if (q == null) { rejected.no_matching_portion += 1; continue; }
      const neu = amounts(cand, q);
      let ok = true;
      let reduction = 0.0;
      for (const key of triggerKeys) {
        const o = orig[key], n = neu[key];
        if (n == null || o == null || o <= 0 || n > (1.0 - R.SWAP_MIN_REDUCTION) * o + 1e-9) { ok = false; break; }
        reduction += (key in weights ? weights[key] : 1.0) * (o - n) / o;
      }
      if (!ok) { rejected.not_lower += 1; continue; }
      if (pTrigger && cand.additive) { rejected.phosphate_additive += 1; continue; }
      if (mode !== 'hypo') {
        for (const key of Object.keys(room.nutrients)) {
          const n = neu[key], o = orig[key];
          if (n != null && n > room.nutrients[key].room + R.NEGLIGIBLE[key] && (o == null || n > o)) { ok = false; break; }
        }
        if (ok) {
          for (const key of R.RENAL_KEYS) {
            if (neu[key] == null && B.levelOf(room, key) !== 'ok') { ok = false; break; }
            const high = R.isHigh(key, neu[key]) || (key === R.P && cand.additive);
            if (high && !origHigh[key]) { ok = false; break; }
          }
        }
        if (!ok) { rejected.new_problem += 1; continue; }
      }
      const level = R.renalLevel(neu[R.K], neu[R.P], neu[R.NA], cand.additive);
      const sameCategory = cand.category === food.category;
      const sameFamily = !!cand.family && cand.family === food.family;
      const fits = fitsRoom(neu, room);
      const carbDiff = Math.abs((neu[R.CARBS] || 0.0) - (orig[R.CARBS] || 0.0));
      let score = (reduction + RENAL_SWAP_SCORE[level] + (sameCategory ? 1.0 : 0.0) + (sameFamily ? 1.0 : 0.0) + (fits ? 1.0 : 0.0)
        + Math.min(1.0, Math.max(0.0, S.staticTerm(cand, habit, today))) - (cand.processed ? 1.0 : 0.0) - 0.1 * carbDiff);
      score = R.roundScore(score);
      const kAmount = neu[R.K] != null ? neu[R.K] : Infinity;
      let key;
      if (mode === 'hypo') {
        const pAmount = neu[R.P] != null ? neu[R.P] : Infinity;
        const fl = R.FLUID in room.nutrients ? (neu[R.FLUID] || 0.0) : 0.0;
        key = [kAmount, pAmount, fl, cand.name_fold, cand.id];
      } else key = [-score, kAmount, cand.name_fold, cand.id];
      found.push([key, [cand, q, neu, sameCategory, fits, score]]);
    }
    found = R.sortBy(found, (pair) => pair[0]);
    const swaps = [];
    for (const [, [cand, q, neu, sameCategory, fits, score]] of found.slice(0, limit)) {
      const item = F.foodCore(cand, q);
      const deltas = {};
      for (const k of [R.CARBS, R.K, R.P, R.NA]) deltas[k] = roundValue(k, (neu[k] || 0.0) - (orig[k] || 0.0));
      let text;
      if (mode === 'hypo') text = M.swapHypoText(cand.name, q, cand.serving_desc, neu[R.CARBS] || 0.0, neu[R.K]);
      else if (mode === 'avoid') text = M.swapAvoidText(cand.name, q, cand.serving_desc, neu, food.name);
      else {
        const d = {};
        for (const k of triggerKeys) d[k] = (neu[k] || 0.0) - (orig[k] || 0.0);
        text = M.swapText(match, cand.name, q, cand.serving_desc, neu, orig, d, triggerKeys);
      }
      Object.assign(item, { same_category: sameCategory, fits_meal: fits, score, deltas, text });
      swaps.push(item);
    }
    base.swaps = swaps;
    base.widened = swaps.some((s) => !s.same_category);
    if (mode === 'normal') {
      base.portion_option = portionOption(food, servings, room, triggers);
      if (pTrigger && food.additive) base.tips.push(T.tipJson(T.ADDITIVES_TIP));
      if (triggerKeys.includes(R.K) && food.category === R.VEGETABLES && R.textHasAny(food.name, R.LEACHING_STEMS)) base.tips.unshift(T.tipJson(T.LEACHING_TIP));
    }
    if (!swaps.length) base.reason = 'no_swap_found';
    if (explain) base.explain = { rejected, passed: found.length };
    return base;
  }

  // A smaller portion of the same food: ¾ when it clears every trigger, else ½ when it fits the room.
  function portionOption(food, servings, room, triggers) {
    if (triggers.some((t) => t.reasons.includes('phosphate_additive'))) return null;
    const keys = triggers.map((t) => t.nutrient).filter((k) => R.ROOM_KEYS.includes(k));
    for (const fraction of R.PORTION_OPTION_FRACTIONS) {
      const q = servings * fraction;
      const a = amounts(food, q);
      if (!fitsRoom(a, room)) continue;
      const clears = keys.every((k) => !(k !== R.FLUID && R.isHigh(k, a[k])));
      if (fraction === 0.75 && !clears) continue;
      const shown = keys.filter((k) => k !== R.FLUID);
      return { servings: q, fraction, fits_meal: true, nutrients: roundNutrients(a),
        text: M.portionOptionText(fraction, a[R.CARBS] || 0.0, a, shown.length ? shown : [R.K]) };
    }
    return null;
  }

  // The person's low-treatment foods at the amount that treats a low, lowest potassium first; never filtered by a budget.
  function hypoOptions(ctx) {
    const dose = Number(ctx.prefs.hypo_dose_g);
    const fluidTracked = R.targetMax(ctx.profile.targets[R.FLUID]) != null;
    let rows = [];
    for (const f of ctx.foods.values()) {
      if (!f.hypo || f.hidden || f.avoid || ctx.prefs.exclude_food_ids.has(f.id)) continue;
      if (ctx.prefs.exclude_categories.has(f.category || '')) continue;
      const q = candidatePortion(f, 'carbs', dose, 'hypo');
      if (q == null) continue;
      const a = amounts(f, q);
      const item = F.foodCore(f, q);
      item.text = M.swapHypoText(f.name, q, f.serving_desc, a[R.CARBS] || 0.0, a[R.K]);
      const k = a[R.K] != null ? a[R.K] : Infinity;
      const p = a[R.P] != null ? a[R.P] : Infinity;
      const fl = fluidTracked ? (a[R.FLUID] || 0.0) : 0.0;
      rows.push([[k, p, fl, f.name_fold, f.id], item]);
    }
    rows = R.sortBy(rows, (pair) => pair[0]);
    return { status: 'ok', rules_version: R.RULES_VERSION, dose_g: roundValue(R.CARBS, dose), options: rows.map((r) => r[1]),
      card: M.treatingALowCard(dose), notes: [M.DISCLAIMER] };
  }

  GE.swaps = { resolveMode, triggersFor, matchDimension, candidatePortion, fitsRoom, eligibleSwap, findSwaps, portionOption, hypoOptions };
})(typeof window !== 'undefined' ? window : globalThis);
