Status: complete

# cloud-env: a second AI provider from the environment (`AI_CLOUD_*`)

Worktree `.../scratchpad/integ-cloudenv`, branch `wip/cloud-env`, based on main 56869a4 (v0.5.0). Local commits only: no push, no tag.

## What it adds

* `AI_CLOUD_PROVIDER` and its siblings: a second locked shared provider, role always `cloud`.
* Schema step 20 (`m020_ai_env_slots.py`): `ai_providers.env_slot` (`main` or `cloud`) and `ai_providers.upstream`.
* An honest consent line when the cloud provider is a proxy (`AI_CLOUD_UPSTREAM`).
* Cloud prompt budget default (32,768) for the cloud slot.
* `scripts/ai_eval.py --role local|cloud`, `--upstream`.
* Tests, docs, deploy files.

## Decisions

* Two env rows are told apart by a new column `env_slot`, not by `locked` (a 0/1 check plus a one-row unique index). Step 20
  drops the old one-row index and adds one row per slot. Existing locked rows become `main`.
* `upstream` is stored on the row so the provider list, the consent sheet and the start-up sync all read one place.
* `POLICY_VERSION` is not changed: no existing line changes. The proxy line is a new line built from the upstream name.
* The demo (`js/mock/ai.js`) has no admin AI routes (AI is switched off in the demo), so there is no mock to change. The
  routing screen's Node harness (`tests/js/routing_page.mjs`) stands in for it.

## Done

* `app/config.py`: `AiCloudEnv`, `load_ai_cloud_env`, secret redaction. Verified by `tests/test_ai_cloud_env.py`.
* `app/migrations/m020_ai_env_slots.py` (`env_slot`, `upstream`, one locked row per slot). Verified by `tests/test_migration_m020.py`.
* `app/ai/presets.py` proxy line (`PROXY_POLICY`), `app/ai/config.py` (`check_env`, two-slot `sync_env_provider`, `env_row`,
  `env_key`, `row_policy`, `upstream` on the config), `app/ai/routing.py` (roles), `app/ai/routes.py` (messages, key fingerprint).
* Screens: `js/views/ai_routing.js` (cloud role fixed, names `AI_CLOUD_PROVIDER`), `js/views/ai.js` (variable in the badge title,
  the policy line of a proxy). Harness `tests/js/routing_page.mjs` + `tests/test_ai_routing_ui.py`.
* Tests: `tests/test_ai_cloud_env.py`, `tests/test_migration_m020.py`, `tests/test_ai_cloud_routing.py` (routing with both env
  providers, labs never reach the cloud provider, deny/proxy rules, local_then_cloud).
* `scripts/ai_eval.py --role/--upstream`, `Options.resolved_role/problem()`, report `provider.role/upstream`; tests in
  `tests/test_ai_eval_script.py`; `docs/dev/ai-eval/README.md`.
* Mutation checks run by hand (put back): `role_row` ignoring the cloud slot, `env_key` always the first key. Both are caught.

## Also done

* Deploy files: `compose.yaml` (pass-throughs for the five non-secret `AI_CLOUD_*`, commented `AI_CLOUD_API_KEY_FILE` secret),
  `.env.example`, Quadlet (a full commented example), Kubernetes (`deployment.yaml`, `secret.example.yaml`, `networkpolicy.yaml`).
  `tests/test_compose_env.py` pins them; `tests/test_ai_cloud_env.py` runs the docs recipe and the Quadlet example through
  `load_settings`, `check_env` and a started app.
* Docs: `docs/ai.md` (three questions, env table, what is sent, routing, recipe, troubleshooting, contributors),
  `docs/deployment.md`, `docs/privacy.md`, `docs/network-allowlist.md`, handbook `self-hosting/configuration.md`,
  `self-hosting/network-allowlist.md`, `app/ai.md`, `ARCHITECTURE.md` (env part, "Environment providers: main and cloud",
  routes, migration table, ownership), `CHANGELOG.md` (`## Unreleased`).
* Checks run: ruff, gen_openapi --check (no change: the admin answers are free dicts), all `tests/data/gen_*.py --check`,
  `node tests/js/run_vectors.mjs`, `build_handbook.py --check`, `git diff --check`: all clean.

## Final checks (all green)

* Full `python -m pytest -q`, run in three parts on a snapshot: 0 failures (one test needs `.git`, and passes in the worktree).
* `python -m pytest -m safety -q`, ruff, `gen_openapi.py --check`, every `tests/data/gen_*.py --check`, `node tests/js/run_vectors.mjs`,
  `build_handbook.py --check`, `git diff --check`.
* Browser: new `tools/e2e/cloud_env.py` (43 checks) and the existing `tools/e2e/fallback.py` (64 checks) pass offline.

## Checks

    python -m pytest -q              (run in the background)
    python -m pytest -m safety -q
    node tests/js/run_vectors.mjs
    ruff check .
    python scripts/gen_openapi.py --check
    for g in tests/data/gen_*.py; do python $g --check; done
    python scripts/build_handbook.py --check
    git diff --check
