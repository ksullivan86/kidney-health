/* Kidney Diet Log — meal guidance, part 4 of 9: food and meal scores and the single meal gate. Twin of
   app/guidance/score.py (note 06 §4.5 "Score", §4.7 "Meal check" and "Meal score").

   Scorer.evaluate is the hot path (plain floats, no formatting); checkMeal is the one gate every meal
   passes (plan options, saved, usual and starter meals); scoreMeal ranks whole meals. Scores are rounded
   to 2 decimals with Math.round semantics before any comparison. Plain script; needs budget.js. */
(function (root) {
  'use strict';
  const KH = root.KH || (root.KH = {});
  const GE = KH.guidanceEngine;
  const R = GE.R;
  const { INF } = GE.budget;

  const NEG_CARBS = R.NEGLIGIBLE[R.CARBS];
  const K_HIGH = R.RENAL_HIGH_CUT[R.K], P_HIGH = R.RENAL_HIGH_CUT[R.P], NA_HIGH = R.RENAL_HIGH_CUT[R.NA];
  const [P_GOOD, P_POOR] = R.P_PER_G_PROTEIN;
  const [K_GOOD, K_POOR] = R.K_PER_G_PROTEIN;

  // ---- habit and variety (the static term) -------------------------------------------------------
  function habitStats(ctx) {
    const start14 = R.addDays(ctx.date, -R.HISTORY_DAYS);
    const start2 = R.addDays(ctx.date, -2);
    const days = new Map(), prev2 = new Map(), slots = new Map();
    const add = (map, key, value) => { let s = map.get(key); if (!s) map.set(key, (s = new Set())); s.add(value); };
    for (const h of ctx.history) {
      if (h.hypo || !(start14 <= h.date && h.date < ctx.date)) continue;
      add(days, h.food_id, h.date);
      add(slots, `${h.food_id}|${h.meal}`, h.date);
      if (h.date >= start2) add(prev2, h.food_id, h.date);
    }
    const saved = new Set();
    for (const m of ctx.saved_meals) for (const [fid] of m.items) saved.add(fid);
    const count = (map) => { const out = new Map(); for (const [k, v] of map) out.set(k, v.size); return out; };
    return { days_14: count(days), prev2: count(prev2), slot_days: count(slots), saved_ids: saved };
  }
  function todayStats(day) {
    const ids = new Set();
    const fams = new Map();
    for (const e of day) {
      ids.add(e.food_id);
      if (e.family) { let s = fams.get(e.family); if (!s) fams.set(e.family, (s = new Set())); s.add(e.food_id); }
    }
    return { food_ids: ids, families: fams };
  }
  function otherInFamily(today, f) {
    const fam = today.families.get(f.family);
    if (!fam || !fam.size) return false;
    for (const other of fam) if (other !== f.id) return true;
    return false;
  }
  function staticTerm(f, habit, today) {
    let s = 0.0;
    if (f.additive) s -= 2.0;
    if (f.processed) s -= 0.5;
    s += Math.min(1.5, 0.5 * (habit.days_14.get(f.id) || 0));
    if (habit.saved_ids.has(f.id)) s += 0.5;
    if (today.food_ids.has(f.id)) s -= 1.5;
    s -= 0.5 * (habit.prev2.get(f.id) || 0);
    if (otherInFamily(today, f)) s -= 0.75;
    return s;
  }

  function evaluation(food, servings, score, whyNot, unknown = [], components = null) {
    return { food, servings, score, why_not: whyNot, unknown, components };
  }
  function newCounter() { return { foods: 0, meals: 0 }; }

  function roundTo4(v) { return R.roundTo(v, 4); }

  // ---- one food at one portion -------------------------------------------------------------------
  class Scorer {
    constructor(room, habit, today, counter = null) {
      this.room = room; this.habit = habit; this.today = today;
      this.counter = counter || newCounter();
      this.meal = room.meal;
      const n = room.nutrients;
      this.tracked = R.ROOM_KEYS.filter((k) => k in n);
      const lim = {};
      for (const k of R.ROOM_KEYS) {
        const a = k in n ? n[k].room + R.NEGLIGIBLE[k] : INF;
        const b = k in room.day_left ? room.day_left[k] : INF;
        lim[k] = Math.min(a, b);
      }
      this.lim_k = lim[R.K]; this.lim_p = lim[R.P]; this.lim_na = lim[R.NA]; this.lim_fl = lim[R.FLUID];
      const denom = (k) => (k in n ? Math.max(n[k].room, R.NEGLIGIBLE[k]) : null);
      this.dk = denom(R.K); this.dp = denom(R.P); this.dna = denom(R.NA); this.dfl = denom(R.FLUID);
      const w = (k) => (k in room.usage_weight ? room.usage_weight[k] : 0.0);
      this.wk = w(R.K); this.wp = w(R.P); this.wna = w(R.NA); this.wfl = w(R.FLUID);
      this.not_ok = {};
      for (const k of R.ROOM_KEYS) this.not_ok[k] = k in n && n[k].level !== 'ok';
      this.k_not_ok = this.not_ok[R.K]; this.p_not_ok = this.not_ok[R.P]; this.na_not_ok = this.not_ok[R.NA];
      this.carb_on = room.carbs != null;
      this.gap = room.carbs == null ? 0.0 : room.carbs.gap;
      this.tol = room.carbs == null ? 0.0 : room.carbs.tolerance;
      this.has_protein = !!room.meal_has.protein;
      this.has_starch = !!room.meal_has.starch;
      this.has_veg = !!room.meal_has.veg_fruit;
      this.aim = room.protein != null ? Math.max(room.protein.aim, R.PROTEIN_AIM_FLOOR_G) : null;
      this.meal_high_k = room.meal_high_k;
      this.day_high_k = room.day_high_k;
      this._static = new Map();
    }
    static(f) {
      let s = this._static.get(f.id);
      if (s === undefined) { s = staticTerm(f, this.habit, this.today); this._static.set(f.id, s); }
      return s;
    }
    slotHabit(f) { return (this.habit.slot_days.get(`${f.id}|${this.meal}`) || 0) >= R.SLOT_HABIT_MIN_DAYS; }

    // Score f at q servings, or the first hard filter it fails (§4.5): would_exceed, unknown, too_many_carbs, high_warning.
    evaluate(f, q, explain = false) {
      this.counter.foods += 1;
      const fk = f.k, fp = f.p, fna = f.na, ffl = f.fluid;
      const ak = fk == null ? null : fk * q;
      const ap = fp == null ? null : fp * q;
      const ana = fna == null ? null : fna * q;
      const afl = ffl == null ? null : ffl * q;
      if (ak != null && ak > this.lim_k) return evaluation(f, q, null, 'would_exceed:potassium_mg');
      if (ap != null && ap > this.lim_p) return evaluation(f, q, null, 'would_exceed:phosphorus_mg');
      if (ana != null && ana > this.lim_na) return evaluation(f, q, null, 'would_exceed:sodium_mg');
      if (afl != null && afl > this.lim_fl) return evaluation(f, q, null, 'would_exceed:fluid_ml');
      let unknown = [];
      if (ak == null || ap == null || ana == null) {
        const missing = [];
        for (const [key, v] of [[R.K, ak], [R.P, ap], [R.NA, ana]]) {
          if (v == null) {
            if (this.not_ok[key]) return evaluation(f, q, null, `unknown:${key}`);
            missing.push(key);
          }
        }
        unknown = missing;
      }
      const fc = f.carbs;
      const ac = fc == null ? null : fc * q;
      const gap = this.gap;
      if (this.carb_on) {
        if (ac == null) return evaluation(f, q, null, 'unknown:carbs_g');
        if (ac > NEG_CARBS && ac > (gap > 0.0 ? gap : 0.0) + this.tol) return evaluation(f, q, null, 'too_many_carbs');
      }
      if (this.k_not_ok && ak != null && ak >= K_HIGH) return evaluation(f, q, null, 'high_warning:potassium_mg');
      if (this.p_not_ok && (f.additive || (ap != null && ap >= P_HIGH))) return evaluation(f, q, null, 'high_warning:phosphorus_mg');
      if (this.na_not_ok && ana != null && ana >= NA_HIGH) return evaluation(f, q, null, 'high_warning:sodium_mg');

      const role = f.role;
      const fpr = f.protein;
      const apr = fpr == null ? null : fpr * q;
      const proteinRole = R.PROTEIN_ROLES.has(role);
      let base;
      if (proteinRole && apr != null && apr >= R.PROTEIN_ROLE_MIN_G) {
        base = 1.0;
        if (ap != null) {
          const ratio = ap / apr;
          if (ratio <= P_GOOD) base += 1.0;
          else if (ratio >= P_POOR) base -= 1.5;
        }
        if (ak != null) {
          const ratio = ak / apr;
          if (ratio <= K_GOOD) base += 0.5;
          else if (ratio >= K_POOR) base -= 1.0;
        }
        if (ana != null && ana >= NA_HIGH) base -= 3.0;
        if (f.additive) base -= 3.0;
      } else {
        const level = R.renalLevel(ak, ap, ana, f.additive);
        base = level === 'green' ? 3.0 : level === 'yellow' ? 1.0 : -3.0;
      }
      const stat = this.static(f);
      const unknownPen = R.UNKNOWN_PENALTY * unknown.length;
      const portion = 0.5 * Math.abs(q - 1.0);
      let usage = 0.0;
      if (ak != null && this.dk != null) { const x = ak / this.dk; usage += this.wk * x * x; }
      if (ap != null && this.dp != null) { const x = ap / this.dp; usage += this.wp * x * x; }
      if (ana != null && this.dna != null) { const x = ana / this.dna; usage += this.wna * x * x; }
      if (afl != null && this.dfl != null) { const x = afl / this.dfl; usage += this.wfl * x * x; }
      let carbsTerm = 0.0, free = 0.0, gi = 0.0;
      if (this.carb_on && ac != null) {
        if (gap > this.tol && R.CARB_FILL_ROLES.has(role)) carbsTerm = 2.0 * (ac < gap ? ac : gap) / gap;
        if (gap <= this.tol && ac <= R.FREE_FOOD_CARBS_G) free = 1.0;
      }
      if (f.high_gi && ac != null && ac >= R.HIGH_GI_PENALTY_MIN_CARBS_G) gi = -1.0;
      let missingGroup = 0.0;
      if (proteinRole && !this.has_protein) missingGroup += 1.5;
      if (R.STARCH_ROLES.has(role) && !this.has_starch && (!this.carb_on || gap > 15.0)) missingGroup += 1.5;
      if (role === 'veg_fruit' && !this.has_veg) missingGroup += 1.0;
      let proteinTerm = 0.0;
      if (proteinRole && this.aim != null && apr != null) {
        const a = this.aim;
        proteinTerm = 1.5 * (apr < a ? apr : a) / a;
        if (apr > a) { const d = (apr - a) / a; proteinTerm -= Math.min(2.0, d * d); }
      }
      const habit = this.slotHabit(f) ? R.SLOT_HABIT_BONUS : 0.0;
      let highK = 0.0;
      if (ak != null && ak > R.HIGH_K_ENTRY_MG) {
        if (this.meal_high_k > 0) highK -= 2.0;
        if (this.day_high_k >= 2) highK -= 1.0;
      }
      const s = base + stat - unknownPen - portion - usage + carbsTerm + free + gi + missingGroup + proteinTerm + habit + highK;
      let comp = null;
      if (explain) {
        comp = { base: roundTo4(base), static: roundTo4(stat), unknown: roundTo4(-unknownPen), portion: roundTo4(-portion),
          usage: roundTo4(-usage), carbs: roundTo4(carbsTerm), free_food: roundTo4(free), high_gi: roundTo4(gi),
          missing_group: roundTo4(missingGroup), protein: roundTo4(proteinTerm), slot_habit: roundTo4(habit), high_potassium: roundTo4(highK) };
      }
      // R.roundScore inlined (hot path); `+ 0` because Python's math.floor returns an int (never -0).
      const x = s * 100.0;
      const fl = Math.floor(x) + 0;
      return evaluation(f, q, (x - fl >= 0.5 ? fl + 1.0 : fl) / 100.0, null, unknown, comp);
    }

    // [best scored evaluation or null, the evaluation at one serving]; ties → lower K, P, Na. Every hard
    // filter is monotone in the portion, so once a portion fails, larger ones are not evaluated.
    bestPortion(f, portions, explain = false) {
      let best = null, bestKey = null, standard = null;
      let failedAt = Infinity;
      for (const q of portions) {
        if (q > failedAt) continue;
        const ev = this.evaluate(f, q, explain);
        if (q === 1.0) standard = ev;
        if (ev.score == null) { failedAt = q; continue; }
        const key = portionKey(ev);
        if (bestKey == null || R.cmp(key, bestKey) < 0) { best = ev; bestKey = key; }
      }
      if (standard == null) standard = this.evaluate(f, 1.0, explain);
      return [best, standard];
    }
  }
  function amount(v, q) { return v == null ? 0.0 : v * q; }
  function portionKey(ev) {
    const f = ev.food, q = ev.servings;
    return [-(ev.score || 0.0), amount(f.k, q), amount(f.p, q), amount(f.na, q)];
  }
  function foodOrderKey(ev) {
    const f = ev.food, q = ev.servings;
    return [-(ev.score || 0.0), amount(f.k, q), amount(f.p, q), amount(f.na, q), f.name_fold, f.id];
  }

  // ---- whole meals -------------------------------------------------------------------------------
  // [totals, Set of keys with an unknown value]; unknown values count as 0 in the totals.
  function mealTotals(items) {
    let k = 0.0, p = 0.0, na = 0.0, fl = 0.0, c = 0.0, pr = 0.0, kcal = 0.0;
    const unknown = new Set();
    for (const [f, q] of items) {
      if (f.k == null) unknown.add(R.K); else k += f.k * q;
      if (f.p == null) unknown.add(R.P); else p += f.p * q;
      if (f.na == null) unknown.add(R.NA); else na += f.na * q;
      if (f.fluid == null) unknown.add(R.FLUID); else fl += f.fluid * q;
      if (f.carbs == null) unknown.add(R.CARBS); else c += f.carbs * q;
      if (f.protein == null) unknown.add(R.PROTEIN); else pr += f.protein * q;
      if (f.kcal == null) unknown.add(R.KCAL); else kcal += f.kcal * q;
    }
    return [{ [R.K]: k, [R.P]: p, [R.NA]: na, [R.FLUID]: fl, [R.CARBS]: c, [R.PROTEIN]: pr, [R.KCAL]: kcal }, unknown];
  }

  function mealCheck(ok, reason = null) { return { ok, reason }; }
  // The single gate (§4.7); kind is built, ai, saved, usual or starter.
  function checkMeal(items, room, kind = 'built', totals = null) {
    if (!items.length) return mealCheck(false, 'empty');
    const [tot, unknown] = totals != null ? totals : mealTotals(items);
    for (const key of [R.K, R.P, R.NA, R.FLUID]) {
      const item = room.nutrients[key];
      if (item == null) continue;
      // Within the meal's room; except for the planner's built slots (cut back together by the whole-day
      // repair), also within what is left of the day's own target: never a new "over" (G4/V5).
      let limit = item.room + R.NEGLIGIBLE[key];
      if (kind !== 'built' && key in room.day_left) limit = Math.min(limit, room.day_left[key]);
      if (tot[key] > limit) return mealCheck(false, `would_exceed:${key}`);
    }
    for (const key of [R.K, R.P, R.NA]) {
      if (unknown.has(key) && GE.budget.levelOf(room, key) !== 'ok') return mealCheck(false, `unknown:${key}`);
    }
    if (room.carbs != null) {
      if (unknown.has(R.CARBS)) return mealCheck(false, 'unknown:carbs_g');
      const carbs = tot[R.CARBS];
      if (carbs > NEG_CARBS && carbs > Math.max(room.carbs.gap, 0.0) + room.carbs.tolerance) return mealCheck(false, 'too_many_carbs');
    }
    const strict = kind === 'built' || kind === 'ai';
    for (const [f, q] of items) {
      if (f.avoid) return mealCheck(false, 'avoid_ckd');
      if (q < R.PORTION_MIN - 1e-9 || q > R.PORTION_MAX + 1e-9) return mealCheck(false, 'portion_out_of_range');
      if (strict) {
        if (f.hypo) return mealCheck(false, 'hypo_treatment');
        if (f.ingredient) return mealCheck(false, 'ingredient');
        if (f.alcohol) return mealCheck(false, 'alcohol');
        let highAny = false;
        for (const [key, v] of [[R.K, f.k], [R.P, f.p], [R.NA, f.na]]) {
          const high = (v != null && R.isHigh(key, v * q)) || (key === R.P && f.additive);
          highAny = highAny || high;
          if (high && GE.budget.levelOf(room, key) !== 'ok') return mealCheck(false, `high_warning:${key}`);
        }
        if (kind === 'ai' && highAny && q > 1.0 + 1e-9) return mealCheck(false, 'high_portion_too_large');
      }
    }
    return mealCheck(true);
  }

  function h(d) { return d <= 2.0 ? d * d : 4.0 + 4.0 * (d - 2.0); }

  function isPoor(f, q) {
    const apr = f.protein == null ? null : f.protein * q;
    const ak = f.k == null ? null : f.k * q;
    const ap = f.p == null ? null : f.p * q;
    const ana = f.na == null ? null : f.na * q;
    if (R.PROTEIN_ROLES.has(f.role) && apr != null && apr >= R.PROTEIN_ROLE_MIN_G) {
      const quality = R.proteinQuality(apr, ak, ap);
      if (quality.p_grade === 'poor' || quality.k_grade === 'poor') return true;
      return R.isHigh(R.NA, ana);
    }
    return R.renalLevel(ak, ap, ana, f.additive) === 'red';
  }

  // The meal score of §4.7, rounded to 2 decimals.
  function scoreMeal(items, room, today, dialysis, scale = 1.0, counter = null, totals = null) {
    if (counter != null) counter.meals += 1;
    const tot = (totals != null ? totals : mealTotals(items))[0];
    let s = 10.0;
    for (const key of Object.keys(room.nutrients)) {
      const item = room.nutrients[key];
      const x = tot[key] / Math.max(item.room, R.NEGLIGIBLE[key]);
      s -= room.usage_weight[key] * x * x;
    }
    if (room.carbs != null && room.carbs.tolerance > 0) s -= 2.0 * h(Math.abs(tot[R.CARBS] - room.carbs.gap) / room.carbs.tolerance);
    if (room.protein != null) {
      const a = Math.max(room.protein.aim, R.PROTEIN_AIM_FLOOR_G);
      const totalP = tot[R.PROTEIN];
      const dev = (totalP - a) / a;
      if (dialysis) {
        // x * x on both sides (a float ** may differ from x * x by one unit in the last place on some C libraries).
        const up = Math.max(0.0, dev);
        s -= 6.0 * Math.max(0.0, -dev) + 0.5 * Math.min(2.0, up * up);
      } else {
        const aMin = Math.max(room.protein.aim_min, R.PROTEIN_AIM_FLOOR_G);
        s -= 4.0 * Math.max(0.0, (aMin - totalP) / aMin) + 1.5 * Math.min(2.0, dev * dev);
      }
    }
    let hasProtein = false, hasVeg = false;
    for (const [f, q] of items) {
      if (isPoor(f, q)) s -= 2.0;
      if (f.additive) s -= 1.0;
      if (today.food_ids.has(f.id)) s -= 1.0;
      if (otherInFamily(today, f)) s -= 0.75;
      if (R.PROTEIN_ROLES.has(f.role)) hasProtein = true;
      if (f.role === 'veg_fruit') hasVeg = true;
    }
    if (hasProtein) s += 1.0;
    if (hasVeg) s += 0.5;
    s -= 1.0 - scale;
    return R.roundScore(s);
  }

  GE.score = { habitStats, todayStats, staticTerm, Scorer, newCounter, foodOrderKey, portionKey, mealTotals, checkMeal, isPoor,
    scoreMeal, otherInFamily };
})(typeof window !== 'undefined' ? window : globalThis);
