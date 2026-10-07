Status: in progress

# docs-release (v0.3.0 release docs and metadata)

Role: prepare docs and metadata for the v0.3.0 release. Edit no code except version strings.
Scratch: `/tmp/claude-0/-home-user-kidney-health/8a6bc573-c86c-5a92-a072-0545790bf9a4/scratchpad/v030/docs-release/`.
Ports 8390-8399 only (fact checks).

## Steps

1. [x] Version 0.3.0 (pyproject.toml, app/main.py APP_VERSION, js/views/settings.js APP_VERSION,
       tests/test_barcode_api.py User-Agent). Service worker version is hash-based: untouched.
2. [x] ARCHITECTURE.md item 7: owner decision 2026-10-06 (no hold; HOLD_LATEST unset).
3. [x] CHANGELOG.md 0.3.0 section (draft done; re-check the integrate agent's fixes before finishing and add them under "Security fixes from review" / Known limitations).
4. [x] CONTRIBUTING.md, CODE_OF_CONDUCT.md, AGENTS.md, docs/README.md, docs/maintainers.md,
       docs/ROADMAP.md, .github/ISSUE_TEMPLATE/*, .github/pull_request_template.md.
5. [x] README.md for v0.3.0 (barcode and AI handoffs: feature lines, config rows incl. OFF_* and USDA_BRANDED_BARCODE, "Optional: barcode lookups and AI" section linking docs/ai.md).
6. [x] Handbook "Using the app" pages (handbook/docs/app/**): every "coming in v0.3" gone; self-hosting
       configuration headings and the building-the-handbook marker rule too; docs/install-on-your-phone.md no
       longer says "tested on 26 and 27" (no real device was used).
7. [ ] Link check of touched Markdown; pytest; handbook checks.

## Decisions

* CODE_OF_CONDUCT.md is the official Contributor Covenant 2.1 text (downloaded from the EthicalSource
  repository's release branch), front matter removed, `[INSERT CONTACT METHOD]` replaced by @ksullivan86 on
  GitHub (profile contact, or an issue with no details asking for private contact). Nothing else changed.
* Issue forms are YAML forms; labels `bug`, `enhancement`, `clinical-content` (docs/maintainers.md says to
  create them). config.yml disables blank issues and sends security reports to SECURITY.md.
* ROADMAP gained: a Clinical review section (REVIEW.md open decisions), note 07 v0.4 items (OIDC, passkeys,
  SMTP, sharing, import, pepper, per-person DB v1.0), note 02 Web Push, note 08 Lunr pruning, the Pi bench
  and note 02's device matrix (merged into the existing device line).

* CHANGELOG keeps a heading "Upgrading from 0.2" (release.yml's HOLD_LATEST comment points at it) and the
  strings `AutoUpdate=registry` and `podman-auto-update.timer` (tests/test_deploy.py checks CHANGELOG, README
  and docs/deployment.md for them).
* "Security fixes from review" lists the M1 code-review and CodeQL fixes plus the note-level security-review
  findings that M2 built in (said so in its intro): none affected a release.
* v0.2 facts checked in git history (331f1b1): `:latest` was every main build; compose used an exec-form
  python health check and k8s httpGet probes, so only the Quadlet unit loops.

* `build/` is gitignored: the preview (`scripts/build_preview.py`) picks up the new APP_VERSION when it is next built; nothing to edit.

## Next

* Re-read `git log` for the integrate agent's fixes and fold them into CHANGELOG ("Security fixes from review",
  safety: the `alcohol` flag) before finishing; final link check of every touched file; full pytest.

## Handoffs (not my files; for the integrate agent)

* app/static/js/views/settings.js This device note says "Offline use, camera scanning and reminders need HTTPS":
  reminders (Web Push) are v0.4 (note 02 R8), not in v0.3.0.
* Settings → Preferences "Units" placeholder says lb/oz are "planned for a later version": no spec defers it, so it
  is not in docs/ROADMAP.md.
* docs/deployment.md Configuration row `AI_*` still says "docs/ai.md once they ship" (integrate step 5).

## Checks

* Handbook: `scripts/build_handbook.py --check` ok; `mkdocs build --strict` (HANDBOOK_APP_LINK=/) ok;
  `handbook/tools/check_links.py $S/learn --allow /`: 119 pages, 0 broken; tests/test_handbook_content.py +
  tests/test_learn_links.py pass.
* Link check of touched Markdown (relative links and anchors, GitHub slugs):
  `python3 $S/check_md_links.py <files>` with `$S` = the scratch dir above (script kept there).
* `python3 .github/scripts/yaml_parse.py .` (issue forms parse, no duplicate keys); `pytest tests/test_deploy.py`.

* Step 1: `python -m pytest tests/test_settings_ui.py tests/test_barcode_api.py tests/test_planning.py` passed.
