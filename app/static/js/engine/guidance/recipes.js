/* Kidney Diet Log — meal guidance, part 10 of 10: recipes that fit. Twin of app/guidance/recipes.py (note 16 §9).

   One serving of a recipe is checked against a meal's room or what is left today. If it does not fit: lower amounts (never a
   protein food or a low treatment, never below RECIPE_FLOOR of the recipe's own amount), then swap a food (at most
   RECIPE_MAX_SWAPS, never a low treatment in or out), then a smaller serving, and stop at the first that fits. Every change is
   listed. Pure; every sort ends in the food id. Plain script; needs hypo.js (the public entry points). */
(function (root) {
  'use strict';
  const KH = root.KH || (root.KH = {});
  const GE = KH.guidanceEngine;
  const { R, M } = GE;
  const B = GE.budget;
  const S = GE.score;
  const F = GE.fits;
  const SW = GE.swaps;
  const { roundValue } = KH.rules;

  const SHOWN_KEYS = [R.K, R.P, R.NA, R.FLUID, R.CARBS, R.PROTEIN, R.KCAL];
  const LOWERABLE = ['would_exceed', 'high_warning', 'too_many_carbs', 'high_portion_too_large', 'portion_out_of_range'];

  function item(food, amount, swappedFrom = null) {
    return { food, amount, original: amount, swapped_from: swappedFrom, because: null };
  }
  const floorOf = (it) => Math.max(R.PORTION_MIN, R.ceilToStep(R.RECIPE_FLOOR * it.original, R.REPAIR_STEP));

  function nextOpenMeal(ctx) {
    const used = new Set(ctx.day.map((e) => e.meal));
    for (const meal of R.MAIN_MEALS) if (!used.has(meal)) return meal;
    return R.SNACK;
  }

  function dayRoom(ctx) {
    const last = R.MAIN_MEALS[R.MAIN_MEALS.length - 1];
    const base = B.mealRoom(ctx, last, [last]);
    const nutrients = {};
    for (const [key, it] of Object.entries(base.nutrients)) {
      const left = Math.max(0.0, it.remaining);
      nutrients[key] = { ...it, share: left, cap: Infinity, in_meal: 0.0, room: left };
    }
    return { ...base, meal: 'day', open_meals: [], nutrients, carbs: null };
  }

  function roomFor(ctx, target) {
    if (target.kind === 'day') return dayRoom(ctx);
    const meal = target.meal || nextOpenMeal(ctx);
    return B.mealRoom(ctx, meal, B.openSlots(meal, ctx.day));
  }

  const shares = (items, n, fraction = 1.0) => items.map((it) => [it.food, it.amount / n * fraction]);
  const check = (items, n, room, fraction = 1.0) => S.checkMeal(shares(items, n, fraction), room, 'recipe');

  function value(f, key) {
    return { [R.K]: f.k, [R.P]: f.p, [R.NA]: f.na, [R.FLUID]: f.fluid, [R.CARBS]: f.carbs, [R.PROTEIN]: f.protein, [R.KCAL]: f.kcal }[key];
  }

  function figures(items, n, room, fraction = 1.0) {
    const part = shares(items, n, fraction);
    const [totals] = S.mealTotals(part);
    const unknown = {};
    for (const [f] of part) for (const key of SHOWN_KEYS) if (value(f, key) == null) unknown[key] = (unknown[key] || 0) + 1;
    const per = {};
    for (const key of SHOWN_KEYS) per[key] = part.length && (unknown[key] || 0) >= part.length ? null : roundValue(key, totals[key]);
    const checks = [];
    for (const key of F.trackedKeys(room)) {
      const it = room.nutrients[key];
      const limit = Math.min(it.room + R.NEGLIGIBLE[key], key in room.day_left ? room.day_left[key] : Infinity);
      const used = totals[key];
      checks.push({ nutrient: key, used: roundValue(key, used), room: roundValue(key, it.room), ok: used <= limit + 1e-9 });
    }
    if (room.carbs != null) {
      const allowed = Math.max(room.carbs.gap, 0.0) + room.carbs.tolerance;
      const carbs = totals[R.CARBS];
      checks.push({ nutrient: R.CARBS, used: roundValue(R.CARBS, carbs), room: roundValue(R.CARBS, allowed), ok: carbs <= 5.0 || carbs <= allowed + 1e-9 });
    }
    const sortedUnknown = Object.fromEntries(Object.keys(unknown).sort().map((k) => [k, unknown[k]]));
    return { per_serving: per, unknown: sortedUnknown, checks };
  }

  function reasonKey(reason) {
    if (reason == null || !reason.includes(':')) return reason === 'too_many_carbs' ? R.CARBS : null;
    return reason.split(':', 2)[1];
  }
  function swapBecause(reason) {
    if (reason === 'avoid_ckd' || reason.startsWith('unknown:')) return reason.split(':')[0];
    return reasonKey(reason) || 'portion';
  }
  function highShare(f, q) {
    return [[R.K, f.k], [R.P, f.p], [R.NA, f.na]].some(([key, v]) => (v != null && R.isHigh(key, v * q)) || (key === R.P && f.additive));
  }

  function contributors(items, n, reason) {
    const key = reasonKey(reason);
    const rows = [];
    items.forEach((it, idx) => {
      const q = it.amount / n;
      if (reason === 'avoid_ckd') { if (it.food.avoid) rows.push([0.0, it.food.id, idx]); }
      else if (reason.startsWith('unknown:')) { if (value(it.food, key) == null) rows.push([0.0, it.food.id, idx]); }
      else if (reason === 'high_portion_too_large' || reason === 'portion_out_of_range') {
        if ((reason === 'portion_out_of_range' && q > R.PORTION_MAX) || (reason === 'high_portion_too_large' && q > 1.0 && highShare(it.food, q))) rows.push([-q, it.food.id, idx]);
      } else if (key != null) {
        const v = value(it.food, key);
        if (v != null && v * q > 0) rows.push([-(v * q), it.food.id, idx]);
      }
    });
    rows.sort((a, b) => a[0] - b[0] || a[1] - b[1] || a[2] - b[2]);
    return rows.map((r) => r[2]);
  }

  const stepDown = (q) => (Math.ceil(4 * q - 1e-9) - 1) / 4;

  function recipeSwap(ctx, it, n, reason, room) {
    const food = it.food, pot = it.amount;
    const key = reasonKey(reason);
    const mode = food.avoid ? 'avoid' : 'normal';
    if (reason === 'too_many_carbs') return null;
    const carbs = (food.carbs || 0.0) * pot, protein = (food.protein || 0.0) * pot;
    let match, target;
    if (carbs >= R.SWAP_MATCH_CARBS_MIN_G * n) { match = 'carbs'; target = carbs; }
    else if (protein >= R.SWAP_MATCH_PROTEIN_MIN_G * n) { match = 'protein'; target = protein; }
    else { match = 'serving'; target = pot; }
    const origShare = {};
    for (const k of R.RENAL_KEYS) origShare[k] = value(food, k) == null ? null : value(food, k) * pot / n;
    const pref = S.habitStats(ctx).pref;
    let best = null;
    for (const cand of ctx.foods.values()) {
      if (cand.hypo || !SW.eligibleSwap(cand, food, ctx, mode)) continue;
      let q;
      if (match === 'serving') q = pot;
      else {
        const per = match === 'carbs' ? cand.carbs : cand.protein;
        if (per == null || per <= 0) continue;
        q = R.clamp(R.roundToQuarter(target / per), R.PORTION_MIN, R.RECIPE_POT_MAX_SERVINGS);
        const [tolMin, tolFrac] = match === 'carbs' ? R.SWAP_CARB_MATCH : R.SWAP_PROTEIN_MATCH;
        if (Math.abs(q * per - target) > Math.max(tolMin, tolFrac * target)) continue;
      }
      const share = q / n;
      if (share > R.PORTION_MAX + 1e-9) continue;
      const nv = {};
      for (const k of R.RENAL_KEYS) nv[k] = value(cand, k) == null ? null : value(cand, k) * share;
      if (reason.startsWith('unknown:') && value(cand, key) == null) continue;
      if (R.RENAL_KEYS.includes(key) && !reason.startsWith('unknown:')) {
        const o = origShare[key], v = nv[key];
        if (o == null || v == null || o <= 0 || v > (1.0 - R.SWAP_MIN_REDUCTION) * o + 1e-9) continue;
        if (key === R.P && cand.additive) continue;
      }
      let problem = false;
      for (const k of R.RENAL_KEYS) {
        if (nv[k] == null && B.levelOf(room, k) !== 'ok') problem = true;
        if (R.isHigh(k, nv[k]) && !R.isHigh(k, origShare[k])) problem = true;
      }
      if (problem) continue;
      const score = R.roundScore((cand.category === food.category ? 1.0 : 0.0) + pref.of(cand) - (cand.processed ? 1.0 : 0.0));
      const rank = [-score, key in nv && nv[key] != null ? nv[key] : 0.0, cand.name_fold, cand.id];
      if (best == null || R.cmp(rank, best.rank) < 0) best = { rank, cand, q };
    }
    return best == null ? null : [best.cand, best.q];
  }

  function fitRecipe(ctx, recipe, servingsMade, target) {
    const room = roomFor(ctx, target);
    const n = Number(servingsMade || 1.0);
    let items = recipe.map(([f, q]) => item(f, Number(q)));
    const before = figures(items, n, room);
    if (check(items, n, room).ok) return result('fits', before, items, n, 1.0, [], room, target);
    const changes = [];
    let lowered = [];

    // 1. Lower amounts, one ingredient at a time, largest contributor first.
    let steps = 0;
    while (steps < R.RECIPE_MAX_LOWER_STEPS) {
      const res = check(items, n, room);
      if (res.ok || res.reason == null || !LOWERABLE.some((p) => res.reason.startsWith(p))) break;
      const pick = contributors(items, n, res.reason).find((i) => items[i].food.role !== 'protein' && !items[i].food.hypo && items[i].amount > floorOf(items[i]) + 1e-9);
      if (pick === undefined) break;
      const reason = res.reason;
      items[pick].because = items[pick].because || reasonKey(reason) || 'portion';
      while (items[pick].amount > floorOf(items[pick]) + 1e-9 && steps < R.RECIPE_MAX_LOWER_STEPS) {
        lowered.push([pick, items[pick].amount]);
        items[pick].amount = Math.max(floorOf(items[pick]), stepDown(items[pick].amount));
        steps += 1;
        if (check(items, n, room).reason !== reason) break;
      }
    }

    // 2. Swap, at most RECIPE_MAX_SWAPS times.
    let swaps = 0;
    while (swaps < R.RECIPE_MAX_SWAPS) {
      const res = check(items, n, room);
      if (res.ok || res.reason == null) break;
      const pick = contributors(items, n, res.reason).find((i) => !items[i].food.hypo && items[i].swapped_from == null);
      if (pick === undefined) break;
      const found = recipeSwap(ctx, items[pick], n, res.reason, room);
      if (found == null) break;
      const old = items[pick];
      items = items.slice();
      items[pick] = item(found[0], found[1], old.food);
      lowered = lowered.filter(([i]) => i !== pick);
      changes.push({ code: 'swapped', food_id: found[0].id, from_food_id: old.food.id, from: old.amount, to: found[1],
        because: swapBecause(res.reason), _from_food: old.food, _to_food: found[0] });
      swaps += 1;
    }

    // 3. A smaller serving.
    let fraction = 1.0;
    if (!check(items, n, room).ok) {
      for (const g of R.RECIPE_SERVING_FRACTIONS) {
        if (check(items, n, room, g).ok) { fraction = g; break; }
      }
    }

    if (check(items, n, room, fraction).ok) {
      while (lowered.length) {
        const [idx, previous] = lowered[lowered.length - 1];
        const keep = items[idx].amount;
        items[idx].amount = previous;
        if (!check(items, n, room, fraction).ok) { items[idx].amount = keep; break; }
        lowered.pop();
      }
      return result(fraction < 1.0 ? 'fits_smaller_serving' : 'fits_after_changes', before, items, n, fraction, changes, room, target);
    }
    const fractions = R.RECIPE_SERVING_FRACTIONS;
    return result('does_not_fit', before, items, n, fractions[fractions.length - 1], changes, room, target);
  }

  // Some food of the serving does not list the nutrient, so its figure counts only the others ("at least").
  const partial = (fig, key) => (fig.unknown[key] || 0) > 0;

  function result(status, before, items, n, fraction, swaps, room, target) {
    const after = figures(items, n, room, fraction);
    const full = fraction !== 1.0 ? figures(items, n, room) : after;
    const label = M.recipeTargetLabel(target.kind, room.meal);
    const changes = [];
    for (const it of items) {
      if (it.swapped_from == null && Math.abs(it.amount - it.original) > 1e-9) {
        const key = it.because || R.K;
        changes.push({ code: 'lowered', food_id: it.food.id, from: it.original, to: it.amount, because: key,
          text: M.recipeLoweredText(it.food.name, it.food.serving_desc, it.original, it.amount, key, label, before.per_serving[key], full.per_serving[key],
            partial(before, key), partial(full, key)) });
      }
    }
    for (const s of swaps) {
      const out = {};
      for (const [k, v] of Object.entries(s)) if (!k.startsWith('_')) out[k] = v;
      out.text = M.recipeSwappedText(s._from_food.name, s._to_food.name, s._to_food.serving_desc, s.to, s.because, label, before.per_serving, full.per_serving,
        before.unknown, full.unknown);
      changes.push(out);
    }
    if (status === 'fits_smaller_serving') {
      const failing = full.checks.find((c) => !c.ok);
      const key = failing ? failing.nutrient : R.K;
      const roomCheck = full.checks.find((c) => c.nutrient === key);
      changes.push({ code: 'smaller_serving', fraction, because: key,
        text: M.recipeSmallerText(fraction, key, label, full.per_serving[key], after.per_serving[key], roomCheck ? roomCheck.room : null, partial(full, key)) });
    }
    const fitted = {
      items: items.map((it) => ({ food_id: it.food.id, name: it.food.name, servings: it.amount, serving_desc: it.food.serving_desc,
        portion_text: M.portionText(it.amount, it.food.serving_desc) })),
      serving_fraction: fraction,
      log_scale: R.roundTo(fraction / n, 4),
    };
    const noFit = status === 'does_not_fit';
    const out = {
      status, servings_made: n, before, after: noFit ? null : after, fitted: noFit ? null : fitted,
      closest: noFit ? { ...fitted, after } : null, changes,
      still_over: noFit ? after.checks.filter((c) => !c.ok).map((c) => c.nutrient) : [],
      notes: [...M.RECIPE_NOTES, M.DISCLAIMER],
    };
    if (noFit) {
      const over = after.checks.find((c) => !c.ok) || null;
      out.changes.push({ code: 'does_not_fit', text: M.recipeNoFitText(label, over, over != null && partial(after, over.nutrient)) });
    }
    return out;
  }

  GE.recipes = { nextOpenMeal, dayRoom, roomFor, shares, figures, recipeSwap, fitRecipe };
  GE.fitRecipe = fitRecipe;
  GE.nextOpenMeal = nextOpenMeal;
})(typeof window !== 'undefined' ? window : globalThis);
