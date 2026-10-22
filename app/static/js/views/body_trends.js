/* Kidney Diet Log — Weight and blood pressure on Trends: two plain SVG charts, each with a table under it, and the 7-day averages
   (ARCHITECTURE.md "Weight and blood pressure", note 10 §4.6).

   * Weight: one line through the weights of the period, a marker per weight (a diamond for a weight after dialysis), and on
     hemodialysis a dashed line for the dry weight in Profile.
   * Blood pressure: the top numbers and the bottom numbers as two lines (a circle and a square per reading), and the goal the
     person's care team gave them as dashed lines when it is set. A reading the handbook points to has a heavier outline.
   * Under each chart a table holds every value, so nothing depends on seeing the chart or on colour; the legend names each line and
     each marker by its words. The charts are built with the DOM (KH.s): no chart library, no HTML strings, no inline style (classes and
     css/body.css only). The scales and the paths are js/engine/body_ui.js.
   * "Import from Apple Health" is shown only when KH.bodyImport exists; this file does not read the export itself.

   js/views/trends.js calls KH.bodyTrends.show(start, end) with the period shown. All text goes in with textContent (h() children). */
(() => {
  'use strict';
  const KH = window.KH;
  const { h, s, $, clear, api, state } = KH;
  const R = KH.bodyRules;
  const U = KH.bodyUi;
  const { fmtDateShort, fmtMonthDay, daysBetween } = KH.util;

  const box = $('#body-trends-body');
  if (!box || !R || !U) return;

  const NEEDS_CONNECTION = 'Weights and blood pressure readings need a connection to your server, and there is none right now.';
  const CHART_HEIGHT = 190;
  let req = 0;
  let last = null; // what the cards were drawn from, so a resize can draw them again

  const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;
  const message = (text) => h('p', { class: 'body-empty' }, text);

  // ---- small SVG pieces ----------------------------------------------------------------------------------------------------
  const rect = (x, y, size, cls) => s('rect', { class: cls, x: x - size / 2, y: y - size / 2, width: size, height: size, rx: 1 });
  const circle = (x, y, r, cls) => s('circle', { class: cls, cx: x, cy: y, r });
  const diamond = (x, y, r, cls) => s('polygon', { class: cls, points: `${x},${y - r} ${x + r},${y} ${x},${y + r} ${x - r},${y}` });
  const fmtTick = (v, step) => (step >= 1 ? String(Math.round(v)) : v.toFixed(1));
  const title = (text) => s('title', {}, text);

  // The frame both charts share: horizontal grid with the values on the left, the days under, the month under the first day of each.
  function frame(svg, ax, dom, start, end) {
    for (const tick of dom.ticks) {
      const y = ax.y(tick);
      svg.append(s('line', { class: 'grid', x1: ax.padL, x2: ax.width - ax.padR, y1: y, y2: y }), s('text', { x: ax.padL - 6, y: y + 3.5, 'text-anchor': 'end' }, fmtTick(tick, dom.step)));
    }
    svg.append(s('line', { class: 'axis', x1: ax.padL, x2: ax.width - ax.padR, y1: ax.y(dom.min), y2: ax.y(dom.min) }));
    const months = new Set([start.slice(0, 7), end.slice(0, 7)]).size > 1;
    for (const lab of U.xLabels(start, end, ax.slot)) {
      const x = ax.padL + (lab.index + 0.5) * ax.slot;
      svg.append(s('text', { x, y: ax.height - (months ? 18 : 6), 'text-anchor': 'middle' }, lab.text));
      if (months && lab.month) svg.append(s('text', { class: 'month', x, y: ax.height - 6, 'text-anchor': 'middle' }, lab.month));
    }
  }
  const legendItem = (shape, text) => h('li', {}, shape, h('span', {}, text));
  const legendLine = (cls, mark) => s('svg', { viewBox: '0 0 22 14', 'aria-hidden': 'true', focusable: 'false' }, s('line', { class: `series ${cls}`, x1: 0, x2: 22, y1: 7, y2: 7 }), mark || null);
  const legendRef = (cls) => s('svg', { viewBox: '0 0 22 14', 'aria-hidden': 'true', focusable: 'false' }, s('line', { class: `ref ${cls}`, x1: 0, x2: 22, y1: 7, y2: 7 }));

  // ---- the weight chart -------------------------------------------------------------------------------------------------------
  function weightChart({ weights, unit, dryKg, start, end, width }) {
    const series = U.weightSeries(weights, unit);
    const dry = dryKg == null ? null : (unit === 'kg' ? dryKg : dryKg / R.KG_PER_LB);
    const dom = U.domainOf(series.map((p) => p.value).concat(dry == null ? [] : [dry]));
    const months = new Set([start.slice(0, 7), end.slice(0, 7)]).size > 1;
    const ax = U.makeAxes({ start, end, width, height: CHART_HEIGHT, padB: months ? 38 : 26, domain: dom });
    const first = series[0], lastP = series[series.length - 1];
    const svg = s('svg', { class: 'body-chart-svg', viewBox: `0 0 ${width} ${CHART_HEIGHT}`, width, height: CHART_HEIGHT, role: 'img',
      'aria-label': `Weight chart, ${plural(series.length, 'weight', 'weights')} from ${fmtMonthDay(first.date)} to ${fmtMonthDay(lastP.date)}, between `
        + `${R.shownWeight(Math.min(...weights.map((w) => w.kg)), unit).toFixed(1)} and ${R.shownWeight(Math.max(...weights.map((w) => w.kg)), unit).toFixed(1)} ${unit}`
        + `${dry == null ? '' : `, with a dashed line for your dry weight, ${R.formatWeight(dryKg, unit)}`}. The table under the chart lists every weight.` });
    frame(svg, ax, dom, start, end);
    if (dry != null) {
      const y = ax.y(dry);
      svg.append(s('line', { class: 'ref dry', x1: ax.padL, x2: ax.width - ax.padR, y1: y, y2: y }));
    }
    const points = series.map((p) => ({ x: ax.x(p.date, p.time), y: ax.y(p.value) }));
    svg.append(s('path', { class: 'series weight', d: U.linePath(points) }));
    series.forEach((p, i) => {
      const text = `${fmtDateShort(p.date)}${p.time ? `, ${U.fmtTime(p.time)}` : ''}: ${R.formatWeight(p.kg, unit)} (${U.contextLabel('weight', p.context).toLowerCase()})`;
      const mark = p.after ? diamond(points[i].x, points[i].y, 5.5, 'mark weight after') : circle(points[i].x, points[i].y, 4, 'mark weight');
      mark.append(title(text));
      svg.append(mark);
    });
    return svg;
  }

  // ---- the blood pressure chart ----------------------------------------------------------------------------------------------
  function bpChart({ readings, goal, start, end, width }) {
    const series = U.readingSeries(readings);
    const goals = [goal.systolic, goal.diastolic].filter((v) => v != null);
    const dom = U.domainOf(series.flatMap((p) => [p.systolic, p.diastolic]).concat(goals));
    const months = new Set([start.slice(0, 7), end.slice(0, 7)]).size > 1;
    const ax = U.makeAxes({ start, end, width, height: CHART_HEIGHT, padB: months ? 38 : 26, domain: dom });
    const svg = s('svg', { class: 'body-chart-svg', viewBox: `0 0 ${width} ${CHART_HEIGHT}`, width, height: CHART_HEIGHT, role: 'img',
      'aria-label': `Blood pressure chart, ${plural(series.length, 'reading', 'readings')} from ${fmtMonthDay(series[0].date)} to ${fmtMonthDay(series[series.length - 1].date)}: `
        + `top numbers between ${Math.min(...series.map((p) => p.systolic))} and ${Math.max(...series.map((p) => p.systolic))}, bottom numbers between `
        + `${Math.min(...series.map((p) => p.diastolic))} and ${Math.max(...series.map((p) => p.diastolic))}`
        + `${U.goalText(goal) ? `, with dashed lines for the goal from your care team, ${U.goalText(goal)}` : ''}. The table under the chart lists every reading.` });
    frame(svg, ax, dom, start, end);
    // The goal lines. The legend names each with its number (never only a colour); a label on the line itself sat on the
    // readings, which are usually close to the goal.
    const ref = (value, cls) => {
      if (value == null) return;
      const y = ax.y(value);
      svg.append(s('line', { class: `ref ${cls}`, x1: ax.padL, x2: ax.width - ax.padR, y1: y, y2: y }));
    };
    ref(goal.systolic, 'goal-top');
    ref(goal.diastolic, 'goal-bottom');
    const top = series.map((p) => ({ x: ax.x(p.date, p.time), y: ax.y(p.systolic) }));
    const bottom = series.map((p) => ({ x: ax.x(p.date, p.time), y: ax.y(p.diastolic) }));
    svg.append(s('path', { class: 'series top', d: U.linePath(top) }), s('path', { class: 'series bottom', d: U.linePath(bottom) }));
    series.forEach((p, i) => {
      const text = `${fmtDateShort(p.date)}${p.time ? `, ${U.fmtTime(p.time)}` : ''}: ${p.systolic}/${p.diastolic} (${U.contextLabel('bp', p.context).toLowerCase()})${p.flagged ? ', the handbook note applies' : ''}`;
      const t = circle(top[i].x, top[i].y, p.flagged ? 5 : 4, `mark top${p.flagged ? ' flagged' : ''}`);
      const b = rect(bottom[i].x, bottom[i].y, p.flagged ? 10 : 8, `mark bottom${p.flagged ? ' flagged' : ''}`);
      t.append(title(text));
      b.append(title(text));
      svg.append(t, b);
    });
    return svg;
  }

  // ---- the tables under the charts -----------------------------------------------------------------------------------------------
  function tableOf(summaryText, label, head, rows) {
    const table = h('table', { class: 'data-table body-table' },
      h('thead', {}, h('tr', {}, head.map(([text, num]) => h('th', { scope: 'col', class: num ? 'num' : null }, text)))),
      h('tbody', {}, rows.map((cells) => h('tr', {}, cells.map(([text, cls]) => h('td', { class: cls || null }, text))))));
    // a table wider than the phone scrolls on its own, so it can be reached with the keyboard and has a name
    return h('details', { class: 'inline-details' }, h('summary', {}, summaryText),
      h('div', { class: 'body-table-wrap', tabindex: '0', role: 'region', 'aria-label': label }, table));
  }
  function weightTable(weights, unit) {
    return tableOf('Show as table', 'Table of weights', [['Date'], ['Time'], [`Weight (${unit})`, true], ['When']],
      U.weightRows(weights, unit).map((r) => [[fmtMonthDay(r.date)], [r.time || '—'], [r.value, 'num'], [r.context]]));
  }
  function bpTable(readings) {
    return tableOf('Show as table', 'Table of blood pressure readings', [['Date'], ['Time'], ['Top', true], ['Bottom', true], ['Pulse', true], ['When'], ['Handbook note']],
      U.readingRows(readings).map((r) => [[fmtMonthDay(r.date)], [r.time || '—'], [String(r.systolic), 'num'], [String(r.diastolic), 'num'],
        [r.pulse === '' ? '—' : String(r.pulse), 'num'], [r.context], [r.flagged ? 'Yes, see Today' : '', r.flagged ? 'flagged' : null]]));
  }

  // ---- the two blocks -----------------------------------------------------------------------------------------------------------
  function weightBlock({ weights, unit, dryKg, start, end, width }) {
    const block = h('div', { class: 'body-trends-block', id: 'body-trends-weight' }, h('h4', { class: 'body-trends-h' }, `Weight (${unit})`));
    if (!weights.length) { block.append(message('No weights recorded in this period. You can add them on Today.')); return block; }
    const latest = weights[weights.length - 1];
    const stats = h('ul', { class: 'body-stats' }, h('li', {}, 'Latest: ', h('b', {}, R.formatWeight(latest.kg, unit)), ` on ${fmtMonthDay(latest.date)}, ${U.contextLabel('weight', latest.context).toLowerCase()}.`));
    const averages = U.weekAverages(weights, end);
    if (!averages.length) stats.append(h('li', {}, 'No weights in the last 7 days.'));
    for (const a of averages) {
      stats.append(h('li', {}, `Last 7 days, ${a.label.toLowerCase()}: average `, h('b', {}, R.formatWeight(a.mean_kg, unit)), ` from ${plural(a.count, 'weight', 'weights')}.`));
    }
    block.append(stats, weightChart({ weights, unit, dryKg, start, end, width }));
    const legend = h('ul', { class: 'body-legend' }, legendItem(legendLine('weight', circle(11, 7, 4, 'mark weight')), 'Weight'));
    if (weights.some((w) => w.context === 'after_dialysis')) legend.append(legendItem(s('svg', { viewBox: '0 0 22 14', 'aria-hidden': 'true', focusable: 'false' }, diamond(11, 7, 5.5, 'mark weight')), 'After dialysis'));
    if (dryKg != null) legend.append(legendItem(legendRef('dry'), `Dry weight in Profile (${R.formatWeight(dryKg, unit)})`));
    block.append(legend, weightTable(weights, unit));
    return block;
  }
  function bpBlock({ readings, goal, summary, start, end, width }) {
    const block = h('div', { class: 'body-trends-block', id: 'body-trends-bp' }, h('h4', { class: 'body-trends-h' }, 'Blood pressure'));
    if (!readings.length) { block.append(message('No blood pressure readings in this period. You can add them on Today.')); return block; }
    const lines = summary && summary.bp ? U.weekSentences(summary.bp.week, summary.bp.goal) : [];
    const goalText = U.goalText(goal);
    block.append(h('ul', { class: 'body-stats' }, goalText ? h('li', {}, 'Goal from your care team: ', h('b', {}, goalText), '.') : null, lines.map((t) => h('li', {}, t))),
      bpChart({ readings, goal, start, end, width }));
    const legend = h('ul', { class: 'body-legend' },
      legendItem(legendLine('top', circle(11, 7, 4, 'mark top')), 'Top number'),
      legendItem(legendLine('bottom', rect(11, 7, 8, 'mark bottom')), 'Bottom number'));
    if (goal.systolic != null) legend.append(legendItem(legendRef('goal-top'), `Top goal: under ${goal.systolic} (dashed)`));
    if (goal.diastolic != null) legend.append(legendItem(legendRef('goal-bottom'), `Bottom goal: under ${goal.diastolic} (dashed)`));
    block.append(legend, bpTable(readings));
    return block;
  }

  function render() {
    if (!last) return;
    const width = Math.max(240, Math.floor(box.clientWidth || 320));
    clear(box);
    const { weights, readings, summary, start, end } = last;
    const goal = summary && summary.bp ? summary.bp.goal : { systolic: null, diastolic: null };
    const dryKg = state.profile && state.profile.dialysis === 'hemodialysis' && state.profile.weight_kg != null ? Number(state.profile.weight_kg) : null;
    if (!weights.length && !readings.length) {
      box.append(message('No weights or blood pressure readings in this period. You can add them on Today.'));
      return;
    }
    box.append(weightBlock({ weights, unit: last.unit, dryKg, start, end, width }), bpBlock({ readings, goal, summary, start, end, width }));
  }

  // ---- Import from Apple Health: a button for a module that is not this file's -----------------------------------------------------
  function importButton() {
    const slot = $('#body-trends-actions');
    if (!slot) return;
    clear(slot);
    const there = !!(KH.bodyImport && typeof KH.bodyImport.open === 'function');
    slot.hidden = !there;
    if (!there) return;
    const btn = h('button', { class: 'btn secondary', type: 'button', id: 'body-import-trends' }, 'Import from Apple Health');
    btn.addEventListener('click', () => KH.bodyImport.open(btn));
    slot.append(btn);
  }

  async function show(start, end) {
    const my = ++req;
    const days = daysBetween(start, end) + 1;
    const sub = $('#body-trends-sub');
    if (sub) sub.textContent = `last ${days} days`;
    importButton();
    if (!state.profile) { try { await KH.loadProfile(); } catch (e) { /* no dry weight line then */ } }
    const [w, b, sum] = await Promise.allSettled([api.bodyWeights(start, end), api.bloodPressures(start, end), api.bodySummary(end)]);
    if (my !== req) return;
    const failure = [w, b].find((x) => x.status === 'rejected');
    if (failure) {
      const err = failure.reason;
      if (err && err.handled) return;
      last = null;
      clear(box).append(message(err && err.status ? 'Weights and blood pressure could not be loaded.' : NEEDS_CONNECTION));
      return;
    }
    const summary = sum.status === 'fulfilled' ? sum.value : null;
    last = { start, end, weights: w.value.weights || [], readings: b.value.readings || [], summary, unit: summary && summary.units === 'kg' ? 'kg' : (summary ? 'lb' : KH.body ? KH.body.units() : 'lb') };
    render();
  }

  let raf = 0;
  window.addEventListener('resize', () => {
    if (state.view !== 'trends' || !last) return;
    cancelAnimationFrame(raf);
    raf = requestAnimationFrame(render);
  });

  KH.bodyTrends = { show, render };
})();
