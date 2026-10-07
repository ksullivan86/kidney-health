## Summary

<!-- What does this change, and why? Link the issue ("Fixes #123") and the part of ARCHITECTURE.md or the
design note (docs/dev/research/NN-*.md §…) it implements or changes. -->

## Test plan

<!-- What you ran and what you saw. Delete the lines that do not apply. -->

- [ ] `python -m pytest` passes with no network
- [ ] `node tests/js/run_vectors.mjs` passes
- [ ] New or changed tests cover the change, including failure paths and limits
- [ ] Browser harnesses run (which ones, and the result): <!-- tools/e2e/parity.py, regress.py, sandbox.py, device.py, learn.py, guidance_perf.py -->
- [ ] Checked by hand at phone width (375 px) and desktop, light and dark (for UI changes)
- [ ] Handbook checks pass (for handbook changes): `scripts/build_handbook.py --check`, `tests/test_handbook_content.py`, `mkdocs build --strict`, link checker

## Safety checklist

- [ ] No insulin or medication dosing anywhere (no doses, units, ratios, correction factors, "stop taking")
- [ ] Treating a low is never blocked, delayed, limited or warned against, and low-treatment text never goes to AI
- [ ] Every new or changed clinical number cites its source (or is labelled as the project's own choice)
- [ ] Parity: JS twins and `tests/data/*.json` vectors updated with their generators (or no twin is affected)
- [ ] Migrations are append-only: a new step in `app/migrations/`, no released step edited, tested by upgrading a populated previous schema (or no schema change)
- [ ] Security rules kept: `current_user` on every new `/api` route, queries scoped by `user.id` (not yours → 404), secrets write-only, no inline scripts or styles, outbound HTTP only through the SSRF-checked transports, settings only through the registry
- [ ] Docs updated where a person can see the change: `ARCHITECTURE.md`, the page in `docs/`, the handbook's "Using the app" pages, `CHANGELOG.md` (`## Unreleased`)

By opening this pull request I agree that my contribution is licensed under the project's licences
(code: PolyForm Noncommercial 1.0.0; handbook text: CC BY-NC-SA 4.0), as described in CONTRIBUTING.md.
