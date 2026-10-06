---
title: Security
description: "What the defaults protect, how to set proxy trust, how to verify an image before running it, and how to serve the handbook from its own origin."
slug: security
audience: [self-hoster]
applies_to: [all]
status: draft
reviewed_by: ""
reviewed_on: null
last_checked: 2026-10-06
sources: [SECDOC, SECURITYMD, NOTE01, NOTE07, NOTE08, DEPLOY, SIGSTORE-VERIFY, K8S-NETPOL, GDPR]
---

# Security

kidney-health holds health data, and a tampered potassium target or food value could lead to an unsafe
meal, so integrity matters as much as privacy ([operator security guide][SECDOC]). The shipped defaults
do most of the work; this page lists what they cover and the few things only you can do.

## What the defaults do

| Default | What it stops |
|---|---|
| Rootless engine, default user namespace (never `keep-id`) | an escape lands as an unused subordinate UID, not root and not you |
| UID 10001, no shell, no package manager in the image | an attacker with code execution has no tools |
| Read-only root, writable `/data` and `/tmp` only, both `noexec` | a compromised process cannot rewrite the app |
| All capabilities dropped, `no-new-privileges`, seccomp | no kernel privileges to gain |
| Memory 512 MiB, 128 processes | a flood or bug cannot take the host down |
| Published on `127.0.0.1` only | LAN devices cannot skip your HTTPS proxy |
| Secrets as files (`*_FILE`) | environment variables leak through `inspect` and crash dumps |
| Host allowlist (`PUBLIC_URL`, `ALLOWED_HOSTS`) | DNS rebinding: unknown names get `400 Unknown host` |
| Strict CSP with Trusted Types, `frame-ancestors 'none'`, `no-referrer`, HSTS over HTTPS | script injection, clickjacking, referrer leaks |
| `X-Requested-With` plus `Origin`/`Sec-Fetch-Site` checks on every change | cross-site request forgery |
| Local accounts, 15-character passwords, Argon2id, throttling, a one-time setup code | password guessing and a "first visitor becomes admin" race |
| Every query scoped to the signed-in person; "not yours" is 404 | one household member reading another's log |
| No outbound requests until you switch a feature on | silent data leaving the house |

Sources: [design note 01][NOTE01], [design note 07][NOTE07], [operator security guide][SECDOC].

## What you must do

- [ ] Put **HTTPS** in front, and set `PUBLIC_URL` ([HTTPS for phones](https.md)).
- [ ] Set **`TRUSTED_PROXIES`** from the address the app actually sees (below).
- [ ] Mount **`SECRET_KEY_FILE`** from your engine's secret store, and keep a copy elsewhere.
- [ ] **Encrypt backups** and test a restore ([Backups](backups.md)).
- [ ] Track `:0.3` or a **verified digest**, never `:latest` or `:edge` ([Upgrades](upgrades.md)).
- [ ] **Never mount** `podman.sock` or `docker.sock` into any container.
- [ ] On Kubernetes, prove that NetworkPolicy is **enforced**; a policy without an enforcing plugin does
      nothing ([Kubernetes: Network Policies][K8S-NETPOL]; [Kubernetes](kubernetes.md)).
- [ ] Tick the checklist for your engine in the [operator security guide][SECDOC].

## Proxy trust: find the address, do not guess it

`TRUSTED_PROXIES` lists the addresses whose `X-Forwarded-For`/`-Proto` the app believes. Too wide lets
anyone fake their address (or, in proxy sign-in mode, their identity); too narrow is safe but makes
everyone look like the proxy.

1. Open the app once through your proxy.
2. Read the access log; each line starts with the peer, for example `10.88.0.5:51234 - "GET / HTTP/1.1" 200`.
3. Put that address in `TRUSTED_PROXIES` and restart. **Settings → Admin → About** then shows the trusted
   proxy and a count of identity headers ignored from untrusted peers.

