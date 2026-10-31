/* Kidney Diet Log — suggestions from your Care team, on your Plan tab (design notes 21 and 29 §5; app/care_suggestions.py).

   KH.suggestions.load() runs when the Plan tab shows your own plan. With nothing waiting (or the Care team off, or no accounts)
   the card stays hidden. Each suggestion is a card: who sent it, the day and meal, the foods (a food you can no longer use says
   so), what it adds to that day against your targets ("≥" and "not listed" as everywhere), the note, and two buttons that each
   take one tap: Add to my plan (planned entries of your own, which you can change like any other) and No thanks. The person who
   sent it sees which one you chose, never why. All text goes in with h() children (textContent), never as HTML. */
(() => {
  'use strict';
  const KH = window.KH;
  const { h, $, clear, request, state, toast } = KH;
  const { MEAL_LABEL } = KH.rules;

  const card = $('#plan-suggestions');
  let loadRequest = 0;

  const A = {
    list: () => request('GET', '/api/me/suggestions'),
    accept: (id) => request('POST', `/api/me/suggestions/${encodeURIComponent(id)}/accept`),
    decline: (id) => request('POST', `/api/me/suggestions/${encodeURIComponent(id)}/decline`),
  };

  // ---------------------------------------------------------------------------
  // Pure helpers (tests/test_care_team_ui.py runs them in Node)
  // ---------------------------------------------------------------------------
  /** "Jordan suggests dinner on Tue, Nov 3" */
  function titleText(sg) {
    return `${sg.from_name} suggests ${(MEAL_LABEL[sg.meal] || sg.meal).toLowerCase()} on ${KH.util.fmtDateLong(sg.date)}`;
  }
  /** One food: "Rice, 1 serving of 1 cup" (and "no longer on your list, so it is left out" when it is gone). */
  function itemText(it) {
    const n = Number(it.servings);
    const amount = `${KH.rules.fmtServings(n)} ${n === 1 ? 'serving' : 'servings'}${it.serving_desc ? ` of ${it.serving_desc}` : ''}`;
    return `${it.name}, ${amount}${it.available === false ? ': no longer on your list, so it is left out' : ''}`;
  }
  function headingText(n) { return n === 1 ? '1 suggestion from your Care team' : `${n} suggestions from your Care team`; }
  /** What Add to my plan says when it is done. */
  function addedText(res) {
    const n = (res.entries || []).length;
    const added = `${n} planned ${n === 1 ? 'food' : 'foods'} added to your plan`;
    return res.skipped ? `${added}. ${res.skipped} ${res.skipped === 1 ? 'food was' : 'foods were'} left out.` : added;
  }

  function authOn() { return ((state.authStatus || {}).auth_mode || 'local') !== 'none'; }

  /** Load and draw the suggestions waiting for you. Only the newest load draws. */
  async function load() {
    if (!card) return;
    const req = ++loadRequest;
    if (!authOn() || !state.me) { card.hidden = true; return; }
    let res;
    try { res = await A.list(); } catch (err) { if (req === loadRequest) card.hidden = true; return; }
    if (req !== loadRequest) return;
    draw(res.enabled ? res.suggestions || [] : []);
  }

  function draw(list) {
    clear(card);
    card.hidden = !list.length || !!(KH.carePlan && KH.carePlan.current()); // not while helping someone else

    if (!list.length) return;
    card.append(h('h2', { class: 'card-title', id: 'plan-suggestions-h' }, headingText(list.length)),
      h('p', { class: 'hint' }, 'Add one to your plan or say no thanks. Nothing changes until you choose.'));
    for (const sg of list) card.append(suggestionCard(sg));
  }

  function suggestionCard(sg) {
    const lines = KH.carePlan ? KH.carePlan.fitLines(sg.fit) : [];
    const add = h('button', { class: 'btn primary', type: 'button' }, 'Add to my plan');
    const no = h('button', { class: 'btn secondary', type: 'button' }, 'No thanks');
    const answer = async (btn, fn) => {
      add.disabled = true; no.disabled = true;
      try { await fn(); } catch (err) { if (!err.handled) toast(err.detail || err.message || 'That did not work. Try again.', 'error'); }
      add.disabled = false; no.disabled = false;
      await load();
    };
    add.addEventListener('click', () => answer(add, async () => {
      const res = await A.accept(sg.id);
      toast(addedText(res), 'ok');
      if (KH.views.plan && state.view === 'plan') KH.views.plan.loadPlan();
    }));
    no.addEventListener('click', () => answer(no, async () => { await A.decline(sg.id); toast(`You said no thanks to ${sg.from_name}`, 'ok'); }));
    return h('article', { class: 'care-suggestion', 'aria-label': titleText(sg) },
      h('h3', { class: 'settings-minor' }, titleText(sg)),
      h('ul', { class: 'visit-body-list' }, (sg.items || []).map((it) => h('li', {}, itemText(it)))),
      lines.length ? [h('p', { class: 'visit-body-sub' }, 'Your day with it'), h('ul', { class: 'visit-body-list' }, lines.map((l) => h('li', {}, l)))] : null,
      sg.note ? h('p', { class: 'care-note' }, `${sg.from_name} wrote: “${sg.note}”`) : null,
      h('div', { class: 'settings-actions' }, add, no));
  }

  KH.suggestions = { load, titleText, itemText, headingText, addedText };
})();
