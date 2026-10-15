Status: complete (pending the caller's PR)

# Visit prep (ROADMAP "Visit prep (small to medium)")

Role: `visit-prep`. Worktree branch `worktree-agent-a98c51a11cbe67027`, based on the symptoms log
(`worktree-agent-a89a43915d2fb3607`, merged as `6a5b7f3`; the merge conflicts were only in docs and the harness list).
Do not touch `app/ai/`. No push, no PR (the caller opens it).

## State

- [x] 0 merged the symptoms log (`6a5b7f3`)
- [x] 1 engine `js/engine/visitprep.js` (`KH.visitPrep`, pure) with `tests/js/visitprep_runner.mjs` and
      `tests/test_visit_prep_numbers.py` (7 tests: the endpoint's numbers, unknown K/P, labs and arrows, grouped symptoms,
      question limits)
- [x] 2 view `js/views/visit.js`, `css/visit.css`, `#view-visit` + the Trends button in `index.html`, `visit` in `VIEWS`,
      `sw.js` precache, `KH.symptoms.flagEl` exported from `js/views/symptoms.js`
- [x] 3 `tests/test_visit_prep_ui.py` (12 static checks), harness list in `tests/test_e2e_tools.py`
- [x] 4 `tools/e2e/visitprep.py`: 105 checks pass in Chromium (375 px light, 1280 px dark, the demo); A4 and Letter PDFs
      are one sheet each for the seeded person
- [x] 5 docs: ARCHITECTURE ("Visit prep", ownership row, module list), CHANGELOG, ROADMAP (item and estimate row removed,
      as for the symptoms log), `docs/privacy.md`, handbook `living/appointments.md` (one sentence in "What to bring"),
      `app/reports-for-your-team.md` (new section "Visit prep: one page for an appointment"), `app/index.md`,
      `tools/e2e/README.md`
- [x] 6 full pytest and `node tests/js/run_vectors.mjs` (see the report for the final result)

## Decisions and why

- **No server code.** Everything the page needs is already an endpoint (`/api/log/summary`, `/api/labs`, `/api/symptoms`), so
  there is no new route, table or twin, and no parity vectors. The averages are the endpoint's numbers: `averageRows` only
  picks and words them (a test asserts it has no arithmetic).
- **Questions: memory only** (least trust). Not `localStorage` (it is per origin, so on a shared browser the next person would
  see them, and sign-out does not clear it), not the server, never the AI. Cost: gone on reload; the page says "print it or
  save the PDF first". A person is dropped from memory by `S.owner` if another signs in on the same page.
- **Unknown K/P**: "≥ N" with the counts; "Not listed" when nothing was listed; the level becomes `unknown` ("Not complete") as
  in Trends. Never 0.
- **Labs**: no ranges, no interpretation. The arrow compares the server's rounded canonical `value` of the newest and the
  previous result. The only warning drawn is the server's existing potassium alert (`KH.labs.alertBanner`), as on the Labs
  screen, so a printed page never hides a current urgent potassium.
- **Symptoms**: `KH.symptomRules.summarise` and `KH.symptoms.flagEl` (the same function and words as Today and Trends).
- **Way in**: Trends' period card, not a tab (six tabs stay). The word "reminders" is not used in the UI
  (`tests/test_settings_ui.py` forbids it before reminders exist): the checklist is "Checklist from the handbook".
- **The checklist** is `handbook/docs/living/appointments.md` "What to do", word for word, checked by a test. The link uses
  `KH.learn.href('/learn/living/appointments/')`, so no handbook means no link.
- **Print**: `:root:has(#view-visit:not([hidden]))` scopes the print rules to this view; `@media print` black on white,
  9 pt, 9 mm margins, two columns for averages, labs and the checklist.

## Commands that reproduce the checks

- `python -m pytest -q -p no:cacheprovider tests/test_visit_prep_ui.py tests/test_visit_prep_numbers.py tests/test_e2e_tools.py tests/test_frontend_shell.py tests/test_learn_links.py tests/test_settings_ui.py tests/test_symptoms_ui.py`
- `python tools/e2e/visitprep.py --out /tmp/kh-visitprep` (needs Playwright and Chromium; writes `shots/` and the PDFs)
- `node tests/js/run_vectors.mjs`
- `python -m pytest -q -x -p no:cacheprovider`
