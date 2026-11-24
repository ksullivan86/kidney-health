Status: in progress

# note39-step8: saved meals, profile, targets, settings and food preferences on the phone (design note 39, step 8)

Role: `note39-step8`. Worktree branch `worktree-agent-ab561d90e798d90fa`, reset (--keep) onto `worktree-agent-a576689c6f00d2f36`
(0fbbd57, steps 1-7). Commit own paths only; no push, no PR.
Venv: /tmp/claude-0/-home-user-kidney-health/8a6bc573-c86c-5a92-a072-0545790bf9a4/scratchpad/venv-new/bin/python
Another helper edits app/static/js/mock/{foods,meals,labs,symptoms,body,lists}.js and the gateway list for recipe import /
Instacart / list sending: keep edits there minimal and list them here.

## Plan
1. Server: saved meals in POST /push/v1/sync (`meals`, items name foods by FoodRef) and meal edits in POST /push/v1/changes
   with items by FoodRef (the phone knows no server food ids).
2. Gateway allow-list: profile GET/PUT, me/settings GET (+PATCH keys widened), guidance preferences GET/PUT/DELETE,
   foods GET one / search (to map server food ids). Swift allow-list the same.
3. Phone: `meal` kind in server_changes.js (read from cursor 0 once), step 4 sends new meals (both ways only);
   new js/mock/server_account.js: profile, targets, settings, food preferences from the server; edits only online.
   §8.7 point 5 card (profile and targets differ).
4. "N to review" badge, "needs review" mark on Today.
5. Tests, docs.

## Done

## Decisions

## Files touched outside my own
