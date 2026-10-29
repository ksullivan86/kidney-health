# Roadmap: work the specifications defer to a later version

One line per item, with the specification that defers it (the design notes are in
[`docs/dev/research/`](dev/research/)). Items leave this list when they ship (move them to
[CHANGELOG.md](../CHANGELOG.md)) or when the owner drops them. Each feature owner appends to its own
section. Last reviewed for the v0.10.0 release (2026-10-29).

## First: daily logging you can trust (the owner, 2026-10-29)

An outside review of the code on 2026-10-29 found three bugs. The owner's order for the work after it: make daily logging and
recovery trustworthy before more AI or native-app features.

1. **A reliability milestone.** Fixed: Today kept showing the previous day's food when a day failed to load; saved meals showed
   unknown potassium or phosphorus as 0; a fitted 100-serving recipe could not be saved. `tools/e2e/reliability.py` makes each one
   happen in Chromium, and so are a slow day load followed by a quick date change, and a failed save with its retry on the entry
   sheet. `tools/e2e/health_save_retry.py` checks failed server saves and successful retries for weight, blood pressure
   and Labs on phone and desktop layouts. Still to test the same way: Plan and Profile.
2. **Unknown, zero and partial, the same on every screen.** Today, Trends, saved meals and the Add tab's shortcuts say "not listed"
   and "≥". So do the "Add a saved meal" sheet, the meals in What fits now and the day plan, and AI meal ideas (`unknown` next
   to each meal's `totals`). Still to check: the swap ideas and the Fit to my targets sheet.
3. **Backup and restore that a person can find and follow.** Done: Server administration shows the last backup and a reminder
   after 7 days with the restore link, and `tests/test_restore_roundtrip.py` restores a backup into an empty server in CI. Left:
   the same reminder for a server whose backups run outside the app (a volume snapshot leaves no `backup.created` row).
4. **Real phones and assistive tech as a release step.** Done: step 2 of the release process in
   [`maintainers.md`](maintainers.md#release-process) is a gate (iPhone offline, large text, keyboard only, VoiceOver, TalkBack),
   and the release pull request says who checked each line on what device.

## Next (the owner, 2026-10-22)

The next build is the **native iOS app as a Health sync companion** (option A of [note 15](dev/research/15-native-ios-app.md)): a small
SwiftUI app that reads weight and blood pressure from Apple Health in the background and sends them to `POST /push/v1/body` with a device
token. The Home Screen web app stays the place for every other screen. In this order:

1. **Done (2026-10-28): the shared Swift package `KidneyHealthCore` and its vector tests, run on Linux.** `ios/KidneyHealthCore` holds the
   rules that must equal the server's (ranges, the time-of-day context, the watch test, `source_key`, kilogram rounding, batches of 50)
   and checks each row as `POST /push/v1/body` does. CI replays `tests/data/body_vectors.json`, `apple_health_vectors.json` and
   `push_vectors.json` on a pinned Swift toolchain.
2. **Done (2026-10-28): the app target, built and unit-tested on GitHub's macOS runner** (in the simulator). `ios/KidneyHealthSync`:
   the server address and token, the Health permission for exactly three read types, background sync, and the status line. **Test
   connection** checks the token with `GET /push/v1/check` and sends nothing else.
3. **Signing, TestFlight and the owner's tests on a real iPhone**, once the owner has an Apple Developer Program membership (USD 99 a year).

Decided 2026-10-22: option A first, and the Swift package first (decisions 1 and 2 of
[note 15 §7](dev/research/15-native-ios-app.md#7-decisions-for-the-owner)). Still open: when to enrol and add the signing secrets (decision
3, needed for step 3), and whether the app pairs by QR code or by pasting the token (decision 4; the QR code is an optional fourth step of about 1M
tokens in note 15 §6, and the route to test a token is built). Cost, from note 15 §6: about 4–6M tokens for option A, against 6–10M for the
full web-view shell (option B), which stays a later choice. Out of scope: an App Store listing, Android, and anything that reads glucose,
insulin or medicines.

## Clinical review (before the draft banners can go)

* Clinician review of every open decision indexed at the top of [`handbook/REVIEW.md`](../handbook/REVIEW.md) ("Open clinical decisions": emergency tiers and red flags, glucose and CGM goals, food targets and the app's numbers, the remaining sections), each decision recorded there with the reviewer's name and date and the pages changed to match; then the sign-off of the pages it unblocks (`status: reviewed`, `reviewed_by`, `reviewed_on`) — note 08 §4.9 and §7 Phase 4; ARCHITECTURE.md v0.3 decision 11. The reviewers per section are listed in [`handbook/README.md`](../handbook/README.md#clinical-review-and-sign-off).
* The app-side rules waiting for the same review are listed under their features below (targets: note 05 C10; guidance: note 06 §5/§8; potassium additives: note 03 R5).

## Accounts, sign-in and secrets (note 07)

* OIDC sign-in (Authelia, Authentik, Keycloak, Kanidm, Pocket ID), choosing between Authlib 1.8 + itsdangerous and the project's own PKCE code (a new runtime dependency needs a contract decision) — note 07 F7, §3.1 and §6 "Later (v0.4)".
* A second factor for local sign-in: one-time codes (TOTP) shipped in 0.9.0 ([note 17](dev/research/17-two-step-sign-in.md)), and so did requiring them for admins. Passkeys shipped in 0.9.0 as an extra way in, with the password kept ([note 18](dev/research/18-passkeys.md)). Using a passkey instead of retyping the password is built too. Still later: accounts with passkeys only; with a second factor the 8-character password minimum becomes acceptable — note 07 §3.1, §6 "Later (v0.4)" and §8 risk R3.
* Optional SMTP for self-service password resets (today an admin makes a reset link or uses `python -m app.admin reset-password`) — note 07 §6 "Later (v0.4)".
* ~~Read-only sharing with a caregiver or dietitian~~ — shipped in 0.10.0 ([note 19](dev/research/19-sharing.md), [`accounts.md`](accounts.md#sharing-with-a-caregiver)): share links, four areas, the Visit prep page read-only, off until the admin turns it on. An end date for a share and shared Trends charts are built too (schema step 25).
* ~~Set the server up by code~~ — shipped in 0.10.0 ([note 20](dev/research/20-setup-by-code.md), [`deployment.md`](deployment.md#set-it-up-by-code)): a variable for every server setting, and `SETTINGS_INITIAL_ONLY` for first values an admin can change in the app later.
* An opt-in password pepper (`PASSWORD_PEPPER_FILE`) once operators keep their keys off the data volume — note 07 §3.2 ("not in v0.3 … revisit").
* One SQLite file per person (strongest isolation, deletion = removing a file) — note 07 §3.7 ("Revisit for v1.0").

## Installable app (note 02)

* Reminders through Web Push, opt-in and off by default (its own switch, because `PUSH_ENABLED` now turns on phone shortcuts; a VAPID key file; `pywebpush` 2.5.0 + `py-vapid` 1.9.4, generic bodies, never for lows: "use your CGM's alerts"), the push hosts in `docs/network-allowlist.md`, device tests on iOS 18.4+ and Chrome on Android — note 02 §3.6, R8 and §6 Phase 6 (v0.4).

## Personalised targets and labs (note 05)

* Clinical review of every rule marked opinion in `app/target_rules.py`, the K-5 alert wording, the 0.6 g/kg lower bound without diabetes (fact-check M6) and the one-step potassium relaxation on hemodialysis (fact-check L15); record reviewer and date in note 05's header — note 05 §7 C10. Until then `targets.lab_rules_enabled` stays off on public demo servers.
* Re-verify the sources when they change: KDIGO 2026 diabetes-in-CKD (final text), ADA Standards 2027, KDOQI nutrition updates, NASEM DRIs; read the GLIM and ISRNM primary tables before release — note 05 §7 C11 and §8.
* EKFC eGFR equation (needs regional Q values) as an alternative to CKD-EPI — note 05 §3.5 ("later option").
* Disease-specific resting-energy equations on dialysis (MHDE) — note 05 §3.2 option D and §6 ("kept as a later option").
* Frailty and sarcopenia screens (SARC-F, FRAIL) instead of the checkbox — note 05 F12 ("a later option. v0.3 uses a checkbox").

## Patient handbook at `/learn` (note 08)

* A "finerenone" profile flag that warns on grapefruit, as the Kerendia label says — note 08 §4.10 "Idea for v0.4".
* Spanish and other languages (page structure and slugs are language-neutral) — note 08 §6 risk 13 (v0.4, with Zensical or `mkdocs-static-i18n`).
* Migrate from MkDocs + Material to Zensical once a Zensical ≥ 0.1 release passes the CI canary (`handbook-zensical`) and the `/learn` browser check, before Material's security fixes end (November 2026 at the earliest) — note 08 §4.1 and §6 risk 2.
* Owner decisions before publishing: enable GitHub Pages (`HANDBOOK_PAGES=true`, needs a public repository or GitHub Pro/Team), then set `HANDBOOK_PUBLIC_URL` and the image's documentation label to the Pages URL — note 08 §4.8 "Owner setup", §7 Phase 0 and Phase 4.
* Clinical sign-off of every handbook page by the named reviewers (draft banners stay until then) — note 08 §4.9 and §7 Phase 4; ARCHITECTURE.md v0.3 decision 11.
* PEMAT-P self-score (understandability and actionability, each ≥ 70 %) of the 10 most-used pages, recorded in [`handbook/REVIEW.md`](../handbook/REVIEW.md) before the patient or caregiver reviewer's clarity pass: the pages the app links to (`get-help-now`, `t1d/treating-a-low`, `eat/potassium`, and `labs/` blood potassium, eGFR and creatinine, phosphate–calcium–PTH, albumin, bicarbonate, UACR, A1c) — note 08 §7 Phase 4 ("a PEMAT self-score on the 10 most-used pages") and §4.9 review roles. Its readability half ships: `tests/test_handbook_content.py` warns on any patient or caregiver page above reading grade 9.

## Meal guidance (note 06)

* Curated `typical_meals` tags on foods (breakfast foods at breakfast) beyond the slot-habit bonus — note 06 F10 ("deferred to v0.4").
* Vegetarian and pescatarian patterns (per-food diet tags) in the guidance settings — note 06 §4.14 ("deferred to v0.4").
* AI-written insights (v0.3 insights are rule-only; insights and low-treatment options are never sent to AI) — note 06 §3.6 and §4.13.
* Dialysis-day eating patterns beyond the interdialytic allowance — note 06 §5 R12 ("revisit in v0.4").
* An offline MILP experiment to measure how far the beam-search plans are from optimal — note 06 §3.1 option C ("could be an offline experiment"). The v0.3.0 review measured the beam against the exhaustive oracle of `tests/guidance/test_planner.py` on 160 seeded days: median 0.10 and at most 0.52 below it (the test bounds 40 days at 0.5).
* Clinical review (renal dietitian, diabetes educator) of the per-meal caps, score weights, tip texts and the "Treating a low" card — note 06 §5 R1/R6/R11 and §8 open questions (default carb tolerance, `purpose` defaulting to "hypo", starter combos). Since 0.4.0 Today's per-meal carbohydrate alert uses the person's carbohydrate tolerance and leaves out low treatments, and a person can set a tolerance for "about" targets (0–10 %, default 0); the review confirms the defaults and the 10 % ceiling (`handbook/REVIEW.md` "Food targets", A4 and v0.3.0 review L8).
* Measure guidance on real hardware: `python3 scripts/bench_guidance.py --max-p95 200` on a Raspberry Pi 4 and a Pi 5 with the image's Python, tables recorded in `docs/guidance.md` (lower `GUIDANCE_POOL_PER_ROLE` if a Pi 4 p95 is above 200 ms) — note 06 §4.12 and its "Re-verify" line (a maintainer action: no build has had a Raspberry Pi; the figures are estimates from an x86 machine, and food preferences added one indexed query per request; the x86 budget of 25 / 5 / 40 ms is already marginal at 2,000 foods on a slow machine, where p95 can flip between ok and over, which is why the CI test uses bounds four times looser).

## Barcodes, Open Food Facts and USDA branded foods (note 03)

* Clinical decision on the potassium-additive rule: whether a potassium additive with **unknown** potassium should be `high` instead of `medium`, by the owner and a renal dietitian (sources in `docs/research/fact-check.md` §5) — note 03 R5 ("the owner and a renal dietitian decide") and §6 item 2; ARCHITECTURE v0.3 item 9.
* Move to Open Food Facts API 3.5+ (`OFF_API_VERSION` in `app/off.py`; `parse_nutrition_v35` and the recorded `nutella_v3.6` fixture are ready) once OFF declares schema 1003+ stable — note 03 F1 ("keep a second parser … ready for when OFF declares schema 1003+ stable") and §5 risk table.
* A local copy of the Open Food Facts dump for large public instances (not in the image; ODbL share-alike applies to redistribution) — note 03 §3.1 ("Optional later for big instances").
* On-device label OCR with Tesseract.js 7 behind an accuracy gate (≥ 30 real labels, ≥ 95 % exact fields), with its own Trusted Types policy — note 03 §3.4 and R8 ("v0.4 experiment").
* Server-side barcode decoding (`zxing-cpp`) for API-only clients — note 03 §3.3 ("Keep as a documented option").
* Fill in Open Food Facts' API usage form for the project and document an admin contact for `OFF_CONTACT` — note 03 §6 item 19 (an owner action; the app already sends the identifying User-Agent).

## Optional AI (note 04)

* Provider-native tool calling, and read-only tools for the one-shot features (photos, meal ideas, describe a meal), for presets whose connection test confirms tool support — note 04 R14 ("Deferred (v0.4+)"). Not built; the Ask screen already lets the model call read-only tools that the server runs (`get_today`, `search_foods`, `check_meal`; at most 6 calls) through the app's own JSON loop, which works with every provider (ARCHITECTURE "The loop").
* Streaming status events ("contacting model… checking…") for perceived latency — note 04 R14.
* The live evaluation behind Ask: `python scripts/ai_eval.py --chat` with the model in use, for `PROMPT_VERSION` 2026-10-21.1 (the owner's). Note 04 R14 made ≥ 99 % correct refusals on live runs, with a golden set that has grown a large safety section, the condition for a free-text box; Ask shipped in 0.4.0 (off by default, answers checked in code) before that run.
* Model-written titles and reasons again, behind the golden-set gates, with NFKC, `Cc`/`Cf` removal, a confusable skeleton, an expanded term list (`shot`, `inject`, `pen`, `skip`, `delay`, `extra`, binder brand names) and a "worded by AI" label — note 04 §9 A2 ("Free text returns in v0.4 only behind the golden-set gates").
* The three reference live evaluations (Ollama `qwen3-vl:8b`, OpenAI `gpt-6-luna`, Hermes Agent) committed under `docs/dev/ai-eval/` before a model is listed as recommended in `docs/ai.md` — note 04 §6 Phase 5 (a maintainer action: no build has had an Ollama server, OpenAI key or Hermes Agent to run them against).
* Re-check whether Hermes Agent's `GET /v1/toolsets` lists tools of configured MCP servers, and tighten the tool check if it does — note 04 §9 A1 (b) and §7.
* **The answer before "nothing fits" on a real local model (the owner).** 0.6.0 changed the order of the answer format and the tests use
  recorded answers. Run `scripts/ai_eval.py` on the local model with 0.5.1 and with 0.6.0 and keep both reports, to see whether the meal
  ideas improved.
* **Recipes from the AI** (phase 3 of [note 16](dev/research/16-recipes-that-fit.md)): shipped in 0.8.0 (`POST /api/ai/recipes`, feature `recipes`,
  steps behind `ai.recipe_steps`, the Plan screens). What is left: the owner's live run of `scripts/ai_eval.py` on the
  cloud chain, which decides whether steps may be turned on (`steps_unsafe_shown` 0, a surviving recipe in 70 % of cases).
* Live runs of the 0.4.0 AI features that tests only fake (a maintainer action, steps in [`maintainers.md`](maintainers.md)): a photo of a real lab report on the local vision model, the route `local_then_cloud` with a real Ollama and a cloud key (`scripts/ai_eval.py` does not exercise routing), and the speech-to-text overlay (its image digest in `deploy/compose.stt-whisper.yaml` is a placeholder; a real whisper container; the microphone on an iPhone and an Android phone).

## Scanning, label photos and the offline outbox in the browser (notes 02 R5/R7, 03 R7–R9)

* Manual checks on real devices before a release: iPhone over HTTP (photo, including a HEIC one, and typed) and HTTPS (live camera, including the 4-second no-frame fallback for WebKit 282327), Android Chrome (native `BarcodeDetector`) and a desktop browser; plus note 02's matrix (install, icon and name, status bar in light and dark, offline start and the outbox, update prompt) on an iPhone, an iPad, an Android phone and desktop Chrome and Safari, over the Tailscale and private-CA HTTPS tiers; and on those devices the screen readers (VoiceOver, TalkBack: reading order of Profile, Lab results, the entry sheet and Settings) and iOS Safari's month and date pickers in Profile and Lab results — note 03 §6 item 14 and note 02 §6 "Manual device test matrix (before the release tag)" (a maintainer action: no build has had phones; add an entry edited and another deleted offline and a conflict made from a second device (note 02 R5), and the Ask microphone; `tools/e2e/device.py` covers Chromium with a fake camera and a stand-in native detector).

## Ideas from the owner (no specification yet)

Added 2026-10-07 after comparing similar projects (for example Kidney Advisor, a browser-only CKD tracker on GitHub Pages that imports Apple Health blood pressure, lab CSVs and patient-portal C-CDA files). Each needs a design note in `docs/dev/research/` before it is built; sizes are rough.

* **Health-data imports: what is left.** A run on real files, because the samples are hand-written: a real Health export from an iPhone, chosen as the `export.zip` itself in Safari on the phone and in a desktop browser ([note 11](dev/research/11-reading-a-zip-in-the-browser.md): the tests build their own archives, so this is the only check on what Apple's archiver writes), and real C-CDA downloads from at least two patient portals (MyChart and one more) — look at what the headline says a real file skips and add a LOINC code only after the lookup in [`targets-and-labs.md`](targets-and-labs.md#in-the-app) (the owner; [`maintainers.md`](maintainers.md)). Not built: reading `export.xml`'s `ClinicalRecord` entries instead of the `clinical-records/` folder, a "pick a folder" chooser (iOS Safari offers files only), the organizer's `effectiveTime` for a result a portal puts only there, and sending more than 1,000 rows in several requests. Open: the R2.1 definition page of the entries-optional results template (`…2.3`) could not be fetched, so that OID rests on HL7's own example and a second source.
* **Weight and blood pressure: what is left.** Built in 0.5.0 ([note 10](dev/research/10-weight-and-blood-pressure.md), [`body.md`](body.md)).
  Left, for the owner: a run with a real `export.xml` from an iPhone (steps in [`maintainers.md`](maintainers.md); it is the same real-file run
  as "Health-data imports" above) and the clinician review of the blood pressure lines in `handbook/REVIEW.md`. Not built, on purpose for
  now: weights and readings in Ask's `get_today` behind the existing consent (they are not sent to an AI or the assistant today), and
  adding them to the offline outbox (they need the connection). Glucose and insulin stay out: no dosing, and CGM apps keep their own alerts.
* **A native iOS app (large; the owner's, 2026-10-22; [note 15](dev/research/15-native-ios-app.md)).** The next build, in three steps: see
  "Next" at the top. After the Health sync companion comes the full shell if wanted (option B: a `WKWebView` around the person's own server,
  which gives up the service worker's offline shell, and later an Android app with Health Connect). A public App Store listing is a
  separate decision: review rejects a wrapped website without native features, it needs a privacy policy and Apple's health-data rules,
  and a regulatory opinion first (wellness app or clinical decision support?).
* **Phone shortcuts: what is left (the owner).** Built in 0.5.0 ([note 12](dev/research/12-phone-push-tokens.md), [`push.md`](push.md)). Left:
  run the handbook's recipe on a real iPhone (the Shortcuts action names and their order; that a personal automation runs without asking;
  that the phone reaches the server) and correct the handbook where it differs (`handbook/REVIEW.md` lists the check).
* **Lab results from a PDF report: what is left.** Built in 0.5.0 ([note 13](dev/research/13-lab-results-from-a-pdf.md), [`ai.md`](ai.md#lab-report-photos)): the PDF is opened and its ticked pages drawn in the browser (the vendored pdf.js), each page read like a photo; the server never takes a PDF. Left, for the owner: the live run on a real local vision model with real portal PDFs (Quest, Labcorp, a hospital portal) on an iPhone (Safari) and a desktop browser (`scripts/ai_eval.py` skips the local-only cases: try real reports on the Arc A770 or a larger card and watch which units and dates the model misreads, and whether a scan made of JPEG 2000 or JBIG2 images, which are not decoded, comes out blank). Not built: reading the PDF's own text layer, which would be faster and exact for the many portal PDFs that have one, but needs its own AI feature, prompt and judge ([note 13 §6](dev/research/13-lab-results-from-a-pdf.md#6-risks-and-later)). A small follow-up: a page is drawn at 2048 px and the photo helper (`KH.ai.prepareJpeg`) then redraws it at 1600 px; drawing it at 1600 px once would save a step.
* **An assistant you can talk to: what is left (the owner's main AI wish, 2026-10-08; built in 0.4.0).** Recipes themselves are built (the recipe API, the fitting engine and the Plan screens: "Recipes that fit your targets" below). Not built: reading a recipe *page* in `check_meal`. That means a recipe page's ingredient list (schema.org `Recipe` data, present on nearly every recipe site; kidney-specific sites such as Kidney Kitchen, DaVita and Kidney Community Kitchen are the useful search targets) or pasted ingredients, resolved like any item, per-serving totals and warnings, saved as a saved meal with the source link. Site nutrition panels usually omit potassium and phosphorus, so the app recomputes every time, and the UI must say recipe values are estimates (cooking losses, leaching); web fetching stays in the chat client, the app keeps talking only to USDA, Open Food Facts and its AI provider. Commercial recipe APIs (Edamam, Spoonacular) are an optional later source (keys, rate limits, terms that restrict storage). Live runs and device checks are in the Optional AI section above.
* **Kidney-only profile: what is left.** The app and the AI prompts follow a profile with *Diabetes: None* (no carbohydrate goals or alerts, the "Not medical advice" note without insulin decisions, prompts worded from the profile: [`ai.md`](ai.md#the-instructions-follow-your-profile), `tests/test_kidney_only.py`). Left to the owner: the golden-set run with a live model for the current `PROMPT_VERSION` (`python scripts/ai_eval.py --chat`, [`ai.md`](ai.md#for-contributors)); the handbook framing (reviewed content: keep the T1D section but stop presenting it as everyone's); and the app's one-line description in the page metadata and the web app manifest ("for a renal diet with type 1 diabetes"), which is the owner's framing to choose.
* **Privacy tiers: what is left (medium).** The app already withholds identity from every provider (no name, exact age, dates or notes; a keyed hash as the user id). Tier (1), per-feature routing, and tier (3), local first with a cloud fallback, ship in 0.4.0 ([`ai.md`](ai.md#which-ai-does-each-feature-use)). What a cloud model still sees is the free text a person types, photos, and the structured meal data. Remaining: (2) *redaction before the cloud*: the right tool is a purpose-built detector, not a chat model: rules plus a small named-entity model (Microsoft Presidio with spaCy or a GLiNER-class model, a few hundred million parameters, milliseconds on CPU, deterministic and testable) that replaces people, places, clinics, dates and record-like numbers with consistent placeholders and restores them in the reply, while leaving the medical content ("potassium 5.8") alone, since that is the question. Preferred placement: a guardrail in the LiteLLM proxy (it documents a Presidio integration; verify in the deployed version), so one redactor covers every client that reaches a cloud model (Hermes, Open WebUI, the app) with no app code; the in-app "Ask" screen later calls the same service and shows the redacted text in "What will be sent?". Add an offline redaction test set (messages with known identifiers, measured recall) next to the AI golden set. 1–2M. Honest limits: high recall, not perfect; it hides who, not that someone with CKD and type 1 diabetes asked; it does not need a bigger GPU; (4) a stronger local model for chat: a 16 GB Arc A770 runs about a 14B model at 4-bit (gemma or qwen class), usable for conversation but not frontier quality; a 24–32 GB card runs a 27–32B model at 4-bit, which follows tool-calling rules far more reliably, but at this app's volume a card costs several years of frontier API spend, so it is a privacy and independence purchase, not a saving: build tiers (1)–(3) first, measure on the A770 with `scripts/ai_eval.py` and real chat sessions, and buy only if the local model is the measured bottleneck (owner decision; for software support a used NVIDIA 24 GB card beats a new Intel or AMD one). Hermes with a cloud model is, by nature, the cloud tier: it keeps transcripts and forwards everything typed.
* **Learn my food preferences: what is left.** Built in 0.4.0 ([note 09](dev/research/09-food-preferences.md), [`guidance.md`](guidance.md)): the preference profile a person edits, signals learned by the app's code, changes proposed from Ask, and the bounded ranking term. Not built, on purpose or for lack of data: cuisines, a diet pattern and cooking effort or prep time as preferences (they need per-food data the built-in list does not have; vegetarian and pescatarian patterns are under "Meal guidance" above), and an allergy filter (ingredient data cannot guarantee it; the app never claims one). The owner's live Ask run for the prompt that added tastes is in the Optional AI section.
* **Recipes that fit your targets (the owner, 2026-10-27; [note 16](dev/research/16-recipes-that-fit.md)).** Phases 0 to 2 shipped in 0.7.0 and phase 3 (AI) in 0.8.0. A recipe is a saved meal with a count of servings and optional steps. The app's own engine fits it to a meal (lower amounts, swap a food, a smaller serving) and lists every change, with no AI. An optional AI feature, `recipes`, proposes or reworks a recipe from rule-made candidates and the app does every number; its steps are the one free text and stay off until the owner's live run. About 4.5–6.5M tokens without AI and 3–4M more for the AI (note 16 §13); the decisions are in [§15](dev/research/16-recipes-that-fit.md#15-decisions-for-the-owner).
* **Suggestions from a caregiver or coach (the owner, 2026-10-29; [note 21](dev/research/21-suggestions-from-a-caregiver.md)).**
  Proposed, not built. Someone a person shares their food log with may suggest a meal or a swap with a short note; it waits in
  the person's Plan until they tap **Add to my plan** or **No thanks**. Nothing is written for them. About 2-3M tokens.
* **The shopping list outside the app (the owner, 2026-10-29; [note 22](dev/research/22-shopping-lists-and-ordering.md)).**
  Share or copy the list to any app is built (Plan → Shopping list). Proposed, not built: send it to Grocy, KitchenOwl or Mealie on the person's
  own server (1.5-2M), and, only if the owner chooses a service, open it at a grocery delivery company (another company, off by
  default).
* **Clinician accounts with notes (large).** Builds on "Read-only sharing with a caregiver or dietitian" above: a `clinician` role that a person invites (and can revoke) to see their log, labs, symptoms and visit summaries read-only, and to add notes the person can read. Every view by a clinician goes to the person's activity log. The read-only sharing it builds on is built (note 19); it still needs a notes table, and wording about what the app is not: a self-hosted personal tool, not part of a clinic's medical record.
* **Direct patient-portal connection (SMART on FHIR, large; probably not).** Each EHR vendor (Epic, Oracle Health) requires registering the app and an OAuth flow per health system; for a self-hosted app each operator would have to register their own instance. The file imports above cover most of the value. This route covers MyChart (Epic's patient portal) and other EHR portals; the lab companies Quest and Labcorp are not EHRs and, as far as we know, offer no open patient API (check before designing), but their portals download PDF reports (the PDF item above) and results usually reach the doctor's EHR too. Paid aggregators (for example 1upHealth or Health Gorilla) would route health data through a third party, against the self-hosted design.

### Rough cost of the owner's ideas

Estimated 2026-10-07 for one agent working directly in a single session (as the small v0.3.0 follow-up PRs were), including re-reading the code and waiting for CI; expect ±50 %. A multi-agent build with separate review and fix rounds costs about 2–3× as much. "Owner" marks work only the maintainer can do (live model runs, vendor registration).

| Item | Tokens | Agent time |
|---|---|---|
| Native iOS app, option A: the Health sync companion (the steps and open decisions are under "Next") | 4–6M | not estimated in hours; the owner's Apple Developer account, signing and phone tests come on top |
| Native iOS app, option B: the full web-view shell (a later choice) | 6–10M | 2–3 days, plus the same owner steps |
| Direct patient-portal connection (SMART on FHIR) | 8–15M+ | several days, plus Epic registration (owner); not recommended |
| Privacy tiers: redaction before the cloud | 1–2M | 2–4 h |
| Clinician accounts with notes (includes the read-only sharing it needs, about 4–6M) | 7–11M | 2–3 days |

## Open items from the v0.3.0 build (no specification defers them)

Left open when v0.3.0 was finished, with the reason; each needs the named owner, not code.

* Cite or retire the six `handbook/sources.yml` entries no page cites (DG13b, DG19b, DG29, DG31, DG40, DG50; `tests/test_handbook_content.py::test_unused_sources_only_warn` lists them): they come from the old diet guide's bibliography, and dropping a source is an editorial decision for the handbook owner, not a build step.
* Ask an Open Food Facts moderator to delete the empty product `0099999999990` (Slack #moderation or contact@openfoodfacts.org): a manual check of the "add a product" link on 2026-10-06 used `action=process`, which creates an anonymous empty product. The app itself links only to `action=display`, which creates nothing; the recorded 404 fixture predates it (owner action).
* With the next `data/foods.json` release (it needs `scripts/build_food_db.py` and a version bump, which the v0.3.0 finish did not make for one word): the builtin "Bread, whole-wheat" note says "fibre" (`scripts/curated_foods.py`); everything else a person reads says "fiber", as the settings, Today, Profile and the handbook do.

## Open items from the v0.4.0 build (no specification defers them)

Left open when v0.4.0 was prepared, with the owner; each is a maintainer's call or run, not a missing feature, or the named next step of a change that is already in.

* Read nutrient labels and order from `GET /api/meta` instead of `rules.js` / `core.js` lists (note 14 change 4, step 2). The route and the demo's twin exist (`app/meta.py`, `js/mock/meta.js`), and `tests/data/meta_vectors.json` already holds the screens' lists equal to the server's; the screens still read their own copies. The step is to load `/api/meta` once after sign-in, build the nutrient table from it (keeping `rules.js` for the offline and demo cases and for the rounding the twins need) and show only the features its `capabilities` say work.
* Move the handbook build stage and the Debian fallback image to Python 3.15 once PyYAML publishes a cp315 wheel (the steps are in [`maintainers.md`](maintainers.md#refreshing-the-lock-files)). Until then Dependabot keeps proposing to move the handbook `FROM` line to the 3.15 digest, and that bump fails the image build (see the comment in `.github/dependabot.yml`); the `latest-dev` digests also move on, so expect a newer pair than the one in `deploy/Containerfile`.

## Open items from the v0.5.0 build (no specification defers them)

Left open when v0.5.0 was prepared; each is a person's call, not a missing feature.

* The header on a phone, for an admin (the shield button) and in the demo (the Preview pill): with the four icons there is no room for the app's name, so only the logo shows. A smaller pill, or moving the Learn link into Settings, would free it.
* Profile, Daily targets and About you: in two-column rows the boxes sit at different heights when one label wraps. The hints under the boxes rule out `align-items: end`; a CSS subgrid worked in a try but crowded two hint paragraphs together.
* Today with an empty log: "...enter them in Settings." ends with a 44 px link button, so the full stop sits a little apart. Cosmetic.
