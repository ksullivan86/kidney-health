# Deployment guide

How to run the Kidney Health food log on a laptop, a Podman host, or a Talos Kubernetes
cluster, and how to keep its one small database safe. Everything the app needs is in one
container image; all state is a single SQLite file.

## What you are deploying

| Fact | Value |
|---|---|
| Image | `ghcr.io/ksullivan86/kidney-health` (linux/amd64 + linux/arm64) |
| Image tags | `latest` = current `main`; `0.2.0`, `0.2` = releases (`v0.2.0` git tag); `sha-<short>` = every main build |
| Listens on | TCP **8000** (plain HTTP; put TLS on a reverse proxy) |
| Runs as | uid/gid **10001** (`app`), no capabilities, no root |
| State | `DATA_DIR` = **`/data`** inside the image: `kidney.db` (+ `kidney.db-wal`, `kidney.db-shm` while running) |
| Health probe | `GET /healthz` returns `{"status":"ok","foods":395}`; it never requires a password |
| Outbound network | none, unless `USDA_API_KEY` is set (then only `api.nal.usda.gov:443`) |
| Browser | talks only to the app itself; no CDN, works on a LAN without internet |
| Footprint | ~60 MB RAM idle; 50 m CPU / 128 Mi requests are generous |
| Licence | PolyForm Noncommercial 1.0.0 (personal and noncommercial use; commercial use needs the author's permission) |

Environment variables (all optional; empty means unset):

| Variable | Default | Purpose |
|---|---|---|
| `DATA_DIR` | `/data` in the image, `./data-local` outside | Directory holding `kidney.db`; created on start |
| `USDA_API_KEY` | unset | Enables the "Search USDA" button, see [USDA lookups](#f-enabling-usda-lookups) |
| `APP_PASSWORD` | unset | Turns on HTTP Basic auth for every page and API call except `/healthz` |
| `FOODS_JSON` | `/app/data/foods.json` | Path of the builtin food database; leave alone |

The server starts in about two seconds: it creates or migrates the schema, then upserts
the 395 builtin foods (skipped when the food database version is unchanged).

**Rules that follow from SQLite:** exactly one instance per database (never two
containers or two pods on the same volume), a `ReadWriteOnce` volume, and a
`Recreate` rollout strategy on Kubernetes. The manifests in `deploy/` already do this.

---

## a. Local run with uvicorn

Needs Python 3.11 or newer (3.12 is what the image and CI use).

```bash
git clone https://github.com/ksullivan86/kidney-health.git
cd kidney-health
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
python -m pytest                                   # no network needed
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Open <http://localhost:8000>. The database lands in `./data-local/kidney.db` (gitignored).
Optional settings go in the environment:

```bash
DATA_DIR=$HOME/kidney-data APP_PASSWORD='a long passphrase' USDA_API_KEY=... \
  uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Add `--reload` while developing. Use `--host 127.0.0.1` if only this machine should
reach it.

---

## b. Podman run / podman-compose

Pulling from GHCR needs outbound access to `ghcr.io` and
`pkg-containers.githubusercontent.com` (see `docs/network-allowlist.md`).

### Plain `podman run`

```bash
podman volume create kidney-data

podman run -d --name kidney-health \
  -p 8000:8000 \
  -v kidney-data:/data \
  --restart always \
  --security-opt no-new-privileges --cap-drop ALL \
  ghcr.io/ksullivan86/kidney-health:latest

podman logs -f kidney-health          # "database /data/kidney.db ready; builtin foods: imported"
curl -s http://localhost:8000/healthz # {"status":"ok","foods":395}
```

Add `-e APP_PASSWORD='...'` and `-e USDA_API_KEY='...'` as needed. Docker: replace
`podman` with `docker`; the flags are identical.

Rootless Podman can bind port 8000 without any sysctl (only ports below 1024 need
`net.ipv4.ip_unprivileged_port_start`). Always name the volume: the image declares
`VOLUME /data`, so a run without `-v` gets an anonymous volume that `podman rm -v`
deletes.

**Bind mount instead of a named volume.** The container writes as uid 10001, so the
directory must be writable by that uid *as seen from inside the container*. With
rootless Podman, uid 10001 inside maps to a sub-uid of your user, hence `podman unshare`:

```bash
mkdir -p ~/kidney-health-data
podman unshare chown -R 10001:10001 ~/kidney-health-data
podman run -d --name kidney-health -p 8000:8000 \
  -v ~/kidney-health-data:/data:Z \
  ghcr.io/ksullivan86/kidney-health:latest
```

`:Z` applies the SELinux container label (Fedora, RHEL, CentOS, AlmaLinux); it is
ignored elsewhere. Alternative that keeps the files owned by *you* on the host:
`--userns=keep-id:uid=10001,gid=10001` (Podman 4.3+) maps your user to uid 10001 inside
the container, so no chown is required.

### Building locally

```bash
podman build -f deploy/Containerfile -t kidney-health:local .      # from the repo root
```

Podman builds OCI-format images and warns that `HEALTHCHECK` is ignored; add
`--format docker` if you want the probe embedded. compose and Quadlet below declare the
probe themselves so this does not matter for them. Local builds also pull
`python:3.12-slim` from Docker Hub (`registry-1.docker.io`, `auth.docker.io`,
`production.cloudflare.docker.com`).

### podman-compose / docker compose

```bash
cp deploy/.env.example deploy/.env      # optional: USDA_API_KEY, APP_PASSWORD
chmod 600 deploy/.env
$EDITOR deploy/.env

podman-compose -f deploy/compose.yaml up -d      # or: docker compose -f deploy/compose.yaml up -d
podman-compose -f deploy/compose.yaml logs -f
podman-compose -f deploy/compose.yaml down       # keeps the volume; add -v to delete the data
```

Compose reads `deploy/.env` because it sits next to the compose file. The volume is
named `kidney-health_kidney-data`. To build locally instead of pulling, uncomment the
`build:` block in `deploy/compose.yaml`.

**Start at boot.** `restart: always` only acts while Podman is running. On a reboot,
rootless containers come back if you enable Podman's restart unit for your user:

```bash
systemctl --user enable --now podman-restart.service
loginctl enable-linger "$USER"
```

For a proper service with health-based restarts and auto-update, use Quadlet (next).

---

## c. Quadlet: systemd service with autostart and auto-update

Quadlet turns `deploy/quadlet/kidney-health.container` into a systemd service. Needs
Podman 4.6 or newer (`podman --version`): Fedora 38+, Debian 13, Ubuntu 24.04, RHEL 9.3+.

```bash
mkdir -p ~/.config/containers/systemd
cp deploy/quadlet/kidney-health.container deploy/quadlet/kidney-health.volume ~/.config/containers/systemd/
cp deploy/.env.example ~/.config/containers/systemd/kidney-health.env
chmod 600 ~/.config/containers/systemd/kidney-health.env
$EDITOR ~/.config/containers/systemd/kidney-health.env      # optional USDA_API_KEY / APP_PASSWORD

systemctl --user daemon-reload                 # generates kidney-health.service + kidney-health-volume.service
systemctl --user start kidney-health.service
systemctl --user status kidney-health.service
loginctl enable-linger "$USER"                 # start at boot, keep running after logout
```

`kidney-health.env` must exist even if empty. Logs: `journalctl --user -u kidney-health -f`.
Quadlet units are not `enable`d; the `[Install] WantedBy=default.target` line makes them
start at boot once linger is on. If `systemctl --user start` says the unit does not exist,
run the generator by hand to see the parse error:
`/usr/libexec/podman/quadlet -user -dryrun` (Debian/Ubuntu: `/usr/lib/podman/quadlet`).

The data lives in the Podman volume `systemd-kidney-health`:

```bash
podman volume inspect systemd-kidney-health --format '{{.Mountpoint}}'
```

**Auto-update.** The unit carries `AutoUpdate=registry`, so:

```bash
podman auto-update --dry-run                              # what would change
podman auto-update                                        # pull + restart if the image changed
systemctl --user enable --now podman-auto-update.timer    # do that daily (00:00 by default)
```

Podman rolls back to the previous image when the restarted unit fails to become active.
`:latest` follows every merge to `main`; for calmer upgrades change `Image=` to a release
tag such as `ghcr.io/ksullivan86/kidney-health:0.2` and `systemctl --user daemon-reload &&
systemctl --user restart kidney-health`. Back up before upgrades regardless, see
[Upgrading](#h-upgrading).

**Rootful variant.** Put the three files in `/etc/containers/systemd/` and drop every
`--user`; the volume is then under `/var/lib/containers/storage/volumes/`.

---

## d. Talos Kubernetes with kustomize

The base in `deploy/k8s/` creates a namespace, a PVC, a single-replica Deployment
(`Recreate`), a ClusterIP Service on port 80 and an Ingress. It satisfies the Pod Security
"restricted" profile, which the namespace opts into (Talos enforces "baseline"
cluster-wide by default; "restricted" is stricter, and the Deployment complies).

```
deploy/k8s/
  kustomization.yaml       resources list + image tag pin
  namespace.yaml           kidney-health, PSA labels
  pvc.yaml                 1 Gi ReadWriteOnce            <- choose storageClassName
  deployment.yaml          uid 10001, probes on /healthz, resources, Secret envFrom (optional)
  service.yaml             ClusterIP :80 -> :8000
  ingress.yaml             host + optional cert-manager / Authelia annotations   <- set host
  httproute.example.yaml   Gateway API alternative, not applied by default
  secret.example.yaml      USDA_API_KEY / APP_PASSWORD, not applied by default
```

Prerequisites: `talosctl kubeconfig` done, `kubectl get nodes` works, a StorageClass
exists (`kubectl get sc`), and an ingress controller or Gateway is installed.

### 1. Pick storage

Edit `deploy/k8s/pvc.yaml` and set `storageClassName`, or leave it unset to use the
cluster default. On Talos the usual choices are:

| StorageClass | Fits when | Notes |
|---|---|---|
| `local-path` (rancher local-path-provisioner) | one node, or you accept the pod being tied to one node | hostPath under `/var/local-path-provisioner`; on Talos the provisioner's namespace needs the `privileged` PSA label and a kubelet extra mount for that path. Pin the pod with the `nodeSelector` comment in `deployment.yaml`. Fastest to set up. |
| `longhorn` | 2+ nodes, want replicas and snapshots | Talos needs the `iscsi-tools` and `util-linux-tools` system extensions and a `/var/lib/longhorn` kubelet mount. Snapshots/backups of the volume are a bonus. |
| `rook-ceph-block` (Rook-Ceph RBD) | you already run Ceph | Needs raw disks. Name is your CephBlockPool StorageClass. Solid, heavier. |
| `mayastor-*` (OpenEBS Mayastor) | you already run Mayastor | Needs hugepages per node; create a StorageClass (`repl: "1"` or `"3"`) and use its name. |
| `openebs-hostpath` | like local-path | Same single-node caveats. |
| NFS (`nfs-csi`) | avoid | SQLite relies on file locking that NFS implements poorly. |

The database is a few megabytes; `1Gi` is already generous. Replication does not replace
backups: a replicated volume faithfully replicates a corrupted file. Do section (e).

### 2. Apply the base

```bash
kubectl apply -k deploy/k8s
kubectl -n kidney-health get pods,pvc,svc,ingress
kubectl -n kidney-health logs deploy/kidney-health
```

Expected log lines: `database schema migrated to version N` (first start only) and
`database /data/kidney.db ready; builtin foods: imported`. A pod stuck in `Pending`
almost always means the PVC is unbound: `kubectl -n kidney-health describe pvc
kidney-health-data`.

Quick check without an Ingress:

```bash
kubectl -n kidney-health port-forward svc/kidney-health 8000:80
curl -s http://localhost:8000/healthz
```

### 3. Secret for `USDA_API_KEY` / `APP_PASSWORD` (optional)

The Deployment references a Secret named `kidney-health` with `optional: true`, so the
pod runs without it (no USDA search, no password). To set either value:

```bash
kubectl -n kidney-health create secret generic kidney-health \
  --from-literal=USDA_API_KEY='your-key' \
  --from-literal=APP_PASSWORD='a long passphrase'
kubectl -n kidney-health rollout restart deploy/kidney-health     # env is read at start
```

Or copy `deploy/k8s/secret.example.yaml` outside the repository, fill it in and
`kubectl apply -f` it. Do not commit the filled-in file. Rotate the same way.

### 4. Ingress or Gateway HTTPRoute

**Ingress** (default): in `deploy/k8s/ingress.yaml` change `kidney.home.example` to your
hostname and `ingressClassName: nginx` to your controller (`traefik`, `cilium`, ...).
The app must be served at the root of a hostname, not under a sub-path: the frontend
calls `/api/...` with absolute paths.

**TLS with cert-manager**: uncomment the `cert-manager.io/cluster-issuer` annotation and
the `spec.tls` block; cert-manager then creates `kidney-health-tls`. For a hostname that
is not reachable from the internet use a DNS-01 solver (Cloudflare, Route53, ...) or a
cert-manager `CA` ClusterIssuer with your own root certificate installed on the phone.
Letting the browser store a Basic-auth password over plain HTTP on anything but a trusted
LAN is a bad idea, so get TLS working before setting `APP_PASSWORD` on a public hostname.

**Gateway API** instead: edit `deploy/k8s/httproute.example.yaml` (`parentRefs` to your
Gateway, `hostnames`), add it to `resources:` in `kustomization.yaml` and remove
`ingress.yaml`. TLS is configured on the Gateway listener, not on the route, and the
Gateway must allow routes from the `kidney-health` namespace
(`allowedRoutes.namespaces`). The route targets Service port 80.

### 5. Pin the image

`kustomization.yaml` has an `images:` entry. `newTag: latest` plus
`imagePullPolicy: Always` means `kubectl rollout restart` pulls whatever `main` is now.
For controlled upgrades set `newTag: "0.2.0"` (or `sha-1a2b3c4`) and `kubectl apply -k`.

---

## e. Backups and restore of `/data/kidney.db`

The database runs in WAL mode. While the app is running, the current state is
`kidney.db` **plus** whatever sits in `kidney.db-wal` (present whenever a connection is open); copying `kidney.db` alone can lose the most recent
entries or produce an inconsistent file. Use one of:

1. SQLite's online backup (safe while running; preferred), or
2. stop the app, then copy the files.

The image has no `sqlite3` command-line tool, but Python's `sqlite3` module does the
same thing. The one-liner used below:

```python
import sqlite3; s=sqlite3.connect('/data/kidney.db'); d=sqlite3.connect('/data/backup.db'); s.backup(d); d.close(); s.close()
```

A second, human-readable safety net is the CSV export in the Trends view
(`GET /api/log/export.csv?start=...&end=...`); it holds the log entries but not the
profile, targets, saved meals or custom foods.

### Podman: online backup

```bash
podman exec kidney-health python -c "import sqlite3; s=sqlite3.connect('/data/kidney.db'); d=sqlite3.connect('/data/backup.db'); s.backup(d); d.close(); s.close()"
podman cp kidney-health:/data/backup.db "./kidney-$(date +%F).db"
podman exec kidney-health rm /data/backup.db
```

With the `sqlite3` CLI on the host and a rootless named volume (the files are owned by a
sub-uid, so wrap it in `podman unshare`):

```bash
M=$(podman volume inspect kidney-data --format '{{.Mountpoint}}')     # systemd-kidney-health for Quadlet
podman unshare sqlite3 "$M/kidney.db" ".backup '$PWD/kidney-$(date +%F).db'"
```

### Podman: stop and copy

```bash
podman stop kidney-health          # or: systemctl --user stop kidney-health
podman volume export kidney-data -o "kidney-data-$(date +%F).tar"   # whole volume as a tar
podman start kidney-health         # or: systemctl --user start kidney-health
```

Put either command in a cron job or a systemd timer and copy the files off the host.

### Kubernetes

```bash
NS=kidney-health
kubectl -n $NS exec deploy/kidney-health -- python -c "import sqlite3; s=sqlite3.connect('/data/kidney.db'); d=sqlite3.connect('/data/backup.db'); s.backup(d); d.close(); s.close()"
kubectl -n $NS exec deploy/kidney-health -- cat /data/backup.db > "kidney-$(date +%F).db"
kubectl -n $NS exec deploy/kidney-health -- rm /data/backup.db
```

(`kubectl cp` works too; the image contains `tar`.) Longhorn or Ceph volume snapshots
are a fine addition but are crash-consistent, not application-consistent; keep the
`.backup` copies as the primary.

### Verify a backup

```bash
python3 -c "import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); print(c.execute('pragma integrity_check').fetchone()[0]); print(c.execute('select count(*) from log_entries').fetchone()[0], 'log entries')" kidney-2026-10-05.db
```

### Restore

Stop the app, replace the file, delete stale WAL files, fix ownership, start.

Podman, named volume:

```bash
podman stop kidney-health
M=$(podman volume inspect kidney-data --format '{{.Mountpoint}}')
podman unshare sh -c "rm -f '$M/kidney.db-wal' '$M/kidney.db-shm' && cp kidney-2026-10-05.db '$M/kidney.db' && chown 10001:10001 '$M/kidney.db'"
podman start kidney-health
```

(`podman volume import kidney-data kidney-data-2026-10-05.tar` restores a tar made with
`volume export`.) Bind mount: same, with the directory path instead of `$M`; rootful or
Docker: `sudo chown 10001:10001` without `podman unshare`.

Kubernetes: scale to zero, mount the PVC in a throwaway pod (the app image itself, so
it already runs as uid 10001 and passes the restricted PSA), copy the file in, scale up.

```bash
NS=kidney-health
kubectl -n $NS scale deploy/kidney-health --replicas=0
kubectl -n $NS apply -f - <<'EOF'
apiVersion: v1
kind: Pod
metadata:
  name: kidney-restore
  namespace: kidney-health
spec:
  restartPolicy: Never
  securityContext:
    runAsNonRoot: true
    runAsUser: 10001
    runAsGroup: 10001
    fsGroup: 10001
    seccompProfile: {type: RuntimeDefault}
  containers:
    - name: shell
      image: ghcr.io/ksullivan86/kidney-health:latest
      command: ["sleep", "infinity"]
      securityContext:
        allowPrivilegeEscalation: false
        capabilities: {drop: ["ALL"]}
      volumeMounts: [{name: data, mountPath: /data}]
  volumes:
    - name: data
      persistentVolumeClaim: {claimName: kidney-health-data}
EOF
kubectl -n $NS wait --for=condition=Ready pod/kidney-restore --timeout=120s
kubectl -n $NS exec kidney-restore -- rm -f /data/kidney.db-wal /data/kidney.db-shm
kubectl -n $NS cp kidney-2026-10-05.db kidney-restore:/data/kidney.db
kubectl -n $NS delete pod kidney-restore
kubectl -n $NS scale deploy/kidney-health --replicas=1
```

After any restore, check `curl .../healthz` and the startup log; if the backup is from an
older release the schema migrates forward automatically on start.

---

## f. Enabling USDA lookups

Without a key the app works fully from its 395 builtin foods plus whatever you add by
hand; "Search USDA" is hidden and `GET /api/foods/usda/search` answers
`503 {"detail":"USDA_API_KEY not configured"}`.

1. Get a free key: <https://fdc.nal.usda.gov/api-key-signup> (arrives by e-mail at once).
   Your key allows 1,000 requests per hour; `DEMO_KEY` works for a quick test but is
   limited to 30 requests per hour and 50 per day.
2. Set `USDA_API_KEY`:
   * `podman run`: `-e USDA_API_KEY=...`
   * compose: `USDA_API_KEY=...` in `deploy/.env`, then `up -d` again
   * Quadlet: `USDA_API_KEY=...` in `~/.config/containers/systemd/kidney-health.env`, then
     `systemctl --user restart kidney-health`
   * Kubernetes: the Secret in section d.3, then `rollout restart`
3. Reload the page: the Add view shows "Search USDA". Imported foods get `source: usda`
   and a 100 g serving unless USDA supplies a household portion.

The server (not the browser) calls `https://api.nal.usda.gov/fdc/v1/...`, so only the
host/cluster needs egress to `api.nal.usda.gov` on 443. Blocked egress shows up as
`502 USDA request failed: ConnectError`; a wrong key as `503 USDA API key was rejected`.

---

## g. Reverse proxy, Authelia or `APP_PASSWORD`

The app speaks plain HTTP on 8000 and has one optional protection: `APP_PASSWORD`.
Pick **one** of the two models.

### Model 1: `APP_PASSWORD` (built-in Basic auth)

Set the variable and every page and API call demands HTTP Basic auth, realm
`kidney-health`, any username, that password (constant-time comparison). `/healthz` stays
open for probes and reveals only the food count. Browsers remember the credentials until
closed; there is no logout. Fine for one person on a home LAN, or behind a TLS-terminating
proxy on the internet. Unset or empty means no auth at all, so never publish port 8000
to the internet without it.

### Model 2: reverse proxy with its own login (Authelia, Authentik, Caddy basic_auth...)

Leave `APP_PASSWORD` empty and let the proxy authenticate. The image starts uvicorn with
`--proxy-headers --forwarded-allow-ips=*`, so client IPs and the `https` scheme are taken
from `X-Forwarded-For` / `X-Forwarded-Proto` **from any source**. That is convenient
behind a proxy and dangerous without one: when using this model, bind the container to
localhost (`-p 127.0.0.1:8000:8000`, `PublishPort=127.0.0.1:8000:8000`) or keep it on an
internal network so only the proxy can reach it. Serve the app at the root of its own
hostname (no sub-path).

Caddy (automatic TLS):

```caddyfile
kidney.home.example {
    reverse_proxy 127.0.0.1:8000
    # Authelia forward auth, if you run it:
    # forward_auth authelia:9091 {
    #     uri /api/authz/forward-auth
    #     copy_headers Remote-User Remote-Groups Remote-Email Remote-Name
    # }
}
```

nginx:

```nginx
server {
    listen 443 ssl;
    server_name kidney.home.example;
    # ssl_certificate ...; ssl_certificate_key ...;
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Kubernetes with ingress-nginx: `deploy/k8s/ingress.yaml` carries commented annotations
for Authelia forward-auth and for nginx's own htpasswd Basic auth; uncomment one block.
Authelia 4.38+ exposes `/api/authz/forward-auth`; older releases use `/api/verify`.

Running both models at once makes the browser answer two different Basic-auth prompts
and is not recommended.

---

## h. Upgrading

1. **Back up first** (section e). The schema migrates forward automatically on start
   (`app/db.py` adds missing columns and tables, never removes any) and logs
   `database schema migrated to version N`. Rolling *back* to an older image after a
   migration is not supported; restore the backup instead.
2. Pull and restart:
   * `podman run`: `podman pull ghcr.io/ksullivan86/kidney-health:latest`, then
     `podman stop kidney-health && podman rm kidney-health` and the same `podman run`
     command as before (the named volume keeps the data).
   * compose: `podman-compose -f deploy/compose.yaml pull && podman-compose -f deploy/compose.yaml up -d`
   * Quadlet: `podman auto-update` (or wait for the timer). To move to a specific release,
     edit `Image=` in the `.container` file, `systemctl --user daemon-reload`,
     `systemctl --user restart kidney-health`.
   * Kubernetes: change `newTag` in `deploy/k8s/kustomization.yaml` and `kubectl apply -k
     deploy/k8s`; with `latest`, `kubectl -n kidney-health rollout restart deploy/kidney-health`.
3. Check `/healthz` and the startup log. New builtin foods (a new `data/foods.json`
   version) are upserted on the first start; your custom foods and log are untouched.

Tag choice: `latest` is every merge to `main`; `0.2` follows patch releases of 0.2;
`0.2.0` never changes. Release tags are created by pushing a `v0.2.0` git tag.

---

## i. ARM homelab builds

The published image is a manifest list for **linux/amd64 and linux/arm64**, so
`podman pull ghcr.io/ksullivan86/kidney-health:latest` picks the right one on a
Raspberry Pi 4/5 or other 64-bit ARM board (Talos also runs on arm64). Nothing to do.

**Build on the ARM device itself** (a Pi 4 takes two to three minutes; all dependencies
have aarch64 wheels, so no compiler is needed):

```bash
podman build -f deploy/Containerfile -t kidney-health:local .
```

**Cross-build from an x86 machine** with QEMU user emulation:

```bash
sudo dnf install qemu-user-static          # Fedora; Debian/Ubuntu: apt install qemu-user-static binfmt-support
podman build --platform linux/arm64 -f deploy/Containerfile -t kidney-health:arm64 .

# or a multi-arch manifest pushed to your own registry:
podman build --platform linux/amd64,linux/arm64 --manifest registry.home.example/kidney-health:local -f deploy/Containerfile .
podman manifest push --all registry.home.example/kidney-health:local
```

32-bit ARM (`armv7`, e.g. a Pi 3 or a Pi running a 32-bit OS) is not published:
`uvicorn[standard]` pulls in `uvloop` and `httptools`, which have no armv7 wheels and
would need a compiler. Use a 64-bit OS on those boards.

CI (`.github/workflows/ci.yml`) builds the arm64 half under QEMU on GitHub's amd64
runners, which is why the image job is allowed up to an hour.

---

## j. Troubleshooting

**`unable to open database file`, `attempt to write a readonly database`,
`PermissionError: /data`** – the volume is not writable by uid 10001.

* Rootless Podman, bind mount: `podman unshare chown -R 10001:10001 /path/on/host`
  (or run with `--userns=keep-id:uid=10001,gid=10001`).
* Rootful Podman / Docker: `sudo chown -R 10001:10001 /path/on/host`.
* Named volumes normally need nothing: Podman copies the image's `/data` ownership into
  an empty volume on first start. If an older container created the volume as root,
  fix it with `podman unshare chown -R 10001:10001 "$(podman volume inspect NAME --format '{{.Mountpoint}}')"`.
* SELinux hosts: add `:Z` to the bind mount, or `ausearch -m avc -ts recent` will show the denial.
* Kubernetes: `fsGroup: 10001` in the Deployment handles CSI volumes (Longhorn, Ceph,
  Mayastor). hostPath-style classes ignore fsGroup; local-path creates its directory
  world-writable so it still works. For any other hostPath volume, chown the directory
  on the node to 10001 (on Talos: a one-off privileged pod in a non-restricted namespace,
  since there is no SSH).

**Health check failing / pod restarting** – the probe is `GET /healthz` on 8000 inside
the container, run with Python because the image has no curl:

```bash
podman healthcheck run kidney-health && echo healthy
podman exec kidney-health python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/healthz').read())"
kubectl -n kidney-health describe pod -l app.kubernetes.io/name=kidney-health   # Events section
```

The first start imports 395 foods; on a slow SD card that can take longer than the
15 s start period / 5 s readiness delay. Raise `HealthStartPeriod` (Quadlet),
`start_period` (compose) or `initialDelaySeconds` (Kubernetes). Also check
`podman logs kidney-health` for a Python traceback.

**Every page returns 401** – `APP_PASSWORD` is set (any username, that password).
`/healthz` is exempt by design, so a 200 there and a 401 everywhere else means auth is
working as intended. An empty value disables auth.

**Wrong client IP or `http://` links behind a proxy** – the proxy must send
`X-Forwarded-For` and `X-Forwarded-Proto` (examples in section g). The container trusts
those headers from all sources, so make sure port 8000 is reachable only by the proxy.

**App not reachable from the phone** – open the port on the host firewall
(`sudo firewall-cmd --add-port=8000/tcp --permanent && sudo firewall-cmd --reload`, or
`sudo ufw allow 8000/tcp`), use the host's LAN IP, and confirm `podman port kidney-health`
shows `0.0.0.0:8000` rather than `127.0.0.1:8000`.

**Pod `Pending`** – `kubectl -n kidney-health describe pvc kidney-health-data`: a
mistyped `storageClassName`, no default StorageClass, or (with local-path) a
`nodeSelector` that matches no node. A previous pod still holding the RWO volume resolves
itself within a minute thanks to the `Recreate` strategy.

**Pod rejected by Pod Security** – the namespace enforces `restricted`. Any extra
container you add (debug pods, init containers) must run as non-root with
`allowPrivilegeEscalation: false`, `capabilities.drop: [ALL]` and
`seccompProfile.type: RuntimeDefault`; the restore pod in section e is a template.

**`database is locked`** – two processes share one database. Run exactly one container
per volume and keep `replicas: 1`. The app waits up to 5 s for locks, which covers the
backup command.

**Data disappeared after `podman rm`** – the container used an anonymous volume. Check
`podman volume ls`; the data may still be in a volume with a random name. Always pass `-v`.

**`USDA_API_KEY not configured` / `USDA request failed`** – see section f; the second
message means the host or cluster cannot reach `api.nal.usda.gov`.

**Which version is running?** `podman inspect kidney-health --format '{{.ImageDigest}}'`
or `kubectl -n kidney-health get deploy kidney-health -o jsonpath='{.spec.template.spec.containers[0].image}'`,
and `GET /docs` shows the API version in the OpenAPI title.

Logs: `podman logs -f kidney-health`, `journalctl --user -u kidney-health -f`,
`kubectl -n kidney-health logs deploy/kidney-health -f`. Dates in the log are the dates
the browser sent, so the container's time zone does not matter.
