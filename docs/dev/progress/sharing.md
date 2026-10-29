Status: in progress (2026-10-29): design note 19 written; server next.

# Read-only sharing with a caregiver or dietitian (design note 19)

## Done

* `docs/dev/research/19-sharing.md`: the design (share links, four areas, `/api/shared/{id}/…` reusing the owner's handlers,
  switch `sharing.enabled` off by default, daily view audit, schema step 24).

## Next

1. Server: `app/migrations/m024_shares.py`, `app/sharing.py` (routes, `shared_owner(area)` dependency), the switch in
   `app/settings_registry.py`, audit actions, admin removal, OpenAPI lists, `docs/api/openapi.json`, tests.
2. Screens: Settings → Account → Sharing, `#/share/<code>`, the shared view (Visit prep from the shared routes, plus a day),
   People badge, demo answers, Node tests, Chromium walk.
3. Docs: ARCHITECTURE, docs/accounts.md, handbook settings page, CHANGELOG, ROADMAP. PR, merge when green.

## Decisions

* See note 19 §10. Shared answers call the owner's own route functions with the owner's user, so they cannot drift.
