Status: complete (2026-11-26)

# phone-reminders: Settings → Reminders as the iPhone's own notifications

Task: Reminders work in the iPhone app (device mode) with no server, as local notifications (UNUserNotificationCenter,
one-shot UNCalendarNotificationTrigger). Design in docs/dev/research/35-reminders.md §7.

## Plan / state
1. [x] Design section in note 35 §7.
2. [x] Page: js/mock/phone_reminders.js (planner, bridge calls, when to replan), loaded after js/mock/device.js (index.html, sw.js).
3. [x] View: js/views/reminders.js device block ("This iPhone"), no device list; KH.openScreen in main.js for taps.
4. [x] Un-hide #set-reminders in device mode (base.css, settings.js DEVICE_LEFT_OUT).
5. [x] Swift: ios/KidneyHealth/Phone/LocalReminders.swift; bridge kind `reminders` in FoodServices.swift; delegate in AppDelegate;
       taps through PageBridge.
6. [x] Tests (node, pytest, e2e reminders_walk in tools/e2e/device_mode.py): tests/js/phone_reminders.mjs + tests/test_phone_reminders.py (pins Swift text and kinds); e2e in tools/e2e/device_mode.py.
7. [x] Docs: handbook reminders page, ARCHITECTURE.md Device mode bullet, CHANGELOG Unreleased.

## Decisions
* The page plans; Swift only replaces the pending requests whose id starts with `reminder-`. Swift owns the words (title
  "Food log", bodies of app/reminders.py BODIES) so the page cannot put other text on the lock screen.
* Times are DateComponents with no time zone: the phone's own zone.

## Checks (reproduce)
* `TZ=UTC node tests/js/phone_reminders.mjs` (28 checks).
* pytest: the repo's deps are in the scratchpad venv `.../scratchpad/venv-new/bin/python -m pytest -q tests/test_phone_reminders.py
  tests/test_ios_app.py tests/test_device_mode.py tests/test_reminders_ui.py` (all pass).
* No Swift toolchain here: LocalReminders.swift is checked by reading and by the pins in tests/test_phone_reminders.py.

## Committing shared files
Shared files carry other agents' hunks. Stage only mine: `python3 <scratchpad>/tools/stage_hunks.py FILE MARKER...` (git apply
--cached), check `git diff --cached`, then `git commit` with no pathspec.
* The device build packs `js/views/reminders.js` (index.html `data-device="keep"`, honoured by scripts/build_preview.py
  `_assets(..., device=True)`); the web demo still leaves it out.
* e2e of only my walk: a scratch driver that imports tools/e2e/device_mode.py and runs `reminders_walk` (17 PASS).
  The e2e uses `_until` polling: wait_for_function is refused by the app's CSP.
* Docs done: note 35 §7, docs/reminders.md "In the iPhone app", handbook settings-and-keys.md #reminders-iphone and install.md,
  ARCHITECTURE.md Device mode bullet "Reminders", CHANGELOG Unreleased "Added", note 39 out-of-scope line.
* Final checks: node phone_reminders (28) and run_vectors pass; targeted pytest (phone_reminders, ios_app, reminders_ui,
  device_mode, handbook_content, preview_build except a failure from another agent's recipe_import.js "<script" text) pass;
  ruff clean. Full suite left to the orchestrator (disk space). test_device_mode.py: the hidden-list check now starts at the
  CSS comment, since #set-care was un-hidden by phone-care.
* Only CI (Xcode) can check LocalReminders.swift compiles and that notifications fire and taps open the screen.
