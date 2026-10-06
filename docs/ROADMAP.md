# Roadmap: work the specifications defer to a later version

One line per item, with the specification that defers it. Items leave this list when they ship (move
them to CHANGELOG.md) or when the owner drops them. Each feature owner appends its own section.

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

## Meal guidance (note 06)

* Curated `typical_meals` tags on foods (breakfast foods at breakfast) beyond the slot-habit bonus — note 06 F10 ("deferred to v0.4").
* Vegetarian and pescatarian patterns (per-food diet tags) in the guidance settings — note 06 §4.14 ("deferred to v0.4").
* AI-written insights (v0.3 insights are rule-only; insights and low-treatment options are never sent to AI) — note 06 §3.6 and §4.13.
* Dialysis-day eating patterns beyond the interdialytic allowance — note 06 §5 R12 ("revisit in v0.4").
* An offline MILP experiment to measure how far the beam-search plans are from optimal — note 06 §3.1 option C ("could be an offline experiment").
* Clinical review (renal dietitian, diabetes educator) of the per-meal caps, score weights, tip texts and the "Treating a low" card — note 06 §5 R1/R6/R11 and §8 open questions (default carb tolerance, `purpose` defaulting to "hypo", starter combos).

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

