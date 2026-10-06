Status: complete

# Handbook fact-check: labs/

Role: adversarial clinical fact-checker for `handbook/docs/labs/*` (11 pages). Task says: do not
git commit. Owned: `handbook/**`, `scripts/build_handbook.py`, `tests/test_handbook_content.py`.

Scratch: `/tmp/claude-0/-home-user-kidney-health/8a6bc573-c86c-5a92-a072-0545790bf9a4/scratchpad/handbook/`
(source texts in `pdf/`: k24.txt, k22.txt, k26a.txt, k17.txt, hc24.txt, ker.txt, nhsk.txt; root:
q20.txt (KDOQI 2020 public-review draft), q19va.txt, jbds.txt, g7ug.txt; venv in `venv/`).
ADA 2026 sections: WebFetch on pmc.ncbi.nlm.nih.gov/articles/PMC12690176/ (§11), PMC12690178 (§6)
works (Europe PMC REST returns 500). AJKD full text (KDOQI 2020 published) is 403.

## Verified so far (no change needed unless listed under "Fixes to apply")

- K24: PP 2.1.1–2.1.5, Rec 3.6.1–3.6.4, PP 3.6.1–3.6.7, PP 3.10.1–3.10.2, bicarbonate prevalence
  7.7 %/38.3 %, BiCARB as KDIGO describes it (G3–G4, age ≥ 60, < 22), Tables 8, 9, 11, 16, 23–28,
  Fig 30–33, PP 3.11.5.1–2, PP 1.2.2.4 meat meal (0.23 mg/dL, 2–4 h, 12 h), PP 1.2.2.6 (cr-cys more
  accurate), PP 1.2.4.2 (race), PP 1.3.1.1–1.3.1.3, PP 4.2.1, conversion factors 88.4 / 0.113.
- K26A: anaemia definition, > 50 % at G4–G5, Fig 5 (G3 yearly, G4 twice, G5/G5D 3-monthly), Rec
  2.1–2.4, PP 1.2.1, 1.2.3, 2.2, 2.5, 2.7–2.9, 3.1.1–3.1.2, Fig 8, Rec 3.2.1–3.3.1, PP 3.4.3.2–3, 4.2,
  4.4; iron deficiency definitions; post-transplant causes (MMF, ACEi/ARB).
- K22: Rec 2.1.1, 2.2.1, PP 2.1.1–2.1.6, 2.2.2, Fig 10, 11; GMI vs A1c difference; glycated albumin
  and fructosamine biases with hypoalbuminaemia (proteinuria, PD); CGM alarms.
- K17: 3.1.1–3.1.5, 3.3.2, 4.1.3, 4.1.8, 4.1.9, 4.2.1–4.2.5.
- ADA 2026 §11: 11.1a, 11.1b, UACR variability, factors, creatinine up to 30 %, GA/fructosamine
  "helpful". §6: 6.2, 6.3a–c (6.3c: < 1 % for older adults), 10–14 days ≥ 70 % wear (text, Table
  6.2, not 6.3b–c), fructosamine 2–4 weeks, A1c unreliable list.
- CKD-EPI 2021 examples recomputed: F60 1.4 = 43.1; M60 1.4 = 57.5 (page says 57; should be 58);
  F30 1.0 = 77.7; F75 1.0 = 58.8.

## Fixes to apply (collected; apply in one pass)

1. egfr: "how much blood your kidneys filter" -> fluid filtered from the blood (as glossary fix).
2. egfr + index: man 60 example eGFR 57 -> 58.
3. index: pregnancy claim cites PP 1.2.4.3 (children only) -> needs other source.
4. haemoglobin: iron infusion reaction with chest tightness in "call today" -> split; breathing
   trouble/swelling/fainting = 911; K26A says no severe delayed reaction expected.
5. cgm: 14 days/70 % wear cite ADA text/Table 6.2 not recs 6.3b–c.
6. uacr: "Sodium under 2,000 mg (KDIGO; KDOQI)" - KDOQI is < 2,300 (6.5.1/6.5.2).
7. phosphate: "binders ... every time you eat, meals and snacks" -> "as prescribed".

