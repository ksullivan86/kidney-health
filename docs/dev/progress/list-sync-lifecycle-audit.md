Status: in progress

# List app configuration lifecycle audit

Base main bf35adb, branch fix/list-sync-configuration-lifecycle. Leave the PR unmerged.
Candidates: late Test writes old list ids/errors to a new connection; Test/Send after Remove
return a response-validation 500; late Send records the previous list's receipt on a new one.
Changing list/app/key also keeps an unrelated last-send receipt even without a race.
Confirmed: the first 14 cases had 13 failures on main; the current fix passes them.
Guards check the configuration under a write transaction after the network wait. A changed
or removed connection gives 409, never the old list's results. A previous send may finish;
its confirmed count is returned with the conflict and audited when the owner still exists,
but never written as the new connection's receipt. Reconfiguration clears old receipts in
the server and demo. Extra tests cover late errors, partial sends and account deletion.
OpenAPI regenerated with Test's conflict response. Full pytest is running; no schema change.
