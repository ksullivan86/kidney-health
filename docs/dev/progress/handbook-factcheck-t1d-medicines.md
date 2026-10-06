Status: complete

# Progress: handbook fact-check, t1d/ and medicines/

Completed 2026-10-06 (attempt 2).

Role: adversarial clinical fact-checker for `handbook/docs/t1d/` and `handbook/docs/medicines/`.
Owned paths: `handbook/**`, `scripts/build_handbook.py`, `tests/test_handbook_content.py`. Do not commit
(the orchestrator commits).

## Done
- Attempt 1 (transcript agent-ae2617e4172e80d8d.jsonl) verified sources and fixed in place, with
  `fact_checked: 2026-10-05` front matter: t1d/index.md, t1d/treating-a-low.md, t1d/sick-days.md,
  t1d/insulin-and-dialysis.md, t1d/kidney-protecting-medicines.md (committed by orchestrator in 4b4a4de).
  The list of edits is recoverable with `git show 4b4a4de -- handbook/docs/t1d`.

- Attempt 2: verified ADA 2026 §11 text: ACEi, ARB, MRA, SGLT2i "contraindicated" in pregnancy
  (rec 11.10, grade B) -> kidney-protecting-medicines.md pregnancy box is correct.
- Attempt 2 verified for medicines/: KDIGO 2024 ch.4 text (PP 4.1.x-4.4.2.1, Tables 25, 26, 31, 32,
  33; rationale: "most reported problem is failure to restart", "medication review within a month",
  ">=48 h RAASi hold before elective CT", "NAC/ascorbic acid not consistent benefit", "prophylactic
  pericontrast HD potentially harmful", NSF "not reported later than 2012"); NKF herbal page (list incl.
  java tea, Oregon grape, parsley root, pennyroyal, rue; no magnesium); AKF herbal list; NKF stages 1-5
  page ("OTC vitamin and mineral supplements may contain too much phosphorous and potassium"); NKF pain
  page; NIDDK managing CKD; FDA 2014 NaP DSC (via search); FDA 2024 phenylephrine proposed order (still
  proposed); DailyMed Sudafed/Sudafed PE drug facts; Dexcom G7 guide (CT: out of field + lead apron);
  Prograf Table 15 (St John's wort -> rejection); ISPD 2022 (colonoscopy antibiotics 2C, drain 2D);
  AHRQ 10 questions; ACR-NKF 2020/2021 abstracts.

## In progress / next
1. (done) ADA pregnancy wording.
2. Fact-check and fix medicines/avoid.md, supplements.md, scans-and-contrast.md, your-medicine-list.md.
3. Append "Fact-check: t1d/ and medicines/" section to handbook/REVIEW.md.
4. Run strict build and content tests (commands below).

## Commands
- venv: /tmp/claude-0/-home-user-kidney-health/8a6bc573-c86c-5a92-a072-0545790bf9a4/scratchpad/handbook/venv
- `python scripts/build_handbook.py` / `mkdocs build --strict -f handbook/mkdocs.yml`
- `python -m pytest tests/test_handbook_content.py -q`

## Update (attempt 2)
- Fixed medicines/avoid.md, supplements.md, scans-and-contrast.md, your-medicine-list.md (+ fact_checked);
  small follow-ups on t1d/insulin-and-dialysis.md (ISPD drain, PD/transplant get-help citations) and
  t1d/treating-a-low.md (fat/protein reason cited).
- Added sources NKF-NUT15, FDA-PE, DECONGEST-LABELS to handbook/sources.yml; ran build_handbook.py.
- mkdocs build --strict: OK. pytest tests/test_handbook_content.py (system python3; venv lacks httpx2
  for conftest): pass.
- Next: append REVIEW.md section "Fact-check: t1d/ and medicines/" (append-only; other agents edit it).

## Final
- REVIEW.md section "Fact-check: t1d/ and medicines/ (2026-10-05)" appended: high 1, medium 9, low 34;
  10 clinician items.
- Final checks: build_handbook.py --check up to date; mkdocs build --strict OK;
  python3 -m pytest tests/test_handbook_content.py -> 583 passed, 1 skipped, 1 warning (unused sources).
