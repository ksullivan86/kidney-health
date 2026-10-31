/* Kidney Diet Log — Plan → Import a recipe (design note 30 §3; app/recipe_import/api.py).

   Step 1: a recipe page's link (only when the server reads pages: GET /api/recipe-import says `web`), or pasted ingredients
   with a name and how many servings it makes. The server reads the page (never the browser) and answers a draft.
   Step 2: every ingredient line with the food the app chose, its amount in servings, and a "Checked" box. The person can choose
   another of the suggestions, search for another food, or leave a line out. Save stays off until every line is checked. One
   serving's key numbers and kidney warnings are worked out here from the chosen foods, as the saved-meal editor does: a food that
   does not list a nutrient makes the figure "at least" (or "not listed"), never 0. The estimate sentence is always shown. Lines
   left out go into the recipe's note. Saving is the ordinary POST /api/meals with the page's link, so every rule runs again.
   A food marked as a low treatment stays one, as in any saved meal; nothing here warns against it.

   KH.recipeImportView.open({ trigger, onSaved }) (KH.recipeImport is the parser, js/engine/recipe_import.js). The demo answers any link with its sample page (js/mock/lists.js).
   All text goes in with h() children (textContent), never as HTML. */
(() => {
  'use strict';
  const KH = window.KH;
  const { h, $, clear, request, api, toast, toastError, sheets } = KH;
  const { NUT, NUTRIENTS, fmtNum, evaluateWarnings } = KH.rules;
  const { KEY_NUMBERS, ratingIcon, renderWarnings, foodsNotListing, atLeast, atLeastWords } = KH.ui;
  const { debounce } = KH.util;

  const A = {
    info: () => request('GET', '/api/recipe-import', undefined, { noQueue: true }),
    page: (url) => request('POST', '/api/recipe-import/page', { url }, { noQueue: true }),
    text: (body) => request('POST', '/api/recipe-import/text', body, { noQueue: true }),
  };
  const ADDITIVE_FLAGS = ['phosphate_additive', 'potassium_additive'];
  const NOTE_MAX = 1000;

  const dlg = $('#sheet-recipe-import');
  if (!dlg) return;
  sheets.setup(dlg);
  const st = { step: 'source', info: null, draft: null, rows: [], onSaved: null, busy: false, search: 0 };

  function goButton(text, disabled = false) { const b = $('#recipe-import-go'); b.textContent = text; b.disabled = disabled; }

  async function open({ trigger, onSaved } = {}) {
    st.onSaved = onSaved || null;
    st.draft = null; st.rows = [];
    try { st.info = await A.info(); } catch (e) { st.info = { web: false, estimate: '' }; }
    showSource();
    sheets.open(dlg, trigger, st.info.web ? $('#ri-url') : $('#ri-text'));
  }

  // ---------------------------------------------------------------------------
  // Step 1: where the recipe comes from
  // ---------------------------------------------------------------------------
  function showSource() {
    st.step = 'source';
    $('#recipe-import-back').hidden = true;
    $('#sheet-recipe-import-sub').textContent = 'From a recipe page, or from ingredients you paste.';
    const body = clear($('#recipe-import-body'));
    if (st.info.web) {
      const url = h('input', { id: 'ri-url', type: 'url', inputmode: 'url', maxlength: 900, autocomplete: 'off', placeholder: 'https://…',
        'aria-describedby': 'ri-url-hint' });
      const read = h('button', { class: 'btn secondary', type: 'button', id: 'ri-read-page' }, 'Read the page');
      read.addEventListener('click', () => readPage(url.value.trim(), read));
      url.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); readPage(url.value.trim(), read); } });
      body.append(h('div', { class: 'field' }, h('label', { for: 'ri-url' }, 'Recipe page link'), h('div', { class: 'search-row' }, url, read),
        h('span', { class: 'hint', id: 'ri-url-hint' }, 'This server opens the page and reads its recipe data. Nothing about you is sent. The page itself is not kept.')),
      h('p', { class: 'muted' }, 'Or paste the ingredients:'));
    } else {
      body.append(h('p', { class: 'hint', id: 'ri-no-web' }, 'Reading recipe pages is off on this server. Paste the ingredients instead.'));
    }
    body.append(
      h('div', { class: 'field' }, h('label', { for: 'ri-text' }, 'Ingredients'),
        h('textarea', { id: 'ri-text', rows: 6, maxlength: 20000, placeholder: '1 lb chicken breast\n2 cups cooked rice\n1 tbsp olive oil', 'aria-describedby': 'ri-text-hint' }),
        h('span', { class: 'hint', id: 'ri-text-hint' }, 'One ingredient on each line, with its amount. Nothing leaves this server.')),
      h('div', { class: 'form-grid' },
        h('div', { class: 'field' }, h('label', { for: 'ri-name' }, 'Recipe name'), h('input', { id: 'ri-name', type: 'text', maxlength: 200, placeholder: 'Optional' })),
        h('div', { class: 'field' }, h('label', { for: 'ri-makes' }, 'Makes (servings)'),
          h('input', { id: 'ri-makes', type: 'number', inputmode: 'decimal', min: 0.25, max: 100, step: 0.25, placeholder: '1' }))));
    goButton('Read ingredients');
  }

  async function readPage(url, btn) {
    if (!url) { toast('Paste the link of a recipe page', 'error'); $('#ri-url').focus(); return; }
    if (st.busy) return;
    st.busy = true; btn.disabled = true; btn.textContent = 'Reading…';
    try { showReview(await A.page(url)); } catch (err) { if (!err.handled) toastError(err); } finally { st.busy = false; btn.disabled = false; btn.textContent = 'Read the page'; }
  }
  async function readText() {
    const text = $('#ri-text').value.trim();
    if (!text) { toast('Paste the ingredients, one on each line', 'error'); $('#ri-text').focus(); return; }
    const makes = Number($('#ri-makes').value);
    const body = { text, name: $('#ri-name').value.trim() || null };
    if ($('#ri-makes').value.trim()) {
      if (!(makes > 0 && makes <= 100)) { toast('Makes is a number of servings from 0.25 to 100', 'error'); $('#ri-makes').focus(); return; }
      body.servings = makes;
    }
    st.busy = true; goButton('Reading…', true);
    try { showReview(await A.text(body)); } catch (err) { if (!err.handled) toastError(err); goButton('Read ingredients'); } finally { st.busy = false; }
  }

  // ---------------------------------------------------------------------------
  // Step 2: check every line
  // ---------------------------------------------------------------------------
  function showReview(draft) {
    st.step = 'review';
    st.draft = draft;
    st.rows = draft.lines.map((line) => {
      const first = line.matches[0];
      return { line, options: line.matches.map((m) => m.food), choice: first ? 0 : 'skip',
        servings: first && first.servings != null ? first.servings : null, checked: false };
    });
    $('#recipe-import-back').hidden = false;
    $('#sheet-recipe-import-sub').textContent = draft.source_url ? 'From a recipe page' : 'From your pasted ingredients';
    const body = clear($('#recipe-import-body'));
    body.append(
      h('div', { class: 'form-grid' },
        h('div', { class: 'field' }, h('label', { for: 'ri-review-name' }, 'Name ', h('span', { class: 'req', 'aria-hidden': 'true' }, '*')),
          h('input', { id: 'ri-review-name', type: 'text', maxlength: 200, required: true, value: draft.name || '' })),
        h('div', { class: 'field' }, h('label', { for: 'ri-review-makes' }, 'Makes (servings)'),
          h('input', { id: 'ri-review-makes', type: 'number', inputmode: 'decimal', min: 0.25, max: 100, step: 0.25, value: draft.servings_made != null ? String(draft.servings_made) : '', placeholder: '1' }))),
      draft.source_url ? h('p', { class: 'hint', id: 'ri-source' }, `Link kept with the recipe: ${draft.source_url}`) : null,
      h('p', { class: 'notice', id: 'ri-notice' }, draft.notice),
      draft.lines_cut ? h('p', { class: 'hint' }, `Only the first ${draft.lines.length} ingredient lines were read.`) : null,
      h('ul', { class: 'list ri-lines', id: 'ri-lines', 'aria-label': 'Ingredients to check' }),
      h('div', { class: 'preview' }, h('div', { class: 'preview-head' }, h('h3', { class: 'preview-title' }, 'One serving'), h('span', { class: 'muted small', id: 'ri-count' })),
        h('div', { id: 'ri-key', class: 'key-numbers' }), h('p', { class: 'hint', id: 'ri-left-out' }), h('div', { id: 'ri-warnings', class: 'warnings' })),
      h('p', { class: 'hint ri-estimate', id: 'ri-estimate' }, draft.estimate),
      draft.steps.length ? h('details', { id: 'ri-steps' }, h('summary', {}, `${draft.steps.length} cooking ${draft.steps.length === 1 ? 'step' : 'steps'} from the page`),
        h('ol', {}, ...draft.steps.map((s) => h('li', {}, s))),
        draft.steps_cut ? h('p', { class: 'hint' }, 'The page had more than 20 steps; the rest were left out.') : null) : null);
    $('#ri-review-name').addEventListener('input', update);
    $('#ri-review-makes').addEventListener('input', update);
    st.rows.forEach((row, i) => $('#ri-lines').append(lineItem(row, i)));
    update();
    $('#ri-review-name').focus();
  }

  function lineItem(row, i) {
    const li = h('li', { class: 'ri-line', id: `ri-line-${i}` });
    const draw = () => {
      clear(li);
      const sel = h('select', { id: `ri-food-${i}`, 'aria-label': `Food for “${row.line.text}”` },
        ...row.options.map((f, k) => h('option', { value: String(k) }, `${f.name} (${f.serving_desc})`)),
        h('option', { value: 'search' }, 'Search for another food…'),
        h('option', { value: 'skip' }, 'Leave this out'));
      sel.value = String(row.choice);
      const sv = h('input', { id: `ri-sv-${i}`, type: 'number', inputmode: 'decimal', min: 0.01, step: 0.01, value: row.servings != null ? String(row.servings) : '',
        'aria-label': `Servings for “${row.line.text}”`, 'aria-describedby': `ri-sv-hint-${i}` });
      const ok = h('input', { type: 'checkbox', id: `ri-ok-${i}`, checked: row.checked || null });
      const food = typeof row.choice === 'number' ? row.options[row.choice] : null;
      sel.addEventListener('change', () => {
        row.checked = false;
        if (sel.value === 'search' || sel.value === 'skip') row.choice = sel.value;
        else {
          row.choice = Number(sel.value);
          const m = row.line.matches.find((x) => x.food.id === row.options[row.choice].id);
          row.servings = m ? m.servings : null;
        }
        draw(); update();
        const again = $(`#ri-food-${i}`); if (again) again.focus();
      });
      sv.addEventListener('input', () => { const v = Number(sv.value); row.servings = sv.value.trim() && v > 0 ? v : null; row.checked = false; ok.checked = false; update(); });
      ok.addEventListener('change', () => { row.checked = ok.checked; update(); });
      li.append(h('div', { class: 'ri-line-text' }, food ? ratingIcon(food.kidney_rating, { decorative: true }) : null, h('b', {}, row.line.text)));
      li.append(h('div', { class: 'ri-line-choice' }, sel));
      if (row.choice === 'search') li.append(searchBox(row, i, draw));
      if (food) {
        li.append(h('div', { class: 'ri-line-amount' }, sv, h('span', { class: 'muted small', id: `ri-sv-hint-${i}` },
          row.servings == null ? `servings of ${food.serving_desc}. The app cannot tell the amount from this line: enter it.` : `servings of ${food.serving_desc}`)));
        const notes = (food.warnings || []).filter((w) => w.nutrient === 'avoid_ckd' || ADDITIVE_FLAGS.includes(w.flag)).map((w) => w.message);
        if (notes.length) li.append(h('p', { class: 'hint ri-line-warn' }, notes.join(' · ')));
      } else if (row.choice === 'skip') {
        li.append(h('p', { class: 'hint' }, row.line.matches.length ? 'Left out: not counted in the numbers.' : 'No food in your list matches this line. Search for one, or leave it out: it is then not counted.'));
      }
      li.append(h('label', { class: 'check', for: `ri-ok-${i}` }, ok, ' Checked'));
    };
    draw();
    return li;
  }

  function searchBox(row, i, redraw) {
    const input = h('input', { id: `ri-search-${i}`, class: 'search-input', type: 'search', placeholder: 'Search foods', autocomplete: 'off',
      'aria-label': `Search for “${row.line.text}”` });
    const ul = h('ul', { class: 'list compact-list', 'aria-label': 'Search results' });
    const run = async () => {
      const q = input.value.trim();
      const req = ++st.search;
      if (!q) { clear(ul); return; }
      try {
        const res = await api.foods({ q, limit: 6 });
        if (req !== st.search) return;
        clear(ul);
        const foods = res.foods || [];
        if (!foods.length) ul.append(h('li', { class: 'empty-state' }, 'No foods match.'));
        for (const f of foods) {
          const b = h('button', { class: 'row-btn compact', type: 'button' }, ratingIcon(f.kidney_rating, { decorative: true }),
            h('div', { class: 'row-main' }, h('div', { class: 'row-title' }, f.name), h('div', { class: 'row-sub' }, f.serving_desc)));
          b.addEventListener('click', () => {
            let k = row.options.findIndex((o) => o.id === f.id);
            if (k < 0) { row.options.push(f); k = row.options.length - 1; }
            row.choice = k;
            row.servings = KH.recipeImport.recipeServings(row.line.amount, row.line.unit, f.serving_desc, f.serving_g);
            row.checked = false;
            redraw(); update();
            const sv = $(`#ri-sv-${i}`); if (sv) sv.focus();
          });
          ul.append(h('li', {}, b));
        }
      } catch (err) { if (req === st.search) toastError(err); }
    };
    input.addEventListener('input', debounce(run, 200));
    input.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); run(); } });
    setTimeout(() => input.focus(), 0);
    return h('div', { class: 'field ri-search' }, input, ul);
  }

  /** The included lines: chosen food and servings. */
  const included = () => st.rows.filter((r) => typeof r.choice === 'number').map((r) => ({ row: r, food: r.options[r.choice] }));
  function makes() { const v = Number($('#ri-review-makes').value); return $('#ri-review-makes').value.trim() && v > 0 ? v : null; }

  function update() {
    if (st.step !== 'review') return;
    const div = makes() || 1;
    const totals = Object.fromEntries(NUTRIENTS.map((n) => [n.key, 0]));
    const missing = Object.fromEntries(NUTRIENTS.map((n) => [n.key, 0]));
    const inc = included().filter((x) => x.row.servings != null);
    for (const { row, food } of inc) {
      for (const n of NUTRIENTS) {
        const v = food.nutrients ? food.nutrients[n.key] : null;
        if (v == null) missing[n.key] += 1; else totals[n.key] += v * row.servings / div;
      }
    }
    const key = clear($('#ri-key'));
    for (const k of KEY_NUMBERS) {
      const unk = missing[k], none = !inc.length || unk === inc.length;
      key.append(h('div', { class: `kn${none ? ' kn-unknown' : ''}`, title: unk ? foodsNotListing(unk, k) : null,
        'aria-label': `${NUT[k].label}: ${none ? 'not listed' : `${atLeastWords(fmtNum(totals[k], k), unk)} ${NUT[k].unit}`}${unk ? `; ${foodsNotListing(unk, k)}` : ''}` },
        h('span', { class: 'kn-v' }, none ? 'not listed' : atLeast(fmtNum(totals[k], k), unk)), none ? null : h('span', { class: 'kn-u' }, NUT[k].unit), h('span', { class: 'kn-l' }, NUT[k].short)));
    }
    const left = st.rows.filter((r) => typeof r.choice !== 'number' || r.servings == null);
    $('#ri-count').textContent = `${inc.length} of ${st.rows.length} ingredients counted${div !== 1 ? `, divided by ${div}` : ''}`;
    $('#ri-left-out').textContent = left.length ? `Not counted (${left.length}): ${left.map((r) => r.line.text).join('; ')}.` : '';
    // Kidney warnings for one serving: the per-serving thresholds over the chosen foods (a "not listed" value is no warning, as on
    // Today), with each food's additive and "not for kidney disease" notes. A low-treatment food stays as it is; only when every
    // counted food is one is the carbohydrate note left out, as for any low treatment.
    const per = Object.fromEntries(NUTRIENTS.map((n) => [n.key, inc.length && missing[n.key] < inc.length ? totals[n.key] : null]));
    const flags = new Set();
    for (const { food } of inc) for (const f of food.flags || []) if (ADDITIVE_FLAGS.includes(f)) flags.add(f);
    if (inc.length && inc.every(({ food }) => (food.flags || []).includes('hypo_treatment'))) flags.add('hypo_treatment');
    const warnings = inc.length ? evaluateWarnings(per, [...flags], null, 'in one serving') : [];
    for (const { food } of inc) for (const w of food.warnings || []) if (w.nutrient === 'avoid_ckd') warnings.unshift({ ...w, message: `${food.name}: ${w.message}` });
    renderWarnings($('#ri-warnings'), warnings, { emptyText: 'Nothing in one serving crosses a per-serving threshold.' });
    const allChecked = st.rows.every((r) => r.checked);
    const bad = included().some((x) => x.row.servings == null || !(x.row.servings > 0));
    const ready = allChecked && !bad && inc.length > 0 && $('#ri-review-name').value.trim();
    goButton(ready ? 'Save recipe' : `Check every line (${st.rows.filter((r) => r.checked).length} of ${st.rows.length})`, !ready);
  }

  async function save() {
    const name = $('#ri-review-name').value.trim();
    const inc = included();
    const left = st.rows.filter((r) => typeof r.choice !== 'number');
    let note = left.length ? `Not counted: ${left.map((r) => r.line.text).join('; ')}` : null;
    if (note && note.length > NOTE_MAX) note = `${note.slice(0, NOTE_MAX - 1)}…`;
    const body = { name, note, items: inc.map(({ row, food }) => ({ food_id: food.id, servings: row.servings })), servings_made: makes(),
      steps: st.draft.steps.length ? st.draft.steps : null, source_url: st.draft.source_url || null };
    st.busy = true; goButton('Saving…', true);
    try {
      const t = await api.createMeal(body);
      dlg.close();
      toast(`Saved “${t.name}”`, 'ok');
      if (st.onSaved) await st.onSaved(t);
    } catch (err) { if (!err.handled) toastError(err); update(); } finally { st.busy = false; }
  }

  $('#recipe-import-back').addEventListener('click', () => { showSource(); const f = st.info.web ? $('#ri-url') : $('#ri-text'); if (f) f.focus(); });
  sheets.onSubmit($('#recipe-import-form'), (e) => {
    e.preventDefault();
    if (st.busy) return;
    if (st.step === 'source') readText(); else save();
  });

  KH.recipeImportView = { open };
})();
