"""AI order, AI swaps and AI day plans on the iPhone (the owner, 2026-11-26; design note 39 §6.6).

* tests/js/phone_ai_more2.mjs drives the page with a stand-in app: the modes rerank, swap and plan of POST /api/ai/next-meal on the
  iPhone's own model and on the person's own key, with the server's checks (twins pinned by tests/data/ai_meal_vectors.json); a
  low treatment is never sent; swaps and day plans never go to the paired server; AI order does, and its rows are found by name.
* The Swift side (read as text): the tasks, and the answer shapes are the server's schemas.
* The own key's prompts are the server's (app/ai/own_key_prompts.json, made by scripts/gen_own_key_prompts.py).
"""
from __future__ import annotations

import importlib.util
import json
import re
import shutil
import subprocess
from pathlib import Path

from app.ai import guard, prompts, schemas
from app.guidance import rules

ROOT = Path(__file__).resolve().parents[1]
SERVICES = ROOT / "ios" / "KidneyHealth" / "Services"
ON_DEVICE = (SERVICES / "OnDeviceAI.swift").read_text(encoding="utf-8")
OWN = (SERVICES / "OwnAI.swift").read_text(encoding="utf-8")
MOCK = (ROOT / "app" / "static" / "js" / "mock" / "ai.js").read_text(encoding="utf-8")
MODES = ("rerank", "swap", "plan")


def _code(text: str) -> str:
    return re.sub(r"//[^\n]*", "", text)


def test_the_page_with_a_stand_in_app() -> None:
    assert shutil.which("node"), "Node.js 22 is needed (CLAUDE.md, Parity)"
    done = subprocess.run(["node", str(ROOT / "tests" / "js" / "phone_ai_more2.mjs")], capture_output=True, text=True, timeout=300,
                          check=False)
    assert done.returncode == 0, done.stdout[-2000:] + done.stderr[-4000:]
    assert "checks passed" in done.stdout


def _fields(struct: str) -> list[str]:
    body = ON_DEVICE[ON_DEVICE.index(f"struct {struct} {{"):]
    body = body[: body.index("\n}\n")]
    return [f for f in re.findall(r"^    var (\w+): ", body, flags=re.M) if f != "json"]


def _keys(struct: str) -> list[str]:
    """The keys of the JSON the reply hands the page."""
    body = ON_DEVICE[ON_DEVICE.index(f"struct {struct} {{"):]
    body = body[: body.index("\n}\n")]
    return re.findall(r'"(\w+)": ', body[body.index("var json"):])


def test_the_iphone_answer_shapes_are_the_servers_schemas() -> None:
    """Each @Generable reply has the fields of the server's wire schema, in its order, and hands the page those keys."""
    for struct, schema, key in (("RerankReply", schemas.rerank_schema(["f1"]), "order"), ("SwapReply", schemas.swap_schema(["s1"]), "pick"),
                                ("PlanReply", schemas.plan_schema(["lunch"], 4), "picks")):
        assert _fields(struct) == list(schema["properties"]), struct
        assert _keys(struct) == list(schema["properties"]), struct
        entry = schema["properties"][key]["items"]["properties"]
        inner = "PlanPick" if struct == "PlanReply" else "RefPick"
        assert _fields(inner) == list(entry) and _keys(inner) == list(entry), inner
    # the counts the server's schemas allow, and the reasons from its list
    assert '.maximumCount(12)' in ON_DEVICE and schemas.MAX_RERANK == 12
    assert '.maximumCount(3))\n    var pick' in ON_DEVICE and schemas.MAX_SWAP_PICKS == 3
    assert '.maximumCount(4))\n    var picks' in ON_DEVICE and len(schemas.MEAL_SLOTS) == 4
    assert f".range(0...{rules.AI_PLAN_OPTIONS_MAX - 1})" in ON_DEVICE
    assert ON_DEVICE.count(".count(1...3)") == 2  # one to three reason codes (schemas._reasons)
    assert "case breakfast, lunch, dinner, snack" in ON_DEVICE and tuple(schemas.MEAL_SLOTS) == ("breakfast", "lunch", "dinner", "snack")
    for mode, struct in (("rerank", "RerankReply"), ("swap", "SwapReply"), ("plan", "PlanReply")):
        assert f'case "{mode}":\n                    let reply = try await session.respond(to: message, generating: {struct}.self)' in ON_DEVICE
    assert 'static let conditionTasks: Set<String> = ["next_meal", "recipes", "rerank", "swap", "plan"]' in ON_DEVICE
    code = _code(ON_DEVICE).lower()
    for word in ("insulin", "dose", "dosing", "bolus", "urlsession", "userdefaults"):
        assert word not in code, word  # never a dosing task; nothing leaves the phone or is kept


