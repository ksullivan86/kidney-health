/* Kidney Diet Log — device mode only: the first-start setup of the iPhone app with no server (design note 38; owner, 2026-11-21:
   "on first start or if it's not set up it should walk through a simple setup and connecting to an optional server").

   Four short steps in one sheet (#sheet-welcome):
   1. Welcome: where the data lives, and the one choice of how to start: an empty log of your own (the default), or the sample
      data to try the app first. The sample data can be swapped for an empty log later (Settings → This device → Start over).
   2. About you: your name, CKD stage, dialysis and diabetes type, saved to the profile (the same choices as Profile).
   3. Your server, optional: what connecting one does now (your log on your other devices, your care team) and what comes later
      (the server's AI and keys, changes coming back; owner, 2026-11-21), how to pair, a button that opens the app's own settings, and Not now.
   4. Done.
   The setup shows at every start until it is finished; Settings → This device → Run the setup again shows it once more.

   Shown only in device mode (KH.flags.DEVICE). Nothing leaves the page; DOM built with KH.h and textContent only. */
(() => {
  'use strict';
  const KH = window.KH;
  const { $, h, state, toastError } = KH;
  const flags = KH.flags || {};
  if (!flags.DEVICE) {
    KH.welcome = { maybeShow: async () => false, open() {} };
    return;
  }

  const dlg = $('#sheet-welcome');
  const body = $('#welcome-body');
  const STAGES = [['', 'Not sure yet'], ['1', 'Stage 1'], ['2', 'Stage 2'], ['3a', 'Stage 3a'], ['3b', 'Stage 3b'], ['4', 'Stage 4'], ['5', 'Stage 5']];
  const DIALYSIS = [['none', 'No dialysis'], ['hemodialysis', 'Hemodialysis'], ['peritoneal', 'Peritoneal dialysis']];
  const DIABETES = [['', 'Not sure yet'], ['none', 'No diabetes'], ['type1', 'Type 1'], ['type2', 'Type 2']];
  let ready = false;

  const phone = () => { try { return window.webkit.messageHandlers.phone; } catch (e) { return null; } };
  const field = (label, control) => h('div', { class: 'field' }, h('label', { for: control.id }, label), control);
  const select = (id, options, value) => h('select', { id }, ...options.map(([v, text]) => h('option', { value: v, selected: v === value }, text)));
  const actions = (...buttons) => h('div', { class: 'sheet-foot' }, ...buttons);
  // One step: the sheet's own head (step and title), body and foot, like every other sheet.
  const step = (n, title, children, foot) => [
    h('div', { class: 'sheet-head' }, h('div', {}, h('h2', { id: 'welcome-title', class: 'sheet-title' }, title),
      h('div', { class: 'sheet-sub' }, `Setting up, step ${n} of 4`))),
    h('div', { class: 'sheet-body' }, ...children), foot];
  const choice = (input, title, hint) => h('label', { class: 'choice', for: input.id }, input,
    h('span', { class: 'choice-text' }, h('b', {}, title), h('span', { class: 'hint' }, hint)));
  const button = (text, kind, onClick, id) => h('button', { type: 'button', class: `btn ${kind}`, id, onclick: onClick }, text);

  function show(children) {
    body.replaceChildren(...children);
    const first = body.querySelector('h2');
    if (first) { first.setAttribute('tabindex', '-1'); first.focus(); }
  }

  function stepWelcome() {
    const own = h('input', { type: 'radio', name: 'welcome-start', value: 'own', id: 'welcome-own', checked: true });
    const sample = h('input', { type: 'radio', name: 'welcome-start', value: 'sample', id: 'welcome-sample' });
    show(step(1, 'Welcome to Kidney Health', [
      h('p', {}, 'Your food log, labs, weight and blood pressure stay on this iPhone. Nothing is sent anywhere unless you connect your own server or turn on a food service.'),
      h('fieldset', { class: 'field choice-list' }, h('legend', {}, 'How do you want to start?'),
        choice(own, 'An empty log of my own', 'The usual way. Add what you eat from the Add tab.'),
        choice(sample, 'The sample data', 'A sample person with a month of meals, to try the app first. You can start over with an empty log later in Settings.'))],
    actions(button('Next', 'primary', async () => {
      if (sample.checked) await startSample(); else stepAbout();
    }, 'welcome-next'))));
  }

  async function startSample() {
    try {
      await setup({ done: true, sample: true });
      await KH.mock.local.restart({ sample: true });
      window.location.reload();
    } catch (e) { toastError(e); }
  }

  function stepAbout() {
    const p = state.profile || {};
    const name = h('input', { type: 'text', id: 'welcome-name', maxlength: 100, autocomplete: 'given-name', value: p.name || '' });
    const stage = select('welcome-stage', STAGES, p.ckd_stage_chosen ? p.ckd_stage : '');
    const dialysis = select('welcome-dialysis', DIALYSIS, p.dialysis || 'none');
    const diabetes = select('welcome-diabetes', DIABETES, p.diabetes_chosen ? p.diabetes : '');
    show(step(2, 'About you', [
      h('p', {}, 'The app uses these to suggest your daily targets. Check targets with your care team. You can change all of this later in Profile.'),
      field('Your name', name), field('CKD stage', stage), field('Dialysis', dialysis), field('Diabetes', diabetes)],
    actions(button('Back', 'secondary', stepWelcome), button('Next', 'primary', async () => {
        const update = { name: name.value.trim(), dialysis: dialysis.value };
        if (stage.value) update.ckd_stage = stage.value;
        if (diabetes.value) update.diabetes = diabetes.value;
        try {
          state.profile = await KH.api.saveProfile(update);
          stepServer();
        } catch (e) { toastError(e); }
      }, 'welcome-about-next'))));
  }

  function stepServer() {
    const handler = phone();
    show(step(3, 'Your own server (optional)', [
      h('p', {}, 'You do not need a server: the app works fully on this iPhone. If you run a Kidney Health server, connecting it adds:'),
      h('ul', {},
        h('li', {}, 'Your log on your other devices. What you add here is sent to your server, so you see it in the web app and it is kept there too.'),
        h('li', {}, 'Your care team, if you share your log with them on the server.'),
        h('li', {}, 'Coming later: your server\'s AI, the keys and food services set up there, and changes made on your other devices coming back to this iPhone.')),
      handler ? h('p', {}, 'To connect one, open the web app on your server: Settings → Account → Your data → Phone shortcuts. Make a token for "The iPhone app". Then tap Open phone settings here and scan its QR code. You can do this any time later.') : null],
    actions(
      handler ? button('Open phone settings', 'secondary', () => handler.postMessage('settings'), 'welcome-server') : null,
      button(handler ? 'Not now' : 'Next', 'primary', stepDone, 'welcome-server-next'))));
  }

  function stepDone() {
    show(step(4, 'You are set', [
      h('p', {}, 'Add what you eat from the Add tab. After each change the app saves a copy in the Files app, under On My iPhone. Export your data now and then and keep the file somewhere safe.')],
    actions(button('Start', 'primary', async () => {
        try { await setup({ done: true }); } catch (e) { toastError(e); return; }
        dlg.close();
        KH.router.show('today');
      }, 'welcome-done'))));
  }

  const setup = (body) => KH.request('PUT', '/api/device/setup', body);

  function open() {
    if (!ready) { KH.sheets.setup(dlg); ready = true; }
    stepWelcome();
    KH.sheets.open(dlg);
  }

  // At every start until the setup was finished.
  async function maybeShow() {
    try {
      const s = await KH.request('GET', '/api/device/setup');
      if (s && s.done) return false;
    } catch (e) { return false; }
    open();
    return true;
  }

  KH.welcome = { maybeShow, open };
})();
