/* Kidney Diet Log — how well each AI is doing (KH.aiQuality; ARCHITECTURE.md "How well each AI is doing", docs/ai.md).

   Server administration → AI providers, under "Which AI does each feature use?": one row for every feature that is on, with
   the AI and model it uses and two facts about it.

   * In use: what the last calls of that feature to that model gave (counts only, from the AI activity log), and a caution when
     most of them had no usable result. A model that answers "nothing fits" to every request shows up here.
   * Evaluation: what scripts/ai_eval.py found for this model and the current prompt version, read from AI_EVAL_REPORTS_DIR.
     Failed, or no report, is a caution. Passed is shown quietly.

   The data is GET /api/admin/ai-quality (through KH.ai.api, which the caller passes in as `load`). Nothing here sends health
   data anywhere. Rules: everything the server sends is drawn with textContent (the h() helper); no inline scripts, styles or
   handlers; the only control is one button at least 44 px high. The demo and preview never show this: they have no AI admin. */
(() => {
  'use strict';
  const KH = window.KH;
  const { h, clear } = KH;

  function note(kind, ...children) { return h('div', { class: `settings-note ${kind}`, role: 'note' }, ...children); }

  // The line about the reports folder, above the rows.
  function folderPart(reports) {
    if (!reports.configured) {
      return h('p', { class: 'hint ai-quality-folder' },
        'No reports folder is set. To see what scripts/ai_eval.py found for each model, set AI_EVAL_REPORTS_DIR to a read-only folder '
        + 'that holds its reports (docs/ai.md).');
    }
    if (!reports.readable) {
      return note('caution', h('p', { class: 'ai-quality-folder' },
        'The reports folder (AI_EVAL_REPORTS_DIR) cannot be read, so the evaluations below cannot be checked.'));
    }
    const left = Object.values(reports.ignored || {}).reduce((sum, n) => sum + n, 0);
    const read = `${reports.reports} ${reports.reports === 1 ? 'report' : 'reports'} read from the reports folder`;
    return h('p', { class: 'hint ai-quality-folder' }, left ? `${read}. ${left} ${left === 1 ? 'file was' : 'files were'} not usable and left out.` : `${read}.`);
  }

  // One feature: who answers, how its last calls went, what the evaluation said. A warning is a caution; the rest is quiet.
  function rowPart(f) {
    const p = f.provider;
    const live = f.live;
    const evaluation = f.evaluation;
    return h('div', { class: 'ai-quality-row', 'data-feature': f.feature },
      h('h4', { class: 'ai-quality-title' }, f.label),
      h('p', { class: 'muted small ai-quality-provider' }, `${p.label} (${p.host}) · ${p.model}`),
      h('div', { class: 'ai-quality-signal' },
        h('b', {}, 'In use'),
        h('p', { class: 'small' }, live.summary),
        live.warn ? note('caution', h('p', {}, live.message)) : null),
      h('div', { class: 'ai-quality-signal' },
        h('b', {}, 'Evaluation'),
        evaluation.warn ? note('caution', h('p', {}, evaluation.message)) : h('p', { class: 'small' }, evaluation.message)));
  }

  function listPart(data) {
    if (!data.enabled) return h('p', { class: 'hint' }, 'AI is switched off, so there is nothing to rate yet.');
    if (!data.features.length) {
      return h('p', { class: 'hint' }, 'No feature is on with an AI behind it yet. Choose one in the table above.');
    }
    return h('div', { class: 'ai-quality-list' }, data.features.map(rowPart));
  }

  // `data` is GET /api/admin/ai-quality; `load` fetches it again (the button), so a report copied into the folder shows at once.
  function adminPart(data, load) {
    const wrap = h('div', { class: 'ai-quality', id: 'ai-quality' });
    const body = h('div', { class: 'ai-quality-body' });
    const msg = h('p', { class: 'status-msg', role: 'status', 'aria-live': 'polite' });
    function draw(d) { clear(body).append(d.enabled ? folderPart(d.reports) : null, listPart(d)); } // with AI off the folder is not read: say nothing about it
    draw(data);
    wrap.append(
      h('h3', { class: 'settings-subtitle' }, 'How well each AI is doing'),
      h('p', { class: 'hint' },
        `In use counts the last ${data.last_calls} calls of each feature in the last ${data.window_days} days, from everyone, and warns when `
        + `${data.warn_percent} % or more of them (from ${data.min_calls} calls) gave no usable result. Counts only: nobody's questions or answers are shown. `
        + 'Evaluation says whether this model passed scripts/ai_eval.py for the current prompts.'),
      body, msg);
    if (typeof load === 'function') {
      const again = h('button', { class: 'btn secondary', type: 'button' }, 'Check again');
      again.addEventListener('click', async () => {
        again.disabled = true;
        msg.textContent = '';
        try { draw(await load()); } catch (e) { msg.textContent = `Could not check again: ${(e && (e.detail || e.message)) || 'something went wrong'}`; } finally { again.disabled = false; }
      });
      wrap.append(h('div', { class: 'settings-actions' }, again));
    }
    return wrap;
  }

  KH.aiQuality = { adminPart };
})();
