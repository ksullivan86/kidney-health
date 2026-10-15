/* Kidney Diet Log — Visit prep (#visit; ARCHITECTURE.md "Visit prep", ROADMAP "Visit prep").

   One printable page for an appointment, made on this device from what the person already logged:
   * the period (last 2 weeks, 4 weeks or 3 months), the person's display name when they have chosen one (the name the app
     already shows in Settings) and the date the page was made;
   * averages of sodium, potassium, phosphorus, protein and fluid against their targets: the server's own period summary
     (GET /api/log/summary, the numbers Trends shows), never a formula of this file; a value some foods do not list is
     "≥" or "Not listed", with the counts, never 0;
   * the latest result of each lab test with its date, the one before it and an arrow (↑ ↓ →) and nothing more;
   * the symptoms log for the period, grouped by symptom, with the handbook's lines for the warning signs exactly as the
     symptoms screens show them (KH.symptoms.flagEl);
   * the person's own questions, and the handbook's checklist as boxes to tick.

   Nothing leaves the device: the only requests are the three reads above (the app's own API); printing is window.print()
   (called here, no inline handler). The questions and the ticks live in this page's memory only: they are not written to
   localStorage, sessionStorage, IndexedDB or the server, are never sent to the AI and are gone on reload and on sign-out.
   That is the least-trust choice: a shared browser keeps nothing of them.

   All text goes in with textContent (h() children), never as HTML; no inline script or style. The print rules (hide the
   header, tabs, banners and the controls; black on white; one page where it fits) are in css/visit.css. */
