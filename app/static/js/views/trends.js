/* Kidney Diet Log — Trends view: the period summary card, one inline-SVG bar chart per
   targeted nutrient (with a table twin), and CSV export (a download in the installed app, a
   copyable text sheet in the demo, which cannot download files). */
(() => {
  'use strict';
  const KH = window.KH;
  const { h, s, $, $$, clear, api, state, toastError, router, sheets } = KH;
  const { NUT, ASSESSMENT, fmtNum, pct } = KH.rules;
  const { TREND_ORDER, LEVEL_TEXT, levelPill } = KH.ui;
  const { todayStr, addDays, parseDate, fmtDateShort, fmtMonthDay, fmtRange, fmtChange } = KH.util;
  const { MOCK } = KH.flags;

  const chartsEl = $('#charts');
  const chartTip = $('#chart-tip');
  let trendsRequest = 0;
  $$('.segmented .seg[data-days]').forEach((b) => b.addEventListener('click', () => {
    state.trendsDays = Number(b.dataset.days);
    $$('.segmented .seg[data-days]').forEach((x) => x.setAttribute('aria-pressed', x === b ? 'true' : 'false'));
    loadTrends();
  }));
  async function loadTrends() {
    const reqId = ++trendsRequest;
    const end = todayStr();
    const start = addDays(end, -(state.trendsDays - 1));
    $('#trends-title').textContent = `Last ${state.trendsDays} days`;
    if (KH.guidance) KH.guidance.trends(state.trendsDays).catch((e) => console.warn('Insights:', e)); // js/views/guidance.js
    $('#trends-range').textContent = `${fmtDateShort(start)} – ${fmtDateShort(end)}`;
    const exportLink = $('#export-csv');
    if (MOCK) {
      // The demo cannot download (the preview's frame blocks it): show the CSV in a sheet instead.
      exportLink.removeAttribute('download');
      exportLink.setAttribute('href', '#export');
      exportLink.setAttribute('role', 'button');
      exportLink.setAttribute('aria-haspopup', 'dialog');
      exportLink.onclick = (e) => { e.preventDefault(); openCsvSheet(start, end, exportLink); };
      exportLink.onkeydown = (e) => { if (e.key === ' ') { e.preventDefault(); openCsvSheet(start, end, exportLink); } };
    } else {
      exportLink.setAttribute('download', `kidney-log_${start}_${end}.csv`);
      exportLink.href = api.exportUrl(start, end);
      exportLink.onclick = null;
    }
    chartsEl.style.opacity = state.trends ? '0.6' : '';
    try {
      const [res, sum] = await Promise.all([
        api.range(start, end),
        api.summary(start, end).then((v) => ({ ok: v })).catch((e) => ({ err: e })),
      ]);
      if (reqId !== trendsRequest) return;
      state.trends = { start, end, days: res.days || [] };
      state.summary = sum.ok || null;
      renderTrends();
      renderPeriodSummary(sum.ok, sum.err);
    } catch (e) { if (reqId === trendsRequest) toastError(e); }
    finally { chartsEl.style.opacity = ''; }
  }
  // ---- CSV sheet (demo only): the text to copy, since the preview cannot download files ----
  const csvDlg = $('#sheet-csv');
  sheets.setup(csvDlg);
  async function openCsvSheet(start, end, trigger) {
    let csv;
    try { csv = await KH.mock.instance.request('GET', api.exportUrl(start, end)); } catch (err) { toastError(err); return; }
    const rows = Math.max(0, csv.split('\r\n').filter(Boolean).length - 1);
    $('#sheet-csv-sub').textContent = `${fmtRange(start, end)} · ${rows} ${rows === 1 ? 'entry' : 'entries'} · kidney-log_${start}_${end}.csv`;
    $('#csv-text').value = csv;
    $('#csv-status').textContent = '';
    sheets.open(csvDlg, trigger, $('#csv-copy'));
  }
  $('#csv-copy').addEventListener('click', () => {
    const ta = $('#csv-text');
    const status = $('#csv-status');
    const selectAll = () => {
      ta.focus();
      ta.select();
      try { ta.setSelectionRange(0, ta.value.length); } catch (e) { /* ignore */ }
      let copied = false;
      try { copied = !!(document.execCommand && document.execCommand('copy')); } catch (e) { copied = false; }
      status.textContent = copied ? 'CSV copied to the clipboard.'
        : 'Copying is blocked here, so the text is selected: press Ctrl+C (⌘C on a Mac), or long-press it and choose Copy.';
    };
    // A frame without clipboard-write would reject (and log an error); skip straight to selecting.
    const policy = document.permissionsPolicy || document.featurePolicy;
    let allowed = true;
    try { allowed = !policy || typeof policy.allowsFeature !== 'function' || policy.allowsFeature('clipboard-write'); } catch (e) { allowed = true; }
    try {
      if (allowed && navigator.clipboard && typeof navigator.clipboard.writeText === 'function') {
        navigator.clipboard.writeText(ta.value).then(() => { status.textContent = 'CSV copied to the clipboard.'; }, selectAll);
      } else selectAll();
    } catch (e) { selectAll(); }
  });
  function renderPeriodSummary(sum, err) {
    const body = clear($('#period-body'));
    const inter = clear($('#period-interdialytic'));
    inter.hidden = true;
    const notes = clear($('#period-notes'));
    if (err || !sum) {
      $('#period-sub').textContent = '';
      body.append(h('p', { class: 'empty-state' }, `Period summary unavailable${err ? ` (${err.detail || err.message})` : ''}.`));
      return;
    }
    $('#period-sub').textContent = `${fmtRange(sum.start, sum.end)} · ${sum.logged_days} of ${sum.days} days logged`;
    const keys = Object.keys(sum.nutrients || {}).filter((k) => NUT[k]).sort((a, b) => TREND_ORDER.indexOf(a) - TREND_ORDER.indexOf(b));
    if (!keys.length) {
      body.append(h('p', { class: 'empty-state' }, 'No targets set yet. Set targets in Profile to see a summary.'));
      return;
    }
    const grid = h('div', { class: 'period-grid' });
    for (const key of keys) {
      const nt = sum.nutrients[key];
      const n = NUT[key];
      const weekly = (nt.assessment || ASSESSMENT[key]) === 'weekly_average';
      // The tag names the period actually averaged: "weekly average" only for a 7-day range.
      const avgTag = sum.days === 7 ? 'weekly average' : `${sum.days}-day average`;
      const avgTitle = sum.days === 7 ? 'Judged on the weekly average' : `Judged on the ${sum.days}-day average`;
      const level = nt.level || 'ok';
      const avgText = nt.average == null ? '—' : fmtNum(nt.average, key);
      const change = fmtChange(nt.change_pct);
      const dir = nt.change_pct == null ? '' : nt.change_pct > 0.05 ? 'up' : nt.change_pct < -0.05 ? 'down' : 'flat';
      // For limits a rise is bad news; for calories/protein it is neutral.
      const tone = nt.role === 'limit' ? (dir === 'up' ? 'bad' : dir === 'down' ? 'good' : '') : '';
      const row = h('div', { class: `period-row level-${level}`, role: 'group',
        'aria-label': `${n.label}: average ${avgText} of ${fmtNum(nt.target, key)} ${n.unit} per day${nt.level ? `, ${LEVEL_TEXT[nt.level]}` : ''}, ${nt.days_over} days over${change ? `, ${change} versus the previous period` : ''}` });
      row.append(h('div', { class: 'period-top' },
        h('div', { class: 'period-name' }, n.label,
          h('span', { class: `strip-tag ${weekly ? 'weekly' : 'daily'}`, title: weekly ? avgTitle : 'Judged day by day' }, weekly ? avgTag : 'day by day')),
        nt.level ? levelPill(nt.level, LEVEL_TEXT[nt.level]) : h('span', { class: 'muted small' }, 'no data')));
      row.append(h('div', { class: 'period-nums tabular' }, h('b', {}, avgText), h('span', { class: 'muted' }, ` / ${fmtNum(nt.target, key)} ${n.unit} per day`)));
      row.append(h('div', { class: 'strip-track' }, h('div', { class: 'strip-fill', style: `width:${Math.round(Math.max(0, Math.min(1, nt.fraction || 0)) * 100)}%` })));
      const facts = [];
      if (nt.average != null) facts.push(`${pct(nt.fraction)} % of ${nt.role === 'goal' ? 'goal' : 'target'}`);
      facts.push(`${nt.days_over} ${nt.days_over === 1 ? 'day' : 'days'} over`);
      if (nt.max_day) facts.push(`highest ${fmtMonthDay(nt.max_day.date)}: ${fmtNum(nt.max_day.value, key)}`);
      const foot = h('div', { class: 'period-foot' }, facts.join(' · '));
      if (change) foot.append(h('span', { class: `period-change ${tone}` }, `${change} vs previous ${sum.days} days`));
      else if (nt.average != null) foot.append(h('span', { class: 'period-change' }, `no data in the previous ${sum.days} days`));
      row.append(foot);
      grid.append(row);
    }
    body.append(grid);
    if (sum.interdialytic && sum.interdialytic.nutrients && Object.keys(sum.interdialytic.nutrients).length) {
      inter.hidden = false;
      inter.append(KH.views.today.interdialyticBlock(sum.interdialytic, false));
    }
    for (const t of sum.notes || []) notes.append(h('li', {}, t));
  }
  function hasData(day) { return !!(day.totals && Object.values(day.totals).some((v) => v)); }
  function renderTrends() {
    const t = state.trends;
    if (!t) return;
    clear(chartsEl);
    const keys = new Set();
    for (const d of t.days) for (const k of Object.keys(d.status || {})) if (NUT[k]) keys.add(k);
    const ordered = [...keys].sort((a, b) => TREND_ORDER.indexOf(a) - TREND_ORDER.indexOf(b));
    if (!ordered.length) {
      chartsEl.append(h('p', { class: 'card empty-state' }, 'No targets set yet. Set targets in Profile to see trends.'));
      return;
    }
    const width = Math.max(240, Math.floor((chartsEl.clientWidth - (chartsEl.clientWidth >= 700 ? 12 : 0)) / (chartsEl.clientWidth >= 700 ? 2 : 1)) - 34);
    for (const key of ordered) chartsEl.append(chartCard(key, t.days, width));
  }
  function chartCard(key, days, width) {
    const n = NUT[key];
    const points = days.map((d) => {
      const st = (d.status && d.status[key]) || {};
      return { date: d.date, value: d.totals ? d.totals[key] || 0 : 0, level: st.level || 'ok', target: st.target, min: st.min, has: hasData(d) };
    });
    const last = [...points].reverse().find((p) => p.target != null) || {};
    const target = last.target;
    const min = last.min;
    const withData = points.filter((p) => p.has);
    const avg = withData.length ? withData.reduce((a, p) => a + p.value, 0) / withData.length : null;
    const overDays = withData.filter((p) => p.level === 'over').length;
    const card = h('section', { class: 'card chart-card', 'aria-labelledby': `chart-h-${key}` });
    card.append(h('div', { class: 'card-head' }, h('h3', { class: 'card-title', id: `chart-h-${key}` }, `${n.label} (${n.unit})`),
      h('span', { class: 'muted small tabular' }, target != null ? `target ${min != null ? `${fmtNum(min, key)}–` : ''}${fmtNum(target, key)}` : 'no target')));
    card.append(h('div', { class: 'chart-sub' },
      h('span', {}, avg != null ? `Average ${fmtNum(avg, key)} ${n.unit}` : 'No entries in this range'),
      withData.length ? h('span', {}, `${overDays} ${overDays === 1 ? 'day' : 'days'} over`) : null));
    card.append(barChart(key, points, target, min, width));
    // Table twin (values reachable without hover)
    const table = h('table', { class: 'data-table' },
      h('thead', {}, h('tr', {}, h('th', {}, 'Date'), h('th', { class: 'num' }, n.unit), h('th', { class: 'num' }, '% of target'), h('th', {}, 'Level'))));
    const tb = h('tbody');
    for (const p of points) {
      tb.append(h('tr', {},
        h('td', {}, fmtDateShort(p.date)),
        h('td', { class: 'num' }, p.has ? fmtNum(p.value, key) : '—'),
        h('td', { class: 'num' }, p.has && target ? `${pct(p.value / target)} %` : '—'),
        h('td', {}, p.has ? h('span', { class: `lvl level-${p.level}` }, h('i', { class: 'swatch' }), LEVEL_TEXT[p.level]) : h('span', { class: 'muted' }, 'no entries'))));
    }
    table.append(tb);
    card.append(h('details', { class: 'inline-details' }, h('summary', {}, 'Show as table'), table));
    return card;
  }
  function barChart(key, points, target, min, width) {
    // Across a month boundary the day numbers restart at 1, so a second label line names the
    // month under the first labelled bar of each month (padB grows to make room for it).
    const spansMonths = new Set(points.map((p) => p.date.slice(0, 7))).size > 1;
    const padL = 46, padR = 10, padT = 14, padB = spansMonths ? 34 : 22, H = 128 + padB;
    const W = Math.max(220, width);
    const plotW = W - padL - padR, plotH = H - padT - padB;
    const maxV = Math.max(target || 0, ...points.map((p) => p.value), 1);
    const yMax = target ? Math.max(target * 1.25, maxV * 1.05) : maxV * 1.1;
    const y = (v) => padT + plotH - (v / yMax) * plotH;
    const slot = plotW / points.length;
    const barW = Math.min(24, Math.max(3, slot - 4));
    const svg = s('svg', { class: 'chart-svg', viewBox: `0 0 ${W} ${H}`, width: W, height: H, role: 'group',
      'aria-label': `${NUT[key].label} per day for the last ${points.length} days${target ? `, target ${fmtNum(target, key)} ${NUT[key].unit}` : ''}` });
    // baseline + y labels
    svg.append(s('line', { class: 'axis', x1: padL, x2: W - padR, y1: y(0) + 0.5, y2: y(0) + 0.5 }));
    svg.append(s('text', { x: padL - 6, y: y(0) + 3, 'text-anchor': 'end' }, '0'));
    if (target) {
      svg.append(s('line', { class: 'target', x1: padL, x2: W - padR, y1: y(target), y2: y(target) }));
      svg.append(s('text', { x: padL - 6, y: y(target) + 3.5, 'text-anchor': 'end' }, fmtNum(target, key)));
      if (min != null) {
        svg.append(s('line', { class: 'target-min', x1: padL, x2: W - padR, y1: y(min), y2: y(min) }));
        svg.append(s('text', { x: padL - 6, y: y(min) + 3.5, 'text-anchor': 'end' }, fmtNum(min, key)));
      }
    }
    const labelEvery = slot >= 22 ? 1 : slot >= 12 ? 2 : slot >= 8 ? 3 : 5;
    let lastLabelledMonth = null;
    const cells = [];
    points.forEach((p, i) => {
      const x0 = padL + i * slot;
      const bx = x0 + (slot - barW) / 2;
      const bar = p.has ? roundedBar(bx, y(p.value), barW, y(0) - y(p.value), 4) : s('line', { class: 'nodata', x1: bx + 1, x2: bx + barW - 1, y1: y(0) - 1, y2: y(0) - 1 });
      bar.setAttribute('class', p.has ? `bar level-${p.level}` : 'nodata');
      const text = p.has ? `${fmtDateShort(p.date)}: ${fmtNum(p.value, key)} ${NUT[key].unit}${target ? ` (${pct(p.value / target)} % of target), ${LEVEL_TEXT[p.level]}` : ''}` : `${fmtDateShort(p.date)}: no entries`;
      const hit = s('rect', { class: 'hit', x: x0, y: padT - 4, width: slot, height: plotH + 4, rx: 4, tabindex: 0, role: 'img', 'aria-label': text });
      hit.append(s('title', {}, text));
      const show = () => { bar.style.opacity = '0.7'; showTip(hit, text, p); };
      const hide = () => { bar.style.opacity = ''; hideTip(); };
      // A mouse hovers each bar; touch and pen are handled for the whole chart below.
      hit.addEventListener('pointerenter', (ev) => { if (ev.pointerType === 'mouse') show(); });
      hit.addEventListener('pointerleave', (ev) => { if (ev.pointerType === 'mouse') hide(); });
      hit.addEventListener('focus', show); hit.addEventListener('blur', hide);
      cells.push({ bar, hit, text, p });
      svg.append(bar, hit);
      if ((points.length - 1 - i) % labelEvery === 0) {
        const d = parseDate(p.date);
        const labelY = spansMonths ? H - 18 : H - 6;
        svg.append(s('text', { x: x0 + slot / 2, y: labelY, 'text-anchor': 'middle' }, String(d.getDate())));
        const month = p.date.slice(0, 7);
        if (spansMonths && month !== lastLabelledMonth) {
          lastLabelledMonth = month;
          svg.append(s('text', { class: 'month', x: x0 + slot / 2, y: H - 6, 'text-anchor': 'middle' }, d.toLocaleDateString('en-US', { month: 'short' })));
        }
      }
    });
    // Touch and pen: press anywhere on the chart and slide sideways to read each day. At 30 days
    // a phone gives each bar about 8 px, too narrow to tap one reliably. The value stays shown
    // until the next tap elsewhere or a scroll.
    let active = -1;
    const release = () => { if (active >= 0) cells[active].bar.style.opacity = ''; active = -1; hideTip(); };
    const activate = (i) => {
      if (i === active) return;
      if (active >= 0) cells[active].bar.style.opacity = '';
      active = i;
      const c = cells[i];
      c.bar.style.opacity = '0.7';
      showTip(c.hit, c.text, c.p);
      touchTip = { svg, release };
    };
    const indexAt = (ev) => {
      const r = svg.getBoundingClientRect();
      const x = ((ev.clientX - r.left) / (r.width || 1)) * W;
      return Math.max(0, Math.min(points.length - 1, Math.floor((x - padL) / slot)));
    };
    svg.addEventListener('pointerdown', (ev) => { if (ev.pointerType !== 'mouse') activate(indexAt(ev)); });
    svg.addEventListener('pointermove', (ev) => { if (ev.pointerType !== 'mouse' && active >= 0 && ev.buttons) activate(indexAt(ev)); });
    return svg;
  }
  let touchTip = null; // { svg, release } of the chart whose value a touch is showing
  function releaseTouchTip(ev) {
    if (!touchTip || (ev && ev.type === 'pointerdown' && touchTip.svg.contains(ev.target))) return;
    const t = touchTip;
    touchTip = null;
    t.release();
  }
  document.addEventListener('pointerdown', releaseTouchTip, true);
  window.addEventListener('scroll', () => releaseTouchTip(), { passive: true });
  function roundedBar(x, yTop, w, hgt, r) {
    if (hgt <= r || w <= 2 * r) return s('rect', { x, y: yTop, width: w, height: Math.max(hgt, 1), rx: Math.min(r, hgt / 2) });
    const d = `M${x},${yTop + hgt} V${yTop + r} Q${x},${yTop} ${x + r},${yTop} H${x + w - r} Q${x + w},${yTop} ${x + w},${yTop + r} V${yTop + hgt} Z`;
    return s('path', { d });
  }
  function showTip(anchor, text, p) {
    clear(chartTip);
    const [datePart, rest] = text.split(': ');
    chartTip.append(h('div', {}, h('b', {}, rest || datePart)), rest ? h('div', { class: 'small' }, datePart) : null);
    chartTip.hidden = false;
    const r = anchor.getBoundingClientRect();
    const tw = chartTip.offsetWidth, th = chartTip.offsetHeight;
    let left = r.left + r.width / 2 - tw / 2;
    left = Math.max(8, Math.min(window.innerWidth - tw - 8, left));
    let top = r.top - th - 8;
    if (top < 8) top = r.bottom + 8;
    chartTip.style.left = `${left}px`; chartTip.style.top = `${top}px`;
    void p;
  }
  function hideTip() { chartTip.hidden = true; }
  let resizeRaf = 0;
  window.addEventListener('resize', () => {
    if (state.view !== 'trends' || !state.trends) return;
    cancelAnimationFrame(resizeRaf);
    resizeRaf = requestAnimationFrame(renderTrends);
  });

  router.register('trends', () => loadTrends());
  KH.views.trends = { loadTrends, renderTrends, renderPeriodSummary };
})();
