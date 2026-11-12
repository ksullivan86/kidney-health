/* Kidney Diet Log — notes from the Care team (design note 37 phase 1; app/care_notes.py).

   * #notes, the person's own: notes from people on their Care team, newest first, each with who wrote it, when, what it is about
     (a link to that day or to Labs), the text and Delete. Showing a note on screen marks it read (POST /api/me/notes/{id}/read
     with the version shown: when the writer changed it meanwhile the answer is 412 and the list loads again, so a note marked
     read is always the text the person saw).
   * #notes for a person whose Care team you are on with notes on (KH.notes.openAuthor): the notes you wrote for them, "Read on …"
     or "Not read yet", with Edit and Withdraw only while unread, and Write a note.
   * The Today card (KH.notes.todayCard, called by js/views/today.js): "1 new note from Dee" with Read, only while there are
     unread notes. It sits under the day's alerts and moves nothing else.
   * The Visit prep line (KH.notes.visitLine): "2 notes from your Care team in this period", on screen only. Notes are never printed.
   * Write a note (KH.notes.write), from Open (Visit prep) and Trends of someone who shares with you: #sheet-note, with what it is
     about filled in from what you are looking at.

   Notes are plain text: every text goes in with h() children (textContent), never as HTML, and nothing in a note is made into
   a link. Notes never reach the AI. The demo answers from js/mock/care.js (Dee, a Clinician, has written you one note). */
