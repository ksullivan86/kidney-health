Status: in progress

Branch `audit/record-import-transactions`, main `cea3c94`. Keep PR unmerged.

Confirmed: body batch duplicate keys/measurements, lab import duplicate results and the manual/batch per-date
measurement limits are checked before acquiring SQLite's write lock. Reproduced overlapping real requests
with a held first snapshot; the second can finish on main, or wait for the lock after a fix. Cases cover
same/different import keys, lab imports, and create/move/batch capacity for weight/BP/symptoms. Clinical
limits and conversion/dedup rules must stay unchanged. Push already uses BEGIN IMMEDIATE; account import
and device writes do too. All 13 new cases fail on clean main and pass after taking BEGIN IMMEDIATE before the relevant reads.
This serializes body creates/moves/batches, symptom creates/moves and lab imports. Batch validation stays
before the lock, and no network is inside these transactions. Existing per-request connection cleanup
rolls back a refused check. Docs/handbook/changelog updated; 13 focused concurrency cases pass. Broad body/symptoms/lab-import suite and full pytest are running.
Ruff, OpenAPI, generated handbook and Node parity pass; strict handbook running. Next: finish checks,
update PR validation, mark ready but never merge. Logs: `/workspace/work/record-import-audit/`.
