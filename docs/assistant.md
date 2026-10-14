# The assistant: a chat assistant that reads your own numbers

The owner's main AI wish is an assistant you can talk to about food ("what fits in the rest of today?"), by text
or voice, that takes every number from the app instead of making one up. Step 1 connects a chat front end you
already use (for example Open WebUI, or a Hermes Agent profile with tools) to the app over MCP, with a personal
token. The plan, its rules and its parts are in
[`dev/plans/assistant-step1.md`](dev/plans/assistant-step1.md); the API contract is in `ARCHITECTURE.md`
("Assistant access tokens").

**Where this stands.** Part A, the access tokens below, is in place. Part B adds the MCP endpoint (`/mcp`) that a
token is for, and this page then explains how to connect Open WebUI and Hermes. Until part B ships, a token is
accepted by nothing.

## Contents

* [Access tokens](#access-tokens)
  * [For people using the app](#for-people-using-the-app)
  * [What ends a token](#what-ends-a-token)
  * [What the server keeps](#what-the-server-keeps)
  * [For the person running the server](#for-the-person-running-the-server)
  * [Security rules](#security-rules)

## Access tokens

A token is a long secret, `kha_` followed by 43 letters, digits, `-` and `_`, that you paste into the chat
assistant you connect. It gives that assistant **read-only** access to **your own** food log and targets: it cannot
change anything, and it never sees anyone else's data. Each token has the scope `assistant:read`; a later step may
add a separate scope for logging food, which you would have to tick when making the token.

### For people using the app

**Settings → Assistant access** (it shows once your admin has turned assistant access on):

1. Under **New token**, give the token a **name** (for example the app or device it is for, so you know which one
   to revoke later) and choose when it **expires**: after 30 days, 90 days (the default) or 1 year.
2. Select **Create token**. The app may ask for your password again first, as it does before saving a key.
3. The token appears once, with **Copy token**. Paste it into your assistant's settings now: **it is not shown
   again**. If it is lost, revoke it and make a new one.

The list shows each token's name, its first characters (`kha_AbCd1234…`), when it was made, when it was last used
(or "never used") and when it expires. **Revoke** asks once more and then ends the token at once; the assistant
using it gets "not allowed" from then on. You can have at most **5** active tokens. Revoked and expired tokens stay
in the list for 30 days, then disappear.

Your activity list (Settings → Account → Recent sign-in activity) shows when a token was made and when tokens were
revoked, and why.

### What ends a token

* You revoke it, or it expires.
* You change your password, or it is changed with a reset link (from an admin or the server's command line):
  every token of yours is revoked, because whoever knew the old password might have made one.
* An admin disables or deletes your account (enabling it again brings no token back).
* While an admin requires you to choose a new password, your tokens do not work; the change then revokes them.
* While the admin has assistant access **turned off**, no token works and no new one can be made. You can still
  see and revoke yours. When it is turned on again, tokens that have not expired or been revoked work again.

### What the server keeps

For each token: its name, its first 12 characters, the dates (made, last used, expires, revoked) and a one-way
**hash** of the whole token (SHA-256). The token itself is never stored, logged or sent again; a lost token cannot
be recovered, only replaced. Tokens are not in your data export (like your sign-in sessions, they are a way in, not
your data). Deleting your account deletes them.

### For the person running the server

* **Switch:** Server administration → Server settings → Optional AI → **Assistant access (personal tokens for a
  chat assistant)**, or `ASSISTANT_ENABLED=true` in the environment (which locks it). It is **off** by default.
  Turning it off is the quick way to stop every assistant at once; nothing is deleted.
* Members see the Settings card only while it is on (or while they still have active tokens, so they can revoke
  them); admins also see it while it is off, with a pointer to the switch.
* A token works for the account it was made by, under the server's current sign-in mode: a local account with
  `AUTH_MODE=local`, a proxy account with `AUTH_MODE=proxy`, user 1 with `AUTH_MODE=none`. Changing the mode
  stops tokens of accounts that cannot sign in under the new one.
* Use HTTPS beyond your own computer: the token travels in a request header, like a password.
* `python -m app.admin reset-password <name> --stdin` and `disable-user <name>` revoke the account's tokens too.

### Security rules

* A token counts only on the assistant surface (part B's `/mcp`). Every other `/api` route ignores the
  `Authorization` header and keeps using the sign-in cookie, so a token can never reach the admin pages or change
  anything.
* Every refusal is the same `401` answer with `WWW-Authenticate: Bearer`, whatever the reason (unknown, revoked,
  expired, account disabled, switch off), so an answer tells nothing about a guessed token.
* A refused token counts as a failed sign-in for the address it came from: after `LOGIN_IP_MAX_FAILURES` (20)
  failures in 10 minutes, sign-in and tokens from that address wait 10 minutes (`429`). Requests without a token,
  and requests while the switch is off, do not count.
* Making a token needs your password within the last 10 minutes and is limited to 20 an hour; the server writes
  "last used" at most once a minute; log lines hide anything that looks like a token.
