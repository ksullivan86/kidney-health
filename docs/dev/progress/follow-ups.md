# Progress: owner follow-ups after v0.3.0 (2026-10-08)

Status: complete for the 2026-10-08 run (stopped at about 16:00 UTC, as the owner asked). Everything under
"Done" is merged in `main`; what is left needs the owner or a later run ("Next"). Way of working: one PR per
item, merged when green, then the working branch `claude/adoring-sagan-th5swr` is reset to `origin/main`.
Rules: CLAUDE.md (tests with every behaviour change, JS twins and vectors, append-only migrations, docs and
handbook, no network in tests).

## Done (all merged)

* Phase 0, docs and config:
  * Homelab review 1a + 7: `app.admin backup --dir --keep`, package-public note (PR #7).
  * Homelab review 2, 3, 6a: Litestream notes, proxy-container `TRUSTED_PROXIES` row, SSO+MFA
    recommendation (PR #10).
  * Homelab review 4: the release notes get the image digest (PR #11).
  * Homelab review 5: cluster-neutral `deploy/k8s` base and an example overlay.
  * AI setup in plain words, docs and handbook (PR #12).
* The v0.3.1 batch (`docs/dev/plans/v0.3.1.md`, all six items):
  * "Not chosen yet" for the stage and diabetes type (#13);
  * adjustable tolerance (#14);
  * Server administration on its own page (#15);
  * running high over several days (#16);
  * the GitHub Pages demo (#17);
  * lab results from a CSV file (#18).
* Kidney-only profile:
  * part 1 (#19): no meal carbohydrate goals for diabetes "None" in Today, Meal guidance and Profile;
  * part 2 (#22): the "Not medical advice" note without insulin decisions.
* Settings → AI ideas opens with "How AI help is set up: three questions" (#20). The same PR fixed
  `regress.py` comparing the handbook's Learn links.
* `journey.py`: the setup step opens Server administration for the AI switch (#21). It had been failing
  since #15.
* Smaller image (#23): the handbook search's other-language files are left out (964 KB). A guard test
  ties this to the English-only search setting.
* Offline handbook pages (#24): the service worker keeps the /learn pages a person opened. A page never
  opened answers offline with a short note.

## Final QA on main (21361bc, after #24)

Logs in `scratchpad/qaf/` (script `scratchpad/final_qa.sh`). The handbook was built with `mkdocs build --strict` with
the image's settings, then pruned like the image (no source maps, no `assets/javascripts/lunr`).

* Full test suite: exit 0. `node tests/js/run_vectors.mjs`: exit 0, including 2034 barcode checks and 24 lab
  import checks.
* `upgrade.py` 71/71; `regress.py` 485 passed, 0 failed; `sandbox.py`, `parity.py`: pass.
* `learn.py` 72/72, including offline step 7; `journey.py` 134/134.
* `device.py` 146/147. The demo section's offline quick add sometimes lost its carbohydrate value: about 1 run
  in 4 on this machine, while earlier runs passed by luck.
  * Cause: `openDialog()` in `core.js` gives a sheet's first field focus 30 ms after it opens. When typing
    started sooner, that late focus pulled the cursor out of the field ("15" landed in the name). It was a race
    in the app since v0.3.0, not a regression from today's PRs. `regress.py` already waited 120 ms to avoid it.
  * Fixed (the last PR of the run): the late focus moves the cursor only if focus has not moved since the sheet
    opened. Test in `tests/test_frontend_shell.py`.
  * Verified: the quick add repeated 8 times, 8 saved (1 in 4 failed before), and `device.py` with the fix
    passed 151/151. The `journey.py` and `regress.py` reruns are reported on the PR.

## Next (in order)

1. Owner decisions and runs:
   * the AI prompts worded from the profile (a `PROMPT_VERSION` bump and a golden-set run with a live
     model);
   * the handbook framing for a kidney-only reader (reviewed content);
   * the app's one-line description ("for a renal diet with type 1 diabetes" in `index.html`'s metadata
     and the web app manifest);
   * the clinical reviews listed at the top of `docs/ROADMAP.md`.
2. Code, in a later run:
   * the assistant back end (ROADMAP "An assistant you can talk to");
   * or the smaller ROADMAP items: "Add this menu day to my plan", import of `export.json` into another
     instance, offline edits of entries already on the server.

## Commands that reproduce the checks

```
python -m pytest -q                                  # full suite, no network
node tests/js/run_vectors.mjs                        # JS twins against the vectors
(cd handbook && NO_MKDOCS_2_WARNING=true HANDBOOK_SITE_URL=http://localhost/learn/ HANDBOOK_APP_LINK=/ \
   mkdocs build --strict -d /tmp/kh-site)            # then, like the image: delete *.map and assets/javascripts/lunr
python tools/e2e/upgrade.py && python tools/e2e/regress.py --no-pytest && python tools/e2e/sandbox.py
python tools/e2e/parity.py && python tools/e2e/device.py
python tools/e2e/learn.py --site /tmp/kh-site && python tools/e2e/journey.py --site /tmp/kh-site
```
