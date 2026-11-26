Status: in progress (2026-11-26)

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
6. [~] Tests (node + pytest done; e2e next): tests/js/phone_reminders.mjs + tests/test_phone_reminders.py (pins Swift text and kinds); e2e in tools/e2e/device_mode.py.
7. [ ] Docs: handbook reminders page, ARCHITECTURE.md Device mode bullet, CHANGELOG Unreleased.

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
