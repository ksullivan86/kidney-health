Status: in progress (started 2026-10-06; second attempt resumed 2026-10-06 after a usage limit)

# Handbook fact-check: prepare/ and living/

Role: adversarial clinical fact-checker for `handbook/docs/prepare/**` (4 pages) and
`handbook/docs/living/**` (9 pages). Owned paths: `handbook/docs/prepare`, `handbook/docs/living`,
`handbook/REVIEW.md`, `handbook/sources.yml`, this note. Commit only those with
`git commit -- <paths>` and push; WIP messages end with " [skip ci]".

Scratch: `/tmp/claude-0/-home-user-kidney-health/8a6bc573-c86c-5a92-a072-0545790bf9a4/scratchpad/v030/factcheck-prepare-living/`
(`src/` = fetched source texts, `tools/fetch.sh name url` fetches and converts). Primary-source PDFs
fetched earlier by the page writer are reused read-only from `.../scratchpad/handbook/`
(q19va.txt = KDOQI 2019 VA, k20tx.txt, k09tx.txt, k24.txt, cellcept_pi.txt, cellcept_letter.txt,
cmsprep.txt, g7ug.txt, txfood.txt, dl/ex17/ex17.txt, dl/ukka/u.txt, dl/unos/ml.txt, dl/cfr494/*.txt);
identity of each was checked from its first page. Handbook venv:
`.../scratchpad/handbook/venv` (the first attempt's note named a `v030/hbvenv` that does not exist).

## Done

- Attempt 1: read spec (note 08 §4.9, §5.8–5.9, F9) and REVIEW.md format; read the pages (no edits).
- Attempt 2: re-read all 13 pages; fetched fresh (2026-10-06): Medicare ESRD, KDE, insulin, ACP,
  travel, MSP; CMS 2026 fact sheet; AKF HIPP; Kidney Care UK grants; EEOC diabetes; JAN dialysis;
  NKF travel, HD access (updated 2026-08-20), home HD, exercise, pregnancy, PEERS, transplant;
  AKF bleeds; 988; POLST; AHRQ; NIDDK HD, PD, transplant, choosing, conservative, hypo, managing.
  Blocked by 403 from curl: dol.gov (FMLA), ssa.gov, tsa.gov, optn PDF -> use WebFetch.
  Europe PMC / efetch give no ADA full text -> use WebFetch on pmc.ncbi.nlm.nih.gov.

## Findings so far (to apply)

- CMS 2026 amounts all confirmed ($202.90, $283, $1,736, B-ID $121.60; B-ID deductible $283 then 20 %).
- Medicare ESRD: B-ID needs Medicare (ESRD) at the time of transplant; home-training start needs
  the doctor to expect you to finish training and a regular course of dialysis.
- Kidney Care UK: under-18s can apply through an adult or guardian (page says "over 18").
- EEOC: accommodation can be requested during hiring too (page: "after you are hired").
- NKF HD access 2026: catheter fever/chills/redness -> call "right away" (page: "same day");
  never a BP cuff on the access arm (page groups it with "unless your team says").
- NKF home HD: training "several weeks to a few months" (choosing page says 3–8 weeks; check NIDDK).
- NKF travel: tell the transplant coordinator before travel if listed (missing on travel page).

## Next

1. Verify remaining sources (KDOQI VA, KDIGO Tx 2020/2009, K24, OPTN, UNOS, ADA §5/§6/§9/§15,
   AASM, EX17, UKKA, CellCept/REMS letter, CFR 494, FDA insulin, TSA, Dexcom G7, CMSPREP, FSTX,
   glucagon kit, NIDDK pages, NKF pregnancy/Tx/PEERS, 988, POLST, AHRQ, SSA, FMLA).
2. Fix pages, add `fact_checked: 2026-10-06` after `last_checked`.
3. Append REVIEW.md section + update index; run checks; commit.

## Checks to run

```
V=/tmp/claude-0/-home-user-kidney-health/8a6bc573-c86c-5a92-a072-0545790bf9a4/scratchpad/handbook/venv
W=/tmp/claude-0/-home-user-kidney-health/8a6bc573-c86c-5a92-a072-0545790bf9a4/scratchpad/v030/factcheck-prepare-living
cd /home/user/kidney-health && $V/bin/mkdocs build --strict -f handbook/mkdocs.yml -d $W/site
$V/bin/python scripts/build_handbook.py --check
python3 -m pytest -q tests/test_handbook_content.py
```
