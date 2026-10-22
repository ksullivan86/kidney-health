# 14 · Reuse map: this code as a base for a general AI meal planner and for the native iOS app

| | |
|---|---|
| Status | Survey 2026-10-22 (read-only, against `main` at `2998cb5`); the order of work in §4 decided the same day (§6). |
| Why | The owner (2026-10-22): build so that most of the work can be reused for a custom AI meal planner / tracker / logger, the iOS app included. |
| Scope | What is domain-agnostic, kidney/T1D-specific or mixed, with evidence (`file:line`); what a second product and a native iOS client could reuse as is; the smallest splits; a ranked list of cheap changes; the risks. "Not found" means looked for and absent. |
| Related | Note 11 (zip reader, a general engine module), note 12 (device tokens and `/push/v1`, the iOS app's Health sync path), note 13 (PDF pages in the browser), ROADMAP "A native iOS app". |

Verdict letters: **A** = domain-agnostic, **M** = mixed, **K** = kidney/T1D-specific. Grep with `--glob '!.claude/**'` (agent worktrees hold full copies of the repo).

## 0. Scale

* `app/`: 39,923 Python lines. Grouped: platform 9.7k (config, db, security, auth, settings, crypto, audit, admin),
  food+log core 8.9k, AI infrastructure 3.4k, AI domain layer 5.0k, MCP 1.9k, guidance 6.3k, kidney-only modules 3.6k, migrations 1.2k.
* In-process `app.openapi()`: 147 operations on 108 paths, 154 schemas, OpenAPI 3.1.0. 2,573 test functions.
* `app/static/js`: engine 8.1k, mock (demo API) 5.3k, views 12.1k, core/offline/pwa/scan/main/learn 3.1k lines.
* Only 6 runtime Python dependencies (`requirements.in`: fastapi, uvicorn, h11, pydantic, httpx2, cryptography). SQLite, one file, one process.
* Extension seams that already exist: `settings_registry.register()`, `ratelimit.register_limit()` (`auth/ratelimit.py:39`),
  `audit.register_action()` (`audit.py:106`), `housekeeping.register_daily`, `security.register_body_limit`,
  `guidance.ai_bridge.register_ai_status`. Routers are **not** pluggable: `app/main.py:107-124` hard-wires 17 `include_router` calls plus `ai_routes.install`.

## 1. Layers and coupling

### 1.1 Server modules

| Module(s) | Verdict | Why (evidence) |
|---|---|---|
| `config.py`, `db.py`, `migrations/__init__.py`, `healthcheck.py`, `textclean.py` | A | Only brand strings: `DB_FILENAME="kidney.db"` `config.py:74`. Migration framework is append-only, numbered, idempotent (`migrations/__init__.py:1-30`). |
| `security.py` | A | CSP `:54`, Host allowlist `:379`, body limit `:499`, CSRF `:556`, log redaction. Brand: `CSRF_HEADER_VALUE="kidney-health"` `:111`. |
| `auth/*` (sessions, passwords, throttle, proxy, tokens, `api_tokens`, ratelimit) | A | No domain terms. Brand: `kha_` prefix and realm `api_tokens.py:56-64`, cookie `kh_session` `sessions.py:35`, HKDF labels `throttle.py:56-57`, `crypto.py:50`. |
| `settings_store.py`, `credentials.py`, `crypto.py`, `audit.py`, `egress.py`, `pwa.py`, `admin.py` | A | Registry precedence env > user > instance > default (`settings_store.py:1-20`); write-only sealed secrets; SSRF-checked `CheckedTransport` (`egress.py:143`); append-only audit. |
| `settings_registry.py` | M | Mechanism `:1-120` is A. The 777 lines also hold every feature's keys (`food.*`, `targets.lab_fresh_days.potassium`, `body.*`, `guidance`, `ai.*`) and `instance.name` default "Kidney Health" `:128-131`. |
| `nutrients.py` | **M** | Core A: `NUTRIENTS` `:33`, rounding `:85`, `add_totals`, unknown-tracking `:116-143`, `daily_status` `:404`, `build_alerts` `:458`. K: `CKD_STAGES/DIALYSIS_MODES/DIABETES_TYPES` `:55-57`, `FLAGS` `:60`, `THRESHOLDS` `:183`, `WARNING_ORDER` `:192`, `food_warnings` `:248`, `kidney_rating` `:318`, `meal_carb_alerts` `:537`, `suggest_targets` `:633`. |
| `foods.py` | M | Search, CRUD, per-user visibility (`user_food_links`), USDA client+mapper are A. K: `kidney_notes`/`kidney_rating` in `row_to_food` `:206-221`, `CATEGORIES` has "Diabetes supplies" `:56`, `scan_custom_food` `:1109`, UA `"kidney-health/0.3"` `:605`. |
| `off.py`, `gtin.py`, `barcode.py` | off/gtin A, barcode M | OFF client, token bucket, ODbL method file are A (`NUTRIENT_MAP` is the fixed 12 nutrients `off.py:76`). `barcode.py` merges the additive flags of both sources. |
| `additives.py` | K | E-number tiers to `phosphate_additive`/`potassium_additive`/`avoid_ckd` (`additives.py:1-30`). |
| `log.py` | M | Entries, batch, `client_id`, `If-Match` version are A. K: `purpose="hypo"` `:119`, `day_figures` hypo/carb branches `:408-497`, dialysis args `:526`, interdialytic `:609-650`. |
| `meals.py` | M | Saved meals + shopping list are A; embeds `kidney_rating` `:91-124`. |
| `periods.py` | M | Period averages A; `interdialytic_interval` `:219`, `pattern_alerts(dialysis=…)` `:342` K. |
| `models.py` | M | 1,438 lines, one file. `CkdStage/Dialysis/Diabetes` `:25-27`, `Profile` `:860-893`, `kidney_rating` in 4 response models (`:307,490,718,729`), `Interdialytic` `:663-685`. |
| `profile.py`, `user_profiles` | M | Core (weight, height, sex, birth_month, activity, week_start, targets_json) with CKD columns (`ckd_stage`, `dialysis`, `diabetes`, `hyperkalemia_history`, `pd_uf_ml`; `m001_base.py`, `m004_targets_labs.py:30-40`). |
| `targets.py`, `target_rules.py`, `kidney_function.py`, `units.py` | K | Pure and separable (`today` injected). KDOQI/KDIGO/ADA rules with citations. |
| `labs.py` | pattern A, content K | Canonical-unit + entered-unit pattern is general; analyte list is renal (`m004:46`). |
| `symptoms.py`, `body.py` | pattern A, content M | Date-ranged logs with `source_key` dedupe. K: dialysis contexts, `weight_alarm_check` (dry weight), `RED_FLAGS` quoting the handbook (`body.py:287`). |
| `guidance/*` (6.3k) | K by constants, algorithm A | Beam-search planner, budgets, scoring are generic. Renal constants `rules.py:33-49`; `R.K/R.P/R.NA/R.FLUID` and the key tuples appear on 111 lines across 11 files; `hypo.py` T1D. |
| `ai/` infrastructure | A | `client.py`, `presets.py`, `netpolicy.py`, `transport.py` (pinned, no redirects, byte cap), `config.py` (providers, resolution, quotas, consent), `routing.py` (local/cloud/off per feature), `cache.py`, `stt.py`, `voice.py`. |
| `ai/` domain layer | K | `prompts.py:47-160` ("Kidney Health", CKD, insulin ban), `guard.py:53-69` (binder names, BLOCKLIST), `features.py`, `schemas.py:22`, `chat.py:38` (imports `guidance.hypo`), `chat_save.py`, `lab_report.py`. `routes.py` M (hypo/red-flag prefilter before any model call `:725,825`). |
| `mcp/server.py`, `request_keys.py`, `measures.py` | A | Hand-written MCP Streamable HTTP (JSON-RPC), per-token limit 60/min, `request_key` dedupe. `INSTRUCTIONS` text is K. |
| `mcp/tools.py` | M | 1,329 lines; find-food/place-items/`write_once` are A; `safety_check` `:818`, `dialysis_info` `:263`, `kidney_rating` are K. |
| `account.py`, `data_import.py` | M | Export/import is versioned JSON (`kidney-health-export` v1, `account.py:65`, `data_import.py:108`) with the 12 nutrient names and CKD profile fields. |
| `handbook.py` + `handbook/` | tooling A, content K | `/learn` mount, CSP carve-out, offline copy are generic; 2,076-line `sources.yml` and pages are renal. |

### 1.2 Browser modules (`app/static/js`)

| Module | Verdict | Note |
|---|---|---|
| `engine/rules.js` (493) | M | Registry + Python-compatible rounding (`pyRound`, `halfUp`, `pyFsum`, `sqliteSum`, `:96-280`) are A and costly; `THRESHOLDS`/`FLAGS`/warnings K. |
| `engine/settings.js` | A mechanism, DEFS table M | Twin of registry, vectors `settings_vectors.json`. |
| `engine/{targets,kidney_function,additives}.js`, `engine/guidance/*.js` (4.7k together) | K | Twins of K server modules. |
| `engine/{textclean,gtin,off}.js` | A | |
| `engine/apple_health.js` (552) | A | Streams `export.xml`, reads only BodyMass and BloodPressure, builds `source_key`. Best seed for a Swift HealthKit mapper. |
| `engine/{body,symptoms,visitprep,menu_link,lab_import,fhir_labs,ccda_labs}.js` | M | |
| `core.js` (850) | M | DOM helpers, router, sheets, **`KH.api` client `:330-520`** (A, there is no `js/api.js`); renal orderings `:34-41` (`KEY_NUMBERS`, `STATUS_ORDER`, `INTERDIALYTIC_KEYS`). |
| `offline.js` (1,151) | A mechanism | IndexedDB outbox, FIFO replay, `client_id`, `If-Match`, 412 conflict card; written around `/api/log` paths. |
| `pwa.js`, `sw.js`, `scan.js` | A | Service worker caches static files only, never `/api` (`sw.js` header). |
| `mock/*` (5.3k) | M | A JS copy of the server's routes for the GitHub Pages demo. It is also an executable description of the API. |
| `views/*` (12.1k) | K | `settings.js` (1,872) and `auth.js` are reusable in shape but mix every feature. |

### 1.3 The ten entanglements that matter

1. **Warnings and the "kidney rating" sit in the nutrient core and reach every response.** `nutrients.py:183,192,248,318`; consumed
   at `foods.py:206,221`, `log.py:225,239`, `meals.py:96,103,124`, `mcp/tools.py:372,684`, `guidance/fits.py:96`; API fields at
   `models.py:307,490,718,729`; `foods.kidney_notes` column (`m001_base.py:43`).
2. **Twelve nutrients are the schema.** Columns in `foods` and `log_entries` (`m001_base.py:31-64`); SQL column lists
   `foods.py:123`, `log.py:99`; USDA/OFF maps `foods.py:75`, `off.py:76`; JS `rules.js:20-33`; vectors store arrays "in `nutrient_keys`
   order"; the entry version hash walks "the 12 nutrient values (registry order)" (`log.py:181`). A 13th nutrient is a migration plus six edits.
3. **The profile is a CKD profile.** `ckd_stage/dialysis/diabetes` NOT NULL with defaults 3b/type1 (`m001_base.py`), `Profile`
   `models.py:860-893`, stage-driven targets (`targets.py:277`); `*_chosen` flags exist only because defaults drive behaviour.
4. **Day maths has T1D and dialysis branches inside the generic pipeline.** `log.day_figures` `log.py:408-497` (`hypo_meals`,
   `meal_carb_alerts`), `day_pattern_alerts` `:526`, `get_summary` `:638`, `PeriodSummary.interdialytic` `models.py:678-685`, `periods.py:219,342`.
5. **`purpose="hypo"` is a column, an API field and part of the entry version hash** (`log.py:119,181`; `LogCreate.purpose`). A general
   product can ignore it but cannot drop it without breaking `If-Match` equality between clients.
6. **The guidance engine's constants are renal.** `guidance/rules.py:33-49` (`ROOM_KEYS`, `CAP_KEYS`, `DAY_JUDGED`, `INTERDIALYTIC_KEYS`),
   `:65-69` (carb tolerance, rule of 15), `budget.py:152` (dialysis allowance), `vectors.py:29` (`renal_level`), `swaps.py` hypo mode.
7. **AI prompts, guard and prefilters name the condition and the dose ban.** `prompts.py:47-160,239`; `guard.py:53-69`;
   `ai/routes.py:725,825`; golden set `tests/ai_golden` has 97 case files, about half domain-specific (`hd-*`, `rules-*`, `safety-*`,
   `prefilter-*`, `kidney-only-*`, `lab-report-*`: 49).
8. **The kidney additive scan runs in every ingest path.** `foods.py:1109-1127` (hand-entered), USDA mapping `foods.py:801-885`,
   `off.map_product`, `barcode.py` flag union. Even a general product's barcode scan would get `avoid_ckd` and phosphate flags.
9. **Cited handbook text is wired into code and tests.** `body.py:287` and `symptoms.py` quote `handbook/docs/get-help-now.md` and tests
   fail if a phrase moves; `guidance/topics.py:43` maps rules to `/learn` pages; `mcp/tools.py:72`.
10. **Brand strings are spread out.** About 96 Python lines in 40 files and 140 JS/HTML/SW lines: cookie `kh_session`, header
    `X-Requested-With: kidney-health`, `kha_`, `kidney.db`, IndexedDB `kdl`, HKDF labels, export `format`, user agents
    (`foods.py:605`, `ai/client.py:38`), manifest "Kidney Diet Log". Some are on-disk compatibility surface (HKDF labels, cookie names).

## 2. Reuse for (a) a general AI meal planner / tracker / logger

### 2.1 Reusable as is (no domain edit needed, only branding)

| Piece | Where | Why it is ready |
|---|---|---|
| Accounts, sessions, invites, reset links, local and trusted-proxy identity (OIDC is a ROADMAP item; the `auth_source` column already allows it), throttling, re-auth, last-admin rule | `app/auth/*`, `m003` | A; many tests (`test_auth*.py`, `test_isolation*.py`, `test_api_tokens.py`); every route `current_user`, scoped by `user.id`, not-yours 404 (`tests/test_auth_coverage.py`, `test_isolation*.py`). |
| Settings registry + store + admin/user views | `settings_registry.py` (mechanism), `settings_store.py`, `engine/settings.js` | Typed pydantic defs, env locks, precedence, vectors-checked JS twin. |
| Secrets/credentials with quotas, audit log, export/delete of account | `credentials.py`, `crypto.py`, `audit.py`, `account.py` | Write-only keys (`{set,last4}`), sealed with purpose+owner. |
| Foods DB layer: search ranking, per-user visibility, USDA client, OFF client, barcode flow, GTIN rules, SSRF transport | `foods.py`, `off.py`, `barcode.py`, `gtin.py`, `egress.py` | "Unknown is never zero" (NULL) is a strong, general rule. Shared `usda`/`off` rows linked per person. |
| Log + saved meals + shopping list + copy-day + mark-eaten + planned/eaten | `log.py`, `meals.py` | Needs only #1/#2/#4 split below to drop the renal fields; `POST /api/log/quick` makes a food from typed nutrients (an AI logger can write through it). |
| AI provider layer | `ai/client|presets|netpolicy|transport|config|routing|cache|stt|voice` | OpenAI-compatible, Ollama, Hermes, OpenRouter presets; address pinning; consent per purpose; local-first routing; activity log without content. |
| MCP server + assistant tokens | `mcp/server.py`, `request_keys.py`, `measures.py`, `auth/api_tokens.py` | Tools are the product-specific part; transport, tokens, scopes, 24 h `request_key` dedupe are generic. |
| Ask-chat loop pattern | `ai/chat.py` | Model calls read-only tools through a JSON step protocol; saves are cards the person confirms; answer checked in code (numbers must match tool results). |
| Export/import | `account.py`, `data_import.py` | `extra="forbid"` models, dry run, merge, never trusts ids in the file. |
| PWA shell, offline outbox, update toast, barcode scan | `pwa.js`, `sw.js`, `offline.js`, `scan.js`, `vendor/` | No CDN, strict CSP with Trusted Types; vendored hashes in `vendor/README.md`. |
| Vectors/twins test pattern | `tests/data/gen_*.py`, `*_vectors.json`, `tests/js/run_vectors.mjs` | Python is the oracle; the generator has `--check`; pytest fails when a vector file is stale. |
| Deploy | `deploy/` (Containerfile by digest, rootless compose, Quadlet, k8s PSA-restricted), `.github/workflows` | SHA-pinned actions, signing, Grype gate; names are `kidney-health` throughout (3 to 21 hits per file). |

### 2.2 Needs a split (smallest split that works)

| Split | Smallest version | Touch points | Size |
|---|---|---|---|
| Nutrient rules out of the nutrient core | Move `THRESHOLDS/WARNING_ORDER/food_warnings/kidney_rating/meal_carb_alerts/suggest_targets` into `app/rules_kidney.py`; `nutrients.py` re-exports (no caller or vector changes). | `nutrients.py` only; the seam is clean: `daily_status`/`build_alerts` use only roles. | S |
| `RulePack` / `domain` profile | One object with: `nutrients` (core 12 + extras), `warnings()`, `rating()`, `day_alerts(rows, profile)`, `suggest_targets()`, guidance constants, prompt texts, prefilters, content links. Default pack `kidney_t1d`; new `general_diet`. | #1, #4, #6, #7, #8 of §1.3. Without it a fork must edit 11 guidance files and 3 log paths. | L (the first hook, warnings+rating, is M) |
| Nutrient set as data | Keep the 12 columns as "core"; add `nutrients_extra_json` (append-only step 19+) and registry-driven keys appended at the end (keeps hash and vector order). | `foods`, `log_entries`, `Entry.version`, USDA/OFF maps, vectors. | M |
| Profile | Core columns stay; move CKD fields behind `profile.condition` JSON keyed by pack. | `ProfileUpdate/Profile` `models.py:804-893`, `profile.py`, `data_import.py`. | M |
| `log.day_figures` | Pass `pack.day_alerts` instead of inline hypo/carb/dialysis branches. | `log.py:408-530`, `periods.py`, `mcp/tools.py:263`. | M |
| AI domain layer | `prompts`, `guard.BLOCKLIST/MEDICINE_NAMES`, `prefilter` list, `condition_text` come from the pack. The dose ban and "prefilter runs before any model call" stay core and not overridable. | `ai/prompts.py`, `guard.py`, `features.py`, `routes.py:725,825`. | M |
| Settings blocks | Move each feature's `register(...)` block next to its module (the API supports it). | `settings_registry.py`, import order. | S |
| Router composition | `create_app(modules=[…])` instead of the fixed list `main.py:107-124`. | `main.py`. | S |
| Browser shell kit | Cut `api.js` out of `core.js:330-520`; read nutrient order and labels from the server (see change 4); keep `offline.js`, `pwa.js`, auth/settings views. Views stay per product. | `core.js:34-41`, `rules.js:20-33`. | M |
| Handbook | Keep the build/serve tooling; content is a per-product pack; `topics.py` and the quote tests move with it. | `handbook.py`, `guidance/topics.py`, `tests/test_handbook_content.py`. | M |

Parity cost to decide up front: each twin directory (engine 8.1k + mock 5.3k lines + 6.3 MB of vectors) doubles work per rule. A new
product can stay server-authoritative and keep twins only for pure validators and for a public demo if wanted.

## 3. What a native iOS client needs, and whether it exists

Plan on record: ROADMAP "A native iOS app" (`docs/ROADMAP.md:84`): Swift shell, `WKWebView` around the person's own server, HealthKit
for weight and blood pressure through the note 10 batch routes, "builds on the narrow write-only tokens". Cost row: 6-10M tokens, 2-3 days,
plus the owner's Apple Developer account, signing and phone tests. No Swift, Xcode or `macos` runner in `.github/` (grep: none).

| Need | Today | Evidence | Gap |
|---|---|---|---|
| Sign-in | **Cookie session only.** `POST /api/auth/login` sets `__Host-kh_session` (HTTPS) or `kh_session`, `HttpOnly; SameSite=Lax`; 30 days absolute, 14 idle; nothing returns the session in the body. | `sessions.py:35,216-234`, `config.py:210-211` | Works in a `WKWebView` unchanged. A URLSession client keeps cookies but a 30-day expiry silently breaks background sync. |
| CSRF/Origin | Unsafe `/api` calls need header `X-Requested-With: kidney-health`; `Sec-Fetch-Site: cross-site/same-site` is refused; a sent `Origin` must match. | `security.py:105-111,556-625` | A native client sends neither Sec-Fetch-Site nor Origin; it only has to add the header. |
| Bearer token on `/api` | **Not found.** `Authorization` is read only by `api_tokens.authenticate`, whose only caller is `/mcp` (`mcp/server.py:158`); `current_user` never reads it (`deps.py:84-96`); `test_auth_coverage` walks every route with a valid token and expects 401. | `api_tokens.py:1-30,56-59` | Scopes today: `assistant:read`, `assistant:log` only (`api_tokens.py:54-56`); max 5 active (`:59`), expiry 30/90/365. |
| Device tokens | **Being built** (note 12): `khd_` family, scope `body:write`, `POST /push/v1/body` outside `/api`, add-only, counts-only answers, 50 rows, 60 req/h per token, off by default, same-reading check, schema step 19. | note 12 §4 | Write-only: enough for HealthKit ingest. A native app with its own read screens would need a read scope or a token-for-session exchange; not designed anywhere. |
| HealthKit write path | **Exists (session auth).** `POST /api/body/weights/batch`, `/blood-pressure/batch`: 1-1,000 rows, `source` `apple_health`\|`import`, `source_key` 1-64 chars, unique `(user_id, source_key)`, repeats counted in `skipped`, whole request refused on the first bad row (`rows.3.kg: …`), 20 weights / 30 readings per day, `body_batch` 60 req/h. | `body.py:485-590`, `ratelimit.py:49`, ARCH "Weight and blood pressure" | The ranges (20-400 kg, 50-300/20-200, systolic > diastolic, date not in future) must be repeated in Swift or one outlier blocks the batch. `source_key` = first 32 hex of SHA-256 of `type|startDate|value|sourceName` is built in JS (`apple_health.js`); Swift must match it to dedupe against the web import. Vectors pin it (`apple_health_vectors.json`, `body_vectors.json`). Only weight and BP exist server-side; no steps, HR, glucose (by design). |
| Food-log writes | **Exists.** `POST /api/log`, `/quick`, `/batch` (<= 40) with `client_id` UUID idempotency; `PUT/DELETE` with `If-Match` entry version and 412 `{detail, current}`. | `log.py:710-960`, ARCH "Entry version" | Session auth only. The outbox protocol is reusable for a Swift queue. |
| Stable, documented API | **Partial.** OpenAPI 3.1 exists in process; `/openapi.json` and `/docs` are **off by default** (`ENABLE_API_DOCS=false`, `main.py:93-95`, `config.py:239`). No committed snapshot, no `/api/v1`, no API version number; policy "API changes stay additive" is prose only. `X-KDL-Version` is a hash of the static files, not an API version. | `main.py:93-95`; ARCH "X-KDL-Version" | The schema lies about validation: it lists `422` but the handler returns **400** `{detail, errors}` (`security.py:662-669`); no `securitySchemes`; operationIds are `login_api_auth_login_post`-style (unstable on rename); 29 of 147 operations lack a typed 2xx schema. |
| Error shape | `{"detail": str}` plus optional flags: `reauth_required`, `setup_required`, `password_change_required`, `https_required`, `retry_after`, `field`, `problems`; validation `{"detail","errors":[{type,loc,msg}]}`; 429 with `Retry-After`; 412 with `current`. | `auth/errors.py`, ARCH "Identity and request rules" | Not in the OpenAPI document. |
| Pagination / changed since | **Not found.** Lists are date windows of at most 366 days (`start`,`end`) for body, log range, symptoms; `labs?limit<=1000`; `foods?limit<=200`. No cursor, no `updated_since`, no tombstones (hard `DELETE`). `updated_at` columns exist on weights, readings and entries. ETag/304 only on `GET /api/foods/builtin` (`foods.py:1048`). | `body.py:413`, `foods.py:1006` | Fine for write-only HealthKit sync. Offline reading in a native app needs `updated_since` and a deletion story. |
| Photos / barcode | Raw `image/jpeg` body (no multipart) to `/api/vision/label\|plate` and `/api/ai/read-lab-report`; barcode digits only to `POST /api/foods/barcode`; server-side decoding not built. | `vision.py:17`, `barcode.py:1-10` | Native-friendly (VisionKit/AVFoundation decode on device, HEIC to JPEG on device). AI routes answer 404 while `ai.enabled` is off. |
| Push / background refresh | **Not found.** No APNs or Web Push code (`pywebpush`/`PUSH_ENABLED` absent from `app/`); ROADMAP lists Web Push as v0.4+, "never for lows". The server only calls out to USDA, OFF, the AI and STT hosts. | `docs/ROADMAP.md` "Installable app" | HealthKit background delivery wakes the app and posts to the server; no server push is needed for that. Reminders would need an APNs sender and a device-token table. |
| Browser-only assumptions | Shell served from `/` (HTML, CSS, JS, service worker); `Clear-Site-Data` on logout; Host allowlist (`localhost`, IP literals, `PUBLIC_URL`, `ALLOWED_HOSTS`; others 400) `security.py:379`; plain-HTTP sign-in only while at most one account exists. | `pwa.py`, `auth/routes.py` | Native client needs the server host in `ALLOWED_HOSTS` or `PUBLIC_URL` and HTTPS (App Transport Security). The service worker never touches `/api`. No HTML responses on `/api`. |

What a Swift client can reuse from the repo as is: the JSON vector files (plain data, Python is the oracle), `js/mock/*` and
`docs/body.md` as API specification, `apple_health.js` as the reference scanner, the export format as a backup/import path.

## 4. Ranked low-cost changes

### Do soon, cheap (helps both, hurts nothing)

| # | Change | Where | Size | Unlocks |
|---|---|---|---|---|
| 1 | Build note 12 (in progress): `khd_` device tokens, scope `body:write`, `POST /push/v1/body`, schema step 19. Keep families separate. Add `scopes`/`family` to the token list answer. | `auth/api_tokens.py`, new `app/push.py`, `m019` | M (note says one part) | iOS HealthKit sync without password or 30-day cookie; later `log:write` for a general logger. |
| 2 | Make the contract honest and checked in: `generate_unique_id_function` for stable operationIds, document 400 validation instead of 422, add `securitySchemes` (cookie + bearer), commit `docs/api/openapi.json` with a `--check` generator and a pytest like the vectors'. The dump needs no `ENABLE_API_DOCS` (tests call `app.openapi()`). | `main.py`, new `scripts/gen_openapi.py`, `tests/` | S | `swift-openapi-generator` for the iOS app; breaking-change alarm for both products. |
| 3 | `app/brand.py` (+ `KH.brand`): name, slug, cookie names, token prefixes, CSRF value, DB filename, user agents, export format. Do not change current values (they are on-disk compatibility). Note 12 adds `khd_`, so do it first. **Done (2026-10-22):** `app/brand.py` and `KH.brand` (`js/engine/brand.js`); no value changed, `tests/test_brand.py` pins them and fails on a new copy of a main literal; ARCHITECTURE.md "Brand strings" lists what was left alone and why. | `security.py:111`, `sessions.py:35`, `api_tokens.py:56`, `config.py:74`, `foods.py:605` … | S | A second product by configuration, not by grep (about 96 + 140 lines). |
| 4 | `GET /api/meta`: `api_version` (integer, bump on breaking), capabilities (ai, chat, voice, assistant, push, barcode providers), and the nutrient registry (key, label, unit, role) and meals. | new small router; reuse `nutrients.NUTRIENTS`, `ai_routes` status | S | Native feature discovery; removes hard-coded lists (`rules.js:20-33`, `core.js:34-41`); first step to nutrients-as-data. |
| 5 | Move renal/T1D rules out of `nutrients.py` into `rules_kidney.py` behind a re-export. | `nutrients.py` | S | Prerequisite for any pack; zero behaviour change, vectors unaffected. |
| 6 | Swift test target that replays `body_vectors.json` and `apple_health_vectors.json` on a `macos` runner; add `tests/data/README.md` describing the vector schema. New workflow must keep the repo rules (`permissions: {}`, SHA-pinned `uses:`, `persist-credentials: false`; `tests/test_deploy.py` checks them). | new workflow, `tests/data/` | S | Proof that Swift rounding, `source_key` and validation equal the server. |
| 7 | Name the safety pack: list the tests that must travel (`tests/guidance/test_hypo.py`, `test_food_safety.py`, `test_messages.py` BANNED_PATTERN lint, `ai_golden/safety-*` and `prefilter-*`, `test_ai_chat_checks.py`) and mark them (`pytest -m safety`). | `pyproject.toml`, `CLAUDE.md` | S | Safe extraction; CI proof that any fork keeps the rules. |

### Do when the second product starts

| # | Change | Size | Note |
|---|---|---|---|
| 8 | `RulePack` hooks (§2.2): warnings+rating first, then `day_alerts`, then guidance constants. | M then L | Start with the two hooks `food_warnings` and `kidney_rating`; every other entanglement can wait. |
| 9 | Nutrients as data (`nutrients_extra_json`, registry keys appended at the end). | M | Keeps `Entry.version` and vector order stable for the existing nutrients. |
| 10 | `profile.condition` JSON per pack; stop NOT NULL defaults 3b/type1 for packs that have no stage. | M | |
| 11 | `updated_since` on body, log and labs plus tombstones (a `deleted_at` table or soft delete). | M | Only if the native app reads data offline. Hard deletes today (`DELETE` routes). |
| 12 | AI domain layer from the pack; dose ban and prefilter-first order stay in core. | M | |
| 13 | Router composition and per-module settings blocks. | S | |
| 14 | Extract `api.js`, keep `offline.js`/`pwa.js`/auth+settings views as a shell kit. | M | |
| 15 | Licence decision (see risks). | S (owner) | Needed before any commercial use of the code. |

Suggested order: 3 (brand) and 2 (contract) first because they are small and everything after depends on stable names and a
checked schema; then 1 (device tokens, which the iOS plan already waits on); then 4 and 6; 5 and 7 in any quiet moment. Nothing in
the first group changes behaviour or any vector, so `python -m pytest` and `node tests/js/run_vectors.mjs` stay the gate.

## 5. Risks

1. **The safety rules must travel with every reused piece** (CLAUDE.md): no insulin or medicine dosing; never block or warn against
   treating a low; every clinical number traceable. Where code enforces them: `guidance/messages.py` BANNED_PATTERN lint; `ai/guard.py`
   BLOCKLIST and `chat.py` dose check; `guidance/hypo.py` prefilter running before any model call (`ai/routes.py:725,825`);
   `hypo_treatment` foods get no carbohydrate warning (`nutrients.py:248-317`); swaps never shrink a low treatment;
   `symptoms`/`body` RED_FLAGS quote the handbook and tests fail on drift; `test_body.py` greps that no line names a cause, treatment or dose.
   A "general" planner will still be used by people with type 1 diabetes: the protections should be default-on in every pack.
2. **Unreviewed clinical content.** Draft banners, `targets.lab_rules_enabled` off on public demos, opinion rules in `target_rules.py`,
   and ROADMAP "Clinical review" are open. Reusing numbers without their citations and review state breaks the "cited source" rule.
   ROADMAP also flags the App Store question "wellness app or clinical decision support?" as unresolved.
3. **Least-trust security must be copied, not re-derived.** Any route outside `/api` (like `/mcp`, `/push/v1`) needs the bearer-only
   CSRF carve-out (`security.py:109`), a generic 401, per-token limits and a test that a cookie-only request is refused. Health
   data is kept away from AI by tests (`app/ai`, `app/mcp`, `app/guidance` do not read weights, readings, symptoms; labs only via local AI).
4. **Session lifetime vs background sync.** 30-day absolute cookie sessions mean a HealthKit observer fails silently with 401 about monthly
   unless it holds a device token (change 1). Store it in the Keychain; revoke on password change (already how `revoke_all` works).
5. **Whole-batch refusal.** One implausible reading in a 1,000-row HealthKit batch returns 400 and writes nothing; the web sheet trims
   per day first (`body_import.js`, `trimDays`) and stops on any refusal. Swift needs the same trimming and 60 req/h awareness.
6. **Twin cost.** Rounding parity with Python needed about 185 lines of JS (`rules.js:96-280`). A Swift twin of the engine would be a third
   copy; prefer showing server numbers and twinning only validators.
7. **Single-process SQLite.** Rate limits (`ratelimit.py`) and the AI answer cache (`ai/cache.py`) are in process memory; SQLite is one
   writer. Fine for self-hosting; a hosted multi-tenant product needs another story ("one file per person" is a ROADMAP idea).
8. **Licence.** Code is PolyForm Noncommercial 1.0.0 (`LICENSE`, `pyproject.toml:5`), handbook text CC BY-NC-SA 4.0, Open Food Facts
   data ODbL (share-alike), USDA data CC0. Git shows one human author (61 commits `ksullivan86`, 4 `Claude`, 3 `dependabot`) and no CLA
   text found, so the owner can relicense or dual-license; a commercial general product cannot ship this code before that decision.
9. **Compatibility surface.** HKDF labels, cookie names and the export `format` string are on disk or in user files; renaming for a fork
   is fine, renaming in this product is a migration.

## Appendix: how this was checked (all read-only)

* Case-insensitive search for `ckd|kidney|dialysis|hypo|diabet|potassium|phosph|insulin|egfr|renal|t1d|type 1` in each `app/**/*.py`: 37 of 118
  files have none (auth core, audit, gtin, imagecheck, vision, symptoms, mcp measures/request_keys, `ai/cache|chat_preference|lab_report`,
  migration steps 6 and 9-17). The hits in the rest are mostly logger names and brand strings in platform code.
* `PYTHONDONTWRITEBYTECODE=1 DATA_DIR=<scratch> python3 -c "from app.main import app; app.openapi()"` for the operation, schema and
  response-code counts (no server started, nothing written to the repo).
* Read: `docs/ROADMAP.md`, `ARCHITECTURE.md` (purpose, v0.3 contract, identity, tokens, MCP, body, offline sections), `app/main.py`,
  `app/security.py`, `app/auth/{deps,api_tokens,errors}.py`, `app/nutrients.py`, `app/log.py` (386-565, 706-860), `app/body.py` header,
  module docstrings of `app/ai/*` and `app/guidance/*`, `tests/test_auth_coverage.py` (token walk at `:215-218`), note 12.

## 6. Decisions (2026-10-22, the owner's standing "recommended least-trust choice")

1. **Now, while other parts are built:** change 5 (renal and T1D rules out of `nutrients.py` behind a re-export, no behaviour change) and change 7 (the named safety set, `pytest -m safety`), because neither touches a file another branch is changing.
2. **Next, after device tokens (change 1) merge:** change 2 (a checked-in OpenAPI document with stable operation ids, honest 400s and security schemes), change 4 (`GET /api/meta`), then change 3 (`app/brand.py`, values unchanged). They touch `main.py`, `security.py` and `api_tokens.py`, which the device-token branch is changing.
3. **With the iOS design note:** change 6 (a Swift test target that replays the JSON vectors). Swift runs on Linux too, so the vector replay need not wait for macOS runners or an Apple account.
4. **Only when a second product starts:** changes 8 to 15. In particular the `RulePack` split is not built ahead of need. The safety protections stay on by default in every pack.
5. **The licence is the owner's decision** (risk 8). The code is PolyForm Noncommercial, so a commercial general product needs the owner to relicense or dual-license first. The owner is the only human author, so they can.
