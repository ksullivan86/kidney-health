/* Kidney Diet Log — helping someone on the Care team (design notes 25 §8 and 29; app/sharing.py, app/care_suggestions.py).

   The Plan tab shows "Planning for: Me / <person>" when the signed-in person may plan, log food or suggest meals for anyone. Choosing a
   person hides their own plan and shows the person's week, with a banner saying whose it is and "Back to my own plan". What shows
   follows the switches the person turned on for them (each checked again on the server on every request):

   * always: the week's days (projected totals as counts and the worst level) and a day's entries, with "Added by <name>";
   * may_plan: change the amount of a planned food and Remove it, Add food as planned, Plan several days (a preview, then "Add to
     <name>'s plan"), Clear planned days (asks first), and the person's shopping list (ticks kept on this device under a key with
     the share's id, Copy and Share);
   * may_log: Add food as eaten, Mark eaten on a planned food, and change or remove eaten food you added yourself;
   * may_use_saved_meals: the person's saved meals, each with Add to plan (may_plan) and Add as eaten (may_log), and Plan several
     days may use them;
   * may_suggest: Suggest a meal (foods, servings and a short note; the answer shows how it fits the person's day) and the
     suggestions you sent with the person's answer.
   A low treatment says only the person changes it: no helper changes, removes, moves or marks one eaten.

   Every request goes to /api/shared/{id}/… (KH.request). js/offline.js matches only the person's own routes (/api/log…), so a
   change for someone else is never queued, never replayed into the helper's own log, and their days are never saved as the
   helper's. Nothing here touches state.plan, state.date or the caches of the helper's own days. The choice of person is kept in
   memory only. A 404 "Not shared with you." reloads what the person allows: back to the helper's own plan when nothing is left. */
