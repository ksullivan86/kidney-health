/* Kidney Diet Log — meal guidance, part 7 of 9: "Plan the rest of my day". Twin of
   app/guidance/planner.py (note 06 §4.7). Computes only, writes nothing.

   Slots are filled in order; each slot's room uses the slots still to fill and the items already placed
   (virtual planned entries). Options: saved meals, usual meals, starter combos, and a meal built by beam
   search (protein → starch → vegetable or fruit; one item for the snack slot). A familiar option wins
   within FAMILIAR_MARGIN of the best built one. Then the whole-day repair, the protein top-up and the
   energy note. Plain script; needs swaps.js. */
(function (root) {
  'use strict';
  const KH = root.KH || (root.KH = {});
  const GE = KH.guidanceEngine;
  const { R, M } = GE;
  const B = GE.budget;
  const S = GE.score;
  const F = GE.fits;
  const { NUTRIENT_KEYS, roundNutrients, roundValue, dailyStatus, buildAlerts } = KH.rules;

  const LEVEL_RANK = { green: 0, yellow: 1, red: 2 };

  // nutrients.daily_status / build_projected_alerts exactly as the engine returns them: "min" only for a range
  // (the API's response model adds "min": null and "meal": null; js/mock/guidance.js does the same).
  function engineStatus(totals, targets, warn) {
    const status = dailyStatus(totals, targets, warn);
    for (const item of Object.values(status)) if (item.min === null) delete item.min;
    return status;
  }
  function projectedAlerts(status) {
    return buildAlerts(status, true).map(({ level, nutrient, message }) => ({ level, nutrient, message }));
  }

  // ---- candidate pools ---------------------------------------------------------------------------
  function buildPools(ctx, habit, today, poolSize) {
    const pools = {};
    for (const role of R.ROLES) pools[role] = [];
    for (const f of F.eligibleFoods(ctx)) pools[f.role].push(f);
    for (const role of Object.keys(pools)) {
      pools[role] = R.sortBy(pools[role], (f) => [LEVEL_RANK[f.level1], -S.staticTerm(f, habit, today),
        f.k != null ? f.k : Infinity, f.name_fold, f.id]).slice(0, poolSize);
    }
    return pools;
  }
  function stepCandidates(scorer, pool, proteinStep) {
    const portions = proteinStep ? R.PORTIONS_BUILD_PROTEIN : R.PORTIONS_BUILD;
    const best = [];
    for (const f of pool) {
      const [ev] = scorer.bestPortion(f, portions);
      if (ev != null) best.push(ev);
    }
    return R.sortBy(best, S.foodOrderKey).slice(0, R.PER_ROLE);
  }

  // ---- beam search -------------------------------------------------------------------------------
  function itemsKey(items) { return items.map(([f, q]) => [f.id, q]); }
  function idOf(items) { return items.map(([f, q]) => `${f.id}:${q}`).join('|'); }
  function built(items, score, kTotal) { return { items, score, k_total: kTotal, key: itemsKey(items) }; }
  function sumCarbs(items) { let s = 0; for (const [f, q] of items) s += (f.carbs || 0.0) * q; return s; }
  function sumK(items) { let s = 0; for (const [f, q] of items) s += (f.k || 0.0) * q; return s; }

  function portions(ev, items, room) {
    const out = [ev.servings, 0.5, 1.0];
    const f = ev.food;
    if (room.carbs != null && f.carbs && f.carbs > 0) {
      const missing = room.carbs.gap - sumCarbs(items);
      if (missing > room.carbs.tolerance) out.push(R.clamp(R.roundToQuarter(missing / f.carbs), R.PORTION_MIN, R.PORTION_MAX));
    }
    const seen = [];
    for (const q of out) if (!seen.includes(q)) seen.push(q);
    return seen;
  }
  function rank(states) { return R.sortBy([...states], (b) => [-b.score, b.k_total, b.key]); }

  function beamBuild(room, scorer, today, dialysis, steps, beamWidth, counter, { snack = false, relaxed = false } = {}) {
    const empty = built([], S.scoreMeal([], room, today, dialysis, 1.0, counter), 0.0);
    let beam = [empty];
    steps.forEach((candidates, index) => {
      const children = new Map();
      for (const state of beam) {
        const hasMixed = state.items.some(([f]) => f.role === 'mixed');
        if (!snack && index === 1 && hasMixed) continue; // a mixed dish fills the starch step
        const ids = new Set(state.items.map(([f]) => f.id));
        for (const ev of candidates) {
          if (ids.has(ev.food.id)) continue;
          for (const q of portions(ev, state.items, room)) {
            const items = [...state.items, [ev.food, q]];
            const key = idOf(items);
            if (children.has(key)) continue;
            const totals = S.mealTotals(items);
            if (!relaxed && !S.checkMeal(items, room, 'built', totals).ok) continue;
            children.set(key, built(items, S.scoreMeal(items, room, today, dialysis, 1.0, counter, totals), totals[0][R.K]));
          }
        }
      }
      beam = rank([...beam, ...children.values()]).slice(0, beamWidth);
    });
    const finals = beam.filter((b) => b.items.length).map((b) => fineTune(b, room, today, dialysis, counter, relaxed));
    const unique = new Map();
    for (const b of finals) { const id = idOf(b.items); if (!unique.has(id)) unique.set(id, b); }
    return rank(unique.values());
  }

  function fineTune(b, room, today, dialysis, counter, relaxed) {
    if (room.carbs == null) return b;
    const idx = b.items.findIndex(([f]) => f.role === 'starch' && f.carbs);
    if (idx < 0) return b;
    const [f, q0] = b.items[idx];
    const others = sumCarbs(b.items) - (f.carbs || 0.0) * q0;
    let bestQ = q0, bestD = Math.abs(others + (f.carbs || 0.0) * q0 - room.carbs.gap);
    let q = R.PORTION_MIN;
    while (q <= R.PORTION_MAX + 1e-9) {
      const d = Math.abs(others + (f.carbs || 0.0) * q - room.carbs.gap);
      if (d < bestD - 1e-9 || (Math.abs(d - bestD) <= 1e-9 && q < bestQ)) {
        const items = [...b.items.slice(0, idx), [f, q], ...b.items.slice(idx + 1)];
        if (relaxed || S.checkMeal(items, room, 'built').ok) { bestQ = q; bestD = d; }
      }
      q += 0.25;
    }
    if (bestQ === q0) return b;
    const items = [...b.items.slice(0, idx), [f, bestQ], ...b.items.slice(idx + 1)];
    return built(items, S.scoreMeal(items, room, today, dialysis, 1.0, counter), sumK(items));
  }

  // ---- the plan ----------------------------------------------------------------------------------
  function slotPlan(meal, room, status, extra = {}) {
    return { meal, room, status, source: null, name: null, template_id: null, scale: 1.0, score: null, items: null, reason: null,
      closest: null, today: null, modified: false, ...extra };
  }
  const isBuilt = (plan) => plan.source === 'built';

  function defaultSlots(ctx) { const used = new Set(ctx.day.map((e) => e.meal)); return R.SLOT_ORDER.filter((m) => !used.has(m)); }
  function dayWith(ctx, plans) {
    const extra = [];
    for (const p of plans) if (p.items) for (const [f, q] of p.items) extra.push(R.virtualEntry(f, p.meal, q));
    return [...ctx.day, ...extra];
  }
  function dayTotals12(day) {
    const totals = {};
    for (const k of NUTRIENT_KEYS) totals[k] = 0.0;
    for (const e of day) for (const k of NUTRIENT_KEYS) { const v = e.nutrients[k]; if (v != null) totals[k] += v; }
    return totals;
  }

  function familiarOptions(ctx, slot, room, today, counter, useSaved, useUsual, useStarters) {
    let options = [];
    if (useSaved) {
      for (const [templateId, name, items] of F.savedMealsFor(ctx, slot)) {
        const opt = F.familiarOption(ctx, room, today, items, { kind: 'saved', name, templateId, counter, detail: false });
        if (opt != null) options.push(opt);
      }
    }
    if (useUsual) {
      for (const [name, items] of F.usualMealsFor(ctx, slot)) {
        const opt = F.familiarOption(ctx, room, today, items, { kind: 'usual', name, templateId: null, counter, detail: false });
        if (opt != null) options.push(opt);
      }
    }
    if (useStarters) {
      for (const combo of ctx.combos) {
        if (combo.meal !== slot) continue;
        const items = F.resolveItems(ctx, combo.items);
        if (!items || !items.length || items.some(([f]) => f.hidden)) continue;
        const opt = F.familiarOption(ctx, room, today, items, { kind: 'starter', name: combo.name, templateId: null, counter, detail: false });
        if (opt != null) options.push(opt);
      }
    }
    options = R.sortBy(options, (o) => [-o.score, o._k, R.casefold(o.name)]);
    return options;
  }
  function fromFamiliar(slot, room, opt) {
    return slotPlan(slot, room, 'ok', { source: opt.source, name: opt.name, template_id: opt.template_id, scale: opt.scale,
      score: opt.score, items: [...opt._items] });
  }

  function planSlot(ctx, slot, openMeals, habit, pools, counter, { useSaved, useUsual, useStarters, variant, forced = null }) {
    const totals = B.dayTotals(ctx.day);
    const room = B.mealRoom(ctx, slot, openMeals, totals);
    const today = S.todayStats(ctx.day);
    const scorer = new S.Scorer(room, habit, today, counter);
    const dialysis = ctx.profile.dialysis !== 'none';
    const snack = slot === R.SNACK;
    let steps;
    if (snack) {
      let candidates = [];
      for (const role of R.SNACK_ROLES) candidates = candidates.concat(stepCandidates(scorer, pools[role] || [], false));
      steps = [R.sortBy(candidates, S.foodOrderKey)];
    } else {
      steps = [
        stepCandidates(scorer, [...(pools.protein || []), ...(pools.mixed || [])], true),
        stepCandidates(scorer, pools.starch || [], false),
        stepCandidates(scorer, pools.veg_fruit || [], false),
      ];
    }
    const width = Math.max(R.BEAM_WIDTH_RANGE[0], Math.min(Math.trunc(ctx.tunables.beam_width), R.BEAM_WIDTH_RANGE[1]));
    const builtMeals = beamBuild(room, scorer, today, dialysis, steps, width, counter, { snack });
    const familiar = familiarOptions(ctx, slot, room, today, counter, useSaved, useUsual, useStarters);

    const builtChoices = builtMeals.length ? builtMeals.slice(Math.min(variant, builtMeals.length - 1)) : [];
    const bestBuilt = builtChoices.length ? builtChoices[0] : null;
    const bestFamiliar = familiar.length ? familiar[0] : null;
    let chosen = null;
    if (bestFamiliar != null && (bestBuilt == null || bestFamiliar.score >= bestBuilt.score - R.FAMILIAR_MARGIN)) {
      chosen = fromFamiliar(slot, room, bestFamiliar);
    } else if (bestBuilt != null) {
      chosen = slotPlan(slot, room, 'ok', { source: 'built', score: bestBuilt.score, items: [...bestBuilt.items] });
    }
    if (chosen != null) {
      let others = familiar.map((o) => fromFamiliar(slot, room, o));
      others = others.concat(builtChoices.map((b) => slotPlan(slot, room, 'ok', { source: 'built', score: b.score, items: [...b.items] })));
      others = R.sortBy(others, (o) => [-(o.score || 0.0), o.source !== 'built' ? 0 : 1, sumK(o.items || [])]);
      const options = [chosen];
      const seen = new Set([idOf(chosen.items || [])]);
      for (const o of others) {
        const key = idOf(o.items || []);
        if (!seen.has(key)) { seen.add(key); options.push(o); }
        if (options.length >= R.AI_PLAN_OPTIONS_MAX) break;
      }
      if (forced != null && forced >= 0 && forced < options.length) chosen = options[forced];
      return [chosen, options];
    }
    // Nothing fits: the closest built meal (no room check) at its best scale.
    let relaxed = beamBuild(room, scorer, today, dialysis, steps, width, counter, { snack, relaxed: true });
    if (!relaxed.length) {
      const roles = snack ? R.SNACK_ROLES : R.MAIN_ROLE_STEPS;
      const fallback = [];
      for (const role of roles) {
        const pool = [...(pools[role] || []), ...(role === 'protein' ? (pools.mixed || []) : [])];
        if (pool.length) {
          fallback.push([pool[0], 1.0]);
          if (snack) break;
        }
      }
      if (fallback.length) relaxed = [built(fallback, S.scoreMeal(fallback, room, today, dialysis, 1.0, counter), sumK(fallback))];
    }
    let closest = null, reason = null;
    if (relaxed.length) {
      const mealItems = [...relaxed[0].items];
      for (const scale of R.SAVED_MEAL_SCALES) {
        const scaledItems = mealItems.map(([f, q]) => [f, q * scale]);
        const check = S.checkMeal(scaledItems, room, 'built');
        if (check.ok) {
          const plan = slotPlan(slot, room, 'ok', { source: 'built', score: S.scoreMeal(scaledItems, room, today, dialysis, 1.0, counter), items: scaledItems });
          return [plan, [plan]];
        }
        if (reason == null) reason = check.reason;
      }
      const scale = R.SAVED_MEAL_SCALES[R.SAVED_MEAL_SCALES.length - 1];
      const scaledItems = mealItems.map(([f, q]) => [f, q * scale]);
      const totalsC = S.mealTotals(scaledItems)[0];
      closest = { scale, items: scaledItems.map(([f, q]) => F.foodCore(f, q)), totals: F.totalsJson(totalsC, room),
        reason: S.checkMeal(scaledItems, room, 'built').reason };
    }
    return [slotPlan(slot, room, 'no_fit', { reason: reason || 'no_candidates', closest }), []];
  }

  function repair(ctx, plans, before) {
    const targets = ctx.profile.targets, warn = ctx.profile.warn_fraction;
    for (let step = 0; step < R.REPAIR_STEPS + 1; step++) {
      const status = engineStatus(dayTotals12(dayWith(ctx, plans)), targets, warn);
      const newOver = R.DAY_JUDGED.filter((k) => (status[k] || {}).level === 'over' && (before[k] || {}).level !== 'over');
      if (!newOver.length) return;
      const key = newOver[0];
      let best = null;
      plans.forEach((plan, pi) => {
        if (!isBuilt(plan) || !plan.items || !plan.items.length) return;
        plan.items.forEach(([f, q], ii) => {
          const v = f.nutrients[key];
          const amount = (v || 0.0) * q;
          if (amount > 0 && (best == null || amount > best[0])) best = [amount, pi, ii];
        });
      });
      if (best == null || step === R.REPAIR_STEPS) {
        for (const plan of plans) {
          if (plan.items && plan.items.length && plan.items.some(([f]) => (f.nutrients[key] || 0.0) > 0)) {
            plan.status = 'partial';
            plan.reason = `day_over:${key}`;
          }
        }
        return;
      }
      const [, pi, ii] = best;
      const plan = plans[pi];
      const [f, q] = plan.items[ii];
      const q2 = q - R.REPAIR_STEP;
      if (q2 < R.PORTION_MIN - 1e-9) plan.items.splice(ii, 1);
      else plan.items[ii] = [f, q2];
      plan.reason = `reduced:${key}`;
      plan.modified = true;
    }
  }

  function proteinTopup(ctx, plans, before) {
    const minimum = R.targetMin(ctx.profile.targets[R.PROTEIN]);
    if (minimum == null) return [];
    const grown = [];
    const targets = ctx.profile.targets, warn = ctx.profile.warn_fraction;
    for (const plan of [...plans].reverse()) {
      if (plan.meal === R.SNACK || !isBuilt(plan) || !plan.items || !plan.items.length) continue;
      for (let step = 0; step < R.PROTEIN_TOPUP_STEPS; step++) {
        const protein = dayTotals12(dayWith(ctx, plans))[R.PROTEIN];
        if (protein >= minimum) return grown;
        const idx = plan.items.findIndex(([f]) => R.PROTEIN_ROLES.has(f.role));
        if (idx < 0) break;
        const [f, q] = plan.items[idx];
        const items = [...plan.items];
        items[idx] = [f, q + R.PROTEIN_TOPUP_STEP];
        if (!S.checkMeal(items, plan.room, 'built').ok) break;
        const old = plan.items;
        plan.items = items;
        const status = engineStatus(dayTotals12(dayWith(ctx, plans)), targets, warn);
        if (R.DAY_JUDGED.some((k) => (status[k] || {}).level === 'over' && (before[k] || {}).level !== 'over')) { plan.items = old; break; }
        plan.modified = true;
        grown.push(plan.meal);
      }
    }
    return grown;
  }

  function energyNote(ctx, plans) {
    const goal = R.targetMax(ctx.profile.targets[R.KCAL]);
    if (goal == null) return null;
    const day = dayWith(ctx, plans);
    if (day.some((e) => e.nutrients[R.KCAL] == null)) return null;
    let kcal = 0;
    for (const e of day) kcal += e.nutrients[R.KCAL] || 0.0;
    if (kcal >= R.ENERGY_NOTE_FRACTION * goal) return null;
    let foods = [];
    for (const f of ctx.foods.values()) {
      if (f.hidden || f.avoid || f.hypo || f.supplies || ctx.prefs.exclude_food_ids.has(f.id)) continue;
      if (f.kcal == null || f.kcal < R.ENERGY_DENSE_MIN_KCAL) continue;
      const pairs = [[R.K, f.k], [R.P, f.p], [R.NA, f.na], [R.CARBS, f.carbs]];
      if (pairs.every(([k, v]) => v != null && v <= R.ENERGY_DENSE_MAX[k])) foods.push(f);
    }
    foods = R.sortBy(foods, (f) => [-(f.kcal || 0.0), f.name_fold, f.id]);
    return { kcal: roundNutrients({ [R.KCAL]: kcal })[R.KCAL], goal: roundNutrients({ [R.KCAL]: goal })[R.KCAL],
      text: M.energyNoteText(kcal, goal), foods: foods.slice(0, R.ENERGY_NOTE_FOODS).map((f) => F.foodCore(f, 1.0)), handbook: 'eating-enough' };
  }

  function why(plan) {
    if (!plan.items || !plan.items.length) return [];
    const totals = S.mealTotals(plan.items)[0];
    const out = [];
    if (plan.room.carbs != null) {
      const c = plan.room.carbs;
      out.push(M.planWhyCarbs(totals[R.CARBS], c.goal, plan.meal, c.gap, c.tolerance));
    }
    for (const key of [R.K, R.P, R.NA, R.FLUID]) {
      const item = plan.room.nutrients[key];
      if (item != null) { out.push(M.planWhyRoom(totals[key], item.room, plan.meal, key)); break; }
    }
    return out;
  }

  function planJson(ctx, plan) {
    const items = plan.items || [];
    const out = {
      meal: plan.meal, status: plan.status, source: plan.source, name: plan.name, template_id: plan.template_id, scale: plan.scale,
      score: plan.score, items: items.map(([f, q]) => F.foodCore(f, q)),
      totals: items.length ? F.totalsJson(S.mealTotals(items)[0], plan.room) : null,
      why: why(plan), room: F.roomJson(plan.room), reason: plan.reason,
    };
    if (plan.status === 'no_fit') {
      const reason = plan.reason || '';
      const key = reason.startsWith('would_exceed:') ? reason.slice(reason.indexOf(':') + 1) : R.K;
      const item = plan.room.nutrients[key];
      const roomLeft = item != null ? item.room : 0.0;
      out.message = M.noFitText(plan.meal, item != null ? key : R.K, roomLeft);
      out.closest = plan.closest;
    } else if (plan.status === 'partial' && plan.reason && plan.reason.includes(':')) {
      out.message = M.partialText(plan.meal, plan.reason.slice(plan.reason.indexOf(':') + 1));
    }
    return out;
  }

  // Plan the requested slots (default: every slot with no entries) of ctx.date.
  function planDay(ctx, meals = null, { useSavedMeals = true, useUsual = true, useStarters = true, variant = 0, counter = null,
    forced = null, withOptions = false } = {}) {
    counter = counter || S.newCounter();
    const slots = meals && meals.length ? R.SLOT_ORDER.filter((m) => meals.includes(m)) : defaultSlots(ctx);
    variant = Math.max(0, Math.min(Math.trunc(variant), R.VARIANT_MAX));
    const targets = ctx.profile.targets, warn = ctx.profile.warn_fraction;
    const before = engineStatus(dayTotals12(ctx.day), targets, warn);
    const habit = S.habitStats(ctx);
    const poolSize = Math.max(R.POOL_PER_ROLE_RANGE[0], Math.min(Math.trunc(ctx.tunables.pool_per_role), R.POOL_PER_ROLE_RANGE[1]));
    const pools = buildPools(ctx, habit, S.todayStats(ctx.day), poolSize);
    const plans = [];
    const slotOptions = {};
    slots.forEach((slot, i) => {
      const ctxI = R.withDay(ctx, dayWith(ctx, plans));
      const [plan, options] = planSlot(ctxI, slot, slots.slice(i), habit, pools, counter, { useSaved: useSavedMeals, useUsual,
        useStarters, variant, forced: forced && slot in forced ? forced[slot] : null });
      plan.today = S.todayStats(ctxI.day);
      plans.push(plan);
      slotOptions[slot] = options;
    });
    repair(ctx, plans, before);
    const grown = proteinTopup(ctx, plans, before);
    const dialysis = ctx.profile.dialysis !== 'none';
    for (const plan of plans) {
      if (plan.modified && plan.items && plan.items.length && plan.today != null) {
        plan.score = S.scoreMeal(plan.items, plan.room, plan.today, dialysis, 1.0, counter);
      }
    }
    const projected = dayTotals12(dayWith(ctx, plans));
    const after = engineStatus(projected, targets, warn);
    const wasOver = new Set(projectedAlerts(before).filter((a) => a.level === 'over').map((a) => a.nutrient));
    const newAlerts = projectedAlerts(after).filter((a) => a.level === 'over' && !wasOver.has(a.nutrient));
    const entries = [];
    for (const p of plans) {
      if (!p.items) continue;
      for (const [f, q] of p.items) entries.push({ date: ctx.date, meal: p.meal, food_id: f.id, servings: R.roundTo(q, 3), status: 'planned', purpose: 'none' });
    }
    const mealsJson = plans.map((p) => {
      const item = planJson(ctx, p);
      if (p.source === 'saved' && p.template_id != null) {
        item.apply_saved = { endpoint: `/api/meals/${p.template_id}/apply`, body: { date: ctx.date, meal: p.meal, status: 'planned', scale: p.scale } };
      }
      return item;
    });
    const result = {
      status: 'ok', rules_version: R.RULES_VERSION, date: ctx.date, variant, meals: mealsJson, protein_topup: grown,
      day_after: { projected_totals: roundNutrients(projected), projected_status: after, new_alerts: newAlerts },
      energy_note: energyNote(ctx, plans), apply: { endpoint: '/api/log/batch', entries }, notes: [M.DISCLAIMER],
    };
    if (withOptions) {
      result.options = {};
      for (const [slot, opts] of Object.entries(slotOptions)) result.options[slot] = opts.map((o) => planJson(ctx, o));
    }
    return result;
  }

  GE.planner = { buildPools, stepCandidates, beamBuild, fineTune, defaultSlots, dayWith, dayTotals12, planSlot, repair,
    proteinTopup, energyNote, planJson, planDay, engineStatus, projectedAlerts, roundValue };
})(typeof window !== 'undefined' ? window : globalThis);
