/* Kidney Diet Log — PWA shell (note 02 R4, R10; note 01 §5.5): service worker registration,
   the "Update ready · Reload" toast, and the "Install this app" panel.

   * Registers /sw.js only in the installed app over a secure context (HTTPS, or localhost):
     never in the demo (?mock=1) or the preview build, which leaves this file out.
   * Trusted Types: the page's CSP has `require-trusted-types-for 'script'; trusted-types kh-sw`,
     and navigator.serviceWorker.register() is a TrustedScriptURL sink. One policy named kh-sw is
     created once and allows exactly '/sw.js'. Never add a default policy.
   * Updates: a waiting worker shows the update toast; Reload posts SKIP_WAITING and the page
     reloads on controllerchange. registration.update() runs at start and when the page becomes
     visible again, at most once an hour (a standalone app has no reload button), and at once when
     an API answer's X-KDL-Version differs from the version of the worker that served this shell
     (versionSeen, called by KH.api; note 02 §5: a cached shell and a newer server).
   * The install panel is part of Settings → This device; renderInstallPanel(container) can render
     it anywhere. deviceStatus() and clearOfflineData() serve the rest of that section
     (js/views/settings.js), which has no service-worker code of its own (the preview build leaves
     this file out). */
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
  let shellVersion = null; // the controlling worker's VERSION: the release this page's shell came from
  let mismatchSeen = null; // the server version an update was already asked for
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
  // KH.api passes every answer's X-KDL-Version. A different version than the shell's means the server was
  // upgraded under a cached shell: fetch the new worker now (once per version); its install shows the toast.
  function versionSeen(serverVersion) {
    if (!serverVersion || !shellVersion || serverVersion === shellVersion || mismatchSeen === serverVersion) return false;
    mismatchSeen = serverVersion;
    if (registration) {
      lastUpdateCheck = Date.now();
      registration.update().catch(() => { /* offline or server unreachable: the hourly check tries again */ });
    }
    return true;
  }
  function askShellVersion() {
    const controller = navigator.serviceWorker && navigator.serviceWorker.controller;
    if (controller) controller.postMessage('VERSION');
  }

  // Settings → This device re-renders when the offline state changes (the first visit's worker
  // takes control a moment after the page opened), so its rows never contradict the panel below.
  const listeners = new Set();
  function onStateChange(fn) { listeners.add(fn); return () => listeners.delete(fn); }
  function notify() { for (const fn of listeners) { try { fn(); } catch (e) { /* a listener's problem */ } } }

  async function register() {
    if (!canUseServiceWorker()) return null;
    navigator.serviceWorker.addEventListener('message', (event) => {
      const data = event.data;
      if (data && data.type === 'kdl-version' && typeof data.version === 'string') shellVersion = data.version;
    });
    if (typeof navigator.serviceWorker.startMessages === 'function') navigator.serviceWorker.startMessages();
    askShellVersion();
    navigator.serviceWorker.addEventListener('controllerchange', () => {
      // Only after the person tapped Reload; the first install's clients.claim() also fires this.
      if (reloadRequested) window.location.reload();
      else { askShellVersion(); renderInstallPanel(); notify(); }
    });
    try {
      registration = await navigator.serviceWorker.register(serviceWorkerURL(), { scope: '/' });
    } catch (e) {
      console.warn('Service worker registration failed; the app works without offline support.', e);
      return null;
    }
    if (!registration) return null; // a browser (or test harness) that blocks service workers answers nothing
    lastUpdateCheck = Date.now(); // register() has just fetched /sw.js
    watchForUpdates(registration);
    document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible') checkForUpdate(); });
    navigator.serviceWorker.ready.then(() => { renderInstallPanel(); notify(); }).catch(() => {});
    return registration;
  }

  // ---------------------------------------------------------------------------
  // "Install this app" panel (Settings → This device, R10)
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

  // ---------------------------------------------------------------------------
  // Settings → This device (R10): state for the Settings view, and "Clear offline data"
  // ---------------------------------------------------------------------------
  async function deviceStatus() {
    const out = { installed: isStandalone(), secure: window.isSecureContext === true, platform: platform(), offline: 'off',
      storage: null, persisted: null, updateReady: !!($('#update-toast') && !$('#update-toast').hidden) };
    if (!out.secure) out.offline = 'insecure';
    else if (MOCK || !('serviceWorker' in navigator)) out.offline = 'unsupported';
    else if (navigator.serviceWorker.controller) out.offline = 'ready';
    else if (registration) out.offline = 'installing';
    const st = navigator.storage;
    if (out.secure && st) {
      try { if (st.estimate) { const e = await st.estimate(); out.storage = { usage: Number(e.usage) || 0, quota: Number(e.quota) || 0 }; } } catch (e) { /* unavailable */ }
      try { if (st.persisted) out.persisted = await st.persisted(); } catch (e) { /* unavailable */ }
    }
    return out;
  }
  // Removes what this device keeps for offline use: the app's caches, the offline database
  // (M2) and the service worker itself; the next visit installs a fresh copy. Never touches
  // the server or the sign-in.
  async function clearOfflineData() {
    let removed = 0;
    if (window.caches && caches.keys) {
      for (const key of await caches.keys()) if (key.startsWith('kdl-')) { await caches.delete(key); removed += 1; }
    }
    try { if (window.indexedDB) indexedDB.deleteDatabase('kdl'); } catch (e) { /* not created yet */ }
    if (navigator.serviceWorker && navigator.serviceWorker.getRegistrations) {
      for (const reg of await navigator.serviceWorker.getRegistrations()) { try { await reg.unregister(); } catch (e) { /* already gone */ } }
    }
    registration = null;
    renderInstallPanel();
    return removed;
  }
  // Note 02 R5: an app opened from the home screen asks the browser to keep its storage.
  function askPersistence() {
    try {
      if (isStandalone() && window.isSecureContext && navigator.storage && navigator.storage.persist) navigator.storage.persist().catch(() => {});
    } catch (e) { /* unsupported */ }
  }

  function init() {
    if (MOCK) return; // demo and preview: no service worker, no install panel
    askPersistence();
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

  KH.pwa = { init, register, renderInstallPanel, isStandalone, checkForUpdate, versionSeen, deviceStatus, clearOfflineData, onStateChange };
})();
