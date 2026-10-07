---
title: Self-hosting
description: "Choose how to run kidney-health at home or for a small group, what you need, and the order to set things up."
slug: self-hosting
audience: [self-hoster]
applies_to: [all]
status: draft
reviewed_by: ""
reviewed_on: null
last_checked: 2026-10-06
fact_checked: 2026-10-05
sources: [DEPLOY, NOTE01, NOTE02, NOTE07, SECDOC, HTTPSDOC]
---

# Self-hosting

kidney-health is one container image with one SQLite database. You run it on a computer you control (a
home server, a Raspberry Pi 4 or 5, a small cloud VM or a Kubernetes cluster), put HTTPS in front of
it, and invite the people who will use it ([deployment guide][DEPLOY]).

These pages are for the person who runs the server, called the **admin** in the "Using the app"
pages. Commands here are the stable outline; the exact, current commands live in the repository's
[deployment guide][DEPLOY], which is updated with every release.

## What you need

| Need | Minimum | Notes |
|---|---|---|
| CPU | 64-bit x86 (amd64) or ARM (arm64) | 32-bit ARM is not supported |
| Memory | about 60–100 MB for the app | the shipped limit is 512 MiB |
| Disk | room for the image and one SQLite file | the database grows slowly; keep space for backups |
| Container engine | rootless Podman 4.9+ (5.0+ recommended), rootless Docker, or Kubernetes | rootful engines work but are not recommended |
| Network | none at runtime, until you switch on a feature that needs it | [Network allowlist](network-allowlist.md) |
| A name and HTTPS | for phones to install the app and work offline | [HTTPS for phones](https.md) |

The image listens on port 8000 over plain HTTP, runs as UID 10001 with no shell, and writes only to
`/data` ([design note 01][NOTE01]).

## Choose a path

| You have | Use | Page |
|---|---|---|
| One Linux machine (recommended) | **rootless Podman with Quadlet**: a systemd user service with auto-update | [Rootless Podman](podman-rootless.md) |
| Docker already | **rootless Docker**, with compose or the run script | [Rootless Docker](docker-rootless.md) |
| A cluster (Talos or similar) | the **Kustomize** files in `deploy/k8s/` | [Kubernetes](kubernetes.md) |
| Just a look | the static preview or demo mode; nothing to install | the project README |

Exactly **one** container may use a database. Never run two copies on the same volume
([deployment guide][DEPLOY]).

## Setup order

1. **Pick the final address** people will type, for example `https://food.home.example.net`. Phones
   treat a different name, port or scheme as a different app with empty storage, so decide before
   anyone installs it ([design note 02][NOTE02]).
2. **Run the container** with your chosen path, with `SECRET_KEY_FILE` from your engine's secret store.
3. **Set `PUBLIC_URL`** (and `TRUSTED_PROXIES` for your proxy) ([Configuration](configuration.md)).
4. **Put HTTPS in front** ([HTTPS for phones](https.md)).
5. **Finish first-run setup** with the one-time setup code from the log ([Users and keys](users-and-keys.md)).
6. **Invite** the other people, and decide which shared keys (USDA, AI) to offer.
7. **Set up backups** and test a restore ([Backups](backups.md)).
8. **Choose an update policy**: track `:0.3` or pin a verified digest ([Upgrades](upgrades.md)).

Then work through the hardening checklist for your engine ([Security](security.md);
[operator security guide][SECDOC]).

## What the defaults already do

- No outbound requests until you enable USDA, Open Food Facts or AI.
- Local accounts with a one-time setup code: no "first visitor becomes admin" race
  ([design note 07][NOTE07]).
- Published on `127.0.0.1` only, so LAN devices cannot skip your HTTPS proxy.
- Read-only root filesystem, no capabilities, no new privileges, memory and process limits.
- Secrets as files, never environment variables.
- The patient handbook is built into the image and served at `/learn/`, with no internet needed.

## If something goes wrong

Start with [Troubleshooting](troubleshooting.md). The health check is `GET /healthz`
(`{"status":"ok","foods":395}`); inside the image, `python -m app.healthcheck`.

## Related pages

- [Configuration](configuration.md) · [Security](security.md) · [Network allowlist](network-allowlist.md)
- [Building the handbook](building-the-handbook.md) (contributors)
- For the people you invite: [Using the app](../app/index.md) · [Install the app](../app/install.md)

## Sources

- [Deployment guide][DEPLOY]; [operator security guide][SECDOC]; [HTTPS guide][HTTPSDOC].
- [Design note 01: rootless containers and security][NOTE01]; [design note 02][NOTE02]; [design note 07][NOTE07].
