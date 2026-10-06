/* Kidney Diet Log — Add view: food search with category chips, saved-meal shortcuts, and the
   sheets that log food: the entry sheet (add + edit, warnings before saving), Quick add and
   the USDA search / import sheet. Meal guidance (js/views/guidance.js, KH.guidance) adds "What fits
   now" above the search and, in the entry sheet, "Used to treat a low" and swap ideas. */
(() => {
  'use strict';
  const KH = window.KH;
  const { h, s, $, $$, clear, api, state, toast, toastError, router, sheets, confirm } = KH;
  const { NUT, NUTRIENTS, FLAGS, FLAG, MEAL_LABEL, fmtNum, fmtWithUnit, fmtServings, evaluateWarnings } = KH.rules;
  const { KEY_NUMBERS, ROW_NUMBERS, LEVEL_TEXT, ratingIcon, levelPill, renderWarnings, selectedMeal, setMeal, selectedStatus, setStatus,
    scaledNutrients, impactOn } = KH.ui;
  const { todayStr, fmtDateLong, defaultStatusFor, defaultMealForNow, debounce, numOrNull } = KH.util;
  const { MOCK } = KH.flags;

  const searchInput = $('#food-search');
  const chipsEl = $('#category-chips');
  const resultsEl = $('#food-results');
  const resultsHeading = $('#results-heading');
  const resultsCount = $('#results-count');
  let addInitialized = false;
  let searchRequest = 0;

  async function initAdd() {
    if (KH.guidance) KH.guidance.add(); // reads state.addMealHint before a sheet consumes it
    if (!addInitialized) {
      addInitialized = true;
      try {
        const res = await api.categories();
        state.categories = res.categories || [];
      } catch (e) { toastError(e); }
      renderChips();
    }
    runSearch();
    KH.loadMeals().then(renderSavedShortcuts).catch(() => renderSavedShortcuts());
  }
  $('#saved-shortcuts-manage').addEventListener('click', () => router.show('plan'));
  function renderSavedShortcuts() {
    const wrap = $('#saved-shortcuts');
    const list = clear($('#saved-shortcuts-list'));
    const meals = state.meals || [];
    wrap.hidden = !meals.length;
    for (const t of meals) {
      // The list item wraps the button: a role="listitem" on the <button> itself would hide its
      // button role from screen readers (ARIA in HTML forbids that combination).
      const b = h('button', { class: 'meal-chip', type: 'button',
        'aria-label': `Add saved meal ${t.name}: ${t.items.length} ${t.items.length === 1 ? 'food' : 'foods'}, ${fmtNum(t.totals.carbs_g, 'carbs_g')} g carbs` },
        ratingIcon(t.kidney_rating, { decorative: true }),
        h('span', { class: 'meal-chip-main' }, h('span', { class: 'meal-chip-name' }, t.name),
          h('span', { class: 'meal-chip-sub' }, `${t.items.length} ${t.items.length === 1 ? 'food' : 'foods'} · ${fmtNum(t.totals.carbs_g, 'carbs_g')} g carbs · K ${fmtNum(t.totals.potassium_mg, 'potassium_mg')}`)));
      b.addEventListener('click', () => KH.views.plan.openApplySheet({ mealId: t.id, date: state.date, meal: state.addMealHint || defaultMealForNow(), status: state.addStatusHint, trigger: b }));
      list.append(h('div', { class: 'meal-chip-item', role: 'listitem' }, b));
    }
  }
  function renderChips() {
    clear(chipsEl);
    const mk = (label, value) => {
      const b = h('button', { class: 'chip', type: 'button', 'aria-pressed': state.category === value ? 'true' : 'false' }, label);
      b.addEventListener('click', () => { state.category = value; renderChips(); runSearch(); });
      return b;
    };
    chipsEl.append(mk('All', ''));
    for (const c of state.categories) chipsEl.append(mk(c, c));
  }
  async function runSearch() {
    const reqId = ++searchRequest;
    const q = searchInput.value.trim();
    state.query = q;
    try {
      const res = await api.foods({ q, category: state.category, limit: 25 });
      if (reqId !== searchRequest) return;
      renderResults(res.foods || []);
    } catch (e) { if (reqId === searchRequest) toastError(e); }
  }
  searchInput.addEventListener('input', debounce(runSearch, 250));
  searchInput.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); runSearch(); } });

  function renderResults(foods) {
    clear(resultsEl);
    const browsing = !state.query && !state.category;
    resultsHeading.textContent = browsing ? 'Recent foods' : state.query ? `Results for “${state.query}”` : state.category;
    resultsCount.textContent = foods.length ? `${foods.length}${foods.length >= 25 ? '+' : ''} ${foods.length === 1 ? 'food' : 'foods'}` : '';
    if (!foods.length) {
      resultsEl.append(h('li', { class: 'empty-state' }, 'No foods match. Try fewer words, use Quick add, or search USDA.'));
      return;
    }
    for (const f of foods) resultsEl.append(h('li', {}, foodRow(f)));
  }
  function foodRow(f) {
    const nums = h('div', { class: 'row-nums' });
    for (const k of ROW_NUMBERS) nums.append(h('span', { class: 'n' }, `${NUT[k].short} `, h('b', {}, fmtNum(f.nutrients[k], k)), ` ${NUT[k].unit}`));
    const btn = h('button', { class: 'row-btn', type: 'button' },
      ratingIcon(f.kidney_rating),
      h('div', { class: 'row-main' },
        h('div', { class: 'row-title' }, f.name, f.brand ? h('span', { class: 'row-sub' }, ` (${f.brand})`) : null,
          f.source && f.source !== 'builtin' ? h('span', { class: 'food-source' }, f.source) : null),
        h('div', { class: 'row-sub' }, f.serving_desc, f.flags && f.flags.includes('hypo_treatment') ? ' · hypo treatment' : '')),
      nums);
    btn.addEventListener('click', () => openEntrySheet('add', { food: f, trigger: btn }));
    return btn;
  }

  // ---------------------------------------------------------------------------
  // ENTRY sheet (add + edit)
  // ---------------------------------------------------------------------------
  const entryDlg = $('#sheet-entry');
  const entryForm = $('#entry-form');
  const entryServings = $('#entry-servings');
  const entryGrams = $('#entry-grams');
  const entryNote = $('#entry-note');
  const entryDate = $('#entry-date');
  const sheet = { mode: 'add', food: null, entry: null, perServing: null, lastEdited: 'servings', amountTouched: false, busy: false };
  sheets.setup(entryDlg);

  function perServingFromEntry(entry) {
    const out = {};
    for (const n of NUTRIENTS) {
      const v = entry.nutrients ? entry.nutrients[n.key] : null;
      out[n.key] = v == null || !entry.servings ? v : v / entry.servings;
    }
    return out;
  }
  function updateStatusHint() {
    const st = selectedStatus($('#entry-status'));
    const date = sheet.mode === 'edit' && entryDate.value ? entryDate.value : state.date;
    const when = date === todayStr() ? 'today' : date > todayStr() ? 'that day' : 'this day';
    $('#entry-status-hint').textContent = st === 'planned'
      ? `Planned foods count toward the projected total for ${when}, not the eaten total. Tap "Eaten" later.`
      : `Counts toward the eaten total for ${when}.`;
  }
  function updateEntryCta() {
    // Planning a food must not read like eating it: title and primary button follow the status.
    if (sheet.mode !== 'add') return;
    const planned = selectedStatus($('#entry-status')) === 'planned';
    const meal = MEAL_LABEL[selectedMeal($('#entry-meal'))] || 'meal';
    $('#sheet-entry-title').textContent = planned ? 'Plan food' : 'Add food';
    $('#entry-save').textContent = planned ? `Plan for ${meal.toLowerCase()}` : `Add to ${meal.toLowerCase()}`;
  }
  $('#entry-status').addEventListener('change', () => { updateStatusHint(); updateEntryCta(); updatePreview(); });
  $('#entry-meal').addEventListener('change', updateEntryCta);
  entryDate.addEventListener('change', updateStatusHint);

  // servings / status: prefilled by a suggestion (KH.guidance: What fits now, swap ideas).
  async function openEntrySheet(mode, { food, entry, meal, trigger, servings = null, status = null }) {
    sheet.mode = mode; sheet.food = food || null; sheet.entry = entry || null;
    sheet.lastEdited = 'servings'; sheet.amountTouched = false; sheet.busy = false;
    entryDlg.dataset.mode = mode;
    $('#sheet-entry-title').textContent = mode === 'add' ? 'Add food' : 'Edit entry';
    $('#entry-save').textContent = mode === 'add' ? 'Add to meal' : 'Save changes';
    const name = food ? food.name : entry.food_name;
    sheet.perServing = food ? food.nutrients : perServingFromEntry(entry);
    renderSheetFood();
    setMeal($('#entry-meal'), entry ? entry.meal : meal || state.addMealHint || defaultMealForNow());
    setStatus($('#entry-status'), entry ? entry.status || 'eaten' : status || state.addStatusHint || defaultStatusFor(state.date));
    state.addMealHint = null; state.addStatusHint = null;
    updateStatusHint();
    updateEntryCta();
    entryServings.value = entry ? String(Math.round(entry.servings * 1000) / 1000) : servings != null ? String(Math.round(servings * 1000) / 1000) : '1';
    entryGrams.value = entry && entry.grams != null ? String(Math.round(entry.grams)) : '';
    entryNote.value = entry && entry.note ? entry.note : '';
    entryDate.value = entry ? entry.date : state.date;
    entryGrams.disabled = !food;
    $('#entry-grams-hint').textContent = food ? `1 serving = ${fmtNum(food.serving_g, 'fluid_ml')} g` : 'Loading serving size…';
    $('#entry-delete-food').hidden = !(mode === 'add' && food && food.source !== 'builtin');
    if (food && !entryGrams.value) syncGramsFromServings();
    if (KH.guidance) KH.guidance.entry.open({ mode, food, entry, onChange: updatePreview });
    updatePreview();
    sheets.open(entryDlg, trigger, entryServings);
    if (!food && entry) {
      try {
        const f = await api.food(entry.food_id);
        if (sheet.entry !== entry) return;
        sheet.food = f;
        sheet.perServing = f.nutrients;
        entryGrams.disabled = false;
        $('#entry-grams-hint').textContent = `1 serving = ${fmtNum(f.serving_g, 'fluid_ml')} g`;
        if (!entryGrams.value) syncGramsFromServings();
        renderSheetFood();
        if (KH.guidance) KH.guidance.entry.open({ mode, food: f, entry, onChange: updatePreview, refresh: true });
        updatePreview();
      } catch (e) {
        $('#entry-grams-hint').textContent = 'Serving size unavailable';
        $('#sheet-entry-food').textContent = name;
      }
    }
  }
  function renderSheetFood() {
    const f = sheet.food;
    const name = f ? f.name : sheet.entry.food_name;
    const sub = $('#sheet-entry-food');
    clear(sub);
    const rating = f ? f.kidney_rating : sheet.entry.kidney_rating;
    sub.append(h('span', { class: 'sheet-food-name' }, name), f && f.brand ? ` (${f.brand})` : '', f ? ` · ${f.serving_desc}` : '', ' ', levelPill(rating, rating === 'red' ? 'High concern' : rating === 'yellow' ? 'Moderate' : 'Kidney-friendly'));
    $('#entry-serving-desc').textContent = f ? `1 serving = ${f.serving_desc}` : '';
    const chips = clear($('#sheet-entry-flags'));
    for (const fl of (f && f.flags) || []) {
      const def = FLAG[fl];
      chips.append(h('span', { class: `flag-chip ${def ? def.kind : ''}` }, def ? def.label : fl));
    }
    const notes = $('#sheet-entry-notes');
    notes.hidden = !(f && f.kidney_notes);
    notes.textContent = f && f.kidney_notes ? f.kidney_notes : '';
  }
  function servingsValue() { const v = Number(entryServings.value); return Number.isFinite(v) && v >= 0 ? v : 0; }
  function syncGramsFromServings() {
    if (sheet.food && sheet.food.serving_g) entryGrams.value = String(Math.round(servingsValue() * sheet.food.serving_g));
  }
  function syncServingsFromGrams() {
    const g = Number(entryGrams.value);
    if (sheet.food && sheet.food.serving_g && Number.isFinite(g) && g >= 0) entryServings.value = String(Math.round((g / sheet.food.serving_g) * 100) / 100);
  }
  entryServings.addEventListener('input', () => { sheet.lastEdited = 'servings'; sheet.amountTouched = true; syncGramsFromServings(); updatePreview(); });
  entryGrams.addEventListener('input', () => { sheet.lastEdited = 'grams'; sheet.amountTouched = true; syncServingsFromGrams(); updatePreview(); });
  $$('.step-btn', entryDlg).forEach((b) => b.addEventListener('click', () => {
    const next = Math.max(0, Math.round((servingsValue() + Number(b.dataset.step)) * 100) / 100);
    entryServings.value = String(next);
    sheet.lastEdited = 'servings'; sheet.amountTouched = true;
    syncGramsFromServings(); updatePreview();
  }));
  $('#entry-meal').addEventListener('change', updatePreview);

  function previewServings() {
    // When the weight was typed last, preview with the exact ratio the server scales the entry by
    // (grams / serving_g, unrounded; only the entry's displayed `servings` is rounded to 3
    // decimals), not the 2-decimal number shown in the servings box, so the numbers read before
    // saving are the numbers seen after saving.
    const g = Number(entryGrams.value);
    if (sheet.lastEdited === 'grams' && sheet.food && sheet.food.serving_g && Number.isFinite(g) && g > 0) {
      return g / sheet.food.serving_g;
    }
    return servingsValue();
  }
  function updatePreview() {
    const sv = previewServings();
    const scaled = scaledNutrients(sheet.perServing, sv);
    $('#entry-preview-amount').textContent = `${fmtServings(sv)}${entryGrams.value ? ` · ${entryGrams.value} g` : ''}`;
    const key = clear($('#entry-preview-key'));
    for (const k of KEY_NUMBERS) {
      key.append(h('div', { class: 'kn' }, h('span', { class: 'kn-v' }, fmtNum(scaled[k], k)), h('span', { class: 'kn-u' }, NUT[k].unit), h('span', { class: 'kn-l' }, NUT[k].short)));
    }
    const all = clear($('#entry-preview-all'));
    for (const n of NUTRIENTS) all.append(h('div', { class: 'ng' }, h('span', {}, n.label), h('b', {}, fmtWithUnit(scaled[n.key], n.key))));

    // Warnings: the server's per-serving warnings for exactly one serving, else re-evaluated for this amount.
    const f = sheet.food;
    let warnings;
    if (sv === 1 && f && Array.isArray(f.warnings)) warnings = f.warnings;
    else warnings = evaluateWarnings(scaled, f ? f.flags : [], f ? f.kidney_notes : '', false);
    const box = $('#entry-warnings');
    const G = KH.guidance ? KH.guidance.entry : null;
    const impact = dayImpact(scaled, selectedMeal($('#entry-meal')));
    if (G) {
      G.update({ mode: sheet.mode, food: f, entry: sheet.entry, servings: sv, grams: Number(entryGrams.value) || null, lastEdited: sheet.lastEdited,
        amountTouched: sheet.amountTouched, meal: selectedMeal($('#entry-meal')), status: selectedStatus($('#entry-status')),
        date: sheet.mode === 'edit' && sheet.entry ? sheet.entry.date : state.date, warnings, impact });
    }
    // A low treatment is never warned against (note 06 F5): its numbers are shown as information.
    if (G && G.isHypo()) { G.renderHypoNote(box, scaled); return; }
    renderWarnings(box, warnings);
    // Day impact: where would today's running totals land after this entry?
    if (impact.length) {
      const list = h('div', { class: 'warnings impact' });
      for (const it of impact) {
        list.append(h('div', { class: `warning level-${it.level}` }, ratingIcon(it.level, { label: LEVEL_TEXT[it.level] }),
          h('div', {}, h('span', { class: 'w-level' }, `${it.level === 'over' ? 'Day total over. ' : 'Day total near limit. '}`), it.message)));
      }
      box.append(list);
    }
  }
  function dayImpact(scaled, meal) {
    const day = state.day;
    if (!day || state.dayLoadedFor !== (sheet.entry ? sheet.entry.date : state.date)) return [];
    return impactOn(day, scaled, meal, { editing: sheet.mode === 'edit' ? sheet.entry : null, status: selectedStatus($('#entry-status')) });
  }

  sheets.onSubmit(entryForm, async (e) => {
    e.preventDefault();
    if (sheet.busy) return;
    const sv = servingsValue();
    if (!(sv > 0)) { toast('Servings must be more than 0', 'error'); entryServings.focus(); return; }
    if (sv > 1000) { toast('Servings must be 1000 or fewer', 'error'); entryServings.focus(); return; }
    const meal = selectedMeal($('#entry-meal'));
    const status = selectedStatus($('#entry-status'));
    const note = entryNote.value.trim() || null;
    const grams = sheet.lastEdited === 'grams' && entryGrams.value !== '' ? Number(entryGrams.value) : null;
    if (grams != null && !(grams > 0 && grams <= 100000)) { toast('Grams must be between 1 and 100,000', 'error'); entryGrams.focus(); return; }
    sheet.busy = true;
    const saveBtn = $('#entry-save');
    saveBtn.disabled = true;
    try {
      if (sheet.mode === 'add') {
        const body = { date: state.date, meal, food_id: sheet.food.id, servings: sv, note, status };
        if (grams != null) body.grams = grams;
        const purpose = KH.guidance ? KH.guidance.entry.purpose('add') : undefined;
        if (purpose) body.purpose = purpose;
        const created = await api.addEntry(body);
        entryDlg.close();
        const when = state.date !== todayStr() ? `, ${fmtDateLong(state.date)}` : '';
        toast(`${status === 'planned' ? 'Planned' : 'Added'} ${created.food_name || sheet.food.name} ${status === 'planned' ? 'for' : 'to'} ${MEAL_LABEL[meal].toLowerCase()}${when}`, 'ok');
        state.dayLoadedFor = null;
        router.show('today');
      } else {
        const body = { meal, note, status };
        if (entryDate.value && /^\d{4}-\d{2}-\d{2}$/.test(entryDate.value)) body.date = entryDate.value;
        if (sheet.amountTouched) { body.servings = sv; body.grams = grams; }
        const purpose = KH.guidance ? KH.guidance.entry.purpose('edit') : undefined;
        if (purpose) body.purpose = purpose;
        await api.updateEntry(sheet.entry.id, body);
        entryDlg.close();
        toast('Entry updated', 'ok');
        if (body.date && body.date !== state.date) KH.views.today.setDate(body.date); else KH.views.today.loadDay();
      }
    } catch (err) { toastError(err); }
    finally { sheet.busy = false; saveBtn.disabled = false; }
  });
  $('#entry-delete').addEventListener('click', (ev) => {
    const entry = sheet.entry;
    if (!entry || sheet.busy) return;
    confirm.inline($('.sheet-foot', entryDlg), ev.currentTarget, {
      message: `Delete ${entry.food_name} from ${MEAL_LABEL[entry.meal].toLowerCase()}${entry.date !== todayStr() ? ` on ${fmtDateLong(entry.date)}` : ''}?`,
      confirmText: 'Delete entry',
      onConfirm: async () => {
        sheet.busy = true;
        try {
          await api.deleteEntry(entry.id);
          entryDlg.close();
          toast('Entry deleted', 'ok');
          KH.views.today.loadDay();
          return true;
        } catch (err) { toastError(err); return false; }
        finally { sheet.busy = false; }
      },
    });
  });
  $('#entry-delete-food').addEventListener('click', (ev) => {
    const f = sheet.food;
    if (!f || sheet.busy) return;
    confirm.inline($('.sheet-foot', entryDlg), ev.currentTarget, {
      message: `Delete the food "${f.name}" from your database? Logged entries keep their numbers.`,
      confirmText: 'Delete food',
      onConfirm: async () => {
        sheet.busy = true;
        try {
          await api.deleteFood(f.id);
          entryDlg.close();
          toast('Food deleted', 'ok');
          runSearch();
          return true;
        } catch (err) { toastError(err); return false; }
        finally { sheet.busy = false; }
      },
    });
  });

  // ---------------------------------------------------------------------------
  // QUICK ADD sheet
  // ---------------------------------------------------------------------------
  const quickDlg = $('#sheet-quick');
  const quickForm = $('#quick-form');
  sheets.setup(quickDlg);
  (function buildQuickForm() {
    const grid = $('#quick-nutrients');
    for (const n of NUTRIENTS) {
      const id = `qn-${n.key}`;
      grid.append(h('div', { class: 'field' },
        h('label', { for: id }, `${n.label} (${n.unit})`),
        h('input', { id, type: 'number', inputmode: 'decimal', min: 0, step: n.unit === 'g' ? 0.1 : 1, 'data-nutrient': n.key, placeholder: '0' })));
    }
    const flags = $('#quick-flags');
    for (const f of FLAGS) {
      const id = `qf-${f.key}`;
      flags.append(h('label', { class: 'check', for: id },
        h('input', { type: 'checkbox', id, 'data-flag': f.key }),
        h('span', { class: 'check-text' }, f.label, f.hint ? h('span', { class: 'hint' }, f.hint) : null)));
    }
    quickForm.addEventListener('input', updateQuickPreview);
  })();
  function quickNutrients() {
    const out = {};
    for (const inp of $$('#quick-nutrients input')) { const v = numOrNull(inp.value); if (v != null) out[inp.dataset.nutrient] = v; }
    return out;
  }
  function quickFlags() { return $$('#quick-flags input:checked').map((i) => i.dataset.flag); }
  function updateQuickPreview() {
    const sv = Number($('#q-servings').value) || 1;
    const per = quickNutrients();
    const flags = quickFlags();
    if (flags.includes('counts_as_fluid') && per.fluid_ml == null && $('#q-serving-g').value) per.fluid_ml = Number($('#q-serving-g').value);
    const scaled = scaledNutrients(per, sv);
    const warnings = evaluateWarnings(scaled, flags, '', false);
    renderWarnings($('#quick-warnings'), warnings, { emptyText: 'Enter the label values to see per-serving warnings.' });
  }
  $('#btn-quick').addEventListener('click', (e) => {
    quickForm.reset();
    $('#q-serving-desc').value = '1 serving';
    $('#q-serving-g').value = '100';
    $('#q-servings').value = '1';
    setMeal($('#quick-meal'), state.addMealHint || defaultMealForNow());
    setStatus($('#quick-status'), state.addStatusHint || defaultStatusFor(state.date));
    updateQuickPreview();
    sheets.open(quickDlg, e.currentTarget, $('#q-name'));
  });
  let quickBusy = false;
  sheets.onSubmit(quickForm, async (e) => {
    e.preventDefault();
    if (quickBusy) return;
    const name = $('#q-name').value.trim();
    if (!name) { toast('Give the food a name', 'error'); $('#q-name').focus(); return; }
    const nutrients = quickNutrients();
    if (!Object.keys(nutrients).length) { toast('Enter at least one nutrient value', 'error'); return; }
    const flags = quickFlags();
    const servingG = numOrNull($('#q-serving-g').value) || 100;
    if (flags.includes('counts_as_fluid') && nutrients.fluid_ml == null) nutrients.fluid_ml = servingG;
    const body = { date: state.date, meal: selectedMeal($('#quick-meal')), name, serving_desc: $('#q-serving-desc').value.trim() || '1 serving',
      serving_g: servingG, nutrients, servings: Number($('#q-servings').value) || 1, flags, status: selectedStatus($('#quick-status')) };
    quickBusy = true; $('#quick-save').disabled = true;
    try {
      const created = await api.quick(body);
      quickDlg.close();
      const when = state.date !== todayStr() ? `, ${fmtDateLong(state.date)}` : '';
      toast(`${body.status === 'planned' ? 'Planned' : 'Logged'} ${created.food_name || name} ${body.status === 'planned' ? 'for' : 'to'} ${MEAL_LABEL[body.meal].toLowerCase()}${when}`, 'ok');
      state.dayLoadedFor = null;
      router.show('today');
    } catch (err) { toastError(err); }
    finally { quickBusy = false; $('#quick-save').disabled = false; }
  });

  // ---------------------------------------------------------------------------
  // USDA sheet
  // ---------------------------------------------------------------------------
  const usdaDlg = $('#sheet-usda');
  const usdaForm = $('#usda-form');
  const usdaStatus = $('#usda-status');
  const usdaResults = $('#usda-results');
  sheets.setup(usdaDlg);
  const USDA_DISABLED_MSG = MOCK
    ? 'USDA search needs the installed app with a USDA API key (free at api.data.gov); the server looks foods up for you. This preview has no server, so use the built-in list or Quick add.'
    : 'USDA search is not set up on this server. Add your own key in Settings → Food data (free at api.data.gov), or ask your admin to share one.';
  $('#btn-usda').addEventListener('click', (e) => {
    clear(usdaResults);
    usdaStatus.textContent = MOCK ? USDA_DISABLED_MSG : '';
    sheets.open(usdaDlg, e.currentTarget, $('#usda-q'));
  });
  async function usdaSearch() {
    const q = $('#usda-q').value.trim();
    if (!q) { $('#usda-q').focus(); return; }
    usdaStatus.textContent = 'Searching USDA FoodData Central…';
    clear(usdaResults);
    try {
      const res = await api.usdaSearch(q);
      const foods = res.foods || [];
      usdaStatus.textContent = foods.length ? `${foods.length} results. Tap one to import it.` : 'No results from USDA.';
      for (const f of foods) {
        const btn = h('button', { class: 'row-btn', type: 'button' },
          s('svg', { class: 'rating', viewBox: '0 0 24 24', 'aria-hidden': 'true' }, s('path', { d: 'M12 4v16M4 12h16', stroke: 'currentColor', 'stroke-width': 2, 'stroke-linecap': 'round', opacity: 0.6 })),
          h('div', { class: 'row-main' },
            h('div', { class: 'row-title' }, f.description),
            h('div', { class: 'row-sub' }, [f.brand, f.category, f.data_type].filter(Boolean).join(' · '))),
          h('span', { class: 'muted small' }, 'Import'));
        btn.addEventListener('click', () => usdaImport(f, btn));
        usdaResults.append(h('li', {}, btn));
      }
    } catch (err) {
      // v0.3: a 503 with a reason ("not_configured", "quota_exhausted", ...) says what to do,
      // e.g. "Add your own key in Settings → Food data"; an older 503 gets the general text.
      usdaStatus.textContent = err.status === 503 ? (err.data && err.data.reason && err.detail ? err.detail : USDA_DISABLED_MSG)
        : `USDA search failed: ${err.detail || err.message}`;
    }
  }
  async function usdaImport(f, btn) {
    btn.disabled = true;
    usdaStatus.textContent = `Importing “${f.description}”…`;
    try {
      const food = await api.usdaImport(f.fdc_id);
      usdaDlg.close();
      toast(`Imported ${food.name}`, 'ok');
      openEntrySheet('add', { food, trigger: $('#btn-usda') });
    } catch (err) {
      usdaStatus.textContent = err.status === 503 ? (err.data && err.data.reason && err.detail ? err.detail : USDA_DISABLED_MSG)
        : `Import failed: ${err.detail || err.message}`;
      btn.disabled = false;
    }
  }
  $('#usda-go').addEventListener('click', usdaSearch);
  usdaForm.addEventListener('submit', (e) => { e.preventDefault(); usdaSearch(); });
  $('#usda-q').addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); usdaSearch(); } });

  // Set the entry sheet's servings (a swap idea's "Use this amount").
  function setServings(n) {
    entryServings.value = String(Math.round(n * 1000) / 1000);
    sheet.lastEdited = 'servings'; sheet.amountTouched = true;
    syncGramsFromServings(); updatePreview();
    entryServings.focus();
  }

  router.register('add', () => initAdd());
  KH.views.add = { initAdd, runSearch, renderSavedShortcuts, openEntrySheet, setServings };
})();
