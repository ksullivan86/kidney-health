---
title: Troubleshooting
description: "Common errors when running kidney-health, what they mean, and how to fix them."
slug: troubleshooting
audience: [self-hoster]
applies_to: [all]
status: draft
reviewed_by: ""
reviewed_on: null
last_checked: 2026-10-30
fact_checked: 2026-10-30
sources: [DEPLOY, SECDOC, HTTPSDOC, NOTE01, NOTE02, NOTE07, DOCKER-ROOTLESS, K8S-NETPOL, NETBIRD-CLI, NETBIRD-ROUTES]
---

# Troubleshooting

Find the message you see, then follow the fix. Most problems are an address the app does not know, a
volume it cannot write, or a proxy it does not trust ([deployment guide][DEPLOY]).

## First checks

1. **The log**: the last 50 lines usually name the problem (secrets are redacted from logs).
2. **`python -m app.admin check`** inside the container: configuration, database integrity, schema
   version and the secret key in one report.
3. **The health check**, run by hand.

The commands for each engine, and the fixes below in more detail, are in the deployment guide's
[troubleshooting section](https://github.com/ksullivan86/kidney-health/blob/main/docs/deployment.md#troubleshooting).

## Messages and fixes

| You see | Why | Fix |
|---|---|---|
| `400 Unknown host` | the browser used a host name the app does not know (DNS-rebinding defense) | set `PUBLIC_URL`, or add the name to `ALLOWED_HOSTS`; the log names the refused host. IP addresses and `localhost` always work |
| `403` on every save | the browser's origin does not match | set `PUBLIC_URL` to exactly the address bar's scheme, host and port, especially if your proxy rewrites `Host` |
| `503 Setup required` | first-run setup is not done | use the setup code from the log ([Users and keys](users-and-keys.md)) |
| Sign-in refused over HTTP | two or more accounts exist, so plain-HTTP sign-in from other machines is refused | set up HTTPS ([HTTPS for phones](https.md)) |
| `unable to open database file`, `attempt to write a readonly database` | `/data` is not writable by UID 10001 | named volumes need nothing; a bind mount needs its owner fixed and, on SELinux, a label ([volumes](https://github.com/ksullivan86/kidney-health/blob/main/docs/deployment.md#volumes-u-and-z)). Kubernetes: `fsGroup: 10001` |
| `SECRET_KEY_FILE points to ..., which does not exist`, or `permission denied` | the secret is missing or unreadable for UID 10001 | create the Podman secret or Kubernetes Secret; compose files need `0644` in a `0700` directory. Setting both `X` and `X_FILE` is also refused |
| The app exits naming `ALLOW_PRIVATE_AI_HOSTS` | that old name is not accepted | use `AI_PRIVATE_HOSTS` with explicit `host:port` entries ([Configuration](configuration.md)) |
| Health check failing | a string-form health command runs through `/bin/sh`, which the image does not have | use `["python", "-m", "app.healthcheck"]`; on Docker do not pass `--health-cmd`. On slow storage raise the start period |
| Every request from one address; rate limits hit everyone | the engine hides client addresses, or `TRUSTED_PROXIES` does not match the proxy | read the peer address from the log and set `TRUSTED_PROXIES` ([Security](security.md)) |
| `database is locked` | two processes share one database | run exactly one container (one pod) per volume |
| Memory or process limit ignored | rootless engines need cgroup v2 with systemd ([Docker][DOCKER-ROOTLESS]) | check the cgroup version the engine reports |
| `USDA request failed` / `USDA API key was rejected` | no route to `api.nal.usda.gov:443` / a wrong key | check egress rules ([Network allowlist](network-allowlist.md)) / the key |
| Kubernetes pod `Pending` | the volume claim cannot bind | describe the claim `kidney-health-data`: storage class name, default class, node selector |
| Pod rejected by Pod Security | an added container misses a restricted setting | non-root, `allowPrivilegeEscalation: false`, drop `ALL`, seccomp `RuntimeDefault` |
| NetworkPolicy test pod gets `{"status":"ok"}` | policies are not enforced ([Kubernetes][K8S-NETPOL]) | enable enforcement in your network plugin (Talos Flannel: `kubeNetworkPoliciesEnabled`) |

## Phones and the installed app

| People report | Fix |
|---|---|
| "My data is gone" | they opened a different address (name, port or scheme). The same app at another address starts empty; the data is still on the server ([design note 02][NOTE02]) |
| The app does not open offline | offline needs trusted HTTPS; check the padlock and **Settings → This device** says "Offline ready" |
| "Update ready" never appears | close the app fully and reopen; if you set `PWA_ENABLED=false`, opening it once removes the old version |
| The camera shows black | use the photo or type-in options for barcodes |
| Asked to sign in again | an installed app keeps its own sign-in, separate from the browser's |

## Only the header shows over a VPN

The app opens on the home Wi-Fi. Over a VPN such as NetBird, Tailscale or WireGuard, only the header shows, and after
about 8 seconds the page says "The app did not start". The page arrived, but the app's script files did not.

This is fixed in your network, not in the app. The app answers whatever reaches it. It cannot change how the VPN
carries packets. Whoever runs the VPN, or the machine that routes it to the server, makes the change below.

**The likely cause** is packets that are too big for the tunnel. A VPN wraps each packet in another one, so packets
inside it must be smaller. Small answers get through, but large files stall when the big packets are dropped and the
"too big" messages never come back. This is called a path MTU black hole. It is likely when the server sits behind a
NetBird routing peer, which passes traffic between the tunnel and your home network
([NetBird: routing peers][NETBIRD-ROUTES]), instead of running NetBird itself.

**To check**, download the largest script file once over the VPN and once on the home Wi-Fi. On Wi-Fi it arrives at
once. Over a black hole it stops after a few kilobytes, while a small address such as `/healthz` still answers.

**To fix it**, do one of these, then check again:

- clamp the TCP segment size (MSS clamping) on the NetBird routing peer, so connections through it use packets that fit;
- lower the MTU of the NetBird interface on both ends. NetBird's default is 1280 ([NetBird: command line][NETBIRD-CLI]);
- run NetBird on the server itself, so it is a peer and no route is involved.

**Also rule out:**

- `400 Unknown host` in the browser or the log: add the NetBird name you use (for example one ending in
  `.netbird.cloud`) to `ALLOWED_HOSTS`, or set `PUBLIC_URL` to it ([Configuration](configuration.md));
- an old copy of the app on the device: where the app works, use **Settings → This device → Clear offline data on this
  device**, after waiting entries have synced, or clear the site's data in the browser;
- a content blocker, or a filtering proxy or DNS on the VPN, that blocks script files.

The commands for each step are in the deployment guide's section
[Only the header shows over a VPN](https://github.com/ksullivan86/kidney-health/blob/main/docs/deployment.md#only-the-header-shows-over-a-vpn).

## Accounts

| Problem | Fix |
|---|---|
| Lost the setup code | restart the app, or `python -m app.admin setup-code` |
| The only admin is locked out | `python -m app.admin reset-password USERNAME --stdin` ([design note 07][NOTE07]) |
| A lost phone is still signed in | `python -m app.admin revoke-sessions USERNAME`, or **Signed-in devices** in the person's settings |
| Two-step sign-in: the phone and the recovery codes are both lost | `python -m app.admin remove-two-step USERNAME` |
| Settings says passkeys need a name for the server | open the app by its name, not an IP address, and set `PUBLIC_URL` to that address |
| A device with a passkey is lost or stolen | **Server administration → People → Remove passkeys**, or `python -m app.admin remove-passkeys USERNAME` |
| Proxy mode: "Your account is not enabled here" | create the account, or set `PROXY_AUTO_CREATE_USERS=true` |
| Proxy mode will not start | `TRUSTED_PROXY_SECRET_FILE` is missing, or `TRUSTED_PROXIES` contains `0.0.0.0/0` |

## Which version is running?

**Server administration → About this server** shows the version and schema. The engine shows the image digest; the
commands are at the end of the guide's [troubleshooting section](https://github.com/ksullivan86/kidney-health/blob/main/docs/deployment.md#troubleshooting).

## Debugging without a shell

The image has no shell on purpose. Most tasks have a `python -m app.admin` command. Otherwise use a
debug container that shares the app's volumes, as described in the [deployment guide][DEPLOY].

## Still stuck?

Collect the log lines around the problem (secrets are redacted from logs), the output of
`python -m app.admin check`, your engine and version, and open an issue on the repository. Report security
problems privately ([Security](security.md)).

## Sources

- [Deployment guide: troubleshooting](https://github.com/ksullivan86/kidney-health/blob/main/docs/deployment.md#troubleshooting); [operator security guide][SECDOC]; [HTTPS guide][HTTPSDOC].
- [Design note 01][NOTE01]; [design note 02][NOTE02]; [design note 07][NOTE07].
- [Docker: rootless mode limitations][DOCKER-ROOTLESS]; [Kubernetes: Network Policies][K8S-NETPOL].
- [NetBird: command line][NETBIRD-CLI]; [NetBird: routing peers][NETBIRD-ROUTES].
