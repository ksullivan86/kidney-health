/* Kidney Diet Log — Weight and blood pressure: the Today card, the two sheets, the Settings section and the numbers Profile offers
   (ARCHITECTURE.md "Weight and blood pressure", note 10 §4.6). The charts are js/views/body_trends.js.

   The app records a weight or a blood pressure reading and shows it back. It never says what a number means, never names a cause
   and never suggests a treatment or a medicine. It never suggests a weight-gain alarm or a blood pressure goal either: those are
   the numbers the person's care team gave them, typed in Settings. The one thing the app adds is a pointer: a weight over the
   person's alarm, or a reading with a top number of 180 or more or a bottom number of 120 or more, carries the handbook's own words
   and a link to its Get help now page (the server sends them in `flag`; js/engine/body.js is the demo's copy). A very high
   reading is a block that stands out and is listed first, with the 911 line first in it.

   * Today (js/views/today.js calls KH.body.today(date) after it draws a day): the day's weights and readings with Edit and Delete,
     Add weight and Add blood pressure (the sheets; nothing is saved until Save), and the alarm line or the goal line when the person
     set one, naming the two weights compared.
   * The sheets: the weight in the person's unit with the other unit echoed ("154.3 lb = 70.0 kg"), when it was taken (the dialysis
     choices only for a profile on dialysis); the top number then the bottom number with their plain names, the one line about how to
     measure, and the reading echoed ("Top 180, bottom 95") so a typing slip is seen before Save.
   * Settings → Weight and blood pressure: the unit, the alarm and the goal, each saying it is the care team's number.
   * Profile (js/views/profile.js calls KH.body.profileHints()): the log's latest weight and the weight about six months before it,
     each offered with "Use this"; Profile is never changed unless the person taps it and presses Save.
   * Nothing is kept offline: a save needs the connection to the server and says so.

   All text goes in with textContent (h() children), never as HTML; no inline script or style. */
