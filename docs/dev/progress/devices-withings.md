Status: in progress

# Connected devices groundwork + Withings (0.16)

Owner's ask: docs/dev/progress/0.14-plan.md, "Owner decisions (2026-10-31, devices)". Design: docs/dev/research/27-connected-devices.md.
Branch: this helper's worktree branch, started from `next-8` (commit locally, no push; the owner merges). Migration step 29.

## Done

1. Research note 27 (findings with links, decisions).
2. Server: m029 (device_connections, device_imports); config WithingsEnv (WITHINGS_ENABLED, WITHINGS_CLIENT_ID,
   WITHINGS_CLIENT_SECRET_FILE; the plain secret refused); registry devices.enabled / devices.sync_hours + JS twin + vectors;
   app/devices/ (base, withings, store, sync, api); lifespan loop; admin About `devices`; audit actions device.*;
   ENCRYPTED_COLUMNS; BodySourceKey 'withings'; brand.USER_AGENT_DEVICES; egress list.
3. UI: js/views/devices.js (Settings → Connected devices, consent box, Sync now, Disconnect + also delete, the way back
   #/devices/<word>/<provider>), settings.js hooks (section, activity labels, About rows, settings group), main.js openPending,
   "from Withings" origin, CSS, sw.js; demo js/mock/devices.js + seed marks morning BP readings 'withings'.
4. Tests: tests/test_connected_devices.py (40, fake Withings tests/devices_support.py), tests/test_connected_devices_ui.py (8),
   tests/js/devices_demo.mjs; isolation matrix; test_body/test_push_ui/gen_import_vectors used 'withings' as an unknown source →
   now 'fitbit'. Body, import and settings vectors regenerated. OpenAPI regenerated.
5. Docs: docs/devices.md (setup), deployment.md rows, .env.example, compose, quadlet, k8s, network-allowlist, privacy, body.md,
   README index, ARCHITECTURE (migration row, section, egress list, status), CHANGELOG Unreleased, handbook (weight page section
   "From a Withings scale or monitor", settings table, self-hosting configuration, NOTE27 source; build_handbook.py run).

## Next

Checks: ruff, gen_openapi --check, settings vectors --check, node vectors, full suite once.

## Commands

    S=/tmp/claude-0/-home-user-kidney-health/8a6bc573-c86c-5a92-a072-0545790bf9a4/scratchpad
    bash $S/pt.sh tests/test_connected_devices.py tests/test_connected_devices_ui.py
    $S/venv312/bin/python scripts/gen_openapi.py --check; $S/venv312/bin/python tests/data/gen_settings_vectors.py --check
    node tests/js/run_vectors.mjs; /root/.local/bin/ruff check .