(() => {
  'use strict';
  const KH = window.KH;
  const { h, $, clear, request, state, toast, confirm } = KH;
  const { MEALS, MEAL_LABEL, fmtServings } = KH.rules;
  const { todayStr, addDays, fmtDateLong, fmtMonthDay, fmtRange, weekStartOf, parseDate, qs } = KH.util;
  const { SHOP_KEY } = KH.keys;

  const view = $('#view-plan');
  const bar = $('#care-for');
  const select = $('#care-for-select');
  const box = $('#care-plan');
  const CHECK_KEYS = ['potassium_mg', 'phosphorus_mg', 'sodium_mg'];
  const FIT_KEYS = ['potassium_mg', 'phosphorus_mg', 'sodium_mg', 'fluid_ml', 'carbs_g', 'protein_g'];
  const BATCH = 40; // POST …/log/batch takes 1 to 40 entries
  const NOTE_MAX = 280; // app/care_suggestions.py MAX_NOTE
  const ANSWER_TEXT = { open: 'waiting for an answer', accepted: 'added to their plan', declined: 'they said no thanks', expired: 'expired',
    ended: 'closed' };

  let helping = []; // the people this person may help (GET /api/shared: may_plan, may_log or may_suggest)
  let current = null; // { person, me, start, date } while helping someone
  let peopleRequest = 0;
  let viewRequest = 0;

  /** The helper routes of share `id`. Each is checked on the server against the share as it is now. */
  function routes(id) {
    const base = `/api/shared/${encodeURIComponent(id)}`;
    return {
      range: (start, end) => request('GET', `${base}/log/range?${qs({ start, end })}`),
      day: (date) => request('GET', `${base}/log?${qs({ date })}`),
      foods: (q) => request('GET', `${base}/foods?${qs({ q, limit: 8 })}`),
      add: (entry) => request('POST', `${base}/log`, entry),
      batch: (entries) => request('POST', `${base}/log/batch`, { entries }),
      change: (entryId, changes, version) => request('PUT', `${base}/log/${encodeURIComponent(entryId)}`, changes, version ? { ifMatch: version } : {}),
      remove: (entryId, version) => request('DELETE', `${base}/log/${encodeURIComponent(entryId)}`, undefined, version ? { ifMatch: version } : {}),
      clearPlanned: (start, end) => request('POST', `${base}/log/clear-planned`, { start, end }),
      planDays: (start, days, useSaved = false) => request('POST', `${base}/guidance/plan-days`, { start, days, use_saved_meals: !!useSaved }),
      shopping: (start, end) => request('GET', `${base}/plan/shopping?${qs({ start, end })}`),
      meals: () => request('GET', `${base}/meals`),
      applyMeal: (mealId, body) => request('POST', `${base}/meals/${encodeURIComponent(mealId)}/apply`, body),
      suggest: (body) => request('POST', `${base}/suggestions`, body),
      sent: () => request('GET', `${base}/suggestions`),
    };
  }

  // ---------------------------------------------------------------------------
  // Pure helpers (tests/test_care_team_ui.py runs them in Node)
  // ---------------------------------------------------------------------------
  function nameOf(p) { return (p && (p.name || p.username)) || ''; }
  /** May the signed-in person help `p` here: plan, log food or suggest meals. */
  function canHelp(p) { return !!(p && (p.may_plan || p.may_log || p.may_suggest)); }
  function bannerText(p) {
    if (p && p.may_log) return `You are helping ${nameOf(p)}. What you add goes into ${nameOf(p)}'s food log, not yours.`;
    if (p && p.may_plan) return `You are planning for ${nameOf(p)}. Changes go to ${nameOf(p)}'s plan, not yours.`;
    return `You are suggesting meals for ${nameOf(p)}. ${nameOf(p)} decides whether to add them.`;
  }
  /** The ticks of this person's list for one week, kept apart from the helper's own list (`kdl-shop:<week>`). */
  function shopKey(shareId, start) { return `${SHOP_KEY}:care:${shareId}:${start}`; }
  /** What a failed change says: offline, gone, or the server's reason. */
  function failText(err, p) {
    if (err && err.status === 404 && err.detail === 'Not shared with you.') return `You can no longer do that for ${nameOf(p)}.`;
    if (!err || !err.status) return `Not saved: helping ${nameOf(p)} needs a connection to your server.`;
    return err.detail || err.message || 'Not saved. Try again.';
  }
  /** The worst level of the day's projected potassium, phosphorus and sodium: 'over', 'caution', 'ok' or null (nothing planned). */
  function dayLevel(d) {
    const counts = (d && d.counts) || {};
    if (!(counts.eaten || counts.planned)) return null;
    const levels = CHECK_KEYS.map((k) => ((d.projected_status || {})[k] || {}).level).filter(Boolean);
    return levels.includes('over') ? 'over' : levels.includes('caution') ? 'caution' : 'ok';
  }
  function amountText(e) {
    return e.grams != null ? `${Math.round(Number(e.grams))} g` : fmtServings(Number(e.servings));
  }
  /** Who the helper is, as "Added by" names them (display name, else user name). */
  function myName() { const me = state.me || {}; return ((me.display_name || '').trim()) || me.username || ''; }
  /** The shopping list as text, as the helper's own list is (js/views/plan.js shoppingText), with the person's name. */
  function shoppingText(p, sh, checks) {
    const items = sh.items || [];
    const left = items.filter((it) => !checks.has(it.food_id));
    const lines = (left.length ? left : items).map((it) => `- ${it.food_name}: ${fmtServings(it.servings)}${it.serving_desc ? ` of ${it.serving_desc}` : ''}`);
    return [`Shopping list for ${nameOf(p)}, ${fmtRange(sh.start, sh.end)}`, '', ...lines].join('\n');
  }
  /** A suggestion's fit as lines: "Potassium: 1,250 of 2,000 mg for the day with this meal (Near limit)". "≥" when a food's value
      is not listed, "not listed" when none is; only nutrients with a target. */
  function fitLines(fit) {
    const status = (fit && fit.day_status) || {};
    const out = [];
    for (const key of FIT_KEYS) {
      const st = status[key];
      const nut = KH.rules.NUT[key];
      if (!st || !nut || st.target == null) continue;
      const value = st.value == null ? 'not listed' : `${st.unknown ? '≥ ' : ''}${KH.rules.fmtNum(st.value, key)}`;
      const level = st.level && st.level !== 'ok' && KH.ui && KH.ui.LEVEL_TEXT ? ` (${KH.ui.LEVEL_TEXT[st.level] || st.level})` : '';
      out.push(`${nut.label}: ${value} of ${KH.rules.fmtNum(st.target, key)} ${nut.unit} for the day with this meal${level}`);
    }
    return out;
  }
  /** One suggestion you sent, in words: "Nov 3, dinner: Apple, Rice · waiting for an answer". */
  function sentLine(sg) {
    const foods = (sg.items || []).map((it) => it.name).join(', ');
    return `${fmtMonthDay(sg.date)}, ${(MEAL_LABEL[sg.meal] || sg.meal).toLowerCase()}: ${foods} · ${ANSWER_TEXT[sg.answer] || sg.answer}`;
  }

  // ---------------------------------------------------------------------------
  // Who: the "Planning for" choice
  // ---------------------------------------------------------------------------
  function authOn() { return ((state.authStatus || {}).auth_mode || 'local') !== 'none'; }

  async function refreshPeople({ quiet = false } = {}) {
    const req = ++peopleRequest;
    let people = [];
    if (authOn() && KH.sharing && state.me) {
      try { people = ((await KH.sharing.people()).people || []).filter(canHelp); } catch (e) { people = []; } // off: 404
    }
    if (req !== peopleRequest) return;
    helping = people;
    drawChoice();
    if (!current) return;
    const fresh = helping.find((p) => p.id === current.person.id);
    if (!fresh) leave(`You can no longer help ${nameOf(current.person)} here.`);
    else if (['may_plan', 'may_log', 'may_use_saved_meals', 'may_suggest'].some((k) => !!fresh[k] !== !!current.person[k])) {
      current.person = fresh;
      if (!quiet) toast(`${nameOf(fresh)} changed what you may do.`);
      if (state.view === 'plan') draw();
    }
  }

  function drawChoice() {
    bar.hidden = !helping.length;
    clear(select).append(h('option', { value: '' }, 'Me'), ...helping.map((p) => h('option', { value: String(p.id) }, nameOf(p))));
    select.value = current ? String(current.person.id) : '';
  }
  select.addEventListener('change', () => {
    const p = helping.find((x) => String(x.id) === select.value);
    if (p) open(p); else leave();
  });

  /** Hide or show the helper's own plan: every part of the Plan tab except the choice and the person's plan. */
  function ownPlan(show) {
    for (const el of [...view.children]) {
      if (el === bar || el === box) continue;
      if (!show && !el.hidden) { el.hidden = true; el.dataset.careHid = '1'; }
      if (show && el.dataset.careHid) { el.hidden = false; delete el.dataset.careHid; }
    }
  }

  /** Start helping `person` (from the choice or Settings → Care team → Plan meals). */
  function open(person) {
    if (!person) return;
    if (!helping.some((p) => p.id === person.id)) helping = [...helping, person];
    const date = addDays(todayStr(), 1);
    current = { person, me: state.me && state.me.id, start: weekStartOf(todayStr(), KH.views.plan ? KH.views.plan.weekStartPref() : 'monday'), date };
    drawChoice();
    ownPlan(false);
    box.hidden = false;
    if (state.view !== 'plan') KH.router.show('plan'); else draw();
    refreshPeople({ quiet: true }).catch((e) => console.warn('Care team:', e)); // the switches as they are now
  }

  /** Back to the helper's own plan. */
  function leave(message) {
    const was = current;
    current = null;
    ++viewRequest;
    clear(box);
    box.hidden = true;
    ownPlan(true);
    drawChoice();
    if (message) toast(message);
    if (was && state.view === 'plan' && KH.views.plan) KH.views.plan.loadPlan();
    if (was && state.view === 'plan' && KH.suggestions) KH.suggestions.load();
  }

  /** Called by the Plan tab when it shows: true when it shows someone else's plan (the helper's own then does not load). */
  function onShow() {
    if (current && state.me && current.me !== state.me.id) { current = null; clear(box); box.hidden = true; ownPlan(true); }
    refreshPeople().catch((e) => console.warn('Care team:', e));
    if (!current) return false;
    draw();
    return true;
  }

  // ---------------------------------------------------------------------------
  // The person's week
  // ---------------------------------------------------------------------------
  function draw() {
    if (!current) return;
    const p = current.person;
    const req = ++viewRequest;
    const rt = routes(p.id);
    const back = h('button', { class: 'btn secondary', type: 'button', id: 'care-back' }, 'Back to my own plan');
    back.addEventListener('click', () => leave());
    const banner = h('div', { class: 'care-banner', role: 'status', id: 'care-banner' }, h('p', {}, bannerText(p)), back);
    const prev = h('button', { class: 'btn secondary', type: 'button', 'aria-label': 'Previous week' }, '‹');
    const next = h('button', { class: 'btn secondary', type: 'button', 'aria-label': 'Next week' }, '›');
    prev.addEventListener('click', () => { current.start = addDays(current.start, -7); draw(); });
    next.addEventListener('click', () => { current.start = addDays(current.start, 7); draw(); });
    const end = addDays(current.start, 6);
    const grid = h('div', { class: 'plan-grid care-grid', id: 'care-grid', role: 'list', 'aria-label': `${nameOf(p)}'s week` }, h('p', { class: 'muted' }, 'Loading…'));
    const dayBox = h('section', { class: 'card', id: 'care-day', 'aria-labelledby': 'care-day-h' });
    const parts = [banner,
      h('div', { class: 'date-nav week-nav' }, prev, h('div', { class: 'date-center' }, h('div', { class: 'date-label' }, `${nameOf(p)}'s week`),
        h('div', { class: 'muted small' }, fmtRange(current.start, end))), next),
      grid, dayBox];
    let mealsBox = null;
    let suggestBox = null;
    let shopBox = null;
    if (p.may_use_saved_meals && (p.may_plan || p.may_log)) parts.push(mealsBox = h('section', { class: 'card', id: 'care-meals', 'aria-labelledby': 'care-meals-h' }));
    if (p.may_suggest) parts.push(suggestBox = h('section', { class: 'card', id: 'care-suggest', 'aria-labelledby': 'care-suggest-h' }));
    if (p.may_plan) parts.push(toolsCard(p, rt), shopBox = h('section', { class: 'card', id: 'care-shopping', 'aria-labelledby': 'care-shopping-h' }));
    clear(box).append(...parts);
    loadWeek(req, rt, grid);
    drawDay(req, rt, dayBox);
    if (mealsBox) drawMeals(req, rt, mealsBox);
    if (suggestBox) drawSuggest(req, rt, suggestBox);
    if (shopBox) drawShopping(req, rt, shopBox);
  }

  async function loadWeek(req, rt, grid) {
    let res;
    try { res = await rt.range(current.start, addDays(current.start, 6)); } catch (err) { if (req === viewRequest) gone(err, () => clear(grid).append(h('p', { class: 'form-error' }, failText(err, current.person)))); return; }
    if (req !== viewRequest) return;
    const byDate = Object.fromEntries((res.days || []).map((d) => [d.date, d]));
    clear(grid);
    for (let i = 0; i < 7; i++) {
      const date = addDays(current.start, i);
      const d = byDate[date] || { date, counts: { eaten: 0, planned: 0 } };
      const counts = d.counts || { eaten: 0, planned: 0 };
      const level = dayLevel(d);
      const btn = h('button', { class: `plan-day-open care-day-btn${date === current.date ? ' selected' : ''}`, type: 'button',
        'aria-pressed': date === current.date ? 'true' : 'false',
        'aria-label': `${fmtDateLong(date)}: ${counts.eaten} eaten, ${counts.planned} planned${level && level !== 'ok' ? `, ${KH.ui.LEVEL_TEXT[level] || level}` : ''}` },
      h('span', { class: 'plan-wd' }, parseDate(date).toLocaleDateString('en-US', { weekday: 'short' })), ' ',
      h('span', { class: 'plan-dnum' }, String(parseDate(date).getDate())),
      h('span', { class: 'muted small' }, ` ${counts.planned} planned`),
      level && level !== 'ok' ? h('span', { class: `plan-chip level-${level}` }, ` ${KH.ui.LEVEL_TEXT[level] || level}`) : null);
      btn.addEventListener('click', () => { current.date = date; draw(); });
      grid.append(h('article', { class: 'plan-day', role: 'listitem' }, btn));
    }
  }

  /** A 404 "Not shared with you." means the share changed: reload what the person allows (back to the helper's own plan when
      nothing is left). Else `otherwise()`. */
  function gone(err, otherwise) {
    if (err && err.status === 404 && err.detail === 'Not shared with you.') {
      const p = current && current.person;
      toast(failText(err, p), 'error');
      refreshPeople().catch(() => leave());
      return;
    }
    if (otherwise) otherwise();
  }
  const saveFailed = (p) => (err) => gone(err, () => toast(failText(err, p), 'error'));

  async function drawDay(req, rt, dayBox) {
    const p = current.person;
    const date = current.date;
    clear(dayBox).append(h('h2', { class: 'card-title', id: 'care-day-h' }, `${nameOf(p)}: ${fmtDateLong(date)}`), h('p', { class: 'muted' }, 'Loading…'));
    let day;
    try { day = await rt.day(date); } catch (err) { if (req === viewRequest) gone(err, () => dayBox.append(h('p', { class: 'form-error' }, failText(err, p)))); return; }
    if (req !== viewRequest) return;
    clear(dayBox).append(h('h2', { class: 'card-title', id: 'care-day-h' }, `${nameOf(p)}: ${fmtDateLong(date)}`));
    const entries = day.entries || [];
    if (!entries.length) dayBox.append(h('p', { class: 'muted small' }, 'Nothing on this day yet.'));
    for (const m of MEALS) {
      const rows = entries.filter((e) => e.meal === m.key);
      if (!rows.length) continue;
      dayBox.append(h('h3', { class: 'settings-minor' }, m.label), h('ul', { class: 'list care-entries' }, rows.map((e) => entryRow(e, rt, p))));
    }
    if (p.may_plan || p.may_log) dayBox.append(addForm(rt, p, date));
  }

  function entryRow(e, rt, p) {
    const tags = [e.status === 'planned' ? 'planned' : 'eaten', e.purpose === 'hypo' ? 'to treat a low' : null,
      e.added_by ? `added by ${e.added_by}` : null].filter(Boolean).join(' · ');
    const main = h('div', { class: 'device-main' }, h('span', { class: 'row-title' }, e.food_name), h('span', { class: 'row-sub' }, `${amountText(e)} · ${tags}`));
    const li = h('li', { class: 'device' }, main);
    if (e.purpose === 'hypo') { li.append(h('span', { class: 'hint' }, `A low treatment: only ${nameOf(p)} changes it.`)); return li; }
    const planned = e.status === 'planned';
    const mineEaten = !planned && p.may_log && e.added_by && e.added_by === myName();
    const mayChange = planned ? p.may_plan : mineEaten;
    const actions = h('div', { class: 'token-actions' });
    if (mayChange) {
      const id = `care-amount-${e.id}`;
      const amount = h('input', { id, type: 'number', min: '0.25', max: '1000', step: '0.25', inputmode: 'decimal', class: 'care-amount', value: String(e.servings) });
      const save = h('button', { class: 'btn secondary', type: 'button' }, 'Save');
      const remove = h('button', { class: 'btn secondary', type: 'button', 'aria-label': `Remove ${e.food_name} from ${nameOf(p)}'s ${planned ? 'plan' : 'food log'}` }, 'Remove');
      actions.append(h('label', { class: 'sr-only', for: id }, `Servings of ${e.food_name}`), amount, save, remove);
      save.addEventListener('click', async () => {
        const n = Number(amount.value);
        if (!(n > 0 && n <= 1000)) { toast('Type a number of servings above 0.'); return; }
        save.disabled = true;
        try { await rt.change(e.id, { servings: n }, e.version); toast('Saved', 'ok'); draw(); } catch (err) { saveFailed(p)(err); } finally { save.disabled = false; }
      });
      remove.addEventListener('click', () => confirm.inline(actions, remove, {
        message: `Take ${e.food_name} off ${nameOf(p)}'s ${planned ? 'plan' : 'food log'}?`,
        confirmText: 'Remove',
        onConfirm: async () => {
          try { await rt.remove(e.id, e.version); toast('Removed', 'ok'); draw(); } catch (err) { saveFailed(p)(err); }
          return true;
        },
      }));
    }
    if (planned && p.may_log) {
      const eat = h('button', { class: 'btn secondary', type: 'button', 'aria-label': `Mark ${e.food_name} eaten for ${nameOf(p)}` }, 'Mark eaten');
      eat.addEventListener('click', async () => {
        eat.disabled = true;
        try { await rt.change(e.id, { status: 'eaten' }, e.version); toast(`Marked eaten for ${nameOf(p)}`, 'ok'); draw(); } catch (err) { saveFailed(p)(err); } finally { eat.disabled = false; }
      });
      actions.append(eat);
    }
    if (actions.children.length) li.append(actions);
    return li;
  }

  /** A search of the foods the person can use, for Add food and Suggest a meal. `onPick(food)` gets the chosen food. */
  function foodSearch(rt, p, prefix, onPick) {
    let searchReq = 0;
    const q = h('input', { id: `${prefix}-q`, type: 'search', autocomplete: 'off', placeholder: 'Search foods' });
    const results = h('ul', { class: 'list care-results', id: `${prefix}-results`, 'aria-label': 'Foods found' });
    const search = KH.util.debounce(async () => {
      const text = q.value.trim();
      const req = ++searchReq;
      if (!text) { clear(results); return; }
      let foods = [];
      try { foods = (await rt.foods(text)).foods || []; } catch (err) { if (req === searchReq) gone(err, () => toast(failText(err, p), 'error')); return; }
      if (req !== searchReq) return;
      clear(results).append(...foods.map((f) => {
        const b = h('button', { class: 'link-btn', type: 'button' }, `${f.name}${f.serving_desc ? ` (${f.serving_desc})` : ''}`);
        b.addEventListener('click', () => { ++searchReq; clear(results); onPick(f); });
        return h('li', {}, b);
      }));
      if (!foods.length) results.append(h('li', { class: 'muted small' }, 'No food found.'));
    }, 250);
    q.addEventListener('input', search);
    return { nodes: [h('label', { class: 'label', for: `${prefix}-q` }, `Foods ${nameOf(p)} can use`), q, results], q };
  }

  /** Add food: a search of the foods the person can use, then the meal, the servings and (when both are allowed) planned or eaten. */
  function addForm(rt, p, date) {
    let chosen = null;
    const meal = h('select', { id: 'care-add-meal' }, ...MEALS.map((m) => h('option', { value: m.key }, m.label)));
    const servings = h('input', { id: 'care-add-servings', type: 'number', min: '0.25', max: '1000', step: '0.25', inputmode: 'decimal', value: '1' });
    const picked = h('p', { class: 'hint', id: 'care-add-picked', role: 'status' }, 'No food chosen yet.');
    const statuses = [p.may_plan ? 'planned' : null, p.may_log ? 'eaten' : null].filter(Boolean);
    const status = h('select', { id: 'care-add-status' }, ...statuses.map((v) => h('option', { value: v }, v === 'planned' ? 'Planned' : 'Eaten')));
    const label = () => (status.value === 'eaten' ? `Add to ${nameOf(p)}'s food log as eaten` : `Add to ${nameOf(p)}'s plan`);
    const add = h('button', { class: 'btn primary', type: 'submit', id: 'care-add' }, label());
    status.addEventListener('change', () => { add.textContent = label(); });
    const search = foodSearch(rt, p, 'care-add', (f) => { chosen = f; picked.textContent = `Chosen: ${f.name}`; servings.focus(); });
    const form = h('form', { class: 'settings-form care-add', novalidate: true },
      h('h3', { class: 'settings-minor' }, 'Add food'), ...search.nodes, picked,
      h('label', { class: 'label', for: 'care-add-meal' }, 'Meal'), meal,
      h('label', { class: 'label', for: 'care-add-servings' }, 'Servings'), servings,
      statuses.length > 1 ? [h('label', { class: 'label', for: 'care-add-status' }, 'Planned or eaten'), status] : null,
      h('div', { class: 'settings-actions' }, add));
    form.addEventListener('submit', async (ev) => {
      ev.preventDefault();
      if (add.disabled) return;
      const n = Number(servings.value);
      if (!chosen) { toast('Choose a food first.'); search.q.focus(); return; }
      if (!(n > 0 && n <= 1000)) { toast('Type a number of servings above 0.'); return; }
      add.disabled = true;
      const eaten = status.value === 'eaten';
      try {
        await rt.add({ date, meal: meal.value, food_id: chosen.id, servings: n, status: eaten ? 'eaten' : 'planned' });
        toast(eaten ? `Added to ${nameOf(p)}'s food log` : `Added to ${nameOf(p)}'s plan`, 'ok');
        draw();
      } catch (err) { saveFailed(p)(err); } finally { add.disabled = false; }
    });
    return form;
  }

  // ---------------------------------------------------------------------------
  // The person's saved meals (may_use_saved_meals): listed and added, never changed
  // ---------------------------------------------------------------------------
  async function drawMeals(req, rt, mealsBox) {
    const p = current.person;
    const date = current.date;
    const title = h('h2', { class: 'card-title', id: 'care-meals-h' }, `${nameOf(p)}'s saved meals`);
    clear(mealsBox).append(title, h('p', { class: 'muted' }, 'Loading…'));
    let meals;
    try { meals = (await rt.meals()).meals || []; } catch (err) { if (req === viewRequest) gone(err, () => mealsBox.append(h('p', { class: 'form-error' }, failText(err, p)))); return; }
    if (req !== viewRequest) return;
    clear(mealsBox).append(title, h('p', { class: 'hint' }, `Adds to ${fmtDateLong(date)}. ${nameOf(p)}'s saved meals stay as they are.`));
    if (!meals.length) { mealsBox.append(h('p', { class: 'muted small' }, `${nameOf(p)} has no saved meals yet.`)); return; }
    const ul = h('ul', { class: 'list care-saved-meals', id: 'care-meals-list' });
    for (const m of meals) {
      const slot = h('select', { 'aria-label': `Meal for ${m.name}` }, ...MEALS.map((x) => h('option', { value: x.key }, x.label)));
      slot.value = m.meal_hint || 'lunch';
      const go = (status) => async (ev) => {
        const btn = ev.currentTarget;
        btn.disabled = true;
        try {
          const res = await rt.applyMeal(m.id, { date, meal: slot.value, status });
          const n = (res.entries || []).length;
          toast(`${m.name}: ${n} ${n === 1 ? 'food' : 'foods'} added to ${nameOf(p)}'s ${status === 'eaten' ? 'food log' : 'plan'}`, 'ok');
          draw();
        } catch (err) { saveFailed(p)(err); } finally { btn.disabled = false; }
      };
      const actions = h('div', { class: 'token-actions' }, slot);
      if (p.may_plan) { const b = h('button', { class: 'btn secondary', type: 'button' }, 'Add to plan'); b.addEventListener('click', go('planned')); actions.append(b); }
      if (p.may_log) { const b = h('button', { class: 'btn secondary', type: 'button' }, 'Add as eaten'); b.addEventListener('click', go('eaten')); actions.append(b); }
      const foods = (m.items || []).map((it) => it.food_name || it.name).filter(Boolean).join(', ');
      ul.append(h('li', { class: 'device' }, h('div', { class: 'device-main' }, h('span', { class: 'row-title' }, m.name),
        h('span', { class: 'row-sub' }, foods || `${(m.items || []).length} foods`)), actions));
    }
    mealsBox.append(ul);
  }

  // ---------------------------------------------------------------------------
  // Suggest a meal (may_suggest) and what you sent
  // ---------------------------------------------------------------------------
  async function drawSuggest(req, rt, suggestBox) {
    const p = current.person;
    const items = []; // { food, servings }
    const list = h('ul', { class: 'list care-suggest-items', id: 'care-suggest-items', 'aria-label': 'Foods in this suggestion' });
    const drawItems = () => {
      clear(list);
      if (!items.length) { list.append(h('li', { class: 'muted small' }, 'No food yet.')); return; }
      items.forEach((it, i) => {
        const id = `care-suggest-servings-${i}`;
        const n = h('input', { id, type: 'number', min: '0.25', max: '1000', step: '0.25', inputmode: 'decimal', class: 'care-amount', value: String(it.servings) });
        n.addEventListener('change', () => { it.servings = Number(n.value); });
        const drop = h('button', { class: 'btn secondary', type: 'button', 'aria-label': `Take ${it.food.name} out` }, 'Take out');
        drop.addEventListener('click', () => { items.splice(i, 1); drawItems(); });
        list.append(h('li', { class: 'device' }, h('div', { class: 'device-main' }, h('span', { class: 'row-title' }, it.food.name)),
          h('div', { class: 'token-actions' }, h('label', { class: 'sr-only', for: id }, `Servings of ${it.food.name}`), n, drop)));
      });
    };
    drawItems();
    const date = h('input', { id: 'care-suggest-date', type: 'date', value: current.date });
    const meal = h('select', { id: 'care-suggest-meal' }, ...MEALS.map((m) => h('option', { value: m.key }, m.label)));
    meal.value = 'dinner';
    const search = foodSearch(rt, p, 'care-suggest', (f) => {
      items.push({ food: f, servings: 1 }); drawItems(); search.q.value = ''; search.q.focus();
      toast(`${f.name} added to the suggestion`, 'ok');
    });
    const note = h('textarea', { id: 'care-suggest-note', rows: '3', maxlength: String(NOTE_MAX) });
    const count = h('span', { class: 'hint', id: 'care-suggest-count' }, `0 of ${NOTE_MAX} characters`);
    note.addEventListener('input', () => { count.textContent = `${note.value.length} of ${NOTE_MAX} characters`; });
    const result = h('div', { id: 'care-suggest-result', role: 'status' });
    const send = h('button', { class: 'btn primary', type: 'submit', id: 'care-suggest-send' }, `Send to ${nameOf(p)}`);
    const sentBox = h('div', { id: 'care-sent' });
    let fromMeal = null;
    if (p.may_use_saved_meals) {
      fromMeal = h('select', { id: 'care-suggest-from' }, h('option', { value: '' }, 'Choose a saved meal'));
      rt.meals().then((res) => {
        for (const m of res.meals || []) fromMeal.append(h('option', { value: String(m.id) }, m.name));
        fromMeal.addEventListener('change', () => {
          const m = (res.meals || []).find((x) => String(x.id) === fromMeal.value);
          if (!m) return;
          for (const it of m.items || []) items.push({ food: { id: it.food_id, name: it.food_name || it.name }, servings: Number(it.servings) || 1 });
          if (m.meal_hint) meal.value = m.meal_hint;
          drawItems();
          fromMeal.value = '';
        });
      }).catch(() => { fromMeal.disabled = true; });
    }
    const form = h('form', { class: 'settings-form care-suggest', novalidate: true },
      h('p', { class: 'hint' }, `${nameOf(p)} sees it on their Plan tab and decides whether to add it. Foods for treating a low are left out: that stays ${nameOf(p)}'s choice.`),
      h('label', { class: 'label', for: 'care-suggest-date' }, 'Day'), date,
      h('label', { class: 'label', for: 'care-suggest-meal' }, 'Meal'), meal,
      fromMeal ? [h('label', { class: 'label', for: 'care-suggest-from' }, `Start from ${nameOf(p)}'s saved meal`), fromMeal] : null,
      ...search.nodes, list,
      h('label', { class: 'label', for: 'care-suggest-note' }, 'A note (optional)'), note, count,
      h('div', { class: 'settings-actions' }, send), result);
    form.addEventListener('submit', async (ev) => {
      ev.preventDefault();
      if (send.disabled) return;
      clear(result);
      if (!items.length) { toast('Add at least one food.'); search.q.focus(); return; }
      if (items.some((it) => !(it.servings > 0 && it.servings <= 1000))) { toast('Type a number of servings above 0.'); return; }
      if (!date.value) { toast('Choose a day.'); return; }
      send.disabled = true;
      try {
        const sg = await rt.suggest({ date: date.value, meal: meal.value, items: items.map((it) => ({ food_id: it.food.id, servings: it.servings })),
          note: note.value.trim() || null });
        items.length = 0; drawItems(); note.value = ''; count.textContent = `0 of ${NOTE_MAX} characters`;
        toast(`Sent to ${nameOf(p)}`, 'ok');
        const lines = fitLines(sg.fit);
        result.append(h('p', { class: 'visit-body-sub' }, `How it fits ${nameOf(p)}'s day`),
          h('ul', { class: 'visit-body-list' }, lines.length ? lines.map((l) => h('li', {}, l)) : [h('li', {}, `${nameOf(p)} has no targets set.`)]));
        drawSent(rt, p, sentBox);
      } catch (err) {
        gone(err, () => result.append(h('p', { class: 'form-error' }, failText(err, p))));
      } finally { send.disabled = false; }
    });
    clear(suggestBox).append(h('h2', { class: 'card-title', id: 'care-suggest-h' }, `Suggest a meal for ${nameOf(p)}`), form,
      h('h3', { class: 'settings-minor', id: 'care-sent-h' }, 'Suggestions you sent'), sentBox);
    if (req === viewRequest) drawSent(rt, p, sentBox);
  }

  async function drawSent(rt, p, sentBox) {
    let res;
    try { res = await rt.sent(); } catch (err) { clear(sentBox).append(h('p', { class: 'form-error' }, failText(err, p))); return; }
    const all = res.suggestions || [];
    clear(sentBox).append(all.length
      ? h('ul', { class: 'list', id: 'care-sent-list', 'aria-labelledby': 'care-sent-h' }, all.map((sg) => h('li', {}, sentLine(sg))))
      : h('p', { class: 'muted small' }, 'None yet.'));
  }

  /** Plan several days (a preview first) and Clear planned days (may_plan). */
  function toolsCard(p, rt) {
    const start = h('input', { id: 'care-plan-start', type: 'date', value: current.date });
    const days = h('input', { id: 'care-plan-days', type: 'number', min: '1', max: '14', step: '1', value: '3', inputmode: 'numeric' });
    const useSaved = h('input', { type: 'checkbox', id: 'care-plan-saved' });
    const preview = h('div', { id: 'care-plan-preview' });
    const make = h('button', { class: 'btn secondary', type: 'button', id: 'care-plan-make' }, 'Make a plan');
    make.addEventListener('click', async () => {
      const n = Math.round(Number(days.value));
      if (!(n >= 1 && n <= 14) || !start.value) { toast('Choose a start day and 1 to 14 days.'); return; }
      make.disabled = true;
      clear(preview).append(h('p', { class: 'muted' }, 'Planning…'));
      try { showPlan(p, rt, await rt.planDays(start.value, n, p.may_use_saved_meals && useSaved.checked), preview); } catch (err) { gone(err, () => clear(preview).append(h('p', { class: 'form-error' }, failText(err, p)))); } finally { make.disabled = false; }
    });
    const from = h('input', { id: 'care-clear-start', type: 'date', value: current.date });
    const to = h('input', { id: 'care-clear-end', type: 'date', value: current.date });
    const clearBtn = h('button', { class: 'btn secondary', type: 'button', id: 'care-clear' }, 'Clear planned days');
    const clearRow = h('div', { class: 'settings-actions' }, clearBtn);
    clearBtn.addEventListener('click', () => {
      if (!from.value || !to.value || to.value < from.value) { toast('Choose the first and last day.'); return; }
      confirm.inline(clearRow, clearBtn, {
        message: `Take the planned food off ${nameOf(p)}'s days from ${fmtMonthDay(from.value)} to ${fmtMonthDay(to.value)}? Eaten food and planned low treatments stay.`,
        confirmText: 'Clear',
        onConfirm: async () => {
          try { const r = await rt.clearPlanned(from.value, to.value); toast(`${r.deleted} planned ${r.deleted === 1 ? 'food' : 'foods'} taken off`, 'ok'); draw(); } catch (err) { saveFailed(p)(err); }
          return true;
        },
      });
    });
    return h('section', { class: 'card', id: 'care-tools', 'aria-labelledby': 'care-tools-h' },
      h('h2', { class: 'card-title', id: 'care-tools-h' }, `Plan several days for ${nameOf(p)}`),
      h('p', { class: 'hint' }, p.may_use_saved_meals ? `The plan follows ${nameOf(p)}'s targets.`
        : `The plan follows ${nameOf(p)}'s targets. ${nameOf(p)}'s saved meals are not used.`),
      h('label', { class: 'label', for: 'care-plan-start' }, 'First day'), start,
      h('label', { class: 'label', for: 'care-plan-days' }, 'Days'), days,
      p.may_use_saved_meals ? h('label', { class: 'check', for: 'care-plan-saved' }, useSaved, ` Use ${nameOf(p)}'s saved meals`) : null,
      h('div', { class: 'settings-actions' }, make), preview,
      h('h3', { class: 'settings-minor' }, 'Clear planned days'),
      h('label', { class: 'label', for: 'care-clear-start' }, 'From'), from,
      h('label', { class: 'label', for: 'care-clear-end' }, 'To'), to, clearRow);
  }

  function showPlan(p, rt, res, preview) {
    clear(preview);
    if (!res || res.status !== 'ok') { preview.append(h('p', { class: 'hint' }, (res && res.message) || 'No plan could be made.')); return; }
    for (const d of res.days || []) {
      const lines = [];
      for (const m of d.meals || []) {
        if (!(m.items || []).length) continue;
        lines.push(h('li', {}, `${MEAL_LABEL[m.meal] || m.meal}: ${m.items.map((it) => `${it.name}, ${it.portion_text}`).join('; ')}`));
      }
      preview.append(h('p', { class: 'visit-body-sub' }, fmtDateLong(d.date)), h('ul', { class: 'visit-body-list' }, lines.length ? lines : [h('li', {}, 'Nothing planned.')]));
    }
    const entries = (res.apply && res.apply.entries) || [];
    if (!entries.length) return;
    const apply = h('button', { class: 'btn primary', type: 'button', id: 'care-plan-apply' }, `Add to ${nameOf(p)}'s plan`);
    apply.addEventListener('click', async () => {
      apply.disabled = true;
      let added = 0;
      try {
        for (let i = 0; i < entries.length; i += BATCH) { await rt.batch(entries.slice(i, i + BATCH)); added += Math.min(BATCH, entries.length - i); }
        toast(`${added} planned ${added === 1 ? 'food' : 'foods'} added to ${nameOf(p)}'s plan`, 'ok');
        draw();
      } catch (err) {
        gone(err, () => toast(added ? `${added} of ${entries.length} were added. ${failText(err, p)}` : failText(err, p), 'error'));
      } finally { apply.disabled = false; }
    });
    preview.append(h('div', { class: 'settings-actions' }, apply));
  }

  // ---------------------------------------------------------------------------
  // The person's shopping list (ticks only on this device)
  // ---------------------------------------------------------------------------
  function loadChecks(key) {
    try { const v = JSON.parse(localStorage.getItem(key) || '[]'); return new Set(Array.isArray(v) ? v : []); } catch (e) { return new Set(); }
  }
  function saveChecks(key, set) {
    try { if (set.size) localStorage.setItem(key, JSON.stringify([...set])); else localStorage.removeItem(key); } catch (e) { /* storage unavailable */ }
  }

  async function drawShopping(req, rt, shopBox) {
    const p = current.person;
    const start = current.start;
    const end = addDays(start, 6);
    clear(shopBox).append(h('h2', { class: 'card-title', id: 'care-shopping-h' }, `${nameOf(p)}'s shopping list`), h('p', { class: 'muted' }, 'Loading…'));
    let sh;
    try { sh = await rt.shopping(start, end); } catch (err) { if (req === viewRequest) gone(err, () => shopBox.append(h('p', { class: 'form-error' }, failText(err, p)))); return; }
    if (req !== viewRequest) return;
    const list = { start, end, items: sh.items || [] };
    const key = shopKey(p.id, start);
    const checks = loadChecks(key);
    clear(shopBox).append(h('h2', { class: 'card-title', id: 'care-shopping-h' }, `${nameOf(p)}'s shopping list`),
      h('p', { class: 'muted small' }, fmtRange(start, end)));
    if (!list.items.length) { shopBox.append(h('p', { class: 'muted small' }, 'Nothing planned this week yet.')); return; }
    const ul = h('ul', { class: 'list shopping-list', id: 'care-shopping-list' });
    for (const it of list.items) {
      const id = `care-shop-${p.id}-${start}-${it.food_id}`;
      const cb = h('input', { type: 'checkbox', id, checked: checks.has(it.food_id) || null });
      cb.addEventListener('change', () => { if (cb.checked) checks.add(it.food_id); else checks.delete(it.food_id); saveChecks(key, checks); });
      ul.append(h('li', { class: 'shop-item' }, h('label', { class: 'check shop-check', for: id }, cb,
        h('span', { class: 'check-text' }, h('span', { class: 'shop-name' }, it.food_name),
          h('span', { class: 'hint' }, `${fmtServings(it.servings)}${it.serving_desc ? ` of ${it.serving_desc}` : ''} · ${it.days} ${it.days === 1 ? 'day' : 'days'}`)))));
    }
    const text = h('textarea', { id: 'care-shopping-text', class: 'shopping-text', readonly: true, rows: '6', hidden: true, 'aria-label': 'Shopping list text' });
    const copy = h('button', { class: 'btn secondary', type: 'button', id: 'care-shopping-copy' }, 'Copy list');
    copy.addEventListener('click', () => KH.views.plan.copyShopping(shoppingText(p, list, checks), text));
    const share = h('button', { class: 'btn secondary', type: 'button', id: 'care-shopping-share', hidden: typeof navigator.share !== 'function' || null }, 'Share list');
    share.addEventListener('click', async () => {
      const t = shoppingText(p, list, checks);
      try { await navigator.share({ title: `Shopping list for ${nameOf(p)}`, text: t }); } catch (e) { if (!(e && e.name === 'AbortError')) KH.views.plan.copyShopping(t, text); }
    });
    shopBox.append(ul, h('div', { class: 'settings-actions' }, copy, share), text);
  }

  KH.carePlan = { open, leave, onShow, refreshPeople, routes, nameOf, canHelp, bannerText, shopKey, failText, dayLevel, shoppingText, fitLines,
    sentLine, current: () => (current ? current.person : null) };
})();
