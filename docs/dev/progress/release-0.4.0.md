# release-0.4.0 (release prep, step 1 of docs/maintainers.md "Release process")

Status: in progress (started 2026-10-21). Never push, tag, open a PR or a release. Delete this note at the end
together with the other progress notes.

Base: `a8dd85d` (Learn my food preferences, part C, #62), branch `worktree-agent-a1352a865d9c990f6`.

## Plan

1. Version 0.4.0 (pyproject, app/main.py, settings.js) and every place that means "the current version".
2. CHANGELOG: `## Unreleased` -> `## 0.4.0 — 2026-10-21` (Highlights, Upgrading from 0.3, audience subsections,
   Security, Known limitations). No new empty Unreleased.
3. ROADMAP: remove shipped items, keep open remainders, "Last reviewed" line.
4. Condense every other progress note (decisions -> ARCHITECTURE / docs, open items -> ROADMAP, checks ->
   maintainers.md), delete them, fix links, note in progress/README.md.
5. Docs describe what ships (grep for coming / planned / not built / part B / next / unreleased).
6. Checks (pytest, node vectors, ruff, handbook, browser harnesses).

## Done

* Step 1 (version): `pyproject.toml`, `app/main.py`, `settings.js` = 0.4.0. Tag pins that mean "the current version" moved
  from `:0.3` / `0.3.0` / `v0.3.1` to `:0.4` / `0.4.0` / `v0.4.0`: `deploy/` (Quadlet, compose, k8s base and overlay,
  restore pod, rootless script), `tests/test_deploy.py` (3 assertions), `tests/test_barcode_api.py` (User-Agent now built
  from `APP_VERSION`), SECURITY.md (supported versions: 0.4.x yes, 0.3.x and older no), docs/deployment.md (new "From v0.3
  to v0.4"), docs/security.md, handbook self-hosting pages (upgrades.md has "From v0.3 to v0.4"), bug report template,
  `scripts/verify-image.sh` usage, a release.yml comment. Left alone on purpose: test fixtures that pass "0.3.0" to pure
  functions (`test_off_mapping.py`, `test_ai_client.py`, `import_vectors.json` app_version), "v0.3.0 review" comments.

* Step 2 (CHANGELOG): `## 0.4.0 — 2026-10-21` with intro, Highlights, "Upgrading from 0.3 (read this first)" (backup, tag
  `:0.3` -> `:0.4`, Python 3.15, Kubernetes base, headers, defaults that change, new-settings table), the three audience
  subsections kept as the detail (the two assistant bullets merged, PROMPT_VERSION notes consolidated into one server bullet,
  `ref=v0.3.1` -> `v0.4.0`), Security (no vulnerability fix: states that and lists the security-relevant changes), Known
  limitations. No new `## Unreleased`. Links checked with a scratch script (anchors incl. `#from-v03-to-v04`).

## In progress / next

README, ROADMAP, progress-note condensing, docs sweep (coming / planned / part B/C), checks.

## Decisions

* v0.3.1 was never tagged (only `v0.3.0` exists), so the v0.3.1 batch ships in 0.4.0; mentions of "v0.3.1" that a
  person reads as a release are fixed to 0.4.0, internal code comments are left alone.

## Commands that reproduce the checks

(filled in as they are run)
