"""The iPhone's own AI in device mode (design note 38 §5.6): the browser twins of the server's AI checks, and ai-prompts.json.

* tests/data/ai_device_vectors.json is generated from app/ai (features, guard, chat, prompts, lab_report) by
  tests/data/gen_ai_device_vectors.py and replayed against js/engine/aijudge.js and lab_report.js by ``node tests/js/run_vectors.mjs``.
  These tests fail when the committed file no longer matches the Python side, or a twin's pattern is not the server's.
* ``scripts/build_preview.py --device`` writes ``ai-prompts.json``, which the iPhone app gives its model. It must be the server's
  prompt: filling a template with the data the page sends must give exactly the message ``prompts.user_message`` builds.
"""
from __future__ import annotations

import importlib.util
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from app.ai import chat, features, guard, lab_report, prompts, schemas

pytestmark = pytest.mark.safety

ROOT = Path(__file__).resolve().parents[1]
VECTORS = ROOT / "tests" / "data" / "ai_device_vectors.json"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _twin_sources() -> dict:
    assert shutil.which("node"), "Node.js 22 is needed to run the browser twins (CLAUDE.md, Parity)"
    loader = (ROOT / "tests" / "js" / "demo_loader.mjs").as_uri()
    script = (f"import {{ loadDemo }} from '{loader}'; const KH = loadDemo(); "
              "console.log(JSON.stringify({ judge: KH.aiJudge.SOURCES, lab: KH.labReport.SOURCES, version: KH.aiJudge.PROMPT_VERSION, "
              "blocklist: KH.aiguard.BLOCKLIST_SOURCE }));")
    done = subprocess.run(["node", "--input-type=module", "-e", script], capture_output=True, text=True, timeout=60, check=False)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_ai_device_vectors_are_current() -> None:
    gen = _load("gen_ai_device_vectors", ROOT / "tests" / "data" / "gen_ai_device_vectors.py")
    assert VECTORS.read_text(encoding="utf-8") == gen.dump(gen.build()), (
        "tests/data/ai_device_vectors.json is stale: app/ai changed. Run `python3 tests/data/gen_ai_device_vectors.py`, then "
        "`node tests/js/run_vectors.mjs`, and update js/engine/aijudge.js and lab_report.js until both agree."
    )


def test_the_twins_use_the_servers_patterns() -> None:
    out = _twin_sources()
    server = {
        "RED_FLAG": features.RED_FLAG, "SUPPLEMENT_AMOUNT": features._SUPPLEMENT_AMOUNT, "DIAGNOSE": features._DIAGNOSE,
        "INSULIN": chat._INSULIN, "DOSE": chat._DOSE, "MEDICINE_NAME": chat._MEDICINE_NAME, "SKIP_MEDICINE": chat._SKIP_MEDICINE,
        "CHANGE_MEDICINE": chat._CHANGE_MEDICINE, "LOW_CONTEXT": chat._LOW_CONTEXT, "RESTRICT": chat._RESTRICT,
        "SENTENCE": chat._SENTENCE, "LAB_WORDS": chat._LAB_WORDS, "URL": guard._URL, "EMAIL": guard._EMAIL, "MARKUP": guard._MARKUP,
        "LEADING": features._LEADING,
    }
    assert out["judge"] == {k: v.pattern for k, v in server.items()}
    lab = {"SEPARATORS": lab_report._SEPARATORS, "DATE_TOKEN": lab_report._DATE_TOKEN, "YMD": lab_report._YMD,
           "NUMERIC": lab_report._NUMERIC, "DAY_NAME_YEAR": lab_report._DAY_NAME_YEAR, "NAME_DAY_YEAR": lab_report._NAME_DAY_YEAR,
           "NUMBER": lab_report._NUMBER, "SPACES": lab_report._SPACES}
    assert out["lab"] == {k: v.pattern for k, v in lab.items()}
    for name, rx in {**server, **lab}.items():  # the twins compile them with re.IGNORECASE exactly where the server does
        ignorecase = bool(rx.flags & re.IGNORECASE)
        assert ignorecase == (name not in ("SENTENCE", "MARKUP", "LEADING") and name not in lab), name
    assert out["blocklist"] == guard.BLOCKLIST.pattern
    assert out["version"] == prompts.PROMPT_VERSION, "prompts changed: check js/engine/aijudge.js, then bump its PROMPT_VERSION"


