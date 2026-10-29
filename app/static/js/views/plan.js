/* Kidney Diet Log — Plan view: the 7-day grid of projected totals, saved meals (list, editor,
   "Add to a day"), the week's shopping list (ticks kept only on this device), and the sheets
   that copy a day, apply a saved meal and save a logged meal as a saved meal. */
(() => {
  'use strict';
  const KH = window.KH;
  const { h, $, $$, clear, api, state, toast, toastError, router, sheets, confirm } = KH;
  const { NUT, NUTRIENTS, MEALS, MEAL_LABEL, fmtNum, fmtServings, pct } = KH.rules;
  const { KEY_NUMBERS, ROW_NUMBERS, PLAN_CHIPS, WEEKDAYS, LEVEL_TEXT, ratingIcon, plusIcon, dashedIcon, checkIcon, closeIcon,
    selectedMeal, setMeal, selectedStatus, setStatus, isPlanned, scaledNutrients, impactOn, unknownOf, notListed, foodsNotListing, atLeast, atLeastWords } = KH.ui;
  const { todayStr, parseDate, addDays, fmtDateLong, fmtMonthDay, fmtRange, weekdayMon, weekStartOf, defaultStatusFor, defaultMealForNow, debounce } = KH.util;
  const { SHOP_KEY } = KH.keys;

  // A recipe saved by Ask or MCP before schema step 21 kept this sentence as its note; the columns hold it now (note 16 §5.1).
  const OLD_RECIPE_NOTE = /^Makes \d+(?:\.\d+)? servings?\.(?: Source: https?:\/\/\S+)?$/;
  const shownNote = (t) => (t.note && !(t.servings_made != null && OLD_RECIPE_NOTE.test(t.note)) ? t.note : null);
  const isRecipe = (t) => t.servings_made != null && t.servings_made !== 1;

  const planGridEl = $('#plan-grid');
  const savedMealsEl = $('#saved-meals');
  const shoppingEl = $('#shopping-list');
  let planRequest = 0;

  function fmtTimes(n) { return `${(Math.round(n * 100) / 100).toLocaleString('en-US', { maximumFractionDigits: 2 })}×`; }
  function weekStartPref() { return state.profile && state.profile.week_start === 'sunday' ? 'sunday' : 'monday'; }
  function currentWeekStart() { return weekStartOf(todayStr(), weekStartPref()); }
  function ensurePlanStart() {
    if (!state.planStart) state.planStart = currentWeekStart();
    return state.planStart;
  }
  // After the log changed on `date`, refresh whatever view is showing and drop caches.
  function afterLogChange(date, { goToDay = false } = {}) {
    state.dayLoadedFor = null; state.trends = null; state.summary = null;
    if (goToDay) { state.date = date; router.show('today'); return; }
    if (state.view === 'plan') loadPlan();
    else if (state.view === 'today') { if (date && date !== state.date) KH.views.today.setDate(date); else KH.views.today.loadDay(); }
    else if (state.view === 'trends') KH.views.trends.loadTrends();
  }

  $('#week-prev').addEventListener('click', () => { state.planStart = addDays(ensurePlanStart(), -7); loadPlan(); });
  $('#week-next').addEventListener('click', () => { state.planStart = addDays(ensurePlanStart(), 7); loadPlan(); });
  $('#week-this').addEventListener('click', () => { state.planStart = currentWeekStart(); loadPlan(); });
  $('#btn-copy-day').addEventListener('click', (e) => openCopySheet({ from: state.date || todayStr(), trigger: e.currentTarget }));
  $('#btn-new-meal').addEventListener('click', (e) => openMealEditor(null, e.currentTarget));
  // AI recipes (note 16 §10): offered only when the server offers them to this person; the demo never does.
  async function aiRecipesOn() {
    if (!KH.ai || typeof KH.ai.status !== 'function') return false;
    try { const st = await KH.ai.status(); return !!(st && st.features && st.features.recipes); } catch (e) { return false; }
  }
  async function afterAiSave() { await KH.loadMeals(true); renderSavedMeals(); }
  $('#btn-ai-recipes').addEventListener('click', (e) => KH.ai.openRecipes({ trigger: e.currentTarget, onSaved: afterAiSave }));

  async function loadPlan() {
    const reqId = ++planRequest;
    try { await KH.loadProfile(); } catch (e) { toastError(e); }
    const start = ensurePlanStart();
    const end = addDays(start, 6);
    const thisWeek = currentWeekStart();
    $('#week-label').textContent = start === thisWeek ? 'This week' : start === addDays(thisWeek, 7) ? 'Next week' : start === addDays(thisWeek, -7) ? 'Last week' : `Week of ${fmtMonthDay(start)}`;
    $('#week-range').textContent = fmtRange(start, end);
    $('#week-this').hidden = start === thisWeek;
    planGridEl.style.opacity = state.plan ? '0.6' : '';
    const [rangeRes, mealsRes, shopRes] = await Promise.allSettled([api.range(start, end), KH.loadMeals(true), api.shopping(start, end)]);
    if (reqId !== planRequest) return;
    planGridEl.style.opacity = '';
    if (rangeRes.status === 'fulfilled') { state.plan = { start, end, days: rangeRes.value.days || [] }; renderPlanGrid(); }
    else { toastError(rangeRes.reason); clear(planGridEl); planGridEl.append(h('p', { class: 'card empty-state' }, 'Could not load this week.')); }
    if (mealsRes.status === 'fulfilled') renderSavedMeals(); else toastError(mealsRes.reason);
    aiRecipesOn().then((on) => { $('#ai-recipes-row').hidden = !on; });
    if (shopRes.status === 'fulfilled') { state.shopping = { start, end, items: shopRes.value.items || [] }; renderShopping(); }
    else toastError(shopRes.reason);
  }

  function renderPlanGrid() {
    const plan = state.plan;
    if (!plan) return;
    clear(planGridEl);
    const today = todayStr();
    const prof = state.profile || {};
    const dd = prof.dialysis === 'hemodialysis' ? (prof.dialysis_days || []).map(Number) : [];
    const byDate = Object.fromEntries(plan.days.map((d) => [d.date, d]));
    for (let i = 0; i < 7; i++) {
      const date = addDays(plan.start, i);
      const d = byDate[date] || { date, totals: {}, planned_totals: {}, projected_totals: {}, status: {}, projected_status: {}, counts: { eaten: 0, planned: 0 } };
      const counts = d.counts || { eaten: 0, planned: 0 };
      const isToday = date === today, isPast = date < today;
      const dial = dd.includes(weekdayMon(date));
      // v0.3.1: "running high" (periods.pattern_alerts); Today shows the whole message.
      const pattern = d.pattern_alerts || [];
      const patternNames = [...new Set(pattern.map((a) => (NUT[a.nutrient] ? NUT[a.nutrient].label.toLowerCase() : a.nutrient)))];
      const card = h('article', { class: `plan-day${isToday ? ' today' : ''}${isPast ? ' past' : ''}${dial ? ' dialysis' : ''}`, role: 'listitem' });
      const open = h('button', { class: 'plan-day-open', type: 'button',
        'aria-label': `${fmtDateLong(date)}${dial ? ', dialysis day' : ''}: ${counts.eaten} eaten, ${counts.planned} planned`
          + `${patternNames.length ? `, running high: ${patternNames.join(', ')}` : ''}. Open in Today` });
      open.append(h('div', { class: 'plan-day-head' },
        h('div', { class: 'plan-day-date' }, h('span', { class: 'plan-wd' }, WEEKDAYS[weekdayMon(date)]), h('span', { class: 'plan-dnum' }, String(parseDate(date).getDate()))),
        h('div', { class: 'plan-day-badges' },
          isToday ? h('span', { class: 'badge today' }, 'Today') : null,
          dial ? h('span', { class: 'badge dialysis', title: 'Dialysis day' }, 'Dialysis') : null)));
      const chips = h('div', { class: 'plan-chips' });
      const pst = d.projected_status || d.status || {};
      const totals = d.projected_totals || d.totals || {};
      const hasEntries = counts.eaten + counts.planned > 0;
      let any = false;
      for (const key of PLAN_CHIPS) {
        const st = pst[key];
        if (!st || !hasEntries) continue;
        any = true;
        const n = NUT[key];
        const val = st.value != null ? st.value : totals[key] || 0;
        // Foods that do not list the value: the total may be higher ("≥", never shown as OK).
        const unk = st.unknown != null ? Number(st.unknown) : unknownOf(d.projected_unknown, key);
        const level = unk && (st.level || 'ok') === 'ok' ? 'unknown' : st.level || 'ok';
        const extra = unk ? `; ${foodsNotListing(unk, key)}` : '';
        chips.append(h('span', { class: `plan-chip level-${level}`, role: 'img',
          title: `${n.label}: projected ${atLeastWords(fmtNum(val, key), unk)} of ${fmtNum(st.target, key)} ${n.unit} (${pct(st.fraction)} %)${extra}`,
          'aria-label': `${n.label} ${atLeastWords(fmtNum(val, key), unk)} of ${KH.ui.isAboutTarget(st, key) ? 'about ' : ''}${fmtNum(st.target, key)} ${n.unit}, ${KH.ui.levelTextFor(st, level, key)}${extra}` },
          h('i', { class: 'swatch', 'aria-hidden': 'true' }), h('span', { class: 'plan-chip-k' }, n.short), h('b', {}, atLeast(fmtNum(val, key), unk))));
      }
      if (!any) chips.append(h('span', { class: 'muted small plan-empty' }, hasEntries ? 'No targets set' : isPast ? 'Nothing logged' : 'Nothing planned yet'));
      open.append(chips);
      if (pattern.length) {
        const lvl = pattern.some((a) => a.level === 'over') ? 'over' : 'caution';
        open.append(h('p', { class: `plan-pattern level-${lvl}`, title: pattern.map((a) => a.message).join(' ') },
          `Running high: ${patternNames.join(', ')}`));
      }
      const cnt = h('div', { class: 'plan-counts' });
      if (counts.eaten) cnt.append(h('span', { class: 'count eaten' }, checkIcon(), `${counts.eaten} eaten`));
      if (counts.planned) cnt.append(h('span', { class: 'count planned' }, dashedIcon(), `${counts.planned} planned`));
      if (hasEntries) open.append(cnt);
      open.addEventListener('click', () => router.openDay(date));
      card.append(open);
      card.append(h('div', { class: 'plan-day-foot' },
        h('button', { class: 'link-btn', type: 'button', onclick: (ev) => openApplySheet({ date, meal: isToday ? defaultMealForNow() : 'breakfast', status: defaultStatusFor(date), trigger: ev.currentTarget }) }, plusIcon(), 'Saved meal'),
        h('button', { class: 'link-btn', type: 'button', onclick: (ev) => openCopySheet({ from: date, trigger: ev.currentTarget }) }, 'Copy…')));
      planGridEl.append(card);
    }
  }

  // ---- Saved meals list ----------------------------------------------------
  function renderSavedMeals() {
    clear(savedMealsEl);
    const meals = state.meals || [];
    if (!meals.length) {
      savedMealsEl.append(h('li', { class: 'empty-state' }, 'No saved meals yet. Create one here, or use "Save as meal" under a meal in Today.'));
      return;
    }
    for (const t of meals) {
      const li = h('li', { class: 'saved-meal' });
      const nums = h('div', { class: 'row-nums' });
      const shown = isRecipe(t) ? t.per_serving : t.totals;
      for (const k of ROW_NUMBERS) {
        // A total skips foods that do not list the value: "≥ 120" when some do not, "not listed" when none does, never a plain 0.
        const unk = unknownOf(t.unknown, k);
        const none = !!t.per_serving && t.per_serving[k] == null; // the server sends null when no food in it lists the value
        nums.append(none
          ? h('span', { class: 'n', title: foodsNotListing(unk, k) }, `${NUT[k].short} `, h('b', {}, 'not listed'))
          : h('span', { class: 'n', title: unk ? foodsNotListing(unk, k) : null,
            'aria-label': `${NUT[k].label} ${atLeastWords(fmtNum(shown[k], k), unk)} ${NUT[k].unit}${unk ? `; ${foodsNotListing(unk, k)}` : ''}` },
            `${NUT[k].short} `, h('b', {}, atLeast(fmtNum(shown[k], k), unk)), ` ${NUT[k].unit}`,
            unk ? h('span', { class: 'not-listed' }, ` (${notListed(unk)})`) : null)); // as on Today's meal lines: "K ≥ 55 (+ 1 not listed)"
      }
      li.append(h('div', { class: 'saved-meal-main' },
        ratingIcon(t.kidney_rating),
        h('div', { class: 'row-main' },
          h('div', { class: 'row-title' }, t.name),
          h('div', { class: 'row-sub' }, t.items.map((it) => `${fmtTimes(it.servings)} ${it.food_name}${it.hidden ? ' (hidden food)' : ''}`).join(', ')),
          isRecipe(t) ? h('div', { class: 'muted small' }, `Makes ${fmtServings(t.servings_made)}. Numbers are for one serving.`) : null,
          shownNote(t) ? h('div', { class: 'entry-note' }, shownNote(t)) : null,
          nums)));
      li.append(h('div', { class: 'saved-meal-actions' },
        h('button', { class: 'btn secondary', type: 'button', onclick: (ev) => openApplySheet({ mealId: t.id, trigger: ev.currentTarget }) }, plusIcon(), 'Add to a day'),
        h('button', { class: 'link-btn', type: 'button', onclick: (ev) => openFitSheet(t, ev.currentTarget) }, 'Fit to my targets'),
        h('button', { class: 'link-btn', type: 'button', onclick: (ev) => openMealEditor(t, ev.currentTarget) }, 'Edit'),
        h('button', { class: 'link-btn danger-link', type: 'button', 'aria-label': `Delete saved meal ${t.name}`,
          onclick: (ev) => confirmDeleteSavedMeal(t, ev.currentTarget.parentElement, ev.currentTarget) }, 'Delete')));
      savedMealsEl.append(li);
    }
  }
  async function deleteSavedMeal(t) {
    try {
      await api.deleteMeal(t.id);
      toast(`Saved meal "${t.name}" deleted`, 'ok');
      await KH.loadMeals(true);
      renderSavedMeals();
      return true;
    } catch (err) { toastError(err); return false; }
  }
  function confirmDeleteSavedMeal(t, host, trigger, after) {
    confirm.inline(host, trigger, {
      message: `Delete the saved meal "${t.name}"? Logged entries are not affected.`,
      confirmText: 'Delete meal',
      onConfirm: async () => {
        const ok = await deleteSavedMeal(t);
        if (ok) { if (after) after(); else $('#btn-new-meal').focus(); }
        return ok;
      },
    });
  }

  // ---- Shopping list (checks live only in localStorage) --------------------
  function shopKey(start) { return `${SHOP_KEY}:${start}`; }
  // Ticks live in memory for the session (keyed by week start) and are mirrored to localStorage
  // when it works, so they survive view reloads even where storage is blocked (sandboxed frame).
  const memChecks = new Map();
  function loadChecks(start) {
    if (!memChecks.has(start)) {
      let stored = [];
      try { const v = JSON.parse(localStorage.getItem(shopKey(start)) || '[]'); if (Array.isArray(v)) stored = v; } catch (e) { /* storage unavailable */ }
      memChecks.set(start, stored);
    }
    return new Set(memChecks.get(start));
  }
  function saveChecks(start, set) {
    memChecks.set(start, [...set]);
    try { if (set.size) localStorage.setItem(shopKey(start), JSON.stringify([...set])); else localStorage.removeItem(shopKey(start)); } catch (e) { /* storage unavailable */ }
  }
  $('#shopping-clear').addEventListener('click', () => { if (state.shopping) { saveChecks(state.shopping.start, new Set()); renderShopping(); } });
  // The list as plain text for any list app (design note 22, part A): what is not ticked yet, one food a line. Nothing leaves
  // this device unless the person shares or pastes it.
  function shoppingText(sh, checks) {
    const items = sh.items || [];
    const left = items.filter((it) => !checks.has(it.food_id));
    const lines = (left.length ? left : items).map((it) => `- ${it.food_name}: ${fmtServings(it.servings)}${it.serving_desc ? ` of ${it.serving_desc}` : ''}`);
    return [`Shopping list, ${fmtRange(sh.start, sh.end)}`, '', ...lines].join('\n');
  }
  function showShoppingText(text) { // where the clipboard is blocked: the text, selected, to copy by hand
    const box = $('#shopping-text');
    box.value = text;
    box.hidden = false;
    box.focus();
    box.select();
  }
  async function copyShopping(text) {
    const policy = document.permissionsPolicy || document.featurePolicy;
    let allowed = true;
    try { allowed = !policy || typeof policy.allowsFeature !== 'function' || policy.allowsFeature('clipboard-write'); } catch (e) { allowed = true; }
    try {
      if (allowed && navigator.clipboard && window.isSecureContext) { await navigator.clipboard.writeText(text); toast('Shopping list copied', 'ok'); return; }
    } catch (e) { /* fall back */ }
    showShoppingText(text);
    toast('Select the list and copy it (Ctrl+C, or touch and hold on a phone).');
  }
  $('#shopping-copy').addEventListener('click', () => { if (state.shopping) copyShopping(shoppingText(state.shopping, loadChecks(state.shopping.start))); });
  $('#shopping-share').addEventListener('click', async () => {
    if (!state.shopping) return;
    const text = shoppingText(state.shopping, loadChecks(state.shopping.start));
    try { await navigator.share({ title: 'Shopping list', text }); } catch (e) {
      if (!(e && e.name === 'AbortError')) copyShopping(text); // closed by the person: nothing to do
    }
  });
  function renderShopping() {
    const sh = state.shopping;
    if (!sh) return;
    clear(shoppingEl);
    const checks = loadChecks(sh.start);
    const items = sh.items || [];
    $('#shopping-sub').textContent = items.length ? `${items.length} ${items.length === 1 ? 'food' : 'foods'} · ${fmtRange(sh.start, sh.end)}` : fmtRange(sh.start, sh.end);
    $('#shopping-clear').hidden = !items.length || !checks.size;
    $('#shopping-copy').hidden = !items.length;
    $('#shopping-share').hidden = !items.length || typeof navigator.share !== 'function';
    $('#shopping-text').hidden = true;
    if (!items.length) {
      shoppingEl.append(h('li', { class: 'empty-state' }, 'Nothing planned this week yet. Plan foods on a day, or add a saved meal, to build the list.'));
      return;
    }
    for (const it of items) {
      const id = `shop-${sh.start}-${it.food_id}`;
      const checked = checks.has(it.food_id);
      const cb = h('input', { type: 'checkbox', id, checked: checked || null });
      const li = h('li', { class: `shop-item${checked ? ' done' : ''}` },
        h('label', { class: 'check shop-check', for: id }, cb,
          h('span', { class: 'check-text' },
            h('span', { class: 'shop-name' }, it.food_name),
            h('span', { class: 'hint' }, `${fmtServings(it.servings)}${it.serving_desc ? ` of ${it.serving_desc}` : ''}${it.grams ? ` · ${fmtNum(it.grams, 'fluid_ml')} g` : ''} · ${it.days} ${it.days === 1 ? 'day' : 'days'}`))));
      cb.addEventListener('change', () => {
        if (cb.checked) checks.add(it.food_id); else checks.delete(it.food_id);
        saveChecks(sh.start, checks);
        li.classList.toggle('done', cb.checked);
        $('#shopping-clear').hidden = !checks.size;
      });
      shoppingEl.append(li);
    }
  }

  // ---- Copy day sheet -------------------------------------------------------
  const copyDlg = $('#sheet-copy');
  sheets.setup(copyDlg);
  let copyBusy = false;
  function openCopySheet({ from, to, trigger } = {}) {
    const f = from || state.date || todayStr();
    $('#copy-from').value = f;
    $('#copy-to').value = to || addDays(f, 1);
    $$('#copy-meals input').forEach((c) => { c.checked = true; });
    $('#copy-include').value = 'all';
    setStatus($('#copy-status'), 'planned');
    updateCopySummary();
    sheets.open(copyDlg, trigger, $('#copy-to'));
  }
  function updateCopySummary() {
    const f = $('#copy-from').value, t = $('#copy-to').value;
    const el = $('#copy-summary');
    if (!f || !t) { el.textContent = ''; return; }
    el.textContent = f === t ? 'Choose two different days.' : `${fmtDateLong(f)} → ${fmtDateLong(t)}`;
  }
  $('#copy-from').addEventListener('change', updateCopySummary);
  $('#copy-to').addEventListener('change', updateCopySummary);
  sheets.onSubmit($('#copy-form'), async (e) => {
    e.preventDefault();
    if (copyBusy) return;
    const from_date = $('#copy-from').value, to_date = $('#copy-to').value;
    if (!/^\d{4}-\d{2}-\d{2}$/.test(from_date) || !/^\d{4}-\d{2}-\d{2}$/.test(to_date)) { toast('Pick both dates', 'error'); return; }
    if (from_date === to_date) { toast('Choose two different days', 'error'); $('#copy-to').focus(); return; }
    const meals = $$('#copy-meals input:checked').map((c) => c.value);
    if (!meals.length) { toast('Pick at least one meal', 'error'); return; }
    const body = { from_date, to_date, include: $('#copy-include').value, status: selectedStatus($('#copy-status')) };
    if (meals.length < MEALS.length) body.meals = meals;
    copyBusy = true; $('#copy-save').disabled = true;
    try {
      const res = await api.copyDay(body);
      copyDlg.close();
      const n = res && typeof res.created === 'number' ? res.created : (res && res.entries ? res.entries.length : 0);
      toast(n ? `Copied ${n} ${n === 1 ? 'entry' : 'entries'} to ${fmtDateLong(to_date)} as ${body.status}` : 'Nothing to copy from that day', n ? 'ok' : '');
      if (n) afterLogChange(to_date);
    } catch (err) { toastError(err); }
    finally { copyBusy = false; $('#copy-save').disabled = false; }
  });

  // ---- Apply saved meal sheet ----------------------------------------------
  const applyDlg = $('#sheet-apply');
  sheets.setup(applyDlg);
  let applyBusy = false;
  let applyStatusTouched = false; // until the person picks a status, it follows the chosen date (past/today → eaten, future → planned)
  $('#apply-status').addEventListener('change', () => { applyStatusTouched = true; });
  $('#apply-date').addEventListener('input', () => {
    const d = $('#apply-date').value;
    if (!applyStatusTouched && /^\d{4}-\d{2}-\d{2}$/.test(d)) setStatus($('#apply-status'), defaultStatusFor(d));
  });
  async function openApplySheet({ mealId, date, meal, status, trigger } = {}) {
    try { await KH.loadMeals(); } catch (e) { toastError(e); return; }
    const meals = state.meals || [];
    if (!meals.length) {
      toast('No saved meals yet. Create one in Plan, or use "Save as meal" under a meal in Today.');
      return;
    }
    const sel = $('#apply-meal-id');
    clear(sel);
    for (const t of meals) sel.append(h('option', { value: t.id }, `${t.name} (${t.items.length} ${t.items.length === 1 ? 'food' : 'foods'})`));
    const chosen = meals.find((t) => t.id === Number(mealId)) || meals[0];
    sel.value = String(chosen.id);
    const d = date || state.date || todayStr();
    $('#apply-date').value = d;
    $('#apply-scale').value = '1';
    setMeal($('#apply-meal'), meal || defaultMealForNow());
    setStatus($('#apply-status'), status || defaultStatusFor(d));
    applyStatusTouched = !!status;
    updateApplyPreview();
    sheets.open(applyDlg, trigger, mealId ? $('#apply-date') : sel);
  }
  function applyTemplate() { return (state.meals || []).find((t) => t.id === Number($('#apply-meal-id').value)) || null; }
  function updateApplyPreview() {
    const t = applyTemplate();
    const items = clear($('#apply-items'));
    const key = clear($('#apply-preview-key'));
    const box = clear($('#apply-warnings'));
    if (!t) return;
    const scale = Number($('#apply-scale').value) > 0 ? Number($('#apply-scale').value) : 1;
    $('#sheet-apply-title').textContent = `Add “${t.name}”`;
    $('#sheet-apply-sub').textContent = t.note ? t.note : 'Logs every food in the saved meal onto one day.';
    $('#apply-preview-amount').textContent = scale === 1 ? `${t.items.length} ${t.items.length === 1 ? 'food' : 'foods'}` : `${t.items.length} foods × ${scale}`;
    for (const it of t.items) {
      items.append(h('li', {}, ratingIcon(it.kidney_rating, { decorative: true }),
        h('span', { class: 'ci-name' }, it.food_name, it.hidden ? h('span', { class: 'food-source' }, 'hidden') : null),
        h('span', { class: 'ci-amt muted' }, fmtServings(it.servings * scale))));
    }
    const scaled = scaledNutrients(t.totals, scale);
    for (const k of KEY_NUMBERS) {
      // Unknown is never 0: "not listed" when no food lists it, "≥" when only some do (the saved-meal card's rule).
      const none = !!t.per_serving && t.per_serving[k] == null;
      const unk = unknownOf(t.unknown, k);
      key.append(h('div', { class: `kn${none ? ' kn-unknown' : ''}`, title: unk ? foodsNotListing(unk, k) : null },
        h('span', { class: 'kn-v' }, none ? 'not listed' : atLeast(fmtNum(scaled[k], k), unk)),
        none ? null : h('span', { class: 'kn-u' }, NUT[k].unit), h('span', { class: 'kn-l' }, NUT[k].short)));
    }
    const date = $('#apply-date').value;
    if (state.day && state.dayLoadedFor === date) {
      const impact = impactOn(state.day, scaled, selectedMeal($('#apply-meal')), { status: selectedStatus($('#apply-status')) });
      for (const it of impact) {
        box.append(h('div', { class: `warning level-${it.level}` }, ratingIcon(it.level, { label: LEVEL_TEXT[it.level] }),
          h('div', {}, h('span', { class: 'w-level' }, it.level === 'over' ? 'Day total over. ' : 'Day total near limit. '), it.message)));
      }
    }
  }
  $('#apply-form').addEventListener('input', updateApplyPreview);
  $('#apply-form').addEventListener('change', updateApplyPreview);
  sheets.onSubmit($('#apply-form'), async (e) => {
    e.preventDefault();
    if (applyBusy) return;
    const t = applyTemplate();
    if (!t) return;
    const date = $('#apply-date').value;
    if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) { toast('Pick a date', 'error'); $('#apply-date').focus(); return; }
    const scale = Number($('#apply-scale').value);
    if (!(scale > 0)) { toast('Scale must be more than 0', 'error'); $('#apply-scale').focus(); return; }
    const body = { date, meal: selectedMeal($('#apply-meal')), status: selectedStatus($('#apply-status')) };
    if (scale !== 1) body.scale = scale;
    applyBusy = true; $('#apply-save').disabled = true;
    try {
      const res = await api.applyMeal(t.id, body);
      applyDlg.close();
      const n = res && res.entries ? res.entries.length : t.items.length;
      toast(`${body.status === 'planned' ? 'Planned' : 'Added'} ${t.name} (${n} ${n === 1 ? 'food' : 'foods'}) for ${MEAL_LABEL[body.meal].toLowerCase()}, ${fmtDateLong(date)}`, 'ok');
      afterLogChange(date, { goToDay: state.view === 'add' });
    } catch (err) { toastError(err); }
    finally { applyBusy = false; $('#apply-save').disabled = false; }
  });

  // ---- Save a logged meal as a template ------------------------------------
  const saveMealDlg = $('#sheet-savemeal');
  sheets.setup(saveMealDlg);
  const saveMealState = { date: null, meal: null, busy: false };
  function openSaveMealSheet(date, meal, entries, trigger) {
    saveMealState.date = date; saveMealState.meal = meal;
    $('#savemeal-name').value = '';
    $('#savemeal-note').value = '';
    // The server leaves low treatments (purpose "hypo") out of a saved meal: say so instead of listing them.
    const kept = entries.filter((e) => e.purpose !== 'hypo');
    const lows = entries.length - kept.length;
    $('#sheet-savemeal-sub').textContent = `${MEAL_LABEL[meal]} on ${fmtDateLong(date)} · ${kept.length} ${kept.length === 1 ? 'food' : 'foods'}`
      + (lows ? ` (${lows} low ${lows === 1 ? 'treatment' : 'treatments'} left out)` : '');
    const ul = clear($('#savemeal-items'));
    for (const e of kept) {
      ul.append(h('li', {}, ratingIcon(e.kidney_rating, { decorative: true }),
        h('span', { class: 'ci-name' }, e.food_name, isPlanned(e) ? h('span', { class: 'badge planned' }, 'planned') : null),
        h('span', { class: 'ci-amt muted' }, fmtServings(e.servings))));
    }
    sheets.open(saveMealDlg, trigger, $('#savemeal-name'));
  }
  sheets.onSubmit($('#savemeal-form'), async (e) => {
    e.preventDefault();
    if (saveMealState.busy) return;
    const name = $('#savemeal-name').value.trim();
    if (!name) { toast('Give the meal a name', 'error'); $('#savemeal-name').focus(); return; }
    saveMealState.busy = true; $('#savemeal-save').disabled = true;
    try {
      const t = await api.mealFromLog({ date: saveMealState.date, meal: saveMealState.meal, name, note: $('#savemeal-note').value.trim() || null });
      saveMealDlg.close();
      KH.invalidateMeals();
      toast(`Saved “${t.name}” (${t.items.length} ${t.items.length === 1 ? 'food' : 'foods'}). Find it under Plan.`, 'ok');
    } catch (err) { toastError(err); }
    finally { saveMealState.busy = false; $('#savemeal-save').disabled = false; }
  });

  // ---- Saved meal editor (create / edit) -----------------------------------
  const mealDlg = $('#sheet-meal');
  sheets.setup(mealDlg);
  const mealEd = { id: null, items: [], busy: false, search: 0 };
  function perServingOfItem(it) {
    const out = {};
    for (const n of NUTRIENTS) { const v = it.nutrients ? it.nutrients[n.key] : null; out[n.key] = v == null || !it.servings ? v : v / it.servings; }
    return out;
  }
  // `t` is the saved meal to edit, or null for a new one. `draft` ({ name, meal_hint, foods: [{ food, servings }] }, with `food`
  // as GET /api/foods/{id} answers) starts a new meal with those foods: Settings → Meal guidance → "Save as a meal" on a usual meal.
  function openMealEditor(t, trigger, draft = null) {
    mealEd.id = t ? t.id : null;
    mealEd.items = t ? t.items.map((it) => ({ food_id: it.food_id, food_name: it.food_name, serving_desc: it.serving_desc, servings: it.servings,
      per: perServingOfItem(it), kidney_rating: it.kidney_rating, hidden: !!it.hidden }))
      : draft ? draft.foods.map(({ food, servings }) => ({ food_id: food.id, food_name: food.name, serving_desc: food.serving_desc, servings,
        per: food.nutrients, kidney_rating: food.kidney_rating, hidden: !!food.hidden })) : [];
    $('#sheet-meal-title').textContent = t ? 'Edit saved meal' : 'New saved meal';
    $('#meal-name').value = t ? t.name : draft ? draft.name : '';
    $('#meal-note').value = t ? shownNote(t) || '' : '';
    $('#meal-makes').value = t && t.servings_made != null ? String(t.servings_made) : '';
    $('#meal-source').value = t && t.source_url ? t.source_url : '';
    $('#meal-steps').value = t && t.steps ? t.steps.join('\n') : '';
    $('#meal-hint').value = t && t.meal_hint ? t.meal_hint : draft && draft.meal_hint ? draft.meal_hint : ''; // v0.3: the meal it is meant for (meal guidance)
    $('#meal-delete').hidden = !t;
    $('#meal-search').value = '';
    clear($('#meal-search-results'));
    renderMealItems();
    sheets.open(mealDlg, trigger, $('#meal-name'));
  }
  function renderMealItems() {
    const ul = clear($('#meal-items'));
    if (!mealEd.items.length) ul.append(h('li', { class: 'empty-state' }, 'No foods yet. Search below to add some.'));
    mealEd.items.forEach((it, idx) => {
      const inp = h('input', { type: 'number', inputmode: 'decimal', min: 0.25, step: 0.25, value: String(it.servings), 'aria-label': `Servings of ${it.food_name}` });
      inp.addEventListener('input', () => { const v = Number(inp.value); if (v > 0) { it.servings = v; renderMealTotals(); } });
      inp.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); inp.blur(); } });
      const rm = h('button', { class: 'icon-btn', type: 'button', 'aria-label': `Remove ${it.food_name}` }, closeIcon());
      rm.addEventListener('click', () => { mealEd.items.splice(idx, 1); renderMealItems(); });
      ul.append(h('li', { class: 'meal-item' }, ratingIcon(it.kidney_rating, { decorative: true }),
        h('div', { class: 'row-main' }, h('div', { class: 'row-title' }, it.food_name, it.hidden ? h('span', { class: 'food-source' }, 'hidden') : null), h('div', { class: 'row-sub' }, it.serving_desc || '')),
        h('div', { class: 'meal-item-sv' }, inp, h('span', { class: 'muted small' }, 'srv')),
        rm));
    });
    renderMealTotals();
  }
  function renderMealTotals() {
    const totals = Object.fromEntries(NUTRIENTS.map((n) => [n.key, 0]));
    const makes = Number($('#meal-makes').value) > 0 ? Number($('#meal-makes').value) : 1;
    for (const it of mealEd.items) for (const n of NUTRIENTS) totals[n.key] += (it.per[n.key] || 0) * it.servings / makes;
    const key = clear($('#meal-preview-key'));
    for (const k of KEY_NUMBERS) key.append(h('div', { class: 'kn' }, h('span', { class: 'kn-v' }, fmtNum(totals[k], k)), h('span', { class: 'kn-u' }, NUT[k].unit), h('span', { class: 'kn-l' }, NUT[k].short)));
    $('#meal-preview-count').textContent = `${mealEd.items.length} ${mealEd.items.length === 1 ? 'food' : 'foods'}${makes !== 1 ? ', one serving' : ''}`;
  }
  async function runMealSearch() {
    const q = $('#meal-search').value.trim();
    const reqId = ++mealEd.search;
    const ul = $('#meal-search-results');
    if (!q) { clear(ul); return; }
    try {
      const res = await api.foods({ q, limit: 8 });
      if (reqId !== mealEd.search) return;
      clear(ul);
      const foods = res.foods || [];
      if (!foods.length) ul.append(h('li', { class: 'empty-state' }, 'No foods match.'));
      for (const f of foods) {
        const b = h('button', { class: 'row-btn compact', type: 'button' }, ratingIcon(f.kidney_rating, { decorative: true }),
          h('div', { class: 'row-main' }, h('div', { class: 'row-title' }, f.name), h('div', { class: 'row-sub' }, f.serving_desc)),
          h('span', { class: 'add-word' }, plusIcon(), 'Add'));
        b.addEventListener('click', () => {
          const existing = mealEd.items.find((it) => it.food_id === f.id);
          if (existing) existing.servings = Math.round((existing.servings + 1) * 100) / 100;
          else mealEd.items.push({ food_id: f.id, food_name: f.name, serving_desc: f.serving_desc, servings: 1, per: f.nutrients, kidney_rating: f.kidney_rating, hidden: false });
          renderMealItems();
          $('#meal-search').value = '';
          clear(ul);
          $('#meal-search').focus();
        });
        ul.append(h('li', {}, b));
      }
    } catch (err) { if (reqId === mealEd.search) toastError(err); }
  }
  $('#meal-makes').addEventListener('input', renderMealTotals);
  $('#meal-search').addEventListener('input', debounce(runMealSearch, 200));
  $('#meal-search').addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); runMealSearch(); } });
  sheets.onSubmit($('#meal-form'), async (e) => {
    e.preventDefault();
    if (mealEd.busy) return;
    const name = $('#meal-name').value.trim();
    if (!name) { toast('Give the meal a name', 'error'); $('#meal-name').focus(); return; }
    if (!mealEd.items.length) { toast('Add at least one food', 'error'); $('#meal-search').focus(); return; }
    const makes = $('#meal-makes').value.trim();
    if (makes && !(Number(makes) > 0 && Number(makes) <= 100)) { toast('Makes is a number of servings from 0.25 to 100', 'error'); $('#meal-makes').focus(); return; }
    const steps = $('#meal-steps').value.split('\n').map((x) => x.trim()).filter(Boolean);
    const body = { name, note: $('#meal-note').value.trim() || null, meal_hint: $('#meal-hint').value || null,
      items: mealEd.items.map((it) => ({ food_id: it.food_id, servings: it.servings })),
      servings_made: makes ? Number(makes) : null, steps: steps.length ? steps : null, source_url: $('#meal-source').value.trim() || null };
    mealEd.busy = true; $('#meal-save').disabled = true;
    try {
      const t = mealEd.id != null ? await api.updateMeal(mealEd.id, body) : await api.createMeal(body);
      mealDlg.close();
      toast(`Saved “${t.name}”`, 'ok');
      await KH.loadMeals(true);
      renderSavedMeals();
      if (state.view === 'add') KH.views.add.renderSavedShortcuts();
    } catch (err) { toastError(err); }
    finally { mealEd.busy = false; $('#meal-save').disabled = false; }
  });
  $('#meal-delete').addEventListener('click', (ev) => {
    if (mealEd.id == null) return;
    const t = (state.meals || []).find((x) => x.id === mealEd.id) || { id: mealEd.id, name: $('#meal-name').value };
    confirmDeleteSavedMeal(t, $('.sheet-foot', mealDlg), ev.currentTarget, () => { mealDlg.close(); $('#btn-new-meal').focus(); });
  });

  // ---- Fit to my targets (note 16 §10): POST /api/guidance/fit-recipe, then Save a fitted copy or Replace ---------------
  const fitDlg = $('#sheet-fit');
  const fit = { meal: null, result: null, req: 0, busy: false, undo: null };
  const STATUS_HEAD = {
    fits: 'One serving fits as it is.',
    fits_after_changes: 'It fits with the changes below.',
    fits_smaller_serving: 'It fits as a smaller serving, with the changes below.',
    does_not_fit: 'It does not fit, even with changes. This is the closest the app found.',
  };
  function openFitSheet(t, trigger) {
    fit.meal = t; fit.result = null; fit.undo = null;
    $('#sheet-fit-sub').textContent = isRecipe(t) ? `${t.name}: one serving (it makes ${fmtServings(t.servings_made)}).` : `${t.name}, as one serving.`;
    $('#fit-target').value = t.meal_hint || ''; // the meal it is meant for, else the next meal today
    sheets.open(fitDlg, trigger, $('#fit-target'));
    $('#fit-rework').hidden = true;
    aiRecipesOn().then((on) => { $('#fit-rework').hidden = !on; });
    runFit();
  }
  function fitTarget() {
    const v = $('#fit-target').value;
    return v === 'day' ? { kind: 'day', date: todayStr() } : { kind: 'meal', meal: v || null, date: todayStr() };
  }
  async function runFit() {
    const req = ++fit.req;
    const host = clear($('#fit-result'));
    host.append(h('p', { class: 'muted' }, 'Checking…'));
    $('#fit-save').hidden = true; $('#fit-replace').hidden = true;
    try {
      const r = await api.fitRecipe({ meal_id: fit.meal.id, target: fitTarget() });
      if (req !== fit.req) return;
      fit.result = r;
      renderFit();
    } catch (err) { if (req === fit.req) { clear(host); toastError(err); } }
  }
  function fitRow(c, after) {
    const key = c.nutrient;
    const unit = NUT[key] ? NUT[key].unit : '';
    const label = NUT[key] ? NUT[key].label || NUT[key].short : key;
    const now = after ? after.checks.find((x) => x.nutrient === key) : null;
    const text = now && now.used !== c.used ? `${fmtNum(c.used, key)} → ${fmtNum(now.used, key)}` : fmtNum(c.used, key);
    const ok = now ? now.ok : c.ok;
    return h('li', { class: ok ? 'fit-ok' : 'fit-over' }, h('span', {}, label), ' ', h('b', {}, `${text} ${unit}`),
      h('span', { class: 'muted' }, ` of ${fmtNum(c.room, key)} ${unit} room`), ok ? '' : h('span', { class: 'fit-over-word' }, ' (over)'));
  }
  function renderFit() {
    const r = fit.result;
    const host = clear($('#fit-result'));
    if (!r || !STATUS_HEAD[r.status]) { host.append(h('p', {}, r && r.message ? r.message : 'The app cannot check this now.')); return; }
    host.append(h('p', { class: 'fit-head' }, STATUS_HEAD[r.status]));
    const after = r.after || (r.closest ? r.closest.after : null);
    const unknown = Object.keys(r.before.unknown || {}).filter((k) => NUT[k]);
    host.append(h('ul', { class: 'fit-checks' }, r.before.checks.map((c) => fitRow(c, after))));
    if (unknown.length) host.append(h('p', { class: 'muted small' }, `Some foods do not list ${unknown.map((k) => NUT[k].short.toLowerCase()).join(', ')}, so those numbers are at least what is shown.`));
    if (r.changes.length) host.append(h('ul', { class: 'fit-changes' }, r.changes.map((c) => h('li', {}, c.text))));
    const shape = r.fitted || r.closest;
    if (shape && r.status !== 'fits') {
      host.append(h('h3', { class: 'preview-title' }, r.fitted ? 'The fitted recipe (whole pot)' : 'The closest it gets (whole pot)'),
        h('ul', { class: 'compact-items' }, shape.items.map((it) => h('li', {}, `${it.portion_text} ${it.name}`))));
    }
    for (const note of r.notes || []) host.append(h('p', { class: 'muted small' }, note));
    if (fit.undo) host.append(h('p', {}, 'Replaced. ', h('button', { class: 'link-btn', type: 'button', onclick: undoReplace }, 'Undo')));
    const canSave = !!r.fitted && r.status !== 'fits';
    $('#fit-save').hidden = !canSave; $('#fit-replace').hidden = !canSave || !!fit.undo;
  }
  const MAX_RECIPE_SERVINGS = 100; // app/models.py: the server refuses a recipe that makes more
  /** The fitted recipe as a saved-meal body. A smaller serving is saved as more servings from the same pot, so one saved serving
      is the size that fits. When that would be more than 100 servings, the pot is made smaller instead (every food scaled down
      alike), so one serving stays exactly the same and the server can save it. */
  function fittedBody(name) {
    const t = fit.meal, f = fit.result.fitted;
    const want = fit.result.servings_made / f.serving_fraction;
    const made = Math.min(want, MAX_RECIPE_SERVINGS);
    const scale = made / want;
    return { name: name.slice(0, 200), note: shownNote(t), meal_hint: t.meal_hint || null,
      items: f.items.map((it) => ({ food_id: it.food_id, servings: Math.max(0.001, Math.round(it.servings * scale * 1000) / 1000) })),
      servings_made: Math.round(made * 100) / 100, steps: t.steps || null, source_url: t.source_url || null };
  }
  const bodyOf = (t) => ({ name: t.name, note: t.note, meal_hint: t.meal_hint || null, items: t.items.map((it) => ({ food_id: it.food_id, servings: it.servings })),
    servings_made: t.servings_made ?? null, steps: t.steps || null, source_url: t.source_url || null });
  const carbsLine = () => {
    const before = fit.result.before.per_serving.carbs_g, after = fit.result.after ? fit.result.after.per_serving.carbs_g : null;
    return `Carbohydrate per serving goes from ${fmtNum(before, 'carbs_g')} g to ${fmtNum(after, 'carbs_g')} g.`;
  };
  $('#fit-target').addEventListener('change', () => { fit.undo = null; runFit(); });
  $('#fit-rework').addEventListener('click', () => {
    const t = fit.meal, target = fitTarget();
    const trigger = $('#saved-meals');
    fitDlg.close();
    KH.ai.openRecipes({ mode: 'change', mealId: t.id, name: t.name, meal: target.kind === 'meal' ? target.meal : null, trigger,
      onSaved: afterAiSave });
  });
  $('#fit-save').addEventListener('click', async () => {
    if (fit.busy || !fit.result || !fit.result.fitted) return;
    fit.busy = true;
    try {
      const saved = await api.createMeal(fittedBody(`${fit.meal.name} (fitted)`));
      toast(`Saved “${saved.name}”. ${carbsLine()}`, 'ok');
      fitDlg.close();
      await KH.loadMeals(true);
      renderSavedMeals();
    } catch (err) { toastError(err); } finally { fit.busy = false; }
  });
  $('#fit-replace').addEventListener('click', (ev) => {
    if (!fit.result || !fit.result.fitted) return;
    confirm.inline($('.sheet-foot', fitDlg), ev.currentTarget, {
      message: `Replace “${fit.meal.name}” with the fitted recipe? ${carbsLine()}`,
      confirmText: 'Replace',
      onConfirm: async () => {
        try {
          const old = bodyOf(fit.meal);
          await api.updateMeal(fit.meal.id, fittedBody(fit.meal.name));
          fit.undo = old;
          await KH.loadMeals(true);
          renderSavedMeals();
          renderFit();
          return true;
        } catch (err) { toastError(err); return false; }
      },
    });
  });
  async function undoReplace() {
    if (!fit.undo) return;
    try {
      await api.updateMeal(fit.meal.id, fit.undo);
      fit.undo = null;
      toast(`“${fit.meal.name}” is back as it was`, 'ok');
      await KH.loadMeals(true);
      renderSavedMeals();
      renderFit();
    } catch (err) { toastError(err); }
  }

  router.register('plan', () => loadPlan());
  KH.views.plan = { loadPlan, afterLogChange, openCopySheet, openApplySheet, openSaveMealSheet, openMealEditor, openFitSheet };
})();
