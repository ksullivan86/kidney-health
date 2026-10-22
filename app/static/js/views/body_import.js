/* Kidney Diet Log — weights and blood pressure from the iPhone Health app's export.xml: the import sheet (KH.bodyImport; docs/dev/research/
   10-weight-and-blood-pressure.md section 4.8, ARCHITECTURE.md "Weight and blood pressure", docs/body.md). Opened with KH.bodyImport.open()
   from Trends and from Settings → Your data; the markup is <dialog id="sheet-body-import"> in index.html.

   * The person exports from the Health app, unzips export.zip in the Files app and chooses apple_health_export/export.xml. THE FILE IS READ
     ON THIS DEVICE, as a stream of text, by KH.appleHealth (js/engine/apple_health.js); it can be hundreds of megabytes, so it is never
     held whole and never given to an XML parser. Nothing is uploaded while it is read. A Cancel aborts the scan.
   * The review shows what was found, what was left out and why (plain words), the date range, a period (the last 3 months by default, or
     everything), the counts for the period, and the sources. Readings from a source whose name contains "Watch" are listed apart and
     UNTICKED (note 10 F4: cuffless devices are not recommended for checking blood pressure); the person decides. A source name comes from
     the file and is drawn with textContent, like everything else here.
   * Import sends only the rows the person keeps, in batches of 1,000, to POST /api/body/weights/batch and /blood-pressure/batch through
     KH.api (importWeights, importBloodPressures): the fields of the reader's rows without sourceName (KH.appleHealth.forUpload) and
     source "apple_health". Importing the same file again adds nothing (the rows' source_key).
   * A day can hold at most 20 weights and 30 readings (KH.bodyRules.LIMITS, the server's own); a batch with a row that would overfill a day
     is refused whole. So before sending, the first rows of such a day in time order are kept and the rest are left out, and the result says
     so ("5 more on 1 day were left out"). How many a day can still take comes from the list routes for the period (rows the person
     already has); if they cannot be read, the limit alone is used. Rows an earlier import of this file stored (an imported row with the same
     time and numbers) take no room, so importing the same file again does not call them "left out". If the server still refuses (another
     device added rows meanwhile, the hourly limit of 60 requests, a version difference), the import STOPS: the sheet shows the server's own
     words and how many were already added, and nothing is dropped silently; pressing Import again carries on, skipping what is already here.
   * When rows were added Today and Trends are loaded again, the way the other imports do (the caches in KH.state are cleared and a
     showing Today or Trends is shown again).

   Rules: everything that comes from the file or the server is drawn with textContent (the h() helper), never as HTML; no inline script,
   handler or style; the only network calls are the app's own API; nothing is stored in the browser. */
