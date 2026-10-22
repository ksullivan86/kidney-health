Status: in progress (started 2026-10-22; branch `worktree-mcp-prefs` from 89b97a5)

# mcp-prefs: `set_food_preference` for an assistant token with `assistant:prefs`

Task: offer Ask's taste tool to an assistant connected with a token, behind a new opt-in scope, least trust
(note 09 §4.8; decisions in the task brief, recorded in note 09 §4.8b).

## Plan and state

1. [ ] Scope `assistant:prefs` (`app/auth/api_tokens.py`, `TokenCreate.can_prefs`, Settings tick).
2. [ ] Shared preference write (`app/guidance/api.py`): `apply_preference` / `drop_preference` used by the PUT/DELETE routes and the tool.
3. [ ] Ask's validation split into reusable helpers (`app/ai/chat_preference.py`), behaviour unchanged.
4. [ ] The tool (`app/mcp/preference_tool.py`), wired in `app/mcp/server.py`; audit `assistant.preference_set`; cap 30 a day per token.
5. [ ] "from your assistant" in the preferences list, activity label, import/export accept `assistant`.
6. [ ] Tests (`tests/test_mcp_prefs.py`, updated pin in `tests/test_ai_chat_preference.py`, scope parsing, Settings tick, safety test).
7. [ ] Docs: note 09 §4.8b, ARCHITECTURE, `docs/assistant.md`, handbook, ROADMAP, CHANGELOG.
8. [ ] Full checks.

## Decisions (and why)

* Request body of `PUT /api/guidance/preferences/{id}` keeps `source` = `person` | `ask`; `assistant` is only ever written by the
  MCP tool (a signed-in browser cannot claim it). Responses, export and import accept it.
* No schema change: `food_preferences.source` is free TEXT (step 17), so no migration.

## Checks that reproduce

(filled in as they are run)
