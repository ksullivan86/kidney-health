/* Kidney Diet Log — "Add this menu day to my plan": reading a link from the handbook (v0.4; ROADMAP, note 08 §4.10).

   Each generated menu day in the handbook has a plain link to the app:

       #plan-menu?items=b173905x1,b167755x0.5,l170187x1,s173944x0.6667

   The list holds only built-in food references and amounts, nothing else: `<meal><fdc_id>x<servings>`, with the
   meal as one letter (b breakfast, l lunch, d dinner, s snack). It carries no name of a person, no date and no
   number the app would trust: the app looks every food up in its own list of built-in foods (GET /api/foods/builtin)
   and works out every nutrient and total itself. scripts/build_handbook.py writes the link (menu_plan_items);
   this file reads it. The link is untrusted input, so the reading is strict:

   * the whole link is refused when it is longer than MAX_LINK_CHARS, holds characters outside [A-Za-z0-9.,_-]
     after `items=`, has any other query parameter, has no entry, or has more than MAX_ITEMS entries;
   * an entry that is not understood is listed as skipped with the reason and never added: a meal letter that
     is not b, l, d or s, an amount that is not above 0 and at most MAX_SERVINGS (the app's own limit for one
     entry) with at most 4 decimals, an empty entry, or the same meal and food twice (the first one is kept);
   * a food reference is only ever resolved against built-in foods (source "builtin"): a custom food, a food
     another person scanned or imported, or an unknown number is skipped with a reason and its name is never
     looked up or shown.

   Pure functions, no DOM, no I/O. Nothing here saves anything: js/views/menuplan.js shows the confirmation sheet
   and posts POST /api/log/batch only when the person presses "Add to plan".
   Tests: tests/data/menu_link_vectors.json (node tests/js/run_vectors.mjs) and tests/test_menu_plan.py.

   Exposes KH.menuLink = { ROUTE, MAX_ITEMS, MAX_LINK_CHARS, MAX_SERVINGS, MEALS, isLink, parse, resolve, batchEntries,
   encode }. */
