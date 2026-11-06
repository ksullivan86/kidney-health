Status: complete

Branch audit/record-import-transactions, main cea3c94. PR #163 ready for review; do not merge.

Confirmed: simultaneous body imports could duplicate a measurement or fail on an import key, lab imports
could duplicate a result, and creates/moves/batches could exceed the existing daily limits. All13 new real
concurrent-request cases fail on clean main and pass with the fix. The held body snapshot is _per_day,
after existing keys and measurement marks were read. Cases cover same/different keys, lab results and
create/move/batch capacity for weight/BP, plus symptom creates/moves. No timing assertion: release the first
snapshot after the second finishes or a bounded wait when the corrected write lock blocks it.

BEGIN IMMEDIATE now protects those reads and saves. Batch validation stays before the lock; no network is
inside it. Failed checks roll back when the request connection closes. Existing limits, matching rules,
conversions, API shapes and schema stay unchanged. Architecture, guides, handbook and changelog updated.

Focused suite:270passed. Ruff, OpenAPI, generated handbook, Node parity and strict handbook pass. Complete
CI run42223648313 for functional commit04f11e0 is green: Python3.12/3.14/3.15, native iOS/Swift, handbook,
lint and image checks. Python3.12 job127911545858 reports7399passed,2skipped and the two existing handbook
citation warnings. Concurrent local full runs exhausted /tmp; the passing isolated CI run verifies the full
suite. Completed local failure artifacts were removed; new checks use /workspace/work/pytest-scratch.
No branch or PR was merged. Logs: /workspace/work/record-import-audit/.
