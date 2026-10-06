/* Kidney Diet Log — meal guidance, part 8 of 9: end-of-day and period insights in plain language. Twin
   of app/guidance/insights.py (note 06 §4.8). Rule-only; only eaten entries count; severity warning >
   attention > info > good, then potassium, phosphorus, sodium, fluid, protein, carbohydrate; at most 6,
   at most one "good", always last. Plain script; needs planner.js. */
(function (root) {
  'use strict';
  const KH = root.KH || (root.KH = {});
  const GE = KH.guidanceEngine;
  const { R, M, T } = GE;
  const B = GE.budget;
  const F = GE.fits;
  const SW = GE.swaps;
  const { NUT } = KH.rules;

  const WEEKDAY = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];
  const WEEKDAY_SHORT = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
  const LABEL = { [R.K]: 'Potassium', [R.P]: 'Phosphorus', [R.NA]: 'Sodium', [R.FLUID]: 'Fluid', [R.PROTEIN]: 'Protein',
    [R.CARBS]: 'Carbohydrate', [R.KCAL]: 'Calories' };

  function insight(id, severity, nutrient, message, numbers = null, sources = [], handbook = []) {
    return { id, severity, nutrient, message, numbers: { ...(numbers || {}) }, sources: [...sources], handbook: T.pages(...handbook) };
  }
  function orderInsights(items) {
    const ranked = R.sortBy(items, (i) => [R.SEVERITY_ORDER[i.severity],
      (i.nutrient || '') in R.NUTRIENT_PRIORITY ? R.NUTRIENT_PRIORITY[i.nutrient || ''] : 9, i.id]);
    const good = ranked.filter((i) => i.severity === 'good').slice(0, 1);
    const rest = ranked.filter((i) => i.severity !== 'good');
    return [...rest.slice(0, Math.max(0, R.INSIGHT_MAX - good.length)), ...good].slice(0, R.INSIGHT_MAX);
  }

  // ---- source attribution ------------------------------------------------------------------------
  function identOf(e) { return e.food_id != null ? `id:${e.food_id}` : `name:${e.name}`; }
  function sources(entries, key) {
    const sums = new Map();
    let total = 0.0;
    for (const e of entries) {
      const v = e.nutrients[key];
      if (v == null || v <= 0) continue;
      const ident = identOf(e);
      if (!sums.has(ident)) sums.set(ident, [e.name, 0.0]);
      sums.get(ident)[1] += v;
      total += v;
    }
    if (total <= 0) return [];
    let rows = [];
    for (const [name, value] of sums.values()) if (value / total >= R.SOURCE_MIN_SHARE) rows.push([name, value, value / total]);
    rows = R.sortBy(rows, (r) => [-r[2], R.casefold(r[0])]).slice(0, R.SOURCE_MAX);
    const shorts = F.shortNames(rows.map((r) => r[0]));
    return rows.map((r, i) => ({ name: M.safeName(r[0]), short_name: shorts[i], value: M.whole(r[1]), share_pct: M.pct(r[2]) }));
  }
  function named(entries) {
    const order = new Map();
    for (const e of entries) {
      const ident = identOf(e);
      if (!order.has(ident)) order.set(ident, [e.name, 0]);
      order.get(ident)[1] += 1;
    }
    const values = [...order.values()];
    const names = F.shortNames(values.map((v) => v[0]));
    return names.map((n, i) => (values[i][1] > 1 ? `${n} (${values[i][1]})` : n));
  }
  function plural(n, word, pluralWord = null) { return `${n} ${n === 1 ? word : (pluralWord || `${word}s`)}`; }
  function sumOf(entries, key) { let s = 0; for (const e of entries) s += e.nutrients[key] || 0.0; return s; }

  // ---- end of day --------------------------------------------------------------------------------
  function bestHypoFood(foods, prefs) {
    let best = null;
    for (const f of foods.values()) {
      if (!f.hypo || f.hidden || f.avoid || prefs.exclude_food_ids.has(f.id) || f.k == null) continue;
      const q = SW.candidatePortion(f, 'carbs', Number(prefs.hypo_dose_g), 'hypo');
      if (q == null) continue;
      const k = f.k * q;
      const key = [k, (f.p || 0.0) * q, f.name_fold, f.id];
      if (best == null || R.cmp(key, best[0]) < 0) best = [key, f, q, k];
    }
    return best == null ? null : [best[1], best[2], best[3]];
  }
  function carbMeals(entries, goal, tol) {
    const above = [], below = [];
    let logged = 0;
    for (const meal of R.MAIN_MEALS) {
      const rows = entries.filter((e) => e.meal === meal && !e.hypo);
      if (!rows.length) continue;
      logged += 1;
      const c = sumOf(rows, R.CARBS);
      if (c > goal + tol) above.push([meal, c]);
      else if (c < goal - tol) below.push([meal, c]);
    }
    return [above, below, logged];
  }
  function mealList(rows) {
    const head = `${M.capitalise(rows[0][0])} had ${M.fmtG(rows[0][1])} g`;
    const rest = rows.slice(1).map(([m, c]) => `${m} ${M.fmtG(c)} g`);
    return `${M.joinAnd([head, ...rest])} of carbs`;
  }
  function roundObj(rows) { const o = {}; for (const [m, c] of rows) o[m] = R.roundTo(c, 1); return o; }

  function dayInsights(ctx) {
    const eaten = ctx.day.filter((e) => e.status === 'eaten');
    const planned = ctx.day.filter((e) => e.status !== 'eaten').length;
    const out = [];
    const targets = ctx.profile.targets;
    const warn = ctx.profile.warn_fraction;
    const dialysis = ctx.profile.dialysis !== 'none';
    if (eaten.length) {
      let kLevel = 'ok';
      for (const key of [R.K, R.NA, R.FLUID]) {
        const t = R.targetMax(targets[key]);
        if (t == null) continue;
        const v = sumOf(eaten, key);
        const fraction = v / t;
        const unit = NUT[key].unit;
        const topic = T.NUTRIENT_TOPIC[key];
        if (fraction > 1.0) {
          const src = sources(eaten, key);
          let msg = `${LABEL[key]} was ${M.fmtAmount(key, v)} ${unit} today, ${M.pct(fraction)} % of your ${M.fmtAmount(key, t)} ${unit} limit.`;
          if (src.length >= 2) msg += ` Most came from ${src[0].short_name} (${src[0].share_pct} %) and ${src[1].short_name} (${src[1].share_pct} %).`;
          else if (src.length === 1) msg += ` Most came from ${src[0].short_name} (${src[0].share_pct} %).`;
          out.push(insight(`day.${key}.over`, 'warning', key, msg, { value: M.whole(v), target: M.whole(t), percent: M.pct(fraction) }, src, [topic]));
          if (key === R.K) kLevel = 'over';
        } else if (fraction >= warn) {
          const msg = `${LABEL[key]} reached ${M.pct(fraction)} % of your limit (${M.fmtAmount(key, v)} of ${M.fmtAmount(key, t)} ${unit}).`;
          out.push(insight(`day.${key}.caution`, 'attention', key, msg, { value: M.whole(v), target: M.whole(t), percent: M.pct(fraction) }, [], [topic]));
          if (key === R.K) kLevel = 'caution';
        }
      }
      const tp = R.targetMax(targets[R.P]);
      if (tp != null && sumOf(eaten, R.P) > tp) {
        const v = sumOf(eaten, R.P);
        out.push(insight('day.phosphorus_mg.over', 'info', R.P,
          `Phosphorus was ${M.fmtInt(v)} mg today, above your ${M.fmtInt(tp)} mg target. It is judged on the `
          + 'weekly average, so lighter days around it balance it out.',
          { value: M.whole(v), target: M.whole(tp) }, sources(eaten, R.P), ['phosphorus']));
      }
      const perMeal = R.targetMax(targets.carbs_per_meal_g);
      if (ctx.profile.diabetes !== 'none' && perMeal != null) {
        const tol = Number(ctx.prefs.carb_tolerance_g);
        const [above, below, logged] = carbMeals(eaten, perMeal, tol);
        const sentences = [];
        if (above.length) sentences.push(`${mealList(above)}, more than ${M.fmtG(tol)} g above your usual ${M.fmtG(perMeal)} g.`);
        if (below.length) sentences.push(`${mealList(below)}, more than ${M.fmtG(tol)} g below your usual ${M.fmtG(perMeal)} g.`);
        if (sentences.length) {
          out.push(insight('day.carbs.meal_off', 'info', R.CARBS, sentences.join(' '),
            { goal: M.whole(perMeal), tolerance: M.whole(tol), above: roundObj(above), below: roundObj(below) }, [], ['carb-counting']));
        } else if (logged >= 2) {
          out.push(insight('day.carbs.consistent', 'good', R.CARBS, `All ${logged} meals were within ${M.fmtG(tol)} g of your ${M.fmtG(perMeal)} g carb goal.`,
            { meals: logged, goal: M.whole(perMeal), tolerance: M.whole(tol) }));
        }
      }
      const hypo = eaten.filter((e) => e.hypo);
      if (hypo.length) {
        const c = sumOf(hypo, R.CARBS), k = sumOf(hypo, R.K);
        let msg = `You logged ${plural(hypo.length, 'low-glucose treatment')} (${M.fmtG(c)} g carbs, ${M.fmtInt(k)} mg `
          + 'potassium). They are not counted in the meal carb check.';
        const numbers = { count: hypo.length, carbs_g: R.roundTo(c, 1), potassium_mg: M.whole(k) };
        if (hypo.some((e) => (e.nutrients[R.K] || 0.0) > R.HYPO_INSIGHT_K_MG)) {
          const best = bestHypoFood(ctx.foods, ctx.prefs);
          if (best != null && best[2] <= R.HYPO_BEST_MAX_K_MG) {
            msg += ` ${M.safeName(best[0].name)} would treat the same low with ${M.fmtInt(best[2])} mg potassium.`;
            numbers.better_food_id = best[0].id;
          }
        }
        out.push(insight('day.hypo.logged', 'info', R.CARBS, msg, numbers, [], ['treating-a-low']));
      }
      const high = eaten.filter((e) => !e.hypo && (e.nutrients[R.K] || 0.0) > R.HIGH_K_ENTRY_MG);
      if (high.length >= 2) {
        const sev = kLevel === 'caution' || kLevel === 'over' ? 'attention' : 'info';
        out.push(insight('day.high_k.count', sev, R.K, `You had ${high.length} high-potassium portions today: ${M.joinAnd(named(high))}.`,
          { count: high.length }, [], ['potassium']));
      }
      const additive = eaten.filter((e) => e.flags.has('phosphate_additive'));
      if (additive.length) {
        const names = named(additive);
        const n = names.length;
        out.push(insight('day.additives', 'info', R.P,
          `${plural(n, 'food')} today had phosphate additives: ${M.joinAnd(names.map((x) => x.split(' (')[0]))}. `
          + 'Additive phosphorus is almost fully absorbed.', { count: n }, [], ['phosphate-additives']));
      }
      const pt = targets[R.PROTEIN];
      const pMin = R.targetMin(pt), pMax = R.targetMax(pt);
      const protein = sumOf(eaten, R.PROTEIN);
      if (dialysis && pMin != null && protein < pMin) {
        out.push(insight('day.protein.low', 'attention', R.PROTEIN,
          `Protein was ${M.fmtG(protein)} g, below your ${M.fmtG(pMin)} g minimum. On dialysis your `
          + 'body needs more protein, not less.', { value: R.roundTo(protein, 1), min: M.whole(pMin) }, [], ['protein']));
      }
      if (!dialysis && pMax != null && protein > pMax) {
        out.push(insight('day.protein.high', 'info', R.PROTEIN,
          `Protein was ${M.fmtG(protein)} g, above your ${M.fmtG(pMax)} g maximum. Protein is judged `
          + 'on the weekly average.', { value: R.roundTo(protein, 1), max: M.whole(pMax) }, [], ['protein']));
      }
      const missingKeys = [R.K, R.P, R.NA].filter((k) => eaten.some((e) => e.nutrients[k] == null));
      if (missingKeys.length) {
        const foodsMissing = new Set(eaten.filter((e) => missingKeys.some((k) => e.nutrients[k] == null)).map((e) => e.food_id));
        const words = M.joinAnd(missingKeys.map((k) => M.NUTRIENT_WORD[k])).split(' and ').join(' or ');
        const n = foodsMissing.size;
        out.push(insight('day.unknown', 'info', missingKeys[0], `${plural(n, 'food')} had no ${words} value, so today's total may be low.`,
          { count: n, nutrients: missingKeys }, [], ['label-reading']));
      }
      const inter = interdialytic(ctx, eaten);
      if (inter != null) out.push(inter);
      const kcalGoal = R.targetMax(targets[R.KCAL]);
      const mealsLogged = new Set(eaten.filter((e) => !e.hypo).map((e) => e.meal)).size;
      if (kcalGoal != null && mealsLogged >= 3 && eaten.every((e) => e.nutrients[R.KCAL] != null)) {
        const kcal = sumOf(eaten, R.KCAL);
        if (kcal < R.ENERGY_LOW_INSIGHT_FRACTION * kcalGoal) {
          out.push(insight('day.energy.low', 'info', R.KCAL,
            `Calories were ${M.fmtInt(kcal)} kcal, ${M.pct(kcal / kcalGoal)} % of your ${M.fmtInt(kcalGoal)} kcal goal. Eating too little can cause muscle loss; fats such as `
            + 'olive oil add calories without potassium or phosphorus.', { value: M.whole(kcal), goal: M.whole(kcalGoal) }, [], ['eating-enough']));
        }
      }
      if (!out.some((i) => i.severity === 'warning' || i.severity === 'attention')) {
        const within = [];
        for (const key of [R.K, R.P, R.NA, R.FLUID]) {
          const t = R.targetMax(targets[key]);
          if (t != null && sumOf(eaten, key) <= t) within.push(M.NUTRIENT_WORD[key]);
        }
        if (within.length) {
          const verb = within.length > 1 ? 'all stayed' : 'stayed';
          const pl = within.length > 1 ? 'targets' : 'target';
          out.push(insight('day.all_good', 'good', null, `${M.capitalise(M.joinAnd(within))} ${verb} within your ${pl} today.`));
        }
      }
    }
    return { status: 'ok', rules_version: R.RULES_VERSION, date: ctx.date, insights: orderInsights(out), planned_excluded: planned,
      notes: [M.DISCLAIMER] };
  }

  function interdialytic(ctx, eaten) {
    if (ctx.profile.dialysis !== 'hemodialysis' || !ctx.profile.dialysis_days.length) return null;
    const interval = B.interdialyticInterval(ctx.date, ctx.profile.dialysis_days);
    if (interval == null) return null;
    const since = interval.since, days = Math.trunc(interval.days);
    const parts = [];
    let worst = 'ok';
    const numbers = { since, days };
    let firstKey = null;
    for (const key of [R.K, R.FLUID]) {
      const t = R.targetMax(ctx.profile.targets[key]);
      if (t == null) continue;
      const total = sumOf(ctx.history.filter((h) => since <= h.date && h.date < ctx.date), key) + sumOf(eaten, key);
      const limit = t * days;
      const fraction = total / limit;
      const level = fraction > 1.0 ? 'over' : fraction >= ctx.profile.warn_fraction ? 'caution' : 'ok';
      if (level === 'ok') continue;
      worst = level === 'over' || worst === 'over' ? 'over' : 'caution';
      const unit = NUT[key].unit;
      parts.push(`${M.NUTRIENT_WORD[key]} adds up to ${M.fmtAmount(key, total)} ${unit} of ${M.fmtAmount(key, limit)} ${unit}`);
      numbers[key] = { total: M.whole(total), limit: M.whole(limit) };
      firstKey = firstKey || key;
    }
    if (!parts.length) return null;
    const sev = worst === 'over' ? 'warning' : 'attention';
    const msg = `Since dialysis on ${WEEKDAY[R.weekday(since)]}, ${M.joinAnd(parts)} for ${plural(days, 'day')}.`;
    return insight('day.interdialytic', sev, firstKey, msg, numbers, [], ['dialysis-days']);
  }

  // ---- period ------------------------------------------------------------------------------------
  function byDay(entries) {
    const out = new Map();
    for (const e of entries) { if (!out.has(e.date)) out.set(e.date, []); out.get(e.date).push(e); }
    return out;
  }

  function periodInsights(profile, prefs, start, end, entries, previous = []) {
    const span = R.daysBetween(start, end) + 1;
    const days = byDay(entries.filter((e) => start <= e.date && e.date <= end));
    const logged = [...days.keys()].sort(R.cmpStr);
    const n = logged.length;
    const base = { status: 'ok', rules_version: R.RULES_VERSION, start, end, days: span, logged_days: n, notes: [M.DISCLAIMER] };
    if (n < R.MIN_LOGGED_DAYS) {
      base.insights = [insight('period.too_few_days', 'info', null, 'Log at least 3 days to see weekly insights.',
        { logged_days: n, needed: R.MIN_LOGGED_DAYS })];
      return base;
    }
    const targets = profile.targets;
    const dialysis = profile.dialysis !== 'none';
    const weekWord = span === 7 ? 'this week' : `in these ${span} days`;
    const allEntries = [];
    for (const d of logged) allEntries.push(...days.get(d));
    const out = [];
    if (n < span) out.push(insight('period.coverage', 'info', null, `You logged ${n} of ${span} days; averages use logged days only.`,
      { logged_days: n, days: span }));
    const dayTotals = new Map();
    for (const d of logged) {
      const t = {};
      for (const k of [R.K, R.P, R.NA, R.FLUID, R.PROTEIN, R.KCAL, R.CARBS]) t[k] = sumOf(days.get(d), k);
      dayTotals.set(d, t);
    }
    const average = (key) => { let s = 0; for (const d of logged) s += dayTotals.get(d)[key]; return s / n; };

    for (const key of [R.P, R.PROTEIN, R.KCAL]) {
      const t = R.targetMax(targets[key]);
      if (t == null) continue;
      const avg = average(key);
      if (avg <= t) continue;
      const above = logged.filter((d) => dayTotals.get(d)[key] > t).length;
      const src = sources(allEntries, key);
      const unit = NUT[key].unit;
      let msg = `${LABEL[key]} averaged ${M.fmtAmount(key, avg)} ${unit} a day on the ${n} days you logged, above your `
        + `${M.fmtAmount(key, t)} ${unit} target. It was above target on ${above} of ${n} days`;
      if (src.length >= 2) msg += `; the main sources were ${src[0].short_name} and ${src[1].short_name}.`;
      else if (src.length === 1) msg += `; the main source was ${src[0].short_name}.`;
      else msg += '.';
      out.push(insight(`period.${key}.average_over`, 'attention', key, msg,
        { average: M.whole(avg), target: M.whole(t), days_above: above, logged_days: n }, src, [T.NUTRIENT_TOPIC[key]]));
    }
    const pmin = R.targetMin(targets[R.PROTEIN]);
    if (dialysis && pmin != null && average(R.PROTEIN) < pmin) {
      const avg = average(R.PROTEIN);
      out.push(insight('period.protein.average_low', 'attention', R.PROTEIN,
        `Protein averaged ${M.fmtG(avg)} g a day, below your ${M.fmtG(pmin)} g minimum.`,
        { average: R.roundTo(avg, 1), min: M.whole(pmin) }, [], ['protein']));
    }
    const stayed = [];
    for (const key of [R.K, R.NA, R.FLUID]) {
      const t = R.targetMax(targets[key]);
      if (t == null) continue;
      const overDays = logged.filter((d) => dayTotals.get(d)[key] > t);
      if (!overDays.length) stayed.push(M.NUTRIENT_WORD[key]);
      if (overDays.length < 2) continue;
      const sev = 2 * overDays.length >= n ? 'warning' : 'attention';
      const wd = overDays.map((d) => R.weekday(d));
      const src = sources(overDays.flatMap((d) => days.get(d)), key);
      let msg = `${LABEL[key]} was over your limit on ${overDays.length} of ${n} days (${wd.map((w) => WEEKDAY_SHORT[w]).join(', ')}).`;
      if (src.length >= 2) msg += ` The main sources were ${src[0].short_name} and ${src[1].short_name}.`;
      else if (src.length === 1) msg += ` The main source was ${src[0].short_name}.`;
      if (wd.every((w) => w >= 5)) msg += ' Mostly at the weekend.';
      out.push(insight(`period.${key}.days_over`, sev, key, msg, { days_over: overDays.length, logged_days: n, dates: overDays }, src,
        [T.NUTRIENT_TOPIC[key]]));
    }
    for (const key of [R.K, R.NA]) {
      if (R.targetMax(targets[key]) == null) continue;
      let total = 0;
      for (const d of logged) total += dayTotals.get(d)[key];
      if (total <= 0) continue;
      for (const meal of R.SLOT_ORDER) {
        const share = sumOf(allEntries.filter((e) => e.meal === meal), key) / total;
        if (share >= R.MEAL_SHARE_MIN) {
          out.push(insight(`period.meal_share.${key}`, 'info', key, `${M.capitalise(meal)} gave ${M.pct(share)} % of your ${M.NUTRIENT_WORD[key]} ${weekWord}.`,
            { meal, share_pct: M.pct(share) }, [], [T.NUTRIENT_TOPIC[key]]));
          break;
        }
      }
    }
    const perMeal = R.targetMax(targets.carbs_per_meal_g);
    if (profile.diabetes !== 'none' && perMeal != null) {
      const tol = Number(prefs.carb_tolerance_g);
      const stats = [];
      for (const meal of R.MAIN_MEALS) {
        const values = [];
        for (const d of logged) {
          const rows = days.get(d).filter((e) => e.meal === meal && !e.hypo);
          if (rows.length) values.push(sumOf(rows, R.CARBS));
        }
        if (values.length) {
          const within = values.filter((v) => Math.abs(v - perMeal) <= tol).length;
          stats.push([meal, within, values.length, Math.min(...values), Math.max(...values)]);
        }
      }
      if (stats.length) {
        const best = R.maxBy(stats, (s) => [s[1] / s[2], s[2], -R.MAIN_MEALS.indexOf(s[0])]);
        const worst = R.minBy(stats, (s) => [s[1] / s[2], -s[2], R.MAIN_MEALS.indexOf(s[0])]);
        let msg = `${M.capitalise(best[0])} carbs were within ${M.fmtG(tol)} g of your ${M.fmtG(perMeal)} g goal on ${best[1]} of ${best[2]} days.`;
        if (worst[0] !== best[0] && worst[1] < worst[2]) msg += ` ${M.capitalise(worst[0])} varied more (${M.fmtG(worst[3])}–${M.fmtG(worst[4])} g).`;
        const allWithin = stats.every((s) => s[1] === s[2]);
        const numbers = {};
        for (const [m, w, c, lo, hi] of stats) numbers[m] = { within: w, days: c, min: R.roundTo(lo, 1), max: R.roundTo(hi, 1) };
        out.push(insight('period.carbs.consistency', allWithin ? 'good' : 'info', R.CARBS, msg, numbers, [], ['carb-counting']));
      }
    }
    const hypo = allEntries.filter((e) => e.hypo);
    if (hypo.length >= R.PERIOD_HYPO_MIN) {
      out.push(insight('period.hypo.count', 'info', R.CARBS, `You logged ${hypo.length} low-glucose treatments ${weekWord}. Your diabetes team may want to know.`,
        { count: hypo.length }, [], ['treating-a-low']));
    }
    const additiveDays = logged.filter((d) => days.get(d).some((e) => e.flags.has('phosphate_additive')));
    if (additiveDays.length >= 2) {
      const counts = new Map();
      for (const d of logged) {
        for (const e of days.get(d)) {
          if (!e.flags.has('phosphate_additive')) continue;
          if (!counts.has(e.food_id)) counts.set(e.food_id, [e.name, 0]);
          counts.get(e.food_id)[1] += 1;
        }
      }
      const rows = R.sortBy([...counts.values()], (r) => [-r[1], R.casefold(r[0])]).slice(0, 3);
      const shorts = F.shortNames(rows.map((r) => r[0]));
      const listed = rows.map(([, c], i) => `${shorts[i]} (${plural(c, 'time')})`).join(', ');
      out.push(insight('period.additives', 'info', R.P, `Phosphate-additive foods were eaten on ${additiveDays.length} of ${n} days: ${listed}.`,
        { days: additiveDays.length, logged_days: n }, [], ['phosphate-additives']));
    }
    const prevDays = byDay(previous);
    if (prevDays.size >= R.MIN_LOGGED_DAYS) {
      for (const key of [R.K, R.P]) {
        if (R.targetMax(targets[key]) == null) continue;
        let s = 0;
        for (const v of prevDays.values()) s += sumOf(v, key);
        const prevAvg = s / prevDays.size;
        if (prevAvg <= 0) continue;
        const change = (average(key) - prevAvg) / prevAvg;
        if (Math.abs(change) >= R.PERIOD_CHANGE_MIN) {
          const word = change < 0 ? 'less' : 'more';
          const before = span === 7 ? 'the week before' : 'the period before';
          out.push(insight(`period.change.${key}`, change < 0 ? 'good' : 'info', key, `${LABEL[key]} averaged ${M.pct(Math.abs(change))} % ${word} than ${before}.`,
            { change_pct: M.pct(change), previous_average: M.whole(prevAvg) }, [], [T.NUTRIENT_TOPIC[key]]));
        }
      }
    }
    if (!out.some((i) => i.severity === 'warning' || i.severity === 'attention') && stayed.length) {
      out.push(insight('period.all_good', 'good', null, `${M.capitalise(M.joinAnd(stayed))} stayed within your limit on all ${n} days you logged.`,
        { logged_days: n }));
    }
    base.insights = orderInsights(out);
    return base;
  }

  // (start, end, previous start, previous end): default the 7 days ending yesterday.
  function periodBounds(start, end, today) {
    let s, e;
    if (end == null && start == null) {
      e = R.addDays(today, -1);
      s = R.addDays(e, -(R.PERIOD_DEFAULT_DAYS - 1));
    } else {
      s = start ? start : R.addDays(end, -(R.PERIOD_DEFAULT_DAYS - 1));
      e = end ? end : R.addDays(s, R.PERIOD_DEFAULT_DAYS - 1);
    }
    const span = R.daysBetween(s, e) + 1;
    const prevEnd = R.addDays(s, -1);
    const prevStart = R.addDays(prevEnd, -(span - 1));
    return [s, e, prevStart, prevEnd];
  }

  GE.insights = { insight, orderInsights, sources, named, sumOf, bestHypoFood, dayInsights, periodInsights, periodBounds, byDay };
})(typeof window !== 'undefined' ? window : globalThis);
