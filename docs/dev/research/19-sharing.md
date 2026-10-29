# 19 · Read-only sharing with a caregiver or dietitian

| | |
|---|---|
| Status | Accepted and built, 2026-10-29. The owner asked for it ("go ahead with caregiver sharing") after passkeys and QR pairing. The choices below are the defaults this note took, listed in §10 so they can be changed. The schema step is **24**; step **25** adds an end date (§11). Two changes while building: the link's info and accept routes are `POST /api/shared/info` and `POST /api/shared/accept` (one router), and §5's audit rows go to the owner's activity only (the activity list finds rows by the person they concern). |
| Scope | A person lets someone else with an account on the same server **see** parts of their log: food, labs, weight and blood pressure, symptoms. The other person reads; they can never add, change or delete anything. The person can take it back at any time and sees when it was last looked at. |
| Out of scope | Writing on someone's behalf, notes from a clinician, sharing with someone who has no account, sharing across servers, an export link for people outside the server. Clinician accounts with notes (ROADMAP) build on this later (§11). |
| Builds on | Note 07 §6 "Later (v0.4)": `shares(owner_user_id, grantee_user_id, scope, created_at, revoked_at)`. `app/auth/tokens.py` (invite links), `app/auth/api_tokens.py` (the instance switch pattern), the Visit prep page (`js/views/visit.js`). |
| Sources | NIST SP 800-63B-4 §5.1.1 on secrets made by a server (the share code is a 256-bit random value, hashed at rest); OWASP ASVS 5.0 V8 (authorization: deny by default, check at the data layer, log access to sensitive data). |

## 1. Why

Many people with kidney disease have a partner, parent or adult child who helps with food, and a dietitian who wants to see
what was eaten before an appointment. Today the only way is to hand over the password or print a page. A read-only share is
safer and kinder: the helper sees what they need, cannot change anything by mistake, and the person stays in control.

## 2. How it works for a person

1. **Ana** opens **Settings → Account → Sharing → Share with someone**. She ticks what to share (food log, lab results,
   weight and blood pressure, symptoms; all ticked at first), and the page shows a **link** once, with **Copy link**. It
   works for 7 days and only once. It asks for her password again first, as making a token does.
2. She sends the link to **Sam** (a text message, in person). Sam needs his own account on the same server.
3. Sam opens the link while signed in. The app shows "Ana wants to share her food log, lab results, … with you. You can look,
   but not change anything." and **Accept** / **No, thanks**.
4. Sam now has **Shared with you → Ana** in Settings. **Open** shows Ana's summary page (the Visit prep page, read-only, with
   her name on it) and a day view of what she ate. A banner on every shared page says whose data it is and that it is read-only.
5. Ana's list shows "Sam (sam) · food log, labs, weight and blood pressure, symptoms · since Oct 29 · last looked today" and
   **Stop sharing**. Sam can also **Stop seeing** on his side. Either ends it at once.

What Sam never sees: Ana's notes about tastes and preferences, her saved meals and recipes, her AI settings or activity, her
keys, tokens, passkeys and sign-in activity, her date of birth or other profile details beyond what the pages need (§5), and
anything she did not tick. Sharing does not let Sam see anyone else's data, and Ana does not see Sam's.

## 3. The share code

* A link `/#/share/<id>.<verifier>`, the same form as invite links: the token is in the URL fragment, which browsers never
  send to the server, so it stays out of proxy logs and `Referer`. `<id>` is 16 random hex characters, `<verifier>` 32 random
  bytes in base64url. Only the SHA-256 of the verifier is stored, compared with `hmac.compare_digest`.
* Single use, 7 days, at most **5** unused codes per person and **10** people sharing a person's data at once.
* Opening it is a two-step read: `POST /api/shared/info {code}` says who and what (it does not use the code up), then
  `POST /api/shared/accept {code}` makes the share. Both need a signed-in session; both are limited to **20 tries an hour**
  for each account and each address, and every wrong code counts.
