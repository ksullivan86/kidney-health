# Network allowlist

Three different places need outbound network rules for this project. Keep them
separate: the Claude Code cloud environment that develops the repo, the homelab
host that builds and pulls container images, and the running app itself.

## 1. Claude Code cloud environment ("Custom" network access)

In the Claude Code environment settings choose **Custom**, keep the default
package-manager list enabled, and add the domains below under *Allowed domains*.
Steps: https://code.claude.com/docs/en/cloud-environments#network-access

There are two tiers. The **core** tier is what this repository actually needs to be
developed, tested and published. The **recommended** tier is what a Claude Code
session working on it will plausibly reach for next: more reference sites to
fact-check diet numbers, tooling downloads to validate the Kubernetes manifests,
and documentation for the stack. Nothing in either tier is needed by the running app.

### Core (paste-ready, one per line)

```
github.com
api.github.com
raw.githubusercontent.com
objects.githubusercontent.com
codeload.github.com
uploads.github.com
ghcr.io
pkg-containers.githubusercontent.com
fdc.nal.usda.gov
api.nal.usda.gov
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
world.openfoodfacts.org
static.openfoodfacts.org
images.openfoodfacts.org
medlineplus.gov
www.mayoclinic.org
www.cdc.gov
www.who.int
www.heart.org
www.nhs.uk
kidneycareuk.org
www.kidneyresearchuk.org
www.renalsupportnetwork.org
www.bda.uk.com
breakthrought1d.org
diatribe.org
www.diabetes.co.uk
www.nephcure.org
www.uptodate.com
doi.org
academic.oup.com
link.springer.com
www.sciencedirect.com
onlinelibrary.wiley.com
jamanetwork.com
www.nejm.org
www.thelancet.com
www.mdpi.com
www.frontiersin.org
journals.plos.org
dl.k8s.io
storage.googleapis.com
get.helm.sh
kubernetesjsonschema.dev
factory.talos.dev
www.talos.dev
kubernetes.io
docs.podman.io
podman.io
fastapi.tiangolo.com
docs.pydantic.dev
www.uvicorn.org
www.starlette.io
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
| `github.com`, `api.github.com`, `raw.githubusercontent.com`, `objects.githubusercontent.com`, `codeload.github.com`, `uploads.github.com` | git push/pull, GitHub API (pull requests, releases), Actions artifacts, release downloads (actionlint, kubeconform, hadolint binaries) |
| `ghcr.io`, `pkg-containers.githubusercontent.com` | GitHub Container Registry (image pushes from CI, pulls from the homelab) |
| `fdc.nal.usda.gov`, `api.nal.usda.gov` | USDA FoodData Central: the SR Legacy CSV download used by `scripts/build_food_db.py`, the website, and the REST API (`DEMO_KEY` for testing, your own key in the app) |
| `www.kidney.org`, `kidney.org`, `www.kidneykitchen.org`, `www.kidneyfund.org`, `www.niddk.nih.gov`, `kdigo.org`, `www.ajkd.org`, `www.kidney-international.org` | Renal diet guidance: National Kidney Foundation, American Kidney Fund, NIDDK, KDIGO, KDOQI (published in AJKD) |
| `diabetes.org`, `diabetesjournals.org`, `professional.diabetes.org` | American Diabetes Association Standards of Care and patient guidance |
| `pubmed.ncbi.nlm.nih.gov`, `www.ncbi.nlm.nih.gov`, `pmc.ncbi.nlm.nih.gov`, `doi.org` and the publisher domains | Primary literature when a number needs a source |
| `ods.od.nih.gov`, `www.fda.gov`, `www.dietaryguidelines.gov`, `www.cdc.gov`, `www.who.int`, `www.heart.org` | Nutrient fact sheets, label rules (sodium/potassium % Daily Value), dietary guidelines, blood-pressure guidance |
| `www.davita.com`, `www.freseniuskidneycare.com`, `www.eatright.org`, `medlineplus.gov`, `www.mayoclinic.org`, `www.nhs.uk`, `kidneycareuk.org`, `www.bda.uk.com` and the other patient-facing sites | Dietitian-written renal and diabetes handouts used for cross-checking |
| `world.openfoodfacts.org`, `static.openfoodfacts.org`, `images.openfoodfacts.org` | Open Food Facts: free barcode database for branded foods (planned feature: scan a barcode to log a packaged food) |
| `polyformproject.org`, `spdx.org` | License texts |
| `dl.k8s.io`, `storage.googleapis.com`, `get.helm.sh`, `kubernetesjsonschema.dev`, `factory.talos.dev`, `www.talos.dev`, `kubernetes.io`, `docs.podman.io`, `podman.io` | kubectl/helm downloads, Kubernetes schema validation (kubeconform), Talos image factory and docs, Podman docs |
| `fastapi.tiangolo.com`, `docs.pydantic.dev`, `www.uvicorn.org`, `www.starlette.io`, `docs.python.org`, `docs.pytest.org`, `developer.mozilla.org`, `playwright.dev` | Documentation for the stack |
| `code.claude.com`, `docs.claude.com` | Claude Code documentation |

Already covered by the default package-manager list (keep it enabled):
`pypi.org`, `files.pythonhosted.org` (pip), `registry.npmjs.org` (npm, tooling only),
`proxy.golang.org`, `index.crates.io`.

Deliberately not listed: the WebSearch tool runs server-side, so no search-engine
domains are required; Playwright's Chromium is preinstalled, so no browser downloads;
Docker Hub is not needed in the Claude environment because it has no container daemon
(it is listed for the homelab below). The shipped UI loads nothing from a CDN, so
`cdn.jsdelivr.net`, `cdnjs.cloudflare.com` and `unpkg.com` are only worth adding if you
decide to pull a frontend library during development. If a fetch to a new reference
site is denied, add just that host.

## 2. Homelab host (building or pulling the image)

```
ghcr.io
pkg-containers.githubusercontent.com
registry-1.docker.io
auth.docker.io
production.cloudflare.docker.com
pypi.org
files.pythonhosted.org
```

`registry-1.docker.io`, `auth.docker.io` and `production.cloudflare.docker.com`
are only needed when building locally (pulling `python:3.12-slim`). Pulling the
prebuilt image from GHCR needs only the first two.

## 3. The running app

The app makes **no** outbound requests by default. If you set `USDA_API_KEY` to
enable live food search, allow:

```
api.nal.usda.gov
```

The browser UI talks only to the app itself; nothing is loaded from a CDN, so
the patient's device needs no internet access to use it.
