Status: in progress

# Care team planning audit

Base main bf35adb, branch fix/care-plan-confirmation-and-retry. Keep this PR unmerged.
Candidates: Clear reads live date fields after displaying its confirmation; plan application
reenables the same preview after a partial batch failure even though helper routes ignore client_id.
Confirmed: original functions fail 5 of 8 Node cases; fixed functions pass all 8.
Clear captures the shown range. Each preview sends once; after a lost/failed batch it offers
Review the plan, opening the first generated day's week. It never auto-retries or removes food.
Chromium: 18 checks pass at phone/light and desktop/dark. Real Clear removes only the confirmed
date and preserves a planned low treatment. Both real batches commit, the second reply is lost,
and the same preview cannot add them again. Focused pytest: 82 passed. Full pytest is running.
No clinical rules or API changes. Next: finish checks and publish the unmerged PR.
