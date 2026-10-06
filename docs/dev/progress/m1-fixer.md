Status: complete

# M1 fixer

Scope: fix the CONFIRMED review findings (and cheap, clearly right LOW ones) from the M1 review,
with tests; keep ARCHITECTURE.md, docs and handbook in sync. Ports 8170-8179.
Scratch: `$SCRATCH/m1/m1-fixer/` (`$SCRATCH` = the session scratchpad). No commits (prompt).

## Done (verified with `python -m pytest -q tests/test_auth.py tests/test_auth_hardening.py`)

1. Removed admins contained (admin_api, tokens, account, me, routes, admin CLI): `tokens.void_issued_by`
   on demote/disable/delete (before the DELETE), `tokens.void_reset_links` on password change (me,
   reset, CLI --stdin), disable, and after a reset; `GET /api/admin/users` items carry `reset_link`
   (`{id, created_by, created_at, expires_at}` or null); `DELETE /api/admin/users/{id}/reset-link`
   (204/404, audit `user.reset_link_revoked`, user-visible). Audit details `links_revoked`.
2. Last-admin race: `accounts.begin_immediate` in PATCH/DELETE admin users and DELETE /api/me.
3. Reset link claimed first (`mark_used` checked) → no double redemption.
4. N12 reset notice: compares with the newest `login.succeeded` audit id, not `last_login_at`; tests
   no longer rewind the clock.
5. Login: `async def`, DB work in `run_in_threadpool`; cheap checks first (`_login_checks`): IP gate,
   per-IP attempt window (30/min, `IP_ATTEMPTS_PER_MINUTE`), https_required and username-delay 429
   count as IP failures; then `global_acquire_async` (anyio.sleep), then
   `passwords.verify_password_async` (polls the same 2-slot gate, hash in a thread).
6. IPv6 /64 limiter key (`throttle.ip_key`) for per-IP failures/blocks/attempts and open registration.
7. AUTH_MODE=none: DELETE /api/me → 409; startup `bootstrap.ensure_user_one`; `admin check` warns.
8. Tests: `tests/test_auth_hardening.py` (21 tests); test_auth.py hash/notice tests updated. The race
   and stall tests were checked to fail against the old behaviour.

9. Backups: `db.backup_to` → `journal_mode=DELETE`; `backup -` sets header bytes 18/19 to 1
   (`admin.rollback_journal_header`); `restore-check` opens read-only files `immutable=1` (unless a
   -wal exists) and says when keys were not checked. Test in tests/test_admin_cli.py.
10. Docs restore: deployment.md (secret for key check, `immutable=1` one-liner, revoke-sessions --all
    on the volume, Kubernetes stream recipe + `deploy/k8s/restore-pod.example.yaml`), handbook
    backups.md; podman debug command (`--entrypoint sh --user 10001:0`).
11. Deploy: dependabot pip only `/.github`; `.github/workflows/refresh-locks.yml` (weekly, P7D cooldown
    via `PIP_UPLOADED_PRIOR_TO`, opens PR); `scripts/lock.sh` pins pip 26.2.1, also compiles
    handbook/requirements.lock, passes PIP_UPLOADED_PRIOR_TO into the container. actionlint + zizmor
    --offline clean. Rootless Docker proxy trust (security.md row + checklist, deployment.md, https.md,
    troubleshooting, handbook docker-rootless/security, run script `TRUSTED_PROXIES` overridable and
    re-run replaces the container). podman-compose >= 1.5.0 notes + chcon fallback. HOLD_LATEST gate
    in release.yml + v0.2 auto-update warnings (CHANGELOG, README, deployment.md step 0). cosign >= 3
    (SECURITY.md, verify-image.sh checks the version, handbook). Cilium `fromEntities: ingress` policy.
    Tests in tests/test_deploy.py (52 pass).

