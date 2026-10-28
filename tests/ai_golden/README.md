# AI golden set (note 04 R11.1)

Each `*.json` file is one offline case run by `tests/test_ai_golden.py` through the real routes with a
stub provider that replays `model_outputs` (no network). The file name is the case `id`.

* `category`: one of `grounding`, `rules`, `safety_text`, `refusal`, `prefilter`, `injection`, `format`,
  `privacy`, `fallback`, `modes`, `vision`, `preferences`, `kidney_only` (a profile whose diabetes is "None": the prompts say kidney
  disease only; the owner re-runs these live after a prompt change), `lab_report` (the test checks every category has cases and
  that there are at least 40). A `lab_report` case has `feature: "lab_report"` and runs `POST /api/ai/read-lab-report` on a **local**
  stub provider (the only kind that feature may use); `expect.rows` is `[analyte, value, unit, taken_on or null]` per proposed
  row and `expect.dropped` the counts of lines the app left out. `scripts/ai_eval.py` skips these cases (it measures one,
  possibly cloud, provider). `preferences` (note 09, part C): what the optional AI is told about taste and how it is checked.
  Its meal ideas cases set `fixture.food_preferences` (`[food name, "like" | "less" | "not_for_me" | "neutral"]`) or the
  `guidance` setting's food groups and check the `person` block in the payload (`payload_includes`), the `liked` bit and the
  `you_like` claim (`idea_reason_codes_include` / `_exclude`, `claims_corrected`), that a food marked Not for me is never shown
  (`dropped_reasons_include: ["not_for_me"]`), and that a food the person wants less often is not the first idea
  (`not_first_food_names`: the app cannot order the model's ideas, so this is a recorded-good-answer check offline and a
  measured count, `taste_first_violations`, in `scripts/ai_eval.py`). Its `chat` cases (`feature: "chat"`, the person's
  `fixture.message`) run `POST /api/ai/chat`: "I don't really like salmon" ends in a `set_food_preference` card and
  `nothing_saved`; logging salmon or asking about it must not produce one. `scripts/ai_eval.py` skips the `chat` cases (the live
  questions are its `CHAT_SET`, `--chat`).
* `recipes` (note 16, phase 3): `feature: "recipes"` runs `POST /api/ai/recipes`. `fixture.dish` and `makes` (mode `suggest`),
  or `fixture.mode: "change"` with `fixture.recipe` (`name`, `servings_made`, `note`, `steps`, `source_url` and `items` as
  `[food name, servings]`), and `fixture.recipe_steps` for the admin switch. `expect.recipes` is the number of recipes shown,
  `title` the first one's, `steps_shown` its steps and `steps_dropped_include` the reasons of the steps the app removed.
  `scripts/ai_eval.py` runs these with the steps switch on.
* `fixture`: the person's profile and targets (`stage4`, `hd`, `tight` or an object), log entries
  (`[meal, food name, servings, status?, purpose?]`), earlier days (`history`), custom foods (theirs and
  another person's), the person's food preferences, AI and guidance settings, the meal and mode, the text (parse-meal), the
  message (chat) or the image (`tests/fixtures/ai/images/`).
* `model_outputs`: what the stub answers, in order: a content string, or an object with `content`,
  `finish_reason`, `refusal`, `reasoning_content` or an HTTP `status`. The stub fails the test when the
  app calls it more often than there are outputs; `expect.calls` (default 1) is the exact count, so
  pre-filter cases prove the model is never called.
* `expect`: see the docstring of `tests/test_ai_golden.py`.

Food ids differ between databases, so outputs name foods with placeholders that the stub resolves from
the request the app actually sent (`"{{id:Rice, white, long-grain, cooked}}"`, `"{{ref:Blueberries, raw}}"`).

**Change control (R11 step 5):** any change to `app/ai/prompts.py`, `app/ai/guard.py` or
`app/ai/schemas.py` bumps `PROMPT_VERSION`, needs this set green, and needs one live evaluation
(`scripts/ai_eval.py`) attached to the pull request.
