Status: complete

Base: current main 84330f3 (#119), all remote branches refreshed. Claude's branch has no Plan
changes. Own branch fix/recipe-fit-unknown-nutrients; no PR/deployment.

Roadmap review: swap ideas show prose/food portions rather than misleading numeric totals. Fit to
my targets still prints exact `used` values, including 0 when none of the foods lists that nutrient.
Its footnote only says "at least" and does not mark the affected row. The carbohydrate confirmation
also omits missing/partial qualifiers. Keep numeric engine/API behavior unchanged; fix presentation.

Fix: format each check with that stage's missing-data flags. Missing amounts say not listed; partial
amounts say ≥; known zero stays 0. Show before/after changes when completeness changes even if the
numeric subtotal is equal. The Replace confirmation uses the same qualifiers. Footnote covers both
before and after. Swap-row review found portions/prose, not a numeric nutrient-total row.

Validation: 8 Node cases pass (6 failed on the baseline, with calls adapted to the old row signature).
Focused pytest: 635 passed, existing unused-handbook-sources warning only. Chromium reliability:
20 passed, including three new actual API-to-Fit-sheet cases: missing, partial and known-zero potassium.
Report: /tmp/kidney-recipe-fit-unknown-20261029/report.json. Node parity vectors, Ruff, JavaScript
syntax, demo build and git diff --check pass. Engine decisions, API values and data are unchanged.

Ready on fix/recipe-fit-unknown-nutrients for Claude to review/cherry-pick. No PR/deployment.
