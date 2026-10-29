Status: complete

# Porting ChatGPT's 2026-10-29 reliability branches

Branch `worktree-agent-a0caf55a146a4e5ef`, fast-forwarded to PR #122's head (fa48c85, release 0.11.0). Local commits only:
no push, no PR.

Done (each new test failed on the code before it and passes after):

1. fc5ba6d Symptoms load on their own: cherry-picked (443edf5). 4 of 8 Node cases failed before.
2. 3659261 weight/BP read starts before food: cherry-picked (0729c43) on top of 1. 2 of 9 Node cases failed before.
   CHANGELOG line covers both cards.
3. 609aaf8 recipe Replace/Undo context: cherry-picked (f530295). Its Node test needed the real core.js helpers
   (`unknownOf`, `atLeast`, `atLeastWords`) that our newer Fit sheet uses; with them 6 of 8 fail on the old plan.js.
4. 471bc95 health_save_retry.py: not cherry-picked. reliability.py already walks failed save + retry for weight, BP and
   Labs (and Plan, Profile). Its extra server-side checks (nothing stored after a failure, same body on retry, stored
   once) were added to `walk_body_save` instead.
5. e866a04 recipe Add to a day by servings: cherry-picked; client only, API scale contract unchanged (server
   `app/meals.py` and the demo `mock/meals.js` both log item × scale). 9 of 10 Node cases failed before.

Integration branch `test/reliability-batch-integration`: only re-applies these and older fixes we have; its plan.js Fit
helpers are an older version than ours. Nothing else to port.

Checks run on the final tree: Chromium reliability.py 87 passed (port 8161), symptoms.py 79 passed (8163), body.py 366
passed (8165); `node --test tests/js/*.test.mjs` 150 passed; run_vectors.mjs, gen_guidance_vectors.py --check,
gen_openapi.py --check and ruff clean; targeted pytest (symptoms, body, recipes, planning, reliability, e2e tools,
handbook, frontend shell, layout, security, PWA, preview build, deploy) all pass. Full pytest not run.
