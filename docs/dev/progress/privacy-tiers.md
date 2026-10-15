Status: complete (tier 1 only: roles, per-feature routing, admin table, per-person lines, tests and docs; merged with origin/claude/adoring-sagan-th5swr (trust, menu links, voice); full suite green; `tools/e2e/ask.py`, `ask_voice.py` and `device.py --only ai` pass in Chromium)

# Privacy tiers, tier 1: provider roles and per-feature routing

ROADMAP "Privacy tiers: use the local GPU to keep details away from cloud AI", tier (1) only. Tiers (2) to (4)
(redaction before the cloud, local first with a cloud fallback, a stronger local model) are not started. Worktree branch
`worktree-agent-a84b504fad2798262`, based on `1c49eff`.

## Design (from the owner's brief; least trust)

* Two **roles** for shared providers: `local` (the host must be private by `app/ai/netpolicy.py` `is_private_host`: an IP
  literal inside `AI_PRIVATE_HOSTS`, or a name listed there by name and port; no DNS) and `cloud`. Stored as the instance
  settings `ai.route.local_provider` / `ai.route.cloud_provider` (a shared provider id, 0 = none; ids are never reused:
  `ai_providers.id` is `AUTOINCREMENT`). The environment provider takes a role from `AI_PROVIDER_ROLE`.
* Four **features**: `photos`, `meal_ideas`, `describe`, `chat`; settings `ai.route.<feature>` =
  `local | cloud | off | any`, default `local` (so off with no local AI). `any` = the rule from before routing.
* **No schema change.** The brief reserved step 15 for a migration, but the voice step (14) is not in this tree and
  `app/migrations` refuses a gap in the numbering, so the upgrade decision is made at start-up instead
  (`app/ai/routing.py` `initialise`, called from `app/ai/routes.py` `startup` before the environment provider is synced) and
  recorded in `meta.ai_routing_initialised`: a database that already has a shared provider starts every feature on `any`
  (nothing changes until an admin chooses); a database with none starts on the least-trust defaults.
* `local` is enforced twice: the role needs a private host when it is set, when the provider's address is edited and
  before each call, and calls use the network scope `local` (`ProviderConfig.local_only` -> `netpolicy` scope `local`):
  every resolved address must be private. Connection tests of the local provider use the same scope.
* **Voice** (the Ask microphone, merged from the voice change) is not a fifth feature: its recording goes to `STT_BASE_URL`,
  `voice_config` is `None` (404) while the chat route is `off`, `voice.transcribe` resolves the `chat` feature, and the
  `voice` consent row (host = the transcription host) stays keyed to the provider the chat route resolves to (moving Ask to
  another provider asks about voice again). `POST /api/ai/consent` with purpose `voice` has its own branch in `routes.py`.
* `off` is off for everyone, including people with their own provider; otherwise a person's own provider is their
  choice, counts as `cloud` (people can only point at public hosts) and is never replaced. Ask `off` answers 404 (like
  `ai.chat_enabled` off); the other features answer `503 feature_off`.

## Done (and how it was checked)

* Registry keys, JS twin (`engine/settings.js`), vectors: `python tests/data/gen_settings_vectors.py --check`,
  `node tests/js/run_vectors.mjs`.
* `netpolicy` (`is_private_host`, scope `local`), `client` (`local_only`), `routing.py` (roles, `resolve_feature`,
  status/me views, `initialise`, admin overview/plan/apply, `pin_if_local`), `routes.py` (every feature resolves through
  routing; consent per resolved provider; status `routes`; `GET/PUT /api/admin/ai-routing`; provider edit/delete guards;
  probes), `app/vision.py` (photos), `AI_PROVIDER_ROLE` in `app/config.py` with a start-up check in `config.check_env`.
* UI: `js/views/ai_routing.js` (admin table with the cloud warning; per-person lines), small hunks in `ai.js`
  (`withConsent` takes a feature, provider choice once routed, API methods, consent/dry-run wording) and `settings.js`
  (the six keys in one group with a pointer), `css/ai.css`, `sw.js`, `index.html`, the demo mock (`routing: null`).
* Deploy: `AI_PROVIDER_ROLE` and `AI_ROUTE_*` pass-through in `deploy/compose.yaml` and `.env.example`; the Ollama overlay sets
  `AI_PROVIDER_ROLE: local`; the e2e tools' fake AI is declared local.
* Docs: `docs/ai.md` (new section "Which AI does each feature use?"), `ARCHITECTURE.md`, `docs/privacy.md`,
  `docs/deployment.md`, `docs/security.md`, handbook `app/ai.md` and `self-hosting/configuration.md`, `CHANGELOG.md`,
  `docs/ROADMAP.md`.
* Tests: `tests/test_ai_routing.py`, `tests/test_ai_routing_ui.py`, `tests/js/routing_page.mjs`; the older AI tests set
  routing to `any` through `tests/ai_support.py` `LEGACY_ROUTING` (and `scripts/ai_eval.py` does the same);
  `tests/test_auth_coverage.py` lists the two new routes.

Reproduce: `python -m pytest tests/test_ai_routing.py tests/test_ai_routing_ui.py -q`; everything:
`python -m pytest -q -x -p no:cacheprovider` (4003 checks passed) and `node tests/js/run_vectors.mjs`.

## Not done / for the owner

* `tools/e2e/journey.py` (needs a built handbook) was not run; `ask.py` (108 checks), `ask_voice.py` (82) and `device.py --only ai`
  (24) pass in Chromium here.
* A live run on a real Ollama plus a cloud key (the owner's).
