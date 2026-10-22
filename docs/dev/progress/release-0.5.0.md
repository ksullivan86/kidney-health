# release-0.5.0 progress

Status: in progress (started 2026-10-22). Worktree branch `wip/release-0.5.0`, based on main 9ab8df4. Not pushed; the caller integrates.
Job: step 1 of "Release process" in `docs/maintainers.md`. Model: `git show 8d3fba3` (the v0.4.0 prep, #64).

## Done
1. Version 0.5.0: `pyproject.toml`, `app/main.py`, `app/static/js/views/settings.js`; `docs/api/openapi.json` regenerated.
2. Image pins and "current version" strings (`:0.4` to `:0.5`, `0.4.0` to `0.5.0`): deploy/, .github/, scripts/verify-image.sh,
   docs/security.md, docs/deployment.md (new "From v0.4 to v0.5"), handbook self-hosting pages (upgrades has "From v0.4 to v0.5"),
   README (Upgrading), SECURITY.md, tests/test_deploy.py, ARCHITECTURE.md (status, `/api/meta` example), maintainers.md (v0.5.0 not held).

3. CHANGELOG: `## Unreleased` became `## 0.5.0 — 2026-10-22` with Highlights, Upgrading from 0.4, Security, Known limitations
   (new) and the old entries tidied (phone shortcuts split into a user entry and a server entry). Committed.
4. ROADMAP (new "Next" section, shipped items out, `Open items from the v0.5.0 build`), note 15 (status, decision line), the ten finished
   progress notes removed and the README sentence updated, handbook `app/index.md` ("New in version 0.5" and a phone-shortcut row),
   README, `docs/README.md`.

## Next
Full checks (pytest in the background, node vectors, ruff, handbook check, openapi and gen checks, `git diff --check`), a last grep for
`0.4`, then remove this note in the last commit.

## Left on purpose (history, not the current version)
Past CHANGELOG sections, "since 0.4.0", "From v0.3 to v0.4", docs/dev/plans and research notes, `tests/test_zip_reader.py` (a made-up
`app_version`), `tests/test_deploy.py` comment about 0.4.0's notes, the "0.4.0's is about 94,000 characters" line in maintainers.md.

## Commands
    python scripts/gen_openapi.py --check
    for f in tests/data/gen_*.py; do python $f --check; done
