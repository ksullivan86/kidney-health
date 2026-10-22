Status: in progress (role reuse-api; design note 14 changes 2 and 4); code, tests and docs written, final checks running

# reuse-api: a checked-in OpenAPI document (change 2) and GET /api/meta (change 4)

Base: `89b97a5` (the integrated stack), branch `worktree-reuse-api`. Spec: `docs/dev/research/14-reuse-map.md` §3, §4 changes 2 and 4, §6.

## Done

* Change 2: `app/api_version.py` (`API_VERSION = 1`), `app/openapi_doc.py` (operation ids `<first tag>_<function>`, 400 instead of 422, shared
  `Problem` responses, `session` / `assistantToken` / `deviceToken` schemes read from the dependencies, `info.x-api-version`), wired in `app/main.py`
  (`generate_unique_id_function`, `openapi_doc.install`); `operation_id="mcp_post"` on `POST /mcp`; `scripts/gen_openapi.py` (+ `--check`);
  `docs/api/openapi.json` (valid OpenAPI 3.1 by `openapi-spec-validator`, identical under pydantic 2.13.4 and the locked 2.14.0);
  `tests/test_openapi_snapshot.py` (27 tests).
* Change 4: `app/meta.py` (`GET /api/meta`), `status_view` split out of `ai_status_route` in `app/ai/routes.py`, `providers_available` in
  `app/barcode.py`; the demo twin `app/static/js/mock/meta.js` (registered in `index.html` and `sw.js`); `tests/data/gen_meta_vectors.py` +
  `meta_vectors.json` + a `meta` group in `tests/js/run_vectors.mjs`; `tests/test_meta.py` (25 tests); `tools/e2e/parity.py` section 10.
* Docs: `docs/api/README.md`, ARCHITECTURE (layout, ownership row, "The API document and `GET /api/meta`"), CONTRIBUTING (one line), CHANGELOG
  (Unreleased, For contributors), ROADMAP open item, `docs/README.md`, `tools/e2e/README.md`.

## Decisions

* Operation id = `<first tag>_<route function name>` (the tag is left off when the name already starts with it). Stable when a path or a
  router prefix changes; a rename of the function renames the id.
* Statuses: structural rules (400 where FastAPI would add its 422; 401/403 on session routes; 404 on path parameters, AI-gated routes and `/mcp`;
  413 on POST/PUT/PATCH) plus one reviewed table by operation id for 409, 415 and 429, plus a `default` on every `/api` operation.
* The 422 FastAPI adds is removed; the 422 that `GET /api/profile/suggested-targets` really returns stays (the route declares it).
* `capabilities` are flat booleans (`ai`, `ai_next_meal`, `ai_parse_meal`, `ai_label`, `ai_plate`, `ai_lab_report`, `chat`, `voice`, `assistant`,
  `push`, `barcode`, `barcode_off`, `barcode_usda`, `handbook`); the AI ones come from `status_view`, so they equal `GET /api/ai/status`.

## Commands that reproduce the checks

```
python scripts/gen_openapi.py --check
python tests/data/gen_meta_vectors.py --check
python -m pytest -q tests/test_openapi_snapshot.py tests/test_meta.py
node tests/js/run_vectors.mjs
ruff check .
python scripts/build_handbook.py --check
PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers python tools/e2e/parity.py --sections 10
python -m pytest -q          # the full suite, in the background
```

## Next

Final full run, `build_handbook.py --check`, parity section 10, then mark this note complete.