8. bicarbonate: Nora example (HD, vomiting, ketones 2.1 -> "calls team") contradicts sick-days
   (ketones >= 1.6 + vomiting -> ED/911). HIGH. Also warning box mixes vomiting into "call today".
9. a1c: JBDS 2016 7.5–8.5 % row superseded by JBDS-IP 2022 (no A1c goal; use with caution; > 80
   mmol/mol likely poor control unless severe iron deficiency). GA research -> JBDS22 2.3. diaTribe
   "clinic adjusts insulin from TIR" unverifiable (403) -> K22 PP 2.2.2 / JBDS22 2.6.
10. cgm: Dexcom G7 + Libre Plus labels say "Don't use if you are on dialysis" (page said only "not
   evaluated"); HD glucose nadir 3rd hour, 75 % of lows within 24 h (JBDS22); sensor-start on
   non-dialysis day is 2016 calibration advice; add Eversense mannitol/sorbitol (PD) and vitamin C
   > 1,000 mg (Libre Plus) from ADA §7 Table 7.4; JBDS22 6–12 mmol/L dialysis range (clinician item).
11. albumin: ALB18 is 506 (331 BCP + 175 BCG, different centres) not 521, not same blood; "cannot
   eat or drink for a day" in "call today" conflicts with sick-days 911 (no liquids > 4 h).
12. dialysis-adequacy: CFR 494.90 PD Kt/V >= 1.7 (US); Rosa 1.6 example; access bleed 911 cite
   AKF-bleed; Table 41 = initiation; DOPPS: skipping (not shortening) linked to death.
13. "On dialysis, blood is taken before the session (KDOQI 2020)" not in Q20 -> drop/recite (3 pages).
14. CFR 494.90: Hb and albumin at least monthly at US dialysis units (index, haemoglobin, albumin).
15. haemoglobin: chest tightness after iron in "call today" -> split.
16. egfr: SGLT2 not approved T1D note; NIDDK "15 or less" vs G5 "< 15"; Table 8 list items not in
   Table 8 (very low weight, frailty) -> trim.
17. index: 911 symptoms cite MEDLINE-K, not Table 28.
18. uacr: "under 30 normal (NIDDK)" NIDDK says "30 or less"; cite K24.
19. phosphate: calcium "about 8.5" lower bound unsourced -> MedlinePlus range.

## Applied (2026-10-06)

All fixes 1–19 above applied to the 11 labs pages; `fact_checked: 2026-10-05` on all 11;
`sources.yml`: ALB18 note corrected, new BICARB20, CFR494 note extended (494.90 a1/a2/a4), JBDS 2016 note;
`scripts/build_handbook.py` regenerated includes/sources.md and reference/sources.md. REVIEW.md section
"Fact-check: labs/ (2026-10-05)" appended (high 1, medium 6, low 27). Helper: scratch `fcl/rep.py`
(exact once-only replacements) with pair files `fcl/*.py`.

## Old next list (done)

ADA §7 (sensor interferences) and §15 (preconception A1c), JBDS (A1c 58–68, dialysis CGM text),
Kerendia label (eGFR dip, K checks, FINE-ONE UACR 22 %/28 %), Foley 2011, DOPPS, KDOQI 2015 HD,
ISPD 2020, Q19VA Kt/V drop 0.2, NIDDK pages, MedlinePlus, DaVita PD calories, Dexcom/Libre
dialysis statements, NHS DKA, note 05 app behaviour; contradictions with other handbook pages.

## Verification (2026-10-06)

- `python scripts/build_handbook.py --check`: up to date (24 files, 6 menus).
- `python -m pytest --noconftest tests/test_handbook_content.py`: 583 passed, 1 skipped.
- `cd handbook && mkdocs build --strict -d <scratch>/site-labs`: exit 0.
- Not committed (task instruction: do not git commit).