(() => {
  'use strict';
  const root = typeof window !== 'undefined' ? window : globalThis;
  const KH = root.KH || (root.KH = {});

  const ROUTE = 'plan-menu';
  const MAX_ITEMS = 40; // POST /api/log/batch takes at most 40 entries (app/models.py MAX_LOG_BATCH)
  const MAX_LINK_CHARS = 1500; // 40 entries are about 600 characters
  const MAX_SERVINGS = 1000; // app/models.py MAX_SERVINGS: servings of one food in one entry
  const MEALS = { b: 'breakfast', l: 'lunch', d: 'dinner', s: 'snack' };
  const MEAL_ORDER = ['breakfast', 'lunch', 'dinner', 'snack'];
  const PREFIX = `#${ROUTE}?items=`;
  const VALUE_CHARS = /^[A-Za-z0-9.,_-]*$/;
  const TOKEN = /^([A-Za-z])([0-9]{1,9})x([0-9]{1,4}(?:\.[0-9]{1,4})?)$/;

  // True for a hash that is meant for this module (even a broken one: parse() says what is wrong).
  function isLink(hash) {
    return typeof hash === 'string' && (hash === `#${ROUTE}` || hash.startsWith(`#${ROUTE}?`));
  }

  // The text shown for an entry that was not understood: only safe characters, cut short.
  function shown(token) {
    const t = String(token);
    return t.length > 30 ? `${t.slice(0, 29)}…` : t;
  }

  // -> { ok: false, error } | { ok: true, items: [{ meal, fdc_id, servings }], skipped: [{ text, reason }] }
  function parse(hash) {
    if (typeof hash !== 'string' || !isLink(hash)) return { ok: false, error: 'This is not a menu link.' };
    if (hash.length > MAX_LINK_CHARS) return { ok: false, error: 'This link is too long to be a menu day.' };
    if (!hash.startsWith(PREFIX)) return { ok: false, error: 'The app does not understand this menu link.' };
    const value = hash.slice(PREFIX.length);
    if (!VALUE_CHARS.test(value)) return { ok: false, error: 'The app does not understand this menu link.' };
    if (!value) return { ok: false, error: 'This menu link has no foods in it.' };
    const tokens = value.split(',');
    if (tokens.length > MAX_ITEMS) return { ok: false, error: `This link has more than ${MAX_ITEMS} foods, more than a menu day has.` };
    const items = [];
    const skipped = [];
    const seen = new Set();
    for (const token of tokens) {
      if (!token) { skipped.push({ text: '(empty)', reason: 'an empty entry' }); continue; }
      const m = TOKEN.exec(token);
      if (!m) { skipped.push({ text: shown(token), reason: 'not a food and an amount the app understands' }); continue; }
      const meal = MEALS[m[1]];
      if (!meal) { skipped.push({ text: shown(token), reason: 'not a meal the app knows (breakfast, lunch, dinner or snack)' }); continue; }
      const fdcId = Number(m[2]);
      const servings = Number(m[3]);
      if (!(fdcId >= 1)) { skipped.push({ text: shown(token), reason: 'not a built-in food number' }); continue; }
      if (!(servings > 0 && servings <= MAX_SERVINGS)) {
        skipped.push({ text: shown(token), reason: `an amount that is not above 0 and at most ${MAX_SERVINGS} servings` });
        continue;
      }
      const key = `${meal}:${fdcId}`;
      if (seen.has(key)) { skipped.push({ text: shown(token), reason: 'the same food is listed twice for this meal (the first one is kept)' }); continue; }
      seen.add(key);
      items.push({ meal, fdc_id: fdcId, servings });
    }
    return { ok: true, items, skipped };
  }

  // Match the entries with the app's built-in foods (the answer of GET /api/foods/builtin, or any list of foods).
  // Only a food with source "builtin" and that fdc_id counts; nothing else is ever looked up or shown.
  // -> { rows: [{ meal, fdc_id, servings, food }], skipped: [{ text, reason }] }, rows in meal order.
  function resolve(items, foods) {
    const byFdc = new Map();
    for (const f of Array.isArray(foods) ? foods : []) {
      if (f && f.source === 'builtin' && !f.hidden && Number.isInteger(f.fdc_id) && !byFdc.has(f.fdc_id)) byFdc.set(f.fdc_id, f);
    }
    const rows = [];
    const skipped = [];
    for (const it of items) {
      const food = byFdc.get(it.fdc_id);
      if (!food) { skipped.push({ text: `food ${it.fdc_id}`, reason: 'not one of the app\'s built-in foods' }); continue; }
      rows.push({ meal: it.meal, fdc_id: it.fdc_id, servings: it.servings, food });
    }
    rows.sort((a, b) => MEAL_ORDER.indexOf(a.meal) - MEAL_ORDER.indexOf(b.meal)); // stable: the link's order inside a meal
    return { rows, skipped };
  }

  // The body of POST /api/log/batch for the rows the person kept: planned entries on `date`, one client_id each
  // (made once per confirmation sheet, so pressing the button twice, or again after a lost answer, adds nothing twice).
  function batchEntries(rows, date, newId) {
    return rows.map((r) => ({
      date, meal: r.meal, food_id: r.food.id, servings: r.servings, status: 'planned', client_id: r.client_id || newId(),
    }));
  }

  // The link text for a list of { meal, fdc_id, servings } (the Python build writes the same form).
  function encode(items) {
    const code = Object.fromEntries(Object.entries(MEALS).map(([k, v]) => [v, k]));
    const fmt = (n) => String(Math.round(n * 10000) / 10000);
    return `${PREFIX}${items.map((i) => `${code[i.meal]}${i.fdc_id}x${fmt(i.servings)}`).join(',')}`;
  }

  KH.menuLink = { ROUTE, MAX_ITEMS, MAX_LINK_CHARS, MAX_SERVINGS, MEALS, isLink, parse, resolve, batchEntries, encode };
})();