* A person cannot accept their own code (`400`), and a second code from the same person replaces the areas of an active share
  rather than making a second one.

## 4. Storage (schema step 24)

```sql
CREATE TABLE IF NOT EXISTS shares (
  id INTEGER PRIMARY KEY,
  owner_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  grantee_user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,  -- NULL while the code is unused
  code_id TEXT UNIQUE,                    -- the <id> of the link; NULL once accepted
  verifier_hash BLOB,                     -- SHA-256 of the verifier; NULL once accepted
  areas TEXT NOT NULL,                    -- JSON list, a subset of ["food","labs","body","symptoms"], not empty
  created_at TEXT NOT NULL,
  expires_at TEXT,                        -- the code's end; NULL once accepted
  accepted_at TEXT,
  ended_at TEXT,                          -- set when either side stops it, or the code is cancelled
  ended_by TEXT CHECK (ended_by IN ('owner','grantee','admin','replaced')),
  last_viewed_at TEXT
);
```

One row is a code until it is accepted, then a share. `CHECK`s keep the two states apart. An active share is
`accepted_at IS NOT NULL AND ended_at IS NULL`, with both accounts active. Not in the export (it is a link between two
accounts, not the person's data). Deleting either account deletes the rows.

## 5. Routes

All need a session (`current_user`); all answer `404` when the switch is off (§6) or in `AUTH_MODE=none`.

| Route | Who | Does |
|---|---|---|
| `GET /api/me/shares` | owner | `{enabled, areas_all, max, sharing: [share], codes: [code]}`: the people who can see your data, and your unused codes |
| `POST /api/me/shares` | owner *(re-auth)* | `{areas}` → `201 {code: {id, areas, expires_at}, link}`: the link is in this answer only |
| `DELETE /api/me/shares/{id}` | owner | Stops a share or cancels a code. `204`; not yours is `404` |
| `GET /api/shared` | grantee | `{people: [{id, name, username, areas, since}]}`: who shares with you |
| `DELETE /api/shared/{id}` | grantee | Stops seeing it. `204`; not yours is `404` |
| `POST /api/shared/info` | grantee | `{code}` → `{name, username, areas, expires_at}` or the generic `404 "That link does not work. Ask for a new one."` |
| `POST /api/shared/accept` | grantee | `{code}` → `201` the share as `GET /api/shared` lists it |
| `GET /api/shared/{id}/profile` | grantee | `{name, ckd_stage, dialysis, diabetes, dialysis_days, week_start, weight_kg, targets}`: what the pages need, nothing more |
| `GET /api/shared/{id}/log?date=` | grantee, `food` | The day, as `GET /api/log` answers it to the owner |
| `GET /api/shared/{id}/log/summary?start=&end=` | grantee, `food` | As `GET /api/log/summary` |
| `GET /api/shared/{id}/labs` | grantee, `labs` | As `GET /api/labs` |
| `GET /api/shared/{id}/body/summary`, `/body/weights`, `/body/blood-pressure` | grantee, `body` | As the owner's routes |
| `GET /api/shared/{id}/symptoms` | grantee, `symptoms` | As `GET /api/symptoms` |
| `DELETE /api/admin/users/{id}/shares` | admin *(re-auth)* | Ends every share and code where the person is either side. `{ended: n}` |

**One check, at the data layer.** Every `/api/shared/{id}/…` route goes through one dependency, `shared_owner(area)`: it loads
the row `WHERE id = ? AND grantee_user_id = ?` (the signed-in person), checks it is active, both accounts are active and the area
was shared, and returns the **owner's** user. The handler then calls the owner's own route function with that user, so the
answer is exactly what the owner sees and no query is written twice. Anything else (another person's share id, an ended share,
an area not shared, an unknown id) is the same `404 "Not shared with you."`. There is no write route under `/api/shared`.

**Views are logged, once a day.** The first read of a share each day (UTC) sets `last_viewed_at` and writes `share.viewed` to the
owner's activity. Audit actions: `share.code_created`, `share.code_cancelled`, `share.accepted`, `share.ended` (`by`: owner,
grantee or admin), `share.viewed`. They all show in the owner's activity; the grantee sees their shares in Settings.

