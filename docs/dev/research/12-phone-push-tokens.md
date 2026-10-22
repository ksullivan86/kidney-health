# 12 · Sending weights and blood pressure from an iPhone (Shortcuts now, the iOS app later)

| | |
|---|---|
| Status | Decided 2026-10-22 (§8), to be built in one part. |
| Date researched | 2026-10-22, against `main` at `1e1ca32` (note 10 Part A merged) |
| Scope | Per-person **device tokens** with one narrow scope, `body:write`. An ingest route outside `/api`, `POST /push/v1/body`, that takes a few weights and readings and answers only with counts. A "same reading" check so a pushed reading and the same reading imported later from the Health export are one row. Settings → **Phone shortcuts** to make, list and revoke the tokens and to delete what one sent. The admin's instance switch. A Shortcut recipe in the handbook. |
| Out of scope | Reading anything with a device token (it is write-only). Food logging, labs or symptoms from a Shortcut: later scopes, §7. A native iOS app (ROADMAP; this is the path it will send HealthKit readings through, §7). Push notifications from the server. Glucose, insulin and medicines (CLAUDE.md: no dosing data; the route refuses every other kind). Sending readings to an AI provider or the assistant (note 10 §4.9 stands). |
| Builds on | `app/auth/api_tokens.py`: the assistant tokens, their hash-only storage, expiry, `revoke_all`, the generic 401 and the sign-in throttle. `app/body.py`: the rows, the per-day limits, `source_key`, the batch insert. `js/engine/apple_health.js`: the context rule by time of day, `isWatchSource`. Note 10 §4.1, 4.8 and 4.9. |
| Re-verify | On a real iPhone (the owner), with the iOS version of the day: the Shortcuts action names in the handbook recipe; that "Find Health Samples" gives the value, unit, start date and source the recipe sends; that a personal automation can run without asking. |

---

## 1. Context

The owner's idea (ROADMAP "Live push from an iPhone Shortcut"): the latest weight or blood pressure goes to the person's own server without opening the app and without an export. The ROADMAP's iOS app line builds on the same thing: "the app sends readings without the person's password or session".

The assistant tokens of 0.4.0 already do most of the hard part. They are made by the person, stored as a hash only, shown once, expire, end on a password change and give the same 401 for every failure. But they work only at `/mcp` and carry assistant scopes. A token on a phone's Shortcut is exposed to more: it sits in the Shortcut's text, and it can be shared with the Shortcut by mistake. So it must be able to do as little as possible.

## 2. Facts used

| # | Fact | Source |
|---|---|---|
| P1 | Shortcuts can read Health samples ("Find Health Samples", with type, sort and limit) and send JSON with headers ("Get Contents of URL": method, headers, request body JSON). Personal automations can run at a time of day. | Apple, Shortcuts User Guide: "Use Health actions in Shortcuts", "Request your first API in Shortcuts", "Create a new personal automation in Shortcuts on iPhone" (re-verify above) |
| P2 | Health exports write a sample's start date as `YYYY-MM-DD HH:MM:SS +HHMM`, the person's own wall-clock time. Shortcuts formats dates with "Format Date" (ISO 8601 gives `YYYY-MM-DDTHH:MM:SS±HH:MM`). | Note 10 §4.8; Apple Shortcuts "Format Date" action |
| P3 | Cuffless watch and ring readings are not trusted as a blood pressure source (note 10 Q-decision; the import starts them unticked). | Note 10 F-series and §4.8 |

## 3. Goals

1. A person can make a Shortcut that sends their latest weight, their latest blood pressure, or both, each morning or when they tap it, to their own server. It needs no password and no session.
2. A leaked device token can only add plausible weights and readings to one person's log, at a limited rate. It cannot read anything, change or delete a row, or reach any other route. The person can see each token's last use and revoke it. They can delete everything it sent in one step.
3. Sending the same reading twice, or importing the Health export after pushing, does not make duplicates.
4. Everything is off until the admin turns it on (least trust, like assistant access).
5. The pieces are general: a token family with scopes and a versioned ingest route. The iOS app and later scopes reuse them without a redesign (§7).

