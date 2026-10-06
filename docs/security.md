# Security guide for operators

This guide is for the person who runs kidney-health for themselves or their household. It explains
what the app protects, which defaults do the protecting, what you must still do yourself, and how
to check each runtime. The design behind it is in
[`docs/dev/research/01-rootless-and-security.md`](dev/research/01-rootless-and-security.md)
(sections 2, 5 and 10) and [`07-accounts-settings-secrets.md`](dev/research/07-accounts-settings-secrets.md).
How to report a vulnerability, and how to verify an image before you run it, is in
[`SECURITY.md`](../SECURITY.md).

Contents:

1. [What is at stake](#1-what-is-at-stake)
2. [Threat model in one table](#2-threat-model-in-one-table)
3. [The defaults and why](#3-the-defaults-and-why)
4. [Proxy trust: `TRUSTED_PROXIES` per topology](#4-proxy-trust-trusted_proxies-per-topology)
5. [Checklists: rootless Podman, rootless Docker, Kubernetes](#5-checklists)
6. [Secrets, the `SECRET_KEY` and backups](#6-secrets-the-secret_key-and-backups)
7. [Never mount the container engine's socket](#7-never-mount-the-container-engines-socket)
8. [Optional features that send data out](#8-optional-features-that-send-data-out)
9. [Supply chain: what CI guarantees](#9-supply-chain-what-ci-guarantees)
10. [Accepted residual risks](#10-accepted-residual-risks)

## 1. What is at stake

| Asset | Why it matters |
|---|---|
| **Health data**: kidney disease stage, dialysis schedule, diabetes type, weight, every meal | Special-category personal data about patients. |
| **Integrity of targets and food values** | A tampered potassium target or food value can lead to an unsafe meal (for example high potassium on dialysis). This is a **safety** asset, not only a privacy one. |
| **API keys** (USDA, an AI provider) | Theft costs money or misuses your AI agent. |
| **Passwords and sessions** | Account takeover leads to everything above. |
| **Your host** | A container escape must never land as root, or as your own user. |
| **Backups** | They contain all of the above. |

## 2. Threat model in one table

| Who | Can do | Main defences |
|---|---|---|
| Internet attacker | Reaches the app only if you expose it | Publish on `127.0.0.1` only; HTTPS proxy in front; local accounts with NIST password rules and throttling; Host allowlist |
| A device on your LAN | Hits published ports, sniffs plain HTTP, tries CSRF or DNS rebinding through your browser | Loopback publishing, HTTPS, `Sec-Fetch-Site`/`Origin` checks plus a required `X-Requested-With` header, the Host allowlist (`ALLOWED_HOSTS`, `PUBLIC_URL`) |
| Another household user | Has a valid account; tries to read your log or your keys | Every query is scoped to the signed-in user; "not yours" answers 404; keys are write-only (the API shows only `•••• last4`) |
| Hostile upstream data (Open Food Facts, AI output) | Injects script or prompt text | Strict CSP with no inline script, Trusted Types, text-only rendering; AI gets no tools and its output never triggers writes |
| Supply-chain attacker | Compromises a package, an action or a base image | Hash-locked wheels, digest-pinned bases, SHA-pinned actions, Grype gate, signed images (section 9) |
| Code running inside the container | Tries to escape or move sideways | Rootless engine, non-root UID 10001, no capabilities, no-new-privileges, seccomp, read-only root, no shell, NetworkPolicy |
| A lost phone | Holds a session and cached pages | Session idle timeout, sign-out clears site data, the service worker never caches `/api/*`, `Cache-Control: no-store` |

## 3. The defaults and why

Every shipped profile (Quadlet, compose, the Docker example, Kubernetes) applies the same baseline.
Do not remove a line unless you understand what it stops.

| Default | What it stops |
|---|---|
| **Rootless engine, default user namespace** (never `keep-id`) | Container UID 10001 is an unused subordinate UID on the host. An escape lands as a user that owns nothing, not as root and not as you. `keep-id` would make the app *you* on the host (your `~/.ssh`, your other containers). |
| **UID 10001, no shell, no pip, no package manager** in the image (Chainguard Python) | An attacker with code execution has no tools to work with and nothing to escalate with. The Debian fallback image keeps a shell but has no pip and no setuid binaries. |
| **Code owned by root, read-only root filesystem**, tmpfs `/tmp` | A compromised process cannot rewrite the app to persist. Only `/data` is writable. |
| **`cap_drop: ALL`, `no-new-privileges`, default seccomp**, SELinux `container_t` | The process has no kernel privileges and cannot gain any. |
| **Memory 512 MiB, PIDs 128** | A request flood or a bug cannot take the host down with it. |
| **Publish on `127.0.0.1` only** | LAN devices cannot bypass your HTTPS proxy and its login by talking to port 8000 directly. |
| **Secrets as files** (`*_FILE`), never env vars | Env vars leak through `inspect`, `/proc/<pid>/environ`, child processes and crash dumps. |
| **uvicorn `--no-proxy-headers`**; the app trusts `X-Forwarded-*` only from `TRUSTED_PROXIES` | Clients cannot fake their address (to dodge rate limits) or fake HTTPS. |
| **Host allowlist**: localhost, IP literals, the `PUBLIC_URL` host and `ALLOWED_HOSTS` | DNS rebinding: a web page whose name re-resolves to your server would otherwise be "same-origin" with the app. Unknown names get `400 Unknown host` and one log line naming the host to add. |
| **Security headers** on every response: strict CSP, `frame-ancestors 'none'`, Trusted Types, `nosniff`, `no-referrer`, COOP/CORP; HSTS over HTTPS | Script injection, clickjacking, referrer leaks. |
| **`--limit-concurrency 64`**, `MAX_BODY_BYTES` 1 MiB, photos `MAX_IMAGE_BYTES` 4 MiB with a header check | Connection floods and oversized bodies. |
| **Local accounts by default** (`AUTH_MODE=local`) with a one-time setup code | No "first visitor becomes admin" race. Passwords of at least 15 characters (NIST SP 800-63B-4), Argon2id, throttling. |

## 4. Proxy trust: `TRUSTED_PROXIES` per topology

`TRUSTED_PROXIES` lists the addresses whose `X-Forwarded-For`/`-Proto` (and, in `AUTH_MODE=proxy`,
the identity header) the app believes. The right value depends on **what source address the
container engine shows the app**, and rootless engines do surprising things. Getting it wrong in the
"too wide" direction lets anyone forge their address or, in proxy mode, their identity. Getting it
wrong in the "too narrow" direction is safe: proxy headers are ignored and everyone appears to come
from the proxy (rate limits then key on the proxy, which the app detects and skips).

**Find the address the app sees, do not guess it.** Open the app once through your proxy, then read
the access log (`journalctl --user -u kidney-health`, `podman logs kidney-health`, `docker logs
kidney-health` or `kubectl logs deploy/kidney-health`). Each line starts with the TCP peer, for
example `INFO:     10.88.0.5:51234 - "GET / HTTP/1.1" 200`. Put that address in `TRUSTED_PROXIES`
and restart. The app then logs `first request with X-Forwarded-For came from trusted proxy …`, and
Admin → About shows it, together with a counter of identity headers ignored from untrusted peers
(a non-zero counter in proxy mode means `TRUSTED_PROXIES` or the proxy secret is wrong).

| Topology | What the app sees as the peer | `TRUSTED_PROXIES` |
|---|---|---|
| Rootless **Podman with pasta** (default since Podman 5), proxy on the **same host** connecting to `127.0.0.1:8000` | The container's **own** IPv4/IPv6 address, not `127.0.0.1` (pasta maps host loopback that way on purpose; CVE-2021-20199). Every other process on the host looks the same. | That address, from the log. Because any local process shares it, use `AUTH_MODE=local`, or in proxy mode **require** `TRUSTED_PROXY_SECRET_FILE`. |
| Rootless Podman with **slirp4netns** (Podman 4.x default) | `10.0.2.100` for **every** client, LAN included | Do not trust anything: use `Network=pasta` (Ubuntu 24.04: install `passt`) or leave the default and do not use proxy mode. |
| Rootless **Docker** without source-IP propagation (the default) | The RootlessKit/bridge gateway (for example `172.17.0.1`) for **every** client, including a proxy on the same host | **No proxy:** leave the loopback default. **An HTTPS proxy on the same host** (Caddy or nginx on the host, `tailscale serve`): that gateway address, from the log. Otherwise the app ignores the proxy's `X-Forwarded-Proto: https`: cookies lose `Secure`, no HSTS, and once a second account exists every sign-in fails with `https_required`. It is safe only while the port is published on `127.0.0.1` (only local processes reach it); in proxy mode also require `TRUSTED_PROXY_SECRET_FILE`. Or use the `compose.caddy.yaml` overlay (container to container). Propagation needs RootlessKit ≥ 3.0 with `"userland-proxy": false`, or `DOCKERD_ROOTLESS_ROOTLESSKIT_NET=pasta` + `..._PORT_DRIVER=implicit`. |
| Proxy in the **same compose network** (`deploy/compose.caddy.yaml`) | The proxy container's address on that network | That one address (the overlay pins Caddy to `172.31.86.10`). |
| **Kubernetes** Gateway / ingress controller | The controller pod's IP | The controller's pod range, as narrow as you can. A whole pod CIDR trusts **every pod** in the cluster: only acceptable while `networkpolicy.yaml` is enforced, or with `TRUSTED_PROXY_SECRET_FILE`. |
| **`tailscale serve`** on the same host | As for pasta (same host) | As for pasta. `tailscale serve` cannot add a secret header, so proxy mode needs `TRUSTED_PROXY_SECRET_OPTIONAL=true` and the app logs a warning. |
| No proxy (a trial on a trusted LAN) | The real client | Leave the default. Phones need HTTPS for the camera and offline mode anyway ([`https.md`](https.md)). |

**`AUTH_MODE=proxy`** (Authelia, Authentik, `tailscale serve`) trusts an identity header such as
`Remote-User`. It refuses to start unless `TRUSTED_PROXY_SECRET_FILE` is set: a long random value
that your proxy sends as `X-Proxy-Secret` (Caddy `header_up X-Proxy-Secret {env.KH_PROXY_SECRET}`,
Traefik `headers.customRequestHeaders`, nginx `proxy_set_header`). The app compares it in constant
time and strips it before anything else sees the request. `TRUSTED_PROXIES` containing `0.0.0.0/0`
or `::/0` is refused outright in proxy mode.

## 5. Checklists

Tick every line before you put real health data in the app.

### Rootless Podman (Quadlet, recommended for one host)

- [ ] `podman info --format '{{.Host.Security.Rootless}}'` prints `true`.
- [ ] `/etc/subuid` and `/etc/subgid` have at least 65 536 IDs for your user.
- [ ] `podman top kidney-health user huser` shows `10001` and a **subordinate** UID, never your own UID.
- [ ] No `UserNS=keep-id` (development only). `UserNS=auto` is fine as an advanced option.
- [ ] `podman inspect kidney-health --format '{{.HostConfig.ReadonlyRootfs}} {{.HostConfig.CapDrop}}'` shows `true` and every capability.
- [ ] `PublishPort=127.0.0.1:...`, never `0.0.0.0`.
- [ ] `SECRET_KEY_FILE` comes from `podman secret` (`Secret=` line), not from `/data/secret.key`.
- [ ] `Network=pasta`; `TRUSTED_PROXIES` set from the logged peer address (section 4).
- [ ] `PUBLIC_URL` set to the URL people type; HTTPS in front ([`https.md`](https.md)).
- [ ] SELinux hosts: enforcing, no `SecurityLabelDisable`; bind mounts use `:Z`.
- [ ] `loginctl enable-linger` for the user; `podman-auto-update.timer` enabled if you track `:0.3`.
- [ ] No Podman socket mounted into any container (section 7).

### Rootless Docker

- [ ] `docker info` lists `name=rootless` under Security Options.
- [ ] `docker info` shows cgroup v2 with systemd; otherwise `--memory` and `--pids-limit` are ignored silently.
- [ ] Published on `127.0.0.1` only; `TRUSTED_PROXIES` at the loopback default without a proxy, or the logged gateway address when an HTTPS proxy on the same host connects to it (section 4).
- [ ] Secret files: `0644` inside a `0700` directory (your UID is container root, so `0600` would be unreadable for UID 10001).
- [ ] `--read-only` together with `--tmpfs /tmp` (Docker does not add `/tmp` itself).
- [ ] No AppArmor under rootless Docker: the remaining layers (user namespace, seccomp, no capabilities) carry the load.
- [ ] No Docker socket mounted into any container.

### Kubernetes (Talos)

- [ ] Namespace labels `pod-security.kubernetes.io/enforce: restricted` (and `audit`, `warn`); `kubectl label --dry-run=server --overwrite ns kidney-health pod-security.kubernetes.io/enforce=restricted` prints no warnings.
- [ ] Pod: `automountServiceAccountToken: false`, `enableServiceLinks: false`, `runAsNonRoot`, UID/GID 10001, seccomp `RuntimeDefault`.
- [ ] Container: `allowPrivilegeEscalation: false`, `readOnlyRootFilesystem: true`, `capabilities.drop: [ALL]`, `/tmp` as an `emptyDir`.
- [ ] Secret mounted as files (`defaultMode: 0440`), never `envFrom`.
- [ ] `networkpolicy.yaml` applied **and enforced**: Talos' default Flannel ignores NetworkPolicy unless `kubeNetworkPoliciesEnabled: true`. Test it (`docs/deployment.md`).
- [ ] Ingress only from your Gateway namespace; egress only DNS and public 443 (or the Cilium FQDN example).
- [ ] Image pinned by digest in `kustomization.yaml` after `scripts/verify-image.sh`; `imagePullPolicy: IfNotPresent`.
- [ ] `TRUSTED_PROXIES` narrowed to the Gateway's pods where possible (section 4).
- [ ] Optional: `hostUsers: false` (Kubernetes ≥ 1.36, idmap-capable storage, Talos `SysctlConfig`).

## 6. Secrets, the `SECRET_KEY` and backups

* **Every secret is a file.** The app reads `SECRET_KEY_FILE`, `USDA_API_KEY_FILE`,
  `ADMIN_PASSWORD_FILE`, `TRUSTED_PROXY_SECRET_FILE` and the AI keys' `*_FILE` variants. Setting both
  `NAME` and `NAME_FILE` is a start-up error; an empty file means "unset"; trailing newlines are
  stripped.
* **Keys you set on the server are locked.** The UI shows them as "set by server"; nobody can read or
  change them through the API.
* **`SECRET_KEY` encrypts the API keys stored in the database** (Fernet under HKDF-derived keys). It
  does not sign sessions; those are opaque server-side tokens. One key per line, at least 32
  characters; the first line is current.
* **Mount `SECRET_KEY_FILE` from your engine's secret store.** Without it the app generates
  `/data/secret.key` and warns at every start and on Admin → About, because that file sits **on the
  data volume**: every volume-level backup (restic or borg of the volume, a PVC snapshot, `podman
  volume export`) would then contain the database *and* its key.
* **Back up with `python -m app.admin backup`**, which writes a consistent SQLite copy without the
  key (commands per runtime in [`deployment.md`](deployment.md#backups-and-restore)). Then:
  * encrypt the backup (restic, borg or age) and keep it `0600`; it holds everyone's health data,
    password hashes and the audit log;
  * back the `SECRET_KEY` up **separately** (a password manager). Restoring without it loses only
    the stored API keys, never health data or passwords.
* **Rotate** with `python -m app.admin rotate-secret-key` (auto-generated key) or, with a mounted
  key: add a new first line, restart, `python -m app.admin reencrypt`, remove the old line, restart.
* The automatic `kidney.db.pre-v3.bak` (taken before the v0.3 accounts migration) holds every v0.2
  meal. It is deleted 30 days after a successful migration; Admin → About shows while it exists.

## 7. Never mount the container engine's socket

Mounting `podman.sock` or `docker.sock` into **any** container (Watchtower-style auto-updaters,
dashboards, "management" tools) hands that container your whole account on the host, and a rootful
socket hands it root. Update kidney-health with Quadlet's `AutoUpdate=registry` plus
`podman-auto-update.timer`, or with pinned digests on Kubernetes.

The optional Ollama overlay (`deploy/compose.ai-ollama.yaml`) follows the same rule: all
capabilities dropped, `no-new-privileges`, pids and memory limits, a digest-pinned image, no
published port, and an `internal` network shared only with kidney-health.

## 8. Optional features that send data out

The app makes **no** outbound request until you turn a feature on. The full list of hosts is in
[`network-allowlist.md`](network-allowlist.md).

| Feature | Off by default? | What leaves the server |
|---|---|---|
| USDA FoodData Central search | Yes (needs a key) | Your search words, with the key in a header (never in a URL or a log). |
| Open Food Facts barcode lookup | Yes (`food.off_enabled=false`; Settings or the setup screen) | The barcode number only. |
| Optional AI (OpenAI, OpenRouter, Nous Portal, a local Ollama or Hermes) | Yes (`AI_ENABLED=false`, then per-person opt-in with a consent text naming the provider) | Only the fields the feature needs, shown to the person before sending. Prefer a local model. AI calls never use tools, and the rules engine checks every suggestion. |
| Breached-password check | Yes (`PASSWORD_BREACH_CHECK=false`) | The first 5 hex characters of the password's SHA-1 (k-anonymity). |

AI base URLs pass an SSRF filter: private, loopback and link-local addresses are reachable only
through the env-only `AI_PRIVATE_HOSTS` allowlist (for example `ollama:11434`), every resolved address
is validated and pinned, and redirects are not followed. On Kubernetes the egress NetworkPolicy is a
second layer.

## 9. Supply chain: what CI guarantees

* **Dependencies**: `requirements.lock` pins every package with SHA-256 hashes; the image installs
  with `--require-hashes --only-binary=:all:`, so no build script from a source package ever runs.
* **Base images**: pinned by digest (`FROM …@sha256:`); Dependabot bumps builder and runtime
  together; a daily check because digests carry security fixes.
* **Actions**: every `uses:` is pinned to a full commit SHA (a test fails otherwise), every workflow
  starts with `permissions: {}`, checkouts do not keep credentials, and there is no
  `pull_request_target`. zizmor audits the workflows on every push, including impostor commits.
  Downloaded tools (actionlint, hadolint, kubeconform, kustomize) are checked against a pinned SHA-256.
* **Scanning**: Grype fails the build on High or Critical vulnerabilities **with a fix available**,
  on pull requests (amd64) and before any tag moves (amd64 and arm64). A weekly scan of the
  published `:latest` and `:edge` prints the full report and opens an issue on a new fixable High.
* **Tags**: pushes to `main` publish `:edge` and `:sha-<short>` only. `:latest`, `:0.3` and `:0.3.x`
  move only on a `v*` tag, after the scan passed. **Track `:0.3` (or a verified digest), never
  `:latest` or `:edge` on a machine you care about.**
* **Signing and provenance**: buildx records SLSA provenance (`mode=max`) and an SBOM in the image
  index. Once the repository is public, release.yml also signs the index keylessly with cosign and
  adds GitHub-signed provenance and SBOM attestations; `scripts/verify-image.sh` checks all of them.
  While the repository is private these steps are skipped (GitHub does not offer attestations or
  CodeQL to private repositories on Free/Pro plans). Podman cannot enforce GitHub keyless signatures
  at pull time (`policy.json` needs a `subjectEmail`), so verify before you pin.
* **CodeQL** (Python, JavaScript, workflows) runs on pull requests and weekly once the repository is
  public; until then zizmor and actionlint cover the workflows and Grype covers the image.

## 10. Accepted residual risks

* The database encryption key lives next to the data in a single-container design, so encryption
  at rest protects against a leaked database file or `app.admin` backup, not against someone who
  holds both the volume and the key.
* An egress rule of "any public address on port 443" still allows exfiltration to any HTTPS host;
  the Cilium FQDN example closes that on Kubernetes. Rootless Podman has no simple per-container
  egress allowlist.
* NetworkPolicy is a no-op on Talos' default Flannel until you enable it.
* A kernel zero-day that escapes a user namespace is out of scope; the subordinate-UID mapping limits
  what it can reach.
* Auto-update trusts whoever controls the tag you track; signing, tag rulesets and the `:0.3`
  advice reduce, but do not remove, that risk.
