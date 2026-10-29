# Retry a save whose reply was lost

Implementation in progress, 2026-10-29. Reproduction: a weight POST commits (201), then a browser
route drops the reply. The old form says nothing was saved; retry creates a second weight.
The existing 500-before-write checks cannot catch this case.

Manual weight, blood pressure, lab and symptom creates, Copy day and saved-meal apply accept an
optional `Idempotency-Key`. New forms make a random key for an attempt, retain it for an unchanged
retry, and use another key for another action. These forms still require a connection; this adds
no offline queue. Callers without a key keep the existing API behavior.

Schema step 26 adds `write_receipts`: user, operation, key, SHA-256 of the validated request,
validated response JSON and creation time. A successful write and its receipt share one SQLite
transaction. The writer is reserved before the key lookup, so concurrent retries cannot both write.
Validation/authentication run first; recipe ownership is checked before replay. Same key with
different data answers 409. A failed transaction leaves neither the write nor a receipt.

The first response can be replayed for 24 hours. Its JSON is cleared lazily on that person's next
keyed write; the key/hash remain until account deletion. After expiry, reuse answers 409 with an
instruction to check the log, and never writes again. Receipts are not imported/exported as patient
records, but are part of full server backups. Removing an account cascades to its receipts.

Security review:

* Every lookup includes user and operation; a key grants no access and is not a credential.
* Only successful, response-model-validated data is cached. No secrets or provider tokens enter it.
* The response cache can temporarily include a record later edited or deleted; replay returns the
  original response without restoring or changing that record. Document this retention in Privacy.
* Keys are bounded ASCII; they must contain no names or health details. The browser uses randomness.
* Header support adds no public route or external request. Existing CSRF/authentication still apply.
* The demo validates and replays the same header, with per-person scopes and the same conflict rules.

Checks: success/replay for every route; changed data, independent keys, no-key behavior, auth and
ownership; rollback, concurrent retries, expiry/tombstones and account deletion; client key lifecycle;
demo/server parity; and a Chromium write-then-drop-reply case that leaves exactly one stored record.
