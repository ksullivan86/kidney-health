Status: complete

Base: main bf7436b. Refreshed all branches; Claude's last fetched branch 10289d8 does not change sharing.js.
Separate from the shared-day fix (same module, different section). No PR, deployment or environment publication.

Reproduced: a first link's late info/error replaces a second question and its Accept code; checking a new link
retains the old code; closing/reopening lets old focus/close/accept replies affect the newer question.
Eight of nine Node cases fail on unchanged main. Normal explicit acceptance already works.

Fix: question generation guards every info/accept result and focus timer. Start clears the old code and hides
Accept until info is ready. Closing invalidates the current question, while queued close events from a previous
opening cannot clear a reopened question. An earlier explicit acceptance may still complete on the server;
its late reply cannot navigate away from a newer question. No automatic accept or server-side change.
Validation: `python -m pytest tests/test_share_question.py tests/test_sharing_ui.py tests/test_e2e_tools.py
tests/test_handbook_content.py`: 636 passed, one existing unused-sources warning. Nine Node cases pass.
Chromium sharing walk plus synthetic info ordering, close and queued-close/reopen cases: 43 passed, zero failed
(/tmp/kidney-share-question-20261029/report.json). Synthetic link checks accept no link on the server.
Normal explicit acceptance, shared data, revocation and demo checks still pass.
Ruff, parity, syntax, demo build and git diff --check passed. Full suite not repeated for this focused fix.
