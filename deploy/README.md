# Deployment assets

| Path | Use |
|---|---|
| `Containerfile` | OCI image. Build from the repo root: `podman build -f deploy/Containerfile -t kidney-health .` |
| `compose.yaml`, `.env.example` | `podman-compose` / `docker compose` |
| `quadlet/` | systemd Quadlet units for rootless Podman (auto-start at boot, auto-update) |
| `k8s/` | Kustomize base for Kubernetes, written for a Talos Linux cluster |

Step-by-step instructions, backups, auth and upgrade notes: [docs/deployment.md](../docs/deployment.md).
