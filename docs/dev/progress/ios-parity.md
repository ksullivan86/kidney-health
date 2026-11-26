Status: complete (2026-11-26): 0.26.0 merged (#196, 2d9e5d7); TestFlight build 11 started with remove_old_ci_certificates=true.

Status: in progress (2026-11-26)

Owner, 2026-11-26: "for the ios id like to be able to do anyting that can be done on the web app with a sever to be available
in the ios app without the need for a server if the setting makes since without a server". Also: care team notes on the phone
(yes), Withings and Whoop set up from the phone (yes), Profile weight in lb (yes).

## Work, one helper role each (each keeps its own docs/dev/progress/<role>.md)
* profile-weight-units: Profile weight boxes follow user.units.weight.
* phone-reminders: Reminders as the iPhone's own local notifications, no server needed.
* phone-care: care team notes and suggestions on the phone through the paired server.
* phone-devices: Withings and Whoop from the phone, with a server and without one.
* phone-ai-more: AI order, swaps and day plans on the phone.
* phone-recipe-import: recipe import from a web page with no server.
* phone-extras: export.zip with CSVs, the handbook in the app, on-device voice for Ask.

## Then (owner, 2026-11-26: "do that and then do an audit and then push the app")
1. When every helper is complete: full pytest, node vectors, e2e device_mode.
2. Audit: code review of the whole branch diff against main (security, CLAUDE.md rules, owner rules).
3. Release PR (bump version, CHANGELOG), CI green, merge, TestFlight build 11.

## Left out on purpose (need a server by nature)
Admin, accounts (password, two-step, passkeys, sign-in), phone shortcut tokens, outside AI apps (MCP), sharing with a care team
when there is no server (nobody to share with), list apps (Grocy, KitchenOwl, Mealie) and Instacart with no server (server keys).
Ask with no server stays off (needs the server's checks).

## Build 10 (2026-11-26)
* v0.25.0 tagged and the image published. TestFlight run 10 failed at archive: "Your account has reached the maximum number of
  certificates". Each run's fresh Mac makes an Apple Development certificate via the API key; the leftovers filled the account.
* Fixed in 54d5a6c: scripts/asc_ci_certs.py (stdlib + openssl), `this-run` in the workflow's EXIT trap, `old-runs` behind the
  workflow input remove_old_ci_certificates (default false). Tests: tests/test_asc_ci_certs.py, test_ios_app TestFlight test.
* Build 11 needs the old ones gone. Owner, 2026-11-26: "yes go ahead" — start build 11 with remove_old_ci_certificates=true.

## For the audit (from the helpers' reports)
* phone-extras: export vectors run by tests/test_export_vectors.py (subprocess), not run_vectors.mjs. Swift (Dictation.swift,
  HelpPages.swift) uncompiled until CI. Handbook packed by build_preview.py --handbook in CI/TestFlight.
* phone-ai-more2: app/ai/guard.py adds food `name` to order/rest rows (server change: check the name is the person's own/
  shared food and nothing else leaks). OnDeviceAI guides `.count(1...3)`, `.range(0...4)` may not compile (fallback
  `.maximumCount(3)`). OwnAI.maxText 60,000 vs the page's 80,000 for own key (pre-existing mismatch).

## Audit (2026-11-26)
* Security (outbound fetch, OAuth, signing, voice, handbook): no high or medium. Fixed: one token refresh per company;
  the signing script runs `python -I -S`. Left: old-runs matches "Created via API" (owner approved the cleanup).
* Server and owner rules: clean. Fixed: AI order rows carry the full stored name (guard.py + aimeal.js twin).
  Left: about.care_team falls back to a user name when no display name (the person sees it on the web too).
* Swift: fixed two ternaries with try/await (Devices.swift), PhoneTests task list, recognizer kept, audio back to playback,
  Safari sheet swipe-down answers. Left: recipe fetch's connected-address check relies on metrics arriving first.
* CI: lint (unused name), handbook on the Mac without watchdog (scripts/lock_without.py), CodeQL script end tags.
* Pending: the page-logic audit; the full pytest run; CI on 3c6401b.
