/* Kidney Diet Log — boot: start the demo API when asked for, apply the theme, load the
   profile and show the first view; then hand over to the PWA shell (js/pwa.js, absent in the
   preview build). */
(() => {
  'use strict';
  const KH = window.KH;
  const { $, state, toastError, router } = KH;
  const { PREVIEW, MOCK, MOCK_HD } = KH.flags;

  // Demo mode: the in-page copy of the server answers every /api call (js/mock/*).
  if (MOCK) KH.mock.start({ hemodialysis: MOCK_HD });

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
    try { await KH.loadProfile(); } catch (e) { toastError(e); }
    const initial = location.hash.replace('#', '');
    router.show(router.VIEWS.includes(initial) ? initial : 'today');
  }
  init();
  if (KH.pwa) KH.pwa.init();
})();
