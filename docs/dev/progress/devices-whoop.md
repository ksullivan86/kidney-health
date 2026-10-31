Status: in progress

# Whoop, Activity and recovery, the active-day calorie extra (0.17)

Owner's ask: docs/dev/progress/0.14-plan.md, "Owner decisions (2026-10-31, devices)". Design: docs/dev/research/28-whoop-activity.md.
Branch: this helper's worktree branch, started from `next-8` (commit locally, no push; the owner merges). Migration step 30.

## Done

1. Research (2026-10-31): note 28 with the WHOOP API facts, accuracy evidence and the quiet-day decision.

2. Server (commit e694d38): m030 (activity_days, activity_workouts, activity_extra; shares/care_invites rebuilt for 5 areas,
   invite→share links restored), WhoopEnv in config, app/devices/whoop.py, store.add_activity/set_external, sync uses
   provider.first_days (Whoop 90), api revoke with token, app/activity.py (engine, GET /api/activity, PUT /api/activity/extra),
   log.day_summary adds calorie_extra (activity_extra=False for shared days without the area), guidance context.load_profile(day),
   sharing area "activity" + GET /api/shared/{id}/activity, audit activity.extra_on/off. tests/test_migration_m030.py passes.
3. Twin + UI (commit 51fb43f): js/engine/activity.js + tests/data/gen_activity_vectors.py (run_vectors "activity" group),
   js/mock/activity.js (sample 45 days, extra off by default), mock log/guidance/care/export/devices (two providers),
   js/views/activity.js (Trends card, Today lines, Whoop extra setting), devices.js generalised ({name} sentences),
   settings.js labels, sharing.js area label, export activity.csv/workouts.csv + JSON keys, import skips them.
   import vectors regenerated (calorie_extra: null in day answers).

## Next

4. tests/test_whoop.py (fake Whoop in tests/devices_support.py style), tests/test_activity.py (extra, API, isolation, care area),
   UI tests (tests/test_activity_ui.py), isolation matrix entries.
5. Docs: docs/devices.md, targets docs, handbook, network allowlist (+ tests/test_egress.py list), deployment table, .env.example,
   compose/quadlet/k8s, ARCHITECTURE, CHANGELOG; settings label text (devices.enabled) + settings vectors; OpenAPI.
6. Checks: ruff, openapi --check, vectors --check, run_vectors, Chromium walk, full suite.

## Commands

    S=/tmp/claude-0/-home-user-kidney-health/8a6bc573-c86c-5a92-a072-0545790bf9a4/scratchpad
    bash $S/whoop/pt.sh tests/test_connected_devices.py tests/test_whoop.py
