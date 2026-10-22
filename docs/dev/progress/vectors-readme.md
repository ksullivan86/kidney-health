Status: complete (role vectors-readme; design note 14 change 6, documentation half)

# vectors-readme: a guide to tests/data/*_vectors.json

Base: `283c497`. Spec: `docs/dev/research/14-reuse-map.md` §3 (iOS needs) and §4 change 6. The Swift test target is not part of this task.

## Plan

1. Read the 17 vector files, their generators and `tests/js/run_vectors.mjs` (how each is replayed, how numbers are compared).
2. Write `tests/data/README.md` (opening, regeneration commands, one `## <file name>` section per file, "Replaying in another language").
3. Write `tests/test_vectors_readme.py` (sections vs files, generator paths exist, `Top-level keys:` lines match the files). Break it on purpose, then fix.
4. Check nothing else lists `tests/data` (Containerfile, .dockerignore, tests).
5. Update note 14 change 6 row, `CHANGELOG.md` (Unreleased, For contributors), `CONTRIBUTING.md`.
6. Run: new test, vector-currency tests, `node tests/js/run_vectors.mjs`, `ruff check .`, full pytest.

## Done

* Step 1 read. Facts found (keep for the README):
  * Python generators all write in place and take `--check`; `gen_apple_health_vectors.mjs` takes `--check`; `gen_fhir_labs`, `gen_ccda_labs`,
    `gen_lab_import` (`.mjs`) just rewrite (no `--check`). `menu_link`, `personal_target` are by hand / copied from design note 05.
  * `personal_target_vectors.json` is only replayed through `targets_vectors.json` (its 23 cases become TV01..TV23) and `tests/test_targets.py`.
  * Number comparison in `run_vectors.mjs`: exact (`isDeepStrictEqual`) except `closeTo` (1e-9 relative, `max(1,|b|)`) for `eer_cases.kcal` and
    `egfr_cases.expect.unrounded`; guidance keeps the sign of zero (`-0.0`).
  * Rounding is decimal half-up on the shortest repr (`26.95` -> `27.0`).
  * `barcode_vectors.json` `textclean_cases` holds 161 values with lone surrogates; `max_len` counts code points.

* Steps 2 and 3 done: `tests/data/README.md` (17 sections, `Top-level keys:` lists, regeneration table, replay rules) and
  `tests/test_vectors_readme.py` (23 tests). Broke the README seven ways (renamed a section, invented a key, dropped a key, wrong generator
  path, a section for a missing file, wrong repo path, dropped a generator mention): each failed the right test, then restored.
* Verified the commands in the README: `--check` on the 11 Python generators and `gen_apple_health_vectors.mjs` exits 0; the other three `.mjs`
  generators rewrite identical files (`git status` clean).
* Step 4: nothing else lists `tests/data` (no test, Containerfile or `.dockerignore` entry; the image allowlist already leaves `tests/` out).

## Decisions

* The "Top-level keys:" list is bullets that start with the key in backticks (name and meaning in one place), not an inline list.
* Only sets are compared for keys (not order). No counts in the prose (they would go stale without a test noticing).
* Hypoglycaemia wording follows `app/rules_kidney.py` and `docs/guidance.md`: no carbohydrate warning and never blocked, delayed or sent to an
  AI; potassium, phosphorus and sodium warnings on low treatments stay (the vectors have them).

* Step 5 done: note 14 change 6 row ("Done in part"), `CHANGELOG.md` (Unreleased, For contributors), `CONTRIBUTING.md` (one sentence in "The parity
  rule"), and one sentence in `ARCHITECTURE.md` next to the parity rule (the same pointer).
* Step 6 checks passed: `python -m pytest tests/test_vectors_readme.py` and the vector-currency, e2e, deploy and safety-set tests; `node tests/js/run_vectors.mjs`
  (all groups pass); `ruff check .`. The full `python -m pytest -q` was started in the background and passed (exit 0, about 14 minutes).

## Reproduce

```bash
python -m pytest tests/test_vectors_readme.py -q
node tests/js/run_vectors.mjs
ruff check .
for g in barcode body entry_version guidance import kidney_function meta rules settings symptoms targets; do python3 tests/data/gen_${g}_vectors.py --check; done
node tests/js/gen_apple_health_vectors.mjs --check
```

## Next

Nothing, once the full run is green. A Swift test target is out of scope (waits for the iOS design note).
