---
title: Kubernetes
description: "Run kidney-health on Kubernetes (Talos): storage, the Secret, Pod Security restricted, NetworkPolicy that is really enforced, and pinning the image."
slug: kubernetes
audience: [self-hoster]
applies_to: [all]
status: draft
reviewed_by: ""
reviewed_on: null
last_checked: 2026-10-06
fact_checked: 2026-10-05
sources: [NOTE01, DEPLOY, SECDOC, K8S-PSS, K8S-NETPOL, K8S-USERNS, TALOS-FLANNEL]
---

# Kubernetes

The Kustomize base in `deploy/k8s/` runs one pod with one SQLite volume, under the Pod Security
**restricted** profile, with a default-deny NetworkPolicy. It was written for Talos Linux and works on
other clusters ([design note 01][NOTE01]; [deployment guide][DEPLOY]). The base is **cluster-neutral**:
you never edit it. Everything that depends on your cluster (host name, Gateway, network ranges, storage
class, image pin) goes in an **overlay**, a small folder of patches you copy from
`deploy/k8s-overlays/example/`.

## What is in `deploy/k8s/` and the example overlay

| File | Purpose | Edit? |
|---|---|---|
| `deploy/k8s/kustomization.yaml` | resources and the image (minor-release tag) | no |
| `deploy/k8s/namespace.yaml` | namespace with Pod Security `restricted` (enforce, audit, warn) | no |
| `deploy/k8s/pvc.yaml` | 1 Gi `ReadWriteOnce` volume, the cluster's default storage class | no |
| `deploy/k8s/deployment.yaml` | UID 10001, read-only root, `/tmp` emptyDir, secret files, probes, `Recreate` | no |
| `deploy/k8s/service.yaml` | ClusterIP port 80 to 8000 | no |
| `deploy/k8s/networkpolicy.yaml` | default deny; DNS; public HTTPS out; nothing in until the overlay | no |
| overlay `kustomization.yaml` | the base, the route, the patches; image pin (tag and digest); storage class | pin the digest |
| overlay `httproute.yaml` | Gateway API route | `parentRefs`, hostname |
| overlay `deployment-env.yaml` | `PUBLIC_URL`, `TRUSTED_PROXIES` | both |
| overlay `networkpolicy-ingress.yaml` | lets the Gateway's namespace in on port 8000 | that namespace |
| `ingress.example.yaml`, `cilium-networkpolicy.example.yaml`, `secret.example.yaml` | examples, not applied | |

**One pod per database:** one replica, `ReadWriteOnce`, `Recreate` rollouts. There is deliberately no
PodDisruptionBudget, because with one replica it would block node drains.

## Steps

The commands for each step are in the deployment guide's [Kubernetes section](https://github.com/ksullivan86/kidney-health/blob/main/docs/deployment.md#kubernetes-talos).

1. **Storage.** Leave the cluster's default storage class, or uncomment the storage-class patch in your
   overlay. Avoid NFS: SQLite needs file locking that NFS handles poorly.
2. **Secret.** Create it with two keys, `secret_key` (a long random value) and `usda_api_key` (empty
   means "off"). Keep a copy of `secret_key` in your password manager ([Backups](backups.md)).
3. **Copy the example overlay and edit it:** `httproute.yaml` (hostname, Gateway),
   `networkpolicy-ingress.yaml` (Gateway namespace) and `deployment-env.yaml`: `PUBLIC_URL` = `https://`
   plus the route's hostname; `TRUSTED_PROXIES` as narrow as your Gateway's pods allow. Keeping your
   overlay in a separate GitOps repository, with the base as a remote resource pinned to a release,
   works too.
4. **Apply** your overlay, wait for the rollout, and read the one-time setup code from the log.
5. **Pin the image** in your overlay by tag and digest; each release's notes carry the digest
   ([Security](security.md)).

## Pod Security restricted

