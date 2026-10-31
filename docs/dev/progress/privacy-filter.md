# privacy-filter progress

Status: in progress

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
  `ERROR_TEXT["privacy_filter"]`. Commit 93b8f8b.
- Tests: `tests/test_ai_privacy_filter.py` (39 pass), `tests/data/redaction_cases.json` (recall 67/70 = 0.957, floor 0.9,
  keep 96/96). `tests/test_ai_chat.py` get_today test now expects `[DATE_1]` in the cloud body.
- Ran test_ai_client, test_ai_routes, test_ai_chat, test_ai_fallback, test_ai_cloud_routing, test_vision_api, test_ai_golden,
  test_ai_prompts, test_ai_chat_save, test_ai_recipes, test_ai_routing: green after the one chat test change.

## Next
1. UI: `renderDryRun` row for `dry.privacy_filter` (app/static/js/views/ai.js); node --check.
2. Docs: ARCHITECTURE (AI section + "v0.20 work" note), docs/ai.md, docs/privacy.md, handbook AI/privacy pages, ROADMAP,
   CHANGELOG Unreleased. Then handbook checks, full suite.

## Decisions
- Filter runs when `not cfg.local_only` (anything not pinned to the private network counts as cloud).
- No prompt change (no PROMPT_VERSION bump); restore tolerates `PERSON_1`, `[person_1]`.
- Overlapping finds are merged into one span (street + town + ZIP = one address).
- Activity row keeps the filtered request and the cloud's own reply (with labels), plus the count.

## Commands
- py=/tmp/claude-0/-home-user-kidney-health/8a6bc573-c86c-5a92-a072-0545790bf9a4/scratchpad/venv312/bin/python
- `$py -m pytest -p no:cacheprovider --basetemp=<scratch>/pf/tN -q tests/test_ai_privacy_filter.py -s` (prints recall)
