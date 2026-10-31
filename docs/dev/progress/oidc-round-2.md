# oidc-round-2 progress

Status: in progress

Branch: worktree branch started from `next-8` (0.14.0). Task: several OIDC providers (up to 4), `OIDC_ONLY`, never-expiring
tokens, docs (README row, accounts.md "If it doesn't work"), tests.

## Design decisions (also written to note 24 §13 when done)

* Providers: the old `OIDC_ISSUER…` variables stay the first provider (id `default`, callback `/api/auth/oidc/callback`, its
  label/domains/groups/sign-up from the registry `auth.oidc.*`). `OIDC_PROVIDERS=authentik,google` adds named ones, each with
  `OIDC_<NAME>_ISSUER`, `_CLIENT_ID`, `_CLIENT_SECRET_FILE`, `_SCOPES`, `_ALLOW_PRIVATE_ISSUER` (connection, per provider) and
  `_BUTTON_LABEL`, `_ALLOWED_DOMAINS`, `_ADMIN_GROUPS`, `_ALLOW_SIGNUP` (overrides of the server-wide registry settings).
  Callback for a named provider: `/api/auth/oidc/callback/<name>` (own redirect URI = mix-up defence, RFC 9700 §4.4).
  `link_by_email` stays server-wide only. At most 4; the same issuer twice refused. No migration (oidc_links keyed by issuer).
* One FlowStore shared; each flow records its provider; `take()` refuses another provider's flow without consuming it.
  Per-provider cap = MAX_FLOWS // number of providers; per-address cap across all. `oidc_start_all` limit keyed per provider.
* `OIDC_ONLY` (env only): /login refuses passwords except test accounts; /register with a password refused; reset/setup links
  still work (admin-made, one time); passkeys allowed; first-run setup allowed. Start-up refuses OIDC_ONLY without a provider.
* Tokens: `expires_in_days: "never"`; stored with sentinel `9999-12-31T23:59:59.999999Z` (expires_at is NOT NULL; no migration);
  API shows `expires_at: null`. Setting `tokens.allow_no_expiry` (env `TOKENS_ALLOW_NO_EXPIRY`, default on). Both families.

## Done

## Next
