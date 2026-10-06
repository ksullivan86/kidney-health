Status: in progress

# Progress: handbook-integration (M3, v0.3.0)

Role: note 08 §4.6 (serve /learn), §4.7 (Containerfile handbook stage), §4.8 (CI handbook job +
Pages workflow), §4.10 (Learn nav entry + /learn links + link test), §4.11 (doc migration). Ports
8320-8329. Scratch: /tmp/claude-0/-home-user-kidney-health/8a6bc573-c86c-5a92-a072-0545790bf9a4/scratchpad/v030/handbook-integration/

Previous attempts (agent-a7737cadc40ee79f0, agent-a052d31b9a18be4d6) were stopped while still
reading; they changed no files. Started 2026-10-06.

## Done

1. Serving (§4.6), verified by `python3 -m pytest -q tests/test_handbook_serving.py` (64 pass) and
   tests/test_auth_coverage.py, test_security.py, test_config_secrets.py:
   - `app/handbook.py`: load() (index.html required; errors logged, never raised, so the food log
     still starts), inline-script hashes (regex prefilter + HTMLParser; 8 hashes / 0.05 s on the real
     119-page site), handbook_csp(), HandbookStaticFiles (immutable for `assets/**/<name>.<8hex>.min.js|css`,
     else no-cache; .gz → application/gzip), mount() before "/" + `/learn` → 308 `/learn/`,
     `GET /api/handbook` (signed in): {available, url, public_url, links{nutrients, flags, pages}}.
   - `app/security.py`: SecurityHeadersMiddleware/install take `path_policies` ((prefix, csp) pairs).
   - `app/config.py`: HANDBOOK_DIR (Settings default None = hermetic tests; load_settings default
     <repo>/handbook/site), HANDBOOK_PUBLIC_URL (validated, normalised to end with "/").
   - `app/main.py`: handbook.setup → security.install(path_policies) → router → mount before "/".
   - tests/fixtures/learn/ (3 pages + 404, Material-shaped), tests/test_handbook_serving.py.
   - .gitignore: handbook/site/, handbook/.cache/.

2. Image (§4.7), verified by hadolint (both Containerfiles + caddy: clean), shellcheck, pytest
   tests/test_deploy.py, and smoke_http.py against a local uvicorn on :8320 with the real site:
   - deploy/Containerfile + Containerfile.debian: handbook stage = venv --without-pip + pip --python
     --no-deps --require-hashes --only-binary=:all: from handbook/requirements.lock (every pin has a
     py3-none-any or cp314 manylinux x86_64+aarch64 wheel, checked on PyPI), mkdocs build --strict
     -d /out/learn with HANDBOOK_SITE_URL=http://localhost/learn/ HANDBOOK_APP_LINK=/, *.map removed,
     index.html required, chmod go=rX; runtime COPY --from=handbook --chown=0:0 /out/learn /app/learn.
   - licences label "PolyForm-Noncommercial-1.0.0 AND CC-BY-NC-SA-4.0" (Containerfiles + release.yml);
     hadolint's spdx check cannot parse expressions, so .hadolint.yaml checks it as text and
     tests/test_deploy.py pins the value.
   - .github/scripts/smoke_http.py: /learn/ 200 + handbook CSP, / keeps Trusted Types, topic page,
     search index, 404 page, fingerprinted bundle immutable. smoke-test.sh doc line.
   - tests/test_deploy.py: handbook-stage test, release label test, .dockerignore test accepts files
     under allowed dirs and requires handbook/site + handbook/.cache excluded.

3. CI and Pages (§4.8), verified by actionlint (all workflows), zizmor 1.30.1 --offline (no
   findings), the CI SHA-pin grep, .github/scripts/yaml_parse.py, tests/test_deploy.py (66 pass):
   - ci.yml: job `handbook` (app deps + handbook venv + build_handbook --check + strict build like the
     image + check_links + content tests (--noconftest) + test_learn_links against the built site +
     Playwright from tools/e2e/requirements.lock with the runner's /usr/bin/google-chrome running
     tools/e2e/learn.py); job `handbook-zensical` (continue-on-error, handbook/requirements-zensical.lock,
     `zensical build -f mkdocs.yml -s`); `image` needs [test, lint, handbook].
   - handbook-pages.yml (vars.HANDBOOK_PAGES == 'true'; build: contents read; deploy: pages+id-token
     write, github-pages env; mkdocs.pages.yml; link check under the Pages base path).
   - handbook-links.yml (weekly Mon 06:17 UTC; lychee v2.9.0; accept 200..=299,403,429; one issue
     labelled handbook-links; contents read + issues write).
   - Action SHAs from `git ls-remote --tags` (the GitHub API is blocked here): configure-pages v6.0.0
     45bfe019…, upload-pages-artifact v5.0.0 fc324d35…, deploy-pages v5.0.1 368f8252…, lychee v2.9.0
     e7477775… (= spec).
   - New locks (pip-tools 7.6.1 on Python 3.14, as scripts/lock.sh): handbook/requirements-zensical.lock
     (-c requirements.lock), tools/e2e/requirements.lock (-c ../../requirements-dev.lock); both added to
     scripts/lock.sh and refresh-locks.yml.
