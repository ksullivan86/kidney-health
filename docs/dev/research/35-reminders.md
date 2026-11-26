# 35 · Reminders by phone notification

| | |
|---|---|
| Status | Accepted and built, 2026-11-12. Not yet released. Schema step 35. |
| Owner's words | Build reminders by Web Push, opt-in, small and plain. |
| Builds on | Note 02 §F6 (Web Push facts) and §R8 (the plan). ROADMAP "Installable app". |
| Out of scope | Anything about lows, insulin, medicines or glucose. Dosing of any kind. Reminders by email. Reminders sent to a Care team helper. |

## 1. What it is

A person can ask for a notification on their phone or computer at a time they choose: "Time to log lunch.", "Time to plan
tomorrow's meals." or "Time to log your weight." They turn notifications on for each device in Settings → Reminders, and pick
the times and days.

It is off unless the person who runs the server turns it on.

**Reminders are a convenience. Do not rely on them for low blood sugar; use your CGM's alerts.** The screen, the docs and the
handbook say this. There is no reminder about lows, insulin, medicines or glucose, and there never will be: delivery is best
effort, Focus modes silence it, and it needs the home server online.

## 2. Why

People asked for a nudge to log meals. A missed meal in the log makes the day's totals wrong. The app is installable already
(note 02), and iPhones show web notifications from Home Screen apps since iOS 16.4.

## 3. Settings (environment only)

| Variable | Default | Meaning |
|---|---|---|
| `REMINDERS_ENABLED` | `false` | Turns it on. Its own switch: `PUSH_ENABLED` already means phone shortcuts (`/push/v1`). |
| `VAPID_SUBJECT` | none | `mailto:` or `https:` contact for the push services. Required when on. Apple refuses other forms. |
| `VAPID_PRIVATE_KEY_FILE` | `$DATA_DIR/vapid_private.pem` | The server's P-256 key in PEM. Made once, mode 0600, when the file does not exist and is inside `DATA_DIR`. A missing file elsewhere stops the start. `VAPID_PRIVATE_KEY` given inline stops the start. |
| `REMINDERS_TIMEOUT_S` | `10` | Seconds per request to a push service. The whole send stops after twice this. |

On needs `PUBLIC_URL` with `https://` (or `http://localhost` for trying it out), because browsers allow push only on secure
pages and the notification opens `PUBLIC_URL`. It is refused with `AUTH_MODE=none`: a server without accounts is a demo.

## 4. How it works

* **Keys.** VAPID (RFC 8292): an ES256 JWT with `aud` (the push service's origin), `exp` 12 hours ahead (Apple allows at most
  24) and `sub` (`VAPID_SUBJECT`), reused for up to 1 hour per push service, as Apple asks. Message encryption is RFC 8291
  `aes128gcm` (RFC 8188), one record. Both are written on the `cryptography` package, like the OIDC and passkey code. No new
  dependency. Tests check the RFC 8291 Appendix A example byte for byte.
* **Schema step 35.** `push_subscriptions` (one row per device: endpoint, keys, the browser's User-Agent, when it last worked
  and its last error) and `reminders` (kind, meal, time, days, time zone, on/off, the date it last went out). Both hang off
  `users` with `ON DELETE CASCADE`. At most 10 reminders and 5 devices per person.
* **Time zone.** The app has no time zone in the profile, and a container often runs on UTC. Each reminder keeps the browser's
  time zone (an IANA name such as `America/Chicago`) when it is saved. With none, the server's own time is used.
* **Push hosts.** The browser picks the push service. The server sends only to these, over `https` on port 443:
  `*.push.apple.com`, `fcm.googleapis.com`, `updates.push.services.mozilla.com` and `*.notify.windows.com`. Any other address is
  refused when the device is added (400). Every request goes through `app/egress.py` with private addresses refused, no
  redirects, and a deadline. A `404` or `410` from the push service deletes that device.
* **The loop.** Once a minute a background task looks for reminders that are on, whose day it is and whose time came in the
  last 5 minutes, in the reminder's time zone, and that have not gone out today. It marks the reminder sent before sending, so
  it goes out at most once a day. A meal reminder is skipped when that meal already has eaten food logged for today.