The namespace enforces the **restricted** profile: non-root, no privilege escalation, all capabilities
dropped, seccomp `RuntimeDefault`, and only safe volume types ([Kubernetes: Pod Security
Standards][K8S-PSS]). Any extra container you add (debug, init, restore) must meet the same rules. A
server-side dry run of the namespace label reports any pod that would not pass; the command is in the
guide's [Pod Security step](https://github.com/ksullivan86/kidney-health/blob/main/docs/deployment.md#5-check-pod-security-pin-the-digest).

## Make NetworkPolicy real

A NetworkPolicy does nothing unless the network plugin enforces it ([Kubernetes: Network
Policies][K8S-NETPOL]). On Talos, the default Flannel **accepts but ignores** policies unless
`kubeNetworkPoliciesEnabled: true` is set (Talos 1.13 and later) ([Talos: Flannel][TALOS-FLANNEL]).

Test it: the guide's [NetworkPolicy step](https://github.com/ksullivan86/kidney-health/blob/main/docs/deployment.md#4-make-networkpolicy-real-on-talos) has a one-line test
pod that tries to reach the app. It **must fail**. If it prints `{"status":"ok",...}`, policies are not
enforced.

The shipped policy lets the pod reach DNS and **public** addresses on port 443 only (private, CGNAT,
link-local and loopback ranges excluded, so cloud metadata and the API server are unreachable). With
Cilium, `cilium-networkpolicy.example.yaml` narrows that to exact host names. A LAN Ollama needs its own
rule and an `AI_PRIVATE_HOSTS` entry ([Network allowlist](network-allowlist.md)).

## `TRUSTED_PROXIES` on a cluster

The base trusts only loopback, which is safe but ignores your Gateway's forwarded headers, so set
`TRUSTED_PROXIES` in your overlay. The example's `10.244.0.0/16` (the Talos and Flannel default pod
range; yours may differ) trusts **every pod**. That is acceptable only while the NetworkPolicy is
enforced, or with `TRUSTED_PROXY_SECRET_FILE` set. Narrow it to your Gateway's pods where you can
([operator security guide][SECDOC]).

## Optional: a user namespace for the pod

`hostUsers: false` runs the pod in its own user namespace, so even root inside it is unprivileged on the
node. It is stable since Kubernetes 1.36 and needs Linux 6.3 or later, containerd 2.0 or later, and
idmap-capable volumes such as ext4, xfs, btrfs or tmpfs, not NFS ([Kubernetes: user
namespaces][K8S-USERNS]). On Talos, also raise `user.max_user_namespaces` with a machine config patch
([deployment guide](https://github.com/ksullivan86/kidney-health/blob/main/docs/deployment.md#6-optional-a-user-namespace-for-the-pod)).

## Debugging without a shell

The image has no shell. Use the admin CLI (`python -m app.admin check` through `kubectl exec`), or an
ephemeral debug container with the restricted profile ([deployment guide](https://github.com/ksullivan86/kidney-health/blob/main/docs/deployment.md#debugging-without-a-shell)).

## If something goes wrong

- **Pod `Pending`**: describe the volume claim `kidney-health-data`. Usually a mistyped storage class or
  no default class.
- **Pod rejected by Pod Security**: an added container is missing one of the restricted settings.
- **`400 Unknown host`**: `PUBLIC_URL` does not match the route's hostname.
- **`database is locked`**: two pods share the volume; keep one replica and `Recreate`.
- More: [Troubleshooting](troubleshooting.md).

## Related pages

- [HTTPS for phones](https.md) (cert-manager) · [Security](security.md) · [Backups](backups.md) · [Upgrades](upgrades.md)

## Sources

- [Design note 01][NOTE01], sections 3.5 and 5.3; [deployment guide][DEPLOY]; [operator security guide][SECDOC].
- [Kubernetes: Pod Security Standards][K8S-PSS]; [Network Policies][K8S-NETPOL]; [user namespaces][K8S-USERNS].
- [Talos: Flannel and NetworkPolicy][TALOS-FLANNEL].
