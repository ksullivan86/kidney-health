Status: in progress (role vectors-readme; design note 14 change 6, documentation half)

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

## Next

Step 2 onwards.
