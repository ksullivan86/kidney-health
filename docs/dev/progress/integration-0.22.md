Status: in progress

# 0.22.2: security choices and the integrated run

Base main 970ba9b (0.22.1). Branch `next`, pushed to `claude/adoring-sagan-th5swr`.

## Done

* The owner's choices from `security-review-recent.md` (2026-11-06): 1 no grantee `ip_prefix` on share rows in the owner's
  activity; 2 a reset link removes every passkey; 3 the share form says a shared food log includes notes; 4 an admin's End
  sharing writes `share.ended` for the other side too; 5 left as is. Tests: `test_a_reset_link_removes_the_passkeys`,
  `test_an_admins_end_sharing_shows_on_both_sides`, `test_the_owners_activity_does_not_show_where_the_grantee_reads_from`.
  Docs: ARCHITECTURE, CHANGELOG Unreleased, docs/accounts.md, handbook settings-and-keys.

* Integrated run: new `tools/e2e/everything.py` (port 8116): one server with the Care team, devices (Withings with a
  placeholder client), list sync, recipe import, Instacart (fake), test accounts and the AI choice on; mum (admin, planned
  week) and dad (her Caregiver) open every screen at 375/1280 light/dark; mum opens the Instacart sheet. 111 passed.
* Feature harnesses at 0.22.1: sharing 89, test_accounts 38, lists_recipes 42, instacart 25, shopping_late_replies 30,
  recipe_import_late_replies 20, care_plan_actions 18, passkeys 31, two_step 42, route_choice 34, reliability 87,
  profile_reliability 8: all pass. late_replies failed on button names from before the Care team (0.14); harness updated,
  8 passed. No app bug found.

## Next

* Integrated Chromium run on one server with everything on (Care team, devices, list sync, Instacart, AI choice) at 375 and
  1280, light and dark, with fake outside services; upgrade from 0.21.1.
* Then version 0.22.2 and its release PR.
