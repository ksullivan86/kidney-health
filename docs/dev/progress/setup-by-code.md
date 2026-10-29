Status: complete (2026-10-29): merged in #111 (0856183). Release 0.10.0 prepared next.

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

- Deploy files, docs/deployment.md "Set it up by code", ARCHITECTURE, CHANGELOG, ROADMAP, handbook configuration page + NOTE20: done.
- Live check: uvicorn with ADMIN_USERNAME/ADMIN_PASSWORD_FILE + SETTINGS_INITIAL_ONLY; first values written and audited, locked name
  refused (409), admin's change kept after restart.

## Next (old list, done)
- deploy/compose.yaml passthrough SETTINGS_INITIAL_ONLY (+ INSTANCE_NAME, REGISTRATION_MODE), deploy/.env.example, quadlet, k8s.
- docs/deployment.md "Set it up by code", ARCHITECTURE, CHANGELOG, handbook self-hosting/configuration.md + sources.yml NOTE20.
- Full pytest; PR after #110 merges (same branch).

## Commands
- `$V -m pytest -q tests/test_settings_initial.py tests/test_settings_store.py tests/test_compose_env.py`
- `$V tests/data/gen_settings_vectors.py && node tests/js/run_vectors.mjs`

## After #111 merges
- merge main into the branch; `git merge release-0.10.0` (local branch from the worktree), push, open "Prepare release 0.10.0" PR.
- Tell the owner: tag v0.9.0 on 401a024 and v0.10.0 on the release merge commit.
