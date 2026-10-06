/* Kidney Diet Log — meal guidance, part 3 of 9: the room left for one meal. Twin of
   app/guidance/budget.py (note 06 §4.4).

   Open slots O(m): m; every later main meal with no entries; the snack slot when empty (for the snack
   slot: every empty main meal). Allowance: the daily target for potassium, sodium and fluid (on
   hemodialysis with dialysis days also (T × D − eaten since the last session) / days left, whichever is
   lower); for phosphorus clamp(T × (n + 1) − S, 0.8 T, 1.2 T) over the n logged days of the previous 6.
   Room: max(0, min(cap − used, share)), share = max(0, A − proj) × w(m) / Σ w(O), cap = 0.30 T per main
   meal, 0.15 T for the snack slot (no cap for fluid). Plain script; needs guidance/rules.js. */
(function (root) {
  'use strict';
  const KH = root.KH || (root.KH = {});
  const GE = KH.guidanceEngine;
  const R = GE.R;
  const INF = Infinity;
  const MAX_INTERDIALYTIC_DAYS = 7; // app/periods.py

  function mealsWithEntries(day) { return new Set(day.map((e) => e.meal)); }

  function openSlots(meal, day) {
    const used = mealsWithEntries(day);
    const slots = [meal];
    if (meal === R.SNACK) {
      for (const m of R.MAIN_MEALS) if (!used.has(m)) slots.push(m);
      return slots;
    }
    for (const m of R.MAIN_MEALS.slice(R.MAIN_MEALS.indexOf(meal) + 1)) if (!used.has(m)) slots.push(m);
    if (!used.has(R.SNACK)) slots.push(R.SNACK);
    return slots;
  }

  // periods.interdialytic_interval
  function interdialyticInterval(end, dialysisDays, maxDays = MAX_INTERDIALYTIC_DAYS) {
    const weekdays = new Set((dialysisDays || []).map(Number).filter((d) => d >= 0 && d <= 6));
    if (!weekdays.size) return null;
    let since = null;
    for (let back = 0; back < maxDays; back++) {
      const c = R.addDays(end, -back);
      if (weekdays.has(R.weekday(c))) { since = c; break; }
    }
    const capped = since == null;
    if (since == null) since = R.addDays(end, -(maxDays - 1));
    let next = null;
    for (let ahead = 1; ahead < 8; ahead++) {
      const c = R.addDays(end, ahead);
      if (weekdays.has(R.weekday(c))) { next = c; break; }
    }
    return { since, end, days: R.daysBetween(since, end) + 1, next, capped };
  }

  function weekAllowance(target, history, day) {
    const start = R.addDays(day, -R.WEEK_LOOKBACK_DAYS);
    const logged = new Set();
    let total = 0.0;
    for (const h of history) {
      if (start <= h.date && h.date < day) {
        logged.add(h.date);
        total += h.nutrients[R.P] || 0.0;
      }
    }
    const n = logged.size;
    const raw = target * (n + 1) - total;
    const [lo, hi] = R.WEEK_CLAMP;
    return [R.clamp(raw, lo * target, hi * target), n, total];
  }

  function interdialyticAllowance(target, key, history, day, dialysisDays) {
    const interval = interdialyticInterval(day, dialysisDays);
    if (interval == null) return null;
    const { since, next } = interval;
    const dTotal = R.daysBetween(since, next);
    const daysLeft = Math.max(1, R.daysBetween(day, next));
    let eaten = 0;
    for (const h of history) if (since <= h.date && h.date < day) eaten += h.nutrients[key] || 0.0;
    return (target * dTotal - eaten) / daysLeft;
  }

  function levelFor(projected, allowance, warnFraction) {
    if (allowance <= 0) return projected > 0 ? 'over' : 'caution';
    const fraction = projected / allowance;
    if (fraction > 1.0) return 'over';
    if (fraction >= warnFraction) return 'caution';
    return 'ok';
  }

  function snackCarbGoal(targets, perMeal) {
    const explicit = R.targetMax(targets.carbs_per_snack_g);
    if (explicit != null) return explicit;
    return Math.max(R.SNACK_CARB_MIN_G, 5.0 * R.jsRound(perMeal / 2.0 / 5.0));
  }

  const TOTAL_KEYS = [R.K, R.P, R.NA, R.FLUID, R.PROTEIN, R.CARBS, R.KCAL];
  function zeros() { const o = {}; for (const k of TOTAL_KEYS) o[k] = 0.0; return o; }

  // Projected totals of the day and per meal, computed once per request.
  function dayTotals(day) {
    const projected = zeros();
    const mealUsed = {}, carbs = {}, hypoCarbs = {}, groups = {}, mealHigh = {};
    for (const m of R.SLOT_ORDER) { mealUsed[m] = zeros(); carbs[m] = 0.0; hypoCarbs[m] = 0.0; groups[m] = new Set(); mealHigh[m] = 0; }
    let dayHigh = 0;
    for (const e of day) {
      const used = mealUsed[e.meal] || (mealUsed[e.meal] = zeros());
      for (const k of TOTAL_KEYS) {
        const v = e.nutrients[k];
        if (v != null) { projected[k] += v; used[k] += v; }
      }
      const c = e.nutrients[R.CARBS] || 0.0;
      if (e.hypo) { hypoCarbs[e.meal] = (hypoCarbs[e.meal] || 0.0) + c; continue; }
      carbs[e.meal] = (carbs[e.meal] || 0.0) + c;
      (groups[e.meal] || (groups[e.meal] = new Set())).add(e.group);
      if (e.role === 'mixed') groups[e.meal].add('starch');
      if ((e.nutrients[R.K] || 0.0) > R.HIGH_K_ENTRY_MG) {
        mealHigh[e.meal] = (mealHigh[e.meal] || 0) + 1;
        dayHigh += 1;
      }
    }
    return { projected, meal_used: mealUsed, meal_carbs: carbs, meal_hypo_carbs: hypoCarbs, meal_groups: groups,
      meal_high_k: mealHigh, day_high_k: dayHigh };
  }

  // The room for `meal` on ctx.date; `openMeals` overrides O(m) (the planner passes slots[i:]).
  function mealRoom(ctx, meal, openMeals = null, totals = null) {
    let slots = openMeals != null ? [...openMeals] : openSlots(meal, ctx.day);
    if (!slots.includes(meal)) slots = [meal, ...slots];
    totals = totals || dayTotals(ctx.day);
    const targets = ctx.profile.targets;
    const warn = ctx.profile.warn_fraction;
    let weightSum = 0;
    for (const m of slots) weightSum += R.MEAL_WEIGHT[m];
    const shareFactor = weightSum > 0 ? R.MEAL_WEIGHT[meal] / weightSum : 1.0;

    const hd = ctx.profile.dialysis === 'hemodialysis' && ctx.profile.dialysis_days.length > 0;
    const nutrients = {};
    const weights = {};
    const dayLeft = {};
    for (const key of R.ROOM_KEYS) {
      const target = R.targetMax(targets[key]);
      if (target == null) continue;
      let basis = 'day';
      let allowance;
      if (key === R.P) {
        allowance = weekAllowance(target, ctx.history, ctx.date)[0];
        basis = 'week_average';
      } else {
        allowance = target;
        if (hd && R.INTERDIALYTIC_KEYS.includes(key)) {
          const inter = interdialyticAllowance(target, key, ctx.history, ctx.date, ctx.profile.dialysis_days);
          if (inter != null && inter < target) { allowance = inter; basis = 'interdialytic'; }
        }
      }
      const proj = totals.projected[key] || 0.0;
      const remaining = allowance - proj;
      const share = Math.max(0.0, remaining) * shareFactor;
      const cap = R.CAP_KEYS.includes(key) ? R.MEAL_CAP_FRACTION[meal] * target : INF;
      const inMeal = (totals.meal_used[meal] || {})[key] || 0.0;
      const room = Math.max(0.0, Math.min(cap - inMeal, share));
      const level = levelFor(proj, allowance, warn);
      nutrients[key] = { key, target, allowance, projected: proj, remaining, share, cap, in_meal: inMeal, room, level, basis };
      let weight = R.USAGE_WEIGHT[key];
      if (key === R.P && level !== 'ok') weight = R.USAGE_WEIGHT_P_NOT_OK;
      weights[key] = weight;
      if (R.DAY_JUDGED.includes(key)) dayLeft[key] = proj <= target ? target - proj : INF;
    }

    let carbs = null;
    const perMeal = R.targetMax(targets.carbs_per_meal_g);
    if (ctx.profile.diabetes !== 'none' && perMeal != null) {
      const goal = meal !== R.SNACK ? perMeal : snackCarbGoal(targets, perMeal);
      const inMeal = totals.meal_carbs[meal] || 0.0;
      carbs = { goal, in_meal: inMeal, gap: goal - inMeal, tolerance: Number(ctx.prefs.carb_tolerance_g),
        hypo_excluded: totals.meal_hypo_carbs[meal] || 0.0 };
    }

    let protein = null;
    const pt = targets[R.PROTEIN];
    const pMax = R.targetMax(pt), pMin = R.targetMin(pt);
    if (pMax != null || pMin != null) {
      const projProtein = totals.projected[R.PROTEIN] || 0.0;
      const mid = pMin != null && pMax != null ? (pMin + pMax) / 2.0 : (pMax != null ? pMax : pMin);
      const aim = Math.max(0.0, mid - projProtein) * shareFactor;
      const aimMin = pMin != null ? Math.max(0.0, pMin - projProtein) * shareFactor : 0.0;
      protein = { aim, aim_min: aimMin, projected: projProtein, minimum: pMin, maximum: pMax };
    }

    const groups = totals.meal_groups[meal] || new Set();
    return {
      meal, open_meals: slots, nutrients, carbs, protein,
      meal_has: { protein: groups.has('protein'), starch: groups.has('starch'), veg_fruit: groups.has('veg_fruit') },
      meal_high_k: totals.meal_high_k[meal] || 0, day_high_k: totals.day_high_k, usage_weight: weights, day_left: dayLeft,
    };
  }
  function roomOf(room, key) { const item = room.nutrients[key]; return item == null ? INF : item.room; }
  function levelOf(room, key) { const item = room.nutrients[key]; return item == null ? 'ok' : item.level; }
  function gapOf(room) { return room.carbs == null ? 0.0 : room.carbs.gap; }
  function toleranceOf(room) { return room.carbs == null ? 0.0 : room.carbs.tolerance; }

  GE.budget = { INF, openSlots, interdialyticInterval, weekAllowance, interdialyticAllowance, levelFor, snackCarbGoal, dayTotals,
    mealRoom, roomOf, levelOf, gapOf, toleranceOf, TOTAL_KEYS };
})(typeof window !== 'undefined' ? window : globalThis);
