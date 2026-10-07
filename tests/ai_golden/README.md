# AI golden set (note 04 R11.1)

Each `*.json` file is one offline case run by `tests/test_ai_golden.py` through the real routes with a
stub provider that replays `model_outputs` (no network). The file name is the case `id`.

* `category`: one of `grounding`, `rules`, `safety_text`, `refusal`, `prefilter`, `injection`, `format`,
  `privacy`, `fallback`, `modes`, `vision` (the test checks every category has cases and that there are
  at least 40).
* `fixture`: the person's profile and targets (`stage4`, `hd`, `tight` or an object), log entries
  (`[meal, food name, servings, status?, purpose?]`), earlier days (`history`), custom foods (theirs and
  another person's), AI and guidance settings, the meal and mode, the text (parse-meal) or the image
  (`tests/fixtures/ai/images/`).
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
