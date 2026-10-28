# Phone shortcuts: sending weight and blood pressure from an iPhone

A person can make a **device token** in Settings and paste it into a Shortcut on their iPhone. The Shortcut sends the person's latest
weight and blood pressure to their own server, without opening the app and without an export. The token can **only add** weights and
blood pressure readings to its owner's log: it cannot read anything, change or delete a row, or reach any other route.

This page is for the person who runs the server and for people who change the code. The contract is in
[`ARCHITECTURE.md`](../ARCHITECTURE.md) ("Device tokens and `/push/v1`") and the design note is
[`dev/research/12-phone-push-tokens.md`](dev/research/12-phone-push-tokens.md). The person's side is **Settings → Account → Your data →
Phone shortcuts** (make, list, revoke, delete what a token sent), the weight and blood pressure screens mark such rows "from a shortcut
(name)", and the handbook has the Shortcut recipe ("From a phone shortcut" on its Weight and blood pressure page). What nobody has done yet
is run that recipe on a real iPhone: the handbook says so and `handbook/REVIEW.md` lists the check.

## Turn it on (admin)

It is **off** until you turn it on, like [assistant access](assistant.md):

* Server administration → Server settings → **Phone shortcuts** → "Let people send weights and blood pressure from a phone shortcut", or
* `PUSH_ENABLED=true` in the environment (`deploy/.env.example`; the setting is then locked in Server administration).

While it is off nothing can be made or used: `POST /push/v1/body` answers `401` to every request, without looking anything up. Turned on
again, tokens that have not expired or been revoked work again. The Phone shortcuts block in Settings is still there while the switch is
off: it says "Your admin has not turned this on", shows no form, and lets a person revoke the tokens they have and delete what they sent
(an admin also sees where the switch is). Turning the switch on or off redraws the block and the People list at once.

**The phone must reach the server.** On your home network, or through the VPN you reach the server by. A server on a private network is
not reachable from mobile data without one. If a reverse proxy lists the paths it passes on, add `/push/v1/` next to `/mcp`; the routes
are `POST /push/v1/body` and the token check `GET /push/v1/check` (below). To let a phone reach them from beyond your LAN without
opening the rest of the app, use the commented second host name in `deploy/caddy/Caddyfile.example`; it passes only these two
requests and `POST /mcp` ([assistant.md](assistant.md)). A VPN is simpler and safer.

## What a token is

* Starts with `khd_` ("device"; assistant tokens start with `kha_`) and holds exactly one scope, `body:write`. The person does not choose
  scopes. The plain token is shown **once**, when it is made; the server keeps only its SHA-256.
* A person has at most **5 active device tokens** (5 assistant tokens besides), valid **30, 90 (default) or 365 days**. Making one needs a
  recent password (like saving a key) and is limited to 20 tokens an hour in all.
* A token has a name (for example "Morning weight"), shows when it was last used and how many weights and readings it sent that are still in
  the log, and is **revoked** at once in Settings. Every token
  also ends when its owner's password is changed or reset, when the account is disabled or deleted and when an admin presses **Revoke
  tokens** for the person (Server administration → People: it ends assistant and device tokens alike). When the server's
  sign-in mode (`AUTH_MODE`) changes, every token of every person ends at the next start.
* The rows a token sent are marked `source: shortcut` and linked to it, so the person can see where a row came from and **delete
  everything one token sent** in one step (`DELETE /api/me/tokens/{id}/body-rows`). If the token is purged 30 days after it ended, the rows
  stay and only lose its name.