(() => {
  'use strict';
  const KH = window.KH;
  const { h, $, clear, api, state, router } = KH;
  const V = KH.visitPrep;
  const { todayStr, addDays, parseDate, fmtMonthDay } = KH.util;
  const { LEVEL_TEXT, levelPill } = KH.ui;

  const view = $('#view-visit');
  if (!view || !V) return;

  // The questions and the ticks: memory only. `owner` is the signed-in person's id; another person in the same page
  // starts with nothing (sign-out reloads the page anyway).
  const S = { days: V.DEFAULT_DAYS, req: 0, owner: undefined, questions: [], ticked: new Set() };

  const fmtDay = (iso) => parseDate(iso).toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric' });
  const note = (text, cls = '') => h('p', { class: `visit-note${cls ? ` ${cls}` : ''}` }, text);
  const live = (text) => { $('#visit-live').textContent = text; };
  const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;
  const lower = (t) => String(t).toLowerCase();
  const loadError = (what, err) => note(`${what} could not be loaded${err && (err.detail || err.message) ? ` (${err.detail || err.message})` : ''}. Try again before you print: this page would otherwise leave it out.`, 'visit-problem');

  // ---- the period and the head of the page -----------------------------------------------------------------------
  const periodsEl = $('#visit-periods');
  for (const p of V.PERIODS) {
    periodsEl.append(h('button', { type: 'button', class: 'seg', 'data-period': p.days, 'aria-pressed': p.days === S.days ? 'true' : 'false',
      onclick: () => { S.days = p.days; syncPeriods(); load(); } }, p.short));
  }
  function syncPeriods() {
    for (const b of periodsEl.querySelectorAll('.seg')) b.setAttribute('aria-pressed', Number(b.dataset.period) === S.days ? 'true' : 'false');
  }

  function renderHead(range) {
    const name = state.me && typeof state.me.display_name === 'string' ? state.me.display_name.trim() : ''; // only a name they chose
    const who = $('#visit-who');
    who.hidden = !name;
    who.textContent = name ? `For ${name}` : '';
    const period = V.PERIODS.find((p) => p.days === S.days);
    $('#visit-period').textContent = `${period.label}: ${fmtDay(range.start)} – ${fmtDay(range.end)}`;
    $('#visit-made').textContent = `Made on ${fmtDay(todayStr())} with Kidney Diet Log, on this device.`;
  }

  // ---- averages against the targets ------------------------------------------------------------------------------
  function renderAverages(sum, err) {
    const body = clear($('#visit-avg-body'));
    const sub = $('#visit-avg-sub');
    sub.textContent = '';
    if (err || !sum) { body.append(loadError('The averages', err)); return; }
    const a = V.averageRows(sum, KH.rules);
    sub.textContent = `${a.loggedDays} of ${a.days} days had food entries. An average counts only the days with entries.`;
    if (!a.rows.length) { body.append(note('No targets are set yet, so there is nothing to compare. You can set them in Profile.')); return; }
    const list = h('ul', { class: 'visit-avg' });
    for (const r of a.rows) {
      const nothing = r.text === 'No entries' || r.text === 'Not listed';
      const judged = r.judged === 'weekly_average';
      const facts = [];
      if (r.percent != null) facts.push(`${r.atLeast ? '≥ ' : ''}${r.percent} % of ${r.role === 'goal' ? 'goal' : 'target'}`);
      facts.push(plural(r.daysOver, 'day over', 'days over'));
      const row = h('li', { class: `visit-avg-row level-${r.level || 'ok'}` },
        h('div', { class: 'visit-avg-top' },
          h('span', { class: 'visit-avg-name' }, r.label),
          h('span', { class: `strip-tag ${judged ? 'weekly' : 'daily'}` }, judged ? 'judged on the average' : 'judged day by day')),
        h('div', { class: 'visit-avg-nums tabular' }, h('b', {}, r.text), h('span', { class: 'muted' }, ` / ${r.target} ${r.unit} per day`)),
        h('div', { class: 'visit-avg-foot' }, nothing ? null : facts.join(' · '), r.level && !nothing ? [' ', levelPill(r.level, LEVEL_TEXT[r.level])] : null));
      if (r.unknownDays) {
        const days = plural(r.unknownDays, 'day', 'days');
        const foods = plural(r.unknownEntries, 'food', 'foods');
        row.append(h('div', { class: 'visit-avg-foot not-listed' }, r.text === 'Not listed'
          ? `${days} with foods that do not list ${lower(r.label)} (${foods}): there is no average to show.`
          : `${days} with foods that do not list ${lower(r.label)} (${foods}): the average may be higher.`));
      }
      list.append(row);
    }
    body.append(list);
    if (a.withoutTarget.length) {
      const names = a.withoutTarget.map(lower).join(', ');
      body.append(note(`No target is set for ${names}, so ${a.withoutTarget.length === 1 ? 'it is' : 'they are'} not shown.`, 'small'));
    }
  }

  // ---- the lab results -------------------------------------------------------------------------------------------
  function renderLabs(res, err) {
    const body = clear($('#visit-labs-body'));
    if (err || !res) { body.append(loadError('The lab results', err)); return; }
    const alert = KH.labs && res.alerts && res.alerts[0]; // the potassium warning the Labs screen shows while it counts
    if (alert) body.append(KH.labs.alertBanner(alert));
    const rows = V.labRows(res.labs || [], KH.labs ? KH.labs.ANALYTE_ORDER : []);
    if (!rows.length) { body.append(note('No lab results are saved yet. You can add them in Profile, under Lab results.')); return; }
    const list = h('ul', { class: 'visit-labs' });
    for (const r of rows) {
      const trend = r.trend
        ? h('span', { class: 'visit-lab-trend', title: V.TREND_WORDS[r.trend] }, h('span', { 'aria-hidden': 'true' }, V.TREND_ARROW[r.trend]), h('span', { class: 'sr-only' }, V.TREND_WORDS[r.trend]))
        : h('span', { class: 'visit-lab-trend' });
      list.append(h('li', { class: 'visit-lab' },
        h('span', { class: 'visit-lab-name' }, r.label),
        h('span', { class: 'visit-lab-latest' }, h('b', {}, r.latest.display), h('span', { class: 'muted' }, ` ${fmtDay(r.latest.taken_on)}`)),
        trend,
        h('span', { class: 'visit-lab-prev muted' }, r.previous ? `Before that: ${r.previous.display}, ${fmtDay(r.previous.taken_on)}` : 'No earlier result saved')));
    }
    body.append(list);
    body.append(note('The arrow compares the newest result with the one before it. It does not say whether the change matters.', 'small muted'));
  }

  // ---- the symptoms log -----------------------------------------------------------------------------------------
  function renderSymptoms(res, err) {
    const body = clear($('#visit-sym-body'));
    if (err || !res) { body.append(loadError('The symptoms', err)); return; }
    const R = KH.symptomRules;
    const groups = R.summarise(res.symptoms || []);
    if (!groups.length) { body.append(note('No symptoms were recorded in this period.')); return; }
    const first = (g) => (g.red_flag && g.red_flag.prominent ? 0 : 1);
    groups.sort((a, b) => first(a) - first(b)); // a stable sort: the rest stay most days first, as in Trends
    const sev = (n) => lower(R.SEVERITY_LABELS[n]);
    const list = h('ul', { class: 'visit-sym' });
    for (const g of groups) {
      list.append(h('li', { class: 'visit-sym-row' },
        h('div', { class: 'visit-sym-head' },
          h('span', { class: 'visit-sym-name' }, g.name),
          h('span', { class: 'visit-sym-count' }, `${plural(g.dayCount, 'day', 'days')}, worst: ${sev(g.worst)}`)),
        h('p', { class: 'visit-sym-dates' }, g.days.map((d) => `${fmtMonthDay(d.date)} ${sev(d.severity)}`).join(', ')),
        g.red_flag && KH.symptoms && KH.symptoms.flagEl ? KH.symptoms.flagEl(g.red_flag) : null));
    }
    body.append(list);
    body.append(note('The notes you wrote stay in the symptoms log.', 'small muted'));
  }

  // ---- my questions (memory only) -------------------------------------------------------------------------------
  const qInput = $('#visit-q-input');
  const qError = $('#visit-q-error');
  const showQError = (text) => { qError.textContent = text || ''; qError.hidden = !text; };

  function renderQuestions() {
    const list = clear($('#visit-q-list'));
    S.questions.forEach((q, i) => {
      const remove = h('button', { class: 'link-btn danger-link screen-only', type: 'button', 'aria-label': `Remove question ${i + 1}: ${q}` }, 'Remove');
      remove.addEventListener('click', () => {
        S.questions = S.questions.filter((_, j) => j !== i);
        renderQuestions();
        live('Question removed.');
        qInput.focus();
      });
      list.append(h('li', { class: 'visit-q' }, h('span', { class: 'visit-q-text' }, q), remove));
    });
    $('#visit-blank-lines').hidden = S.questions.length > 0; // printed lines to write on when the list is empty
  }
  // → true when the typed text (if any) is on the list.
  function addTyped() {
    if (!V.cleanQuestion(qInput.value)) { showQError(''); return true; }
    const res = V.addQuestion(S.questions, qInput.value);
    if (res.error) { showQError(res.error); qInput.focus(); return false; }
    S.questions = res.list;
    qInput.value = '';
    showQError('');
    renderQuestions();
    live(`Question ${S.questions.length} added.`);
    return true;
  }
  $('#visit-q-add').addEventListener('click', () => {
    if (!V.cleanQuestion(qInput.value)) { showQError('Write a question first.'); qInput.focus(); return; }
    addTyped();
    qInput.focus();
  });
  qInput.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); $('#visit-q-add').click(); } });

  // ---- the handbook's checklist ---------------------------------------------------------------------------------
  function renderChecklist() {
    const list = clear($('#visit-checklist'));
    V.CHECKLIST.forEach((text, i) => {
      const id = `visit-check-${i}`;
      const box = h('input', { type: 'checkbox', id });
      box.checked = S.ticked.has(i);
      box.addEventListener('change', () => { if (box.checked) S.ticked.add(i); else S.ticked.delete(i); });
      list.append(h('li', { class: 'visit-check' }, box, h('label', { for: id }, text)));
    });
    const href = KH.learn ? KH.learn.href(V.CHECKLIST_HREF) : null;
    const where = clear($('#visit-check-link'));
    if (href) where.append(h('a', { class: 'learn-more', href, target: '_blank', rel: 'noopener' }, 'Handbook: Getting the most from appointments', h('span', { class: 'sr-only' }, ' (opens in a new tab)')));
  }

  // ---- loading ---------------------------------------------------------------------------------------------------
  async function load() {
    const req = ++S.req;
    const range = V.periodRange(todayStr(), S.days, addDays);
    renderHead(range);
    for (const id of ['#visit-avg-body', '#visit-labs-body', '#visit-sym-body']) clear($(id)).append(note('Loading…', 'muted'));
    $('#visit-avg-sub').textContent = '';
    const settle = (p) => p.then((v) => ({ ok: v }), (e) => ({ err: e }));
    const [sum, labs, sym] = await Promise.all([
      settle(api.summary(range.start, range.end)),
      settle(api.labs({ limit: 1000 })),
      settle(api.symptoms(range.start, range.end)),
    ]);
    if (req !== S.req) return; // a newer period was chosen meanwhile
    renderAverages(sum.ok, sum.err);
    renderLabs(labs.ok, labs.err);
    renderSymptoms(sym.ok, sym.err);
    live(`Visit summary ready for the ${lower(V.PERIODS.find((p) => p.days === S.days).label)}.`);
  }

  // ---- print, back, the way in -----------------------------------------------------------------------------------
  $('#visit-print').addEventListener('click', () => {
    if (!addTyped()) return; // a question typed but not added would be left off the page: say why instead
    window.print();
  });
  $('#visit-back').addEventListener('click', () => router.show('trends'));
  const open = $('#visit-open');
  if (open) open.addEventListener('click', () => router.show('visit'));

  router.register('visit', () => {
    const owner = state.me ? state.me.id : null;
    if (S.owner !== owner) { S.owner = owner; S.questions = []; S.ticked = new Set(); S.days = V.DEFAULT_DAYS; qInput.value = ''; showQError(''); }
    syncPeriods();
    renderQuestions();
    renderChecklist();
    $('#visit-title').focus();
    load();
  });

  KH.views.visit = { load, renderAverages, renderLabs, renderSymptoms };
})();
