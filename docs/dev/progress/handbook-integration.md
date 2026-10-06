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

## Decisions

- HANDBOOK_PUBLIC_URL lives in config.py (deployment URL like PUBLIC_URL), not the settings registry.
- /api/handbook (signed in, not public) tells the UI where Learn links go; the link table imports
  app/guidance/topics.py (NUTRIENT_TOPIC, TOPIC_PAGES) so slugs have one source.
- A broken site (too many inline scripts, non-UTF-8 page) → ERROR log, /learn 404, app keeps running.

## Known failures not mine

- tests/test_settings_ui.py (2) and tests/test_rules_vectors.py::test_js_engine_matches_vectors:
  settings registry gained targets.*/guidance keys without the JS twin (engine/settings.js) and
  vectors being updated (targets/guidance roles). Recheck later.

## Next

3. ci.yml handbook job (image jobs need it) + handbook-pages.yml.
4. Frontend Learn entry + About link + /learn links from warnings/target notes + link test.
5. Docs: diet-guide pointer, self-hosting pages link to canonical docs, "coming in v0.3" fixes,
   ARCHITECTURE.md (/learn live), ROADMAP for deferred items.
6. E2E Chromium check, hadolint, actionlint, zizmor, SHA-pin check, full pytest.
