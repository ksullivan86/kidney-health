Status: complete

Current combined verification branch, base 3659261. No production code change planned.
The remaining save/retry roadmap case is Plan's Copy day: existing regress.py checks success,
but not an injected server refusal followed by a retry with the chosen meals/date/status kept.

Add a browser check against temporary data: select Breakfast only, hold the first POST at 500,
verify nothing was copied, retry the identical body, verify exactly the selected entries once
and leave the source day unchanged. Then record results in the current combined verification.

Result: all six new checks pass. Combined reliability walk: 48 passed, 0 failed; report
/tmp/kidney-plan-copy-retry-20261029/report.json. E2E tool pytest: 35 passed; Ruff and diff checks
pass. No app code changed. Retry preserves the body and copies exactly the selected contents once;
the source records are byte-for-byte unchanged through the API. This tests a refused POST (500),
not the separate case where a write commits but its success reply is lost.

Ready in test/reliability-batch-integration. No PR, deployment or environment publication.
