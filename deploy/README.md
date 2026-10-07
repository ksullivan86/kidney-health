# Deployment assets

Everything here assumes a **rootless** engine and the hardened defaults described in
[`docs/security.md`](../docs/security.md). Step-by-step instructions, first-run setup, backups and
upgrades: [`docs/deployment.md`](../docs/deployment.md). HTTPS for phones: [`docs/https.md`](../docs/https.md).

| Path | Use |
|---|---|
| `Containerfile` | The published image: Chainguard Python by digest, hash-locked wheels, root-owned read-only code, no shell or pip, UID 10001. Build from the repo root: `podman build --format docker -f deploy/Containerfile -t kidney-health:local .` |
| `Containerfile.debian` | Fallback on `python:3.14-slim-trixie` (keeps `/bin/sh` for debugging; no pip, no setuid). Built and smoke-tested by CI, not published. |
| `quadlet/` | systemd Quadlet units for rootless Podman (recommended on one host): auto-start, auto-update, `Secret=` files |
| `compose.yaml`, `.env.example`, `secrets/` | podman-compose / docker compose; secrets are files in `secrets/` (git-ignored) |
| `compose.caddy.yaml`, `caddy/` | Optional overlay: Caddy with a DNS-01 wildcard certificate (HTTPS tier 1) |
| `compose.ai-ollama.yaml` | Optional overlay: a local Ollama on an internal network, for the optional AI features |
| `docker-rootless-run.sh` | The same hardening as plain `docker run` flags for rootless Docker |
| `k8s/` | Kustomize base for Kubernetes (Talos): PSA restricted, read-only root, NetworkPolicy, HTTPRoute (`kubectl apply -k deploy/k8s`) |
| `../scripts/verify-image.sh` | Verify a published image's signature and attestations, print the digest to pin |
| `../.github/workflows/` | `ci.yml` (tests, lint, smoke test, Grype gate), `release.yml` (build by digest → scan → sign/attest → tag), `codeql.yml`, `scheduled-scan.yml` |

Lint locally: `hadolint deploy/Containerfile deploy/Containerfile.debian` (config in
`/.hadolint.yaml`), `kustomize build deploy/k8s | kubeconform -strict -summary`,
`/usr/libexec/podman/quadlet -user -dryrun` after copying the Quadlet files.
