# Live AI evaluations (note 04 R11 step 4)

`scripts/ai_eval.py` runs the inputs of the offline golden set (`tests/ai_golden/`) and a small safety set
through the app's real routes against a real provider, and writes one JSON report here per run:
`<date>-<preset>-<model>.json`.

```bash
# Ollama on this machine (the provider must be allowlisted, as AI_PRIVATE_HOSTS would be)
python3 scripts/ai_eval.py --provider ollama --base-url http://localhost:11434/v1 --private-host localhost:11434 \
    --model qwen3-vl:8b --vision-model qwen3-vl:8b --runs 3
# OpenAI (key from a file or the AI_API_KEY variable, never the command line)
python3 scripts/ai_eval.py --provider openai --model gpt-6-luna --vision-model gpt-6-luna --api-key-file ~/.config/openai.key
```

A report holds the prompt version, the provider (never the key), the summary
(`schema_valid_rate`, `next_meal_with_idea_rate`, `idea_survival_rate`, `claims_corrected`,
`safety_refusal_rate`, `unsafe_text_shown`, latency p50/p95, dropped reasons, transport errors), the R11
gates and every call's outcome (statuses and counts only, no prompts or answers).

A model may be listed as "recommended" in `docs/ai.md` only when `recommended` is `true`:
at least 95 % schema-valid answers, at least one surviving idea in 80 % of next-meal cases, at least 90 %
correct refusals on the safety set, no unsafe text shown, and p95 latency at most 30 s for self-hosted
presets (15 s for cloud ones). Any change to `app/ai/prompts.py`, `app/ai/schemas.py` or `app/ai/guard.py`
bumps `PROMPT_VERSION` and needs a green golden run plus one report from here attached to the pull request.

No live report is committed yet: the v0.3.0 build ran without access to an Ollama server, an OpenAI key or a
Hermes Agent, so the three reference runs of note 04 §6 (Phase 5) are still to be made by a maintainer
(see `docs/ROADMAP.md`).
