# Network allowlist

Four different places need outbound network rules. Keep them separate:

1. [The running app](#1-the-running-app-runtime-egress) (what a firewall or NetworkPolicy around the
   container must allow),
2. [The host that pulls or builds the image](#2-the-host-that-pulls-or-builds-the-image),
3. [CI](#3-ci-github-actions) (GitHub Actions),
4. [The development environment](#4-development-environment-claude-code-cloud) (Claude Code cloud).

The patient's phone or browser talks **only to the app itself**: the UI loads nothing from a CDN,
fonts and scripts are served by the app, and offline mode works with no internet at all.

## 1. The running app (runtime egress)

The app makes **no outbound request until you turn a feature on**. Every outbound call is HTTPS on
port 443, made by the server (never the browser) through the app's SSRF-checked transport
(`app/egress.py` for USDA and Open Food Facts: the address is resolved and checked on every request,
private and metadata addresses are refused, redirects are not followed); API keys travel in headers,
never in URLs.

| Host | Port | Needed when | Default |
|---|---|---|---|
| `api.nal.usda.gov` | 443 | A USDA FoodData Central key is set (`USDA_API_KEY_FILE`, or a key in Settings → Food data): food search, import, and branded-food barcode lookups (`food.usda_branded_barcode`) | off |
| `world.openfoodfacts.org` | 443 | Barcode lookups are on (`food.off_enabled`, Settings → Food data, or the first-run checkbox) **and** the person scanning agreed (`food.off_consent`); only the barcode digits are sent ([`barcode-and-photos.md`](barcode-and-photos.md)). The env-only `OFF_BASE_URL` can point at staging (`world.openfoodfacts.net`) or your own Product Opener instead. `images.openfoodfacts.org` is **not** needed: the app shows no product images. | off |
| `api.openai.com` | 443 | AI with the `openai` preset | off (`AI_ENABLED=false`) |
| `openrouter.ai` | 443 | AI with the `openrouter` preset | off |
| `inference-api.nousresearch.com` | 443 | AI with the `nous_portal` preset | off |
| your AI host (e.g. `ollama:11434`, `host.containers.internal:8643`) | its port | A local Ollama, Hermes or other OpenAI-compatible server. Private addresses are reachable only when listed in the env-only `AI_PRIVATE_HOSTS`. | off |
| `api.pwnedpasswords.com` | 443 | `PASSWORD_BREACH_CHECK=true` (k-anonymity: only 5 hex characters of a hash leave the server) | off |

Not used: Web Push services (planned for v0.4, opt-in; their hosts will be added here), telemetry,
update checks, analytics. The patient handbook at `/learn` makes no request outside the server either:
its fonts, scripts and search run from the image (a CI build fails on any external asset). DNS
resolution is needed for any of the hosts above.

**How to enforce it.**

* **Kubernetes:** `deploy/k8s/networkpolicy.yaml` allows DNS plus HTTPS to public addresses only
  (private, CGNAT, link-local and loopback ranges are excluded, which blocks cloud metadata and the
  API server). With Cilium, `deploy/k8s/cilium-networkpolicy.example.yaml` narrows that to the exact
  host names above (uncomment the AI hosts you use). A LAN AI host needs its own `ipBlock` rule
  (commented example in `networkpolicy.yaml`). On Talos, enable NetworkPolicy in Flannel first
  ([`deployment.md`](deployment.md#4-make-networkpolicy-real-on-talos)).
* **Rootless Podman / Docker:** there is no simple per-container egress allowlist (an accepted
  residual risk, [`security.md`](security.md#10-accepted-residual-risks)). Use a host firewall or your
  router if you need one. The optional Ollama overlay puts Ollama on an `internal` network with no
  route out at all.
* **Egress proxy:** the AI client ignores `HTTP(S)_PROXY` on purpose; set `AI_HTTP_PROXY` explicitly
  if AI calls must go through a proxy (address pinning is then the proxy's job, and per-user base
  URLs are disabled). The health check never uses a proxy.

## 2. The host that pulls or builds the image

**Pulling the published image** (Quadlet, compose, Kubernetes nodes):

```
ghcr.io
pkg-containers.githubusercontent.com
```

**Verifying it** with `scripts/verify-image.sh`: `ghcr.io`, `api.github.com` (`gh attestation`),
and Sigstore's public services (`tuf-repo-cdn.sigstore.dev`, `rekor.sigstore.dev`,
`fulcio.sigstore.dev`).

**Building it yourself** additionally needs:

| Host | For |
|---|---|
| `cgr.dev` and its blob storage (a `*.r2.cloudflarestorage.com` host, redirected to by cgr.dev) | Chainguard `python:latest-dev` / `:latest` base images (`deploy/Containerfile`) |
| `pypi.org`, `files.pythonhosted.org` | The hash-locked wheels from `requirements.lock`, and the handbook toolchain from `handbook/requirements.lock` (the image's `handbook` stage) |
| `registry-1.docker.io`, `auth.docker.io`, `production.cloudflare.docker.com` | Only for `deploy/Containerfile.debian` (python:3.14-slim-trixie) or the Caddy example. Anonymous Docker Hub pulls are rate-limited. |
| `proxy.golang.org`, `sum.golang.org` | Only for the Caddy image with a DNS module (`xcaddy` downloads Go modules and checks them against the checksum database) |
| `docker.io/ollama/ollama` (Docker Hub hosts above) | Only for the Ollama overlay; then the model pull reaches `registry.ollama.ai` and its download CDN once |

The Caddy container itself needs the ACME endpoints (`acme-v02.api.letsencrypt.org`) and your DNS
provider's API (for Cloudflare `api.cloudflare.com`) to obtain and renew certificates.

## 3. CI (GitHub Actions)

GitHub-hosted runners have open egress, so this list matters only for self-hosted runners or
egress auditing. The workflows reach:

| Host | For |
|---|---|
| `github.com`, `api.github.com`, `codeload.github.com` | Checkout, action downloads, `gh`, attestations |
| `objects.githubusercontent.com`, `release-assets.githubusercontent.com` | Release downloads, each SHA-256 checked: actionlint 1.7.12, hadolint 2.14.0, kubeconform v0.8.0, kustomize v5.8.2; setup-python and setup-node toolchains |
| `raw.githubusercontent.com` | kubeconform schemas (`yannh/kubernetes-json-schema`, `datreeio/CRDs-catalog`) |
| `pypi.org`, `files.pythonhosted.org` | Hash-locked test and lint dependencies |
| `cgr.dev` (+ blob storage), `registry-1.docker.io`, `auth.docker.io`, `production.cloudflare.docker.com` | Base images; `moby/buildkit` and `tonistiigi/binfmt` (pinned by digest) |
| `ghcr.io`, `pkg-containers.githubusercontent.com` | Pushing the image by digest, scanning it, moving tags; the zizmor container |
| `grype.anchore.io` | The Grype vulnerability database (fresh on every scan) |
| `fulcio.sigstore.dev`, `rekor.sigstore.dev`, `tuf-repo-cdn.sigstore.dev` | Keyless cosign signing and GitHub attestations (public repository only) |
| `nodejs.org` (if the toolchain cache misses) | `actions/setup-node` |
| none extra | The `handbook` job's browser check uses the runner's preinstalled Google Chrome (no browser download) and talks only to the app on `127.0.0.1` |
| `*.github.io` (Pages) | `handbook-pages.yml` deploys the public copy of the handbook through the Pages API, only when the repository variable `HANDBOOK_PAGES` is `true` |
| Every external link in the handbook | `handbook-links.yml` (weekly) checks the sources and links of the handbook with lychee |

## 4. Development environment (Claude Code cloud)

In the Claude Code environment settings choose **Custom**, keep the default package-manager list
enabled, and add the domains below under *Allowed domains*
(<https://code.claude.com/docs/en/cloud-environments#network-access>). Nothing in this section is
needed by the running app.

### Core (paste-ready, one per line)

```
github.com
api.github.com
raw.githubusercontent.com
objects.githubusercontent.com
release-assets.githubusercontent.com
codeload.github.com
uploads.github.com
ghcr.io
pkg-containers.githubusercontent.com
cgr.dev
hub.docker.com
registry-1.docker.io
auth.docker.io
fdc.nal.usda.gov
api.nal.usda.gov
world.openfoodfacts.org
www.kidney.org
kidney.org
www.kidneykitchen.org
www.kidneyfund.org
www.niddk.nih.gov
kdigo.org
www.ajkd.org
www.kidney-international.org
diabetes.org
diabetesjournals.org
professional.diabetes.org
pubmed.ncbi.nlm.nih.gov
www.ncbi.nlm.nih.gov
pmc.ncbi.nlm.nih.gov
ods.od.nih.gov
www.fda.gov
www.dietaryguidelines.gov
www.davita.com
www.freseniuskidneycare.com
www.eatright.org
polyformproject.org
spdx.org
```

### Recommended additions

```
static.openfoodfacts.org
medlineplus.gov
www.mayoclinic.org
www.cdc.gov
www.who.int
www.heart.org
www.nhs.uk
kidneycareuk.org
www.kidneyresearchuk.org
www.bda.uk.com
breakthrought1d.org
doi.org
academic.oup.com
link.springer.com
www.sciencedirect.com
onlinelibrary.wiley.com
jamanetwork.com
www.nejm.org
www.thelancet.com
dl.k8s.io
docs.siderolabs.com
kubernetes.io
docs.podman.io
podman.io
docs.docker.com
docs.sigstore.dev
docs.zizmor.sh
grype.anchore.io
fastapi.tiangolo.com
docs.pydantic.dev
docs.python.org
docs.pytest.org
developer.mozilla.org
playwright.dev
code.claude.com
docs.claude.com
```

What each group is for:

| Domains | Purpose |
|---|---|
| GitHub hosts | git, pull requests, action and tool release downloads (and their SHA-256 files), resolving action SHAs |
| `ghcr.io`, `cgr.dev`, Docker Hub hosts | Inspecting image digests and configs (`crane digest`, registry API) for the pinned `FROM` lines; there is no container daemon in this environment |
| `fdc.nal.usda.gov`, `api.nal.usda.gov`, `world.openfoodfacts.org` | Food data: the SR Legacy download used by `scripts/build_food_db.py`, and API checks |
| Kidney, diabetes and literature sites | Checking every clinical number against its source (`docs/research/`, the handbook bibliography) |
| Kubernetes, Talos, Podman, Docker, Sigstore, zizmor, Grype docs | Re-verifying the deployment guidance (`docs/dev/research/01-rootless-and-security.md` §8) |
| Stack documentation | FastAPI, Pydantic, Python, pytest, MDN, Playwright |

Already covered by the default package-manager list (keep it enabled): `pypi.org`,
`files.pythonhosted.org`, `registry.npmjs.org`, `proxy.golang.org`, `index.crates.io`. Playwright's
Chromium is preinstalled, so no browser downloads are needed. If a fetch to a new reference site is
denied, add just that host.