| Setup | What the app sees |
|---|---|
| Rootless Podman (pasta), proxy on the same host | the container's **own** address, not `127.0.0.1`; every local process looks the same |
| Rootless Podman with slirp4netns | `10.0.2.100` for every client: switch to pasta |
| Rootless Docker (default) | the RootlessKit gateway for every client: keep the loopback default |
| Proxy in the same compose network | the proxy container's address (the Caddy overlay pins it) |
| Kubernetes | the Gateway pods' addresses: keep the range narrow |

([operator security guide][SECDOC], section 4)

## Verify an image before you run it

Release images are built from hash-locked dependencies on digest-pinned bases and scanned before any tag
moves. Once the repository is public, they are also signed keylessly with cosign and carry
GitHub-signed provenance and SBOM attestations ([security policy][SECURITYMD]).

```bash
scripts/verify-image.sh 0.3.0      # checks signature and attestations, prints the digest to pin
```

By hand, `cosign verify` checks that the signature came from this repository's release workflow, using
`--certificate-identity-regexp` and `--certificate-oidc-issuer` ([Sigstore][SIGSTORE-VERIFY]); the exact
lines are in the [security policy][SECURITYMD]. Podman cannot enforce these signatures at pull time, so
verify first and then deploy **by digest**.

## Serving `/learn` from its own origin (optional, coming in v0.3)

By default the app serves this handbook at `/learn/` on the same address as the app. The handbook's theme
needs a few inline scripts, so `/learn` gets a slightly looser policy than the app: those scripts are
allowed by exact hash, and Trusted Types are off there. No handbook page reads or sends data, and the
policy still blocks every other script ([design note 08][NOTE08]).

For stricter isolation, serve the handbook from **another host name**, so its policy never shares an
origin (cookies, storage, API) with the app:

1. Copy the built handbook out of the image:
   `podman create --name hb ghcr.io/ksullivan86/kidney-health:0.3 && podman cp hb:/app/learn ./site/learn && podman rm hb`.
2. Serve `./site` as static files on its own name, for example `https://learn.home.example.net/learn/`,
   from your reverse proxy. Keep the `/learn/` path: the build expects it.
3. On the app, point `HANDBOOK_DIR` at a path that does not exist, so `/learn` answers 404 there, and set
   `HANDBOOK_PUBLIC_URL=https://learn.home.example.net/learn/`, so the app's **Learn** link goes to the
   new address ([Configuration](configuration.md#the-handbook-at-learn-coming-in-v03)).

A public copy on GitHub Pages works the same way through `HANDBOOK_PUBLIC_URL`, but then readers load it
from the internet.

## Data at rest

The key that encrypts stored API keys lives with the app, so encryption protects a leaked database file
or `app.admin` backup, not someone who holds both the volume and the key. Passwords are hashed, not
encrypted. Health data is not encrypted in the database: protect the disk and the backups
([operator security guide][SECDOC], section 10). If you run the server for people outside your
household, their health data is a special category under EU law ([GDPR][GDPR], Article 9).

## Report a vulnerability

Use GitHub's private vulnerability reporting on the repository, not a public issue. Anything that makes
the app give a dose or warn against treating a low counts as a security issue ([security policy][SECURITYMD]).

## Related pages

- [Configuration](configuration.md) · [Network allowlist](network-allowlist.md) · [Backups](backups.md) · [Upgrades](upgrades.md)
- For your users: [Privacy and your data](../app/privacy.md)

## Sources

- [Operator security guide][SECDOC]; [security policy and image verification][SECURITYMD]; [deployment guide][DEPLOY].
- [Design note 01][NOTE01] (including its security review); [design note 07][NOTE07]; [design note 08][NOTE08] §4.6.
- [Sigstore: verifying signatures][SIGSTORE-VERIFY]; [Kubernetes: Network Policies][K8S-NETPOL]; [GDPR][GDPR].
