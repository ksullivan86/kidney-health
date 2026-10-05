# 01 · Rootless containers, image hardening and supply-chain security

| | |
|---|---|
| Status | Decision note, proposed for v0.3. No application code has been changed. |
| Date researched | 2026-10-05 |
| Scope | Rootless Podman and rootless Docker, the container image, runtime flags, Kubernetes on Talos, the GitHub Actions supply chain (GHCR image), app-level HTTP hardening, secrets handling, and a threat model for v0.3 |
| Out of scope | The auth and multi-user data model, the AI providers, barcode and food APIs, the PWA. Sibling notes in `docs/dev/research/` own those; this note only records the security requirements they must meet. TLS options for phones are in [`02-ios-pwa.md`](02-ios-pwa.md). |
| Re-verify | Action SHAs and base-image digests before every release (Dependabot does most of it). Podman, Docker, Talos and Kubernetes versions every six months. See [§8](#8-how-to-re-verify). |

Versions current on 2026-10-05: Podman **6.1.3**, Docker Engine **29.8.2**, RootlessKit **3.2.0**,
Talos **1.14.2**, Kubernetes **1.37** docs (Talos 1.13 supports up to 1.36), Cilium **1.20.2**,
CPython **3.14.8** (3.15.0 final slipped to the week of 2026-10-09), grype **0.120.0**,
cosign **3.1.3**.

---

## 1. Context

### 1.1 The ask

The owner wants the app to run on rootless Podman or Docker, so that a flaw in any component never
has root on the host. The app will be public. Homelab users will self-host it from a GHCR image on
Podman, Docker or Kubernetes (Talos). v0.3 adds features that raise the stakes:

* **Multi-user**, with API keys that an admin shares and keys that each user keeps private.
* **Outbound calls** to USDA, Open Food Facts and optional AI providers (OpenAI, a local Ollama, the
  owner's Hermes agent).
* **Camera and photo input**, plus a service worker for the PWA. Both need HTTPS (a secure context).
* **Health data for several people** in one SQLite file.

### 1.2 What exists today (v0.2), read from the repository

| Area | Today | Gap |
|---|---|---|
| `deploy/Containerfile` | `python:3.12-slim` (tag, no digest), multi-stage venv, `USER app` (10001), stdlib `HEALTHCHECK` | Code under `/app` is **owned by the app user**, so a compromised process can rewrite it. pip is in the venv and in the base image. The image has a shell, apt and perl. `CMD` passes `--forwarded-allow-ips=*`, so any client can spoof `X-Forwarded-For`/`-Proto`. |
| `deploy/compose.yaml` | `cap_drop: ALL`, `no-new-privileges` | `read_only` is commented out. Port bound on `0.0.0.0`. No memory or pids limits. Secrets come from env vars. |
| `deploy/quadlet/` | Rootless unit, `DropCapability=ALL`, `NoNewPrivileges=true`, health check, auto-update | No `ReadOnly=true`. `PublishPort=8000:8000` is on all interfaces, which **bypasses** any reverse-proxy login (Authelia). No limits. Secrets come from an EnvironmentFile. `docs/deployment.md` recommends `--userns=keep-id`, which is the weaker choice (§3.1). |
| `deploy/k8s/` | PSA `restricted` enforce + warn, `automountServiceAccountToken: false`, seccomp `RuntimeDefault`, drop ALL | `readOnlyRootFilesystem: false`. No NetworkPolicy. The default `ingress.yaml` targets **ingress-nginx, retired upstream in March 2026** (no more security fixes; [Kubernetes blog](https://kubernetes.io/blog/2025/11/11/ingress-nginx-retirement/)). `:latest` with `imagePullPolicy: Always`. |
| `.github/workflows/ci.yml` | Least-privilege `permissions`, PRs build without push, multi-arch publish | Actions pinned by **mutable tags** (`@v4`, `@v3`…). `actionlint` and `kubeconform` are fetched with `curl \| tar` and **no checksum**. `provenance: false`, `sbom: false`. No vulnerability gate, no signing, no CodeQL, no Dependabot. |
| Python deps | `requirements.txt` with ranges, no hashes | Builds are not reproducible. `uvicorn[standard]` pulls 6 extras the app never uses: `watchfiles`, `websockets`, `python-dotenv`, `PyYAML`, `uvloop`, `httptools`. |
| App | Optional HTTP Basic auth (constant-time compare). The USDA key is sent as an `X-Api-Key` header, which is good: it never appears in a URL or a log. | No security headers. `index.html` has an **inline `<script>`** (the theme bootstrap) and a `data:` favicon, so a strict CSP would break the page. FastAPI `/docs` loads Swagger from `cdn.jsdelivr.net`. No request-body size limit. Secrets come only from env vars. |
| Frontend | **Zero HTML sinks**: no `innerHTML`, `outerHTML`, `insertAdjacentHTML` or `document.write` in `app.js` or `index.html` (grep, 2026-10-05) | That makes Trusted Types enforcement close to free (§3.7). |

### 1.3 A constraint found during research: the repository is private

`GET https://api.github.com/repos/ksullivan86/kidney-health` returns `"private": true` (checked
2026-10-05). While it stays private on a Free or Pro plan:

* **GitHub artifact attestations are not available.** They work for public repos on every plan, but
  for private repos only on Enterprise Cloud
  ([actions/attest-build-provenance README](https://github.com/actions/attest-build-provenance)).
* **CodeQL code scanning needs GitHub Code Security** for private repos. It is free for public repos.
* **buildx records only `mode=min` provenance** by default for private repos (`mode=max` for public;
  [Docker docs](https://docs.docker.com/build/ci/github-actions/attestations/)).
* Keyless **cosign** signing writes the workflow identity, which includes the repo name, into the
  public Rekor transparency log.
* Anonymous `podman pull ghcr.io/ksullivan86/kidney-health` works only once the GHCR **package** is
  set to public.

The workflows below therefore gate the public-only steps on `!github.event.repository.private`. They
switch on by themselves when the repo goes public.

---

## 2. Threat model

### 2.1 Assets

| ID | Asset | Why it matters |
|---|---|---|
| A1 | **Health data**: CKD stage, dialysis schedule, diabetes type, weight, height, age, sex, every meal, targets | Special-category personal data. Disclosure harms privacy. The users are patients. |
| A2 | **Integrity of targets, thresholds and food data** | A tampered potassium target or food value can lead to an unsafe meal (for example hyperkalaemia on dialysis). This is a **safety** asset, not just a data asset. |
| A3 | **API keys**: USDA (free), OpenAI (costs money), Hermes or Ollama endpoints (may expose a tool-using agent) | Theft causes financial loss or misuse of the owner's agent. |
| A4 | **Credentials and sessions**: admin and user passwords, session cookies, `APP_PASSWORD`, `SECRET_KEY` | Account takeover leads to A1, A2 and A3. |
| A5 | **The published image and its tags** on GHCR | A malicious `:latest` reaches every homelab that auto-updates. |
| A6 | **The host** (the homelab server, the user's home directory, other containers) | A container escape must not land as root, or as the user's own UID. |
| A7 | **Backups** of `kidney.db` | They contain A1, A3 (encrypted) and A4 (hashes). |

### 2.2 Actors

| ID | Actor | Capability |
|---|---|---|
| T-NET | Internet attacker | Reaches the app only if it is exposed through a proxy or tunnel. Scans, sprays credentials, exploits known CVEs. |
| T-LAN | Device on the home LAN (a compromised IoT device, a guest) | Can reach published ports directly, sniff plain HTTP, try CSRF through a user's browser. |
| T-USR | Another household user, or a curious user on a shared instance | Holds a valid account. Tries to read another user's log, read the admin's shared keys, or overspend them. |
| T-DATA | Hostile upstream data: Open Food Facts product names and ingredients, AI responses | Injects markup or script (XSS), or prompt-injects the AI or a tool-using agent. |
| T-SC | Supply-chain attacker: a compromised PyPI package, GitHub Action, base image or maintainer token | Runs code in CI (steals `GITHUB_TOKEN` or OIDC tokens, pushes a malicious image) or inside the runtime image. Real precedents: the `tj-actions/changed-files` tag rewrite (March 2025) and the **Trivy compromise of March 2026**, in which 76 of 77 `aquasecurity/trivy-action` tags were force-pushed to secret-stealing commits ([Aqua advisory](https://www.aquasec.com/blog/trivy-supply-chain-attack-what-you-need-to-know), [Wiz](https://wiz.io/blog/trivy-compromised-teampcp-supply-chain-attack)). |
| T-ESC | An attacker who already has code execution in the container | Tries to escape to the host or move to other services (Kubernetes API, cloud metadata, LAN). |
| T-AI | Third-party AI provider | Receives whatever the app sends it. |
| T-DEV | A lost or stolen phone with the PWA installed | Holds a long-lived session and any cached data. |

### 2.3 Trust boundaries

```
 phone / PC browser ──(1) TLS──▶ reverse proxy (Caddy / Traefik / Gateway API / tailscale serve)
   untrusted input                optional forward-auth (Authelia), sets X-Forwarded-*, Remote-User
                                         │ (2) loopback or cluster network only
                                         ▼
                    ┌──────── kidney-health container ───────────────────────────────┐
                    │ uid 10001, rootless userns, caps dropped, NNP, seccomp,        │
                    │ read-only rootfs, tmpfs /tmp, memory and pids limits           │
                    │   /data (SQLite, the only writable path)                       │
                    │   /run/secrets (read-only files)                               │
                    └──(3) egress: api.nal.usda.gov, world.openfoodfacts.org, AI host┘
 CI (GitHub Actions) ──(4) OIDC, GITHUB_TOKEN──▶ GHCR image (signed, attested) ──(5) pull──▶ hosts
```

### 2.4 Threats and mitigations

The control IDs (C-…) are implemented in [§5](#5-recommendation) and tracked in [§7](#7-implementation-checklist).

| # | Threat (actor → asset) | Mitigations |
|---|---|---|
| 1 | T-ESC: a container escape gains root on the host or your UID (A6) | Rootless engine (**C-ROOTLESS**). Default subordinate-UID mapping, **not keep-id** (**C-USERNS**). Non-root UID 10001 with no setuid binaries and no shell (**C-IMAGE**). `--cap-drop=ALL`, `no-new-privileges`, default seccomp, SELinux `container_t` (**C-RUNTIME**). Optional `hostUsers: false` on Kubernetes (**C-K8S**). |
| 2 | T-ESC: a compromised process persists by rewriting app code | Code owned by root and not writable by 10001, plus a read-only rootfs (**C-IMAGE**, **C-RUNTIME**). |
| 3 | T-ESC: lateral movement to the Kubernetes API, cloud metadata or the LAN | `automountServiceAccountToken: false`. Default-deny NetworkPolicy with egress only to DNS and public :443 (or a Cilium FQDN allowlist) (**C-NETPOL**). |
| 4 | T-SC: a malicious dependency or base image | Hash-locked deps installed with `--require-hashes --only-binary=:all:` (**C-LOCK**). Base images pinned by digest. Minimal runtime with no pip, no shell and no package manager (**C-IMAGE**). Dependabot cooldown (**C-DEPBOT**). Grype gate (**C-SCAN**). |
| 5 | T-SC: a compromised GitHub Action steals secrets or pushes an image | Actions pinned by full commit SHA and checked with zizmor's impostor-commit audit (**C-PIN**). `permissions: {}` at the top of each workflow and per-job grants. Scanners run in a job with no write scopes. No `pull_request_target`. Downloaded tools checked against a SHA-256 (**C-CI**). |
| 6 | T-SC: a stolen maintainer token pushes a malicious `:latest` that auto-update deploys (A5) | Keyless cosign signature and SLSA provenance (**C-SIGN**). Docs tell users to track a minor tag (`:0.3`) or pin a digest after `cosign verify`. Tag and branch rulesets, immutable releases. |
| 7 | T-LAN: bypasses the proxy login by hitting `:8000` directly | Publish on `127.0.0.1` only (Podman/Docker), or NetworkPolicy ingress only from the Gateway namespace (**C-NETPOL**). The app accepts an identity header only from `TRUSTED_PROXIES` (**C-PROXY**). |
| 8 | T-LAN or T-NET: spoofs `X-Forwarded-For` or `-Proto` to dodge rate limits, fake HTTPS or forge `Remote-User` | Remove `--forwarded-allow-ips=*`. The app owns proxy-header handling and trusts only `TRUSTED_PROXIES` (**C-PROXY**). |
| 9 | T-LAN: sniffs credentials over plain HTTP | HTTPS via the reverse proxy is required for multi-user mode. Secure cookies and HSTS when the scheme is https (**C-HEADERS**; TLS options in note 02). |
| 10 | T-LAN or T-NET: CSRF through a logged-in browser (Basic auth credentials are sent cross-site automatically) | Reject unsafe methods unless `Sec-Fetch-Site` is `same-origin` (falling back to an `Origin` check). `SameSite=Lax` cookies. JSON-only API (**C-CSRF**). |
| 11 | T-DATA: XSS via product names or AI output (A1, A4) | Strict CSP with no inline script and `frame-ancestors 'none'`, Trusted Types `require-trusted-types-for 'script'`, and `textContent`-only rendering (**C-HEADERS**). AI output rendered as plain text. |
| 12 | T-DATA: prompt injection through food data into the **Hermes agent**, which may have tools (A3, A6) | Call a plain chat-completion endpoint with **no tools**. Never let AI output trigger writes. The rules engine checks every AI suggestion (owned by the AI note). |
| 13 | T-USR: reads another user's data or the admin's keys | Every query is scoped to the user id. Key fields are write-only: the API never returns a key, only `•••• last4`. Admin-shared keys are used server-side only. Each user has a quota on shared keys (owned by the multi-user note; requirements here). |
| 14 | T-USR, or a compromised admin account: SSRF through a configurable AI base URL (to `169.254.169.254`, the Kubernetes API or LAN admin panels) | Resolve, validate and pin every address; private, loopback and link-local targets only through the env-only `AI_PRIVATE_HOSTS` allowlist; user URLs https:443 to global addresses only ([note 04 R5](04-optional-ai.md)). Egress NetworkPolicy (**C-NETPOL**). |
| 15 | T-NET: denial of service through large bodies or photo uploads | `MAX_BODY_BYTES` limit, raw `image/jpeg` bodies capped at `MAX_IMAGE_BYTES` with a header dimension check (no multipart; note 03 R8, §10 S5), memory and pids limits (**C-LIMITS**). |
| 16 | Any actor: keys leak through env vars, logs or `podman inspect` (A3) | `*_FILE` secrets mounted read-only (**C-SECRETS**). Keys go in headers, never in URLs. Secrets are never logged. Stored user keys are encrypted with `SECRET_KEY` (**C-SECRETS**). |
| 17 | T-AI: health data sent to a third party (A1) | AI is off by default, with per-user opt-in and a consent text naming the provider. Send only the fields needed. Prefer local models (owned by the AI note). |
| 18 | T-DEV: a stolen phone (A1, A4) | Session idle timeout and logout with `Clear-Site-Data`. The service worker never caches `/api/*` (note 02). `Cache-Control: no-store` on the API (**C-HEADERS**). |
| 19 | Backups leak (A7) | Docs: encrypt backups (restic or borg), `0600`, keep `SECRET_KEY_FILE` outside the backup set where possible. |
| 20 | Tampered targets (A2) | Auth plus CSRF (above). Record `updated_by`/`updated_at` on profile and targets, show "last changed by … at …". The CSV export lets the dietitian review. |

**Accepted residual risks.** The single-container design keeps the database encryption key next to
the data, so encryption at rest only protects against leaks of the database file alone. A plain
`ipBlock 0.0.0.0/0:443` egress rule still allows exfiltration to any HTTPS host (Cilium FQDN rules
close this). Rootless Podman has no simple per-container egress allowlist. A kernel zero-day that
escapes a user namespace is out of scope.

---

## 3. Findings

### 3.1 Rootless Podman

* **Requirements.** Entries in `/etc/subuid` and `/etc/subgid` (≥ 65 536 IDs; `usermod
  --add-subuids 100000-165535 --add-subgids 100000-165535 <user>`, then `podman system migrate`),
  plus `newuidmap`/`newgidmap`. Storage lives in `~/.local/share/containers/storage`
  ([rootless tutorial](https://github.com/containers/podman/blob/main/docs/tutorials/rootless_tutorial.md)).
* **The default rootless mapping is the safest simple choice for this app.** Under `--userns` (host,
  the default), your UID becomes container root (0), and container UID *n* ≥ 1 maps to *subuid_start
  + n − 1*. The app runs as container UID 10001, which is an **unprivileged subordinate UID on the
  host**: not root and not you. Even a full escape lands as a UID that owns nothing but this
  container's files ([podman-run `--userns`](https://github.com/containers/podman/blob/main/docs/source/markdown/options/userns.container.md)).
* **`keep-id` weakens that.** `--userns=keep-id:uid=10001,gid=10001` maps **your own host UID** to
  10001, so the app process *is* you on the host. An escape can then read `~/.ssh`, other
  containers' storage and the Hermes agent's keys. It is convenient for bind mounts, but for this app
  use it only in development. `docs/deployment.md` currently recommends it, so correct that.
* **`auto` and `nomap`.** `--userns=auto` gives each container its own slice of your subuid range and
  leaves your UID unmapped. `nomap` maps everything except your UID. Both add isolation between
  containers that share one account. The catch is that ownership no longer matches the
  `podman unshare chown` recipes in the docs. Offer `UserNS=auto` with a volume `:U` as an
  "advanced" option. Do not make it the default.
* **Volume ownership.** A named volume that starts empty is populated from the image's `/data`
  (owner and mode included), so no chown is needed. For a **bind mount**, either
  `podman unshare chown -R 10001:0 DIR` or the `:U` option, which chowns the source recursively to
  the container UID on every start; `/data` is tiny, so the cost is negligible. Never use `:U` or
  `:Z` on `$HOME` or a system directory.
* **SELinux** (Fedora, RHEL, Alma). Rootless containers run as `container_t`. Bind mounts need `:Z`
  (a private label). Named volumes are labelled automatically. Never use `--security-opt
  label=disable`.
* **Ports.** Rootless containers can bind ports ≥ 1024 with no sysctl. The app listens on 8000.
  Publish it as `127.0.0.1:8000:8000` when the reverse proxy runs on the same host.
* **Networking: pasta.** pasta has been the rootless default since **Podman 5.0**. **Podman 6.0
  (2026-06-24) removed slirp4netns**, CNI, cgroups v1, BoltDB and the iptables backend
  ([Fedora change Podman6](https://fedoraproject.org/wiki/Changes/Podman6),
  [linuxiac](https://linuxiac.com/podman-6-0-lands-with-breaking-changes-amd-gpus-support/)).
  Since **5.3**, `host.containers.internal` resolves to `169.254.1.2`, which pasta maps to the host.
  That is how the container reaches an Ollama or Hermes server running on the same host
  ([Podman blog](https://blog.podman.io/2024/10/podman-5-3-changes-for-improved-networking-experience-with-pasta/)).
  Before you trust any proxy, check what source address the app sees. **Corrected in the security
  review (§10 S2):** with Podman's default pasta options, a connection from the host's loopback to
  a published port does **not** arrive as loopback. passt(1): "Connections from loopback to
  loopback on the host will appear to come from the target namespace's public address within the
  guest" (Podman leaves `--host-lo-to-ns-lo` off because of CVE-2021-20199). Connections from other
  machines keep their real source address. So a Caddy on the same host shows up as the container's
  own address, and `127.0.0.1` in `TRUSTED_PROXIES` matches nothing. Log `request.client` once and
  use the address you see ([passt(1)](https://passt.top/passt/plain/passt.1)).
* **cgroup v2 limits in rootless mode.** systemd delegates only the **memory and pids** controllers
  to users by default. `--cpus` and io limits need `/etc/systemd/system/user@.service.d/delegate.conf`
  with `Delegate=cpu cpuset io memory pids`
  ([rootlesscontaine.rs](https://rootlesscontaine.rs/getting-started/common/cgroup2/)). Ship memory
  and pids limits by default; document CPU as optional.
* **Quadlet keys and the Podman version that added them** (from Podman release notes):
  `UserNS=`, `Tmpfs=` and `Secret=` 4.5. `PidsLimit=` 4.7. `ReadOnlyTmpfs=` 4.8 (default `true`
  with `ReadOnly=true`: tmpfs on `/tmp`, `/var/tmp`, `/run`, `/dev/shm`). `Notify=healthy` 5.0.
  **`Memory=` 5.5.** Ubuntu 24.04 LTS ships Podman 4.9, so the unit uses `PodmanArgs=--memory=…`,
  which works on 4.9 through 6.1, and keeps `Notify=healthy` optional
  ([podman-systemd.unit(5)](https://docs.podman.io/en/latest/markdown/podman-systemd.unit.5.html)).
* **Secrets.** `Secret=name,type=mount,target=…,uid=10001,gid=10001,mode=0400` mounts the secret at
  `/run/secrets/<target>` with exactly the ownership the app needs. `type=env` also exists, but env
  vars leak more easily ([`--secret`](https://github.com/containers/podman/blob/main/docs/source/markdown/options/secret.md)).
  The default `file` driver stores secrets unencrypted (base64) under your home directory with
  `0600`. That is no worse than an env file, and the `pass` driver is available if you want more.
* **Image signature enforcement does not work for us.** `containers-policy.json(5)` `sigstoreSigned`
  with `fulcio` **requires `subjectEmail`** (or `subjectHostname`). GitHub Actions certificates
  carry a workflow URI, not an email, so Podman cannot enforce GitHub-keyless signatures at pull or
  auto-update time
  ([containers-policy.json.5](https://github.com/containers/container-libs/blob/main/image/docs/containers-policy.json.5.md)).
  Users verify with `cosign`/`gh` before they pin a digest.

### 3.2 Rootless Docker

* **Setup.** Install `uidmap` and `docker-ce-rootless-extras`, then run
  `dockerd-rootless-setuptool.sh install` as the user. It creates
  `~/.config/systemd/user/docker.service` and the `rootless` context, with the socket at
  `unix:///run/user/$UID/docker.sock`. Run `sudo loginctl enable-linger $USER` so it starts at boot.
  `docker info` must list `name=rootless` under Security Options
  ([Docker rootless](https://docs.docker.com/engine/security/rootless/)).
* **Limitations that matter here**
  ([troubleshoot](https://docs.docker.com/engine/security/rootless/troubleshoot/)):
  * cgroup limits need **cgroup v2 + systemd**, otherwise `--memory` and `--pids-limit` are
    silently ignored.
  * **No AppArmor.**
  * overlay2 needs kernel ≥ 5.11.
  * Ports < 1024 need `net.ipv4.ip_unprivileged_port_start`.
  * **Source IP is not propagated by default.** Every client appears to come from the RootlessKit
    gateway. Fix it with RootlessKit ≥ 3.0 plus `{"userland-proxy": false}`, or with
    `DOCKERD_ROOTLESS_ROOTLESSKIT_NET=pasta` + `DOCKERD_ROOTLESS_ROOTLESSKIT_PORT_DRIVER=implicit`.

  **Security consequence:** without source-IP propagation, "trust the proxy's IP" equals "trust
  everyone". Under rootless Docker, publish only on `127.0.0.1` and leave `TRUSTED_PROXIES` at the
  loopback default.
* `--user`, `--read-only`, `--tmpfs`, `--cap-drop`, `--security-opt no-new-privileges` behave
  exactly as on Podman. Docker's `--read-only` does **not** add `/tmp` automatically, so pass
  `--tmpfs /tmp`.

### 3.3 The base image

Data below was measured on 2026-10-05 with **grype 0.120.0** (fresh database), `linux/amd64`, all
images pulled anonymously from their registries. Files are in the scratchpad (`scan-*.json`).

| Image (index digest, 2026-10-05) | Python | Size (uncompressed) | Findings (C / H / M / L / Neg) | Fix available | Notes |
|---|---|---|---|---|---|
| `python:3.12-slim-trixie` (`02108f5d…`) | 3.12.15 | ~128 MB | 174 (0 / 56 / 60 / 11 / 47) | 1 H, 11 M | Current base family. 3.12 is security-only until 2028-10. |
| `python:3.14-slim-trixie` (`c3e521df…`) | 3.14.8 | 127.9 MB | 164 (0 / 56 / 52 / 10 / 46) | 1 H (pcre2), 3 M | 48 of the 56 High are Debian `wont-fix` in util-linux, `login`, `mount`, `perl-base` and glibc, none of which the app uses. Has `/bin/sh`, apt and pip (3.12+ images ship pip but no setuptools or wheel). |
| `gcr.io/distroless/python3-debian13:nonroot` | **3.13.5** (Debian) | 59.9 MB | 157 (**4** / 39 / 55 / 14 / 45) | 0 | The Python version is whatever Debian ships (3.13, security-only upstream). The builder must be `debian:13` + `python3-venv` so paths match. amd64, arm64, riscv64 ([distroless](https://github.com/GoogleContainerTools/distroless)). |
| `cgr.dev/chainguard/python:latest` (`3de78d56…`) / `:latest-dev` (`a876b100…`) | 3.14.8 | **67.6 MB** | **8 (0 / 0 / 6 / 2 / 0)** | 0 | Wolfi (glibc, so manylinux wheels work). Runtime has no shell and no pip. `User=65532`, `Entrypoint=["/usr/bin/python"]`. amd64 + arm64. The **free tier offers only `:latest`/`:latest-dev`**; version tags are paid. Old digests stay pullable ([Chainguard](https://images.chainguard.dev/directory/image/python/overview), [tags & EOL](https://support.chainguard.dev/hc/en-us/articles/49563564450075-How-Chainguard-Image-Tags-Versions-and-EOL-Work)). |
| `dhi.io/python:3.14` / `:3.14-dev` (Docker Hardened Images) | 3.14.x | n/a | not scanned (login required) | n/a | **Apache-2.0** since 2025-12-17. Debian 13 base, no shell, `User=65532`, SLSA L3 provenance, VEX, version tags free. **But every pull needs `docker login dhi.io`**, so CI needs Docker Hub secrets and **fork PRs cannot build** ([Docker](https://www.docker.com/blog/docker-hardened-images-for-every-developer/), [DHI use](https://docs.docker.com/dhi/how-to/use/)). |

Other facts that shape the choice:

* **Python support** ([devguide](https://devguide.python.org/versions/)): 3.14 is the only bugfix
  branch (security fixes to 2030-10). 3.12 and 3.13 are security-only. 3.15.0 is imminent.
  Recommendation: **runtime 3.14**, CI tests 3.12 (the `requires-python` floor stays `>=3.11` for
  source users) and 3.14.
* **Docker Hub rate limits.** During this research anonymous Docker Hub requests began returning
  **HTTP 429** after a handful of pulls. GHCR and cgr.dev did not.
* **Image entrypoints.** Chainguard, distroless and DHI set `ENTRYPOINT` to the interpreter, so the
  Containerfile must set its own `ENTRYPOINT`.
* **Dependabot** updates only **literal** `FROM image:tag@sha256:…` lines. `FROM ${ARG}` is not
  parsed ([dependabot-core file_parser.rb](https://github.com/dependabot/dependabot-core/blob/main/docker/lib/dependabot/docker/file_parser.rb)).
  It does detect `Containerfile` (`/dockerfile|containerfile/i`). So "one Containerfile with a base
  build-arg" would leave the digests stale. Use one file per base family instead.
* **Docker Official Images already ship in-index attestation manifests** (`unknown/unknown` platform
  entries; observed in the `python:3.14-slim-trixie` index), and Podman pulls them every day. The old
  reason in `ci.yml` for `provenance: false` ("confuses podman pull/auto-update") no longer holds.
  The `unknown/unknown` rows in the GHCR UI are cosmetic.

### 3.4 Runtime flags

| Flag | Podman | Docker | Kubernetes | Notes |
|---|---|---|---|---|
| Drop capabilities | `--cap-drop=all` / `DropCapability=all` | `--cap-drop=ALL` | `capabilities.drop: [ALL]` | The app needs none (port 8000 > 1024). |
| No privilege escalation | `--security-opt=no-new-privileges` / `NoNewPrivileges=true` | same | `allowPrivilegeEscalation: false` | |
| Seccomp | default profile, automatic | default, automatic | `seccompProfile: RuntimeDefault` | Never `unconfined`. A custom profile is not worth maintaining for this app. |
| Read-only rootfs | `--read-only` (adds tmpfs on `/tmp`, `/var/tmp`, `/run`, `/dev/shm` because `--read-only-tmpfs` defaults to true) | `--read-only --tmpfs /tmp:rw,noexec,nosuid,nodev,size=64m` | `readOnlyRootFilesystem: true` + `emptyDir` on `/tmp` | The app writes only `/data` (SQLite + WAL/SHM). SQLite's own temp files go to `/tmp`. Photo uploads are raw bodies held in memory (≤ `MAX_IMAGE_BYTES`), never spooled (security review). |
| Memory | `--memory=512m` | `--memory=512m` | `limits.memory: 512Mi` | Rootless: needs cgroup v2 (memory is delegated by default). |
| PIDs | `--pids-limit=128` (Podman default 2048) | `--pids-limit=128` | (kubelet podPidsLimit) | FastAPI runs sync endpoints in an AnyIO thread pool of **40 threads**, and threads count as PIDs. 64 would be tight; 128 is safe. |
| SELinux | `:Z` on bind mounts | `:Z` | n/a | Fedora, RHEL, Alma. |
| User | image `USER 10001:10001` | same | `runAsUser/runAsGroup: 10001` | Also works under an arbitrary UID with GID 0 (§5.1). |

### 3.5 Kubernetes on Talos

* **PSA.** Talos enforces `baseline` cluster-wide and audits/warns on `restricted` (exempting
  `kube-system`) ([Talos pod security](https://docs.siderolabs.com/kubernetes-guides/security/pod-security)).
  The namespace opts into `enforce: restricted`. The `restricted` profile requires
  `allowPrivilegeEscalation: false`, `runAsNonRoot: true`, `runAsUser ≠ 0`, seccomp
  `RuntimeDefault`/`Localhost`, `capabilities.drop: [ALL]` (add only `NET_BIND_SERVICE`), and
  volume types limited to configMap, csi, downwardAPI, emptyDir, ephemeral, **persistentVolumeClaim**,
  projected and secret. **`readOnlyRootFilesystem` is not part of the profile.** Set it anyway
  ([PSS source](https://github.com/kubernetes/website/blob/main/content/en/docs/concepts/security/pod-security-standards.md)).
* **NetworkPolicy on Talos.** The default CNI (Flannel) **silently ignores NetworkPolicy** unless
  `kubeNetworkPoliciesEnabled: true` is set (Talos ≥ 1.13; on 1.14+ it lives in the
  `KubeFlannelCNIConfig` document) ([Talos Flannel](https://docs.siderolabs.com/kubernetes-guides/cni/flannel)).
  Vanilla NetworkPolicy cannot match **domain names**. An FQDN allowlist (api.nal.usda.gov …)
  needs Cilium `toFQDNs`.
* **User namespaces for pods.** `UserNamespacesSupport` is **GA in Kubernetes 1.36**
  ([feature gate](https://github.com/kubernetes/website/blob/main/content/en/docs/reference/command-line-tools-reference/feature-gates/UserNamespacesSupport.md)).
  `hostUsers: false` needs Linux ≥ 6.3, idmap-capable filesystems for every volume (ext4, xfs,
  btrfs, tmpfs; **not NFS**) and containerd ≥ 2.0. **Talos keeps user namespaces disabled by
  default**, so it needs a `SysctlConfig` with `user.max_user_namespaces: "11255"`
  ([Talos user namespaces](https://docs.siderolabs.com/kubernetes-guides/security/usernamespace)).
  Treat it as an optional overlay.
* **Other pod fields.** `supplementalGroupsPolicy: Strict` is beta and on by default since 1.33.
  It stops image `/etc/group` memberships from being merged in. The runtime must support it
  (containerd ≥ 2.0, which Talos ships); otherwise the kubelet rejects the pod. `enableServiceLinks: false` keeps
  other Services' env vars out of the pod.
* **Secrets.** Talos clusters created since 1.3 encrypt Secrets in etcd with **secretbox** by
  default. Mount them as files with `defaultMode: 0440` (the group is the `fsGroup`) rather than
  `envFrom`.
* **PodDisruptionBudget: do not add one.** With one replica, `minAvailable: 1` makes every eviction
  fail, so `talosctl upgrade` or `kubectl drain` hangs on this pod. A short outage during a node
  drain is acceptable for this app. `strategy: Recreate` already handles the SQLite lock.

### 3.6 Supply chain

* **Pin actions by full commit SHA.** GitHub calls it "the only way to use an action as an immutable
  release". Make sure the SHA comes from the action's own repo and not from a fork (impostor
  commits). Repos can also **require SHA pinning** in Settings → Actions → General
  ([secure use](https://docs.github.com/en/actions/reference/security/secure-use)). The Trivy
  incident shows why: tags were rewritten, and pipelines pinned to a SHA were not affected.
* **Latest action releases, resolved with `git ls-remote` on 2026-10-05.** Re-resolve with
  `pinact run` before committing.

  | Action | Tag | Commit SHA |
  |---|---|---|
  | actions/checkout | v7.0.1 | `3d3c42e5aac5ba805825da76410c181273ba90b1` |
  | actions/setup-python | v7.0.0 | `5fda3b95a4ea91299a34e894583c3862153e4b97` |
  | docker/setup-qemu-action | v4.4.0 | `99012661954931238ded8c8b007157a8430204e1` |
  | docker/setup-buildx-action | v4.4.1 | `f87e5991a6d7451dcb8d9637bfbc97413f497069` |
  | docker/login-action | v4.6.0 | `dbcb813823bdd20940b903addbd779551569679f` |
  | docker/metadata-action | v6.2.0 | `dc802804100637a589fabce1cb79ff13a1411302` |
  | docker/build-push-action | v7.4.0 | `c3c9e263c25d99ce0380d002d59b67737d91b0dc` |
  | actions/attest | v4.2.2 | `1e69f48acb82d1966a394da916b4c1698aa569d6` |
  | actions/attest-build-provenance | v4.2.2 (now a wrapper over `actions/attest`) | `4d101475d8b20a2381f78447822ac1eab6504dd8` |
  | sigstore/cosign-installer | v4.1.2 (cosign v3.1.3) | `6f9f17788090df1f26f669e9d70d6ae9567deba6` |
  | anchore/scan-action | v7.4.2 (grype v0.120.0) | `27805bf3b4e84b4a5c980df22ed233c00390a439` |
  | anchore/sbom-action | v0.24.3 | `66cbf4bc1f1c0d2edc94016e65bc221b6bb0ad6c` |
  | aquasecurity/trivy-action | v0.36.0 (post-incident) | `ed142fd0673e97e23eac54620cfb913e5ce36c25` |
  | github/codeql-action | v4.38.2 | `2892aa5e19bbd11bc0cff5427e3b750a04d9e3c2` |
  | zizmorcore/zizmor-action | v0.6.4 (zizmor v1.30.1) | `cc914d7f3750a2d13d75c7f184a1060aa0e9d482` |
  | hadolint/hadolint-action | v3.5.0 | `06be81baf89a55ffd0e24b8f04a4185738dd3387` |
  | actions/dependency-review-action | v5.0.0 | `a1d282b36b6f3519aa1f3fc636f609c47dddb294` |
  | ossf/scorecard-action (optional) | v2.4.4 | `2d1146689b8cda280b9bc96326124645441f03bc` |
  | rhysd/actionlint (binary) | v1.7.12 | download the release asset and check its SHA-256 |

  `actions/checkout` v7 **refuses to check out fork PRs under `pull_request_target`/`workflow_run`**,
  and since v6 it persists credentials to a separate file
  ([CHANGELOG](https://github.com/actions/checkout/blob/main/CHANGELOG.md)). Still set
  `persist-credentials: false`.
* **Dependabot** ([options](https://docs.github.com/en/code-security/dependabot/working-with-dependabot/dependabot-options-reference)):
  * Ecosystems `pip` (including pip-compile, regenerating hashes), `github-actions` (updates SHA
    pins and their version comments) and `docker` (updates `tag@sha256` digests in a
    `Containerfile`).
  * `cooldown` (`default-days`, `semver-*-days`) applies to version updates only. Security updates
    are never delayed. **Dependabot now applies a default 3-day cooldown even when none is
    configured.**
  * Dependabot cannot read cooldown dates for GHCR images. It can for Docker Hub.
* **Locking.** pip-tools **7.6.1** (BSD-3-Clause): `pip-compile --generate-hashes` hashes every
  wheel and sdist of each pinned release, so the same lock works for amd64 and arm64. Dependabot
  supports pip-compile natively. uv **0.12.23** (MIT OR Apache-2.0) is faster and can target another
  Python with `--python-version`. Dependabot's `uv` ecosystem, however, is designed around `uv.lock`
  in project mode. **Pick pip-tools for now.** Install with `pip install --no-deps --require-hashes
  --only-binary=:all: -r requirements.lock`; `--only-binary` means no sdist build backends run at
  build time.
* **Provenance and SBOM.**
  * buildx `provenance: mode=max` + `sbom: true` stores attestations in the image index. They
    are unsigned on their own, but they are covered once the index digest is signed. Never pass
    secrets as build-args: `mode=max` records them.
  * `actions/attest` (subject name + digest, `push-to-registry: true`) adds GitHub-signed SLSA
    provenance, verifiable with `gh attestation verify`. It needs `id-token: write` and
    `attestations: write`.
  * Storage records (`artifact-metadata: write`) work **only for organisation-owned repos**, so set
    `create-storage-record: false` here
    ([actions/attest](https://github.com/actions/attest)).
* **Signing.** cosign v3 signs keylessly through Fulcio, using the GitHub OIDC token. Since v3 the
  default is the **Sigstore bundle format stored as an OCI 1.1 referrer**. Verify with:

  ```
  cosign verify IMAGE@DIGEST \
    --certificate-identity-regexp '^https://github.com/ksullivan86/kidney-health/\.github/workflows/release\.yml@refs/(heads/main|tags/v.+)$' \
    --certificate-oidc-issuer https://token.actions.githubusercontent.com
  ```

  ([Sigstore verify](https://docs.sigstore.dev/cosign/verifying/verify/)).
* **Scanners.**
  * **Grype** (Apache-2.0): `anchore/scan-action` exposes `severity-cutoff`, `only-fixed` and
    SARIF output.
  * **Trivy** (Apache-2.0) is equally capable. Its March 2026 compromise affected binary v0.69.4,
    almost all `trivy-action` tags, `setup-trivy` and Docker images 0.69.5/0.69.6. It makes a
    point: a scanner runs with whatever the job can reach, so run scanners in a job with **no write
    scopes and no secrets**.
  * Choose Grype, partly to avoid a recently compromised supply chain and partly to stay with one
    vendor for SBOM (Syft) and scan.
* **CodeQL** supports `python`, `javascript-typescript` and **`actions`** (workflow injection)
  ([CodeQL](https://docs.github.com/en/code-security/code-scanning/introduction-to-code-scanning/about-code-scanning-with-codeql)).
  It is free once the repo is public. **zizmor** audits workflows (template injection, excessive
  permissions, unpinned uses, impostor commits) and runs on private repos too.

### 3.7 App-level hardening

* **Browser support** (MDN browser-compat-data, 2026-10-05):
  * **`Permissions-Policy` is Chromium-only.** Safari and Firefox have no support, so on the
    target platform (iOS) `camera=(self)` is defence in depth only. CSP is what actually protects.
  * `frame-ancestors`, `base-uri` and `form-action` work everywhere (iOS 9.3+).
  * `worker-src`: Safari 15.5. `'wasm-unsafe-eval'`: Safari 16 (needed if the barcode decoder is
    WebAssembly).
  * **Trusted Types (`require-trusted-types-for`): Chrome 83, Firefox 148, Safari 26.** It is now
    cross-browser, and browsers that lack it simply ignore it. Its `TrustedScriptURL` sinks include
    **`ServiceWorkerContainer.register()`** and the `Worker()` URL
    ([MDN](https://developer.mozilla.org/en-US/docs/Web/API/Trusted_Types_API)), so
    `trusted-types 'none'` would make note 02's `navigator.serviceWorker.register('/sw.js')` throw on
    iOS 26 and Chrome. §5.5 therefore allows one named policy (security review §10 S3).
  * `Sec-Fetch-Site`: Chrome 76, Firefox 90, Safari 16.4. `COOP`: Safari 15.2.
  * `BarcodeDetector` is **not** available in Safari or Firefox by default.
  * `getUserMedia` needs a secure context.
* **Things that break a strict CSP today.**
  * The inline theme `<script>` in `index.html`: move it to `/theme-init.js`, loaded synchronously
    in `<head>`.
  * The `data:` favicon: replace it with a file; note 02 adds PNG icons anyway.
  * FastAPI `/docs`/`/redoc` (CDN + inline): disable by default.
  * Setting `el.style.x` from JS is CSSOM and **is allowed** without `'unsafe-inline'`.
  * `upgrade-insecure-requests` would **break** a page served over plain `http://lan:8000`. Send it
    only when the effective scheme is https.
* **uvicorn proxy headers** ([settings](https://github.com/encode/uvicorn/blob/main/docs/settings.md),
  [deployment](https://github.com/encode/uvicorn/blob/main/docs/deployment/index.md)).
  `--proxy-headers` is on by default but trusts only `--forwarded-allow-ips` (env
  `FORWARDED_ALLOW_IPS`, default `127.0.0.1,::1`, CIDRs allowed). `'*'` means trust everyone; the
  image does this today. Once uvicorn rewrites `scope["client"]`, the app can no longer see the
  real peer, so it cannot decide whether to trust a forward-auth header such as `Remote-User` or
  `Tailscale-User-Login`. **The app must do proxy handling itself** (§5.5).
* **Request bodies.** uvicorn sets no body-size limit (`--h11-max-incomplete-event-size` covers
  headers only). Starlette's `request.form()` takes `max_files`, `max_fields` and `max_part_size`.
* **Secrets in env vars** are visible in `/proc/<pid>/environ`, get inherited by child processes,
  and end up in `inspect` output and crash dumps. Docker's docs recommend file secrets and the
  `*_FILE` convention of the official images
  ([compose secrets](https://docs.docker.com/compose/how-tos/use-secrets/)).

---

## 4. Options compared

### 4.1 Runtime base image

| | `python:3.14-slim-trixie` | **Chainguard `python:latest`** | distroless `python3-debian13` | DHI `python:3.14` |
|---|---|---|---|---|
| High + Critical (grype, 2026-10-05) | 56 (1 fixable) | **0** | 43 (0 fixable) | not measured |
| Shell / package manager at runtime | yes / apt + pip | **no / no** | no / no | no / no |
| Python version control | any tag | `latest` floats (3.14 today) | Debian's 3.13 only | any tag |
| arm64 | yes | yes | yes | yes |
| Licence / terms | Debian packages, PSF; Dockerfiles MIT | Wolfi OSS packages, PSF; free-tier terms of Chainguard | Apache-2.0 build, Debian packages | **Apache-2.0** |
| Anonymous pull (forks, contributors) | yes (Docker Hub rate limits) | **yes** | yes | **no (login)** |
| Dependabot digest bumps | yes | yes | yes | needs registry creds |
| Builder/runtime match | trivial | `latest-dev` → `latest` (same digest generation) | awkward (Debian python3-venv) | `-dev` → runtime |
| Verdict | **Fallback** (`Containerfile.debian`) | **Default** | Rejected (old Python, Critical CVEs) | Revisit if login is dropped |

### 4.2 Rootless Podman user-namespace mode

| Mode | Host UID of the app process | Bind-mount ergonomics | Isolation between your containers | Verdict |
|---|---|---|---|---|
| default (`host`) | subuid_start + 10000 | `podman unshare chown` or `:U` | shared subuid range | **Default** |
| `keep-id:uid=10001,gid=10001` | **your own UID** | files stay yours | none | Development only |
| `auto` (+ `:U`) | a fresh slice of your subuids | `:U` on each start | **yes** | Advanced option |
| `nomap` | subuid; your UID unmapped | `podman unshare` offsets differ | partial | Not documented |

### 4.3 Scanner

| | Grype (anchore/scan-action) | Trivy (trivy-action) |
|---|---|---|
| Gate on HIGH/CRITICAL with fixes only | `severity-cutoff: high`, `only-fixed: true` | `severity: HIGH,CRITICAL`, `ignore-unfixed: true` |
| SBOM pairing | Syft (same vendor) | built in |
| 2026 supply-chain incident | none known | March 2026 compromise (binary, action tags, images) |
| Verdict | **Use** | Acceptable if pinned to SHA ≥ v0.35.0, not chosen |

### 4.4 Provenance and signing

| Mechanism | Works while private | Verifier | Covers | Verdict |
|---|---|---|---|---|
| buildx `provenance: mode=max` + `sbom: true` (in-index) | yes (mode=max must be explicit) | `docker buildx imagetools inspect --format '{{json .Provenance}}'` | build recipe, packages | **Yes** |
| cosign keyless sign of the index digest | yes, but leaks the repo name to Rekor | `cosign verify` | image + in-index attestations | **Yes, public only** |
| `actions/attest` provenance, `push-to-registry` | **no** (Free plan) | `gh attestation verify oci://… --repo ksullivan86/kidney-health` | GitHub-signed SLSA v1 provenance | **Yes, public only** |
| Podman `policy.json` enforcement | n/a | n/a | n/a | Not possible (needs `subjectEmail`) |

### 4.5 Kubernetes egress control

| | Vanilla NetworkPolicy | Cilium `CiliumNetworkPolicy` |
|---|---|---|
| Runs on Talos default (Flannel) | only with `kubeNetworkPoliciesEnabled: true` | needs CNI replaced at cluster creation |
| Domain allowlist | no: `0.0.0.0/0` except private ranges, port 443 | **yes**: `toFQDNs` + DNS proxy |
| Verdict | **Ship as default** (`networkpolicy.yaml`) | **Ship as example** |

---

## 5. Recommendation

### 5.1 Image: `deploy/Containerfile` (Chainguard) and `deploy/Containerfile.debian` (fallback)

Principles:

* Literal `FROM …@sha256:` lines, so Dependabot can update them.
* Builder and runtime from the same family.
* **Code owned by root and not writable.** Only `/data` belongs to `10001:0` with mode `0770`
  (group 0 lets OpenShift-style arbitrary UIDs with GID 0 work).
* **Keep UID 10001.** Switching to 65532 would break every existing volume.
* No pip, no shell and no package manager at runtime.
* The health check is a module, not inline `-c` code.

```dockerfile
# syntax=docker/dockerfile:1
# deploy/Containerfile -- published image. Build from the repo root:
#   podman build --format docker -f deploy/Containerfile -t kidney-health:local .
FROM cgr.dev/chainguard/python:latest-dev@sha256:a876b1000774bdd68322ac020cd813aaf42b52941ca812f4d2f0149059bd0e67 AS builder
USER 0
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /build
COPY requirements.lock ./
# venv without pip; the builder's pip installs into it (pip >= 22.3 supports --python).
RUN python -m venv --without-pip /opt/venv \
 && python -m pip --python /opt/venv/bin/python install \
      --no-deps --require-hashes --only-binary=:all: -r requirements.lock
COPY app/ /opt/app/app/
COPY data/foods.json /opt/app/data/foods.json
COPY LICENSE /opt/app/LICENSE
RUN /opt/venv/bin/python -m compileall -q -j 0 /opt/app/app \
 && chmod -R go-w /opt/venv /opt/app \
 && mkdir -p /out/data && chmod 0770 /out/data

FROM cgr.dev/chainguard/python:latest@sha256:3de78d5699d76c56f74a4a47abcd81f22f5a16757eee9fac45837fb2ae3f0e06
LABEL org.opencontainers.image.title="kidney-health" \
      org.opencontainers.image.source="https://github.com/ksullivan86/kidney-health" \
      org.opencontainers.image.licenses="PolyForm-Noncommercial-1.0.0"
ENV PATH=/opt/venv/bin:/usr/bin:/bin \
    PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    DATA_DIR=/data
COPY --from=builder --chown=0:0     /opt/venv  /opt/venv
COPY --from=builder --chown=0:0     /opt/app   /app
COPY --from=builder --chown=10001:0 /out/data  /data
WORKDIR /app
USER 10001:10001
EXPOSE 8000
VOLUME ["/data"]
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD ["python", "-m", "app.healthcheck"]
# The base image sets ENTRYPOINT to the interpreter; replace it.
ENTRYPOINT ["python", "-m", "uvicorn", "app.main:app"]
# --no-proxy-headers: the app handles X-Forwarded-* itself (TRUSTED_PROXIES, §5.5).
CMD ["--host", "0.0.0.0", "--port", "8000", "--no-proxy-headers", "--no-server-header", \
     "--timeout-graceful-shutdown", "10"]
```

`deploy/Containerfile.debian` is the same file with both `FROM` lines changed to
`docker.io/library/python:3.14-slim-trixie@sha256:c3e521df8b2b498a7a682e7e18676771cb80c6b75b8699af886b2d554ce40151`.
In the final stage, add `RUN ["python", "-m", "pip", "uninstall", "-y", "pip"]` before `USER`. CI
builds it on PRs that touch `deploy/` or the lock file; it is not published. Use it if you need a
shell for debugging or if Chainguard's free tier changes.

Dependencies (`requirements.in`):

* `fastapi`, `uvicorn` **without `[standard]`**, `pydantic`, `httpx`, plus whatever v0.3 adds:
  `cryptography` 50.0.2 (Apache-2.0 OR BSD-3-Clause) for Argon2id passwords and key encryption
  (note 07). **Not** `python-multipart`: photos are raw `image/jpeg` bodies (note 03 R8), so no
  multipart parser and no spooling to `/tmp`. **Not** `argon2-cffi`: superseded by note 07.
  (Corrected in the security review.)
* Dropping the extras removes six packages, three of them native. The h11 server is ample for a
  household (keep `h11>=0.16.0`, the request-smuggling fix).
* Lock with
  `pip-compile --generate-hashes --strip-extras -o requirements.lock requirements.in`, run under
  Python 3.14 (`scripts/lock.sh` runs it inside `python:3.14-slim-trixie`). Do the same for
  `requirements-dev.in` → `requirements-dev.lock`.

`app/healthcheck.py` uses the stdlib only and **bypasses `HTTP(S)_PROXY`**, so an egress-proxy
setting can never break the probe:

```python
import os, sys, urllib.request
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
try:
    with opener.open(f"http://127.0.0.1:{os.environ.get('PORT', '8000')}/healthz", timeout=4) as r:
        sys.exit(0 if r.status == 200 else 1)
except Exception:
    sys.exit(1)
```

`app/admin.py` is a CLI that replaces the shell commands in `docs/deployment.md`. The current docs
use `podman exec … rm` and `kubectl exec … cat`, which fail without coreutils.

* `python -m app.admin backup -` writes a consistent `sqlite3.backup` copy to stdout, so
  `kubectl exec deploy/kidney-health -- python -m app.admin backup - > kidney.db` works.
* `backup /data/backup.db`, `restore-check FILE`, `rotate-secret-key`.

For debugging, use `podman cp`, `podman run --rm -it --volumes-from kidney-health
cgr.dev/chainguard/python:latest-dev sh`, or `kubectl debug -it --profile=restricted
--target=app POD --image=cgr.dev/chainguard/python:latest-dev`.

### 5.2 Runtime profiles

**Rootless Podman with Quadlet (recommended for single hosts),
`deploy/quadlet/kidney-health.container`.** Works with Podman ≥ 4.9; `Notify=healthy` needs 5.0.

```ini
[Container]
Image=ghcr.io/ksullivan86/kidney-health:0.3
ContainerName=kidney-health
AutoUpdate=registry
Network=pasta
PublishPort=127.0.0.1:8000:8000
Volume=kidney-health.volume:/data
# Default rootless mapping. Do NOT add UserNS=keep-id: it would run the app as your own host UID.
User=10001
Group=10001
ReadOnly=true
DropCapability=all
NoNewPrivileges=true
PidsLimit=128
PodmanArgs=--memory=512m
# Add --cpus=1 only after delegating the cpu controller (Delegate=cpu cpuset io memory pids).
Secret=kidney-secret-key,type=mount,target=secret_key,uid=10001,gid=10001,mode=0400
Secret=kidney-usda-key,type=mount,target=usda_api_key,uid=10001,gid=10001,mode=0400
Environment=SECRET_KEY_FILE=/run/secrets/secret_key
Environment=USDA_API_KEY_FILE=/run/secrets/usda_api_key
# With pasta a proxy on this host appears as the container's OWN address, not 127.0.0.1 (§3.1).
# Put the address the app logs here; in AUTH_MODE=proxy also mount TRUSTED_PROXY_SECRET_FILE (§10 S2).
Environment=TRUSTED_PROXIES=127.0.0.1,::1
HealthCmd=python -m app.healthcheck
HealthInterval=30s
HealthTimeout=5s
HealthStartPeriod=15s
HealthRetries=3
HealthOnFailure=kill
# Notify=healthy        # Podman >= 5.0

[Service]
Restart=always
RestartSec=5
TimeoutStartSec=900
```

Setup and checks:

```bash
openssl rand -base64 32 | podman secret create kidney-secret-key -
printf '%s' "$USDA_KEY" | podman secret create kidney-usda-key -
systemctl --user daemon-reload && systemctl --user start kidney-health
podman info --format '{{.Host.Security.Rootless}}'          # true
podman top kidney-health user huser                         # 10001  <subuid_start+10000>, never your UID
podman inspect kidney-health --format '{{.HostConfig.ReadonlyRootfs}} {{.HostConfig.CapDrop}}'
```

Bind mount instead of a named volume: `Volume=%h/kidney-data:/data:Z,U`.

**Rootless Docker / compose (`deploy/compose.yaml`).** Works with podman-compose and
`docker compose`.

```yaml
services:
  kidney-health:
    image: ghcr.io/ksullivan86/kidney-health:0.3
    user: "10001:10001"
    read_only: true
    tmpfs: ["/tmp:rw,noexec,nosuid,nodev,size=64m"]
    cap_drop: [ALL]
    security_opt: ["no-new-privileges:true"]
    pids_limit: 128
    mem_limit: 512m
    ports: ["127.0.0.1:8000:8000"]
    environment:
      TRUSTED_PROXIES: "127.0.0.1,::1"
      SECRET_KEY_FILE: /run/secrets/secret_key
      USDA_API_KEY_FILE: /run/secrets/usda_api_key
    secrets: [secret_key, usda_api_key]
    volumes: ["kidney-data:/data"]
    restart: always
secrets:
  secret_key:   {file: ./secrets/secret_key}     # deploy/secrets/ is git-ignored
  usda_api_key: {file: ./secrets/usda_api_key}
volumes:
  kidney-data: {}
```

Compose file secrets are bind mounts. Under a rootless engine your host UID is container root, so a
`0600` file you own is **unreadable by 10001**. Either `podman unshare chown 10001:10001
deploy/secrets/*`, or use mode `0644` inside a `0700` directory. Quadlet `Secret=` avoids this
problem, which is one more reason to prefer Quadlet on Podman.

Rootless Docker setup:

1. `dockerd-rootless-setuptool.sh install`.
2. `systemctl --user enable --now docker`.
3. `sudo loginctl enable-linger $USER`.
4. `docker info` must show `name=rootless`.
5. Keep `127.0.0.1` publishing: source IP is not propagated (§3.2).

### 5.3 Kubernetes (Talos)

`namespace.yaml` labels:

```yaml
pod-security.kubernetes.io/enforce: restricted
pod-security.kubernetes.io/enforce-version: latest
pod-security.kubernetes.io/audit: restricted
pod-security.kubernetes.io/warn: restricted
```

`deployment.yaml` pod template (replace the existing security-relevant parts):

```yaml
spec:
  automountServiceAccountToken: false
  enableServiceLinks: false
  # hostUsers: false   # optional: k8s >= 1.36, Talos SysctlConfig user.max_user_namespaces, idmap-capable storage
  securityContext:
    runAsNonRoot: true
    runAsUser: 10001
    runAsGroup: 10001
    fsGroup: 10001
    fsGroupChangePolicy: OnRootMismatch
    supplementalGroupsPolicy: Strict
    seccompProfile: {type: RuntimeDefault}
  containers:
    - name: app
      image: ghcr.io/ksullivan86/kidney-health:0.3.0@sha256:<digest>   # via kustomize images: digest
      imagePullPolicy: IfNotPresent
      env:
        # A pod CIDR trusts EVERY pod in the cluster. Only safe while networkpolicy.yaml is enforced
        # (Talos Flannel ignores it unless kubeNetworkPoliciesEnabled) or TRUSTED_PROXY_SECRET_FILE is set (§10 S2).
        - {name: TRUSTED_PROXIES, value: "10.244.0.0/16"}
        - {name: SECRET_KEY_FILE, value: /run/secrets/kidney-health/secret_key}
        - {name: USDA_API_KEY_FILE, value: /run/secrets/kidney-health/usda_api_key}
      securityContext:
        allowPrivilegeEscalation: false
        readOnlyRootFilesystem: true
        runAsNonRoot: true
        privileged: false
        capabilities: {drop: [ALL]}
      resources:
        requests: {cpu: 50m, memory: 128Mi, ephemeral-storage: 64Mi}
        limits:   {memory: 512Mi, ephemeral-storage: 256Mi}   # no CPU limit: avoids throttling
      volumeMounts:
        - {name: data, mountPath: /data}
        - {name: tmp, mountPath: /tmp}
        - {name: secrets, mountPath: /run/secrets/kidney-health, readOnly: true}
  volumes:
    - {name: data, persistentVolumeClaim: {claimName: kidney-health-data}}
    - {name: tmp, emptyDir: {medium: Memory, sizeLimit: 64Mi}}
    - name: secrets
      secret: {secretName: kidney-health, defaultMode: 0440, optional: true}
```

`networkpolicy.yaml` (vanilla, portable; on Talos + Flannel it needs `kubeNetworkPoliciesEnabled: true`):

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata: {name: default-deny, namespace: kidney-health}
spec: {podSelector: {}, policyTypes: [Ingress, Egress]}
---
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata: {name: kidney-health, namespace: kidney-health}
spec:
  podSelector: {matchLabels: {app.kubernetes.io/name: kidney-health}}
  policyTypes: [Ingress, Egress]
  ingress:
    - from:
        - namespaceSelector: {matchLabels: {kubernetes.io/metadata.name: gateway-system}}  # your Gateway / ingress namespace
      ports: [{port: 8000, protocol: TCP}]
  egress:
    - to:
        - namespaceSelector: {matchLabels: {kubernetes.io/metadata.name: kube-system}}
          podSelector: {matchLabels: {k8s-app: kube-dns}}
      ports: [{port: 53, protocol: UDP}, {port: 53, protocol: TCP}]
    - to:   # public HTTPS only: USDA, Open Food Facts, OpenAI
        - ipBlock: {cidr: 0.0.0.0/0, except: [10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, 100.64.0.0/10, 169.254.0.0/16, 127.0.0.0/8]}
        - ipBlock: {cidr: "::/0", except: ["fc00::/7", "fe80::/10", "::1/128"]}
      ports: [{port: 443, protocol: TCP}]
    # Optional LAN AI host (Ollama 11434 / Hermes):
    # - to: [{ipBlock: {cidr: 192.168.1.50/32}}]
    #   ports: [{port: 11434, protocol: TCP}]
```

Kubelet probes are not affected: per the Kubernetes NetworkPolicy docs, pods cannot block access
from their own node, which is where the kubelet probes from. Check this on your CNI anyway.

`cilium-networkpolicy.example.yaml` (FQDN-precise; replace the `0.0.0.0/0` rule when using Cilium):

```yaml
apiVersion: cilium.io/v2
kind: CiliumNetworkPolicy
metadata: {name: kidney-health-egress-fqdn, namespace: kidney-health}
spec:
  endpointSelector: {matchLabels: {app.kubernetes.io/name: kidney-health}}
  egress:
    - toEndpoints:
        - matchLabels: {k8s:io.kubernetes.pod.namespace: kube-system, k8s-app: kube-dns}
      toPorts:
        - ports: [{port: "53", protocol: ANY}]
          rules: {dns: [{matchPattern: "*"}]}
    - toFQDNs:
        - matchName: api.nal.usda.gov
        - matchName: world.openfoodfacts.org
        # - matchName: api.openai.com
      toPorts: [{ports: [{port: "443", protocol: TCP}]}]
```

Other Kubernetes changes:

* Make `httproute.yaml` (Gateway API) the default and rename `ingress.yaml` to
  `ingress.example.yaml`, with a note about the ingress-nginx retirement.
* Pin images by digest in `kustomization.yaml`:
  `images: [{name: ghcr.io/ksullivan86/kidney-health, newTag: "0.3.0", digest: "sha256:…"}]`.
* No PDB.

### 5.4 Supply chain (GitHub)

Workflows. Every workflow starts with `permissions: {}`, every `uses:` is pinned to a SHA with a
`# vX.Y.Z` comment, every checkout sets `persist-credentials: false`, and no workflow uses
`pull_request_target`.

* **`ci.yml`** (pull_request, push):
  * pytest on 3.12 and 3.14, installing from `requirements-dev.lock` with `--require-hashes`.
  * actionlint (binary pinned with a SHA-256 check), **zizmor** and hadolint. Add `cgr.dev` to
    `trustedRegistries` in `.hadolint.yaml`.
  * kubeconform with a checksum.
  * Build `linux/amd64` with `load: true`, then **container smoke test**: run with `--read-only
    --cap-drop=ALL --security-opt=no-new-privileges`, once as `--user 10001:10001` and once as
    `--user 12345:0`. Expect `/healthz` 200 and a `POST /api/log` 201.
  * **Grype gate** on the local image: `severity-cutoff: high`, `only-fixed: true`.
  * `dependency-review-action` on PRs once the repo is public.
* **`release.yml`** (push to main, `v*` tags), with jobs in this order:
  1. **build** (`packages: write`):
     * metadata-action computes the tags.
     * build-push-action with
       `outputs: type=image,name=ghcr.io/ksullivan86/kidney-health,push-by-digest=true,name-canonical=true,push=true`,
       `platforms: linux/amd64,linux/arm64`, `provenance: mode=max`, `sbom: true`.
     * Outputs the `digest`.
  2. **scan** (`contents: read`, `packages: read`, plus `security-events: write` only when public;
     **no other scopes**): Grype on `IMAGE@digest`, matrix over both platforms (`GRYPE_PLATFORM`, grype's `platform` setting),
     `fail-build: true`.
  3. **publish** (`packages: write`, `id-token: write`, `attestations: write`; optionally behind a
     GitHub Environment `release` with required reviewers):
     * `cosign sign --yes IMAGE@digest`, only when public.
     * `actions/attest` with `subject-name`/`subject-digest`, `push-to-registry: true`,
       `create-storage-record: false`, only when public.
     * Finally `docker buildx imagetools create -t … IMAGE@digest`, so **tags move only after the
       scan has passed**.
* **`codeql.yml`**: languages `python`, `javascript-typescript`, `actions`, `build-mode: none`. Runs
  on PRs and weekly once public; until then, use zizmor plus the `actions` checks in CI.
* **`scheduled-scan.yml`** (weekly): Grype on `:latest` with a fresh database. It fails, or opens an
  issue, when a new fixable High appears.

`.github/dependabot.yml`:

```yaml
version: 2
updates:
  - package-ecosystem: pip
    directory: /
    schedule: {interval: weekly}
    cooldown: {default-days: 7}
    groups: {python: {patterns: ["*"]}}
  - package-ecosystem: github-actions
    directory: /
    schedule: {interval: weekly}
    cooldown: {default-days: 7}
    groups: {actions: {patterns: ["*"]}}
  - package-ecosystem: docker
    directory: /deploy
    schedule: {interval: daily}           # base-image digests carry security fixes
    cooldown: {default-days: 2}
    groups: {base-images: {patterns: ["*"]}}   # builder + runtime bump together
```

Repository settings:

* Require SHA-pinned actions.
* Rulesets: PRs + green CI on `main`; no force-push or deletion of `v*` tags; **immutable releases**.
* Workflow token default read-only.
* GHCR package public, with "Manage Actions access" limited to this repo.
* Private vulnerability reporting on; `SECURITY.md`.
* Optional: OpenSSF Scorecard once public.

User-side verification (document it in `docs/security.md`, and ship it as `scripts/verify-image.sh`):

```bash
D=$(skopeo inspect --format '{{.Digest}}' docker://ghcr.io/ksullivan86/kidney-health:0.3.0)   # or crane digest
cosign verify "ghcr.io/ksullivan86/kidney-health@$D" \
  --certificate-identity-regexp '^https://github.com/ksullivan86/kidney-health/\.github/workflows/release\.yml@refs/tags/v' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com
gh attestation verify "oci://ghcr.io/ksullivan86/kidney-health@$D" --repo ksullivan86/kidney-health
```

Then deploy by digest, or track the minor tag `:0.3` with auto-update. Do not track `:latest` on
machines you care about.

### 5.5 App-level hardening

New module `app/security.py`, a pure-ASGI stack registered in `create_app()`. The **first entry is
the outermost** middleware:

1. **`PeerCaptureMiddleware`** stores the real TCP peer in `scope["state"]["peer"]`.
2. **Proxy handling.** `uvicorn.middleware.proxy_headers.ProxyHeadersMiddleware(app,
   trusted_hosts=settings.trusted_proxies)` applies `X-Forwarded-For`/`-Proto` only from trusted
   peers. The image runs uvicorn with `--no-proxy-headers`, so this happens exactly once.
3. **`BodyLimitMiddleware`**: `413` when `Content-Length` exceeds `MAX_BODY_BYTES`, and stops
   streaming when the counted bytes exceed it (Starlette ≥ 1.6 `max_body_size` on the app and on
   routes does the same; prefer it). Photo routes take a raw `image/jpeg` body with their own
   route-level limit `MAX_IMAGE_BYTES` (4 MiB) and a header check (§10 S5); nothing parses
   multipart. (Corrected in the security review; the earlier `request.form()` plan spooled parts
   over 1 MB to `/tmp`.)
4. **`CsrfMiddleware`**: for POST, PUT, PATCH and DELETE, reject with `403` when `Sec-Fetch-Site`
   is present and not `same-origin`. When the header is absent, require `Origin` to be absent or
   equal to the request's own origin.
5. **`SecurityHeadersMiddleware`** adds these headers to **every** response (static files, errors,
   404s):

   ```
   Content-Security-Policy: default-src 'self'; script-src 'self' 'wasm-unsafe-eval'; style-src 'self';
     img-src 'self' blob:; connect-src 'self'; font-src 'self'; manifest-src 'self'; worker-src 'self';
     media-src 'self' blob:; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none';
     require-trusted-types-for 'script'; trusted-types kh-sw
   X-Content-Type-Options: nosniff
   Referrer-Policy: no-referrer
   Permissions-Policy: camera=(self), microphone=(), geolocation=(), payment=(), usb=(), browsing-topics=()
   Cross-Origin-Opener-Policy: same-origin
   Cross-Origin-Resource-Policy: same-origin
   X-Frame-Options: DENY
   ```

   It also adds:

   * `upgrade-insecure-requests` to the CSP and `Strict-Transport-Security: max-age=<HSTS_MAX_AGE>`,
     **only when the effective scheme is https**.
   * `Cache-Control: no-store` on `/api/*`.

   Note 03 picked the WebAssembly decoder, so `'wasm-unsafe-eval'` is in `script-src`. Nothing
   else. **`trusted-types kh-sw`, not `'none'`** (corrected in the security review, §10 S3):
   `navigator.serviceWorker.register()` is a `TrustedScriptURL` sink, so the app needs exactly one
   policy, created once in the registration script and allowing exactly one URL:

   ```js
   const swPolicy = window.trustedTypes?.createPolicy('kh-sw', {
     createScriptURL: (u) => { if (u === '/sw.js') return u; throw new TypeError('blocked script URL'); },
   });
   navigator.serviceWorker.register(swPolicy ? swPolicy.createScriptURL('/sw.js') : '/sw.js');
   ```

   Never add `'allow-duplicates'` or a `default` policy. Note 03's later Tesseract experiment adds
   its own named policy (`kh-ocr`).

Proxy authentication: when `TRUSTED_PROXY_USER_HEADER` is set (for example `Remote-User`, or
`Tailscale-User-Login` behind `tailscale serve`), honour that header **only if
`scope["state"]["peer"]` is in `TRUSTED_PROXIES`**. Strip it otherwise.

Frontend changes required by the CSP:

* Move the inline theme script to `app/static/theme-init.js`.
* Replace the `data:` favicon with `app/static/icons/icon.svg`.
* Keep `textContent` and DOM APIs only. A test greps `app/static/*.js` for HTML sinks.

`/docs`, `/redoc` and `/openapi.json` are off unless `ENABLE_API_DOCS=true`. When on, those paths
alone get a relaxed CSP.

**Configuration keys** (env; every secret key also accepts `<KEY>_FILE`; setting both is a startup
error; file contents are read once with trailing `\r\n` stripped):

| Key | Default | Purpose |
|---|---|---|
| `TRUSTED_PROXIES` | `127.0.0.1,::1` | IPs or CIDRs whose `X-Forwarded-*` (and identity header) are trusted. Replaces `--forwarded-allow-ips=*`. |
| `TRUSTED_PROXY_USER_HEADER` | unset | Forward-auth identity header name. Honoured only from `TRUSTED_PROXIES`. |
| `SECRET_KEY` / `SECRET_KEY_FILE` | auto-generated `/data/secret.key` (`0600`) with a startup warning. That file sits on the data volume, so **volume-level backups contain it** (§10 S8); every shipped profile mounts `SECRET_KEY_FILE` instead | Encrypts stored API keys (Fernet under HKDF-derived keys, note 07 §4.12). Sessions are opaque server-side tokens and are **not** signed with it (note 07; corrected in the security review). Rotate with `python -m app.admin rotate-secret-key`. |
| `USDA_API_KEY[_FILE]`, `APP_PASSWORD[_FILE]`, `OPENAI_API_KEY[_FILE]`, other AI keys | unset | An operator-supplied key is **locked**: the UI shows it as "set by server" and it cannot be changed or read through the API. |
| `MAX_BODY_BYTES` | `1048576` | JSON request limit. |
| `MAX_IMAGE_BYTES` | `4194304` | Raw `image/jpeg` body limit for photo routes (note 03 R8). Replaces the earlier `MAX_UPLOAD_BYTES` (10 MiB, multipart). |
| `HSTS_MAX_AGE` | `31536000` (sent only over https) | `0` disables it. |
| `ENABLE_API_DOCS` | `false` | Swagger and ReDoc. |
| `ALLOW_INSECURE_HTTP` | `true` in single-user mode, `false` in multi-user mode | When false, non-loopback plain-HTTP requests get a banner and login is refused. |

Secret-handling rules, for the settings and multi-user notes to follow:

* Keys are write-only in the API (`{"set": true, "last4": "…"}`).
* Admin-shared keys are used only server-side, with a per-user quota.
* Keys are never logged; httpx gets them through headers, not URLs.
* AI base URLs follow [note 04 R5](04-optional-ai.md): resolve, validate every address, pin it, no
  redirects. Private, loopback and link-local targets (a LAN Ollama or Hermes) only through the
  env-only `AI_PRIVATE_HOSTS` allowlist, which replaces the earlier boolean
  `ALLOW_PRIVATE_AI_HOSTS` (one flag opened all of RFC 1918). Corrected in the security review.

### 5.6 File layout (new or changed)

```
deploy/Containerfile                      rewritten (Chainguard, digests, root-owned code, no pip)
deploy/Containerfile.debian               fallback (python:3.14-slim-trixie digest), CI-built, not published
deploy/compose.yaml                       hardened defaults + file secrets
deploy/secrets/.gitignore                 "*" and "!.gitignore"
deploy/quadlet/kidney-health.container    hardened (§5.2)
deploy/k8s/{namespace,deployment}.yaml    PSA audit, full securityContext, ro rootfs, secret volume
deploy/k8s/networkpolicy.yaml             default-deny + DNS + public 443 + gateway ingress
deploy/k8s/cilium-networkpolicy.example.yaml
deploy/k8s/httproute.yaml                 default; ingress.yaml → ingress.example.yaml
requirements.in, requirements.lock        pip-compile --generate-hashes (runtime)
requirements-dev.in, requirements-dev.lock
scripts/lock.sh, scripts/verify-image.sh
app/security.py                           middlewares (§5.5)
app/healthcheck.py, app/admin.py
app/config.py                             *_FILE loader, new keys
app/static/theme-init.js, app/static/icons/icon.svg
tests/test_security.py, tests/test_config_secrets.py
.github/workflows/{ci,release,codeql,scheduled-scan}.yml
.github/dependabot.yml
.hadolint.yaml                            trustedRegistries += cgr.dev
SECURITY.md                               reporting, supported versions, how to verify images
docs/security.md                          operator hardening guide + threat-model summary
```

---

## 6. Risks

| # | Risk | Likelihood / impact | Mitigation |
|---|---|---|---|
| R1 | **Chainguard free tier is `latest` only.** When `latest` moves to Python 3.15, staying on the old digest means no more patches, while moving may fail if a wheel (pydantic-core) lags. The vendor has changed free-tier terms before. | Medium / Medium | Dependabot bumps builder and runtime digests together, and CI catches build failures. Switch to `Containerfile.debian` (or DHI) for the gap. Revisit every release. |
| R2 | No shell at runtime makes debugging and the existing backup and restore docs harder | High / Low | `app.admin` CLI, `podman cp`, `kubectl debug` with the `-dev` image. Rewrite `docs/deployment.md` §backup. |
| R3 | A read-only rootfs exposes an unexpected write (a library writing to `$HOME`, SQLite temp) | Low / Medium | tmpfs `/tmp`. The CI smoke test runs the real image read-only as two UIDs. |
| R4 | The CSP or Trusted Types break the UI, or a future library | Medium / Medium | Move the inline script, replace the `data:` favicon. Tests assert the header and grep for sinks. A Playwright smoke test in CI watches the console for CSP violations. A future library that needs HTML gets a named Trusted Types policy, never `'unsafe-inline'`. |
| R5 | The repo stays private, so no attestations or CodeQL | Certain until public / Low | Steps are gated on `!github.event.repository.private`. zizmor and Grype run regardless. |
| R6 | Users cannot enforce signatures in Podman; auto-update trusts whoever controls the tag | Medium / High | Rulesets, environment protection on `release`, signing, docs recommending `:0.3` or a digest. |
| R7 | NetworkPolicy is a no-op on default Talos Flannel; the 443 rule still allows exfiltration to any HTTPS host | High / Medium | Docs state the Flannel flag. Cilium FQDN example. Accepted residual risk. |
| R8 | Wrong `TRUSTED_PROXIES` (for example a whole pod CIDR including attacker pods, or rootless Docker without source-IP propagation) | Medium / High | Default to loopback. Docs give a per-topology table. Log the peer at startup at debug level. Identity headers stay off unless explicitly set. |
| R9 | Plain HTTP on the LAN: no camera, no service worker, no Secure cookies | High / Medium | Note 02's TLS options (Caddy internal CA, DNS-01, `tailscale serve`). Multi-user mode refuses non-loopback HTTP unless `ALLOW_INSECURE_HTTP=true`. |
| R10 | SHA pinning churn and impostor commits | Low / Medium | Dependabot plus pinact, zizmor `impostor-commit`, version comments. |
| R11 | UID mismatches on upgrade (old volumes `10001:10001`, new image `10001:0`) | Low / Low | Owner UID 10001 is unchanged, so it works. Release notes mention `:U` for bind mounts. |
| R12 | `only-fixed` gating hides unfixed Highs | Medium / Low | Weekly scheduled report. Chainguard's low baseline keeps the list readable. |
| R13 | Docker Hub anonymous rate limits (HTTP 429 seen during this research) | Medium / Low | The default base is on cgr.dev and the app on GHCR. Only the fallback uses Docker Hub. |
| R14 | Hermes or other agent endpoints with tools turn prompt injection into actions on the host | Low / High | Plain chat completions only; no tools. Documented in the AI note and in `docs/security.md`. |

---

## 7. Implementation checklist

Work in this order. Each phase is a separate PR. Acceptance criteria are in *italics*.

**Phase A: image and dependencies**
- [ ] Create `requirements.in` (`fastapi`, `uvicorn` without extras, `pydantic`, `httpx`, plus v0.3 additions) and `requirements-dev.in`. Generate both `.lock` files with `scripts/lock.sh` (pip-tools 7.6.1, Python 3.14, `--generate-hashes --strip-extras`). Keep `requirements.txt` as `-r requirements.lock` for one release so old docs still work.
- [ ] Rewrite `deploy/Containerfile` per §5.1. Re-resolve the digests (`crane digest cgr.dev/chainguard/python:latest-dev` / `:latest`) on the day you commit. *`podman build --format docker -f deploy/Containerfile .` works. `podman run --rm IMAGE` serves `/healthz`. `podman run --rm --entrypoint sh IMAGE` fails (no shell). `find /app -writable` would be empty: verify via a `-dev` debug container with `--volumes-from`.*
- [ ] Add `deploy/Containerfile.debian`.
- [ ] Add `app/healthcheck.py`. Point the image `HEALTHCHECK`, Quadlet `HealthCmd` and compose `healthcheck` at `python -m app.healthcheck`.
- [ ] Add `app/admin.py` (`backup FILE|-`, `restore-check`, `rotate-secret-key`). Rewrite the backup and restore sections of `docs/deployment.md` so they need no shell in the container.
- [ ] `.hadolint.yaml`: add `cgr.dev` to `trustedRegistries`.

**Phase B: app hardening**
- [ ] `app/config.py`: generic `_secret(env, name)` that reads `NAME` or `NAME_FILE` (error if both), plus the new keys from §5.5. *Tests: file wins, both set fails, a trailing newline is stripped, an empty file means unset.*
- [ ] `app/security.py`: peer capture, `ProxyHeadersMiddleware(trusted_hosts=TRUSTED_PROXIES)`, body limit, CSRF (Sec-Fetch-Site / Origin), security headers. Register them in `create_app()` in the order of §5.5.
- [ ] Image `CMD`: `--no-proxy-headers --no-server-header`. Remove `--forwarded-allow-ips=*` everywhere (Containerfile, docs).
- [ ] `index.html`: move the inline script to `theme-init.js` and replace the `data:` favicon. Set `docs_url`, `redoc_url` and `openapi_url` to `None` unless `ENABLE_API_DOCS`. Update the README "browsable at /docs" line.
- [ ] `tests/test_security.py`:
  - [ ] Headers on `/`, `/api/profile`, a 404 and a 400.
  - [ ] No `'unsafe-inline'` or `'unsafe-eval'` token in the CSP (compare whole tokens: `'wasm-unsafe-eval'` is expected and contains the substring). `trusted-types` lists only `kh-sw`.
  - [ ] HSTS only with `X-Forwarded-Proto: https` from a trusted peer.
  - [ ] `X-Forwarded-For` ignored from an untrusted peer.
  - [ ] Identity header ignored from an untrusted peer.
  - [ ] Cross-site POST → 403.
  - [ ] Oversized body → 413.
  - [ ] `Cache-Control: no-store` on `/api/*`.
  - [ ] A grep test: no `innerHTML`, `outerHTML`, `insertAdjacentHTML` or `document.write` in `app/static`.

  *`python -m pytest` stays green with no network.*
- [ ] Hand the requirements in §2.4 rows 12–14 and 17 and §5.5 (write-only keys, quotas, SSRF rules, no-tools AI) to the multi-user, settings and AI implementers. Link this note from their decision notes.

**Phase C: runtime profiles**
- [ ] `deploy/quadlet/kidney-health.container` per §5.2 (127.0.0.1 publish, `ReadOnly`, `PidsLimit`, `--memory`, `Secret=`, `TRUSTED_PROXIES`). Update the header comment: Podman ≥ 4.9, `Notify=healthy` ≥ 5.0. *`/usr/libexec/podman/quadlet -user -dryrun` shows no errors. `podman top kidney-health user huser` shows a subuid.*
- [ ] `deploy/compose.yaml` per §5.2, plus `deploy/secrets/.gitignore`. Update `deploy/.env.example` to point at file secrets.
- [ ] `docs/deployment.md`:
  - [ ] Rootless prerequisites (subuid, linger, cgroup delegation).
  - [ ] **Remove the keep-id recommendation**, or move it under "development only" with the reason.
  - [ ] `:U`/`:Z` guidance.
  - [ ] A rootless Docker section (setup tool, source-IP caveat).
  - [ ] Pasta and `host.containers.internal` for a local Ollama or Hermes.

**Phase D: Kubernetes**
- [ ] `namespace.yaml`: add `audit` and `enforce-version`.
- [ ] `deployment.yaml` per §5.3: `readOnlyRootFilesystem: true`, `/tmp` emptyDir, file-mounted Secret (`defaultMode: 0440`), `enableServiceLinks: false`, `supplementalGroupsPolicy: Strict`, `TRUSTED_PROXIES`, digest pin through kustomize, `imagePullPolicy: IfNotPresent`.
- [ ] `secret.example.yaml`: add `secret_key`. Switch from `envFrom` to a volume.
- [ ] Add `networkpolicy.yaml` to `kustomization.yaml`. Add `cilium-networkpolicy.example.yaml` (not in the kustomization). Document Talos `kubeNetworkPoliciesEnabled: true` and the optional `hostUsers: false` + `SysctlConfig`.
- [ ] Make HTTPRoute the default; rename `ingress.yaml` → `ingress.example.yaml` with the retirement note.
- [ ] *`kubectl label --dry-run=server --overwrite ns kidney-health pod-security.kubernetes.io/enforce=restricted` prints no warnings. kubeconform passes. The pod starts read-only and a log entry can be saved.*

**Phase E: CI/CD supply chain**
- [ ] Pin every action in `ci.yml` to the SHAs in §3.6 (run `pinact run`, then `zizmor .github/workflows`). Set `permissions: {}` at the top and per-job grants, and `persist-credentials: false`. Download actionlint and kubeconform with a pinned `sha256sum -c`.
- [ ] `ci.yml`:
  - [ ] Tests on 3.12 and 3.14 from the lock file.
  - [ ] zizmor job.
  - [ ] PR image build with `load: true`.
  - [ ] Read-only, two-UID container smoke test.
  - [ ] Grype gate (`severity-cutoff: high`, `only-fixed: true`).
  - [ ] Build `Containerfile.debian` when `deploy/**` or the lock files change.
- [ ] Create `release.yml` (build by digest → scan matrix → sign, attest and tag) per §5.4. Remove the image job from `ci.yml`. *A push to main produces an index with amd64, arm64 and attestation manifests. `:latest` moves only after the scan job passes.*
- [ ] Gate cosign and `actions/attest` on `!github.event.repository.private`, with `create-storage-record: false`.
- [ ] Add `.github/dependabot.yml` per §5.4. Add `codeql.yml` (python, javascript-typescript, actions) and `scheduled-scan.yml`.
- [ ] Repo settings: require SHA pinning, rulesets for `main` and `v*`, immutable releases, read-only default token, GHCR package access limited to this repo, private vulnerability reporting. When going public, make the GHCR package public.

**Phase F: documentation**
- [ ] Add `SECURITY.md`: how to report (GitHub private advisories), supported versions (latest minor), the image verification commands.
- [ ] Add `docs/security.md`: the threat model (§2 condensed), the hardening defaults and why, a `TRUSTED_PROXIES` table per topology (same-host Caddy, rootless Docker, Kubernetes Gateway, tailscale serve), backup encryption, the AI data-sharing statement.
- [ ] README: new configuration keys, `_FILE` secrets, image verification, the "track `:0.3`, not `:latest`" advice. ARCHITECTURE.md: the security middleware and config contract.

---

## 8. How to re-verify

* **Action SHAs.**
  `git ls-remote --tags https://github.com/<owner>/<repo> | grep 'refs/tags/vX.Y.Z^{}'` (or
  `pinact run --update`). Confirm the commit appears on the action's own branch or tag (zizmor
  `impostor-commit`).
* **Base digests and CVEs.** `crane digest cgr.dev/chainguard/python:latest`, then
  `grype registry:<image> --platform linux/amd64` (this note used grype 0.120.0 on 2026-10-05).
* **Repo visibility.** `curl -s https://api.github.com/repos/ksullivan86/kidney-health | jq .private`.
* **Podman features.** `podman --version` and the [release notes](https://github.com/containers/podman/blob/main/RELEASE_NOTES.md).
* **Browser support.** MDN browser-compat-data `http/headers/Content-Security-Policy.json` and
  `Permissions-Policy.json`.

## 9. Sources

* Podman: [rootless tutorial](https://github.com/containers/podman/blob/main/docs/tutorials/rootless_tutorial.md) · [`--userns`](https://github.com/containers/podman/blob/main/docs/source/markdown/options/userns.container.md) · [`--secret`](https://github.com/containers/podman/blob/main/docs/source/markdown/options/secret.md) · [podman-systemd.unit(5)](https://docs.podman.io/en/latest/markdown/podman-systemd.unit.5.html) · [podman-run(1)](https://docs.podman.io/en/latest/markdown/podman-run.1.html) · [release notes](https://github.com/containers/podman/blob/main/RELEASE_NOTES.md) · [Podman 5.3 pasta changes](https://blog.podman.io/2024/10/podman-5-3-changes-for-improved-networking-experience-with-pasta/) · [Fedora Podman 6 change](https://fedoraproject.org/wiki/Changes/Podman6) · [linuxiac on Podman 6.0](https://linuxiac.com/podman-6-0-lands-with-breaking-changes-amd-gpus-support/) · [cgroup v2 delegation](https://rootlesscontaine.rs/getting-started/common/cgroup2/) · [containers-policy.json(5)](https://github.com/containers/container-libs/blob/main/image/docs/containers-policy.json.5.md)
* Docker: [rootless mode](https://docs.docker.com/engine/security/rootless/) · [rootless troubleshooting and limitations](https://docs.docker.com/engine/security/rootless/troubleshoot/) · [compose secrets](https://docs.docker.com/compose/how-tos/use-secrets/) · [GHA attestations](https://docs.docker.com/build/ci/github-actions/attestations/) · [build-push-action](https://github.com/docker/build-push-action) · [Hardened Images free](https://www.docker.com/blog/docker-hardened-images-for-every-developer/) · [DHI quickstart](https://docs.docker.com/dhi/get-started/) · [DHI use](https://docs.docker.com/dhi/how-to/use/) · [python official image](https://hub.docker.com/_/python) · [python Dockerfile 3.14 slim-trixie](https://github.com/docker-library/python/blob/master/3.14/slim-trixie/Dockerfile)
* Base images: [Chainguard python](https://images.chainguard.dev/directory/image/python/overview) · [Chainguard tags & EOL](https://support.chainguard.dev/hc/en-us/articles/49563564450075-How-Chainguard-Image-Tags-Versions-and-EOL-Work) · [distroless](https://github.com/GoogleContainerTools/distroless) · [Python versions](https://devguide.python.org/versions/) · [PEP 790](https://peps.python.org/pep-0790/) · [Python 3.15.0rc3](https://www.python.org/downloads/release/python-3150rc3/)
* Kubernetes and Talos: [Pod Security Standards](https://kubernetes.io/docs/concepts/security/pod-security-standards/) · [user namespaces](https://kubernetes.io/docs/concepts/workloads/pods/user-namespaces/) · [UserNamespacesSupport gate](https://github.com/kubernetes/website/blob/main/content/en/docs/reference/command-line-tools-reference/feature-gates/UserNamespacesSupport.md) · [Talos pod security](https://docs.siderolabs.com/kubernetes-guides/security/pod-security) · [Talos user namespaces](https://docs.siderolabs.com/kubernetes-guides/security/usernamespace) · [Talos Flannel NetworkPolicy](https://docs.siderolabs.com/kubernetes-guides/cni/flannel) · [Talos support matrix](https://docs.siderolabs.com/talos/v1.13/getting-started/support-matrix) · [ingress-nginx retirement](https://kubernetes.io/blog/2025/11/11/ingress-nginx-retirement/)
* Supply chain: [GitHub Actions secure use](https://docs.github.com/en/actions/reference/security/secure-use) · [Dependabot options](https://docs.github.com/en/code-security/dependabot/working-with-dependabot/dependabot-options-reference) · [dependabot-core docker parser](https://github.com/dependabot/dependabot-core/blob/main/docker/lib/dependabot/docker/file_parser.rb) · [actions/attest](https://github.com/actions/attest) · [attest-build-provenance](https://github.com/actions/attest-build-provenance) · [actions/checkout changelog](https://github.com/actions/checkout/blob/main/CHANGELOG.md) · [cosign signing](https://docs.sigstore.dev/cosign/signing/signing_with_containers/) · [cosign verify](https://docs.sigstore.dev/cosign/verifying/verify/) · [CodeQL](https://docs.github.com/en/code-security/code-scanning/introduction-to-code-scanning/about-code-scanning-with-codeql) · [Trivy incident (Aqua)](https://www.aquasec.com/blog/trivy-supply-chain-attack-what-you-need-to-know) · [Trivy incident (Wiz)](https://wiz.io/blog/trivy-compromised-teampcp-supply-chain-attack) · [pip-tools on PyPI](https://pypi.org/project/pip-tools/) · [uv on PyPI](https://pypi.org/project/uv/)
* App: [uvicorn settings](https://github.com/encode/uvicorn/blob/main/docs/settings.md) · [uvicorn proxies](https://github.com/encode/uvicorn/blob/main/docs/deployment/index.md) · [MDN browser-compat-data](https://github.com/mdn/browser-compat-data) (CSP, Permissions-Policy, Sec-Fetch-Site, BarcodeDetector, getUserMedia)

---

## 10. Security review (2026-10-05)

A second pass over this note together with notes [03](03-barcode-and-photo.md),
[04](04-optional-ai.md) and [07](07-accounts-settings-secrets.md), read against the code
(`app/main.py`, `app/foods.py`, `app/log.py`) and re-checked against primary sources. Each finding
has a required change. Text above that the review corrected says so where it was changed.

### 10.1 Corrected in place

| Where | Was | Now |
|---|---|---|
| §3.1 pasta | "connections from host loopback normally arrive as loopback" | They arrive from the container's **own** address (passt(1); Podman keeps `--host-lo-to-ns-lo` off because of [CVE-2021-20199](https://nvd.nist.gov/vuln/detail/CVE-2021-20199)). |
| §3.7, §5.5 CSP | `trusted-types 'none'`; `'wasm-unsafe-eval'` only "if" | `trusted-types kh-sw` with one policy for `/sw.js` (S3); `'wasm-unsafe-eval'` included because note 03 chose the WASM decoder. CSP test compares whole tokens. |
| §5.1 dependencies | `python-multipart`, `argon2-cffi` | Neither: raw-body uploads (note 03), Argon2id from `cryptography` (note 07). |
| §5.5 body limit, config | `request.form(...)`, `MAX_UPLOAD_BYTES` 10 MiB | Raw `image/jpeg` body, `MAX_IMAGE_BYTES` 4 MiB, header check (S5). |
| §5.5 config | `SECRET_KEY` "signs sessions" | Encrypts stored keys only; sessions are opaque (note 07). Default file location flagged as inside volume backups. |
| §2.4 row 14, §5.5 rules | `ALLOW_PRIVATE_AI_HOSTS=true` | Note 04 R5 `AI_PRIVATE_HOSTS` allowlist; the boolean is refused at start-up. |
| §5.2 Quadlet, §5.3 Kubernetes | `TRUSTED_PROXIES` defaults presented as safe | Comments explain the pasta address and that a pod CIDR trusts every pod (S2). |

### 10.2 Findings and required changes

| ID | Severity | Finding | Required change |
|---|---|---|---|
| S1 | **High** | **DNS rebinding.** No note validates `Host`. A page on `attacker.example` whose name re-resolves to `192.168.1.10` (or `127.0.0.1`) is same-origin with the app as far as the browser knows: `Origin` equals `Host` (`attacker.example:8000`), `Sec-Fetch-Site` is `same-origin`, custom headers are allowed. With `AUTH_MODE=none` it reads every log and rewrites potassium targets (asset A2). On the owner's desktop in proxy mode it can send `Remote-User: admin` from a trusted peer. In local mode it can brute-force the login or try setup codes from inside the LAN. Chrome 141+ asks before public-to-local requests ([Local Network Access](https://developer.chrome.com/blog/local-network-access)); Safari on iOS, the target platform, does not. | `HostAllowlistMiddleware`, directly after peer capture: `ALLOWED_HOSTS` (comma list, `*.example.org` wildcards). Default: `localhost`, any IP literal (v4 or bracketed v6) and the host of `PUBLIC_URL` (S4). IP literals are safe because rebinding needs a DNS name. Anything else gets `400 {"detail": "Unknown host"}` and one WARNING log line naming the host to add. Starlette's `TrustedHostMiddleware` cannot express "any IP literal", so write the ~30 lines. Tests: `Host: evil.example` → 400 on `/`, `/api/profile` and `/sw.js`; `Host: 192.168.1.10:8000` and a kubelet probe with the pod IP pass. |
| S2 | **High** | **Proxy trust depends on the engine, and the shipped defaults are wrong.** Rootless Podman with pasta shows host-local clients (Caddy, but also every other process on the host) as the container's own address. Podman 4.9 with slirp4netns + rootlesskit shows **every** client, LAN included, as `10.0.2.100`. Rootless Docker without source-IP propagation shows every client as the RootlessKit gateway. The Kubernetes example trusts the whole pod CIDR while Talos' default Flannel ignores NetworkPolicy. Consequences: (a) the identity header (`Remote-User`) is forgeable by any process on the host, including a Hermes agent with a terminal tool after a prompt injection, or by any pod; (b) the per-IP login limiter of note 07 keyed on that one address becomes an instance-wide lock-out that one attacker triggers. uvicorn's `ProxyHeadersMiddleware` itself is sound: it takes the right-most untrusted `X-Forwarded-For` entry and ignores `X-Forwarded-Host` ([source](https://github.com/encode/uvicorn/blob/master/uvicorn/middleware/proxy_headers.py)). | (1) New `TRUSTED_PROXY_SECRET_FILE`. When set, `X-Forwarded-*` and identity headers count only if `X-Proxy-Secret` matches (`hmac.compare_digest`) **and** the peer is in `TRUSTED_PROXIES`; the header is removed before the app sees the request. Caddy `header_up X-Proxy-Secret {$KH_PROXY_SECRET}`, Traefik `headers.customRequestHeaders`, nginx `proxy_set_header`. (2) `AUTH_MODE=proxy` refuses to start without it, unless `TRUSTED_PROXY_SECRET_OPTIONAL=true` (for `tailscale serve`, which cannot add headers) with a startup warning. (3) Log the peer address of the first request that carries `X-Forwarded-For`, and show it on Admin → About. (4) `docs/security.md` gets a per-topology table: pasta → the container's own IPv4/IPv6; slirp4netns → `10.0.2.100` for everyone, so use `Network=pasta` (needs the `passt` package on Ubuntu 24.04) or no proxy mode; rootless Docker → the RootlessKit gateway unless propagation is on; Kubernetes → the pod CIDR only with enforced NetworkPolicy or the secret. (5) Per-IP limits never key on a proxy or gateway address (note 07 §9 N3). |
| S3 | **High** | **Trusted Types `'none'` breaks the PWA.** MDN lists `ServiceWorkerContainer.register()` and the `Worker()` URL as `TrustedScriptURL` sinks ([MDN](https://developer.mozilla.org/en-US/docs/Web/API/Trusted_Types_API)), and Safari 26 enforces Trusted Types. Note 02's `navigator.serviceWorker.register('/sw.js')` would throw on iOS 26 and in Chrome, and the likely "fix" under time pressure is deleting the whole Trusted Types line. | Fixed in §5.5: `trusted-types kh-sw` and a policy whose `createScriptURL` returns only `/sw.js`. Feature-detect `window.trustedTypes`. No `'allow-duplicates'`, no `default` policy. Playwright on Chromium and WebKit: the service worker registers and the console shows no CSP or Trusted Types violation. |
| S4 | Medium | **`PUBLIC_URL` is missing.** Because only `X-Forwarded-For`/`-Proto` are honoured, the CSRF origin check compares `Origin` with the raw `Host`. A proxy that rewrites `Host` (Traefik `passHostHeader: false`, nginx `proxy_set_header Host upstream`) makes every write 403, and operators then disable the check. Invite and reset links and the setup-code log line would be built from `Host`. | `PUBLIC_URL` (for example `https://kidney.example.org`). When set, `Origin` must equal its origin exactly, its host joins `ALLOWED_HOSTS`, and every absolute URL the server prints (invites, reset links, the first-run line) comes from it, never from `Host`. When unset, the client builds invite links from `location.origin`. |
| S5 | Medium | **Upload handling was split three ways** (note 01 multipart 10 MiB, note 03 raw 4 MiB JPEG, note 04 multipart 2 MiB JPEG/PNG), and "the server does not decode the image" was treated as the whole defence. The bytes still reach the AI backend's C/C++ image code: a public proof of concept reports a stack overflow in llama.cpp's `mtmd/clip.cpp` from a 52800×44 image ([PoC page](https://huggingface.co/igfray/minicpmv-bucket-coords-stack-overflow-poc)), and a 4 MiB JPEG can declare 65535×65535 pixels. The client's canvas step cannot be trusted. | One shared `app/imagecheck.py` (pure Python, no decoder) used by every photo route: `Content-Type: image/jpeg`, `Content-Length` ≤ `MAX_IMAGE_BYTES` before reading, streaming cap while reading, SOI magic, walk the marker segments, exactly one SOF0/1/2 frame with 1 or 3 components, 16 ≤ width, height ≤ 2048, aspect ratio ≤ 4:1, ≤ 4 megapixels; drop APP1–APP15 and COM segments (EXIF, GPS, XMP, ICC, maker notes, thumbnails) and anything after EOI; forward only the rewritten bytes; never write them to disk or logs. Route-level Starlette `max_body_size`. Tests: a GPS-tagged JPEG comes out without APP1; 52800×44, 65535×65535, a PNG and a JPEG with trailing ZIP data are refused. Details in note 04 §9 A4 and note 03 §9 B1. |
| S6 | Medium | **Container escape surface outside this image.** Nothing forbids mounting the Podman or Docker socket (Watchtower-style updaters do), which hands a compromised container your host account. The Ollama overlay of note 04 R10 runs the upstream image as root inside its namespace with only `no-new-privileges`, and it now parses attacker-influenced images (S5). | `docs/security.md`: never mount `podman.sock`/`docker.sock` into this or any helper container; update with Quadlet `AutoUpdate=registry` or Kubernetes digests. Quadlet: `Volume=kidney-health.volume:/data:noexec,nosuid,nodev` and `Tmpfs=/tmp:rw,noexec,nosuid,nodev,size=64m` (Podman supports these volume options). Ollama overlay: `cap_drop: [ALL]`, `security_opt: [no-new-privileges:true]`, `pids_limit: 256`, `mem_limit` sized to the model, digest-pinned image, no `ports:`, and once models are pulled an `internal: true` network shared only with kidney-health. |
| S7 | Medium | **`:latest` moves on every push to main** (`release.yml` triggers on main and `v*`). A merged malicious or mistaken PR reaches every homelab that auto-updates `:latest` within hours. | Pushes to main publish `:edge` and the digest only. `:latest`, `:0.3` and `:0.3.x` move only on `v*` tags created under the tag ruleset (signed and attested once public). README and Quadlet examples track `:0.3`. |
| S8 | Medium | **Auto-generated `/data/secret.key` is inside every volume-level backup**, so "encryption at rest" of stored keys gives nothing against the most common leak (a backup). | Already in the corrected config row: every shipped profile (Quadlet `Secret=`, compose `secrets:`, Kubernetes Secret) provisions `SECRET_KEY_FILE`; the auto-generated file stays a fallback with a startup WARNING and an About-page warning. |
| S9 | Low | uvicorn bounds nothing by default under a connection flood. | Add `--limit-concurrency 64` (503 beyond) to the image `CMD`; keep `--timeout-keep-alive 5` (default). |

### 10.3 Checks that passed

* Rootless default user namespace, non-root UID 10001, read-only root, `cap_drop ALL`,
  `no-new-privileges`, seccomp `RuntimeDefault`, no shell or package manager at runtime, root-owned
  code: a sound baseline. Recommending against `keep-id` is right.
* SHA-pinned actions, `permissions: {}`, scanners in jobs without write scopes, tags moved only after
  the scan: right, with S7 on top.
* `Sec-Fetch-*` headers are only sent to potentially trustworthy URLs, as note 07 assumes
  ([Fetch Metadata](https://www.w3.org/TR/fetch-metadata/)), so plain-HTTP LAN setups rely on the
  `Origin` check plus note 07's custom header.

### 10.4 Implementation checklist additions

- [ ] `app/security.py`: `HostAllowlistMiddleware` (S1) after peer capture; `ALLOWED_HOSTS`, `PUBLIC_URL` in `app/config.py` (S4). *Tests as in S1 and S4.*
- [ ] `TRUSTED_PROXY_SECRET_FILE` and `TRUSTED_PROXY_SECRET_OPTIONAL`; strip `X-Proxy-Secret`; refuse `AUTH_MODE=proxy` without it; log the first forwarded peer (S2). *Tests: correct peer + wrong secret → headers ignored; right secret + untrusted peer → ignored.*
- [ ] `docs/security.md`: the per-topology `TRUSTED_PROXIES` table (S2), socket and auto-updater warning (S6), backup and `SECRET_KEY_FILE` guidance (S8).
- [ ] `app/imagecheck.py` shared by notes 03 and 04 (S5).
- [ ] Quadlet/compose: `noexec,nosuid,nodev` on `/data` where supported; Ollama overlay hardening (S6).
- [ ] `release.yml`: `:edge` from main; `:latest`/`:0.3` from `v*` tags only (S7).
- [ ] Image `CMD`: `--limit-concurrency 64` (S9).

### 10.5 Sources checked for this review

[passt(1)](https://passt.top/passt/plain/passt.1) ·
[Podman `--network`](https://github.com/containers/podman/blob/main/docs/source/markdown/options/network.md) ·
[CVE-2021-20199](https://nvd.nist.gov/vuln/detail/CVE-2021-20199) ·
[uvicorn `proxy_headers.py`](https://github.com/encode/uvicorn/blob/master/uvicorn/middleware/proxy_headers.py) ·
[MDN Trusted Types API](https://developer.mozilla.org/en-US/docs/Web/API/Trusted_Types_API) ·
[Fetch Metadata](https://www.w3.org/TR/fetch-metadata/) ·
[Chrome Local Network Access](https://developer.chrome.com/blog/local-network-access) ·
[Starlette release notes](https://github.com/Kludex/starlette/blob/main/docs/release-notes.md) (1.6.0 `max_body_size`) ·
[llama.cpp mtmd PoC](https://huggingface.co/igfray/minicpmv-bucket-coords-stack-overflow-poc)
