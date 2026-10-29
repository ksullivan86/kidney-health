Status: in progress (2026-10-29): design note 18 written; server being built on the local branch `passkeys-local` while PR #104
(admins must use two-step) waits for CI. After #104 merges: `git rebase --onto origin/main 3625ad0 passkeys-local`, then push to
`claude/adoring-sagan-th5swr`.

# Passkeys (design note 18)

## Plan

1. `app/auth/webauthn.py`: CBOR reader, COSE keys, registration and assertion checks; tests against `tests/data/webauthn_w3c_vectors.json`.
2. Schema step 23 (`m023_passkeys.py`), `app/auth/passkeys_api.py` (`/api/me/passkeys*`, `/api/auth/passkey*`), admin removal, CLI
   `remove-passkeys`, audit actions, OpenAPI.
3. Screens: sign-in button, Settings → Passkeys, admin People, demo; Chromium with a virtual authenticator.
4. Docs: ARCHITECTURE, docs/accounts.md, handbook, CHANGELOG, ROADMAP.

## Done

* Design note 18; W3C vectors saved (`tests/data/webauthn_w3c_vectors.json`, from WebAuthn L3 §16, read 2026-10-29).

## Reproduce

```bash
python -m pytest -q tests/test_webauthn.py tests/test_passkeys.py
```
