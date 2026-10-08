/* Kidney Diet Log — Today view: date navigation, alerts, daily status bars, meals with their
   entries, all-nutrient totals and the "Last 7 days" strip (with "since last dialysis"). Meal
   guidance (js/views/guidance.js) adds the Meal ideas card, a "What fits" link per meal, the
   "treated a low" badge and the end-of-day insights. Offline (js/offline.js), the day may be this
   device's saved copy ("Saved at …") and entries waiting to sync carry a "waiting to sync" or "not
   saved" badge; they are counted in the day and open Settings → This device instead of the editor. */
(() => {
  'use strict';
  const KH = window.KH;
  const { h, $, clear, api, state, toast, toastError, router } = KH;
  const { NUT, NUTRIENTS, MEALS, ROLE_WORD, fmtNum, fmtWithUnit, fmtServings, pct } = KH.rules;
  const { STATUS_ORDER, ROW_NUMBERS, STRIP_KEYS, INTERDIALYTIC_KEYS, LEVEL_TEXT, ratingIcon, levelPill, plusIcon, dashedIcon, checkIcon, isPlanned,
    unknownOf, notListed, foodsNotListing, atLeast, atLeastWords } = KH.ui;
  const { todayStr, addDays, fmtDateLong, fmtDateShort, fmtMonthDay } = KH.util;
  const views = () => KH.views;

  const dateInput = $('#date-input');
  const dateLabel = $('#date-label');
  const alertsEl = $('#alerts');
  const statusBarsEl = $('#status-bars');
  const mealsEl = $('#meals');
  const totalsAllEl = $('#totals-all');
  const backToToday = $('#date-today');

  function setDate(d) {
    state.date = d;
    dateInput.value = d;
    dateLabel.textContent = fmtDateLong(d);
    backToToday.hidden = d === todayStr();
    loadDay();
  }
  $('#date-prev').addEventListener('click', () => setDate(addDays(state.date, -1)));
  $('#date-next').addEventListener('click', () => setDate(addDays(state.date, 1)));
  backToToday.addEventListener('click', () => setDate(todayStr()));
  dateInput.addEventListener('change', () => { if (/^\d{4}-\d{2}-\d{2}$/.test(dateInput.value)) setDate(dateInput.value); });

  let dayRequest = 0;
  async function loadDay() {
    const reqId = ++dayRequest;
    dateInput.value = state.date;
    dateLabel.textContent = fmtDateLong(state.date);
    backToToday.hidden = state.date === todayStr();
    if (state.dayLoadedFor !== state.date) mealsEl.style.opacity = '0.6';
    loadWeekStrip();
    try {
      const day = await api.day(state.date);
      if (reqId !== dayRequest) return;
      state.day = day;
      state.dayLoadedFor = state.date;
      renderToday();
    } catch (e) {
      if (reqId === dayRequest) toastError(e);
    } finally {
      mealsEl.style.opacity = '';
    }
  }

  function renderToday() {
    const day = state.day;
    if (!day) return;
    const counts = day.counts || { eaten: (day.entries || []).filter((e) => !isPlanned(e)).length, planned: (day.entries || []).filter(isPlanned).length };
    // Alerts (eaten)
    clear(alertsEl);
    const saved = KH.offline ? KH.offline.servedOffline(day) : null;
    if (saved) {
      const at = saved.fetched_at ? new Date(saved.fetched_at).toLocaleString('en-US', { weekday: 'short', hour: 'numeric', minute: '2-digit' }) : null;
      alertsEl.append(h('p', { class: 'offline-note', role: 'note' }, at ? `Offline: this is the copy this device saved ${at}. ` : 'Offline: this device has no copy of this day. ',
        'Food you add now waits here and syncs when your server can be reached.'));
    }
    const p = state.profile;
    if (p && (p.ckd_stage_chosen === false || p.diabetes_chosen === false)) {
      alertsEl.append(h('p', { class: 'offline-note profile-choose-note', role: 'note' },
        'Your CKD stage and diabetes type are not chosen yet, so the app uses stage 3b and type 1 diabetes for now. ',
        h('button', { class: 'link-btn', type: 'button', onclick: () => router.show('profile') }, 'Choose them in Profile')));
    }
    for (const a of day.alerts || []) {
      const lvl = a.level === 'over' ? 'over' : 'caution';
      const more = KH.learn ? KH.learn.forWarning(a) : null; // the nutrient's handbook page
      alertsEl.append(h('div', { class: `alert level-${lvl}` },
        ratingIcon(lvl, { label: lvl === 'over' ? 'Over limit' : 'Near limit' }),
        h('div', {}, h('b', {}, lvl === 'over' ? 'Over limit. ' : 'Near limit. '), a.message, more ? [' ', more] : null)));
    }
    // Projected alerts: only worth showing when something is planned and the level differs from the eaten alert.
    const projEl = $('#projected-alerts');
    clear(projEl);
    if (counts.planned > 0) {
      // v0.3.1: the last few days joined with the plan (periods.pattern_alerts), first: a pattern matters more than a day.
      const pattern = day.pattern_alerts || [];
      if (pattern.length) {
        projEl.append(h('div', { class: 'alerts-title' }, 'Running high over several days'));
        for (const a of pattern) {
          const lvl = a.level === 'over' ? 'over' : 'caution';
          const word = lvl === 'over' ? 'Running high' : 'Weekly average high';
          const more = KH.learn ? KH.learn.forWarning(a) : null;
          projEl.append(h('div', { class: `alert pattern level-${lvl}` }, ratingIcon(lvl, { label: word }),
            h('div', {}, h('b', {}, `${word}. `), a.message, more ? [' ', more] : null)));
        }
      }
      // A day alert and a per-meal carbohydrate alert share the nutrient key; the meal tells them apart.
      const alertKey = (a) => `${a.nutrient}|${a.meal || ''}`;
      const eatenLevel = Object.fromEntries((day.alerts || []).map((a) => [alertKey(a), a.level]));
      const shown = (day.projected_alerts || []).filter((a) => eatenLevel[alertKey(a)] !== a.level);
      if (shown.length) {
        projEl.append(h('div', { class: 'alerts-title' }, dashedIcon(), 'If you eat what\'s planned…'));
        for (const a of shown) {
          const lvl = a.level === 'over' ? 'over' : 'caution';
          // The heading already says "If you eat what's planned"; do not read the phrase twice per line.
          const text = String(a.message || '').replace(/^If you eat what's planned,\s*/i, '');
          const message = text ? text.charAt(0).toUpperCase() + text.slice(1) : a.message;
          const more = KH.learn ? KH.learn.forWarning(a) : null;
          projEl.append(h('div', { class: `alert projected level-${lvl}` },
            ratingIcon(lvl, { label: lvl === 'over' ? 'Projected over limit' : 'Projected near limit' }),
            h('div', {}, h('b', {}, lvl === 'over' ? 'Projected over. ' : 'Projected near limit. '), message, more ? [' ', more] : null)));
        }
      }
    }
    // Status bars
    clear(statusBarsEl);
    const keys = Object.keys(day.status || {}).sort((a, b) => STATUS_ORDER.indexOf(a) - STATUS_ORDER.indexOf(b));
    if (!keys.length) {
      statusBarsEl.append(h('p', { class: 'empty-state' }, 'No targets set yet. ',
        h('button', { class: 'link-btn', type: 'button', onclick: () => router.show('profile') }, 'Set your weight and targets in Profile')));
    }
    for (const key of keys) statusBarsEl.append(statusBar(key, day.status[key], counts.planned > 0 && day.projected_status ? day.projected_status[key] : null));
    const statusSub = $('#status-heading').nextElementSibling;
    if (statusSub) statusSub.textContent = counts.planned > 0 ? 'eaten / target · lighter part = planned' : 'running total / target';

    // Meals
    clear(mealsEl);
    const perMealGoal = day.targets && typeof day.targets.carbs_per_meal_g === 'number' ? day.targets.carbs_per_meal_g : null;
    const snackGoal = day.targets && typeof day.targets.carbs_per_snack_g === 'number' ? day.targets.carbs_per_snack_g : null;
    const wf = (state.profile && state.profile.warn_fraction) || 0.8;
    // v0.3.1: a meal is "over" only more than the person's tolerance above its goal (the server's alerts use the same
    // number), and carbohydrate eaten to treat a low is left out of the meal's goal: treating a low is never warned against.
    const carbTol = Number(day.carb_tolerance_g || 0);
    // A kidney-only profile (diabetes "None", v0.3.1) has no per-meal carbohydrate goal: the meal headers show no
    // carbohydrate line and the server sends no per-meal alert; the day's carbohydrate stays in the bars above.
    const mealCarbs = !(state.profile && state.profile.diabetes === 'none');
    const hypoCarbsOf = (list) => list.filter((e) => e.purpose === 'hypo').reduce((a, e) => a + ((e.nutrients && e.nutrients.carbs_g) || 0), 0);
    for (const meal of MEALS) {
      // The snack has its own carbohydrate goal when the person set one (nutrients.meal_carb_alerts does the same).
      const snackOwn = meal.key === 'snack' && snackGoal != null;
      const perMeal = snackOwn ? snackGoal : perMealGoal;
      const goalWords = snackOwn ? 'snack carbohydrate goal' : 'meal carbohydrate target';
      const entries = (day.entries || []).filter((e) => e.meal === meal.key);
      const eatenEntries = entries.filter((e) => !isPlanned(e));
      const plannedEntries = entries.filter(isPlanned);
      const mt = (day.meals && day.meals[meal.key]) || null;
      const pmt = (day.planned_meals && day.planned_meals[meal.key]) || null;
      // Entries whose food does not list a value (the totals skip them; the server counts them).
      const mu = (day.meal_unknown && day.meal_unknown[meal.key]) || countMissing(eatenEntries);
      const pmu = (day.planned_meal_unknown && day.planned_meal_unknown[meal.key]) || countMissing(plannedEntries);
      const carbsUnknown = unknownOf(mu, 'carbs_g');
      const carbs = mt ? mt.carbs_g || 0 : eatenEntries.reduce((a, e) => a + (e.nutrients.carbs_g || 0), 0);
      const plannedCarbs = pmt ? pmt.carbs_g || 0 : plannedEntries.reduce((a, e) => a + (e.nutrients.carbs_g || 0), 0);
      const hypoCarbs = hypoCarbsOf(eatenEntries);
      const counted = carbs - hypoCarbs;
      const over = perMeal != null && counted > perMeal + carbTol;
      const near = perMeal != null && !over && counted >= perMeal * wf;
      const carbsEl = h('span', { class: `meal-carbs${over ? ' over' : ''}`,
        'aria-label': `Carbohydrate eaten ${atLeastWords(fmtNum(carbs, 'carbs_g'), carbsUnknown)} grams${perMeal != null ? ` of ${perMeal} gram ${snackOwn ? 'snack goal' : 'meal target'}` : ''}`
          + (carbsUnknown ? `; ${foodsNotListing(carbsUnknown, 'carbs_g')}` : '') },
        over ? ratingIcon('over', { label: `Over ${goalWords}` }) : near ? ratingIcon('caution', { label: `Near ${goalWords}` }) : null,
        `Carbs: ${atLeast(fmtNum(carbs, 'carbs_g'), carbsUnknown)} g`,
        perMeal != null ? h('span', { class: 'of' }, ` of ${perMeal} g`) : null,
        carbsUnknown ? h('span', { class: 'not-listed' }, ` ${notListed(carbsUnknown)}`) : null);
      const headRight = h('div', { class: 'meal-head-right' }, mealCarbs ? carbsEl : null);
      if (mealCarbs && plannedEntries.length) {
        const projOver = perMeal != null && counted + plannedCarbs - hypoCarbsOf(plannedEntries) > perMeal + carbTol;
        headRight.append(h('span', { class: `meal-planned-carbs${projOver ? ' over' : ''}`, 'aria-label': `Planned: ${fmtNum(plannedCarbs, 'carbs_g')} more grams of carbohydrate` },
          `Planned: +${fmtNum(plannedCarbs, 'carbs_g')} g carbs`, projOver ? ` (${fmtNum(carbs + plannedCarbs, 'carbs_g')} g total)` : ''));
      }
      const card = h('section', { class: 'card meal', 'aria-labelledby': `meal-h-${meal.key}` },
        h('div', { class: 'meal-head' }, h('h2', { class: 'meal-name', id: `meal-h-${meal.key}` }, meal.label), headRight));
      if (!entries.length) {
        card.append(h('p', { class: 'empty-state' }, 'Nothing logged.'));
      } else {
        const ul = h('ul', { class: 'list' });
        for (const e of entries) {
          const waiting = e.pending ? ' entry-waiting' : '';
          ul.append(isPlanned(e) ? h('li', { class: `entry-planned${waiting}` }, entryRow(e), e.pending ? null : eatenButton(e)) : h('li', { class: waiting.trim() || null }, entryRow(e)));
        }
        card.append(ul);
      }
      const foot = h('div', { class: 'meal-foot' });
      if (mt && eatenEntries.length) foot.append(mealSum(mt, mu, eatenEntries.length, false));
      if (pmt && plannedEntries.length) foot.append(mealSum(pmt, pmu, plannedEntries.length, true));
      card.append(foot);
      const actions = h('div', { class: 'meal-actions' });
      actions.append(h('button', { class: 'link-btn meal-add', type: 'button', onclick: () => { state.addMealHint = meal.key; state.addStatusHint = null; router.show('add'); $('#food-search').focus(); } },
        plusIcon(), `Add to ${meal.label.toLowerCase()}`));
      const fits = KH.guidance && day.date >= todayStr() ? KH.guidance.whatFitsButton(meal.key) : null;
      if (fits) actions.append(fits);
      actions.append(h('button', { class: 'link-btn', type: 'button', onclick: (ev) => views().plan.openApplySheet({ date: day.date, meal: meal.key, trigger: ev.currentTarget }) }, 'Add saved meal'));
      if (plannedEntries.length) {
        actions.append(h('button', { class: 'link-btn', type: 'button', onclick: (ev) => markAllEaten(day.date, meal.key, ev.currentTarget) },
          checkIcon(), plannedEntries.length === 1 ? 'Mark eaten' : 'Mark all eaten'));
      }
      if (entries.length) {
        actions.append(h('button', { class: 'link-btn', type: 'button', onclick: (ev) => views().plan.openSaveMealSheet(day.date, meal.key, entries, ev.currentTarget) }, 'Save as meal'));
      }
      card.append(actions);
      mealsEl.append(card);
    }
    // All totals
    clear(totalsAllEl);
    for (const n of NUTRIENTS) {
      const eatenV = day.totals ? day.totals[n.key] : null;
      const projV = day.projected_totals ? day.projected_totals[n.key] : null;
      const unk = unknownOf(day.unknown, n.key);
      const projUnk = unknownOf(day.projected_unknown, n.key);
      const showProj = counts.planned > 0 && projV != null && (projV !== eatenV || projUnk !== unk);
      totalsAllEl.append(h('div', { class: 'ng' }, h('span', {}, n.label), h('b', {}, atLeast(fmtWithUnit(eatenV, n.key), unk),
        showProj ? h('span', { class: 'ng-proj' }, ` → ${atLeast(fmtNum(projV, n.key), projUnk)}`) : null,
        unk || (showProj && projUnk) ? h('span', { class: 'not-listed' }, ` ${notListed(showProj ? projUnk : unk)}`) : null)));
    }
    $('#totals-details > summary').textContent = counts.planned > 0 ? 'All nutrient totals for the day (eaten → projected)' : 'All nutrient totals for the day';
    if (KH.guidance) KH.guidance.today(day).catch((e) => console.warn('Meal guidance:', e));
  }

  // A goal with only a minimum (fibre, note 05 §4.8): progress toward it, never "over".
  function goalBar(key, st) {
    const n = NUT[key] || { label: key, unit: '' };
    const value = Number(st.value || 0);
    const goal = Number(st.min);
    const p = goal > 0 ? Math.round((value / goal) * 100) : 0;
    const reached = value >= goal;
    const unk = Number(st.unknown || 0); // foods that do not list it: progress may be further along
    const wrap = h('div', { class: `stat level-ok goal-only${reached ? ' goal-reached' : ''}` },
      h('div', { class: 'stat-label' }, n.label, levelPill('ok', reached ? 'Goal reached' : 'Goal')),
      h('div', { class: 'stat-value' }, h('b', {}, atLeast(fmtNum(value, key), unk)), ` of at least ${fmtNum(goal, key)} ${n.unit}`));
    const track = h('div', { class: 'stat-track', role: 'meter', 'aria-valuemin': 0, 'aria-valuemax': goal, 'aria-valuenow': value,
      'aria-label': `${n.label}: ${atLeastWords(fmtNum(value, key), unk)} of a goal of at least ${fmtNum(goal, key)} ${n.unit}, ${p} percent${reached ? ', goal reached' : ''}`
        + (unk ? `; ${foodsNotListing(unk, key)}` : '') });
    track.append(h('div', { class: `stat-fill${value ? '' : ' empty'}`, style: `width:${Math.max(0, Math.min(100, p))}%` }));
    const foot = [reached ? `${p} % of goal · goal reached` : `${atLeast(String(p), unk)} % of goal · ${fmtNum(goal - value, key)} ${n.unit} to go`];
    if (unk) foot.push(`${foodsNotListing(unk, key)}, so you may be closer`);
    wrap.append(track, h('div', { class: 'stat-foot' }, foot.join(' · ')));
    return wrap;
  }

  function statusBar(key, st, pst) {
    if (st.target == null && st.min != null) return goalBar(key, st);
    const n = NUT[key] || { label: key, unit: '' };
    const level = st.level || 'ok';
    const p = pct(st.fraction);
    // A range whose minimum equals its maximum (protein "about 56 g", note 05 §4.8) reads as one number.
    const about = KH.ui.isAboutTarget(st, key); // never for a limit (nutrients.is_about)
    const hasMin = st.min != null && !about;
    const targetText = about ? `about ${fmtNum(st.target, key)}` : hasMin ? `${fmtNum(st.min, key)}–${fmtNum(st.target, key)}` : fmtNum(st.target, key);
    // Same word as the server's alerts: goal (calories, carbohydrate), maximum (ranges, info), limit.
    const isGoal = n.role === 'goal' || n.role === 'track';
    const levelWord = (lv) => (about ? KH.ui.ABOUT_LEVEL_TEXT[lv] : lv === 'over' && hasMin ? 'Over max' : lv === 'over' && isGoal ? 'Over goal'
      : lv === 'caution' && isGoal ? 'Near goal' : LEVEL_TEXT[lv]);
    // Foods that do not list this value: the total may be higher, so it is never "OK" and nothing is "left".
    const unk = Number(st.unknown || 0);
    const nothingKnown = unk > 0 && !Number(st.value); // every food so far leaves it out (or lists 0)
    const shown = unk && level === 'ok' ? 'unknown' : level;
    const levelText = shown === 'unknown' ? LEVEL_TEXT.unknown : levelWord(level);
    const hasProj = pst && pst.value != null && (pst.value > (st.value || 0) || Number(pst.unknown || 0) > unk);
    const pp = hasProj ? pct(pst.fraction) : p;
    const projUnk = hasProj ? Number(pst.unknown || 0) : unk;
    const projLevel = hasProj ? (projUnk && (pst.level || 'ok') === 'ok' ? 'unknown' : pst.level || 'ok') : shown;
    const projWord = (lv) => (lv === 'unknown' ? LEVEL_TEXT.unknown : levelWord(lv));
    const wrap = h('div', { class: `stat level-${shown}${hasMin ? ' has-min' : ''}${hasProj ? ' has-proj' : ''}${unk ? ' incomplete' : ''}` },
      h('div', { class: 'stat-label' }, n.label, levelPill(shown, levelText)),
      h('div', { class: 'stat-value' }, h('b', {}, nothingKnown ? 'not listed' : atLeast(fmtNum(st.value, key), unk)), ` / ${targetText} ${n.unit}`,
        hasProj ? h('span', { class: `stat-proj-value level-${projLevel}` }, ` → ${atLeast(fmtNum(pst.value, key), projUnk)}`) : null));
    const ariaProj = hasProj ? `, projected ${atLeastWords(fmtNum(pst.value, key), projUnk)} ${n.unit} (${pp} percent, ${projWord(projLevel)}) with planned foods` : '';
    const ariaUnknown = unk ? `; ${foodsNotListing(unk, key)}, so the total may be higher` : '';
    const track = h('div', { class: 'stat-track', role: 'meter', 'aria-valuemin': 0, 'aria-valuemax': st.target, 'aria-valuenow': st.value,
      'aria-label': `${n.label}: ${atLeastWords(fmtNum(st.value, key), unk)} of ${targetText} ${n.unit}, ${p} percent, ${levelText}${ariaProj}${ariaUnknown}` });
    if (hasProj) {
      const left = Math.max(0, Math.min(100, p)), right = Math.max(0, Math.min(100, pp));
      track.append(h('div', { class: `stat-fill-proj level-${projLevel}`, style: `left:${left}%;width:${Math.max(0, right - left)}%` }));
      track.append(h('div', { class: `stat-proj-marker level-${projLevel}`, style: `left:${right}%`, title: `Projected ${fmtNum(pst.value, key)} ${n.unit}` }));
    }
    track.append(h('div', { class: `stat-fill${st.value ? '' : ' empty'}`, style: `width:${Math.max(0, Math.min(100, p))}%` }));
    if (hasMin && st.target) track.append(h('div', { class: 'stat-min', style: `left:${Math.min(100, (st.min / st.target) * 100).toFixed(1)}%`, title: `Minimum ${fmtNum(st.min, key)} ${n.unit}` }));
    wrap.append(track);
    const foot = nothingKnown ? [] : [`${atLeast(String(p), unk)} % of ${hasMin ? 'maximum' : about ? 'target' : ROLE_WORD[n.role] || 'limit'}`];
    if (hasMin && st.value < st.min) foot.push(`below the ${fmtNum(st.min, key)} ${n.unit} minimum so far`);
    // An "about" target within the person's tolerance (Profile, v0.3.1) is above the number but not "over".
    if (st.fraction > 1 && about && level !== 'over') foot.push(`${atLeast(fmtNum(st.value - st.target, key), unk)} ${n.unit} above, within your tolerance`);
    else if (st.fraction > 1) foot.push(`${atLeast(fmtNum(st.value - st.target, key), unk)} ${n.unit} over`);
    else if (!unk) foot.push(`${fmtNum(st.target - st.value, key)} ${n.unit} left`);
    if (hasProj) foot.push(`${atLeast(String(pp), projUnk)} % with planned`);
    if (foot.length) wrap.append(h('div', { class: 'stat-foot' }, foot.join(' · ')));
    if (unk) wrap.append(h('div', { class: 'stat-foot not-listed' }, `${foodsNotListing(unk, key)}, so the total may be higher.`));
    return wrap;
  }
  // {key: entries without a value} for entries the day has no server count for (a day this device drew offline).
  function countMissing(entries) {
    const out = {};
    for (const e of entries) for (const k of Object.keys(NUT)) if (!e.nutrients || e.nutrients[k] == null) out[k] = (out[k] || 0) + 1;
    return out;
  }
  // A meal's line of key numbers: "Protein 6.3 g · K ≥ 55 (+ 1 not listed) · P not listed · Na 43 mg".
  function mealSum(totals, unknown, entryCount, planned) {
    const sign = planned ? '+' : '';
    const part = (key, label, unit) => {
      const n = unknownOf(unknown, key);
      if (n && n >= entryCount) return `${label} not listed`;
      const value = `${sign}${fmtNum(totals[key], key)}${unit}`;
      return n ? `${label} ≥ ${value} (${notListed(n)})` : `${label} ${value}`;
    };
    // Planned protein keeps its v0.2 wording: "Planned: +12 g protein · K +… · P +… · Na +… mg".
    const proteinUnknown = unknownOf(unknown, 'protein_g');
    const protein = !planned ? part('protein_g', 'Protein', ' g')
      : proteinUnknown && proteinUnknown >= entryCount ? 'protein not listed'
        : `${proteinUnknown ? '≥ ' : ''}+${fmtNum(totals.protein_g, 'protein_g')} g protein${proteinUnknown ? ` (${notListed(proteinUnknown)})` : ''}`;
    const text = [protein, part('potassium_mg', 'K', ''), part('phosphorus_mg', 'P', ''), part('sodium_mg', 'Na', ' mg')].join(' · ');
    const missing = ['potassium_mg', 'phosphorus_mg', 'sodium_mg', 'protein_g'].filter((k) => unknownOf(unknown, k));
    return h('span', { class: `tabular meal-sum${planned ? ' planned' : ''}${missing.length ? ' incomplete' : ''}` }, planned ? `Planned: ${text}` : text);
  }

  function entryRow(e) {
    const planned = isPlanned(e);
    const amount = e.grams != null ? `${fmtNum(e.grams, 'fluid_ml')} g (${fmtServings(e.servings)})` : fmtServings(e.servings);
    const nums = h('div', { class: 'row-nums' });
    for (const k of ROW_NUMBERS) {
      // A value the food does not list is said so, never "0" or a bare dash.
      nums.append(e.nutrients[k] == null
        ? h('span', { class: 'n not-listed', 'aria-label': `${NUT[k].label} not listed` }, `${NUT[k].short} `, h('b', {}, 'not listed'))
        : h('span', { class: 'n' }, `${NUT[k].short} `, h('b', {}, fmtNum(e.nutrients[k], k)), ` ${NUT[k].unit}`));
    }
    // An entry still on this device (js/offline.js): it cannot be edited until it reaches the server.
    const waiting = e.pending ? (e.failed ? 'not saved' : 'waiting to sync') : null;
    const label = e.pending ? `${e.food_name}, ${amount}, ${waiting}: open This device` : `Edit ${planned ? 'planned ' : ''}${e.food_name}, ${amount}${e.purpose === 'hypo' ? ', used to treat a low' : ''}`;
    const btn = h('button', { class: `row-btn${planned ? ' planned' : ''}`, type: 'button', 'aria-label': label },
      ratingIcon(e.kidney_rating),
      h('div', { class: 'row-main' },
        h('div', { class: 'row-title' }, e.food_name, planned ? h('span', { class: 'badge planned' }, 'planned') : null,
          waiting ? h('span', { class: `badge ${e.failed ? 'failed' : 'pending'}` }, waiting) : null, KH.guidance ? KH.guidance.lowBadge(e) : null),
        h('div', { class: 'row-sub' }, h('span', { class: 'entry-servings' }, amount), e.note ? h('span', { class: 'entry-note' }, ` · ${e.note}`) : null)),
      nums);
    btn.addEventListener('click', () => {
      if (!e.pending) { views().add.openEntrySheet('edit', { entry: e, trigger: btn }); return; }
      toast(e.failed ? 'This entry did not reach your server. Review it in Settings → This device.' : 'This entry is waiting to sync. You can change it once it has reached your server.');
      $('#sync-badge').click();
    });
    return btn;
  }
  function eatenButton(e) {
    const b = h('button', { class: 'btn secondary eaten-btn', type: 'button', 'aria-label': `Mark ${e.food_name} as eaten` }, checkIcon(), 'Eaten');
    b.addEventListener('click', async () => {
      b.disabled = true;
      try {
        await api.updateEntry(e.id, { status: 'eaten' });
        toast(`${e.food_name} marked as eaten`, 'ok');
        await loadDay();
      } catch (err) { toastError(err); b.disabled = false; }
    });
    return b;
  }
  async function markAllEaten(date, meal, btn) {
    if (btn) btn.disabled = true;
    try {
      const res = await api.markEaten(meal ? { date, meal } : { date });
      const n = res && typeof res.updated === 'number' ? res.updated : 0;
      if (res && res.pending) toast(`Saved on this device: ${n || 'planned'} ${n === 1 ? 'entry' : 'entries'} marked as eaten when your server can be reached`, 'ok');
      else toast(n ? `${n} ${n === 1 ? 'entry' : 'entries'} marked as eaten` : 'Nothing was planned', 'ok');
      await loadDay();
    } catch (err) { toastError(err); if (btn) btn.disabled = false; }
  }

  // ---- "Last 7 days" strip -------------------------------------------------
  const weekStripBody = $('#week-strip-body');
  let stripRequest = 0;
  $('#week-strip-trends').addEventListener('click', () => router.show('trends'));
  async function loadWeekStrip() {
    const reqId = ++stripRequest;
    const end = state.date;
    const start = addDays(end, -6);
    $('#week-strip-heading').textContent = end === todayStr() ? 'Last 7 days' : `7 days to ${fmtMonthDay(end)}`;
    try {
      const sum = await api.summary(start, end);
      if (reqId !== stripRequest) return;
      renderWeekStrip(sum);
    } catch (e) {
      if (reqId !== stripRequest) return;
      clear(weekStripBody);
      weekStripBody.append(h('p', { class: 'empty-state' }, `Weekly summary unavailable (${e.detail || e.message}).`));
    }
  }
  function renderWeekStrip(sum) {
    clear(weekStripBody);
    const nutrients = sum.nutrients || {};
    const keys = STRIP_KEYS.filter((k) => nutrients[k]);
    $('#week-strip-sub').textContent = sum.logged_days ? `average per logged day · ${sum.logged_days} of ${sum.days} days logged` : 'no days logged yet';
    if (!keys.length) {
      weekStripBody.append(h('p', { class: 'empty-state' }, 'Set targets in Profile to see weekly averages.'));
    } else {
      const grid = h('div', { class: 'strip-grid' });
      for (const key of keys) {
        const nt = nutrients[key];
        const n = NUT[key];
        const level = nt.level || 'ok';
        const frac = nt.fraction != null ? Math.max(0, Math.min(1, nt.fraction)) : 0;
        // Days with foods that do not list the value: the average misses them, so it may be higher.
        const unkDays = Number(nt.unknown_days || 0);
        const shown = unkDays && level === 'ok' ? 'unknown' : level;
        const avgText = nt.average == null ? '—' : atLeast(fmtNum(nt.average, key), unkDays);
        const avgWords = nt.average == null ? 'no data' : atLeastWords(fmtNum(nt.average, key), unkDays);
        const unkText = unkDays ? `${unkDays} ${unkDays === 1 ? 'day has' : 'days have'} foods that do not list ${n.label.toLowerCase()}` : '';
        const cell = h('div', { class: `strip-cell level-${shown}`, role: 'group', 'aria-label': `${n.label}: average ${avgWords} of ${fmtNum(nt.target, key)} ${n.unit} per day${nt.level ? `, ${LEVEL_TEXT[shown]}` : ''}${nt.days_over ? `, ${nt.days_over} days over` : ''}${unkText ? `; ${unkText}` : ''}` },
          h('div', { class: 'strip-label' }, n.label, nt.assessment === 'weekly_average' ? h('span', { class: 'strip-tag', title: 'Judged on the weekly average' }, 'avg') : null),
          h('div', { class: 'strip-value' }, h('b', {}, avgText), h('span', { class: 'muted' }, ` / ${fmtNum(nt.target, key)} ${n.unit}`)),
          h('div', { class: 'strip-track' }, h('div', { class: 'strip-fill', style: `width:${Math.round(frac * 100)}%` })),
          h('div', { class: 'strip-foot' }, nt.average == null ? 'no data' : `${atLeast(String(pct(nt.fraction)), unkDays)} %${nt.days_over ? ` · ${nt.days_over} ${nt.days_over === 1 ? 'day' : 'days'} over` : ''}`),
          unkDays ? h('div', { class: 'strip-foot not-listed' }, `${unkDays} ${unkDays === 1 ? 'day' : 'days'} not complete`) : null);
        grid.append(cell);
      }
      weekStripBody.append(grid);
    }
    const inter = sum.interdialytic;
    if (inter && inter.nutrients && Object.keys(inter.nutrients).length) {
      weekStripBody.append(interdialyticBlock(inter, true));
    }
  }
  function interdialyticBlock(inter, compact) {
    const wrap = h('div', { class: `interdialytic${compact ? ' compact' : ''}`, role: 'group', 'aria-labelledby': compact ? 'inter-h-compact' : 'inter-h' });
    const since = fmtDateShort(inter.since), next = inter.next ? fmtDateShort(inter.next) : null;
    wrap.append(h('div', { class: 'inter-head' },
      h('h3', { class: 'inter-title', id: compact ? 'inter-h-compact' : 'inter-h' }, 'Since last dialysis'),
      h('span', { class: 'muted small' }, `${since} · ${inter.days} ${inter.days === 1 ? 'day' : 'days'}${next ? ` · next ${next}` : ''}`)));
    const list = h('div', { class: 'inter-list' });
    for (const key of INTERDIALYTIC_KEYS) {
      const it = inter.nutrients[key];
      if (!it) continue;
      const n = NUT[key];
      const level = it.level || 'ok';
      const unk = Number(it.unknown_entries || 0);
      const shown = unk && level === 'ok' ? 'unknown' : level;
      list.append(h('div', { class: `inter-row level-${shown}` },
        h('span', { class: 'inter-label' }, n.label),
        h('div', { class: 'strip-track' }, h('div', { class: 'strip-fill', style: `width:${Math.round(Math.max(0, Math.min(1, it.fraction || 0)) * 100)}%` })),
        h('span', { class: 'inter-nums tabular', 'aria-label': `${atLeastWords(fmtNum(it.total, key), unk)} of ${fmtNum(it.limit, key)} ${n.unit}${unk ? `; ${foodsNotListing(unk, key)}` : ''}` },
          h('b', {}, atLeast(fmtNum(it.total, key), unk)), ` / ${fmtNum(it.limit, key)} ${n.unit}`, unk ? h('span', { class: 'not-listed' }, ` ${notListed(unk)}`) : null),
        levelPill(shown, `${atLeast(String(pct(it.fraction)), unk)} %`)));
    }
    // Fluid matters most between sessions; without a fluid target the server leaves it out, so
    // say it is not tracked and lead to the target instead of silently dropping the row.
    if (!inter.nutrients.fluid_ml) {
      const go = h('button', { type: 'button', class: 'link-btn' }, 'Set a fluid limit');
      go.addEventListener('click', () => {
        router.show('profile');
        KH.loadProfile().then(() => { const f = $('#tg-fluid_ml'); f.scrollIntoView({ block: 'center' }); f.focus({ preventScroll: true }); }).catch(() => {});
      });
      list.append(h('div', { class: 'inter-row untracked' },
        h('span', { class: 'inter-label' }, 'Fluid'),
        h('span', { class: 'inter-note' }, 'Not tracked: no daily fluid limit set'), go));
    }
    wrap.append(list);
    if (!compact) wrap.append(h('p', { class: 'hint' }, 'Limit = daily target × days since the last session. Intake on a dialysis day counts toward the next session.'));
    return wrap;
  }

  router.register('today', () => loadDay());
  KH.views.today = { setDate, loadDay, renderToday, markAllEaten, interdialyticBlock };
})();
