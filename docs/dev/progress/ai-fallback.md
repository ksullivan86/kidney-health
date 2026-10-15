Status: complete (2026-10-15 12:40 UTC; the caller integrates the branch; nothing pushed, no PR opened)

# ai-fallback: privacy tier 3, "local first, cloud only when the local answer fails"

Branch `worktree-agent-a8a6db04c46be27aa`, base `f95d586` (lab-photo merged: `labs` is local-only in `app/ai/routing.py`).
ROADMAP "Privacy tiers", tier (3). Route value `local_then_cloud` for `photos`, `meal_ideas`, `describe` only.

## Design (decisions and why)
* Fallback only when the local answer **fails the schema or the app's rules**: client status `invalid` (no_json, schema, empty,
  truncated, invalid_response) or a judge verdict `dropped_all` / `no_fit` (or items all dropped by the text policy). NOT for
  unreachable, timeout, http errors, quota, a refusal (`refused`), a judge crash. Those answer exactly as route `local`.
* Cloud consent (same purpose, the cloud provider's host) is checked before the second call; without it nothing is sent and the
  local failure is returned with `cloud_fallback: {used: false, reason: "no_consent", consent: <request>}` (UI button).
* The cloud request is a second `Prepared` built for the cloud cfg (`Prepared.cloud`), so it is exactly what route `cloud` sends.
* Never a person's own provider (a person on "own" is not routed at all, as for `local`).
* Final answer is the cloud's when it is usable (`ok` or `refused`), else the local failure with a line saying the cloud was asked.

## Done
(nothing yet)

## In progress / next
1. routing.py + registry + JS twin + vectors
2. run_call fallback + dry run + consent
3. admin UI + person line + answer line
4. tests, docs

## Checkpoint 1 (backend core, 12:30 UTC)
Done: registry + JS twin + vectors (`local_then_cloud` for photos/meal_ideas/describe; chat/labs refuse); `routing.py` (resolve,
`Resolved.fallback`, text, route_view, plan); `routes.py` `run_call` rewritten around `Attempt` (fallback inside the same slot, both
calls quota-counted and audited, `cloud_fallback` in the answer); dry run (`cloud_fallback`); consent 409 names the cloud host
(`consent.fallback`); `/api/ai/consent` accepts the cloud provider; vision.py threads the cloud cfg. Existing AI tests pass.
Next: tests/test_ai_fallback.py, UI (ai_routing.js, ai.js consent sheet/answers, scan.js), docs.

## Checkpoint 2 (tests + UI, 12:15 UTC)
Done: `tests/test_ai_fallback.py` (35 tests: setting, plan, labs/chat refusal, resolution, every no-fallback case, consent, dry run, quota,
audit rows, photos, describe, cache), admin table (`ai_routing.js`: column + rule + warnings), `ai.js` (consent sheet with the
cloud checkbox, dry-run block, answer line `fallbackNotes`, activity row line), `scan.js` label line, CSS, `routing_page.mjs` scenario 7
and `test_ai_routing_ui.py`. Reproduce: `python -m pytest -q -p no:cacheprovider tests/test_ai_fallback.py tests/test_ai_routing_ui.py`.
Next: docs (ai.md, privacy.md, ARCHITECTURE.md, CHANGELOG, ROADMAP, handbook), full suite in 4 shards, final report.

## Checkpoint 3 (docs, 12:45 UTC)
Done: docs/ai.md (new "Local first, cloud only when the local answer fails" section, people/consent/dry-run lines, API, settings row),
docs/privacy.md, ARCHITECTURE.md (tier 3 section, PUT row, pipeline, frontend), CHANGELOG (Unreleased: people, operators,
contributors), ROADMAP (tier 3 done), handbook app/ai.md and self-hosting/configuration.md, deploy/.env.example comment.
Next: full suite in 4 shards, e2e Chromium check of the consent sheet (optional), final report.


## Checkpoint 4 (13:00 UTC)
Done since checkpoint 3: Settings → AI ideas offers "Allow the cloud AI (host) as the fallback" (`route_view` has `fallback.given` and
`fallback.request`; `personLines` in `ai_routing.js`; scenario 8 in `routing_page.mjs`); fallback answers are cached under their own key
(`_cache_key(..., fallback=True)`) so an answer from route `cloud` is never shown as a fallback; browser harness `tools/e2e/fallback.py`
(54 checks pass in Chromium: `cd tools/e2e && python fallback.py`), README row, `tests/test_e2e_tools.py` list. First full run (4 shards, before
these edits): shards 1-3 exit 0; shard 0 stopped at `test_guidance_ui` (it pins the export string `droppedNotes };`; fixed by ordering the
export `fallbackNotes, droppedNotes }`).
Next: full suite again at the final commit (4 shards), `node tests/js/run_vectors.mjs`, `device.py --only ai`, `ask.py`, final report.

## Final verification (12:40 UTC, at the last commit)
* Full suite in 4 shards (`timeout 900 python -m pytest -q -x -p no:cacheprovider <files>`): all exit 0.
* `tests/test_ai_fallback.py` (37), `tests/test_ai_routing*.py`, `tests/test_lab_photo*.py`, `tests/test_isolation_v03.py`,
  `tests/test_auth_coverage.py`: exit 0. `node tests/js/run_vectors.mjs` and `python tests/data/gen_settings_vectors.py --check`: ok.
* Chromium (`cd tools/e2e`): `python fallback.py` 54 checks, `python device.py --only ai` 24, `python ask.py` 108: all pass.

## Decisions to know about
* "Fails the checks" = client status `invalid` (after the one repair turn) or a judge verdict `dropped_all` / a food list whose items were all
  dropped by the text policy. `no_fit` (the model's own "nothing fits"), `refused`, `not_a_label`, `unreadable`, `no_food`, a judge crash and
  every transport error are NOT failures. Plausibility `checks` on a label are warnings, not rejections.
* The cloud consent is requested with the first consent (own tick box, default off) and can be given later (Settings line, or the answer's
  button); it is not required for the local call.
* If the cloud also gives nothing usable, the local failure is returned (with the line saying the cloud was asked).
* Fallback answers are cached under their own key (`:fallback`), so an answer from route `cloud` is never presented as a fallback.
* Photos: the cloud provider is a fallback only if it has a vision model and photos may go to it.

## Not done / for the owner
* A live run with a real Ollama and a real cloud key (the harnesses use fakes). `scripts/ai_eval.py` does not exercise the route.
* No schema change, no new route; `PROMPT_VERSION` unchanged.

## Reproduce
`python -m pytest -q -p no:cacheprovider tests/test_ai_fallback.py tests/test_ai_routing_ui.py`  `node tests/js/run_vectors.mjs`
`cd tools/e2e && python fallback.py`
