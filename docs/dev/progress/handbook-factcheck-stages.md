Status: complete

# Handbook fact-check: stages/

Role: adversarial clinical fact-checker for `handbook/docs/stages/*` (index, G1–G2, G3a, G3b, G4,
G5 without dialysis, in-centre HD, home HD, PD, before and after transplant). The task says not to
git commit. Owns only `handbook/**`, `scripts/build_handbook.py` and `tests/test_handbook_content.py`.

## Done (verified)

- Read all 11 stage pages, spec 08 §4.9/§5.3/§5.13, the ARCHITECTURE v0.3 contract and the
  research inputs.
- Primary texts are in the scratchpad (`handbook/pdf/*.txt`, `handbook/*.txt`, `handbook/stages-src/dl/`):
  - KDIGO 2024, 2022, 2017, 2026 anaemia, 2020 and 2009 transplant;
  - KDOQI 2015 HD adequacy and 2019 VA;
  - JBDS 2016 and 2022;
  - labels: Kerendia, Prograf, CellCept;
  - FSTX and CMS emergency guide;
  - read with WebFetch: ADA 2026 §6/§9/§11, NIDDK, NKF, DaVita, AKF, Medicare, OPTN and ISPD;
  - abstracts (Europe PMC): Foley, DOPPS and Cabrera;
  - USDA SR Legacy (local CSV).
- Fixes applied: 1 high, 2 medium and 27 low. Every stage page has `fact_checked: 2026-10-05`.
- Findings and clinician items were appended to `handbook/REVIEW.md` under
  "Fact-check: stages/ (2026-10-05)".
- Checks run, all green:
  - `scripts/build_handbook.py --check` (up to date);
  - `mkdocs build --strict` (venv `scratchpad/handbook/venv`);
  - `python3 -m pytest tests/test_handbook_content.py`: 583 passed, 1 skipped.

## Reproduce

    V=<scratchpad>/handbook/venv/bin
    $V/python scripts/build_handbook.py --check
    (cd handbook && $V/mkdocs build --strict -d <scratchpad>/handbook/site-stages)
    python3 -m pytest -q tests/test_handbook_content.py
