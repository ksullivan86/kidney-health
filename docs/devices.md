# Connected devices: Withings and Whoop

Each person can connect their own **Withings** account, their own **Whoop** account, or both. The server then fetches that
person's data every few hours:

* from Withings, **weight, blood pressure and pulse**, added to the Weight and blood pressure screens, marked "from Withings";
* from Whoop, **calories burned, strain, recovery, resting heart rate, heart rate variability (HRV), sleep and workouts**, shown
  on Trends in the **Activity and recovery** card. A person can also choose to add Whoop's calories on active days to their
  calorie target ([below](#the-active-day-calorie-extra)).

Nothing about the person is sent to either company: the server only signs in and reads.

This page is for the person who runs the server and for people who change the code. The contract is in
[`ARCHITECTURE.md`](../ARCHITECTURE.md) ("Connected devices") and the design note, with what we checked in Withings' own
documents, is [`dev/research/27-connected-devices.md`](dev/research/27-connected-devices.md). Whoop and the active-day extra
are in [`dev/research/28-whoop-activity.md`](dev/research/28-whoop-activity.md). The person's side is **Settings → Connected
devices**; the handbook's Weight and blood pressure page and its Targets page explain it in plain words.

## What a person sees

* **Settings → Connected devices → Connect Withings.** A short box says what is fetched and that nothing is sent. **Continue to
  Withings** opens Withings' own sign-in page; the person signs in there and says yes. Withings sends them back to the app,
  which says "Withings is connected" and fetches the last year of readings at once.
* After that the server fetches new readings every 4 hours (`DEVICES_SYNC_HOURS`). **Sync now** fetches at once, at most once
  every 10 minutes (Withings asks apps not to ask more often).
* Readings show "from Withings" in the tables. They count like any other reading: the 7-day blood pressure average, the
  weight-gain alarm, Trends, the visit summary, the export and the Care team's "weight and blood pressure" area.
* **The server never changes a reading the person typed.** A Withings reading at the same minute with the same numbers as one
  already in the log is not added twice. A reading the person deletes does not come back at the next sync. A reading the
  person edits becomes theirs.
* Only readings Withings knows are this person's are fetched. Withings marks a weighing it is not sure about (a guest on the
  scale) as "ambiguous"; those are left out until the person assigns them in the Withings app.
* **Disconnect** stops the fetching and deletes the server's sign-in. Readings already fetched stay, unless the person ticks
  "Also delete the readings that came from Withings" (edited readings stay either way). The server also asks Withings to end
  its access; the person can check it in the Withings app under their account's connected apps.
* If Withings stops accepting the sign-in (the person removed the app at Withings, or a year passed without a sync), the section
  says "Withings needs you to connect again" and shows **Connect again**.
* Deleting the account deletes the connection here at once. Withings may still list the app until the person removes it in their
  Withings account (the server does not ask Withings for that, only Disconnect does).
* Settings → Account → Activity lists connect, disconnect, and a sync that stopped working.
* **Test accounts cannot connect a device**: they are shared by testers. The demo shows a sample Withings connection with
  sample readings, and never contacts Withings.

## What a person sees with Whoop

* **Settings → Connected devices → Connect Whoop**: the same "before you connect" box, then Whoop's own sign-in page. Back in
  the app, the server fetches the last 90 days at once.
* Trends shows an **Activity and recovery** card once there is data: the average calories burned, strain, recovery, resting
  heart rate, HRV and sleep for the period, a chart of calories burned with a table of every day under it, and the workouts.
  Today's figure grows during the day: the server fetches it again at each round.
* A Whoop day runs from falling asleep to the next sleep. The app gives it to the date 12 hours after it starts, so a night that
  starts on Monday evening is Tuesday's day.
* HRV, recovery, sleep and strain are **shown, never acted on**: no warning, suggestion or target comes from them.
* The Care team area **"activity and recovery"** lets a Viewer or Care helper see the card.
* **Disconnect** works as for Withings; "Also delete the days and workouts that came from Whoop" removes them.

## The active-day calorie extra

Off unless the person turns it on: Settings → Connected devices → Whoop → **Add active-day calories to my target**.

* On a day Whoop counts more calories burned than the person's **usual quiet day**, the difference is added to that day's
  calorie target. It counts all of it unless the person picks a smaller share (for example 50 %), and never more than an
  optional daily ceiling.
* The **usual quiet day** is the lower quarter of the person's own finished Whoop days in the 28 days before (Whoop compared
  with Whoop, so a strap that always reads high or low does not add calories every day). It needs 14 such days; until then
  there is no extra.
