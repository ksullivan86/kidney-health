/* Kidney Diet Log — "Plan several days" (design note 23): plan up to 60 days at once from the Plan tab.

   Fills the guidance sheet (#sheet-guidance, kind "plan-days") with the range (first day, number of days, quick choices), the
   meals to plan, the snack, the meals that may repeat, a preview of each day (POST /api/guidance/plan-days, which computes
   only), and the range's shopping list. Nothing is written until the person confirms "Add to plan": the foods then go in as
   planned food through POST /api/log/batch, at most 40 a request, each with its own client_id, so a retry after a lost answer
   adds nothing twice. Undo takes off exactly the foods that were added; "Clear planned days" is a reset: it takes off every
   planned food of the range (POST /api/log/clear-planned). Eaten food is never touched and a planned low treatment stays. A
   plan never holds a low treatment and nothing here delays treating one. Answers are kept in memory only
   (KH.guidance.plan.remembered); the snack and repeat choices are remembered on the server (the person's guidance settings),
   and "OK to repeat" marks go through /api/guidance/repeat-ok (design note 23 §12). */
(() => {
  'use strict';
  const KH = window.KH;
  const { h, $, $$, clear, state, toast, request, sheets, confirm } = KH;
  const { MEALS, MEAL_LABEL, fmtServings, fmtNum } = KH.rules;
  const { todayStr, addDays, fmtDateShort, weekStartOf, daysBetween, debounce } = KH.util;
  const G = KH.guidance;
  const P = G.plan;

  const MAX_DAYS = 60; // the server's PLAN_DAYS_MAX by default (app/guidance/rules.py, design note 23 §12.1); each answer gives the cap
  const BATCH = 40; // POST /api/log/batch takes at most 40 entries
  const QUICK = [7, 14, 30, 60]; // the quick choices after "Rest of this week"; one above the cap is hidden
  // Today's meals whose time has passed (note 23 §12.6). The profile has no meal times, so these are the usual ones: times, not targets.
  const MEAL_TIMES = { breakfast: '08:00', lunch: '12:30', snack: '15:30', dinner: '18:30' };
  const PAST_ASK_MINUTES = 120; // more than 2 hours past: not planned; up to 2 hours past: asked
  const MAIN = ['breakfast', 'lunch', 'dinner'];
  const api = {
    planDays: (body) => request('POST', '/api/guidance/plan-days', body),
    logBatch: (entries) => request('POST', '/api/log/batch', { entries }),
    clearPlanned: (body) => request('POST', '/api/log/clear-planned', body),
    repeatOk: () => request('GET', '/api/guidance/repeat-ok'),
    setRepeatOk: (kind, id, on) => request(on ? 'PUT' : 'DELETE', `/api/guidance/repeat-ok/${kind}/${encodeURIComponent(id)}`),
  };
  const st = { start: null, days: 7, meals: [], variant: 0, options: { use_saved_meals: true, use_usual: true, use_starters: true },
    snack: false, repeatMeals: [], past: {}, maxDays: MAX_DAYS, ok: { foods: new Map(), meals: new Map() },
    result: null, rows: null, request: 0, busy: false };

  const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;
  function rangeText(start, end) { return start === end ? fmtDateShort(start) : `${fmtDateShort(start)} to ${fmtDateShort(end)}`; }
  function endOf() { return addDays(st.start, st.days - 1); }
  function validRange() { return /^\d{4}-\d{2}-\d{2}$/.test(st.start || '') && Number.isInteger(st.days) && st.days >= 1 && st.days <= st.maxDays; }
  function restOfWeek() {
    const pref = KH.views.plan && KH.views.plan.weekStartPref ? KH.views.plan.weekStartPref() : 'monday';
    return daysBetween(st.start, addDays(weekStartOf(st.start, pref), 6)) + 1;
  }
  const mealWord = (m, first) => (first ? MEAL_LABEL[m] : MEAL_LABEL[m].toLowerCase());

  // ---- Today's meals that are already past (the browser's clock and the person's day) ----------------------------------
  // { skip: meals more than 2 hours past, ask: meals up to 2 hours past }, only when the first day is today.
  function pastMeals(now = new Date()) {
    const out = { skip: [], ask: [] };
    if (st.start !== todayStr()) return out;
    const minutes = now.getHours() * 60 + now.getMinutes();
    for (const m of ['breakfast', 'lunch', 'snack', 'dinner']) {
      const [hh, mm] = MEAL_TIMES[m].split(':').map(Number);
      const late = minutes - (hh * 60 + mm);
      if (late > PAST_ASK_MINUTES) out.skip.push(m);
      else if (late > 0) out.ask.push(m);
    }
    return out;
  }
  function skipFirstDay() {
    const { skip, ask } = pastMeals();
    return [...skip, ...ask.filter((m) => st.past[m] === 'skip')];
  }
  function pastNote() {
    const el = $('#g-days-past');
    if (!el) return;
    const { skip } = pastMeals();
    const shown = skip.filter((m) => m !== 'snack' || st.snack);
    clear(el);
    el.hidden = !shown.length;
    if (!shown.length) return;
    const words = P.joinWords(shown.map((m, i) => mealWord(m, i === 0)));
    el.append(`${words} ${shown.length === 1 ? 'is' : 'are'} not planned for today: ${shown.length === 1 ? 'its' : 'their'} time has passed. `,
      h('button', { class: 'link-btn', type: 'button', id: 'g-days-tomorrow-2', onclick: () => startTomorrow() }, 'Start tomorrow'));
  }
  // A meal of today up to 2 hours past that the plan holds: ask once, in the sheet ("Lunch was at 12:30. Plan it anyway?").
  function askAboutPast(res) {
    const first = res && res.days && res.days[0];
    if (!first || first.date !== todayStr()) return;
    const pending = pastMeals().ask.filter((m) => !(m in st.past) && first.meals.some((x) => x.meal === m));
    if (!pending.length) return;
    const add = $('#g-days-add');
    if (add) add.disabled = true; // answered first: the plan is added as the person chose
    const said = pending.map((m, i) => `${mealWord(m, i === 0)} was at ${MEAL_TIMES[m]}`);
    const one = pending.length === 1;
    confirm.inline($('#g-days-ask'), $('#g-days-start'), {
      message: `${P.joinWords(said)}. Plan ${one ? 'it' : 'them'} anyway?`,
      confirmText: one ? 'Plan it' : 'Plan them',
      cancelText: 'Skip',
      tone: 'primary',
      onConfirm: () => {
        for (const m of pending) st.past[m] = 'plan';
        const b = $('#g-days-add');
        if (b && st.result === res && (res.apply.entries || []).length) b.disabled = false;
        return true;
      },
      onCancel: () => { for (const m of pending) st.past[m] = 'skip'; run(); },
    });
  }
  function startTomorrow() {
    const input = $('#g-days-start');
    st.start = addDays(todayStr(), 1);
    if (input) input.value = st.start;
    st.past = {};
    changed();
  }

  // ---- Remembered choices and "OK to repeat" ----------------------------------------------------------------------
  async function remember(patch) {
    try { await G.savePrefs(patch); } catch (err) {
      if (!err.handled) live(`Not remembered for next time: ${err.detail || err.message}`);
    }
  }
  function applyMarks(list) {
    st.ok.foods = new Map(((list && list.foods) || []).map((f) => [f.food_id, f.name]));
    st.ok.meals = new Map(((list && list.meals) || []).map((m) => [m.meal_id, m.name]));
    renderMarks();
  }
  async function loadMarks() {
    try { applyMarks(await api.repeatOk()); } catch (err) { /* offline: the marks stay as the server has them */ }
  }
  async function setMark(kind, id, name, button) {
    const on = button.getAttribute('aria-pressed') !== 'true';
    button.disabled = true;
    try {
      applyMarks(await api.setRepeatOk(kind, id, on));
      G.forgetAnswers();
      toast(on ? `${name} is OK to repeat: a plan may have it every day.` : `${name} is no longer marked OK to repeat.`, 'ok');
      await replan();
    } catch (err) {
      if (!err.handled) toast(err.detail || err.message, 'error');
    } finally {
      if (document.contains(button)) button.disabled = false;
    }
  }
  const repeat = {
    on: (foodId) => st.ok.foods.has(foodId),
    mealOn: (mealId) => st.ok.meals.has(mealId),
    toggle: (item, button) => setMark('foods', item.food_id, item.name, button),
    toggleMeal: (m, button) => setMark('meals', m.template_id, m.name, button),
  };
  function renderMarks() {
    const box = $('#g-days-ok-list');
    if (!box) return;
    const rows = [...[...st.ok.meals].map(([id, name]) => ['meals', id, name]), ...[...st.ok.foods].map(([id, name]) => ['foods', id, name])];
    clear(box);
    if (!rows.length) {
      box.append(h('p', { class: 'hint' }, 'None yet. Use “OK to repeat” on a saved meal, or in a food’s “⋯” menu, in the plan below.'));
      return;
    }
    box.append(h('ul', { class: 'compact-items g-days-ok-items', role: 'list' }, rows.map(([kind, id, name]) => h('li', {},
      h('span', { class: 'ci-name' }, name, h('span', { class: 'muted small' }, kind === 'meals' ? ' · saved meal' : ' · food')),
      h('button', { class: 'link-btn', type: 'button', 'aria-label': `Remove ${name} from OK to repeat`, 'aria-pressed': 'true',
        onclick: (e) => setMark(kind, id, name, e.currentTarget) }, 'Remove')))));
  }

  // ---- The sheet ----------------------------------------------------------------------------------------------------
  async function openPlanDays({ start = null, trigger = null } = {}) {
    await G.loadPrefs();
    const remembered = G.prefValue('plan_repeat_meals', []);
    Object.assign(st, { start: start || todayStr(), days: 7, meals: [], variant: 0, result: null, rows: null, past: {},
      snack: G.prefValue('plan_snack', false) === true, repeatMeals: Array.isArray(remembered) ? [...remembered] : [] });
    const { body, foot } = P.fillSheet('plan-days', 'Plan these days',
      'Days or weeks from your own foods. Each day is planned against what is left of your targets.');
    const startInput = h('input', { id: 'g-days-start', type: 'date', value: st.start, required: true });
    const countInput = h('input', { id: 'g-days-count', type: 'number', min: '1', max: String(st.maxDays), step: '1', inputmode: 'numeric',
      value: String(st.days), required: true, 'aria-describedby': 'g-days-count-hint' });
    const setCount = (n) => { st.days = n; countInput.value = String(n); changed(); };
    const quick = h('div', { class: 'g-days-quick', role: 'group', 'aria-label': 'Quick choices' },
      h('button', { class: 'btn secondary', type: 'button', id: 'g-days-week', onclick: () => setCount(restOfWeek()) }, 'Rest of this week'),
      QUICK.map((n) => h('button', { class: 'btn secondary', type: 'button', id: `g-days-${n}`, 'data-days': String(n), hidden: n > st.maxDays,
        onclick: () => setCount(n) }, `${n} days`)));
    const mealsBox = h('div', { class: 'checks four g-plan-meals' });
    for (const m of MEALS.filter((x) => MAIN.includes(x.key))) {
      const id = `g-days-meal-${m.key}`;
      const box = h('input', { type: 'checkbox', id, value: m.key });
      box.addEventListener('change', () => { st.meals = $$('input:checked', mealsBox).map((x) => x.value); changed(); });
      mealsBox.append(h('label', { class: 'check', for: id }, box, h('span', { class: 'check-text' }, m.label)));
    }
    const snackBox = h('input', { type: 'checkbox', id: 'g-days-snack', 'aria-describedby': 'g-days-snack-hint' });
    snackBox.checked = st.snack;
    snackBox.addEventListener('change', () => { st.snack = snackBox.checked; remember({ plan_snack: st.snack }); changed(); });
    const repeatBox = h('div', { class: 'checks four g-days-repeat-meals' });
    for (const m of MEALS) {
      const id = `g-days-repeat-${m.key}`;
      const box = h('input', { type: 'checkbox', id, value: m.key });
      box.checked = st.repeatMeals.includes(m.key);
      box.addEventListener('change', () => {
        st.repeatMeals = $$('input:checked', repeatBox).map((x) => x.value);
        remember({ plan_repeat_meals: st.repeatMeals });
        changed();
      });
      repeatBox.append(h('label', { class: 'check', for: id }, box, h('span', { class: 'check-text' }, m.label)));
    }
    const opts = h('div', { class: 'g-plan-options' });
    for (const [key, label] of [['use_saved_meals', 'Use my saved meals'], ['use_usual', 'Use meals I often have'], ['use_starters', 'Use starter meals']]) {
      const id = `g-days-${key}`;
      const box = h('input', { type: 'checkbox', id });
      box.checked = st.options[key];
      box.addEventListener('change', () => { st.options[key] = box.checked; changed(); });
      opts.append(h('label', { class: 'check', for: id }, box, h('span', { class: 'check-text' }, label)));
    }
    startInput.addEventListener('change', () => {
      if (/^\d{4}-\d{2}-\d{2}$/.test(startInput.value)) { st.start = startInput.value; st.past = {}; changed(); }
    });
    const typed = debounce(() => changed(), 400);
    countInput.addEventListener('input', () => { st.days = Number(countInput.value); typed(); });
    const clearRow = h('p', { class: 'g-days-clear' },
      h('button', { class: 'link-btn', type: 'button', id: 'g-days-clear', onclick: (e) => confirmClear(e.currentTarget) }, 'Clear planned days…'));
    const out = h('div', { class: 'g-plan-out', id: 'g-days-out' });
    body.append(
      h('div', { class: 'g-days-range' },
        h('div', { class: 'field' }, h('label', { for: 'g-days-start' }, 'First day'), startInput,
          h('button', { class: 'link-btn', type: 'button', id: 'g-days-tomorrow', onclick: () => startTomorrow() }, 'Start tomorrow')),
        h('div', { class: 'field' }, h('label', { for: 'g-days-count' }, 'Days'), countInput)),
      h('span', { class: 'hint', id: 'g-days-count-hint' }, `1 to ${st.maxDays} days.`),
      quick,
      h('fieldset', { class: 'field' }, h('legend', {}, 'Meals to plan'), mealsBox,
        h('span', { class: 'hint' }, 'With none ticked, every meal with nothing logged yet. A ticked meal is planned on every day.'),
        h('label', { class: 'check', for: 'g-days-snack' }, snackBox, h('span', { class: 'check-text' }, 'Plan a snack too')),
        h('span', { class: 'hint', id: 'g-days-snack-hint' }, 'Off at first. Your choice is remembered.')),
      h('fieldset', { class: 'field' }, h('legend', {}, 'Meals that may repeat'), repeatBox,
        h('span', { class: 'hint' }, 'A ticked meal may be the same on following days. Other meals change for 2 days. Your choice is remembered.'),
        h('details', { class: 'g-disclosure', id: 'g-days-ok' }, h('summary', {}, 'Foods and meals OK to repeat'),
          h('div', { id: 'g-days-ok-list' }))),
      h('details', { class: 'g-disclosure' }, h('summary', {}, 'Where ideas come from'), opts,
        h('span', { class: 'hint' }, 'All three come from your own foods and the app’s rules. Nothing is sent to AI.')),
      clearRow,
      h('p', { class: 'hint g-days-past', id: 'g-days-past', hidden: true }),
      h('div', { class: 'g-days-ask', id: 'g-days-ask' }),
      h('p', { class: 'sr-only', role: 'status', id: 'g-days-status' }),
      out);
    renderMarks();
    const another = h('button', { class: 'btn secondary', type: 'button', id: 'g-days-another', disabled: true,
      onclick: () => { st.variant = (st.variant + 1) % (P.MAX_VARIANT + 1); run(); } }, 'Show another');
    const add = h('button', { class: 'btn primary', type: 'button', id: 'g-days-add', disabled: true, onclick: (e) => confirmAdd(e.currentTarget) }, 'Add to plan');
    foot.append(another, h('span', { class: 'spacer' }), add);
    sheets.open(P.sheetEl, trigger, startInput);
    loadMarks();
    run();
  }
  function changed() { st.variant = 0; run(); }
  function live(text) { const el = $('#g-days-status'); if (el) el.textContent = text; }
  function setButtons({ add = false, another = false } = {}) {
    const a = $('#g-days-add'), b = $('#g-days-another');
    if (a) a.disabled = !add;
    if (b) b.disabled = !another;
  }
  // The server's caps (PLAN_DAYS_MAX): the field, the hint and the quick choices follow the last answer.
  function applyLimits(limits) {
    if (!limits || !Number.isInteger(limits.days_max) || limits.days_max === st.maxDays) return;
    st.maxDays = limits.days_max;
    const input = $('#g-days-count');
    if (input) input.max = String(st.maxDays);
    const hint = $('#g-days-count-hint');
    if (hint) hint.textContent = `1 to ${st.maxDays} days.`;
    for (const b of $$('[data-days]', P.sheetEl)) b.hidden = Number(b.dataset.days) > st.maxDays;
  }

  async function run() {
    const out = $('#g-days-out');
    if (!out) return;
    const reqId = ++st.request;
    st.result = null;
    st.rows = null;
    setButtons();
    const ask = $('#g-days-ask');
    if (ask && ask._confirmRow) ask._confirmRow._close(false);
    $('#g-days-clear').disabled = !validRange();
    pastNote();
    if (!validRange()) {
      clear(out).append(h('p', { class: 'empty-state' }, `Choose a first day and 1 to ${st.maxDays} days.`));
      return;
    }
    const body = { start: st.start, days: st.days, variant: st.variant, ...st.options, snack: st.snack, repeat_meals: st.repeatMeals,
      skip_first_day: skipFirstDay() };
    if (st.meals.length) body.meals = st.meals;
    out.setAttribute('aria-busy', 'true');
    clear(out).append(P.loadingNote(`Planning ${plural(st.days, 'day', 'days')}…`));
    try {
      const { data, at } = await P.remembered(`plan-days:${JSON.stringify(body)}`, () => api.planDays(body));
      if (reqId !== st.request) return;
      P.noteAnswer(data);
      st.result = data;
      applyLimits(data && data.limits);
      render(out, data, at);
      if (!at) askAboutPast(data);
    } catch (err) {
      if (reqId !== st.request) return;
      if (!err.handled) clear(out).append(P.failure(err));
      live(err.offline ? P.NEEDS_CONNECTION : 'The plan could not be made.');
    } finally {
      if (reqId === st.request) out.removeAttribute('aria-busy');
    }
  }
  // "Not for me" or "OK to repeat" on a planned food: plan the same days again (the menu is in js/views/guidance.js).
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
      if (!d.meals.length) box.append(h('p', { class: 'empty-state' }, 'Every meal of this day already has food, or its time has passed. Tick the meals you want planned anyway.'));
      for (const m of d.meals) {
        const sec = P.planMeal(m, false, { repeat });
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
  // One line a food, however many days: 60 days list about as many lines as 14.
  function shopping(res) {
    const items = (res.shopping && res.shopping.items) || [];
    const sec = h('section', { class: 'g-days-shop', 'aria-labelledby': 'g-days-shop-h' },
      h('h3', { class: 'g-group-title', id: 'g-days-shop-h' }, 'Shopping list for these days'));
    if (!items.length) { sec.append(h('p', { class: 'hint' }, 'This plan adds no food.')); return sec; }
    sec.append(h('p', { class: 'hint' }, `${plural(items.length, 'food', 'foods')}, each once with the total for ${rangeText(res.start, res.end)}.`));
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
        if (rows.length > BATCH) live(`Added ${sent} of ${rows.length} foods…`);
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
    const msg = h('p', {}, `Added ${plural(ids.length, 'planned food', 'planned foods')} to ${rangeText(res.start, res.end)}. Nothing is marked as eaten. `
      + 'Undo takes off only what this plan added.');
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

  // ---- Clear planned days: a reset of the range ---------------------------------------------------------------------
  function confirmClear(trigger) {
    if (!validRange()) return;
    const start = st.start, end = endOf();
    confirm.inline(trigger.parentElement, trigger, {
      message: `Take every planned food off ${rangeText(start, end)}? This is a reset: it also takes off food you planned yourself, not only what a plan added. Eaten food and planned low treatments stay.`,
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

  KH.views.planDays = { open: openPlanDays, replan, pastMeals, MEAL_TIMES };
})();
