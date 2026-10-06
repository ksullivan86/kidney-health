/* Kidney Diet Log — meal guidance in the app (KH.guidance; docs/dev/research/06-meal-guidance.md §4.16,
   ARCHITECTURE.md "M2 API: guidance"). The server's rule engine (app/guidance/) decides everything; this
   file only asks it and shows the answers, word for word (every number is already in the server's text).

   * Add view: "What fits now" above the search (#guidance-fits): pick a meal (or arrive from a meal's
     "Add" / "What fits" on Today), see what is left for it, foods grouped by role with Add / Plan and a
     "Not for me" row menu, saved and usual meals that fit as chips, tips, and (when the server offers
     AI) the AI ideas block of js/views/ai.js.
   * Entry sheet (js/views/add.js calls KH.guidance.entry): the "Used to treat a low" box (pre-ticked for
     low-treatment foods; sent as purpose "hypo" / "none"), "Lower-… ideas" swaps when a potassium,
     phosphorus or sodium warning shows, and for a low treatment the "For your next low" card instead.
     A low treatment is never warned against: its numbers are shown as plain information.
   * Today: the "Meal ideas" card (What fits now, Plan the rest of my day, Treating a low), a "What fits"
     link under each meal, a "treated a low" badge on low-treatment entries, and end-of-day insight
     cards (a past day, or today once breakfast, lunch and dinner are logged or after 19:00).
   * Plan view and Today: the plan sheet ("Use this plan" → POST /api/log/batch with client_ids, "Show
     another" → the next variant).
   * Trends: period insights above the charts. Settings: the person's guidance preferences and the
     "Not for me" list.
   * Offline: the last answer of each kind is kept in memory with its time and shown with "Saved at …";
     without one, "Guidance needs a connection to your server." The "Treating a low" card is drawn from
     the browser twin of the server's text (KH.guidanceEngine.M) when the server cannot be reached, so
     it is there when it matters. Nothing is written to browser storage (it is health data).

   DOM is built with KH.h and textContent only (CSP + Trusted Types); lists carry role="list" (list-style
   none drops list semantics in Safari); async results are announced through role="status" regions. */
