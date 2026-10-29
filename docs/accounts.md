# Accounts, sign-in and keys (operator guide)

Version 0.3 turns Kidney Health into a small multi-user app: each person signs in and sees only
their own log, foods, saved meals, profile, settings and keys. This page is for whoever runs the
server. The design and its reasoning are in
[`dev/research/07-accounts-settings-secrets.md`](dev/research/07-accounts-settings-secrets.md); the
API is in `ARCHITECTURE.md` ("M1 API").

## Choose how people sign in (`AUTH_MODE`)

| Mode | Use it when | What happens |
|---|---|---|
| `local` (default) | Most homes and small groups | Username and password, a session cookie, invites from the admin |
| `proxy` | You already run Authelia, authentik or `tailscale serve` and want its sign-in (and MFA) | The proxy tells the app who is signed in through a header; the app has no passwords |
| `none` | One person on a trusted network who wants the v0.2 behaviour | No sign-in at all; everything belongs to user 1; the app shows a red banner |

`none` means anyone who can open the page can read and change all data. Do not expose it beyond
your own network. In `none` mode there is no personal account to delete (Settings hides it and the
API answers `409`): every request is user 1, and the server would be unusable without it. If user 1
is missing anyway (deleted in `local` mode before switching), the next start creates it again,
empty, and `python -m app.admin check` warns about it.

## First start

On the first start of v0.3 the server upgrades the database (existing data stays, owned by the
first account) and needs a first admin. Pick one way:

1. **The setup code (default).** The server prints one line at WARNING level:

   ```
   FIRST-RUN SETUP: open https://food.home.example.net/#/setup and enter the code 7KQ2-M9XD-PL4R-T6WN (valid 60 min; ...)
   ```

   The address comes from `PUBLIC_URL`. Without it the line says "open this server's address followed
   by /#/setup (for example http://localhost:8000/#/setup)", since the server cannot know its own
   address or scheme. Find it with `podman logs kidney-health 2>&1 | grep FIRST-RUN` (or `docker logs`, `kubectl logs`).
   Open the page, enter the code, choose a username and a password. A new code is printed at every
   start while setup is pending, or run `python -m app.admin setup-code`.
2. **From a secret file (GitOps, Kubernetes).** Set `ADMIN_USERNAME` and `ADMIN_PASSWORD_FILE`
   (pointing at a mounted secret). The password must meet the policy below or the server will not
   start. Once an admin exists the variables are ignored (a warning says so); remove them.
3. **From the command line.** `printf '%s\n' "$PASSWORD" | python -m app.admin create-admin mum`
   inside the container.

Upgrading from v0.2 with `APP_PASSWORD` set: the old password becomes the password of the admin
`ADMIN_USERNAME` (or `admin` if you did not set one), once. HTTP Basic sign-in is gone. If the old
password is shorter than 15 characters, the app asks for a new one at the first sign-in. Remove
`APP_PASSWORD` afterwards.

The first start on an existing database also writes `kidney.db.pre-v3.bak` next to it (mode 0600).
That is your way back to v0.2: **restore it rather than running v0.2 against the upgraded file**,
which would mix everybody's entries together once a second person has joined. The copy is deleted
automatically 30 days after the upgrade, because it holds every meal logged before; delete it
earlier with `python -m app.admin purge-pre-v3-backup`.

## Passwords

At least 15 characters (`PASSWORD_MIN_LENGTH`, 8–64; NIST SP 800-63B-4 asks for 15 when a password
is the only factor), at most 128. No rules about digits or symbols and no expiry: a short sentence
or three or four unrelated words works well. The server refuses the 10,000 most common passwords,
the person's own name or username, the app's name, one repeated character and straight runs of keys
(`123456789012345`, `qwertyuiopasdfg`). Password managers and paste work. With
`PASSWORD_BREACH_CHECK=true` the server also asks Have I Been Pwned (only the first five characters
of a SHA-1 hash leave the server; add `api.pwnedpasswords.com` to your egress allowlist).

Passwords are stored as Argon2id hashes. Sign-in delays grow after five wrong passwords for one name
(30 s, doubling to 15 minutes); the device someone signed in from before is exempt. After 100 wrong
passwords in a row the account is locked; an admin unlocks it with a reset link.

