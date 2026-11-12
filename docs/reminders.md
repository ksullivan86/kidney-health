# Reminders by phone notification

A person can get a notification on their phone or computer at a time they choose: "Time to log lunch.", "Time to plan
tomorrow's meals." or "Time to log your weight." It is off unless the person who runs the server turns it on.

**Reminders are a convenience. Do not rely on them for low blood sugar; use your CGM's alerts.** There is no reminder about
lows, insulin, medicines or glucose. A notification can arrive late or not at all: Focus modes silence it, the phone may be
off, and the home server must be up.

This page is for the person who runs the server and for people who change the code. The contract is in
[`ARCHITECTURE.md`](../ARCHITECTURE.md) ("Reminders by phone notification") and the design note is
[`dev/research/35-reminders.md`](dev/research/35-reminders.md). The person's side is in the handbook: **Settings and keys →
Reminders**.

Not the same as [phone shortcuts](push.md): `PUSH_ENABLED` and `/push/v1` let an iPhone Shortcut *send* weights to the server.
Reminders *come from* the server and have their own switch.

## Turn it on (admin)

```
REMINDERS_ENABLED=true
VAPID_SUBJECT=mailto:you@example.org
PUBLIC_URL=https://kidney.example.org
```

* `VAPID_SUBJECT` tells the push services how to reach you if something goes wrong: `mailto:` with your address, or an `https:`
  address. Apple refuses anything else.
* `PUBLIC_URL` must be `https://`. Browsers allow notifications only on secure pages, and a notification opens this address.
  `http://localhost` works for trying it out on one computer.
* The server makes its push key once, in `DATA_DIR/vapid_private.pem`, mode 0600. It is part of your backup of the data folder.
  To keep it elsewhere, set `VAPID_PRIVATE_KEY_FILE` to a P-256 key in PEM (`openssl ecparam -name prime256v1 -genkey -noout |
  openssl pkcs8 -topk8 -nocrypt`). `VAPID_PRIVATE_KEY` given inline stops the start, as for the other secrets.
* If the key changes, every device must be turned on again: the push services refuse messages signed with another key.
* `REMINDERS_TIMEOUT_S` (default 10) is how long to wait for a push service. A send stops after twice that.
* With `AUTH_MODE=none` the server does not start with reminders on: a server without accounts is a demo.

These are environment settings only. Where the server sends is decided by the person who runs it.

**Firewall.** The server sends to the push services, `https` on port 443 ([network allowlist](network-allowlist.md)):

| Browser | Push service |
|---|---|
| Safari on iPhone, iPad and Mac | `web.push.apple.com` (any `*.push.apple.com`) |
| Chrome, Edge and most browsers on Android and computers | `fcm.googleapis.com` |
| Firefox | `updates.push.services.mozilla.com` |
| Some Edge on Windows | `*.notify.windows.com` |

A device on any other push service is refused when it is added. The Cilium example in `deploy/k8s` has these hosts commented.

## On the phone

* **iPhone and iPad (iOS 16.4 or later):** notifications work only in the app added to the Home Screen. In Safari, tap Share, then
  Add to Home Screen, open the app from there, then Settings → Reminders → Turn on notifications on this device. iOS 18.4 and
  later show the message without running the app's code.
* **Android and computers:** Settings → Reminders → Turn on notifications on this device, in the browser.
* Each phone or computer is turned on by itself, up to 5 per person. The list shows them with "This device" on the one in hand.

## What a person sees

Settings → Reminders, shown only when the server has it on:

* the safety words above;
* **This device**: Turn on notifications on this device (the browser asks for permission only after this tap), Send a test,
  Turn off on this device;
* **Your reminders**: up to 10, each with what (log breakfast, lunch, dinner or a snack, plan tomorrow, log your weight), a time
  and days. The time is in the phone's time zone when the reminder is saved;
* **Devices with notifications on**: each one with Remove, and a short note when the last send did not work.

A meal reminder is skipped when that meal already has food logged as eaten that day. Each reminder goes out at most once a day,
at its time or within 5 minutes after it. A reminder whose time passed while the server was down is not sent late.

Test accounts cannot use reminders. The demo shows the block but never sends anything.

## What is sent

To the device's push service, encrypted so only that browser can read it (RFC 8291):

```
{"web_push": 8030, "notification": {"title": "Food log", "body": "Time to log lunch.", "navigate": "https://kidney.example.org/#add", "lang": "en"}}
```

The title is the server name you set in Server administration, or "Food log" while it is the default "Kidney Health": a lock
screen is public. The words never hold food names, numbers, a condition or the person's name. The push service learns when a
message is sent and that it came from this server.

## Routes

```
GET    /api/reminders                     status, public key, kinds, the person's reminders and devices
POST   /api/reminders                     {"kind": "log_meal", "meal": "lunch", "time": "12:30", "days": 31, "time_zone": "America/Chicago"}
PATCH  /api/reminders/{id}
DELETE /api/reminders/{id}
POST   /api/reminders/subscriptions       PushSubscription.toJSON()
DELETE /api/reminders/subscriptions/{id}
POST   /api/reminders/test                one test to each device, 5 an hour
```

`days` is a bitmask: 1 Monday, 2 Tuesday, 4 Wednesday ... 64 Sunday; 127 every day, 31 weekdays. While the switch is off, `GET`
answers `{"enabled": false, ...}` and the other routes `404`.

## Troubleshooting

* **The block is missing in Settings:** `REMINDERS_ENABLED` is not `true`, or the server did not start. The log names the
  missing setting.
* **"Notifications are blocked for this site":** the person said no once. They allow it again in the browser's or phone's
  settings.
* **A device shows "The push service did not accept this server":** the key changed. Turn notifications off and on again on
  that device.
* **A device shows "The server could not reach this device's push service":** a firewall blocks the host above.
* A device the push service no longer knows (the app was removed, or the browser data cleared) is deleted at the next send.

Nobody has yet tested this on a real iPhone and Android phone. That is listed in the [roadmap](ROADMAP.md).
