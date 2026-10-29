Status: in progress

# Security review of the newest server features

Branch `worktree-agent-ac13f3ce2566e6259` (worktree `.claude/worktrees/agent-ac13f3ce2566e6259`), merged
`claude/adoring-sagan-th5swr` at 289c2b3 first. Commits stay local.

Scope: caregiver sharing (note 19), passkeys and two-step sign-in (notes 17, 18), device tokens, `/push/v1` and
QR pairing (note 12, pairing), assistant tokens and `/mcp`, `record-backup` and `GET /api/admin/about`.

Method: read the code; prove each suspected bug with a test against the real app; fix only what a test shows.

## Checked so far

* `app/sharing.py`: link entropy (64-bit id + 256-bit verifier, hash only, compared in constant time), 7-day expiry,
  single use (accept clears the code under `BEGIN IMMEDIATE`), 20 tries an hour per account and per address,
  `shared_owner(area)` on every read, end dates (`expire` runs before every sharing route), revocation, admin removal.
* Passkeys: challenges single use, tied to kind and person, 5 minutes; origin, RP ID hash, UP and UV checked;
  counter that does not go up is refused and audited; re-auth for add and remove; another person's passkey is 404.
* Two-step: each code works once (`last_step`), wrong codes count like wrong passwords, a reset link does not skip
  the code, recovery codes about 50 bits, hashed, single use.
* Tokens: families never mix, prefix checked before lookup, every `/api` route ignores a bearer token
  (`tests/test_auth_coverage.py` walks every route with a token of each family).
* Pairing: the QR link is the device token itself (no separate code); shown once.
* `GET /api/admin/about`: admin only; holds counts and the key's source, not the key.

## Findings

1. **Low: a share without `body` showed the owner's saved weight.** `GET /api/shared/{id}/profile` is open to every
   area and returned `weight_kg`. Only the body pages use it (`visit.js` renderBody, `body_trends.js`).
   Test `tests/test_sharing_security.py::test_the_owners_weight_is_shared_only_with_weight_and_blood_pressure`
   failed for food, labs, symptoms and food+labs+symptoms. Fix: `shared_profile` sets `weight_kg` to `null` unless the
   share holds `body`. Shape unchanged; OpenAPI regenerated (description only). Docs: ARCHITECTURE sharing table,
   `docs/accounts.md`, handbook `settings-and-keys.md`, CHANGELOG Unreleased → Security.

## New tests that passed at once (the guarantee held)

* `tests/test_sharing_security.py`: every `/api/shared/{id}` read is in the area list; a one-area share opens only that
  area's routes (all four areas); an ended share is the same 404 on every route (owner stops, grantee stops, admin
  ends, end date passes, a newer link replaces it, owner's account turned off); a used link fails for a third person;
  a new account after a deleted grantee sees nothing.

## Next

1. Test that `/api/admin/about` holds no secret.
2. Full run of the touched and related test files; ruff.

## Commands

    PY=/tmp/claude-0/-home-user-kidney-health/8a6bc573-c86c-5a92-a072-0545790bf9a4/scratchpad/venv312/bin/python
    $PY -m pytest -q tests/test_sharing*.py tests/test_auth*.py tests/test_mcp*.py tests/test_push*.py tests/test_passkey*.py
    /root/.local/bin/ruff check .
