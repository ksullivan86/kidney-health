---
title: Rootless Podman
description: "Run kidney-health with rootless Podman: prerequisites, Quadlet (recommended), compose, user namespaces and volumes."
slug: podman-rootless
audience: [self-hoster]
applies_to: [all]
status: draft
reviewed_by: ""
reviewed_on: null
last_checked: 2026-10-06
fact_checked: 2026-10-05
sources: [NOTE01, DEPLOY, SECDOC, PODMAN-QUADLET, PODMAN-ROOTLESS]
---

# Rootless Podman

Rootless Podman runs the container as your ordinary user, and the app inside runs as UID 10001, which
maps to an unused **subordinate** UID on the host: not root and not you. Quadlet turns the shipped
unit file into a systemd user service that starts at boot, restarts when unhealthy, and can update
itself ([design note 01][NOTE01]; [Podman: Quadlet][PODMAN-QUADLET]).

This page explains the choices. The commands live in one place, the repository's
[deployment guide][DEPLOY], and each step below links to its section there, so they cannot drift apart.

## Before you start

The [rootless prerequisites](https://github.com/ksullivan86/kidney-health/blob/main/docs/deployment.md#rootless-prerequisites-podman-or-docker) in the deployment guide
check each of these with one command:

- [ ] **Subordinate IDs**: a range of at least 65,536 for your user, and `newuidmap`/`newgidmap`
      installed ([Podman: rootless tutorial][PODMAN-ROOTLESS]).
- [ ] **Linger**, so the service runs without a login and starts at boot.
- [ ] **cgroup v2**. The memory and pids limits work by default; CPU limits need the cpu controller
      delegated ([design note 01][NOTE01]).
- [ ] **Networking**: pasta, the rootless default since Podman 5.0. On Podman 4.9 (Ubuntu 24.04) install
      `passt`; the unit sets `Network=pasta`.
- [ ] Your final address and HTTPS plan ([HTTPS for phones](https.md)).

## Quadlet (recommended)

The steps, with the exact commands in the deployment guide's
[Quadlet section](https://github.com/ksullivan86/kidney-health/blob/main/docs/deployment.md#rootless-podman-with-quadlet-recommended):

1. Copy the shipped unit and volume files (`deploy/quadlet/`) into your user's Quadlet folder
   ([Podman: Quadlet][PODMAN-QUADLET]).
2. Create the encryption key for stored API keys **in Podman's secret store**, not on the data volume.
3. Set `PUBLIC_URL` and `TRUSTED_PROXIES` in the unit ([Configuration](configuration.md)).
4. Check the unit with Quadlet's dry run, then start it and switch on the daily auto-update timer.
5. Read the one-time setup code from the log ([Users and keys](users-and-keys.md)).

A typo makes systemd skip the unit **silently**; the dry run in step 4 is what catches it.

### What the unit sets, and why

| Setting | Why |
|---|---|
| `PublishPort=127.0.0.1:8000:8000` | only your HTTPS proxy on this host can reach the app |
| `ReadOnly=true`, `Tmpfs=/tmp:…noexec` | a compromised process cannot rewrite the app |
| `DropCapability=all`, `NoNewPrivileges=true` | no kernel privileges, and no way to gain them |
| `PidsLimit=128`, `--memory=512m` | a bug or flood cannot take the host down |
| `Volume=…:/data:noexec,nosuid,nodev` | the only writable place holds data, never programs |
| `Secret=kidney-secret-key,…,mode=0400` | the key is a file owned by UID 10001, outside `/data` |
| `HealthCmd=["python", "-m", "app.healthcheck"]` | exec form: the image has no shell |
| `AutoUpdate=registry` | `podman-auto-update` pulls new `:0.3` patch releases |

## User namespaces: keep the default

- **Do not use `UserNS=keep-id`** outside development. It maps your own UID to the app's UID, so an
  escaped process could read your `~/.ssh` and other containers ([design note 01][NOTE01]).
- `UserNS=auto` gives the container its own slice of IDs, isolating it from your other containers. It is
  an advanced option: use a named volume, or `:U` on a bind mount.
- The container's user must show as `10001` mapped to a subordinate UID, never your own; the guide's
  [check after starting](https://github.com/ksullivan86/kidney-health/blob/main/docs/deployment.md#rootless-podman-with-quadlet-recommended) shows it.

## Volumes, `:U` and `:Z`

- The default **named volume** starts empty and is filled from the image with the right owner (10001,
  group 0, mode 0770). Nothing to do.
- A **bind mount** must be writable by UID 10001: the `:U` option (Podman fixes the owner at each start)
  or a one-time owner change, plus `:Z` on SELinux hosts. The guide's
  [volumes section](https://github.com/ksullivan86/kidney-health/blob/main/docs/deployment.md#volumes-u-and-z) has both commands.
- **Never** put `:U` or `:Z` on your home directory or a system directory, and never switch SELinux
  labelling off for the container ([deployment guide][DEPLOY]).

## Compose instead of Quadlet

`deploy/compose.yaml` carries the same hardening for `podman-compose` (or Docker compose). Use a
**current podman-compose (1.5.0 or later)**: older ones, such as Ubuntu 24.04's, run the health check
through a shell the image does not have, so the container always shows `unhealthy`, and they skip the
SELinux relabelling of the secrets. Quadlet has neither problem. Secrets are files in `deploy/secrets/`
(compose mounts them as bind mounts, so their mode matters), settings go in `deploy/.env`, and a
container with `restart: always` needs Podman's restart service to come back after a reboot. All of it,
with the commands and the workaround for older versions, is in the guide's
[compose section](https://github.com/ksullivan86/kidney-health/blob/main/docs/deployment.md#compose-podman-compose-or-docker-compose).

## A local Ollama or Hermes on the same host

pasta maps `host.containers.internal` to the host (Podman 5.3+), but a service listening only on
`127.0.0.1` stays unreachable, which is good. Do not "fix" that with `pasta:--map-gw`, which exposes every
loopback service to the container. Run Ollama as a container next to the app
(`deploy/compose.ai-ollama.yaml`), or bind Hermes to one LAN address and list it in `AI_PRIVATE_HOSTS`
([Network allowlist](network-allowlist.md)).

## Check the result

Four checks prove the hardening took effect: Podman runs rootless, the app's UID maps to a subordinate
UID, the root filesystem is read-only with every capability dropped, and the health check passes. The
commands are at the end of the guide's [Quadlet section](https://github.com/ksullivan86/kidney-health/blob/main/docs/deployment.md#rootless-podman-with-quadlet-recommended).
Then tick the Podman checklist in the [operator security guide](https://github.com/ksullivan86/kidney-health/blob/main/docs/security.md#rootless-podman-quadlet-recommended-for-one-host).

## If something goes wrong

- **`attempt to write a readonly database`**: the bind mount is not writable by 10001 (see
  [volumes](https://github.com/ksullivan86/kidney-health/blob/main/docs/deployment.md#volumes-u-and-z)).
- **The unit does not exist after `daemon-reload`**: run Quadlet's dry run to see the error.
- **Every request comes from one address, or the proxy is not trusted**: with pasta, a proxy on the same
  host appears as the container's **own** address, not `127.0.0.1`. Read the address from the log and put
  it in `TRUSTED_PROXIES` ([Security](security.md)).
- More: [Troubleshooting](troubleshooting.md).

## Related pages

- [Configuration](configuration.md) · [HTTPS for phones](https.md) · [Backups](backups.md) · [Upgrades](upgrades.md)
- Using Docker instead: [Docker (rootless)](docker-rootless.md) · on a cluster: [Kubernetes](kubernetes.md)

## Sources

- [Deployment guide][DEPLOY]; [operator security guide][SECDOC].
- [Design note 01][NOTE01], sections 3.1 and 5.2.
- [Podman: Quadlet units][PODMAN-QUADLET]; [Podman: rootless tutorial][PODMAN-ROOTLESS].
