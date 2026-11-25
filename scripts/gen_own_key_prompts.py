#!/usr/bin/env python3
"""Write app/ai/own_key_prompts.json: what the iPhone app sends the person's own AI key (design note 39 §6.5).

    python3 scripts/gen_own_key_prompts.py           # rewrite the file
    python3 scripts/gen_own_key_prompts.py --check   # exit 1 when the committed file is stale

The prompts and schemas are the server's own (app/ai/prompts.py, app/ai/schemas.py), so nothing is written twice. The file is
committed because scripts/build_preview.py --device packs it into the iPhone app with plain Python, without the app's
dependencies. tests/test_phone_own_key.py fails when it is stale.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "app" / "ai" / "own_key_prompts.json"
AI_PROMPT_PLACEHOLDER = "{text}"

# The tasks the person's own AI key may do from the iPhone app (owner, 2026-11-25; design note 39 §6.5): the bridge's task name ->
# (app/ai/prompts.py TASK_LINES key, app/ai/schemas.py schema builder, the schema's name in the request, a photo task). Never a lab
# report task: lab text and lab photos go only to a local model.
AI_OWN_KEY_TASKS = {
    "parse_meal": ("parse_meal", "parse_meal_schema", "kidney_parse_meal", False),
    "read_label": ("read_label", "read_label_schema", "nutrition_label", True),
    "plate": ("plate", "plate_schema", "plate_photo", True),
    # Meal ideas and AI recipes (note 39 §6.6): the candidate ids are per request, so the schema holds CANDIDATE_IDS where the
    # server puts its list of ids, and the app puts in the page's ids (whole numbers only). The system message is the meal ideas
    # or recipe rules (ai-prompts.json "systems"), with the person's condition from "conditions".
    "next_meal": ("ideas", "ideas_schema", "kidney_ideas", False),
    "recipes": ("recipes_suggest", "recipes_schema", "kidney_recipes", False),
}
CANDIDATE_IDS = "__CANDIDATE_IDS__"
SYSTEMS = {"next_meal": "meal", "recipes": "recipe"}


def schema_for(schemas, prompts, builder: str) -> dict:
    """The answer schema as the server builds it; for meal ideas and recipes with CANDIDATE_IDS in place of the id list."""
    if builder == "ideas_schema":
        schema = schemas.ideas_schema([-1], prompts.AI_HANDBOOK_SLUGS)
    elif builder == "recipes_schema":
        schema = schemas.recipes_schema([-1], steps=False)  # the phone never shows cooking steps from AI
    else:
        return getattr(schemas, builder)()

    def mark(node):
        if isinstance(node, dict):
            return {k: (CANDIDATE_IDS if k == "enum" and v == [-1] else mark(v)) for k, v in node.items()}
        if isinstance(node, list):
            return [mark(v) for v in node]
        return node

    marked = mark(schema)
    if json.dumps(marked).count(CANDIDATE_IDS) != 1:
        raise SystemExit(f"app/ai/schemas.py: {builder} must name the candidate ids once")
    return marked


def own_key_prompts() -> dict:
    """``own_key`` in ``ai-prompts.json``: what the iPhone app sends the person's own AI key, as the server's
    ``features.prepare_parse_meal``, ``prepare_read_label`` and ``prepare_plate`` build it. For each task: the answer's JSON schema
    and its name (sent as ``response_format`` to a provider that enforces it), and two user messages: ``json_schema`` for such a
    provider, ``prompt`` (with the schema line) for one that does not. A text task holds one ``{text}`` where the page's data JSON
    goes; a photo task has no data block (the photo is sent beside it)."""
    from app.ai import config, prompts, schemas

    tasks = {}
    for task, (key, builder, name, image) in AI_OWN_KEY_TASKS.items():
        schema = schema_for(schemas, prompts, builder)
        entry: dict = {"schema_name": name, "schema": schema, "image": image, "system": SYSTEMS.get(task, "task"),
                       "ids": task in SYSTEMS}
        for mode in ("json_schema", "prompt"):
            if image:
                entry[mode] = prompts.user_message(key, None, mode=mode, schema=schema)
                continue
            marker = {"marker": "x"}
            message = prompts.user_message(key, marker, mode=mode, schema=schema)
            block = prompts.data_block(marker)
            if not message.endswith("\n" + block) or AI_PROMPT_PLACEHOLDER in message:
                raise SystemExit(f"app/ai/prompts.py: the {key} message is not a task line and one data block")
            entry[mode] = message[: -len(block)] + "<data>\n" + AI_PROMPT_PLACEHOLDER + "\n</data>"
        tasks[task] = entry
    return {"prompt_version": prompts.PROMPT_VERSION, "system": prompts.TASK_SYSTEM_PROMPT, "max_tokens": config.DEFAULT_MAX_TOKENS,
            "tasks": tasks}


def render() -> str:
    return json.dumps(own_key_prompts(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="exit 1 when the committed file is stale")
    args = parser.parse_args()
    text = render()
    if args.check:
        if not OUT.exists() or OUT.read_text(encoding="utf-8") != text:
            print(f"{OUT.relative_to(ROOT)} is stale: run python3 scripts/gen_own_key_prompts.py", file=sys.stderr)
            return 1
        return 0
    OUT.write_text(text, encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