def test_vectors_cover_each_outcome() -> None:
    doc = json.loads(VECTORS.read_text(encoding="utf-8"))
    statuses = {(c["output"] or {}).get("status") for c in doc["prefilter_cases"]}
    assert statuses == {None, "treating_a_low", "red_flag", "medicine_question"}
    reasons = {str(c["output"][1]).split(":")[0] for c in doc["name_policy_cases"]}
    assert reasons == {"None", "empty", "url", "markup", "blocklist"}
    assert any(c["output"] is not None for c in doc["servings_for_cases"]) and any(c["output"] is None for c in doc["servings_for_cases"])
    assert {c["output"]["status"] for c in doc["lab_judge_cases"]} == {"ok", "not_a_lab_report", "unreadable", "no_results"}
    dropped = [c["output"]["dropped"] for c in doc["lab_text_cases"]]
    for key in ("unknown_analyte", "unknown_unit", "out_of_range", "not_in_text"):
        assert any(d[key] for d in dropped), key
    problems = {c["parse"][1] for c in doc["printed_date_cases"]}
    assert problems == {None, "missing", "ambiguous", "unreadable"}
    assert {c["output"]["status"] for c in doc["parse_meal_cases"]} == {"ok", "refused"}


def test_ai_prompts_json_is_the_servers_prompt(tmp_path) -> None:
    builder = _load("build_preview", ROOT / "scripts" / "build_preview.py")
    files = {f.relative_to(tmp_path).as_posix() for f in builder.build_device(tmp_path)}
    assert {"ai-prompts.json", "vendor/pdfjs-dist-6.4.299/pdf.min.mjs", "vendor/pdfjs-dist-6.4.299/pdf.worker.min.mjs"} <= files
    doc = json.loads((tmp_path / "ai-prompts.json").read_text(encoding="utf-8"))
    assert set(doc) == {"system", "tasks"} and set(doc["tasks"]) == {"parse_meal", "read_lab_report_text"}
    assert doc["system"] == prompts.TASK_SYSTEM_PROMPT
    for task in doc["tasks"].values():
        assert set(task) == {"template"} and task["template"].count("{text}") == 1
    vectors = json.loads(VECTORS.read_text(encoding="utf-8"))["payload_cases"]
    assert {c["task"] for c in vectors} == {"parse_meal", "lab_report_text"}
    for case in vectors:  # the page sends `payload` (the twin is checked against it by run_vectors.mjs); the app fills the template
        task = "parse_meal" if case["task"] == "parse_meal" else "read_lab_report_text"
        filled = doc["tasks"][task]["template"].replace("{text}", case["payload"])
        assert filled == case["message"]
        schema = schemas.parse_meal_schema() if task == "parse_meal" else schemas.lab_report_schema()
        data = prompts.parse_meal_data(case["text"]) if task == "parse_meal" else {"lines": features.lab_text_lines(case["text"])}
        assert filled == prompts.user_message(case["task"], data, mode="json_schema", schema=schema)
    # Never a task that could dose: the system prompt forbids it, and only these two tasks exist.
    assert "Never give, calculate or adjust insulin doses" in doc["system"]


def test_the_device_ai_never_offers_more_than_the_two_tasks() -> None:
    mock = (ROOT / "app" / "static" / "js" / "mock" / "ai.js").read_text(encoding="utf-8")
    tasks = set(re.findall(r"ask\('([a-z_]+)'", mock))
    assert tasks == {"parse_meal", "read_lab_report_text"}
    assert "localStorage" not in mock and "indexedDB" not in mock  # nothing about a prompt or reply is kept
