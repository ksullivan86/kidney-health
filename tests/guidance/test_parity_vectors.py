"""Demo-mode parity vectors for meal guidance (ARCHITECTURE "Frontend modules", parity rule):
``tests/data/guidance_vectors.json`` must be what the engine produces now, and every case must replay
from its plain-JSON input alone (what the JavaScript twin will do)."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from app.guidance import rules as R

ROOT = Path(__file__).resolve().parents[2]
VECTORS = ROOT / "tests" / "data" / "guidance_vectors.json"


def _generator():
    spec = importlib.util.spec_from_file_location("gen_guidance_vectors", ROOT / "tests" / "data" / "gen_guidance_vectors.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


GEN = _generator()


def test_guidance_vectors_are_current():
    committed = json.loads(VECTORS.read_text(encoding="utf-8"))
    assert committed == json.loads(GEN.dumps(GEN.build())), (
        "tests/data/guidance_vectors.json is stale: app/guidance changed. Run `python3 tests/data/gen_guidance_vectors.py`, "
        "then update app/static/js/engine/guidance.js until `node tests/js/run_vectors.mjs` agrees.")


def test_every_case_replays_from_its_plain_json_input():
    doc = json.loads(VECTORS.read_text(encoding="utf-8"))
    assert doc["format"] == 1 and doc["rules_version"] == R.RULES_VERSION and doc["rules_hash"] == R.rules_hash()
    foods = GEN.food_map(doc["foods"])
    for case in doc["cases"]:
        got = json.loads(json.dumps(GEN.call(case["input"], case["call"], foods), sort_keys=True))
        assert got == case["output"], case["id"]


def test_vectors_cover_every_engine_function_and_the_note_06_cases():
    doc = json.loads(VECTORS.read_text(encoding="utf-8"))
    fns = {c["call"]["fn"] for c in doc["cases"]}
    assert fns == {"meal_room", "what_fits", "find_swaps", "hypo_options", "plan_day", "day_insights", "period_insights",
                   "prefilter"}
    ids = {c["id"].split(" ")[0] for c in doc["cases"]}
    for vector in ("TV-B4", "TV-B5", "TV-B6", "TV-B7", "TV-F8", "TV-S1", "TV-S2", "TV-S3", "TV-S4", "TV-S5", "TV-S6",
                   "TV-P1", "TV-P2", "TV-P6", "TV-P7", "TV-I1", "TV-I2", "TV-I3", "TV-I5"):
        assert vector in ids, vector
    # Plain JSON: no NaN or Infinity anywhere, inputs carry their snapshots.
    text = VECTORS.read_text(encoding="utf-8")
    assert "NaN" not in text and "Infinity" not in text
    tp1 = next(c for c in doc["cases"] if c["id"].startswith("TV-P1"))
    assert [(i["food_id"], i["servings"]) for i in tp1["output"]["meals"][0]["items"]] == [(4, 1.0), (1, 1.0), (7, 1.25)]


def test_check_mode_reports_a_stale_file(tmp_path, monkeypatch, capsys):
    stale = tmp_path / "guidance_vectors.json"
    stale.write_text('{"format": 0}', encoding="utf-8")
    monkeypatch.setattr(GEN, "OUT", stale)
    monkeypatch.setattr(GEN, "ROOT", tmp_path)
    assert GEN.main(["--check"]) == 1
    assert "is stale" in capsys.readouterr().err
