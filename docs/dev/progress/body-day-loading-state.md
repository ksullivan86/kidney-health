Status: complete

Base: main 84330f3. Refreshed all branches; Claude bbc9629 changes shared caches/backups and
does not change body.js. Own branch fix/body-day-loading-state; no PR/deployment.

Reviewing health save/retry flows found a related date problem: Today clears food when a date
changes, but its weights/readings remain until their own requests finish. Old alarms/rows are
visible under the new date while loading; a handled failure leaves them indefinitely. Clear the
body card and summary immediately and preserve latest-request ordering and existing Retry.

Fix: clear the card and summary before waiting for any Profile/measurement read, show a loading
message, and retain a Try again button for handled failures too. Existing request-order guard stays.

Validation: 7 Node cases pass (5 failed on main). Focused pytest: 654 passed, existing unused-source
warning only. Full weight/BP Chromium walk: 366 passed across mobile/desktop, hemodialysis and demo.
New delayed-date cases pass on all three real-server full walks. Initial run: 364 passed, two demo
row counts ran during loading; updated them to wait for the final card before asserting (no assertion
removed). Final report /tmp/kidney-body-day-loading-verified-20261029/report.json. Node vectors,
Ruff, JavaScript syntax, demo build and git diff --check pass.

Ready on fix/body-day-loading-state for Claude to review/cherry-pick. No PR/deployment.
An independent full pytest run of main 84330f3 is running in /tmp/kidney-health-validation-20261029;
log /tmp/kidney-current-main-full-suite.log. It does not read this branch's changing files.
