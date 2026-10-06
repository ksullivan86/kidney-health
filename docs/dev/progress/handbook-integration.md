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

2. Containerfiles (both) + smoke-test.sh /learn fetch + tests/test_deploy.py updates.
3. ci.yml handbook job (image jobs need it) + handbook-pages.yml.
4. Frontend Learn entry + About link + /learn links from warnings/target notes + link test.
5. Docs: diet-guide pointer, self-hosting pages link to canonical docs, "coming in v0.3" fixes,
   ARCHITECTURE.md (/learn live), ROADMAP for deferred items.
6. E2E Chromium check, hadolint, actionlint, zizmor, SHA-pin check, full pytest.
