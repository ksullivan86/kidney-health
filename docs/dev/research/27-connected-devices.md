# 27 · Connected devices: the groundwork, and Withings

| | |
|---|---|
| Status | Accepted and built for 0.16, 2026-10-31. Schema step **29**. |
| Owner's words | "Withings for weight and blood pressure; Whoop later." Agreed: "the server would sign in to Whoop and Withings and fetch each person's own data from them, and nothing about the person would be sent out" (docs/dev/progress/0.14-plan.md, "Owner decisions (2026-10-31, devices)"). |
| Builds on | Note 10 (weight and blood pressure), note 12 (phone shortcuts: the "same reading" rule), note 07 (secrets as files, the settings registry, the audit log), note 24 (OIDC: state, binder, the checked transport), note 19/25 (Care team areas). |
| Scope | A framework for more than one provider (connections, an import ledger, provenance, a sync loop); Withings weight, blood pressure and pulse into the existing screens. |
| Out of scope | Whoop (0.17, on top of this), Withings notifications (webhooks), activity and sleep from Withings, sending anything to a provider. |

## 1. What Withings offers (checked 2026-10-31)

Sources: the Withings developer reference for AI agents, [developer.withings.com/llms.md](https://developer.withings.com/llms.md)
(read 2026-10-31); the signing guide,
[developer.withings.com/…/sign-your-requests](https://developer.withings.com/developer-guide/v3/integration-guide/bulkship-sdk/get-access/sign-your-requests/)
(read 2026-10-31); the Public API overview,
[developer.withings.com/…/public-health-data-api-overview](https://developer.withings.com/developer-guide/v3/integration-guide/public-health-data-api/public-health-data-api-overview/);
the API plans page, [developer.withings.com/…/withings-api-plans](https://developer.withings.com/developer-guide/v3/withings-solutions/withings-api-plans/)
(as quoted by search results on 2026-10-31; the page itself is drawn by script and did not load for us); the open-source client
[python_withings_api](https://github.com/vangorra/python_withings_api) (`common.py`, `const.py`: the `attrib` meanings and the
status code groups); and the Open Wearables provider notes,
[openwearables.io/docs/providers/withings-api-integration](https://openwearables.io/docs/providers/withings-api-integration)
(callback URL rules).

| Question | Answer |
|---|---|
| Sign-in | OAuth 2 authorization code. The browser goes to `https://account.withings.com/oauth2_user/authorize2?response_type=code&client_id=…&scope=user.metrics&redirect_uri=…&state=…`. |
| Token endpoint | `POST https://wbsapi.withings.net/v2/oauth2`, form body `action=requesttoken`, `grant_type=authorization_code` (or `refresh_token`), `client_id`, `client_secret`, `code` (or `refresh_token`), `redirect_uri`. The answer is HTTP 200 with JSON `{"status": 0, "body": {"userid", "access_token", "refresh_token", "expires_in", "scope", "token_type"}}`. A non-zero `status` is an error, even with HTTP 200. |
| Lifetimes | The code lives **30 seconds**. The access token lives **3 hours** (`expires_in` 10800). The refresh token lives **1 year**. Each refresh returns a **new** refresh token; the old one stops working 8 hours later. So the new pair must be saved before anything else happens. |
| PKCE | Not documented. We do not send `code_challenge`. The `state` value, bound to the person's session, guards the way back; the client secret guards the code exchange. |
| Scope | `user.metrics` covers weight, blood pressure and pulse. We ask for nothing else (no `user.info`, `user.activity`). |
| Measures | `POST https://wbsapi.withings.net/measure`, `Authorization: Bearer`, `action=getmeas`, `meastypes=1,9,10,11`, `category=1` (real measures, not goals), `lastupdate=<unix time>` for "changed since", `offset` while `more` is 1. The answer has `updatetime` (keep it as the next `lastupdate`), `timezone` and `measuregrps`. |
| Types | 1 weight (kg), 9 diastolic (mmHg), 10 systolic (mmHg), 11 heart pulse (bpm). |
| Units | `value × 10^unit`: `{"value": 7512, "unit": -2}` is 75.12 kg. |
| `attrib` | 0 device, known to be this person; 1 device, **ambiguous** (Withings is not sure whose it is: another person in the house may have stepped on the scale); 2 typed by the person in the Withings app; 4 typed when the Withings account was made; 5 automatic; 7 confirmed by the person; 8 same as a device entry. |
| Revoke | `POST https://wbsapi.withings.net/v2/oauth2`, `action=revoke`, `client_id`, `userid`, `nonce`, `signature`. The nonce comes from `POST https://wbsapi.withings.net/v2/signature`, `action=getnonce`, `client_id`, `timestamp`, `signature`. The signature is HMAC-SHA256, hex, with the client secret as key, over the parameter values joined with commas (`getnonce,<client_id>,<timestamp>`; for other actions the values of `action`, `client_id`, `nonce` sorted by key name). One nonce per request. |
| Errors | `status` 0 ok; 401 and 100–102 invalid or expired token; 601 too many requests. Other codes are errors on Withings' side or ours. |
| Rate limits | The free plan allows **120 requests a minute per app** (not per person); over it, `status` 601 with HTTP 200. Withings asks apps **not to poll more than once every 10 minutes per person**. |
| Notifications | Webhooks are "recommended", not required. They need a public HTTPS address that Withings can reach (it sends a `HEAD` first). A home server often has none, so we **poll**. |
| Registering an app | Free, in the developer dashboard (`https://developer.withings.com/dashboard/`), as a "Public API integration". No contract. The free plan is said to allow up to 5,000 active users (one search source said 1,000), far more than a home server. |
| Callback URL | Must be registered exactly. Withings refuses `localhost` and bare IP addresses; HTTPS only for notifications. It is a **browser** redirect: Withings does not need to reach the server for sign-in, so a home server with a real domain name that only resolves at home works. |
| Hosts | `account.withings.com` (the person's browser only), `wbsapi.withings.net` (the server). |

Uncertain, and what we do about it:

* Whether the dashboard checks the callback is reachable. We tell owners it must be the exact address and HTTPS.
* Whether `revoke` works for a Public API app without a contract (one source says the OAuth2 service is for contract partners).
  We try it once on Disconnect and carry on if it fails: the tokens are deleted here either way, and the person is told how to
  remove the app in their Withings account.
* Whether `status` 401 is the only "token invalid" code. We treat 100, 101, 102 and 401 as "sign in again" after one refresh.

## 2. Decisions

1. **Polling, no webhooks.** Every few hours (`DEVICES_SYNC_HOURS`, default 4) and when the person presses **Sync now** (at most
   once every 10 minutes per person, Withings' own rule). Nothing needs to reach the server from the internet.
2. **Only the server talks to Withings**, through `app.egress.CheckedTransport` (no redirects, 1 MiB cap, 15 s timeout).
   Requests carry the client id, the client secret (token calls only), the code or tokens, and the `getmeas` filters. Nothing
   about the person is sent.
3. **One connection per person and provider.** One Withings account can be connected to one person on this server at a time
   (a second person gets "This Withings account is already connected to someone else here").
4. **Tokens at rest**: sealed with the app's keyring (`Keyring.seal`, purpose `device:withings`, owner the person's id), so a
   copied row does not decrypt under another person. `device_connections.tokens_enc` is in `ENCRYPTED_COLUMNS`, so
   `rotate-secret-key` re-encrypts it. Tokens are never logged (they are registered with the log redaction when read) and
   never returned by the API.
5. **State bound to the session.** `POST /api/devices/withings/start` makes 32 random bytes of state, kept in memory for 10
   minutes, single use, with the person's id and the SHA-256 of their session id. The way back must come from the same person
   on the same session; anything else is refused before the code is used. At most 5 waiting flows per person.
6. **Exact redirect**: `<PUBLIC_URL>/api/devices/withings/callback`. `WITHINGS_ENABLED` needs `PUBLIC_URL`.
7. **What is imported**: measure groups with `category` 1 and `attrib` 0, 2, 5, 7 or 8. Ambiguous (1) and account-creation (4)
   groups are left out: a guest on the scale must not land in the person's log. Weight from type 1; a blood pressure reading
   needs both 10 and 9, with 11 as its pulse. A pulse alone is not imported.
8. **Where it goes**: the existing `weights` and `blood_pressures` tables with `source = 'withings'` and
   `source_key = 'withings:<grpid>'`. The date and time are the person's clock in the `timezone` Withings gives. The Chainguard
   runtime has no system time-zone files, so the app depends on `tzdata` (added to `requirements.in` for 0.16); without it
   every reading would fall back to UTC and an evening reading in California would land on the next day. The context
   follows the phone-shortcut rule (`app.body.context_for`). Values outside the app's plausibility ranges are skipped.
9. **Never overwrite**: the sync only adds rows. It skips a reading the person already has at the same date and minute with the
   same numbers, from any source, typed ones included (a typed copy of the cuff's display is the same reading). Editing an
   imported row makes it `manual`, as for every source, and the sync never brings the old value back.
10. **Import ledger** (`device_imports`): one row per provider measure the sync has seen (imported, already there, or skipped),
    so a reading the person deleted does not come back. Disconnecting with "also delete readings from Withings" removes those
    readings and the ledger, so a later connection can bring them back.
11. **Errors** in plain words, kept as short codes on the connection: `needs_reconnect` (Withings said no to the tokens),
    `rate_limited` (wait an hour), `unreachable`, `provider_error`. The Activity list shows connect, disconnect and the first
    sync error of a kind (not every retry).
12. **Switches**: `DEVICES_ENABLED` (setting `devices.enabled`, off) turns the whole feature on; while off
    `GET /api/devices` answers `enabled: false` (Settings asks it on every open, and a 404 is a failed request in the
    browser), every other `/api/devices` route is 404 and nothing syncs. `WITHINGS_ENABLED`, `WITHINGS_CLIENT_ID` and
    `WITHINGS_CLIENT_SECRET_FILE` are env only (what the server connects to is never changed at run time;
    `WITHINGS_CLIENT_SECRET` is refused, as `OIDC_CLIENT_SECRET` is).
13. **Test accounts cannot connect a device**: they are shared by testers, and a real Withings account must not land in one.
    The demo shows a sample Withings connection with sample readings, and calls nothing.
14. **Care team**: imported rows are weights and readings like any other, so they follow the "weight and blood pressure" area.
15. **For Whoop (0.17)**: a provider is a small class in `app/devices/` with its authorize URL, token exchange, refresh and
    fetch. Connections, the ledger, the flow store, the routes (`/api/devices/{provider}/…`), the loop and the UI list are
    shared.

## 3. Data (schema step 29)

```
device_connections(id, user_id → users ON DELETE CASCADE, provider, external_user_id, tokens_enc, key_id,
                   access_expires_at, scopes, status, sync_cursor, last_sync_at, last_success_at, last_error,
                   next_sync_after, created_at, updated_at)
  UNIQUE (user_id, provider); UNIQUE (provider, external_user_id)
device_imports(user_id → users ON DELETE CASCADE, provider, external_id, kind, row_id, imported_at)
  PRIMARY KEY (user_id, provider, external_id)
```

No CHECK on `provider` or `status`: a later version may add values (as `weights.source` has none).

## 4. API

| Route | What |
|---|---|
| `GET /api/devices` | The providers this server offers and the person's connection to each (status, last sync, counts). Never a token. |
| `POST /api/devices/{provider}/start` | `{url}` to send the browser to. 403 for a test account; 409 when already connected. |
| `GET /api/devices/{provider}/callback` | The way back. Redirects to `/#/devices/<word>/<provider>`. |
| `POST /api/devices/{provider}/sync` | Sync now. 429 within 10 minutes of the last one. |
| `DELETE /api/devices/{provider}?delete_readings=1` | Disconnect. |

All need a signed-in person; another person's connection is never visible (there is no id to guess: a person only ever
reaches their own).
