/* Kidney Diet Log — AI meal ideas and AI recipes on the iPhone app (design note 39 §6.6): browser twins of the server's
   candidate lists, prompt data and checks, so the person's own AI key and the iPhone's own model get exactly what the server's
   AI gets and their answers pass exactly the server's checks.

   Twins (tests/data/gen_guidance_vectors.py writes vectors from the server's code; tests/js/run_vectors.mjs replays them):
   * app/guidance/ai_bridge.py: candidates_for_ai (mode "ideas"), max_quarters, lower_to_fit, validate_ai_items;
   * app/ai/guard.py: true_reasons, true_theme, sentence, check_claims, handbook_refs, judge_ideas, after_room, fallback;
   * app/ai/recipes.py: recipe_ineligible, recipe_candidates, title_for, differences, judge_recipes (cooking steps off: the
     phone never shows steps written by AI, as the server with ai.recipe_steps off, its default);
   * app/ai/prompts.py: candidate_block, meal_budget, targets_block, totals, week_average, person_block, condition_text,
     repeat_ok_block, next_meal_context, recipe_context;
   * app/ai/schemas.py: the V2 checks of IdeasAnswer and RecipesAnswer.
   * app/ai/guard.py judge_rerank, judge_swap, judge_plan with ai_bridge.validate_ai_plan, and prompts.swap_extra, plan_extra
     (AI order, AI swaps and AI day plans; phone-ai-more2, 2026-11-26), with the V2 checks of RerankAnswer, SwapAnswer and PlanAnswer.
   Needs the guidance engine (js/engine/guidance/*.js), textclean.js and aiguard.js.

   KH.aiMeal = { candidatesForAi, maxQuarters, lowerToFit, validateAiItems, judgeIdeas, fallback, recipeCandidates, judgeRecipes,
     nextMealContext, recipeContext, personBlock, conditionText, checkIdeas, checkRecipes, ... } */