**In Settings** (Account → Your data → Phone shortcuts): give the token a name, choose when it ends (30 days, 90 days or 1 year) and press
Make token. After a few minutes without a password the app asks for it again first. The token is shown **once**, with **Copy token** and
the address to send to (this server's address followed by `/push/v1/body`); paste both into the Shortcut ([the
recipe](../handbook/docs/app/weight-and-blood-pressure.md#from-a-phone-shortcut)). The list below shows each token's name, its first
characters, when it was made, last used and expires, and what it sent. **Revoke** ends it at once; **Delete what it sent** asks (naming the
count) and removes only the rows that token sent, never ones the person typed or imported. For a lost phone press Revoke, then Delete what
it sent; an ended token stays in the list for a while and still offers the second.

The screen uses these routes (a signed-in browser session; the switch on), which a script can call as well:

```
POST /api/me/tokens        {"name": "Morning weight", "family": "device", "expires_in_days": 90}
GET  /api/me/tokens?family=device
DELETE /api/me/tokens/{id}                  revoke
DELETE /api/me/tokens/{id}/body-rows        delete what it sent
```

**On the weight and blood pressure screens** a row a token sent says "from a shortcut (Morning weight)" on Today, and the tables under the
Trends charts get a "From" column while some row of the period has an origin ("from a shortcut (name)", "from the Health app" or "from a
file"). Editing a row makes it the person's own and the label goes. The label is the token's name drawn as text; a token that was purged
after it ended leaves the rows with "from a shortcut".

**The demo** (the preview build) has no server to send to: the block says so, makes no token and sends no request.

## The route

```
POST /push/v1/body
Authorization: Bearer khd_…
Content-Type: application/json

{"weights":  [{"at": "2026-10-22T07:15:00-04:00", "value": 154.3, "unit": "lb", "source": "Health"}],
 "readings": [{"at": "2026-10-22T07:20:00-04:00", "systolic": 122, "diastolic": 78, "source": "Omron Connect"}]}
```

```
curl -sS https://food.example.org/push/v1/body \
  -H "Authorization: Bearer khd_…" -H "Content-Type: application/json" \
  -d '{"weights":[{"at":"2026-10-22T07:15:00-04:00","value":154.3,"unit":"lb","source":"Health"}]}'
# {"added":{"weights":1,"readings":0},"already_there":{"weights":0,"readings":0},"refused":{"watch":0}}
```

* **`at`** is the date and time **with its zone** (`Z` or an offset). The log records the **wall clock as written** (the Health export writes
  the same), not a conversion to UTC. A time without a zone is a `400`.
* **`value`** and **`unit`** (`kg` or `lb`) for a weight; **`systolic`** and **`diastolic`** (whole numbers) for a reading. Numbers may
  be sent as text (a plain decimal such as `"154.3"`). **`source`** is the app or device the sample came from (1 to 60 characters).
* The same ranges and per-day limits as every weight and reading (20 to 400 kg; 50 to 300 over 20 to 200, the top number above the bottom
  one; at most 20 weights and 30 readings a day). The ranges are the project's own plausibility choice, not clinical numbers.
* **Only weights and blood pressure.** Any other field (`glucose`, `insulin`, `pulse`, a medicine) is a `400`. The app takes no dosing data.
* **Context** (morning, evening, other) comes from the clock time; the person is not asked. A **reading from a watch** (a source whose
  name contains "Watch") is **not stored** and is counted as `refused.watch`: cuffless readings are not recommended for checking blood
  pressure, and a Shortcut cannot ask. A weight from a watch is kept.
* **All or nothing.** The first invalid row is a `400` that names it (`weights.0.at: …`) and nothing is stored.
* **No duplicates.** Sending the same reading again, or importing the Health export after sending it (or the other way round), adds
  nothing: a row is "already there" when the person has the same key or a row that was not typed with the same day, minute and numbers.
  A reading the person typed is never matched.
* **The answer is counts only**: it never repeats a row, an id, a name or a flag, so a token reads nothing. The app does not watch
  these readings: a reading of 180/120 or higher shows its flag, with the handbook's Get help now words, the next time the app is opened.

| Answer | Meaning |
|---|---|
| `200` | counts, as above |
| `400` | a row or field is not valid (the text names it); nothing stored |
| `401` | no valid device token, or phone shortcuts are off (the same answer for every reason) |
| `403` | a browser page on another site tried it (`Origin`) |
| `413` / `415` | body over 32 KiB / not `application/json` |
| `429` | more than 60 requests an hour for this token, or too many wrong tokens from this address (`Retry-After`) |

## Testing a token

`GET /push/v1/check` with the same `Authorization: Bearer khd_…` answers `200 {"ok": true}` when the token works, and the same `401`,
`403` and `429` as above when it does not. It sends and stores nothing, and counts toward the token's 60 requests an hour. The iPhone
app's **Test connection** button uses it ([`ios/README.md`](../ios/README.md)). Any other method is a `405`.

```bash
curl -sS https://food.example.org/push/v1/check -H "Authorization: Bearer khd_…"
```

## What a leaked token can do

It can add up to 60 requests of up to 50 plausible weights and readings an hour (never more than 20 weights and 30 readings a day) to
**one** person's log, until it expires (at most 365 days) or is revoked. It cannot read the log, the profile or anything else, change or
delete a row, make or see tokens, or reach any other route (every other route ignores the `Authorization` header). The check route only says whether it works. The false rows are
marked as sent by that token, so the person can see them and delete all of them in one step. Nothing is acted on automatically. Revoke the
token (and delete what it sent) if a phone is lost or a Shortcut was shared.

Tokens are not in the export (a credential, like sessions); the rows are, as `source: shortcut`, without the token. Rows a token sent
are never sent to an AI provider or the assistant, like the rest of the weight and blood pressure log ([`privacy.md`](privacy.md)).

## For contributors

* Code: `app/push.py`, the device family in `app/auth/api_tokens.py`, `context_for` / `is_watch_source` / the same-reading check in
  `app/body.py`, schema step 19 (`app/migrations/m019_body_token.py`), the `push.enabled` key in `app/settings_registry.py`. The screens:
  `pushBlock` and the admin People and Activity changes in `app/static/js/views/settings.js`, `originText` in `app/static/js/engine/body_ui.js`
  (drawn by `views/body.js` and `views/body_trends.js`), the demo's routes in `app/static/js/mock/auth.js`.
* UI tests: `tests/test_push_ui.py` (runs `tests/js/push_page.mjs`, which executes the block against a fake page: make, shown once, copy,
  list, revoke, delete what it sent, the switch-off text, the demo text, `via` as text), the source checks in `tests/test_settings_ui.py` and
  `tests/test_body_ui.py`, and the browser walk `tools/e2e/push.py` (a real Chromium and a harness that posts like a Shortcut).
* Tests: `tests/test_push.py` (the route), `tests/test_device_tokens.py` (the family, limits, revocation, "Delete what it sent"),
  `tests/test_migration_m019.py`, the two additions in `tests/test_auth_coverage.py`, and `context_cases` / `watch_cases` in
  `tests/data/body_vectors.json` (generated by `tests/data/gen_body_vectors.py`; `node tests/js/run_vectors.mjs` holds the Apple Health
  reader's `contextOf` and `isWatchSource` to the server's `context_for` and `is_watch_source`).
* `/push/v1` is a promise: a change that breaks it gets `/push/v2`, and v1 keeps working for at least one release.
