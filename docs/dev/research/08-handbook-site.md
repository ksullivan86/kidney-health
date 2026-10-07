# 08 · Patient handbook website (`/learn`): tooling, hosting and content plan

| | |
|---|---|
| Status | Decision note, proposed for v0.3. No application code has been changed. |
| Date researched | 2026-10-05 |
| Scope | Part A: the static-site tooling for a public patient handbook. That covers offline and private builds, search without internet, serving the site inside the app at `/learn` on a LAN (CSP, caching, auth), the container build stage, and GitHub Pages deployment (including private-repo limits). Part B: the full content plan. For every page it gives the audience, what the page must teach and the primary sources to cite. It also covers the editorial and clinical-review process, licensing of the text, and how the app links to pages. |
| Out of scope | Writing the pages themselves. App features described on "Using the app" pages are owned by notes [01](01-rootless-and-security.md)–[07](07-accounts-settings-secrets.md). Target formulas are in [05](05-personalized-targets.md), guidance rules in [06](06-meal-guidance.md) and the CSP baseline in [01](01-rootless-and-security.md) §5.5. This note only adds the `/learn` exception to that CSP. |
| Supersedes | Notes [02](02-ios-pwa.md) R4 and [06](06-meal-guidance.md) §4.15 / [04](04-optional-ai.md) R2 call the site `/handbook/<slug>/`. **Use `/learn/<path>/` instead.** The final slug → URL table is in [§4.10](#410-app-integration-slugs-links-and-the-learn-entry). Nothing has been implemented yet, so no redirect is needed. |
| Re-verify | Material for MkDocs support ends no earlier than Nov 2026. Zensical 0.1.0 is announced for Nov 5. Recheck the MkDocs 2.0 situation, action SHAs, KDIGO Diabetes-in-CKD 2026 (final), ADA Standards 2027 (December), and Medicare 2027 amounts (published around November). See [§8](#8-how-to-re-verify). |

Versions current on 2026-10-05 (PyPI JSON / npm registry / `git ls-remote`, upload dates in brackets):
**mkdocs-material 9.7.7** (2026-07-17, MIT), **mkdocs 1.6.1** (2024-08-30, BSD-2-Clause; 2.0.dev1–dev6
pre-releases 2026-08-29…09-15), **pymdown-extensions 12.1** (2026-09-23, MIT), **zensical 0.0.68**
(2026-10-05, MIT, "Development Status :: 3 - Alpha"), **properdocs 1.6.7** (2026-03-20, BSD-2-Clause),
**textstat 0.7.13** (2026-02-18, MIT), Docusaurus **3.10.2** (2026-07-10, MIT), Starlight **0.42.5**
(2026-10-01, MIT), VitePress **1.6.4** (2025-08-05), Sphinx **9.1.0**, Hugo **v0.167.0**.

---

## 1. Context

### 1.1 The ask

> "also just a document website to view all the data you have gathered like what foods to eat and
> basically how to live and deal with each stage of failure. this should be info for patients but not
> just vague info a doctor would print off, it needs to be helpful."

The same request makes the project public and open source ("make sure everything is documented and
able for other sessions AIs/humans to pickup and improve"). It also asks whether age and sex should
affect targets, which is answered in note 05. This note covers how the handbook explains those factors.
The owner wants three things: the handbook works on a LAN without internet, it sits inside the
self-hosted app, and it is also published on GitHub.

### 1.2 What exists today (read from the repository)

* `docs/diet-guide.md` (448 lines) is a carefully sourced renal + type 1 guide for family and caregivers.
  It covers the six numbers, targets by stage, eat/limit/avoid lists, carb counting with renal swaps,
  treating a low, label reading, leaching, eating out, salt substitutes, supplements, a sample day and
  55 numbered sources. Its research base is in `docs/research/*.md` and `targets_by_stage.json`.
  Code comments in `app/nutrients.py` (lines ~459, 471), `scripts/curated_foods.py` (~109, 370, 522)
  and `tests/test_food_db.py` (line 5) point to "docs/diet-guide.md section N". No test parses the guide.
* `docs/deployment.md` (643 lines) covers Podman, Quadlet, Kubernetes, backups, auth, ARM and
  troubleshooting. `docs/network-allowlist.md` lists the outbound domains.
* The app mounts `StaticFiles(directory=app/static, html=True)` at `/`. Optional HTTP Basic auth
  (`APP_PASSWORD`) covers everything except `/healthz`. Note 07 replaces this with session auth and
  keeps static files public, because they "carry no data".
* Note 01 §5.5 adds a strict CSP to every response: `script-src 'self'`, `style-src 'self'`,
  `require-trusted-types-for 'script'; trusted-types 'none'`. Note 02 R4's service worker leaves
  every path except `/` and `/index.html` to the network.
* `.dockerignore` excludes `.git`, `docs`, `tests` and `README.md` from the image build context.
* The GitHub repository is **private** (note 01 §1.3). The image is built by
  `.github/workflows/ci.yml`. Note 01 pins actions by SHA and plans `permissions: {}` per workflow.

### 1.3 Constraints

1. **No CDN and no external requests from the browser.** The handbook must work on a LAN with no
   internet, the same as the app (ARCHITECTURE.md "Stack").
2. **Rootless, read-only image.** Code is root-owned and read-only, and runs as uid 10001 (note 01).
   Nothing may be built or written at runtime.
3. **CSP.** The `/learn` path may relax note 01's policy only where measured necessary, and never to
   `'unsafe-inline'`.
4. **Public, health-related content.** The handbook needs clinical accuracy, review dates, sources,
   no dosing advice, and a licence that lets patients and clinics share it.
5. **Portable.** The text must outlive the generator, because the MkDocs ecosystem is in flux (F1).

---

## 2. Findings

### Part A: tooling

#### F1. The MkDocs ecosystem in October 2026

* **Material for MkDocs is in maintenance mode.** The team announced Zensical on 2025-11-05 and
  released 9.7.0 on 2025-11-11 as the last feature release. That release also made all former
  Insiders features free, including the privacy, optimize and social plugins and `navigation.path`.
  The team "will continue to fix critical bugs and security issues for 12 month at least", so until
  **November 2026 at the earliest**
  ([Material blog index](https://squidfunk.github.io/mkdocs-material/blog/)). The latest release is
  **9.7.7 (2026-07-17)**.
* **MkDocs 1.x is unmaintained.** The last release, 1.6.1, was on 2024-08-30. **MkDocs 2.0** is a
  rewrite with no plugin system, a rewritten theming system and TOML configuration. Pre-releases
  2.0.dev1–dev6 appeared on PyPI between 2026-08-29 and 2026-09-15. Material states that it "will
  cease to work with MkDocs 2.0". Since **9.7.5 (2026-03-10)** it pins `mkdocs<2,>=1.6`, so
  `pip install mkdocs-material` cannot pull 2.0 in by accident
  ([Material: "What MkDocs 2.0 means"](https://squidfunk.github.io/mkdocs-material/blog/2026/02/18/mkdocs-2.0/)).
  Material 9.7.7 prints a red warning about this on every `mkdocs` run. Setting `NO_MKDOCS_2_WARNING=true`
  silences it (`material/templates/__init__.py`, read from the installed package).
* **ProperDocs 1.6.7** (BSD-2-Clause) is a community fork of MkDocs 1.6.1 and a "drop-in
  replacement", started by the previous MkDocs maintainer. `mkdocs-redirects 1.2.3` already depends on
  it. Material does not declare support for it.
* **Zensical** is by the Material team, MIT-licensed, written in Rust and Python, and needs Python ≥ 3.11.
  It reads `mkdocs.yml`, supports "the complete [Material] settings surface", provides a "classic"
  theme, and keeps template overrides working "rarely needing changes". It ships its own search
  engine (English UI only) and its own offline mode
  ([compatibility](https://zensical.org/docs/compatibility/mkdocs/),
  [search](https://zensical.org/docs/setup/search/),
  [offline](https://zensical.org/docs/setup/offline/)). It is still **0.0.68, Alpha** (released today).
  The site banner announces "Zensical 0.1.0 … November 5", and the
  [roadmap](https://zensical.org/roadmap/) still lists plugin replacements as in progress.
* **Measured.** The same `mkdocs.yml` skeleton built cleanly with Material 9.7.7 + MkDocs 1.6.1
  (`--strict`, Python 3.11 and 3.14) and with Zensical 0.0.68 (`zensical build -f mkdocs.yml -s`).
  The skeleton had `!ENV` values, a `custom_dir` override, snippets, abbreviations, tabs and the
  privacy plugin config. Zensical rendered the override and was not browser-tested.

#### F2. Privacy and offline: what has to be configured (measured with 9.7.7)

* **Fonts.** `theme.font: false` stops Google Fonts loading and uses the system font stack. No
  download is needed at build time ([Zensical/Material fonts](https://zensical.org/docs/setup/fonts/)).
* **Privacy plugin.** The options are read from `material/plugins/privacy/config.py`:
  `assets`, `assets_fetch`, `assets_exclude`, `links_attr_map`, `links_noopener`.
  * With the default `assets_fetch: true` it **downloads at build time**. It even downloaded
    `unpkg.com/mermaid@11/dist/mermaid.min.js` (3.5 MB) for a site with no diagrams, because the
    theme bundle references it for lazy loading.
  * With `assets_fetch: false` plus `--strict`, any external asset in the content **fails the build**.
    Example: `WARNING - External file: https://www.kidney.org/…/logo.png … Aborted with 2 warnings in strict mode!`.
    That is exactly the guard needed. The theme bundle's own lazy URLs (`unpkg.com/mermaid@11`,
    `unpkg.com/resize-observer-polyfill`) must be excluded with `assets_exclude: ["unpkg.com/*"]`.
    Otherwise the build fails on the bundle itself. Those URLs only load if a page uses Mermaid or the
    browser lacks `ResizeObserver`, and the CSP blocks them anyway.
  * `links_attr_map: {target: _blank}` plus `links_noopener: true` gives every external citation
    `target="_blank" rel="noopener"`. `rel` is only added to `_blank` links.
* **Things that phone home.** Setting `repo_url` makes the bundle call `api.github.com` from the
  reader's browser to show stars and forks. Leave it unset and put a plain link in `extra.social`.
  Do not configure `extra.analytics`. Mermaid and MathJax load from CDNs, so do not use them.
* **Offline plugin.** It exists only for **`file://`** distribution. It forces `use_directory_urls = false`
  and adds `https://unpkg.com/iframe-worker/shim` unless vendored (`material/plugins/offline/plugin.py`).
  **It is not needed for `/learn`**, because served over HTTP the lunr search worker works with no
  internet (F4).
* **Size.** A 4-page build is 2.6 MB, of which 1.3 MB is source maps and 964 KB is lunr
  language files (only loaded for non-English search). With `*.map` deleted it is **1.4 MB**.
  The content of about 90 pages adds roughly 1–2 MB of HTML plus the search index.
* **Licence notices.** The built theme assets carry no Material MIT text. The build must copy
  `mkdocs_material-9.7.7.dist-info/licenses/LICENSE` into the site. Zensical writes
  `assets/javascripts/LICENSE` itself.

#### F3. Inline scripts, CSP and Trusted Types (measured in headless Chromium)

The test setup served the build with FastAPI `StaticFiles` at `/learn`, plus a header middleware.
Playwright 1.63 and Chromium 1194 then exercised load, search, instant navigation, the palette
toggle, the 404 page and a 390 × 844 mobile viewport, while recording `securitypolicyviolation`
events.

* Every page has **4 inline executable scripts**:
  1. `__md_scope=new URL("<depth>",location)` plus helpers. This one differs by directory depth
     (`"."`, `".."`, `"../.."`), and in `404.html` it holds the absolute site path from `site_url`.
  2. Palette restore.
  3. Tab restore.
  4. A tab-target fix.
* There is also `<script id="__config" type="application/json">`, which is not executed and not
  subject to `script-src`.
* There are **no inline `style=` attributes** and no `<style>` blocks. The CSS uses `data:` SVG masks
  for icons.
* A 3-depth site produced **7 distinct hashes**. The number grows by one per directory depth.

| Policy on `/learn` | Result |
|---|---|
| Note 01 verbatim (`script-src 'self'`, `img-src 'self' blob:`, Trusted Types `'none'`) | **Broken.** All 4 inline scripts blocked, icons blocked (`img-src data:`), search box never becomes usable |
| Hashes in `script-src` **plus** `require-trusted-types-for 'script'` | **Broken.** `TrustedScriptURL` on `script.src`, the `Worker` constructor (search) and `DOMParser.parseFromString` (instant navigation) |
| `script-src 'self' 'sha256-…'×N; style-src 'self'; img-src 'self' data:; worker-src 'self'; connect-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'; object-src 'none'` | **Works.** Search ("2 matching documents"), instant navigation, palette, tabs, 404 (status 404, styled), mobile drawer and search. **Zero violations, zero external requests** |

#### F4. Serving inside FastAPI, and instant navigation

* `app.mount("/learn", StaticFiles(directory=…, html=True))` registered **before** the `/` mount:
  * serves `index.html` for directory URLs,
  * redirects `GET /learn` to `/learn/`,
  * serves `404.html` with status **404** for unknown paths.
* **`site_url` has three effects:**
  1. canonical links and `sitemap.xml`;
  2. the absolute base path in `404.html` (so the LAN build must have path `/learn/`);
  3. **instant navigation**. The bundle fetches `sitemap.xml`, rewrites each URL's protocol and
     **hostname** (not port) to the current page's (`function fi(e,t){e.protocol=t.protocol;e.hostname=t.hostname}`),
     and only does XHR navigation for URLs it finds there.
* **Measured:**
  * A build with `site_url` port 8772 kept one JS context across navigation on `127.0.0.1:8772`
    and on `localhost:8772`.
  * The same build served on port 8775 **fell back to normal page loads**. Pages still work; they are
    just not "instant".
  * Deleting `sitemap.xml` produces the same fallback plus a 404 per page.
* **Consequence.**
  * Keep `sitemap.xml` in the LAN build.
  * Build it with `site_url: http://localhost/learn/` (no port). Instant navigation then works for
    the usual reverse-proxied `https://host/learn/` (port 443) and `http://host/learn/` (port 80).
  * Direct `http://host:8000/learn/` gets ordinary page loads. That is acceptable.

#### F5. Container build constraints

* `.dockerignore` excludes `.git`. Plugins that read git history, such as
  `mkdocs-git-revision-date-localized-plugin` 1.6.0, cannot run in the image build. Put
  review dates in front matter instead.
* Python 3.14 (Chainguard `latest`, note 01) builds the site: tested with CPython 3.14.0rc2,
  mkdocs 1.6.1 and Material 9.7.7.
* The site is generated in a throw-away build stage. The runtime gets plain files, so no new
  runtime dependency is added.

#### F6. GitHub Pages (docs read 2026-10-05)

* **Availability.** "GitHub Pages is available in public repositories with GitHub Free and GitHub Free
  for organizations, and in public and private repositories with GitHub Pro, GitHub Team, GitHub
  Enterprise Cloud, and GitHub Enterprise Server" ([limits](https://docs.github.com/en/pages/getting-started-with-github-pages/github-pages-limits)).
* **Private Pages** need an organization on Enterprise Cloud. With Pro or Team, a Pages site built
  from a private repo is **public on the internet**
  ([plans](https://docs.github.com/en/get-started/learning-about-github/githubs-plans),
  [visibility](https://docs.github.com/en/enterprise-cloud@latest/pages/getting-started-with-github-pages/changing-the-visibility-of-your-github-pages-site)).
* **For this repo** (private, personal account): on Free there is no Pages until the repo goes
  public. On Pro the handbook can be published now, and it will be public. That is fine for
  handbook content, but it is a choice the owner must make.
* **Limits.**
  * Published site ≤ 1 GB.
  * Soft bandwidth limit 100 GB/month.
  * Deployments time out after 10 minutes.
  * The 10 builds/hour soft limit "does not apply if you build and publish your site with a custom
    GitHub Actions workflow".
  * Not for "sensitive transactions" or commercial SaaS.
* **Actions** (tags and SHAs from `git ls-remote`):

  | Action | Tag | SHA |
  |---|---|---|
  | actions/configure-pages | v6.0.0 | `45bfe0192ca1faeb007ade9deae92b16b8254a0d` |
  | actions/upload-pages-artifact | v5.0.0 | `fc324d3547104276b827a68afc52ff2a11cc49c9` |
  | actions/deploy-pages | v5.0.1 | `368f82528645a54fb793d4d04e342629a3f51346` |
  | actions/checkout | v7.0.1 | `3d3c42e5aac5ba805825da76410c181273ba90b1` (as note 01) |
  | actions/setup-python | v7.0.0 | `5fda3b95a4ea91299a34e894583c3862153e4b97` (as note 01) |
  | lycheeverse/lychee-action | v2.9.0 | `e7477775783ea5526144ba13e8db5eec57747ce8` |

* **Permissions.** The deploy job needs `pages: write` and `id-token: write`, and the
  `github-pages` environment ([deploy-pages README](https://github.com/actions/deploy-pages)).
  `upload-pages-artifact` excludes dotfiles unless `include-hidden-files: true`. Pages cannot set
  response headers, so the public copy has no CSP header. It is static and has no inputs.

#### F7. Alternatives

* **Docusaurus 3.10.2** (MIT). Requires Node ≥ 20, and its React SPA also needs inline scripts.
  Its "official" search is Algolia DocSearch, an external crawler and API. Local search exists only
  as community plugins, for example `@easyops-cn/docusaurus-search-local` 0.55.3
  ([Docusaurus search](https://docusaurus.io/docs/search)).
* **Starlight** (Astro) **0.42.5** is active but 0.x. **VitePress 1.6.4** has had no release since
  2025-08. **Sphinx 9.1.0** is a weaker fit for a patient audience. **Hugo** is a Go binary and would
  need a theme. **Plain HTML** has no search and no navigation without hand-written JS.

### Part B: content

#### F8. What "helpful, not a vague printout" means in practice

* KDIGO 2024 asks for patient education "that also involve[s] care partners" (PP 5.3.2) and supports
  "telehealth technologies including web-based, mobile applications" (PP 5.3.3) ([K24]).
* AHRQ's **PEMAT** scores understandability and actionability. Studies commonly treat ≥ 70 % as
  adequate. The CDC **Clear Communication Index** has a 90-point benchmark ([PEMAT], [CCI]).
* The useful things a printout lacks are:
  * numbers with units in both US and SI;
  * examples with real foods and servings;
  * checklists;
  * "what to ask your team";
  * "when to get help now";
  * the *reason* behind each rule;
  * day-to-day differences between stages and treatments.
* Every page template in [§4.9](#49-editorial-policy-page-template-and-clinical-review) has those parts.

#### F9. Facts that changed in 2025–2026 and must be in the handbook (verified 2026-10-05)

1. **Finerenone (Kerendia) is FDA-approved for CKD with type 1 diabetes.** The approval was on
   2026-09-17 and the label was revised 9/2026. The indication is "reduce urinary
   albumin-to-creatinine ratio (UACR) … in adults with CKD associated with Type 1 diabetes mellitus".
   * Do not start it if potassium is > 5.0 mEq/L.
   * Avoid grapefruit and grapefruit juice.
   * Strong CYP3A4 inhibitors are contraindicated ([KER]).
   * In FINE-ONE (n = 242, 6 months) UACR fell 25 % more than with placebo. Hyperkalaemia occurred
     in 10.1 % vs 3.3 %, and the eGFR dip was −5.6 vs −2.7 mL/min/1.73 m², reversible
     (N Engl J Med 2026;394(10):947–957, as reported) ([F1]).
2. **No SGLT2 inhibitor is approved for type 1 diabetes in the US.** KDIGO 2024 lists people with
   T1D as "understudied" in the SGLT2i trials ([K24], research recommendations). Sotagliflozin got an
   FDA complete response letter (December 2024); Lexicon expects to resubmit in Q4 2026, with a
   decision possible in 2027 (company filings). Pages must say that if prescribed off-label, ketone
   checks and sick-day rules are mandatory.
3. **KDIGO 2026 Anemia in CKD guideline** (published 2026-01-02) ([K26A]):
   * Anaemia is Hb < 13 g/dL (130 g/L) in men and < 12 g/dL (120 g/L) in women.
   * Iron deficiency is TSAT < 20 % with ferritin < 100 ng/mL (not on dialysis) or < 200 ng/mL
     (on hemodialysis).
   * Consider an ESA when Hb ≤ 9–10 g/dL. Do not use an ESA to keep Hb ≥ 11.5 g/dL.
   * Withhold iron if ferritin > 700 ng/mL or TSAT ≥ 40 % (HD algorithm).
4. **The KDIGO 2026 Diabetes in CKD update is a draft.** Public review closed 2026-04-13 and the work
   group is revising it. The 2022 guideline remains current ([K22]).
5. **KDIGO 2024 sick-day rules come with a caution** ([K24], PP 4.3.2–4.3.3 and Figure 47):
   * The "SADMANS" list is sulfonylureas, ACEi, diuretics, metformin, ARBs, NSAIDs and SGLT2i.
   * "There is a paucity of evidence", errors are common, and "the most reported problem is failure
     to restart".
   * Plans must be written down and include when to restart.
6. **DKA definition** (2024 ADA/EASD/JBDS/AACE/DTS consensus) ([HC24]):
   * glucose ≥ 200 mg/dL or known diabetes;
   * β-hydroxybutyrate ≥ 3.0 mmol/L or urine ketones ≥ 2+;
   * pH < 7.3 and/or bicarbonate < 18 mmol/L.

   People with advanced CKD often have a low bicarbonate anyway, so the handbook must tell them to
   treat ketones as the deciding number.
7. **Icodextrin (Extraneal) PD fluid** falsely raises glucose readings on GDH-PQQ, GDO and some
   GDH-FAD **meters** for up to two weeks after stopping. Deaths have resulted from insulin given for
   false highs, so use glucose-specific meters ([MHRA]).
8. **Medicare 2026** ([MED-ESRD], [CMS26], [MED-KDE]):
   * Part B premium $202.90/month, deductible $283.
   * Immunosuppressive-drug benefit (Part B-ID) $121.60/month.
   * ESRD coverage usually starts on the first day of the **fourth** month of dialysis, earlier with
     home-dialysis training.
   * Coverage ends 12 months after dialysis stops or **36 months after a transplant**.
   * A 30-month coordination period applies with employer plans.
   * Medicare Advantage is open to people with ESRD.
   * Kidney disease education: **up to 6 sessions at stage 4**.
9. **KDIGO nomenclature** prefers "kidney" over "renal" and "kidney failure" over "ESRD" ([K20NOM]).
   Use "ESRD" only when naming Medicare's legal category.

#### F10. Re-use and copyright of sources

* **NIDDK** health information is mostly public domain and may be reproduced with attribution.
  NIDDK/NIH logos must not be used, and some images are licensed ([NIDDK-copyright]).
* **KDIGO guidelines** are open access under **CC BY-NC-ND 4.0**, so no derivatives. Cite and
  paraphrase facts. Do **not** adapt KDIGO tables or figures. The risk heat map is itself reproduced
  from JAMA "All rights reserved". Build our own plain category tables from the definitions.
* **NKF, AKF, DaVita, ADA** pages and recipes are copyrighted. Link and paraphrase, and do not copy
  tables or recipes. **USDA FoodData Central** data (already used for `data/foods.json`) is public domain.

#### F11. Age and sex in a handbook

This reflects note 05 F16. Sex changes the anaemia thresholds (F9.3) and is an input to the CKD-EPI
2021 creatinine eGFR (with age). Age and sex change energy needs. They do not change protein per kg,
sodium, potassium or phosphorus limits. A labs page and an "Does age or sex change my numbers?"
section answer the owner's question in plain words and link to the app's target explanation.

---

## 3. Options compared

### 3.1 Site generator

| | **MkDocs 1.6.1 + Material 9.7.7** | Zensical 0.0.68 | Docusaurus 3.10.2 | Starlight 0.42.5 | Plain HTML |
|---|---|---|---|---|---|
| Licence | BSD-2 + MIT | MIT | MIT | MIT | – |
| Toolchain in image build | Python, same as the app | Python + Rust wheel | Node ≥ 20 | Node | none |
| Offline search over HTTP | Yes (lunr worker, tested) | Yes (new engine) | Plugin only (community) | Yes (Pagefind) | No |
| No external requests | Yes, with `font:false` and the privacy guard (tested) | Probably (bundle has lazy CDN URLs: pyodide, ace, glightbox, mermaid) | Algolia by default | Yes | Yes |
| CSP | Hashes work; no Trusted Types (tested) | Similar inline scripts (7 hashes, not browser-tested) | Inline scripts | Inline scripts | Trivial |
| Maintenance | Security fixes to Nov 2026 at least; MkDocs core unmaintained | Active, alpha | Active | Active, 0.x | You |
| Patient-friendly features | Admonitions, linked unit tabs, tooltips, task lists, print CSS, dark mode, instant nav | Same surface | Good | Good | Hand-built |
| Migration risk | Content and `mkdocs.yml` move to Zensical | n/a | Rewrite config, MDX | Rewrite config | n/a |
| **Verdict** | **Use for v0.3** | **CI canary**; switch when ≥ 0.1 passes the same tests | No | No | No |

### 3.2 Where the LAN copy lives

| | **Baked into the app image at `/learn`** | Separate static container (Caddy, nginx) | GitHub Pages only | Build at container start |
|---|---|---|---|---|
| Works without internet | Yes | Yes | No | Yes |
| Extra moving parts for homelab users | None (+~2–4 MB image) | A second service, port, proxy rule | None | Build deps at runtime |
| Read-only, rootless image | Yes (files root-owned) | Yes | n/a | **No** (writes at runtime) |
| Same auth and HTTPS as the app | Yes | Must duplicate | n/a | Yes |
| **Verdict** | **Chosen** | Documented as an option for strict origin isolation (R3) | Public copy only | Rejected |

### 3.3 CSP strategy for `/learn`

| | `'unsafe-inline'` | **Hashes computed at app startup from the files** | Hashes written at build time | Template overrides that remove all inline JS |
|---|---|---|---|---|
| Blocks injected inline script | No | **Yes** | Yes | Yes |
| Can go stale | No | **No** (reads what is served) | If the JSON and the site drift | When Material changes templates |
| Upkeep | none | ~30 lines, tested | build step plus file | Override 4 template blocks; fragile across theme updates |
| **Verdict** | Rejected | **Chosen** | Fallback | Rejected |

### 3.4 Public hosting

| | **Pages via a custom Actions workflow** | `mkdocs gh-deploy` (`gh-pages` branch) | Netlify or Cloudflare Pages | None |
|---|---|---|---|---|
| Needs a token with write access to a branch | No (OIDC deploy) | Yes | Third-party app | – |
| Plan requirement | Public repo, or Pro/Team for private | same | No | – |
| Fits note 01 (SHA pins, least privilege) | Yes | Weaker | Extra trust | – |
| **Verdict** | **Chosen, opt-in via a repo variable** | No | No | Until the owner opts in |

### 3.5 Content structure

| | One long guide (today's `diet-guide.md`) | **Task pages plus stage hubs plus generated menus** | Separate full guide per stage |
|---|---|---|---|
| Findable on a phone, linkable from app warnings | Poor | **Good** (one slug per topic) | Good |
| Duplication and drift | None | Low (stage hubs link to topic pages) | High (6× the same text) |
| Numbers stay in step with the app | Manual | **Generated** from `targets_by_stage.json`, `foods.json` and `suggest_targets()` | Manual |
| **Verdict** | Migrate away | **Chosen** | No |

---

## 4. Recommendation

### 4.1 Decision summary

1. **Use MkDocs 1.6.1 + Material for MkDocs 9.7.7 (MIT)** for v0.3, with pymdown-extensions 12.1.
   * Install from a hash-locked `handbook/requirements.lock`.
   * Set `font: false` and the privacy plugin with `assets_fetch: false` and
     `assets_exclude: ["unpkg.com/*"]`, with strict builds. Any external asset then fails CI.
   * Do not use the offline plugin, Mermaid, MathJax, `repo_url` or analytics.
   * Run a **Zensical canary** CI job that is allowed to fail. Migrate when Zensical ≥ 0.1 passes
     the same tests, and before Material fixes stop.
2. **Bake the site into the app image** and serve it at **`/learn/`**:
   * read-only `StaticFiles`, mounted before `/`;
   * a path-scoped CSP using **inline-script hashes computed at startup**, `img-src 'self' data:`,
     and no Trusted Types;
   * `immutable` caching for fingerprinted assets.
3. **Publish a public copy to GitHub Pages** from a dedicated workflow with SHA-pinned actions. It only
   deploys when the repo variable `HANDBOOK_PAGES` is `true` (needs a public repo, or Pro/Team, F6).
4. **Write the content as task-oriented pages with stage "hub" pages.** Generate menus, grocery lists
   and the targets table from the same data the app uses.
   * Every medical page has front-matter review metadata and ≥ 3 primary sources.
   * Pages carry a draft banner until a clinician reviews them.
   * No dosing advice.
5. **Licence the handbook text CC BY-NC-SA 4.0 (owner to confirm).** Code stays PolyForm
   Noncommercial. CC BY 4.0 is the alternative if for-profit dialysis clinics should be able to hand
   it out.

### 4.2 File layout (new or changed)

```
handbook/
  mkdocs.yml                       §4.3
  requirements.in                  mkdocs==1.6.1, mkdocs-material==9.7.7, pymdown-extensions==12.1, pyyaml
  requirements.lock                pip-compile --generate-hashes (note 01 scripts/lock.sh)
  sources.yml                      bibliography: id → cite, url, licence, checked (§4.9)
  data/menus.yml                   7-day menus per stage, by fdc_id + servings (§5.5)
  data/recipes.yml                 original recipes, ingredients by fdc_id + grams
  includes/abbreviations.md        hand-written: *[eGFR]: estimated glomerular filtration rate …
  includes/sources.md              GENERATED: [kdigo-ckd-2024]: https://… "KDIGO 2024 …" (reference links)
  overrides/main.html              announce bar (back to app, get help now), draft banner, last-reviewed line
  docs/
    index.md                       Start here
    get-help-now.md
    ckd/ stages/ labs/ eat/ t1d/ medicines/ prepare/ living/ reference/   (Part B, §5)
    app/ self-hosting/                                                     (§5.11, §5.12)
    eat/menus/*.md                 GENERATED (do not edit)
    eat/grocery-lists.md           GENERATED
    eat/_targets-table.md          GENERATED snippet (not in nav), included by eat/index.md
    assets/icon.svg                copied from app/static/icons/icon.svg (note 02)
    assets/licences/material-LICENSE.txt   MIT text of Material (F2)
    stylesheets/extra.css          print styles, wallet card, tables on narrow screens
scripts/build_handbook.py          generate + --check (§4.5)
app/handbook.py                    mount, CSP hashes, cache headers (§4.6)
tests/test_handbook_serving.py     main pytest job; uses a tiny fixture site in tests/fixtures/learn/
tests/test_handbook_content.py     handbook CI job; front matter, sources, slugs, safety lints (§4.9)
.github/workflows/ci.yml           + job "handbook"; image job needs it
.github/workflows/handbook-pages.yml
.github/workflows/handbook-links.yml   weekly external-link check
deploy/Containerfile               + stage "handbook" (§4.7)
.dockerignore                      + handbook/site, handbook/.cache
docs/diet-guide.md                 replaced by a pointer to /learn/eat/ (§4.11)
docs/deployment.md, docs/network-allowlist.md   moved to handbook/docs/self-hosting/ with pointer stubs
```

### 4.3 `handbook/mkdocs.yml`

Build from inside `handbook/` (`cd handbook && mkdocs build`). This way snippet paths resolve from the
config directory for both MkDocs and Zensical.

```yaml
site_name: Kidney Health Handbook
site_description: Practical, sourced guidance for living with chronic kidney disease and type 1 diabetes.
# LAN build: http://localhost/learn/ (no port; see F4). Pages build: base_url from configure-pages.
site_url: !ENV [HANDBOOK_SITE_URL, "http://localhost/learn/"]
docs_dir: docs
site_dir: site
strict: true
exclude_docs: |
  _drafts/
not_in_nav: |
  eat/_targets-table.md
validation:
  nav: {omitted_files: warn, not_found: warn, absolute_links: info}
  links: {not_found: warn, anchors: warn, absolute_links: warn, unrecognized_links: warn}

theme:
  name: material
  custom_dir: overrides
  language: en
  font: false                       # system fonts; no Google Fonts
  logo: assets/icon.svg
  favicon: assets/icon.svg
  palette:
    - media: "(prefers-color-scheme: light)"
      scheme: default
      primary: teal
      toggle: {icon: material/weather-night, name: Switch to dark mode}
    - media: "(prefers-color-scheme: dark)"
      scheme: slate
      primary: teal
      toggle: {icon: material/weather-sunny, name: Switch to light mode}
  features:
    - navigation.instant            # needs sitemap.xml and matching port (F4); falls back gracefully
    - navigation.instant.progress
    - navigation.tabs               # Handbook · Using the app · Self-hosting · About
    - navigation.sections
    - navigation.indexes
    - navigation.path               # breadcrumbs (free since 9.7.0)
    - navigation.top
    - navigation.footer
    - toc.follow
    - search.suggest
    - search.highlight
    - content.tabs.link             # "US units" / "International" tabs stay in sync across pages
    - content.tooltips              # abbreviation tooltips

plugins:
  - search:
      lang: en
  - privacy:
      assets_fetch: false           # never download; with strict, any external asset fails the build
      assets_exclude: ["unpkg.com/*"]   # the theme bundle's lazy URLs (mermaid, RO polyfill)
      links_attr_map: {target: _blank}
      links_noopener: true

extra:
  app_link: !ENV [HANDBOOK_APP_LINK, ""]   # "/" in the image build, empty on Pages
  generator: false
  social:
    - icon: fontawesome/brands/github
      link: https://github.com/ksullivan86/kidney-health
extra_css:
  - stylesheets/extra.css
copyright: >-
  Education, not medical advice. Text CC BY-NC-SA 4.0 (proposed) ·
  <a href="https://github.com/ksullivan86/kidney-health">source</a>

markdown_extensions:
  - abbr
  - admonition
  - attr_list
  - def_list
  - footnotes
  - md_in_html
  - tables
  - toc: {permalink: true}
  - pymdownx.details
  - pymdownx.superfences            # no custom fences: no Mermaid
  - pymdownx.tabbed: {alternate_style: true}
  - pymdownx.tasklist: {custom_checkbox: true}
  - pymdownx.snippets:
      auto_append: [includes/abbreviations.md, includes/sources.md]
      check_paths: true

nav:  # abbreviated; full order follows §5
  - Handbook:
      - index.md
      - Get help now: get-help-now.md
      - Understanding CKD: [ckd/index.md, ckd/stages.md, ckd/diabetes-and-your-kidneys.md]
      - Your stage, day to day: [stages/index.md, stages/g1-g2.md, "…"]
      - Lab results: [labs/index.md, "…"]
      - Eating well: [eat/index.md, "…"]
      - Type 1 diabetes and CKD: [t1d/index.md, "…"]
      - Medicines and tests: ["…"]
      - Preparing for treatment: ["…"]
      - Living well: ["…"]
  - Using the app: [app/index.md, "…"]
  - Self-hosting: [self-hosting/index.md, "…"]
  - About: [reference/glossary.md, reference/units.md, reference/sources.md, reference/about.md, reference/licences.md]
```

`handbook/overrides/main.html` (tested with MkDocs; Zensical rendered it too):

```jinja
{% extends "base.html" %}
{% block announce %}
  {% if config.extra.app_link %}<a href="{{ config.extra.app_link }}">&larr; Back to the food log</a> &middot; {% endif %}
  <a href="{{ 'get-help-now/' | url }}"><strong>Get help now</strong></a>
{% endblock %}
{% block content %}
  {% set review = page.meta.review if page and page.meta and page.meta.review else none %}
  {% if review and review.status != "reviewed" %}
    <div class="admonition warning"><p class="admonition-title">Draft</p>
    <p>This page has not yet been checked by a clinician. Use it to prepare questions for your care team.</p></div>
  {% endif %}
  {{ super() }}
  {% if review and review.last_reviewed %}<p class="kh-reviewed">Last reviewed {{ review.last_reviewed }}{% if review.reviewed_by %} by {{ review.reviewed_by }}{% endif %}.</p>{% endif %}
{% endblock %}
```

iOS Home Screen apps (note 02) have no browser back button. The announce bar's "Back to the food log"
link is the way out of `/learn` in standalone mode.

### 4.4 Build commands and the image stage

```bash
# local preview (contributors)
python -m venv .venv-hb && .venv-hb/bin/pip install --require-hashes -r handbook/requirements.lock
.venv-hb/bin/python scripts/build_handbook.py            # regenerate menus, grocery lists, sources.md
cd handbook && NO_MKDOCS_2_WARNING=true ../.venv-hb/bin/mkdocs serve
```

### 4.5 `scripts/build_handbook.py` (dev-only; runs in the handbook venv)

* `--write` (the default) regenerates:
  * `includes/sources.md`, as reference-link definitions from `sources.yml`;
  * `docs/eat/_targets-table.md`, from `docs/research/targets_by_stage.json`;
  * `docs/eat/menus/*.md` and `docs/eat/grocery-lists.md`, from `data/menus.yml` + `data/foods.json`;
  * recipe nutrient tables, from `data/recipes.yml`;
  * `docs/assets/licences/material-LICENSE.txt`, from the installed dist-info;
  * `docs/assets/icon.svg`, from `app/static/icons/icon.svg`.
* **Targets for menus come from `app.nutrients.suggest_targets()`** for a stated reference person
  (70 kg ideal body weight, 170 cm), so the handbook and the app never disagree. `nutrients.py` is
  stdlib-only.
* **Menu checks.** Each day's totals must satisfy that stage's targets (§5.5 table). Every `fdc_id`
  must exist in `foods.json`. Carbohydrate per meal must stay within ±10 g of the menu's stated
  per-meal amount. Any failure exits 1.
* `--check` regenerates in memory and exits 1 if any generated file differs. CI runs it, the same
  way `data/foods.json` is committed and regenerated today. Generated files start with
  `<!-- GENERATED by scripts/build_handbook.py; do not edit -->`.

### 4.6 Serving at `/learn` (`app/handbook.py`)

```python
# Sketch; the backend owner writes the real module.
INLINE_SCRIPT = re.compile(r"<script(?![^>]*\bsrc=)(?![^>]*type=\"application/json\")[^>]*>(.*?)</script>", re.S)

def script_hashes(site: Path, limit: int = 64) -> list[str]:
    hashes = {"'sha256-" + base64.b64encode(hashlib.sha256(b.encode()).digest()).decode() + "'"
              for f in site.rglob("*.html") for b in INLINE_SCRIPT.findall(f.read_text("utf-8"))}
    if len(hashes) > limit:
        raise RuntimeError(f"{len(hashes)} inline scripts in handbook; refusing to build a CSP")
    return sorted(hashes)

def handbook_csp(hashes: list[str]) -> str:
    return ("default-src 'self'; script-src 'self' " + " ".join(hashes) + "; style-src 'self'; "
            "img-src 'self' data:; font-src 'self'; connect-src 'self'; worker-src 'self'; "
            "manifest-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'; "
            "frame-ancestors 'none'")
```

* **Mount.** In `create_app()`, if `settings.handbook_dir / "index.html"` exists, compute the hashes
  once and call `app.mount("/learn", StaticFiles(directory=…, html=True), name="learn")` **before**
  the `/` mount. Otherwise `/learn` returns 404, and the app's Learn link points to
  `HANDBOOK_PUBLIC_URL` when that is set.
* **Headers.** Note 01's `SecurityHeadersMiddleware` uses `handbook_csp` for `path == "/learn"` or
  `path.startswith("/learn/")`, and the app CSP everywhere else. Other headers stay the same
  (`nosniff`, `no-referrer`, COOP, CORP, `X-Frame-Options: DENY`, HSTS over https).
  `upgrade-insecure-requests` is added over https exactly as for the app.
* **Cache.**
  * Files matching `^/learn/assets/.*\.[0-9a-f]{8}\.min\.(js|css)$` get
    `Cache-Control: public, max-age=31536000, immutable`.
  * Everything else under `/learn` gets `no-cache`. Starlette already sends ETag and Last-Modified.
* **Auth.**
  * Under note 07 the handbook is static and data-free, like the app shell, so it is **public**.
  * Under legacy `APP_PASSWORD` it sits behind Basic auth like every other path.
  * No new switch is needed.
* **Service worker.** Note 02 R4 already leaves `/learn` to the network. Offline caching of handbook
  pages is a v0.4 runtime cache.
* **Configuration keys:**

  | Key | Default | Purpose |
  |---|---|---|
  | `HANDBOOK_DIR` | `/app/learn` in the image; `<repo>/handbook/site` otherwise | Built site to serve at `/learn`. Missing means `/learn` is 404 |
  | `HANDBOOK_PUBLIC_URL` | empty (set to the Pages URL once published) | Fallback link and "public copy" link in Settings → About |

* **Stricter isolation option.** This goes in `self-hosting/security`. Operators can serve the handbook
  from its own origin (`learn.example.org`) with a reverse proxy, so the relaxed CSP never shares an
  origin with the API. The default keeps one origin because it is the simplest homelab setup.

### 4.7 Container stage (fits note 01's Chainguard Containerfile)

```dockerfile
# Throw-away stage: only /out/learn reaches the runtime image.
FROM cgr.dev/chainguard/python:latest-dev@sha256:<same digest as the builder stage> AS handbook
USER root
WORKDIR /src/handbook
COPY handbook/requirements.lock /tmp/handbook.lock
RUN python -m venv /opt/hb \
 && /opt/hb/bin/pip install --no-cache-dir --require-hashes -r /tmp/handbook.lock
COPY handbook/ /src/handbook/
ENV NO_MKDOCS_2_WARNING=true \
    HANDBOOK_SITE_URL=http://localhost/learn/ \
    HANDBOOK_APP_LINK=/
RUN /opt/hb/bin/mkdocs build --strict -d /out/learn \
 && find /out/learn -name '*.map' -delete            # keep sitemap.xml (instant navigation, F4)

# … runtime stage (note 01) …
COPY --from=handbook /out/learn /app/learn          # root-owned, read-only like /app
ENV HANDBOOK_DIR=/app/learn
```

Generated files are committed and checked by CI, so the image build needs nothing from `docs/` or
`data/`. The `.dockerignore` stays as it is apart from `handbook/site` and `handbook/.cache`.

### 4.8 CI and Pages

**`ci.yml`, new job `handbook`.** The `image` job adds it to `needs:`.

1. Check out and set up Python 3.14 (SHA pins as in note 01).
2. `pip install --require-hashes -r handbook/requirements.lock`.
3. `python scripts/build_handbook.py --check`.
4. `cd handbook && NO_MKDOCS_2_WARNING=true mkdocs build --strict`.
5. `pytest tests/test_handbook_content.py`.
6. The Playwright CSP smoke test from note 01 R4 also loads `/learn/`, runs a search, follows a link,
   and fails on any `securitypolicyviolation`.
7. A second job, **`handbook-zensical`**, runs with `continue-on-error: true`. It installs
   `zensical==0.0.68` and runs `zensical build -f mkdocs.yml -s`.

**`.github/workflows/handbook-pages.yml`:**

```yaml
name: Handbook (GitHub Pages)
on:
  push:
    branches: [main]
    paths: ["handbook/**", "scripts/build_handbook.py", "data/foods.json", "docs/research/targets_by_stage.json"]
  workflow_dispatch:
permissions: {}
concurrency: {group: pages, cancel-in-progress: false}
jobs:
  build:
    if: vars.HANDBOOK_PAGES == 'true'      # needs a public repo, or Pro/Team (site is then public)
    runs-on: ubuntu-latest
    permissions: {contents: read}
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
        with: {persist-credentials: false}
      - uses: actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97 # v7.0.0
        with: {python-version: "3.14"}
      - run: pip install --require-hashes -r handbook/requirements.lock
      - run: python scripts/build_handbook.py --check
      - id: pages
        uses: actions/configure-pages@45bfe0192ca1faeb007ade9deae92b16b8254a0d # v6.0.0
      - name: Build
        working-directory: handbook
        env:
          HANDBOOK_SITE_URL: ${{ steps.pages.outputs.base_url }}/
          NO_MKDOCS_2_WARNING: "true"
        run: mkdocs build --strict -d "$RUNNER_TEMP/site" && find "$RUNNER_TEMP/site" -name '*.map' -delete
      - uses: actions/upload-pages-artifact@fc324d3547104276b827a68afc52ff2a11cc49c9 # v5.0.0
        with: {path: "${{ runner.temp }}/site"}
  deploy:
    needs: build
    runs-on: ubuntu-latest
    permissions: {pages: write, id-token: write}
    environment: {name: github-pages, url: "${{ steps.deployment.outputs.page_url }}"}
    steps:
      - id: deployment
        uses: actions/deploy-pages@368f82528645a54fb793d4d04e342629a3f51346 # v5.0.1
```

**Owner setup:**

1. Settings → Pages → Source: **GitHub Actions**.
2. Keep the `github-pages` environment restricted to `main`.
3. Set the repository variable `HANDBOOK_PAGES=true`.

After that, update the image label `org.opencontainers.image.documentation` and `HANDBOOK_PUBLIC_URL`
to the Pages URL.

**`.github/workflows/handbook-links.yml`** runs weekly (Monday 06:17 UTC) and on dispatch, using
lychee-action v2.9.0 (SHA above). It checks every URL in `handbook/sources.yml` and in the built
site's external links. Accept `200..=299, 403, 429`, because NIH, TSA and SSA return 403 to bots. On
failure it opens or updates one issue labelled `handbook-links`
(`permissions: {contents: read, issues: write}`).

### 4.9 Editorial policy, page template and clinical review

This goes in `handbook/docs/reference/about.md`, and `tests/test_handbook_content.py` enforces it.

**Front matter (every page):**

```yaml
---
title: Potassium
description: How much potassium is in common foods, when to limit it, and what high blood potassium feels like.
slug: potassium                 # = file stem (or folder name for index.md); unique site-wide; the app links by slug
audience: [patient, caregiver]  # patient | caregiver | clinician | app-user | self-hoster
applies_to: [G3a, G3b, G4, G5, HD, PD]   # G1-G2 | G3a | G3b | G4 | G5 | HD | HHD | PD | Tx | all
review:
  status: draft                 # draft | reviewed
  last_reviewed: 2026-10-05
  reviewed_by: ""               # e.g. "J. Doe, RDN, CSR"; required when status is reviewed
  next_review: 2027-10-05
figures_as_of: 2026-10-05       # optional; required on pages with prices, benefit amounts or laws
---
```

**Page template (medical pages).** Use these sections in this order:

1. **In short**: 3–5 sentences.
2. **Your numbers**: a key-numbers box, with `=== "US units"` / `=== "International"` tabs wherever
   the units differ.
3. **What to do**: a checklist using `- [ ]` task lists, which print well.
4. **Examples**: real foods and servings from USDA FDC, or worked cases.
5. **Ask your care team**: 3–6 specific questions.
6. **Get help now if…**: red flags plus a link to `/learn/get-help-now/`.
7. **Sources**: reference links such as `[KDIGO 2024 CKD guideline][kdigo-ckd-2024], PP 3.11.5.1`.

**Rules enforced by tests** (fail unless marked warn):

* Front matter is complete. Slugs are unique and equal to the file stem or folder. Dates are ISO.
* Medical sections (`get-help-now`, `ckd/`, `stages/`, `labs/`, `eat/`, `t1d/`, `medicines/`,
  `prepare/`, `living/`) have a `## Sources` heading with **≥ 3** reference links. Every `[…][id]`
  exists in `sources.yml`. Unused ids only warn.
* **No dosing.** Under `t1d/` and `medicines/` the regex `\b\d+(\.\d+)?\s*(units?|U)\b` and
  `\bmg\b` next to a drug name fail the build. Allowed exceptions use an inline
  `<!-- dose-ok: quoting label -->` marker that the reviewer checks.
* No raw `<script>`, `<iframe>`, `style=` or external `<img>`. The privacy plugin also blocks external
  images.
* Warnings only:
  * `review.last_reviewed` older than 365 days;
  * `figures_as_of` older than 1 January of the current year;
  * Flesch-Kincaid grade > 9 on patient pages (textstat 0.7.13);
  * "ESRD" outside `living/costs-and-benefits`;
  * "renal" in a title.
* `TOPIC_PAGES` slugs in `app/guidance/topics.py` (note 06) all exist (§4.10).

**Writing rules:**

* Explain the reason behind every rule.
* Every number has a unit and a source. Give ranges and say "your lab's range wins".
* Never tell people to stop or change a medicine or insulin dose. Write "ask your team whether to
  pause X when you are ill", and have them get it written down.
* Use KDIGO terms (kidney failure, kidney replacement therapy) and people-first language.
* Use the US first, with an "Outside the US" note where systems differ.
* Do not copy NKF, AKF, DaVita or ADA text or recipes, or KDIGO tables and figures (F10). Quote at
  most one sentence with attribution.

**Clinical review roles:**

| Area | Reviewer |
|---|---|
| `eat/` | renal dietitian (RDN, ideally CSR) |
| `stages/`, `labs/`, `medicines/`, `prepare/`, `get-help-now` | nephrologist or nephrology NP/PA |
| `t1d/` | diabetes specialist or CDCES |
| Every patient page | one patient or caregiver reviewer, for clarity (PEMAT ≥ 70 %) |

**Review cadence:**

* every 12 months;
* each December, after the ADA Standards and any new KDIGO guideline;
* within 30 days of an FDA approval or a safety communication that touches a page;
* each November for `living/costs-and-benefits` (Medicare amounts).

**`handbook/sources.yml` entry:**

```yaml
kdigo-ckd-2024:
  cite: "KDIGO 2024 Clinical Practice Guideline for the Evaluation and Management of CKD. Kidney Int 2024;105(4S):S117–S314."
  url: https://kdigo.org/wp-content/uploads/2024/03/KDIGO-2024-CKD-Guideline.pdf
  licence: CC BY-NC-ND 4.0 (cite and paraphrase only)
  checked: 2026-10-05
```

### 4.10 App integration: slugs, links and the Learn entry

* **Nav.** Add a **Learn** item to the app's navigation and to Settings → About & privacy (note 07
  §4.17), opening `/learn/` in the same window. Warnings, insights, guidance and AI cards link to
  `/learn/<path>/` by slug.
* **Final slug → URL table** for notes 04 and 06 `TOPIC_PAGES`. Replace `/handbook/<slug>/` with these:

  | slug (note 06) | URL |
  |---|---|
  | `potassium` | `/learn/eat/potassium/` |
  | `potassium-leaching` | `/learn/eat/potassium-leaching/` |
  | `phosphorus` | `/learn/eat/phosphorus/` |
  | `phosphate-additives` | `/learn/eat/phosphate-additives/` |
  | `sodium` | `/learn/eat/sodium/` |
  | `fluid` | `/learn/eat/fluid/` |
  | `protein` | `/learn/eat/protein/` |
  | `eating-enough` | `/learn/eat/eating-enough/` |
  | `carb-counting` | `/learn/eat/carb-counting/` |
  | `treating-a-low` | `/learn/t1d/treating-a-low/` |
  | `dialysis-days` | `/learn/eat/dialysis-days/` |
  | `label-reading` | `/learn/eat/label-reading/` |
  | `eating-out` | `/learn/eat/eating-out/` |
  | `portions` | `/learn/eat/portions/` |
  | new: `sick-days` | `/learn/t1d/sick-days/` |
  | new: `get-help-now` | `/learn/get-help-now/` |
  | new: `blood-potassium` | `/learn/labs/blood-potassium/` |
  | new: `targets-and-warnings` | `/learn/app/targets-and-warnings/` |

* **Test.** `tests/test_handbook_serving.py` (or note 06's topics test) asserts that every
  `TOPIC_PAGES` path matches `handbook/docs/<path>.md` or `<path>/index.md`.
* **Idea for v0.4.** "Add this menu day to my plan" can turn a generated menu day into planned
  entries, because menus use builtin `fdc_id`s. Similarly, a "finerenone" profile flag could warn on
  grapefruit, as the Kerendia label says to avoid it.

### 4.11 Migrating today's documents

| `docs/diet-guide.md` section | Becomes |
|---|---|
| "Please read this first" | `reference/about` (disclaimer) + a short admonition on `eat/index` |
| §1 The short version | `eat/index` → "In short" |
| §2 "The five numbers and the sixth" (rows) | `eat/potassium`, `eat/phosphorus`, `eat/sodium`, `eat/protein`, `eat/fluid`, `eat/carb-counting` (why it is limited, what happens if not) |
| §2 Typical daily targets by stage | `eat/_targets-table.md` (generated) included in `eat/index`, linked from each stage page |
| §2 Day by day or weekly average | `eat/index` + `app/targets-and-warnings` |
| §3 EAT, LIMIT and AVOID lists | `eat/food-lists` (tabs Eat / Limit / Avoid); nutrient pages include their relevant rows |
| §4 Carb counting with renal swaps | `eat/carb-counting` |
| §4 Treating a low | `t1d/treating-a-low` |
| §4 For the clinician | `t1d/index` (collapsed "For your clinician" block) |
| §4 CGM and A1c | `labs/a1c`, `labs/cgm-metrics` |
| §5 Reading the label | `eat/label-reading`, `eat/phosphate-additives` |
| §5 Potassium leaching | `eat/potassium-leaching` |
| §5 Eating out | `eat/eating-out` |
| §5 Salt substitutes | `eat/sodium` (+ `medicines/avoid`) |
| §5 Supplements and OTC products | `medicines/supplements`, `medicines/avoid` |
| §6 Sample day | `eat/menus/g3-g4` Day 1 (generated from `menus.yml`) |
| §7 How the app uses this | `app/targets-and-warnings` |
| §8 Sources | `handbook/sources.yml` ids; the diet guide's numbers are kept in a `dg:` field for traceability |

* Afterwards `docs/diet-guide.md` becomes a 5-line pointer. Update the code comments that cite
  "docs/diet-guide.md section N" to cite the new page paths.
* `docs/deployment.md` and `docs/network-allowlist.md` move to `self-hosting/` and leave pointer stubs.
* README links switch to `/learn/…` or Pages URLs, and the "Project layout" section gains `handbook/`.
* `docs/research/` stays as the evidence base for contributors. It is not published.

---

## 5. Content plan (Part B)

**Conventions:**

* **Audience:** P = patient, C = caregiver, Cl = clinician skim, U = app user, H = self-hoster.
* **Applies to:** stage tags as in the front matter.
* **Source ids** are defined in [§5.13](#513-bibliography-source-ids-for-handbooksourcesyml).
  `DGn` means source *n* of `docs/diet-guide.md` §8 (already fact-checked).
* "Must teach" lists the minimum concrete content. Every number below was checked against its source
  on 2026-10-05. Page paths are relative to `/learn/`.

### 5.1 Start here and Get help now

| Page | Audience | Must teach | Sources |
|---|---|---|---|
| `index` (Start here) | P, C | **Who the handbook is for:** CKD with type 1 diabetes, any stage, plus caregivers. **What it is not:** your care team's advice. **How to use it:** a "find your stage" chooser (eGFR, dialysis type, transplant) linking to stage hubs. **The 5 things to know today:** never skip treating a low; your sick-day plan; your potassium and fluid rules if you have them; star fruit is never allowed; bring questions to every visit. Where your numbers come from (lab report, the app). Units tabs explained. Last-reviewed and draft banners explained. | K24 (PP 5.3.2), A26-6, DG17/DG39, NIDDK-CKD |
| `get-help-now` | P, C | **Three tiers in one table, printable as a wallet card.** **Call 911 (or 112, 999, 000):** chest pain; severe breathlessness or unable to lie flat or frothy cough (fluid overload); fainting, very slow or irregular pulse, or sudden severe weakness, especially with known high potassium or a lab K ≥ 6.5 mmol/L (KDIGO "severe: take immediate action"); new confusion, seizure or unrousable drowsiness; a low the person cannot treat themselves (give glucagon, then call); vomiting with blood ketones ≥ 3.0 mmol/L, deep fast breathing or fruity breath (possible DKA); bleeding from a fistula or graft that does not stop after 10 minutes of firm pressure; fever with chills after a transplant. **Call your team today:** K 6.0–6.4 on a lab (KDIGO: assess in hospital if unwell, otherwise repeat within 24 h); blood ketones 1.6–2.9 mmol/L, or glucose above about 250 mg/dL (13.9 mmol/L) not falling for 2 h; vomiting, diarrhoea or not eating (start your sick-day plan); cloudy PD fluid, belly pain or fever on PD (keep the bag); no buzz (thrill) in the fistula, or redness or pus at an access or exit site; much less urine, new swelling, or weight gain above your team's alarm number; a missed dialysis session; repeated or unnoticed lows. **Mention at your next visit:** itch, tiredness, poor appetite, restless legs, low mood, poor sleep. Outside the US: local emergency numbers and the national kidney charity. | K24 (Table 28, Table 41, PP 5.2.2.1), HC24, NHSK, A26-6, I22P, Q19VA |

### 5.2 Understanding CKD

| Page | Audience | Must teach | Sources |
|---|---|---|---|
| `ckd/index` (What CKD is) | P, C | **What kidneys do:** filter waste, balance potassium, sodium, acid and water, make the hormones for red cells and bone. **The definition:** kidney damage or eGFR < 60 lasting > 3 months. CKD is usually silent until late. Damage can often be slowed but rarely reversed. Heart disease is the main risk at every stage. Words used: "kidney failure" (not ESRD), "kidney replacement therapy". | K24 (Tables 1–3), K20NOM, NIDDK-CKD, NKF-eGFR |
| `ckd/stages` | P, C | **G categories** (mL/min/1.73 m²): G1 ≥ 90, G2 60–89, G3a 45–59, G3b 30–44, G4 15–29, G5 < 15. **A categories** (UACR): A1 < 30 mg/g (< 3 mg/mmol), A2 30–300 (3–30), A3 > 300 (> 30). Risk rises with both, so "G3a A3" is higher risk than "G3b A1". Explained in our own table, not KDIGO's figure (F10). **Kidney-failure risk (KFRE):** 5-year risk 3–5 % is a reason to see a nephrologist; 2-year risk > 10 % is when to join multidisciplinary care; > 40 % is when to prepare for dialysis or transplant. KFRE is not valid at G1–G2. Checks: GFR and UACR at least yearly, more often at higher risk. An eGFR change > 20 % or a UACR doubling is "more than noise". | K24 (Tables 2–3, PP 2.1.1–2.1.5, PP 2.2.1–2.2.4), NIDDK-tests, NKF-eGFR |
| `ckd/diabetes-and-your-kidneys` | P, C | How type 1 diabetes damages the filters over years. Why albumin in the urine is the early sign. **What slows it:** glucose in range, blood pressure (systolic < 120 if tolerated, KDIGO; ADA < 130/80), ACE inhibitor or ARB when albuminuria is present, finerenone (FDA 2026 for T1D), no smoking, activity. What is *not* approved in T1D (SGLT2 inhibitors) and why (DKA). **When to suspect another cause:** sudden change, blood in urine, no retinopathy (ask). | K22, K24 (Rec 3.4.1, 3.6.3), A26-11, KER, F1, NIDDK-DKD |

### 5.3 Your stage, day to day (hub pages)

Every stage page has the same structure:

* what this stage means;
* how people usually feel;
* **what changes now** (diet, medicines, labs, diabetes);
* a "your starting numbers" row from the generated targets table;
* labs to expect and how often;
* a checklist;
* questions to ask;
* red flags (link to get-help-now);
* links to topic pages.

| Page | Audience | Must teach | Sources |
|---|---|---|---|
| `stages/index` | P, C | Chooser: by eGFR and treatment. "Stages are labels for risk and planning, not a countdown." Many people stay at one stage for years. | K24, NIDDK-CKD |
| `stages/g1-g2` | P | **Kidneys still filter well, but albumin leaks.** **Goals:** BP, glucose, an ACEi or ARB if A2–A3 (KDIGO 1B), and ask about finerenone. **Diet:** no potassium or phosphorus limit unless labs are high; sodium < 2,000 mg; protein about 0.8 g/kg and avoid > 1.3 g/kg; a plant-forward pattern. Activity ≥ 150 min/week. GFR and UACR at least yearly. **Checklist:** home BP log, UACR result, no NSAIDs as a habit. | K24 (Rec 3.4.1, 3.6.3, 3.2.2.1, PP 3.3.1.1, 2.1.1), K22, DG1, A26-11 |
| `stages/g3a` | P, C | **Medicines start being dosed by eGFR**, so tell every prescriber and pharmacist. Avoid NSAIDs. **New labs from G3a:** calcium, phosphate, PTH, alkaline phosphatase; also haemoglobin. Potassium and phosphorus limits only if labs are high. **Hypo risk starts to rise** as the kidney clears less insulin. KFRE becomes meaningful. **Sick-day plan:** get one now. | K24 (PP 4.2.1, 4.1.3), K17 (Rec 3.1.1), K26A, AK22, K24 (PP 4.3.2) |
| `stages/g3b` | P, C | **Same as G3a, plus:** a nephrology referral if KFRE 5-year risk ≥ 3–5 % or other criteria; check bicarbonate (treatment considered < 18 mmol/L); potassium limits more often needed (review ceiling about 3,500 mg/day in the app); anaemia work-up when Hb is low (iron first). Protein 0.6–0.8 g/kg with diabetes (KDOQI), or 0.8 (KDIGO). Your dietitian decides. | K24 (PP 2.2.1, 3.10.1, 3.11.5.1), Q20 (3.1.3), K26A, DG26 |
| `stages/g4` | P, C | **The planning stage.** Learn about all options now: home or in-centre HD, PD, transplant (pre-emptive is best), and comprehensive conservative care. **Transplant:** referral at eGFR < 30 and at least 6–12 months before dialysis would be needed; US waiting time counts from eGFR ≤ 20. **Plan access** when GFR < 15–20 or 2-year KFRE > 40 %. **Protect arm veins:** no IVs or blood draws in the planned arm, avoid PICC lines. **Medicare:** up to 6 kidney-disease education sessions. **Diet:** potassium about 3,000 mg and phosphorus 1,000 mg review ceilings; additives first. **Diabetes:** insulin needs often fall, A1c becomes unreliable, use CGM metrics. | K24 (PP 5.4.3, 5.5.1), K20TX, OPTN, Q19VA, MED-KDE, AK22, DG1 |
| `stages/g5-without-dialysis` | P, C | **Dialysis is started for symptoms or problems, not a number.** Usually GFR 5–10. **Uraemia symptoms to report:** poor appetite, nausea, itch, trouble thinking, breathlessness, swelling, chest pain (pericarditis is urgent). **Comprehensive conservative care** is a real choice: symptom control, advance care planning, diet for comfort. **Type 1:** basal insulin is *always* needed. Glucose targets may relax for comfort and safety. Potassium about 2,500 mg and phosphorus 900 mg starting points. | K24 (PP 5.4.1–5.4.2, Table 41, 5.5.2–5.5.3), K15SC, NIDDK-conservative, A26-6 |
| `stages/hemodialysis-in-centre` | P, C | **Schedule:** usually 3 sessions per week of about 4 h. **The long weekend gap** is the riskiest time: deaths 22.1 vs 18.0 per 100 patient-years on the day after it. **Fluid:** about 1,000 mL plus your urine output per day; weight gain between sessions above 3.5 % of body weight is linked to death. **Diet:** potassium 2,000–3,000 mg, protein *up* to 1.0–1.2 g/kg, phosphate binders with meals, sodium < 2,000 mg. **Access care:** feel the thrill daily, no BP cuff or tight sleeves on the access arm. **Adequacy:** spKt/V target 1.4, minimum 1.2 per session (3×/week). **Diabetes on dialysis days:** lows during and after sessions; check before and after; carry glucose; the team adjusts insulin on dialysis days. **Never skip or shorten sessions.** | NIDDK-HD, NIDDK-HD-eat, Q15HD, Q19VA, JBDS, DG19, DG28, DG53 |
| `stages/home-hemodialysis` | P, C | **Options:** short daily (5–6/week) or nocturnal. Training takes weeks. Often more liberal diet and fluid; ask your unit. **Needs:** space, supplies, water and power; often a care partner. **Plan for power cuts and supply delays.** Medicare can start in the first month if training begins within the first 3 months. Same insulin and hypo advice as in-centre, adapted to your schedule. | NKF-HHD, NIDDK-HD, Q15HD, MED-ESRD |
| `stages/peritoneal-dialysis` | P, C | **Types:** CAPD (manual exchanges through the day) or APD (night cycler). **Catheter exit-site care** daily. **Peritonitis:** cloudy fluid, belly pain or fever means call the PD unit **the same day** and keep the bag. **Diet:** potassium often 3,000–4,000 mg (some people run low), protein 1.0–1.2 g/kg (protein is lost into the fluid), fluid about 2 L individualised, constipation hurts drainage. **Diabetes:** dialysate glucose adds roughly 400+ kcal and raises glucose, so insulin often changes. **Icodextrin** gives false highs on some meters, so use a glucose-specific meter. | I20PD, I22P, NIDDK-PD, DG25, MHRA, AK22 |
| `stages/before-transplant` | P, C | **Living-donor pre-emptive transplant** is the preferred option where possible. **For type 1:** ask for referral to a centre doing **simultaneous pancreas-kidney** transplant. The work-up takes weeks to months. US waiting time counts from eGFR ≤ 20 or the start of dialysis. **Stay transplant-ready:** dental checks, vaccines, cancer screening, activity, your phone always on. Costs and Medicare (Part B-ID after 36 months). | K20TX, OPTN, NIDDK-Tx, NKF-Tx, MED-ESRD |
| `stages/after-transplant` | P, C | **Immunosuppressants every day, on time, lifelong.** Missed doses risk rejection. Interactions: grapefruit, pomelo, St John's wort; tell every prescriber. **Rejection or infection signs:** fever, less urine, swelling, pain over the kidney, rising creatinine. **Food safety** for a weakened immune system. Potassium can rise on tacrolimus; magnesium can fall. **Glucose:** steroids and tacrolimus raise glucose, so insulin needs change. After a successful SPK, insulin may stop; ask. Sun protection. **Pregnancy:** wait at least 1 year; mycophenolate needs contraception (REMS). Medicare ends 36 months after the transplant; Part B-ID is $121.60/month in 2026. | K09TX, NIDDK-Tx, NKF-Tx, REMS, MED-ESRD, FOODSAFE |

### 5.4 Lab results explained

Each lab page covers:

* what the test measures;
* a typical range in both unit systems, plus "your lab's range wins";
* what high or low means;
* what you can do;
* when it is urgent;
* how often it is checked;
* what can fool it;
* where age or sex matters.

| Page | Audience | Must teach | Sources |
|---|---|---|---|
| `labs/index` | P, C | How to read a lab report (flags, reference ranges, units). **Trends beat single values:** eGFR > 20 % change and UACR doubling are meaningful. A lab-tracker printable. **Age and sex:** they enter the eGFR equation and the anaemia thresholds, not the diet limits (link to `app/targets-and-warnings`). | K24 (PP 2.1.3–2.1.5), K26A, note 05 F16 |
| `labs/egfr-and-creatinine` | P | eGFR is estimated from creatinine with age and sex (CKD-EPI 2021, race-free). Cystatin C is better when muscle mass is unusual (very muscular, amputation, frailty). Creatinine mg/dL × 88.4 = µmol/L. **What raises creatinine without kidney damage:** a big meat meal, creatine supplements, some drugs. An expected small dip when starting an ACEi, ARB, MRA or SGLT2i; > 30 % needs review. | K24 (Rec 1.2.2.1, PP 1.2.4.2, PP 2.1.4), NKF-eGFR, NIDDK-tests |
| `labs/uacr` | P | The categories (above). A first-morning sample is preferred. Exercise, fever, infection, menstruation and high glucose raise it, so repeat to confirm. A doubling is meaningful. Why lowering UACR matters (finerenone's T1D approval is based on UACR). | K24 (PP 1.3.1.1–1.3.1.3, 2.1.5), KER, NIDDK-tests |
| `labs/blood-potassium` | P, C | Typical 3.5–5.0 mmol/L (= mEq/L). **KDIGO action table:** 6.0–6.4 is "moderate" (assess in hospital if unwell, otherwise repeat within 24 h); ≥ 6.5 is "severe" (immediate). **Often no symptoms**; sometimes weakness or palpitations. **Causes besides food:** ACEi, ARB, finerenone (do not start if K > 5.0), constipation, acidosis, high glucose or missed insulin, trimethoprim, NSAIDs, a haemolysed sample. **What helps:** fix the cause, limit bioavailable potassium (processed foods), binders the team prescribes; stopping a protective medicine is the last resort. | K24 (Table 28, Fig. 32, PP 3.11.1.1, 3.11.5.1–2), KER, DG2, DG36 |
| `labs/phosphate-calcium-pth` | P, C | Phosphate 2.5–4.5 mg/dL (0.81–1.45 mmol/L); calcium about 8.5–10.2 mg/dL (2.1–2.55 mmol/L), lab-specific; PTH on dialysis is kept at about 2–9× the assay's upper limit. Why bone and blood vessels care. Binders work only *with* meals. Additives are the biggest lever. Monitoring starts at G3a. | K17 (Rec 3.1.1, 4.1.x, 4.2.3), DG20, DG10 |
| `labs/bicarbonate` | P | Typical 22–29 mmol/L. KDIGO: consider treatment if < 18. KDOQI: aim 24–26 (opinion). Treatment with tablets and/or more fruit and vegetables, if potassium allows. **A low bicarbonate is not DKA by itself, but leaves less buffer when ill.** | K24 (PP 3.10.1–3.10.2), Q20, HC24 |
| `labs/albumin` | P | Serum albumin typically 3.5–5.0 g/dL (35–50 g/L). It is low with inflammation, urine losses or poor intake, so it is not a nutrition test on its own. Not the same thing as urine albumin. | Q20, NIDDK-tests, K24 |
| `labs/haemoglobin-and-iron` | P | **Anaemia:** Hb < 13 g/dL in men and < 12 g/dL in women. **Iron deficiency:** TSAT < 20 % with ferritin < 100 ng/mL (< 200 on HD). Iron first, then ESA if Hb ≤ 9–10. ESAs are not used to keep Hb ≥ 11.5. Symptoms are tiredness and breathlessness. **ESA, iron or a transfusion lowers A1c**, so A1c misleads. | K26A, K22 (PP 2.1.2), DG55 |
| `labs/a1c` | P | KDIGO individualised goal < 6.5 % to < 8.0 %. Unreliable at G4–G5 and on dialysis: anaemia, ESA, iron and transfusion push it down; uraemia pushes it up. Alternatives: CGM/GMI, fructosamine, glycated albumin. **Conversion:** mmol/mol = (% − 2.15) × 10.929. | K22 (Rec 2.2.1, PP 2.1.2, 2.2.2), A26-6, NGSP, DG55 |
| `labs/cgm-metrics` | P | **Time in range** 70–180 mg/dL > 70 %; < 70 mg/dL under 4 %; < 54 under 1 %; > 180 under 25 %; > 250 under 5 %. Older or high-risk: TIR > 50 %, < 70 under 1 %. CV ≤ 36 %. Use 14 days with ≥ 70 % wear. Reading the AGP report. **Dialysis:** CGM accuracy is less studied, so confirm lows with a fingerstick on a glucose-specific meter; check your device's interference list. | TIR19, A26-6, A26-7, MHRA |
| `labs/dialysis-adequacy` | P (HD, PD) | **HD:** spKt/V target 1.4, minimum 1.2 per session (3×/week); stdKt/V 2.3 target for other schedules. **PD:** goal-directed. Clearance plus how you feel, fluid and nutrition. What lowers adequacy: missed or shortened sessions, access problems. | Q15HD, I20PD, NIDDK-HD |

### 5.5 Eating well (from the diet guide, split and extended)

| Page | Audience | Must teach | Sources |
|---|---|---|---|
| `eat/index` | P, C | **"Portions, not bans"; fresh over packaged.** Which numbers are judged per day (K, Na, fluid, carbohydrate) and which per week (P, protein). The generated targets-by-stage table, labelled "starting points; your team sets yours". **Does age or sex change my numbers?** (F11). Why on dialysis protein goes *up*. | DG1–DG4, K24 (PP 3.3.1.x), Q20, note 05 |
| `eat/potassium` | P, C | Why limit, and only if blood K runs high. **Per-serving cues:** ≤ 150 / 151–250 / ≥ 251 mg (AKF); NKF high ≥ 200. A large serving of a low-K food is high. Additive KCl is about 90 % absorbed. Top swaps with mg. The app's thresholds. | DG2, DG5, DG26, DG46, DG52 |
| `eat/potassium-leaching` | P, C | **Step-by-step** NKF soak method. **Evidence:** boiling small cubes removes about 50 %, shredded about 75 %; soaking alone does almost nothing; baking or microwaving removes none. Leached ½ cup potato is still about 130 mg. | DG5, DG6, DG32, DG49 |
| `eat/phosphorus` | P, C | Natural phosphorus (plants ~20–50 % absorbed, meat ~40–60 %) vs additives (~90–100 %). Binders. The weekly average. P-to-protein ratio < 10–12 mg/g. | DG10–DG15, DG20 |
| `eat/phosphate-additives` | P, C | The "PHOS" ingredient list. Usual carriers (colas, processed cheese, "enhanced" meat, mixes, plant milks). Phosphorus is not required on the US label. | DG4, DG18, DG20, DG38 |
| `eat/sodium` | P, C | < 2,000 mg/day (KDIGO). Over 70 % comes from packaged and restaurant food. Label words (low ≤ 140 mg). **Salt substitutes are potassium chloride:** never use them without your team. | K24 (Rec 3.3.2.1), DG34, DG35, DG37 |
| `eat/protein` | P, C | **Targets:** 0.6–0.8 g/kg (G3–G5 with diabetes, KDOQI) or 0.8 (KDIGO); 1.0–1.2 on dialysis; avoid > 1.3. Per kg of ideal weight (note 05). 3 oz cooked = a deck of cards ≈ 21–25 g protein. Plant protein counts. | Q20 (3.1.x), K24 (PP 3.3.1.1), DG1, DG3 |
| `eat/eating-enough` | P, C | 25–35 kcal/kg. Weight loss and frailty warning signs. Add calories with fats and insulin-covered starch, not more meat. PD dialysate calories. Ask for a dietitian if intake falls. | Q20 (3.0.1), K24 (PP 5.2.3.2–5.2.3.3), DG25 |
| `eat/fluid` | P, C (HD, PD) | **What counts:** drinks, soup, ice, jelly, ice cream, fruit juice. HD 1,000 mL plus urine; PD about 2 L. Thirst tricks (salt is the driver). Weigh daily. **Lows on a fluid limit:** glucose tablets or gel add no fluid. | DG19, DG23, DG24, DG28 |
| `eat/carb-counting` | P | Carb counting is unchanged (15 g = 1 choice; 3–6 per meal per NKF, individualised). **Renal swaps raise glycaemic load**, so the ratio may need re-tuning with your team. Fibre from low-K produce. No dosing advice. | DG7, DG8, DG3, DG16, A26-5 |
| `eat/label-reading` | P, C | The 5-step label checklist (ingredients first, then K, P, Na in mg, then carbs per serving eaten). % DV misleads for K and P. | DG4, DG20, DG34, DG38, DG46 |
| `eat/portions` | P, C | Hand and household measures. Cup vs bowl. Restaurant portions are 2–3× renal portions. The app's serving picker. | DG5, DG48, DG51 |
| `eat/dialysis-days` | P (HD) | Eating before and after sessions (unit policy). Hypos during dialysis. The interdialytic allowance (per-day target × days). The weekend gap. Packing a dialysis-day bag. | DG53, DG28, JBDS, NIDDK-HD-eat |
| `eat/eating-out` | P, C | Plan the day around the meal. **The scripts to say**, sauces on the side. **US chains with ≥ 20 locations must give written nutrition information on request**, including sodium, carbohydrate and protein, but not K or P. Carbs before bolus. Alcohol with a plan. | DG48, DG14, DG35, FDAmenu, A26-5 |
| `eat/food-lists` | P, C | Eat, limit and avoid lists with mg per serving (from DG §3); a dialysis note; star fruit never. | DG17, DG22, DG39, DG51 |
| `eat/grocery-lists` (generated) | P, C | Per stage, printable task-list checklists: the 7-day menu's ingredients plus staples plus a "check the label for" box. | FDC, DG22, DG46 |
| `eat/menus/index` + 6 generated pages | P, C | **7-day sample menus**, each meal showing carb, protein, K, P, Na and fluid. Daily totals against reference targets, with a "scale for your weight" note and swaps. Built only from builtin foods (`fdc_id`), so they can be logged in the app. Per-stage rules are below. | FDC, Q20, K24 (PP 3.3.1.x), A26-5, DG8, app `suggest_targets()` |
| `eat/recipes/index` + about 12 recipes | P, C | Original recipes (3 breakfasts, 3 lunches, 4 dinners, 2 snacks or desserts). Per-serving nutrients computed from USDA ingredients. Carbs per serving for bolusing. Tags (HD-friendly, low-K, low-P, freezer). No copied recipes (F10). | FDC, AKFkitchen (inspiration only), DG5 (leaching) |

**Generated menu constraints.** The reference person has 70 kg ideal body weight. Targets come from
`suggest_targets(70, stage, dialysis, "type1", 170)`. A day must not exceed any limit and must meet
the protein minimum. Carbs are the same ±10 g at each meal across the week.

| Menu page | Protein g/day | K mg ≤ | P mg ≤ | Na mg ≤ | Fluid mL ≤ | Extra rules |
|---|---|---|---|---|---|---|
| `g1-g2` | 56–70 | (no limit; plant-forward) | – | 2,000 | – | fibre ≥ 14 g/1,000 kcal |
| `g3` (3a–3b) | 42–56 | 3,500 | 1,000 | 2,000 | – | no phosphate-additive foods |
| `g4-g5` | 42–56 | 2,500 | 900 | 2,000 | – | as `g3` |
| `hemodialysis` | 70–84 | 2,500 | 1,000 | 2,000 | 1,500 incl. food fluids | dialysis-day and non-dialysis-day variants |
| `peritoneal` | 70–84 | 3,500 | 1,000 | 2,000 | 2,000 | note the ~400 kcal from dialysate |
| `transplant` | 56–70 | (no limit unless labs) | – | 2,000 | – | no grapefruit or pomelo; food-safety swaps |

### 5.6 Type 1 diabetes and CKD

| Page | Audience | Must teach | Sources |
|---|---|---|---|
| `t1d/index` (How CKD changes diabetes) | P, C, Cl | The kidney clears insulin and makes glucose, so as eGFR falls, **doses often need lowering and lows rise**; restrictive diets add to it. Blunted hypo warning signs, so ask for yearly awareness screening. "Burnt-out diabetes" does not apply to T1D: **insulin is always needed**. A "for your clinician" collapsible (DG §4). | AK22, DG54, DG55, A26-6 (Rec 6.11), K22 |
| `t1d/treating-a-low` | P, C | **Levels:** < 70, < 54, needs help. **15 g, recheck in 15 min** (5–10 g on AID). **Potassium never delays treatment.** The ranked 15 g table (tablets best). Glucagon for everyone on insulin, including nasal or ready-to-use forms; train caregivers. Sugar-free sweets do not work. Fluid-limit tip: tablets or gel. | A26-6 (Rec 6.15, 6.16), DG4, DG24, DG27, NIDDK-hypo |
| `t1d/sick-days` | P, C | **Never stop basal insulin**; illness often needs *more*. Check glucose every 2–4 h. Check ketones when unwell or glucose > 240–250 mg/dL (13.3–13.9 mmol/L), every 4–6 h (ADA). **Blood ketones:** < 0.6 normal; 0.6–1.5 recheck in 2 h and follow your plan; 1.6–2.9 call the team now; ≥ 3.0 go to emergency. **Little urine (dialysis):** urine strips do not work, so use a blood ketone meter. **Medicines:** KDIGO's sick-day list covers ACEi or ARB, diuretics, NSAIDs (avoid anyway) and SGLT2i if prescribed off-label (also metformin and sulfonylureas, rarely used in T1D). Ask your team which of *yours* to pause, **get it in writing with the restart rule**. KDIGO warns evidence is limited and forgetting to restart is the commonest harm. **Fluids** when on a fluid limit: ask for a sick-day allowance. A sick-day kit checklist: in-date ketone strips, glucose tablets, glucagon, written plan, numbers. | K24 (PP 4.3.2–4.3.3, Fig. 47), HC24, NHSK, ADAK, A26-6 |
| `t1d/insulin-and-dialysis` | P, C | **HD:** dialysate glucose content matters; lows during and after sessions; the team often adjusts basal on dialysis days (JBDS); check before, during if symptomatic, and after. **PD:** absorbed glucose raises needs; icodextrin meter warning. **After transplant:** steroids and tacrolimus raise glucose. CGM caveats. No numbers for doses. | JBDS, MHRA, AK22, I20PD, K09TX, A26-7 |
| `t1d/kidney-protecting-medicines` | P, C | **ACEi or ARB:** first line with albuminuria (1B). Labs 2–4 weeks after a start or change. Keep taking it unless creatinine rises > 30 %. Keep it below eGFR 30. Never combine an ACEi with an ARB. **Finerenone:** approved for T1D CKD in Sept 2026; K checks; not started if K > 5.0; avoid grapefruit. **SGLT2 inhibitors:** not approved in T1D (DKA risk), so ask before any off-label use. **GLP-1 RAs:** not approved in T1D. Pregnancy warning (link). | K24 (Rec 3.6.3–3.6.4, PP 3.6.2–3.6.7, research recs), KER, F1, K22, A26-11 |

### 5.7 Medicines, supplements and tests

| Page | Audience | Must teach | Sources |
|---|---|---|---|
| `medicines/avoid` | P, C | **NSAIDs** (ibuprofen, naproxen, high-dose aspirin) harm the kidneys; acetaminophen (paracetamol) at the labelled dose is usually preferred, so ask. **Sodium phosphate laxatives and enemas (Fleet-type)** can cause acute kidney injury and death. **Magnesium laxatives and antacids**, aluminium antacids, effervescent high-sodium tablets, potassium-chloride salt substitutes. Decongestants raise BP. Some antibiotics raise potassium (trimethoprim). Always say "I have CKD stage X" to prescribers and pharmacists. | NKFpain, FDANaP, DG44, DG45, K24 (PP 4.1.1–4.1.3), DG35 |
| `medicines/supplements` | P, C | No supplement without nephrologist sign-off; renal vitamins only. The NKF/AKF herb list (aristolochia, licorice, St John's wort, …). Creatine. "Kidney cleanse" products. Hidden K, P and Mg in powders. | NKFherb, AKFherb, K24 (PP 4.1.3), DG41, DG42 |
| `medicines/scans-and-contrast` | P | **CT contrast:** the risk is lower than once thought. Not on dialysis with eGFR < 30: IV fluids beforehand (ACR–NKF). Do not refuse a needed scan. **Gadolinium MRI at G4–G5:** group II agents preferred. Heart catheter contrast is risk-assessed separately. Bowel preps: avoid sodium-phosphate preps. | CON20, GAD21, K24 (PP 4.4.1.1–4.4.2.1), FDANaP |
| `medicines/your-medicine-list` | P, C | One up-to-date list (template), one pharmacy if possible, doses checked against eGFR, a review at every transition. Your written sick-day plan and restart dates. A printable card. | K24 (PP 4.2.1, 4.3.1–4.3.2, 4.3.1.1), NIDDK-managing |

### 5.8 Preparing for treatment

| Page | Audience | Must teach | Sources |
|---|---|---|---|
| `prepare/choosing-a-treatment` | P, C | A comparison table: in-centre HD, home HD, PD (CAPD or APD), pre-emptive transplant (living or deceased), SPK for T1D, and comprehensive conservative care. Rows: time per week, diet and fluid freedom, travel, work, equipment, space, care partner, infection risks, how it feels. Timeline by KFRE. Medicare education sessions. | K24 (PP 2.2.3, 5.4.3, 5.5.1–5.5.2), NIDDK-choosing, K20TX, I20PD, MED-KDE |
| `prepare/dialysis-access` | P, C | **Fistula** (preferred for most; healing "may take several months"), **graft**, **catheter** (highest infection risk), **PD catheter**. Vein preservation from G4. Daily checks (thrill, redness). Bleeding first aid (10 minutes of firm pressure, then 911). | Q19VA, NIDDK-HD, NKF-HDaccess, I20PD |
| `prepare/transplant-referral` | P, C | Referral timing (eGFR < 30; ≥ 6–12 months before dialysis). Waiting time from eGFR ≤ 20. Living donation. SPK referral for T1D. Evaluation tests. Being listed at more than one centre. Costs. | K20TX, OPTN, NIDDK-Tx, NKF-Tx, MED-ESRD |
| `prepare/advance-care-planning` | P, C | What advance care planning covers; health-care proxy; revisiting it at each stage; supportive care alongside any treatment; conservative care is not "giving up". | K24 (PP 5.5.3), K15SC, NIDDK-conservative |

### 5.9 Living well

| Page | Audience | Must teach | Sources |
|---|---|---|---|
| `living/exercise` | P | **≥ 150 min/week** of moderate activity, or as tolerated; avoid sitting for long periods; falls advice. **T1D:** carbs and bolus planning; check ketones if glucose > 270 mg/dL (15 mmol/L); no exercise with blood ketones ≥ 1.5. Exercise during dialysis. Access-arm and PD-catheter cautions; ask your unit about swimming. | K24 (Rec 3.2.2.1, PP 3.2.2.2–3.2.2.3), EX17, A26-5, NKF-exercise |
| `living/sleep` | P | **Restless legs:** check iron; iron and alpha-2-delta drugs are first line; dopamine agonists are no longer recommended long term (AASM 2024). Sleep apnoea, itch, nocturia. **Night-time lows:** CGM alarms. | AASM24, K24 (PP 5.2.2.1, 5.2.3.1), K26A, A26-6, TIR19 |
| `living/mental-health` | P, C | Depression, anxiety and diabetes distress are common and treatable. Screening. Dialysis social workers and peer support. **US crisis line 988**; outside the US, local services. | A26-5, K24 (PP 5.2.3.1), 988 |
| `living/work` | P | US disability-law accommodations: time for dialysis, breaks for glucose checks, storing insulin, working from home. **FMLA:** up to 12 weeks of job-protected leave. SSDI if you cannot work. Home or nocturnal dialysis to keep working. Telling your employer is optional. | EEOC, FMLA, SSA, NIDDK-choosing |
| `living/travel` | P, C | Book dialysis away from home early, through your unit. PD supplies can be shipped. **TSA:** diabetes supplies are allowed, so tell the officer, ask for a pat-down if needed, and follow your pump and CGM maker's scanner advice. Insulin storage. Time-zone plans with your team. Original Medicare generally does not pay for care outside the US. Immunosuppressant timing. Food and water safety after a transplant. | TSA, ADA-travel, MED-ESRD, NIDDK-HD, NIDDK-PD |
| `living/sex-fertility-pregnancy` | P | ED and low libido are common and can be treated, so ask. Fertility falls with stage and returns after a transplant, so use contraception. **Pregnancy risk rises with stage:** plan with a nephrologist and maternal-fetal medicine. **ACEi and ARB harm the fetus:** plan the switch *before* trying. Mycophenolate REMS. Wait at least 1 year after a transplant. T1D preconception A1c < 6.5 % if it can be reached safely. Dialysis during pregnancy needs more sessions. *Referral page, not a how-to.* | UKKA19, K24 (PP 4.1.4), REMS, K09TX, A26-15, NKF-pregnancy |
| `living/costs-and-benefits` | P, C | **US:** Medicare ESRD eligibility (work credits), start dates, end dates, the 30-month coordination period, Medicare Advantage, Part B-ID ($121.60/month in 2026), the $35/month insulin cap on Medicare, education sessions, Medicaid, SSDI, AKF HIPP grants. `figures_as_of` must be updated every November. **Outside the US:** dialysis and transplant are usually covered by national systems; check the national kidney charity (Kidney Care UK grants as an example) and travel insurance. | MED-ESRD, CMS26, MED-KDE, MED-INS, SSA, HIPP, KCUK |
| `living/appointments` | P, C | **Bring:** the app's CSV or period summary, home BP and weights, CGM report, medicine list. **Question lists per stage** (generated from each stage page's "Ask your team"). Teach-back. Shared decision-making. | K24 (PP 5.3.1, 5.5.1), AHRQ-Q, NIDDK-managing |
| `living/caregivers` | C | Spotting and treating lows, and giving glucagon. The sick-day plan. Dialysis schedules and access checks. Medicine lists. **Caregiver burnout**, respite and FMLA for caregivers. Join education sessions (KDIGO). | K24 (PP 5.3.2), A26-6, NIDDK-hypo, FMLA, NIDDK-HD |

### 5.10 Reference

| Page | Audience | Must teach | Sources |
|---|---|---|---|
| `reference/glossary` | all | Plain definitions using KDIGO terms. It also feeds `includes/abbreviations.md`, so terms get tooltips on every page. | K20NOM, NIDDK-CKD |
| `reference/units` | P, Cl | **Conversions:** creatinine mg/dL × 88.4 = µmol/L; glucose mg/dL ÷ 18 = mmol/L; phosphate mg/dL × 0.323 = mmol/L; calcium mg/dL × 0.25 = mmol/L; albumin and Hb g/dL × 10 = g/L; UACR 30 mg/g ≈ 3 mg/mmol; K and bicarbonate mEq/L = mmol/L; ferritin ng/mL = µg/L; A1c mmol/mol = (% − 2.15) × 10.929. | K24 (dual-unit tables), NGSP |
| `reference/sources` | Cl | The rendered `sources.yml`: citation, URL, licence, date checked. | (all) |
| `reference/about` | all | Disclaimer, editorial policy (§4.9), the review log, how to suggest a correction, licence of the text and of third-party material. | PEMAT, CCI, NIDDK-copyright |
| `reference/licences` | all | Material MIT, lunr MIT and other bundled-asset licences; project licences. | F2 |

### 5.11 Using the app (audience U; sources are the notes and ARCHITECTURE.md)

| Page | Must teach | Sources |
|---|---|---|
| `app/index` | What the app does and does not do (no dosing; not a medical device); the privacy summary. | README, ARCHITECTURE.md, note 07 |
| `app/install` | Add to Home Screen on iOS, Android and desktop; why HTTPS is needed; offline behaviour. | note 02 |
| `app/first-setup` | Accounts and invites, the profile, "Suggest targets", **which factors change targets (age, sex, height, weight, stage, dialysis, labs) and which do not**. | notes 05, 07 |
| `app/targets-and-warnings` | Per-serving thresholds, daily status, day vs week judging, interdialytic totals, green/yellow/red ratings. | ARCHITECTURE.md, DG §7 |
| `app/logging` | Search, servings and grams, quick add from a label, custom foods. | ARCHITECTURE.md |
| `app/barcode-and-photo` | Scanning, Open Food Facts and USDA Branded data, the additive flags, photo of a label, limits. | note 03 |
| `app/planning-and-menus` | Planned entries, saved meals, copy day, shopping list, using the handbook menus. | ARCHITECTURE.md v0.2, §5.5 |
| `app/guidance` | "What fits now", swaps, plan my day, insights; how the rules work. | note 06 |
| `app/ai` | Optional AI (Hermes, Ollama, OpenAI): what is sent, consent, labels, limits. | note 04 |
| `app/settings-and-keys` | Shared vs private keys, quotas, locked server keys. | note 07 §4.17 |
| `app/reports-for-your-team` | CSV export, period summaries, what a dietitian sees. | ARCHITECTURE.md |
| `app/privacy` | What is stored, who can see it, deleting and exporting your data. | notes 01, 07 |

### 5.12 Self-hosting (audience H; mostly moved from `docs/deployment.md`)

| Page | Must teach | Sources |
|---|---|---|
| `self-hosting/index` | Choosing a path; the requirements. | docs/deployment.md |
| `self-hosting/podman-rootless` | `podman run`, compose, Quadlet, userns, volumes `:U`. | note 01 §5.2, docs/deployment.md |
| `self-hosting/docker-rootless` | Rootless Docker caveats (source IP, proxies). | note 01 §3.2 |
| `self-hosting/kubernetes` | Talos, kustomize, PSA restricted, NetworkPolicy. | note 01 §5.3 |
| `self-hosting/https` | The four HTTPS tiers for phones. | note 02 R9 |
| `self-hosting/configuration` | Every environment key, including `HANDBOOK_DIR` and `HANDBOOK_PUBLIC_URL`. | notes 01, 04, 07, this note |
| `self-hosting/users-and-keys` | First admin, invites, shared keys, secret files. | note 07 |
| `self-hosting/backups` | Online backup, restore, verify. | docs/deployment.md, note 07 §4.15 |
| `self-hosting/upgrades` | Tags vs digests, auto-update, migrations. | docs/deployment.md, note 01 |
| `self-hosting/security` | The hardening summary, verifying images, **serving `/learn` from its own origin** (§4.6). | note 01, this note |
| `self-hosting/network-allowlist` | Outbound domains per feature. | docs/network-allowlist.md, notes 03, 04 |
| `self-hosting/troubleshooting` | Common errors. | docs/deployment.md |
| `self-hosting/building-the-handbook` | Contributor guide: venv, `build_handbook.py`, `mkdocs serve`, front matter, sources, the review flow. | this note |

### 5.13 Bibliography (source ids for `handbook/sources.yml`)

`DGn` = `docs/diet-guide.md` §8 source *n* (copy its citation and URL). Others:

| id | Citation and URL |
|---|---|
| K24 | KDIGO 2024 CKD guideline. Kidney Int 2024;105(4S):S117–S314. https://kdigo.org/wp-content/uploads/2024/03/KDIGO-2024-CKD-Guideline.pdf (CC BY-NC-ND) |
| K22 | KDIGO 2022 Diabetes Management in CKD. Kidney Int 2022;102(5S):S1–S127. https://kdigo.org/wp-content/uploads/2023/12/KDIGO-2022-Diabetes-Guideline.pdf; status of the 2026 update: https://kdigo.org/guidelines/diabetes-ckd/ |
| K26A | KDIGO 2026 Anemia in CKD. Babitt JL et al., executive summary, Kidney Int 2026;109:44–56. https://kdigo.org/wp-content/uploads/2026/01/KDIGO-2026-Anemia-in-CKD-Guideline-Executive-Summary.pdf; full: https://kdigo.org/wp-content/uploads/2026/04/KDIGO-2026-Anemia-in-CKD-Guideline.pdf |
| K17 | KDIGO 2017 CKD-MBD update. Kidney Int Suppl 2017;7:1–59. https://pmc.ncbi.nlm.nih.gov/articles/PMC6340919 |
| K20TX | KDIGO 2020 transplant candidates. Chadban SJ et al., Transplantation 2020;104(4S1):S11–S103; summary 2020;104(4):708–714. https://pmc.ncbi.nlm.nih.gov/articles/PMC7147399/ |
| K09TX | KDIGO 2009 care of kidney transplant recipients. Am J Transplant 2009;9(Suppl 3):S1–S155. https://kdigo.org/guidelines/transplant-recipient/ |
| K20NOM | Levey AS et al. Nomenclature for kidney function and disease. Kidney Int 2020;97:1117–1129. https://doi.org/10.1016/j.kint.2020.02.010; https://kdigo.org/conferences/nomenclature/ |
| K15SC | Davison SN et al. KDIGO Controversies Conference on Supportive Care in CKD. Kidney Int 2015;88:447–459. https://doi.org/10.1038/ki.2015.110 |
| Q20 | KDOQI Nutrition in CKD 2020 (= DG1). https://doi.org/10.1053/j.ajkd.2020.05.006 |
| Q19VA | Lok CE et al. KDOQI Vascular Access 2019 Update. Am J Kidney Dis 2020;75(4 Suppl 2):S1–S164. https://doi.org/10.1053/j.ajkd.2019.12.001 |
| Q15HD | KDOQI Hemodialysis Adequacy 2015 Update. Am J Kidney Dis 2015;66:884–930. https://doi.org/10.1053/j.ajkd.2015.07.015 |
| I20PD | Brown EA et al. ISPD: prescribing high-quality goal-directed PD. Perit Dial Int 2020;40:244–253. https://doi.org/10.1177/0896860819895364 |
| I22P | Li PKT et al. ISPD peritonitis guideline 2022 update. Perit Dial Int 2022;42:110–153. https://doi.org/10.1177/08968608221080586 |
| A26-5 / A26-6 / A26-11 | ADA Standards of Care 2026 §5, §6, §11 (= DG8, DG9). https://pmc.ncbi.nlm.nih.gov/articles/PMC12690188, …PMC12690178, …PMC12690176 |
| A26-7 / A26-15 | ADA Standards of Care 2026 §7 (Diabetes Technology), §15 (Pregnancy). Diabetes Care 2026;49(Suppl 1). https://diabetesjournals.org/care/issue/49/Supplement_1 |
| AK22 | de Boer IH et al. ADA–KDIGO consensus. Diabetes Care 2022;45:3075–3090 (= DG54). https://pmc.ncbi.nlm.nih.gov/articles/PMC9870667 |
| HC24 | Umpierrez GE et al. Hyperglycemic crises in adults with diabetes: a consensus report. Diabetes Care 2024;47(8):1257–1275. https://doi.org/10.2337/dci24-0032 |
| TIR19 | Battelino T et al. International consensus on time in range. Diabetes Care 2019;42:1593–1603. https://doi.org/10.2337/dci19-0028 |
| EX17 | Riddell MC et al. Exercise management in type 1 diabetes: a consensus statement. Lancet Diabetes Endocrinol 2017;5:377–390. https://doi.org/10.1016/S2213-8587(17)30014-1 |
| JBDS | Frankel AH et al. Management of adults with diabetes on the haemodialysis unit (JBDS and Renal Association). Br J Diabetes 2016;16:69–77. https://bjd-abcd.com/index.php/bjd/article/view/134; current JBDS-IP dialysis guidance listing: https://www.rightdecisions.scot.nhs.uk/nhs-borders-clinical-guidelines/diabetes-and-endocrinology/management-of-adults-with-diabetes-on-dialysis-jbds-ip-national-guidance-external-link |
| NHSK | NHS London Procurement Partnership. Ketone testing in type 1 diabetes, patient advice (2018). https://www.england.nhs.uk/london/wp-content/uploads/sites/8/2019/07/NHSLPP-ketone-testing-type-1-px-advice-for-primary-care-Oct18-v1.0.pdf |
| ADAK | American Diabetes Association. DKA (ketoacidosis) and ketones. https://diabetes.org/dka-ketoacidosis-ketones |
| KER | Kerendia (finerenone) US prescribing information, revised 9/2026. https://labeling.bayerhealthcare.com/html/products/pi/Kerendia_PI.pdf |
| F1 | Heerspink HJL et al. Finerenone in type 1 diabetes and CKD (FINE-ONE). N Engl J Med 2026;394(10):947–957 (DOI to be added after checking) |
| CON20 | Davenport MS et al. ACR–NKF consensus: IV iodinated contrast in kidney disease. Radiology 2020;294:660–668. https://doi.org/10.1148/radiol.2019192094 |
| GAD21 | Weinreb JC et al. ACR–NKF consensus: gadolinium-based contrast in kidney disease. Radiology 2021;298:28–35. https://doi.org/10.1148/radiol.2020202903 |
| FDANaP | FDA Drug Safety Communication on OTC sodium phosphate products, 2014 (= DG43) |
| MHRA | MHRA Drug Safety Update: Extraneal (icodextrin) and false blood glucose readings. https://www.gov.uk/drug-safety-update/extraneal-and-products-that-contain-or-are-metabolised-to-maltose-xylose-or-galactose-false-blood-glucose-readings |
| NKFpain / NKFherb / AKFherb | https://www.kidney.org/kidney-topics/pain-medicines-and-kidney-disease; https://www.kidney.org/kidney-topics/herbal-supplements-and-kidney-disease (= DG41); DG42 |
| NKF-eGFR / NKF-HDaccess / NKF-HHD / NKF-Tx / NKF-exercise / NKF-pregnancy | https://www.kidney.org/kidney-topics/estimated-glomerular-filtration-rate-egfr; …/hemodialysis-access; …/home-hemodialysis; …/kidney-transplant; …/exercise-and-chronic-kidney-disease; …/pregnancy-and-kidney-disease |
| NIDDK-CKD / -tests / -managing / -HD / -HD-eat / -PD / -Tx / -conservative / -choosing / -hypo / -DKD / -copyright | https://www.niddk.nih.gov/health-information/kidney-disease/chronic-kidney-disease-ckd (and /tests-diagnosis, /managing); …/kidney-failure/hemodialysis (and /eating-nutrition); …/kidney-failure/peritoneal-dialysis; …/kidney-failure/kidney-transplant; …/kidney-failure/conservative-management; …/kidney-failure/choosing-treatment; https://www.niddk.nih.gov/health-information/diabetes/overview/preventing-problems/low-blood-glucose-hypoglycemia; …/preventing-problems/diabetic-kidney-disease; https://www.niddk.nih.gov/copyright |
| MED-ESRD / MED-KDE / MED-INS / CMS26 | https://www.medicare.gov/basics/end-stage-renal-disease; https://www.medicare.gov/coverage/kidney-disease-education; https://www.medicare.gov/coverage/insulin; https://www.cms.gov/newsroom/fact-sheets/2026-medicare-parts-b-premiums-deductibles |
| OPTN | OPTN Policies (Policy 8 Kidney, Policy 11 Pancreas). https://optn.transplant.hrsa.gov/policies-bylaws/policies/ |
| REMS | Mycophenolate REMS. https://www.mycophenolaterems.com/ |
| UKKA19 | Wiles K et al. Clinical practice guideline on pregnancy and renal disease. BMC Nephrol 2019;20:401. https://doi.org/10.1186/s12882-019-1560-2 |
| AASM24 | Winkelman JW et al. AASM guideline: treatment of RLS and PLMD. J Clin Sleep Med (published online 2024-09-26). https://doi.org/10.5664/jcsm.11390 |
| TSA / ADA-travel | https://www.tsa.gov/travel/security-screening/whatcanibring/medical; https://diabetes.org/tools-support/know-your-rights/what-can-i-bring-with-me-on-plane |
| EEOC / FMLA / SSA | https://www.eeoc.gov/laws/guidance/diabetes-workplace-and-ada; https://www.dol.gov/agencies/whd/fmla; https://www.ssa.gov/benefits/disability/ |
| HIPP / KCUK / 988 | https://www.kidneyfund.org/get-assistance/health-insurance-premium-program; https://www.kidneycareuk.org/get-support/financial-support/; https://988lifeline.org/ |
| FDAmenu / FDC / AKFkitchen / FOODSAFE | https://www.fda.gov/food/food-labeling-nutrition/menu-labeling-requirements; https://fdc.nal.usda.gov/; https://kitchen.kidneyfund.org/; https://www.foodsafety.gov/people-at-risk/people-with-weakened-immune-systems |
| NGSP / AHRQ-Q / PEMAT / CCI | https://ngsp.org/ifccngsp.asp; https://www.ahrq.gov/questions/index.html; https://www.ahrq.gov/health-literacy/patient-education/pemat.html; https://www.cdc.gov/ccindex/index.html |

URLs that returned 403 to the bot check are expected to work in a browser: OPTN, TSA, DOL, SSA,
AHRQ and foodsafety.gov. These sites block automated requests, which is why lychee accepts 403.
Five candidate NKF and AKF URLs returned 404 and are **not** used (for example NKF "hyperkalemia" and
"uremia" topic pages). Pick replacements while writing.

---

## 6. Risks

| # | Risk | Likelihood / impact | Mitigation |
|---|---|---|---|
| 1 | **Wrong or outdated medical content harms someone** | Medium / High | Clinical review roles and draft banners. ≥ 3 primary sources per page. `last_reviewed` and `next_review`. Review triggers (ADA each December, KDIGO, FDA). A no-dosing lint. Get-help-now on every page. The disclaimer. Numbers are generated from the app's own rules. |
| 2 | **Material maintenance ends (Nov 2026 at the earliest); MkDocs 1.x unmaintained** | High / Medium | Build-time only, with static output and nothing running in production. Hash-locked pins. Material already pins `mkdocs<2`. Zensical canary job. Content is plain Markdown plus a portable `mkdocs.yml`. ProperDocs 1.6.7 is a core fallback. Migrate once Zensical ≥ 0.1 passes the content tests and the CSP smoke test. |
| 3 | **The `/learn` CSP is weaker than the app's** (no Trusted Types) on the same origin | Low / Medium | Static, read-only files with no user content. Inline scripts are allowed by **hash only**, never `'unsafe-inline'`. `connect-src 'self'`. Same `frame-ancestors`, COOP and CORP. A separate origin is documented for strict operators. |
| 4 | **Theme update changes inline scripts** and the CSP breaks the handbook | Medium / Low | Hashes are computed from the served files at startup. The CI Playwright smoke test fails on any violation. |
| 5 | **Copyright problems** (copied NKF/AKF tables or recipes, adapted KDIGO figures) | Medium / Medium | Editorial rules (F10, §4.9). Reviewer checklist. Original recipes computed from USDA data. `sources.yml` records each licence. |
| 6 | **Readers take generic numbers as personal prescriptions** | High / Medium | "Starting point; your team sets yours" on every numbers box. Links to the app's personal targets, which carry the same label. Never "stop" or "dose" language. |
| 7 | **Benefit amounts and laws go stale** (Medicare, ADA law, FMLA) | High / Low | `figures_as_of` with a November review; the test warns when stale. |
| 8 | **Pages unavailable** (private repo on Free), or **unexpectedly public** (private repo on Pro) | Certain until a decision / Low | Opt-in `HANDBOOK_PAGES` variable plus the documented plan facts (F6). The handbook contains no private data. |
| 9 | **Non-US readers misapply US numbers or benefits** | Medium / Low | US/International unit tabs. "Outside the US" boxes. National charity links. |
| 10 | **Instant navigation silently off** when the port differs from `site_url` | High / Low | Expected and harmless (F4). The LAN build uses the default-port `site_url`, which suits the HTTPS setups note 02 recommends. |
| 11 | **Contributors add external images, scripts or iframes** | Medium / Low | Privacy plugin with `assets_fetch: false` plus strict, plus content lints. |
| 12 | **Image size grows** | Low / Low | About 1.4 MB of theme plus 1–2 MB of content. Source maps removed. Lunr language pruning is possible later (−0.9 MB). |
| 13 | **Translation lag** (Spanish matters for US CKD patients) | High / Low | English-only in v0.3. The page structure and slugs are language-neutral. Revisit i18n in v0.4 with Zensical or `mkdocs-static-i18n`. |

---

## 7. Implementation checklist

**Phase 0: owner decisions**

- [ ] Licence for `handbook/` text: CC BY-NC-SA 4.0 (recommended) or CC BY 4.0. Add a `handbook/LICENSE` and a README line.
- [ ] GitHub Pages: make the repo public, or use Pro (site public). Set `HANDBOOK_PAGES=true` when ready.
- [ ] Name the clinical reviewers (renal dietitian, nephrology, diabetes, one patient or caregiver).

**Phase 1: tooling (one PR, no medical content beyond stubs)**

- [ ] Create `handbook/` as in §4.2: `mkdocs.yml` (§4.3), `overrides/main.html`, `stylesheets/extra.css` (print styles, wallet card, narrow tables), `includes/abbreviations.md`, a `sources.yml` with the §5.13 ids, and `docs/` stubs for every §5 page with front matter (`review.status: draft`).
- [ ] `handbook/requirements.in` pins `mkdocs==1.6.1`, `mkdocs-material==9.7.7`, `pymdown-extensions==12.1` and `pyyaml`. Generate `requirements.lock` with hashes using note 01's `scripts/lock.sh`. Add the `pip` ecosystem entry for `handbook/` to Dependabot.
- [ ] `scripts/build_handbook.py` with `--write` and `--check` (§4.5): sources.md, the targets table, menus, grocery lists, recipe tables, Material licence copy, icon copy.
- [ ] `tests/test_handbook_content.py` covering every rule in §4.9.
- [ ] `app/handbook.py` + `create_app()` wiring (§4.6): mount before `/`, path-scoped CSP, cache headers, `HANDBOOK_DIR`, `HANDBOOK_PUBLIC_URL` in `app/config.py`.
- [ ] `tests/test_handbook_serving.py` with a 3-page fixture site (`tests/fixtures/learn/`). Assert:
  - `/learn` redirects to `/learn/`;
  - a 404 is returned for missing pages;
  - the `/learn/` CSP contains every fixture hash, has no `trusted-types` and has `img-src 'self' data:`;
  - `/` keeps note 01's CSP unchanged;
  - fingerprinted assets get `immutable`;
  - the mount is skipped when the directory is missing;
  - more than 64 hashes raises.
- [ ] `deploy/Containerfile`: add the handbook stage and copy it into `/app/learn` (§4.7). `.dockerignore`: add `handbook/site`, `handbook/.cache`.
- [ ] `ci.yml`: add the `handbook` job (with the Playwright `/learn` smoke test) and the `handbook-zensical` canary. The `image` job `needs: [test, deploy-lint, handbook]`.
- [ ] Add `.github/workflows/handbook-pages.yml` and `handbook-links.yml` (§4.8). zizmor passes; actions are SHA-pinned.
- [ ] Frontend: a **Learn** nav entry and an About & privacy link (note 07 §4.17). Same-window navigation.
- [ ] Note 06 `topics.py` uses the §4.10 URL table, and a test verifies the paths exist.

**Phase 2: migrate existing documents**

- [ ] Split `docs/diet-guide.md` per §4.11. Carry `DGn` citations into `sources.yml` with a `dg: n` field. Replace the guide with a pointer.
- [ ] Update the code comments that cite "docs/diet-guide.md section N" (`app/nutrients.py`, `scripts/curated_foods.py`, `tests/test_food_db.py`).
- [ ] Move `docs/deployment.md` and `docs/network-allowlist.md` into `self-hosting/`, leave stubs, and fix the README, Containerfile label and compose comment links.
- [ ] Author `data/menus.yml` (6 menus × 7 days) and `data/recipes.yml` (about 12). `build_handbook.py --check` passes the §5.5 constraints.

**Phase 3: write content, in this order (safety first)**

1. [ ] `get-help-now` (plus a print-tested wallet card).
2. [ ] `t1d/sick-days`, `t1d/treating-a-low`.
3. [ ] `stages/*` (10 hubs).
4. [ ] `labs/*`.
5. [ ] `medicines/*`.
6. [ ] `eat/*` (migrated pages first, then menus, grocery lists, recipes).
7. [ ] `t1d/index`, `t1d/insulin-and-dialysis`, `t1d/kidney-protecting-medicines`.
8. [ ] `prepare/*`.
9. [ ] `living/*`.
10. [ ] `ckd/*`, `reference/*`.
11. [ ] `app/*` (after the features land).
12. [ ] `self-hosting/*`.

**Phase 4: review and publish**

- [ ] Run a readability pass (textstat warnings) and a PEMAT self-score on the 10 most-used pages.
- [ ] Clinical review: set `review.status: reviewed`, `reviewed_by`, `last_reviewed` and `next_review`.
- [ ] Enable Pages. Set `HANDBOOK_PUBLIC_URL` and update the image documentation label.
- [ ] README "Patient handbook" section with the Pages link and `/learn`.
- [ ] Update notes 02, 04 and 06 to say `/learn/` instead of `/handbook/` (one-line edits).

---

## 8. How to re-verify

```bash
# Versions and release dates
for p in mkdocs-material mkdocs zensical properdocs pymdown-extensions textstat; do
  curl -s https://pypi.org/pypi/$p/json | python3 -c "import json,sys;d=json.load(sys.stdin);print('$p',d['info']['version'])"; done
# Material support status / MkDocs 2.0 stance
open https://squidfunk.github.io/mkdocs-material/blog/      # look for an end-of-maintenance post after Nov 2026
open https://zensical.org/roadmap/                           # 0.1.0 shipped? plugin replacements?
# Action SHAs
for r in actions/configure-pages actions/upload-pages-artifact actions/deploy-pages lycheeverse/lychee-action; do
  git ls-remote --tags https://github.com/$r | sort -k2 -V | tail -2; done
# Pages plan facts
open https://docs.github.com/en/pages/getting-started-with-github-pages/github-pages-limits
# CSP still sufficient: build the handbook, serve it with app/handbook.py, run the Playwright /learn smoke test
# Clinical facts with dates in this note
open https://kdigo.org/guidelines/diabetes-ckd/              # 2026 update final?
open https://www.cms.gov/newsroom                            # 2027 Part B and Part B-ID amounts (Nov)
open https://labeling.bayerhealthcare.com/html/products/pi/Kerendia_PI.pdf   # label revision date
# Sotagliflozin (Zynquista) FDA decision for T1D, expected 2027 (company filings)
```

---

## 9. Sources (tooling and verification for this note)

Tooling:

* Material for MkDocs blog index (maintenance announcement, Insiders free, Zensical):
  https://squidfunk.github.io/mkdocs-material/blog/
* "What MkDocs 2.0 means for your documentation projects" (2026-02-18):
  https://squidfunk.github.io/mkdocs-material/blog/2026/02/18/mkdocs-2.0/
* PyPI JSON for mkdocs-material, mkdocs, zensical, properdocs, pymdown-extensions, mkdocs-redirects
  and textstat (versions, dates, licences, `requires_dist`), queried 2026-10-05: https://pypi.org/pypi/<name>/json
* Installed Material 9.7.7 source, read directly:
  * `material/plugins/privacy/config.py`;
  * `material/plugins/offline/plugin.py` (`use_directory_urls=False`, unpkg iframe-worker);
  * `material/templates/__init__.py` (`NO_MKDOCS_2_WARNING`);
  * `material/templates/partials/header.html` (`extra.homepage`);
  * `partials/copyright.html` (`extra.generator`);
  * the built `bundle.*.min.js` (sitemap host rewrite `fi()`).
* Zensical docs: https://zensical.org/docs/compatibility/mkdocs/,
  https://zensical.org/roadmap/, https://zensical.org/docs/setup/offline/,
  https://zensical.org/docs/setup/search/, https://zensical.org/docs/setup/fonts/,
  https://zensical.org/docs/setup/basics/
* ProperDocs: https://github.com/properdocs/properdocs (PyPI description), https://properdocs.org
* GitHub Pages:
  * limits: https://docs.github.com/en/pages/getting-started-with-github-pages/github-pages-limits
  * plans: https://docs.github.com/en/get-started/learning-about-github/githubs-plans
  * visibility: https://docs.github.com/en/enterprise-cloud@latest/pages/getting-started-with-github-pages/changing-the-visibility-of-your-github-pages-site
* Pages actions READMEs: https://github.com/actions/deploy-pages,
  https://github.com/actions/upload-pages-artifact, https://github.com/actions/configure-pages.
  Tags and SHAs come from `git ls-remote`.
* Docusaurus search: https://docusaurus.io/docs/search. Versions from the npm registry
  (`@docusaurus/core`, `@easyops-cn/docusaurus-search-local`, `@astrojs/starlight`, `vitepress`).

Local experiments (scratchpad, 2026-10-05):

* Built sample sites with Material 9.7.7 + MkDocs 1.6.1 (Python 3.11 and 3.14.0rc2) and with Zensical 0.0.68.
* Ran Material's privacy plugin variants (`assets_fetch` true/false, `assets_exclude`, strict) and size measurements.
* Served the build with FastAPI `StaticFiles` at `/learn`.
* Ran Playwright 1.63 + Chromium 1194 under four CSP variants, a mobile viewport, a 404 page, sitemap removal, and port and host mismatch for instant navigation.

Clinical and benefit facts verified for this note:

* KDIGO 2024 CKD guideline PDF, text searched: PP 2.1.x, 2.2.x, 3.2.2.1, 3.4.1, 3.6.x, 3.7.x,
  3.10.x, 3.11.x, Table 28, Fig. 32, 4.x, Fig. 47, 5.4.x, 5.5.x; licence CC BY-NC-ND.
* KDIGO 2026 Anemia executive summary PDF (thresholds, licence).
* KDIGO Diabetes-in-CKD status page.
* Kerendia PI (revised 9/2026; indication, potassium rules, grapefruit).
* FINE-ONE results as reported by Drug Topics (2026-09-17):
  https://www.drugtopics.com/view/fda-approves-finerenone-for-chronic-kidney-disease-with-type-1-diabetes
* Lexicon / Zynquista status (company filings as summarised in search results; recheck).
* Medicare.gov ESRD, kidney disease education and insulin pages, and the CMS 2026 premiums fact sheet.
* KDIGO 2020 transplant-candidate summary (PMC7147399).
* OPTN waiting-time rule (OPTN policy notices).
* 2024 hyperglycemic crises consensus (Diabetes Care 2024;47:1257–1275).
* NHS ketone advice; ADA DKA page.
* MHRA icodextrin update; KDOQI 2015 HD adequacy targets; ACR–NKF contrast statements; AASM 2024 RLS guideline.
* NIDDK copyright page; FDA menu labeling; NIDDK hemodialysis page (access "healing may take several months").
* DOIs resolved via doi.org and Crossref (Levey 2020, Davison 2015).
