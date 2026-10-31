# Connected devices: a Withings scale or blood pressure monitor

Each person can connect their own **Withings** account. The server then fetches that person's **weight, blood pressure and
pulse** from Withings every few hours and adds them to their log, on the Weight and blood pressure screens, marked "from
Withings". Nothing about the person is sent to Withings: the server only signs in and reads.

This page is for the person who runs the server and for people who change the code. The contract is in
[`ARCHITECTURE.md`](../ARCHITECTURE.md) ("Connected devices") and the design note, with what we checked in Withings' own
documents, is [`dev/research/27-connected-devices.md`](dev/research/27-connected-devices.md). The person's side is
**Settings → Connected devices**, and the handbook's Weight and blood pressure page explains it in plain words.

Whoop (activity, sleep and recovery) comes in a later version, on the same groundwork.

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
* Settings → Account → Activity lists connect, disconnect, and a sync that stopped working.
* **Test accounts cannot connect a device**: they are shared by testers. The demo shows a sample Withings connection with
  sample readings, and never contacts Withings.

## Set it up (server owner)

You need a **free Withings developer app**, an `https` address for the server (`PUBLIC_URL`) and about ten minutes.

### 1. Register the Withings app

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

### 2. Give the server the app

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

### 3. Let it out

The server needs HTTPS to **`wbsapi.withings.net`** ([network-allowlist.md](network-allowlist.md)). The person's browser visits
`account.withings.com` to say yes. Nothing else.

## How it works

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

## Privacy

Withings learns that this app (by the name you gave it) reads the person's measurements, and sees the server's address. The
server sends Withings nothing but the sign-in and the request for measurements. The readings are health data like any other in
the log: they stay on the server, go out only in the person's own export, and are never sent to an AI provider.

## Removing it

Set `WITHINGS_ENABLED=false` (or `DEVICES_ENABLED=false`) and restart. Fetching stops; connections and readings stay, and work
again when you turn it back on. To end everyone's connections, ask each person to press Disconnect, or delete the Withings app in
the developer dashboard (every token stops working).
