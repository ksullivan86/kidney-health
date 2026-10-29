Status: complete (2026-10-29): merged in #109 (14171bc).

# Read-only sharing with a caregiver or dietitian (design note 19)

## Done

* `docs/dev/research/19-sharing.md`: the design (share links, four areas, `/api/shared/{id}/…` reusing the owner's handlers,
  switch `sharing.enabled` off by default, daily view audit, schema step 24).

* Server: `app/migrations/m024_shares.py`, `app/sharing.py` (routes, `shared_owner(area)`), `sharing.enabled` (registry, JS
  twin, settings vectors, admin group "Sharing", deploy files, docs/deployment.md), `share.*` audit actions, `shares` in the admin
  people list and `DELETE /api/admin/users/{id}/shares`, OpenAPI lists and `docs/api/openapi.json`. Verified: `tests/test_sharing.py`
  (30), `tests/test_migration_m024.py`, the isolation matrix, auth coverage, OpenAPI, settings UI, deploy tests.
* Route change from the note: info and accept are `POST /api/shared/info` and `POST /api/shared/accept` (one router).
* Audit: rows are found by the activity query through the target, so `share.viewed`, `share.accepted` and the grantee's
  `share.ended` target the owner (`target_type='user'`) and land in the owner's activity; the owner's own actions target the share.

* Screens: `js/views/sharing.js`, the shared mode of `js/views/visit.js` (reads from `KH.sharing.reads`, headings and banner name
  the owner, areas not shared say so, a day card), `#sheet-share`, People badge and End sharing, activity labels, the demo's
  answers, CSS. Verified: `tests/test_sharing_ui.py` (8), the visit and body UI tests, `tools/e2e/sharing.py` (29/29).
* Docs: docs/accounts.md "Sharing with a caregiver", ARCHITECTURE (file map, feature row, migrations row, /api/me rows, "Sharing"),
  CHANGELOG, ROADMAP, note 19 (built, route and audit changes), handbook settings-and-keys `#sharing` and caregivers link,
  sources.yml NOTE19 (regenerated with scripts/build_handbook.py), tools/e2e/README.md, deploy files, docs/deployment.md.

## Next

1. Screens: Settings → Account → Sharing, `#/share/<code>`, the shared view (Visit prep from the shared routes, plus a day),
   People badge, demo answers, Node tests, Chromium walk.
3. Docs: ARCHITECTURE, docs/accounts.md, handbook settings page, CHANGELOG, ROADMAP. PR, merge when green.

## Decisions

* See note 19 §10. Shared answers call the owner's own route functions with the owner's user, so they cannot drift.