(function (root) {
  'use strict';
  const KH = root.KH || (root.KH = {});
  const GE = KH.guidanceEngine;
  const { R, M, T } = GE;
  const B = GE.budget;
  const S = GE.score;
  const F = GE.fits;
  const TC = KH.textclean;
  const { roundValue, pyRound } = KH.rules;

  // ---------------------------------------------------------------------------
  // Constants (the server's; tests/test_phone_ai_more.py compares them)
  // ---------------------------------------------------------------------------
  const THEMES = ['light', 'hearty', 'familiar', 'new_idea'];
  const MODES = ['rerank', 'ideas', 'swap', 'plan'];
  const REASON_CODES = ['low_potassium', 'low_phosphorus', 'low_sodium', 'fits_carb_goal', 'adds_protein', 'adds_missing_group',
    'you_eat_often', 'you_like'];
  const AI_HANDBOOK_SLUGS = ['potassium', 'potassium-leaching', 'phosphorus', 'phosphate-additives', 'sodium', 'fluid', 'protein',
    'eating-enough', 'carb-counting', 'dialysis-days', 'label-reading', 'eating-out', 'portions', 'guidance'];
  const UNTRUSTED_SOURCES = ['custom', 'off'];
  const REFUSED_TEXT = 'This is outside what the app\'s AI helps with. Your care team can answer it.';
  const NO_FIT_TEXT = 'The AI found nothing that fits your targets for this meal, so these are the app\'s own ideas.';
  const PORTION_LOWERED_TEXT = 'The app made a portion smaller so the meal fits your targets.';
  const PORTIONS_LOWERED_TEXT = 'The app made some portions smaller so the meal fits your targets.';
  const NOTICE = (label, model) => `AI idea · ${label} · ${model} · checked against your targets · not medical advice`;
  const HEARTY_KCAL = 450.0;
  const THEME_TITLE = { light: 'A light {meal}', hearty: 'A hearty {meal}', familiar: 'A familiar {meal}', new_idea: 'Something new for {meal}' };
  const REASON_TEXT = {
    low_potassium: 'low in potassium ({k} mg) for what is left today',
    low_phosphorus: 'low in phosphorus ({p} mg)',
    low_sodium: 'low in sodium ({na} mg)',
    fits_carb_goal: 'brings {meal} close to your carbohydrate goal',
    adds_protein: 'adds a protein portion',
    adds_missing_group: 'adds what this {meal} is missing',
    you_eat_often: 'uses foods you often have',
    you_like: 'uses a food you said you like',
  };
  const LOW_SODIUM_PORTION_MG = 140.0;
  const LOW_PORTION_MG = { [R.K]: R.LOW_K_REASON_MG, [R.P]: R.LOW_P_REASON_MG, [R.NA]: LOW_SODIUM_PORTION_MG };
  const NOT_FOR_ME_REASONS = ['not_for_me', 'excluded_category'];
  const IDEA_KEYS = ['theme', 'items', 'reason_codes', 'handbook'];
  const LOWERABLE = ['high_portion_too_large', 'would_exceed:', 'too_many_carbs', 'quarters_out_of_range'];
  const AMOUNT = { [R.K]: 'k', [R.P]: 'p', [R.NA]: 'na', [R.FLUID]: 'fluid', [R.CARBS]: 'carbs' };
  // recipes.py
  const RECIPE_PORTIONS = [0.25, 0.5, 1.0];
  const AI_RECIPE_FOODS_MAX = 48;
  const AI_RECIPE_INGREDIENTS_MIN = 4;
  const COOK_LATER = ['Beverages', 'Sweets & Snacks', 'Prepared & Fast Food'];
  const NEVER_ADD = /\b(?:salt|salt substitutes?|salt replacers?|potassium chloride|lo-?salt|nu-?salt|no-?salt|lite salt)\b/i;
  const RECIPE_NOTICE = (label, model) => `AI recipe · ${label} · ${model} · checked against your targets · not medical advice`;
  const RECIPE_NO_FIT_TEXT = 'The AI found no recipe that fits your targets for this meal.';
  const DROPPED_ALL_TEXT = 'The AI\'s recipes did not fit your targets, so none are shown.';
  const RECIPE_PORTION_LOWERED_TEXT = 'The app made a portion smaller so the recipe fits your targets.';
  const RECIPE_PORTIONS_LOWERED_TEXT = 'The app made some portions smaller so the recipe fits your targets.';
  const FOOD_SWAPPED_TEXT = 'The app changed a food so the recipe fits your targets.';
  const DISH_WORD = { soup: 'soup', stew: 'stew', bowl: 'bowl', stir_fry: 'stir-fry', bake: 'bake', salad: 'salad', sandwich: 'sandwich',
    pasta: 'pasta', rice_dish: 'rice dish', egg_dish: 'egg dish', porridge: 'porridge', snack: 'snack', drink: 'drink' };
  const RECIPE_KEYS = ['dish', 'theme', 'ingredients', 'steps', 'reason_codes'];
  const NAME_MAX = 80;
  const MAX_RECIPES = 2;
  const MIN_RECIPE_ITEMS = 2;
  const MAX_RECIPE_ITEMS = 12;
  const MAX_RECIPE_QUARTERS = 160;
  // prompts.py
  const DAY_JUDGED = ['carbs_g', 'fluid_ml', 'potassium_mg', 'sodium_mg'];
  const WEEK_JUDGED = ['calcium_mg', 'calories_kcal', 'phosphorus_mg', 'protein_g'];
  const TARGET_KEYS = ['calories_kcal', 'protein_g', 'carbs_g', 'carbs_per_meal_g', 'carbs_per_snack_g', 'fiber_g', 'sodium_mg',
    'potassium_mg', 'phosphorus_mg', 'calcium_mg', 'fluid_ml'];
  const MEAL_CARB_KEYS = ['carbs_per_meal_g', 'carbs_per_snack_g'];
  const TOTAL_KEYS = ['carbs_g', 'protein_g', 'potassium_mg', 'phosphorus_mg', 'sodium_mg', 'fluid_ml', 'calories_kcal'];
  const PER_PORTION_KEYS = { carbs: 'carbs_g', potassium: 'potassium_mg', phosphorus: 'phosphorus_mg', sodium: 'sodium_mg',
    fluid: 'fluid_ml', protein: 'protein_g' };
  const SHOWN_FLAGS = ['phosphate_additive', 'potassium_additive', 'high_gi', 'counts_as_fluid', 'processed', 'low_potassium_fruit'];
  const CKD_STAGES = ['1', '2', '3a', '3b', '4', '5'];
  const DIALYSIS_TEXT = { hemodialysis: 'on hemodialysis', peritoneal: 'on peritoneal dialysis' };
  const DIABETES_TEXT = { type1: 'type 1 diabetes', type2: 'type 2 diabetes' };
  const NOT_CHOSEN = 'not chosen yet';
  const MEAL_NAMES = ['breakfast', 'lunch', 'dinner', 'snack'];
  const TASTE_KEYS = ['likes', 'less_often', 'not_for_me'];

  const isDict = (v) => v !== null && typeof v === 'object' && !Array.isArray(v);
  const isInt = (v) => typeof v === 'number' && Number.isInteger(v);
  const unique = (list) => [...new Set(list)];
  const cmpTuple = (a, b) => { for (let i = 0; i < a.length; i += 1) { if (a[i] < b[i]) return -1; if (a[i] > b[i]) return 1; } return 0; };
  const clean = (text, limit = 80) => TC.cleanText(text, { maxLen: limit }) || '';
  const fold = (text) => KH.aiguard.fold(text);

  // ---------------------------------------------------------------------------
  // app/guidance/ai_bridge.py
  // ---------------------------------------------------------------------------
  function perPortion(f, q) {
    const a = F.scaled(f, q);
    const out = {};
    for (const [key, name] of [[R.CARBS, 'carbs'], [R.K, 'potassium'], [R.P, 'phosphorus'], [R.NA, 'sodium'], [R.FLUID, 'fluid'], [R.PROTEIN, 'protein']]) {
      out[name] = a[key] == null ? null : ([R.K, R.P, R.NA, R.FLUID].includes(key) ? M.whole(a[key]) : R.roundTo(a[key], 1));
    }
    return out;
  }
  function levelsOf(room) { return Object.fromEntries(Object.entries(room.nutrients).map(([k, v]) => [k, v.level])); }

  // candidates_for_ai(ctx, meal, mode, food=, servings=, purpose=, exclude=…). `swap` = { food, servings, purpose } for mode "swap".
  function candidatesForAi(ctx, meal, exclude = new Set(), mode = 'ideas', swap = null) {
    if (!MODES.includes(mode)) throw new Error(`mode must be one of ${MODES.join(', ')}`);
    const counter = S.newCounter();
    const totals = B.dayTotals(ctx.day);
    const room = B.mealRoom(ctx, meal, null, totals);
    const habit = S.habitStats(ctx);
    const today = S.todayStats(ctx.day);
    const scorer = new S.Scorer(room, habit, today, counter);
    let [ranked] = F.rankFoods(ctx, room, scorer, F.eligibleFoods(ctx).filter((f) => !exclude.has(f.id)));
    ranked = ranked.filter((pair) => (pair[0].score || 0.0) >= R.MIN_SHOW_SCORE);
    let picked = [];
    const perGroup = {};
    for (const pair of ranked) {
      const g = pair[0].food.group;
      if ((perGroup[g] || 0) < R.AI_FOODS_PER_GROUP_MIN) { picked.push(pair); perGroup[g] = (perGroup[g] || 0) + 1; }
    }
    for (const pair of ranked) {
      if (picked.length >= R.AI_FOODS_MAX) break;
      if (!picked.includes(pair)) picked.push(pair);
    }
    picked = picked.slice(0, R.AI_FOODS_MAX).sort((a, b) => ranked.indexOf(a) - ranked.indexOf(b));
    const tracked = [R.K, R.P, R.NA, R.FLUID].filter((k) => k in room.nutrients);
    const foods = picked.map(([best, std], i) => {
      const f = best.food, q = best.servings;
      const [reasons] = F.reasonsFor(best, scorer, room, std, habit);
      const a = F.scaled(f, q);
      return { ref: `f${i + 1}`, food_id: f.id, name: M.safeName(f.name), untrusted: UNTRUSTED_SOURCES.includes(f.source), group: f.group,
        portion: q, per_portion: perPortion(f, q), renal_rating: R.renalLevel(a[R.K], a[R.P], a[R.NA], f.additive),
        fit_text: M.fitText(a, tracked, room.carbs != null), reasons: reasons.map((r) => r.code).filter((c) => c !== 'you_like'),
        liked: habit.pref.liked.has(f.id), often: (habit.days_14.get(f.id) || 0) >= R.OFTEN_MIN_DAYS, max_quarters: maxQuarters(f, room) };
    });
    const meals = F.fittingSavedMeals(ctx, meal, room, today, counter, R.AI_MEALS_MAX).map(F.publicOption);
    meals.forEach((m, i) => { m.ref = `m${i + 1}`; m.name = M.safeName(m.name); });
    const result = { rules_version: R.RULES_VERSION, rules_hash: R.RULES_HASH, date: ctx.date, meal, mode, room: F.roomJson(room),
      levels: levelsOf(room), foods, meals, handbook: Object.keys(T.TOPIC_PAGES).sort() };
    if (mode === 'swap') {
      if (!swap || swap.food == null || swap.servings == null) throw new Error('swap mode needs the food and its servings');
      const found = GE.swaps.findSwaps(ctx, meal, swap.food, swap.servings, swap.purpose == null ? null : swap.purpose, R.SWAP_AI_MAX);
      if (found.mode === 'hypo') throw new Error('low treatments are never sent to AI (note 04 G7)');
      result.swaps = found.swaps.map((s, i) => ({ ref: `s${i + 1}`, food_id: s.food_id, name: s.name, servings: s.servings,
        renal_rating: s.renal_rating, text: s.text }));
      result.triggers = found.triggers;
    }
    if (mode === 'plan') {
      const plan = GE.planner.planDay(ctx, null, { withOptions: true });
      result.plan = {};
      for (const [slot, opts] of Object.entries(plan.options || {})) {
        result.plan[slot] = opts.map((o, i) => ({ index: i, source: o.source, name: o.name, score: o.score,
          items: o.items.map((it) => ({ food_id: it.food_id, name: M.safeName(it.name), servings: it.servings })), totals: o.totals }));
      }
    }
    return result;
  }

  function maxQuarters(f, room) {
    const [lo, hi] = R.AI_QUARTERS_RANGE;
    for (let qt = hi; qt >= lo; qt -= 1) if (S.checkMeal([[f, qt / 4.0]], room, 'ai').ok) return qt;
    return 0;
  }

  function merge(items) {
    const merged = new Map();
    for (const raw of items) {
      if (!isDict(raw) || !isInt(raw.food_id) || !isInt(raw.quarters)) return [null, 'malformed_item'];
      merged.set(raw.food_id, (merged.get(raw.food_id) || 0) + raw.quarters);
    }
    return [[...merged], null];
  }

  function notForLowering(f, q, room) {
    if (f.avoid || f.hypo || f.ingredient || f.alcohol) return true;
    if (room.carbs != null && f.carbs == null) return true;
    for (const [key, v] of [[R.K, f.k], [R.P, f.p], [R.NA, f.na]]) {
      if (B.levelOf(room, key) === 'ok') continue;
      if (v == null || R.isHigh(key, v * q) || (key === R.P && f.additive)) return true;
    }
    return false;
  }
  function toLower(items, reason) {
    const lo = R.AI_QUARTERS_RANGE[0];
    const rows = [];
    items.forEach(([f, qt], idx) => {
      if (f.hypo || qt <= lo) return;
      const q = qt / 4.0;
      if (reason === 'high_portion_too_large') {
        const high = f.additive || [[R.K, f.k], [R.P, f.p], [R.NA, f.na]].some(([key, v]) => v != null && R.isHigh(key, v * q));
        if (q > 1.0 + 1e-9 && high) rows.push([-q, -qt, f.id, idx]);
      } else if (reason === 'portion_out_of_range') {
        if (q > R.PORTION_MAX + 1e-9) rows.push([-q, -qt, f.id, idx]);
      } else {
        const key = reason === 'too_many_carbs' ? R.CARBS : reason.split(':').slice(1).join(':');
        const v = key in AMOUNT ? f[AMOUNT[key]] : null;
        if (v != null && v * q > 0) rows.push([-(v * q), -qt, f.id, idx]);
      }
    });
    if (!rows.length) return null;
    rows.sort(cmpTuple);
    return rows[0][3];
  }
  const startsWithAny = (text, list) => list.some((p) => text.startsWith(p));
  function lowerToFit(items, room, reason) {
    const [lo, hi] = R.AI_QUARTERS_RANGE;
    if (!startsWithAny(reason, LOWERABLE) || items.some(([, qt]) => qt < lo)) return null;
    if (items.some(([f, qt]) => notForLowering(f, qt / 4.0, room))) return null;
    const work = items.map(([f, qt]) => [f, Math.min(qt, hi)]);
    const steps = work.reduce((s, [, qt]) => s + qt, 0);
    for (let i = 0; i < steps; i += 1) {
      const check = S.checkMeal(work.map(([f, qt]) => [f, qt / 4.0]), room, 'ai');
      if (check.ok) return work;
      if (check.reason == null || !startsWithAny(check.reason, [...LOWERABLE, 'portion_out_of_range'])) return null;
      const pick = toLower(work, check.reason);
      if (pick == null) return null;
      work[pick] = [work[pick][0], work[pick][1] - 1];
    }
    return S.checkMeal(work.map(([f, qt]) => [f, qt / 4.0]), room, 'ai').ok ? work : null;
  }

  // validate_ai_items(ctx, meal, ideas, candidate_ids)
  function validateAiItems(ctx, meal, ideas, candidateIds = null) {
    let allowed;
    if (candidateIds == null) {
      const c = candidatesForAi(ctx, meal);
      allowed = new Set(c.foods.map((f) => f.food_id));
      for (const m of c.meals) for (const it of m.items) allowed.add(it.food_id);
    } else allowed = new Set(candidateIds);
    const totals = B.dayTotals(ctx.day);
    const room = B.mealRoom(ctx, meal, null, totals);
    const today = S.todayStats(ctx.day);
    const pref = S.prefTerms(ctx);
    const accepted = [], dropped = [], lowered = [];
    const [lo, hi] = R.AI_QUARTERS_RANGE;
    ideas.forEach((idea, index) => {
      if (index >= 3) { dropped.push({ index, reason: 'too_many_ideas' }); return; }
      const [merged, error] = merge(idea);
      if (error || merged == null) { dropped.push({ index, reason: error || 'malformed_item' }); return; }
      if (!merged.length) { dropped.push({ index, reason: 'empty' }); return; }
      if (merged.length > 5) { dropped.push({ index, reason: 'too_many_items' }); return; }
      const reasons = [];
      for (const [foodId, quarters] of merged) {
        if (!allowed.has(foodId) || !ctx.foods.has(foodId)) reasons.push('not_a_candidate');
        else if (!(lo <= quarters && quarters <= hi)) reasons.push(quarters > hi ? 'quarters_out_of_range' : 'quarters_too_small');
      }
      if (reasons.length) {
        const first = reasons[0] === 'quarters_too_small' ? 'quarters_out_of_range' : reasons[0];
        if (!reasons.every((r) => r === 'quarters_out_of_range')) { dropped.push({ index, reason: first }); return; }
      }
      let proposed = merged.map(([foodId, quarters]) => [ctx.foods.get(foodId), quarters]);
      let reason;
      if (reasons.length) reason = 'quarters_out_of_range';
      else {
        const check = S.checkMeal(proposed.map(([f, qt]) => [f, qt / 4.0]), room, 'ai');
        reason = check.ok ? null : check.reason;
      }
      let changes = [];
      if (reason != null) {
        const fixed = lowerToFit(proposed, room, reason);
        if (fixed == null) { dropped.push({ index, reason }); return; }
        changes = proposed.map(([f, was], i) => ({ food_id: f.id, from_quarters: was, to_quarters: fixed[i][1] })).filter((c) => c.to_quarters !== c.from_quarters);
        lowered.push({ index, reason, changes });
        proposed = fixed;
      }
      const items = proposed.map(([f, qt]) => [f, qt / 4.0]);
      const [mealT, mealU] = S.mealTotals(items);
      const out = { index, items: items.map(([f, q]) => F.foodCore(f, q)), totals: F.totalsJson(mealT, room), unknown: F.unknownJson(mealU, room),
        score: S.scoreMeal(items, room, today, ctx.profile.dialysis !== 'none', 1.0, null, null, pref), checked: true };
      if (changes.length) out.portions_lowered = changes;
      accepted.push(out);
    });
    return { ideas: accepted, dropped, portions_lowered: lowered, note: accepted.length ? null : M.AI_FALLBACK };
  }

  // ---------------------------------------------------------------------------
  // app/ai/guard.py
  // ---------------------------------------------------------------------------
  const amountOf = (f, key) => ({ [R.K]: f.k, [R.P]: f.p, [R.NA]: f.na })[key];
  function trueReasons(items, room, often, liked = new Set()) {
    const [totals, unknown] = S.mealTotals(items);
    const out = new Set();
    const low = (key) => {
      if (unknown.has(key)) return false;
      const limit = LOW_PORTION_MG[key];
      if (items.some(([f, q]) => (amountOf(f, key) || 0.0) * q > limit)) return false;
      const item = room.nutrients[key];
      if (item != null) return item.room > 0 && totals[key] <= 0.5 * item.room;
      return true;
    };
    if (low(R.K)) out.add('low_potassium');
    if (low(R.P)) out.add('low_phosphorus');
    if (low(R.NA)) out.add('low_sodium');
    if (room.carbs != null && !unknown.has(R.CARBS)) {
      if (Math.abs(room.carbs.in_meal + totals[R.CARBS] - room.carbs.goal) <= room.carbs.tolerance) out.add('fits_carb_goal');
    }
    if (!unknown.has(R.PROTEIN) && totals[R.PROTEIN] >= R.PROTEIN_ROLE_MIN_G) out.add('adds_protein');
    const has = room.meal_has;
    for (const [f] of items) {
      if ((R.PROTEIN_ROLES.has(f.role) && !has.protein) || (R.STARCH_ROLES.has(f.role) && !has.starch) || (f.role === 'veg_fruit' && !has.veg_fruit)) {
        out.add('adds_missing_group');
        break;
      }
    }
    if (items.some(([f]) => often.has(f.id))) out.add('you_eat_often');
    if (items.some(([f]) => liked.has(f.id))) out.add('you_like');
    return out;
  }
  function trueTheme(items, claimed, often) {
    const familiar = items.some(([f]) => often.has(f.id));
    const kcal = items.reduce((s, [f, q]) => s + (f.kcal || 0.0) * q, 0.0);
    if (claimed === 'familiar') return familiar ? 'familiar' : 'new_idea';
    if (claimed === 'new_idea') return !familiar ? 'new_idea' : 'familiar';
    if (claimed === 'hearty') return kcal >= HEARTY_KCAL ? 'hearty' : 'light';
    return kcal < HEARTY_KCAL ? 'light' : 'hearty';
  }
  function sentence(codes, meal, items = []) {
    const [totals] = S.mealTotals(items);
    const values = { meal, k: M.fmtInt(totals[R.K]), p: M.fmtInt(totals[R.P]), na: M.fmtInt(totals[R.NA]) };
    const parts = codes.filter((c) => c in REASON_TEXT).map((c) => REASON_TEXT[c].replace(/\{(\w+)\}/g, (_, k) => values[k]));
    if (!parts.length) return `Fits your targets for ${meal}.`;
    const text = parts.join('; ');
    return text[0].toUpperCase() + text.slice(1) + '.';
  }
  function checkClaims(claimed, items, room, often, liked = new Set()) {
    const truth = trueReasons(items, room, often, liked);
    const claims = unique(claimed);
    let kept = claims.filter((c) => REASON_CODES.includes(c) && truth.has(c));
    const corrected = claims.filter((c) => !kept.includes(c)).length;
    if (!kept.length) kept = REASON_CODES.filter((c) => truth.has(c)).slice(0, 2);
    return [kept.slice(0, 3), corrected];
  }
  function handbookRefs(slugs) {
    const pages = [];
    let dropped = 0;
    for (const slug of slugs) {
      const allowed = typeof slug === 'string' && AI_HANDBOOK_SLUGS.includes(slug) && slug in T.TOPIC_PAGES;
      if (allowed && pages.length < 2 && pages.every((p) => p.slug !== slug)) { pages.push({ ...T.TOPIC_PAGES[slug] }); continue; }
      dropped += 1;
    }
    return [pages, dropped];
  }
  const oftenIds = (bridge) => new Set((bridge.foods || []).filter((f) => f.often === true).map((f) => Number(f.food_id)));
  const likedIds = (bridge) => new Set((bridge.foods || []).filter((f) => f.liked === true).map((f) => Number(f.food_id)));
  function personExcluded(ctx, foodIds) {
    for (const fid of foodIds) {
      const food = ctx.foods.get(fid);
      if (food == null) continue;
      const reason = F.ineligibleReason(food, ctx);
      if (NOT_FOR_ME_REASONS.includes(reason)) return reason;
    }
    return null;
  }
  function label(providerLabel, model, notice = NOTICE) {
    return { source: 'ai', provider_label: providerLabel, model, checked: true, notice: notice(providerLabel, model) };
  }
  function ideaItems(raw) {
    if (!isDict(raw)) return [null, 'malformed_idea'];
    if (Object.keys(raw).some((k) => !IDEA_KEYS.includes(k))) return [null, 'unexpected_field'];
    const items = raw.items;
    if (!Array.isArray(items)) return [null, 'malformed_idea'];
    if (!items.length) return [null, 'empty'];
    const out = [];
    for (const it of items) {
      if (!isDict(it) || Object.keys(it).some((k) => k !== 'food_id' && k !== 'quarters')) return [null, 'malformed_item'];
      if (!isInt(it.food_id) || !isInt(it.quarters)) return [null, 'malformed_item'];
      out.push({ food_id: it.food_id, quarters: it.quarters });
    }
    return [out, null];
  }
  function afterRoom(room, items) {
    const [totals] = S.mealTotals(items);
    const out = {};
    for (const [key, item] of Object.entries(room.nutrients)) {
      out[key] = { used: roundValue(key, totals[key]), left_today_after: roundValue(key, item.remaining - totals[key]) };
    }
    if (room.carbs != null) {
      out[R.CARBS] = { meal_after: roundValue(R.CARBS, room.carbs.in_meal + totals[R.CARBS]), goal: roundValue(R.CARBS, room.carbs.goal) };
    }
    return out;
  }

  // guard.judge_ideas
  function judgeIdeas(answer, ctx, meal, bridge, providerLabel, model) {
    if (answer.status === 'refused') return { status: 'refused', message: REFUSED_TEXT, ideas: [], dropped: [], claims_corrected: 0 };
    const candidateIds = new Set((bridge.foods || []).map((f) => Number(f.food_id)));
    for (const m of bridge.meals || []) for (const it of m.items || []) candidateIds.add(Number(it.food_id));
    const rawIdeas = Array.isArray(answer.ideas) ? answer.ideas : [];
    const parsed = [];
    const dropped = [];
    rawIdeas.forEach((raw, index) => {
      if (index >= 3) { dropped.push({ index, reason: 'too_many_ideas' }); return; }
      const [items, error] = ideaItems(raw);
      if (error || items == null) { dropped.push({ index, reason: error || 'malformed_idea' }); return; }
      if (new Set(items.map((i) => i.food_id)).size > 5) { dropped.push({ index, reason: 'too_many_items' }); return; }
      const excluded = personExcluded(ctx, items.map((i) => i.food_id));
      if (excluded != null) { dropped.push({ index, reason: excluded }); return; }
      parsed.push([index, raw, items]);
    });
    const checked = validateAiItems(ctx, meal, parsed.map(([, , items]) => items), candidateIds);
    const room = B.mealRoom(ctx, meal, null, B.dayTotals(ctx.day));
    const often = oftenIds(bridge), liked = likedIds(bridge);
    const acceptedByPos = new Map(checked.ideas.map((a) => [a.index, a]));
    for (const d of checked.dropped) dropped.push({ index: d.index < parsed.length ? parsed[d.index][0] : d.index, reason: d.reason });
    const lowered = (checked.portions_lowered || []).map((r) => ({ ...r, index: parsed[r.index][0] }));
    const shown = [];
    let correctedTotal = 0;
    parsed.forEach(([index, raw], pos) => {
      const accepted = acceptedByPos.get(pos);
      if (accepted == null) return;
      const vecItems = accepted.items.map((it) => [ctx.foods.get(it.food_id), Number(it.servings)]);
      let [codes, corrected] = checkClaims((Array.isArray(raw.reason_codes) ? raw.reason_codes : []).filter((c) => typeof c === 'string'), vecItems, room, often, liked);
      const themeClaim = THEMES.includes(raw.theme) ? raw.theme : 'light';
      const theme = trueTheme(vecItems, themeClaim, often);
      corrected += Number(theme !== themeClaim);
      const [pages, slugsDropped] = handbookRefs(Array.isArray(raw.handbook) ? raw.handbook : []);
      correctedTotal += corrected;
      const changes = accepted.portions_lowered || [];
      const note = changes.length ? { portion_note: changes.length === 1 ? PORTION_LOWERED_TEXT : PORTIONS_LOWERED_TEXT } : {};
      shown.push({ ...label(providerLabel, model), index, theme, title: THEME_TITLE[theme].replace('{meal}', meal), reason_codes: codes,
        why: sentence(codes, meal, vecItems), items: accepted.items, totals: accepted.totals, unknown: accepted.unknown || [],
        score: accepted.score, after: afterRoom(room, vecItems), handbook: pages, handbook_dropped: slugsDropped, ...note });
    });
    if (!shown.length) {
      const status = answer.refusal === 'no_fit' && !rawIdeas.length ? 'no_fit' : 'dropped_all';
      return { status, message: status === 'no_fit' ? NO_FIT_TEXT : M.AI_FALLBACK, ideas: [], dropped, portions_lowered: lowered,
        claims_corrected: correctedTotal };
    }
    return { status: 'ok', ideas: shown, dropped, portions_lowered: lowered, claims_corrected: correctedTotal };
  }
  function fallback(bridge, limit = 8) {
    return { note: M.AI_FALLBACK, meals: [...(bridge.meals || [])],
      foods: (bridge.foods || []).slice(0, limit).map((f) => ({ food_id: f.food_id, name: f.name, portion: f.portion, renal_rating: f.renal_rating, fit_text: f.fit_text })) };
  }

  // guard._ref_picks: the refs the AI named that are in `allowed` (a Map ref → row), in its order, at most `limit`.
  function refPicks(raw, allowed, limit) {
    const picks = [];
    const dropped = [];
    const seen = new Set();
    (Array.isArray(raw) ? raw : []).forEach((entry, index) => {
      const ref = isDict(entry) ? entry.ref : undefined;
      if (typeof ref !== 'string' || !allowed.has(ref)) { dropped.push({ index, reason: 'not_a_candidate' }); return; }
      if (seen.has(ref)) { dropped.push({ index, reason: 'duplicate' }); return; }
      if (picks.length >= limit) { dropped.push({ index, reason: 'too_many' }); return; }
      seen.add(ref);
      picks.push([ref, (Array.isArray(entry.reason_codes) ? entry.reason_codes : []).filter((c) => typeof c === 'string')]);
    });
    return [picks, dropped];
  }
  // guard.judge_rerank: the AI's order for the refs it names, then the rule order; numbers and texts are the rules' own.
  function judgeRerank(answer, ctx, meal, bridge, providerLabel, model) {
    if (answer.status === 'refused') return { status: 'refused', message: REFUSED_TEXT, order: [], dropped: [], claims_corrected: 0 };
    const foods = new Map((bridge.foods || []).map((f) => [f.ref, f]));
    const [picks, dropped] = refPicks(answer.order, foods, 12);
    const room = B.mealRoom(ctx, meal, null, B.dayTotals(ctx.day));
    const often = oftenIds(bridge), liked = likedIds(bridge);
    const order = [];
    let correctedTotal = 0;
    picks.forEach(([ref, claimed], i) => {
      const f = foods.get(ref);
      const vec = [[ctx.foods.get(Number(f.food_id)), Number(f.portion)]];
      const [codes, corrected] = checkClaims(claimed, vec, room, often, liked);
      correctedTotal += corrected;
      order.push({ ref, food_id: Number(f.food_id), name: f.name, ai_rank: i + 1, reason_codes: codes, why: sentence(codes, meal, vec) });
    });
    const picked = new Set(picks.map(([ref]) => ref));
    const rest = [...foods].filter(([ref]) => !picked.has(ref)).map(([ref, f]) => ({ ref, food_id: Number(f.food_id), name: f.name }));
    if (!order.length) return { status: 'dropped_all', message: M.AI_FALLBACK, order: [], rest, dropped, claims_corrected: 0 };
    return { status: 'ok', ...label(providerLabel, model), order, rest, dropped, claims_corrected: correctedTotal };
  }
  // guard.judge_swap: the AI picks among the rule swaps, which already passed every rule.
  function judgeSwap(answer, ctx, meal, bridge, providerLabel, model) {
    if (answer.status === 'refused') return { status: 'refused', message: REFUSED_TEXT, pick: [], dropped: [], claims_corrected: 0 };
    const swaps = new Map((bridge.swaps || []).map((s) => [s.ref, s]));
    const [picks, dropped] = refPicks(answer.pick, swaps, 3);
    const room = B.mealRoom(ctx, meal, null, B.dayTotals(ctx.day));
    const often = oftenIds(bridge), liked = likedIds(bridge);
    const shown = [];
    let correctedTotal = 0;
    for (const [ref, claimed] of picks) {
      const s = swaps.get(ref);
      const vec = [[ctx.foods.get(Number(s.food_id)), Number(s.servings)]];
      const [codes, corrected] = checkClaims(claimed, vec, room, often, liked);
      correctedTotal += corrected;
      shown.push({ ...label(providerLabel, model), ref, food_id: Number(s.food_id), name: s.name, servings: s.servings,
        renal_rating: s.renal_rating == null ? null : s.renal_rating, text: s.text == null ? null : s.text, reason_codes: codes,
        why: sentence(codes, meal, vec) });
    }
    if (!shown.length) return { status: 'dropped_all', message: M.AI_FALLBACK, pick: [], dropped, claims_corrected: 0 };
    return { status: 'ok', pick: shown, dropped, claims_corrected: correctedTotal };
  }
  // ai_bridge.validate_ai_plan: the plan rebuilt with the AI's picks; the whole-day check, repair and protein top-up run again.
  function validateAiPlan(ctx, picks) {
    const clean = {};
    for (const [slot, i] of Object.entries(picks)) {
      if (R.SLOT_ORDER.includes(slot) && isInt(i) && i >= 0 && i < R.AI_PLAN_OPTIONS_MAX) clean[slot] = i;
    }
    return GE.planner.planDay(ctx, null, { forced: clean });
  }
  // guard.judge_plan: one option index per meal of the plan.
  function judgePlan(answer, ctx, bridge, providerLabel, model) {
    if (answer.status === 'refused') return { status: 'refused', message: REFUSED_TEXT, plan: null, dropped: [], claims_corrected: 0 };
    const plan = bridge.plan || {};
    const picks = {};
    const dropped = [];
    (Array.isArray(answer.picks) ? answer.picks : []).forEach((entry, index) => {
      const slot = isDict(entry) ? entry.meal : undefined;
      const option = isDict(entry) ? entry.index : undefined;
      if (typeof slot !== 'string' || !Object.prototype.hasOwnProperty.call(plan, slot) || !isInt(option) || option < 0 || option >= plan[slot].length) {
        dropped.push({ index, reason: 'not_a_candidate' });
        return;
      }
      if (slot in picks) { dropped.push({ index, reason: 'duplicate' }); return; }
      picks[slot] = option;
    });
    if (!Object.keys(picks).length) return { status: 'dropped_all', message: M.AI_FALLBACK, plan: null, dropped, claims_corrected: 0 };
    return { status: 'ok', ...label(providerLabel, model), ai_picks: picks, plan: validateAiPlan(ctx, picks), dropped, claims_corrected: 0 };
  }

  // ---------------------------------------------------------------------------
  // app/ai/recipes.py (cooking steps off)
  // ---------------------------------------------------------------------------
  function recipeIneligible(f, ctx) {
    if (f.hidden) return 'hidden';
    if (f.avoid) return 'avoid_ckd';
    if (f.hypo) return 'hypo_treatment';
    if (f.alcohol) return 'alcohol';
    if (f.supplies) return 'diabetes_supplies';
    if (ctx.prefs.exclude_food_ids.has(f.id)) return 'not_for_me';
    if (ctx.prefs.exclude_categories.has(f.category || '')) return 'excluded_category';
    if (NEVER_ADD.test(fold(f.name || ''))) return 'never_added';
    return null;
  }
  function recipeCandidates(ctx, target, extra = [], exclude = new Set()) {
    const room = GE.recipes.roomFor(ctx, target);
    const counter = S.newCounter();
    const scorer = new S.Scorer(room, S.habitStats(ctx), S.todayStats(ctx.day), counter);
    const habit = scorer.habit;
    let ranked = [];
    for (const f of ctx.foods.values()) {
      if (recipeIneligible(f, ctx) != null || (exclude.has(f.id) && !f.ingredient)) continue;
      const [best] = scorer.bestPortion(f, RECIPE_PORTIONS);
      if (best == null) continue;
      ranked.push([best.score || 0.0, f]);
    }
    ranked = R.sortBy(ranked, ([score, f]) => [-score, f.name_fold, f.id]);
    let picked = [];
    let ingredients = 0;
    for (const [, f] of ranked) {
      if (ingredients >= AI_RECIPE_INGREDIENTS_MIN) break;
      if (f.ingredient) { picked.push(f); ingredients += 1; }
    }
    const byCategory = new Map();
    const later = [];
    for (const [, f] of ranked) {
      if (picked.includes(f)) continue;
      if (f.processed || COOK_LATER.includes(f.category || '')) later.push(f);
      else {
        const key = f.category || f.group;
        if (!byCategory.has(key)) byCategory.set(key, []);
        byCategory.get(key).push(f);
      }
    }
    const categories = [...byCategory.keys()].sort(R.cmpStr);
    while (picked.length < AI_RECIPE_FOODS_MAX && categories.some((c) => byCategory.get(c).length)) {
      for (const c of categories) if (byCategory.get(c).length && picked.length < AI_RECIPE_FOODS_MAX) picked.push(byCategory.get(c).shift());
    }
    picked = picked.concat(later.slice(0, Math.max(0, AI_RECIPE_FOODS_MAX - picked.length)));
    const order = new Map(ranked.map(([, f], i) => [f.id, i]));
    picked = picked.slice(0, AI_RECIPE_FOODS_MAX).sort((a, b) => order.get(a.id) - order.get(b.id));
    for (const f of extra) if (recipeIneligible(f, ctx) == null && picked.every((p) => p.id !== f.id)) picked.push(f);
    const foods = picked.map((f, i) => {
      const a = F.scaled(f, 1.0);
      return { ref: `f${i + 1}`, food_id: f.id, group: f.group, portion: 1.0, per_portion: perPortion(f, 1.0),
        renal_rating: R.renalLevel(a[R.K], a[R.P], a[R.NA], f.additive), reasons: [], liked: habit.pref.liked.has(f.id),
        often: (habit.days_14.get(f.id) || 0) >= R.OFTEN_MIN_DAYS };
    });
    return { room: F.roomJson(room), levels: levelsOf(room), foods, meal: room.meal };
  }
  // prepare_recipes' `recipe` block for mode "change": the person's recipe as foods and pot amounts with the app's findings. Never
  // its name, note, steps or link.
  function recipeChangeBlock(ctx, bridge, original, makes, target) {
    const before = GE.fitRecipe(ctx, original, makes, target).before;
    const sendable = original.filter(([f]) => bridge.foods.some((c) => Number(c.food_id) === f.id));
    return { ref: 'r1', makes, ingredients: sendable.map(([f, q]) => ({ id: f.id, quarters: quartersOf(q) })),
      findings: before.checks.map((c) => ({ nutrient: c.nutrient, per_serving: c.used, room: c.room, ok: c.ok })) };
  }
  const quartersOf = (servings) => Math.max(1, Math.min(MAX_RECIPE_QUARTERS, Math.trunc(pyRound(Number(servings) * 4))));
  function portionNote(changes) {
    if (!changes.length) return null;
    if (changes.some((c) => c.to_servings === 0)) return FOOD_SWAPPED_TEXT;
    return changes.length === 1 ? RECIPE_PORTION_LOWERED_TEXT : RECIPE_PORTIONS_LOWERED_TEXT;
  }
  function recipeIngredients(raw) {
    const items = raw.ingredients;
    if (!Array.isArray(items)) return [null, 'malformed_recipe'];
    const merged = new Map();
    for (const it of items) {
      if (!isDict(it) || Object.keys(it).some((k) => k !== 'food_id' && k !== 'quarters')) return [null, 'malformed_item'];
      if (!isInt(it.food_id) || !isInt(it.quarters)) return [null, 'malformed_item'];
      merged.set(it.food_id, (merged.get(it.food_id) || 0) + it.quarters);
    }
    return [[...merged], null];
  }
  function titleFor(items, dish) {
    let mains = items.filter(([f]) => !f.ingredient);
    if (!mains.length) mains = [...items];
    mains = R.sortBy(mains, ([f, q]) => [-(f.serving_g || 0.0) * q, f.name_fold, f.id]);
    const names = F.shortNames(mains.slice(0, 2).map(([f]) => f.name)).map((n) => TC.pyStrip(TC.cpSlice(n, 0, 30)));
    const word = DISH_WORD[dish] || 'dish';
    let text = unique(names.filter((n) => n)).join(' and ');
    if (!text.split(/\s+/).includes(word)) text = `${text} ${word}`.trim();
    text = text.slice(0, 1).toUpperCase() + text.slice(1);
    return TC.cpSlice(text, 0, NAME_MAX);
  }
  function differences(original, next, foods) {
    const before = new Map();
    for (const [f, q] of original) before.set(f.id, (before.get(f.id) || 0.0) + Number(q));
    const after = new Map(next.map((i) => [Number(i.food_id), Number(i.servings)]));
    const lines = [];
    for (const [fid, q] of after) {
      const f = foods.get(fid);
      if (!before.has(fid)) lines.push(`Added ${M.safeName(f.name).toLowerCase()}: ${M.portionText(q, f.serving_desc)}.`);
      else if (Math.abs(before.get(fid) - q) > 1e-9) {
        lines.push(`${M.safeName(f.name)}: ${M.portionText(q, f.serving_desc)} instead of ${M.portionText(before.get(fid), f.serving_desc)}.`);
      }
    }
    for (const [f] of original) {
      const line = `Took out ${M.safeName(f.name).toLowerCase()}.`;
      if (!after.has(f.id) && !lines.includes(line)) lines.push(line);
    }
    return lines;
  }
  // recipes.judge_recipes with steps off. target: { kind: 'meal' | 'day', meal }.
  function judgeRecipes(answer, ctx, target, bridge, { mode = 'suggest', makes, original = [], name = null, providerLabel, model }) {
    if (answer.status === 'refused') {
      return { status: 'refused', message: REFUSED_TEXT, recipes: [], dropped: [], portions_lowered: [], claims_corrected: 0, steps_dropped: 0 };
    }
    const candidates = new Set((bridge.foods || []).map((f) => Number(f.food_id)));
    const often = oftenIds(bridge), liked = likedIds(bridge);
    const room = GE.recipes.roomFor(ctx, target);
    const meal = target.kind === 'meal' && target.meal ? target.meal : room.meal;
    const limit = mode === 'change' ? 1 : MAX_RECIPES;
    const rawRecipes = Array.isArray(answer.recipes) ? answer.recipes : [];
    const shown = [], dropped = [], lowered = [];
    let correctedTotal = 0, stepsDroppedTotal = 0;
    rawRecipes.forEach((raw, index) => {
      if (index >= limit) { dropped.push({ index, reason: 'too_many_recipes' }); return; }
      if (!isDict(raw)) { dropped.push({ index, reason: 'malformed_recipe' }); return; }
      if (Object.keys(raw).some((k) => !RECIPE_KEYS.includes(k))) { dropped.push({ index, reason: 'unexpected_field' }); return; }
      const [merged, error] = recipeIngredients(raw);
      if (error || merged == null) { dropped.push({ index, reason: error || 'malformed_recipe' }); return; }
      let reason = null;
      if (!(MIN_RECIPE_ITEMS <= merged.length && merged.length <= MAX_RECIPE_ITEMS)) reason = merged.length > MAX_RECIPE_ITEMS ? 'too_many_items' : 'too_few_items';
      const items = [], tooBig = [];
      for (const [fid, quarters] of merged) {
        if (reason != null) break;
        const food = ctx.foods.get(fid);
        if (!candidates.has(fid) || food == null) reason = 'not_a_candidate';
        else if (!(quarters >= 1 && quarters <= MAX_RECIPE_QUARTERS)) reason = 'quarters_out_of_range';
        else {
          const why = recipeIneligible(food, ctx);
          if (NOT_FOR_ME_REASONS.includes(why)) reason = why;
          else if (why != null) reason = why === 'never_added' ? 'excluded_category' : 'not_a_candidate';
          else {
            items.push([food, quarters / 4.0]);
            if (quarters / 4.0 / makes > R.PORTION_MAX + 1e-9) tooBig.push([fid, quarters / 4.0 / makes]);
          }
        }
      }
      if (reason != null) { dropped.push({ index, reason }); return; }
      const fit = GE.fitRecipe(ctx, items, makes, target);
      if (fit.status === 'does_not_fit') {
        const closest = fit.closest;
        const stillBig = closest.items.some((i) => Number(i.servings) / makes * Number(closest.serving_fraction) > R.PORTION_MAX + 1e-9);
        const over = (fit.still_over && fit.still_over.length ? fit.still_over : ['portion'])[0];
        dropped.push({ index, reason: stillBig ? 'share_too_large' : `would_exceed:${over}` });
        return;
      }
      const fitted = fit.fitted;
      const fraction = Number(fitted.serving_fraction);
      const final = fitted.items.map((i) => [ctx.foods.get(Number(i.food_id)), Number(i.servings)]);
      const oneServing = final.map(([f, q]) => [f, q / makes * fraction]);
      const portionChanges = tooBig.map(([fid, was]) => ({ food_id: fid, from_servings: R.roundTo(was, 2),
        to_servings: R.roundTo(oneServing.filter(([f]) => f.id === fid).reduce((s, [, q]) => s + q, 0), 2) }));
      if (portionChanges.length) lowered.push({ index, reason: 'share_too_large', changes: portionChanges });
      let [codes, corrected] = checkClaims((Array.isArray(raw.reason_codes) ? raw.reason_codes : []).filter((c) => typeof c === 'string'), oneServing, room, often, liked);
      const themeClaim = THEMES.includes(raw.theme) ? raw.theme : 'light';
      const theme = trueTheme(oneServing, themeClaim, often);
      corrected += Number(theme !== themeClaim);
      correctedTotal += corrected;
      const rawSteps = Array.isArray(raw.steps) ? raw.steps : [];
      const stepDrops = rawSteps.map((_, i) => ({ index: i, reason: 'steps_off' }));
      stepsDroppedTotal += stepDrops.length;
      const dish = raw.dish in DISH_WORD ? raw.dish : 'bowl';
      const title = mode === 'change' && name ? `${TC.cpSlice(name, 0, NAME_MAX - 12)} (reworked)` : titleFor(final, dish);
      const servingsMade = R.roundTo(makes / fraction, 2);
      shown.push({ ...label(providerLabel, model, RECIPE_NOTICE), index, dish, theme, title, reason_codes: codes, why: sentence(codes, meal, oneServing),
        makes, fit: { status: fit.status, before: fit.before, after: fit.after, changes: fit.changes, still_over: fit.still_over },
        fitted, items: fitted.items, per_serving: fit.after.per_serving, unknown: fit.after.unknown, steps: [], steps_label: null, steps_note: null,
        steps_dropped: stepDrops, differences: mode === 'change' ? differences(original, fitted.items, ctx.foods) : [],
        portions_lowered: portionChanges, portion_note: portionNote(portionChanges),
        body: { name: title, meal_hint: target.kind === 'meal' ? meal : null, servings_made: servingsMade,
          items: fitted.items.map((i) => ({ food_id: Number(i.food_id), servings: Number(i.servings) })), steps: [] } });
    });
    if (!shown.length) {
      const status = answer.refusal === 'no_fit' && !rawRecipes.length ? 'no_fit' : 'dropped_all';
      return { status, message: status === 'no_fit' ? RECIPE_NO_FIT_TEXT : DROPPED_ALL_TEXT, recipes: [], dropped, portions_lowered: lowered,
        claims_corrected: correctedTotal, steps_dropped: stepsDroppedTotal };
    }
    return { status: 'ok', recipes: shown, dropped, portions_lowered: lowered, claims_corrected: correctedTotal, steps_dropped: stepsDroppedTotal };
  }

  // ---------------------------------------------------------------------------
  // app/ai/prompts.py: the data blocks and the person
  // ---------------------------------------------------------------------------
  function number(value, key) {
    if (value == null || typeof value === 'boolean') return null;
    const v = Number(value);
    if (!Number.isFinite(v)) return null;
    if (key.endsWith('_mg') || key.endsWith('_ml') || key === 'calories_kcal') return pyRound(v);
    return pyRound(v, 1);
  }
  function targetsBlock(targets, mealCarbs = true) {
    const out = {};
    for (const key of TARGET_KEYS) {
      if (!mealCarbs && MEAL_CARB_KEYS.includes(key)) continue;
      const value = targets[key];
      if (isDict(value)) {
        const o = {};
        for (const b of ['min', 'max']) if (value[b] != null) o[b] = number(value[b], key);
        out[key] = o;
      } else if (value != null) out[key] = number(value, key);
    }
    return out;
  }
  function totals(entries, status = null) {
    const sums = Object.fromEntries(TOTAL_KEYS.map((k) => [k, 0.0]));
    for (const e of entries) {
      if (status != null && e.status !== status) continue;
      for (const k of TOTAL_KEYS) { const v = e.nutrients[k]; if (v != null) sums[k] += Number(v); }
    }
    return Object.fromEntries(Object.entries(sums).map(([k, v]) => [k, number(v, k)]));
  }
  function weekAverage(day, history, dayIso) {
    const start = R.addDays(dayIso, -6);
    const sums = { phosphorus_mg: 0.0, protein_g: 0.0 };
    for (const e of [...history.filter((h) => h.date >= start), ...day.filter((d) => (d.status || 'eaten') === 'eaten')]) {
      for (const k of Object.keys(sums)) { const v = e.nutrients[k]; if (v != null) sums[k] += Number(v); }
    }
    return Object.fromEntries(Object.entries(sums).map(([k, v]) => [k, number(v / 7.0, k)]));
  }
  function mealBudget(room) {
    const out = {};
    for (const key of ['potassium_mg', 'phosphorus_mg', 'sodium_mg', 'fluid_ml']) {
      const item = room[key];
      if (isDict(item)) out[key] = { share: item.room, day_level: item.level, basis: item.basis };
    }
    const carbs = room.carbs_g;
    if (isDict(carbs)) out.carbs_g = { goal: carbs.goal, in_meal: carbs.in_meal, gap: carbs.gap, tolerance: carbs.tolerance };
    const protein = room.protein_g;
    if (isDict(protein)) out.protein_g = { aim: protein.aim, aim_min: protein.aim_min };
    return out;
  }
  function candidateBlock(item, food) {
    const core = F.foodCore(food, Number(item.portion));
    const seen = new Map();
    for (const w of core.warnings) if (w.nutrient) seen.set(`${w.nutrient}\u0000${w.level}`, [String(w.nutrient), String(w.level)]);
    const warnings = [...seen.values()].sort(cmpTuple);
    const per = {};
    for (const [k, v] of Object.entries(item.per_portion || {})) per[PER_PORTION_KEYS[k] || k] = v;
    const out = { id: Number(item.food_id), ref: item.ref, name: clean(food.name),
      source: ['builtin', 'usda', 'off', 'custom'].includes(food.source) ? food.source : 'custom',
      category: clean(food.category, 60) || null, group: item.group == null ? null : item.group, serving: clean(food.serving_desc, 60),
      portion_quarters: pyRound(Number(item.portion) * 4), per_portion: per, rating: item.renal_rating == null ? null : item.renal_rating,
      warnings: warnings.map(([n, lv]) => ({ nutrient: n, level: lv })), flags: [...food.flags].filter((f) => SHOWN_FLAGS.includes(f)).sort(R.cmpStr),
      often: !!item.often, liked: !!item.liked, reasons: (item.reasons || []).filter((r) => !r.includes(':')) };
    if ('max_quarters' in item) out.max_quarters = Number(item.max_quarters);
    return out;
  }
  function repeatOkBlock(ctx, candidates, saved, savedIds) {
    const meals = new Set(ctx.prefs.plan_repeat_meals || []);
    const foods = ctx.prefs.repeat_ok_food_ids || new Set();
    const marked = ctx.prefs.repeat_ok_meal_ids || new Set();
    return { meals: MEAL_NAMES.filter((m) => meals.has(m)),
      food_ids: unique(candidates.map((c) => c.id).filter((id) => foods.has(id))).sort((a, b) => a - b),
      saved_meals: saved.filter((m, i) => savedIds[i] != null && marked.has(savedIds[i])).map((m) => m.ref) };
  }
  function diabetesStatus(person) {
    const value = (person || {}).diabetes;
    if (!value) return 'unknown';
    return value === 'none' ? 'none' : 'yes';
  }
  // prompts.condition_text: the person's condition from the profile alone (no identity). The app puts only one of these wordings
  // into the meal ideas and recipe rules (ai-prompts.json "conditions").
  function conditionText(person) {
    person = person || {};
    const stage = person.ckd_stage;
    const parts = [CKD_STAGES.includes(stage) ? `stage ${stage}` : `stage ${NOT_CHOSEN}`];
    const dialysis = DIALYSIS_TEXT[person.dialysis || ''];
    if (dialysis) parts.push(dialysis);
    const detail = parts.join(', ');
    const status = diabetesStatus(person);
    if (status === 'none') return `chronic kidney disease only (CKD, ${detail})`;
    const kidney = `chronic kidney disease (CKD, ${detail})`;
    if (status === 'yes') return `${kidney} and ${DIABETES_TEXT[String(person.diabetes)] || 'diabetes'}`;
    return `${kidney}; whether they also have diabetes is ${NOT_CHOSEN}, so do not assume that they do or that they do not`;
  }
  function ageBand(birthMonth, today) {
    if (!birthMonth) return null;
    const m = /^(\d+)-(\d+)/.exec(String(birthMonth));
    if (!m) return null;
    const [ty, tm] = today.split('-').map(Number);
    const age = ty - Number(m[1]) - (tm < Number(m[2]) ? 1 : 0);
    if (!(age >= 0 && age <= 130)) return null;
    const low = Math.floor(age / 10) * 10;
    return `${low}-${low + 9}`;
  }
  function tasteNames(names) {
    const out = [];
    for (const name of names || []) {
      const text = clean(name, 60);
      if (text && !out.includes(text)) out.push(text);
      if (out.length >= 10) break;
    }
    return out.length ? out : null;
  }
  // prompts.person_block(profile, ai_prefs, today, tastes)
  function personBlock(profile, aiPrefs, today, tastes = {}) {
    const share = !!aiPrefs.share_age_sex;
    const sex = share ? profile.sex : null;
    const stageChosen = profile.ckd_stage_chosen !== false;
    const diabetesChosen = profile.diabetes_chosen !== false;
    const out = { ckd_stage: stageChosen ? (profile.ckd_stage == null ? null : profile.ckd_stage) : null,
      dialysis: profile.dialysis == null ? null : profile.dialysis,
      diabetes: diabetesChosen ? (profile.diabetes == null ? null : profile.diabetes) : null,
      preferences: clean(aiPrefs.preferences, 200) || null };
    for (const key of TASTE_KEYS) out[key] = tasteNames((tastes || {})[key]);
    out.age_band = share ? ageBand(profile.birth_month, today) : null;
    out.sex = sex === 'female' || sex === 'male' ? sex : null;
    return out;
  }
  function commonData(bridge, ctx, meal, mealsLeft, person, candidates) {
    return { candidates, judged: { day: [...DAY_JUDGED], week: [...WEEK_JUDGED] }, meal, meal_budget: mealBudget(bridge.room),
      meals_left: [...mealsLeft], person: { ...person },
      targets: targetsBlock(ctx.profile.targets, diabetesStatus(person) !== 'none'),
      today: { eaten: totals(ctx.day, 'eaten'), planned: totals(ctx.day, 'planned'), status: { ...(bridge.levels || {}) } },
      week_avg: weekAverage(ctx.day, ctx.history, ctx.date) };
  }
  // prompts.next_meal_context(bridge, ctx, mode, meal, meals_left, person, extra): `extra` is swapExtra or planExtra for those modes
  function nextMealContext(bridge, ctx, meal, mealsLeft, person, extra = null) {
    const candidates = bridge.foods.filter((item) => ctx.foods.has(Number(item.food_id))).map((item) => candidateBlock(item, ctx.foods.get(Number(item.food_id))));
    const saved = (bridge.meals || []).map((m) => ({ ref: m.ref, name: clean(m.name),
      items: (m.items || []).map((it) => ({ id: Number(it.food_id), quarters: pyRound(Number(it.servings) * 4) })) }));
    return { ...commonData(bridge, ctx, meal, mealsLeft, person, candidates), saved_meals: saved,
      handbook_pages: AI_HANDBOOK_SLUGS.filter((s) => s in T.TOPIC_PAGES).map((s) => ({ slug: s, title: T.TOPIC_PAGES[s].title })),
      repeat_ok: repeatOkBlock(ctx, candidates, saved, (bridge.meals || []).map((m) => (m.template_id == null ? null : m.template_id))),
      ...(extra || {}) };
  }
  // prompts.swap_extra(bridge, food, servings)
  function swapExtra(bridge, food, servings) {
    const core = F.foodCore(food, Number(servings));
    const reasons = [...new Set((bridge.triggers || []).map((t) => t.nutrient).filter(Boolean))].sort();
    return {
      planned_item: { name: clean(food.name), quarters: pyRound(Number(servings) * 4),
        per_portion: Object.fromEntries(TOTAL_KEYS.map((k) => [k, core.nutrients[k] === undefined ? null : core.nutrients[k]])) },
      swap_reason: reasons,
      swaps: (bridge.swaps || []).map((s) => ({ ref: s.ref, name: clean(s.name), quarters: pyRound(Number(s.servings) * 4),
        rating: s.renal_rating == null ? null : s.renal_rating })),
    };
  }
  // prompts.plan_extra(bridge)
  function planExtra(bridge) {
    const plan = {};
    for (const [slot, options] of Object.entries(bridge.plan || {})) {
      plan[slot] = options.map((o) => ({ index: o.index, name: clean(o.name),
        items: (o.items || []).map((it) => ({ name: clean(it.name), quarters: pyRound(Number(it.servings) * 4) })) }));
    }
    return { plan };
  }
  // prompts.recipe_context(bridge, ctx, meal, meals_left, person, request, recipe)
  function recipeContext(bridge, ctx, meal, mealsLeft, person, request, recipe = null) {
    const candidates = bridge.foods.filter((item) => ctx.foods.has(Number(item.food_id))).map((item) => candidateBlock(item, ctx.foods.get(Number(item.food_id))));
    const data = { ...commonData(bridge, ctx, meal, mealsLeft, person, candidates), recipe_request: { ...request } };
    if (recipe != null) data.recipe = { ...recipe };
    return data;
  }

  // ---------------------------------------------------------------------------
  // app/ai/schemas.py IdeasAnswer, RecipesAnswer (V2): the three keys, a status and refusal from their lists, a list of at most 10
  // ---------------------------------------------------------------------------
  function checkHead(raw, listKey) {
    if (!isDict(raw)) return { ok: false };
    const keys = Object.keys(raw).sort();
    if (keys.join(',') !== [listKey, 'refusal', 'status'].sort().join(',')) return { ok: false };
    if (!['ok', 'refused'].includes(raw.status) || !['none', 'outside_scope', 'no_fit'].includes(raw.refusal)) return { ok: false };
    if (!Array.isArray(raw[listKey]) || raw[listKey].length > 10 || !raw[listKey].every(isDict)) return { ok: false };
    return { ok: true, answer: raw };
  }
  const checkIdeas = (raw) => checkHead(raw, 'ideas');
  const checkRecipes = (raw) => checkHead(raw, 'recipes');
  // RerankAnswer, SwapAnswer (RefPick: ref, a string of at most 8 characters, and one to three reason codes) and PlanAnswer
  // (PlanPick: a meal, a whole-number index 0 to 20, one to three reason codes), each with no other keys.
  const codesOk = (v) => Array.isArray(v) && v.length >= 1 && v.length <= 3 && v.every((c) => REASON_CODES.includes(c));
  const keysAre = (o, keys) => Object.keys(o).sort().join(',') === [...keys].sort().join(',');
  const refPickOk = (e) => isDict(e) && keysAre(e, ['ref', 'reason_codes']) && typeof e.ref === 'string' && [...e.ref].length <= 8 && codesOk(e.reason_codes);
  const planPickOk = (e) => isDict(e) && keysAre(e, ['meal', 'index', 'reason_codes']) && ['breakfast', 'lunch', 'dinner', 'snack'].includes(e.meal)
    && isInt(e.index) && e.index >= 0 && e.index <= 20 && codesOk(e.reason_codes);
  function checkPicks(raw, listKey, max, entryOk) {
    if (!isDict(raw) || !keysAre(raw, [listKey, 'refusal', 'status'])) return { ok: false };
    if (!['ok', 'refused'].includes(raw.status) || !['none', 'outside_scope', 'no_fit'].includes(raw.refusal)) return { ok: false };
    if (!Array.isArray(raw[listKey]) || raw[listKey].length > max || !raw[listKey].every(entryOk)) return { ok: false };
    return { ok: true, answer: raw };
  }
  const checkRerank = (raw) => checkPicks(raw, 'order', 40, refPickOk);
  const checkSwap = (raw) => checkPicks(raw, 'pick', 15, refPickOk);
  const checkPlan = (raw) => checkPicks(raw, 'picks', 4, planPickOk);

  KH.aiMeal = {
    THEMES, REASON_CODES, AI_HANDBOOK_SLUGS, RECIPE_PORTIONS, AI_RECIPE_FOODS_MAX, AI_RECIPE_INGREDIENTS_MIN, NEVER_ADD, DISH_WORD,
    candidatesForAi, maxQuarters, lowerToFit, validateAiItems, trueReasons, trueTheme, sentence, checkClaims, handbookRefs, judgeIdeas,
    afterRoom, fallback, recipeIneligible, recipeCandidates, recipeChangeBlock, quartersOf, titleFor, differences, judgeRecipes, targetsBlock, totals,
    weekAverage, mealBudget, candidateBlock, conditionText, personBlock, nextMealContext, recipeContext, checkIdeas, checkRecipes,
    MODES, judgeRerank, judgeSwap, judgePlan, validateAiPlan, swapExtra, planExtra, checkRerank, checkSwap, checkPlan,
  };
})(typeof window !== 'undefined' ? window : globalThis);
