Status: complete

Base: main 84330f3, branches refreshed; Claude cbc48fc has no symptoms.js changes.
Own branch fix/symptom-day-loading-state. No PR/deployment.

Today Symptoms has the same stale-date gap as the weight/BP card: rows and handbook blocks remain
while the next date loads, and a handled failure leaves them indefinitely. Clear before waiting,
show a loading message, preserve request ordering, and retain Try again on failures.

Fix: clear at the start of the Symptoms loader and retain Try again for handled failures.
Today now starts Symptoms before waiting for food; rendering food or its error does not restart
that read. Otherwise a slow food request could still leave the previous day's symptoms visible.

Validation: 8 Node cases pass, including initial stale-content/handled-error regressions and both
food-read outcomes. Focused pytest: 671 passed, existing unused-handbook-source warning only.
Chromium Symptoms: 79 passed on real phone/desktop layouts and demo; the new cases hold BOTH
food and Symptoms reads across a date change, then test failure and retry. Today reliability:
17 passed. Reports: /tmp/kidney-symptom-independent-20261029/report.json and
/tmp/kidney-symptom-today-reliability-20261029/report.json. Parity, Ruff, syntax, demo build and
git diff --check pass.

Harness fixes: isolate its published-handbook fixture from any local build, and wait for the
initial day/symptom refresh before capturing the expected card (the test had captured Loading).
No assertion removed. Ready on fix/symptom-day-loading-state for Claude. No PR/deployment.
