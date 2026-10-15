/* Kidney Diet Log — "Add this menu day to my plan" (v0.4; ROADMAP, note 08 §4.10).

   A menu day in the handbook has a plain link to the app, "#plan-menu?items=…" (js/engine/menu_link.js says what is in
   it and reads it strictly: built-in food numbers and servings only). Opening it shows a confirmation sheet and never
   writes anything on its own:

   * the foods are looked up in the app's own list of built-in foods (GET /api/foods/builtin); anything that is not a
     built-in food, or not understood, is listed as "Not added" with the reason;
   * every number shown is the app's own: each food's nutrients and the day's projected totals from GET /api/log
     (what is already planned on that date), with the same near / over lines as the other planning sheets;
   * the person picks the date (tomorrow, or the next of the following 14 days with nothing logged or planned) and can
     untick foods;
   * only "Add to plan" posts the ticked foods as planned entries through POST /api/log/batch (CSRF header as every
     write; one client_id per food, made when the sheet opens, so a second press or a retry after a lost answer adds
     nothing twice).

   A food that treats a low is planned like any other and gets no warning of its own.

   Signed out: the link is kept in memory only (never stored), the sign-in screens run, and the sheet opens once the
   person is in (js/main.js start(), js/views/auth.js enterApp). A page reload or an outside sign-in page forgets it:
   open the link again. All text goes in with textContent (h() children), never as HTML. */