* **Only calories rise.** Protein, potassium, phosphorus, sodium, fluid and carbohydrate targets stay as they are. The base
  target is the same rule as before (the NASEM 2023 energy estimate kept inside KDOQI 2020's 25 to 35 kcal per kg).
* Today shows the base target and the extra as separate lines, "Why this number" says it came from Whoop, and on an active day
  one line says: "Extra calories on active days change your carbs; your care team can help you plan insulin for exercise." The
  app gives no insulin advice and never warns against treating a low.
* "What fits now" and the other meal ideas for that day use the raised calorie target. Trends' averages compare with the base.
* **Tracker calories can be off by a lot, in either direction.** Two reviews of many studies found wrist trackers' energy
  figures often wrong by more than a third (O'Driscoll 2020, Germini 2022). We found no published check of Whoop's calories.
  The share and the ceiling are there for that.

## Set it up (server owner)

### Withings

You need a **free Withings developer app**, an `https` address for the server (`PUBLIC_URL`) and about ten minutes.

#### 1. Register the Withings app

1. Go to the Withings developer dashboard, <https://developer.withings.com/dashboard/>, and make a free Withings account or
   sign in with yours.
2. **Create an application**. Choose **Public API integration** (no contract is needed). Accept the terms.
3. Fill in the form:
   * **Application name**: your server's name, for example "Our family food log". People see it when they say yes.
   * **Description**: for example "Adds my weight and blood pressure to my own food log on our home server".
   * **Callback URL** (also called redirect URI): exactly
     `<PUBLIC_URL>/api/devices/withings/callback`, for example `https://food.example.org/api/devices/withings/callback`.
     Copy it from Server administration → About this server once Withings is on (it is shown there).
     * It must be `https` and a real name: Withings refuses `localhost` and bare IP addresses.
     * Withings never visits this address itself; only the person's browser is sent there. So a server that is only reachable
       at home (a name your home network resolves) works, as long as the phone or computer that connects is at home too.
4. Save. The dashboard shows a **Client ID** and a **Client Secret**.

#### 2. Give the server the app

The client ID is a plain setting. The client secret is **only a file**: `WITHINGS_CLIENT_SECRET` stops the server at start-up.

| Variable | What |
|---|---|
| `DEVICES_ENABLED` | `true` turns Connected devices on. Also in Server administration → Server settings → Connected devices. Off by default. |
| `DEVICES_SYNC_HOURS` | How often the server fetches, 1 to 24 hours. Default 4. Also in Server settings. |
| `WITHINGS_ENABLED` | `true` turns Withings on. Needs the two below and `PUBLIC_URL`. |
| `WITHINGS_CLIENT_ID` | The Client ID from the dashboard. |
| `WITHINGS_CLIENT_SECRET_FILE` | A file holding the Client Secret. |

**Compose** (`deploy/compose.yaml`): put the secret in `deploy/secrets/withings_client_secret`, then in `deploy/.env`:

```
DEVICES_ENABLED=true
WITHINGS_ENABLED=true
WITHINGS_CLIENT_ID=your-client-id
```

and uncomment `WITHINGS_CLIENT_SECRET_FILE`, `- withings_client_secret` and the `withings_client_secret:` secret in
`compose.yaml`.

**Podman Quadlet** (`deploy/quadlet/kidney-health.container`):

```
printf '%s' 'the-client-secret' | podman secret create kidney-withings-secret -
```

then uncomment the Connected devices lines:

```
Environment=DEVICES_ENABLED=true
Environment=WITHINGS_ENABLED=true
Environment=WITHINGS_CLIENT_ID=your-client-id
Secret=kidney-withings-secret,type=mount,target=withings_client_secret,uid=10001,gid=10001,mode=0400
Environment=WITHINGS_CLIENT_SECRET_FILE=/run/secrets/withings_client_secret
```

**Kubernetes**: add `withings_client_secret` to the Secret and uncomment the four variables in `deploy/k8s/deployment.yaml`.

Restart. Server administration → About this server shows "Withings: client …, secret set, return address …" and how many people
are connected. The secret itself is never shown anywhere.

#### 3. Let it out

The server needs HTTPS to **`wbsapi.withings.net`** ([network-allowlist.md](network-allowlist.md)). The person's browser visits
`account.withings.com` to say yes. Nothing else.

### Whoop

You need a **Whoop developer app**, a Whoop membership to sign in to the dashboard, an `https` address for the server
(`PUBLIC_URL`) and about ten minutes.

#### 1. Register the Whoop app

1. Go to the Whoop developer dashboard, <https://developer-dashboard.whoop.com>, and sign in with your Whoop account.
2. **Create a new app.** Fill in:
   * **Name**: your server's name, for example "Our family food log". People see it when they say yes.
   * **Contact email** and **Privacy policy URL**: yours. A link to your copy of [privacy.md](privacy.md) is fine.
   * **Scopes**: tick `read:cycles`, `read:recovery`, `read:sleep`, `read:workout` and `offline`. The app does not use
     `read:profile` or `read:body_measurement`.
   * **Redirect URL**: exactly `<PUBLIC_URL>/api/devices/whoop/callback`, for example
     `https://food.example.org/api/devices/whoop/callback`. Server administration → About this server shows it once Whoop is on.
     Whoop never visits it itself; only the person's browser is sent there.
3. Save. The dashboard shows a **Client ID** and a **Client Secret**.
4. A new app is on Whoop's **Sandbox tier: up to 10 Whoop members** can connect, with no approval and no fee mentioned. That is
   enough for a family. For more, Whoop must approve the app (a privacy policy, a test with one member, its brand rules), and
   people report waiting weeks for an answer.

Whoop allows 100 requests a minute and 10,000 a day per app. One sync is 4 to 8 requests, so a home server is far below that.

#### 2. Give the server the app

| Variable | What |
|---|---|
| `WHOOP_ENABLED` | `true` turns Whoop on. Needs the two below, `PUBLIC_URL` and `DEVICES_ENABLED`. |
| `WHOOP_CLIENT_ID` | The Client ID from the dashboard. |
| `WHOOP_CLIENT_SECRET_FILE` | A file holding the Client Secret. `WHOOP_CLIENT_SECRET` stops the server at start-up. |

**Compose**: put the secret in `deploy/secrets/whoop_client_secret`, set `WHOOP_ENABLED=true` and `WHOOP_CLIENT_ID` in
`deploy/.env`, and uncomment `WHOOP_CLIENT_SECRET_FILE`, `- whoop_client_secret` and the `whoop_client_secret:` secret in
`compose.yaml`.

**Podman Quadlet**:

```
printf '%s' 'the-client-secret' | podman secret create kidney-whoop-secret -
```

then uncomment:

```
Environment=WHOOP_ENABLED=true
Environment=WHOOP_CLIENT_ID=your-client-id
Secret=kidney-whoop-secret,type=mount,target=whoop_client_secret,uid=10001,gid=10001,mode=0400
Environment=WHOOP_CLIENT_SECRET_FILE=/run/secrets/whoop_client_secret
```

**Kubernetes**: add `whoop_client_secret` to the Secret and uncomment the three `WHOOP_` variables in
`deploy/k8s/deployment.yaml`.

Restart. Server administration → About this server shows "Whoop: client …, secret set, return address …".

#### 3. Let it out

The server needs HTTPS to **`api.prod.whoop.com`** ([network-allowlist.md](network-allowlist.md)); the person's browser visits
the same host to say yes.

## How it works (Withings)

* **Sign-in.** OAuth 2 with Withings' authorization code. The server asks only for `user.metrics` (measurements). The state in
  the address is 32 random bytes, kept in the server's memory for 10 minutes, used once, and tied to the person and to the
  browser session that started it: a way back from another person or another device is refused before the code is used.
  Withings does not document PKCE, so it is not used; the client secret protects the code exchange.
* **Tokens** are encrypted with the server's secret key (the same way as stored API keys) and bound to the person, so a copied
  row does not open for someone else. `python -m app.admin rotate-secret-key` re-encrypts them. They are never logged and
  never returned by any API. Withings' access token lasts 3 hours and its refresh token a year; each refresh gives a new pair,
  which the server keeps at once.
* **Fetching** asks Withings for weight (type 1), blood pressure (9 and 10) and pulse (11), real measures only, changed since
  the last fetch. Values are decoded exactly (`value × 10^unit`), times are put on the person's clock in the time zone Withings
  gives, and the morning and evening labels follow the same rule as a phone shortcut. Values outside the app's plausibility
  ranges are skipped.
* **The import ledger** remembers every Withings measure the server has looked at, so nothing is fetched into the log twice.
* **Errors.** "Too many requests" pauses that person's fetching for an hour. A refused sign-in, even after a refresh, deletes
  the tokens and asks the person to connect again. Other errors are kept and tried again at the next round.
* **Polling, no webhooks.** Withings can call a server back when there is new data, but only at a public address it can reach.
  Most home servers have none, so the server asks instead.
* **One process.** The background fetch runs inside the app every 10 minutes and syncs whoever is due, one after another. It
  never syncs a disabled account or a test account.

## How it works (Whoop)

* **Sign-in.** OAuth 2 with Whoop's authorization code, the same state rules as Withings. Scopes: `offline read:cycles
  read:recovery read:sleep read:workout`. The token answer has no id for the person, so the server takes Whoop's member number
  from the first cycle it reads; one Whoop account can be connected to one person here.
* **Tokens.** Whoop's access token lasts about an hour. **Each refresh ends the old refresh token at once**, so the server keeps
  the new pair before anything else. A refused refresh asks the person to connect again.
* **Fetching** reads the four v2 lists (cycles, recoveries, sleeps, workouts), 25 records a page, from 3 days before the last
  fetch (the first time, 90 days). Only scored records count; naps are left out of sleep. Energy is in kilojoules: kcal = kJ ÷
  4.184. Values outside plausible ranges are left empty.
* **The day the person is in** has no end yet; each fetch **replaces** that day's numbers. Whoop's days and workouts are Whoop's
  own rows: a person cannot type or edit them.
* **Polling, no webhooks.** Whoop has none for cycles, and a home server may not be reachable.
* **Disconnect** deletes the tokens here and asks Whoop to end the access (`DELETE /v2/user/access`).

## Privacy

Withings learns that this app (by the name you gave it) reads the person's measurements, and sees the server's address. The
server sends Withings nothing but the sign-in and the request for measurements. Whoop learns the same about the person's Whoop
data. The readings, days and workouts are health data like any other in the log: they stay on the server, go out only in the
person's own export (Whoop's days and workouts are not imported back from a file: connecting Whoop again fetches them), and are
never sent to an AI provider.

## Removing it

Set `WITHINGS_ENABLED=false` or `WHOOP_ENABLED=false` (or `DEVICES_ENABLED=false`) and restart. Fetching stops; connections and readings stay, and work
again when you turn it back on. To end everyone's connections, ask each person to press Disconnect, or delete the app in the
company's developer dashboard (every token stops working).
