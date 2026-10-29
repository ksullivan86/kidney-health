/* Kidney Diet Log — boot: start the demo API when asked for, apply the theme, check who is
   signed in (js/views/auth.js shows the setup / sign-in / invite / reset screens when needed),
   then load the profile, start the offline outbox (js/offline.js) and show the first view; finally hand over to
   the PWA shell (js/pwa.js, absent in the preview build). */
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
    // Entries saved on this device while the server was unreachable sync now (js/offline.js, note 02 R5).
    if (KH.offline) KH.offline.start().catch((e) => console.warn('Offline outbox:', e));
    // The Ask tab appears only when the server's chat is available (opened at #ask without it, the view goes to Today).
    if (KH.views.ask && KH.views.ask.refreshTab) KH.views.ask.refreshTab().catch(() => false);
    const initial = view || location.hash.replace('#', '');
    router.show(router.VIEWS.includes(initial) ? initial : 'today');
    // A "Add this day to my plan" link from the handbook, kept in memory while signing in (js/views/menuplan.js): shows
    // its confirmation sheet now; nothing is saved until the person presses "Add to plan".
    if (KH.menuPlan) KH.menuPlan.openPending().catch((e) => console.warn('Menu day:', e));
    // A share link (#/share/<code>, js/views/sharing.js), kept the same way: asks "Accept?" before anything is saved.
    if (KH.sharing) KH.sharing.openPending().catch((e) => console.warn('Share link:', e));
    // A signed-in visit: on an iPhone or iPad the third one offers the Home Screen tip (js/pwa.js, note 02 R10).
    if (KH.pwa && KH.pwa.countVisit) KH.pwa.countVisit();
  }
  KH.app = { start };

  async function init() {
    KH.theme.apply(KH.theme.stored());
    $('#date-input').value = state.date;
    if (MOCK) {
      document.title = KH.brand.screenName;
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
    // Demo build only (js/mock/persist.js): a copy the person chose to keep in this browser is read back before the first request;
    // everywhere else this does nothing and touches no browser store.
    if (MOCK && KH.mock.local) await KH.mock.local.boot();
    if (MOCK && KH.demoLocal) KH.demoLocal.init();
    // false: a sign-in screen is showing; it calls KH.app.start() once someone is signed in.
    if (!(await KH.auth.boot())) return;
    if (KH.views.settings && KH.views.settings.onSignedIn) KH.views.settings.onSignedIn(state.me);
    await start();
  }
  init();
  if (KH.pwa) KH.pwa.init();
})();
