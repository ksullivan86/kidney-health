Status: complete (2026-10-30): sign-in with a provider (design note 24), server, screens, docs, tests and a Chromium walk.

# OIDC sign-in (design note 24)

Owner request: "can we add integration with oauth so we could setup google login like I did with netbird or use my authentik
instance". Branch: worktree-agent-ab043c4f8b74d7667 (local commits only, no push, no PR).

## Done

1. Design note `docs/dev/research/24-oidc-sign-in.md`. Decision: no new dependency (JWS on `cryptography`).
2. Server: `OidcEnv` in app/config.py (env only, secret only as `_FILE`), registry keys `auth.oidc.*` + JS twin + settings vectors,
   step 26 `m026_oidc.py` (oidc_links, sessions.signed_in_with), `app/auth/oidc.py` (discovery, JWKS cache with refresh on unknown
   kid at most once a minute, PKCE, token exchange via CheckedTransport, JWS RS/PS/ES/EdDSA, claim checks), `app/auth/oidc_api.py`
   (routes, account rules), admin removal + `oidc_links` count + About `oidc`, two-step exemption for OIDC sessions, passwordless
   DELETE /api/me, brand cookie names, `security.PROVIDER_RETURN_PATHS` (the callback may be a cross-site top-level navigation).
3. Screens: `js/views/oidc.js`, sign-in button (relative link), invite button, re-auth button, Settings → Linked sign-in, People
   badge and removal, About lines, activity labels, demo answers.
4. Deploy: compose pass-throughs + commented secret, .env.example section, Quadlet, k8s Deployment and Secret comments.
5. openapi.json regenerated; auth coverage PUBLIC list and isolation matrix updated.
6. Chromium walk `tools/e2e/oidc.py` (14 checks pass). It found the cross-site guard refusing the callback (fixed in 2).
7. Docs: ARCHITECTURE, docs/accounts.md, docs/deployment.md, docs/security.md, docs/network-allowlist.md, handbook users-and-keys
   (+ NOTE24 source), CHANGELOG Unreleased, ROADMAP, tools/e2e/README.md.

## Decisions

* Connection settings env only; who-may-sign-in rules in the registry.
* OIDC_ONLY out of scope (lockout risk).
* Accounts made by OIDC keep auth_source 'local'; links in `oidc_links`; links are not in the export.
* Flow state in memory (like passkey challenges) + a binding cookie `__Host-kh_oidc`.
* OIDC sessions exempt from `auth.require_two_step_admins` (provider's factors), recorded as an open question.

## Checks

```
PY=/tmp/claude-0/-home-user-kidney-health/8a6bc573-c86c-5a92-a072-0545790bf9a4/scratchpad/venv312/bin/python
$PY -m pytest -q tests/test_oidc.py tests/test_oidc_ui.py tests/test_migration_m026.py tests/test_auth*.py tests/test_isolation*.py \
  tests/test_security.py tests/test_settings*.py tests/test_deploy.py tests/test_compose_env.py tests/test_config_secrets.py ...
node tests/js/run_vectors.mjs; node --test tests/js/*.test.mjs; $PY scripts/gen_openapi.py --check; /root/.local/bin/ruff check .
python3 tools/e2e/oidc.py --out <scratch>/oidc-walk
```