## 6. The switch

`sharing.enabled` (instance, bool, default **off**, env `SHARING_ENABLED`; Server administration → Server settings). Off: every
route above answers `404` and Settings says the admin has not turned it on. Shares are kept: turned on again, they work again.
Codes do not wait: their 7 days run while the switch is off. Off by default because a new way to see someone's health data is a
choice an admin makes for their server, as phone shortcuts and the assistant are.

## 7. The screens

* **Settings → Account → Sharing** (accounts in `local` and `proxy` mode): who can see your data (name, user name, areas, since,
  last looked, **Stop sharing**), your unused links (areas, ends, **Cancel**), **Share with someone** (four boxes, then the link
  once with **Copy link**). Then **Shared with you**: each person with **Open** and **Stop seeing**.
* **`#/share/<code>`**: the question of §2 step 3. Signed out, it asks to sign in first and comes back to the question.
* **The shared view** (`#shared`): the person's name, "Read-only: you can look but not change anything", and two parts:
  * **Summary**: the Visit prep page, built from the shared routes instead of the signed-in person's (period, averages against
    targets, labs, symptoms, weight and blood pressure; parts that were not shared say so). Print works as before.
  * **A day**: a date and what was eaten that day with the day's totals against targets, read-only.
  Every control that would change data is absent, not just disabled.
* Server administration → People: "Sharing: n" and **End sharing**.
* The demo answers as a server with sharing off.

## 8. Tests

The code (wrong, used, expired, cancelled, own code, the limit of 5, the limit of 10, replace), the dependency for every
`/api/shared` route (another person's share id, ended, area not shared, disabled owner or grantee, unknown id: all the same
`404`), that the answers equal the owner's own, that no write method exists under `/api/shared`, the daily view audit, the switch
and none mode, the admin removal, account deletion of either side, the migration, the screens in Node, and a Chromium walk of two
people sharing and stopping.

## 9. Risks

* **A forwarded link.** Anyone with an account who gets the link before Sam can accept it. The question names who is sharing,
  Ana's list shows who accepted, and she can stop it at once. The link works once and for 7 days.
* **Too much shown.** The shared answers reuse the owner's handlers, so a field added to one of those later is shared too. The
  profile is a separate, short model for this reason, and the tests compare each shared answer to the owner's on purpose so a
  change is seen.
* **A caregiver relationship that ends badly.** Either side can stop at once, and an admin can end every share of a person.

## 10. Choices taken (the owner can change any of them)

1. A link the owner sends, accepted by the other person, rather than typing a user name (no guessing of who has an account,
   and the other person agrees).
2. Four areas: food log, lab results, weight and blood pressure, symptoms. Preferences, meals, recipes and AI are never shared.
3. Read-only only.
4. The switch is off by default.
5. Codes last 7 days; at most 5 unused codes and 10 active shares a person.
6. Views are logged once a day per share, not every page.

## 11. Later

* Clinician accounts with notes (ROADMAP): a `clinician` role and notes the person can read; every view logged.
* ~~Sharing Trends charts as they look to the owner~~: built 2026-10-29. **Shared with you → Trends** opens the Trends tab in a read-only mode: the person's charts, period summary, symptoms and weight and blood pressure, from `GET /api/shared/{id}/log/range` (food) and the routes above; no CSV export, no insights, no link to Visit prep; parts not shared say so. The Trends tab itself always shows your own.
* ~~A time limit on a share ("for the next 30 days")~~: built 2026-10-29, schema step 25. When making the link the owner picks
  until they stop it, a week, 30 days, 90 days or a year (`days`, 1 to 365, in the API). The end date is set when the link is
  accepted (`ends_at`). The next sharing request after it ends the share as if the owner stopped it (`ended_by: owner`), with
  `share.ended` (`by: time`) in the owner's activity. A newer link that replaces a share brings its own end date.