4. App integration (§4.10), verified by node --check, pytest (frontend shell, preview build,
   test_learn_links 26 pass, with and without HANDBOOK_BUILT_SITE), tools/e2e/learn.py (50/50 pass on
   :8321 with the real site) and an ad-hoc Chromium run (target-note links, About):
   - js/learn.js (KH.learn: load/href/link/forWarning), js/mock/handbook.js (demo: no handbook),
     header #learn-link (book icon, name "Learn", same window), Settings → About "Learn: the patient
     handbook" (+ public copy), warnings (core.js renderWarnings), Today alerts and projected alerts,
     suggested-target notes (Targets and warnings · First setup); in-context links open a new tab.
   - main.js start() loads /api/handbook with the profile; sw.js shell list + comment.
   - tests/test_learn_links.py: scans app/static + app/**/*.py for /learn/ links, plus TOPIC_PAGES and
     handbook.LINKS; resolves against handbook/docs (and the built site when HANDBOOK_BUILT_SITE is set),
     anchors included.
   - tools/e2e/learn.py + README + tests/test_e2e_tools.py HARNESSES.

5. Docs (§4.11) + ARCHITECTURE, verified by tests/test_deploy.py (79), test_learn_links (26),
   test_handbook_content (584, handbook venv --noconftest), strict rebuild (HANDBOOK_APP_LINK=/),
   check_links --allow / (119 pages, 0 broken):
   - docs/diet-guide.md → pointer (in-app /learn/eat/, source, `git show 331f1b1:docs/diet-guide.md`,
     old section → page map); comments in scripts/curated_foods.py, tests/test_food_db.py updated
     (guidance-owned citations "diet-guide §6" left; the map resolves them).
   - docs canonical: handbook/docs/self-hosting/{podman-rootless,docker-rootless,kubernetes,backups,
     upgrades,troubleshooting,security,users-and-keys,https,configuration} now link to sections of
     docs/deployment.md, docs/security.md, docs/https.md, SECURITY.md instead of copying commands;
     tests/test_deploy.py: anchor check for every such link + no shell blocks on those pages; the 3
     tests that checked commands in both places now check docs/ + the link.
   - docs/security.md: "The handbook at /learn: its own policy, and its own origin" (+ commands, row in
     defaults, residual risk, supply chain); docs/deployment.md: config rows, image facts;
     docs/network-allowlist.md: handbook build/CI hosts, /learn makes no requests.
   - `python -m app.handbook csp [DIR]` (tests added); handbook/tools/check_links.py `--allow PATH`
     (CI passes `--allow /` for the app link); handbook README + building-the-handbook page.
   - "coming in v0.3" for /learn removed (configuration.md, security.md, app/index.md, README layout).
   - ARCHITECTURE.md "M3: the handbook at /learn"; CHANGELOG; docs/ROADMAP.md (note 08 deferrals).

## Decisions

- HANDBOOK_PUBLIC_URL lives in config.py (deployment URL like PUBLIC_URL), not the settings registry.
- /api/handbook (signed in, not public) tells the UI where Learn links go; the link table imports
  app/guidance/topics.py (NUTRIENT_TOPIC, TOPIC_PAGES) so slugs have one source.
- A broken site (too many inline scripts, non-UTF-8 page) → ERROR log, /learn 404, app keeps running.
- Header Learn entry is icon-only (book) with accessible name "Learn" + tooltip: the 880 px header
  truncated the app name with a visible word. In-context links (warnings, alerts, notes) open a new
  tab so an entry being typed in a sheet is not lost; nav links use the same window (spec).
- Playwright in CI uses the runner's Google Chrome (no unpinned browser download).

## Known failures not mine

- tests/test_settings_ui.py (2) and tests/test_rules_vectors.py::test_js_engine_matches_vectors:
  settings registry gained targets.*/guidance keys without the JS twin (engine/settings.js) and
  vectors being updated (targets/guidance roles). Recheck later.

## Next

6. E2E Chromium check, hadolint, actionlint, zizmor, SHA-pin check, full pytest.
