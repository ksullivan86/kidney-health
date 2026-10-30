# 24 · Sign in with another account (OpenID Connect): Authentik, Google and others

| | |
|---|---|
| Status | Accepted, 2026-10-30. The owner asked: "can we add integration with oauth so we could setup google login like I did with netbird or use my authentik instance". The choices below are the defaults this note took; §12 lists the open questions so the owner can change any of them. The schema step is **26**. Built 2026-10-30, the server and the screens together, tested against a fake provider (`tests/oidc_support.py`) and in Chromium (`tools/e2e/oidc.py`); not yet tried against a real Authentik or Google. |
| Scope | One OpenID Connect provider per server, set by the admin in the environment. People sign in with it from the sign-in page; a person with a password links it in Settings → Account → Linked sign-in; an invite link can create an account with it; new accounts on first sign-in only when the admin allows it. Off by default. |
| Out of scope | More than one provider at once, hiding the password form (`OIDC_ONLY`), single sign-out at the provider, the userinfo endpoint, `form_post` responses, encrypted ID tokens, dynamic client registration. See §12 "Later". |
| Builds on | Note 07 (accounts, F6 proxy sign-in, F7 OIDC, §3.1, §6 "Later"), note 17 (two-step sign-in), note 18 (passkeys, the precedent of checking signatures with `cryptography` only), `app/egress.py` (the SSRF-checked transport). |
| Sources | OpenID Connect Core 1.0 (§3.1.2 authorization request, §3.1.3.7 ID token validation, §15.5.2 nonce); OpenID Connect Discovery 1.0 (§4 provider metadata, §4.3 issuer match); RFC 7636 (PKCE, S256); RFC 9700 (OAuth 2.0 Security Best Current Practice, 2025: PKCE for every client, exact redirect URIs, `iss` check); RFC 9207 (`iss` in the authorization response); RFC 7515/7517/7518 (JWS, JWK, algorithms); RFC 8037 (EdDSA in JOSE); Google Identity "OpenID Connect" guide (the `hd` and `email_verified` claims); authentik documentation "OAuth2 provider" (issuer per application, redirect URIs, `groups` in the profile scope). |

## 1. Why, and what the owner already has

The owner runs NetBird with Google sign-in and runs an Authentik server at home. Both speak OpenID Connect (OIDC). With this feature
the app becomes one more application in Authentik, or one more OAuth client in Google Cloud, and people sign in with that account. No
new password to remember, and the provider's own two-step sign-in, passkeys and account recovery apply.

The project's rule is that no third company is involved unless the admin chooses it. So OIDC is **off** until the admin sets it, and
Google is only one issuer the admin may pick. A home Authentik involves no company at all.

## 2. Two ways to use an identity provider, and when to pick which

| | `AUTH_MODE=proxy` (forward auth, works today) | `AUTH_MODE=local` with `OIDC_ENABLED=true` (this note) |
|---|---|---|
| Who checks the person | The reverse proxy (an Authentik proxy outpost, Authelia, `tailscale serve`) before any request reaches the app; it adds a user header | The app, through the OIDC code flow; then the app's own session cookie |
| What reaches the app without signing in | Nothing | The sign-in page and the public auth routes |
| Local passwords, passkeys, two-step codes | None (the proxy does it all) | Still there: people can use either way, or both |
| Setup | Proxy provider, outpost, a shared secret header, `TRUSTED_PROXIES` | An OAuth2/OpenID provider (Authentik) or an OAuth client (Google), the redirect URI, `PUBLIC_URL` |
| Danger when set up wrong | A takeover if the app port is reachable past the proxy | A wrong issuer or client ID only makes sign-in fail; the checks in §5 refuse forged tokens |
| Works with Google | No (Google is not a proxy) | Yes |
| Phone shortcuts, the iPhone app, an assistant | Need the proxy to let `/push/v1` and `/mcp` through with their own tokens | Unchanged: they use their own tokens |

Pick **proxy** when everything already sits behind Authentik forward auth and nobody should even see the app's sign-in page. Pick
**OIDC** for Google, for a family where some people use the provider and some keep a password, or when the app is reached directly
(a VPN such as NetBird, a LAN name) without a forward-auth proxy in front.

## 3. The flow (authorization code with PKCE)

