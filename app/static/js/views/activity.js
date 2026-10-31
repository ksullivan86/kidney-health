/* Kidney Diet Log — Activity and recovery from Whoop, and the active-day calorie extra (design note 28; app/activity.py).

   * KH.activityViews.show(start, end, source): the "Activity and recovery" card on Trends: calories burned, strain, recovery,
     resting heart rate, HRV, sleep and workouts for the period. It is shown only when there is something to show. A small bar
     chart of calories burned has a table under it with every value, so nothing depends on seeing the chart or on colour.
     `source` is a Care team share (js/views/sharing.js reads()); without the "activity and recovery" area the card stays hidden.
   * KH.activityViews.todayBlock(calorieExtra): the lines under Today's daily status: the base target and the active-day extra as
     separate lines, why the number is what it is, and on an active day one plain line about carbs and the care team.
   * KH.activityViews.extraBlock(): Settings → Connected devices → Whoop → "Add active-day calories to my target", with the share
     counted and an optional daily ceiling.

   HRV, recovery, sleep and strain are shown, never acted on: nothing here suggests, warns or changes a target from them. No
   insulin advice, and nothing about treating a low. All text goes in with h() children (textContent), never as HTML. */
(() => {
  'use strict';
  const KH = window.KH;
  const { h, s, $, clear, api, toast, toastError } = KH;
  const A = KH.activityRules;
  const { fmtDateShort, fmtMonthDay, daysBetween } = KH.util;

  const CARBS_LINE = 'Extra calories on active days change your carbs; your care team can help you plan insulin for exercise.';
  const ACCURACY = 'Tracker calories can be off by a lot, in either direction.';
  const NOT_ACTED_ON = 'Recovery, HRV, sleep and strain are shown for you and your care team. The app does not change anything because of them.';
  const fmtKcal = (n) => `${Math.round(n).toLocaleString('en-US')} kcal`;
  const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;
  const fmtSleep = (min) => (min == null ? '–' : `${Math.floor(min / 60)} h ${String(min % 60).padStart(2, '0')} min`);
  const dash = (v, unit = '') => (v == null ? '–' : `${v}${unit}`);

  // ---- Today --------------------------------------------------------------------------------------------------------------
  /** What Today says about the extra. `x` is GET /api/log's calorie_extra (never null here). */
  function todayLines(x) {
    if (x.quiet_kcal == null) {
      return { lines: [`Active-day calories start once Whoop has ${A.QUIET_MIN_DAYS} finished days in the last ${A.QUIET_WINDOW_DAYS} (${x.history_days} so far).`],
        active: false };
    }
    if (!x.extra_kcal) {
      return { lines: [`No active-day extra today so far: Whoop has counted ${fmtKcal(x.burned_kcal)}, and your usual quiet day is ${fmtKcal(x.quiet_kcal)}.`],
        active: false };
    }
    const why = `Whoop has counted ${fmtKcal(x.burned_kcal)} burned today so far. Your usual quiet day is ${fmtKcal(x.quiet_kcal)} `
      + `(the lowest quarter of your finished Whoop days in the last ${A.QUIET_WINDOW_DAYS}). The extra counts ${x.share_pct}% of the difference`
      + `${x.ceiling_kcal != null ? `, at most ${fmtKcal(x.ceiling_kcal)} a day` : ''}. Only the calorie target changes. ${ACCURACY}`;
    return { lines: [`Base target: ${fmtKcal(x.base_kcal)}`, `Active-day extra (from Whoop): +${fmtKcal(x.extra_kcal)}`], why, active: true };
  }

  function todayBlock(x) {
    const t = todayLines(x);
    const box = h('div', { class: 'activity-extra', id: 'today-activity-extra' });
    const list = h('ul', { class: 'activity-extra-lines' }, ...t.lines.map((line) => h('li', {}, line)));
    box.append(list);
    if (t.active) {
      box.append(h('details', { class: 'activity-why' }, h('summary', {}, 'Why this number'), h('p', {}, t.why)),
        h('p', { class: 'hint', id: 'today-activity-carbs' }, CARBS_LINE));
    }
    return box;
  }

  // ---- Settings → Connected devices → Whoop -------------------------------------------------------------------------------
  function extraBlock() {
    const box = h('div', { class: 'activity-extra-setting', id: 'set-whoop-extra' }, h('p', { class: 'hint' }, 'Loading…'));
    api.activity().then((res) => fillExtra(box, res.extra || { enabled: false, share_pct: A.SHARE_DEFAULT, ceiling_kcal: null }))
      .catch(() => { clear(box).append(h('p', { class: 'hint' }, 'The active-day calorie setting could not be loaded.')); });
    return box;
  }

  function fillExtra(box, extra) {
    const on = h('input', { type: 'checkbox', id: 'set-whoop-extra-on' });
    on.checked = !!extra.enabled;
    const share = h('input', { type: 'number', id: 'set-whoop-extra-share', min: String(A.SHARE_MIN), max: String(A.SHARE_MAX), step: '5',
      inputmode: 'numeric', value: String(extra.share_pct || A.SHARE_DEFAULT), 'aria-describedby': 'set-whoop-extra-share-help' });
    const ceiling = h('input', { type: 'number', id: 'set-whoop-extra-ceiling', min: String(A.CEILING_MIN), max: String(A.CEILING_MAX), step: '50',
      inputmode: 'numeric', value: extra.ceiling_kcal == null ? '' : String(extra.ceiling_kcal), 'aria-describedby': 'set-whoop-extra-ceiling-help' });
    const details = h('div', { class: 'activity-extra-fields', id: 'set-whoop-extra-fields' },
      h('label', { class: 'label', for: 'set-whoop-extra-share' }, 'Share of the extra to count (%)'), share,
      h('p', { class: 'hint', id: 'set-whoop-extra-share-help' }, `100% counts all of it; 50% counts half. Between ${A.SHARE_MIN} and ${A.SHARE_MAX}.`),
      h('label', { class: 'label', for: 'set-whoop-extra-ceiling' }, 'Most extra in a day (kcal, optional)'), ceiling,
      h('p', { class: 'hint', id: 'set-whoop-extra-ceiling-help' }, `Leave empty for no limit. Between ${A.CEILING_MIN} and ${A.CEILING_MAX}.`));
    details.hidden = !on.checked;
    on.addEventListener('change', () => { details.hidden = !on.checked; });
    const save = h('button', { class: 'btn secondary', type: 'button', id: 'set-whoop-extra-save' }, 'Save');
    const err = h('p', { class: 'form-error', id: 'set-whoop-extra-error', role: 'alert' });
    save.addEventListener('click', async () => {
      err.textContent = '';
      const shareN = Number(share.value);
      const ceilingN = ceiling.value.trim() === '' ? null : Number(ceiling.value);
      if (!Number.isInteger(shareN) || shareN < A.SHARE_MIN || shareN > A.SHARE_MAX) { err.textContent = `The share is a whole number from ${A.SHARE_MIN} to ${A.SHARE_MAX}.`; share.focus(); return; }
      if (ceilingN != null && (!Number.isInteger(ceilingN) || ceilingN < A.CEILING_MIN || ceilingN > A.CEILING_MAX)) {
        err.textContent = `The most extra in a day is a whole number from ${A.CEILING_MIN} to ${A.CEILING_MAX}, or empty.`; ceiling.focus(); return;
      }
      save.disabled = true;
      try {
        const out = await api.setActivityExtra({ enabled: on.checked, share_pct: shareN, ceiling_kcal: ceilingN });
        toast(out.enabled ? 'Active-day calories are on.' : 'Active-day calories are off.', 'ok');
      } catch (e) { if (!e.handled) toastError(e); } finally { save.disabled = false; }
    });
    clear(box).append(
      h('label', { class: 'check', for: 'set-whoop-extra-on' }, on, ' Add active-day calories to my target'),
      h('p', { class: 'hint' }, 'On a day Whoop counts more calories than your usual quiet day, the difference is added to your calorie target, '
        + `as the day goes on. Only calories change: protein, potassium, phosphorus, sodium and fluid stay the same. ${ACCURACY}`),
      details, h('div', { class: 'settings-actions' }, save), err);
  }

  // ---- Trends: the Activity and recovery card -----------------------------------------------------------------------------
  const card = $('#activity-trends');
  const body = $('#activity-trends-body');
  let req = 0;

  function average(rows, key) {
    const vals = rows.map((r) => r[key]).filter((v) => typeof v === 'number');
    return vals.length ? vals.reduce((a, b) => a + b, 0) / vals.length : null;
  }

  function kcalChart(days, start, end) {
    const width = 320, height = 120, padL = 36, padB = 18, padT = 6;
    const n = daysBetween(start, end) + 1;
    const slot = (width - padL) / n;
    const max = Math.max(...days.map((d) => d.kcal || 0), 1);
    const top = Math.ceil(max / 500) * 500;
    const y = (v) => padT + (height - padT - padB) * (1 - v / top);
    const shown = days.filter((d) => d.kcal != null);
    const svg = s('svg', { class: 'chart-svg activity-chart', viewBox: `0 0 ${width} ${height}`, role: 'img',
      'aria-label': `Calories burned each day, ${plural(shown.length, 'day', 'days')} from Whoop, between ${fmtKcal(Math.min(...shown.map((d) => d.kcal)))} `
        + `and ${fmtKcal(Math.max(...shown.map((d) => d.kcal)))}. The table under the chart lists every day.` });
    for (const tick of [0, top / 2, top]) {
      svg.append(s('line', { class: 'axis', x1: padL, x2: width, y1: y(tick), y2: y(tick) }),
        s('text', { x: padL - 4, y: y(tick) + 3.5, 'text-anchor': 'end' }, String(tick)));
    }
    for (const d of shown) {
      const i = daysBetween(start, d.date);
      const bar = s('rect', { class: `bar activity-bar${d.finished ? '' : ' ongoing'}`, x: padL + i * slot + slot * 0.15, y: y(d.kcal),
        width: Math.max(slot * 0.7, 1), height: Math.max(y(0) - y(d.kcal), 0) });
      bar.append(s('title', {}, `${fmtDateShort(d.date)}: ${fmtKcal(d.kcal)}${d.finished ? '' : ' so far'}`));
      svg.append(bar);
    }
    svg.append(s('text', { x: padL, y: height - 4 }, fmtMonthDay(start)), s('text', { x: width, y: height - 4, 'text-anchor': 'end' }, fmtMonthDay(end)));
    return svg;
  }

  function dayTable(days) {
    const head = ['Day', 'Burned', 'Strain', 'Recovery', 'Resting HR', 'HRV', 'Sleep'];
    const rows = [...days].reverse().map((d) => h('tr', {},
      h('th', { scope: 'row' }, fmtDateShort(d.date)),
      h('td', { class: 'num' }, d.kcal == null ? '–' : `${fmtKcal(d.kcal)}${d.finished ? '' : ' so far'}`),
      h('td', { class: 'num' }, dash(d.strain)), h('td', { class: 'num' }, dash(d.recovery_pct, '%')),
      h('td', { class: 'num' }, dash(d.resting_hr, ' bpm')), h('td', { class: 'num' }, dash(d.hrv_ms, ' ms')),
      h('td', { class: 'num' }, fmtSleep(d.sleep_minutes))));
    const table = h('table', { class: 'data-table body-table' },
      h('caption', { class: 'sr-only' }, 'Whoop days, newest first'),
      h('thead', {}, h('tr', {}, ...head.map((t, i) => h('th', { scope: 'col', class: i ? 'num' : '' }, t)))), h('tbody', {}, ...rows));
    return h('div', { class: 'body-table-wrap', tabindex: '0', role: 'region', 'aria-label': 'Whoop days, every value' }, table);
  }

  function workoutList(workouts) {
    if (!workouts.length) return null;
    return h('div', {}, h('h4', { class: 'activity-sub' }, plural(workouts.length, 'workout', 'workouts')),
      h('ul', { class: 'activity-workouts' }, ...[...workouts].reverse().map((w) => h('li', {},
        [fmtDateShort(w.date), w.sport || 'workout', w.minutes != null ? `${w.minutes} min` : null,
          w.kcal != null ? fmtKcal(w.kcal) : null, w.strain != null ? `strain ${w.strain}` : null].filter(Boolean).join(' · ')))));
  }

  function summaryList(days) {
    const items = [
      ['Calories burned', average(days, 'kcal'), (v) => `${fmtKcal(v)} a day`],
      ['Strain', average(days, 'strain'), (v) => v.toFixed(1)],
      ['Recovery', average(days, 'recovery_pct'), (v) => `${Math.round(v)}%`],
      ['Resting heart rate', average(days, 'resting_hr'), (v) => `${Math.round(v)} bpm`],
      ['HRV', average(days, 'hrv_ms'), (v) => `${Math.round(v)} ms`],
      ['Sleep', average(days, 'sleep_minutes'), (v) => fmtSleep(Math.round(v))],
    ].filter(([, v]) => v != null);
    return h('dl', { class: 'activity-summary' }, ...items.flatMap(([label, v, f]) => [h('dt', {}, label), h('dd', {}, f(v))]));
  }

  async function show(start, end, source = null) {
    if (!card || !body) return;
    const my = ++req;
    if (source && !(source.areas || []).includes('activity')) { card.hidden = true; clear(body); return; }
    let res;
    try { res = await (source ? source.reads.activity(start, end) : api.activity(start, end)); } catch (e) {
      if (my === req) { card.hidden = true; clear(body); }
      return;
    }
    if (my !== req) return;
    const days = res.days || [];
    const workouts = res.workouts || [];
    if (!days.length && !workouts.length) { card.hidden = true; clear(body); return; }
    const sub = $('#activity-trends-sub');
    if (sub) sub.textContent = `from Whoop · average per day with data · ${plural(days.length, 'day', 'days')}`;
    const parts = [summaryList(days)];
    if (days.some((d) => d.kcal != null)) parts.push(kcalChart(days, start, end));
    if (days.length) parts.push(dayTable(days));
    const list = workoutList(workouts);
    if (list) parts.push(list);
    parts.push(h('p', { class: 'hint' }, `${ACCURACY} ${NOT_ACTED_ON}`));
    clear(body).append(...parts);
    card.hidden = false;
  }

  KH.activityViews = { show, todayBlock, todayLines, extraBlock, CARBS_LINE, ACCURACY, NOT_ACTED_ON };
})();
