Status: complete (2026-10-31)

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

4. Tests (f2c0a2e, e3ddc6e): tests/test_whoop.py (18, fake Whoop in tests/devices_support.py), tests/test_activity.py (16),
   tests/test_activity_ui.py (9, incl. Node runs of the Today lines and the demo vs the server engine), tests/test_migration_m030.py (3);
   isolation matrix (3 tables), sharing SAME list (+activity), egress client list, export file/key lists, import vectors.
5. Docs (0918b46): docs/devices.md (Whoop section, the extra), targets-and-labs.md, privacy.md, accounts.md, deployment.md rows,
   network-allowlist.md, deploy/.env.example, compose, quadlet, k8s; handbook targets-and-warnings (#active-day-calories),
   reports-for-your-team (#activity-and-recovery), settings-and-keys, self-hosting/configuration; sources NOTE28, ODRISCOLL20,
   GERMINI22, WHOOP-API (build_handbook.py run); ARCHITECTURE (row 30, section, egress, status, area list); CHANGELOG Unreleased.
   devices.enabled label/help name Whoop (settings vectors regenerated).
6. Found and fixed (345af1e): the Connected devices section had id set-devices, the same as Account → Signed-in devices (which comes
   first), so Settings never showed Connected devices. Now set-connected. Screenshots at 375 px light/dark checked (no sideways scroll).
7. Checks: ruff clean; gen_openapi --check; settings/import/activity vectors current; node run_vectors no failures; handbook
   --check + content tests (592 passed); mkdocs strict build, check_links 0 broken; Chromium walk tools/e2e/learn.py 72 passed.

8. Full suite: 7023 passed, 2 skipped, 5 failed (31 min). The 5 were lists that name every export key or vector file
   (settings.js IMPORT_NEVER_SENT, tests/js/demo_local_storage.mjs, tests/data/README.md); fixed and those tests rerun
   (42 passed), with run_vectors, ruff and gen_openapi --check.

## For the owner

* Register a Whoop developer app (developer-dashboard.whoop.com, needs a Whoop membership; Sandbox tier = up to 10 members, no
  approval) with redirect `<PUBLIC_URL>/api/devices/whoop/callback` and scopes offline, read:cycles, read:recovery, read:sleep,
  read:workout; then set WHOOP_ENABLED, WHOOP_CLIENT_ID, WHOOP_CLIENT_SECRET_FILE (docs/devices.md#whoop) with DEVICES_ENABLED.
* Not tried against the real Whoop: token endpoint auth style (form, as Whoop's tutorials), the score_state of the cycle in
  progress, and whether a refused refresh is 400 or 401 (both handled).

## Decisions

* Quiet-day level = lower quartile (nearest rank) of the person's finished Whoop days in the 28 days before, at least 14 days
  (note 28 §4.1): Whoop compared with Whoop cancels a tracker's constant error (O'Driscoll 2020, Germini 2022).
* A Whoop day = date of (cycle start + 12 h) in its timezone_offset; two cycles on a date keep the later.
* No read:profile: Whoop's user id comes from the first cycle (exchange reads cycle?limit=1; else the first sync).
* Shared day views without the activity area use the base calorie target (activity_extra=False).
* Whoop days/workouts are exported, not imported (SKIPPED_SECTIONS + NOT_IMPORTED line).

## Commands

    S=/tmp/claude-0/-home-user-kidney-health/8a6bc573-c86c-5a92-a072-0545790bf9a4/scratchpad
    bash $S/whoop/pq.sh tests/test_whoop.py tests/test_activity.py tests/test_activity_ui.py tests/test_migration_m030.py
    $S/venv312/bin/python tests/data/gen_activity_vectors.py --check; node tests/js/run_vectors.mjs
    $S/venv312/bin/python scripts/gen_openapi.py --check; /root/.local/bin/ruff check .
    bash $S/whoop/walk.sh   # handbook build + links + Chromium walk
