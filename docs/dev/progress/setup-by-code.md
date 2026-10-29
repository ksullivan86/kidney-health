Status: in progress (2026-10-29): server, twin, vectors, tests and design note done; deploy files, docs, handbook, PR next.

# Set the server up by code (design note 20)

Owner's ask: most settings set by code so an AI can deploy; some changeable in the app later ("set on first pull").

## Done (verified)
- `app/settings_registry.py`: env names for the 12 settings that had none (note 20 §3).
- `app/settings_store.py`: `SETTINGS_INITIAL_ONLY` (`initial_only`, `initial_value`, `initial_keys`, `apply_initial`); a listed
  variable is not a lock; meta row `settings_initial:<key>` marks a setting as done.
- `app/main.py` `_initial_settings` runs after init_db, audit `settings.changed` with `env`; `app/admin.py check` prints them.
- JS twin `engine/settings.js` (env names + initialOnly); `views/settings.js` activity text "(first value from X)".
- Vectors: `tests/data/gen_settings_vectors.py` two new precedence cases; `node tests/js/run_vectors.mjs` passes.
- `tests/test_settings_initial.py` (12) passes; `tests/test_settings_store.py` updated; related suites pass.

## Next
- deploy/compose.yaml passthrough SETTINGS_INITIAL_ONLY (+ INSTANCE_NAME, REGISTRATION_MODE), deploy/.env.example, quadlet, k8s.
- docs/deployment.md "Set it up by code", ARCHITECTURE, CHANGELOG, handbook self-hosting/configuration.md + sources.yml NOTE20.
- Full pytest; PR after #110 merges (same branch).

## Commands
- `$V -m pytest -q tests/test_settings_initial.py tests/test_settings_store.py tests/test_compose_env.py`
- `$V tests/data/gen_settings_vectors.py && node tests/js/run_vectors.mjs`