(() => {
  'use strict';
  const KH = window.KH;
  const { h, $, $$, clear, state, toast, toastError, router, sheets, request } = KH;
  const { NUT, MEALS, MEAL_LABEL, fmtNum } = KH.rules;
  const { ratingIcon, levelPill, LEVEL_TEXT } = KH.ui;
  const { todayStr, addDays, fmtDateLong, fmtDateShort, fmtRange, defaultMealForNow, defaultStatusFor, qs } = KH.util;
  const GE = KH.guidanceEngine || null; // the browser twin (texts for the offline "Treating a low" card)

  const MAIN_MEALS = ['breakfast', 'lunch', 'dinner'];
  const GROUPS = [
    ['protein', 'Protein'],
    ['starch', 'Starches'],
    ['veg_fruit', 'Vegetables and fruit'],
    ['extra', 'Extras'],
  ];
  const SWAP_NUTRIENTS = { potassium_mg: 'potassium', phosphorus_mg: 'phosphorus', sodium_mg: 'sodium', fluid_ml: 'fluid' };
  const SWAP_FLAGS = new Set(['phosphate_additive', 'avoid_ckd', 'potassium_additive']);
  const INSIGHT_LEVEL = { warning: 'over', attention: 'caution', info: 'info', good: 'ok' };
  const INSIGHT_WORD = { warning: 'Over limit', attention: 'Worth a look', info: 'Note', good: 'Going well' };
  const DAY_KEYS = ['potassium_mg', 'phosphorus_mg', 'sodium_mg', 'fluid_ml', 'protein_g', 'carbs_g', 'calories_kcal'];
  const END_OF_DAY_HOUR = 19; // note 06 §4.16: insights after 19:00 local, or once every main meal is logged
  const MAX_VARIANT = 4;
  const NEEDS_CONNECTION = (GE && GE.M && GE.M.NEEDS_CONNECTION) || 'Guidance needs a connection to your server.';
  const DEFAULT_HYPO_DOSE_G = 15;
  const FITS_SHOWN = 2; // foods per group shown before "Show more" in What fits now

  // ---------------------------------------------------------------------------
  // API (same-origin /api/guidance/*; the demo answers the same routes in js/mock/guidance.js)
  // ---------------------------------------------------------------------------
  const api = {
    nextMeal: (params) => request('GET', `/api/guidance/next-meal?${qs(params)}`),
    swaps: (params) => request('GET', `/api/guidance/swaps?${qs(params)}`),
    hypoOptions: () => request('GET', '/api/guidance/hypo-options'),
    planDay: (body) => request('POST', '/api/guidance/plan-day', body),
    insightsDay: (date) => request('GET', `/api/guidance/insights/day?${qs({ date })}`),
    insightsPeriod: (start, end) => request('GET', `/api/guidance/insights/period?${qs({ start, end })}`),
    notForMe: () => request('GET', '/api/guidance/not-for-me'),
    addNotForMe: (foodId) => request('PUT', `/api/guidance/not-for-me/${encodeURIComponent(foodId)}`),
    removeNotForMe: (foodId) => request('DELETE', `/api/guidance/not-for-me/${encodeURIComponent(foodId)}`),
    logBatch: (entries) => request('POST', '/api/log/batch', { entries }),
  };

  // The last good answer per request, in memory only, for the offline message (§4.16).
  const memo = new Map();
  const MEMO_MAX = 40;
  async function remembered(key, fn) {
    try {
      const data = await fn();
      memo.delete(key);
      memo.set(key, { data, at: new Date() });
      while (memo.size > MEMO_MAX) memo.delete(memo.keys().next().value);
      return { data, at: null };
    } catch (err) {
      if (err && err.status === 0) {
        const hit = memo.get(key);
        if (hit) return { data: hit.data, at: hit.at };
        err.offline = true;
      }
      throw err;
    }
  }
  function forgetAnswers() { memo.clear(); }

  // A version 4 UUID for POST /api/log client_id (the offline outbox's idempotency key, note 02 R5).
  // crypto.randomUUID needs a secure context; getRandomValues also works on a plain-HTTP LAN.
  function uuid() {
    const c = window.crypto;
    if (c && typeof c.randomUUID === 'function') { try { return c.randomUUID(); } catch (e) { /* insecure context */ } }
    const b = new Uint8Array(16);
    c.getRandomValues(b);
    b[6] = (b[6] & 0x0f) | 0x40;
    b[8] = (b[8] & 0x3f) | 0x80;
    const x = Array.from(b, (v) => v.toString(16).padStart(2, '0')).join('');
    return `${x.slice(0, 8)}-${x.slice(8, 12)}-${x.slice(12, 16)}-${x.slice(16, 20)}-${x.slice(20)}`;
  }

  // ---------------------------------------------------------------------------
  // The person's guidance settings (GET /api/me/settings → "guidance"), cached for the page
  // ---------------------------------------------------------------------------
  let prefsCache = null; // { item: {value, source, editable}, at }
  let serverOff = false; // an answer said the admin switched guidance off
  async function loadPrefs(force = false) {
    if (prefsCache && !force) return prefsCache.item;
    try {
      const res = await KH.api.mySettings();
      const item = res && res.settings ? res.settings.guidance : null;
      prefsCache = { item: item || null };
    } catch (err) {
      if (!prefsCache) prefsCache = { item: null };
      if (!(err && err.handled) && err && err.status !== 0) console.warn('Guidance settings unavailable:', err.detail || err);
    }
    return prefsCache.item;
  }
  function prefValue(name, fallback) {
    const v = prefsCache && prefsCache.item && prefsCache.item.value;
    return v && Object.prototype.hasOwnProperty.call(v, name) ? v[name] : fallback;
  }
  function guidanceOn() { return prefValue('enabled', true) !== false && !serverOff; }
  function hasDiabetes() { return !!(state.profile && state.profile.diabetes && state.profile.diabetes !== 'none'); }
  function noteAnswer(res) {
    if (res && res.status === 'disabled' && GE && res.message === GE.M.DISABLED) serverOff = true;
    if (res && res.status === 'ok') serverOff = false;
  }

  // ---------------------------------------------------------------------------
  // Small building blocks
  // ---------------------------------------------------------------------------
  let uidSeq = 0;
  function uid(prefix) { uidSeq += 1; return `${prefix}-${uidSeq}`; }
  function list(cls, items) { return h('ul', { class: cls, role: 'list' }, items); }
  function btn(label, cls, onClick, attrs = {}) {
    const b = h('button', { class: `btn ${cls}`, type: 'button', ...attrs }, label);
    b.addEventListener('click', onClick);
    return b;
  }
  function linkBtn(label, onClick, attrs = {}) {
    const b = h('button', { class: 'link-btn', type: 'button', ...attrs }, label);
    b.addEventListener('click', onClick);
    return b;
  }
  // "Learn: Potassium" links for [{slug, title, url}] (opens in a new tab; none without a handbook).
  function learnLinks(pages) {
    const out = [];
    const seen = new Set();
    for (const p of pages || []) {
      if (!p || seen.has(p.url)) continue;
      seen.add(p.url);
      const href = KH.learn ? KH.learn.href(p.url) : null;
      if (!href) continue;
      out.push(h('a', { class: 'learn-more', href, target: '_blank', rel: 'noopener' },
        `Learn: ${p.title}`, h('span', { class: 'sr-only' }, ' (opens in a new tab)')));
    }
    return out.length ? h('p', { class: 'g-learn' }, ...out.flatMap((a, i) => (i ? [' ', a] : [a]))) : null;
  }
  function learnFor(url, title) { return learnLinks([{ url, title }]); }
  function notes(items) {
    const texts = (items || []).filter(Boolean);
    return texts.length ? h('div', { class: 'g-notes' }, texts.map((t) => h('p', { class: 'hint' }, t))) : null;
  }
  function timeText(d) { return d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' }); }
  function staleNote(at) {
    return at ? h('p', { class: 'g-offline', role: 'note' }, `Saved at ${timeText(at)}. ${NEEDS_CONNECTION} The suggestions update when it is back.`) : null;
  }
  function loadingNote(text) { return h('p', { class: 'muted small g-loading' }, text); }
  // An answer that is not a result: no targets yet, guidance switched off, offline, or an error.
  function unavailable(res, { compact = false } = {}) {
    const box = h('div', { class: 'g-unavailable' });
    if (res && res.status === 'no_targets') {
      box.append(h('p', {}, res.message), linkBtn('Set your targets in Profile', () => router.show('profile')));
    } else if (res && res.status === 'disabled') {
      box.append(h('p', {}, res.message));
      if (!(GE && res.message === GE.M.DISABLED) && !compact) box.append(linkBtn('Open Settings → Meal guidance', () => openSettingsSection()));
    } else {
      box.append(h('p', {}, res && res.message ? res.message : NEEDS_CONNECTION));
    }
    return box;
  }
  function failure(err) {
    if (err && err.offline) return h('div', { class: 'g-unavailable' }, h('p', { class: 'g-offline', role: 'note' }, NEEDS_CONNECTION));
    return h('div', { class: 'g-unavailable' }, h('p', { class: 'form-error' }, `Guidance could not load: ${(err && (err.detail || err.message)) || 'unknown error'}`));
  }
  function openSettingsSection() {
    router.show('settings');
    setTimeout(() => {
      const head = $('#set-guidance-h');
      if (head) { head.setAttribute('tabindex', '-1'); head.scrollIntoView({ block: 'start' }); head.focus({ preventScroll: true }); }
    }, 60);
  }
  // Four key numbers of a portion: "45 g carbs · 55 mg potassium · 70 mg phosphorus · 0 mg sodium".
  function keyNumbers(n) {
    if (!n) return '';
    const parts = [];
    for (const k of ['carbs_g', 'potassium_mg', 'phosphorus_mg', 'sodium_mg']) {
      if (n[k] != null) parts.push(`${fmtNum(n[k], k)} ${NUT[k].unit} ${NUT[k].label.toLowerCase().replace('carbohydrate', 'carbs')}`);
    }
    return parts.join(' · ');
  }
  function ratingOf(item) { return ratingIcon(item.renal_rating || 'green'); }

  // ---------------------------------------------------------------------------
  // Logging from a suggestion: the entry sheet, prefilled (the person sees warnings before saving)
  // ---------------------------------------------------------------------------
  async function openEntryFor(item, { meal, status, trigger }) {
    try {
      const food = await KH.api.food(item.food_id);
      KH.views.add.openEntrySheet('add', { food, meal, servings: item.servings, status, trigger });
    } catch (err) { toastError(err); }
  }

  // "⋯" row menu with "Not for me" (a disclosure: the button controls a small inline action row).
  function rowMenu(item, { onHidden }) {
    const menuId = uid('g-menu');
    const more = h('button', { class: 'icon-btn g-more', type: 'button', 'aria-expanded': 'false', 'aria-controls': menuId,
      'aria-label': `More for ${item.name}` }, moreIcon());
    const nfm = h('button', { class: 'btn secondary g-nfm', type: 'button' }, 'Not for me');
    const menu = h('div', { class: 'g-menu', id: menuId, hidden: true },
      nfm, h('span', { class: 'hint' }, 'Never suggest this food again. It stays in search, and Settings → Meal guidance can bring it back.'));
    const close = (refocus) => { menu.hidden = true; more.setAttribute('aria-expanded', 'false'); if (refocus) more.focus(); };
    more.addEventListener('click', () => {
      const open = menu.hidden;
      menu.hidden = !open;
      more.setAttribute('aria-expanded', open ? 'true' : 'false');
      if (open) nfm.focus();
    });
    menu.addEventListener('keydown', (e) => { if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); close(true); } });
    nfm.addEventListener('click', async () => {
      nfm.disabled = true;
      try {
        await api.addNotForMe(item.food_id);
        forgetAnswers();
        toast(`${item.name} will not be suggested again. Settings → Meal guidance lists it.`, 'ok');
        if (onHidden) onHidden();
      } catch (err) { toastError(err); nfm.disabled = false; }
    });
    return { more, menu };
  }
  function moreIcon() {
    return KH.s('svg', { viewBox: '0 0 24 24', 'aria-hidden': 'true', focusable: 'false' },
      KH.s('circle', { cx: 5, cy: 12, r: 2, fill: 'currentColor' }), KH.s('circle', { cx: 12, cy: 12, r: 2, fill: 'currentColor' }),
      KH.s('circle', { cx: 19, cy: 12, r: 2, fill: 'currentColor' }));
  }

  // One suggested food (FoodPortion + fit_text + reasons): name, portion, fit text, one reason, the
  // renal dot, Add / Plan and the row menu.
  function foodRow(item, { meal, date, onChange, ai = null }) {
    const status = defaultStatusFor(date);
    const reason = item.reasons && item.reasons.length ? item.reasons[0].text : null;
    const nameId = uid('g-food');
    const { more, menu } = rowMenu(item, { onHidden: onChange });
    const add = btn('Add', 'secondary g-act', (e) => openEntryFor(item, { meal, status: 'eaten', trigger: e.currentTarget }),
      { 'aria-describedby': nameId, 'aria-label': `Add ${item.name}, ${item.portion_text}, to ${MEAL_LABEL[meal].toLowerCase()}` });
    const plan = btn('Plan', 'secondary g-act', (e) => openEntryFor(item, { meal, status: 'planned', trigger: e.currentTarget }),
      { 'aria-label': `Plan ${item.name}, ${item.portion_text}, for ${MEAL_LABEL[meal].toLowerCase()}` });
    const actions = h('div', { class: 'g-actions' }, status === 'planned' ? [plan, add] : [add, plan], more);
    return h('li', { class: 'g-food' },
      h('div', { class: 'g-food-main' }, ratingOf(item),
        h('div', { class: 'g-food-text' },
          h('div', { class: 'row-title', id: nameId }, item.name),
          h('div', { class: 'row-sub' }, item.portion_text),
          item.fit_text ? h('div', { class: 'g-fit tabular' }, item.fit_text) : null,
          reason ? h('div', { class: 'g-reason' }, reason) : null,
          ai && ai.why ? h('div', { class: 'g-ai-why' }, h('span', { class: 'g-ai-badge' }, `AI #${ai.ai_rank}`), ` ${ai.why}`) : null)),
      actions, menu);
  }

  // ---------------------------------------------------------------------------
  // "What fits now" (Add view)
  // ---------------------------------------------------------------------------
  const fits = { meal: null, request: 0, last: null, ai: null }; // ai: the AI order for last.meal/date, or null
  const fitsEl = $('#guidance-fits');
  const fitsBody = $('#guidance-fits-body');
  const fitsStatus = $('#guidance-fits-status');
  const fitsPick = $('#guidance-fits-meal');

  function chosenFitsMeal() { const r = $('input:checked', fitsPick); return r ? r.value : null; }
  function setFitsMeal(meal) {
    for (const r of $$('input', fitsPick)) r.checked = r.value === meal;
  }
  fitsPick.addEventListener('change', () => {
    fits.meal = chosenFitsMeal();
    loadFits();
  });
  $('#guidance-fits-clear').addEventListener('click', () => {
    fits.meal = null;
    setFitsMeal(null);
    renderFitsIdle();
    $('input', fitsPick).focus();
  });

  async function showAdd() {
    await loadPrefs();
    fitsEl.hidden = !guidanceOn();
    if (fitsEl.hidden) return;
    const hint = state.addMealHint;
    if (hint) { fits.meal = hint; setFitsMeal(hint); }
    if (fits.meal) loadFits(); else renderFitsIdle();
  }
  function renderFitsIdle() {
    clear(fitsBody);
    $('#guidance-fits-clear').hidden = true;
    fitsBody.append(h('p', { class: 'hint g-idle' }, 'Pick a meal to see foods that fit what is left of today’s targets.'));
  }
  async function loadFits() {
    const meal = fits.meal;
    if (!meal) { renderFitsIdle(); return; }
    const date = state.date || todayStr();
    const reqId = ++fits.request;
    $('#guidance-fits-clear').hidden = false;
    fitsBody.setAttribute('aria-busy', 'true');
    clear(fitsBody).append(loadingNote(`Finding foods that fit ${MEAL_LABEL[meal].toLowerCase()}…`));
    try {
      const { data, at } = await remembered(`next:${date}:${meal}`, () => api.nextMeal({ meal, date }));
      if (reqId !== fits.request) return;
      noteAnswer(data);
      if (!fits.last || fits.last.meal !== meal || fits.last.date !== date) fits.ai = null;
      fits.last = { res: data, meal, date, at };
      renderFits(data, { meal, date, at });
    } catch (err) {
      if (reqId !== fits.request) return;
      if (!err.handled) clear(fitsBody).append(failure(err));
      fitsStatus.textContent = err.offline ? NEEDS_CONNECTION : 'Guidance could not load.';
    } finally {
      if (reqId === fits.request) fitsBody.removeAttribute('aria-busy');
    }
  }
  function renderFits(res, { meal, date, at }) {
    clear(fitsBody);
    if (!res || res.status !== 'ok') {
      fitsBody.append(unavailable(res));
      fitsStatus.textContent = res && res.message ? res.message : '';
      return;
    }
    const mealWord = MEAL_LABEL[meal].toLowerCase();
    const stale = staleNote(at);
    if (stale) fitsBody.append(stale);
    if (date !== todayStr()) fitsBody.append(h('p', { class: 'hint' }, `For ${fmtDateLong(date)}.`));
    fitsBody.append(h('p', { class: 'g-room tabular' }, res.room_text));
    const onChange = () => loadFits();
    const foods = res.foods || [];
    for (const [group, label] of GROUPS) {
      const items = foods.filter((f) => f.group === group);
      if (!items.length) continue;
      const hid = uid('g-grp');
      const rows = aiOrdered(items).map((item) => foodRow(item, { meal, date, onChange, ai: fits.ai ? fits.ai.ranks.get(item.food_id) : null }));
      const ul = list('g-foods', rows);
      ul.id = uid('g-list');
      const sec = h('section', { class: 'g-group', 'aria-labelledby': hid }, h('h3', { class: 'g-group-title', id: hid }, label), ul);
      // The best FITS_SHOWN per group first, so the search stays near the top on a phone.
      if (rows.length > FITS_SHOWN) {
        const extra = rows.slice(FITS_SHOWN);
        for (const r of extra) r.hidden = true;
        const word = label.toLowerCase();
        const more = linkBtn(`Show ${extra.length} more`, () => {
          const open = more.getAttribute('aria-expanded') !== 'true';
          for (const r of extra) r.hidden = !open;
          more.setAttribute('aria-expanded', open ? 'true' : 'false');
          more.textContent = open ? 'Show fewer' : `Show ${extra.length} more`;
          if (open) { const first = $('button', extra[0]); if (first) first.focus(); }
        }, { 'aria-expanded': 'false', 'aria-controls': ul.id, 'aria-label': `Show ${extra.length} more ${word}` });
        sec.append(more);
      }
      fitsBody.append(sec);
    }
    if (!foods.length) fitsBody.append(h('p', { class: 'empty-state' }, `No foods in your list fit ${mealWord} within what is left today. Try a smaller portion of something you like, or plan the rest of the day.`));
    const saved = res.saved_meals || [];
    if (saved.length) {
      const hid = uid('g-saved');
      fitsBody.append(h('section', { class: 'g-group', 'aria-labelledby': hid },
        h('h3', { class: 'g-group-title', id: hid }, 'Meals that fit'),
        list('chips g-meal-chips', saved.map((m) => h('li', { class: 'meal-chip-item' }, mealChip(m, { meal, date }))))));
    }
    for (const tip of res.tips || []) {
      fitsBody.append(h('div', { class: 'g-tip' }, h('p', {}, tip.text), learnFor(tip.url, tipTitle(tip))));
    }
    if (res.ai && res.ai.available && KH.ai && typeof KH.ai.mountIdeas === 'function') {
      if (aiEnrich()) fitsBody.prepend(aiOrderBar(res, meal, date));
      fitsBody.append(aiBlock(meal, date, res.ai));
    }
    const n = notes(res.notes);
    if (n) fitsBody.append(n);
    fitsStatus.textContent = `${foods.length} ${foods.length === 1 ? 'food fits' : 'foods fit'} ${mealWord}${saved.length ? `, and ${saved.length} ${saved.length === 1 ? 'meal' : 'meals'}` : ''}. ${res.room_text}`;
  }
  function tipTitle(tip) {
    const page = GE && GE.T && GE.T.TOPIC_PAGES[tip.handbook];
    return page ? page.title : 'More in the handbook';
  }
  // The AI ideas block (js/views/ai.js), mounted on first open of the disclosure.
  function aiBlock(meal, date, ai) {
    const box = h('div', { class: 'ai-block' });
    const det = h('details', { class: 'g-disclosure' },
      h('summary', {}, ai.provider_label ? `AI ideas, checked against your targets (${ai.provider_label})` : 'AI ideas, checked against your targets'), box);
    let mounted = false;
    det.addEventListener('toggle', () => { if (det.open && !mounted) { mounted = true; KH.ai.mountIdeas(box, { date, meal }); } });
    return det;
  }
  // A saved or usual meal that fits: a chip that opens the meal sheet (add it, plan it).
  function mealChip(m, { meal, date }) {
    const carbs = m.totals && m.totals.carbs_g != null ? `${fmtNum(m.totals.carbs_g, 'carbs_g')} g carbs` : '';
    const k = m.totals && m.totals.potassium_mg != null ? `${fmtNum(m.totals.potassium_mg, 'potassium_mg')} mg potassium` : '';
    const b = h('button', { class: 'meal-chip', type: 'button',
      'aria-label': `${m.name}: ${m.items.length} ${m.items.length === 1 ? 'food' : 'foods'}${carbs ? `, ${carbs}` : ''}${k ? `, ${k}` : ''}. ${m.note || ''}` },
      h('span', { class: 'meal-chip-main' }, h('span', { class: 'meal-chip-name' }, m.name),
        h('span', { class: 'meal-chip-sub' }, [m.source === 'usual' ? 'Usual' : 'Saved', carbs].filter(Boolean).join(' · '))));
    b.addEventListener('click', () => openMealSheet(m, { meal, date, trigger: b }));
    return b;
  }

  // ---------------------------------------------------------------------------
  // Optional AI on top of the rules (note 06 §4.13; js/views/ai.js does consent and the calls). Only
  // when the person opted in to "AI may re-order and explain" (guidance.ai_enrich) and the server
  // offers AI; the numbers, fit checks and texts always stay the rules' own.
  // ---------------------------------------------------------------------------
  function aiEnrich() { return prefValue('ai_enrich', false) === true && !!(KH.ai && KH.ai.withConsent); }
  async function aiAvailable() {
    if (!aiEnrich()) return null;
    try { const st = await KH.ai.status(); return st && st.features && st.features.next_meal ? st : null; } catch (e) { return null; }
  }
  async function aiNextMeal(body, trigger) {
    return KH.ai.withConsent('text', () => KH.ai.api.nextMeal(body), () => KH.ai.api.nextMeal(body, true), trigger);
  }
  function aiAnswerNote(answer) {
    if (!answer || answer.status === 'ok') return null;
    return h('p', { class: 'g-offline', role: 'note' }, answer.message || 'The AI answer could not be used; these are the app’s own suggestions.');
  }
  function aiError(box, err) {
    if (err && (err.handled || err.cancelled)) return;
    clear(box).append(h('p', { class: 'form-error' }, `AI: ${(err && (err.detail || err.message)) || 'the request failed'}`));
  }
  function aiOrdered(items) {
    if (!fits.ai) return items;
    const rank = (f) => { const r = fits.ai.ranks.get(f.food_id); return r ? r.ai_rank : Infinity; };
    return items.map((f, i) => [f, i]).sort((a, b) => rank(a[0]) - rank(b[0]) || a[1] - b[1]).map(([f]) => f);
  }
  // "AI order · provider": a toggle over the same list (mode "rerank").
  function aiOrderBar(res, meal, date) {
    const on = !!fits.ai;
    const label = (res.ai && res.ai.provider_label) || 'AI';
    const toggle = h('button', { class: 'btn secondary g-ai-toggle', type: 'button', 'aria-pressed': on ? 'true' : 'false' },
      `AI order · ${on ? fits.ai.provider : label}`);
    const msg = h('div', { class: 'g-ai-msg' });
    toggle.addEventListener('click', async () => {
      if (fits.ai) {
        fits.ai = null;
        renderFits(fits.last.res, fits.last);
        const t = $('.g-ai-toggle', fitsBody);
        if (t) t.focus();
        return;
      }
      toggle.disabled = true;
      clear(msg);
      try {
        const answer = await aiNextMeal({ meal, date, mode: 'rerank' }, toggle);
        if (!answer) return;
        if (answer.status === 'ok' && (answer.order || []).length) {
          fits.ai = { provider: (answer.provider && answer.provider.label) || label, ranks: new Map(answer.order.map((o) => [o.food_id, o])) };
          renderFits(fits.last.res, fits.last);
          const t = $('.g-ai-toggle', fitsBody);
          if (t) t.focus();
          fitsStatus.textContent = `Shown in the AI's order (${fits.ai.provider}). The numbers and fit checks are the app's own.`;
        } else msg.append(aiAnswerNote(answer));
      } catch (err) { aiError(msg, err); } finally { if (document.contains(toggle)) toggle.disabled = false; }
    });
    return h('div', { class: 'g-ai-bar' }, toggle,
      h('p', { class: 'hint' }, on ? 'In the AI’s order. The numbers and fit checks are still the app’s own.'
        : 'Let AI put these foods in the order it suggests and say why. The numbers stay the app’s own.'), msg);
  }
  // "Ask AI to pick" under the rule swaps (mode "swap": the AI picks among the rule swaps). Never for a low.
  function aiSwapBlock(c, res) {
    const box = h('div', { class: 'g-ai-swap' });
    aiAvailable().then((st) => {
      if (!st || !document.contains(box)) return;
      const out = h('div', { class: 'g-ai-msg' });
      const ask = h('button', { class: 'btn secondary', type: 'button' }, `Ask AI to pick · ${st.provider ? st.provider.label : 'AI'}`);
      ask.addEventListener('click', async () => {
        ask.disabled = true;
        clear(out);
        const body = c.mode === 'edit' && c.entry && !c.amountTouched ? { meal: c.meal, date: c.date, mode: 'swap', entry_id: c.entry.id }
          : { meal: c.meal, date: c.date, mode: 'swap', food_id: c.food.id, servings: Math.min(20, c.servings > 0 ? c.servings : 1) };
        try {
          const answer = await aiNextMeal(body, ask);
          if (!answer) return;
          if (answer.status === 'ok' && (answer.pick || []).length) {
            out.append(list('g-foods', answer.pick.map((p) => h('li', { class: 'g-food' }, h('div', { class: 'g-food-main' }, ratingIcon(p.renal_rating || 'green'),
              h('div', { class: 'g-food-text' }, h('div', { class: 'row-title' }, h('span', { class: 'g-ai-badge' }, 'AI’s pick'), ` ${p.name}`),
                p.text ? h('div', { class: 'g-reason' }, p.text) : null, p.why ? h('div', { class: 'g-ai-why' }, p.why) : null))))));
          } else out.append(aiAnswerNote(answer) || h('p', { class: 'hint' }, 'The AI did not pick a swap.'));
        } catch (err) { aiError(out, err); } finally { if (document.contains(ask)) ask.disabled = false; }
      });
      box.append(ask, out);
    });
    return (res.swaps || []).length ? box : null;
  }
  // "Let AI choose" in the plan sheet (mode "plan"): the AI picks one option per meal; the rules rebuild
  // and check the whole day again; the meals it picked carry an "AI's pick" badge.
  async function aiPlanButton(foot) {
    const st = await aiAvailable();
    if (!st || sheetEl.dataset.kind !== 'plan' || $('#g-plan-ai')) return;
    const b = btn(`Let AI choose · ${st.provider ? st.provider.label : 'AI'}`, 'secondary', async () => {
      const res = planState.result;
      const out = $('#g-plan-out');
      if (!res || !res.meals.length || !out) return;
      b.disabled = true;
      try {
        const answer = await aiNextMeal({ meal: res.meals[0].meal, date: res.date, mode: 'plan' }, b);
        if (!answer) return;
        if (answer.status === 'ok' && answer.plan && answer.plan.status === 'ok') {
          planState.result = answer.plan;
          planState.aiPicks = answer.ai_picks || {};
          renderPlan(out, answer.plan, null);
          $('#g-plan-status').textContent = `The AI chose ${Object.keys(planState.aiPicks).length} of the meals; the app checked the whole day again.`;
        } else { const n = aiAnswerNote(answer); if (n) out.prepend(n); }
      } catch (err) { const box = h('div'); aiError(box, err); out.prepend(box); } finally { if (document.contains(b)) b.disabled = false; }
    }, { id: 'g-plan-ai' });
    foot.insertBefore(b, foot.querySelector('.spacer'));
  }

  // ---------------------------------------------------------------------------
  // The guidance sheet (#sheet-guidance): plan the day, a fitting meal, treating a low
  // ---------------------------------------------------------------------------
  const sheetEl = $('#sheet-guidance');
  sheets.setup(sheetEl);
  sheetEl.addEventListener('close', () => { sheetEl.dataset.kind = ''; });
  function fillSheet(kind, title, sub) {
    sheetEl.dataset.kind = kind;
    $('#sheet-guidance-title').textContent = title;
    $('#sheet-guidance-sub').textContent = sub || '';
    return { body: clear($('.sheet-body', sheetEl)), foot: clear($('.sheet-foot', sheetEl)) };
  }
  function closeButton() { return btn('Close', 'secondary', () => sheetEl.close()); }

  // A saved meal (template_id) or a usual meal: add or plan every food at the suggested scale.
  function openMealSheet(m, { meal, date, trigger }) {
    const { body, foot } = fillSheet('meal', m.name, `${MEAL_LABEL[meal]}, ${fmtDateLong(date)}`);
    if (m.note) body.append(h('p', {}, m.note));
    body.append(list('compact-items', m.items.map((it) => h('li', {},
      h('span', { class: 'ci-name' }, it.name),
      h('span', { class: 'ci-amt muted' }, KH.rules.fmtServings(it.servings))))));
    if (m.totals) body.append(h('p', { class: 'tabular' }, keyNumbers(m.totals)));
    const err = h('div', { class: 'form-error', role: 'alert' });
    body.append(err);
    const run = async (status, b) => {
      clear(err);
      b.disabled = true;
      try {
        let n;
        if (m.template_id != null) {
          const res = await KH.api.applyMeal(m.template_id, { date, meal, status, scale: m.scale });
          n = res && res.entries ? res.entries.length : m.items.length;
        } else {
          const res = await api.logBatch(m.items.map((it) => ({ date, meal, food_id: it.food_id, servings: it.servings, status, purpose: 'none', client_id: uuid() })));
          n = res && res.entries ? res.entries.length : m.items.length;
        }
        sheetEl.close();
        forgetAnswers();
        toast(`${status === 'planned' ? 'Planned' : 'Added'} ${m.name} (${n} ${n === 1 ? 'food' : 'foods'}) for ${MEAL_LABEL[meal].toLowerCase()}`, 'ok');
        KH.views.plan.afterLogChange(date, { goToDay: state.view === 'add' });
      } catch (e) {
        if (!e.handled) { clear(err).append(h('p', {}, e.detail || e.message)); }
        b.disabled = false;
      }
    };
    const status = defaultStatusFor(date);
    const add = btn(status === 'planned' ? 'Plan these' : 'Add these', 'primary', (e) => run(status, e.currentTarget));
    const other = btn(status === 'planned' ? 'Log as eaten' : 'Plan instead', 'secondary', (e) => run(status === 'planned' ? 'eaten' : 'planned', e.currentTarget));
    foot.append(h('span', { class: 'spacer' }), other, add);
    sheets.open(sheetEl, trigger, add);
  }

  // ---- Plan the rest of my day ----------------------------------------------------------------------
  const planState = { date: null, variant: 0, meals: null, options: { use_saved_meals: true, use_usual: true, use_starters: true },
    result: null, request: 0, busy: false, aiPicks: null };
  async function openPlan({ date = null, trigger = null } = {}) {
    await loadPrefs();
    planState.date = date || state.date || todayStr();
    planState.variant = 0;
    planState.meals = null;
    planState.result = null;
    planState.aiPicks = null;
    const { body, foot } = fillSheet('plan', 'Plan the rest of my day', 'Foods from your own list that fit what is left of your targets.');
    const dateId = uid('g-plan-date');
    const dateInput = h('input', { id: dateId, type: 'date', value: planState.date, required: true });
    const mealsBox = h('div', { class: 'checks four g-plan-meals' });
    for (const m of MEALS) {
      const id = `g-plan-meal-${m.key}`;
      const box = h('input', { type: 'checkbox', id, value: m.key });
      box.addEventListener('change', () => { planState.meals = $$('input:checked', mealsBox).map((x) => x.value); planState.variant = 0; runPlan(); });
      mealsBox.append(h('label', { class: 'check', for: id }, box, h('span', { class: 'check-text' }, m.label)));
    }
    const opts = h('div', { class: 'g-plan-options' });
    for (const [key, label, hint] of [
      ['use_saved_meals', 'Use my saved meals', 'Saved meals that fit, at full, ¾ or ½ size.'],
      ['use_usual', 'Use meals I often have', 'Combinations you logged on several of the last 60 days.'],
      ['use_starters', 'Use starter meals', 'The sample-day meals of the app’s diet guide.'],
    ]) {
      const id = `g-plan-${key}`;
      const box = h('input', { type: 'checkbox', id, 'aria-describedby': `${id}-hint` });
      box.checked = planState.options[key];
      box.addEventListener('change', () => { planState.options[key] = box.checked; planState.variant = 0; runPlan(); });
      opts.append(h('label', { class: 'check', for: id }, box, h('span', { class: 'check-text' }, label, h('span', { class: 'hint', id: `${id}-hint` }, hint))));
    }
    dateInput.addEventListener('change', () => {
      if (!/^\d{4}-\d{2}-\d{2}$/.test(dateInput.value)) return;
      planState.date = dateInput.value; planState.meals = null; planState.variant = 0; runPlan();
    });
    const out = h('div', { class: 'g-plan-out', id: 'g-plan-out' });
    const live = h('p', { class: 'sr-only', role: 'status', id: 'g-plan-status' });
    body.append(
      h('div', { class: 'field' }, h('label', { for: dateId }, 'Day'), dateInput),
      h('fieldset', { class: 'field' }, h('legend', {}, 'Meals to plan'), mealsBox,
        h('span', { class: 'hint' }, 'At first, every meal with nothing logged yet.')),
      h('details', { class: 'g-disclosure' }, h('summary', {}, 'Where ideas come from'), opts),
      live, out);
    const another = btn('Show another', 'secondary', () => { planState.variant = (planState.variant + 1) % (MAX_VARIANT + 1); runPlan(); }, { id: 'g-plan-another' });
    const use = btn('Use this plan', 'primary', (e) => applyPlan(e.currentTarget), { id: 'g-plan-use', disabled: true });
    foot.append(another, h('span', { class: 'spacer' }), use); // the header's × closes (no third button at 375 px)
    sheets.open(sheetEl, trigger, dateInput);
    runPlan();
    aiPlanButton(foot);
  }
  async function runPlan() {
    const out = $('#g-plan-out');
    if (!out) return;
    const reqId = ++planState.request;
    const body = { date: planState.date, variant: planState.variant, ...planState.options };
    if (planState.meals) {
      if (!planState.meals.length) {
        planState.result = null;
        clear(out).append(h('p', { class: 'empty-state' }, 'Tick at least one meal to plan.'));
        $('#g-plan-use').disabled = true;
        return;
      }
      body.meals = planState.meals;
    }
    out.setAttribute('aria-busy', 'true');
    $('#g-plan-use').disabled = true;
    clear(out).append(loadingNote('Planning…'));
    try {
      const key = `plan:${JSON.stringify(body)}`;
      const { data, at } = await remembered(key, () => api.planDay(body));
      if (reqId !== planState.request) return;
      noteAnswer(data);
      planState.result = data;
      planState.aiPicks = null;
      renderPlan(out, data, at);
    } catch (err) {
      if (reqId !== planState.request) return;
      planState.result = null;
      if (!err.handled) clear(out).append(failure(err));
      $('#g-plan-status').textContent = err.offline ? NEEDS_CONNECTION : 'The plan could not be made.';
    } finally {
      if (reqId === planState.request) out.removeAttribute('aria-busy');
    }
  }
  function renderPlan(out, res, at) {
    clear(out);
    const live = $('#g-plan-status');
    const use = $('#g-plan-use');
    const another = $('#g-plan-another');
    if (!res || res.status !== 'ok') {
      out.append(unavailable(res));
      live.textContent = res && res.message ? res.message : '';
      use.disabled = true; another.disabled = true;
      return;
    }
    another.disabled = !res.meals.length;
    // Reflect the slots the server planned (the first answer chooses them).
    if (!planState.meals) {
      const planned = new Set(res.meals.map((m) => m.meal));
      for (const m of MEALS) { const box = $(`#g-plan-meal-${m.key}`); if (box) box.checked = planned.has(m.key); }
    }
    const stale = staleNote(at);
    if (stale) out.append(stale);
    out.append(h('p', { class: 'hint' }, `${fmtDateLong(res.date)} · option ${res.variant + 1} of ${MAX_VARIANT + 1}`));
    if (!res.meals.length) {
      out.append(h('p', { class: 'empty-state' }, `Every meal of ${fmtDateLong(res.date)} already has food. Tick the meals you want planned anyway.`));
    }
    for (const m of res.meals) out.append(planMeal(m, !!(planState.aiPicks && m.meal in planState.aiPicks)));
    if (res.protein_topup && res.protein_topup.length) {
      out.append(h('p', { class: 'g-tip' }, `The protein portion at ${joinWords(res.protein_topup.map((x) => MEAL_LABEL[x].toLowerCase()))} was made larger to reach your daily protein minimum.`));
    }
    if (res.meals.length) {
      if (res.energy_note) out.append(energyNote(res.energy_note));
      out.append(dayAfter(res.day_after));
    }
    const n = notes(res.notes);
    if (n) out.append(n);
    const entries = (res.apply && res.apply.entries) || [];
    use.disabled = !entries.length || !!at;
    use.setAttribute('aria-label', entries.length ? `Use this plan: plan ${entries.length} ${entries.length === 1 ? 'food' : 'foods'} for ${fmtDateLong(res.date)}` : 'Use this plan');
    const okMeals = res.meals.filter((m) => m.status !== 'no_fit').length;
    live.textContent = !res.meals.length ? `Every meal of ${fmtDateLong(res.date)} already has food. Tick the meals to plan anyway.`
      : `Plan option ${res.variant + 1}: ${okMeals} of ${res.meals.length} ${res.meals.length === 1 ? 'meal' : 'meals'} planned, ${entries.length} ${entries.length === 1 ? 'food' : 'foods'}.`;
  }
  function joinWords(words) {
    if (words.length < 2) return words.join('');
    return `${words.slice(0, -1).join(', ')} and ${words[words.length - 1]}`;
  }
  const SOURCE_TEXT = { saved: 'Your saved meal', usual: 'A meal you often have', starter: 'Starter meal', built: 'Built from your foods' };
  function planMeal(m, aiPick = false) {
    const hid = uid('g-plan-h');
    const sec = h('section', { class: `g-plan-meal status-${m.status}`, 'aria-labelledby': hid });
    const source = m.source ? SOURCE_TEXT[m.source] || m.source : null;
    sec.append(h('div', { class: 'g-plan-head' },
      h('h3', { class: 'g-plan-title', id: hid }, MEAL_LABEL[m.meal], aiPick ? h('span', { class: 'g-ai-badge' }, 'AI’s pick') : null),
      source ? h('span', { class: 'g-source' }, m.name && m.source !== 'built' ? `${source}: ${m.name}` : source) : null));
    if (m.message) {
      sec.append(h('div', { class: `warning level-${m.status === 'no_fit' ? 'over' : 'caution'}` },
        ratingIcon(m.status === 'no_fit' ? 'over' : 'caution', { label: m.status === 'no_fit' ? 'Nothing fits' : 'Partly fits' }),
        h('div', {}, m.message)));
    }
    if (m.items && m.items.length) sec.append(portionList(m.items));
    if (m.totals) sec.append(h('p', { class: 'g-totals tabular' }, `Meal: ${keyNumbers(m.totals)}`));
    if (m.why && m.why.length) sec.append(list('g-why', m.why.map((w) => h('li', {}, w))));
    if (m.status === 'no_fit' && m.closest && m.closest.items && m.closest.items.length) {
      sec.append(h('p', { class: 'hint' }, 'The closest the app found (not part of the plan):'), portionList(m.closest.items));
    }
    return sec;
  }
  function portionList(items) {
    return list('compact-items g-portions', items.map((it) => h('li', {},
      ratingIcon(it.renal_rating || 'green'),
      h('span', { class: 'ci-name' }, it.name, h('span', { class: 'muted small' }, ` · ${it.portion_text}`)),
      h('span', { class: 'ci-amt muted tabular' }, it.nutrients && it.nutrients.carbs_g != null ? `${fmtNum(it.nutrients.carbs_g, 'carbs_g')} g carbs` : ''))));
  }
  function energyNote(e) {
    const box = h('div', { class: 'g-tip' }, h('p', {}, e.text));
    if (e.foods && e.foods.length) box.append(portionList(e.foods));
    const page = GE && GE.T && GE.T.TOPIC_PAGES[e.handbook];
    if (page) { const l = learnFor(page.url, page.title); if (l) box.append(l); }
    return box;
  }
  function dayAfter(d) {
    const hid = uid('g-after');
    const sec = h('section', { class: 'g-after', 'aria-labelledby': hid }, h('h3', { class: 'g-group-title', id: hid }, 'The day with this plan'));
    const rows = [];
    for (const k of DAY_KEYS) {
      const st = d && d.projected_status ? d.projected_status[k] : null;
      if (!st || st.target == null || !NUT[k]) continue;
      const pctText = `${Math.round((st.fraction || 0) * 100)} %`;
      rows.push(h('li', { class: 'g-after-row' },
        h('span', { class: 'g-after-label' }, NUT[k].label),
        h('span', { class: 'tabular' }, `${fmtNum(st.value, k)} of ${fmtNum(st.target, k)} ${NUT[k].unit} (${pctText})`),
        levelPill(st.level || 'ok', LEVEL_TEXT[st.level || 'ok'])));
    }
    if (rows.length) sec.append(list('g-after-list', rows));
    for (const a of (d && d.new_alerts) || []) {
      const lvl = a.level === 'over' ? 'over' : 'caution';
      sec.append(h('div', { class: `warning level-${lvl}` }, ratingIcon(lvl, { label: lvl === 'over' ? 'Over limit' : 'Near limit' }), h('div', {}, a.message)));
    }
    return sec;
  }
  async function applyPlan(b) {
    const res = planState.result;
    const entries = (res && res.apply && res.apply.entries) || [];
    if (!entries.length || planState.busy) return;
    planState.busy = true;
    b.disabled = true;
    // One client_id per item: a retry after a lost answer finds the entries already made (200 "existing").
    const withIds = entries.map((e) => ({ ...e, client_id: uuid() }));
    const date = res.date;
    try {
      let answer = null;
      for (let attempt = 0; attempt < 2 && !answer; attempt++) {
        try { answer = await api.logBatch(withIds); } catch (err) { if (err.status !== 0 || attempt) throw err; }
      }
      sheetEl.close();
      forgetAnswers();
      const n = answer && answer.entries ? answer.entries.length : withIds.length;
      toast(`Planned ${n} ${n === 1 ? 'food' : 'foods'} for ${fmtDateLong(date)}. Tap “Eaten” as you have them.`, 'ok');
      KH.views.plan.afterLogChange(date, { goToDay: state.view !== 'plan' });
    } catch (err) {
      if (!err.handled) {
        const out = $('#g-plan-out');
        if (out) out.prepend(h('p', { class: 'form-error', role: 'alert' }, `The plan was not saved: ${err.detail || err.message}`));
      }
    } finally {
      planState.busy = false;
      if (document.contains(b)) b.disabled = false;
    }
  }
  $('#btn-plan-day').addEventListener('click', (e) => {
    const start = state.planStart;
    const today = todayStr();
    // This week: today. Another week: its first day (the date field can change it).
    const date = !start || (today >= start && today <= addDays(start, 6)) ? today : start;
    openPlan({ date, trigger: e.currentTarget });
  });

  // ---- Treating a low (never blocked, never warned against, answers even with guidance off) -------
  async function openLow({ trigger = null } = {}) {
    const { body, foot } = fillSheet('low', 'Treating a low', 'What to do, and the foods in your list that treat a low.');
    const live = h('p', { class: 'sr-only', role: 'status' });
    const out = h('div', { class: 'g-low' }, loadingNote('Loading…'));
    body.append(live, out);
    foot.append(h('span', { class: 'spacer' }), closeButton());
    sheets.open(sheetEl, trigger, $('[data-close]', sheetEl));
    let res = null;
    let at = null;
    try {
      ({ data: res, at } = await remembered('hypo', () => api.hypoOptions()));
    } catch (err) {
      if (err.handled) return;
      res = null;
    }
    if (sheetEl.dataset.kind !== 'low') return;
    clear(out);
    if (!res) {
      // Offline (or an error): the card from the browser twin of the server's text, with the person's dose.
      const dose = Number(prefValue('hypo_dose_g', DEFAULT_HYPO_DOSE_G)) || DEFAULT_HYPO_DOSE_G;
      const card = GE && GE.M ? GE.M.treatingALowCard(dose) : null;
      if (card) out.append(lowCard(card));
      out.append(h('p', { class: 'g-offline', role: 'note' }, `${NEEDS_CONNECTION} Your own low-treatment foods show here when it is back.`));
      live.textContent = card ? `Treating a low: take ${dose} g of fast carbs.` : NEEDS_CONNECTION;
      return;
    }
    const stale = staleNote(at);
    if (stale) out.append(stale);
    out.append(lowCard(res.card));
    const opts = res.options || [];
    const hid = uid('g-low-opts');
    if (opts.length) {
      out.append(h('h3', { class: 'g-group-title', id: hid }, `Your low treatments for ${fmtNum(res.dose_g, 'carbs_g')} g of carbs`),
        list('g-foods', opts.map((o) => lowOption(o))));
    } else {
      out.append(h('p', { class: 'empty-state' }, 'None of your foods is marked as a low treatment. Glucose tablets, glucose gel or juice in the food list are; Quick add can mark your own.'));
    }
    const n = notes(res.notes);
    if (n) out.append(n);
    live.textContent = `Treating a low: take ${fmtNum(res.dose_g, 'carbs_g')} g of fast carbs. ${opts.length} ${opts.length === 1 ? 'option' : 'options'}.`;
  }
  function lowCard(card) {
    const hid = uid('g-lowcard');
    return h('section', { class: 'g-lowcard', 'aria-labelledby': hid },
      h('h3', { id: hid }, card.title),
      list('g-lowcard-lines', card.lines.map((line) => h('li', {}, line))),
      learnFor(card.url, card.title));
  }
  function lowOption(o) {
    const nameId = uid('g-low');
    const log = btn('Log it', 'secondary g-act', async (e) => {
      const b = e.currentTarget;
      b.disabled = true;
      const date = todayStr();
      const meal = defaultMealForNow();
      try {
        await KH.api.addEntry({ date, meal, food_id: o.food_id, servings: o.servings, status: 'eaten', purpose: 'hypo', client_id: uuid() });
        toast(`Logged ${o.name} (${o.portion_text}) as a low treatment`, 'ok');
        forgetAnswers();
        state.dayLoadedFor = null;
        if (state.view === 'today' && state.date === date) KH.views.today.loadDay();
      } catch (err) { toastError(err); }
      finally { if (document.contains(b)) b.disabled = false; }
    }, { 'aria-label': `Log ${o.name}, ${o.portion_text}, as a low treatment now` });
    return h('li', { class: 'g-food' },
      h('div', { class: 'g-food-main' }, ratingIcon(o.renal_rating || 'green', { decorative: true }),
        h('div', { class: 'g-food-text' },
          h('div', { class: 'row-title', id: nameId }, o.name),
          h('div', { class: 'row-sub' }, o.portion_text),
          h('div', { class: 'g-fit tabular' }, keyNumbers(o.nutrients)))),
      h('div', { class: 'g-actions' }, log));
  }

  // ---------------------------------------------------------------------------
  // Today: the "Meal ideas" card, a "What fits" link per meal, the low badge, end-of-day insights
  // ---------------------------------------------------------------------------
  const todayCard = $('#guidance-today');
  const insightsCard = $('#guidance-day-insights');
  let insightsRequest = 0;
  function firstOpenMeal(day) {
    const eaten = new Set((day.entries || []).map((e) => e.meal));
    const now = defaultMealForNow();
    if (!eaten.has(now)) return now;
    return MEALS.map((m) => m.key).find((k) => !eaten.has(k)) || now;
  }
  async function showToday(day) {
    await loadPrefs();
    const on = guidanceOn();
    if (!on) $$('#meals .g-whatfits').forEach((b) => b.remove()); // drawn before the settings had loaded
    const actions = clear($('#guidance-today-actions'));
    const date = day.date;
    const isPast = date < todayStr();
    const meal = firstOpenMeal(day);
    if (on && !isPast) {
      actions.append(btn(`What fits ${MEAL_LABEL[meal].toLowerCase()}`, 'secondary', () => goWhatFits(meal)));
      if (prefValue('show_plan_builder', true) !== false) {
        actions.append(btn(date === todayStr() ? 'Plan the rest of my day' : 'Plan this day', 'secondary', (e) => openPlan({ date, trigger: e.currentTarget })));
      }
    }
    if (hasDiabetes()) actions.append(btn('Treating a low', 'secondary g-low-btn', (e) => openLow({ trigger: e.currentTarget })));
    todayCard.hidden = !actions.childElementCount;
    $('#guidance-today-sub').textContent = on && !isPast ? 'From your own foods, within what is left of your targets' : '';
    showDayInsights(day, on);
  }
  function goWhatFits(meal) {
    state.addMealHint = meal;
    state.addStatusHint = null;
    router.show('add');
    setTimeout(() => { const r = $(`#gfm-${meal}`); if (r) r.focus(); }, 0);
  }
  function whatFitsButton(meal) {
    if (!guidanceOn()) return null;
    return h('button', { class: 'link-btn g-whatfits', type: 'button', onclick: () => goWhatFits(meal) }, 'What fits');
  }
  // The client decides when the day is "done" (§4.16): a past day, or today with every main meal
  // logged as eaten, or after 19:00 local time. A future day has no insights.
  function dayIsDone(day) {
    const today = todayStr();
    if (day.date < today) return true;
    if (day.date > today) return false;
    const eaten = new Set((day.entries || []).filter((e) => e.status !== 'planned').map((e) => e.meal));
    return MAIN_MEALS.every((m) => eaten.has(m)) || new Date().getHours() >= END_OF_DAY_HOUR;
  }
  async function showDayInsights(day, on) {
    const reqId = ++insightsRequest;
    const bodyEl = $('#guidance-day-insights-body');
    const hasEaten = (day.entries || []).some((e) => e.status !== 'planned');
    if (!on || prefValue('show_insights', true) === false || !hasEaten || !dayIsDone(day)) { insightsCard.hidden = true; return; }
    $('#guidance-day-insights-h').textContent = day.date === todayStr() ? 'How today went' : 'How this day went';
    try {
      const { data, at } = await remembered(`day:${day.date}:${day.counts ? `${day.counts.eaten}/${day.counts.planned}` : ''}`, () => api.insightsDay(day.date));
      if (reqId !== insightsRequest) return;
      noteAnswer(data);
      if (!data || data.status !== 'ok' || !(data.insights || []).length) { insightsCard.hidden = true; return; }
      clear(bodyEl);
      const stale = staleNote(at);
      if (stale) bodyEl.append(stale);
      bodyEl.append(insightList(data.insights));
      if (data.planned_excluded) {
        bodyEl.append(h('p', { class: 'hint' }, `${data.planned_excluded} planned ${data.planned_excluded === 1 ? 'food is' : 'foods are'} not counted until marked as eaten.`));
      }
      const n = notes(data.notes);
      if (n) bodyEl.append(n);
      $('#guidance-day-insights-sub').textContent = `${data.insights.length} ${data.insights.length === 1 ? 'note' : 'notes'}`;
      insightsCard.hidden = false;
    } catch (err) {
      if (reqId !== insightsRequest) return;
      insightsCard.hidden = true;
      if (!err.handled && !err.offline) console.warn('Day insights unavailable:', err.detail || err);
    }
  }
  function insightList(items) {
    return list('g-insights', items.map((it) => {
      const lvl = INSIGHT_LEVEL[it.severity] || 'info';
      const icon = lvl === 'info' ? infoIcon() : ratingIcon(lvl, { label: INSIGHT_WORD[it.severity] || 'Note' });
      const sources = (it.sources || []).length > 1 && !/came from|sources were/i.test(it.message)
        ? h('p', { class: 'hint' }, `Most from: ${it.sources.map((s) => `${s.short_name || s.name} ${s.share_pct} %`).join(', ')}`) : null;
      return h('li', { class: `g-insight level-${lvl}` }, icon,
        h('div', { class: 'g-insight-text' },
          h('span', { class: 'sr-only' }, `${INSIGHT_WORD[it.severity] || 'Note'}: `),
          h('p', {}, it.message), sources, learnLinks(it.handbook)));
    }));
  }
  function infoIcon() {
    return KH.s('svg', { class: 'rating g-info-icon', viewBox: '0 0 24 24', 'aria-hidden': 'true', focusable: 'false' },
      KH.s('circle', { class: 'shape', cx: 12, cy: 12, r: 11 }),
      KH.s('rect', { class: 'glyph', x: 10.9, y: 10, width: 2.2, height: 7.5, rx: 1 }),
      KH.s('circle', { class: 'glyph', cx: 12, cy: 6.9, r: 1.4 }));
  }
  // "treated a low" badge for Today's entry rows.
  function lowBadge(entry) {
    return entry && entry.purpose === 'hypo' ? h('span', { class: 'badge low' }, 'treated a low') : null;
  }

  // ---------------------------------------------------------------------------
  // Trends: insights for the chosen range (ending yesterday: today is not over yet)
  // ---------------------------------------------------------------------------
  const periodCard = $('#guidance-period');
  let periodRequest = 0;
  async function showTrends(days) {
    const reqId = ++periodRequest;
    await loadPrefs();
    if (!guidanceOn() || prefValue('show_insights', true) === false) { periodCard.hidden = true; return; }
    const end = addDays(todayStr(), -1);
    const start = addDays(end, -(days - 1));
    $('#guidance-period-sub').textContent = `${fmtRange(start, end)} · ${days} days ending yesterday`;
    const bodyEl = $('#guidance-period-body');
    try {
      const { data, at } = await remembered(`period:${start}:${end}`, () => api.insightsPeriod(start, end));
      if (reqId !== periodRequest) return;
      noteAnswer(data);
      clear(bodyEl);
      if (!data || data.status !== 'ok') {
        if (data && data.status === 'no_targets') { bodyEl.append(unavailable(data)); periodCard.hidden = false; } else periodCard.hidden = true;
        return;
      }
      const stale = staleNote(at);
      if (stale) bodyEl.append(stale);
      if (!data.logged_days) bodyEl.append(h('p', { class: 'empty-state' }, 'Nothing was logged as eaten in these days.'));
      else if (!(data.insights || []).length) bodyEl.append(h('p', { class: 'empty-state' }, `Nothing stood out on the ${data.logged_days} ${data.logged_days === 1 ? 'day' : 'days'} you logged.`));
      else bodyEl.append(insightList(data.insights));
      if (data.logged_days) bodyEl.append(h('p', { class: 'hint' }, `${data.logged_days} of ${data.days} days logged · compared with ${fmtDateShort(data.previous.start)} – ${fmtDateShort(data.previous.end)}`));
      const n = notes(data.notes);
      if (n) bodyEl.append(n);
      periodCard.hidden = false;
    } catch (err) {
      if (reqId !== periodRequest) return;
      clear(bodyEl);
      if (err.handled) { periodCard.hidden = true; return; }
      bodyEl.append(failure(err));
      periodCard.hidden = false;
    }
  }

  // ---------------------------------------------------------------------------
  // Entry sheet: "Used to treat a low", swap ideas, "For your next low" (js/views/add.js calls these)
  // ---------------------------------------------------------------------------
  const hypoRow = $('#entry-hypo-row');
  const hypoBox = $('#entry-hypo');
  const entryBox = $('#entry-guidance');
  const entryCtl = { ctx: null, opened: null, swapKey: null, request: 0, timer: null, details: null, mode: null };
  hypoBox.addEventListener('change', () => { if (entryCtl.onChange) entryCtl.onChange(); });

  // Called when the sheet opens (add or edit) and, with refresh, when the food of an edited entry has
  // loaded (then only the box's visibility changes, not what the person ticked). The box shows for a
  // low-treatment food, an entry stored as one, and anyone whose profile has diabetes.
  function entryOpen({ mode, food, entry, onChange, refresh = false }) {
    entryCtl.onChange = onChange;
    const isHypoFood = !!(food && (food.flags || []).includes('hypo_treatment'));
    const stored = !!(entry && entry.purpose === 'hypo');
    const visible = () => isHypoFood || stored || hasDiabetes();
    if (!refresh) {
      entryCtl.swapKey = null;
      entryCtl.details = null;
      entryCtl.mode = null;
      clear(entryBox);
      hypoBox.checked = mode === 'edit' ? stored : isHypoFood;
      entryCtl.opened = hypoBox.checked;
    }
    hypoRow.hidden = !visible();
    if (!state.profile) {
      KH.loadProfile().then(() => {
        if (hypoRow.hidden && visible()) { hypoRow.hidden = false; if (entryCtl.onChange) entryCtl.onChange(); }
      }).catch(() => null);
    }
  }
  function entryIsHypo() { return !hypoRow.hidden && hypoBox.checked; }
  // While "Used to treat a low" is ticked the sheet shows no warning colours (css: #sheet-entry[data-hypo]).
  function markHypo() { if (entryIsHypo()) $('#sheet-entry').dataset.hypo = 'true'; else delete $('#sheet-entry').dataset.hypo; }
  // The purpose to send: on add, whenever the box is shown ("none" overrides a low-treatment food's
  // default); on edit, only when the box changed.
  function entryPurpose(mode) {
    if (hypoRow.hidden) return undefined;
    if (mode === 'edit' && hypoBox.checked === entryCtl.opened) return undefined;
    return hypoBox.checked ? 'hypo' : 'none';
  }
  // A low treatment's numbers as plain information (never a warning; diet guide policy, note 06 F5).
  function entryHypoNote(box, scaled) {
    clear(box);
    const parts = [];
    if (scaled.carbs_g != null) parts.push(`${fmtNum(scaled.carbs_g, 'carbs_g')} g carbs`);
    for (const k of ['potassium_mg', 'phosphorus_mg', 'sodium_mg', 'fluid_ml']) if (scaled[k]) parts.push(`${fmtNum(scaled[k], k)} ${NUT[k].unit} ${NUT[k].label.toLowerCase()}`);
    box.append(h('div', { class: 'g-hypo-note', role: 'note' },
      h('p', {}, h('b', {}, 'Treating a low comes first. '), 'This counts toward today’s totals but never toward your meal carbs.'),
      parts.length ? h('p', { class: 'tabular' }, `This amount: ${parts.join(' · ')}.`) : null));
  }
  function swapLabel(nutrients, avoid) {
    if (avoid) return 'Ideas instead of this food';
    const words = [...new Set(nutrients.map((k) => SWAP_NUTRIENTS[k]).filter(Boolean))];
    if (!words.length) return 'Swap ideas';
    return `Lower-${words.join(', lower-').replace(/, (lower-[a-z]+)$/, ' and $1')} ideas`;
  }
  // After every preview update: decide what the box below the warnings shows.
  function entryUpdate(c) {
    markHypo();
    if (!guidanceOn() || !c.food) { clear(entryBox); entryCtl.details = null; entryCtl.mode = null; return; }
    if (entryIsHypo()) { ensureDisclosure('hypo', 'For your next low', c); return; }
    const nutrients = (c.warnings || []).filter((w) => w.level && SWAP_NUTRIENTS[w.nutrient]).map((w) => w.nutrient);
    const avoid = (c.warnings || []).some((w) => w.flag === 'avoid_ckd' || w.nutrient === 'avoid_ckd');
    const flagged = (c.warnings || []).some((w) => SWAP_FLAGS.has(w.flag));
    if (flagged && !nutrients.includes('phosphorus_mg') && (c.warnings || []).some((w) => w.flag === 'phosphate_additive')) nutrients.push('phosphorus_mg');
    if (!nutrients.length && !avoid && !flagged && !(c.impact || []).length) { clear(entryBox); entryCtl.details = null; entryCtl.mode = null; return; }
    ensureDisclosure('normal', swapLabel(nutrients, avoid), c);
  }
  function ensureDisclosure(mode, label, c) {
    entryCtl.ctx = c;
    if (entryCtl.mode !== mode || !entryCtl.details) {
      clear(entryBox);
      const out = h('div', { class: 'g-swaps' });
      const live = h('p', { class: 'sr-only', role: 'status' });
      const summary = h('summary', {}, label);
      const det = h('details', { class: 'g-disclosure' }, summary, live, out);
      det.addEventListener('toggle', () => { if (det.open) loadSwaps(); });
      entryBox.append(det);
      entryCtl.details = { det, out, live, summary };
      entryCtl.mode = mode;
      entryCtl.swapKey = null;
    } else {
      entryCtl.details.summary.textContent = label;
    }
    if (entryCtl.details.det.open) {
      clearTimeout(entryCtl.timer);
      entryCtl.timer = setTimeout(loadSwaps, 350);
    }
  }
  function swapParams(c) {
    const purpose = entryIsHypo() ? 'hypo' : 'none';
    const unchanged = c.mode === 'edit' && c.entry && !c.amountTouched && c.meal === c.entry.meal;
    if (unchanged) return { entry_id: c.entry.id, purpose };
    const p = { food_id: c.food.id, meal: c.meal, date: c.date, purpose };
    if (c.lastEdited === 'grams' && c.grams > 0) p.grams = c.grams; else p.servings = c.servings > 0 ? c.servings : 1;
    return p;
  }
  async function loadSwaps() {
    const d = entryCtl.details;
    const c = entryCtl.ctx;
    if (!d || !c) return;
    const params = swapParams(c);
    const key = JSON.stringify(params);
    if (key === entryCtl.swapKey) return;
    entryCtl.swapKey = key;
    const reqId = ++entryCtl.request;
    d.out.setAttribute('aria-busy', 'true');
    clear(d.out).append(loadingNote('Looking through your foods…'));
    try {
      const { data, at } = await remembered(`swaps:${key}`, () => api.swaps(params));
      if (reqId !== entryCtl.request) return;
      noteAnswer(data);
      renderSwaps(d, data, at, c);
    } catch (err) {
      if (reqId !== entryCtl.request) return;
      entryCtl.swapKey = null;
      if (!err.handled) clear(d.out).append(failure(err));
      d.live.textContent = err.offline ? NEEDS_CONNECTION : 'Swap ideas could not load.';
    } finally {
      if (reqId === entryCtl.request) d.out.removeAttribute('aria-busy');
    }
  }
  function renderSwaps(d, res, at, c) {
    const out = clear(d.out);
    if (!res || res.status !== 'ok') { out.append(unavailable(res, { compact: true })); d.live.textContent = res && res.message ? res.message : ''; return; }
    const stale = staleNote(at);
    if (stale) out.append(stale);
    if (res.mode === 'hypo' && res.card) out.append(lowCard(res.card));
    const swaps = res.swaps || [];
    if (swaps.length) {
      out.append(list('g-foods g-swap-list', swaps.map((s) => swapRow(s, res, c))));
      const ai = res.mode === 'normal' ? aiSwapBlock(c, res) : null;
      if (ai) out.append(ai);
    } else if (res.reason === 'no_warning') {
      out.append(h('p', { class: 'hint' }, 'Nothing in this amount needs a swap for this meal.'));
    } else if (res.mode !== 'hypo') {
      out.append(h('p', { class: 'hint' }, 'No swap from your foods keeps the same carbs or protein with less of this.'));
    }
    if (res.portion_option && res.mode !== 'hypo') {
      const po = res.portion_option;
      const use = btn('Use this amount', 'secondary g-act', () => KH.views.add.setServings(po.servings),
        { 'aria-label': `Use this amount: ${po.text}` });
      out.append(h('div', { class: 'g-portion' }, h('p', {}, po.text), use));
    }
    for (const tip of res.tips || []) {
      if (res.mode === 'hypo' && tip.handbook === 'treating-a-low' && res.card) continue; // the card above says it
      out.append(h('div', { class: 'g-tip' }, h('p', {}, tip.text), learnFor(tip.url, tipTitle(tip))));
    }
    const n = notes(res.notes);
    if (n) out.append(n);
    d.live.textContent = res.mode === 'hypo'
      ? `${swaps.length} ${swaps.length === 1 ? 'option' : 'options'} for your next low.`
      : `${swaps.length} swap ${swaps.length === 1 ? 'idea' : 'ideas'}${res.portion_option ? ' and a smaller portion' : ''}.`;
  }
  function swapRow(s, res, c) {
    const nameId = uid('g-swap');
    const row = h('li', { class: 'g-food' },
      h('div', { class: 'g-food-main' }, ratingOf(s),
        h('div', { class: 'g-food-text' }, h('div', { class: 'row-title', id: nameId }, s.name), h('div', { class: 'g-reason' }, s.text))));
    // On a new entry the swap can replace the food in the sheet; an entry already saved keeps its food
    // (the ideas are for next time) — delete it and add the other food to change it.
    if (c.mode === 'add' && res.mode !== 'hypo') {
      row.append(h('div', { class: 'g-actions' }, btn('Use this instead', 'secondary g-act', async (e) => {
        const b = e.currentTarget;
        b.disabled = true;
        try {
          const food = await KH.api.food(s.food_id);
          KH.views.add.openEntrySheet('add', { food, meal: c.meal, servings: s.servings, status: c.status, trigger: $('#sheet-entry')._returnFocus || null });
          toast(`Switched to ${s.name} (${s.portion_text})`, 'ok');
        } catch (err) { toastError(err); if (document.contains(b)) b.disabled = false; }
      }, { 'aria-label': `Use ${s.name}, ${s.portion_text}, instead` })));
    }
    return row;
  }

  // ---------------------------------------------------------------------------
  // Settings → Meal guidance (the person's "guidance" object and the "Not for me" list)
  // ---------------------------------------------------------------------------
  // "Let AI re-order and explain" (guidance.ai_enrich, note 04): shown when this server offers AI.
  function aiEnrichRow(check) {
    const slot = h('div', { class: 'g-ai-setting' });
    if (KH.ai && typeof KH.ai.status === 'function') {
      KH.ai.status().then((st) => {
        if (!st || !st.enabled || !document.contains(slot)) return;
        slot.append(check('ai_enrich', 'Let AI re-order and explain suggestions',
          'Adds “AI order”, “Ask AI to pick” and “Let AI choose” next to the app’s own suggestions, once AI ideas are on in Settings → AI ideas. The app still checks every number.'));
      }).catch(() => null);
    }
    return slot;
  }
  async function renderSettings() {
    const body = $('#set-guidance-body');
    if (!body) return;
    clear(body).append(loadingNote('Loading…'));
    const [item, nfm, cats] = await Promise.allSettled([loadPrefs(true), api.notForMe(), KH.api.categories()]);
    clear(body);
    const setting = item.status === 'fulfilled' ? item.value : null;
    if (!setting) { body.append(h('p', { class: 'form-error' }, 'Your guidance settings could not load.')); return; }
    const v = { ...(KH.settings.BY_KEY.guidance ? KH.settings.BY_KEY.guidance.default : {}), ...(setting.value || {}) };
    const locked = setting.editable === false;
    const msg = h('p', { class: 'status-msg', id: 'set-guidance-msg', role: 'status', 'aria-live': 'polite' });
    const err = h('div', { class: 'form-error', role: 'alert', id: 'set-guidance-error' });
    const save = async (patch, control) => {
      clear(err);
      KH.forms.clearFieldErrors(body);
      const next = { ...v, ...patch };
      try {
        const res = await KH.api.updateMySettings({ guidance: next });
        prefsCache = { item: res.settings.guidance };
        Object.assign(v, res.settings.guidance.value);
        forgetAnswers();
        msg.textContent = 'Saved.';
        return true;
      } catch (e) {
        if (e.handled) return false;
        const parts = KH.forms.splitFieldErrors(String(e.detail || e.message).replace(/^guidance: /, ''));
        let shown = false;
        for (const p of parts) {
          const field = p.field && $(`#set-g-${p.field.split('.')[0].replace(/_/g, '-')}`, body);
          if (field) { KH.forms.fieldError(field, p.message); shown = true; }
        }
        if (!shown) err.append(h('p', {}, e.detail || e.message));
        if (control && control.focus) control.focus();
        return false;
      }
    };
    const check = (key, label, hint) => {
      const id = `set-g-${key.replace(/_/g, '-')}`;
      const box = h('input', { type: 'checkbox', id, 'aria-describedby': hint ? `${id}-hint` : null });
      box.checked = v[key] !== false;
      box.disabled = locked;
      box.addEventListener('change', async () => {
        box.disabled = true;
        const ok = await save({ [key]: box.checked }, box);
        if (!ok) box.checked = !box.checked;
        box.disabled = locked;
      });
      return h('label', { class: 'check', for: id }, box, h('span', { class: 'check-text' }, label, hint ? h('span', { class: 'hint', id: `${id}-hint` }, hint) : null));
    };
    const number = (key, label, hint, min, max) => {
      const id = `set-g-${key.replace(/_/g, '-')}`;
      const input = h('input', { id, type: 'number', inputmode: 'numeric', min, max, step: 1, 'aria-describedby': `${id}-hint` });
      input.value = String(v[key]);
      input.disabled = locked;
      const saveBtn = btn('Save', 'secondary', async () => {
        KH.forms.clearFieldErrors(body);
        const n = Number(input.value);
        if (input.value.trim() === '' || !Number.isInteger(n) || n < min || n > max) {
          KH.forms.fieldError(input, `Enter a whole number from ${min} to ${max}.`);
          input.focus();
          return;
        }
        saveBtn.disabled = true;
        await save({ [key]: n }, input);
        saveBtn.disabled = false;
      }, { hidden: locked, 'aria-label': `Save: ${label}` });
      input.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); saveBtn.click(); } });
      return h('div', { class: 'field' }, h('label', { for: id }, label), h('div', { class: 'inline-row' }, input, saveBtn),
        h('span', { class: 'hint', id: `${id}-hint` }, hint));
    };
    body.append(
      h('p', { class: 'hint' }, 'Suggestions use only your own food list and the targets in your profile. They never suggest insulin or medicine doses.'),
      check('enabled', 'Show meal guidance', '“What fits now”, swap ideas, the plan builder and insights. Treating a low is always available.'),
      check('show_plan_builder', 'Show “Plan the rest of my day”'),
      check('show_insights', 'Show insights on Today and Trends'),
      aiEnrichRow(check),
      number('carb_tolerance_g', 'How close to my meal carb goal counts as on target (g)', 'Ask your diabetes team. 5 to 20 g; the app uses 10 g if you are not sure.', 5, 20),
      number('hypo_dose_g', 'Carbs I take to treat a low (g)', 'The amount your diabetes team gave you, 5 to 30 g. Low-treatment options are sized to it.', 5, 30));
    // Never suggest (categories)
    const catList = cats.status === 'fulfilled' ? cats.value.categories || [] : [];
    if (catList.length) {
      const excluded = new Set(v.exclude_categories || []);
      const fs = h('fieldset', { class: 'field', id: 'set-g-exclude-categories', 'aria-describedby': 'set-g-exclude-hint' },
        h('legend', {}, 'Never suggest these kinds of food'), h('span', { class: 'hint', id: 'set-g-exclude-hint' }, 'They stay in search and can still be logged.'));
      const grid = h('div', { class: 'checks' });
      catList.forEach((cat, i) => {
        const id = `set-g-cat-${i}`;
        const box = h('input', { type: 'checkbox', id, value: cat });
        box.checked = excluded.has(cat);
        box.disabled = locked;
        box.addEventListener('change', async () => {
          box.disabled = true;
          const chosen = $$('input:checked', grid).map((x) => x.value);
          const ok = await save({ exclude_categories: chosen }, box);
          if (!ok) box.checked = !box.checked;
          box.disabled = locked;
        });
        grid.append(h('label', { class: 'check', for: id }, box, h('span', { class: 'check-text' }, cat)));
      });
      fs.append(grid);
      body.append(fs);
    }
    const src = KH.settings.SOURCE_LABEL[setting.source] || setting.source || '';
    body.append(h('span', { class: `setting-source src-${setting.source}` }, src), msg, err);
    // Not for me
    body.append(h('h3', { class: 'settings-subtitle', id: 'set-g-nfm-h' }, '“Not for me” foods'));
    const nfmList = list('list g-nfm-list', []);
    nfmList.setAttribute('aria-labelledby', 'set-g-nfm-h');
    const fill = (data) => {
      clear(nfmList);
      const foods = (data && data.foods) || [];
      if (!foods.length) nfmList.append(h('li', { class: 'empty-state' }, 'None. Use “⋯ → Not for me” on a suggestion to hide a food from guidance.'));
      for (const f of foods) {
        const rm = btn('Suggest again', 'secondary g-act', async () => {
          rm.disabled = true;
          try {
            await api.removeNotForMe(f.food_id);
            forgetAnswers();
            fill(await api.notForMe());
            msg.textContent = `${f.name} can be suggested again.`;
            const first = $('button', nfmList);
            (first || $('#set-g-nfm-h')).focus();
          } catch (e) { toastError(e); rm.disabled = false; }
        }, { 'aria-label': `Suggest ${f.name} again` });
        nfmList.append(h('li', { class: 'g-nfm' }, h('div', { class: 'row-main' }, h('div', { class: 'row-title' }, f.name), h('div', { class: 'row-sub' }, f.category || '')), rm));
      }
      if (data && foods.length) nfmList.append(h('li', { class: 'hint g-nfm-count' }, `${foods.length} of ${data.limit} foods`));
    };
    if (nfm.status === 'fulfilled') fill(nfm.value);
    else nfmList.append(h('li', { class: 'form-error' }, 'The list could not load.'));
    body.append(nfmList);
  }

  // ---------------------------------------------------------------------------
  // Wiring
  // ---------------------------------------------------------------------------
  KH.guidance = {
    api,
    uuid,
    loadPrefs,
    forgetAnswers,
    add: showAdd,
    reloadFits: () => { if (fits.meal && state.view === 'add') loadFits(); },
    today: showToday,
    trends: showTrends,
    whatFitsButton,
    lowBadge,
    openPlan,
    openLow,
    renderSettings,
    entry: { open: entryOpen, update: entryUpdate, isHypo: entryIsHypo, purpose: entryPurpose, renderHypoNote: entryHypoNote },
    dayIsDone,
  };
})();