(() => {
  'use strict';
  const KH = window.KH;
  const { h, $, clear, request, toast, toastError, confirm, sheets, state, router } = KH;
  const { parseDate } = KH.util;

  const view = $('#view-notes');
  if (!view) return;

  const MAX_BODY = 1000;
  const AREA_LABEL = { food: 'food log', labs: 'lab results', body: 'weight and blood pressure', symptoms: 'symptoms',
    activity: 'activity and recovery' };
  const AREAS = Object.keys(AREA_LABEL);
  const OWN_INTRO = 'Notes are messages from people on your Care team. They are not a medical record and never change your targets, '
    + 'labs or medicines. The app does not check who someone is. People read notes when they open the app, so for anything urgent, '
    + 'call your care team.';
  const WHAT = (name) => `${name} reads this in their own app. A note is not a medical record and gives no orders: it never changes `
    + `${name}'s targets, labs, medicines or log. No insulin or medicine doses, and nothing about treating a low. Keep your own record as `
    + 'your clinic requires.';
  const UNDER = 'A note from your Care team. It is not a medical record and changes nothing in your app.';

  // ---------------------------------------------------------------------------
  // Pure helpers (tests/js/notes_ui.test.mjs runs them in Node)
  // ---------------------------------------------------------------------------
  function dayWords(iso) {
    return parseDate(iso).toLocaleDateString('en-US', { weekday: 'long', month: 'short', day: 'numeric', year: 'numeric' });
  }
  function whenWords(iso) {
    if (!iso) return '';
    const d = new Date(iso);
    return Number.isNaN(d.getTime()) ? '' : d.toLocaleString('en-US', { month: 'short', day: 'numeric', year: 'numeric', hour: 'numeric', minute: '2-digit' });
  }
  /** What a note is about, in words: "About Tuesday, Nov 10, 2026, your food log", "About your lab results", or null. `whose`
      is "your" for the person and "Ana's" for the writer. */
  function aboutText(note, whose = 'your') {
    const parts = [note.date ? dayWords(note.date) : null, note.area ? `${whose} ${AREA_LABEL[note.area] || note.area}` : null].filter(Boolean);
    return parts.length ? `About ${parts.join(', ')}` : null;
  }
  /** Who wrote it: "Dee", or "Dee (account removed)" once their account is gone. */
  function fromText(note) {
    const name = (note.from && note.from.name) || 'Someone';
    return note.from && note.from.removed ? `${name} (account removed)` : name;
  }
  /** For the writer: "Read on Nov 12, 2026" or "Not read yet". */
  function readText(note) {
    return note.read_at ? `Read on ${new Date(note.read_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })}` : 'Not read yet';
  }
  /** The Today card: "1 new note from Dee", "2 new notes from Dee and Sam", "3 new notes from your Care team". */
  function newNotesText(unread, names) {
    const who = [...new Set(names)];
    const from = who.length === 1 ? who[0] : who.length === 2 ? `${who[0]} and ${who[1]}` : 'your Care team';
    return `${unread} new ${unread === 1 ? 'note' : 'notes'} from ${from}`;
  }
  /** "120 of 1,000 characters". */
  function counterText(text) { return `${[...String(text || '')].length.toLocaleString('en-US')} of ${MAX_BODY.toLocaleString('en-US')} characters`; }
  /** How many notes were written in [start, end] (YYYY-MM-DD, by the day they were written), for Visit prep. */
  function countInPeriod(notes, start, end) {
    return (notes || []).filter((n) => { const d = String(n.created_at || '').slice(0, 10); return d >= start && d <= end; }).length;
  }
  function periodText(n) { return `${n} ${n === 1 ? 'note' : 'notes'} from your Care team in this period`; }

  // ---------------------------------------------------------------------------
  // Requests
  // ---------------------------------------------------------------------------
  const A = {
    mine: (before) => request('GET', `/api/me/notes${before ? `?before=${encodeURIComponent(before)}` : ''}`),
    read: (n) => request('POST', `/api/me/notes/${n.id}/read`, undefined, { ifMatch: String(n.version), noQueue: true }),
    remove: (id) => request('DELETE', `/api/me/notes/${id}`, undefined, { noQueue: true }),
    written: (sid) => request('GET', `/api/shared/${encodeURIComponent(sid)}/notes`),
    write: (sid, body) => request('POST', `/api/shared/${encodeURIComponent(sid)}/notes`, body, { noQueue: true }),
    edit: (sid, n, body) => request('PUT', `/api/shared/${encodeURIComponent(sid)}/notes/${n.id}`, body, { ifMatch: String(n.version), noQueue: true }),
    withdraw: (sid, n) => request('DELETE', `/api/shared/${encodeURIComponent(sid)}/notes/${n.id}`, undefined, { ifMatch: String(n.version), noQueue: true }),
  };
  const errText = (err) => (err && (err.detail || err.message)) || 'Something went wrong. Try again.';

  // ---------------------------------------------------------------------------
  // The Notes view: your own, or what you wrote for someone (`source`)
  // ---------------------------------------------------------------------------
  // `source` is null for the person's own notes, else {id, name, areas}: a share of someone whose Care team you are on.
  const S = { source: null, pending: null, req: 0, notes: [], more: false, back: 'today' };
  const list = $('#notes-list');

  function renderHead() {
    const author = !!S.source;
    $('#notes-title').textContent = author ? `Your notes for ${S.source.name}` : 'Notes from your Care team';
    $('#notes-intro').textContent = author ? WHAT(S.source.name) : OWN_INTRO;
    $('#notes-actions').hidden = !author;
    $('#notes-back').textContent = S.back === 'settings' ? 'Back to Settings' : S.back === 'visit' ? 'Back to Visit prep' : 'Back to Today';
  }

  function noteCard(n) {
    const about = aboutText(n, S.source ? `${S.source.name}'s` : 'your');
    const actions = h('div', { class: 'note-card-actions' });
    const card = h('article', { class: `card note-card${!S.source && !n.read_at ? ' note-new' : ''}`, 'data-note': n.id },
      h('header', { class: 'note-card-head' },
        h('span', { class: 'note-from' }, S.source ? readText(n) : fromText(n)),
        h('span', { class: 'muted small' }, whenWords(n.created_at), n.edited_at ? ' · edited' : '')),
      about ? h('p', { class: 'note-about small' }, aboutLink(n, about)) : null,
      h('p', { class: 'note-body' }, n.body),
      S.source ? null : h('p', { class: 'hint note-under' }, UNDER),
      actions);
    if (S.source) {
      if (!n.read_at) {
        const edit = h('button', { class: 'btn secondary', type: 'button', 'aria-label': 'Change this note' }, 'Edit');
        edit.addEventListener('click', () => write(S.source, { note: n, trigger: edit }));
        const withdraw = h('button', { class: 'btn secondary', type: 'button', 'aria-label': 'Withdraw this note' }, 'Withdraw');
        withdraw.addEventListener('click', () => confirm.inline(actions, withdraw, {
          message: `Withdraw this note? ${S.source.name} will not see it.`,
          confirmText: 'Withdraw',
          onConfirm: async () => {
            try { await A.withdraw(S.source.id, n); toast('Note withdrawn', 'ok'); } catch (err) { if (!err.handled) toastError(err); }
            await load();
            return true;
          },
        }));
        actions.append(edit, withdraw);
      }
    } else {
      const del = h('button', { class: 'btn secondary', type: 'button', 'aria-label': `Delete the note from ${fromText(n)}` }, 'Delete');
      del.addEventListener('click', () => confirm.inline(actions, del, {
        message: 'Delete this note? It is gone for you and for the person who wrote it.',
        confirmText: 'Delete',
        onConfirm: async () => {
          try { await A.remove(n.id); toast('Note deleted', 'ok'); } catch (err) { if (!err.handled) toastError(err); }
          await load();
          return true;
        },
      }));
      actions.append(del);
    }
    return card;
  }
  /** The person's own note: its day opens that day on Today, lab results open Labs. The writer's view has no links. */
  function aboutLink(n, text) {
    if (S.source) return text;
    const go = n.area === 'labs' ? () => router.show('labs') : n.date ? () => router.openDay(n.date) : null;
    if (!go) return text;
    const b = h('button', { class: 'link-btn', type: 'button' }, text);
    b.addEventListener('click', go);
    return b;
  }

  function render() {
    clear(list);
    if (!S.notes.length) {
      list.append(h('p', { class: 'empty-state' }, S.source ? `You have not written a note for ${S.source.name} yet.` : 'No notes from your Care team.'));
    }
    for (const n of S.notes) list.append(noteCard(n));
    $('#notes-more').hidden = !S.more;
  }

  async function load(older = false) {
    const req = ++S.req;
    if (!older) { clear(list).append(h('p', { class: 'muted' }, 'Loading…')); S.notes = []; }
    let got;
    try {
      got = S.source ? await A.written(S.source.id) : await A.mine(older && S.notes.length ? S.notes[S.notes.length - 1].id : null);
    } catch (err) {
      if (req !== S.req) return;
      clear(list).append(h('p', { class: 'form-error' }, `The notes could not be loaded (${errText(err)}).`));
      if (err.status === 404 && S.source) list.append(h('p', { class: 'hint' }, `${S.source.name} no longer lets you write notes.`));
      return;
    }
    if (req !== S.req) return;
    if (!S.source && got.enabled === false) {
      S.notes = []; S.more = false;
      clear(list).append(h('p', { class: 'empty-state' }, 'Notes from the Care team are turned off on this server.'));
      $('#notes-more').hidden = true;
      return;
    }
    const page = got.notes || [];
    S.notes = older ? [...S.notes, ...page] : page;
    S.more = !S.source && page.length >= 50;
    render();
    if (!S.source) await markShownRead(req, page);
  }

  /** Showing a note marks it read, with the version on screen. A 412 (the writer changed it meanwhile) loads the list again. */
  async function markShownRead(req, page) {
    let changed = false;
    for (const n of page.filter((x) => !x.read_at)) {
      if (req !== S.req || state.view !== 'notes') return;
      try { await A.read(n); } catch (err) {
        if (err.status === 412) { changed = true; continue; }
        if (!err.handled) console.warn('Marking a note read:', err);
      }
    }
    if (changed && req === S.req) {
      toast('A note changed while it was on screen. Here it is as it is now.');
      await load();
    }
  }

  $('#notes-older').addEventListener('click', () => load(true));
  $('#notes-back').addEventListener('click', () => router.show(S.back || 'today'));
  $('#notes-write').addEventListener('click', (e) => { if (S.source) write(S.source, { trigger: e.currentTarget }); });

  router.register('notes', () => {
    S.source = S.pending ? S.pending.source : null;
    S.back = S.pending ? S.pending.back : 'today';
    S.pending = null;
    renderHead();
    $('#notes-title').focus();
    load();
  });

  /** Your own notes, opened from `back` ("today", "settings" or "visit"). */
  function openOwn(back = 'today') { S.pending = { source: null, back }; router.show('notes'); }
  /** The notes you wrote for `person` (an item of GET /api/shared). */
  function openAuthor(person) {
    S.pending = { source: { id: person.id, name: person.name || person.username, areas: person.areas || [] }, back: 'settings' };
    router.show('notes');
  }

  // ---------------------------------------------------------------------------
  // Write a note (#sheet-note)
  // ---------------------------------------------------------------------------
  const dlg = $('#sheet-note');
  const W = { source: null, note: null, after: null, sending: 0 };
  const bodyEl = $('#note-body');
  const countEl = $('#note-count');
  const errEl = $('#note-error');
  const showErr = (text) => { errEl.textContent = text || ''; errEl.hidden = !text; };
  bodyEl.addEventListener('input', () => { countEl.textContent = counterText(bodyEl.value); });

  /** Open the sheet for `person` ({id, name, areas}): a new note with `area` / `date` filled in, or `note` to change one. */
  function write(person, { note = null, area = null, date = null, trigger = null, after = null } = {}) {
    if (!dlg) return;
    W.source = { id: person.id, name: person.name || person.username, areas: person.areas || [] };
    W.note = note; W.after = after; ++W.sending;
    $('#sheet-note-title').textContent = note ? `Change your note for ${W.source.name}` : `Write a note for ${W.source.name}`;
    $('#note-what').textContent = WHAT(W.source.name);
    const select = clear($('#note-area'));
    select.append(h('option', { value: '' }, 'Nothing in particular'));
    const shown = AREAS.filter((a) => W.source.areas.includes(a) || (note && note.area === a));
    for (const a of shown) select.append(h('option', { value: a }, `${W.source.name}'s ${AREA_LABEL[a]}`));
    select.value = (note ? note.area : area && W.source.areas.includes(area) ? area : '') || '';
    const day = $('#note-date');
    day.max = KH.util.addDays(KH.util.todayStr(), 1);
    day.min = KH.util.addDays(KH.util.todayStr(), -365);
    day.value = (note ? note.date : date) || '';
    bodyEl.value = note ? note.body : '';
    countEl.textContent = counterText(bodyEl.value);
    showErr('');
    const send = $('#note-send');
    send.textContent = note ? 'Save' : `Send to ${W.source.name}`;
    send.disabled = false;
    sheets.open(dlg, trigger, bodyEl);
  }

  if (dlg) {
    sheets.setup(dlg);
    const send = $('#note-send');
    send.addEventListener('click', async () => {
      if (send.disabled || !W.source) return;
      const text = bodyEl.value.trim();
      if (!text) { showErr('Write the note first.'); bodyEl.focus(); return; }
      const areaVal = $('#note-area').value || null;
      const dateVal = $('#note-date').value || null;
      const body = { body: text, area: areaVal, date: dateVal };
      const ticket = ++W.sending;
      send.disabled = true;
      showErr('');
      try {
        if (W.note) await A.edit(W.source.id, W.note, body);
        else await A.write(W.source.id, body);
        if (ticket !== W.sending) return;
        dlg.close();
        toast(W.note ? 'Note saved' : `Note sent to ${W.source.name}`, 'ok');
        if (state.view === 'notes' && S.source && S.source.id === W.source.id) await load();
        if (W.after) W.after();
      } catch (err) {
        if (ticket !== W.sending || err.handled) return;
        showErr(err.status === 409 && W.note ? `${errText(err)}` : err.status === 412 ? 'This note changed since you opened it. Close this and open it again.' : errText(err));
      } finally { if (ticket === W.sending) send.disabled = false; }
    });
    dlg.addEventListener('close', () => { ++W.sending; });
  }

  // ---------------------------------------------------------------------------
  // The Today card and the Visit prep line (the person's own)
  // ---------------------------------------------------------------------------
  let todayReq = 0;
  async function todayCard() {
    const box = $('#today-notes');
    if (!box) return;
    const req = ++todayReq;
    let got;
    try { got = await A.mine(null); } catch (err) { if (req === todayReq) box.hidden = true; return; }
    if (req !== todayReq) return;
    if (!got.enabled || !got.unread) { clear(box); box.hidden = true; return; }
    const names = (got.notes || []).filter((n) => !n.read_at).map(fromText);
    const read = h('button', { class: 'btn primary', type: 'button', id: 'today-notes-read' }, 'Read');
    read.addEventListener('click', () => openOwn('today'));
    clear(box).append(h('div', { class: 'card today-notes-card', role: 'status' },
      h('span', { class: 'today-notes-text' }, newNotesText(got.unread, names.length ? names : ['your Care team'])), read));
    box.hidden = false;
  }

  let visitReq = 0;
  /** Visit prep, the person's own page: "2 notes from your Care team in this period" with a way to the notes. Screen only. */
  async function visitLine(range, shared) {
    const line = $('#visit-notes-line');
    if (!line) return;
    const req = ++visitReq;
    line.hidden = true;
    if (shared) return;
    let got;
    try { got = await A.mine(null); } catch (err) { return; }
    if (req !== visitReq || !got.enabled) return;
    const n = countInPeriod(got.notes, range.start, range.end);
    if (!n) return;
    const open = h('button', { class: 'link-btn', type: 'button', id: 'visit-notes-open' }, 'Read them');
    open.addEventListener('click', () => openOwn('visit'));
    clear(line).append(periodText(n), '. ', open);
    line.hidden = false;
  }

  /** The Write a note button of Open (Visit prep) or Trends: shown for someone who lets you write notes. `fill` gives what is in view. */
  const buttonFor = {};
  function noteButton(holderId, buttonId, source, fill) {
    const holder = $(`#${holderId}`);
    if (!holder) return;
    const btn = $(`#${buttonId}`);
    if (!buttonFor[buttonId]) {
      buttonFor[buttonId] = {};
      btn.addEventListener('click', () => {
        const cur = buttonFor[buttonId];
        if (cur.source) write(cur.source, { ...(cur.fill ? cur.fill() : {}), trigger: btn });
      });
    }
    const can = !!(source && source.may_note);
    buttonFor[buttonId] = { source: can ? source : null, fill };
    holder.hidden = !can;
  }

  KH.notes = { todayCard, visitLine, noteButton, openOwn, openAuthor, write, aboutText, fromText, readText, newNotesText, counterText,
    countInPeriod, periodText, MAX_BODY };
})();
