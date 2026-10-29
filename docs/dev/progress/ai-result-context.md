Status: complete

Base: main bf7436b. Fetched all branches; Claude's latest known branch 10289d8 changes nutrientLine
in ai.js but does not change mountIdeas/openRecipes. This fix does not edit their nutrient formatting.

Reproduced with the entire real AI UI module: a breakfast reply after setMeal('dinner') is labelled
Dinner and Add to plan sends dinner, although the request was checked for breakfast. Date changes,
late errors, competing Other ideas/Ask requests, and recipe-input changes also keep stale results.
Seven of eight Node cases fail on unchanged main; unchanged-context Add still works.

Fix: per-widget generations invalidate stale success/error/busy states on a new request or reset.
Rendered actions get a snapshot of the meal/date sent with that request. Consent and clinical rules
are unchanged; a request already sent is not cancelled and may still count as an AI call.
Validation: `python -m pytest tests/test_ai_context.py tests/test_other_choices_ui.py tests/test_recipes_ui.py
tests/test_ai_guard_twin.py tests/test_e2e_tools.py tests/test_handbook_content.py`: 638 passed,
one existing unused-sources warning. Eight Node cases pass with the fix.
Chromium recipes/ideas walk at 375 light and 1280 dark: 40 passed, zero failed
(/tmp/kidney-ai-context-20261029/report.json). The added controlled requests send no AI or log writes;
they verify stale breakfast cards stay gone and a fresh dinner answer still renders/plans dinner.
Ruff, parity, syntax, demo build and git diff --check passed. No PR/deployment.
Full suite was run on the prior health-loading branch; not repeated for this isolated frontend fix.
