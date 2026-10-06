---
title: HTTPS for phones
description: "Why phones need trusted HTTPS, and four ways to get it for a home server: your own domain with Caddy, Tailscale, a private certificate authority, or cert-manager."
slug: https
audience: [self-hoster]
applies_to: [all]
status: draft
reviewed_by: ""
reviewed_on: null
last_checked: 2026-10-06
fact_checked: 2026-10-05
sources: [HTTPSDOC, NOTE02, MDN-SECURE, LE-LIFETIMES, TS-HTTPS, APPLE-TRUST, APPLE-TLS, RFC8375, SECDOC]
---

# HTTPS for phones

Phones treat kidney-health as a real app only over HTTPS they trust. Over plain
`http://192.168.x.y:8000` people get a bookmark with no offline mode, no live barcode camera, no secure
sign-in cookie, and passwords that anyone on the Wi-Fi can read ([design note 02][NOTE02]). Browsers allow
the offline service worker only in a "secure context": HTTPS, or the same computer
([MDN][MDN-SECURE]).

The full recipes, with every file, are in the repository's [HTTPS guide][HTTPSDOC].

## Two decisions first

1. **Pick the final address before anyone installs the app.** The browser treats scheme, host name and
   port together as the app's identity. Moving from `:8443` to `:443`, or from a Tailscale name to your
   own domain, makes a **new, empty app** on every phone, and entries still waiting to sync on the old
   one are lost.
2. **Pick a neutral host name.** Public certificates are listed in Certificate Transparency logs that
   anyone can search. `kidney.smith-family.net` publishes a medical condition. Use a wildcard
   certificate (`*.home.example.net`) or a name such as `food.`, `log.` or `homelab-1`
   ([Tailscale][TS-HTTPS]).

Certificates are getting shorter: Let's Encrypt's default moves from 90 to 64 days on 10 February 2027,
and to 45 days on 16 February 2028 ([Let's Encrypt][LE-LIFETIMES]). Every option below renews
**automatically**. Do not set up a certificate you renew by hand.

## The four options

| Option | You need | Phones need | Best when |
|---|---|---|---|
| **1. Your own domain + Caddy with DNS-01** (recommended) | a domain (about $10 a year) whose DNS has an API, such as Cloudflare | nothing | you want a normal address that works for everyone in the house |
| **2. Tailscale** (easiest) | a Tailscale account; HTTPS certificates switched on | the Tailscale app, connected | everyone who uses the app already runs Tailscale |
| **3. Your own certificate authority** | Caddy `tls internal` or step-ca | your root certificate installed **and** fully trusted | no domain, no outside services |
| **4. Kubernetes cert-manager** | an ACME issuer with DNS-01, or a CA issuer | as for 1 or 3 | you run the app on a cluster |

### 1. Your own domain and Caddy

Caddy gets a Let's Encrypt **wildcard** certificate through your DNS provider's API, so no port needs to
be open to the internet and the app's name never appears in the certificate logs. The repository ships a
Caddy image with the Cloudflare DNS module, an example Caddyfile and a compose overlay
(`deploy/compose.caddy.yaml`) that puts Caddy and the app on a private network ([HTTPS guide][HTTPSDOC]).

- Give the Cloudflare token only **Zone → DNS → Edit** for that one zone.
- In your home DNS (router, Pi-hole, AdGuard Home), point the name at this machine's LAN address.
- Rootless engines cannot publish port 443 by default, so the overlay uses **8443**
  (`https://food.home.example.net:8443`). Decide on 443 or 8443 before phones install the app.

### 2. Tailscale

`tailscale serve --bg localhost:8000` gives `https://<machine>.<tailnet>.ts.net` with a trusted
certificate. Rename the machine to something neutral first: machine names are published in the public
certificate ledger ([Tailscale][TS-HTTPS]). Do not use Tailscale **Funnel** (public internet) unless the
app's own sign-in is on.

### 3. Your own certificate authority

Use a name under `home.arpa`, the name space reserved for home networks ([RFC 8375][RFC8375]), for example
`food.home.arpa`. On iPhone and iPad, install the root certificate, then switch on **Settings → General →
About → Certificate Trust Settings → Enable full trust** for it ([Apple][APPLE-TRUST]). The certificates
must meet Apple's rules (name in the SAN, `serverAuth`, SHA-2, RSA 2048 or more, at most 825 days);
Caddy and step-ca do by default ([Apple][APPLE-TLS]). Your root can vouch for **any** website on those
phones, so keep its private key offline.

### 4. cert-manager

An ACME `ClusterIssuer` with DNS-01 (or a CA issuer from a private root), attached to your Gateway's
HTTPS listener. Set `PUBLIC_URL` to the same host name ([Kubernetes](kubernetes.md)).

## After any option: tell the app its address

| Setting | Example | Why |
|---|---|---|
| `PUBLIC_URL` | `https://food.home.example.net` (add `:8443` if used) | passes the Host check; the browser's `Origin` must match it; invite and reset links use it |
| `TRUSTED_PROXIES` | the address your proxy connects from | so the app believes `X-Forwarded-Proto: https` (secure cookies, HSTS) |
| `ALLOWED_HOSTS` | extra names only | |

The right `TRUSTED_PROXIES` value depends on your engine; read it from the app's log rather than
guessing ([Security](security.md); [operator security guide][SECDOC]).

## Check on a phone

- [ ] The padlock shows and there is no warning.
- [ ] In the app, the install panel says "Offline ready: the app opens without a connection."
- [ ] Install it to the Home Screen, switch on Airplane Mode, and confirm it still opens
      ([Install the app](../app/install.md)).

## Not supported

- A self-signed certificate that people "tap through": the warning returns on every visit, and browsers
  refuse the offline service worker on a page with a certificate error.
- A certificate you renew by hand.

## If something goes wrong

- **`400 Unknown host`**: set `PUBLIC_URL` to exactly the address in the browser bar.
- **`403` on every save**: the browser's origin (scheme, host, port) does not match `PUBLIC_URL`.
- **Sign-in refused over HTTP**: with two or more accounts the app refuses plain-HTTP sign-in from other
  machines. That is on purpose; finish HTTPS.
- More: [Troubleshooting](troubleshooting.md).

## Related pages

- [Configuration](configuration.md) · [Security](security.md) · [Install the app](../app/install.md)

## Sources

- [HTTPS guide][HTTPSDOC]; [design note 02][NOTE02], F9, F10 and R9; [operator security guide][SECDOC].
- [MDN: secure contexts][MDN-SECURE]; [Let's Encrypt: shorter lifetimes][LE-LIFETIMES]; [Tailscale: enabling HTTPS][TS-HTTPS].
- [Apple: trust a manually installed certificate][APPLE-TRUST]; [Apple: requirements for trusted certificates][APPLE-TLS]; [RFC 8375][RFC8375].
