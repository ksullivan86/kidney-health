Status: in progress

# Whoop, Activity and recovery, the active-day calorie extra (0.17)

Owner's ask: docs/dev/progress/0.14-plan.md, "Owner decisions (2026-10-31, devices)". Design: docs/dev/research/28-whoop-activity.md.
Branch: this helper's worktree branch, started from `next-8` (commit locally, no push; the owner merges). Migration step 30.

## Done

1. Research (2026-10-31): note 28 with the WHOOP API facts, accuracy evidence and the quiet-day decision.

## Next

2. Server: m030 (activity_days, activity_workouts, activity_extra_settings; shares/care_invites areas up to 5), WhoopEnv,
   app/devices/whoop.py, store/sync generalised for activity, app/activity.py (API + extra), Care team area "activity".
3. Engine twin + vectors (tests/data/activity_vectors.json), Today/What fits now, mock twin.
4. UI: devices.js Whoop + extra settings; Trends card; Today lines.
5. Tests, docs, checks.

## Commands

    S=/tmp/claude-0/-home-user-kidney-health/8a6bc573-c86c-5a92-a072-0545790bf9a4/scratchpad
    bash $S/whoop/pt.sh tests/test_connected_devices.py tests/test_whoop.py
