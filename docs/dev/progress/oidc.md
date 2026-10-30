Status: in progress

# OIDC sign-in (design note 24)

Owner request: "can we add integration with oauth so we could setup google login like I did with netbird or use my authentik
instance". Branch: worktree-agent-ab043c4f8b74d7667 (local commits only, no push, no PR).

## Done

1. Design note `docs/dev/research/24-oidc-sign-in.md` (flow, checks, settings, linking, sessions, two-step, audit, proxy vs OIDC,
   Google and Authentik, risks, open questions). Decision: no new dependency (JWS on `cryptography`).

## Next

2. Config (`OidcEnv` in app/config.py), registry keys `auth.oidc.*` + JS twin + settings vectors.
3. `app/migrations/m026_oidc.py` (oidc_links, sessions.signed_in_with).
4. `app/auth/oidc.py` (discovery, JWKS, PKCE, JWS, claims), `app/auth/oidc_api.py` (routes).
5. Screens: sign-in button, invite button, Settings → Linked sign-in, re-auth sheet, About, demo.
6. Tests with a fake provider (`tests/oidc_support.py`), docs, openapi.

## Decisions

* Connection settings env-only (OIDC_ENABLED, ISSUER, CLIENT_ID, CLIENT_SECRET_FILE, SCOPES, ALLOW_PRIVATE_ISSUER); who-may-sign-in
  rules in the registry (`auth.oidc.button_label`, `allow_signup`, `link_by_email`, `allowed_domains`, `admin_groups`).
* OIDC_ONLY out of scope (lockout risk).
* Accounts made by OIDC keep auth_source 'local'; links in `oidc_links`.
* Flow state in memory (like passkey challenges) + a binding cookie.

## Checks

PY=/tmp/claude-0/-home-user-kidney-health/8a6bc573-c86c-5a92-a072-0545790bf9a4/scratchpad/venv312/bin/python
BT=/tmp/claude-0/-home-user-kidney-health/8a6bc573-c86c-5a92-a072-0545790bf9a4/scratchpad/oidc-bt
