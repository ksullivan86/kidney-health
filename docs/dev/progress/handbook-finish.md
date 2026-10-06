Status: complete

# Progress: handbook finisher

Role: make the whole handbook site coherent (numbers, terms, nav, glossary, cross-links, draft
banner), build --strict, `scripts/build_handbook.py --check`, `tests/test_handbook_content.py`,
internal link check over built HTML, screenshots + extra.css fixes, handbook/README.md, REVIEW.md
open decisions. Owned: `handbook/**`, `scripts/build_handbook.py`, `tests/test_handbook_content.py`.
Do not git commit (orchestrator commits). Do not fact-check prepare/ and living/ (skipped this run).

Scratch: /tmp/claude-0/-home-user-kidney-health/8a6bc573-c86c-5a92-a072-0545790bf9a4/scratchpad/handbook/

Previous attempt (agent-a69daa5fa10aa60ff) hit the usage limit before doing anything. Started fresh
2026-10-06 08:55 UTC. All six fact-check progress notes say complete.

## Done

- Baseline (09:00 UTC): `build_handbook.py --check` OK (24 generated files, 6 menus); `mkdocs build
  --strict` OK (~57 s); `pytest tests/test_handbook_content.py` all pass (1 skip: app/guidance/topics.py
  not written yet; warning: 6 unused DG ids); link checker: 119 pages, 14476 internal links, 0 broken,
  0 bad anchors.

- Consistency sweep, numbers: hypo rule of 15 (70/54 mg/dL, 3.9/3.0 mmol/L, 15 g, recheck 15 min),
  blood K action levels (6.0-6.4 call today / >= 6.5 call 911; normal 3.5-5.1), sodium < 2,000 mg,
  protein 0.8 g/kg (dialysis 1.0-1.2), phosphate 2.5-4.5 mg/dL, bicarbonate 22/18, Hb 13/12, A1c
  goals: all consistent across sections. Fixed living/appointments "6.5 or more" -> "6.5 mmol/L".
- US spelling normalised in prose (script $S/tools/usspell.py; protects quotes, ref-link text,
  link targets, slugs/file names): haemoglobin, anaemia, centre, in-centre, fibre, diarrhoea, etc.
  ~270 replacements in 54 pages + menus.yml/recipes.yml + build_handbook.py table headers ("Fiber");
  generated files regenerated. File names/slugs unchanged (labs/haemoglobin-and-iron,
  stages/hemodialysis-in-centre). UK source titles (JBDS) kept as published.
- Abbreviations: ~85 tooltips added to includes/abbreviations.md; glossary gained entries (AGP, BMI,
  CV, ECG, Ferritin/TSAT, GDO/GDH, IV, PICC, POLST, Practice point, RAAS, REMS, T1D/T2D) and an
  "Other abbreviations" section (organizations, food, benefits, app/self-hosting). Every tooltip
  abbreviation appears in the glossary. units.md "ACR" -> "UACR" (ACR = American College of Radiology).
- Cross-links added: treating-a-low and cgm-metrics -> living/sleep; labs/index -> glossary;
  podman-rootless -> docker-rootless, kubernetes; building-the-handbook -> licences + README.

- Rebuild after sweep: strict build OK, linkcheck 0 broken, content tests 583 passed / 1 skipped.
- Screenshots (Playwright, Chromium /opt/pw-browsers/chromium-1194, http.server on 127.0.0.1:8765
  over $S/site; script $S/tools/shots.mjs): home, stages/g4, labs/blood-potassium, eat/potassium,
  t1d/treating-a-low at 375 and 1280, light and dark (shots in $S/shots/v1-*, v2-*). No page-level
  horizontal overflow, no console errors, draft banner + announce bar on all. extra.css fixes:
  hide Material's untitled "i" status icons in nav (from `status:` front matter); mobile table cells
  min-width 3.25rem (was 5rem) so 4-col tables fit; scroll-edge shadow on wide tables (CSS only).

- handbook/README.md rewritten (layout, build + 4 checks, edit, house style with the shared-number
  table, safety rules, cite, editorial policy, clinical review roles + sign-off steps, licence).
- handbook/tools/check_links.py added (stdlib link + anchor checker; README documents it).
- REVIEW.md: new top section "Open clinical decisions: index" covering every item of the six
  "For a clinician to decide" lists (S1-7, St1-11, L1-8, E1-8, A1-5, T1-10) + peritonitis "keep the
  bag" (About page) + prepare/living not independently fact-checked + sign-off status + open items
  for other owners.
- reference/about.md: reviewer rows for Living well, Using the app, Self-hosting; two review-log rows.
- medicines/avoid salt-substitute row "They are" -> "They contain potassium chloride" (Lite Salt is a mix).
- templates/medical-page.md example K range aligned to 3.5-5.1.

- Final verification (2026-10-06 ~10:00 UTC): `build_handbook.py --check` OK (24 files, 6 menus);
  `mkdocs build --strict` OK; `handbook/tools/check_links.py`: 119 HTML pages, 14,491 internal links,
  0 broken, 0 bad anchors; `pytest tests/test_handbook_content.py`: 583 passed, 1 skipped
  (app/guidance/topics.py not written yet), 1 warning (6 unused DG ids); same with the venv and
  `--noconftest`; tests/test_deploy.py passes. Final screenshots v5: 20 shots, no page overflow, no
  console errors, draft banner + announce bar everywhere.
- Totals: 118 pages (2 root, ckd 3, stages 11, labs 11, eat 37, t1d 5, medicines 4, prepare 4,
  living 9, reference 7, app 12, self-hosting 13); about 162,000 words (116,000 hand-written,
  46,000 generated menus/recipes/grocery lists/bibliography).

## Not done / left for others

- prepare/ and living/ have no independent fact-check (listed in REVIEW.md index).
- Every page is still `status: draft`; no clinical sign-off yet.
- app/guidance/topics.py (M2) will enable the skipped slug test.


## Commands

```bash
S=/tmp/claude-0/-home-user-kidney-health/8a6bc573-c86c-5a92-a072-0545790bf9a4/scratchpad/handbook
$S/venv/bin/python scripts/build_handbook.py --check
(cd handbook && NO_MKDOCS_2_WARNING=true $S/venv/bin/mkdocs build --strict -d $S/site)
python3 -m pytest -q tests/test_handbook_content.py   # system python (conftest needs httpx2, not in venv)
python3 $S/tools/linkcheck.py $S/site                 # internal links + anchors over built HTML
```
