"""The demo's potassium banner follows the same window as the server (v0.3.0 review L3).

The Labs view and Profile's card showed the red "very high potassium" banner for 90 days, a constant in the
browser, while Suggest targets (and its alert) used the admin's ``targets.lab_fresh_days.potassium``. Now the
server says which alert is current (``GET /api/labs`` ``alerts``, ``app.labs.current_alerts``) and the views only
draw it. The demo answers the same route from ``js/mock/labs.js`` (``_labAlerts`` over the targets twin's
``freshLabs``); this replays it through ``tests/js/demo_api.mjs``. ``tests/test_targets_api.py`` checks the server
and ``tools/e2e/parity.py`` section 11c compares the two under each window setting.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "tests" / "js" / "demo_api.mjs"
STATIC = ROOT / "app" / "static" / "js"


def _demo(requests: list[dict[str, Any]]) -> list[dict[str, Any]]:
    assert shutil.which("node"), "Node.js 22 is needed to run the demo API (CLAUDE.md, Parity)"
    done = subprocess.run(["node", str(RUNNER)], input=json.dumps(requests), capture_output=True, text=True, timeout=120, check=False)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


@pytest.mark.parametrize("window, days_ago, alerted", [(30, 40, False), (30, 29, True), (180, 100, True), (90, 91, False)])
def test_the_demo_labs_alert_uses_the_admins_potassium_window(window: int, days_ago: int, alerted: bool) -> None:
    taken = (date.today() - timedelta(days=days_ago)).isoformat()
    # The demo's sample results include newer, normal potassium results: remove them (their ids are the same in
    # every fresh demo) so the 6.2 is the newest.
    seeded = [r["id"] for r in _demo([{"method": "GET", "path": "/api/labs?analyte=potassium"}])[0]["body"]["labs"]]
    answers = _demo([{"method": "DELETE", "path": f"/api/labs/{i}"} for i in seeded] + [
        {"method": "PATCH", "path": "/api/admin/settings", "body": {"targets.lab_fresh_days.potassium": window}},
        {"method": "POST", "path": "/api/labs", "body": {"analyte": "potassium", "value": 6.2, "unit": "mmol/L", "taken_on": taken}},
        {"method": "GET", "path": "/api/labs"},
        {"method": "GET", "path": "/api/labs?analyte=phosphate"},
    ])
    assert seeded and all(a["ok"] for a in answers), answers
    for listed in answers[-2:]:
        alerts = listed["body"]["alerts"]
        assert [(a["level"], a["value"], a["taken_on"]) for a in alerts] == ([("urgent", 6.2, taken)] if alerted else [])


def test_the_views_draw_the_servers_alert_and_apply_no_window_of_their_own() -> None:
    labs = (STATIC / "views" / "labs.js").read_text(encoding="utf-8")
    profile = (STATIC / "views" / "profile.js").read_text(encoding="utf-8")
    assert "DEFAULT_FRESH_DAYS" not in labs and "ALERT_DAYS" not in labs and "isFresh" not in labs
    assert "alerts: list.alerts || []" in labs and "data.alerts" in labs
    assert "currentAlert(data)" in labs and "KH.labs.currentAlert(data)" in profile
