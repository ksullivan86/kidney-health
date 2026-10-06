---
title: Network allowlist
description: "The outbound hosts kidney-health needs for each feature, how to enforce them, and why the handbook and the phone need none."
slug: network-allowlist
audience: [self-hoster]
applies_to: [all]
status: draft
reviewed_by: ""
reviewed_on: null
last_checked: 2026-10-06
fact_checked: 2026-10-05
sources: [ALLOWLIST, NOTE01, NOTE03, NOTE04, NOTE08, SECDOC, K8S-NETPOL, OFF-API, FDC-API]
---

# Network allowlist

The running app makes **no outbound request until you switch a feature on**. Every outbound call is
HTTPS, made by the server (never by the phone), through a transport that checks addresses before
connecting; API keys travel in headers, never in URLs ([network allowlist][ALLOWLIST];
[design note 01][NOTE01]).

The phone talks only to your server: the app loads nothing from a CDN, and the handbook at `/learn` is
built offline and loads nothing from the internet either, no fonts, no scripts, no images
([design note 08][NOTE08]).

## What the running app may reach

| Host | Port | Needed when | Default |
|---|---|---|---|
| `api.nal.usda.gov` | 443 | a USDA key is set (shared or a person's own) ([USDA][FDC-API]) | off |
| `world.openfoodfacts.org` | 443 | barcode lookups are on ([Open Food Facts][OFF-API]) | off |
| `api.openai.com` | 443 | AI with the `openai` preset | off |
| `openrouter.ai` | 443 | AI with the `openrouter` preset | off |
| `inference-api.nousresearch.com` | 443 | AI with the `nous_portal` preset | off |
| your AI host, e.g. `ollama:11434` | its port | a local Ollama, Hermes or other compatible server, listed in `AI_PRIVATE_HOSTS` | off |
| `api.pwnedpasswords.com` | 443 | `PASSWORD_BREACH_CHECK=true` | off |

Not needed: `images.openfoodfacts.org` (the app shows no product images), telemetry, update checks or
analytics (there are none). DNS is needed for any host above ([design note 03][NOTE03];
[design note 04][NOTE04]).

## Private addresses and AI

Shared AI providers may reach private, loopback or link-local addresses **only** when listed in the
env-only `AI_PRIVATE_HOSTS` (for example `ollama:11434,192.168.1.10:8643`). Each resolved address is
checked and pinned, and redirects are not followed. People's own AI addresses (if you allow them) must be
public HTTPS on port 443. The AI client ignores `HTTP(S)_PROXY`; set `AI_HTTP_PROXY` if AI must go through
a proxy ([design note 04][NOTE04]).

## How to enforce it

- **Kubernetes:** `deploy/k8s/networkpolicy.yaml` allows DNS and HTTPS to **public** addresses only
  (private, CGNAT, link-local and loopback excluded, so cloud metadata and the API server are blocked).
  With Cilium, `cilium-networkpolicy.example.yaml` narrows it to the exact host names above. A NetworkPolicy
  only works if your network plugin enforces it; on Talos, switch it on in Flannel first
  ([Kubernetes: Network Policies][K8S-NETPOL]; [Kubernetes](kubernetes.md)).
- **Rootless Podman or Docker:** there is no simple per-container egress allowlist. Use a host firewall or
  your router if you need one. The optional Ollama overlay puts Ollama on an `internal` network with no
  route out at all ([operator security guide][SECDOC]).

## The host that pulls or builds the image

| For | Hosts |
|---|---|
| Pulling the image | `ghcr.io`, `pkg-containers.githubusercontent.com` |
| Verifying it | `ghcr.io`, `api.github.com`, and Sigstore's `tuf-repo-cdn.sigstore.dev`, `rekor.sigstore.dev`, `fulcio.sigstore.dev` |
| Building it yourself | `cgr.dev` (and its blob storage), `pypi.org`, `files.pythonhosted.org`; Docker Hub hosts only for the Debian fallback or the Caddy image |
| Caddy certificates | `acme-v02.api.letsencrypt.org` and your DNS provider's API (for Cloudflare `api.cloudflare.com`) |

The handbook is built inside the image build from hash-locked packages on `pypi.org`; serving it needs
nothing ([Building the handbook](building-the-handbook.md)). The repository's
[network allowlist][ALLOWLIST] also lists CI and development hosts.

## If something goes wrong

- **`USDA request failed`**: the server cannot reach `api.nal.usda.gov:443`. Check egress rules.
  `USDA API key was rejected` means a wrong key.
- **Barcode lookups time out**: allow `world.openfoodfacts.org:443`.
- **A local AI server is refused**: add its `host:port` to `AI_PRIVATE_HOSTS`, and on Kubernetes add an
  egress rule for its address.
- More: [Troubleshooting](troubleshooting.md).

## Related pages

- [Configuration](configuration.md) · [Security](security.md) · [Kubernetes](kubernetes.md)
- For your users: [Privacy and your data](../app/privacy.md)

## Sources

- [Network allowlist][ALLOWLIST] (repository); [operator security guide][SECDOC].
- [Design note 01][NOTE01]; [design note 03][NOTE03] R10; [design note 04][NOTE04] R4–R5 and security review; [design note 08][NOTE08].
- [Kubernetes: Network Policies][K8S-NETPOL]; [Open Food Facts API][OFF-API]; [USDA FoodData Central API guide][FDC-API].
