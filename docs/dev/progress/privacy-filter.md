# privacy-filter progress

Status: complete

Task: release 0.20 feature, the privacy filter (ROADMAP "Privacy tiers", tier 2). Rule-based, standard library, runs on
every request to a cloud AI, never on the local AI. Design note: `docs/dev/research/31-privacy-filter.md`.

## Done
- Merged next-8 (ff to 2c69a4e).
- Design note 31 (commit d62b20c).
- `app/ai/privacy_filter.py`: Shield (labels per request, in memory), filter_body, restore, known_terms, expand_terms,
  preview. Hooked in `ChatClient.complete_json` (filter before each send incl. repair; restore parsed reply before validate);
  `ChatClient.request(filtered=...)` refuses an unfiltered cloud body. `ProviderConfig.privacy_terms` set in
  `routing.resolve_feature` (wrapper over `_resolve_feature`). `Prepared.sent_body/dry_run/audit_copy` show the filtered body;
  dry run has `privacy_filter: {on, replaced, text}` (None for local). Activity verdict `privacy_filter: N` (cloud only).
  `ERROR_TEXT["privacy_filter"]`. Commit 93b8f8b, 797df98.
- Tests: `tests/test_ai_privacy_filter.py`, `tests/data/redaction_cases.json` (recall 67/70 = 0.957, floor 0.9,
  keep 96/96). `tests/test_ai_chat.py` get_today test now expects `[DATE_1]` in the cloud body.
- UI: `js/views/ai.js` "Privacy filter" row in the dry run (and the fallback's), one line in the consent sheet for a provider
  that is not local. No JS twin (the server makes the filtered body).
- Docs (commit be5f40e): ARCHITECTURE ("v0.20 work" note, "Privacy tiers, tier 2" section, pipeline line), docs/ai.md
  "The privacy filter", docs/privacy.md, handbook app/ai.md + app/privacy.md (+ NOTE31 in sources.yml, regenerated), ROADMAP,
  CHANGELOG "Unreleased".
- Checks: ruff clean; node --check ai.js; run_vectors exit 0; gen_openapi --check exit 0; build_handbook --check ok;
  mkdocs --strict ok; AI test files + handbook tests 756 passed.

- Full suite: 7257 passed, 2 skipped, 1 failed (test_ai_chat_preference: a 19-digit food id in a tool error now reaches the cloud
  as `[ID_1]`, which is the filter working); test updated, that file 42 passed. The worker-thread change (4b3bda1) came after the
  full run started; test_ai_privacy_filter, test_ai_client and test_ai_chat were re-run on it: 155 passed.

## Left for the owner
- A named-entity model on top of the rules (note 31 §5): a dependency decision.
- A live run against a real cloud model to see whether models keep the labels intact (no prompt line tells them).

## Decisions
- Filter runs when `not cfg.local_only` (anything not pinned to the private network counts as cloud).
- No prompt change (no PROMPT_VERSION bump); restore tolerates `PERSON_1`, `[person_1]`.
- Overlapping finds are merged into one span (street + town + ZIP = one address).
- Activity row keeps the filtered request and the cloud's own reply (with labels), plus the count.

## Commands
- py=/tmp/claude-0/-home-user-kidney-health/8a6bc573-c86c-5a92-a072-0545790bf9a4/scratchpad/venv312/bin/python
- `$py -m pytest -o addopts= -q -p no:cacheprovider --basetemp=<scratch>/pf/tN tests/test_ai_privacy_filter.py -s` (prints recall)
