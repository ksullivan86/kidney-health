Status: complete

Base: verification branch f439498 (app snapshot 12523c2), equivalent to main 6fa43ab plus the
seven reviewed fixes. Fetched all branches; Claude 289c2b3 changes Scan/USDA/Ask/admin, not apply.
Own branch fix/recipe-apply-serving-preview in /workspace/kidney-health-apply-preview.
The batch's full pytest continues against its immutable separate checkout.

Usability improvement: the recipe card shows one serving, but Add to a day starts at Scale 1,
which previews AND logs the whole pot. This matches the old handbook but asks people to divide
manually. Change this sheet to ask for recipe servings (default 1), converting to the existing
API scale internally. Keep ordinary saved meals, third-party API callers and the demo API unchanged.
Preview ingredients/nutrients and request scale must agree, including fractional Makes and limits.

Implemented: recipe sheets ask Servings to add (default 1), preview that many shares and divide
the count by Makes for the API request. Ordinary saved meals retain Scale. Dynamic input maximum
respects both the existing sheet limit and the API's pot-scale maximum, including fractional Makes.
Labels/hints, ingredient amounts, nutrient amounts, request body and daily impact all use that count.

Validation: 10 real-sheet Node cases pass. Focused pytest: 699 passed, existing handbook warning
only, including three API cases proving omitted/0.5/0.25 scale still means whole/half/quarter pot.
Chromium reliability: 42 passed, with one/two recipe servings compared to actual stored entries,
failed apply preserving count/date, nothing stored after failure, identical retry body, and exactly
one serving logged once. Report /tmp/kidney-recipe-apply-servings-20261029/report.json.
Node parity, JavaScript syntax, demo build, Ruff and diff checks pass. Handbook generated files
are current; strict build passed with 120 pages, 14803 internal links, 0 broken, 312 external URLs.
The base was advanced to a557970 for its completed verification note only; app code was unchanged.
Ready on fix/recipe-apply-serving-preview. No PR, deployment or environment publication.
