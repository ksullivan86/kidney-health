Status: in progress

Branch fix/retry-safe-health-writes, separate checkout /workspace/kidney-health-retry-safe,
base f2580fc (current main 7729123/Claude 289c2b3 plus tested reliability work). Refreshed all
branches before starting; schema steps currently end at 25. No PR/deployment/publication.

Confirmed in Chromium with a fresh temporary account: route.fetch lets POST weight commit (201),
then route.abort drops its reply. UI says "Nothing was saved", although GET shows one row.
Retrying the unchanged form creates two rows. Proof /tmp/kidney-lost-ack-probe/result.json,
script /tmp/kidney_lost_ack_probe.py. This is distinct from the already passing 500-before-write tests.

Implementation contract: optional Idempotency-Key for manual weight/BP/lab/symptom creates,
Copy day and saved-meal apply. Scope receipts by user + operation + key. Hash validated bodies;
same key/different data is 409; successful writes and receipt commit atomically in one transaction.
Replay the validated first result (201) for 24 hours. Then discard response JSON but retain the
key/hash tombstone until account deletion, returning a check-your-log conflict rather than ever
running that key again. No-key callers retain existing behavior. New append-only schema step 26.
No medication/dose/clinical-rule changes, no new external calls and no offline queue for these forms.

Client: reusable per-form attempt helper makes a random key, retains it across an unchanged retry,
changes it for changed data and resets on a new form/action or confirmed success. Pass it in request
options to the existing API helpers. Demo routes must honor the same header; raw API callers remain
compatible. Replace the false "Nothing was saved" network message with a truthful check-your-log
message (a failed connection cannot prove that a save did not commit).

Next: architecture/spec and schema/helper; API ownership, collision, rollback, expiry and replay
tests; client helper/header + demo parity and form wiring; Chromium lost-ack proof + normal failures;
relevant/full tests, docs and review branch push. Keep progress current after each step.

Backend checkpoint: schema 26, shared transaction/receipt helper and all six API operations are
implemented. 353 focused backend/migration/planning/health tests pass, with no skips or warnings.
Includes per-user keys, ownership before recipe replay, changed-body conflicts, independent/no-key
saves, concurrent eight-way retries, record-limit replay, failed receipt rollback, domain failure,
expired tombstones, deleted records not recreated, and owner cascade/foreign-key constraints.
Ruff and diff checks pass. Client and demo wiring are NOT complete; do not merge this WIP yet.
Next: client attempt helper/header forwarding, six forms, demo parity, lost-ack browser reproduction.
