Status: complete

# Handbook fact-check: app/ and self-hosting/

Role: adversarial clinical fact-checker for `handbook/docs/app/*` (12 pages) and
`handbook/docs/self-hosting/*` (13 pages). Task says: do not git commit. Owned: `handbook/**`,
`scripts/build_handbook.py`, `tests/test_handbook_content.py`.

Previous attempt (agent-ad7ce01d50f4bbef8) was cut off before doing anything. Started fresh 2026-10-06.

Scratch: `/tmp/claude-0/-home-user-kidney-health/8a6bc573-c86c-5a92-a072-0545790bf9a4/scratchpad/handbook/`
(source texts: k24.txt, pdf/k22.txt, pdf/k26a.txt, pdf/a12690176.txt (ADA §11), pdf/a12690178.txt (ADA §6), venv/).

## Done

- Read all 12 app/ and 13 self-hosting/ pages, ARCHITECTURE v0.3, notes 05/06/04/07 (relevant parts),
  app/nutrients.py, data/foods.json, deploy/quadlet + k8s (read-only).
- Verified (no change): food example values vs foods.json; thresholds vs app/nutrients.py; KDIGO 2024
  Table 28 (k24.txt); ADA 2026 Rec 11.3 (0.8 g/kg, A; "below 0.8 not recommended"), Rec 5.24 (fibre
  14 g/1000 kcal, B), Rec 5.28 (consistent carbs, B) via WebFetch PMC12690176/PMC12690188; KDOQI 2020
  published numbering energy 3.1.1; NIST 63B-4 §3.1.1.2; NKF "200 mg or more"; OFF 15 product
  reads/min; K8s userns stable 1.36; Talos 1.13 kubeNetworkPoliciesEnabled; LE 64 d 2027-02-10, 45 d
  2028-02-16; note 06 budget maths (example 800/300/600); note 05 K and P ladders.

## Findings to apply (collected)

1. MED first-setup + targets-and-warnings: protein 0.8 g/kg at G3-5 with diabetes shown as current;
   v0.2 app (app/nutrients.py) still suggests 0.6-0.8 (42-56 g). Mark v0.3; tell reader not below 0.8.
2. MED first-setup: "no starting targets if pregnant/<18/<12 wk transplant" presented as current; v0.2
   has no such check. Mark v0.3 + "until then do not use Suggest targets".
3. MED targets-and-warnings: K 6.0-6.4 box says "repeat within 24 h, or care in hospital if unwell";
   align with eat/potassium + labs: unwell -> hospital now.
4. LOW: emergency symptom list cited only to K24 Table 28 (no symptoms there) -> add MEDLINE-K + fainting
   (first-setup, targets-and-warnings).
5. LOW: NKF high = 200 mg or more; app high = over 200 -> wording.
6. LOW guidance: per-meal 30 %/15 % cap applies to K, P, Na (not fluid).
7. LOW privacy: "cannot become you" vs note 07 N12 (reset link lets admin sign in as you, not quietly).
8. LOW barcode: OFF "a few lookups per minute" -> 15 per minute per IP.
9. LOW logging: low treatment without threshold -> add < 70 mg/dL (3.9 mmol/L).
10. LOW index: "juice you log as a low treatment" -> foods marked as low treatments (v0.2 flag is per food).
11. LOW targets-and-warnings: nutrition-risk list omits low BMI; glucose gel "the lowest-potassium" -> zero.
12. LOW reports: CSV escaping applies to any text cell (names, notes), also tab/newline; cite ARCH.

## Applied (2026-10-06)

- All 16 findings fixed in place (3 medium, 13 low; self-hosting: none), `fact_checked: 2026-10-05`
  added to all 25 pages, REVIEW.md section "Fact-check: app/ and self-hosting/" appended (findings,
  checked list, notes for M2/M3, 5 clinician items).
- Regenerated handbook/includes/sources.md and reference/sources.md (stale from the t1d/medicines
  agent's concurrent sources.yml edit; derived files only).
- Verified: `mkdocs build --strict` OK (scratch site-appsh-fc); `pytest --noconftest
  tests/test_handbook_content.py`: 583 passed, 1 skipped.

## Reproduce

    S=/tmp/claude-0/-home-user-kidney-health/8a6bc573-c86c-5a92-a072-0545790bf9a4/scratchpad/handbook
    cd handbook && NO_MKDOCS_2_WARNING=true $S/venv/bin/mkdocs build --strict -d $S/site-appsh-fc
    cd .. && $S/venv/bin/python -m pytest --noconftest -p no:cacheprovider tests/test_handbook_content.py

