# Roadmap: work the specifications defer to a later version

One line per item, with the specification that defers it (the design notes are in
[`docs/dev/research/`](dev/research/)). Items leave this list when they ship (move them to
[CHANGELOG.md](../CHANGELOG.md)) or when the owner drops them. Each feature owner appends to its own
section. Last reviewed for the v0.3.0 release (2026-10-07).

## Clinical review (before the draft banners can go)

* Clinician review of every open decision indexed at the top of [`handbook/REVIEW.md`](../handbook/REVIEW.md) ("Open clinical decisions": emergency tiers and red flags, glucose and CGM goals, food targets and the app's numbers, the remaining sections), each decision recorded there with the reviewer's name and date and the pages changed to match; then the sign-off of the pages it unblocks (`status: reviewed`, `reviewed_by`, `reviewed_on`) — note 08 §4.9 and §7 Phase 4; ARCHITECTURE.md v0.3 decision 11. The reviewers per section are listed in [`handbook/README.md`](../handbook/README.md#clinical-review-and-sign-off).
* The app-side rules waiting for the same review are listed under their features below (targets: note 05 C10; guidance: note 06 §5/§8; potassium additives: note 03 R5).

## Accounts, sign-in and secrets (note 07)

* OIDC sign-in (Authelia, Authentik, Keycloak, Kanidm, Pocket ID), choosing between Authlib 1.8 + itsdangerous and the project's own PKCE code (a new runtime dependency needs a contract decision) — note 07 F7, §3.1 and §6 "Later (v0.4)".
* Passkeys (WebAuthn, `webauthn` 3.0.1) as a second factor or passwordless; with a second factor the 8-character password minimum becomes acceptable — note 07 §3.1, §6 "Later (v0.4)" and §8 risk R3.
* Optional SMTP for self-service password resets (today an admin makes a reset link or uses `python -m app.admin reset-password`) — note 07 §6 "Later (v0.4)".
* Read-only sharing with a caregiver or dietitian (`shares(owner_user_id, grantee_user_id, scope, created_at, revoked_at)` and a `Principal(user, acting_for)` dependency) — note 07 §6 "Later (v0.4)".
* Import of `export.json` into another instance (`POST /api/me/import`; the v0.3 export format was designed for it) — note 07 §4.14 and §6 "Later (v0.4)".
* An opt-in password pepper (`PASSWORD_PEPPER_FILE`) once operators keep their keys off the data volume — note 07 §3.2 ("not in v0.3 … revisit").
* One SQLite file per person (strongest isolation, deletion = removing a file) — note 07 §3.7 ("Revisit for v1.0").
* A "Not chosen yet" kidney stage and diabetes type for a new household account. The schema gives every new profile the single-user defaults (stage 3b, type 1 diabetes; `user_profiles` in note 07 §4.4), and the Profile form shows them preselected. Showing them as unchosen until the person saves needs a marker their first save sets (a schema step), an empty choice in the Profile form, and the same in the demo twin and the parity harness. Defaulting diabetes to "none" instead would hide the Treating a low card from a person with type 1 diabetes until they save, so the owner decides between the two — v0.3.0 review (UX, `app/migrations/m003_accounts.py`).

## Installable app (note 02)

* Reminders through Web Push, opt-in and off by default (`PUSH_ENABLED`, VAPID key file, `pywebpush` 2.5.0 + `py-vapid` 1.9.4, generic bodies, never for lows: "use your CGM's alerts"), the push hosts in `docs/network-allowlist.md`, device tests on iOS 18.4+ and Chrome on Android — note 02 §3.6, R8 and §6 Phase 6 (v0.4).

## Personalised targets and labs (note 05)

* Clinical review of every rule marked opinion in `app/target_rules.py`, the K-5 alert wording, the 0.6 g/kg lower bound without diabetes (fact-check M6) and the one-step potassium relaxation on hemodialysis (fact-check L15); record reviewer and date in note 05's header — note 05 §7 C10. Until then `targets.lab_rules_enabled` stays off on public demo servers.
* Re-verify the sources when they change: KDIGO 2026 diabetes-in-CKD (final text), ADA Standards 2027, KDOQI nutrition updates, NASEM DRIs; read the GLIM and ISRNM primary tables before release — note 05 §7 C11 and §8.
* EKFC eGFR equation (needs regional Q values) as an alternative to CKD-EPI — note 05 §3.5 ("later option").
* Disease-specific resting-energy equations on dialysis (MHDE) — note 05 §3.2 option D and §6 ("kept as a later option").
* Frailty and sarcopenia screens (SARC-F, FRAIL) instead of the checkbox — note 05 F12 ("a later option. v0.3 uses a checkbox").

## Patient handbook at `/learn` (note 08)

* Offline handbook pages: a runtime cache in the service worker (v0.3 leaves `/learn` to the network) — note 08 §4.6 "Service worker" (v0.4).
* "Add this menu day to my plan": turn a generated handbook menu day into planned entries (menus use builtin `fdc_id`s) — note 08 §4.10 "Idea for v0.4".
* A "finerenone" profile flag that warns on grapefruit, as the Kerendia label says — note 08 §4.10 "Idea for v0.4".
* Spanish and other languages (page structure and slugs are language-neutral) — note 08 §6 risk 13 (v0.4, with Zensical or `mkdocs-static-i18n`).
* Migrate from MkDocs + Material to Zensical once a Zensical ≥ 0.1 release passes the CI canary (`handbook-zensical`) and the `/learn` browser check, before Material's security fixes end (November 2026 at the earliest) — note 08 §4.1 and §6 risk 2.
* Owner decisions before publishing: enable GitHub Pages (`HANDBOOK_PAGES=true`, needs a public repository or GitHub Pro/Team), then set `HANDBOOK_PUBLIC_URL` and the image's documentation label to the Pages URL — note 08 §4.8 "Owner setup", §7 Phase 0 and Phase 4.
* Clinical sign-off of every handbook page by the named reviewers (draft banners stay until then) — note 08 §4.9 and §7 Phase 4; ARCHITECTURE.md v0.3 decision 11.
* Smaller handbook search index: prune the Lunr language support (about −0.9 MB of the image) — note 08 §6 risk 12 ("possible later").

## Meal guidance (note 06)

* Curated `typical_meals` tags on foods (breakfast foods at breakfast) beyond the slot-habit bonus — note 06 F10 ("deferred to v0.4").
* Vegetarian and pescatarian patterns (per-food diet tags) in the guidance settings — note 06 §4.14 ("deferred to v0.4").
* AI-written insights (v0.3 insights are rule-only; insights and low-treatment options are never sent to AI) — note 06 §3.6 and §4.13.
* Dialysis-day eating patterns beyond the interdialytic allowance — note 06 §5 R12 ("revisit in v0.4").
* An offline MILP experiment to measure how far the beam-search plans are from optimal — note 06 §3.1 option C ("could be an offline experiment").
* Clinical review (renal dietitian, diabetes educator) of the per-meal caps, score weights, tip texts and the "Treating a low" card — note 06 §5 R1/R6/R11 and §8 open questions (default carb tolerance, `purpose` defaulting to "hypo", starter combos).
* Measure guidance on real hardware: `python3 scripts/bench_guidance.py --max-p95 200` on a Raspberry Pi 4 and a Pi 5 with the image's Python, tables recorded in `docs/guidance.md` (lower `GUIDANCE_POOL_PER_ROLE` if a Pi 4 p95 is above 200 ms) — note 06 §4.12 and its "Re-verify" line (a maintainer action: the v0.3.0 build had no Raspberry Pi; the figures are estimates from an x86 VM).

## Barcodes, Open Food Facts and USDA branded foods (note 03)

* Clinical decision on the potassium-additive rule: whether a potassium additive with **unknown** potassium should be `high` instead of `medium`, by the owner and a renal dietitian (sources in `docs/research/fact-check.md` §5) — note 03 R5 ("the owner and a renal dietitian decide") and §6 item 2; ARCHITECTURE v0.3 item 9.
* Move to Open Food Facts API 3.5+ (`OFF_API_VERSION` in `app/off.py`; `parse_nutrition_v35` and the recorded `nutella_v3.6` fixture are ready) once OFF declares schema 1003+ stable — note 03 F1 ("keep a second parser … ready for when OFF declares schema 1003+ stable") and §5 risk table.
* A local copy of the Open Food Facts dump for large public instances (not in the image; ODbL share-alike applies to redistribution) — note 03 §3.1 ("Optional later for big instances").
* On-device label OCR with Tesseract.js 7 behind an accuracy gate (≥ 30 real labels, ≥ 95 % exact fields), with its own Trusted Types policy — note 03 §3.4 and R8 ("v0.4 experiment").
* Server-side barcode decoding (`zxing-cpp`) for API-only clients — note 03 §3.3 ("Keep as a documented option").
* Fill in Open Food Facts' API usage form for the project and document an admin contact for `OFF_CONTACT` — note 03 §6 item 19 (an owner action; the app already sends the identifying User-Agent).

## Optional AI (note 04)

* Read-only tool calling (for example `search_foods(q)` run by the server, at most 3 calls) for presets whose connection test confirms tool support — note 04 R14 ("Deferred (v0.4+)").
* kidney-health as an MCP server for Hermes Agent (streamable HTTP, a per-person bearer token, read-only tools returning rule-checked results only) — note 04 R14 and §3.3 H5.
* Streaming status events ("contacting model… checking…") for perceived latency — note 04 R14.
* A free-text "ask" box, only after the golden set grows a large safety section and live evaluations show ≥ 99 % correct refusals — note 04 R14.
* Model-written titles and reasons again, behind the golden-set gates, with NFKC, `Cc`/`Cf` removal, a confusable skeleton, an expanded term list (`shot`, `inject`, `pen`, `skip`, `delay`, `extra`, binder brand names) and a "worded by AI" label — note 04 §9 A2 ("Free text returns in v0.4 only behind the golden-set gates").
* The three reference live evaluations (Ollama `qwen3-vl:8b`, OpenAI `gpt-6-luna`, Hermes Agent) committed under `docs/dev/ai-eval/` before a model is listed as recommended in `docs/ai.md` — note 04 §6 Phase 5 (a maintainer action: the v0.3.0 build had no Ollama server, OpenAI key or Hermes Agent to run them against).
* Re-check whether Hermes Agent's `GET /v1/toolsets` lists tools of configured MCP servers, and tighten the tool check if it does — note 04 §9 A1 (b) and §7.

## Scanning, label photos and the offline outbox in the browser (notes 02 R5/R7, 03 R7–R9)

* Manual checks on real devices before a release: iPhone over HTTP (photo and typed) and HTTPS (live camera, including the 4-second no-frame fallback for WebKit 282327), Android Chrome (native `BarcodeDetector`) and a desktop browser; plus note 02's matrix (install, icon and name, status bar in light and dark, offline start and the outbox, update prompt) on an iPhone, an iPad, an Android phone and desktop Chrome and Safari, over the Tailscale and private-CA HTTPS tiers — note 03 §6 item 14 and note 02 §6 "Manual device test matrix (before the release tag)" (a maintainer action: the v0.3.0 build had no phones; `tools/e2e/device.py` covers Chromium with a fake camera and a stand-in native detector).
* Offline edits and deletes of entries already on the server, and profile changes (v0.3 queues only new entries, quick adds and "mark eaten"; anything else says it needs a connection) — note 02 R5 "Queueable offline actions (v0.3)".
