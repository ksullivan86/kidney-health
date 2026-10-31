Status: in progress

# Connected devices groundwork + Withings (0.16)

Owner's ask: docs/dev/progress/0.14-plan.md, "Owner decisions (2026-10-31, devices)". Design: docs/dev/research/27-connected-devices.md.
Branch: this helper's worktree branch, started from `next-8` (commit locally, no push; the owner merges). Migration step 29.

## Plan

1. Research note 27 (done).
2. m029 (device_connections, device_imports); config WithingsEnv (WITHINGS_ENABLED, WITHINGS_CLIENT_ID, WITHINGS_CLIENT_SECRET_FILE);
   registry devices.enabled (DEVICES_ENABLED), devices.sync_hours (DEVICES_SYNC_HOURS) + JS twin + vectors.
3. app/devices/ package: store (connections, ledger, tokens sealed), withings (client via CheckedTransport), sync, routes, loop.
4. Admin About row; audit actions; BodySourceKey 'withings'; ENCRYPTED_COLUMNS.
5. UI: js/views/devices.js (Settings → Connected devices), origin "from Withings", demo mock.
6. Tests; OpenAPI; vectors; docs.

## Done

1. Research note 27 written (findings with links).

## Next

Step 2.
