---
title: Upgrades
description: "Which image tag to follow, tags versus pinned digests, automatic updates, database migrations, and moving from v0.2 to v0.3."
slug: upgrades
audience: [self-hoster]
applies_to: [all]
status: draft
reviewed_by: ""
reviewed_on: null
last_checked: 2026-10-06
fact_checked: 2026-10-05
sources: [DEPLOY, NOTE01, NOTE07, SECDOC, SECURITYMD, PODMAN-QUADLET, ARCH]
---

# Upgrades

Upgrading means running a newer image on the same data volume. The app upgrades its database by itself
at start-up, so the work is choosing **what to follow** and **keeping a backup** first
([deployment guide][DEPLOY]).

## Tags: which one to follow

| Tag | Moves when | Use it for |
|---|---|---|
| `0.3` | every 0.3.x patch release | **most homes**: security fixes, no breaking changes |
| `0.3.0` | never | a fixed release |
| `latest` | every release, including a new minor version | not on a machine you care about |
| `edge`, `sha-<short>` | every merge to `main` | testing only |

Tags move only after the image passed a vulnerability scan; pushes to `main` publish only `edge` and
`sha-<short>` ([architecture contract][ARCH], v0.3 item 7; [operator security guide][SECDOC]).

## Tag or digest?

- **Track `:0.3` with auto-update** (simplest). Quadlet's `AutoUpdate=registry` plus
  `podman-auto-update.timer` pulls new patch releases daily and restarts the service
  ([Podman: Quadlet][PODMAN-QUADLET]).
- **Pin a digest** (`…:0.3.0@sha256:…`) that you verified with `scripts/verify-image.sh`, and change it on
  purpose ([security policy][SECURITYMD]). This is the default on Kubernetes, with
  `imagePullPolicy: IfNotPresent`.

Auto-update trusts whoever controls the tag you follow. Signing and the `:0.3` advice reduce that risk
but do not remove it.

!!! warning "Never mount the container engine's socket into an updater"
    Watchtower-style updaters need `podman.sock` or `docker.sock`, which hands that container your whole
    account on the host (or root, with a rootful socket). Use Quadlet auto-update or pinned digests
    instead ([operator security guide][SECDOC]).

## Before a minor upgrade (0.3 to 0.4)

- [ ] Take a backup and check it ([Backups](backups.md)).
- [ ] Read the release notes for changed settings and removed features.
- [ ] Replace your deployment files if the notes say so.
- [ ] Change the tag (or digest), start, and watch the log.
- [ ] Open the app, check **Settings → Admin → About** for the version and schema.

## Database migrations

Schema changes are numbered, append-only steps that run in order at start-up and are recorded in the
database. Each step checks before it changes anything, so a restart in the middle is safe
([architecture contract][ARCH]). A backup restores into the same or a newer version, never an older one.

## From v0.2 to v0.3

1. **Back up first.** v0.2 has no `app.admin backup`; the guide's
   [v0.2 to v0.3 steps](https://github.com/ksullivan86/kidney-health/blob/main/docs/deployment.md#from-v02-to-v03) have a one-line SQLite copy for the old image, and what to
   do first on a host that auto-updates `:latest`.
2. **The upgrade makes its own backup** too, `/data/kidney.db.pre-v3.bak`, before the accounts migration.
   It is deleted automatically after 30 days ([design note 07][NOTE07]).
3. **Replace your deployment files** with the v0.3 ones. What changed:
   - the image has no shell; backups and health checks use `python -m app…`;
   - secrets are files: move `USDA_API_KEY` into a secret file, and add `SECRET_KEY_FILE`;
   - the port is published on `127.0.0.1`; reach the app through your HTTPS proxy;
   - set `PUBLIC_URL` (or `ALLOWED_HOSTS`) if people use a host name: unknown names now get
     `400 Unknown host`;
   - `--forwarded-allow-ips=*` is gone: list your proxy in `TRUSTED_PROXIES`;
   - `:latest` now means "newest release", not `main`; track `:0.3`;
   - `--userns=keep-id` is no longer recommended ([design note 01][NOTE01]).
4. **Accounts.** On first start the existing log becomes the admin's. A v0.2 `APP_PASSWORD` becomes the
   admin's password once (you are asked to change it if it is shorter than 15 characters); otherwise
   use the setup code from the log ([Users and keys](users-and-keys.md)).
5. **Rolling back:** stop v0.3, restore `kidney.db.pre-v3.bak` as `kidney.db`, and start the old image.
   **Do not roll back after a second person has signed up**: v0.2 has no accounts and would mix
   everyone's log together.

## If something goes wrong

- **`400 Unknown host` after the upgrade**: set `PUBLIC_URL`.
- **The health check fails**: an old string-form health command runs through `/bin/sh`, which the image
  no longer has. Use the exec form `["python", "-m", "app.healthcheck"]`.
- **Which version is running?** **Settings → Admin → About** shows the version and schema; the engine
  shows the image digest ([Troubleshooting](troubleshooting.md#which-version-is-running)).
- More: [Troubleshooting](troubleshooting.md).

## Related pages

- [Backups](backups.md) · [Security](security.md) (verifying images) · [Rootless Podman](podman-rootless.md) · [Kubernetes](kubernetes.md)

## Sources

- [Deployment guide: upgrades](https://github.com/ksullivan86/kidney-health/blob/main/docs/deployment.md#upgrades); [operator security guide][SECDOC], sections 7 and 9; [security policy][SECURITYMD].
- [Design note 01][NOTE01]; [design note 07][NOTE07] §4.15; [architecture contract][ARCH], v0.3 contract.
- [Podman: Quadlet units][PODMAN-QUADLET].
