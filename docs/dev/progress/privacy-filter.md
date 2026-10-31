# privacy-filter progress

Status: in progress

Task: release 0.20 feature, the privacy filter (ROADMAP "Privacy tiers", tier 2). Rule-based, standard library, runs on
every request to a cloud AI, never on the local AI. Design note: `docs/dev/research/31-privacy-filter.md`.

## Done
- Merged next-8 (ff to 2c69a4e). Read client.py, routing.py, routes.py run_call/run_chat, features.Prepared, prompts.

## Next
1. Design note 31.
2. `app/ai/privacy_filter.py` + hook in `ChatClient.complete_json` (one place), `Prepared.dry_run` / `audit_copy`.
3. Known identifiers on `ProviderConfig.privacy_terms`, set in `routing.resolve_feature`.
4. Tests + `tests/data/redaction_cases.json`; docs; handbook.

## Decisions
- Filter runs when `not cfg.local_only` (anything not pinned to the private network counts as cloud).

## Commands
- py=/tmp/claude-0/-home-user-kidney-health/8a6bc573-c86c-5a92-a072-0545790bf9a4/scratchpad/venv312/bin/python