## 4. Design

### 4.1 Tokens (`app/auth/api_tokens.py`: the same table, a second family; no new table)

* **Scope and prefix.** A new scope, `body:write`. Tokens of this family start with `khd_` ("device"); assistant tokens keep `kha_`. Each family has its own pattern (`khd_` + 43 base64url characters). The prefix tells a person, and a secret scanner, which kind of token leaked.
* **Families do not mix.** `parse_scopes` keeps `assistant:log` ⇒ `assistant:read` and nothing else, so a device token never gains an assistant scope. `authenticate(request, conn, scope)` checks the scope's family switch (§4.4) and the prefix pattern of that family before any lookup.
  * A `kha_` token at `/push` is refused before any lookup.
  * A `khd_` token at `/mcp` is refused the same way.
  * Both get the same generic 401 and count toward the sign-in throttle.
* **Limits.**
  * At most 5 active tokens per family per person (`MAX_ACTIVE` becomes per family).
  * Expiry 30, 90 (default) or 365 days, as today.
  * `last_used_at` is written at most once a minute.
  * Revoked and expired tokens are kept 30 days.
* **Revoking and seeing tokens.**
  * `revoke_all` already ends every row of a person (password change or reset, account disabled or deleted, the admin's "Revoke assistant tokens"). It now ends both families. The admin button and its audit reason become "Revoke tokens" (wording only).
  * `GET /api/me/tokens?family=device|assistant` lists one family. Without the parameter it lists `assistant`, as the screen expects today.
  * `POST /api/me/tokens` takes `family`, default `assistant`. A device token's scopes are always exactly `["body:write"]`; the request cannot choose them.
  * Making a token needs a recent sign-in, as today (`RecentUser`), and is audited as `api_token.created` with `family`.
* **No migration for the tokens.** The `scopes` text column holds `body:write`, and the prefix and family are derived from it.

### 4.2 The ingest route (`app/push.py`, router mounted at `/push/v1`, outside `/api` like `/mcp`)

`POST /push/v1/body`, with `Authorization: Bearer khd_…` and `Content-Type: application/json`:

```json
{
  "weights":  [{"at": "2026-10-22T07:15:00-04:00", "value": 154.3, "unit": "lb", "source": "Health"}],
  "readings": [{"at": "2026-10-22T07:20:00-04:00", "systolic": 122, "diastolic": 78, "source": "Omron Connect"}]
}
```

* **Auth.** Only the bearer dependency (`authenticate(..., scope="body:write")`). The route never reads the session cookie, so a browser cannot be made to post to it (no CSRF surface). Every other route still ignores `Authorization` (unchanged). The CSRF and Origin checks of the `/api` middleware do not apply, as for `/mcp`. Check `main.py` and test that a cookie-only request is a 401.
* **Body.**
  * The body is a JSON object of at most 32 KiB; anything larger is 413 before parsing. It holds at most 50 rows in all, and unknown fields are 400 (`extra="forbid"`).
  * `at` is ISO 8601 with a UTC offset, or `Z`. The row's `date` and `time` are the wall-clock time **as written in that offset** (P2), not converted. A date more than one day after the server's today, or before 1900, is a 400. A time without an offset is a 400 too ("send the time with its zone"): the wall clock would be a guess.
  * `value` is a number or a plain decimal string (`^\d{1,3}(\.\d{1,3})?$`, because Shortcuts may send text). `unit` is exactly `kg` or `lb` (`lb` × 0.45359237, note 10 F7). The value is rounded half up to 0.01 kg (the server's `round_kg`).
  * `systolic` and `diastolic` are whole numbers. A string of digits is accepted, and a fraction is a 400.
  * `source` is 1 to 60 characters, cleaned like a token name. It is for the person and the duplicate check, and is never shown as HTML.
* **Validity.** The same ranges and per-day limits as every weight and reading (`app/body.py`), using the existing validators so the rules cannot drift.
  * Weight is 20 to 400 kg. Systolic is 50 to 300 and diastolic 20 to 200, with systolic greater than diastolic.
  * At most 20 weights and 30 readings on one day.
  * The context comes from the time, by the reader's rule: weight is `morning` from 04:00 to 10:59, else `other`; a reading is `morning` from 04:00 to 10:59, `evening` from 17:00 to 23:59, else `other`. It moves into `app/body.py` as `context_for(kind, time)`, and `js/engine/apple_health.js` is checked against it by new vectors in `tests/data/body_vectors.json`.
  * A reading whose `source` is watch-like (the reader's `isWatchSource`, moved to `app/body.py` with a twin and vectors) is **not stored**. It is counted as `refused.watch` (P3): a Shortcut cannot ask the person to tick a box.
* **All or nothing**, as the batch routes: the first invalid row is a 400 naming it (`weights.0.at: …`), and nothing is written.
* **Rows written.**
  * `source = 'shortcut'` (a new value of `BodySourceKey`; the column has no CHECK, note 10 §4.1). `api_token_id` is the token's id (§4.3).
  * `source_key` = the first 32 hex characters of the SHA-256 of the same text the Health export reader builds (note 10 §4.8):
    * `HKQuantityTypeIdentifierBodyMass|<at as YYYY-MM-DD HH:MM:SS +HHMM>|<value as sent>|<source>` for a weight;
    * `BloodPressure|<at as YYYY-MM-DD HH:MM:SS +HHMM>|<systolic>/<diastolic>|<source>` for a reading.
  * When the Shortcut's value and source text match the export's, a later import skips the row by key. When they do not, the same-reading check below catches it.
* **The same reading** (new, §4.3). A row is already there when the person has a weight with the same date, the same `HH:MM` and the same kg (after rounding), or a reading with the same date, `HH:MM`, systolic and diastolic, from any source except `manual`. It is counted, not added.
* **Answer.** 200 with only counts: `{"added": {"weights": n, "readings": n}, "already_there": {...}, "refused": {"watch": n}}`. No row, no id, no flag and no name are echoed, so the token reads nothing.
* **Rate limit.** 60 requests an hour per token (`register_limit("push_body", 60, 3600, ...)`, keyed by token id). The body routes' own per-person limit is separate. The sign-in throttle already counts refused tokens by address.
* **Errors** follow the app's problem shape (`{"detail": ...}`, field names in `rows.N.field` style). The 401 is the generic one with `WWW-Authenticate: Bearer`.

### 4.3 Storage (schema step 19, `m019_body_token.py`, append-only)

* `ALTER TABLE weights ADD COLUMN api_token_id INTEGER REFERENCES api_tokens(id) ON DELETE SET NULL`, and the same on `blood_pressures`. Partial indexes on `(user_id, api_token_id) WHERE api_token_id IS NOT NULL`.
* An index `weights(user_id, date, time)` and `blood_pressures(user_id, date, time)` for the same-reading check, if the step 18 indexes do not already cover it (check).
* **The same-reading check applies to the batch import routes too** (Part A's `/api/body/*/batch`). Those count it as `skipped`, as a known `source_key` is today, so "import after push" adds nothing twice. Manual entries are never matched: a person may type the same reading twice on purpose, and it stays theirs to delete.
* **Export and import.** The export's weights and readings gain nothing: `api_token_id` is a server-local id and is not exported. `source: "shortcut"` is exported and imported like the other sources.

### 4.4 Settings and the admin switch

* **Instance switch** `push.enabled` (scope `instance`, default **off**, env `PUSH_ENABLED` wins, like `assistant.enabled`). It sits on the admin settings page: "Let people send weights and blood pressure from a phone shortcut". While it is off:
  * `/push/v1/body` gives the generic 401 to every request, and nothing is looked up;
  * Settings shows the section with "Your admin has not turned this on".
* **Settings → Your data → Phone shortcuts** (a block in the same style as Assistant access):
  * **What it does**, in plain words: "A shortcut on your iPhone can send your latest weight and blood pressure here. Its token can only add readings: it cannot see your log."
  * **Make a token**: name (for example "Morning weight"), and expiry 30, 90 or 365 days. The token is shown once with a Copy button, together with the address to send to: this server's origin + `/push/v1/body`, from `location.origin`. Below it: "It is shown only now. Paste it into your shortcut."
  * **The list**: each token's name, prefix, created, last used and expires, with **Revoke**, and **Delete what it sent** (a confirm step that names the count). Deleting calls `DELETE /api/me/tokens/{id}/body-rows`, which is `current_user`, scoped by `user.id`, not-yours is 404, and is audited as `body.token_rows_deleted` with the counts.
* A **link to the handbook recipe** (§4.5).
* **Where the rows show.** The weight and blood pressure screens show the source as "from a shortcut (Morning weight)" where they show "from the Health app" today. The token's name comes from `GET /api/body/*`, whose rows gain `via` (the token name, or `null` once the token is purged). It is drawn with `textContent`.

### 4.5 The handbook (`handbook/docs/app/` weight and blood pressure page, a "From a shortcut" section)

* **A step-by-step recipe** for "Latest weight": Find Health Samples (Weight, Start Date, Latest First, Limit 1); Get Details of Health Sample (Value, Unit, Start Date, Source); Format Date (ISO 8601, with time); Dictionary; Get Contents of URL (POST, header `Authorization: Bearer <token>`, Request Body JSON). Then the same for blood pressure, and a personal automation at a time of day.
  * The text says action names can differ between iOS versions. `handbook/REVIEW.md` records the owner's real-phone check.
* **The phone must reach the server.** On the home network, or through the VPN the server is reached by. A server on a private network is not reachable from mobile data without one, and the page says so.
* **What the token can do** (add only) and what to do if the phone is lost or the shortcut was shared: Revoke, then Delete what it sent.
* **The app does not watch these readings.** A pushed reading of 180/120 or higher shows its flag the next time the app is opened, nothing more. The page points to Get help now, in its own words, as the rest of the weight and blood pressure page does.
* No new clinical number. The page cites note 10's sources where it repeats one.

### 4.6 The demo (GitHub Pages)

The demo has no server to push to. Settings shows the Phone shortcuts block with the same "The preview has no server…" pattern as Import from a file. The mock answers `GET /api/me/tokens?family=device` with an empty list and refuses to make one, with the preview's message. No JS twin is needed for `/push` (no browser code calls it). The `context_for` and `isWatchSource` vectors keep the reader and the server in step.

## 5. Security review (least trust)

| Threat | Answer |
|---|---|
| A token leaks (shared shortcut, lost phone) | Add-only, 50 rows a request, 60 requests an hour. Plausible ranges and per-day caps. Visible last use. Revoke, and Delete what it sent. Expiry of at most 365 days. Every token ends on a password change. |
| False readings planted to alarm or mislead | Only within the ranges and per-day caps. Each row is marked "from a shortcut (name)", so the person can see where it came from and delete it all. Nothing is acted on automatically. |
| Token used elsewhere | Family prefix and scope checked before lookup. `/mcp` refuses `khd_`, `/push` refuses `kha_`, and every `/api` route ignores `Authorization` (existing test extended to the new prefix). |
| Guessing or brute force | 256-bit tokens, hash lookup, generic 401, the address throttle, 429 with `Retry-After`. |
| CSRF or browser abuse | The route reads no cookie; a cookie-only request is 401. CORS is not enabled, and it is not needed because Shortcuts is not a browser. |
| Data leak through answers | Counts only. No echo of rows, names, flags or ids. |
| Health-data rules | Only weights and blood pressure. Every other kind is a 400 by `extra="forbid"`. No glucose, insulin or medicines. Not sent to AI or the assistant. Never logged: the route logs only the token id and counts, never values (test). |

## 6. Tests (`python -m pytest`, no network)

* **Tokens:**
  * a family's prefix and scope;
  * a `kha_` token at `/push` is 401 and a `khd_` token at `/mcp` is 401, both throttled;
  * per-family `MAX_ACTIVE`;
  * `revoke_all` ends both families;
  * the list filters by family;
  * a device token's scopes cannot be chosen;
  * a recent sign-in is needed to make one.
* **The route:**
  * switch off gives 401 with no lookup, and on gives 200;
  * a cookie-only request is 401;
  * the 32 KiB cap gives 413, and over 50 rows gives 400;
  * `at` parsing (offsets, `Z`, no offset is 400, wall clock kept, future and 1900 bounds);
  * `lb` to kg and rounding;
  * string numbers, and a fraction in a reading is 400;
  * the watch source is refused and counted;
  * all or nothing;
  * per-day limits;
  * the rate limit is 429 after 60;
  * the answer holds counts only;
  * values never reach the log (caplog).
* **The same reading:**
  * push then import of the same reading gives one row;
  * import then push gives one row;
  * a manual twin is not matched;
  * `source_key` equals the reader's for matching text (a vector shared with `apple_health_vectors.json`).
* **Migration step 19:** an upgrade from step 18 with rows. Deleting the token sets `api_token_id` to null. "Delete what it sent" removes only that token's rows of that person, and a token that is not yours is 404.
* **Vectors** for `context_for` and `isWatchSource` (Python and JS), and `node tests/js/run_vectors.mjs`.
* **UI:**
  * the Phone shortcuts block (make, show once, copy, list, revoke, delete-what-it-sent confirm);
  * the switch-off text;
  * the demo text;
  * `via` drawn with `textContent`;
  * a browser walk in `tools/e2e/` that makes a token, `curl`s the route like a Shortcut and sees the row on the weight screen marked "from a shortcut".
* **Handbook:** the recipe page builds, the links resolve, and a REVIEW.md row is added for the real-phone check.

## 7. How this carries to the iOS app and later scopes (reuse)

* **iOS app.** The ROADMAP's Swift shell (`WKWebView` around the person's server) keeps the PWA for every screen. HealthKit background delivery posts new samples to the same `POST /push/v1/body`, with a `khd_` token kept in the iOS Keychain.
  * Pairing is a later small step. The web page, signed in, hands a freshly made device token to the native shell through `window.webkit.messageHandlers`, so the person never copies a token.
  * The route, its limits and the same-reading check are the whole server side of the app's Health sync.
* **Later scopes** follow the same pattern: one family, one scope, one versioned route under `/push/v1/`, add-only, counts-only answers. Examples are `log:write` ("I ate this", from a Shortcut or the app), `labs:write` (HealthKit clinical records) and `symptoms:write`. A general meal tracker built on this server gets device ingest for free.
* **Versioning.** `/push/v1` is a promise. A breaking change gets `/push/v2`, and v1 keeps working for at least one release.

## 8. Decisions (2026-10-22, the owner's standing "recommended least-trust choice")

1. **One token table, a second family** (`khd_`, `body:write`) instead of a new table. Revocation, expiry, housekeeping and the 401 are reused, and the prefix and scope keep the families apart.
2. **The route lives outside `/api`**, like `/mcp`. Every `/api` route stays session-only (CLAUDE.md), and the bearer route never reads a cookie.
3. **Add-only, counts-only.** No read scope for devices.
4. **Off by default** (instance switch), like assistant access.
5. **Watch-like sources are refused**, not stored unticked, because a Shortcut has no review step (note 10's distrust of cuffless readings).
6. **A same-reading check** for every non-manual source, applied to the batch import too, so "push, then import" does not duplicate.
7. **The token's rows can be deleted together** (`api_token_id`, schema step 19).
