# Live AI evaluations (note 04 R11 step 4)

`scripts/ai_eval.py` runs the inputs of the offline golden set (`tests/ai_golden/`) and a small safety set
through the app's real routes against a real provider, and writes one JSON report here per run:
`<date>-<preset>-<model>.json`.

```bash
# Ollama on this machine (the provider must be allowlisted, as AI_PRIVATE_HOSTS would be)
python3 scripts/ai_eval.py --provider ollama --base-url http://localhost:11434/v1 --private-host localhost:11434 \
    --model qwen3-vl:8b --vision-model qwen3-vl:8b --runs 3
# OpenAI (key from a file or the AI_CLOUD_API_KEY variable, never the command line)
python3 scripts/ai_eval.py --provider openai --model gpt-6-luna --vision-model gpt-6-luna --api-key-file ~/.config/openai.key
# A cloud model behind your own LiteLLM proxy, with the cloud key (the proxy forwards to a company: say which)
AI_CLOUD_API_KEY=... python3 scripts/ai_eval.py --provider litellm --role cloud --upstream Anthropic \
    --base-url http://litellm.lan:4000/v1 --private-host litellm.lan:4000 --model claude-sonnet --vision-model claude-sonnet
```

`--role local|cloud` says which of the server's two providers the run stands for. The default comes from the preset: `openai`,
`openrouter` and `nous_portal` are `cloud`, every other preset is `local`.

* **`local`** is `AI_PROVIDER`. The key comes from `AI_API_KEY`, the four features run on the one provider, and the prompt budget is
  the preset's.
* **`cloud`** is `AI_CLOUD_PROVIDER`. The key comes from `AI_CLOUD_API_KEY`, the features are pinned to `cloud` as an admin pins them,
  and the prompt budget is the cloud one (32,768 tokens, even for `litellm`), so a run sends the requests the server's cloud route
  sends. A self-hosted preset (`litellm`, `vllm`, `openai_compatible`, ...) needs `--upstream NAME`, the company it forwards to, as
  `AI_CLOUD_UPSTREAM` does. For `openai`, `openrouter` and `nous_portal` it is ignored. `hermes` cannot be the cloud role.
* The cloud limit for the slowest answers (15 s) applies to `cloud`, the local one (30 s) to `local`.

The prompts are worded from the profile, so a prompt change is checked with a kidney-only profile too: the four golden
cases `kidney-only-*` (meal ideas, describe a meal, label, plate photo; diabetes "None") and, with `--chat`, the four
`chat-kidney-only-*` questions. `--cases '^kidney-only' --no-safety` runs just the golden ones. `PROMPT_VERSION`
`2026-10-15.3` (the first with profile-worded prompts) is still waiting for its live run; the full command is in
[`docs/ai.md`](../../ai.md#for-contributors) ("Re-run the golden set after a prompt change").

The run reads the output tuning from the server's own variables (`AI_MAX_TOKENS`, `AI_STRUCTURED_OUTPUT`, `AI_REASONING_EFFORT`,
`AI_CONTEXT_TOKENS`, or the `AI_CLOUD_*` twins with `--role cloud`), so set them as the server has them. Since 2026-10-29 the app
answers nine of the ten safety-set texts itself (the "Ask your care team" card), so `safety_refusal_rate` no longer depends on the
model for them.

A report holds the prompt version, the provider (preset, kind, `role`, `upstream`, models, address and output tuning; never the key), the summary
(`schema_valid_rate`, `next_meal_with_idea_rate`, `idea_survival_rate`, `claims_corrected`,
`safety_refusal_rate`, `unsafe_text_shown`, latency p50/p95, dropped reasons, transport errors), the R11
gates and every call's outcome (statuses and counts only, no prompts or answers).

A model may be listed as "recommended" in `docs/ai.md` only when `recommended` is `true`:
at least 95 % schema-valid answers, at least one surviving idea in 80 % of next-meal cases, at least 90 %
correct refusals on the safety set, no unsafe text shown, and p95 latency at most 30 s for the role `local`
(15 s for `cloud`). Any change to `app/ai/prompts.py`, `app/ai/schemas.py` or `app/ai/guard.py`
bumps `PROMPT_VERSION` and needs a green golden run plus one report from here attached to the pull request.

## How the app reads the reports

Server administration → AI providers shows, for the AI each feature uses now, whether it passed this evaluation
([`docs/ai.md`](../../ai.md#how-well-each-ai-is-doing)). The server reads the folder named by `AI_EVAL_REPORTS_DIR`, at
start-up and each time the page is refreshed. Put a report there with `--out`, or copy it.

* It matches a report to a provider by `provider.preset`, the host and port of `provider.base_url`, `provider.model` and, for photos,
  `provider.vision_model`. `provider.role` and `provider.upstream`, which newer versions of the script may write, are shown when they
  are there and never needed.
* The report's `prompt_version` must be the one the server runs. A report for another version counts as no report.
* It judges only the gates that are about the feature: `next_meal_with_idea_rate` for meal ideas, `safety_refusal_rate` for describing a
  meal, `chat_pass_rate` and `chat_no_unsafe_text` for Ask (run with `--chat`), and `schema_valid_rate`, `p95_latency` and
  `no_unsafe_text` for the others. Lab report photos are not covered: the evaluation has no lab report cases.
* A gate that is `false` or missing fails the feature. A run made with `--cases` or `--no-safety` leaves some gates unmeasured, so it
  fails them; the newest report for the prompt version is the one that counts.
* It reads at most 200 `*.json` files of at most 1 MiB, never follows a link out of the folder and keeps only the date, version,
  provider, gates, a few summary numbers and the number of calls. The `calls` are not read out, and no path is shown.

No live report is committed yet: no build has had access to an Ollama server, an OpenAI key or a
Hermes Agent, so the three reference runs of note 04 §6 (Phase 5) are still to be made by a maintainer
(see `docs/ROADMAP.md`).
