/* Kidney Diet Log — links into the patient handbook (/learn; docs/dev/research/08-handbook-site.md §4.10).

   GET /api/handbook (app/handbook.py) says where the handbook is — "/learn/" when this server serves
   the built site, the published copy (HANDBOOK_PUBLIC_URL) otherwise, or nowhere — and which page
   each warning, alert and note links to. Nothing here hard-codes a handbook page: the server's table
   (from app/guidance/topics.py) is the one source, and tests/test_learn_links.py checks every path.

   * The Learn entry in the header (#learn-link) and Settings → About open the handbook in the same
     window: the handbook's own header has "Back to the food log", which matters in a Home Screen app
     with no browser back button.
   * Links inside warnings, alerts and notes open in a new tab (said to screen readers), so an entry
     being typed in a sheet is not lost.
   * When the server has no handbook and no public copy, no link is shown at all.

   Views call KH.learn.link(group, key) or KH.learn.forWarning(warning); guidance and AI cards carry a
   server URL ("/learn/eat/potassium/") and use KH.learn.href(url). Demo mode: js/mock/handbook.js. */
(() => {
  'use strict';
  const KH = window.KH;
  const { $, h } = KH;

  let info = null; // the last GET /api/handbook answer, or null (not loaded / failed)

  // Loads once per signed-in page (KH.app.start). Never throws: without it the app simply shows no
  // handbook links, and the reason goes to the console.
  async function load() {
    try {
      info = await KH.request('GET', '/api/handbook');
    } catch (err) {
      info = null;
      if (!(err && err.handled)) console.warn('Handbook links are unavailable:', err && err.message ? err.message : err);
    }
    renderNav();
    return info;
  }

  function baseUrl() {
    const url = info && typeof info.url === 'string' ? info.url : '';
    return url ? (url.endsWith('/') ? url : `${url}/`) : null;
  }

  // A handbook path ("eat/potassium/", "" for the start page, or a server URL "/learn/eat/potassium/",
  // optionally with "#anchor") → the href to use, or null when there is no handbook to link to.
  function href(path) {
    const base = baseUrl();
    if (base == null || path == null) return null;
    let p = String(path);
    if (p === '/learn' || p.startsWith('/learn/')) p = p.replace(/^\/learn\/?/, '');
    if (p.startsWith('/') || /^[a-z][a-z0-9+.-]*:/i.test(p) || p.split(/[?#]/)[0].split('/').includes('..')) return null;
    return base + p;
  }

  function entry(group, key) {
    const table = info && info.links && info.links[group];
    return table && Object.prototype.hasOwnProperty.call(table, key) ? table[key] : null;
  }

  // <a> "Learn: <page title>" for a table entry, or null. opts.sameWindow for navigation links.
  function anchor(target, title, { sameWindow = false, text = null, className = 'learn-more' } = {}) {
    if (!target) return null;
    const label = text || `Learn: ${title}`;
    if (sameWindow) return h('a', { class: className, href: target }, label);
    return h('a', { class: className, href: target, target: '_blank', rel: 'noopener' },
      label, h('span', { class: 'sr-only' }, ' (opens in a new tab)'));
  }
  function link(group, key, opts = {}) {
    const e = entry(group, key);
    return e ? anchor(href(e.path), e.title, opts) : null;
  }

  // The page for a warning or alert ({nutrient, flag?}): the flag's page when the flag caused it
  // (phosphate additives, avoid-list foods ...), else the nutrient's page.
  function forWarning(w, opts = {}) {
    if (!w) return null;
    if (w.flag && entry('flags', w.flag)) return link('flags', w.flag, opts);
    if (w.nutrient && entry('flags', w.nutrient)) return link('flags', w.nutrient, opts); // nutrient "avoid_ckd"
    return w.nutrient ? link('nutrients', w.nutrient, opts) : null;
  }

  // The header entry: shown once the server says where the handbook is.
  function renderNav() {
    const el = $('#learn-link');
    if (!el) return;
    const target = href('');
    if (target) el.setAttribute('href', target);
    el.hidden = !target;
  }

  KH.learn = {
    load,
    href,
    link,
    forWarning,
    info: () => info,
    available: () => !!(info && info.available),
    publicUrl: () => (info && info.public_url) || null,
  };
})();