def test_the_own_key_takes_the_three_tasks_with_the_condition_and_no_ids() -> None:
    assert 'static let conditionTasks: Set<String> = ["next_meal", "recipes", "rerank", "swap", "plan"]' in OWN
    assert 'static let candidateTasks: Set<String> = ["next_meal", "recipes"]' in OWN
    code = _code(OWN)
    assert 'guard condition != nil, request["ids"] == nil else { return Self.problem("bad_request") }' in code
    assert 'guard entry["ids"] as? Bool == false, ids == nil, let condition,' in code


def test_the_own_key_prompts_are_the_servers() -> None:
    own = json.loads((ROOT / "app" / "ai" / "own_key_prompts.json").read_text(encoding="utf-8"))
    data = {"candidates": [], "meal": "lunch", "swaps": [{"ref": "s1"}]}
    payload = prompts.data_block(data)[len("<data>\n"):-len("\n</data>")]
    expected = {"rerank": schemas.rerank_schema([]), "swap": schemas.swap_schema([]),
                "plan": schemas.plan_schema(schemas.MEAL_SLOTS, rules.AI_PLAN_OPTIONS_MAX - 1)}
    for mode in MODES:
        t = own["tasks"][mode]
        assert (t["schema_name"], t["system"], t["ids"], t["image"]) == (f"kidney_{mode}", "meal", False, False), mode
        assert t["schema"] == expected[mode] and "__CANDIDATE_IDS__" not in json.dumps(t)
        for style in ("json_schema", "prompt"):
            assert t[style].replace("{text}", payload) == prompts.user_message(mode, data, mode=style, schema=expected[mode]), (mode, style)


def test_the_iphone_prompts_are_the_servers(tmp_path) -> None:
    spec = importlib.util.spec_from_file_location("build_preview", ROOT / "scripts" / "build_preview.py")
    builder = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(builder)
    for mode in MODES:
        assert builder.AI_DEVICE_TASKS[mode] == (mode, "meal", False)
    builder.build_device(tmp_path)
    doc = json.loads((tmp_path / "ai-prompts.json").read_text(encoding="utf-8"))
    person = {"ckd_stage": "3b", "dialysis": "none", "diabetes": "type2"}
    assert doc["systems"]["meal"].replace("[[CONDITION]]", prompts.condition_text(person)) == prompts.system_prompt(person)
    data = {"plan": {"lunch": []}}
    payload = prompts.data_block(data)[len("<data>\n"):-len("\n</data>")]
    for mode in MODES:
        assert doc["tasks"][mode]["template"].replace("{text}", payload) == prompts.user_message(mode, data, mode="json_schema", schema={})


def test_swaps_and_day_plans_stay_on_the_phone_and_a_low_is_never_sent() -> None:
    assert "const PHONE_ONLY_MODES = ['swap', 'plan'];" in MOCK
    assert "PHONE_ONLY_MODES.includes(b.mode) ? Promise.resolve({ skip: 'phone_only' })" in MOCK
    assert "if (purpose === 'hypo' || food.hypo) {" in MOCK  # before anything is built or asked
    assert MOCK.index("if (purpose === 'hypo' || food.hypo) {") < MOCK.index("const got = await onPhone(api, 'meal_ideas', task, build, dry);")


def test_the_servers_ai_order_rows_name_their_food() -> None:
    """The phone finds the server's AI order in its own list by name (its ids differ): each row carries the food's name. The
    vectors (tests/data/ai_meal_vectors.json, MJUDGE rerank) pin the whole answer."""
    vectors = json.loads((ROOT / "tests" / "data" / "ai_meal_vectors.json").read_text(encoding="utf-8"))
    case = next(c for c in vectors["cases"] if c["id"].startswith("MJUDGE rerank: good"))
    rows = case["output"]["order"] + case["output"]["rest"]
    assert rows and all(isinstance(r["name"], str) and r["name"] for r in rows)
    assert guard.judge_rerank({"status": "refused", "refusal": "outside_scope", "order": []}, None, "lunch", {}, provider_label="x",
                              model="y")["status"] == "refused"


def test_ai_order_rows_carry_the_full_stored_name() -> None:
    """Audit, 2026-11-26: the bridge's names are cut to 60 characters for the model, so a long name would not match on the phone
    and its food would lose its rank. The rows carry the stored name, on the server and in the JS twin alike."""
    import inspect

    src = inspect.getsource(guard.judge_rerank)
    assert src.count("ctx.foods[int(f[\"food_id\"])].name") == 2 and '"name": f["name"]' not in src
    twin = (ROOT / "app" / "static" / "js" / "engine" / "aimeal.js").read_text(encoding="utf-8")
    body = twin[twin.index("function judgeRerank("):twin.index("return { status: 'ok', ...label(providerLabel, model), order, rest")]
    assert body.count("ctx.foods.get(Number(f.food_id)).name") == 2 and "name: f.name" not in body