One address (an IPv6 client counts per /64) is blocked for 10 minutes after
`LOGIN_IP_MAX_FAILURES` refused sign-ins (20 by default; a wrong password, a "wait" answer for a
name in its delay and "HTTPS required" all count) and may try at most 30 sign-ins a minute, so one
client cannot use up the server-wide budget of 60 sign-ins a minute and lock everyone else out. The
per-address limits do not apply to your proxy's own address (`TRUSTED_PROXIES`). Sign-ins that wait
for that budget or for a hashing slot wait without holding a server thread, so the rest of the app
stays responsive during a flood.

## Two-step sign-in

Anyone with a password can add a second step: a 6-digit code from an authenticator app on their phone (Aegis, 2FAS, Google
Authenticator, Microsoft Authenticator, 1Password, Bitwarden and others). It is off until a person turns it on, and nobody is made
to use it. The codes come from the phone's clock, so they need no network, no texts and no other company.

* Sign-in asks for the code after the right password. A wrong code counts like a wrong password, with the same delays and the same
  lock after 100.
* Turning it on gives the person **ten recovery codes**. Each one works once instead of a code, for a lost or broken phone.
* A reset link sets a new password but does not sign the person in. They sign in with the new password and a code.
* Phone shortcut and assistant tokens keep working. Each is its own credential and can only do one thing.
* No phone and no recovery codes: **Server administration → People → Remove two-step sign-in**, or
  `python -m app.admin remove-two-step USERNAME` (this works for the only admin too). The person then signs in with the password
  alone and can turn it on again.
* **Admins must use it** is a switch in **Server administration → Server settings → Sign-in and registration**, or
  `AUTH_REQUIRE_TWO_STEP_ADMINS=true`. While it is on, an admin without two-step sign-in can still use the app, but Server
  administration shows only a note that sends them to turn it on. You can switch it on there only after turning on your own.
  The command line is not affected.
* The secret each phone holds is stored encrypted with `SECRET_KEY`. If you lose that key, the codes stop working, but recovery
  codes still do, and you can remove two-step sign-in as above.

How it works, and why: [design note 17](dev/research/17-two-step-sign-in.md).

## Passkeys

Anyone with a password can also add **passkeys** in **Settings → Account → Passkeys**, up to 10. A passkey lets a person sign in with
the fingerprint, face or PIN of their phone or computer, with no password and no code: the sign-in page shows **Sign in with a
passkey**. The private key stays on the device, and the browser offers it only to this server's address, so it cannot be guessed,
phished or reused from a leak.

* Passkeys are an extra way in. The password keeps working, with the two-step code if that is on.
* Browsers that support it also list the person's passkeys when they tap the username field, so picking one there signs in too.
* A passkey sign-in is not asked for the two-step code: the device has already checked a fingerprint, face or PIN.
* Passkeys need the server's name, not an IP address, and HTTPS (or `localhost`). Set `PUBLIC_URL` to the address people open; a
  passkey works only there. Opened by an IP address, Settings says why it cannot add one.
* A failed passkey sign-in counts against the address like a wrong password. A passkey whose counter goes backwards, a sign of a
  copied key, is refused and shown in the person's activity.
* Lost or stolen device: the person removes that passkey in Settings, or you remove all of theirs in **Server administration →
  People → Remove passkeys**, or with `python -m app.admin remove-passkeys USERNAME`.
* When an action asks for the password again (adding a passkey, changing a key, exporting), **Use a passkey instead** answers
  it with the fingerprint, face or PIN. Only the person's own passkey counts, and failures count like wrong passwords.
* The server stores public keys only. Nothing about them is secret, and they are not in the data export.

How it works, and why: [design note 18](dev/research/18-passkeys.md).

## Sharing with a caregiver

A person can let someone else with an account on the same server **see** parts of their log: a partner who helps with food, a
parent, an adult child, a dietitian. The other person reads and never changes anything. It is off until you turn it on:
`SHARING_ENABLED=true`, or **Server administration → Server settings → Sharing**.

