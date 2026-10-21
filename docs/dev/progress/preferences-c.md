Status: complete

# Learn my food preferences, part C (the optional AI and the Ask chat)

Role: `preferences-c`. Worktree branch `worktree-agent-a54671d2c3cc100a0`, started at `29554eb` (part A, #60). Spec:
`docs/dev/research/09-food-preferences.md` §4.7, §4.8, §4.9, §8 (Q2, Q3), §7 "Part C". Parts A (done) and B (screens, in
parallel) are not mine. Never push, never open a PR, never touch another branch; the integrator does.

## Plan / state

- [x] 1 server side, tested: `prompts.person_block` tastes (`taste_names`, `taste_block`), `features.person_for`,
      `routes._person` (reads `context.explicit_preferences`), candidate `liked` bit, `you_like` reason code (schemas + guard),
      `guard.liked_ids`, `guard.person_excluded` (an idea with a Not for me food or a never-suggest group is dropped)
- [x] 2 `set_food_preference`: new `app/ai/chat_preference.py` (args, schema, `propose`), `chat.py` (`PREFERENCE_TOOL` in
      `SAVE_TOOLS`, `CONFIRM_PREFERENCE_TEXT`), `chat_save.py` (`run_save` dispatch before the mode, `save_now` refuses it,
      `tool_schemas`), `routes._prepare_chat`; not in `app/mcp/tools.py` at all (so MCP cannot list or call it)
- [x] 3 Ask card in `app/static/js/views/ask.js` (Remember / Cancel / Undo), API calls in `core.js` (not `ai.js`: part B);
      `tests/js/ask_taste_page.mjs` + `tests/test_ask_taste_ui.py` run the page code in Node against a fake server
- [x] 4 prompt rule 9 (meal ideas), rule 10 "Tastes" (Ask), tool note, `PROMPT_VERSION` = `2026-10-21.1`, snapshots and pin regenerated
- [x] 5 tests: `tests/test_ai_guard_preferences.py`, `tests/test_ai_chat_preference.py`, `tests/test_ai_preferences.py`,
      `tests/test_ask_taste_ui.py`, edits to `test_ai_prompts.py`, `test_ai_chat_save.py`, `test_ai_golden.py` (feature `chat`),
      `test_ai_eval_script.py`; 10 golden cases (`preferences-*`, `injection-preference-name`); `scripts/ai_eval.py` (skips the
      `chat` golden cases, four `chat-taste-*` questions in `CHAT_SET`, `taste_first_violations`)
- [x] 6 docs: ARCHITECTURE (food preferences, prompts and guard, Ask chat, Saving from the chat, MCP, file list), docs/ai.md,
      docs/assistant.md, docs/privacy.md, handbook `app/ai.md` and `app/privacy.md`, CHANGELOG, ROADMAP (the two live-evaluation
      lines), note 09 §7 and status, `tools/e2e/README.md`
- [x] 7 Chromium walk: `tools/e2e/ask.py` has a `tastes()` section; run at 375 light and 1280 dark: 144 passed, 0 failed
- [x] 8 final runs on the final tree: full `python -m pytest -q` in four shards, 4,812 tests passed, 0 failed, 0 skipped (no network);
      `node tests/js/run_vectors.mjs` all suites pass (guidance 109 checks, settings 615, import 254); `ruff check .` clean;
      `node --check` on `ask.js`, `core.js` and `tests/js/ask_taste_page.mjs`; `tools/e2e/ask.py` 144 checks passed (375 light,
      1280 dark). One existing test pinned `PROMPT_VERSION == "2026-10-15.4"` (`tests/test_lab_photo.py`): it now says `>=`.

## Decisions and why

- `set_food_preference` is NOT registered in `app/mcp/tools.py`. The chat looks its schema up in `chat_preference.INPUT_SCHEMA`
  (`chat_save.tool_schemas()`). Registering it with a flag would have meant a filter in `tools/list` and `tools/call`; leaving it
  out is safe by construction, and `tests/test_ai_chat_preference.py` pins it for the read and the read+save token scope.
- The tool's `run` never exists: `chat_save.run_save` hands it to `chat_preference.propose` before it looks at the trust mode,
  `chat_save.save_now` raises for it, and `propose` writes nothing. The request's trust mode is still computed by the route (it
  is for log_food / save_recipe); the tests patch `save_now` and `chat_save.propose` to fail and run all three modes.
