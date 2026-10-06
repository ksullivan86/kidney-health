# frontend sign-in + settings (M1)

Status: complete

Scope: note 07 §4.5 (flows) and §4.17 (settings menu), note 02 R10 (This device), ARCHITECTURE.md
"Frontend modules" and "M1 API". Ports 8140-8149. Scratch: `$SCRATCH/m1/frontend-signin-settings/`
(`$SCRATCH` = the session scratchpad).

## Plan

1. Register `food.off_enabled` (+ `food.off_consent`) in `app/settings_registry.py` (note 03 R10 /
   note 07 registry; minimal touch of a backend file, so the setup checkbox and the OFF_ENABLED lock work).
2. `index.html`: header gear, auth placeholder, Settings view, no-login banner, re-auth dialog, new
   scripts and stylesheets; `sw.js` SHELL_URLS in step.
3. `js/core.js`: router accepts views without a tab (settings); API hooks for `reauth_required`,
   `password_change_required`, `setup_required`; raw download helper.
4. `js/views/auth.js`: setup, sign-in, invite, reset, must-change-password, sign-out, re-auth, banners.
5. `js/views/settings.js`: Account, Preferences, Food data, AI placeholder, This device, Admin, About.
6. `js/mock/auth.js`, `js/mock/settings.js` (+ parity vectors `tests/data/settings_vectors.json`).
7. CSS `css/auth.css`, `css/settings.css`.
8. Tests; Playwright against the real server (375x812, 1280x800, light/dark); preview + sandbox.

## Done (written, not yet verified in a browser unless noted)

* `app/settings_registry.py`: `food.off_enabled` (instance, env OFF_ENABLED, default false) and
  `food.off_consent` (user) registered (minimal touch of a backend-core file; M2 barcode owns them).
* `index.html`: gear button, tabs `data-signed-in`, no-login banner, `#view-auth` (static forms for
  login/setup/invite/reset/change + proxy/signed-in panels), `#view-settings` skeleton (install panel
  moved from Profile into This device), Profile "Settings" card (Appearance card removed: the theme
  select is `#set-theme` in Settings → Preferences), `#sheet-reauth`, new scripts/styles; `sw.js` list.
* `js/core.js`: `afterError` hooks (401, 403 reauth_required → retry once, 403
  password_change_required, 503 setup_required) for server and demo; `download()`; router knows
  `settings` (no tab); `api.authStatus/me/updateMe/mySettings/updateMySettings/myKeys/setMyKey/deleteMyKey`.
* `js/engine/settings.js` (registry twin + precedence), `tests/data/gen_settings_vectors.py`,
  `tests/data/settings_vectors.json`, `tests/js/run_vectors.mjs` replays them (136 checks pass).
* `js/mock/auth.js`, `js/mock/settings.js` (demo twins), `js/views/auth.js`, `js/views/settings.js`,
  `js/main.js` (KH.app.start, auth boot), `js/pwa.js` (deviceStatus, clearOfflineData, persist),
  `js/views/profile.js` (theme moved, Open Settings), `css/auth.css`, `css/settings.css`.

* Verified against the real server (scratch `verify_real.py`: 55 checks; `verify_extra.py`: theme/week
  start saved, keys add/remove, re-auth cancel/complete, create account + setup link, admin reset link,
  invite while signed in, invite revoke, device sign-out, self delete, last-admin refusal, plain-HTTP
  notes from a LAN address, AUTH_MODE=none banner, proxy mode setup/logout URL/not-enabled reason).
  Zero CSP violations; console errors only "Failed to load resource" for provoked 4xx, plus Chromium's
  COOP-over-plain-HTTP note (server header, not the UI).
* Sandbox harness copy (`$SCRATCH/m1/frontend-signin-settings/sandbox/sandbox.py`) walks Settings:
  gear, invite + Copy, own key, export (demo), delete refused, disable Alex, sign out / in.

## Decisions

* `food.off_enabled` / `food.off_consent` registered in `app/settings_registry.py` now (backend-core
  file, minimal block) so the setup checkbox works and `OFF_ENABLED` locks it; M2 barcode owns them
  and must register its other `food.off_*` keys next to these (an identical re-registration is a no-op).
* Key widget buttons are **Test and save** and **Save**: `PUT /api/me/keys/{p}` stores the key
  whatever the test says (no test-only route), so a separate "Test" would be misleading.
* Theme moved from Profile to Settings → Preferences and is saved to the account (`ui.theme`,
  'auto' ↔ 'system'); the header toggle saves too; at sign-in a non-default account value wins over
  the device's stored choice. The install panel moved from Profile to Settings → This device.
* New engine twin `js/engine/settings.js` (labels, choices and precedence the view and the demo
  use), checked by `tests/data/settings_vectors.json` (generator + Node replay + pytest freshness).
* `APP_VERSION` constant in `settings.js` (no public version route); a test keeps it = `app/main.py`.
* Invite/reset tokens: moved from the URL to memory + this tab's sessionStorage at once (a reload
  keeps the link usable), removed after use.
* After a mid-session 401 the same person resumes the same view; a different person → fresh page.
* Proxy mode without a person calls `GET /api/me` to show the server's reason (not enabled / clash).
* Demo: Sam is a signed-in admin, Alex a sample member; OFF_ENABLED=false simulated as an env lock
  (the demo never contacts OFF); demo sign-out shows the sign-in screen (sam + any 15+ char password);
  links are `https://kidney.example/#/…` examples; export explains instead of downloading; no
  password blocklist, throttling or cookies.
* No "Meal guidance" section yet (note 06 / M2); AI is a "Not configured" placeholder with `#set-ai-slot`.

## Known, outside this role

* Chromium logs "Cross-Origin-Opener-Policy header has been ignored" on plain-HTTP non-loopback
  origins (`app/security.py` sends COOP on every response). Harmless; the security owner may send it
  only over HTTPS.

## Resumed run (after the usage limit)

* Last edits of the cut-off run were on disk: `core.js` ignores view hash changes while a sign-in
  screen shows; `settings.css` aligns source lines under checkboxes.
* Re-verified on the current tree: `node tests/js/run_vectors.mjs` (rules 5153 + settings 136 checks),
  `node --check` on every script, `verify_real.py 8141` 55 passed / 0 failed with zero CSP
  violations (console errors only the provoked 400/401/403/404/409/429 "Failed to load resource"),
  preview rebuilt (`build/kidney-diet-log.html`, 693,974 bytes) and walked with the sandbox copy,
  full `python -m pytest`: 1207 passed, 1 skipped. Sandbox: 17 walks + 3 sweeps + probes, 0 issues,
  782 requests, 0 unexpected.

Reproduce (scratch = `$SCRATCH/m1/frontend-signin-settings`):
`cd $scratch && python3 verify_real.py 8141` (then `./stop.sh real`), `python3 verify_extra.py`,
`python3 /home/user/kidney-health/scripts/build_preview.py --out sandbox/preview.html && cd sandbox && python3 sandbox.py --workers 3`.

## Next (for later milestones, not this role's M1 task)

* M2 fills `#set-ai-slot` (AI ideas) and adds a Meal guidance section; M2 barcode registers its
  other `food.off_*` keys next to `food.off_enabled` / `food.off_consent`.
* Sign-out's unsynced-entries warning activates when `KH.offline` (M2 outbox) exists.