1. In **Settings → Account → Sharing**, the person ticks what to share (food log, lab results, weight and blood pressure,
   symptoms), picks how long (until they stop it, a week, 30 days, 90 days or a year) and presses **Make a link**. It asks for
   the password again, like making a token.
2. They send the link. It works once and for 7 days. Whoever opens it first while signed in can accept it, so it should go only to
   the right person. The link stays on the screen while Settings is open, until it is used or cancelled.
   The **Accept** button appears only after the app has checked that link. Opening another link replaces the question;
   a slow reply from the earlier link cannot change it back.
3. The other person opens it, sees who is sharing what, and presses **Accept**. Then **Settings → Account → Sharing → Shared with
   you → Open** shows the person's summary (the Visit prep page) and one day of food at a time, and **Trends** shows their Trends
   charts, both with a banner that says it is read-only.
   A shared weight chart uses that person's dry weight. If their profile cannot be loaded, the dry-weight line is left out;
   your own dry weight is never used on their chart.
   While Trends loads, the food charts, symptoms and weight and blood pressure cards clear first, so the previous person's data
   is never left under the new heading. If a part cannot load, press **Retry**.

* Never shared: notes about tastes, saved meals and recipes, AI settings and activity, keys, tokens, passkeys, sign-in activity,
  the date of birth and other profile details. The weight saved in the profile is shared only with weight and blood pressure.
* A share with an end date stops by itself on that day, and the person's activity says so.
* Either side can stop at once: **Stop sharing** or **Stop seeing**. The person's list says who can see their data and when they
  last looked. The first look each day goes to the person's activity.
* At most 10 people can see one person's data, and a person can have 5 unused links.
* You can end every share of a person in **Server administration → People → End sharing**. Deleting either account deletes its
  shares. While an account is turned off, nothing it shares can be seen.
* Not with `AUTH_MODE=none`, where there is only one person.

How it works, and why: [design note 19](dev/research/19-sharing.md).

The shared food-day card loads without waiting for the rest of the summary. Changing the date or person
discards older replies, so a slow response cannot replace the day you chose. If loading fails, press **Retry**.

## Adding people

* **Invite (default, `registration.mode = invite`).** Server administration → People → Invite.
  Copy the link and send it however you like; it works once and expires after 7 days
  (`registration.invite_ttl_days`). The secret part sits after `#`, so it never reaches the
  server's or a proxy's logs.
* **Closed.** The admin creates the account (username, role) and gets a one-time link where the
  person sets their password.
* **Open.** Anyone who reaches the page can register (HTTPS only, 3 accounts per address per hour).
  Only for servers meant to be public.

**Use HTTPS before adding a second person.** While only one account exists the app also works over
plain `http://` on your network; as soon as there are two, signing in over plain HTTP from another
device is refused (`ALLOW_INSECURE_HTTP=true` overrides this; do not). See [https.md](https.md).
Give the app its own host name and do not serve other plain-HTTP apps on that same name or address:
cookies are not separated by port.

## Lost passwords and locked accounts

There is no e-mail. An admin opens Users, picks the person and chooses **Reset link** (valid 24
hours, single use); completing it signs the person out everywhere and unlocks the account. The
person sees "Your password was reset with a link from an admin" at their next password sign-in, so a
reset cannot happen silently. The page the link opens shows the account's username (an account an
admin created was never seen by its owner), so password managers save both.

