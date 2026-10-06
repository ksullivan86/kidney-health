/* Kidney Diet Log — Today view: date navigation, alerts, daily status bars, meals with their
   entries, all-nutrient totals and the "Last 7 days" strip (with "since last dialysis"). */
(() => {
  'use strict';
  const KH = window.KH;
  const { h, $, clear, api, state, toast, toastError, router } = KH;
  const { NUT, NUTRIENTS, MEALS, ROLE_WORD, fmtNum, fmtWithUnit, fmtServings, pct } = KH.rules;
  const { STATUS_ORDER, ROW_NUMBERS, STRIP_KEYS, INTERDIALYTIC_KEYS, LEVEL_TEXT, ratingIcon, levelPill, plusIcon, dashedIcon, checkIcon, isPlanned } = KH.ui;
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
    for (const a of day.alerts || []) {
      const lvl = a.level === 'over' ? 'over' : 'caution';
      alertsEl.append(h('div', { class: `alert level-${lvl}` },
        ratingIcon(lvl, { label: lvl === 'over' ? 'Over limit' : 'Near limit' }),
        h('div', {}, h('b', {}, lvl === 'over' ? 'Over limit. ' : 'Near limit. '), a.message)));
    }
    // Projected alerts: only worth showing when something is planned and the level differs from the eaten alert.
    const projEl = $('#projected-alerts');
    clear(projEl);
    if (counts.planned > 0) {
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
          projEl.append(h('div', { class: `alert projected level-${lvl}` },
            ratingIcon(lvl, { label: lvl === 'over' ? 'Projected over limit' : 'Projected near limit' }),
            h('div', {}, h('b', {}, lvl === 'over' ? 'Projected over. ' : 'Projected near limit. '), message)));
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
    const perMeal = day.targets && typeof day.targets.carbs_per_meal_g === 'number' ? day.targets.carbs_per_meal_g : null;
    const wf = (state.profile && state.profile.warn_fraction) || 0.8;
    for (const meal of MEALS) {
      const entries = (day.entries || []).filter((e) => e.meal === meal.key);
      const eatenEntries = entries.filter((e) => !isPlanned(e));
      const plannedEntries = entries.filter(isPlanned);
      const mt = (day.meals && day.meals[meal.key]) || null;
      const pmt = (day.planned_meals && day.planned_meals[meal.key]) || null;
      const carbs = mt ? mt.carbs_g || 0 : eatenEntries.reduce((a, e) => a + (e.nutrients.carbs_g || 0), 0);
      const plannedCarbs = pmt ? pmt.carbs_g || 0 : plannedEntries.reduce((a, e) => a + (e.nutrients.carbs_g || 0), 0);
      const over = perMeal != null && carbs > perMeal;
      const near = perMeal != null && !over && carbs >= perMeal * wf;
      const carbsEl = h('span', { class: `meal-carbs${over ? ' over' : ''}`, 'aria-label': `Carbohydrate eaten ${fmtNum(carbs, 'carbs_g')} grams${perMeal != null ? ` of ${perMeal} gram meal target` : ''}` },
        over ? ratingIcon('over', { label: 'Over meal carbohydrate target' }) : near ? ratingIcon('caution', { label: 'Near meal carbohydrate target' }) : null,
        `Carbs: ${fmtNum(carbs, 'carbs_g')} g`,
        perMeal != null ? h('span', { class: 'of' }, ` of ${perMeal} g`) : null);
      const headRight = h('div', { class: 'meal-head-right' }, carbsEl);
      if (plannedEntries.length) {
        const projOver = perMeal != null && carbs + plannedCarbs > perMeal;
        headRight.append(h('span', { class: `meal-planned-carbs${projOver ? ' over' : ''}`, 'aria-label': `Planned: ${fmtNum(plannedCarbs, 'carbs_g')} more grams of carbohydrate` },
          `Planned: +${fmtNum(plannedCarbs, 'carbs_g')} g carbs`, projOver ? ` (${fmtNum(carbs + plannedCarbs, 'carbs_g')} g total)` : ''));
      }
      const card = h('section', { class: 'card meal', 'aria-labelledby': `meal-h-${meal.key}` },
        h('div', { class: 'meal-head' }, h('h2', { class: 'meal-name', id: `meal-h-${meal.key}` }, meal.label), headRight));
      if (!entries.length) {
        card.append(h('p', { class: 'empty-state' }, 'Nothing logged.'));
      } else {
        const ul = h('ul', { class: 'list' });
        for (const e of entries) ul.append(isPlanned(e) ? h('li', { class: 'entry-planned' }, entryRow(e), eatenButton(e)) : h('li', {}, entryRow(e)));
        card.append(ul);
      }
      const foot = h('div', { class: 'meal-foot' });
      if (mt && eatenEntries.length) {
        foot.append(h('span', { class: 'tabular meal-sum' }, `Protein ${fmtNum(mt.protein_g, 'protein_g')} g · K ${fmtNum(mt.potassium_mg, 'potassium_mg')} · P ${fmtNum(mt.phosphorus_mg, 'phosphorus_mg')} · Na ${fmtNum(mt.sodium_mg, 'sodium_mg')} mg`));
      }
      if (pmt && plannedEntries.length) {
        foot.append(h('span', { class: 'tabular meal-sum planned' }, `Planned: +${fmtNum(pmt.protein_g, 'protein_g')} g protein · K +${fmtNum(pmt.potassium_mg, 'potassium_mg')} · P +${fmtNum(pmt.phosphorus_mg, 'phosphorus_mg')} · Na +${fmtNum(pmt.sodium_mg, 'sodium_mg')} mg`));
      }
      card.append(foot);
      const actions = h('div', { class: 'meal-actions' });
      actions.append(h('button', { class: 'link-btn meal-add', type: 'button', onclick: () => { state.addMealHint = meal.key; state.addStatusHint = null; router.show('add'); $('#food-search').focus(); } },
        plusIcon(), `Add to ${meal.label.toLowerCase()}`));
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
      totalsAllEl.append(h('div', { class: 'ng' }, h('span', {}, n.label), h('b', {}, fmtWithUnit(eatenV, n.key),
        counts.planned > 0 && projV != null && projV !== eatenV ? h('span', { class: 'ng-proj' }, ` → ${fmtNum(projV, n.key)}`) : null)));
    }
    $('#totals-details > summary').textContent = counts.planned > 0 ? 'All nutrient totals for the day (eaten → projected)' : 'All nutrient totals for the day';
  }

  function statusBar(key, st, pst) {
    const n = NUT[key] || { label: key, unit: '' };
    const level = st.level || 'ok';
    const p = pct(st.fraction);
    const hasMin = st.min != null;
    const targetText = hasMin ? `${fmtNum(st.min, key)}–${fmtNum(st.target, key)}` : fmtNum(st.target, key);
    // Same word as the server's alerts: goal (calories, carbohydrate), maximum (ranges, info), limit.
    const isGoal = n.role === 'goal' || n.role === 'track';
    const levelWord = (lv) => (lv === 'over' && hasMin ? 'Over max' : lv === 'over' && isGoal ? 'Over goal' : lv === 'caution' && isGoal ? 'Near goal' : LEVEL_TEXT[lv]);
    const levelText = levelWord(level);
    const hasProj = pst && pst.value != null && pst.value > (st.value || 0);
    const pp = hasProj ? pct(pst.fraction) : p;
    const projLevel = hasProj ? pst.level || 'ok' : level;
    const wrap = h('div', { class: `stat level-${level}${hasMin ? ' has-min' : ''}${hasProj ? ' has-proj' : ''}` },
      h('div', { class: 'stat-label' }, n.label, levelPill(level, levelText)),
      h('div', { class: 'stat-value' }, h('b', {}, fmtNum(st.value, key)), ` / ${targetText} ${n.unit}`,
        hasProj ? h('span', { class: `stat-proj-value level-${projLevel}` }, ` → ${fmtNum(pst.value, key)}`) : null));
    const ariaProj = hasProj ? `, projected ${fmtNum(pst.value, key)} ${n.unit} (${pp} percent, ${levelWord(projLevel)}) with planned foods` : '';
    const track = h('div', { class: 'stat-track', role: 'meter', 'aria-valuemin': 0, 'aria-valuemax': st.target, 'aria-valuenow': st.value,
      'aria-label': `${n.label}: ${fmtNum(st.value, key)} of ${targetText} ${n.unit}, ${p} percent, ${levelText}${ariaProj}` });
    if (hasProj) {
      const left = Math.max(0, Math.min(100, p)), right = Math.max(0, Math.min(100, pp));
      track.append(h('div', { class: `stat-fill-proj level-${projLevel}`, style: `left:${left}%;width:${Math.max(0, right - left)}%` }));
      track.append(h('div', { class: `stat-proj-marker level-${projLevel}`, style: `left:${right}%`, title: `Projected ${fmtNum(pst.value, key)} ${n.unit}` }));
    }
    track.append(h('div', { class: `stat-fill${st.value ? '' : ' empty'}`, style: `width:${Math.max(0, Math.min(100, p))}%` }));
    if (hasMin && st.target) track.append(h('div', { class: 'stat-min', style: `left:${Math.min(100, (st.min / st.target) * 100).toFixed(1)}%`, title: `Minimum ${fmtNum(st.min, key)} ${n.unit}` }));
    wrap.append(track);
    const foot = [`${p} % of ${hasMin ? 'maximum' : ROLE_WORD[n.role] || 'limit'}`];
    if (hasMin && st.value < st.min) foot.push(`below the ${fmtNum(st.min, key)} ${n.unit} minimum so far`);
    if (st.fraction > 1) foot.push(`${fmtNum(st.value - st.target, key)} ${n.unit} over`);
    else foot.push(`${fmtNum(st.target - st.value, key)} ${n.unit} left`);
    if (hasProj) foot.push(`${pp} % with planned`);
    wrap.append(h('div', { class: 'stat-foot' }, foot.join(' · ')));
    return wrap;
  }

  function entryRow(e) {
    const planned = isPlanned(e);
    const amount = e.grams != null ? `${fmtNum(e.grams, 'fluid_ml')} g (${fmtServings(e.servings)})` : fmtServings(e.servings);
    const nums = h('div', { class: 'row-nums' });
    for (const k of ROW_NUMBERS) {
      nums.append(h('span', { class: 'n' }, `${NUT[k].short} `, h('b', {}, fmtNum(e.nutrients[k], k)), ` ${NUT[k].unit}`));
    }
    const btn = h('button', { class: `row-btn${planned ? ' planned' : ''}`, type: 'button', 'aria-label': `Edit ${planned ? 'planned ' : ''}${e.food_name}, ${amount}` },
      ratingIcon(e.kidney_rating),
      h('div', { class: 'row-main' },
        h('div', { class: 'row-title' }, e.food_name, planned ? h('span', { class: 'badge planned' }, 'planned') : null),
        h('div', { class: 'row-sub' }, h('span', { class: 'entry-servings' }, amount), e.note ? h('span', { class: 'entry-note' }, ` · ${e.note}`) : null)),
      nums);
    btn.addEventListener('click', () => views().add.openEntrySheet('edit', { entry: e, trigger: btn }));
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
      toast(n ? `${n} ${n === 1 ? 'entry' : 'entries'} marked as eaten` : 'Nothing was planned', 'ok');
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
        const avgText = nt.average == null ? '—' : fmtNum(nt.average, key);
        const cell = h('div', { class: `strip-cell level-${level}`, role: 'group', 'aria-label': `${n.label}: average ${avgText} of ${fmtNum(nt.target, key)} ${n.unit} per day${nt.level ? `, ${LEVEL_TEXT[nt.level]}` : ''}${nt.days_over ? `, ${nt.days_over} days over` : ''}` },
          h('div', { class: 'strip-label' }, n.label, nt.assessment === 'weekly_average' ? h('span', { class: 'strip-tag', title: 'Judged on the weekly average' }, 'avg') : null),
          h('div', { class: 'strip-value' }, h('b', {}, avgText), h('span', { class: 'muted' }, ` / ${fmtNum(nt.target, key)} ${n.unit}`)),
          h('div', { class: 'strip-track' }, h('div', { class: 'strip-fill', style: `width:${Math.round(frac * 100)}%` })),
          h('div', { class: 'strip-foot' }, nt.average == null ? 'no data' : `${pct(nt.fraction)} %${nt.days_over ? ` · ${nt.days_over} ${nt.days_over === 1 ? 'day' : 'days'} over` : ''}`));
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
      list.append(h('div', { class: `inter-row level-${level}` },
        h('span', { class: 'inter-label' }, n.label),
        h('div', { class: 'strip-track' }, h('div', { class: 'strip-fill', style: `width:${Math.round(Math.max(0, Math.min(1, it.fraction || 0)) * 100)}%` })),
        h('span', { class: 'inter-nums tabular' }, h('b', {}, fmtNum(it.total, key)), ` / ${fmtNum(it.limit, key)} ${n.unit}`),
        levelPill(level, `${pct(it.fraction)} %`)));
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
