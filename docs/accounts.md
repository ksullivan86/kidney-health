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
your own network.

## First start

On the first start of v0.3 the server upgrades the database (existing data stays, owned by the
first account) and needs a first admin. Pick one way:

1. **The setup code (default).** The server prints one line at WARNING level:

   ```
   FIRST-RUN SETUP: open https://<this server>/#/setup and enter the code 7KQ2-M9XD-PL4R-T6WN (valid 60 min; ...)
   ```

   Find it with `podman logs kidney-health 2>&1 | grep FIRST-RUN` (or `docker logs`, `kubectl logs`).
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

## Adding people

* **Invite (default, `registration.mode = invite`).** Settings → Admin → Users & invites → Invite.
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
person sees "Your password was reset with a link from an admin" at their next sign-in, so a reset
cannot happen silently.

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
`AUTH_MODE` signs everybody out.

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
(provider only, never the key), exports and deletions. It never holds health data or typed
usernames of unknown accounts, and keeps entries for 365 days (`AUDIT_RETENTION_DAYS`).

## Command reference

`python -m app.admin` `create-admin USER` · `reset-password USER [--stdin]` · `list-users [--json]` ·
`setup-code` · `revoke-sessions USER|--all` · `purge-pre-v3-backup` · `vacuum` · `backup FILE|-` ·
`check` · `restore-check FILE [--revoke-sessions]` · `rotate-secret-key` · `reencrypt` · `settings
list|get|set|unset`.
