---
title: Users and keys
description: "Create the first admin, invite people, reset passwords, share USDA and AI keys with daily limits, and handle the secret key."
slug: users-and-keys
audience: [self-hoster]
applies_to: [all]
status: draft
reviewed_by: ""
reviewed_on: null
last_checked: 2026-10-06
fact_checked: 2026-10-05
sources: [NOTE07, NOTE04, DEPLOY, SECDOC, NIST-63B4, FDC-API]
---

# Users and keys

From v0.3 every person has their own account, and nobody sees anyone else's log. As the admin you create
the first account, invite the others, and decide which API keys to share ([design note 07][NOTE07]).
Being admin does not give you a screen to read other people's data.

## The first admin

On the first start of an empty (or v0.2) database the app creates no account by itself. It prints a
**one-time setup code** to its log, valid for 60 minutes:

```
FIRST-RUN SETUP: open https://food.home.example.net/#/setup and enter the code 7KQ2-M9XD-PL4R-T6WN (valid 60 min; ...)
```

1. Read it from the log: the line starts with `FIRST-RUN SETUP` (the command for each engine is in
   the deployment guide's [first-run section](https://github.com/ksullivan86/kidney-health/blob/main/docs/deployment.md#first-run)).
2. Open the address, enter the code, and choose the admin's user name and a password of at least
   15 characters ([NIST SP 800-63B-4][NIST-63B4]).
3. The setup screen also asks whether to switch on Open Food Facts barcode lookups (off by default).

Until setup is done, every API call except setup answers `503 Setup required`. An expired code: restart,
or run `python -m app.admin setup-code` in the container.

Alternatives ([deployment guide][DEPLOY]):

- **GitOps:** `ADMIN_USERNAME` plus `ADMIN_PASSWORD_FILE` create the admin on first start.
- **CLI:** `python -m app.admin create-admin USERNAME` reads the password from stdin.
- **Upgrading from v0.2:** the existing log becomes the admin's (user 1). A v0.2 `APP_PASSWORD` becomes
  that admin's password once; if it is shorter than 15 characters, you are asked to change it.

## Invite people

**Settings → Admin → Users & invites → Invite**. The app shows a link **once**:
`https://food.home.example.net/#/invite/…`. Send it however you like; it works once and expires after
7 days. The secret part sits after `#`, which browsers never send to the server, so it stays out of
proxy logs. Revoke unused invites from the same screen.

| `REGISTRATION_MODE` | Who can create an account |
|---|---|
| `invite` (default) | people with an invite link |
| `closed` | only the admin; each person sets their password from a one-time link |
| `open` | anyone who reaches the page (HTTPS required; 3 sign-ups per address per hour) |

**Use HTTPS before you invite anyone.** With two or more accounts the app refuses plain-HTTP sign-in
from other machines ([HTTPS for phones](https.md)).

## Roles

- **user**: their own log, foods, meals and settings.
- **admin**: also users and invites, sign-in settings, shared keys, usage counts, the activity log and
  server status. **No impersonation and no log viewer.**
- An admin can issue a password-reset link for anyone. That signs the person out everywhere and tells
  them at their next sign-in, and it appears in their activity, so it cannot be done quietly
  ([design note 07][NOTE07]).
- Open reset and setup links are listed under each account in **Settings → Admin → People**, with
  who created them, and can be revoked there. A link someone made for **your own** account is
  flagged in your row.
- Removing an admin contains them: demoting, disabling or deleting an admin also deletes every
  unused invite and reset or setup link they created. A reset link also stops working once the
  account's password is changed another way, or the account is disabled.

## Passwords and lock-outs

- No email in v0.3, so no self-service reset. **Settings → Admin → Users → Reset link** (24 hours,
  single use), or `python -m app.admin reset-password USERNAME`. `--stdin` sets a password directly
  (break-glass; also unlocks a locked account).
- Repeated wrong passwords slow that account down, then block the address for a while (refused
  attempts of any kind count, and an IPv6 network counts as one address). After 100 failures in a
  row an account needs an admin reset.
- An account the admin creates gets a one-time setup link; the page it opens shows the username the
  admin chose, so the person (and their password manager) knows what to sign in with.
- `python -m app.admin list-users` and `revoke-sessions USERNAME` (or `--all`) help after a lost phone.

## Shared keys and quotas

| Key | Set it as | Daily limit per person |
|---|---|---|
| USDA FoodData Central | `USDA_API_KEY_FILE` (locked), or **Admin → Shared keys** | `USDA_SHARED_DAILY_LIMIT`, default 200 |
| AI provider (v0.3) | `AI_*` variables (locked), or **Admin → AI providers** | `AI_SHARED_DAILY_LIMIT`, default 30 |

- A USDA key is free and allows 1,000 requests an hour; the server stays under that
  ([USDA API guide][FDC-API]).
- Per person you can switch shared use off ("can use shared keys").
- People may add **their own** keys (on by default). Their own key is always used first, has no app
  quota, and is never swapped for the shared one when it fails.
- Keys are **write-only**: the app shows "set, ends in 9xQz", never the key. A key set by environment
  shows "Set by the server" and cannot be changed in the app.
- For a Hermes agent, paste the key of the **dedicated tool-free profile**, never your main one
  ([design note 04][NOTE04]).

## The secret key

`SECRET_KEY` encrypts stored API keys (not passwords, not health data). Every shipped profile mounts it
as `SECRET_KEY_FILE` from the engine's secret store, **outside** the data volume, and you should keep a
copy in a password manager ([operator security guide][SECDOC]). Lose it, and stored keys must be entered
again; nothing else is lost.

Rotate it ([deployment guide][DEPLOY]):

- auto-generated `/data/secret.key`: `python -m app.admin rotate-secret-key`, then restart;
- mounted file: add a new **first** line, restart, `python -m app.admin reencrypt`, remove the old line,
  restart.

**Settings → Admin → About this server** shows where the key comes from and whether any secret still
uses an older key.

## Proxy sign-in instead of passwords

With Authelia, Authentik or `tailscale serve` in front, `AUTH_MODE=proxy` takes the user name from a
header. It needs `TRUSTED_PROXY_USER_HEADER`, a matching `TRUSTED_PROXIES`, and
`TRUSTED_PROXY_SECRET_FILE` (a value the proxy sends as `X-Proxy-Secret`); without the secret the app
refuses to start. Set-up details: [Configuration](configuration.md#proxy-sign-in-auth_modeproxy) and the
[deployment guide][DEPLOY].

## If something goes wrong

- **No `FIRST-RUN SETUP` line**: an admin already exists, or `ADMIN_PASSWORD_FILE` was used. Check
  `python -m app.admin list-users`.
- **"Your account is not enabled here"** in proxy mode: create the account first, or set
  `PROXY_AUTO_CREATE_USERS=true`.
- **The only admin is locked out**: `python -m app.admin reset-password USERNAME --stdin`.
- More: [Troubleshooting](troubleshooting.md).

## Related pages

- [Configuration](configuration.md) · [Security](security.md) · [Backups](backups.md)
- For your users: [First setup](../app/first-setup.md) · [Settings and keys](../app/settings-and-keys.md)

## Sources

- [Design note 07: accounts, settings and secrets][NOTE07], sections 4.3–4.5, 4.12 and the security review.
- [Design note 04][NOTE04] (AI providers); [deployment guide][DEPLOY]; [operator security guide][SECDOC].
- [NIST SP 800-63B-4][NIST-63B4]; [USDA FoodData Central API guide][FDC-API].
