Status: complete

Base: main 867b09b. All remote branches refreshed before starting; Claude 55b9c29 has no
changes to the suggestion function. Own branch fix/profile-suggestion-context; no PR/deployment.

Problem: Suggest targets validates the saved profile before requesting, then applies its reply even
if the person changes their profile details or manually entered care-team targets while it waits.
An old error/refusal can also appear against a newer form. Preserve the entries and require a new
suggestion when the form or saved profile changes. Keep genuine latest failures and retry working.

Fix: compare the saved profile reference and raw profile/target entries before applying a reply or
showing an error. Newer requests own the result and busy state. Disable all three suggestion triggers
while loading. If entries changed, keep them and announce that the person can suggest again.

Validation: 8 Node scenarios pass (6 fail on main). Chromium on an isolated local server: 8 passed,
including changed target/weight, retrying a suggestion, failed Profile save with entries preserved,
unchanged persisted data after failure, and successful save retry. Report:
/tmp/kidney-profile-suggestion-20261029/report.json. Focused pytest: 743 passed, with the existing
unused-handbook-sources warning. Node parity vectors, Ruff, JavaScript syntax, demo build and
git diff --check pass. API tests need local asyncio socket support, so ran outside the restricted
network sandbox; the earlier sandbox attempts were stopped. No assertion was skipped.

Ready on fix/profile-suggestion-context for Claude to review/cherry-pick. No PR/deployment.
