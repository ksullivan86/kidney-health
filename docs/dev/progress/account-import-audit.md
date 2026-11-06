Status: in progress

Branch `audit/account-import-write-lifecycle` from main `cea3c94`. Create a PR and leave it unmerged.

Confirmed three UI failures: Cancel claims "Nothing was imported" while a real import is outstanding;
file/options can change while the write waits; an old Import action reads the latest payload/options,
and remains enabled while changed options are being checked. Three new Node cases fail on clean main;
two existing guarantees (failed import retry, cancelling a dry run) pass.

The Import callback now captures the reviewed payload/options and check generation. Changing an option
disables the previous Import button immediately. File, options and Cancel are disabled during a write,
with handler guards too. A failed answer restores controls and keeps the reviewed choices, explaining
that the person should check their data before retrying an uncertain result. Dry-run Cancel still works.
Backend import remains one transaction with rollback, duplicate detection and post-rollback cache invalidation.

Verified: 5 Node lifecycle cases, 14 focused pytest cases. Full pytest running. Extended the existing
`tools/e2e/import_walk.py` to hold the real committed reply after password re-authentication, check disabled
controls and verify Cancel cannot claim to cancel that committed import. Browser: 113 checks pass at phone/desktop sizes. The first run found an outdated harness expectation that omitted the exported activity/workouts CSV files; aligned it with app/account.py and reran successfully.

Ruff, vectors and generated pages pass. Next: finish all Node tests/strict handbook/full suite, review,
commit/push owned paths and create unmerged PR. Logs: `/workspace/work/import-audit/`.
