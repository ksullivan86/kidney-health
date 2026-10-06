/* Kidney Diet Log — meal guidance, part 5 of 9: "What fits now", saved and usual meals that fit, the
   JSON helpers shared with swaps and the planner. Twin of app/guidance/fits.py (note 06 §4.5).
   Plain script; needs score.js and messages.js. */
(function (root) {
  'use strict';
  const KH = root.KH || (root.KH = {});
  const GE = KH.guidanceEngine;
  const { R, M, T } = GE;
  const B = GE.budget;
  const S = GE.score;
  const { roundValue, roundNutrients, evaluateWarnings } = KH.rules;

  // ---- eligibility -------------------------------------------------------------------------------
  function ineligibleReason(f, ctx) {
    if (f.hidden) return 'hidden';
    if (f.avoid) return 'avoid_ckd';
    if (f.hypo) return 'hypo_treatment';
    if (f.ingredient) return 'ingredient';
    if (f.supplies) return 'diabetes_supplies';
    if (ctx.prefs.exclude_food_ids.has(f.id)) return 'not_for_me';
    if (ctx.prefs.exclude_categories.has(f.category || '')) return 'excluded_category';
    return null;
  }
  function eligibleForMeals(f, ctx) {
    return !(f.hidden || f.avoid || f.hypo || f.ingredient || f.supplies
      || ctx.prefs.exclude_food_ids.has(f.id) || ctx.prefs.exclude_categories.has(f.category || ''));
  }
  function eligibleFoods(ctx) { const out = []; for (const f of ctx.foods.values()) if (eligibleForMeals(f, ctx)) out.push(f); return out; }

  // ---- JSON helpers ------------------------------------------------------------------------------
  const scaled = R.scaledValues;
  function gramsOf(f, q) { return roundValue('carbs_g', f.serving_g * q) || 0.0; }
  function foodCore(f, q) {
    const values = scaled(f, q);
    const warnings = evaluateWarnings(values, [...f.flags], f.kidney_notes, 'in this portion');
    return {
      food_id: f.id, name: f.name, group: f.group, role: f.role, servings: q, serving_desc: f.serving_desc, grams: gramsOf(f, q),
      portion_text: M.portionText(q, f.serving_desc), nutrients: roundNutrients(values), warnings,
      renal_rating: R.renalLevel(values[R.K], values[R.P], values[R.NA], f.additive),
    };
  }
  function trackedKeys(room) { return [R.K, R.P, R.NA, R.FLUID].filter((k) => k in room.nutrients); }
  function roomJson(room) {
    const out = {};
    for (const key of [R.K, R.P, R.NA, R.FLUID]) {
      const item = room.nutrients[key];
      if (item == null) { out[key] = null; continue; }
      out[key] = { room: roundValue(key, item.room), cap: item.cap === Infinity ? null : roundValue(key, item.cap),
        share: roundValue(key, item.share), in_meal: roundValue(key, item.in_meal), remaining_today: roundValue(key, item.remaining),
        allowance_today: roundValue(key, item.allowance), level: item.level, basis: item.basis };
    }
    if (room.carbs != null) {
      const c = room.carbs;
      out[R.CARBS] = { goal: roundValue(R.CARBS, c.goal), in_meal: roundValue(R.CARBS, c.in_meal), gap: roundValue(R.CARBS, c.gap),
        tolerance: roundValue(R.CARBS, c.tolerance), hypo_excluded_g: roundValue(R.CARBS, c.hypo_excluded) };
    } else out[R.CARBS] = null;
    out[R.PROTEIN] = room.protein != null
      ? { aim: roundValue(R.PROTEIN, room.protein.aim), aim_min: roundValue(R.PROTEIN, room.protein.aim_min) } : null;
    return out;
  }
  function totalsJson(totals, room = null) {
    const keys = [R.CARBS, R.PROTEIN, R.K, R.P, R.NA];
    if (room != null && R.FLUID in room.nutrients) keys.push(R.FLUID);
    const out = {};
    for (const k of keys) out[k] = roundValue(k, k in totals ? totals[k] : 0.0);
    return out;
  }

  // ---- reasons -----------------------------------------------------------------------------------
  const REASON_TOPIC = { fills_carbs: 'carb-counting', low_potassium: 'potassium', low_phosphorus: 'phosphorus',
    protein_quality: 'protein', free_food: 'carb-counting', half_portion: 'portions' };
  const GROUP_TOPIC = { protein: 'protein', starch: 'carb-counting', veg_fruit: 'potassium', extra: 'portions' };

  function reasonsFor(ev, scorer, room, standard, habit) {
    const f = ev.food, q = ev.servings;
    const meal = room.meal;
    const amounts = scaled(f, q);
    const candidates = [];
    const group = f.group;
    const missing = (R.PROTEIN_ROLES.has(f.role) && !room.meal_has.protein)
      || (R.STARCH_ROLES.has(f.role) && !room.meal_has.starch)
      || (f.role === 'veg_fruit' && !room.meal_has.veg_fruit);
    if (missing) {
      const g = R.PROTEIN_ROLES.has(f.role) ? 'protein' : group;
      candidates.push(['adds_missing_group', M.reasonText('adds_missing_group', { group: R.GROUP_LABEL[g], meal }), GROUP_TOPIC[g] || null]);
    }
    const ac = amounts[R.CARBS];
    const gap = B.gapOf(room), tol = B.toleranceOf(room);
    if (room.carbs != null && ac != null && gap > tol && R.CARB_FILL_ROLES.has(f.role) && ac >= R.FILLS_CARBS_MIN_G) {
      const after = room.carbs.in_meal + ac;
      candidates.push(['fills_carbs', M.reasonText('fills_carbs', { meal, after: M.fmtG(after), goal: M.fmtG(room.carbs.goal) }), REASON_TOPIC.fills_carbs]);
    }
    const ak = amounts[R.K], ap = amounts[R.P];
    if (ak != null && ak <= R.LOW_K_REASON_MG) candidates.push(['low_potassium', M.reasonText('low_potassium', { k: M.fmtInt(ak) }), REASON_TOPIC.low_potassium]);
    if (ap != null && ap <= R.LOW_P_REASON_MG) candidates.push(['low_phosphorus', M.reasonText('low_phosphorus', { p: M.fmtInt(ap) }), REASON_TOPIC.low_phosphorus]);
    const apr = amounts[R.PROTEIN];
    const quality = R.proteinQuality(apr, ak, ap);
    if (R.PROTEIN_ROLES.has(f.role) && quality.p_grade === 'good') {
      candidates.push(['protein_quality', M.reasonText('protein_quality', { protein: M.fmtG(apr), ratio: M.fmtInt(quality.p_per_g) }), REASON_TOPIC.protein_quality]);
    }
    if ((habit.days_14.get(f.id) || 0) >= R.OFTEN_MIN_DAYS) candidates.push(['you_eat_often', M.reasonText('you_eat_often'), null]);
    if (room.carbs != null && ac != null && gap <= tol && ac <= R.FREE_FOOD_CARBS_G) {
      candidates.push(['free_food', M.reasonText('free_food', { carbs: M.fmtG(ac) }), REASON_TOPIC.free_food]);
    }
    if (q === 0.5 && standard != null && standard.score == null && standard.why_not) {
      const i = standard.why_not.indexOf(':');
      const key = i >= 0 ? standard.why_not.slice(i + 1) : R.CARBS;
      const word = M.NUTRIENT_WORD[key] || 'carbs';
      candidates.push(['half_portion', M.reasonText('half_portion', { nutrient: word, meal }), REASON_TOPIC.half_portion]);
    }
    const positive = candidates.slice(0, 2);
    const reasons = positive.map(([c, t]) => ({ code: c, text: t }));
    const slugs = positive.map((p) => p[2]).filter((s) => s);
    if (ev.unknown.length) {
      const key = ev.unknown[0];
      reasons.push({ code: `unknown:${key}`, text: M.reasonText('unknown', { Nutrient: M.capitalise(M.NUTRIENT_WORD[key]) }) });
      slugs.push('label-reading');
    }
    const seen = [];
    for (const s of slugs) if (!seen.includes(s)) seen.push(s);
    return [reasons, seen];
  }

  // ---- tips --------------------------------------------------------------------------------------
  function dayTips(ctx, room) {
    const out = [];
    const dialysis = ctx.profile.dialysis !== 'none';
    const pctOf = (item) => (item.allowance > 0 ? M.pct(item.projected / item.allowance) : 100);
    for (const t of T.TIPS) {
      let values = null;
      if (t.when === 'potassium_not_ok') {
        const item = room.nutrients[R.K];
        if (item != null && item.level !== 'ok') values = { pct: pctOf(item) };
      } else if (t.when === 'phosphorus_week_not_ok') {
        const item = room.nutrients[R.P];
        if (item != null && item.level !== 'ok') values = { pct: pctOf(item) };
      } else if (t.when === 'sodium_caution') {
        const item = room.nutrients[R.NA];
        if (item != null && item.level !== 'ok') values = { pct: pctOf(item) };
      } else if (t.when === 'fluid_caution_dialysis') {
        const item = room.nutrients[R.FLUID];
        if (dialysis && item != null && item.level !== 'ok') values = { pct: pctOf(item) };
      } else if (t.when === 'dialysis_protein_low') {
        const p = room.protein;
        if (dialysis && p != null && p.minimum != null && p.projected < p.minimum) values = { value: M.fmtG(p.projected), min: M.fmtG(p.minimum) };
      } else if (t.when === 'meal_carbs_done') {
        const c = room.carbs;
        if (c != null && c.in_meal > 0 && c.gap <= c.tolerance) values = { Meal: M.capitalise(room.meal), carbs: M.fmtG(c.in_meal), goal: M.fmtG(c.goal) };
      }
      if (values != null) out.push(T.tipJson(t, values));
      if (out.length >= 2) break;
    }
    return out;
  }

  // ---- saved and usual meals ---------------------------------------------------------------------
  function resolveItems(ctx, items) {
    const out = [];
    for (const [foodId, servings] of items) {
      const f = ctx.foods.get(foodId);
      if (f == null) return null;
      out.push([f, Number(servings)]);
    }
    return out;
  }
  function bestScale(items, room, kind) {
    let firstReason = null;
    for (const scale of R.SAVED_MEAL_SCALES) {
      const check = S.checkMeal(items.map(([f, q]) => [f, q * scale]), room, kind);
      if (check.ok) return [scale, firstReason];
      if (firstReason == null) firstReason = check.reason;
    }
    return [null, firstReason];
  }
  function familiarOption(ctx, room, today, items, { kind, name, templateId, counter = null, detail = true }) {
    if (items.some(([f]) => f.avoid)) return null;
    const [scale, reason] = bestScale(items, room, kind);
    if (scale == null) return null;
    const scaledItems = items.map(([f, q]) => [f, q * scale]);
    const score = S.scoreMeal(scaledItems, room, today, ctx.profile.dialysis !== 'none', scale, counter);
    const totals = S.mealTotals(scaledItems)[0];
    const option = { template_id: templateId, name, source: kind, scale, score, _items: scaledItems, _k: roundValue(R.K, totals[R.K]) || 0 };
    if (!detail) return option;
    let limiting = null;
    if (reason && reason.startsWith('would_exceed:')) {
      const key = reason.slice(reason.indexOf(':') + 1);
      const item = room.nutrients[key];
      if (item != null) limiting = [key, item.room, item.basis];
    }
    const goal = room.carbs != null ? room.carbs.goal : null;
    option.items = scaledItems.map(([f, q]) => ({ food_id: f.id, name: f.name, servings: R.roundTo(q, 3) }));
    option.totals = totalsJson(totals, room);
    option.note = M.savedMealNote(scale, totals[R.CARBS], B.gapOf(room), goal, room.meal, limiting);
    return option;
  }
  function savedMealsFor(ctx, meal) {
    const out = [];
    for (const m of ctx.saved_meals) {
      if (m.meal_hint === meal || (m.meal_hint == null && R.MAIN_MEALS.includes(meal))) {
        const items = resolveItems(ctx, m.items);
        if (items && items.length) out.push([m.id, m.name, items]);
      }
    }
    return out;
  }
  function shortNames(names) {
    const heads = names.map((n) => R.casefold(M.safeName(n).split(',')[0].trim()));
    return names.map((name, i) => (heads.filter((h) => h === heads[i]).length > 1 ? R.casefold(M.safeName(name)) : heads[i]));
  }
  function usualMealsFor(ctx, meal) {
    const byDay = new Map();
    for (const h of ctx.history60) {
      if (h.meal !== meal || h.hypo) continue;
      let foods = byDay.get(h.date);
      if (!foods) byDay.set(h.date, (foods = new Map()));
      foods.set(h.food_id, (foods.get(h.food_id) || 0.0) + h.servings);
    }
    const counts = new Map();
    for (const foods of byDay.values()) {
      const key = R.sortBy([...foods.entries()].map(([fid, s]) => [fid, R.roundToQuarter(s)]), (x) => x);
      if (key.length >= R.USUAL_MIN_ITEMS && key.length <= R.USUAL_MAX_ITEMS && key.every(([, q]) => q > 0)) {
        const id = JSON.stringify(key);
        const c = counts.get(id);
        if (c) c[1] += 1; else counts.set(id, [key, 1]);
      }
    }
    const out = [];
    for (const [key, n] of R.sortBy([...counts.values()], ([k, c]) => [-c, k])) {
      if (n < R.USUAL_MIN_DATES) continue;
      let items = resolveItems(ctx, key);
      if (!items || !items.length || items.some(([f]) => f.hidden)) continue;
      items = R.sortBy(items, ([f]) => [R.ROLES.indexOf(f.role), f.name_fold, f.id]);
      out.push([M.usualMealName(meal, shortNames(items.map(([f]) => f.name))), items]);
    }
    return out;
  }
  function fittingSavedMeals(ctx, meal, room, today, counter = null, limit = R.SAVED_MEALS_MAX) {
    let options = [];
    for (const [templateId, name, items] of savedMealsFor(ctx, meal)) {
      const opt = familiarOption(ctx, room, today, items, { kind: 'saved', name, templateId, counter });
      if (opt != null) options.push(opt);
    }
    for (const [name, items] of usualMealsFor(ctx, meal)) {
      const opt = familiarOption(ctx, room, today, items, { kind: 'usual', name, templateId: null, counter });
      if (opt != null) options.push(opt);
    }
    options = R.sortBy(options, (o) => [-o.score, R.casefold(o.name), o.template_id || 0]);
    return options.slice(0, limit);
  }
  function publicOption(option) {
    const out = {};
    for (const [k, v] of Object.entries(option)) if (!k.startsWith('_')) out[k] = v;
    return out;
  }

  // ---- what fits now -----------------------------------------------------------------------------
  function rankFoods(ctx, room, scorer, foods, explain = false) {
    let ranked = [];
    const whyNot = new Map();
    for (const f of foods) {
      const [best, standard] = scorer.bestPortion(f, R.portionsFor(f.role), explain);
      if (best == null) { whyNot.set(f.id, standard.why_not || 'no_portion'); continue; }
      ranked.push([best, standard]);
    }
    ranked = R.sortBy(ranked, (pair) => S.foodOrderKey(pair[0]));
    return [ranked, whyNot];
  }
  function select(ranked, limit) {
    const chosen = [];
    const perGroup = {}, perCategory = new Map();
    for (const [best, standard] of ranked) {
      if ((best.score || 0.0) < R.MIN_SHOW_SCORE) break;
      const f = best.food;
      if ((perGroup[f.group] || 0) >= (R.GROUP_LIMITS[f.group] || 0)) continue;
      const cat = f.category || '';
      if ((perCategory.get(cat) || 0) >= R.CATEGORY_LIMIT) continue;
      chosen.push([best, standard]);
      perGroup[f.group] = (perGroup[f.group] || 0) + 1;
      perCategory.set(cat, (perCategory.get(cat) || 0) + 1);
      if (chosen.length >= limit) break;
    }
    return chosen;
  }
  function whatFits(ctx, meal, limit = R.DEFAULT_LIMIT, explain = false, counter = null) {
    counter = counter || S.newCounter();
    const totals = B.dayTotals(ctx.day);
    const room = B.mealRoom(ctx, meal, null, totals);
    const habit = S.habitStats(ctx);
    const today = S.todayStats(ctx.day);
    const scorer = new S.Scorer(room, habit, today, counter);
    const [ranked, whyNot] = rankFoods(ctx, room, scorer, eligibleFoods(ctx), explain);
    const chosen = select(ranked, Math.max(1, Math.min(Math.trunc(limit), R.MAX_LIMIT)));
    const tracked = trackedKeys(room);
    const carbsFirst = room.carbs != null;
    const foods = [];
    for (const [best, standard] of chosen) {
      const item = foodCore(best.food, best.servings);
      const [reasons, slugs] = reasonsFor(best, scorer, room, standard, habit);
      item.score = best.score;
      item.fit_text = M.fitText(scaled(best.food, best.servings), tracked, carbsFirst);
      item.reasons = reasons;
      item.handbook = T.pages(...slugs);
      if (explain) item.explain = { components: best.components || {} };
      foods.push(item);
    }
    const saved = fittingSavedMeals(ctx, meal, room, today, counter).map(publicOption);
    const rj = roomJson(room);
    const result = {
      status: 'ok', rules_version: R.RULES_VERSION, date: ctx.date, meal, open_meals: [...room.open_meals], room: rj,
      room_text: M.roomLine(meal, { [R.K]: rj[R.K], [R.P]: rj[R.P], [R.NA]: rj[R.NA], [R.FLUID]: rj[R.FLUID], [R.CARBS]: rj[R.CARBS] }),
      meal_has: { ...room.meal_has }, foods, saved_meals: saved, tips: dayTips(ctx, room), notes: [M.DISCLAIMER],
    };
    if (explain) {
      const notEligible = {};
      for (const f of ctx.foods.values()) { const code = ineligibleReason(f, ctx); if (code != null) notEligible[String(f.id)] = code; }
      const why = {};
      for (const fid of [...whyNot.keys()].sort((a, b) => a - b)) why[String(fid)] = whyNot.get(fid);
      result.explain = { why_not: why, not_eligible: notEligible, evaluations: counter.foods, meal_evaluations: counter.meals,
        eligible: ranked.length + whyNot.size };
    }
    return result;
  }

  GE.fits = { ineligibleReason, eligibleForMeals, eligibleFoods, scaled, gramsOf, foodCore, trackedKeys, roomJson, totalsJson,
    reasonsFor, dayTips, resolveItems, bestScale, familiarOption, savedMealsFor, shortNames, usualMealsFor, fittingSavedMeals,
    publicOption, rankFoods, select, whatFits };
})(typeof window !== 'undefined' ? window : globalThis);
