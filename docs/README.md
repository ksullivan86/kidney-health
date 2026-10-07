# Documentation index

Every document in the repository, one line each. The patient handbook (served by the app at `/learn`,
source in [`handbook/docs/`](../handbook/docs/index.md)) is the plain-language guide for the people
using the app; the pages below are for the people who run, maintain and check it.

## Start here

* [README](../README.md): what the app is and is not, features, quick start, licences.
* [CHANGELOG](../CHANGELOG.md): what changed in each version, upgrade notes, known limitations.
* [ROADMAP](ROADMAP.md): work the design notes defer to later versions, with the section that defers it.
* [SECURITY](../SECURITY.md): how to report a vulnerability, supported versions, verifying the image.

## Running a server

* [Deployment](deployment.md): rootless Podman (Quadlet), compose, rootless Docker, Kubernetes; every
  setting; first run; backups, restore and upgrades (including from v0.2); troubleshooting.
* [HTTPS](https.md): HTTPS for a homelab (own domain + Caddy, Tailscale, a private CA, cert-manager), so
  phones can install the app.
* [Security guide](security.md): threat model, the defaults and why, `TRUSTED_PROXIES` per topology,
  checklists per runtime, secrets, residual risks.
* [Accounts](accounts.md): sign-in modes, first start, passwords, adding people, lost passwords, keys,
  admin commands.
* [Privacy](privacy.md): what the server stores, who can see it, export and deletion.
* [Network allowlist](network-allowlist.md): every outbound host the app, the image build, CI and the
  development environment need, and when.
* [Deployment assets](../deploy/README.md): what each file in `deploy/` is for.

## Features (for operators and anyone checking the reasoning)

* [Install on your phone](install-on-your-phone.md): installing on iPhone, Android and computers;
  offline logging; updates (written for the people using the app).
* [Personalised targets and labs](targets-and-labs.md): how each suggested target is worked out, what lab
  results change, the eGFR card, open clinical review.
* [Meal guidance](guidance.md): what fits now, swaps, treating a low, plan the day, insights; every rule
  and number with its source; performance.
* [Optional AI](ai.md): what AI does and never does, what is sent, consent, providers and recipes,
  the SSRF policy, limits, turning it off.
* [Barcodes and photos](barcode-and-photos.md): scanning, Open Food Facts and USDA lookups, what leaves
  the device, licences; label and plate photos.
* [Diet guide (moved)](diet-guide.md): a pointer from the old diet guide's sections to the handbook pages.

## Contributing and maintaining

* [CONTRIBUTING](../CONTRIBUTING.md): setup, tests, the parity rule, harnesses, migrations, safety and
  security rules, how to add a food, a handbook page, a guidance rule, an AI preset or a setting, and the
  clinical-content policy.
* [Code of Conduct](../CODE_OF_CONDUCT.md): Contributor Covenant 2.1.
* [Maintainers](maintainers.md): the release process, verifying signatures and the SBOM, `HOLD_LATEST`,
  the repository settings to turn on, refreshing the lock files.
* [ARCHITECTURE](../ARCHITECTURE.md): the contract every change follows (API, data model, rules, the
  v0.3 decisions and file ownership).
* [AGENTS](../AGENTS.md) and [CLAUDE](../CLAUDE.md): the short rules for AI coding agents.
* [Progress notes](dev/progress/README.md): how build agents record interrupted work.
* [End-to-end harnesses](../tools/e2e/README.md): the browser checks run by hand before a release.
* [Vendored files](../app/static/vendor/README.md): the barcode decoder the browser uses, its licences
  and SHA-256 pins, and how to update it.
* [Handbook README](../handbook/README.md): building and checking the handbook, editing a page, citing a
  source, house style, clinical review and sign-off.
* [Handbook review log](../handbook/REVIEW.md): the fact-check findings per section and the open
  decisions for clinicians.
* [Live AI evaluations](dev/ai-eval/README.md): how `scripts/ai_eval.py` reports are made and judged.
* Test fixtures: [AI golden set](../tests/ai_golden/README.md),
  [Open Food Facts](../tests/fixtures/off/README.md), [USDA](../tests/fixtures/usda/README.md).

## Design notes (the specifications behind the contract)

* [01 Rootless containers, image hardening and supply chain](dev/research/01-rootless-and-security.md)
* [02 Installable app (PWA), service worker, offline, HTTPS](dev/research/02-ios-pwa.md)
* [03 Barcodes, Open Food Facts, USDA branded, label and plate photos](dev/research/03-barcode-and-photo.md)
* [04 Optional AI on top of rule-based guidance](dev/research/04-optional-ai.md)
* [05 Personalised targets (age, sex, activity, labs, eGFR)](dev/research/05-personalized-targets.md)
* [06 Rule-based meal guidance](dev/research/06-meal-guidance.md)
* [07 Accounts, settings and secrets](dev/research/07-accounts-settings-secrets.md)
* [08 The patient handbook site at `/learn`](dev/research/08-handbook-site.md)

## Research behind the numbers

* [CKD diet research brief](research/ckd-diet.md): renal nutrition for an adult with type 1 diabetes,
  from KDOQI, KDIGO and ADA.
* [Type 1 diabetes on a renal diet](research/t1d-and-ckd.md): carb counting, lows and the kidney diet.
* [Food lists](research/food-lists.md): eat / limit / avoid lists for stages 3b–5 with USDA values.
* [Fact-check of the research drafts](research/fact-check.md): the adversarial review and its
  corrections.
* [`targets_by_stage.json`](research/targets_by_stage.json): the fact-checked target table the app's
  suggestions are tested against.
