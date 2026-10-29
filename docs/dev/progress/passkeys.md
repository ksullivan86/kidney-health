Status: complete (2026-10-29): passkeys built (design note 18), server and screens; full pytest, the W3C vectors and the Chromium walk pass.

# Passkeys (design note 18)

## Done

* `app/auth/webauthn.py`: the WebAuthn RP checks (§7.1, §7.2), a CBOR reader, COSE keys (ES256/384/512, RS256, EdDSA), on
  `cryptography` only. Verified: `tests/test_webauthn.py` against `tests/data/webauthn_w3c_vectors.json` (WebAuthn L3 §16) and a
  software passkey (`tests/webauthn_support.py`). The W3C vectors set the flags at random, so the tests pass `require_uv=False` for
  the signature checks and check separately that a vector without UV is refused when UV is required (the routes always require it).
* Schema step 23 (`m023_passkeys.py`), `app/auth/passkeys.py` (storage, in-memory challenges), `app/auth/passkeys_api.py`,
  `DELETE /api/admin/users/{id}/passkeys` and `passkeys` in the people list, CLI `remove-passkeys`, `passkey.*` audit actions,
  `passkeys` in `/api/auth/status`, OpenAPI lists and `docs/api/openapi.json`. Verified: `tests/test_passkeys.py`,
  `tests/test_migration_m023.py`, the auth coverage, isolation matrix and OpenAPI tests.
* Screens: `js/views/passkeys.js` (Settings block, `KH.passkeys.signIn`), the sign-in button, the People badge and removal,
  activity labels, the demo's answers, CSS. Verified: `tests/test_passkeys_ui.py`, `tools/e2e/passkeys.py` (26 checks, Chromium's
  virtual authenticator).
* Docs: ARCHITECTURE, docs/accounts.md, CHANGELOG, ROADMAP, handbook settings-and-keys, users-and-keys, troubleshooting, NOTE18
  source, tools/e2e/README.md.

## Decisions

* No `webauthn` package (it adds cbor2, pyOpenSSL, pyasn1, pyasn1-modules); attestation is not checked.
* The user handle is random, kept per row and reused for a person's later passkeys.
* RP ID and origin come from `PUBLIC_URL`, else the request; an IP address cannot carry passkeys, so Settings says why.

## Reproduce

```bash
python -m pytest -q tests/test_webauthn.py tests/test_passkeys.py tests/test_migration_m023.py tests/test_passkeys_ui.py
python tools/e2e/passkeys.py
```
