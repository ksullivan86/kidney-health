Status: in progress

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
* Tests so far: `tests/test_ai_cloud_env.py` (84), `tests/test_migration_m020.py`.

## Next

1. `tests/test_ai_cloud_routing.py`: both providers routed, labs never reach the cloud, proxy and deny rules.
2. `scripts/ai_eval.py --role/--upstream` and `tests/test_ai_eval_script.py`.
3. Deploy files (`compose.yaml`, `.env.example`, quadlet, k8s) and `tests/test_compose_env.py`.
4. Docs: `docs/ai.md`, `docs/deployment.md`, handbook configuration page, `ARCHITECTURE.md`, `CHANGELOG.md`, ai-eval README.
5. Full checks (see below).

## Checks

    python -m pytest -q              (run in the background)
    python -m pytest -m safety -q
    node tests/js/run_vectors.mjs
    ruff check .
    python scripts/gen_openapi.py --check
    for g in tests/data/gen_*.py; do python $g --check; done
    python scripts/build_handbook.py --check
    git diff --check