1. **Discovery.** The server reads `OIDC_ISSUER` + `/.well-known/openid-configuration` (OIDC Discovery §4; one trailing `/` of the
   issuer is dropped first, so Authentik's `…/application/o/kidney-health/` works). The document's `issuer` must equal `OIDC_ISSUER`
   exactly (§4.3). It must name `authorization_endpoint`, `token_endpoint` and `jwks_uri`; each is `https://` (plain `http://` only
   for a loopback issuer, for tests). When it lists `code_challenge_methods_supported`, `S256` must be in it. Cached for an hour; a
   failure is retried at the next sign-in, never in a loop.
2. **Start** (`GET /api/auth/oidc/start`, public). The server makes `state` and `nonce` (32 random bytes each), a PKCE
   `code_verifier` (32 random bytes, base64url) and its S256 challenge, and keeps them in memory for 10 minutes under the state's
   hash, single use (like the passkey challenges). At most 10,000 wait in all and 10 per address (or per person, for linking and
   re-entry), and at most 300 starts a minute in all; beyond that a start is refused ("Too many sign-ins started. Try again soon.",
   result `full`) and nothing waiting is dropped. It sets a short cookie,
   `__Host-kh_oidc` (`kh_oidc` on plain HTTP; `HttpOnly`, `SameSite=Lax`, `Path=/`, 10 minutes), holding a random value whose hash is
   stored with the flow. Then it answers `303` to the provider's authorization endpoint with `response_type=code`, `client_id`,
   `redirect_uri`, `scope`, `state`, `nonce`, `code_challenge`, `code_challenge_method=S256`.
3. The person signs in **at the provider**. The provider sends the browser back to `GET /api/auth/oidc/callback?code&state` (a
   top-level navigation, so the `SameSite=Lax` cookies come along). The browser marks it `Sec-Fetch-Site: cross-site` (or
   `same-site` for a provider on a sibling host), which the app's cross-site read guard refuses for every other `/api` path; this
   one path is let through only as a top-level `GET` navigation (`security.PROVIDER_RETURN_PATHS`). The Chromium walk found this.
4. **Callback** (public). The flow is taken by `state` (once); the cookie must match the flow (this stops another browser from
   finishing someone else's flow, the classic login CSRF of OAuth). A state that is not waiting, or a cookie that does not match,
   changes nothing: the flow stays for its own browser, the browser's cookie stays, and it is not counted as a failed sign-in
   (any web page can send a browser here, so counting it would let a page lock a visitor's address out). `iss`, when the provider
   sends it (RFC 9207), must equal the issuer. An `error` from the provider is not shown as given: the person sees a fixed message.
5. **Token exchange.** `POST token_endpoint` with `grant_type=authorization_code`, `code`, `redirect_uri`, `code_verifier`, through
   the SSRF-checked transport, no redirects followed, 10-second timeout, at most 256 KiB read. The client authenticates with
   `client_secret_basic` (the OIDC default), or `client_secret_post` when the provider lists only that; a public client (no secret
   file) sends only `client_id` and relies on PKCE. Only the `id_token` of the answer is used; the access and refresh tokens are
   dropped at once and never stored or logged.
6. **ID token checks** (§5), then the account rules (§6), then a session (§7). The answer is a `303` to `/` (signed in), or to
   `/#/oidc/<result>` with one of a short list of result words that the page turns into a plain sentence. Nothing the provider sent is
   reflected into the page.

The redirect URI is always `<PUBLIC_URL>/api/auth/oidc/callback`, so **`PUBLIC_URL` is required** when OIDC is on (start-up refuses
otherwise). A request's own Host is never used for it: the provider needs one exact URI (RFC 9700 §2.1).

## 4. Settings

The connection is environment only, like `AUTH_MODE` and the AI provider's address: what the server connects to, and its secret, are
never changed at run time from the browser (the same rule as `AI_PRIVATE_HOSTS`). They are in `app/config.py` (`OidcEnv`) and
`deploy/.env.example`.

| Variable | Default | What it does |
|---|---|---|
| `OIDC_ENABLED` | `false` | Turns it on. Needs `AUTH_MODE=local`, `PUBLIC_URL`, `OIDC_ISSUER` and `OIDC_CLIENT_ID`. |
| `OIDC_ISSUER` | — | The issuer, exactly as the provider names it: `https://accounts.google.com`, or Authentik's `https://auth.example.org/application/o/kidney-health/`. |
| `OIDC_CLIENT_ID` | — | The client ID from the provider. |
| `OIDC_CLIENT_SECRET_FILE` | — | A file holding the client secret. **Only as a file**: `OIDC_CLIENT_SECRET` is refused at start-up, so the secret is never in `compose.yaml`, `ps` or the environment of the process. Leave it out for a public client. |
| `OIDC_SCOPES` | `openid email profile` | Space-separated; must include `openid`. Add `groups` only if your provider needs it for the groups claim. |
| `OIDC_ALLOW_PRIVATE_ISSUER` | `false` | Lets the server reach a provider on a private address (a home Authentik on the LAN or a VPN). Off, every address the provider's names resolve to must be public. Like `AI_PRIVATE_HOSTS` for a local AI, the admin allows it on purpose. |

The rules about **who** may sign in are settings in the registry (instance scope), so the admin can change them in Server
administration → Server settings, and each has a variable that locks it (they appear in `python -m app.admin env-template`):

| Setting (variable) | Default | What it does |
|---|---|---|
| `auth.oidc.button_label` (`OIDC_BUTTON_LABEL`) | `Sign in with single sign-on` | The button on the sign-in page, for example "Sign in with Authentik" or "Sign in with Google". |
| `auth.oidc.allow_signup` (`OIDC_ALLOW_SIGNUP`) | `false` | Create an account at the first sign-in of someone the server does not know. Off: only accounts that exist, are linked, or come from an invite link. |
| `auth.oidc.link_by_email` (`OIDC_LINK_BY_EMAIL`) | `false` | Give an unknown provider account with a verified email the account an admin made for that address in People, if nobody has used it yet (§6 step 3). Never an admin account or a self-registered one. |
| `auth.oidc.allowed_domains` (`OIDC_ALLOWED_DOMAINS`) | empty | Comma list of email domains. When set, every sign-in needs a verified email in one of them, and an `hd` claim, when sent, in them too. With Google as the issuer `hd` is required: a personal Google account can carry a work address as its email. Important with Google, where anyone in the world has an account. |
| `auth.oidc.admin_groups` (`OIDC_ADMIN_GROUPS`) | empty | Comma list of group names. When set and the ID token carries a `groups` claim, the role follows it at each sign-in: in a group → admin, else user (never the last admin; audited). No claim: the role is left alone. |

**`OIDC_ONLY` (hide the password form) is not in scope now.** Hiding the form while the server still takes passwords would only look
safer. Doing it properly means refusing passwords and passkeys too, and then an outage at the provider, or a lost Google account, locks
everyone out with the command line as the only way back. Revisit when someone asks for it (§12).

## 5. ID token checks (`app/auth/oidc.py`, on `cryptography` only)

OIDC Core §3.1.3.7, in order; any failure refuses the sign-in with one plain message and counts as a failed sign-in for the address.

* The token is three base64url parts. The header's `alg` is one of **RS256, RS384, RS512, PS256, ES256, ES384, EdDSA** (Ed25519).
  `none` and the HMAC algorithms (`HS256`, which would use the client secret as a key) are refused. A `crit` header is refused.
* The key is the JWK from the issuer's JWKS whose `kid` matches (or the only key of the right type when the token has no `kid`). Its
  `kty` (and `crv`) must fit the algorithm; a `use` other than `sig` and an `alg` other than the header's are refused.
  **JWKS cache:** kept for an hour. A `kid` that is not in the cache fetches the JWKS once more (a provider that rotated its keys),
  at most once a minute, so a stream of made-up `kid`s cannot make the server hammer the provider.
* The signature is checked with `cryptography` (PKCS#1 v1.5, PSS with the hash's length as salt, ECDSA with the JOSE `r||s` form
  turned into DER, Ed25519).
* `iss` equals `OIDC_ISSUER` exactly. `aud` is `OIDC_CLIENT_ID` or a list holding it; with more than one audience, `azp` must be
  the client ID, and `azp`, when present, must be the client ID.
* `exp` is in the future and `iat` not in the future, each with **60 seconds** of clock skew; `iat` no more than 10 minutes old.
  Both must be finite numbers: JSON parsers read `Infinity` and `NaN`, which would pass every comparison.
* `nonce` equals the flow's nonce (constant-time compare).
* `sub` is a string of 1 to 255 characters.
* For a re-entry (§8), `auth_time` must be present and not older than the flow's start (minus the skew): the server asked for
  `max_age=0` and `prompt=login`, and OIDC Core makes `auth_time` required then.

The claims used afterwards: `sub`; `email` and `email_verified` (only `true`, the boolean, counts as verified); `hd` (Google); `name`
and `preferred_username` (for a new account's names); `groups` (a list of strings). Only the ID token is read; the userinfo endpoint
is not called (with Authentik, keep "Include claims in id_token" on, which is its default).

**The dependency question.** The roadmap named Authlib 1.8 + itsdangerous against the project's own code. `cryptography` 50.0.2 is
already a runtime dependency (Argon2id, Fernet, passkeys) and does every signature check above. Authlib would add Authlib, joserfc
and, for its Starlette client, itsdangerous and Starlette's `SessionMiddleware` (a signed cookie session this app does not otherwise
need). The code here is about 500 lines: discovery, PKCE, the JWKS cache, the JWS checks and the claim checks, each tested against
a fake provider that signs with real keys. **Decision: no new dependency**, as for passkeys (note 18 §3). `requirements.in`,
`requirements.lock` and the contract's dependency list stay as they are, and the browser loads nothing new (the button is a plain
link; `app/static/vendor/` is unchanged).

## 6. Accounts and linking (schema step 26)

**Table `oidc_links`**: `id`, `user_id` (`REFERENCES users(id) ON DELETE CASCADE`), `issuer`, `subject`, `email` (as the provider
last sent it, for the Settings list; may be NULL), `created_at`, `last_used_at`. `UNIQUE (issuer, subject)`: one provider account
signs in to one app account. `UNIQUE (user_id, issuer)`: one link per person per provider. Accounts made by OIDC keep
`auth_source = 'local'`: they are ordinary accounts of this app (cookie sessions, passkeys, a password added later with a reset link),
just without a password at first. The `'oidc'` value that step 3 allowed stays unused; `external_subject` stays for proxy accounts.

**`sessions.signed_in_with`** (TEXT, NULL for every earlier row): `oidc` for a session started by the provider, NULL for a password
or passkey sign-in. Two-step rules read it (§9).

At the callback, after the checks, in this order:

1. **Allowed domains.** With `auth.oidc.allowed_domains` set, the email must be verified and its domain listed, and when the token
   has `hd` (Google Workspace) it must be listed too. Otherwise refused: "This server only lets in accounts from …".
2. **A known link** `(issuer, sub)`: that account signs in, if it is active ("This account is turned off. Ask your admin." otherwise).
3. **Link by email** (only with `auth.oidc.link_by_email` on and `email_verified` true). *Narrowed after the security review of
   2026-10-30*, which showed account pre-hijacking: an invited person could register the username `victim@example.org` with their
   own password and receive the real owner's provider sign-in (and, with admin groups, an admin role). Now the only account that
   can be linked this way is one **an admin made in People** that **nobody has used yet**: `pending_setup`, not an admin, no
   password, no passkey, no link. It is activated, its setup link voided, and linked (audit `oidc.linked`, `via: email`). The
   email, as the provider sent it, must be plain ASCII and equal the username in lower case: Unicode folding would merge
   different mailboxes (`straße` and `strasse`, the Kelvin sign, fullwidth letters). The plain-HTTP rule applies as for a new
   account. The admin groups are not applied on that sign-in; the next one follows them. Never by an unverified email.
4. **An invite** (§3 with an invite, below): a new account with the invite's role, linked.
5. **Sign-up** (only with `auth.oidc.allow_signup` on): a new account with role `user`, linked. The username is the verified email,
   else `preferred_username`, cut to the local rules; when taken, `-2` to `-9` is added; failing that, the sign-in is refused with a
   plain message. The display name is `name`. Open sign-up needs HTTPS, like open registration.
6. Otherwise: "There is no account here for that sign-in. Ask your admin for an invite link." Nothing is created.

**Invites.** The invite page offers "Create the account with <label>": `POST /api/auth/oidc/invite {token}` (public, like
`/register`; the invite must be valid) answers `{url}`, and the page goes there. The invite is used only when the account is made.

**Linking while signed in.** Settings → Account → Linked sign-in → **Link** asks for the password or a passkey again (re-auth), then
`POST /api/me/oidc/link` answers `{url}`. The flow remembers the person and this session; the callback links only if the same
session comes back, and only if that provider account is not linked to someone else ("That account is already linked to another
account here."). Audit `oidc.linked` (`via: settings`).

**Unlinking.** `DELETE /api/me/oidc/{id}` (re-auth). Refused with 409 when it is the person's last way in: no password, no passkey and
no other link. Audit `oidc.unlinked`. Another person's link id is 404, like everything else. An admin can remove all of an account's
links (`DELETE /api/admin/users/{id}/oidc`, for a lost provider account), and the people list shows how many each person has.

## 7. Sessions and throttles

The same session cookie, lifetime and idle limit as a password sign-in, a new session id each time, the remembered-device cookie, and
`last_login_at`. The per-address checks of the sign-in apply to both routes: blocked addresses wait; a failed callback of a flow this
browser started (token, claims, no account) counts as a failure for the address, while an unknown state or a missing cookie does
not (§3 step 4); `GET /start` counts toward the 30 sign-in attempts a minute.
There is no password, so the per-name delay and the hashing budget do not apply. The plain-HTTP rule is the same as for sign-in
(allowed on a LAN while the server has one account; HTTPS needed beyond it).

`GET /api/auth/status` adds `oidc: {enabled, label}` (no issuer, no client ID) so the sign-in page can show the button.

## 8. Re-entering for sensitive actions

People who signed up through the provider have no password. When an action asks for the password again, the re-auth sheet offers
**Confirm with <label>** to anyone with a link: `POST /api/auth/reauth/oidc` answers `{url}` for a flow with `prompt=login` and
`max_age=0`; the callback checks that the same session came back, that `(iss, sub)` is this person's link, and that `auth_time` is
fresh, and marks the session as re-entered. The page returns to Settings and says "Confirmed. Do it again now." (a full-page trip
loses the request that asked). `DELETE /api/me` takes a recent re-entry instead of the password for an account that has none.

## 9. Two-step sign-in

An OIDC sign-in counts as the provider's own sign-in, with whatever factors the provider asked for. **The app's two-step code is not
asked after it**, as with a passkey or a sign-in proxy. A password sign-in to the same account still asks for the code if it is on.

**"Admins must use two-step sign-in"** (`auth.require_two_step_admins`) applies to password sessions only. An admin's session that
came through the provider (`sessions.signed_in_with = 'oidc'`) is treated like a proxy sign-in: the provider is responsible. So an
admin who links a provider should make the provider ask for a second factor: in Authentik an authentication flow with an MFA stage;
with Google, 2-Step Verification on the account (enforced for a Workspace domain). The docs say this plainly. The switch is still
refused for an admin who has no app two-step code, as today.

## 10. Activity log, privacy and the API

Audit actions: `login.succeeded` with `via: oidc`; `login.failed` with `via: oidc` and a short `reason` word (no claim values) when an
account is known; `oidc.linked` (`via: settings | email | invite | signup`), `oidc.unlinked` (`via: self | admin`, `count`),
`user.registered` with `via: oidc_invite | oidc_signup`, `user.role_changed` with `via: oidc_groups`. The person's activity list shows
the link events. **Tokens, the nonce and the client secret are never logged or stored**; the one-time code and the state appear
in the callback's query string, so the log redaction (`app/security.py`) shows them as `code=[redacted]` and `state=[redacted]` in
uvicorn's access line; the issuer and the email
are stored for the person's own Settings list. The export (`export.json`) does not carry the links: a link means nothing on another
server, and the person links again there. Deleting an account deletes its links.

The client secret is write-only by construction: it exists only in the file and in memory, no route returns it, and `GET
/api/admin/about` shows `oidc: {enabled, issuer, client_id, secret: "set" | "not set", private_issuer_allowed, redirect_uri,
discovery: "ok" | the short reason it failed}`. The secret is added to the log redaction list.

Outbound requests: discovery, the JWKS and the token endpoint, nothing else, all through `app/egress.py`'s `CheckedTransport`. Every
address the names resolve to is checked at request time; a private one is refused unless `OIDC_ALLOW_PRIVATE_ISSUER=true`; metadata,
link-local and similar addresses are always refused. `docs/network-allowlist.md` lists the hosts. The browser makes no request of its
own: it follows two redirects. The CSP is unchanged (the `303` responses are navigations, which CSP does not limit).

## 11. Provider notes

**Authentik.** Applications → Create with provider → OAuth2/OpenID Provider. Client type Confidential; redirect URI (strict)
`https://kidney.example.org/api/auth/oidc/callback`; signing key: any certificate (RS256) or an EC key (ES256), not "no key" (HS256 is
refused); scopes `openid`, `email`, `profile` (Authentik's profile scope carries `groups`). The issuer is shown on the provider's page
as "OpenID Configuration Issuer", for example `https://auth.example.org/application/o/kidney-health/`. Put the client secret in a file
and point `OIDC_CLIENT_SECRET_FILE` at it. A home Authentik on a LAN or NetBird address needs `OIDC_ALLOW_PRIVATE_ISSUER=true`. Check what
your Authentik's email scope mapping sends as `email_verified`: linking by email happens only when it is `true`.

**Google.** Google Cloud console → APIs & Services → OAuth consent screen (External for personal accounts, Internal for a Workspace
domain; scopes `openid`, email, profile only, so no Google review is needed), then Credentials → Create OAuth client ID → Web
application, authorised redirect URI `https://kidney.example.org/api/auth/oidc/callback`. `OIDC_ISSUER=https://accounts.google.com`.
While the consent screen is in "Testing", only the test users listed there can sign in; "In production"
lets any Google account reach the app's own checks. **Any of the world's Google accounts can then reach those checks**,
so keep `auth.oidc.allow_signup` off or set `auth.oidc.allowed_domains`. Google sets `email_verified` and, for Workspace accounts,
`hd`. With allowed domains set and Google as the issuer, `hd` is required: a personal Google account can use a work address as its
email, and only `hd` shows the account belongs to the Workspace domain. Google needs a public `PUBLIC_URL` host name for the redirect URI (an IP address is refused by Google; `localhost` is allowed
for testing).

## 12. Risks and the owner's open questions

**Risks.**

* **The provider becomes a key to the app.** Whoever controls the provider account (or the provider) can sign in. With Google that
  is the person's Google security; at home it is the Authentik admin. Two-step at the provider matters most for admins (§9).
* **Signup with a public provider.** Google plus `allow_signup` and no allowed domains lets any Google account make an account. The
  docs and the setting's help say so; the default is off.
* **Email linking** is the riskiest rule, so it is off by default, needs `email_verified`, matches only plain ASCII usernames
  exactly, links only an admin-made account nobody has used, never an admin, and never promotes on that sign-in (§6 step 3).
* **Group mapping** makes the provider the source of truth for admin rights. A wrong group name can demote admins at their next sign-in
  (never the last one).
* **State in memory.** A restart during the minute someone is at the provider loses their flow; they press the button again. One
  process only, as the passkey challenges.
* **Clock drift** beyond 60 seconds makes every sign-in fail; the message says to check the server's clock.
* **Our own JOSE code** could have a bug that a library would not. The tests cover each refusal (wrong key, algorithm, kid, audience,
  issuer, time, nonce, `none`, HS256) with real signatures.

**Questions for the owner** (each has a default above):

1. Should OIDC admins be exempt from "Admins must use two-step sign-in" (the default, §9), or should an admin need the app's code even
   after the provider?
2. Is linking by email wanted at all, given the usernames in this app are rarely email addresses?
3. Should sign-up through the provider follow `registration.mode` (open / invite / closed) instead of its own switch?
4. One provider per server: enough, or do you want Google and Authentik side by side?
5. Do you want `OIDC_ONLY` later (§4), knowing it makes the provider a single point of failure?
6. Should signing out of the app also sign out at the provider (`end_session_endpoint`)? Today it signs out of the app only.

**Later.** Several providers; `OIDC_ONLY`; single sign-out; reading `amr`/`acr` to require a second factor at the provider; the
userinfo endpoint for providers that put nothing in the ID token; a CLI `remove-oidc USERNAME`.
