# 34 · Password reset by email

| | |
|---|---|
| Status | Accepted and built, 2026-11-07. Not yet released. Schema step 34. |
| Owner's words (2026-11-07) | "Do it": password reset by email, small and plain. |
| Builds on | Note 07 §4.5 (reset links: single use, token in the URL fragment, only a hash stored), §4.9 (throttles), §6 "Later": "optional SMTP for self-service reset". |
| Out of scope | Signing in by email link. Email for anything else (reminders, invites, Care team). Email as a user name. Showing an address to anyone but its owner. |

## 1. What it is

Until now a person who forgot their password asked an admin for a reset link. With this, a person may add an email address in
Settings → Account. Once they confirm it, "Forgot your password?" on the sign-in page sends a reset link to that address. The
link is the same kind an admin makes, but it works for 1 hour instead of 24.

It is off unless the person who runs the server sets up a mail server. The admin's reset link still works as before.

## 2. Why

Families use this app at home. The admin is often the same person who forgot. A link to one's own inbox is the usual way back
in, and the server already had single-use reset links. All that was missing was a way to send one.

## 3. Settings (environment only)

| Variable | Default | Meaning |
|---|---|---|
| `EMAIL_ENABLED` | `false` | Turns it on. Needs `AUTH_MODE=local` and `PUBLIC_URL`, or the server does not start. |
| `SMTP_HOST` | none | The mail server. Required when on. |
| `SMTP_PORT` | `587` | Its port. |
| `SMTP_SECURITY` | `starttls` | `starttls`, `tls` (encrypted from the first byte, usually port 465) or `none`. `none` only to `localhost`, `127.0.0.1` or `::1`; any other host stops the start. |
| `SMTP_USERNAME` | none | The user name, when the mail server asks for one. |
| `SMTP_PASSWORD_FILE` | none | A file holding its password. `SMTP_PASSWORD` given inline stops the start, as for the other secrets. |
| `SMTP_FROM` | none | The sender, such as `kidney@example.org` or `Kidney Health <kidney@example.org>`. Required when on. |
| `SMTP_TIMEOUT_S` | `15` | Seconds per step. The whole send stops after twice this. |

These are not runtime settings: where the server sends mail is decided by the person who runs it, like every other outbound
address.

## 4. How it works

* **Schema step 34.** `users.email` (at most 320 characters, stored lower case) and `users.email_confirmed_at`. A unique index
  covers confirmed addresses only. `email_tokens` holds the confirmation links: SHA-256 of the verifier, the address it was sent
  to, 24 hours, single use. They are in their own table because `auth_tokens.purpose` has a CHECK that allows only setup, invite
  and reset, and changing it would mean rebuilding the table.
* **Setting an address** (`PUT /api/me/email`) needs a password entered in the last 10 minutes. It saves the address as not
  confirmed and emails a link to `<PUBLIC_URL>/#/confirm-email/<token>`. Until the link is opened the address gets no reset
  emails. Saving the same address again sends a new link. Removing it (`DELETE /api/me/email`) needs nothing more.
* **Confirming** (`POST /api/auth/email/confirm`) works without being signed in, so the link can be opened on any device. A link
  for an address the person has since changed does not confirm the new one.
* **Forgot your password?** (`POST /api/auth/forgot {username}`) always answers `202` with the same words. Only for an active,
  local, non-test account with a confirmed address does it void the account's older reset links, make a new one for 1 hour and
  email it. The email is sent after the answer, so the answer takes about as long either way. `POST /api/auth/reset` then works
  unchanged: it signs every other session out, removes every passkey, voids the other links and keeps two-step sign-in.
* **Limits.** 10 requests an hour from one address (429 after that). 3 an hour per typed user name, counted whether or not the
  account exists; beyond that the answer is the same 202 and nothing is sent. 5 confirmation or test emails an hour per person.
* **Admin.** Server administration → About this server says whether email is on and where it goes (never the password), and has
  "Send a test email" to the admin's own confirmed address. The user list shows "Email confirmed", never the address.
* **Audit.** `email.set`, `email.confirmed`, `email.removed` (the person's own activity, without the address);
  `user.reset_link_issued` with `via: email`; `user.password_changed` with `via: email_link`.
* **Export.** The person's own `export.json` has the address under `user`. The import skips it.
* **Demo.** The demo sends nothing: an address counts as confirmed at once, and the answers say "Demo: nothing was sent".

## 5. The emails

Plain text. No health data, and no name except the user name.

> Someone asked to reset the password for sam on Our kitchen.
>
> Open this link within 1 hour to choose a new one: (link)
>
> The link works once. Choosing a new password signs you out on your other devices.
>
> If this was not you, ignore this email. Your password stays the same.

The confirmation email says the same kind of thing for 24 hours. The test email says only that it is a test.

## 6. Threats

* **Finding out who has an account.** The forgot answer is the same status, body and length for every name, and the per-account
  limit is silent. Sending happens after the answer. Sign-in itself already answers the same way for a wrong name and a wrong
  password.
* **Link lifetime.** 1 hour, single use, only its hash stored, carried in the URL fragment so it stays out of server and proxy
  logs. A newer request voids the older links. Changing or removing the address voids the reset links sent to it.
* **The mail server.** The server sends only to the host its operator set (`SMTP_HOST`), never to a host taken from a request, so
  this is not the SSRF-checked HTTP transport. TLS is verified (`ssl.create_default_context`). Plain SMTP is refused unless the
  mail server is on the same machine. The password is read from a file, kept out of `repr` and the log, and never returned by
  an API. The log says only "email sent" or "email failed: <error class>": never the address, the text or the link.
* **The mailbox.** Whoever reads the person's email can reset the password. That is the usual trade-off of email resets, and it
  is why the feature is optional per person and off per server. Two-step sign-in still asks for the code after a reset.
* **Someone who sets an email on another person's account** must already be signed in as them and know their password (the
  change needs a recent password). They could then reset the password later from that mailbox. The person sees `email.set` in
  their activity and the address in Settings. They can remove it, and changing the password does not need it.
* **Someone who types another person's address on their own account** gets nothing: it stays unconfirmed, receives one
  confirmation email the owner can ignore, and never blocks the owner from confirming it on their own account (the unique
  index covers confirmed addresses only). If the owner has confirmed it, the other link answers "already confirmed for another
  account" only to whoever opens it, which means the mailbox owner.
* **Annoying someone with emails.** At most 3 reset emails an hour per account and 10 requests an hour per address.
* **Voiding an admin's link.** A forgot request voids the account's open links, including one an admin made. That only happens
  for an account with a confirmed address, whose owner then gets a fresh link by email.