(() => {
  'use strict';
  const KH = window.KH;
  const { h, $, clear, api, state, toast, toastError, sheets, router } = KH;
  const R = KH.bodyRules;
  const U = KH.bodyUi;
  const { ratingIcon } = KH.ui;
  const { todayStr, addDays, fmtDateShort, fmtMonthDay } = KH.util;

  const todayBody = $('#body-today-body');
  const addWeightBtn = $('#body-add-weight');
  const addBpBtn = $('#body-add-bp');
  const weightDlg = $('#sheet-weight');
  const bpDlg = $('#sheet-bp');
  if (!todayBody || !addWeightBtn || !addBpBtn || !weightDlg || !bpDlg || !R || !U) return;
  sheets.setup(weightDlg);
  sheets.setup(bpDlg);

  const NEEDS_CONNECTION = 'Weights and blood pressure readings need a connection to your server, and there is none right now.';
  // What the person last saw: their weight unit (user.units.weight, "lb" until the server says otherwise).
  const S = { units: 'lb', shownDate: null, req: 0, busy: false, summary: null };

  const live = (text) => { const el = $('#body-live'); if (el) el.textContent = text; };
  const message = (text) => h('p', { class: 'body-empty' }, text);
  const onDialysis = () => !!(state.profile && state.profile.dialysis && state.profile.dialysis !== 'none');
  const learnLink = (key, text, anchor = '') => {
    const e = KH.learn && KH.learn.info() && KH.learn.info().links && KH.learn.info().links.pages && KH.learn.info().links.pages[key];
    const target = e && KH.learn.href(e.path + anchor);
    return target ? h('a', { class: 'learn-more', href: target, target: '_blank', rel: 'noopener' }, text, h('span', { class: 'sr-only' }, ' (opens in a new tab)')) : null;
  };

  // ---- the handbook's line -------------------------------------------------------------------------------------------
  // `flag` is the server's flag: { level, text, href, link_text, prominent }. The words are the server's, never this file's; `label`
  // names the reading. The link goes where the handbook is served (no handbook, no link: the line stays).
  function flagBlock(flag, label = null) {
    const target = KH.learn ? KH.learn.href(flag.href) : null;
    const link = target ? h('a', { class: 'learn-more', href: target, target: '_blank', rel: 'noopener' }, flag.link_text, h('span', { class: 'sr-only' }, ' (opens in a new tab)')) : null;
    return h('div', { class: `body-flag${flag.prominent ? ' prominent' : ''}` },
      ratingIcon(flag.prominent ? 'over' : 'caution', { decorative: true }),
      h('div', { class: 'body-flag-text' },
        label ? h('b', { class: 'body-flag-label' }, label) : null,
        h('p', {}, flag.text, link ? [' ', link] : null)));
  }

  // ---- Today ---------------------------------------------------------------------------------------------------------
  const readingText = (r) => `${r.systolic}/${r.diastolic}`;
  const readingWhen = (r) => [U.contextLabel('bp', r.context), U.fmtTime(r.time)].filter(Boolean).join(', ');

  // "from a shortcut (Morning weight)" for a row a phone shortcut's token sent (also "from the Health app", "from a file"); nothing for a
  // typed row. The token's name is the person's own text: it is drawn as text.
  const originEl = (row) => { const text = U.originText(row); return text ? h('span', { class: 'body-when body-origin' }, text) : null; };

  function weightItem(w) {
    const what = `${R.formatWeight(w.kg, S.units)}, ${U.contextLabel('weight', w.context)}, ${fmtDateShort(w.date)}`;
    const edit = h('button', { class: 'link-btn', type: 'button', 'aria-label': `Edit ${what}` }, 'Edit');
    const del = h('button', { class: 'link-btn danger-link', type: 'button', 'aria-label': `Delete ${what}` }, 'Delete');
    const actions = h('div', { class: 'body-actions-row' }, edit, del);
    edit.addEventListener('click', (ev) => openWeight({ weight: w, trigger: ev.currentTarget }));
    del.addEventListener('click', (ev) => KH.confirm.inline(actions, ev.currentTarget, {
      message: `Delete the weight ${R.formatWeight(w.kg, S.units)} (${U.contextLabel('weight', w.context).toLowerCase()}) from ${fmtDateShort(w.date)}?`,
      onConfirm: async () => { await api.deleteWeight(w.id); await afterDelete(`Deleted ${what}.`, 'Weight deleted'); return true; },
    }));
    return h('li', { class: 'body-item' },
      h('div', { class: 'body-main' }, h('span', { class: 'body-val' }, R.formatWeight(w.kg, S.units)),
        h('span', { class: 'body-when' }, [U.contextLabel('weight', w.context), U.fmtTime(w.time)].filter(Boolean).join(', ')),
        originEl(w), actions),
      w.note ? h('p', { class: 'body-note' }, w.note) : null);
  }

  function readingItem(r) {
    const what = `${readingText(r)}, ${readingWhen(r)}, ${fmtDateShort(r.date)}`;
    const edit = h('button', { class: 'link-btn', type: 'button', 'aria-label': `Edit blood pressure ${what}` }, 'Edit');
    const del = h('button', { class: 'link-btn danger-link', type: 'button', 'aria-label': `Delete blood pressure ${what}` }, 'Delete');
    const actions = h('div', { class: 'body-actions-row' }, edit, del);
    edit.addEventListener('click', (ev) => openBp({ reading: r, trigger: ev.currentTarget }));
    del.addEventListener('click', (ev) => KH.confirm.inline(actions, ev.currentTarget, {
      message: `Delete the blood pressure reading ${readingText(r)} (${readingWhen(r).toLowerCase()}) from ${fmtDateShort(r.date)}?`,
      onConfirm: async () => { await api.deleteBloodPressure(r.id); await afterDelete(`Deleted blood pressure ${what}.`, 'Reading deleted'); return true; },
    }));
    return h('li', { class: `body-item${r.flag ? ' flagged' : ''}` },
      h('div', { class: 'body-main' }, h('span', { class: 'body-val' }, readingText(r)),
        r.pulse != null ? h('span', { class: 'body-when' }, `pulse ${r.pulse}`) : null,
        h('span', { class: 'body-when' }, readingWhen(r)),
        originEl(r),
        r.flag ? h('span', { class: 'body-tag' }, 'See the handbook note') : null, actions),
      r.note ? h('p', { class: 'body-note' }, r.note) : null);
  }

  async function afterDelete(announce, toastText) {
    toast(toastText, 'ok');
    live(announce);
    await loadToday(S.shownDate || todayStr());
    const heading = $('#body-today-h');
    if (heading) { heading.setAttribute('tabindex', '-1'); heading.focus(); }
  }

  // The weight-gain alarm's line (summary.weight.alarm, null with no alarm number or no weight): how much the weight changed, the
  // alarm as the person's care team gave it, and the two weights compared, as the server names them.
  function alarmLine(alarm, latest) {
    const box = h('div', { class: 'body-line', id: 'body-alarm-line' });
    const rule = `Your alarm: ${U.alarmSentence(alarm, S.units)}.`;
    if (alarm.status !== 'compared') {
      box.append(h('p', {}, h('b', {}, 'Weight-gain alarm. '), alarm.message ? `${alarm.message}. ` : '', rule));
      return box;
    }
    const now = `${R.formatWeight(latest.kg, S.units)} (${fmtMonthDay(latest.date)}, ${U.contextLabel('weight', latest.context).toLowerCase()})`;
    box.append(h('p', {}, h('b', {}, `Weight ${U.gainText(alarm.gain_kg, S.units)}. `), alarm.over_alarm ? h('b', {}, 'Over your alarm. ') : 'Not over your alarm. ', rule),
      h('p', { class: 'body-line-sub' }, `Latest: ${now}. ${alarm.message}`));
    if (alarm.flag) box.append(flagBlock(alarm.flag));
    return box;
  }
  // The goal's line: the goal as the care team gave it and what the last 7 days averaged against it.
  function goalLine(bp) {
    const text = U.goalText(bp.goal);
    const box = h('div', { class: 'body-line', id: 'body-goal-line' });
    box.append(h('p', {}, h('b', {}, 'Blood pressure goal from your care team: '), `${text}.`));
    for (const line of U.weekSentences(bp.week, bp.goal)) box.append(h('p', { class: 'body-line-sub' }, line));
    return box;
  }

  function renderToday(weights, readings, summary) {
    clear(todayBody);
    // a very high reading first, and prominent: one block (its words are the same for every such reading)
    const flagged = readings.filter((r) => r.flag).sort((a, b) => (b.flag.prominent ? 1 : 0) - (a.flag.prominent ? 1 : 0));
    if (flagged.length) {
      const label = `${flagged.length === 1 ? 'Reading' : 'Readings'} ${flagged.map((r) => `${readingText(r)}${r.time ? ` at ${U.fmtTime(r.time)}` : ''}`).join(' and ')}`;
      todayBody.append(flagBlock(flagged[0].flag, label));
    }
    const alarmSet = !!(summary && summary.weight && summary.weight.alarm);
    const goalSet = !!(summary && summary.bp && U.goalText(summary.bp.goal));
    if (alarmSet) todayBody.append(alarmLine(summary.weight.alarm, summary.weight.latest));
    if (goalSet) todayBody.append(goalLine(summary.bp));
    if (!weights.length && !readings.length) todayBody.append(message('No weight or blood pressure recorded for this day.'));
    if (weights.length) todayBody.append(h('h3', { class: 'body-sub-h' }, 'Weight'), h('ul', { class: 'body-list' }, weights.map(weightItem)));
    if (readings.length) todayBody.append(h('h3', { class: 'body-sub-h' }, 'Blood pressure'), h('ul', { class: 'body-list' }, readings.map(readingItem)));
    if (summary && !alarmSet && !goalSet) {
      const settings = h('button', { class: 'link-btn', type: 'button', id: 'body-open-settings' }, 'Settings');
      settings.addEventListener('click', () => router.show('settings'));
      todayBody.append(h('p', { class: 'body-hint-line' }, 'To see how a weight or a reading compares with the numbers your care team gave you, enter them in ', settings, '.'));
    }
  }

  async function loadToday(date) {
    const req = ++S.req;
    S.shownDate = date;
    S.summary = null;
    const future = date > todayStr();
    addWeightBtn.disabled = future;
    addBpBtn.disabled = future;
    if (future) { clear(todayBody).append(message('You can record weights and blood pressure for today and for days that have passed.')); return; }
    clear(todayBody).append(h('p', { class: 'body-empty', id: 'body-today-loading' }, 'Loading weights and blood pressure…'));
    if (!state.profile) { try { await KH.loadProfile(); } catch (e) { /* the sheets then offer the choices that need no dialysis */ } }
    const [w, b, sum] = await Promise.allSettled([api.bodyWeights(date, date), api.bloodPressures(date, date), api.bodySummary(date)]);
    if (req !== S.req) return;
    const failure = [w, b].find((x) => x.status === 'rejected');
    if (failure) {
      const err = failure.reason;
      clear(todayBody).append(message(err && err.status ? 'Weights and blood pressure could not be loaded.' : NEEDS_CONNECTION),
        h('button', { class: 'link-btn', type: 'button', onclick: () => loadToday(date) }, 'Try again'));
      return;
    }
    S.summary = sum.status === 'fulfilled' ? sum.value : null;
    if (S.summary && S.summary.units) S.units = S.summary.units;
    renderToday(w.value.weights || [], b.value.readings || [], S.summary);
  }

  // ---- the sheets: shared parts ----------------------------------------------------------------------------------------
  const timeOf = (input) => (input.value ? input.value : null);
  function fillContexts(box, name, kind, current) {
    clear(box);
    for (const [key, label] of U.contextChoices(kind, onDialysis(), current)) {
      const id = `${name}-${key.replace(/_/g, '-')}`;
      const radio = h('input', { type: 'radio', name, id, value: key });
      radio.checked = key === current;
      box.append(radio, h('label', { for: id }, label));
    }
    box.classList.toggle('body-seg-4', box.querySelectorAll('input').length >= 4);
  }
  const chosen = (box) => { const r = $('input:checked', box); return r ? r.value : ''; };
  const showError = (box, text) => { box.textContent = text || ''; box.hidden = !text; };
  function dayToSave() { return S.shownDate && S.shownDate <= todayStr() ? S.shownDate : todayStr(); }
  // A refused save keeps the sheet open with what was typed: a lost connection says so, a refusal says why.
  function saveFailed(box, err) {
    if (err && err.handled) return;
    if (err && (err.status === 400 || err.status === 422)) showError(box, err.detail || err.message);
    else if (err && err.offline) showError(box, `${NEEDS_CONNECTION} Nothing was saved.`);
    else toastError(err);
  }

  // ---- the weight sheet ------------------------------------------------------------------------------------------------
  const wForm = $('#weight-form');
  const wValue = $('#weight-value');
  const wCtx = $('#weight-context');
  const wDate = $('#weight-date');
  const wTime = $('#weight-time');
  const wNote = $('#weight-note');
  const wEcho = $('#weight-echo');
  const wError = $('#weight-error');
  const wSave = $('#weight-save');
  const W = { editing: null, initialText: '' };

  function syncWeightEcho() {
    const res = U.weightFromInput(wValue.value, S.units);
    wEcho.textContent = res.kg != null ? U.echoWeight(res.kg, S.units) : '';
  }
  wValue.addEventListener('input', syncWeightEcho);

  function openWeight({ weight = null, trigger = null } = {}) {
    W.editing = weight;
    $('#sheet-weight-title').textContent = weight ? 'Edit weight' : 'Add a weight';
    $('#weight-label').textContent = `Weight (${S.units})`;
    $('#weight-hint').textContent = `Your unit is ${S.units === 'lb' ? 'pounds' : 'kilograms'}; you can change it in Settings. The app keeps weights in kilograms.`;
    W.initialText = weight ? U.inputNumber(R.shownWeight(weight.kg, S.units).toFixed(1)) : '';
    wValue.value = W.initialText;
    fillContexts(wCtx, 'weight-context', 'weight', weight ? weight.context : '');
    wDate.value = weight ? weight.date : dayToSave();
    wDate.max = todayStr();
    wTime.value = weight && weight.time ? weight.time : '';
    wNote.value = weight ? weight.note : '';
    showError(wError, '');
    syncWeightEcho();
    sheets.open(weightDlg, trigger, wValue);
  }
  addWeightBtn.addEventListener('click', (ev) => openWeight({ trigger: ev.currentTarget }));

  sheets.onSubmit(wForm, async (e) => {
    e.preventDefault();
    if (S.busy) return;
    const res = U.weightFromInput(wValue.value, S.units);
    if (res.error) { showError(wError, res.error); wValue.focus(); return; }
    const context = chosen(wCtx);
    if (!context) { showError(wError, 'Choose when it was taken.'); const first = $('input', wCtx); if (first) first.focus(); return; }
    if (!/^\d{4}-\d{2}-\d{2}$/.test(wDate.value)) { showError(wError, 'Choose the date.'); wDate.focus(); return; }
    // An edit that leaves the number as shown keeps the stored weight to the hundredth (the box shows one decimal).
    const kg = W.editing && wValue.value.trim() === W.initialText ? W.editing.kg : res.kg;
    const body = { date: wDate.value, time: timeOf(wTime), kg, context, note: wNote.value };
    const editing = W.editing;
    S.busy = true;
    wSave.disabled = true;
    showError(wError, '');
    try {
      const saved = editing ? await api.updateWeight(editing.id, body) : await api.addWeight(body);
      weightDlg.close();
      toast(editing ? 'Weight updated' : 'Weight saved', 'ok');
      live(`${editing ? 'Updated' : 'Saved'} weight ${R.formatWeight(saved.kg, S.units)}, ${fmtDateShort(saved.date)}.`);
      await loadToday(S.shownDate || todayStr());
    } catch (err) {
      saveFailed(wError, err);
    } finally {
      S.busy = false;
      wSave.disabled = false;
    }
  });

  // ---- the blood pressure sheet ----------------------------------------------------------------------------------------
  const bForm = $('#bp-form');
  const bTop = $('#bp-systolic');
  const bBottom = $('#bp-diastolic');
  const bPulse = $('#bp-pulse');
  const bCtx = $('#bp-context');
  const bDate = $('#bp-date');
  const bTime = $('#bp-time');
  const bNote = $('#bp-note');
  const bEcho = $('#bp-echo');
  const bFlag = $('#bp-flag');
  const bError = $('#bp-error');
  const bSave = $('#bp-save');
  const B = { editing: null };

  // The reading as typed, before Save, and (for a valid reading) the handbook's words if it is very high: the same twin of the
  // server's rule the demo uses (KH.bodyRules.bpFlag).
  function syncBp() {
    bEcho.textContent = U.echoReading(bTop.value, bBottom.value, bPulse.value);
    clear(bFlag);
    const res = U.readingFromInput({ systolic: bTop.value, diastolic: bBottom.value, pulse: bPulse.value });
    if (res.systolic != null && res.diastolic != null && !res.errors.systolic && !res.errors.diastolic) {
      const flag = R.bpFlag(res.systolic, res.diastolic);
      if (flag) bFlag.append(flagBlock(flag, `Reading ${res.systolic}/${res.diastolic}`));
    }
  }
  for (const el of [bTop, bBottom, bPulse]) el.addEventListener('input', syncBp);

  function openBp({ reading = null, trigger = null } = {}) {
    B.editing = reading;
    $('#sheet-bp-title').textContent = reading ? 'Edit blood pressure reading' : 'Add a blood pressure reading';
    const hint = $('#bp-hint');
    clear(hint).append(U.BP_HINT);
    const how = learnLink('weight_and_blood_pressure', 'How to measure', '#how-to-measure');
    if (how) hint.append(' ', how);
    bTop.value = reading ? String(reading.systolic) : '';
    bBottom.value = reading ? String(reading.diastolic) : '';
    bPulse.value = reading && reading.pulse != null ? String(reading.pulse) : '';
    fillContexts(bCtx, 'bp-context', 'bp', reading ? reading.context : '');
    bDate.value = reading ? reading.date : dayToSave();
    bDate.max = todayStr();
    bTime.value = reading && reading.time ? reading.time : '';
    bNote.value = reading ? reading.note : '';
    showError(bError, '');
    syncBp();
    sheets.open(bpDlg, trigger, bTop);
  }
  addBpBtn.addEventListener('click', (ev) => openBp({ trigger: ev.currentTarget }));

  sheets.onSubmit(bForm, async (e) => {
    e.preventDefault();
    if (S.busy) return;
    const res = U.readingFromInput({ systolic: bTop.value, diastolic: bBottom.value, pulse: bPulse.value });
    const fields = [['systolic', bTop], ['diastolic', bBottom], ['pulse', bPulse]];
    const bad = fields.find(([k]) => res.errors[k]);
    if (bad) { showError(bError, res.errors[bad[0]]); bad[1].focus(); return; }
    const context = chosen(bCtx);
    if (!context) { showError(bError, 'Choose when it was taken.'); const first = $('input', bCtx); if (first) first.focus(); return; }
    if (!/^\d{4}-\d{2}-\d{2}$/.test(bDate.value)) { showError(bError, 'Choose the date.'); bDate.focus(); return; }
    const body = { date: bDate.value, time: timeOf(bTime), systolic: res.systolic, diastolic: res.diastolic, pulse: res.pulse, context, note: bNote.value };
    const editing = B.editing;
    S.busy = true;
    bSave.disabled = true;
    showError(bError, '');
    try {
      const saved = editing ? await api.updateBloodPressure(editing.id, body) : await api.addBloodPressure(body);
      bpDlg.close();
      toast(editing ? 'Reading updated' : 'Reading saved', 'ok');
      live(`${editing ? 'Updated' : 'Saved'} blood pressure ${readingText(saved)}, ${fmtDateShort(saved.date)}.${saved.flag ? ' The handbook note for a very high reading is at the top of the card.' : ''}`);
      await loadToday(S.shownDate || todayStr());
      if (saved.flag) { const block = $('.body-flag', todayBody); if (block) { block.setAttribute('tabindex', '-1'); block.focus(); } }
    } catch (err) {
      saveFailed(bError, err);
    } finally {
      S.busy = false;
      bSave.disabled = false;
    }
  });

  // ---- Settings → Weight and blood pressure -------------------------------------------------------------------------------
  // The unit, the alarm and the goal. The alarm and the goal are the numbers the care team gave the person: the app suggests neither.
  let settingsReq = 0;
  let unitNote = ''; // what the unit change said, shown once the section is drawn again in the new unit
  async function renderSettings() {
    const body = $('#set-body-body');
    if (!body) return;
    const req = ++settingsReq;
    clear(body).append(h('p', { class: 'muted small' }, 'Loading…'));
    let items;
    try {
      items = (await api.mySettings()).settings;
      if (!state.profile) await KH.loadProfile().catch(() => null);
    } catch (err) {
      if (req !== settingsReq || (err && err.handled)) return;
      clear(body).append(h('p', { class: 'form-error' }, err && err.offline ? 'Your settings need a connection to your server, and there is none right now.' : 'Your settings could not be loaded.'));
      return;
    }
    if (req !== settingsReq) return;
    const unitItem = items['user.units.weight'];
    const alarmItem = items['body.weight_alarm'];
    const goalItem = items['body.bp_goal'];
    if (!unitItem || !alarmItem || !goalItem) { clear(body).append(h('p', { class: 'form-error' }, 'This server does not offer these settings.')); return; }
    const unit = unitItem.value === 'kg' ? 'kg' : 'lb';
    S.units = unit;
    const hd = !!(state.profile && state.profile.dialysis === 'hemodialysis');
    const sourceOf = (item) => h('span', { class: `setting-source src-${item.source}` }, KH.settings.SOURCE_LABEL[item.source] || item.source || '');
    clear(body);
    const how = learnLink('weight_and_blood_pressure', 'Learn: Weight and blood pressure');
    body.append(h('p', { class: 'hint' }, 'The app keeps a log of your weights and blood pressure readings. The two numbers below are the ones your care team gave you: the app never suggests a weight-gain alarm or a blood pressure goal.'),
      how ? h('p', { class: 'notes-learn' }, how) : null);

    // -- the unit
    const unitSel = h('select', { id: 'set-body-unit', 'aria-describedby': 'set-body-unit-hint set-body-unit-src' },
      h('option', { value: 'lb' }, 'Pounds (lb)'), h('option', { value: 'kg' }, 'Kilograms (kg)'));
    unitSel.value = unit;
    unitSel.disabled = unitItem.editable === false;
    const unitMsg = h('p', { class: 'status-msg', id: 'set-body-unit-msg', role: 'status', 'aria-live': 'polite' });
    unitSel.addEventListener('change', async () => {
      unitSel.disabled = true;
      try {
        await api.updateMySettings({ 'user.units.weight': unitSel.value });
        unitNote = unitSel.value === 'kg' ? 'Weights are now shown and typed in kilograms.' : 'Weights are now shown and typed in pounds.';
        S.units = unitSel.value;
        state.trends = null;
        state.dayLoadedFor = null;
        await renderSettings(); // the alarm's box is in the unit too
        const again = $('#set-body-unit');
        if (again) again.focus();
      } catch (err) { if (!err.handled) toastError(err); unitSel.value = unit; } finally { unitSel.disabled = unitItem.editable === false; }
    });
    body.append(h('div', { class: 'field' }, h('label', { for: 'set-body-unit' }, 'Unit for weight'), unitSel,
      h('span', { class: 'hint', id: 'set-body-unit-hint' }, 'Only how a weight is shown and typed changes; weights are kept in kilograms.'),
      h('span', { id: 'set-body-unit-src' }, sourceOf(unitItem)), unitMsg));
    unitMsg.textContent = unitNote;
    unitNote = '';

    // -- the alarm: "Call my team if my weight goes up by more than [ ] [kg/lb] [between sessions | in [n] days]"
    const alarm = alarmItem.value;
    const aAmount = h('input', { id: 'set-body-alarm-amount', type: 'text', inputmode: 'decimal', autocomplete: 'off', maxlength: 6, 'aria-describedby': 'set-body-alarm-hint set-body-alarm-sentence' });
    aAmount.value = alarm.amount_kg == null ? '' : U.inputNumber(R.shownWeight(alarm.amount_kg, unit));
    const aOver = h('select', { id: 'set-body-alarm-over', 'aria-describedby': 'set-body-alarm-over-hint' },
      hd || alarm.over === 'between_sessions' ? h('option', { value: 'between_sessions' }, 'between sessions') : null,
      h('option', { value: 'days' }, 'in a number of days'));
    aOver.value = alarm.over;
    const aDays = h('input', { id: 'set-body-alarm-days', type: 'text', inputmode: 'numeric', autocomplete: 'off', maxlength: 1 });
    aDays.value = String(alarm.days);
    const aDaysField = h('div', { class: 'field' }, h('label', { for: 'set-body-alarm-days' }, 'Days (1 to 7)'), aDays);
    const sentence = h('p', { class: 'body-alarm-sentence', id: 'set-body-alarm-sentence', 'aria-live': 'polite' });
    const aMsg = h('p', { class: 'status-msg', id: 'set-body-alarm-msg', role: 'status', 'aria-live': 'polite' });
    const aErr = h('div', { class: 'form-error', role: 'alert', id: 'set-body-alarm-error', hidden: true });
    const readAlarm = () => {
      const amount = U.alarmFromInput(aAmount.value, unit);
      const days = /^[1-7]$/.test(aDays.value.trim()) ? Number(aDays.value.trim()) : null;
      return { amount, days, over: aOver.value };
    };
    const syncAlarm = () => {
      aDaysField.hidden = aOver.value !== 'days';
      const a = readAlarm();
      sentence.textContent = a.amount.amount_kg == null
        ? 'No alarm set.'
        : `Call my team if my weight goes up by more than ${U.alarmSentence({ amount_kg: a.amount.amount_kg, over: a.over, days: a.days || alarm.days }, unit).replace(/^more than /, '')}`;
    };
    for (const el of [aAmount, aOver, aDays]) el.addEventListener('input', syncAlarm);
    aOver.addEventListener('change', syncAlarm);
    const aSave = h('button', { class: 'btn primary', type: 'button', id: 'set-body-alarm-save' }, 'Save alarm');
    aSave.addEventListener('click', async () => {
      clear(aErr); aErr.hidden = true; aMsg.textContent = '';
      KH.forms.clearFieldErrors(body);
      const a = readAlarm();
      if (a.amount.error) { KH.forms.fieldError(aAmount, a.amount.error); aAmount.focus(); return; }
      if (a.over === 'days' && a.days == null) { KH.forms.fieldError(aDays, 'Enter a whole number of days from 1 to 7.'); aDays.focus(); return; }
      aSave.disabled = true;
      try {
        await api.updateMySettings({ 'body.weight_alarm': { amount_kg: a.amount.amount_kg, over: a.over, days: a.days || alarm.days } });
        aMsg.textContent = a.amount.amount_kg == null ? 'Saved: no weight-gain alarm.' : 'Saved.';
        state.dayLoadedFor = null;
      } catch (err) {
        if (!err.handled) { aErr.hidden = false; aErr.append(h('p', {}, err.detail || err.message)); }
      } finally { aSave.disabled = false; }
    });
    const overHint = !hd && alarm.over === 'between_sessions'
      ? 'Between sessions is for people on hemodialysis. Your Profile does not say hemodialysis, so choose a number of days, or change Profile.'
      : hd ? 'Between sessions compares a weight before dialysis with the one after your last session.' : 'Compares a weight with the one of the same kind from that many days earlier.';
    body.append(h('fieldset', { class: 'field body-alarm', id: 'set-body-alarm' },
      h('legend', {}, 'My weight-gain alarm (from my care team)'),
      h('div', { class: 'body-stack' },
        h('div', { class: 'field' }, h('label', { for: 'set-body-alarm-amount' }, `Goes up by more than (${unit})`), aAmount),
        h('div', { class: 'field' }, h('label', { for: 'set-body-alarm-over' }, 'Over'), aOver, h('span', { class: 'hint', id: 'set-body-alarm-over-hint' }, overHint)),
        aDaysField),
      sentence,
      h('span', { class: 'hint', id: 'set-body-alarm-hint' }, 'The number your care team gave you. The app does not suggest one. Leave the amount empty for no alarm.'),
      h('span', {}, sourceOf(alarmItem)), aErr, h('div', { class: 'settings-actions' }, aSave), aMsg));
    syncAlarm();

    // -- the goal: "My blood pressure goal from my team: under [ ] / [ ]"
    const goal = goalItem.value;
    const gTop = h('input', { id: 'set-body-goal-systolic', type: 'text', inputmode: 'numeric', autocomplete: 'off', maxlength: 3, placeholder: 'e.g. 130', 'aria-describedby': 'set-body-goal-hint' });
    const gBottom = h('input', { id: 'set-body-goal-diastolic', type: 'text', inputmode: 'numeric', autocomplete: 'off', maxlength: 3, placeholder: 'e.g. 80', 'aria-describedby': 'set-body-goal-hint' });
    gTop.value = goal.systolic == null ? '' : String(goal.systolic);
    gBottom.value = goal.diastolic == null ? '' : String(goal.diastolic);
    const gMsg = h('p', { class: 'status-msg', id: 'set-body-goal-msg', role: 'status', 'aria-live': 'polite' });
    const gErr = h('div', { class: 'form-error', role: 'alert', id: 'set-body-goal-error', hidden: true });
    const gSave = h('button', { class: 'btn primary', type: 'button', id: 'set-body-goal-save' }, 'Save goal');
    gSave.addEventListener('click', async () => {
      clear(gErr); gErr.hidden = true; gMsg.textContent = '';
      KH.forms.clearFieldErrors(body);
      const g = U.goalFromInput(gTop.value, gBottom.value);
      if (g.errors.systolic) { KH.forms.fieldError(gTop, g.errors.systolic); gTop.focus(); return; }
      if (g.errors.diastolic) { KH.forms.fieldError(gBottom, g.errors.diastolic); gBottom.focus(); return; }
      gSave.disabled = true;
      try {
        await api.updateMySettings({ 'body.bp_goal': { systolic: g.systolic, diastolic: g.diastolic } });
        gMsg.textContent = g.systolic == null && g.diastolic == null ? 'Saved: no blood pressure goal.' : 'Saved.';
        state.dayLoadedFor = null;
      } catch (err) {
        if (!err.handled) { gErr.hidden = false; gErr.append(h('p', {}, err.detail || err.message)); }
      } finally { gSave.disabled = false; }
    });
    body.append(h('fieldset', { class: 'field body-goal', id: 'set-body-goal' },
      h('legend', {}, 'My blood pressure goal from my team: under'),
      h('div', { class: 'form-grid align-end' },
        h('div', { class: 'field' }, h('label', { for: 'set-body-goal-systolic' }, 'Top number (systolic)'), gTop),
        h('div', { class: 'field' }, h('label', { for: 'set-body-goal-diastolic' }, 'Bottom number (diastolic)'), gBottom)),
      h('span', { class: 'hint', id: 'set-body-goal-hint' }, 'The numbers your care team gave you, for example 130 and 80. The app does not suggest a goal, and a home reading is not the same as one taken at the clinic. Leave both empty for no goal.'),
      h('span', {}, sourceOf(goalItem)), gErr, h('div', { class: 'settings-actions' }, gSave), gMsg));
  }

  // ---- Profile: the log's weights, offered and never applied ---------------------------------------------------------------
  // → { units, latest, sixMonth }: the latest weight in the log, and the weight dated closest to six months before it (note 10 §4.4:
  // 182 days, within 30). Either is null when the log has none. Reads only; Profile changes when the person taps "Use this" and saves.
  async function profileHints() {
    const today = todayStr();
    const sum = await api.bodySummary(today);
    const latest = sum.weight && sum.weight.latest ? sum.weight.latest : null;
    const out = { units: sum.units === 'kg' ? 'kg' : 'lb', latest, sixMonth: null };
    if (!latest) return out;
    const from = [addDays(latest.date, -U.SIX_MONTH_LOOKBACK_DAYS), addDays(today, -365)].sort().pop(); // the list is at most 366 days
    if (from <= latest.date) {
      const list = (await api.bodyWeights(from, latest.date)).weights || [];
      const change = R.sixMonthChange(list.filter((x) => x.id !== latest.id).concat([latest]));
      out.sixMonth = change ? change.earlier : null;
    }
    return out;
  }

  KH.body = { today: loadToday, openWeight, openBp, flagBlock, renderSettings, profileHints, units: () => S.units };
})();
