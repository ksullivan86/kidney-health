/* Kidney Diet Log — PWA shell (note 02 R4, R10; note 01 §5.5): service worker registration,
   the "Update ready · Reload" toast, and the "Install on your phone" panel.

   * Registers /sw.js only in the installed app over a secure context (HTTPS, or localhost):
     never in the demo (?mock=1) or the preview build, which leaves this file out.
   * Trusted Types: the page's CSP has `require-trusted-types-for 'script'; trusted-types kh-sw`,
     and navigator.serviceWorker.register() is a TrustedScriptURL sink. One policy named kh-sw is
     created once and allows exactly '/sw.js'. Never add a default policy.
   * Updates: a waiting worker shows the update toast; Reload posts SKIP_WAITING and the page
     reloads on controllerchange. registration.update() runs at start and when the page becomes
     visible again, at most once an hour (a standalone app has no reload button).
   * The install panel lives in the Profile view until the Settings view exists
     ("Settings → This device"); renderInstallPanel(container) can render it anywhere. */
(() => {
  'use strict';
  const KH = window.KH;
  const { h, $, clear } = KH;
  const { MOCK } = KH.flags;

  const SW_URL = '/sw.js';
  const UPDATE_EVERY_MS = 60 * 60 * 1000;
  const HTTPS_DOC = 'docs/https.md';

  let swPolicy = null;
  let registration = null;
  let lastUpdateCheck = 0;
  let reloadRequested = false;
  let installPrompt = null; // Chromium's beforeinstallprompt event, kept for the Install button

  function isStandalone() {
    try { return window.matchMedia('(display-mode: standalone)').matches || window.navigator.standalone === true; } catch (e) { return false; }
  }
  function canUseServiceWorker() {
    return !MOCK && window.isSecureContext === true && 'serviceWorker' in navigator;
  }
  function platform() {
    const ua = navigator.userAgent || '';
    // iPadOS 13+ reports a Mac user agent; touch points tell it apart.
    if (/iPhone|iPad|iPod/.test(ua) || (/Macintosh/.test(ua) && navigator.maxTouchPoints > 1)) return 'ios';
    if (/Android/.test(ua)) return 'android';
    return 'desktop';
  }

  // The only TrustedScriptURL this page ever creates.
  function serviceWorkerURL() {
    const tt = window.trustedTypes;
    if (!tt || typeof tt.createPolicy !== 'function') return SW_URL;
    if (!swPolicy) {
      swPolicy = tt.createPolicy('kh-sw', {
        createScriptURL: (url) => { if (url === SW_URL) return url; throw new TypeError('blocked script URL'); },
      });
    }
    return swPolicy.createScriptURL(SW_URL);
  }

  // ---------------------------------------------------------------------------
  // Update toast
  // ---------------------------------------------------------------------------
  function showUpdateReady(worker) {
    const bar = $('#update-toast');
    if (!bar || !worker) return;
    bar.hidden = false;
    const btn = $('#update-reload');
    btn.disabled = false;
    btn.onclick = () => {
      btn.disabled = true;
      reloadRequested = true;
      worker.postMessage('SKIP_WAITING');
      // controllerchange normally reloads at once; do not leave the person waiting if it never comes.
      setTimeout(() => window.location.reload(), 4000);
    };
  }
  function watchForUpdates(reg) {
    if (reg.waiting && navigator.serviceWorker.controller) showUpdateReady(reg.waiting);
    reg.addEventListener('updatefound', () => {
      const worker = reg.installing;
      if (!worker) return;
      worker.addEventListener('statechange', () => {
        // With no controller this is the first install, not an update: nothing to reload.
        if (worker.state === 'installed' && navigator.serviceWorker.controller) showUpdateReady(worker);
        if (worker.state === 'activated') renderInstallPanel();
      });
    });
  }
  function checkForUpdate() {
    if (!registration || Date.now() - lastUpdateCheck < UPDATE_EVERY_MS) return;
    lastUpdateCheck = Date.now();
    registration.update().catch(() => { /* offline or server unreachable: try again later */ });
  }

  async function register() {
    if (!canUseServiceWorker()) return null;
    navigator.serviceWorker.addEventListener('controllerchange', () => {
      // Only after the person tapped Reload; the first install's clients.claim() also fires this.
      if (reloadRequested) window.location.reload();
    });
    try {
      registration = await navigator.serviceWorker.register(serviceWorkerURL(), { scope: '/' });
    } catch (e) {
      console.warn('Service worker registration failed; the app works without offline support.', e);
      return null;
    }
    lastUpdateCheck = Date.now(); // register() has just fetched /sw.js
    watchForUpdates(registration);
    document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible') checkForUpdate(); });
    navigator.serviceWorker.ready.then(() => renderInstallPanel()).catch(() => {});
    return registration;
  }

  // ---------------------------------------------------------------------------
  // "Install on your phone" panel (Settings → This device, R10)
  // ---------------------------------------------------------------------------
  function steps(...items) { return h('ol', { class: 'install-steps' }, items.map((t) => h('li', {}, t))); }
  function renderInstallPanel(container) {
    const panel = container || $('#install-panel');
    if (!panel || MOCK) return;
    const body = $('#install-body', panel) || panel;
    const installed = isStandalone();
    const offlineReady = !!(navigator.serviceWorker && navigator.serviceWorker.controller);
    const state = $('#install-state', panel);
    if (state) {
      const how = installed ? 'Installed as an app on this device.' : 'Open in the browser.';
      const offline = !window.isSecureContext ? 'Offline use needs HTTPS.'
        : offlineReady ? 'Offline ready: the app opens without a connection.'
          : canUseServiceWorker() ? 'Getting ready to work offline…' : 'This browser cannot keep the app for offline use.';
      state.textContent = `${how} ${offline}`;
    }
    clear(body);
    if (installed) {
      body.append(h('p', {}, 'It opens from your home screen like any other app. Your log stays on your own server; this device keeps only the app itself.'));
    } else if (installPrompt) {
      const btn = h('button', { class: 'btn primary', type: 'button', id: 'install-app' }, 'Install app');
      btn.addEventListener('click', async () => {
        const ev = installPrompt;
        installPrompt = null;
        btn.disabled = true;
        try { ev.prompt(); await ev.userChoice; } catch (e) { /* dismissed */ }
        renderInstallPanel();
      });
      body.append(h('p', {}, 'Add the app to this device so it opens in its own window, like an installed app.'), btn);
    } else if (platform() === 'ios') {
      body.append(steps('Open this page in Safari (Chrome on iPhone works too).', 'Tap Share, then "Add to Home Screen".',
        'Keep "Open as Web App" switched on, then tap Add.'));
    } else if (platform() === 'android') {
      body.append(steps('Open this page in Chrome.', 'Open the ⋮ menu and choose "Install app" (or "Add to Home screen").',
        'Open the app from its new icon.'));
    } else {
      body.append(steps('In Chrome or Edge: choose the install icon at the right of the address bar (or the menu → "Install").',
        'In Safari on a Mac: File → "Add to Dock".'));
    }
    if (!window.isSecureContext) {
      body.append(h('p', { class: 'install-note' }, 'Offline use and live camera scanning need HTTPS. Over plain HTTP the app still goes on your home screen, '
        + `but only as a shortcut that needs the server. Your administrator can follow ${HTTPS_DOC} in the project documentation.`));
    }
    body.append(h('p', { class: 'hint' }, 'Install from the address you will keep using: the same app at a different address (another name, port or http/https) starts empty.'));
    panel.hidden = false;
  }

  function init() {
    if (MOCK) return; // demo and preview: no service worker, no install panel
    window.addEventListener('beforeinstallprompt', (e) => {
      e.preventDefault(); // offer it from the panel instead of the browser's mini bar
      installPrompt = e;
      renderInstallPanel();
    });
    window.addEventListener('appinstalled', () => { installPrompt = null; renderInstallPanel(); });
    renderInstallPanel();
    // Register after the page has loaded, so the first visit's requests come first.
    if (document.readyState === 'complete') register();
    else window.addEventListener('load', () => { register(); }, { once: true });
  }

  KH.pwa = { init, register, renderInstallPanel, isStandalone, checkForUpdate };
})();
