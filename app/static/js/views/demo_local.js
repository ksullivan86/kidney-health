/* Kidney Diet Log — demo only: the "Keep my data in this browser" banner button and sheet (KH.demoLocal; ARCHITECTURE.md
   "Keep my data in this browser", docs/demo.md). The storage itself is js/mock/persist.js (KH.mock.local); this file only draws.

   * The banner gets a button that opens the sheet. The sheet says plainly where the data would live and how it can be lost, and
     turning the mode on needs the "I understand" box ticked. "Stop keeping data here" deletes the stored copy after an in-page
     confirmation and starts the sample demo again.
   * Shown only in the Pages demo build (KH.flags.PREVIEW): in the installed app, and on a development server's ?mock=1 page, the
     button stays hidden and nothing here runs. This file never touches a browser store itself.
   * Everything from outside the page (a stored time, an error) is drawn with textContent. No inline script, handler or style. */
(() => {
  'use strict';
  const KH = window.KH;
  const { $, h } = KH;
  const flags = KH.flags || {};
  const L = KH.mock && KH.mock.local;

  const FILE_NAME = 'export.json';
  const KEPT_TEXT = 'Your data is kept in this browser only: not on a server, and not backed up. Export it regularly (Settings, Your data).';
  const PERSIST_TEXT = {
    yes: 'Your browser has agreed to keep this data unless you clear the site data yourself.',
    no: 'Your browser has not agreed to keep this data for good: it may delete it when the device runs low on space. Export it regularly.',
    unknown: 'This browser does not say whether it will keep the data. Export it regularly.',
  };

  // Not the demo build: no button, no sheet, no storage. (The fallback keeps the Settings page's calls harmless.)
  if (!flags.MOCK || flags.PREVIEW !== true || !L) {
    KH.demoLocal = { init() {}, on: () => false, open() {}, exportFile: async () => null };
    return;
  }

  const banner = $('#preview-banner');
  const bannerText = $('#preview-banner-text');
  const keepBtn = $('#preview-banner-keep');
  const dlg = $('#sheet-demo-local');
  const offBox = $('#dl-off');
  const onBox = $('#dl-on');
  const blockedBox = $('#dl-blocked');
  const understand = $('#dl-understand');
  const enableBtn = $('#dl-enable');
  const exportBtn = $('#dl-export');
  const stopBtn = $('#dl-stop');
  const foot = $('#dl-foot');
  const problem = $('#dl-problem');
  const msg = $('#dl-msg');
  const originalBannerText = bannerText.textContent;
  let busy = false;

  function setMsg(text) { msg.textContent = text || ''; }
  function savedLine(s) {
    if (s.saving) return 'Saving…';
    if (s.error || s.conflict) return 'Not saved just now. See the message above.';
    if (!s.savedAt) return '';
    const when = new Date(s.savedAt);
    return Number.isNaN(when.getTime()) ? '' : `Saved in this browser at ${when.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}.`;
  }

  function render(s) {
    // the banner
    keepBtn.hidden = false;
    if (s.blocked) { bannerText.textContent = s.blocked.message; keepBtn.textContent = 'About my saved data'; banner.hidden = false; }
    else if (s.on && (s.error || s.conflict)) { bannerText.textContent = s.error || 'Your data could not be saved just now.'; keepBtn.textContent = 'Manage'; banner.hidden = false; }
    else if (s.on) { bannerText.textContent = KEPT_TEXT; keepBtn.textContent = 'Manage'; }
    else { bannerText.textContent = originalBannerText; keepBtn.textContent = 'Keep my data in this browser'; }
    // the sheet
    offBox.hidden = s.on || !!s.blocked;
    onBox.hidden = !s.on;
    blockedBox.hidden = !s.blocked;
    if (s.blocked) $('#dl-blocked-text').textContent = s.blocked.message;
    enableBtn.hidden = s.on || !!s.blocked;
    exportBtn.hidden = !s.on;
    stopBtn.hidden = !s.on;
    const why = s.on ? (s.error || '') : (s.unavailable || '');
    problem.textContent = why;
    problem.hidden = !why;
    enableBtn.disabled = busy || !understand.checked || !!s.unavailable || !!s.blocked;
    if (s.on) {
      $('#dl-saved').textContent = savedLine(s);
      $('#dl-persist').textContent = PERSIST_TEXT[s.persisted === true ? 'yes' : s.persisted === false ? 'no' : 'unknown'];
    }
  }

  function openSheet(trigger) {
    setMsg('');
    understand.checked = false;
    render(L.status());
    KH.sheets.open(dlg, trigger);
    if (!L.status().on) L.probe().then(render, () => {}); // can this browser store anything here? says so before the person ticks anything
  }

  // The file the server's zip holds, built by the demo API (js/mock/export.js) and saved by the browser.
  async function exportFile() {
    const doc = await KH.request('GET', '/api/me/export.json');
    const text = `${JSON.stringify(doc, null, 2)}\n`;
    const blob = new Blob([text], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = h('a', { href: url, download: FILE_NAME, class: 'sr-only' });
    document.body.append(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 60000);
    return { name: FILE_NAME, bytes: blob.size };
  }

  function init() {
    KH.sheets.setup(dlg);
    keepBtn.addEventListener('click', () => openSheet(keepBtn));
    understand.addEventListener('change', () => render(L.status()));
    enableBtn.addEventListener('click', async () => {
      if (busy || !understand.checked) return;
      busy = true; setMsg('Turning it on…'); render(L.status());
      try {
        const fresh = $('#dl-start-empty').checked;
        const res = await L.enable({ fresh });
        setMsg('');
        if (res.reload) { window.location.reload(); return; } // starts from the empty copy that was just stored
      } catch (e) {
        setMsg('');
        problem.textContent = (e && (e.userMessage || e.message)) || 'It could not be turned on.';
        problem.hidden = false;
      } finally { busy = false; render(L.status()); }
    });
    exportBtn.addEventListener('click', async () => {
      setMsg('Preparing the file…');
      try {
        const res = await exportFile();
        setMsg(`Saved ${res.name}. Keep it somewhere private: it holds your health data.`);
      } catch (e) { setMsg(''); KH.toastError(e); }
    });
    stopBtn.addEventListener('click', () => {
      KH.confirm.inline(foot, stopBtn, {
        message: 'Delete the copy of your data stored in this browser? The demo then starts again with its sample data. This cannot be undone: export first if you want to keep it.',
        confirmText: 'Delete my stored data',
        onConfirm: async () => { await L.disable(); window.location.reload(); },
      });
    });
    L.subscribe(render);
    render(L.status());
  }

  KH.demoLocal = { init, on: () => L.on(), open: openSheet, exportFile };
})();
