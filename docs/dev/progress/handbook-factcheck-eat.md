Status: done (2026-10-06)

# Handbook fact-check: eat/

Role: adversarial clinical fact-checker for `handbook/docs/eat/**` (nutrient pages, label reading,
leaching, eating out, grocery shopping, menus, recipes from `handbook/data/recipes.yml`). Do not git
commit. Owned: `handbook/**`, `scripts/build_handbook.py`, `tests/test_handbook_content.py`.
Tasks #68–#70.

Scratch: `/tmp/claude-0/-home-user-kidney-health/8a6bc573-c86c-5a92-a072-0545790bf9a4/scratchpad/handbook/`
(source texts in `pdf/`, USDA SR Legacy pickle in `eat/sr_eat.pkl`, venv in `venv/`).

## Verified so far

- K24 text: 36 weeks sodium RCTs; PP 3.3.1.1–3.3.1.5, 3.3.2 ("individual needs"); 3.11.5.1–2; Table 28; Fig 30
  (8.8 % G3A1 -> 34.4 % G5A3); Fig 33; "absorbable potassium" quote; hot-soak quote. No "90 % excreted" in K24.
- K22: 0.8 g/kg; low protein -> malnutrition and hypoglycaemia; Rec 3.1.2 sodium; PP 3.1.1 quote.
- ADA 2026 §5: 5.18 alcohol limits, 5.19 delayed hypo, 5.24 fibre, 5.27–5.28; §11: 11.3 + >1.3 text.
- JBDS 2016: last hour; 20–30 g if < 7; 10–20 g 2nd hour; big meal -> hypotension h3–4; IDWG < 2 kg; gastroparesis.
  JBDS 2022: nadir third hour; 75 % lows within 24 h.
- FDA: 20-oz soda / 15-oz soup labelled as ONE serving (serving-size rule). Menu labeling list. Sodium page quotes.
- NKF potassium: exact quote "A large amount of a low-potassium food can easily turn it into a high-potassium
  food"; 200 mg; soak steps; no 130 mg figure; lists "salt substitutes / lite salt" only.
- NKF phosphorus: range, deposits quote, binders quote, PHOS list. Not salt substitutes.
- NKF label guide: 240 mg / Na < kcal / 200 mg K; no "double" statement. NKF HD diet: 1–2 L, < 2,300.
- NKF dining: 4–6 oz lunch, 6–8 oz dinner; > 3 times a week. NKFherb: creatine. NKF milk alts: Oatly phosphate.
- AKF fluids: definition, pudding listed; G1–2 ~64 oz; G3–5 "may need to limit".
- Bethke 2008, de Abreu 2023, Sherman 2009, León 2013 abstracts: all numbers match. Sullivan 2007: databases
  under-count additive P (PMID 17720105).
- DaVita double-cook 50–72 %. Medtronic: subtract half of sugar alcohols (no erythritol statement).
- NoSalt 640 mg K / 1/4 tsp (retailer label, warns diabetes/kidney disease); Nu-Salt 530 mg/serving.
- App thresholds (app/nutrients.py) and note 05 lab rules match the pages. Food numbers spot-checked vs
  data/foods.json (swap tables, day totals, burger, soup, label example all re-summed OK).

## Fixes to apply

1. HIGH carb-counting + label-reading: "20-oz soda is 2.5 servings" -> labelled as 1 serving (FDA).
2. eating-out: "rescue is never a cola" -> never delay; regular soda is fine.
3. carb-counting call-today: unsourced 250 mg/dL 2 h -> get-help-now wording + ADA 1.6 ED.
4. Misquote NKF (potassium, index, portions). 130 mg leached attribution (potassium-leaching, food-lists?).
5. potassium: 90 % kidneys unsourced; range 3.5–5.0 -> about 3.5–5.1 (MEDLINE-LOWK); 6.0–6.4 unwell -> hospital now.
6. Lite Salt is a mix: "contain potassium chloride" (potassium, sodium, recipes index, menus.yml).
7. sodium: NoSalt/Nu-Salt cited to DG20 -> new source SALTSUB-LABELS; NIDDK/NKF/AKF herbs claim.
8. fluid: "the best way" -> one of the best; 4 oz juice 110 -> 120 mL; sherbet volume vs water note + example.
9. dialysis-days: JBDS22 timing; access bleed heavy/spurting/starts again; add DKA line.
10. carb-counting: erythritol unsupported; "expect" -> may; "insulin from TIR not A1c" overstated.
11. phosphorus: binders wording; "every database" -> Sullivan 2007; mac & cheese 222 vs 442 note; any-phos -> NKF.
12. menus/index + eating-enough: 1 oz less meat = ~9 g protein, 65 mg P (not 12/90); 80 kg 530 kcal under.
13. peach crisp "lower per serving" wording; portions doubling cite; potassium "since 2020" -> 2020–2021.
14. fact_checked on all eat pages incl. generated (menus.yml/recipes.yml + build script).

## Next

## Fixes applied (as of this note)

Done: 1 (carb-counting, label-reading), 2 (eating-out), 3, 5, 6 (potassium, sodium), 7, 8, 9, 10; new
sources SALTSUB-LABELS and SULLIVAN07 appended to sources.yml; FDA-label note extended (serving rule).
Remaining: 4 (index, portions, leaching), 6 (recipes index, menus.yml), 11, 12, 13, 14, other pages'
fact_checked lines, REVIEW.md section, build + tests.

## Done

All fixes applied (35 findings: high 1, medium 4, low 30), `fact_checked: 2026-10-05` on every eat/ page
(generated pages via `fact_checked` in menus.yml/recipes.yml and `with_fact_check` in
scripts/build_handbook.py). REVIEW.md section "Fact-check: eat/" appended. `mkdocs build --strict` OK;
`pytest tests/test_handbook_content.py`: 583 passed, 1 skipped.
