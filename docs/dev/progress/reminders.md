# Progress: reminders by phone notification (role: reminders)

Status: complete

Branch `reminders` (from origin/main 01f5298) in worktree agent-a57dfd0f60ce89724. Do not push, no PR, no version bump, no
dependency changes. Design note: `docs/dev/research/35-reminders.md`.

## Done
1. Design note 35.
2. `app/webpush.py` (VAPID JWT, RFC 8291 encryption, host allowlist, sender); `tests/test_webpush.py` (RFC 8291 App. A exact).
3. Config `RemindersEnv` (+ `Settings.vapid_key_path`), m035 + `tests/test_migration_m035.py`, `app/reminders.py` (routes,
   `run_due`, `loop`), audit actions, export `reminders` (import skips it: SKIPPED_SECTIONS, NOT_IMPORTED, mock + settings.js
   IMPORT_NEVER_SENT, import vectors regenerated), main.py wiring, brand.USER_AGENT_PUSH, isolation matrix.
   `tests/test_reminders.py` 54 pass; isolation/export/import/audit/auth-coverage pass.

## Next
4. DONE: sw.js push + notificationclick; Settings → Reminders (`js/views/reminders.js`, section #set-reminders); demo twin (`js/mock/reminders.js`, `tests/js/reminders_demo.mjs`); `tests/test_reminders_ui.py`; OpenAPI regenerated (schema names prefixed Reminder/Push to avoid collisions).
5. DONE: Chromium walk `tools/e2e/reminders.py` (+ `reminders_app.py`; port 8118): 29 PASS (`cd tools/e2e && $PY reminders.py --out <scratch>/e2e-rem`).
6. DONE: docs/reminders.md, push.md note, deployment, network-allowlist, privacy, security, README index, deploy templates (.env, compose, quadlet, k8s deployment/secret, cilium), handbook (settings-and-keys #reminders, configuration, network-allowlist, NOTE35 source), CHANGELOG Unreleased, ROADMAP, ARCHITECTURE (egress list, step 35, ownership, section at the end). test_egress client list gains webpush.py.
7. DONE: full suite: 4 failures, 3 fixed (export key lists in tests/js/demo_local_storage.mjs and tools/e2e/demo_local.py; js/views/reminders.js omitted from the preview build, which must not mention serviceWorker). The 4th, test_ai_routing::test_the_status_says_where_each_feature_runs, saw a `lab_report_text` feature that exists only in another agent's worktree (agent-aa7dfc179da56c1ae); it passes alone here.

## Decisions
- Each reminder stores the browser's IANA time zone (`time_zone` column): the app has no profile time zone and containers run
  in UTC. Empty: the server's local time.
- Notification title: instance name only when the admin changed it from the default ("Kidney Health" names a condition), else
  "Food log".
- Due window: from the chosen time to 5 minutes after, once per day (`last_sent_on`, set before sending).
- Days bitmask: bit 0 = Monday ... bit 6 = Sunday (Python `weekday()`); 127 = every day.
- The device list shows the raw User-Agent turned into "Safari on iPhone" by the client's `deviceName` (as signed-in devices).
- "This device": GET returns `endpoint_hash` (SHA-256 of the endpoint, 32 hex) per device; the page hashes its own subscription and matches. Turn off = DELETE that id, then unsubscribe().

## Commands
PY=/tmp/claude-0/-home-user-kidney-health/8a6bc573-c86c-5a92-a072-0545790bf9a4/scratchpad/venv-new/bin/python
`$PY -m pytest -q -p no:cacheprovider -o addopts="" --basetemp=<scratch>/bt tests/test_reminders*.py tests/test_webpush.py`
