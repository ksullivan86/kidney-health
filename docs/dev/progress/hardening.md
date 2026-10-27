Status: in progress

# hardening (access-control audit fixes)

Worktree branch `wip/hardening`. Findings and the asked work: fix 1 (tokens survive an AUTH_MODE change), fix 2 (file
modes under DATA_DIR), doc gaps 3 to 7, CHANGELOG, ARCHITECTURE.

## Done
* Fix 1: `api_tokens.revoke_everyone`, reason `auth_mode_changed`, called from `_auth_mode_changed` in
  `app/auth/bootstrap.py`; settings.js label; tests in `tests/test_auth_mode_tokens.py` (they fail without the fix);
  docs (assistant, accounts, push, deployment, handbook x2, ARCHITECTURE).

* Fix 2: `Settings.ensure_data_dir` (0770, tighten when owned), `db.init_db` pre-creates 0660 and `db.secure_database_files`;
  tests in `tests/test_data_file_modes.py` (fail without the fix); docs deployment, README, security, ARCHITECTURE.
  Nothing else under DATA_DIR is written by the app besides secret.key (0600) and backups (0600); there is no photo,
  export or lab PDF cache on disk.

## Next
* Docs 3 to 7, CHANGELOG, final checks.

## Checks
* `python -m pytest tests/test_auth_mode_tokens.py -q`
* `python <audit>/modeswitch.py` from the worktree: 401 on both after the switch.
