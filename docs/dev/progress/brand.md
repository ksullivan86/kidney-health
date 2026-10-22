Status: in progress (role brand; design note 14 change 3)

# brand: the brand strings in one place

Base: `a441fa2`. Spec: `docs/dev/research/14-reuse-map.md` §1 point 10 and §4 change 3. No value may change: many are cookie names,
HKDF labels, token prefixes, the database filename, the IndexedDB name and the export `format`.

## Plan

1. `app/brand.py` (plain constants, no imports) and use it at each Python site.
2. `app/static/js/engine/brand.js` (`KH.brand`), registered in `index.html` (the last engine file, just before `core.js`) and in the `sw.js` precache list.
   `scripts/build_preview.py` reads `index.html`, so it needs nothing. Test harnesses that load files by hand get it added.
3. Tests: `tests/test_brand.py` (values pinned, Python and JS twins agree, literals only in an allowlist).
4. Docs: ARCHITECTURE (layout, ownership, "Brand strings"), CONTRIBUTING, CHANGELOG, note 14.

## Done

* `app/brand.py` (32 constants, each with a comment saying whether it is compatibility surface) and every Python site uses it: cookies, CSRF
  value, version header, token prefixes and regexes, bearer realm, DB filename, backup prefix, MCP name/title/source, export format and README,
  User-Agents, HKDF labels, logger names (31 modules), the API document's texts, the admin CLI's help.
* `app/static/js/engine/brand.js` (`KH.brand`), the last engine script in `index.html` (just before `core.js`), in `sw.js`'s precache list; used by core.js, offline.js, pwa.js,
  views/{ai,ask-voice,auth,settings,trends,visit}.js, main.js, mock/{export,import}.js.
* `tests/test_brand.py` (27 tests): values pinned, sites unchanged (incl. HKDF known answers), JS twin agrees, grep test with an allowlist.
* Text pins in five existing tests updated to the new JS wording (test_ai_ui, test_ask_voice_ui, test_device_ui, test_frontend_shell,
  test_pwa_routes) and test_demo_local_ui.
* Checked so far: `ruff check .`, `gen_openapi.py --check`, `node tests/js/run_vectors.mjs`, the affected pytest files.

* Docs done: ARCHITECTURE.md (layout, ownership row, frontend tree, "Brand strings"), CONTRIBUTING.md (a line and a twin-table row), CHANGELOG.md
  (Unreleased, For contributors), note 14 (change 3 marked done).
* Checked: `tests/data/gen_*.py --check` (11 files), `build_handbook.py --check`, browser: `tools/e2e/device.py --only outbox,changes,demo,firstvisit`
  (77 passed), `demo_local.py` (90 passed), `import_walk.py` (105 passed, 4 failed; the same 4 fail on the base commit `a441fa2`, they expect the
  preview text without ", 0 weights, 0 blood pressure readings").

## Next

* The full `python -m pytest -q` result (running in the background; log in the scratchpad), then mark the note complete.

## Decisions

* The JS file lives in `js/engine/` so `tests/js/demo_loader.mjs` (which loads `engine/`, `mock/` and `core.js` from `index.html`) finds it.
  Two tests (`test_apple_health.py`, `test_body_import_ui.py`) want `apple_health.js` right after `rules.js`, and `test_frontend_shell.py` /
  `test_preview_build.py` want `rules.js` first, so `brand.js` is the last engine file, right before `core.js` (the first reader). My first
  placement (second) failed those two tests in the full run; moved.

## Commands that reproduce the checks

```
python -m pytest -q tests/test_brand.py
python scripts/gen_openapi.py --check
for f in tests/data/gen_*.py; do python "$f" --check; done
node tests/js/run_vectors.mjs
ruff check .
python scripts/build_handbook.py --check
python -m pytest -q          # the full suite, in the background
```
