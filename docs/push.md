# Phone shortcuts: sending weight and blood pressure from an iPhone

Not reminders: notifications from the server to a phone are [reminders.md](reminders.md), with their own switch
(`REMINDERS_ENABLED`). `PUSH_ENABLED` is only about phone shortcuts.

A person can make a **device token** in Settings and paste it into a Shortcut on their iPhone. The Shortcut sends the person's latest
weight and blood pressure to their own server, without opening the app and without an export. The token can **only add** weights and
blood pressure readings to its owner's log: it cannot read anything, change or delete a row, or reach any other route.

A device token can also be made **for the iPhone app**. The app keeps the log on the phone and sends what the person adds there:
food, foods they made, lab results, symptoms, weights and blood pressure. That token can also only add. See
[Sending from the iPhone app](#sending-from-the-iphone-app).

When the admin also allows it, a token can be made **for the iPhone app, both ways**. With it the app can also use this server's
AI and food services as the person, and read and change the person's own data here. See
[The iPhone app, both ways](#the-iphone-app-both-ways).

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
are `POST /push/v1/body`, the token check `GET /push/v1/check`, the iPhone app's `POST` and `GET /push/v1/sync` (below), and for the
app both ways `GET /push/v1/about`, everything under `/push/v1/api/`, `GET` and `POST /push/v1/changes` and `POST /push/v1/match`. To let a phone reach them from beyond your LAN without opening
the rest of the app, use the commented second host name in `deploy/caddy/Caddyfile.example`; it passes only these requests and
`POST /mcp` ([assistant.md](assistant.md)). A VPN is simpler and safer.

**The iPhone app, both ways** has a second switch, under the first: Server administration → Server settings → Phone shortcuts →
"Let the iPhone app read and change the person's data and use this server's AI and food services", or `PUSH_APP_SYNC=true`. It is
**off** by default and works only while phone shortcuts are on. So you can let phones add without letting them read. While it is
off, nobody can make such a token, and the tokens made before answer `401`; tokens that only add keep working.

## What a token is

* Starts with `khd_` ("device"; assistant tokens start with `kha_`). A Shortcut's token holds exactly one scope, `body:write`. A token
  for the iPhone app also holds `app:add`. The person chooses which one it is for, never the scopes. The plain token is shown
  **once**, when it is made; the server keeps only its SHA-256.
* A person has at most **5 active device tokens** (5 assistant tokens besides), valid **30, 90 (default) or 365 days**, or until it is revoked when the admin allows tokens that never expire
  (`TOKENS_ALLOW_NEVER_EXPIRING`, on by default). Making one needs a
  recent password (like saving a key) and is limited to 20 tokens an hour in all.
* A token has a name (for example "Morning weight"), shows when it was last used and how many weights and readings it sent that are still in
  the log, and is **revoked** at once in Settings. Every token
  also ends when its owner's password is changed or reset, when the account is disabled or deleted and when an admin presses **Revoke
  tokens** for the person (Server administration → People: it ends assistant and device tokens alike). When the server's
  sign-in mode (`AUTH_MODE`) changes, every token of every person ends at the next start.
* The rows a token sent are marked `source: shortcut` and linked to it, so the person can see where a row came from and **delete
  everything one token sent** in one step (`DELETE /api/me/tokens/{id}/body-rows`). If the token is purged 30 days after it ended, the rows
  stay and only lose its name.

**In Settings** (Account → Your data → Phone shortcuts): give the token a name, choose when it ends (30 days, 90 days, 1 year, or Never: until you remove it) and press
Make token. After a few minutes without a password the app asks for it again first. The token is shown **once**, with **Copy token** and
the address to send to (this server's address followed by `/push/v1/body`); paste both into the Shortcut ([the
recipe](../handbook/docs/app/weight-and-blood-pressure.md#from-a-phone-shortcut)). The list below shows each token's name, its first
characters, when it was made, last used and expires, and what it sent. **Revoke** ends it at once; **Delete what it sent** asks (naming the
count) and removes only the rows that token sent, never ones the person typed or imported. For a lost phone press Revoke, then Delete what
it sent; an ended token stays in the list for a while and still offers the second.

The screen uses these routes (a signed-in browser session; the switch on), which a script can call as well:

```
POST /api/me/tokens        {"name": "Morning weight", "family": "device", "expires_in_days": 90}
POST /api/me/tokens        {"name": "My iPhone", "family": "device", "kind": "app"}      a token for the iPhone app
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

## Sending from the iPhone app

The iPhone app keeps the log on the phone and works without a server ([design note 38](dev/research/38-iphone-app-without-a-server.md)).
When a server is set up and can be reached, the app sends the **new** rows the person made on the phone. With this token it never
sends an edit or a delete, and it reads nothing back. For both ways, see "The iPhone app, both ways" below.

**The token.** In Settings → Account → Your data → Phone shortcuts, choose **What it is for: The iPhone app** and make the token. It
works where a Shortcut's token works, so the app can keep sending Health readings to `/push/v1/body`, and it also works at
`/push/v1/sync`. Pair the app with the QR code as before. A Shortcut's token is refused at `/push/v1/sync` with the usual `401`.

**What it can add:** food log entries, the foods those entries need, lab results, symptoms, weights and blood pressure readings.
A phone that syncs both ways also sends its saved meals and recipes here, in `meals` (below). Never preferences, settings or the
profile. The token cannot read, change or delete anything.

### The request

```
POST /push/v1/sync
Authorization: Bearer khd_…
Content-Type: application/json

{"foods":    [{"client_id": "0f8fad5b-d9cb-469f-a165-70867728950e", "name": "Grandma's rice pudding", "serving_desc": "1 bowl",
               "serving_g": 150, "nutrients": {"calories_kcal": 210, "potassium_mg": 180}}],
 "entries":  [{"client_id": "7c9e6679-7425-40de-944b-e07fc1f90ae7", "date": "2026-11-21", "meal": "lunch",
               "food": {"client_id": "0f8fad5b-d9cb-469f-a165-70867728950e"}, "servings": 1},
              {"client_id": "16fd2706-8baf-433b-82eb-8c7fada847da", "date": "2026-11-21", "meal": "lunch",
               "food": {"builtin": {"fdc_id": 173944, "name": "Banana, raw"}}, "grams": 118}],
 "labs":     [{"client_id": "886313e1-3b8a-4372-9b90-0c9aee199e5d", "analyte": "potassium", "value": 5.1, "unit": "mmol/L",
               "taken_on": "2026-11-20"}],
 "symptoms": [{"client_id": "a8098c1a-f86e-41d4-9d28-5d2a8b1e2c3f", "date": "2026-11-21", "symptom": "itching", "severity": 2}],
 "weights":  [{"client_id": "c56a4180-65aa-42ec-a945-5fd21dec0538", "date": "2026-11-21", "time": "07:15", "kg": 70.2,
               "context": "morning"}],
 "readings": [{"client_id": "e4eaaaf2-d142-11e1-b3e4-080027620cdd", "date": "2026-11-21", "time": "07:20", "systolic": 122,
               "diastolic": 78, "context": "morning"}]}
```

```
{"added": {"foods": 1, "entries": 2, "labs": 1, "symptoms": 1, "weights": 1, "readings": 1},
 "already_there": {"foods": 0, "entries": 0, "labs": 0, "symptoms": 0, "weights": 0, "readings": 0},
 "skipped": {"food_not_found": 0, "day_full": 0}}
```

* Every list is optional, but send at least one row. At most **200 rows** in all and **256 KiB** in one request.
* Each row has the same fields and the same checks as the screen that adds it here (`POST /api/foods`, `/api/log`, `/api/labs`,
  `/api/symptoms`, `/api/body/weights`, `/api/body/blood-pressure`), plus a **`client_id`**. A row that fails a check is a `400` that
  names it, such as `entries.1.date: …`, and nothing in the request is stored.
* **`client_id`** is a UUID the phone makes once for the row and never changes. Sending a row again adds nothing, even if the person
  deleted it here since. Each list has its own IDs.
* An entry names its **food** in one of four ways: `{"client_id": …}` for a food in `foods` (in this request or an earlier one),
  `{"builtin": {"fdc_id": …, "name": …}}` for a food of the built-in list (by `fdc_id`, or by name when it has none), or
  `{"usda": {"fdc_id": …, "name": …}}` and `{"off": {"gtin": …, "name": …}}` for a USDA or Open Food Facts food this server already
  holds. A USDA or Open Food Facts food the phone found itself is best sent in `foods` with `"source": "usda"` and its `fdc_id`, or
  `"source": "off"` and its `gtin`: the server uses its own copy when it has one, and keeps the phone's as the person's own food
  otherwise, as an import of a file does.
* Entries, labs and symptoms may carry **`created_at`** (as the export writes it). A row that came here earlier in an exported file is
  then found and not added twice. Weights and readings may carry the Health **`source_key`**, so a reading already sent to
  `/push/v1/body` is not added twice.
* A row the server cannot place is **skipped**, not refused: an entry whose food it cannot find, or a symptom, weight or reading on a
  day that already holds the most allowed. It is counted, and sending it again tries again.
* The answer holds **counts only**.

Weights and readings the app sends show "from a shortcut (name)" like a Shortcut's. The person's activity list shows "The iPhone app
added to your log" with the counts. In the token list the app's token shows what it sent that is still here, and **Delete what it
sent** removes all of it: entries, lab results, symptoms, weights, readings, and the foods it made that nothing of the person's uses.
Rows the app found already here, and anything the person typed or imported, stay.

| Answer | Meaning |
|---|---|
| `200` | counts, as above |
| `400` | a row or field is not valid (the text names it); nothing stored |
| `401` | no valid app token (a Shortcut's token included), or phone shortcuts are off |
| `403` | a browser page on another site tried it (`Origin`) |
| `405` | a method other than `GET` or `POST` |
| `413` / `415` | body over 256 KiB / not `application/json` |
| `429` | more than 60 requests an hour for this token, more than 2,000 new rows a day for this token, or too many wrong tokens from this address (`Retry-After`) |

`GET /push/v1/sync` with the app token answers `200 {"ok": true}`: the app's test that the token may send rows. It counts toward the
same 60 an hour.

### What the app does

The page inside the app keeps the queue and builds each request (`app/static/js/mock/server_sync.js`). The app only carries it to
the paired server over HTTPS, with the token from its Keychain (`ios/KidneyHealth/Services/ServerSync.swift`). The token never
reaches the page.

* It sends 10 seconds after a change is saved, when the app comes to the front, and when the person taps **Sync now** in
  Settings → This device → Your server. It first checks the token with `GET /push/v1/sync`, and keeps that answer for a day.
* Each row gets a `client_id` once, saved on the phone before the row is sent. Foods go first, oldest rows first, at most 200 rows
  and 256 KiB a request. The person's own foods, and the USDA and Open Food Facts foods an entry uses, go in `foods`; built-in foods
  are named with `builtin`. With a token that only adds, a planned entry waits until its day is over; both ways it is sent at once.
* A row is sent once. After a `200` it is never sent again. With a token that only adds, a later change or delete on the phone
  stays on the phone; both ways, it goes through `POST /push/v1/changes` (below).
* The answer counts skipped rows without naming them. The app sends the rows that could have been skipped again, in smaller groups,
  until it knows which they were. A row skipped three times stops and the screen lists it.
* A `400` that names a row (`entries.3.date: …`) marks that row as refused: it stays on the phone, is listed on the screen and is
  never sent again. The rest is sent.
* `401` stops sending and the screen says the token is not an iPhone app token or the server turned phone shortcuts off. The app
  checks again by itself at most once an hour. `413` sends smaller requests, `429` waits for `Retry-After`, and with no connection the
  rows wait on the phone.
* The sample data is never sent. Starting over on the phone starts a new queue.

## The iPhone app, both ways

This is [design note 39](dev/research/39-iphone-app-with-a-server.md), step 2. The token lets the iPhone app use some of this
server's routes as the person, so the phone can use the server's AI and food services. The phone's use of it, and the two-way sync of
the log, come in later steps of the note.

**The token.** Turn on both switches (above). In Settings → Account → Your data → Phone shortcuts, choose **What it is for: The
iPhone app, both ways** and make the token. It holds `body:write app:add app:sync`, so it also works where an iPhone app token works.
Pair it by QR code as before. A token made for the iPhone app before is **never widened**: to get the server's data and AI on the
phone, the person makes a new token and pairs again.

**The gateway, `/push/v1/api/<path>`.** It runs the `/api/<path>` route of a short list as the token's owner. The phone calls
`/push/v1/api/ai/status` where the web app calls `/api/ai/status`, with the same body and the same answer. In order:

1. Any `Origin` header, or a `Sec-Fetch-Site` other than `none`, is `403`. The app sends neither; a browser always does.
2. The token: a device token with `app:sync`, while both switches are on. Every failure is the same `401` as the other routes here. A
   request with a session cookie and no token is that `401` too. No cookie is ever read, and none reaches the route.
3. At most **600 requests an hour** for each token, together with `GET /push/v1/about`. The route's own limits apply after that, as
   for the web app (for example the AI's daily limit).
4. The list. A route that is not on it is `404` with "This is not open to the iPhone app." The list today:

   | Route | What for |
   |---|---|
   | `GET /api/ai/status`, `POST /api/ai/consent`, `DELETE /api/ai/consent/{provider_id}` | which AI runs each feature, and the person's consent |
   | `POST /api/ai/next-meal`, `/api/ai/parse-meal`, `/api/ai/recipes`, `/api/ai/chat`, `/api/ai/transcribe` | meal ideas, describe a meal, recipes, Ask and its microphone |
   | `POST /api/vision/label`, `/api/vision/plate` | label and plate photos |
   | `POST /api/ai/read-lab-report`, `/api/ai/read-lab-report-text` | lab report photos and text: on the local AI only |
   | `GET /api/foods/usda/search`, `POST /api/foods/usda/import`, `POST /api/foods/barcode` | the server's food services, with its keys |
   | `PATCH /api/me/settings` with only `food.off_consent`, `user.units.labs`, `user.units.weight`, `user.units.height`, `body.weight_alarm`, `body.bp_goal` and `guidance`; `PATCH /api/me/ai` with only `opt_in` | the person's Open Food Facts consent, AI opt-in and account settings. Any other key, such as the theme, is `403` and the route does not run |
   | `GET` and `PUT /api/profile`, `GET /api/me/settings` | the profile and targets, and the settings, which the server owns |
   | `GET /api/guidance/preferences`, `PUT` and `DELETE /api/guidance/preferences/{food_id}`, `GET /api/foods`, `GET /api/foods/{food_id}` | the food preferences, and finding which food each one is about |
   | `GET /api/recipe-import`, `POST /api/recipe-import/page` | a recipe from a web page: the server reads the page through its checked connection, as for the web app |
   | `GET /api/instacart`, `POST /api/instacart/preview`, `/api/instacart/send` | the Plan's shopping list at Instacart, with the server's key |
   | `GET /api/list-sync`, `POST /api/list-sync/preview`, `/api/list-sync/send` | sending the shopping list to the person's own list app |
   | `GET /api/devices`, `POST /api/devices/{provider_id}/sync`, `DELETE /api/devices/{provider_id}` | Withings and Whoop on the server: the person's status, Sync now and Disconnect. Connecting is not on the list (below) |
   | `GET /api/activity`, `PUT /api/activity/extra` | the Whoop days for Trends, and the active-day calorie setting |
   | `GET /api/me/notes`, `POST /api/me/notes/{note_id}/read`, `DELETE /api/me/notes/{note_id}` | notes from the person's Care team: read them, mark one read with the version shown (`If-Match`), delete one |
   | `GET /api/me/suggestions`, `POST /api/me/suggestions/{suggestion_id}/accept`, `/decline` | meal suggestions from the Care team: add one to the plan, or say no thanks |

   Each service works only while it is on for this server (`RECIPE_IMPORT_ENABLED`, `INSTACART_ENABLED` with its key,
   `LIST_SYNC_ENABLED`); otherwise its route answers as it does for the web app. The list app is set up only in the web app: its
   address and key are never sent from the phone, and its key never goes to it.

   The notes and suggestions find a row only by the token owner's id, so another person's note is `404`. Writing a note, and
   sharing itself (who is on the Care team and what they may see and do), stay in the web app.

   Connecting Withings or Whoop (`POST /api/devices/{provider_id}/start` and the way back) is tied to the browser session that
   started it, so it is never on the list. The iPhone app opens the server's own page at `/#/devices/open/<provider>` in Safari's
   sheet instead. The person signs in to the server there and connects as in the web app; the app hands that page no token. The
   readings the server then fetches reach the phone through the change feed, marked "from Withings".

   **Never on it:** anything that needs the password again, admin routes, sign-in, tokens, sessions, keys and AI providers, sharing,
   the import, the `.zip` export, and deleting or changing the account. A test pins the list.
5. The route runs as the token's owner with the role of a person, **never an admin**, even when the owner is one. It cannot pass a
   password check either. Every rule of the route still holds: it sees only this person's data, and another person's row is `404`.

Every answer has `Cache-Control: no-store`. The server's log holds the token's id, the route and the status, never a value. The
person's activity list shows "The iPhone app read your data" once a day for each token, and the token's "last used" in Settings.

**The AI's rules are the same as on the web.** The phone calls the same routes, so the admin's choice of local or cloud AI for each
feature, the person's opt-in and consent, the checks before and after the AI, the daily limit and the AI activity list all apply.
Lab report text and photos go only to the local AI: without one, the lab routes answer `503 no_local_provider`, and nothing falls
back to a cloud model. Prompts and answers are not kept, as on the web, and no route on the list asks the AI about doses.

**No key moves.** The server's USDA key, Open Food Facts consent and other keys stay on the server and are never sent to the phone.

### `GET /push/v1/about`

What this server offers this person, so the phone can choose without trying each route. Same token, same `401`, `403` (a foreign
`Origin`) and `429`; only `GET` (`405` otherwise).

```json
{"account": "5f1d0c1e9a8b7c6d5e4f3a2b1c0d9e8f",
 "api_version": 1, "app_version": "0.25.0",
 "sync": {"gateway": true, "changes": true},
 "gateway": [{"method": "GET", "path": "/api/ai/status"}, …],
 "ai": {"enabled": true, "available": true, "routes": {"meal_ideas": {…}, "labs": {…}, …}},
 "services": {"usda_search": true, "barcode": true, "barcode_off": false, "barcode_usda": true,
              "recipe_import": false, "instacart": false, "list_sync": false},
 "capabilities": {…},
 "features": {"usda_search": true, "barcode": true, "ai": true, "changes": true},
 "care_team": {"enabled": true, "notes": true, "team": [{"name": "Dee", "role": "clinician", "areas": ["labs"]}],
               "on": [{"name": "Ana", "role": "care_helper"}]}}
```

* `account` is the same for every token of this person on this server, and different for anyone else. It is a keyed hash of the
  person's id, so it names neither the person nor the server. The phone keeps it to notice a different account or server. It changes
  if the server's `SECRET_KEY` is replaced; the phone then asks once.
* `ai.routes` is `routes` of `GET /api/ai/status`; `capabilities` is that of `GET /api/meta`.
* `features` repeats the four answers the phone needs first: `services.usda_search`, `services.barcode`, `ai.available` and
  `sync.changes`.
* `care_team` is for Settings → Care team on the phone, which only shows it: whether the Care team and its notes are on, who is on
  the person's Care team (name, role, what they see) and whose Care team the person is on. No ids, user names, links or invites.
* `200` means the token works both ways. A token that only adds gets `401`, and a server older than this gets `404`.
* An AI route answers `404` while the AI is off for the person, as on the web. The phone then uses its own AI.

### The change feed

Step 5 of the note. Every row the phone syncs has one ID on every device, its `client_id`: the person's own foods, food log
entries, saved meals and recipes, lab results, symptoms, weights and blood pressure readings. Rows the iPhone app added before
keep the phone's ID. The server records every change, whoever made it (the web app, an import, the Care team, the assistant, the
phone), and keeps a marker for each delete for 180 days.

**`GET /push/v1/changes?after=<next>&limit=<1 to 500>`** answers what changed since the last answer, oldest first, and only
the latest state of each row:

```json
{"changes": [{"kind": "entry", "id": "7c9e6679-…", "op": "put", "version": "3f0c…", "row": {…, "food": {"builtin": {"fdc_id": 173944, "name": "Banana, raw"}}}},
             {"kind": "lab", "id": "886313e1-…", "op": "delete", "version": null}],
 "foods": [{"ref": {"client_id": "0f8fad5b-…"}, "food": {…}}],
 "next": "1234", "more": false}
```

* `kind` is `food`, `entry`, `meal`, `lab`, `symptom`, `weight` or `reading`. `row` has the export's shape, with `client_id`.
  An entry's food, and each saved meal item's, is named as `POST /push/v1/sync` names it. `foods` holds the foods (not
  built-in) that this answer's rows use.
* `version` is the row's version (below). Send `next` back as `after` until `more` is false. Without `after`, or with `0`, the
  feed starts at the beginning.
* A cursor older than the delete markers kept is `410 {"resync": true}`: read everything again from `0`.
* At most 120 reads an hour for each token.

**Versions.** Every kind has a version, as entries do: a hash of what the person sees of the row, so the same content has the
same version everywhere. The browser's copy is `app/static/js/engine/row_versions.js`. Each kind's `PUT` and `DELETE` route in
`/api` takes `If-Match: "<version>"` and answers `412` with the row as stored when it changed. Without the header they work as
before. Lab results have no edits, so only their delete takes it. The page's own copy of these routes, which the demo and the
iPhone app run, does the same, and gives every new row a `client_id` as the server does.

**`POST /push/v1/changes`** sends edits and deletes made on the phone:

```json
{"changes": [{"kind": "entry", "id": "7c9e6679-…", "op": "edit", "base": "3f0c…", "fields": {"servings": 2}},
             {"kind": "weight", "id": "c56a4180-…", "op": "delete", "base": "91aa…"}]}
```

* `base` is the version the change was made on. `fields` is the body of that kind's `PUT` route. An edit may also carry
  `version`, the version of the phone's copy after the change.
* Each change runs through its route with `If-Match`, and has its own answer in `results`, in order: `done` with the new
  version; `conflict` with the row as stored and its version, when the row changed since `base`; `gone` when the row is not
  here; `refused` with the reason. One answer never stops the others. Nothing is ever overwritten without a question.
* The same edit made on both sides is `done`, not a conflict: send `version` and the server compares.
* At most 200 changes and 256 KiB a request.
* A saved meal's `fields` name each food as `POST /push/v1/sync` does (`{"food": {"builtin": {…}}, "servings": 1}`), never by this
  server's ids. A food the server does not have yet is `refused`; the phone sends the food first.

**`POST /push/v1/match`** helps the first two-way sync of a phone that already sent rows:
`{"ids": {"entry": ["<phone id>", …], …}}` answers `{"known": {"entry": {"<phone id>": "<server id>"}}, "unknown": {"entry": […]}}`.
A row the phone sent that matched a row already here is named by that row's ID. At most 2,000 IDs a request. `POST` requests to
`/changes` and `/match` share 120 an hour for each token.

### What the iPhone app does with it

Steps 6 and 7 of the note (`app/static/js/mock/server_changes.js`). The page owns the rules; the app only carries the requests,
and only these three paths besides the gateway's.

* **When.** After the new rows are sent (above): 10 seconds after a save, when the app comes to the front, every 15 minutes while
  it is open, and on **Sync now**. Never while the app is closed.
* **The account.** The phone keeps `account` from `GET /push/v1/about` with its cursor. A new token for the same account goes on
  from the same cursor. Another account, or another server, stops everything until the person chooses: send this iPhone's data
  there, replace this iPhone's data with the server's, or cancel. Two people's data are never mixed without that question.
* **The first sync** of a phone that already has data calls `POST /push/v1/match`, then reads everything from `0`. A row that only
  one side changed since the phone sent it takes that side. A row changed on both, or one the phone cannot tell, goes to a review
  in Settings, **Your iPhone and your server differ**, with **Keep your server's** and **Keep this iPhone's**. A row deleted on the
  phone after it was sent is listed as **Deleted on this iPhone, still on your server**, with **Delete it there** and **Keep it**.
  Until the person chooses, the server's copy is shown and the phone's is kept.
* **Each run** sends the phone's edits and deletes with `base`, the server's version it last agreed on, then reads the feed. The
  rows and the new cursor are saved together, so a run cut short starts again from the old cursor. `410` reads everything again
  and removes rows the server no longer has.
* **Conflicts** follow the web app's rule: nothing is overwritten without a question. A row changed on both sides shows a card,
  **This entry was changed on another device**, with both copies and **Keep the saved one** or **Use mine**. "Use mine" sends again
  on the server's current version; if it changed again meanwhile, that is a new card. An edit of a row deleted elsewhere is dropped,
  and the phone says "This entry no longer exists, so your change was dropped". A refused change stays on the phone, is listed, and
  is sent again only after the person changes it.
* **What syncs** both ways: food log entries, the person's own foods, saved meals and recipes, lab results (added and deleted),
  symptoms, weights and blood pressure readings. A low treatment syncs like any entry. A phone that synced before saved meals did
  reads the feed once more from `0` for them; a saved meal of the phone with the same name as one of the server's becomes that row
  (the same: one row; different: the review).
* **The profile, targets, account settings and food preferences** come from the server, because a Care team member may set them
  (step 8, `app/static/js/mock/server_account.js`). Each run reads `GET /push/v1/api/profile`, `/api/me/settings` and
  `/api/guidance/preferences` and copies them to the phone, which works offline from that copy. A change on the phone goes straight
  to the server's route through the gateway and is kept only when the server took it. Offline the phone says "This needs a
  connection to your server." The first time, if the phone's own profile and targets differ, one card shows both: **Keep your
  server's** or **Keep this iPhone's**. The phone's own settings stay on the phone: the theme, the camera, its keys and the lock.
* **Notes and suggestions from the Care team** are read from the server each time they are shown (`app/static/js/mock/server_care.js`)
  and never kept on the phone: not in its saved data, its safety copy or its export. While the server cannot be reached the phone
  says so. **Add to my plan** makes the planned entries on the server, and a sync brings them to the phone at once, so it needs sync
  both ways to be on.
* **"N to review"**: the sync badge in the header counts what waits for the person, and Today marks such an entry "needs review".

## Pairing the iPhone app by QR code

When a device token is made, `POST /api/me/tokens` also answers `pair_url`, and Settings → Account → Your data → Phone shortcuts draws it as a QR code
next to the token. It is shown once, like the token.

```text
kidneyhealth://pair?v=1&server=https%3A%2F%2Ffood.example.org&token=khd_…
```

* `server` is `PUBLIC_URL`'s origin, or else the address the page came from. It must be `https://` and a host name or IPv4
  address, with an optional port. Otherwise `pair_url` is `null` and the page says why: the app needs HTTPS.
* The iPhone Camera opens the app with the link. The app asks "Pair with food.example.org?" before it saves the address and the
  token, so a QR code from someone else cannot quietly point it at their server.
* The app reads a link only in the exact form the server makes (`app/pairing.py`, `ios/KidneyHealthCore` `Pairing`, checked
  by `tests/data/pairing_vectors.json`).
* Another app on the phone could claim the same link scheme. The token can only add readings and can be revoked, so this is
  the same risk as a token copied by hand. Paste the token instead if you prefer.

## What a leaked token can do

In the iPhone app, changing the server or token starts a fresh sync position. Saving the same settings keeps
it. Removing or replacing the settings stops further requests with the old token; a request already sent may
still finish. Its reply cannot bring back the old status or sync position, or pause the new server.

When the server refuses the token (it was revoked, phone shortcuts were turned off, or the person must change their password),
the iPhone app stops sending in the background. It does not try again by itself. Open the app and tap **Test connection** or
**Save** once the token works again, and sending carries on from where it stopped.

It can add up to 60 requests of up to 50 plausible weights and readings an hour (never more than 20 weights and 30 readings a day) to
**one** person's log, until it expires (at most 365 days, or never when the person chose so) or is revoked. It cannot read the log, the profile or anything else, change or
delete a row, make or see tokens, or reach any other route (every other route ignores the `Authorization` header). The check route only says whether it works. The false rows are
marked as sent by that token, so the person can see them and delete all of them in one step. Nothing is acted on automatically. Revoke the
token (and delete what it sent) if a phone is lost or a Shortcut was shared.

A leaked **app** token can also add food entries, foods, lab results and symptoms: at most 200 rows a request, 60 requests an hour and
2,000 new rows a day, each one checked like a row typed in the app. It still reads nothing and changes nothing that is there. The rows
are linked to the token, and Delete what it sent removes them.

The server checks the token again before saving the readings. If access ended while the phone was sending,
the request gets 401 and none of its readings are saved. Readings already saved stay in your log until you delete them.

A leaked token **for the iPhone app, both ways** is worth more: it can use the routes of the list above as the person, so it can
read what those routes answer and use the person's AI quota. It still cannot reach any other route, change the password, a key, a
token or the account, or act as an admin. It works only while both switches are on, at most 600 requests an hour, and shows as "last
used" and as a daily activity row. Revoke it, or change the password, and it stops at once.

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
* The iPhone app's side: `app/static/js/mock/server_sync.js` (the queue), `serverSyncBlock` in `app/static/js/views/settings.js`,
  `ios/KidneyHealth/Services/ServerSync.swift`. Tests: `tests/js/server_sync.mjs` and `tests/test_server_sync_phone.py` (which also
  posts the page's body to the real route), the step 4 check in `tests/test_ios_app.py`, Send now in `tools/e2e/device_mode.py`.
* The iPhone app's route: `app/app_sync.py`, schema step 37 (`app/migrations/m037_app_sync.py`, the receipts), the food matching it
  shares with the import (`shared_match`, `builtin_match`, `food_key` in `app/data_import.py`). Tests: `tests/test_app_sync.py`,
  `tests/test_migration_m037.py`, the app parts of `tests/test_push_ui.py` and `tests/test_auth_coverage.py`.
* The iPhone app both ways (design note 39): `app/app_gateway.py` (the gateway's middleware, its list, the second check `guard` and
  `GET /push/v1/about`), `app:sync` and the kind `app_sync` in `app/auth/api_tokens.py`, the one change point in `app/auth/deps.py`
  (`GatewayCaller`), the Origin rule and the body limit in `app/security.py`, the `push.app_sync` key. Tests: `tests/test_app_gateway.py`
  (the list pinned, the isolation matrix through the gateway, the AI's rules), the two-way parts of `tests/test_auth_coverage.py` and
  `tests/test_push_ui.py`.
* The change feed: `app/sync_feed.py`, schema step 38 (`app/migrations/m038_change_feed.py`), versions in `app/row_versions.py` and
  `app/static/js/engine/row_versions.js` (vectors `tests/data/row_version_vectors.json`). Tests: `tests/test_sync_feed.py`,
  `tests/test_migration_m038.py`, `tests/test_row_versions.py`.
* `/push/v1` is a promise: a change that breaks it gets `/push/v2`, and v1 keeps working for at least one release.
