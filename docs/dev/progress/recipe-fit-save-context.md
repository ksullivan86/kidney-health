Status: complete

Base: main 84330f3; all branches refreshed before starting. Claude cbc48fc does not change fit
mutations. Own branch fix/recipe-fit-save-context. No PR/deployment.

Confirmed data-loss race: Replace recipe A, close/reopen Fit for B while the PUT waits. A's reply
sets global fit.undo to A's old body, but Undo uses the now-current B id. This can overwrite B.
Copy success can similarly close B's new dialog and use B's carbohydrate line in A's toast.
Capture mutation context; attach UI state only to the matching open result; store Undo's recipe id.

Fix: bind confirmation callbacks and write completions to the original request/recipe. Undo
stores that recipe id, name and old body, and never looks up the current dialog's id. Closing
invalidates pending fits; changing targets clears the result and dismisses stale confirmation.
Copy saves capture their carbohydrate line and only close the matching dialog. Issued writes
still complete and refresh the saved-meal list even when their old dialog has closed.

Validation: 8 Node scenarios pass (6 failed on main), including normal Replace/Undo, retry,
late copy, stale confirmation, closing a pending read, and a late Undo toast naming A rather
than B. Focused pytest: 638 passed, existing unused-handbook-source warning only. Chromium
reliability: 22 passed, including delayed real PUT for A while B opens, B unchanged on the
server, no Undo on B, normal Replace, and Undo restoring the prior ingredients/serving count.
Report /tmp/kidney-recipe-fit-context-20261029/report.json. Parity vectors, Ruff, syntax,
demo build and git diff --check pass. Ready on fix/recipe-fit-save-context. No PR/deployment.
