# finalize: progress note

Role: finalize the v0.3.0 build (ports 8640-8659; scratch
/tmp/claude-0/-home-user-kidney-health/8a6bc573-c86c-5a92-a072-0545790bf9a4/scratchpad/v030/finalize/).

## Done (HEAD 5b7d70f, clean tree)
- Read every progress note (24) and the CHANGELOG / ROADMAP.
- node tests/js/run_vectors.mjs: all 6 suites pass (rules 5721, settings 456, targets 1859, kidney 140,
  guidance 66, barcode 2034). node --check: 49 app/static JS files + tests/js/*.mjs ok.
- SHA-pin grep ok; actionlint 1.7.12, hadolint 2.14.0 (3 files), zizmor 1.30.1 --offline: clean;
  kustomize 5.8.2 + kubeconform 0.8.0 strict: 12 valid; shellcheck 0.11 ok; yaml_parse 35 files ok;
  docker compose config (compose, +ollama, +caddy with dummy secrets in a git-archive copy): ok.
  (CI-version binaries: scratchpad/m1/m1-integrate/bin.)
- Handbook: build_handbook --check up to date; mkdocs --strict (HANDBOOK_APP_LINK=/) ok;
  check_links 119 pages / 14636 links / 0 broken; content tests 587 passed (1 warning: 6 uncited
  sources); test_learn_links with HANDBOOK_BUILT_SITE 32 passed.
- TODO/FIXME/XXX/NotImplementedError/skip/xfail grep over app tests tools scripts deploy .github: none.
- Preview built: 1,454,523 bytes (1420.4 KiB).

- pytest: python3 3.11.15 and venv312 (3.12.3): 3418 passed each, 0 failed/skipped/xfail, 1 UserWarning
  (6 uncited handbook sources). Note: pyproject addopts has -q, so do not pass -q (it hides the summary).
- parity.py (8640/8641): 6528/6528 in all sections.
- regress.py --no-pytest (8642): first run 484 + 1 FAIL ("repository unchanged": my edits mid-run);
  re-run on the clean tree after 5415679: 485 passed, 0 failed.
- device.py (8647/8648): 146 passed, 1 FAIL in [demo] (20 s wait for the offline badge) while sandbox ran
  in parallel; `--only demo` re-run alone: 13/13. Load flake, not a code fault.
- Smoke test runs the app's CA-store self-check inside the built image (CI image job verifies on push);
  tests/test_deploy.py pins it. Handbook app/install.md points at the "Works offline" row.
- CHANGELOG "Fixes from the release review" rewritten with every fixer/integrate fix (grouped); Known
  limitations + meal-alert tolerance. ROADMAP: MILP numbers, screen readers/date pickers, tolerance in
  guidance review, new "Open items from the v0.3.0 build" (uncited sources, OFF test product).
  maintainers.md pre-tag checks: journey/upgrade, first runs of refresh-locks/handbook-links/pages,
  live AI evals. ARCHITECTURE Milestones status + smoke-test CA note.
- Fixed M1-review leftovers: This device no longer repeats installed/offline in the install panel;
  "reminders need HTTPS" (reminders are v0.4) -> "Offline use and the live camera need HTTPS";
  docs/https.md + handbook self-hosting/https.md point at the "Works offline" row; 2 tests in
  tests/test_settings_ui.py. Test docstrings no longer point at progress notes (they get deleted).

## In progress
- sandbox.py on the rebuilt preview (8643, 2 workers).

## Next
1. Run every check (pytest python3 + venv312, vectors, node --check, handbook build/check/content/links,
   hadolint, actionlint, zizmor, SHA pins, kubeconform, parity.py, regress.py, preview + sandbox.py).
2. Fix failures.
3. CHANGELOG / ROADMAP / ARCHITECTURE reflect the final state and every not-done item.
4. Condense docs/dev/progress/*.md (not README.md) into those docs, delete the notes.
5. Last commit without [skip ci]; push.
