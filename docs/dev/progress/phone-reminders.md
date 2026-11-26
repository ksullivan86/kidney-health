Status: in progress (2026-11-26)

# phone-reminders: Settings → Reminders as the iPhone's own notifications

Task: Reminders work in the iPhone app (device mode) with no server, as local notifications (UNUserNotificationCenter,
one-shot UNCalendarNotificationTrigger). Design in docs/dev/research/35-reminders.md §7.

## Plan / state
1. [ ] Design section in note 35 §7.
2. [ ] Page: js/mock/phone_reminders.js (planner, bridge calls, when to replan), loaded after js/mock/device.js (index.html, sw.js).
3. [ ] View: js/views/reminders.js device block ("This iPhone"), no device list; KH.openScreen in main.js for taps.
4. [ ] Un-hide #set-reminders in device mode (base.css, settings.js DEVICE_LEFT_OUT).
5. [ ] Swift: ios/KidneyHealth/Phone/LocalReminders.swift; bridge kind `reminders` in FoodServices.swift; delegate in AppDelegate;
       taps through PageBridge.
6. [ ] Tests: tests/js/phone_reminders.mjs + tests/test_phone_reminders.py (pins Swift text and kinds); e2e in tools/e2e/device_mode.py.
7. [ ] Docs: handbook reminders page, ARCHITECTURE.md Device mode bullet, CHANGELOG Unreleased.

## Decisions
* The page plans; Swift only replaces the pending requests whose id starts with `reminder-`. Swift owns the words (title
  "Food log", bodies of app/reminders.py BODIES) so the page cannot put other text on the lock screen.
* Times are DateComponents with no time zone: the phone's own zone.
