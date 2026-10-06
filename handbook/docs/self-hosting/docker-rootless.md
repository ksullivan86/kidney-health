---
title: Rootless Docker
description: "Run kidney-health on rootless Docker, and the limits that matter: client addresses, resource limits, ports and health checks."
slug: docker-rootless
audience: [self-hoster]
applies_to: [all]
status: draft
reviewed_by: ""
reviewed_on: null
last_checked: 2026-10-06
fact_checked: 2026-10-05
sources: [NOTE01, DEPLOY, SECDOC, DOCKER-ROOTLESS]
---

# Rootless Docker

Rootless Docker runs the Docker daemon as your user instead of root, so a container escape does not
land as root on the host. It works for kidney-health, but it hides your users' real addresses from
the app by default, which changes how you set up proxy trust ([design note 01][NOTE01]). If you are
choosing fresh, [rootless Podman](podman-rootless.md) is the better fit.

## Set up rootless Docker

1. Install `uidmap` and `docker-ce-rootless-extras`, then, as your user:
   `dockerd-rootless-setuptool.sh install`.
2. `systemctl --user enable --now docker` and `sudo loginctl enable-linger "$USER"`.
3. `docker context use rootless`.
4. Check: `docker info` lists `name=rootless` under Security Options, and shows cgroup v2 with systemd.

## Run kidney-health

Either:

- **compose**: `docker compose -f deploy/compose.yaml up -d`, with secrets in `deploy/secrets/` and
  settings in `deploy/.env` (see [Rootless Podman](podman-rootless.md#compose-instead-of-quadlet)); or
- **the run script**: `deploy/docker-rootless-run.sh`. It spells out every hardening flag
  (`--read-only`, `--tmpfs /tmp`, `--cap-drop ALL`, `--security-opt no-new-privileges:true`,
  `--pids-limit 128`, `--memory 512m`, publishing on `127.0.0.1`, secrets as read-only files), creates
  the `secret_key` file on first run, and **refuses a rootful daemon** ([deployment guide][DEPLOY]).

Set `PUBLIC_URL` (the script reads it from the environment), then read the setup code with
`docker logs kidney-health 2>&1 | grep 'FIRST-RUN SETUP'` ([Users and keys](users-and-keys.md)).

## The limits that matter

| Limit | What happens | What to do |
|---|---|---|
| **Client addresses are not passed through** | every client appears to come from the RootlessKit gateway ([Docker][DOCKER-ROOTLESS]) | publish on `127.0.0.1` only and leave `TRUSTED_PROXIES` at the loopback default. Trusting the gateway would mean trusting everyone |
| Resource limits need cgroup v2 | without it `--memory` and `--pids-limit` are **ignored silently** ([Docker][DOCKER-ROOTLESS]) | check `docker info` |
| Ports below 1024 | not allowed by default | put HTTPS on 8443, or set `net.ipv4.ip_unprivileged_port_start` |
| No AppArmor | one layer fewer | the user namespace, seccomp and dropped capabilities still apply |
| Health checks | Docker's `--health-cmd` runs through `/bin/sh`, which the image does not have | do not pass one; the image's own exec-form `HEALTHCHECK` applies |
| `--read-only` | Docker does not add a writable `/tmp` | always pair it with `--tmpfs /tmp` |

You can make client addresses visible with RootlessKit 3.0 or later and `"userland-proxy": false`, or
with `DOCKERD_ROOTLESS_ROOTLESSKIT_NET=pasta` and `..._PORT_DRIVER=implicit`. Only then is it safe to
trust a specific proxy address ([operator security guide][SECDOC]).

## Secret files

Under rootless Docker your UID is container root, so a `0600` file you own is unreadable for the app's
UID 10001. Use `0644` files inside a `0700` directory: other host users still cannot reach them
([deployment guide][DEPLOY]).

## Checklist

- [ ] `docker info` shows `name=rootless` and cgroup v2.
- [ ] Published on `127.0.0.1` only; `TRUSTED_PROXIES` at its default unless addresses are propagated.
- [ ] Secret files `0644` in a `0700` directory; `SECRET_KEY_FILE` set.
- [ ] `--read-only` with `--tmpfs /tmp`.
- [ ] No Docker socket mounted into any container ([Security](security.md)).

## If something goes wrong

- **Rate limits or sign-in blocks hit everyone at once**: all clients share one address. Keep the
  defaults above; the app detects a gateway address and skips per-address limits.
- **`permission denied` on `/run/secrets/...`**: fix the file mode as above.
- **The container restarts as unhealthy**: remove any `--health-cmd` you added.
- More: [Troubleshooting](troubleshooting.md).

## Related pages

- [Rootless Podman](podman-rootless.md) · [Security](security.md) · [HTTPS for phones](https.md) · [Configuration](configuration.md)

## Sources

- [Design note 01][NOTE01], sections 3.2 and 5.2.
- [Deployment guide][DEPLOY]; [operator security guide][SECDOC].
- [Docker: rootless mode limitations][DOCKER-ROOTLESS].