(() => {
  'use strict';
  const KH = window.KH;
  const { h, $, clear, state, toast, router, sheets } = KH;
  const M = KH.menuLink;
  const { NUT, MEALS, MEAL_LABEL, NUTRIENT_KEYS, fmtNum, fmtServings, pct } = KH.rules;
  const { KEY_NUMBERS, ROW_NUMBERS, PLAN_CHIPS, LEVEL_TEXT, ratingIcon, scaledNutrients, impactOn, unknownOf, atLeast } = KH.ui;
  const { todayStr, addDays, fmtDateLong, weekStartOf } = KH.util;

  const dlg = $('#sheet-menuplan');
  if (!dlg) return;
  sheets.setup(dlg);
  const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;
  const LOOK_AHEAD_DAYS = 14;

  // What the open sheet shows: rows = [{ meal, fdc_id, servings, food, on, client_id }].
  const S = { rows: [], date: '', day: null, dayFor: null, dayReq: 0, busy: false, token: 0 };
  let pending = null; // the link text waiting for a signed-in person (memory only)

  const uid = () => {
    const c = window.crypto;
    if (c && typeof c.randomUUID === 'function') { try { return c.randomUUID(); } catch (e) { /* insecure context */ } }
    const b = new Uint8Array(16);
    c.getRandomValues(b);
    b[6] = (b[6] & 0x0f) | 0x40;
    b[8] = (b[8] & 0x3f) | 0x80;
    const x = Array.from(b, (v) => v.toString(16).padStart(2, '0')).join('');
    return `${x.slice(0, 8)}-${x.slice(8, 12)}-${x.slice(12, 16)}-${x.slice(16, 20)}-${x.slice(20)}`;
  };

  // ---- The link ---------------------------------------------------------------------------------------------------
  // Take a menu link out of the address bar into memory (so a sign-in screen, which rewrites the address, does not lose
  // it, and so the list does not stay in the history). True when there was one.
  function takeLink() {
    let hash = '';
    try { hash = location.hash || ''; } catch (e) { return false; }
    if (!M.isLink(hash)) return false;
    pending = hash.slice(0, M.MAX_LINK_CHARS + 1);
    try { history.replaceState(null, '', location.pathname + location.search); } catch (e) { /* sandboxed frame */ }
    return true;
  }
  function openPending() {
    if (!pending) return Promise.resolve();
    const link = pending;
    pending = null;
    return openLink(link);
  }

  // ---- Sheet ------------------------------------------------------------------------------------------------------
  function ticked() { return S.rows.filter((r) => r.on); }

  function setProblem(message) {
    const box = $('#menuplan-error');
    clear(box);
    box.hidden = !message;
    if (message) box.append(h('p', {}, message));
  }

  function renderGroups() {
    const host = clear($('#menuplan-groups'));
    let i = 0;
    for (const meal of MEALS.map((m) => m.key)) {
      const rows = S.rows.filter((r) => r.meal === meal);
      if (!rows.length) continue;
      const list = h('ul', { class: 'mp-items' });
      for (const r of rows) {
        const id = `mp-item-${i++}`;
        const box = h('input', { type: 'checkbox', id, checked: r.on || null });
        box.addEventListener('change', () => { r.on = box.checked; renderTotals(); });
        const scaled = scaledNutrients(r.food.nutrients, r.servings);
        const nums = ROW_NUMBERS.map((k) => `${NUT[k].short} ${fmtNum(scaled[k], k)} ${NUT[k].unit}`).join(' · ');
        list.append(h('li', { class: 'mp-item' },
          h('label', { class: 'check', for: id }, box,
            h('span', { class: 'check-text' },
              h('span', { class: 'mp-name' }, ratingIcon(r.food.kidney_rating, { decorative: true }), r.food.name),
              h('span', { class: 'hint' }, `${fmtServings(r.servings)}${r.food.serving_desc ? ` of ${r.food.serving_desc}` : ''}`),
              h('span', { class: 'hint' }, nums)))));
      }
      host.append(h('section', { class: 'mp-meal' }, h('h3', { class: 'mp-meal-title' }, MEAL_LABEL[meal]), list));
    }
  }

  function renderSkipped(skipped) {
    const box = $('#menuplan-skipped');
    const list = clear($('#menuplan-skipped-list'));
    box.hidden = !skipped.length;
    for (const s of skipped) list.append(h('li', {}, h('b', {}, s.text), `: ${s.reason}`));
  }

  function menuTotals() {
    const total = {};
    const unknown = {};
    for (const k of NUTRIENT_KEYS) { total[k] = 0; unknown[k] = 0; }
    for (const r of ticked()) {
      const sc = scaledNutrients(r.food.nutrients, r.servings);
      for (const k of NUTRIENT_KEYS) { if (sc[k] == null) unknown[k] += 1; else total[k] += sc[k]; }
    }
    return { total, unknown };
  }

  // The menu day alone, then the day with everything already planned on that date (the server's projected totals plus
  // this menu), then the app's near / over lines for it.
  function renderTotals() {
    const on = ticked();
    $('#menuplan-count').textContent = `${on.length} of ${S.rows.length} ${S.rows.length === 1 ? 'food' : 'foods'}`;
    $('#menuplan-save').disabled = S.busy || !on.length || !DATE_RE.test(S.date);
    const key = clear($('#menuplan-key'));
    const lines = clear($('#menuplan-lines'));
    const box = clear($('#menuplan-warnings'));
    const { total, unknown } = menuTotals();
    for (const k of KEY_NUMBERS) {
      key.append(h('div', { class: 'kn' }, h('span', { class: 'kn-v' }, atLeast(fmtNum(total[k], k), unknown[k])),
        h('span', { class: 'kn-u' }, NUT[k].unit), h('span', { class: 'kn-l' }, NUT[k].short)));
    }
    const day = S.dayFor === S.date ? S.day : null;
    $('#menuplan-day-title').textContent = DATE_RE.test(S.date) ? `With what is planned on ${fmtDateLong(S.date)}` : 'With what is planned that day';
    if (!day || !on.length) {
      lines.append(h('li', { class: 'muted small' }, !on.length ? 'Nothing ticked.' : DATE_RE.test(S.date) ? 'Loading that day…' : 'Pick a date.'));
      return;
    }
    const wf = (state.profile && state.profile.warn_fraction) || 0.8;
    const tol = (state.profile && state.profile.about_tolerance_pct) || 0;
    const projected = day.projected_status || day.status || {};
    let any = false;
    for (const k of PLAN_CHIPS) {
      const st = projected[k];
      if (!st || !st.target) continue;
      any = true;
      const value = (Number(st.value) || 0) + total[k];
      const unk = (st.unknown != null ? Number(st.unknown) : unknownOf(day.projected_unknown, k)) + unknown[k];
      const fraction = value / st.target;
      const level = KH.rules.statusLevel(fraction, wf, KH.rules.overAt(k, st.min, st.target, tol));
      const about = KH.ui.isAboutTarget(st, k) ? 'about ' : '';
      lines.append(h('li', { class: `mp-line level-${level}` }, ratingIcon(level, { label: LEVEL_TEXT[level] }),
        h('span', {}, `${NUT[k].label} `, h('b', {}, atLeast(fmtNum(value, k), unk)), ` of ${about}${fmtNum(st.target, k)} ${NUT[k].unit} (${pct(fraction)} %)`)));
    }
    if (!any) lines.append(h('li', { class: 'muted small' }, 'No daily targets are set, so there is nothing to compare with.'));
    const notes = impactOn(day, total, null, { status: 'planned' });
    for (const meal of MEALS.map((m) => m.key)) {
      // Carbohydrate per meal; a food that treats a low is left out of a meal's carbohydrate, as for any entry.
      const carbs = on.filter((r) => r.meal === meal && !(r.food.flags || []).includes('hypo_treatment'))
        .reduce((a, r) => a + ((scaledNutrients(r.food.nutrients, r.servings).carbs_g) || 0), 0);
      if (carbs > 0) notes.push(...impactOn(day, { carbs_g: carbs }, meal, { status: 'planned' }));
    }
    for (const it of notes) {
      box.append(h('div', { class: `warning level-${it.level}` }, ratingIcon(it.level, { label: LEVEL_TEXT[it.level] }),
        h('div', {}, h('span', { class: 'w-level' }, it.level === 'over' ? 'Day total over. ' : 'Day total near limit. '), it.message)));
    }
  }

  async function loadDay() {
    const date = S.date;
    const req = ++S.dayReq;
    S.dayFor = null;
    renderTotals();
    if (!DATE_RE.test(date)) return;
    let day = null;
    try { day = await KH.api.day(date); } catch (e) { day = null; }
    if (req !== S.dayReq) return;
    S.day = day;
    S.dayFor = day ? date : null;
    renderTotals();
  }

  // Tomorrow, or the first of the next 14 days with nothing logged or planned (tomorrow when every one has something).
  async function defaultDate() {
    const first = addDays(todayStr(), 1);
    try {
      const res = await KH.api.range(first, addDays(first, LOOK_AHEAD_DAYS - 1));
      const busy = new Set((res.days || []).filter((d) => d && d.counts && (d.counts.eaten || 0) + (d.counts.planned || 0) > 0).map((d) => d.date));
      for (let i = 0; i < LOOK_AHEAD_DAYS; i++) { const d = addDays(first, i); if (!busy.has(d)) return d; }
    } catch (e) { /* the date can be picked by hand */ }
    return first;
  }

  async function openLink(raw) {
    const token = ++S.token;
    S.rows = [];
    S.busy = false;
    S.day = null;
    S.dayFor = null;
    const parsed = M.parse(raw);
    let skipped = [];
    let foods = [];
    let problem = parsed.ok ? '' : parsed.error;
    if (parsed.ok) {
      skipped = [...parsed.skipped];
      try {
        const answer = await KH.request('GET', '/api/foods/builtin');
        foods = (answer && answer.foods) || [];
      } catch (e) {
        if (!e.handled) problem = 'The app could not load its food list. Check your connection and open the link again.';
        else return;
      }
    }
    if (token !== S.token) return;
    if (!problem) {
      const resolved = M.resolve(parsed.items, foods);
      skipped.push(...resolved.skipped);
      S.rows = resolved.rows.map((r) => ({ ...r, on: true, client_id: uid() }));
      if (!S.rows.length) problem = 'None of the foods in this link could be used, so there is nothing to add.';
    }
    S.date = problem ? '' : await defaultDate();
    if (token !== S.token) return;
    $('#menuplan-date').value = S.date;
    $('#menuplan-groups').hidden = !!problem;
    $('#menuplan-preview').hidden = !!problem;
    $('#menuplan-date-field').hidden = !!problem;
    setProblem(problem);
    renderGroups();
    renderSkipped(skipped);
    renderTotals();
    sheets.open(dlg, null, problem ? $('#menuplan-close') : $('#menuplan-save'));
    if (!problem) loadDay();
  }

  $('#menuplan-date').addEventListener('input', () => {
    S.date = $('#menuplan-date').value;
    loadDay();
  });

  // The only write: the ticked foods, as planned entries, in one batch (all or nothing on the server).
  sheets.onSubmit($('#menuplan-form'), async (e) => {
    e.preventDefault();
    if (S.busy) return;
    const on = ticked();
    if (!on.length || !DATE_RE.test(S.date)) return;
    const date = S.date;
    S.busy = true;
    renderTotals();
    setProblem('');
    try {
      const entries = M.batchEntries(on, date, uid);
      const res = await KH.request('POST', '/api/log/batch', { entries });
      const created = ((res && res.results) || []).filter((r) => r.result === 'created').length;
      const count = res && res.results ? created : entries.length;
      S.rows = [];
      dlg.close();
      toast(count ? `Added ${count} ${count === 1 ? 'food' : 'foods'} to ${fmtDateLong(date)} as planned` : `These foods were already in your plan for ${fmtDateLong(date)}`, 'ok');
      state.dayLoadedFor = null; state.trends = null; state.summary = null;
      state.planStart = weekStartOf(date, state.profile && state.profile.week_start === 'sunday' ? 'sunday' : 'monday');
      router.show('plan');
    } catch (err) {
      if (!err.handled) setProblem(err.detail || err.message || 'The foods could not be added. Try again.');
    } finally {
      S.busy = false;
      if (dlg.open) renderTotals();
    }
  });

  // A link followed while the app is already open (the address bar changed): take it, and show it once someone is signed in.
  window.addEventListener('hashchange', () => {
    if (!takeLink()) return;
    if (state.me && state.view !== 'auth') openPending();
  });
  takeLink(); // a link the page was opened with: kept before any sign-in screen rewrites the address

  KH.menuPlan = { takeLink, openPending, openLink, state: S };
})();
