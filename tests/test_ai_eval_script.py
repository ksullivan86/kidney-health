"""``scripts/ai_eval.py`` (note 04 R11 step 4), run offline: the live runner is driven through the real
routes against a scripted fake model, so the manual tool keeps working between live evaluations. The
fake model answers what each task asks (ideas from the first candidate, a refusal for every safety-set
text); nothing reaches the network."""
from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any

import pytest

from ai_support import FakeProvider, chat

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("ai_eval", ROOT / "scripts" / "ai_eval.py")
ai_eval = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules["ai_eval"] = ai_eval  # dataclasses look their module up while the class is created
spec.loader.exec_module(ai_eval)

KEY = "sk-eval-0123456789abcdefghijklmn"
LABEL = {"status": "ok", "product_name": "Crackers", "serving_text": "5 crackers (30 g)", "serving_g": 30, "basis": "per_serving",
         "per_serving": {k: None for k in ("calories_kcal", "protein_g", "fat_g", "sat_fat_g", "carbs_g", "fiber_g", "sugar_g",
                                           "sodium_mg", "potassium_mg", "phosphorus_mg", "calcium_mg")},
         "salt_g": None, "percent_dv": {"sodium": None, "potassium": None, "phosphorus": None, "calcium": None},
         "ingredients_text": None, "label_style": "us_nutrition_facts"}


def scripted_model(request: Any) -> Any:
    body = json.loads(request.content)
    content = body["messages"][1]["content"]
    text = content if isinstance(content, str) else content[0]["text"]
    data = json.loads(text.split("<data>\n", 1)[1].split("\n</data>", 1)[0]) if "<data>" in text else {}
    if text.startswith("TASK: next_meal"):
        first = data["candidates"][0]
        return chat({"status": "ok", "refusal": "none", "ideas": [
            {"theme": "light", "items": [{"food_id": first["id"], "quarters": first["portion_quarters"]}],
             "reason_codes": ["low_potassium"], "handbook": []}]})
    if text.startswith("TASK: rerank"):
        return chat({"status": "ok", "refusal": "none", "order": [{"ref": data["candidates"][0]["ref"], "reason_codes": ["low_sodium"]}]})
    if text.startswith("TASK: swap"):
        return chat({"status": "ok", "refusal": "none", "pick": [{"ref": s["ref"], "reason_codes": ["low_potassium"]} for s in data["swaps"][:1]]})
    if text.startswith("TASK: plan"):
        return chat({"status": "ok", "refusal": "none", "picks": []})
    if text.startswith("TASK: parse_meal"):
        if re.search(r"insulin|dose|binder|bolus|basal|lab|supplement|diagnose|unlimited", data["text"], re.I):
            return chat({"status": "refused", "items": []})
        return chat({"status": "ok", "items": [{"text": "toast", "search": "bread", "amount": 1, "unit": "slice"}]})
    if text.startswith("TASK: read_label"):
        return chat(LABEL)
    if text.startswith("TASK: identify_food"):
        return chat({"status": "ok", "items": [{"name": "apple", "search": "apple", "grams_estimate": 90, "confidence": "high"}]})
    raise AssertionError(text[:80])


def run(tmp_path: Path, **extra: Any) -> dict[str, Any]:
    provider = FakeProvider(route=scripted_model)
    options = ai_eval.Options(preset="openai", model="gpt-6-luna", vision_model="gpt-6-luna", api_key=KEY,
                              cases=r"^(baseline-good-idea|mode-rerank|vision-plate|vision-not-a-label|prefilter-low-1)$", **extra)
    return ai_eval.run_eval(options, transport_factory=provider.factory, data_dir=tmp_path, log=lambda line: None)


def test_the_live_runner_measures_the_golden_inputs_and_the_safety_set(tmp_path):
    rep = run(tmp_path)
    s = rep["summary"]
    assert rep["prompt_version"] and rep["provider"] == {"preset": "openai", "kind": "cloud", "model": "gpt-6-luna",
                                                         "vision_model": "gpt-6-luna", "base_url": "https://api.openai.com/v1"}
    assert s["safety_cases"] == len(ai_eval.SAFETY_SET) and s["safety_refusal_rate"] == 1.0 and s["unsafe_text_shown"] == 0
    assert s["schema_valid_rate"] == 1.0 and s["next_meal_cases"] == 1 and s["next_meal_with_idea_rate"] == 1.0
    assert s["latency_ms"]["p95"] is not None and rep["p95_limit_ms"] == 15_000
    assert rep["gates"] == {"schema_valid_rate": True, "next_meal_with_idea_rate": True, "safety_refusal_rate": True,
                            "p95_latency": True, "no_unsafe_text": True}
    assert rep["recommended"] is True
    prefilter = next(c for c in rep["calls"] if c["case"] == "prefilter-low-1")
    assert prefilter["ai_called"] is False  # answered by the app's card, never sent
    assert KEY not in json.dumps(rep)


def test_failing_gates_are_reported(tmp_path):
    def bad_model(request: Any) -> Any:
        return chat("not json at all")

    provider = FakeProvider(route=bad_model)
    options = ai_eval.Options(preset="ollama", model="tiny", api_key=None, private_hosts=("ollama:11434",), cases=r"^baseline-good-idea$")
    provider.address = "10.89.0.5"
    rep = ai_eval.run_eval(options, transport_factory=provider.factory, data_dir=tmp_path, log=lambda line: None)
    assert rep["summary"]["schema_valid_rate"] == 0.0 and rep["gates"]["schema_valid_rate"] is False
    assert rep["p95_limit_ms"] == 30_000 and rep["recommended"] is False


def test_main_writes_the_report_without_the_key(tmp_path, monkeypatch, capsys):
    key_file = tmp_path / "key"
    key_file.write_text(KEY + "\n")
    seen: dict[str, Any] = {}

    def fake_run(options: Any) -> dict[str, Any]:
        seen["key"] = options.api_key
        return ai_eval.report(options, [])

    monkeypatch.setattr(ai_eval, "run_eval", fake_run)
    out = tmp_path / "report.json"
    code = ai_eval.main(["--provider", "openai", "--model", "gpt-6-luna", "--api-key-file", str(key_file), "--runs", "1",
                         "--out", str(out)])
    assert code == 1 and seen["key"] == KEY  # no calls: the gates cannot pass
    data = json.loads(out.read_text())
    assert KEY not in out.read_text() and data["recommended"] is False and "report:" in capsys.readouterr().out
    assert ai_eval.output_path(data).name.endswith("-openai-gpt-6-luna.json")


def test_runs_must_be_positive():
    with pytest.raises(SystemExit):
        ai_eval.main(["--provider", "openai", "--model", "m", "--runs", "0"])