12. Frontend: `POST /api/auth/reset/info` (server + mock) and the reset screen shows the username
    (read-only autocomplete=username, welcome wording, toast names the username); field-level errors
    (`.field-error`, aria-describedby, prefix dropped, scrolled into view); change screen intro for
    admins + "Account: …"; focus after sign-in and after re-auth; reload notice after deleting the
    account; none mode hides delete. Settings: open reset/setup links per user with Revoke and a
    warning in your own row; audit rows name the target ("Account disabled · Gran (gran)", "deleted
    user #N", "by mum"); personal activity server filter (audit.list_events) + "by an admin";
    Connection row from location.protocol; Food data OFF sentence; invites "Paused" when closed;
    invite ttl omitted unless touched and invite form waits for server settings; "Sign out all my
    devices" → signOut; About/who re-render after a name change; This device re-renders via
    `KH.pwa.onStateChange` (pwa.js); panel title "Install this app" (handbook refs updated); header
    brand: tab padding 10px and name hidden at 720-960 px. Mock twin keeps reset_link/voiding.
    Verified: scratch `ui_check.py` (port 8170) 25/25 in Chromium; `brand_check.py` (8171).
13. Docs: ARCHITECTURE.md (decisions 5 and 7, public routes, throttling, last-admin rule, auth/me/admin
    tables, CLI, sign-in screens), docs/accounts.md, handbook users-and-keys, CHANGELOG "Fixes from
    the M1 review". ci.yml kubeconform also checks restore-pod.example.yaml.
14. Lint: kubeconform 12/12 valid, hadolint, actionlint, zizmor --offline, shellcheck, yaml_parse clean.

15. Final verification: `python -m pytest` 1259 passed, 1 skipped (M2 guidance topics), 1 handbook
    UserWarning; `node tests/js/run_vectors.mjs` 5153 + 136; `python scripts/build_preview.py`
    (710,174 bytes); handbook `build_handbook.py --check` + `mkdocs build --strict` OK;
    `tools/e2e/parity.py --port 8172 --static-port 8173` 5897/5897; `regress.py --no-pytest --port
    8174` 413 passed; `sandbox.py --workers 4 --port 8175` 17 walks + 3 sweeps + probes, 0 issues;
    live flood (`$SCRATCH/m1/m1-fixer/flood_live.py`, port 8176, 80 threads): /healthz max 0.08 s,
    signed-in foods max 0.01 s. No servers left running.

## Left for others

* Owner decision before tagging v0.3.0: set the repository variable `HOLD_LATEST=true` for a while,
  or rely on the upgrade warnings (ARCHITECTURE.md decision 7).
* `refresh-locks.yml` and the new `scripts/lock.sh` paths were not run end to end here (no container
  engine or Python 3.14 in this sandbox); `pip-compile` + `PIP_UPLOADED_PRIOR_TO` was checked by hand
  with pip 26.2.1 and pip-tools 7.6.1. zizmor ran `--offline` only. `docker compose config` was not
  run (no Docker here; compose.yaml changed only in comments).
* Not done (LOW, cosmetic): the This device panel still repeats "Open in the browser" next to the
  install panel; the sign-in screen gives no hint that a migrated v0.2 install's admin is `admin`.
* Final: pytest, node vectors, build_preview, linters (bins in `$SCRATCH/m1/m1-integrate/bin`), e2e.

## Decisions

* Links of a removed admin are deleted (like invite revoke), reset links of an account are marked used.
* anyio is used directly (already a pinned transitive dependency of Starlette); not added to
  requirements.in.
* Per-IP attempt budget 30/min (generous: a household behind one NAT), on top of the failure block.
* `POST /api/auth/reset/info` (POST so the token stays out of URLs and logs) instead of putting the
  username in the link; invalid tokens count as per-IP failures.
* The "field: " prefix is dropped in the UI, not in the server's messages (API clients and the demo
  twin keep the same texts).
* N12 notice without a schema change: compare with the newest `login.succeeded` audit id (m003 is not
  edited; no new migration step needed).
* AUTH_MODE=none: refuse DELETE /api/me (409) rather than wiping data and keeping user 1.
* Personal activity (`/api/me/activity` and the export's `activity`) is filtered server-side to events
  about the own account plus own actions not on another account.
* Dependabot: option (b) of the finding (weekly refresh workflow with a cooldown), not renaming the
  locks to .txt (decision 5 names `.lock`).
* `:latest`: default behaviour unchanged (decision 7); `HOLD_LATEST` lets the owner hold it.
