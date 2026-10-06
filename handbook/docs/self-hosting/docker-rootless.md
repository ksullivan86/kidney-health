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

## Set up rootless Docker and run kidney-health

The commands are in the deployment guide's [rootless Docker section](https://github.com/ksullivan86/kidney-health/blob/main/docs/deployment.md#rootless-docker). In short:

1. Install Docker's rootless extras, run its setup tool as your user, start the user service and switch
   on linger so it runs at boot.
2. Switch to the rootless context and check that Docker reports `rootless` and cgroup v2.
3. Run the app either with **compose** (`deploy/compose.yaml`, the same files as on
   [Podman](podman-rootless.md#compose-instead-of-quadlet)) or with **the run script**
   `deploy/docker-rootless-run.sh`. The script spells out every hardening flag (read-only root, `/tmp` in
   memory, no capabilities, no new privileges, process and memory limits, publishing on `127.0.0.1`,
   secrets as read-only files), creates the secret key on first run, and **refuses a rootful daemon**.
4. Set `PUBLIC_URL`, then read the one-time setup code from the log ([Users and keys](users-and-keys.md)).

## The limits that matter

| Limit | What happens | What to do |
|---|---|---|
| **Client addresses are not passed through** | every client, an HTTPS proxy on the same host included, appears to come from the RootlessKit gateway, for example `172.17.0.1` ([Docker][DOCKER-ROOTLESS]) | publish on `127.0.0.1` only. Without a proxy, leave `TRUSTED_PROXIES` at the loopback default. With Caddy, nginx or `tailscale serve` on the same host, set `TRUSTED_PROXIES` to the gateway address the app logs: because the port is published on `127.0.0.1`, only local processes reach it. Without that, a second account cannot sign in (`https_required`) |
| Resource limits need cgroup v2 | without it `--memory` and `--pids-limit` are **ignored silently** ([Docker][DOCKER-ROOTLESS]) | check `docker info` |
| Ports below 1024 | not allowed by default | put HTTPS on 8443, or set `net.ipv4.ip_unprivileged_port_start` |
| No AppArmor | one layer fewer | the user namespace, seccomp and dropped capabilities still apply |
| Health checks | Docker's `--health-cmd` runs through `/bin/sh`, which the image does not have | do not pass one; the image's own exec-form `HEALTHCHECK` applies |
| `--read-only` | Docker does not add a writable `/tmp` | always pair it with `--tmpfs /tmp` |

Trusting the gateway would mean trusting everyone only if the port were published on a LAN address;
on `127.0.0.1` it means trusting the processes on this machine, which is what a same-host proxy needs.
In proxy sign-in mode also set `TRUSTED_PROXY_SECRET_FILE`. The Caddy compose overlay avoids the
question (container to container). How to pass the gateway address to the run script, and how running
it again replaces the container (the data stays on its volume), is in the
[deployment guide](https://github.com/ksullivan86/kidney-health/blob/main/docs/deployment.md#rootless-docker).

Client addresses can be made visible with newer RootlessKit network settings; the
[operator security guide](https://github.com/ksullivan86/kidney-health/blob/main/docs/security.md#4-proxy-trust-trusted_proxies-per-topology) lists them.

## Secret files

Under rootless Docker your UID is container root, so a `0600` file you own is unreadable for the app's
UID 10001. Use `0644` files inside a `0700` directory: other host users still cannot reach them
([deployment guide](https://github.com/ksullivan86/kidney-health/blob/main/docs/deployment.md#compose-podman-compose-or-docker-compose)).

## Checklist

- [ ] `docker info` shows `name=rootless` and cgroup v2.
- [ ] Published on `127.0.0.1` only; `TRUSTED_PROXIES` at its default without a proxy, or the logged
      gateway address when an HTTPS proxy on the same host connects to it.
- [ ] Secret files `0644` in a `0700` directory; `SECRET_KEY_FILE` set.
- [ ] `--read-only` with `--tmpfs /tmp`.
- [ ] No Docker socket mounted into any container ([Security](security.md)).

## If something goes wrong

- **Rate limits or sign-in blocks hit everyone at once**: all clients share one address. Keep the
  defaults above; the app detects a gateway address and skips per-address limits.
- **`permission denied` on `/run/secrets/...`**: fix the file mode as above.
- **The container restarts as unhealthy**: remove any `--health-cmd` you added.
- **`https_required` although the browser shows HTTPS**: the app does not trust your same-host proxy;
  put the gateway address from `docker logs kidney-health` in `TRUSTED_PROXIES`.
- More: [Troubleshooting](troubleshooting.md).

## Related pages

- [Rootless Podman](podman-rootless.md) · [Security](security.md) · [HTTPS for phones](https.md) · [Configuration](configuration.md)

## Sources

- [Design note 01][NOTE01], sections 3.2 and 5.2.
- [Deployment guide][DEPLOY]; [operator security guide][SECDOC].
- [Docker: rootless mode limitations][DOCKER-ROOTLESS].
