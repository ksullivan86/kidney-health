# Network allowlist

Three different places need outbound network rules for this project. Keep them
separate: the Claude Code cloud environment that develops the repo, the homelab
host that builds and pulls container images, and the running app itself.

## 1. Claude Code cloud environment ("Custom" network access)

In the Claude Code environment settings choose **Custom**, keep the default
package-manager list enabled, and add the domains below under *Allowed domains*.
Steps: https://code.claude.com/docs/en/cloud-environments#network-access

Paste-ready list (one per line):

```
github.com
api.github.com
raw.githubusercontent.com
objects.githubusercontent.com
codeload.github.com
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
cdn.jsdelivr.net
cdnjs.cloudflare.com
unpkg.com
```

What each group is for:

| Domains | Purpose |
|---|---|
| `github.com`, `api.github.com`, `raw.githubusercontent.com`, `objects.githubusercontent.com`, `codeload.github.com` | git push/pull, GitHub Actions artifacts, fetching files from GitHub |
| `ghcr.io`, `pkg-containers.githubusercontent.com` | GitHub Container Registry (image pushes from CI, pulls from the homelab) |
| `fdc.nal.usda.gov` | USDA FoodData Central website and the SR Legacy CSV download used by `scripts/build_food_db.py` |
| `api.nal.usda.gov` | USDA FoodData Central REST API (optional live food search in the app; `DEMO_KEY` for testing) |
| `www.kidney.org`, `kidney.org`, `www.kidneykitchen.org`, `www.kidneyfund.org`, `www.niddk.nih.gov`, `kdigo.org`, `www.ajkd.org`, `www.kidney-international.org` | Renal diet guidance: National Kidney Foundation, American Kidney Fund, NIDDK, KDIGO, KDOQI (published in AJKD) |
| `diabetes.org`, `diabetesjournals.org`, `professional.diabetes.org` | American Diabetes Association Standards of Care and patient guidance |
| `pubmed.ncbi.nlm.nih.gov`, `www.ncbi.nlm.nih.gov`, `pmc.ncbi.nlm.nih.gov` | Primary literature |
| `ods.od.nih.gov`, `www.fda.gov`, `www.dietaryguidelines.gov` | Nutrient fact sheets, label rules (sodium/potassium % DV), dietary guidelines |
| `www.davita.com`, `www.freseniuskidneycare.com`, `www.eatright.org` | Dietitian-written renal diet handouts and recipes used for cross-checking |
| `cdn.jsdelivr.net`, `cdnjs.cloudflare.com`, `unpkg.com` | Only needed if you later decide to pull a frontend library during development. The shipped UI loads nothing from the internet. |

Already covered by the default package-manager list (do not remove it):
`pypi.org`, `files.pythonhosted.org` (pip), `registry.npmjs.org` (npm, not used by the
app but by tooling), `proxy.golang.org`, `index.crates.io`.

Not needed: Playwright browsers are preinstalled in the environment, and the
WebSearch tool runs server-side, so no search-engine domains are required. If a
WebFetch to a new reference site is denied, add just that host.

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
