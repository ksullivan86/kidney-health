Status: in progress (started 2026-10-06)

# Handbook fact-check: prepare/ and living/

Role: adversarial clinical fact-checker for `handbook/docs/prepare/**` (4 pages) and
`handbook/docs/living/**` (9 pages). Owned paths: `handbook/docs/prepare`, `handbook/docs/living`,
`handbook/REVIEW.md`, `handbook/sources.yml`, this note. Commit only those with
`git commit -- <paths>` and push.

Scratch: `/tmp/claude-0/-home-user-kidney-health/8a6bc573-c86c-5a92-a072-0545790bf9a4/scratchpad/v030/factcheck-prepare-living/`
(fetched source texts in `src/`). Handbook venv: `.../scratchpad/v030/hbvenv`.

## Done

- Read spec (note 08 §4.9, §5.8–5.9, F9), REVIEW.md format.

## In progress / next

1. Read all 13 pages; list every checkable claim.
2. Fetch sources and verify (Medicare 2026 amounts, KDOQI VA, KDIGO Tx, OPTN, AASM 2024, ADA §5/§15,
   UKKA pregnancy, TSA, FMLA, EEOC, SSA, HIPP, 988 …).
3. Fix pages, add `fact_checked: 2026-10-06` after `last_checked`.
4. Append REVIEW.md section + update index; run checks; commit.

## Checks to run

```
V=/tmp/claude-0/-home-user-kidney-health/8a6bc573-c86c-5a92-a072-0545790bf9a4/scratchpad/v030/hbvenv
cd /home/user/kidney-health && $V/bin/mkdocs build --strict -f handbook/mkdocs.yml -d <scratch>/site
$V/bin/python scripts/build_handbook.py --check
python3 -m pytest -q tests/test_handbook_content.py
```
