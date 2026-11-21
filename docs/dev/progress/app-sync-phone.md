Status: in progress

# app-sync-phone: the phone side of note 38 step 4 (sending to your server)

Role: `app-sync-phone`. Branch: the worktree branch (no push, no PR). Server side: PR #188 (`app/app_sync.py`).

## Plan
1. [ ] Page module `app/static/js/mock/server_sync.js` (queue, batches, answers), loaded after `mock/device.js` (index.html, sw.js).
2. [ ] Swift: `ios/KidneyHealth/Services/ServerSync.swift` + bridge kinds in `FoodServices.answer`; `Settings.syncURL` in Core.
3. [ ] Settings → This device: "Sending to your server" block (`views/settings.js`).
4. [ ] Tests: `tests/js/server_sync.mjs` (+ pytest runner), round trip in pytest, static checks in `tests/test_ios_app.py`, e2e case.
5. [ ] Docs: ARCHITECTURE "Device mode", docs/push.md, handbook install page, CHANGELOG, note 38 status.
