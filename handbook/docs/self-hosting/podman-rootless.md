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

The current commands are in the [deployment guide][DEPLOY]; this page explains the choices.

## Before you start

- [ ] **Subordinate IDs.** `grep "^$USER:" /etc/subuid /etc/subgid` shows a range of at least 65,536.
      Otherwise: `sudo usermod --add-subuids 100000-165535 --add-subgids 100000-165535 "$USER"` and
      `podman system migrate`. Install `newuidmap`/`newgidmap` (package `uidmap` or `shadow-utils`)
      ([Podman: rootless tutorial][PODMAN-ROOTLESS]).
- [ ] **Linger**, so it runs without a login and at boot: `sudo loginctl enable-linger "$USER"`.
- [ ] **cgroup v2**: `stat -fc %T /sys/fs/cgroup` prints `cgroup2fs`. The memory and pids limits work
      by default; CPU limits need the cpu controller delegated ([design note 01][NOTE01]).
- [ ] **Networking**: pasta (the rootless default since Podman 5.0). On Podman 4.9 (Ubuntu 24.04)
      install `passt`; the unit sets `Network=pasta`.
- [ ] Your final address and HTTPS plan ([HTTPS for phones](https.md)).

## Quadlet (recommended)

1. Copy `deploy/quadlet/kidney-health.container` and `kidney-health.volume` to
   `~/.config/containers/systemd/` ([Podman: Quadlet][PODMAN-QUADLET]).
2. Create the encryption key for stored API keys **in Podman's secret store**, not on the data volume:

    ```bash
    python3 -c "import secrets; print(secrets.token_urlsafe(32))" | podman secret create kidney-secret-key -
    ```

3. Edit the unit: set `PUBLIC_URL` and `TRUSTED_PROXIES` ([Configuration](configuration.md)).
4. Check the unit, then start it:

    ```bash
    /usr/libexec/podman/quadlet -user -dryrun >/dev/null && echo unit OK   # Debian/Ubuntu: /usr/lib/podman/quadlet
    systemctl --user daemon-reload
    systemctl --user start kidney-health
    systemctl --user enable --now podman-auto-update.timer               # daily pulls of the :0.3 tag
    ```

5. Read the setup code: `journalctl --user -u kidney-health | grep 'FIRST-RUN SETUP'`
   ([Users and keys](users-and-keys.md)).

A typo makes `daemon-reload` skip the unit **silently**; the `-dryrun` line catches it.

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
- Check: `podman top kidney-health user huser` shows `10001` and a subordinate UID, never your own.

## Volumes, `:U` and `:Z`

- The default **named volume** starts empty and is filled from the image with the right owner (10001,
  group 0, mode 0770). Nothing to do.
- A **bind mount** must be writable by UID 10001: add `:U` (Podman chowns it at each start) or run
  `podman unshare chown -R 10001:0 DIR`. On SELinux hosts add `:Z`. Example:
  `-v ~/kidney-data:/data:Z,U`.
- **Never** put `:U` or `:Z` on your home directory or a system directory, and never use
  `--security-opt label=disable` ([deployment guide][DEPLOY]).

## Compose instead of Quadlet

`deploy/compose.yaml` carries the same hardening for `podman-compose` (or Docker compose). It needs
**podman-compose 1.5.0 or later**: older versions (Ubuntu 24.04 packages 1.0.6) run the health check
through a shell the image does not have, so the container always shows `unhealthy`, and they skip the
SELinux relabelling of the secrets (`chcon -t container_file_t deploy/secrets/*` works around that).
`pipx install 'podman-compose>=1.5'` gets a current one; Quadlet has neither problem. Secrets are
files in `deploy/secrets/`, settings go in `deploy/.env`. Because compose mounts secret files as bind
mounts, they need mode `0644` inside a `0700` directory, or `podman unshare chown 10001:10001` on the
files. With `restart: always`, enable `podman-restart.service` so the container comes back after a
reboot ([deployment guide][DEPLOY]).

## A local Ollama or Hermes on the same host

pasta maps `host.containers.internal` to the host (Podman 5.3+), but a service listening only on
`127.0.0.1` stays unreachable, which is good. Do not "fix" that with `pasta:--map-gw`, which exposes every
loopback service to the container. Run Ollama as a container next to the app
(`deploy/compose.ai-ollama.yaml`), or bind Hermes to one LAN address and list it in `AI_PRIVATE_HOSTS`
([Network allowlist](network-allowlist.md)).

## Check the result

```bash
podman info --format '{{.Host.Security.Rootless}}'                       # true
podman top kidney-health user huser                                       # 10001  <subordinate UID>
podman inspect kidney-health --format '{{.HostConfig.ReadonlyRootfs}} {{.HostConfig.CapDrop}}'
podman healthcheck run kidney-health && echo healthy
```

Then tick the Podman checklist in the [operator security guide][SECDOC].

## If something goes wrong

- **`attempt to write a readonly database`**: the bind mount is not writable by 10001. Use `:U`, or the
  `podman unshare chown` line above; on SELinux add `:Z`.
- **The unit does not exist after `daemon-reload`**: run the `quadlet -dryrun` line to see the error.
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
