# Progress: reminders by phone notification (role: reminders)

Status: in progress

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
4. Service worker push handler, Settings → Reminders (`js/views/reminders.js`), demo twin (`js/mock/reminders.js`).
5. Docs, deploy templates, handbook, OpenAPI, Chromium walk `tools/e2e/reminders.py`.
6. Full suite.

## Decisions
- Each reminder stores the browser's IANA time zone (`time_zone` column): the app has no profile time zone and containers run
  in UTC. Empty: the server's local time.
- Notification title: instance name only when the admin changed it from the default ("Kidney Health" names a condition), else
  "Food log".
- Due window: from the chosen time to 5 minutes after, once per day (`last_sent_on`, set before sending).
- Days bitmask: bit 0 = Monday ... bit 6 = Sunday (Python `weekday()`); 127 = every day.
- The device list shows the raw User-Agent turned into "Safari on iPhone" by the client's `deviceName` (as signed-in devices).
- Turning off "this device": the page re-posts its subscription (idempotent, returns the id), deletes it, then unsubscribes.

## Commands
PY=/tmp/claude-0/-home-user-kidney-health/8a6bc573-c86c-5a92-a072-0545790bf9a4/scratchpad/venv-new/bin/python
`$PY -m pytest -q -p no:cacheprovider -o addopts="" --basetemp=<scratch>/bt tests/test_reminders*.py tests/test_webpush.py`
