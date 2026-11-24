# 39 · The iPhone app with a server, both ways

| | |
|---|---|
| Status | Decided 2026-11-24 (§12), with the usual good practice the owner asked for. The plan is §11. Built: step 2 (the gateway, `app:sync`, `GET /push/v1/about`; `app/app_gateway.py`). |
| Owner's words | "Connecting a server should let the iPhone app use the server's AI and the other keys and services set up there, and sync between devices." (2026-11-21) And: "finish whatever is left on the roadmap." (2026-11-24) |
| Builds on | [Note 38](38-iphone-app-without-a-server.md) (the app alone, device mode, step 4's one-way sending, §5.5 and §5.6, D2), [note 02](02-ios-pwa.md) R5 (the outbox, entry versions, "never overwrite another device's change"), [note 12](12-phone-push-tokens.md) (device tokens, `/push/v1`), [note 32](32-choose-local-or-cloud-ai.md) and [note 36](36-lab-pdf-text.md) (AI routing, lab text on the local model only). |
| Scope | What the iPhone app can do once it is paired with the person's server: read and edit the person's data there, use the server's AI, use the server's food services and keys, and keep the phone and the server in step both ways. This is note 38 §9 step 6. |
| Out of scope | Android. An App Store listing (note 38 D6). Syncing while the app is closed. Anything that needs the password today: changing it, two-step sign-in, passkeys, tokens, keys, the `.zip` export, deleting the account. Admin screens. The Care team's own view of someone else's log. Reminders on the phone (they would need Apple's push service). Setting up Withings or Whoop from the phone (their readings still reach the phone through sync). |

## 1. What it is for

Today the app keeps the log on the phone and sends new rows to the server. Nothing comes back. So:

* An entry made in the web app never reaches the phone.
* An edit or a delete made on the phone never reaches the server.
* The phone looks foods up with its own keys, even when the server has a USDA key.
* The phone cannot use the server's AI. Note 38 kept the phone away from any cloud AI.

The owner wants the server, once connected, to be the shared home of the data and the place the keys and the AI live.
The phone should still work offline, as it does now (note 38 D2, local-first).

## 2. What already exists

* **The app token** (`khd_`, kind "The iPhone app", scopes `body:write app:add`). It is made in Settings → Phone shortcuts,
  paired by QR code, kept in the Keychain, and can be revoked. It can only add (note 12 decision 3).
* **`POST /push/v1/sync`** adds rows with a `client_id` each. A receipt per row (`app_sync_rows`, schema step 37) keeps a
  second send from adding anything, even after the row was deleted on the server. Each receipt names the row it made or
  found (`row_id`) and whether it added it.
* **Entry versions and `If-Match`** (note 02 R5). An entry's `version` is a hash of what the person sees, so the same content
  has the same version everywhere. `PUT` and `DELETE /api/log/{id}` with a stale version answer `412` with the entry as stored.
  The web app's outbox turns that into a conflict card: "Keep the saved one" or "Use mine". It never overwrites silently.
* **The phone already has every screen and rule**, because device mode runs the demo's engine (`js/mock/*`), checked against
  the server by the vectors in `tests/data/`.
* **The phone's queue** (`js/mock/server_sync.js`) remembers each row it sent, keeps that mark after the row is deleted on the
  phone, and saves before a new ID leaves the phone.
* **The bridge.** The page owns the rules and builds every request. The app only carries it, with the token from the Keychain,
  over HTTPS, with no cookies, no cache and no redirects (`Services/ServerSync.swift`). The token never reaches the page.
* **The server's AI** decides per feature which provider runs it, asks for consent per provider and purpose, checks the text
  before calling (lows, red flags, medicine questions), checks the answer (the guard), counts the daily limit, and keeps the
  person's AI activity list. Lab reports go only to the local AI: `ai.route.labs` takes only `local` or `off`, and the cloud
  provider can never hold the local role (ARCHITECTURE "Privacy tiers").
* **The server's food services**: USDA search and import with the server's key, barcodes through Open Food Facts and USDA,
  and the shared rows that make a second lookup free.

## 3. Facts to rely on

| # | Fact | Source |
|---|---|---|
| F1 | A session lasts 30 days at most and ends after 14 idle days. Sensitive routes need the password entered on that session in the last 10 minutes. | ARCHITECTURE "Identity and request rules" |
| F2 | Every `/api` route reads the session cookie only. A bearer token works only at `/mcp` and `/push/v1`. | ARCHITECTURE "Identity and request rules"; note 12 decision 2 |
| F3 | People who reach the server from outside through a reverse proxy are told to pass `/push/v1/`. The example second Caddy host passes only the phone's paths (`/push/v1/body`, `/check` and `/sync`) and `POST /mcp`, so the rest of the app stays private. | [`docs/push.md`](../../push.md); `deploy/caddy/Caddyfile.example` |
| F4 | For native apps, the usual practice is to sign in through the system browser with PKCE and hold a refresh token. | RFC 8252, "OAuth 2.0 for Native Apps", §4 and §8.1 |
| F5 | `If-Match` with a strong comparison lets a client say "change this only if it is still the version I saw". A mismatch is `412`. | RFC 9110 §13.1.1 |
| F6 | Sync systems hand out changes since a cursor, and keep a marker ("tombstone") for each delete so other devices learn of it. | CouchDB `_changes` feed; Apple CloudKit `CKServerChangeToken` |
| F7 | With `AUTOINCREMENT`, SQLite never gives a row id twice, even after a delete, so a growing id can serve as a cursor. | sqlite.org, "Autoincrement" |
| F8 | iOS runs background refresh only when the system chooses, so an app cannot count on syncing while it is closed. | Apple, `BGTaskScheduler` and `BGAppRefreshTask` |
| F9 | A Keychain item can be kept to this device only, readable after the first unlock. | Apple, `kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly` |

## 4. How may the phone read and edit the person's data?

Today's token can only add. Two-way sync needs to read, change and delete. So do the server's AI and food routes.

| Option | What it is | Good | Bad | Verdict |
|---|---|---|---|---|
| **A. A wider app token at a bearer gateway** | A new scope, `app:sync`, on a new kind of app token. The phone calls `/push/v1/api/<path>`. The gateway runs the `/api/<path>` route of an allow-list as the token's person. | One credential, already paired by QR, kept in the Keychain and revocable. `/api` stays cookie-only. It passes through any proxy that already passes `/push/v1/` (F3). The phone gets only the routes it needs. No route is copied. | `/push/v1` can now read health data, so a stolen token is worth more (§9). | **Decided** |
| B. A session the app holds | The person signs in inside the app. The app keeps the session cookie and sends it. | Every `/api` route works as it is. Every sign-in method works. | The phone holds full account power, admin included. Sessions end after 30 days or 14 idle (F1), so sync stops until the person signs in again. The whole app must face the internet, not just `/push/v1/` (F3). | No |
| C. A new token family with refresh tokens | OAuth-style: sign in through the browser, get a short access token and a refresh token (F4). | The textbook pattern for public apps. | A third family to build and secure twice, for a self-hosted server where the device token already does the refresh token's job. It still needs the gateway or a sign-in at `/api`. | No |

Option A keeps the shape of note 12 and note 38: one family, the prefix and the scope checked before any lookup, the switch,
the 5-token cap, expiry, revocation, and every token ended by a password change.

## 5. Design: the gateway and the token

### 5.1 The token

* **A new kind**, "The iPhone app, both ways", in Settings → Phone shortcuts. Its scopes are `body:write app:add app:sync`.
  `app:sync` implies the other two and nothing of the assistant family.
* **An old app token is never widened.** It keeps working for adding rows. When the phone meets `401` at the gateway with an
  old token, it says: "To get your server's data and AI on this iPhone, make a new token for the iPhone app, both ways, and
  pair again."
* **The server switch** `push.app_sync` (instance, off by default, env `PUSH_APP_SYNC`), under the existing `push.enabled`.
  An admin can allow phones to add without allowing them to read. Every other server feature in this app starts off too.
* **Expiry** as today. The phone shows the token's end date in Settings and reminds the person 14 days before.
* **Revoking** in Settings, or by a password change, ends it at once. The phone keeps its data and says the server stopped
  accepting it.

### 5.2 The gateway, `/push/v1/api/<path>`

* It takes the same checks as every `/push/v1` route, in the same order: `Origin` (`403`), the bearer token of the device
  family with `app:sync` (the generic `401`; switch off: the same, no lookup), then the token's own hourly limit.
* It then runs the `/api/<path>` route **only if it is on the allow-list**, as the token's person. The person is the token's
  owner and nobody else. Every query still takes `user.id`, and not-yours is still `404`, because it is the same route.
* **Never on the list:** any route marked *(re-auth)*, admin routes, `/api/auth/*`, `/api/me/tokens*`, `/api/me/sessions*`,
  keys and providers (`/api/me/ai/provider`, `/api/admin/*`), sharing invites, `/api/me/import`, the `.zip` export and
  deleting the account. A request through the gateway is never an admin, even when the person is one.
* **The CSRF header** is not needed there, because the gateway reads no cookie. A request with a cookie and no token is `401`.
* **One change point.** The gateway hands the person to the route through the request's internal state, which no outside
  request can set. `current_user` uses it only when the gateway set it. `/api` itself still ignores the `Authorization`
  header.
* **The list starts small** and grows step by step (§11): the AI routes, the food lookups, the change feed and the online
  edits. A test fails if a route on the list is missing, marked *(re-auth)*, or an admin route.
* **Limits:** at most 600 gateway requests an hour per token, on top of each route's own limits. Answers keep
  `Cache-Control: no-store`. Logs hold the token id, the path and the status, never a value.
* **What the person sees:** the token's "last used" in Settings, and an activity row "The iPhone app read your data" once a
  day per token, like the Care team's look rows.

### 5.3 `GET /push/v1/about`

Answers what this server offers this person, so the phone can choose without trying each route:

* `account`: an opaque key, stable for this person on this server, that names neither (an HMAC of the person's id).
  The phone uses it to notice a different account or server (§8.6).
* `api_version`, and which features are on: sync, the AI features (the same `routes` as `GET /api/ai/status`), USDA search,
  barcodes, and the other services of §7.

### 5.4 The bridge

One new message, `serverApi`: `{ method, path, body?, ifMatch?, jpeg? }`. The app checks that the method is one it allows and
that the path starts with `/push/v1/`, then sends it with the token, as `serverSync` does today. A photo comes from the page as
base64 and goes out as `image/jpeg`. The answer is `{ ok, status, json, retryAfter? }`, up to 4 MiB for the change feed.
The page still owns every rule. Nothing is logged on the phone.

## 6. The server's AI from the phone

### 6.1 Which AI runs a feature

One rule for every feature, worked out by the page each time:

1. **The server's AI**, when the phone is paired, the server answers, and `about` says the feature is available for this
   person. The server's routing, consent, prefilters, guard, daily limit and activity list apply unchanged, because the phone
   calls the same routes as the web app.
2. **Else the iPhone's own AI** (note 38 §5.6), where the phone has it.
3. **Else the feature's way without AI**, as today: the rules' meal ideas, typing the foods, entering lab values by hand.

A setting, **Use only this iPhone's AI** (off), skips step 1 for people who want nothing sent to any AI.

Why the server first: the server's models are larger, its answers are the ones the web app gives, and an admin's choice of
local or cloud for each feature, and the person's consent, already govern it. The phone adds no new path to a cloud AI.

**Only a failure falls back.** Step 2 is tried only when the server cannot be reached, or answers that the feature is not
available (`503`). A safety answer is never a failure: "treating a low", "get help now" and "ask your care team" are shown as
they are and are not retried anywhere else. A consent question (`409`) shows the server's consent sheet on the phone, the same
sheet as the web app.

The iPhone's own AI must use the same prefilters (low, red flag, medicine question) and the same guard as the server, through
their JavaScript twins and vectors, whichever is built first.

### 6.2 Lab reports, names and dates of birth

* **Lab report text and photos go only to the server's lab routes** (`/api/ai/read-lab-report-text` and
  `/api/ai/read-lab-report`), which run only on the local AI, or to the iPhone's own model. Both are local. The page never puts
  lab text into any other AI request, and a phone test checks that.
* If the server has no local AI, its lab routes answer `503 no_local_provider`. The phone then uses its own model, which is
  also local. **Nothing ever falls back to a cloud model.**
* The phone never builds a prompt with the person's name or date of birth. The server's own rules keep identity out of every
  prompt and run the privacy filter before any cloud AI. Those rules are unchanged.
* The iPhone's 4,096-token window (note 38 F3) is one more reason to let the server's local AI read a long lab page first.

### 6.3 What is kept

* The phone keeps no prompt and no answer. Only what the person chooses to save becomes a row.
* The server keeps what it keeps today for the web app: the person's AI activity list, emptied after the days the admin set.
  Photos are never kept.
* The AI is never given a dosing task. No route on the list asks for one, and the guard still checks every answer.

### 6.4 Features through the gateway

Meal ideas, describe a meal, recipes, the Ask chat, label and plate photos, lab report photos and text, consent, and AI status.
The Ask microphone, where the server has speech to text, sends the clip to the server's route as the web app does.

## 7. The server's keys and food services from the phone

| Service | Paired and reachable | Offline, or not paired |
|---|---|---|
| USDA search and import | Through the server, with the key the server would use for this person (their own or the shared one) | The phone's own USDA key, if the person saved one (note 38 §5.3); else the built-in list and foods already saved |
| Barcodes | Through the server: Open Food Facts after the person agreed, then USDA Branded, then the shared rows | The phone's own Open Food Facts switch and USDA key, if on; else "Look this up when your server can be reached" |
| Import a recipe from a page | Through the server (the server reads the page, if `RECIPE_IMPORT_ENABLED`) | Pasting the ingredients works offline |
| Open the shopping list at Instacart; send it to Grocy, KitchenOwl or Mealie | Through the server, with its keys | Share or copy the list, as today |

* **No key moves.** The server's keys stay on the server and are never sent to the phone. The phone's keys stay in its
  Keychain and are never sent to the server.
* **The server's rules apply**: its limits, its outbound checks (the SSRF-checked transport), and its consent question for
  Open Food Facts. The phone's own limits apply only to its own lookups.
* **A food found through the server** is saved on the server and comes back in the answer. The phone saves it at once, so it
  works offline. Before two-way sync exists, step 4's sending names it by `fdc_id` or barcode, and the server finds it already
  there.
* Settings → Keys and services says which one is in use: "Using your server's food services" or "Using this iPhone's keys".

## 8. Two-way sync

### 8.1 What syncs

| Data | Direction | Edits offline on the phone |
|---|---|---|
| Food log entries (eaten and planned) | both ways | yes, with versions |
| The person's own foods, and the USDA and Open Food Facts foods they use | both ways | yes, with versions |
| Saved meals and recipes | both ways | yes, with versions |
| Lab results, symptoms, weights, blood pressure readings | both ways | yes, with versions (each kind's existing edits: labs have add and delete only) |
| Profile and targets | server to phone | no: edited only while connected, through the server's route |
| The person's account settings and food preferences | server to phone | no: edited only while connected |
| This iPhone's own settings (keys and services, lock, camera, theme) | stay on the phone | yes |
| AI activity, Care team notes and suggestions, sharing | not synced | – |

Profile, targets and settings stay with the server because a Care team member may set them, and note 02 decided that a stale
offline copy must never overwrite a care team's targets. The phone shows the server's values and sends a change straight to
the server's route, which applies the Care team's rules. Offline, those screens say "This needs a connection to your server".
On a phone that is not paired, nothing changes: the phone owns everything, as now.

### 8.2 One ID per row, everywhere

* Every synced table gets a `client_id` (a UUID), as log entries already have. A new schema step adds the column, gives every
  existing row a new one, and adds a unique index per person.
* **Step 4's receipts carry over.** For a receipt with `added = 1`, the row takes the phone's `client_id`, so the phone and the
  server already agree. A receipt with `added = 0` means the phone's row matched a row that was already there. Then the server
  tells the phone the row's own ID in the first sync (§8.5), and the phone renames its copy.
* A row made on the server gets a `client_id` when it is made. The export carries `client_id` for every kind, and the import
  keeps it, so moving to another server by file keeps the IDs.

### 8.3 Versions for every kind

Note 02's entry version, a 64-bit FNV-1a hash of the canonical text of what the person sees, is extended to foods, saved
meals, labs, symptoms, weights and readings, each with its own field list. The same content has the same version on every
device. Each kind's `PUT` and `DELETE` route takes `If-Match` and answers `412` with the row as stored, as the log does.
Without the header they behave as before. The JavaScript twins and their vectors in `tests/data/` follow (CLAUDE.md, "Parity").

### 8.4 The change feed

* **What records a change.** A new table, `sync_changes` (`id` AUTOINCREMENT, `user_id`, `kind`, `row_id`, `client_id`,
  `deleted`), is filled by SQLite triggers on each synced table, for inserts, updates and deletes. Triggers catch every writer:
  the web app, the import, the assistant, the Care team, the phone and housekeeping. No route can forget to record.
* **`GET /push/v1/changes?after=<cursor>&limit=`** (through the token, scope `app:sync`) answers
  `{ changes: [{ kind, id, op: "put" | "delete", version, row? }], next, more }`. Each row has the same shape as in the export,
  so the phone reads it with the code it already has for importing. Only the latest state of each row since the cursor is sent.
  A food that an entry uses comes in the same answer. The cursor is opaque to the phone and per person, because the
  server filters by `user_id`.
* **Tombstones.** A delete leaves a `deleted` mark that is kept for 180 days. A phone whose cursor is older than that gets
  `410 {"resync": true}` and does a full resync (§8.5).
* **Limits:** 120 feed requests an hour per token, at most 500 changes an answer.
* Deleting the account deletes its changes.

### 8.5 One sync run on the phone

The page runs it 10 seconds after a save, when the app comes to the front, on **Sync now**, and every 15 minutes while the app
is open. It does not run while the app is closed (F8).

1. **Send.** First the new rows, through `POST /push/v1/sync` as today. Then edits and deletes, through a new
   `POST /push/v1/changes`: `{ changes: [{ kind, id, op: "edit" | "delete", base, fields? }] }`. `base` is the version the
   change was made on. Each change is checked as `If-Match` is checked, through the same functions as the `PUT` and `DELETE`
   routes, and answered per row: `done` with the new version, `conflict` with the row as stored, or `gone`. One conflict does
   not stop the others.
2. **Receive.** Read the feed from the saved cursor until `more` is false. For each change:
   * no change of the phone's own waits for that row: take the server's copy;
   * a change waits, and the server's version is the one it was made on: keep it waiting, it will be sent;
   * a change waits, and the server's version differs: it becomes a conflict (§8.6).

   The page saves the rows and the new cursor in one save, so a run cut short starts again from the old cursor and changes
   nothing twice.

**A planned entry** is sent at once from this step on. Step 4 held it until its day was over only because edits were not sent.

### 8.6 Conflicts: what the person sees

The rule is note 02's: **never overwrite another device's change silently.** The phone uses the web app's conflict card
(`conflictCard` in `js/offline.js`, moved to a shared file if device mode does not load it):

* "This entry was changed on another device", the server's copy and the person's change side by side, and **Keep the saved
  one** or **Use mine**. "Use mine" sends again with the server's current version. If it changed again meanwhile, that is a
  new conflict, never an overwrite.
* An edit on the phone of a row deleted elsewhere: "This entry no longer exists, so your change was dropped", as in the web app.
* A delete on the phone of a row changed elsewhere: a conflict card that shows "Delete <name>".
* The same edit on both sides is no conflict, because the versions match.
* The badge says "N to review". Today marks the row "needs review". Settings → This device → **Your server** lists them, with
  when the phone last synced and what waits.

A low treatment is synced, edited and reviewed like any other entry. Nothing in sync looks at `purpose`, and nothing warns
about or blocks treating a low.

### 8.7 The first two-way sync of a phone that already has data

1. **Send what is new**, as step 4 does today.
2. **Match.** `POST /push/v1/match` takes the phone's IDs by kind and answers the server's ID for each one it knows (§8.2), and
   which it does not. The phone renames its copies and keeps one row each.
3. **Download everything** from cursor 0, and compare each row the phone also has:
   * the same version: nothing to do;
   * the phone recorded the version it sent (step 1 of §11), and only one side changed since: that side wins, and an edit made
     on the phone is sent;
   * both changed, or the phone has no record: the row goes to a one-time review, **Your iPhone and your server differ**, with
     the same two buttons, labelled for this case: **Keep your server's** and **Keep this iPhone's**.
4. **Rows the phone deleted after sending** (the queue still marks them sent): listed in the same review as "Deleted on this
   iPhone, still on your server", with **Delete it there** and **Keep it**.
5. **Profile and targets** that differ: one card shows both. The server's is chosen unless the person picks the phone's.

The review never decides for the person. Until they choose, the server's copy is shown and the phone's is kept.

### 8.8 A different server or a different account

The phone stores the server's host and the `account` key from `about` with its cursor.

* **The same account, a new token:** sync goes on from the same cursor.
* **A different server, or a different account on the same server:** the phone asks before it sends anything:
  * **Send this iPhone's data to <host>**: everything is sent as new. The server's receipts, the `client_id`s and the content
    checks keep it from adding twice. The cursor starts again at 0.
  * **Replace this iPhone's data with <host>'s**: the phone saves the safety copy (note 38 §5.2), offers to export it, then
    starts over from the server's data.
  * **Cancel**: nothing changes, and the old pairing stays.
* Nothing is ever deleted on the old server. Its token stays until the person revokes it there.
* Two people's data are never mixed without a question: a new `account` key always asks.

## 9. Safety and privacy review

| Concern | Answer |
|---|---|
| A stolen app token now reads health data | Kept in the Keychain on this device only (F9). Never in the page, the export, the safety copy or a log. HTTPS only. 256 random bits, hash-only on the server, the generic `401` and the address throttle. Revocable in Settings, ended by a password change, visible as "last used" and a daily activity row. The switch `push.app_sync` is off until an admin turns it on. The optional app lock (note 38 D4). |
| The token used for more than the app needs | The gateway's allow-list. No route that needs the password, no admin route, never an admin. `/api` itself still ignores bearer tokens. A test pins the list. |
| Another person's data | Same routes, same `user.id` scoping, not-yours is `404`. The isolation matrix runs through the gateway too. The feed filters by `user_id`. The `account` key keeps a phone from mixing two people's data (§8.8). |
| CSRF or browser abuse | The gateway reads no cookie, refuses a request with an `Origin`, and has no CORS. |
| A stale copy overwriting a newer one | Versions and `If-Match` on every kind, the conflict card, and the one-time review (§8.6, §8.7). Profile and targets are edited only through the server. |
| Lab text or identity reaching a cloud AI | Lab text goes only to the server's lab routes, which are local-only, or to the iPhone's own model (§6.2). There is no new path to a cloud AI, and no fallback to one. The server's identity rules and privacy filter are unchanged. |
| Dosing, lows | No new AI task. Safety answers are never retried elsewhere (§6.1). Sync treats a low treatment like any entry. Nothing blocks or warns against treating a low. |
| Keys leaking | No key crosses between phone and server (§7). Secrets stay write-only. |
| Outbound requests | Food services and AI are reached only from the server, through its SSRF-checked transport, or from the phone's bridge to its fixed hosts (note 38 §5.3). |
| Data lost on the phone | Unchanged: the safety copy, export, and now the server's copy too. A run cut short resumes from the saved cursor. |
| A server that is too old | `about` missing (`404`) means the phone keeps step 4's one-way sending and says the server needs an update. |

## 10. What changes, by part

* **Server:** the `app:sync` scope, the token kind and the switch (`app/auth/api_tokens.py`, `app/settings_registry.py`); the
  gateway and its allow-list, `GET /push/v1/about`, `GET` and `POST /push/v1/changes`, `POST /push/v1/match` (new module next
  to `app/app_sync.py`); a schema step for `client_id` on every synced table and the `sync_changes` table and triggers;
  versions and `If-Match` for every kind; `client_id` in the export and import. Tests: auth coverage, the isolation matrix
  through the gateway, the allow-list pin, the feed and tombstones, every conflict case, the migration with step 4's receipts.
* **Web app (shared code):** the JavaScript twins of the new versions and their vectors; the conflict card made shareable;
  Settings → Phone shortcuts offers the new kind and says what it allows.
* **The page in device mode:** the sync run, the feed reader, the review, the account check, the choice of AI (§6.1), food
  services through the server (§7), the Your server block in Settings.
* **iPhone app:** the `serverApi` bridge message with its path and method checks; the token's end date and reminder.
* **Deploy:** the second Caddy host also passes `/push/v1/api/*`, `/push/v1/about`, `/push/v1/changes` and `/push/v1/match`.
  Proxies that pass all of `/push/v1/`, as `docs/push.md` asks, need no change.
* **Docs:** ARCHITECTURE (the gateway in "Identity and request rules", device tokens, the feed, device mode), `docs/push.md`,
  `docs/privacy.md` (what the phone reads from the server), `docs/ai.md` (which AI the phone uses), and the handbook's page on
  using the app with a server.

## 11. Plan and size

Each step is its own pull request with tests, and each is useful when it lands.

| Step | What | Size | Useful alone because |
|---|---|---|---|
| 1 | **Phone: remember what was sent.** The queue records each row's version when it is sent, and keeps the mark of rows deleted after sending. Settings says how many changed on the phone since they were sent. | small | Every day it runs makes the first two-way sync (§8.7) more exact. |
| 2 | **Server: the gateway.** `app:sync`, the new token kind, `push.app_sync`, `/push/v1/api/` with an allow-list of the AI and food routes, `GET /push/v1/about`, the Settings screen, the Caddy example. | medium | Any client with the new token can use the server's AI and food services safely. |
| 3 | **Phone: the server's food services.** USDA and barcodes through the server when connected; the phone's own keys offline (§7). | small | A family member no longer needs a USDA key on the phone. |
| 4 | **Phone: the server's AI.** About, consent, the features of §6.4, and the choice of §6.1, whether or not note 38's step 5 is built yet. | medium | The phone gets the AI the web app has. |
| 5 | **Server: the change feed.** `client_id` on every synced table (schema step), receipts carried over, `sync_changes` and its triggers, versions and `If-Match` for every kind with their vectors, `GET /push/v1/changes`, `POST /push/v1/match`. | large | The web outbox can use versions for every kind, and any client can read changes. |
| 6 | **Phone: receive.** The feed reader, the first sync with its review, the account check and a different server (§8.7, §8.8). | large | Entries made in the web app or by a Care team member reach the phone. This removes note 38 D2's cost. |
| 7 | **Both: send edits and deletes.** `POST /push/v1/changes`, the phone's queue with base versions, the conflict card, planned entries sent at once. | medium | Full two-way sync of the log and its rows. |
| 8 | **Both: profile, targets, settings, food preferences, saved meals and recipes** (§8.1). | medium | The phone shows the targets a Care team set, and saved meals follow the person. |
| 9 | **Phone: the other server services.** Recipe import from a page, Instacart, and sending the shopping list (§7). | small | The last server features the phone lacks. |

Order: 1, then 2 to 4 (each small to medium, useful at once), then 5 to 7 (the sync itself), then 8 and 9. Step 1 goes first
because it is small and phone-only, and the sooner it runs the fewer rows the first sync must ask about.

## 12. Decisions (2026-11-24)

The owner asked us to finish and to use the usual good practice. These are decided:

* **D1. Auth: a wider app token at a bearer gateway** (§4, §5). A new scope `app:sync` on a new token kind, used only at
  `/push/v1/api/`, which runs an allow-list of `/api` routes as the token's person. Old tokens are never widened. Off until the
  admin turns on `push.app_sync`. This changes note 12 decision 3 ("no read scope for devices") for this kind only, because the
  owner asked for sync both ways. `/api` stays cookie-only.
* **D2. The server's AI first, then the iPhone's, then no AI** (§6.1), with a setting to use only the iPhone's. Only a failure
  falls back. Safety answers never do.
* **D3. Lab text only to local models** (§6.2): the server's local-only lab routes or the iPhone's own model. Never a cloud
  model, never as a fallback.
* **D4. Food services through the server when connected**, the phone's own keys offline (§7). No key crosses.
* **D5. What syncs** is §8.1. Rows both ways with versions. Profile, targets and settings stay server-owned and are edited
  only while connected.
* **D6. A change feed** with a per-person cursor, tombstones kept 180 days, and triggers on every synced table (§8.4).
* **D7. Conflicts** use note 02's rule and card. The first sync asks about every row it cannot decide (§8.7).
* **D8. A new server or account always asks** before any data moves (§8.8).
* **D9. Sync runs only while the app is open** (F8).

### Open questions for the owner

1. Should the phone also show Care team notes and suggestions? It is a small step after step 6, read-only, and is left out
   until the owner asks.
2. Should Withings and Whoop be set up from the phone too? Today they are set up in the web app, and their readings reach the
   phone through sync.

## 13. Sources

* IETF, [RFC 8252: OAuth 2.0 for Native Apps](https://www.rfc-editor.org/rfc/rfc8252),
  [RFC 9110: HTTP Semantics](https://www.rfc-editor.org/rfc/rfc9110) (§13.1.1 `If-Match`).
* Apache CouchDB, [the `_changes` feed](https://docs.couchdb.org/en/stable/api/database/changes.html).
* Apple, [`CKServerChangeToken`](https://developer.apple.com/documentation/cloudkit/ckserverchangetoken),
  [`BGTaskScheduler`](https://developer.apple.com/documentation/backgroundtasks/bgtaskscheduler),
  [`kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly`](https://developer.apple.com/documentation/security/ksecattraccessibleafterfirstunlockthisdeviceonly).
* SQLite, [Autoincrement](https://www.sqlite.org/autoinc.html).
* This repository: ARCHITECTURE.md ("Identity and request rules", "Privacy tiers", "Device tokens and `/push/v1`",
  "`POST /push/v1/sync`", "Offline edits and deletes", "Device mode"), [`docs/push.md`](../../push.md), notes 02, 12, 32, 36
  and 38.