* **The message.** Declarative Web Push JSON, which iOS 18.4+ shows without running any code:
  `{"web_push": 8030, "notification": {"title": "Food log", "body": "Time to log lunch.", "navigate": "<PUBLIC_URL>/#add"}}`,
  with `TTL: 3600` and `Urgency: normal`. The service worker's `push` handler shows the same notification on other browsers,
  and `notificationclick` opens `navigate`. The title is the server name when the admin changed it, else "Food log": the
  default name has "Kidney" in it, and a lock screen is public.
* **Bodies stay generic.** No nutrient values, condition names, food names or the person's name. The push service sees when a
  message is sent, so the words say nothing about health.
* **Test accounts** cannot use it (403): the account is shared by testers.
* **Audit.** `reminder.set`, `reminder.removed`, `reminder.device_added`, `reminder.device_removed`, all in the person's own
  activity.
* **Export.** The reminders are in `export.json`. The devices and their keys are not: they belong to one browser.
* **Demo.** The routes answer, nothing is sent, and "Send a test" says so.

## 5. API

| Route | What it does |
|---|---|
| `GET /api/reminders` | Whether it is on, whether this person can use it, the public key, the kinds, the reminders and the devices. With the server switch off: `{"enabled": false, ...}`. |
| `POST /api/reminders` | Add a reminder: `{kind, meal?, time, days, time_zone?, enabled?}`. |
| `PATCH /api/reminders/{id}` | Change one. |
| `DELETE /api/reminders/{id}` | Remove one. |
| `POST /api/reminders/subscriptions` | Add this device: `PushSubscription.toJSON()`. The same endpoint again answers the same device. |
| `DELETE /api/reminders/subscriptions/{id}` | Remove a device. |
| `POST /api/reminders/test` | One test notification to each of this person's devices. 5 an hour. |

Every route needs a signed-in person and touches only their own rows; another person's id is 404. With the switch off every
route but `GET` is 404.

## 6. Threats

* **SSRF.** The endpoint comes from the browser, so it is a URL a person controls. Only the fixed push hosts are accepted, at
  subscribe time and again at send time, through the checked transport.
* **The private key.** Read from a file, never logged, never in any answer. The public key is public by design.
* **Someone else's device.** Endpoints are long random URLs the browser makes. If a second account on the same browser turns
  notifications on, the device moves to that account: one browser profile has one subscription per site.
* **What the push service learns.** The time of each message and that this server sent it. The body is encrypted end to end;
  it is generic anyway.
* **Annoyance.** At most 10 reminders, each at most once a day, and 5 test sends an hour.

## 7. In the iPhone app (added 2026-11-26)

Owner, 2026-11-26: what the web app does with a server should work in the iPhone app without one when it makes sense. Reminders
do. In the iPhone app they are the iPhone's own notifications. No Web Push, no server and no push service are involved.

* **Where they are kept.** In the log on the phone, like the rest of the data (`js/mock/reminders.js`). They are in the export.
  The same routes, limits and texts as §5 answer; the device routes are not used.
* **Planning.** The page plans the next 7 days as single notifications, at most 60 (iOS keeps 64 pending; a few stay free).
  Each is a reminder that is on, on one of its days, at its time, still in the future. A meal reminder for today is left out when
  that meal already has eaten food logged today, as the server does.
* **When.** After a reminder is added, changed or removed, after each save of the log, when the app starts and when it comes back
  to the front. The page sends the whole plan; the app replaces every pending reminder with it.
* **Time.** The phone's own time zone, at the moment each one goes off. A reminder's saved `time_zone` is not used on the phone.
* **The bridge.** `{kind: "reminders", action}` to the app's `bridge` handler:
  `status` and `allow` answer `{ok, permission: allowed | denied | not_asked, pending}`; `allow` asks iOS only from the person's
  tap. `schedule` takes `items: [{id, at: "YYYY-MM-DDTHH:MM", kind, meal}]`. `test` sends one in 5 seconds. `openSettings` opens
  the app's page in iOS Settings.
* **The words.** The app writes them, not the page: title "Food log", the bodies of §4, and the test's sentence. The page sends
  only the kind and the meal, so no other text can reach the lock screen. No health words, no food names.
* **A tap** opens the screen of §4 (`add`, `plan`, `today`; the test opens Settings) once the page has started.
* **Not allowed.** If the person said no, Settings says how to allow it: Settings, Notifications, Kidney Health, Allow
  Notifications. Nothing is planned until they do.
* **With a server (note 39).** Reminders set on the phone stay on the phone. They are not synced. The screen says so.
* **Safety.** The line of §1 stays on the screen. There is no reminder about lows, insulin, medicines or glucose.
