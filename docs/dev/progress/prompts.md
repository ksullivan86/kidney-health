# Progress: AI prompts worded from the profile (kidney-only profile, part 3)

Status: complete (code, tests and docs done, reviewed and revised; the owner's live golden run for 2026-10-15.3 is the only thing
left). Role: `prompts`. Worktree branch `worktree-agent-ab8653f4223b714a0` (no push, no PR: the owner or the parent agent opens it).
Task: ROADMAP "Kidney-only profile: diabetes as an option, not an assumption", the item "the AI prompts worded from the profile".

## Done

* `app/ai/prompts.py`: `SYSTEM_PROMPT` (meal ideas) and `CHAT_SYSTEM_PROMPT` (Ask) are templates whose **only** profile-dependent
  part is `[[CONDITION]]`; `condition_text(person)` words the person from whitelisted profile values; `system_prompt(person)` and
  `chat_prompt(person)` render them (`chat_system` uses `chat_prompt`). `person_block` sends null for a stage or diabetes type
  not chosen yet (not the stored default 3b / type 1); `targets_block(meal_carbs=False)` leaves out the per-meal and per-snack
  carbohydrate goals for diabetes "None". `PROMPT_VERSION` is `2026-10-15.3`.
* **Revision after review (coordinator, 2026-10-15):** (1) the low-treatment rules, the "a low is never questioned or delayed"
  clause and the log_food `hypo` purpose note are the same text for every profile (the "None" variants, the slots and the
  renumbering were removed; `chat.tools_text` lists `purpose` for everyone); (2) `TASK_SYSTEM_PROMPT` (describe a meal, label,
  plate) is one fixed sentence with no profile data, and the `prepare_parse_meal` / `prepare_read_label` / `prepare_plate`
  signatures, `app/vision.py` and the docs rows are back to what they were; (3) merged `origin/main` (privacy tier 1, 5eb2867).
* Tests: `tests/test_ai_prompts.py` (three-profile snapshots `tests/fixtures/ai/prompts_*.txt`; a test that a profile changes
  nothing but the condition sentence and that the low rules and the hypo note are byte-identical across the three profiles; the
  task prompt has no profile data; whitelist; fingerprint pin for `2026-10-15.3`), `tests/test_ai_profile_prompts.py` (dry runs of
  all five features for three profiles, no identity, a low and an emergency still answered without a model), golden cases
  `tests/ai_golden/kidney-only-*.json` (one per feature), `scripts/ai_eval.py` `chat-kidney-only-*` questions and
  `tests/test_ai_eval_script.py`.
* Docs: `docs/ai.md` (section "The instructions follow your profile", the re-run command), `docs/privacy.md`,
  `docs/dev/ai-eval/README.md`, `CHANGELOG.md`, `docs/ROADMAP.md`, `ARCHITECTURE.md`, handbook `app/ai.md` ("what is sent" row).

## Decisions

* Nothing about treating a low depends on the profile (CLAUDE.md: never block or warn against hypoglycaemia treatment; a person
  with "None" can still have a low or log for someone who does). The code is untouched: `hypo.prefilter`, `features.red_flag`,
  `safety_check`, the answer checks in `chat.py`, the guard.
* "Not chosen yet" says not to assume either way; "None" says kidney disease only.
* Least data: describe a meal and photos send no profile data.

## Next

* Owner: the live golden run for `2026-10-15.3` (command in `docs/ai.md`, "Re-run the golden set after a prompt change").
* Not done on purpose: the plate photo banner (`features.PLATE_BANNER`, "do not dose insulin from this alone") is screen copy,
  not a prompt, and is shown to everyone; the handbook framing and the app's one-line description stay the owner's.

## Reproduce

    python -m pytest -q -p no:cacheprovider tests/test_ai_prompts.py tests/test_ai_profile_prompts.py tests/test_ai_golden.py tests/test_ai_eval_script.py
    KH_UPDATE_SNAPSHOTS=1 python -m pytest tests/test_ai_prompts.py   # only after reviewing a prompt change (an unreleased version's pin must be removed first)
