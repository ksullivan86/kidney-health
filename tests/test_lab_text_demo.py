"""The demo's answer for the text of a lab report PDF (``app/static/js/mock/ai.js``; design note 36 §4.4) is in the server's shape.

The demo has no AI and sends nothing: ``POST /api/ai/read-lab-report-text`` there always answers the same three rows. This keeps those rows
honest: the server's own judge (:func:`app.ai.lab_report.judge_text`), given the same copied lines and a page that has them, gives exactly
the rows the demo shows (labels, units, displays, dates), and the demo's checks of the body are the server's limits."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

from app.ai import lab_report as LR
from app.ai import schemas

MOCK_AI = (Path(__file__).resolve().parents[1] / "app" / "static" / "js" / "mock" / "ai.js").read_text(encoding="utf-8")
PAGE = "Collected 2026-10-07\nPotassium 4.6 mmol/L\nPhosphorus 3.4 mg/dL\neGFR 61 mL/min/1.73m2"
COPIED = [{"analyte": "potassium", "value": 4.6, "unit": "mmol/L", "taken_on": "2026-10-07"},
          {"analyte": "phosphate", "value": 3.4, "unit": "mg/dL", "taken_on": "2026-10-07"},
          {"analyte": "egfr", "value": 61, "unit": "mL/min/1.73m2", "taken_on": "2026-10-07"}]


def demo_example() -> dict:
    literal = re.search(r"/\* lab-text-example \*/(.*?)/\* end-lab-text-example \*/", MOCK_AI, re.S).group(1)
    assert shutil.which("node"), "Node.js is required to read the demo's example"
    done = subprocess.run(["node", "-e", "process.stdout.write(JSON.stringify(eval('(' + process.argv[1] + ')')))", literal],
                          capture_output=True, text=True, timeout=30, check=True)
    return json.loads(done.stdout)


def test_the_demo_rows_are_what_the_servers_judge_gives():
    example = demo_example()
    verdict = LR.judge_text(schemas.LabReportAnswer.model_validate({"status": "ok", "rows": COPIED}), PAGE)
    assert example["status"] == verdict["status"] == "ok"
    assert example["rows"] == verdict["rows"]
    assert example["dropped"] == verdict["dropped"] and example["dropped_notes"] == verdict["dropped_notes"] == []


def test_the_demo_checks_the_body_as_the_server_does_and_says_nothing_was_sent():
    assert f"text.length > {LR.MAX_TEXT_CHARS}" in MOCK_AI
    assert "page >= 1 && page <= 50" in MOCK_AI
    from app import vision

    assert vision.MAX_PDF_PAGES == 50
    assert "This is the demo: nothing was sent to an AI. These rows are a fixed example, not read from your file." in MOCK_AI