- `clear` on a `neutral` row (the "stop using what you learned" switch) is "nothing to forget": no card, the model is told. A
  `neutral` row is not a taste, and Ask must not switch learned signals back on. Setting like/less/not_for_me over a neutral row
  is a card whose `previous` is `neutral`, so Undo puts neutral back.
- A request that changes nothing (already liked, `clear` with nothing saved, group already there) gets no card: the model gets a
  result with `saved: false, changed: false` and a note. It still counts toward `MAX_SAVES`.
- The card carries `previous` (`none|like|less|not_for_me|neutral` for a food, `none|like|less|not_for_me` for a group) and
  `previous_source`. The page re-reads the current state when Remember is pressed and keeps that for Undo (the person may have
  changed it elsewhere while the card was open). The page's source word for a food is its own `'ask'`, not read from the card.
- Fixed loop text for a taste card: `CONFIRM_PREFERENCE_TEXT` "Nothing has been remembered yet. Check this, then press Remember,
  or Cancel." (the old text says "Save button").
- Person block: the three keys are always present, `null` when empty (the block's existing convention), so the dry run always
  shows them. All existing person-block assertions were updated (`test_ai_prompts.py`, snapshots).
- Part A fix (reported to the integrator): `ai_bridge` set `liked = "you_like" in codes`, but a card shows at most two reasons,
  so a liked food with two kidney reasons read as not liked. `liked` is now `f.id in habit.pref.liked` (the person's Like itself).
  `often` has the same limit and was left as it is (existing behaviour, not part of this task).
- `guard.person_excluded`: the foods of a saved meal are candidate ids even when the person said Not for me to one of them (a
  saved meal is still offered by the rules, by design). An AI idea with such a food (or a never-suggest group) is dropped, reason
  `not_for_me` / `excluded_category` (the UI shows unknown codes with underscores as spaces, so `ai.js` needs no change).
- A food marked `less` (-2.0) usually scores below `MIN_SHOW_SCORE` (0) and is not a candidate at all; a `less` group (-1.0) is
  (checked by running the fixture). So the golden case "a less_often name is not recommended first" uses a less-often group and
  records an answer that puts none of its foods first; the app cannot order the model's ideas, so `not_first_food_names` is a
  recorded-good-answer check offline and `taste_first_violations` (reported, not a gate) in the live script.
- Added `foods.visible_categories(conn, user_id)` (the route `GET /api/foods/categories` uses it) so the tool and the route agree
  on "the person's food groups".
- The page's API calls (`foodPreferences`, `setFoodPreference`, `clearFoodPreference`) are in `js/core.js`, because `views/ai.js`
  belongs to part B right now. `tests/test_ask_ui.py` still holds: `ask.js` calls no route itself, only `KH.api`.
- Golden harness: `feature: "chat"` runs `POST /api/ai/chat`; `ai.chat_enabled` is switched on in its fixture and prepare() also
  gives the `chat` consent; `expect.nothing_saved` compares the rows of food_preferences, log_entries, meal_templates,
  user_settings and assistant_ask_keys before and after.

## Commands that reproduce the checks

- `python -m pytest tests/test_ai_prompts.py tests/test_ai_guard.py tests/test_ai_guard_preferences.py tests/test_ai_chat.py tests/test_ai_chat_save.py tests/test_ai_chat_preference.py tests/test_ai_preferences.py tests/test_ai_golden.py tests/test_ai_eval_script.py tests/test_mcp.py tests/test_mcp_write.py tests/test_ask_ui.py tests/test_ask_taste_ui.py -q`
- `KH_UPDATE_SNAPSHOTS=1 python -m pytest tests/test_ai_prompts.py` only after the prompts are final (then review `git diff tests/fixtures/ai`)
- `PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers python tools/e2e/ask.py --out <dir>` (Chromium, 375 and 1280 px, fake provider)
- `node tests/js/ask_taste_page.mjs` prints the taste-card scenarios as JSON
- `python -m pytest -q` (full), `node tests/js/run_vectors.mjs`, `ruff check .`
- Not done here (the owner): `python scripts/ai_eval.py --chat` with the model in use for `PROMPT_VERSION` 2026-10-21.1
