/* Kidney Diet Log — boot: start the demo API when asked for, apply the theme, check who is
   signed in (js/views/auth.js shows the setup / sign-in / invite / reset screens when needed),
   then load the profile and show the first view; finally hand over to the PWA shell (js/pwa.js,
   absent in the preview build). */
(() => {
  'use strict';
  const KH = window.KH;
  const { $, state, toastError, router } = KH;
  const { PREVIEW, MOCK, MOCK_HD } = KH.flags;

  // Demo mode: the in-page copy of the server answers every /api call (js/mock/*).
  if (MOCK) KH.mock.start({ hemodialysis: MOCK_HD });

  // Runs once per page, for the signed-in person: at boot, or after the sign-in screens.
  async function start(view) {
    // The profile, and where the handbook links go (js/learn.js; it never throws), before the first view.
    await Promise.all([KH.loadProfile().catch(toastError), KH.learn ? KH.learn.load() : null]);
    const initial = view || location.hash.replace('#', '');
    router.show(router.VIEWS.includes(initial) ? initial : 'today');
  }
  KH.app = { start };

  async function init() {
    KH.theme.apply(KH.theme.stored());
    $('#date-input').value = state.date;
    if (MOCK) {
      document.title = 'Kidney Diet Log';
      const pill = $('#brand-pill');
      pill.textContent = PREVIEW ? 'Preview' : 'Demo';
      pill.hidden = false;
      const banner = $('#preview-banner');
      banner.hidden = false; // dismissing it lasts until the page reloads (nothing is stored)
      $('#preview-banner-close').addEventListener('click', () => {
        banner.hidden = true;
        const tab = $('.tab[aria-selected="true"]');
        if (tab) tab.focus();
      });
    }
    // false: a sign-in screen is showing; it calls KH.app.start() once someone is signed in.
    if (!(await KH.auth.boot())) return;
    if (KH.views.settings && KH.views.settings.onSignedIn) KH.views.settings.onSignedIn(state.me);
    await start();
  }
  init();
  if (KH.pwa) KH.pwa.init();
})();