Open reset and setup links are listed with the account (Admin → People: "Password reset link open
until …, created by …") and can be revoked there; a link someone created for **your** account is
flagged in your own row. A link stops working when the account's password changes any other way,
when the account is disabled, and when its creator stops being an admin: demoting, disabling or
deleting an admin deletes every unused invite and reset or setup link they created.

The only admin locked out: `python -m app.admin reset-password mum` prints a link (set `PUBLIC_URL`
for a full address), or `printf '%s\n' "$NEW" | python -m app.admin reset-password mum --stdin` sets
it directly. `python -m app.admin list-users` shows every account.

## Proxy mode

Requirements (the server refuses to start otherwise):

* `AUTH_MODE=proxy`, `TRUSTED_PROXY_USER_HEADER` (`Remote-User`, `X-authentik-username`,
  `Tailscale-User-Login`), `TRUSTED_PROXIES` listing only your proxy (never `0.0.0.0/0`), and
  `TRUSTED_PROXY_SECRET_FILE`: a shared secret your proxy sends as `X-Proxy-Secret`. Headers from
  anything else are dropped and counted on Admin → About. `tailscale serve` cannot add headers; there
  set `TRUSTED_PROXY_SECRET_OPTIONAL=true` and make sure nothing else can reach the app's port.
* Optional: `TRUSTED_PROXY_GROUPS_HEADER` and `TRUSTED_PROXY_ADMIN_GROUP` (members are admins; the
  role follows the groups on every request), `TRUSTED_PROXY_NAME_HEADER`, `PROXY_AUTO_CREATE_USERS`
  (otherwise the admin adds each proxy name first), `PROXY_LOGOUT_URL`.

First setup in proxy mode still uses the setup code, opened through the proxy: the person who enters
it becomes the admin. A proxy name never takes over a local account with the same name. Changing
`AUTH_MODE` signs everybody out and revokes every assistant and phone shortcut token ([what ends a token](assistant.md#what-ends-a-token)).

Caddy with Authelia, for example:

```
kidney.example.org {
  forward_auth authelia:9091 {
    uri /api/authz/forward-auth
    copy_headers Remote-User Remote-Groups Remote-Name
  }
  reverse_proxy kidney-health:8000 {
    header_up X-Proxy-Secret {$KH_PROXY_SECRET}
  }
}
```

## Keys (USDA now, AI later)

People can store their own USDA FoodData Central key (Settings → Food data) and the admin can share
one (Admin → Shared keys, or `USDA_API_KEY_FILE`, which locks it). A person's own key always wins;
the shared one is used when the admin allows it (`providers.usda.shared_enabled`, per-person "may
use shared keys") and within `providers.usda.daily_limit_per_user` lookups per day (200 by default;
api.data.gov allows 1,000 per hour per key). A rejected own key is never silently replaced by the
shared one.

Keys are write-only: the app shows "set, ends in 9xQz" and nothing more, never logs them, and stores
them encrypted with a key derived from `SECRET_KEY`. **Mount `SECRET_KEY_FILE` from your engine's
secret store**; the auto-generated `/data/secret.key` sits in every volume backup. Losing the key
loses only the stored API keys (people enter them again); passwords and health data are not
affected. Rotation: `python -m app.admin rotate-secret-key` (auto-generated key) or add a new first
line to `SECRET_KEY_FILE`, restart, `python -m app.admin reencrypt`, remove the old line, restart.

## Admins and privacy

Admins manage accounts, settings and shared keys. There is no screen or API to read another
person's log, foods or profile, and no "sign in as". But whoever runs the server can technically
read the database, and an admin can issue a reset link for any account (the person is told at
their next sign-in). Say so to the people you invite; [privacy.md](privacy.md) has the wording.

The audit log (Admin → Activity) records sign-ins, failed sign-ins on existing accounts, invites,
role and status changes, password resets, setting changes (old and new values), key changes
(provider only, never the key), exports, imports (counts only) and deletions, each with who did it and which account it
concerned. It never holds health data or typed usernames of unknown accounts, and keeps entries for
365 days (`AUDIT_RETENTION_DAYS`). A person's own "Recent sign-in activity" lists only events about
their account (including what an admin did to it), never an admin's actions on other accounts.

## Command reference

`python -m app.admin` `create-admin USER` · `reset-password USER [--stdin]` · `list-users [--json]` ·
`setup-code` · `revoke-sessions USER|--all` · `remove-two-step USER` (lost phone and recovery codes) · `remove-passkeys USER` (lost or stolen device) · `export-user USER FILE|-` (that person's data export, for
someone who cannot sign in) · `disable-user USER` (never the only admin; signs out their devices; enable
it again in Settings → People) · `purge-pre-v3-backup` · `vacuum` · `backup FILE|-` ·
`check` · `restore-check FILE [--revoke-sessions]` · `rotate-secret-key` · `reencrypt` · `settings
list|get|set|unset`. `backup` writes its copy in SQLite's rollback-journal mode, and `restore-check`
opens a read-only file as immutable, so a backup can be checked on a read-only mount
([deployment.md](deployment.md#backups-and-restore)).
