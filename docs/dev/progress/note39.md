Status: complete

# note39: design note 39, the iPhone app with a server, both ways

Role: `note39`. Branch: the worktree branch `worktree-agent-ade74ad8f65c9263a`. Commit own paths only. No push, no PR.
Task: write `docs/dev/research/39-iphone-app-with-a-server.md` (no code changes), a one-line pointer in note 38's status line.

## Done

* Read: CLAUDE.md, ARCHITECTURE.md (Identity and request rules; AI routes and routing; device tokens, `/push/v1/sync`;
  offline edits and deletes; Device mode), note 38 (all), note 02 R5, note 12 §5, §7, §8, `app/auth/api_tokens.py`,
  `app/migrations/m037_app_sync.py`, `app/static/js/mock/server_sync.js`, `ios/KidneyHealth/Services/ServerSync.swift`,
  `docs/push.md` (proxy and the second Caddy host).
* There is no research index file (`docs/dev/research/` has no README). The handbook bibliography lists notes only when the
  handbook cites them, so note 39 is not added there.

## Decisions taken in the note (and why)

* Auth: the app token gets a new scope `app:sync` (new tokens of a new kind; old ones are never widened) and a bearer gateway
  `/push/v1/api/...` that runs an allow-list of `/api` routes as the token's person. Why: keeps `/api` cookie-only, works
  through reverse proxies and the second Caddy host that already pass `/push/v1/`, no copied route logic, least privilege
  (no re-auth or admin routes). A held session was rejected (full account power, 30/14-day expiry breaks sync, the whole app
  must face the internet); a new OAuth-style token kind was rejected (a third family for no gain).
* Server switch `push.app_sync` (off by default), like every other server feature.
* AI: server's AI when paired, reachable and the feature is available there; else the iPhone's own; a setting "Use only this
  iPhone's AI". Lab text only to the server's local-only lab routes or the iPhone's own model. Only network failures and
  "not available" fall back; safety cards never do.
* Food services: through the server when connected; offline the phone's own keys if set, else the built-in list.
* Sync: `client_id` on every synced table (receipts carry over), a change feed with a per-person cursor and tombstones
  (triggers, so no writer is missed), content versions for every kind (note 02's entry version generalised), If-Match,
  conflict card reused. Profile, targets and settings stay server-owned and online-only to edit.

* Wrote `docs/dev/research/39-iphone-app-with-a-server.md` (§1 to §13: facts, auth options, gateway, AI, food services,
  sync, safety review, changes by part, a 9-step plan, decisions D1 to D9, two open questions).
* Note 38's status line points to note 39.
* Checked: the Caddy example lists the phone's paths one by one, so the note says it must add the new ones.
  No test reads research notes; pytest is not installed in this worktree, and this change touches docs only.

## Next

* Nothing. The build follows note 39 §11, one PR per step.
