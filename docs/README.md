# Documentation index

Every document in the repository, one line each. The patient handbook (served by the app at `/learn`,
source in [`handbook/docs/`](../handbook/docs/index.md)) is the plain-language guide for the people
using the app; the pages below are for the people who run, maintain and check it.

## Start here

* [README](../README.md): what the app is and is not, features, quick start, licences.
* [CHANGELOG](../CHANGELOG.md): what changed in each version, upgrade notes, known limitations.
* [ROADMAP](ROADMAP.md): the owner's next build (a native iOS app, in steps), then work the design notes defer to later versions, with the section that defers it.
* [SECURITY](../SECURITY.md): how to report a vulnerability, supported versions, verifying the image.
* [LICENSE](../LICENSE) (code, PolyForm Noncommercial 1.0.0) and [handbook/LICENSE](../handbook/LICENSE)
  (handbook text, CC BY-NC-SA 4.0); the data and third-party licences are listed in the
  [README](../README.md#licences).

## Running a server

* [Deployment](deployment.md): rootless Podman (Quadlet), compose, rootless Docker, Kubernetes; every
  setting; first run; backups, restore and upgrades (from v0.4, v0.3 and v0.2); troubleshooting.
* [HTTPS](https.md): HTTPS for a homelab (own domain + Caddy, Tailscale, a private CA, cert-manager), so
  phones can install the app.
* [Security guide](security.md): threat model, the defaults and why, `TRUSTED_PROXIES` per topology,
  checklists per runtime, secrets, residual risks.
* [Accounts](accounts.md): sign-in modes, first start, passwords, adding people, lost passwords, keys,
  admin commands.
* [Privacy](privacy.md): what the server stores, who can see it, export, import and deletion.
* [Network allowlist](network-allowlist.md): every outbound host the app, the image build, CI and the
  development environment need, and when.
* [Deployment assets](../deploy/README.md): what each file in `deploy/` is for.

## Features (for operators and anyone checking the reasoning)

* [Install on your phone](install-on-your-phone.md): installing on iPhone, Android and computers;
  offline logging; updates (written for the people using the app).
* [Personalised targets and labs](targets-and-labs.md): how each suggested target is worked out, what lab
  results change, the eGFR card, open clinical review.
* [Weight and blood pressure](body.md): the log of weights and blood pressure readings: the tables, routes and settings, what the app works out
  (kilograms and pounds, the weight-gain alarm, the 7-day means against the goal), the handbook's words for a warning sign, export and import,
  the demo's twin and its checks (screens come in the next part).
* [Symptoms](symptoms.md): recording symptoms, loading another day, retrying a failed request and the Trends list.
* [Meal guidance](guidance.md): what fits now, swaps, treating a low, plan the day, insights; every rule
  and number with its source; performance.
* [Optional AI](ai.md): what AI does and never does, what is sent, consent, providers and recipes,
  the SSRF policy, limits, turning it off.
* [Barcodes and photos](barcode-and-photos.md): scanning, Open Food Facts and USDA lookups, what leaves
  the device, licences; label and plate photos.
* [The assistant](assistant.md): a chat assistant that reads your own food log and targets: personal access tokens,
  the MCP server at `/mcp` and its tools, connecting Open WebUI or a Hermes Agent profile, the system prompt template,
  the **Ask** screen inside the app with saving and a trust setting, voice, and the honest limits.
* [Connected devices](devices.md): a Withings scale or blood pressure monitor, or a Whoop strap, sends each person's data to their own log and Trends; the active-day calorie extra; how the server owner sets up each company's app
* [Your own list app](list-sync.md): send the Plan's shopping list to your own Grocy, KitchenOwl or Mealie; the address rules and `LIST_SYNC_ALLOWED_HOSTS`
* [Open the list at Instacart](instacart.md): send the Plan's shopping list to Instacart and open the page it makes; the server's own key, the development host and what is sent
* [Import a recipe](recipe-import.md): from a recipe page (the server reads its schema.org data) or pasted ingredients; every match checked by the person
* [Phone shortcuts](push.md): device tokens that let an iPhone Shortcut add weights and blood pressure readings to your own log
  (`POST /push/v1/body`): turning it on, the limits, what a leaked token can do. Add-only; it reads nothing.
* [The online demo](demo.md): the Pages demo, and **Keep my data in this browser** (IndexedDB, off until you choose it): what is
  stored, export and import of `export.json`, when it cannot work.
* [Try the app: a walk-through for people who know kidney disease](try-it-for-ckd.md): 45 minutes in the demo, with questions to answer. For testers who are not developers.
* [Test the full app](test-the-full-app.md): about an hour on your own server with the two test accounts (tester and tester-helper):
  turning them on, then everything from Today to the Care team, offline use and Send feedback. For testers who are not developers.
* [Diet guide (moved)](diet-guide.md): a pointer from the old diet guide's sections to the handbook pages.

## Contributing and maintaining

* [CONTRIBUTING](../CONTRIBUTING.md): setup, tests, the parity rule, harnesses, migrations, safety and
  security rules, how to add a food, a handbook page, a guidance rule, an AI preset or a setting, and the
  clinical-content policy.
* [Code of Conduct](../CODE_OF_CONDUCT.md): Contributor Covenant 2.1.
* [Maintainers](maintainers.md): the release process, verifying signatures and the SBOM, `HOLD_LATEST`,
  the repository settings to turn on, refreshing the lock files.
* [ARCHITECTURE](../ARCHITECTURE.md): the contract every change follows (API, data model, rules, the
  v0.3 decisions, the later sections and file ownership).
* [AGENTS](../AGENTS.md) and [CLAUDE](../CLAUDE.md): the short rules for AI coding agents.
* [The HTTP API document](api/README.md): `docs/api/openapi.json`, the checked-in OpenAPI document (regenerate it with
  `python scripts/gen_openapi.py`), the API-version rule, and what clients such as the iOS app generate from.
* [Progress notes](dev/progress/README.md): how build agents record interrupted work (condensed and removed at each release).
* [End-to-end harnesses](../tools/e2e/README.md): the browser checks run by hand before a release.
* [Vendored files](../app/static/vendor/README.md): the barcode decoder and the PDF reader (pdf.js) the browser uses, their licences
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
* [09 Learn my food preferences](dev/research/09-food-preferences.md)
* [10 Weight and blood pressure](dev/research/10-weight-and-blood-pressure.md)

## Research behind the numbers

* [CKD diet research brief](research/ckd-diet.md): renal nutrition for an adult with type 1 diabetes,
  from KDOQI, KDIGO and ADA.
* [Type 1 diabetes on a renal diet](research/t1d-and-ckd.md): carb counting, lows and the kidney diet.
* [Food lists](research/food-lists.md): eat / limit / avoid lists for stages 3b–5 with USDA values.
* [Fact-check of the research drafts](research/fact-check.md): the adversarial review and its
  corrections.
* [`targets_by_stage.json`](research/targets_by_stage.json): the fact-checked target table the app's
  suggestions are tested against.
