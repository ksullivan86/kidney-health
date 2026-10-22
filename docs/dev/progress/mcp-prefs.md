Status: complete (2026-10-22; branch `worktree-mcp-prefs` from 89b97a5; full pytest 5639 passed, safety set 528 passed, ruff, vectors, handbook check and the MCP smoke harness green)

# mcp-prefs: `set_food_preference` for an assistant token with `assistant:prefs`

Task: offer Ask's taste tool to an assistant connected with a token, behind a new opt-in scope, least trust
(note 09 §4.8; decisions in the task brief, recorded in note 09 §4.8b).

## Done (how verified)

1. Scope `assistant:prefs`: `app/auth/api_tokens.py` (`PREFS`, `SCOPES`, `parse_scopes`, `scopes_for(can_log, can_prefs)`),
   `TokenCreate.can_prefs`, device tokens refuse it. Verified: `tests/test_mcp_prefs.py` (scope parsing, the tick, existing tokens),
   `tests/test_api_tokens.py`, `tests/test_device_tokens.py`.
2. Shared preference write: `app/guidance/api.py` `apply_preference` / `drop_preference` (the PUT and DELETE routes call them);
   `PreferenceBody` still `person` | `ask`, `PreferenceFood.source` also `assistant`. Verified: `tests/guidance/test_preferences_api.py`.
3. Ask's validation split into reusable helpers in `app/ai/chat_preference.py` (behaviour unchanged): `tests/test_ai_chat_preference.py`
   (the old "never listed" pin is now "listed and callable only with the scope"; plus "Ask is still a card whatever tokens exist").
4. The tool: `app/mcp/preference_tool.py`, wired in `app/mcp/server.py` (`all_tools`, `tool_named`, `Tool.needs`), audit
   `assistant.preference_set` (`app/audit.py`), daily cap `mcp_prefs` 30 per token, `PREFS_INSTRUCTIONS`.
5. App: "from your assistant" in the preferences list (`views/guidance.js`), the second tick, list words and activity label
   (`views/settings.js`), import/export accept `assistant` (`app/data_import.py`, `mock/import.js`, `tests/data/gen_import_vectors.py`
   then `import_vectors.json`).
6. Tests: `tests/test_mcp_prefs.py` (48), `tests/test_assistant_ui.py` + `tests/js/assistant_page.mjs`, `tests/test_settings_ui.py`,
   `tests/test_guidance_ui.py`, safety file listed in `tests/test_safety_set.py`; `tools/e2e/mcp_smoke.py` has a taste section.
7. Docs: note 09 §4.8b, ARCHITECTURE (tokens, MCP, Ask, step 17 wording, API table), `docs/assistant.md`, `docs/privacy.md`,
   `docs/deployment.md`, `docs/ai.md`, handbook (`app/ai.md`, `app/settings-and-keys.md`, `app/guidance.md`,
   `self-hosting/configuration.md`), ROADMAP line removed, CHANGELOG (three Unreleased sections), `tools/e2e/README.md`.

## Decisions and why

* **`not_for_me` is refused for a food flagged `hypo_treatment` and for a food group holding one.** The brief says such a Not for me
  "still leaves it listed under Treating a low"; the existing rule (note 09 §8 Q1; `swaps.hypo_options`, `insights.best_hypo_food`)
  is that a person's Not for me / Never suggest takes the food out of the options unless that would leave none (pinned in
  `tests/guidance/test_preferences_api.py`). Letting an unconfirmed assistant do that would change the options a person reads when low.
* The PUT body now takes `assistant` as a `source` too (Ask's Undo puts a row back with the source it had, which can be `assistant`; the demo twin
  `mock/guidance.js` has the same three).
* `request_key` is required (the brief lists it without `?`); `neutral` is not offered.
* The public PUT keeps `source` = `person` | `ask`: only the MCP tool writes `assistant`. No migration (the column is free text).
* A food group has no source, so a group set this way has no "from your assistant" label (only the activity list); the preferences list
  shows no token name (the row stores none).
* The daily cap raises the limit's own 429 (`ApiProblem` re-raised by `call_tool`), like the per-minute limit, not a tool result.
* The tool lives in `app/mcp/preference_tool.py` and `server.all_tools()` adds it: `tools.py` cannot import Ask's module (cycle).

## Not run here

* Browser walks (`tools/e2e/parity.py`, `prefs.py`, ...): no Chromium in this environment (`playwright` has no browser installed).

## Commands that reproduce

    python -m pytest tests/test_mcp_prefs.py tests/test_assistant_ui.py tests/test_ai_chat_preference.py
    python -m pytest -m safety
    node tests/js/run_vectors.mjs ; python tests/data/gen_import_vectors.py --check
    ruff check . ; python scripts/build_handbook.py --check
    python tools/e2e/mcp_smoke.py --port 8073        # 36 checks
    python -m pytest                                  # full