(() => {
  'use strict';
  const KH = window.KH;
  const { h, $, clear, api, state, toast, router, sheets } = KH;
  const { todayStr, addDays, parseDate } = KH.util;
  const AH = KH.appleHealth;
  const LIMIT = KH.bodyRules.LIMITS;

  const SOURCE = 'apple_health'; // what a batch row may say besides "import" (app/models.py BodyImportSource)
  const WINDOW_DAYS = 366; // the list routes take at most 366 days
  const PERIOD_RECENT = 'recent';
  const PERIOD_ALL = 'all';
  const WATCH_NOTE = 'Cuffless devices such as watches and rings are not recommended for checking blood pressure (2025 AHA/ACC guideline). '
    + 'These readings are not ticked. Tick a source only if you want its readings in your log.';
  const CANCEL_LABEL = { pick: 'Close', reading: 'Cancel', review: 'Cancel', importing: 'Stop', done: 'Close' };

  const fmt = (n) => Number(n).toLocaleString('en-US');
  const plural = (n, one, many) => `${fmt(n)} ${n === 1 ? one : many}`;
  const weightsText = (n) => plural(n, 'weight', 'weights');
  const readingsText = (n, long = false) => plural(n, long ? 'blood pressure reading' : 'reading', long ? 'blood pressure readings' : 'readings');
  const recordsText = (n) => plural(n, 'record', 'records');
  const countsText = (c) => `${weightsText(c.weights)} and ${readingsText(c.readings)}`;
  const fmtDay = (iso) => parseDate(iso).toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric' });
  const megabytes = (bytes) => `${(bytes / 1048576).toFixed(bytes >= 10 * 1048576 ? 0 : 1)} MB`;

  // The two kinds of row, with what differs between them. `same` says whether a stored row (list route) is probably the file's row.
  const KINDS = {
    weights: {
      key: 'weights', many: 'weights', limit: LIMIT.max_weights_per_day,
      list: (start, end) => api.bodyWeights(start, end), post: (rows) => api.importWeights(rows),
      same: (stored, row) => stored.time === row.time && Math.abs(Number(stored.kg) - row.kg) < 0.005,
    },
    readings: {
      key: 'readings', many: 'readings', limit: LIMIT.max_readings_per_day,
      list: (start, end) => api.bloodPressures(start, end), post: (rows) => api.importBloodPressures(rows),
      same: (stored, row) => stored.time === row.time && stored.systolic === row.systolic && stored.diastolic === row.diastolic,
    },
  };

  const dlg = $('#sheet-body-import');
  const input = $('#body-import-file');
  const pickEl = $('#body-import-pick');
  const problemEl = $('#body-import-problem');
  const statusEl = $('#body-import-status');
  const reviewEl = $('#body-import-review');
  const cancelBtn = $('#body-import-cancel');
  const goBtn = $('#body-import-go');

  // One import at a time. `seq` numbers the reads: a result that comes back for an older number is dropped.
  const imp = {
    phase: 'pick', seq: 0, ctrl: null, res: null, period: PERIOD_RECENT, since: null, ticked: new Set(), stop: false, batch: null,
    ui: { hints: {}, watch: [], days: null, controls: [] },
  };

  // ---------------------------------------------------------------------------
  // What the sheet says
  // ---------------------------------------------------------------------------
  function status(text) { statusEl.textContent = text || ''; }
  function problem(lines) {
    clear(problemEl);
    const list = lines ? [].concat(lines) : [];
    for (const line of list) problemEl.append(h('p', {}, line));
    problemEl.hidden = !list.length;
  }

  // What was found but cannot be kept, in plain words, one line per reason (none for a reason that did not happen).
  function leftOutLines(res) {
    const s = res.summary;
    const k = s.skipped;
    const lines = [];
    const add = (n, text) => { if (n > 0) lines.push(text(n)); };
    add(k.unknownUnit, (n) => `${recordsText(n)} in a unit the app does not read (weights in kg or lb, blood pressure in mmHg)`);
    add(k.halfPair, (n) => `${plural(n, 'blood pressure record', 'blood pressure records')} with only a top number or only a bottom number`);
    add(s.found.weights - s.kept.weights, (n) => `${weightsText(n)} outside what the app accepts (${LIMIT.min_kg} to ${LIMIT.max_kg} kg)`);
    add(s.found.readings - s.kept.readings, (n) => `${readingsText(n, true)} outside what the app accepts (top number ${LIMIT.min_systolic} to ${LIMIT.max_systolic}, `
      + `bottom number ${LIMIT.min_diastolic} to ${LIMIT.max_diastolic}, top above bottom)`);
    add(k.unreadable, (n) => `${recordsText(n)} the app could not read (a value, a date or a source that is missing or not valid)`);
    add(k.badEntity, (n) => `${recordsText(n)} with a character code the app does not read`);
    add(k.tagTooLong, (n) => `${recordsText(n)} that were too long to read`);
    add(k.duplicate, (n) => `${plural(n, 'repeat', 'repeats')} of a record that is already counted`);
    return lines;
  }

  // After the import: "5 more on 1 day were left out (the app keeps at most 20 weights and 30 readings a day)", or '' when no day was over.
  // In the review, before the rows the person already has are known: what the file alone shows (so, at least that many).
  function leftOutText(weightsPlan, readingsPlan, future) {
    const n = weightsPlan.leftOut + readingsPlan.leftOut;
    if (!n) return '';
    const days = new Set([...weightsPlan.days, ...readingsPlan.days]).size;
    const limits = `at most ${LIMIT.max_weights_per_day} weights and ${LIMIT.max_readings_per_day} readings a day`;
    if (future) {
      return `${fmt(n)} or more will be left out: ${plural(days, 'day', 'days')} in the file ${days === 1 ? 'has' : 'have'} more than the app keeps (${limits}).`;
    }
    return `${fmt(n)} more on ${plural(days, 'day', 'days')} ${n === 1 ? 'was' : 'were'} left out (the app keeps ${limits}).`;
  }

  const addedText = (t) => `Added ${weightsText(t.weights)} and ${plural(t.readings, 'reading', 'readings')}`;
  const alreadyText = (t) => (t.already ? `; ${fmt(t.already)} ${t.already === 1 ? 'was' : 'were'} already here` : '');

  // "(the row dated Oct 4, 2026)" for a server message that names a row of the batch that was refused ("rows.5: too many ...").
  function rowNote(detail, batch) {
    const m = /^rows\.(\d+)\b/.exec(String(detail));
    const row = m && batch ? batch[Number(m[1])] : null;
    return row && row.date ? ` (the row dated ${fmtDay(row.date)})` : '';
  }

  // ---------------------------------------------------------------------------
  // Days with more rows than a day can hold
  // ---------------------------------------------------------------------------
  /* The rows of `rows` (the reader's, in date and time order) that can be sent: each day's first rows in time order, as many as the day can
     still take. `limit` is the server's most per day; `stored` the rows the person already has (list route rows with date, time, source and
     the numbers) or null when they could not be read; `same(stored, row)` says whether a stored row is probably the file's row.
     A day whose rows fit is kept whole. Otherwise the rows that an earlier import of this file stored (a stored row that is not typed in
     by hand, with the same time and numbers; each stored row matches one file row) are kept without taking room, because the server skips
     them; the rest keep their time order and only as many as there is room for stay. Returns {keep, leftOut, days}: the rows to send, how
     many were dropped and the Set of the days they were dropped from. */
  function trimDays(rows, limit, stored, same) {
    const perDay = new Map();
    for (const r of rows) {
      const list = perDay.get(r.date);
      if (list) list.push(r); else perDay.set(r.date, [r]);
    }
    const have = new Map();
    for (const e of stored || []) {
      const list = have.get(e.date);
      if (list) list.push(e); else have.set(e.date, [e]);
    }
    const dropped = new Set();
    const days = new Set();
    let leftOut = 0;
    for (const [day, list] of perDay) {
      const here = have.get(day) || [];
      const room = Math.max(0, limit - here.length);
      if (list.length <= room) continue;
      const pool = here.filter((e) => e.source !== 'manual');
      const fresh = [];
      for (const r of list) {
        const at = pool.findIndex((e) => same(e, r));
        if (at >= 0) pool.splice(at, 1); else fresh.push(r);
      }
      const cut = fresh.slice(room);
      for (const r of cut) dropped.add(r);
      if (cut.length) { leftOut += cut.length; days.add(day); }
    }
    return { keep: dropped.size ? rows.filter((r) => !dropped.has(r)) : rows, leftOut, days };
  }

  // The rows the person already has for the days of `rows`, or null when they could not be read (then only the limit is used). The list
  // routes take at most 366 days, so a long file is asked for in windows, and a window with no row of the file in it is not asked for.
  async function storedRows(kind, rows) {
    if (!rows.length) return [];
    const first = rows[0].date;
    const last = rows[rows.length - 1].date;
    const have = [];
    try {
      for (let start = first; start <= last; start = addDays(start, WINDOW_DAYS)) {
        const end = addDays(start, WINDOW_DAYS - 1);
        if (!rows.some((r) => r.date >= start && r.date <= end)) continue;
        const res = await kind.list(start, end < last ? end : last);
        for (const e of (res && res[kind.key]) || []) have.push(e);
      }
    } catch (err) {
      if (err && err.handled) throw err; // signed out: the sign-in screen is showing
      return null;
    }
    return have;
  }

  // ---------------------------------------------------------------------------
  // The sheet's steps
  // ---------------------------------------------------------------------------
  function setPhase(phase) {
    imp.phase = phase;
    pickEl.hidden = phase !== 'pick';
    reviewEl.hidden = !(phase === 'review' || phase === 'importing' || phase === 'done');
    goBtn.hidden = !(phase === 'review' || phase === 'importing');
    cancelBtn.textContent = CANCEL_LABEL[phase];
    cancelBtn.disabled = false;
    for (const c of imp.ui.controls) c.disabled = phase === 'importing';
    if (phase === 'importing') reviewEl.setAttribute('aria-busy', 'true'); else reviewEl.removeAttribute('aria-busy');
  }

  // Back to choosing a file: a read in progress is dropped, and the file and what was read from it are forgotten.
  function reset() {
    imp.seq += 1;
    if (imp.ctrl) { try { imp.ctrl.abort(); } catch (e) { /* already finished */ } }
    imp.ctrl = null;
    imp.res = null;
    imp.ticked.clear();
    imp.period = PERIOD_RECENT;
    imp.since = null;
    imp.batch = null;
    imp.ui = { hints: {}, watch: [], days: null, controls: [] };
    input.value = '';
    clear(reviewEl);
    problem(null);
    status('');
    goBtn.textContent = 'Import';
    setPhase('pick');
  }

  function open(trigger) {
    if (imp.phase === 'importing') { sheets.open(dlg, trigger); return; } // an import is still running: show it
    reset();
    sheets.open(dlg, trigger, input);
  }

  function refuse(message) {
    input.value = '';
    problem(message);
  }

  async function onPick() {
    const file = input.files && input.files[0];
    if (!file) return;
    problem(null);
    status('');
    const name = String(file.name || '');
    if (/\.zip$/i.test(name) || file.type === 'application/zip') {
      refuse('That is the whole export. In Files, tap export.zip to unzip it, then choose apple_health_export/export.xml.');
    } else if (/cda/i.test(name)) {
      refuse('That is the clinical documents file (export_cda.xml). Choose export.xml from the same folder.');
    } else if (!file.size) {
      refuse('That file is empty. Choose export.xml from the unzipped export folder.');
    } else if (typeof file.stream !== 'function' || typeof TextDecoderStream !== 'function') {
      refuse('This browser cannot read a file this large here. Update it, or open the app in a newer browser.');
    } else {
      await startScan(file);
    }
  }

  async function startScan(file) {
    imp.seq += 1;
    const mine = imp.seq;
    const ctrl = new AbortController();
    imp.ctrl = ctrl;
    const name = String(file.name);
    setPhase('reading');
    status(`Reading ${name} (${megabytes(file.size)}) on this device…`);
    try {
      const text = file.stream().pipeThrough(new TextDecoderStream());
      const res = await AH.scan(text, {
        today: todayStr(),
        signal: ctrl.signal,
        onProgress: ({ chars }) => { if (mine === imp.seq) status(`Reading ${name}: about ${megabytes(Math.min(chars, file.size))} of ${megabytes(file.size)}…`); },
      });
      if (mine !== imp.seq) return; // Cancel, or a newer pick, took over
      imp.ctrl = null;
      imp.res = res;
      status('');
      showReview();
    } catch (err) {
      if (mine !== imp.seq) return;
      imp.ctrl = null;
      input.value = '';
      setPhase('pick');
      status('');
      problem(err && err.name === 'AbortError' ? 'The reading was cancelled. Nothing was saved.'
        : 'The file could not be read. Make sure it is on this device (in Files, tap it once so it downloads), then choose it again.');
    }
  }

  // The rows for a period (since: 'YYYY-MM-DD', or null for everything): readings from a watch-like source only when its box is ticked.
  function select(since) {
    const wanted = (r) => !AH.isWatchSource(r.sourceName) || imp.ticked.has(r.sourceName);
    return { weights: AH.filterSince(imp.res.weights, since), readings: AH.filterSince(imp.res.readings, since).filter(wanted) };
  }
  const currentSince = () => (imp.period === PERIOD_RECENT ? imp.since : null);

  function refresh() {
    const ui = imp.ui;
    const since = currentSince();
    const chosen = select(since);
    const s = imp.res.summary;
    if (ui.hints[PERIOD_RECENT]) {
      const c = select(imp.since);
      ui.hints[PERIOD_RECENT].textContent = `Since ${fmtDay(imp.since)}: ${countsText({ weights: c.weights.length, readings: c.readings.length })}.`;
    }
    if (ui.hints[PERIOD_ALL]) {
      const c = select(null);
      ui.hints[PERIOD_ALL].textContent = `${fmtDay(s.firstDate)} to ${fmtDay(s.lastDate)}: ${countsText({ weights: c.weights.length, readings: c.readings.length })}.`;
    }
    if (ui.watch.length) {
      const inPeriod = AH.filterSince(imp.res.readings, since);
      for (const w of ui.watch) w.hint.textContent = `${readingsText(inPeriod.filter((r) => r.sourceName === w.name).length)} in this period`;
    }
    const parts = [chosen.weights.length ? weightsText(chosen.weights.length) : null, chosen.readings.length ? readingsText(chosen.readings.length) : null].filter(Boolean);
    goBtn.textContent = parts.length ? `Import ${parts.join(' and ')}` : 'Import';
    goBtn.disabled = !parts.length;
    const text = leftOutText(trimDays(chosen.weights, KINDS.weights.limit, null, KINDS.weights.same),
      trimDays(chosen.readings, KINDS.readings.limit, null, KINDS.readings.same), true);
    ui.days.textContent = text;
    ui.days.hidden = !text;
  }

  function showReview() {
    const res = imp.res;
    const s = res.summary;
    const ui = imp.ui;
    const found = s.found.weights + s.found.readings;
    const kept = s.kept.weights + s.kept.readings;
    imp.since = AH.defaultSince(todayStr());
    imp.ticked.clear();
    // The period picker is of use only when the file has rows older than the default period.
    const picker = kept > 0 && s.firstDate < imp.since;
    imp.period = picker ? PERIOD_RECENT : PERIOD_ALL;
    clear(reviewEl);
    ui.controls = [];

    const headline = h('p', { class: 'bi-headline', id: 'body-import-summary', role: 'status', tabindex: '-1' },
      found === 0 ? 'No weights or blood pressure readings were found in this file.'
        : `Found ${weightsText(s.found.weights)} and ${readingsText(s.found.readings, true)}. The app can keep ${weightsText(s.kept.weights)} and ${readingsText(s.kept.readings)}.`);
    reviewEl.append(headline);
    if (found === 0) {
      reviewEl.append(h('p', { class: 'hint' }, 'Choose export.xml from the unzipped Health export (the apple_health_export folder). If it is the right file, it holds no weights or blood pressure readings in kg, lb or mmHg.'));
    }
    if (kept > 0) {
      reviewEl.append(h('p', { class: 'bi-range', id: 'body-import-range' },
        s.firstDate === s.lastDate ? `Date in the file: ${fmtDay(s.firstDate)}.` : `Dates in the file: ${fmtDay(s.firstDate)} to ${fmtDay(s.lastDate)}.`));
      if (s.sourceNames.length) {
        const shown = s.sourceNames.slice(0, 6).join(', ');
        const more = s.sourceNames.length > 6 ? ` and ${s.sourceNames.length - 6} more` : '';
        reviewEl.append(h('p', { class: 'bi-sources', id: 'body-import-sources' }, `From: ${shown}${more}.`));
      }
    }
    const lines = leftOutLines(res);
    if (lines.length) {
      reviewEl.append(h('p', { class: 'bi-left-title' }, 'Left out:'), h('ul', { class: 'bi-left-out', id: 'body-import-left-out' }, lines.map((t) => h('li', {}, t))));
    }
    if (kept === 0) { // nothing to import: Cancel goes back to the file chooser
      setPhase('review');
      goBtn.hidden = true;
      focusHeadline(headline);
      return;
    }

    if (picker) {
      const field = h('fieldset', { class: 'field choice-list', id: 'body-import-period' }, h('legend', {}, 'Which dates to import'));
      for (const [value, title] of [[PERIOD_RECENT, 'The last 3 months'], [PERIOD_ALL, 'Everything in the file']]) {
        const id = `body-import-period-${value}`;
        const radio = h('input', { type: 'radio', name: 'body-import-period', id, value });
        radio.checked = value === imp.period;
        radio.addEventListener('change', () => { if (radio.checked) { imp.period = value; refresh(); } });
        const hint = h('span', { class: 'hint', id: `${id}-hint` });
        ui.hints[value] = hint;
        ui.controls.push(radio);
        field.append(h('label', { class: 'choice', for: id }, radio, h('span', { class: 'choice-text' }, h('b', {}, title), hint)));
      }
      reviewEl.append(field);
    } else {
      reviewEl.append(h('p', { class: 'hint', id: 'body-import-period' }, 'All of it is from the last 3 months.'));
    }

    // Readings from a watch-like source: listed apart, unticked.
    const watchCounts = new Map();
    for (const r of res.readings) if (AH.isWatchSource(r.sourceName)) watchCounts.set(r.sourceName, (watchCounts.get(r.sourceName) || 0) + 1);
    if (watchCounts.size) {
      const box = h('fieldset', { class: 'field bi-watch', id: 'body-import-watch' }, h('legend', {}, 'Blood pressure from a watch'), h('p', { class: 'hint' }, WATCH_NOTE));
      let i = 0;
      for (const name of [...watchCounts.keys()].sort()) {
        const id = `body-import-watch-${i}`;
        i += 1;
        const box1 = h('input', { type: 'checkbox', id });
        box1.checked = false;
        box1.addEventListener('change', () => { if (box1.checked) imp.ticked.add(name); else imp.ticked.delete(name); refresh(); });
        const hint = h('span', { class: 'hint' });
        ui.watch.push({ name, hint });
        ui.controls.push(box1);
        box.append(h('label', { class: 'choice', for: id }, box1, h('span', { class: 'choice-text' }, h('b', {}, name), hint)));
      }
      reviewEl.append(box);
    }

    ui.days = h('p', { class: 'bi-days', id: 'body-import-days', hidden: true });
    reviewEl.append(ui.days, h('p', { class: 'hint' }, 'Nothing is saved until you press Import. Importing the same file again adds nothing: what is already here is skipped.'));
    setPhase('review');
    refresh();
    focusHeadline(headline);
  }

  function focusHeadline(el) { if (el && el.focus) el.focus(); }

  // ---------------------------------------------------------------------------
  // Import
  // ---------------------------------------------------------------------------
  // Sends the rows of one kind in batches of 1,000. false when the person pressed Stop (or closed the sheet) between two requests.
  async function send(kind, rows, totals) {
    if (!rows.length) return true;
    const upload = AH.forUpload(rows).map((r) => ({ ...r, source: SOURCE }));
    let sent = 0;
    for (const batch of AH.batches(upload)) {
      if (imp.stop) return false;
      status(`Saving ${kind.many}: ${fmt(sent)} of ${fmt(upload.length)}…`);
      imp.batch = batch;
      const res = await kind.post(batch);
      totals[kind.key] += Number(res.added) || 0;
      totals.already += Number(res.skipped) || 0;
      sent += batch.length;
    }
    return true;
  }

  // Today and Trends keep what they loaded: forget it, and load a showing one again.
  function refreshViews() {
    state.dayLoadedFor = null;
    state.trends = null;
    state.summary = null;
    if (state.view === 'today' || state.view === 'trends') router.show(state.view);
  }

  async function runImport() {
    if (imp.phase !== 'review' || !imp.res) return;
    const chosen = select(currentSince());
    const totals = { weights: 0, readings: 0, already: 0 };
    let weightsPlan = { keep: [], leftOut: 0, days: new Set() };
    let readingsPlan = weightsPlan;
    imp.stop = false;
    imp.batch = null;
    problem(null);
    setPhase('importing');
    goBtn.textContent = 'Importing…';
    goBtn.disabled = true;
    try {
      status('Checking what you already have…');
      const [haveWeights, haveReadings] = await Promise.all([storedRows(KINDS.weights, chosen.weights), storedRows(KINDS.readings, chosen.readings)]);
      weightsPlan = trimDays(chosen.weights, KINDS.weights.limit, haveWeights, KINDS.weights.same);
      readingsPlan = trimDays(chosen.readings, KINDS.readings.limit, haveReadings, KINDS.readings.same);
      const finished = (await send(KINDS.weights, weightsPlan.keep, totals)) && (await send(KINDS.readings, readingsPlan.keep, totals));
      const left = leftOutText(weightsPlan, readingsPlan, false);
      if (finished) {
        const sentence = `${addedText(totals)}${alreadyText(totals)}.`;
        setPhase('done');
        status('');
        clear(reviewEl).append(h('div', { class: 'bi-result' }, h('p', { class: 'bi-headline', id: 'body-import-result', role: 'status', tabindex: '-1' }, sentence),
          left ? h('p', { class: 'bi-days', id: 'body-import-left' }, left) : null,
          h('p', { class: 'hint' }, 'Importing the same file again adds nothing: what is already here is skipped.')));
        focusHeadline($('#body-import-result'));
        toast(sentence, 'ok');
      } else {
        const sentence = `Stopped. ${addedText(totals)}${alreadyText(totals)} so far. Press Import to carry on: what is already here is skipped.`;
        setPhase('review');
        refresh();
        status(sentence);
        if (!dlg.open) toast(sentence);
      }
    } catch (err) {
      if (err && err.handled) { // signed out: the sign-in screen needs the page
        if (dlg.open) dlg.close();
      } else {
        const detail = (err && (err.detail || err.message)) || 'Something went wrong';
        const done = totals.weights + totals.readings > 0
          ? `${addedText(totals)}${alreadyText(totals)} before it stopped.` : 'Nothing was added.';
        const lines = [`The import stopped: ${detail}${rowNote(detail, imp.batch)}`, `${done} Nothing that was added is lost. Press Import to try again: what is already here is skipped.`];
        setPhase('review');
        refresh();
        status('');
        problem(lines);
        if (!dlg.open) toast(lines.join(' '), 'error');
      }
    } finally {
      imp.stop = false;
      if (totals.weights + totals.readings > 0) refreshViews();
      if (!dlg.open) reset(); // the sheet was closed meanwhile: let go of the file's rows
    }
  }

  function onCancel() {
    if (imp.phase === 'reading') {
      reset();
      status('Cancelled. Nothing was read or saved.');
      input.focus();
    } else if (imp.phase === 'review') {
      reset();
      status('Cancelled. Nothing was saved.');
      input.focus();
    } else if (imp.phase === 'importing') {
      imp.stop = true;
      cancelBtn.disabled = true;
      status('Stopping after the step in progress…');
    } else {
      dlg.close();
    }
  }

  sheets.setup(dlg);
  dlg.addEventListener('close', () => {
    if (imp.phase === 'importing') { imp.stop = true; return; } // the request in flight finishes; the result comes as a message
    reset();
  });
  input.addEventListener('change', onPick);
  cancelBtn.addEventListener('click', onCancel);
  goBtn.addEventListener('click', runImport);

  KH.bodyImport = { open, trimDays };
})();
