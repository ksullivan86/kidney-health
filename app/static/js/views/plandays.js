/* Kidney Diet Log — "Plan several days" (design note 23): plan 1 to 14 days at once from the Plan tab.

   Fills the guidance sheet (#sheet-guidance, kind "plan-days") with the range (first day, number of days, quick choices), the
   meals to plan, a preview of each day (POST /api/guidance/plan-days, which computes only), and the range's shopping list.
   Nothing is written until the person confirms "Add to plan": the foods then go in as planned food through
   POST /api/log/batch, at most 40 a request, each with its own client_id, so a retry after a lost answer adds nothing twice.
   Undo takes off exactly the foods that were added; "Clear planned days" takes off every planned food of the range
   (POST /api/log/clear-planned). Eaten food is never touched and a planned low treatment stays. A plan never holds a low
   treatment and nothing here delays treating one. Answers are kept in memory only (KH.guidance.plan.remembered). */
(() => {
  'use strict';
  const KH = window.KH;
  const { h, $, $$, clear, state, toast, request, sheets, confirm } = KH;
  const { MEALS, MEAL_LABEL, fmtServings, fmtNum } = KH.rules;
  const { todayStr, addDays, fmtDateShort, weekStartOf, daysBetween, debounce } = KH.util;
  const G = KH.guidance;
  const P = G.plan;

  const MAX_DAYS = 14; // the server's PLAN_DAYS_MAX (app/guidance/rules.py, design note 23 §2)
  const BATCH = 40; // POST /api/log/batch takes at most 40 entries
  const api = {
    planDays: (body) => request('POST', '/api/guidance/plan-days', body),
    logBatch: (entries) => request('POST', '/api/log/batch', { entries }),
    clearPlanned: (body) => request('POST', '/api/log/clear-planned', body),
  };
  const st = { start: null, days: 7, meals: [], variant: 0, options: { use_saved_meals: true, use_usual: true, use_starters: true },
    result: null, rows: null, request: 0, busy: false };

  const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;
  function rangeText(start, end) { return start === end ? fmtDateShort(start) : `${fmtDateShort(start)} to ${fmtDateShort(end)}`; }
  function endOf() { return addDays(st.start, st.days - 1); }
  function validRange() { return /^\d{4}-\d{2}-\d{2}$/.test(st.start || '') && Number.isInteger(st.days) && st.days >= 1 && st.days <= MAX_DAYS; }
  function restOfWeek() {
    const pref = KH.views.plan && KH.views.plan.weekStartPref ? KH.views.plan.weekStartPref() : 'monday';
    return daysBetween(st.start, addDays(weekStartOf(st.start, pref), 6)) + 1;
  }

  // ---- The sheet ----------------------------------------------------------------------------------------------------
  async function openPlanDays({ start = null, trigger = null } = {}) {
    await G.loadPrefs();
    Object.assign(st, { start: start || todayStr(), days: 7, meals: [], variant: 0, result: null, rows: null });
    const { body, foot } = P.fillSheet('plan-days', 'Plan these days',
      'Up to 14 days from your own foods. Each day is planned against what is left of your targets.');
    const startInput = h('input', { id: 'g-days-start', type: 'date', value: st.start, required: true });
    const countInput = h('input', { id: 'g-days-count', type: 'number', min: '1', max: String(MAX_DAYS), step: '1', inputmode: 'numeric',
      value: String(st.days), required: true, 'aria-describedby': 'g-days-count-hint' });
    const setCount = (n) => { st.days = n; countInput.value = String(n); changed(); };
    const quick = h('div', { class: 'g-days-quick', role: 'group', 'aria-label': 'Quick choices' },
      h('button', { class: 'btn secondary', type: 'button', id: 'g-days-week', onclick: () => setCount(restOfWeek()) }, 'Rest of this week'),
      h('button', { class: 'btn secondary', type: 'button', id: 'g-days-7', onclick: () => setCount(7) }, '7 days'),
      h('button', { class: 'btn secondary', type: 'button', id: 'g-days-14', onclick: () => setCount(MAX_DAYS) }, '14 days'));
    const mealsBox = h('div', { class: 'checks four g-plan-meals' });
    for (const m of MEALS) {
      const id = `g-days-meal-${m.key}`;
      const box = h('input', { type: 'checkbox', id, value: m.key });
      box.addEventListener('change', () => { st.meals = $$('input:checked', mealsBox).map((x) => x.value); changed(); });
      mealsBox.append(h('label', { class: 'check', for: id }, box, h('span', { class: 'check-text' }, m.label)));
    }
    const opts = h('div', { class: 'g-plan-options' });
    for (const [key, label] of [['use_saved_meals', 'Use my saved meals'], ['use_usual', 'Use meals I often have'], ['use_starters', 'Use starter meals']]) {
      const id = `g-days-${key}`;
      const box = h('input', { type: 'checkbox', id });
      box.checked = st.options[key];
      box.addEventListener('change', () => { st.options[key] = box.checked; changed(); });
      opts.append(h('label', { class: 'check', for: id }, box, h('span', { class: 'check-text' }, label)));
    }
    startInput.addEventListener('change', () => { if (/^\d{4}-\d{2}-\d{2}$/.test(startInput.value)) { st.start = startInput.value; changed(); } });
    const typed = debounce(() => changed(), 400);
    countInput.addEventListener('input', () => { st.days = Number(countInput.value); typed(); });
    const clearRow = h('p', { class: 'g-days-clear' },
      h('button', { class: 'link-btn', type: 'button', id: 'g-days-clear', onclick: (e) => confirmClear(e.currentTarget) }, 'Clear planned days…'));
    const out = h('div', { class: 'g-plan-out', id: 'g-days-out' });
    body.append(
      h('div', { class: 'g-days-range' },
        h('div', { class: 'field' }, h('label', { for: 'g-days-start' }, 'First day'), startInput),
        h('div', { class: 'field' }, h('label', { for: 'g-days-count' }, 'Days'), countInput)),
      h('span', { class: 'hint', id: 'g-days-count-hint' }, '1 to 14 days.'),
      quick,
      h('fieldset', { class: 'field' }, h('legend', {}, 'Meals to plan'), mealsBox,
        h('span', { class: 'hint' }, 'With none ticked, every meal with nothing logged yet. A ticked meal is planned on every day.')),
      h('details', { class: 'g-disclosure' }, h('summary', {}, 'Where ideas come from'), opts),
      clearRow,
      h('p', { class: 'sr-only', role: 'status', id: 'g-days-status' }),
      out);
    const another = h('button', { class: 'btn secondary', type: 'button', id: 'g-days-another', disabled: true,
      onclick: () => { st.variant = (st.variant + 1) % (P.MAX_VARIANT + 1); run(); } }, 'Show another');
    const add = h('button', { class: 'btn primary', type: 'button', id: 'g-days-add', disabled: true, onclick: (e) => confirmAdd(e.currentTarget) }, 'Add to plan');
    foot.append(another, h('span', { class: 'spacer' }), add);
    sheets.open(P.sheetEl, trigger, startInput);
    run();
  }
  function changed() { st.variant = 0; run(); }
  function live(text) { const el = $('#g-days-status'); if (el) el.textContent = text; }
  function setButtons({ add = false, another = false } = {}) {
    const a = $('#g-days-add'), b = $('#g-days-another');
    if (a) a.disabled = !add;
    if (b) b.disabled = !another;
  }

  async function run() {
    const out = $('#g-days-out');
    if (!out) return;
    const reqId = ++st.request;
    st.result = null;
    st.rows = null;
    setButtons();
    $('#g-days-clear').disabled = !validRange();
    if (!validRange()) {
      clear(out).append(h('p', { class: 'empty-state' }, 'Choose a first day and 1 to 14 days.'));
      return;
    }
    const body = { start: st.start, days: st.days, variant: st.variant, ...st.options };
    if (st.meals.length) body.meals = st.meals;
    out.setAttribute('aria-busy', 'true');
    clear(out).append(P.loadingNote(`Planning ${plural(st.days, 'day', 'days')}…`));
    try {
      const { data, at } = await P.remembered(`plan-days:${JSON.stringify(body)}`, () => api.planDays(body));
      if (reqId !== st.request) return;
      P.noteAnswer(data);
      st.result = data;
      render(out, data, at);
    } catch (err) {
      if (reqId !== st.request) return;
      if (!err.handled) clear(out).append(P.failure(err));
      live(err.offline ? P.NEEDS_CONNECTION : 'The plan could not be made.');
    } finally {
      if (reqId === st.request) out.removeAttribute('aria-busy');
    }
  }
  // "Not for me" on a planned food: plan the same days again without it (the menu is in js/views/guidance.js).
  async function replan() {
    await run();
    const b = $('#g-days-another');
    if (b && !b.disabled) b.focus();
  }

  // ---- The preview ------------------------------------------------------------------------------------------------
  function render(out, res, at) {
    clear(out);
    if (!res || res.status !== 'ok') {
      out.append(P.unavailable(res));
      live(res && res.message ? res.message : '');
      return;
    }
    const entries = (res.apply && res.apply.entries) || [];
    const stale = P.staleNote(at);
    if (stale) out.append(stale);
    out.append(h('p', { class: 'hint' }, `${rangeText(res.start, res.end)} · option ${res.variant + 1} of ${P.MAX_VARIANT + 1}`));
    const perDay = new Map();
    for (const e of entries) perDay.set(e.date, (perDay.get(e.date) || 0) + 1);
    let opened = false;
    for (const d of res.days) {
      const n = perDay.get(d.date) || 0;
      const sum = h('summary', { class: 'g-days-sum' },
        h('span', { class: 'g-days-date' }, fmtDateShort(d.date)),
        d.dialysis_day ? h('span', { class: 'badge dialysis' }, 'Dialysis day') : null,
        h('span', { class: 'muted small' }, d.meals.length ? `${plural(d.meals.length, 'meal', 'meals')}, ${plural(n, 'food', 'foods')}` : 'Nothing to plan'));
      const inner = h('div', { class: 'g-days-body' });
      const day = h('details', { class: 'g-days-day', 'data-date': d.date }, sum, inner);
      if (!opened && d.meals.length) { day.open = true; opened = true; }
      const box = inner;
      if (!d.meals.length) box.append(h('p', { class: 'empty-state' }, 'Every meal of this day already has food. Tick the meals you want planned anyway.'));
      for (const m of d.meals) {
        const sec = P.planMeal(m);
        if (m.repeated) sec.append(h('p', { class: 'hint g-days-repeat' }, 'Same as a day before: nothing else fits.'));
        box.append(sec);
      }
      if (d.protein_topup && d.protein_topup.length) {
        box.append(h('p', { class: 'g-tip' }, `The protein portion at ${P.joinWords(d.protein_topup.map((x) => MEAL_LABEL[x].toLowerCase()))} was made larger to reach your daily protein minimum.`));
      }
      if (d.meals.length) {
        if (d.energy_note) box.append(P.energyNote(d.energy_note));
        box.append(P.dayAfter(d.day_after));
      }
      out.append(day);
    }
    out.append(shopping(res));
    const used = P.targetsUsed(res.targets, { beforeLeave: () => P.sheetEl.close() });
    if (used) out.append(used);
    const n = P.notes(res.notes);
    if (n) out.append(n);
    const days = perDay.size;
    setButtons({ add: entries.length > 0 && !at, another: entries.length > 0 });
    const add = $('#g-days-add');
    if (add) add.setAttribute('aria-label', entries.length ? `Add to plan: ${plural(entries.length, 'food', 'foods')} on ${plural(days, 'day', 'days')}` : 'Add to plan');
    live(entries.length ? `Plan option ${res.variant + 1}: ${plural(entries.length, 'food', 'foods')} on ${plural(days, 'day', 'days')}.`
      : 'Every meal of these days already has food. Tick the meals to plan anyway.');
  }

  // What the plan adds, summed over the days (GET /api/plan/shopping's shape), with Copy list and Share list (note 22 part A).
  function shopping(res) {
    const items = (res.shopping && res.shopping.items) || [];
    const sec = h('section', { class: 'g-days-shop', 'aria-labelledby': 'g-days-shop-h' },
      h('h3', { class: 'g-group-title', id: 'g-days-shop-h' }, 'Shopping list for these days'));
    if (!items.length) { sec.append(h('p', { class: 'hint' }, 'This plan adds no food.')); return sec; }
    sec.append(h('ul', { class: 'compact-items g-days-shop-list', role: 'list' }, items.map((it) => h('li', {},
      h('span', { class: 'ci-name' }, it.food_name),
      h('span', { class: 'ci-amt muted' }, `${fmtServings(it.servings)}${it.serving_desc ? ` of ${it.serving_desc}` : ''}${it.grams ? ` · ${fmtNum(it.grams, 'fluid_ml')} g` : ''} · ${plural(it.days, 'day', 'days')}`)))));
    const text = h('textarea', { class: 'shopping-text', rows: '6', readonly: true, hidden: true, 'aria-label': 'Shopping list as text', id: 'g-days-shop-text' });
    const listText = () => KH.views.plan.shoppingText({ start: res.start, end: res.end, items }, new Set());
    const row = h('div', { class: 'shopping-foot' },
      h('button', { class: 'btn secondary', type: 'button', id: 'g-days-copy', onclick: () => KH.views.plan.copyShopping(listText(), text) }, 'Copy list'));
    if (typeof navigator.share === 'function') {
      row.prepend(h('button', { class: 'btn secondary', type: 'button', id: 'g-days-share', onclick: async () => {
        try { await navigator.share({ title: 'Shopping list', text: listText() }); } catch (e) {
          if (!(e && e.name === 'AbortError')) KH.views.plan.copyShopping(listText(), text);
        }
      } }, 'Share list'));
    }
    sec.append(row, text);
    return sec;
  }

  // ---- Add to plan, Undo ----------------------------------------------------------------------------------------------
  function confirmAdd(trigger) {
    const res = st.result;
    const entries = (res && res.apply && res.apply.entries) || [];
    if (!entries.length || st.busy) return;
    const days = new Set(entries.map((e) => e.date)).size;
    confirm.inline($('.sheet-foot', P.sheetEl), trigger, {
      message: `Add ${plural(entries.length, 'planned food', 'planned foods')} to ${plural(days, 'day', 'days')}, ${rangeText(res.start, res.end)}? Nothing is marked as eaten.`,
      confirmText: 'Add to plan',
      tone: 'primary',
      onConfirm: () => addPlan(res),
    });
  }
  async function sendChunk(chunk) {
    for (let attempt = 0; ; attempt++) {
      try { return await api.logBatch(chunk); } catch (err) { if (err.status !== 0 || attempt) throw err; } // one retry after a lost answer
    }
  }
  async function addPlan(res) {
    if (st.busy || st.result !== res) return false;
    // The client_ids are made once per plan: pressing Add to plan again after a failure adds only what is missing.
    if (!st.rows) st.rows = res.apply.entries.map((e) => ({ ...e, client_id: G.uuid() }));
    const rows = st.rows;
    const out = $('#g-days-out');
    st.busy = true;
    const ids = [];
    let sent = 0;
    try {
      for (let i = 0; i < rows.length; i += BATCH) {
        const chunk = rows.slice(i, i + BATCH);
        const answer = await sendChunk(chunk);
        for (const r of (answer && answer.results) || []) ids.push(r.id);
        sent += chunk.length;
      }
    } catch (err) {
      if (sent) { G.forgetAnswers(); KH.views.plan.afterLogChange(res.start); }
      if (!err.handled && out) {
        const why = err.detail || err.message;
        out.prepend(h('p', { class: 'form-error', role: 'alert' }, sent
          ? `Only ${sent} of ${rows.length} foods were added: ${why}. Press Add to plan again to add the rest. Nothing is added twice.`
          : `The plan was not saved: ${why}`));
      }
      return false;
    } finally {
      st.busy = false;
    }
    G.forgetAnswers();
    added(res, ids);
    toast(`Planned ${plural(ids.length, 'food', 'foods')} for ${rangeText(res.start, res.end)}. Tap “Eaten” as you have them.`, 'ok');
    KH.views.plan.afterLogChange(res.start);
    return true;
  }
  // After adding: what was added, with Undo (exactly these entries) until the range or the plan changes.
  function added(res, ids) {
    const out = $('#g-days-out');
    if (!out) return;
    st.result = null;
    st.rows = null;
    setButtons();
    const msg = h('p', {}, `Added ${plural(ids.length, 'planned food', 'planned foods')} to ${rangeText(res.start, res.end)}. Nothing is marked as eaten.`);
    const undo = h('button', { class: 'btn secondary', type: 'button', id: 'g-days-undo' }, 'Undo');
    const box = h('div', { class: 'g-days-added', role: 'status' }, msg, undo);
    undo.addEventListener('click', async () => {
      undo.disabled = true;
      try {
        const r = await api.clearPlanned({ start: res.start, end: res.end, ids });
        G.forgetAnswers();
        KH.views.plan.afterLogChange(res.start);
        toast(`Undone. ${plural(r.deleted, 'planned food', 'planned foods')} taken off.`, 'ok');
        run();
      } catch (err) {
        undo.disabled = false;
        if (!err.handled) box.append(h('p', { class: 'form-error', role: 'alert' }, `Not undone: ${err.detail || err.message}`));
      }
    });
    clear(out).append(box);
    live(msg.textContent);
    undo.focus();
  }

  // ---- Clear planned days -------------------------------------------------------------------------------------------
  function confirmClear(trigger) {
    if (!validRange()) return;
    const start = st.start, end = endOf();
    confirm.inline(trigger.parentElement, trigger, {
      message: `Take every planned food off ${rangeText(start, end)}? Eaten food and planned low treatments stay.`,
      confirmText: 'Clear planned days',
      onConfirm: async () => {
        const r = await api.clearPlanned({ start, end });
        G.forgetAnswers();
        KH.views.plan.afterLogChange(start);
        toast(r.deleted ? `Took ${plural(r.deleted, 'planned food', 'planned foods')} off ${rangeText(start, end)}.` : 'No planned food on these days.', 'ok');
        run();
        return true;
      },
    });
  }

  $('#btn-plan-days').addEventListener('click', (e) => {
    const start = state.planStart;
    const today = todayStr();
    // This week: today. Another week: its first day (the field can change it).
    openPlanDays({ start: !start || (today >= start && today <= addDays(start, 6)) ? today : start, trigger: e.currentTarget });
  });

  KH.views.planDays = { open: openPlanDays, replan };
})();
