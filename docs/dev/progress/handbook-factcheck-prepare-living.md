Status: complete (2026-10-06)

# Handbook fact-check: prepare/ and living/

Role: adversarial clinical fact-checker for `handbook/docs/prepare/**` (4 pages) and
`handbook/docs/living/**` (9 pages). Owned paths: `handbook/docs/prepare`, `handbook/docs/living`,
`handbook/REVIEW.md`, `handbook/sources.yml`, this note. Commits use `git commit -- <paths>`; WIP
messages end with " [skip ci]".

Scratch: `/tmp/claude-0/-home-user-kidney-health/8a6bc573-c86c-5a92-a072-0545790bf9a4/scratchpad/v030/factcheck-prepare-living/`
(`src/` = source texts fetched 2026-10-06; `tools/fetch.sh name url` fetches and converts).
Primary-source PDFs fetched earlier by the page writer were reused read-only from
`.../scratchpad/handbook/` (q19va.txt, k20tx.txt, k09tx.txt, k24.txt, cellcept_pi.txt,
cellcept_letter.txt, cmsprep.txt, g7ug.txt, txfood.txt, dl/ex17/ex17.txt, dl/ukka/u.txt,
dl/unos/ml.txt, dl/cfr494/*.txt) after checking each one's first page. ADA 2026 §5/§9/§15 and AASM
2024 were read with WebFetch on pmc.ncbi.nlm.nih.gov (curl gets a captcha); DOL and TSA with WebFetch;
SSA listings from eCFR (20 CFR 404 Subpart P App. 1). Handbook venv: `.../scratchpad/handbook/venv`.

## Done

- Read the spec (note 08 §4.9, §5.8–5.9, F9), REVIEW.md format, all 13 pages and their sources.
- Verified every number, benefit amount, legal rule and cited recommendation (list in REVIEW.md,
  "Fact-check: prepare/ and living/ (2026-10-06)"). Counts: high 0, medium 4, low 31.
- Fixed the pages in place; `fact_checked: 2026-10-06` added after `last_checked` on all 13.
- REVIEW.md: new section (findings table, checked-and-correct list, notes for other owners, clinician
  items P1–P8) and the open-decisions index (legend **P**, items P1–P8, coverage line ticked, OPTN note).
- Commits: `WIP(handbook-factcheck-prepare-living): page corrections …` and the REVIEW/final commit.

## Decisions

- `sources.yml` left unchanged: the only candidate edit (OPTN URL now redirects to HRSA) would change
  the generated `includes/sources.md` and `reference/sources.md`, which this role may not commit; it
  is recorded as a note for the handbook owner. No new source ids were needed.
- Where a page disagreed with `get-help-now` (fever after a transplant; ketones with vomiting), the
  page was aligned to `get-help-now` and the wording choice listed for a clinician.
- An unsourced cause (nocturia "high glucose", cited to ADA §5 which does not cover it) was removed
  rather than re-sourced to a page that refuses automated checks (CDC).

## Checks (all passed on 2026-10-06 after the last edit)

```
V=/tmp/claude-0/-home-user-kidney-health/8a6bc573-c86c-5a92-a072-0545790bf9a4/scratchpad/handbook/venv
W=/tmp/claude-0/-home-user-kidney-health/8a6bc573-c86c-5a92-a072-0545790bf9a4/scratchpad/v030/factcheck-prepare-living
cd /home/user/kidney-health && $V/bin/mkdocs build --strict -f handbook/mkdocs.yml -d $W/site
$V/bin/python scripts/build_handbook.py --check
python3 -m pytest -q tests/test_handbook_content.py
python3 -m pytest -q
```

## Not verifiable here

- CDC DKA page (403 to automated requests; the wording comes from `get-help-now`).
- KDIGO 2015 supportive care conference: abstract only.
- OPTN policy 8.4.A read through OPTN policy notices and search results (the policy PDF host now
  redirects to hrsa.gov, which refuses automated requests).
