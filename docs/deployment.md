# Deployment guide (v0.3)

How to run the Kidney Health food log on **rootless** Podman, rootless Docker or Kubernetes
(Talos), set it up on first start, keep its database safe, and upgrade it. Everything the app needs
is in one container image; all state is one SQLite database.

Read with it: [`security.md`](security.md) (what the defaults protect, per-runtime checklists, the
`TRUSTED_PROXIES` table), [`https.md`](https.md) (HTTPS so phones can install the app) and
[`network-allowlist.md`](network-allowlist.md) (outbound hosts). The design behind this page is
[`docs/dev/research/01-rootless-and-security.md`](dev/research/01-rootless-and-security.md).

Contents:
[What you are deploying](#what-you-are-deploying) ·
[Before you start](#before-you-start) ·
[Configuration](#configuration) ·
[First run](#first-run) ·
[Rootless Podman with Quadlet](#rootless-podman-with-quadlet-recommended) ·
[Compose](#compose-podman-compose-or-docker-compose) ·
[Rootless Docker](#rootless-docker) ·
[Kubernetes (Talos)](#kubernetes-talos) ·
[Sign-in modes](#sign-in-modes) ·
[Backups and restore](#backups-and-restore) ·
[Upgrades](#upgrades) ·
[Building the image yourself](#building-the-image-yourself) ·
[Local development run](#local-development-run) ·
[Troubleshooting](#troubleshooting)

## What you are deploying

| Fact | Value |
|---|---|
| Image | `ghcr.io/ksullivan86/kidney-health` (linux/amd64 + linux/arm64), based on Chainguard Python (no shell, no pip, no package manager) |
| Tags | `0.3` = the current 0.3.x release (**track this**); `0.3.0` = one release; `latest` = the newest release; `edge` and `sha-<short>` = every push to `main` (testing only) |
| Verify | `scripts/verify-image.sh 0.3.0` checks the signature and attestations and prints the digest to pin ([`SECURITY.md`](../SECURITY.md)) |
| Listens on | TCP **8000**, plain HTTP: put HTTPS on a reverse proxy ([`https.md`](https.md)) |
| Runs as | UID **10001**, GID 10001 (works with any UID whose GID is 0, too); no capabilities |
| Writes | only `/data` (`kidney.db`, its `-wal`/`-shm` files) and `/tmp`; the root filesystem can be read-only |
| Secrets | files: `SECRET_KEY_FILE`, `USDA_API_KEY_FILE`, ... (never environment variables) |
| Health | `GET /healthz` → `{"status":"ok","foods":395}`; in the image: `python -m app.healthcheck` |
| Admin CLI | `python -m app.admin backup|check|restore-check|rotate-secret-key|reencrypt|settings|create-admin|reset-password` (no shell needed) |
| Patient handbook | built into the image and served at **`/learn/`** (no sign-in, no internet needed); the app's **Learn** entry opens it |
| Outbound network | none until you turn a feature on ([`network-allowlist.md`](network-allowlist.md)) |
| Footprint | about 60–100 MB RAM; the shipped limits are 512 MiB and 128 PIDs |
| Licence | PolyForm Noncommercial 1.0.0 (personal and noncommercial use) |

**Rules that follow from SQLite:** exactly one container per database (never two containers or
two pods on the same volume), a `ReadWriteOnce` volume, and a `Recreate` rollout on Kubernetes. The
shipped files already do this.

## Before you start

### Rootless prerequisites (Podman or Docker)

1. **Subordinate IDs.** `grep "^$USER:" /etc/subuid /etc/subgid` must show a range of at least
   65 536 IDs. Otherwise:
   `sudo usermod --add-subuids 100000-165535 --add-subgids 100000-165535 "$USER"`, then
   `podman system migrate`. Also install `newuidmap`/`newgidmap` (package `uidmap` or `shadow-utils`).
2. **Linger**, so the container runs without an open login and starts at boot:
   `sudo loginctl enable-linger "$USER"`.
3. **cgroup v2** (`stat -fc %T /sys/fs/cgroup` prints `cgroup2fs`). systemd delegates the **memory**
   and **pids** controllers to users by default, which is what the shipped limits use. CPU limits
   (`--cpus`) need the cpu controller delegated too:

   ```ini
   # /etc/systemd/system/user@.service.d/delegate.conf, then: sudo systemctl daemon-reload
   [Service]
   Delegate=cpu cpuset io memory pids
   ```
4. **Networking (Podman).** pasta is the rootless default since Podman 5.0 (Podman 6 removed
   slirp4netns). On Podman 4.9 (Ubuntu 24.04) install the `passt` package; the Quadlet unit sets
   `Network=pasta` because slirp4netns would show every client as `10.0.2.100`.

### User namespaces: keep the default

Under rootless Podman your UID is container root and container UID *n* maps to a subordinate UID.
The app's UID 10001 is therefore an unused subordinate UID on the host: **not root and not you**.

* **Do not use `--userns=keep-id`** (or `UserNS=keep-id`) for this app outside development: it maps
  *your own* UID to 10001, so an escaped process could read `~/.ssh`, your other containers and any
  agent keys. Older versions of this guide recommended it; that advice is withdrawn.
* `--userns=auto` (Quadlet `UserNS=auto`) gives the container its own slice of your subordinate
  range, which also isolates it from your other containers. Use it with a named volume, or with
  `:U` on a bind mount. It is an advanced option because the `podman unshare chown` recipes below
  no longer apply.

### Volumes, `:U` and `:Z`

* A **named volume** that starts empty is populated from the image's `/data` (owner 10001, group 0,
  mode 0770): nothing to chown. This is the default everywhere.
* A **bind mount** must be writable by 10001: either `podman unshare chown -R 10001:0 DIR`, or the
  `:U` volume option (chowns it to the container user on every start; `/data` is small, so that is
  cheap). On SELinux hosts (Fedora, RHEL, Alma) add `:Z`. Example: `-v ~/kidney-data:/data:Z,U`.
  **Never** use `:U` or `:Z` on `$HOME` itself or a system directory.
* Never use `--security-opt label=disable`.

### Plan HTTPS and the URL first

Phones need HTTPS for offline mode, the barcode camera and secure sign-in. Pick the address people
will type **before** anyone installs the app on a phone; changing it later creates a new, empty app
on every phone. The four options are in [`https.md`](https.md).

## Configuration

Set these as environment variables (Quadlet `Environment=`, `deploy/.env` for compose, `env:` in
Kubernetes). Every **secret** is given as a file through its `*_FILE` variable; setting both `NAME`
and `NAME_FILE` is a start-up error, an empty file means "unset", and trailing newlines are ignored.
Anything set here is **locked**: the Settings screen shows it as "set by server"; an **empty** value
counts as unset, so `deploy/.env` can leave a key blank and an admin still chooses in the app. The
complete list with defaults is at the top of [`app/config.py`](../app/config.py) and in
[`app/settings_registry.py`](../app/settings_registry.py).

**Outbound connections.** Meal guidance and everything else in the app work with no internet access.
Each feature that contacts the internet is off until you switch it on and then reaches one host only:
USDA search (`api.nal.usda.gov`, when a USDA key is set), Open Food Facts (`world.openfoodfacts.org`),
the AI provider you configure, and the breached-password check (`api.pwnedpasswords.com`). Every
request goes through the app's address check (no private, loopback or metadata addresses unless
listed). Firewall rules per host: [network-allowlist.md](network-allowlist.md); the Kubernetes
NetworkPolicy and the compose, Quadlet and `.env.example` comments name the same hosts.

| Variable | Default | Purpose |
|---|---|---|
| `PUBLIC_URL` | unset | The URL people type, e.g. `https://food.home.example.net`. Its host passes the Host check, browsers' `Origin` must match it, and invite/reset links and the setup line use it. **Set it whenever you use a host name.** |
| `ALLOWED_HOSTS` | localhost, IP literals and the `PUBLIC_URL` host | Extra host names (comma list, `*.example.org` wildcards). Any other `Host` gets `400 Unknown host` (DNS-rebinding defence) and one log line naming it. |
| `TRUSTED_PROXIES` | `127.0.0.1,::1` | Addresses whose `X-Forwarded-For`/`-Proto` are believed. **Depends on your engine**: see [`security.md` §4](security.md#4-proxy-trust-trusted_proxies-per-topology). |
| `AUTH_MODE` | `local` | `local` (accounts with passwords), `proxy` (identity from Authelia, Authentik or `tailscale serve`), `none` (no sign-in). See [Sign-in modes](#sign-in-modes). |
| `SECRET_KEY_FILE` | auto-generated `/data/secret.key` with a warning | Encrypts stored API keys. One key per line, ≥ 32 characters. Every shipped profile mounts it from the engine's secret store, **outside** the data volume. |
| `USDA_API_KEY_FILE` | unset | Enables "Search USDA" (free key: <https://fdc.nal.usda.gov/api-key-signup>; `DEMO_KEY` allows 30 requests per hour). |
| `ADMIN_USERNAME` + `ADMIN_PASSWORD_FILE` | unset | First run only: create the admin from a file instead of the setup code (GitOps). |
| `TRUSTED_PROXY_USER_HEADER`, `TRUSTED_PROXY_SECRET_FILE` | unset | `AUTH_MODE=proxy`: the identity header (`Remote-User`) and the shared secret the proxy sends as `X-Proxy-Secret`. |
| `ALLOW_INSECURE_HTTP` | automatic | Plain-HTTP sign-in from other machines is allowed while only one account exists, refused once there are two. |
| `SESSION_IDLE_DAYS`, `SESSION_MAX_DAYS` | 14, 30 | Sign-in lifetime. |
| `LOG_LEVEL` | `INFO` | `DEBUG` shows more; secrets are redacted from logs either way. |
| `MAX_BODY_BYTES`, `MAX_IMAGE_BYTES` | 1 MiB, 4 MiB | Request size limits (JSON; photos). |
| `HSTS_MAX_AGE` | 31536000 | Sent only over HTTPS; `0` disables it. |
| `ENABLE_API_DOCS` | `false` | `/docs` and `/openapi.json` (with a relaxed CSP on those paths only). |
| `PWA_ENABLED` | `true` | `false` is the kill switch for the offline service worker. |
| `DATA_DIR` | `/data` in the image | Where `kidney.db` lives. |
| `HANDBOOK_DIR` | `/app/learn` in the image; `handbook/site` in a checkout | The built handbook served at `/learn/`. Without an `index.html` there, `/learn` answers 404 and the app's Learn links use `HANDBOOK_PUBLIC_URL`, or are hidden. The app reads the site once at start: restart it after rebuilding the handbook in place. |
| `HANDBOOK_PUBLIC_URL` | unset | A published copy of the handbook (for example GitHub Pages), `http(s)://` only: where Learn links point when this server has no handbook, and the "public copy" link in Settings → About. |
| `PASSWORD_BREACH_CHECK` | `false` | Refuse new passwords found in the Have I Been Pwned list (only the first 5 characters of the password's SHA-1 leave the server, to `api.pwnedpasswords.com`). |
| `OFF_ENABLED`, `OFF_CONTACT` | off; the project URL | Open Food Facts barcode lookups (only the barcode digits go to `world.openfoodfacts.org`, and only for people who agreed in Settings → Food data) and the contact sent in their `User-Agent`. `OFF_RATE_PER_MINUTE` (10, at most 15), `BARCODE_NEGATIVE_TTL_HOURS` (24) and `USDA_BRANDED_BARCODE` (`true`: with a USDA key, a barcode Open Food Facts does not know, or knows without nutrition facts, is looked up in USDA's branded foods) tune them. See [barcode-and-photos.md](barcode-and-photos.md). |
| `GUIDANCE_ENABLED` | `true` | Rule-based meal guidance (What fits now, swaps, Plan the rest of my day, insights). It runs on the server and sends nothing out. `GUIDANCE_POOL_PER_ROLE` (200) and `GUIDANCE_BEAM_WIDTH` (16) make planning cheaper on a small server. See [guidance.md](guidance.md). |
| `AI_ENABLED` and the other `AI_*` | AI off | Optional AI ideas. `AI_ENABLED` is the server-wide switch (also in Settings → Admin); the provider is env-only: `AI_PROVIDER`, `AI_BASE_URL`, `AI_MODEL`, `AI_VISION_MODEL`, `AI_API_KEY_FILE`, `AI_PRIVATE_HOSTS` for a server on your LAN. Each person still opts in. Full list and recipes: [ai.md](ai.md); a local Ollama: `deploy/compose.ai-ollama.yaml`. |
| `INSTANCE_NAME`, `REGISTRATION_MODE`, `AUDIT_RETENTION_DAYS`, `USDA_SHARED_DAILY_LIMIT` | Kidney Health, `invite`, 365, 200 | Server settings an admin can also change in Settings → Admin → Server settings, unless set here. |

`APP_PASSWORD` (v0.2's HTTP Basic auth) is **deprecated**: on the first v0.3 start with no admin
it becomes the admin's password, then it is ignored. HTTP Basic is no longer accepted.

## First run

On the first start of an empty (or v0.2) database the app creates no account by itself. It prints a
**one-time setup code** to its log, valid for 60 minutes:

```
FIRST-RUN SETUP: open https://food.home.example.net/#/setup and enter the code 7KQ2-M9XD-PL4R-T6WN (valid 60 min; restart or run "python -m app.admin setup-code" for a new one)
```

Read it with `journalctl --user -u kidney-health | grep 'FIRST-RUN SETUP'` (Quadlet),
`podman logs kidney-health 2>&1 | grep 'FIRST-RUN SETUP'` (compose, Docker: `docker logs`), or
`kubectl -n kidney-health logs deploy/kidney-health | grep 'FIRST-RUN SETUP'`. Open the app, enter
the code, and choose the admin's user name and password (at least 15 characters). The setup screen
also offers to switch on Open Food Facts barcode lookups (off by default). Until setup is done,
every API call except the setup screen answers `503 Setup required`.

Alternatives: `ADMIN_USERNAME` + `ADMIN_PASSWORD_FILE` (GitOps, Kubernetes), or
`python -m app.admin create-admin` inside the container (the password is read from stdin). After
setup, invite the other people in your household from Settings → Admin → Users & invites.

## Rootless Podman with Quadlet (recommended)

Quadlet turns [`deploy/quadlet/kidney-health.container`](../deploy/quadlet/kidney-health.container)
into a systemd user service with auto-start, health-based restarts and auto-update. It needs Podman
4.9 or later (`Notify=healthy` needs 5.0).

```bash
mkdir -p ~/.config/containers/systemd
cp deploy/quadlet/kidney-health.container deploy/quadlet/kidney-health.volume ~/.config/containers/systemd/

# The encryption key for stored API keys, kept by Podman's secret store (not on the data volume).
python3 -c "import secrets; print(secrets.token_urlsafe(32))" | podman secret create kidney-secret-key -
# Optional USDA key: create the secret, then uncomment the two USDA lines in the unit.
#   printf '%s' "$USDA_KEY" | podman secret create kidney-usda-key -

$EDITOR ~/.config/containers/systemd/kidney-health.container     # PUBLIC_URL, TRUSTED_PROXIES
/usr/libexec/podman/quadlet -user -dryrun >/dev/null && echo unit OK  # Debian/Ubuntu: /usr/lib/podman/quadlet
systemctl --user daemon-reload
systemctl --user start kidney-health
sudo loginctl enable-linger "$USER"
systemctl --user enable --now podman-auto-update.timer               # daily pulls of the :0.3 tag
```

What the unit sets, and why, is commented line by line in the file: `127.0.0.1` publishing,
`ReadOnly=true` with a `noexec` tmpfs on `/tmp`, `DropCapability=all`, `NoNewPrivileges=true`,
`PidsLimit=128`, `--memory=512m`, a `noexec,nosuid,nodev` data volume, `Secret=` mounted as
`/run/secrets/secret_key` (owner 10001, mode 0400), and the health check in exec form (the image has
no shell). Check the result:

```bash
podman info --format '{{.Host.Security.Rootless}}'        # true
podman top kidney-health user huser                       # 10001  <subordinate UID>
podman inspect kidney-health --format '{{.HostConfig.ReadonlyRootfs}} {{.HostConfig.CapDrop}}'
podman healthcheck run kidney-health && echo healthy
```

Status and logs: `systemctl --user status kidney-health`, `journalctl --user -u kidney-health -f`.
Typos make `daemon-reload` skip the unit silently: run the `quadlet -dryrun` line above.

**A local Ollama or Hermes on the same host.** pasta maps `host.containers.internal` to the host
(169.254.1.2, Podman ≥ 5.3), but a host service that listens only on `127.0.0.1` (the default for
Ollama and Hermes) stays unreachable, which is good. Do not "fix" that with `pasta:--map-gw`, which
exposes every loopback service on the host to the container. Run Ollama as a container next to the
app instead (`deploy/compose.ai-ollama.yaml`), or bind Hermes to a specific LAN address and add it
to `AI_PRIVATE_HOSTS`.

**Rootful instead?** Not recommended. If you must, place the files in `/etc/containers/systemd/`
and drop `--user`; the app still runs as UID 10001, but an escape lands as a host UID that the
kernel does not separate from root's user namespace.

## Compose (podman-compose or docker compose)

[`deploy/compose.yaml`](../deploy/compose.yaml) carries the same hardening. With Podman it needs
**podman-compose 1.5.0 or later** (`podman-compose version`). Older versions, which Ubuntu 24.04
(1.0.6), Debian 12/13 and RHEL 8's EPEL package, run the exec-form health check through `/bin/sh`,
which the image does not have, so the container always reports `unhealthy`; and they ignore
`x-podman.relabel`, so on SELinux hosts the app cannot read its secrets (`SECRET_KEY_FILE: cannot
read ... permission denied`). Install a current one (`pipx install 'podman-compose>=1.5'`) or use
Quadlet (above). If you must stay on an older one: `chcon -t container_file_t deploy/secrets/*`
fixes the secrets, and the `unhealthy` status is then cosmetic (the app still serves). Secrets are
files in `deploy/secrets/` (git-ignored):

```bash
install -d -m 0700 deploy/secrets
python3 -c "import secrets; print(secrets.token_urlsafe(32))" > deploy/secrets/secret_key
: > deploy/secrets/usda_api_key            # empty = USDA search off; or paste your key
chmod 0644 deploy/secrets/secret_key deploy/secrets/usda_api_key
cp deploy/.env.example deploy/.env && $EDITOR deploy/.env     # PUBLIC_URL, TRUSTED_PROXIES, ...
podman-compose -f deploy/compose.yaml up -d                   # or: docker compose -f deploy/compose.yaml up -d
```

Why `0644` inside a `0700` directory: compose mounts file secrets as bind mounts, and under a
rootless engine your UID is container root, so a `0600` file you own is unreadable for UID 10001.
The directory keeps other host users out. On Podman you can instead keep `0600` and run
`podman unshare chown 10001:10001 deploy/secrets/*`. On SELinux hosts podman-compose 1.5.0 or later
relabels the secrets (`x-podman.relabel: Z`).

With `restart: always`, enable `systemctl --user enable --now podman-restart.service` so Podman
starts the container after a reboot, or use Quadlet. Optional overlays:
`-f deploy/compose.caddy.yaml` (HTTPS with Caddy, [`https.md`](https.md) tier 1) and
`-f deploy/compose.ai-ollama.yaml` (a local Ollama on an internal network).

## Rootless Docker

1. Install `uidmap` and `docker-ce-rootless-extras`, then as your user:
   `dockerd-rootless-setuptool.sh install`.
2. `systemctl --user enable --now docker` and `sudo loginctl enable-linger "$USER"`.
3. `docker context use rootless`; `docker info` must list `name=rootless` under Security Options.
4. Run it, either with compose as above, or with
   [`deploy/docker-rootless-run.sh`](../deploy/docker-rootless-run.sh), which spells out every flag
   (`--read-only`, `--tmpfs /tmp`, `--cap-drop ALL`, `--security-opt no-new-privileges:true`,
   `--pids-limit 128`, `--memory 512m`, `127.0.0.1` publishing, secrets as read-only bind mounts)
   and refuses a rootful daemon.

Limits that matter here:

* **Source addresses are not propagated by default**: every client, including an HTTPS proxy on
  the same host (Caddy or nginx on the host, `tailscale serve`), appears to come from the
  RootlessKit/bridge gateway, for example `172.17.0.1`. Keep publishing on `127.0.0.1`. Without a
  proxy, leave `TRUSTED_PROXIES` at the loopback default. **With a same-host HTTPS proxy, set
  `TRUSTED_PROXIES` to the gateway address the app logs** (`docker logs kidney-health`; with the run
  script: `TRUSTED_PROXIES=172.17.0.1 deploy/docker-rootless-run.sh`), otherwise the app does not
  believe the proxy's `X-Forwarded-Proto: https`, and a second account cannot register or sign in
  (`https_required`). Trusting the gateway is safe only because the port is published on
  `127.0.0.1`, so only local processes reach it; in proxy mode also set `TRUSTED_PROXY_SECRET_FILE`.
  The `compose.caddy.yaml` overlay avoids the question (container to container). Details in
  [`security.md` §4](security.md#4-proxy-trust-trusted_proxies-per-topology).
* **Re-running the script** (for example to pin a verified digest with `IMAGE=...@sha256:...`)
  replaces the running container: it stops and removes `kidney-health` first. The data stays on the
  `kidney-health-data` volume.
* `--memory` and `--pids-limit` need cgroup v2 with systemd; otherwise Docker ignores them silently.
* No AppArmor; ports below 1024 need `net.ipv4.ip_unprivileged_port_start`.
* Docker's `--health-cmd` always runs through `/bin/sh`, which the image does not have, so do not
  pass one: the image's own `HEALTHCHECK` (exec form) applies.

## Kubernetes (Talos)

The Kustomize base in [`deploy/k8s/`](../deploy/k8s/) satisfies Pod Security **restricted**, which
the namespace enforces:

```
deploy/k8s/
  kustomization.yaml                  resources + image pin (tag and digest)
  namespace.yaml                      PSA enforce/audit/warn: restricted
  pvc.yaml                            1 Gi ReadWriteOnce                    <- storageClassName
  deployment.yaml                     UID 10001, read-only root, /tmp emptyDir, secret files, probes
  service.yaml                        ClusterIP :80 -> :8000
  networkpolicy.yaml                  default-deny + DNS + public 443 + ingress from the Gateway
  httproute.yaml                      Gateway API route (default)           <- parentRefs, hostname
  ingress.example.yaml                Ingress instead (not applied; ingress-nginx is retired)
  cilium-networkpolicy.example.yaml   FQDN egress allowlist for Cilium (not applied)
  secret.example.yaml                 the Secret's shape (not applied: never commit secrets)
```

### 1. Pick storage

Edit `pvc.yaml` (`storageClassName`) or leave it unset for the cluster default.

| StorageClass | Fits when | Notes |
|---|---|---|
| `local-path` | one node, or the pod may be tied to one node | hostPath; on Talos the provisioner's namespace needs the `privileged` PSA label and a kubelet extra mount. Pin the pod with the `nodeSelector` comment in `deployment.yaml`. |
| `longhorn` | 2+ nodes, replicas and snapshots | Talos needs the `iscsi-tools` and `util-linux-tools` extensions and a `/var/lib/longhorn` kubelet mount. |
| `rook-ceph-block` | you already run Ceph | Raw disks; the name is your CephBlockPool StorageClass. |
| `mayastor-*` (OpenEBS) | you already run Mayastor | Hugepages per node; create a StorageClass and use its name. |
| NFS | avoid | SQLite relies on file locking that NFS implements poorly; also not idmap-capable (no `hostUsers: false`). |

A replicated volume faithfully replicates a corrupted file: replication does not replace backups.

### 2. Secret, then apply

```bash
kubectl create namespace kidney-health --dry-run=client -o yaml | kubectl apply -f -
kubectl -n kidney-health create secret generic kidney-health \
  --from-literal=secret_key="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')" \
  --from-literal=usda_api_key=''
$EDITOR deploy/k8s/httproute.yaml deploy/k8s/networkpolicy.yaml deploy/k8s/deployment.yaml
kubectl apply -k deploy/k8s
kubectl -n kidney-health rollout status deploy/kidney-health
kubectl -n kidney-health logs deploy/kidney-health | grep 'FIRST-RUN SETUP'
```

Both Secret keys must exist (the app reads both files; an empty `usda_api_key` means "off"). Keep a
copy of `secret_key` in your password manager. Talos encrypts Secrets in etcd (secretbox) by default.

### 3. Things to set in `deployment.yaml`

* `PUBLIC_URL` = the HTTPRoute host name with `https://`.
* `TRUSTED_PROXIES`: the shipped `10.244.0.0/16` (Talos' default pod CIDR) trusts **every pod**; it is
  only safe while the NetworkPolicy below is enforced or `TRUSTED_PROXY_SECRET_FILE` is set. Narrow
  it to your Gateway's pods where you can.
* `supplementalGroupsPolicy: Strict` needs containerd ≥ 2.0 (Talos ships it); remove the line if the
  kubelet rejects the pod.

### 4. Make NetworkPolicy real on Talos

Talos' default CNI (Flannel) **silently ignores** NetworkPolicy unless `kubeNetworkPoliciesEnabled:
true` is set in its configuration (Talos ≥ 1.13; from 1.14 in the `KubeFlannelCNIConfig` document;
see the Talos Flannel guide). Test that the policy is enforced:

```bash
kubectl -n kidney-health run np-test --rm -it --restart=Never \
  --image=cgr.dev/chainguard/curl:latest --overrides='{"spec":{"securityContext":{"runAsNonRoot":true,"runAsUser":65532,"seccompProfile":{"type":"RuntimeDefault"}},"containers":[{"name":"np-test","image":"cgr.dev/chainguard/curl:latest","args":["-sS","-m","5","http://kidney-health/healthz"],"securityContext":{"allowPrivilegeEscalation":false,"capabilities":{"drop":["ALL"]}}}]}}'
# must FAIL (DNS error or timeout): default-deny blocks this pod's egress and the app's ingress.
# If it prints {"status":"ok",...}, NetworkPolicy is not enforced on your cluster.
```

`networkpolicy.yaml` lets the Gateway's namespace in on port 8000 (edit `gateway-system`), and lets
the pod out only to kube-dns and to **public** addresses on 443 (private, CGNAT, link-local and
loopback ranges are excluded, so cloud metadata and the API server are unreachable). Kubelet probes
come from the node and are not affected. With Cilium, replace the `0.0.0.0/0` rule with
`cilium-networkpolicy.example.yaml` (exact host names). **Cilium's own Gateway API or Ingress** is
not a pod in a namespace: its Envoy sends traffic with the reserved `ingress` identity, which the
`namespaceSelector` rule never matches, so default-deny drops it (the Gateway answers 403 or 503).
Apply the second policy in `cilium-networkpolicy.example.yaml` (`fromEntities: [ingress]` on port
8000) in that case. A LAN Ollama needs its own egress rule (a commented example is in the file) and
an `AI_PRIVATE_HOSTS` entry.

### 5. Check Pod Security, pin the digest

```bash
kubectl label --dry-run=server --overwrite ns kidney-health pod-security.kubernetes.io/enforce=restricted   # no warnings
scripts/verify-image.sh 0.3.0                 # prints the verified digest
cd deploy/k8s && kustomize edit set image ghcr.io/ksullivan86/kidney-health=ghcr.io/ksullivan86/kidney-health:0.3.0@sha256:<digest>
```

`imagePullPolicy: IfNotPresent` plus a digest means a node never pulls something you did not verify.
There is deliberately **no PodDisruptionBudget**: with one replica it would block every node drain
(`talosctl upgrade`); a short outage during a drain is fine for this app.

### 6. Optional: a user namespace for the pod

`hostUsers: false` (GA in Kubernetes 1.36) runs the pod in its own user namespace, so even root in
the container is unprivileged on the node. It needs Linux ≥ 6.3, containerd ≥ 2.0, idmap-capable
volumes (ext4, xfs, btrfs, tmpfs; not NFS) and, on Talos, user namespaces switched on:

```yaml
# Talos machine config patch
apiVersion: v1alpha1
kind: SysctlConfig
sysctls:
  user.max_user_namespaces: "11255"
```

Then uncomment `hostUsers: false` in `deployment.yaml`.

### Debugging without a shell

The image has no shell by design. Use `kubectl debug -it --profile=restricted --target=app POD
--image=cgr.dev/chainguard/python:latest-dev`, or on Podman `podman cp` and
`podman run --rm -it --entrypoint sh --user 10001:0 --volumes-from kidney-health cgr.dev/chainguard/python:latest-dev`
(the `-dev` image's entrypoint is `python` and its default user cannot enter `/data`, hence
`--entrypoint sh` and `--user 10001:0`). Most tasks have an `app.admin` command instead (below).

## Sign-in modes

* **`AUTH_MODE=local`** (default): accounts with passwords, an in-app sign-in page, sessions in an
  `HttpOnly` cookie. Works behind any reverse proxy. Use HTTPS once more than one person signs in
  (the app refuses plain-HTTP sign-in from other machines when there are two accounts).
* **`AUTH_MODE=proxy`**: your reverse proxy signs people in (Authelia, Authentik) and passes the
  user name in a header. Set `TRUSTED_PROXY_USER_HEADER=Remote-User` (optionally
  `TRUSTED_PROXY_GROUPS_HEADER`, `TRUSTED_PROXY_ADMIN_GROUP`, `PROXY_LOGOUT_URL`),
  `TRUSTED_PROXIES` = the proxy's address, and **`TRUSTED_PROXY_SECRET_FILE`**: a long random value
  the proxy also sends as `X-Proxy-Secret`. Without it the app refuses to start, because any process
  that can reach the app from the proxy's address could otherwise claim to be anyone. Caddy:
  `header_up X-Proxy-Secret {env.KH_PROXY_SECRET}` inside `reverse_proxy`; Traefik:
  `headers.customRequestHeaders`; nginx: `proxy_set_header X-Proxy-Secret ...`. `tailscale serve`
  cannot add headers, so it needs `TRUSTED_PROXY_SECRET_OPTIONAL=true` (logged as a warning).
* **`AUTH_MODE=none`**: no sign-in at all; everything belongs to one person and anyone who can open
  the page can read and change it. Only for one person on a trusted LAN, never exposed beyond it.

## Backups and restore

`kidney.db` holds every person's health data, password hashes and the encrypted API keys. Back it
up with the built-in command: it uses SQLite's online backup API, so the copy is consistent while
the app keeps running, and it needs no shell in the container.

```bash
# Quadlet / compose / Docker (use docker instead of podman as needed)
podman exec kidney-health python -m app.admin backup - > "kidney-$(date +%F).db"
# Kubernetes
kubectl -n kidney-health exec deploy/kidney-health -- python -m app.admin backup - > "kidney-$(date +%F).db"
chmod 0600 kidney-*.db
```

Then:

* **Encrypt** the copies (restic, borg or age): they contain special-category health data.
* **Back up `SECRET_KEY` separately** (a password manager). The `app.admin backup` copy does not
  contain it; a volume-level backup does if the key was auto-generated as `/data/secret.key`, which
  is why every shipped profile mounts `SECRET_KEY_FILE` instead. Restoring without the key loses
  only the stored API keys.
* Check a backup now and then: `python -m app.admin restore-check FILE` reports integrity, the
  schema version, the number of users and, when it is given the app's `SECRET_KEY_FILE`, whether
  the stored keys decrypt with the current key (without it, it says the keys were not checked).

**Restore** (the app must be stopped, so nothing writes during the copy). The backup file must be
readable for UID 10001 inside the container: `podman unshare chown 10001:0 kidney-2026-10-01.db`
(rootless Podman), or `chmod 0644` it inside a `0700` directory (rootless Docker). `app.admin
backup` writes the copy in SQLite's rollback-journal mode, and `restore-check` opens a read-only
file as immutable, so the file can stay on a read-only (`:ro`) mount: SQLite needs no `-shm` file
next to it. (A copy made some other way, for example from a volume snapshot, is in WAL mode; the
one-liner in step 2 opens it with `immutable=1` for the same reason.)

```bash
# 1. Check the backup with the same image (no shell needed; works on Docker too). Pass the app's
#    secret so restore-check can also say whether the stored API keys decrypt with it.
podman run --rm --user 10001:10001 --entrypoint python \
  --secret kidney-secret-key,type=mount,target=secret_key,uid=10001,mode=0400 \
  -e SECRET_KEY_FILE=/run/secrets/secret_key \
  -v "$PWD/kidney-2026-10-01.db:/restore/kidney.db:ro,Z" \
  ghcr.io/ksullivan86/kidney-health:0.3 -m app.admin restore-check /restore/kidney.db

# 2. Stop the app, then copy the backup INTO the volume through SQLite (handles the WAL files).
systemctl --user stop kidney-health          # compose: podman-compose -f deploy/compose.yaml stop
podman run --rm --user 10001:10001 --entrypoint python \
  -v systemd-kidney-health:/data \
  -v "$PWD/kidney-2026-10-01.db:/restore/kidney.db:ro,Z" \
  ghcr.io/ksullivan86/kidney-health:0.3 -c "import sqlite3; s=sqlite3.connect('file:/restore/kidney.db?mode=ro&immutable=1', uri=True); d=sqlite3.connect('/data/kidney.db'); s.backup(d); d.close(); s.close()"

# 3. Optional: sign everybody out of the restored copy (sessions in the backup become valid again).
podman run --rm --user 10001:10001 --entrypoint python -v systemd-kidney-health:/data \
  ghcr.io/ksullivan86/kidney-health:0.3 -m app.admin revoke-sessions --all
systemctl --user start kidney-health
```

(The compose volume is `kidney-health_kidney-data`; Docker without compose: `kidney-health-data`.
Compose and Docker keep the secret as a file: replace the `--secret` line with
`-v "$PWD/deploy/secrets/secret_key:/run/secrets/secret_key:ro,Z"`, without `,Z` on Docker.)
Restoring a copy into a directory you can write instead (`restore-check --revoke-sessions FILE`)
also works; it cannot work on a `:ro` mount, which is why step 3 runs on the volume.

**Kubernetes.** The image has no `tar`, so `kubectl cp` cannot copy into it; stream the file
through Python instead. Scale the app down, start the restore pod from
[`deploy/k8s/restore-pod.example.yaml`](../deploy/k8s/restore-pod.example.yaml) (restricted security
context, UID 10001, the PVC at `/data`, an `emptyDir` at `/tmp`), then:

```bash
kubectl -n kidney-health scale deploy/kidney-health --replicas=0
kubectl -n kidney-health apply -f deploy/k8s/restore-pod.example.yaml
kubectl -n kidney-health wait --for=condition=Ready pod/kidney-health-restore
kubectl -n kidney-health exec -i kidney-health-restore -- python -c \
  "import shutil,sys; shutil.copyfileobj(sys.stdin.buffer, open('/tmp/restore.db','wb'))" < kidney-2026-10-01.db
kubectl -n kidney-health exec kidney-health-restore -- python -m app.admin restore-check /tmp/restore.db
kubectl -n kidney-health exec kidney-health-restore -- python -c \
  "import sqlite3; s=sqlite3.connect('file:/tmp/restore.db?mode=ro&immutable=1', uri=True); d=sqlite3.connect('/data/kidney.db'); s.backup(d); d.close(); s.close()"
kubectl -n kidney-health exec kidney-health-restore -- python -m app.admin revoke-sessions --all   # optional
kubectl -n kidney-health delete pod kidney-health-restore
kubectl -n kidney-health scale deploy/kidney-health --replicas=1
```

A backup restores into the same or a **newer** app version (migrations run on start); never into an
older one.

## Upgrades

* **Track `:0.3`** (patch releases, no breaking changes) with Quadlet `AutoUpdate=registry` and
  `podman-auto-update.timer`, or pin a digest you verified (`scripts/verify-image.sh`) and change
  it deliberately. Do not track `:latest` or `:edge` on a machine you care about: `:edge` follows
  every merge to `main`.
* Before a minor upgrade (0.3 → 0.4): take a backup, read the release notes, then change the tag.
* Never mount the Podman or Docker socket into an "updater" container ([`security.md` §7](security.md#7-never-mount-the-container-engines-socket)).

### From v0.2 to v0.3

0. **An auto-updating v0.2 host: act before v0.3.0 is released.** v0.2's Quadlet unit tracks
   `:latest` with `AutoUpdate=registry`, `HealthOnFailure=kill` and a plain-string `HealthCmd=`
   (run through `/bin/sh`). Once `:latest` points at v0.3, `podman-auto-update` pulls the shell-less
   image under that unit; the restart succeeds, so nothing rolls back, and then the health check
   fails, the container is killed and restarted, about every two minutes. Either do this upgrade
   first (the steps below, with the v0.3 unit), or pin the running v0.2 image by digest
   (`podman inspect kidney-health --format '{{.ImageDigest}}'` → `Image=...@sha256:...`) and
   `systemctl --user disable --now podman-auto-update.timer` until you do. If a host is already in
   the loop: `systemctl --user stop kidney-health`, install the v0.3 unit, `systemctl --user
   daemon-reload`, start it.
1. **Back up first** (`app.admin backup` does not exist in v0.2; with the old image, which still
   has a shell, copy the file: `podman exec kidney-health python -c "import sqlite3; s=sqlite3.connect('/data/kidney.db'); d=sqlite3.connect('/data/v02-backup.db'); s.backup(d)"` and
   `podman cp kidney-health:/data/v02-backup.db .`).
2. **The upgrade makes its own backup too**: before the accounts migration (schema v3) the app copies
   the database to `/data/kidney.db.pre-v3.bak` with the SQLite backup API. It is the rollback path
   and is deleted automatically 30 days after the upgrade (Admin → About shows it while it exists).
   To roll back, stop v0.3, restore that file as `kidney.db` (as in [Restore](#backups-and-restore)) and
   start the old image. **Do not roll back after a second person has signed up**: v0.2 has no
   accounts and would mix everyone's log; restore the pre-v3 backup instead.
3. **Replace your deployment files** with the v0.3 ones (Quadlet unit, `compose.yaml`, `deploy/k8s/`).
   What changed and why it matters:
   * The image has no shell any more: backups, restores and health checks use `python -m app...`.
   * Secrets are files: move `USDA_API_KEY` from the env file into a Podman secret,
     `deploy/secrets/usda_api_key` or the Kubernetes Secret, and add `SECRET_KEY_FILE`.
   * The port is published on `127.0.0.1`; reach the app through your HTTPS proxy.
   * Set **`PUBLIC_URL`** (or `ALLOWED_HOSTS`) if people use a host name: unknown host names now get
     `400 Unknown host`. IP addresses and `localhost` keep working.
   * `--forwarded-allow-ips=*` is gone: list your proxy in `TRUSTED_PROXIES` ([`security.md` §4](security.md#4-proxy-trust-trusted_proxies-per-topology)).
   * Tags: `:latest` now means "newest release", not "main"; `main` builds are `:edge`. Track `:0.3`.
   * `--userns=keep-id` is no longer recommended (see [User namespaces](#user-namespaces-keep-the-default)).
4. **Accounts.** On first start the existing log becomes the admin's (user 1). If you used
   `APP_PASSWORD`, it becomes that admin's password (you are asked to change it if it is shorter
   than 15 characters); otherwise finish setup with the setup code from the log.
5. Volumes keep working: the owner UID is still 10001 (new volumes are `10001:0`, mode 0770). For a
   bind mount, `:U` or `podman unshare chown -R 10001:0 DIR` sets the new group.

## Building the image yourself

From the repository root (the `.dockerignore` lets only `app/`, `data/foods.json`, `LICENSE`,
`requirements.lock` and `handbook/` into the build):

```bash
podman build --format docker -f deploy/Containerfile -t kidney-health:local .          # Chainguard (published)
podman build --format docker -f deploy/Containerfile.debian -t kidney-health:debian .  # Debian fallback
```

`--format docker` keeps the image `HEALTHCHECK` (Podman's default OCI format drops it; the Quadlet
unit and compose file declare the probe anyway). Dependencies are installed from the hash-locked
`requirements.lock`, wheels only, so a build needs `pypi.org` and `files.pythonhosted.org` but never
compiles anything.

* **Which file?** `deploy/Containerfile` (Chainguard Python, 0 High/Critical findings when chosen)
  is what CI publishes. `deploy/Containerfile.debian` (`python:3.14-slim-trixie`) is the fallback
  if Chainguard's free tier changes or a wheel lags its Python; it keeps `/bin/sh` for debugging but
  has no pip and no setuid binaries. CI builds and smoke-tests both.
* **ARM**: the published image covers linux/arm64 (Raspberry Pi 4/5, Talos on arm64). To build on
  the device itself just run the command above; to cross-build use
  `podman build --platform linux/arm64 ...` with `qemu-user-static` installed. 32-bit ARM is not
  supported.
* **Base digests** are pinned in the `FROM` lines and bumped by Dependabot; to re-resolve them by
  hand: `crane digest cgr.dev/chainguard/python:latest-dev` and `crane digest cgr.dev/chainguard/python:latest`.
* The patient handbook is built by a separate, throw-away stage (`handbook`) from the hash-locked
  `handbook/requirements.lock` with `mkdocs build --strict`; only the built site reaches the runtime
  image, read-only at `/app/learn`, and the app serves it at `/learn/`. The build fails on any broken
  link or external asset. To build or preview it without the image, see
  [`handbook/README.md`](../handbook/README.md).

## Local development run

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install --require-hashes --no-deps -r requirements-dev.lock
uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-proxy-headers   # DATA_DIR defaults to ./data-local
python -m pytest
```

## Troubleshooting

**`400 Unknown host`** – you opened the app by a host name the app does not know. Set `PUBLIC_URL`
(or `ALLOWED_HOSTS`); the log names the host it refused. IP addresses and `localhost` always work.

**`unable to open database file` / `attempt to write a readonly database`** – `/data` is not
writable by UID 10001. Named volumes need nothing. Bind mounts: `:U` (Podman) or
`podman unshare chown -R 10001:0 DIR`; on SELinux hosts add `:Z` (`ausearch -m avc -ts recent`
shows denials). Kubernetes: `fsGroup: 10001` handles CSI volumes; hostPath-style classes may need
the directory chowned on the node.

**`SECRET_KEY_FILE points to ..., which does not exist`** or `permission denied` – the secret is
missing or unreadable for UID 10001: create the Podman secret / Kubernetes Secret, or fix the file
mode (compose: `0644` in a `0700` directory). Setting both `X` and `X_FILE` is also refused.

**Health check failing** – the probe runs `python -m app.healthcheck` in exec form. A health command
given as a plain string (Docker `--health-cmd`, an old Quadlet `HealthCmd=` line) runs through
`/bin/sh`, which the image does not have: use the JSON form `["python", "-m", "app.healthcheck"]`.
`podman healthcheck run kidney-health` runs it by hand; `podman logs kidney-health` shows Python
errors. On slow storage raise the start period.

**Every request looks like it comes from one address / rate limits hit everyone** – your engine does
not pass client addresses through (rootless Docker, slirp4netns) or `TRUSTED_PROXIES` does not
match your proxy. See [`security.md` §4](security.md#4-proxy-trust-trusted_proxies-per-topology).

**`403` on every save** – the browser's `Origin` does not match: set `PUBLIC_URL` to exactly the
URL in the address bar (scheme, host and port), especially if your proxy rewrites `Host`.

**Sign-in refused over HTTP** – with two or more accounts the app refuses plain-HTTP sign-in from
other machines. Set up HTTPS ([`https.md`](https.md)).

**`https_required` although the browser shows HTTPS** – the app does not believe your proxy's
`X-Forwarded-Proto: https`, because the address it connects from is not in `TRUSTED_PROXIES`. Typical
with rootless Docker or rootless Podman and a proxy on the same host (Caddy, nginx, `tailscale
serve`): the app sees a gateway or its own container address, not `127.0.0.1`. Put the address from
the access log in `TRUSTED_PROXIES` ([`security.md` §4](security.md#4-proxy-trust-trusted_proxies-per-topology)).
Admin → About shows whether the proxy is trusted.

**Memory or pids limit ignored** – rootless engines need cgroup v2 with systemd (see
[Before you start](#before-you-start)); `docker info`/`podman info` show the cgroup version.

**Pod `Pending`** – `kubectl -n kidney-health describe pvc kidney-health-data`: a mistyped
`storageClassName`, no default class, or a `nodeSelector` that matches no node.

**Pod rejected by Pod Security** – any extra container you add (debug, init, restore) must run as
non-root with `allowPrivilegeEscalation: false`, `capabilities.drop: [ALL]`, `seccompProfile:
RuntimeDefault`.

**`database is locked`** – two processes share one database. Run exactly one container per volume.

**`USDA request failed`** – the server cannot reach `api.nal.usda.gov:443` (egress rules,
[`network-allowlist.md`](network-allowlist.md)); `USDA API key was rejected` means a wrong key.

**Which version is running?** `podman inspect kidney-health --format '{{.ImageDigest}}'` or
`kubectl -n kidney-health get deploy kidney-health -o jsonpath='{.spec.template.spec.containers[0].image}'`.
