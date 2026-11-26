"""Profile's two weights in pounds or kilograms (user.units.weight).

The profile stores ``weight_kg`` and ``weight_6_months_ago_kg`` in kilograms as before; the setting changes only how Profile shows
and takes them. These tests cover the setting's default, the page's wiring, the pounds range against the kilogram limits, and the
conversions and Profile's boxes in tests/js/weight_units.test.mjs.
"""
from __future__ import annotations

import math
import re
import shutil
import subprocess
from pathlib import Path

from app.body import KG_PER_LB
from app.models import ProfileUpdate
from app.settings_registry import REGISTRY
from conftest import TestClient

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "app" / "static"
KEY = "user.units.weight"


def _field_limits(name: str) -> tuple[float, float]:
    lo = hi = None
    for m in ProfileUpdate.model_fields[name].metadata:
        lo = getattr(m, "ge", None) or getattr(m, "gt", None) or lo
        hi = getattr(m, "le", None) or hi
    return lo, hi


def test_the_default_is_pounds_and_the_profile_stays_in_kilograms(client: TestClient):
    d = REGISTRY[KEY]
    assert (d.scope, d.default) == ("user_default", "lb")
    assert client.get("/api/me/settings").json()["settings"][KEY]["value"] == "lb"
    assert client.patch("/api/me/settings", json={KEY: "lb"}).status_code == 200
    r = client.put("/api/profile", json={**client.get("/api/profile").json(), "weight_kg": 70.23, "weight_6_months_ago_kg": 74})
    assert r.status_code == 200, r.text
    p = client.get("/api/profile").json()
    assert (p["weight_kg"], p["weight_6_months_ago_kg"]) == (70.23, 74)


def test_the_pounds_ranges_stay_inside_what_the_server_takes():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    for box, low_kg, high_kg in (("pf-weight", 20, 300), ("pf-weight-6mo", 20, 400)):
        m = re.search(rf'id="{box}"[^>]*min="([\d.]+)" max="([\d.]+)" step="0.1"', html)
        assert m, box
        lo, hi = float(m.group(1)), float(m.group(2))
        assert lo == math.ceil(low_kg / KG_PER_LB * 10) / 10 and hi == math.floor(high_kg / KG_PER_LB * 10) / 10, box
    _, max_kg = _field_limits("weight_kg")
    min_6, max_6 = _field_limits("weight_6_months_ago_kg")
    assert max_kg >= 300 and (min_6, max_6) == (20, 400)


def test_the_page_names_the_unit_and_profile_follows_the_setting():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert '<label for="pf-weight" id="pf-weight-label">Weight (lb)</label>' in html
    assert '<label for="pf-weight-6mo" id="pf-weight-6mo-label">Weight 6 months ago (lb)</label>' in html
    profile = (STATIC / "js" / "views" / "profile.js").read_text(encoding="utf-8")
    for line in ("weight_kg: readWeightKg('#pf-weight'),", "weight_6_months_ago_kg: readWeightKg('#pf-weight-6mo'),",
                 "fillWeight('#pf-weight', p.weight_kg ?? null);", "fillWeight('#pf-weight-6mo', p.weight_6_months_ago_kg ?? null);",
                 "loadWeightUnit();", "`Dry weight (${weightUnit}, after dialysis)`", "toast(`Enter your weight (${weightUnit}) first;"):
        assert line in profile, line
    assert "numOrNull($('#pf-weight" not in profile
    body = (STATIC / "js" / "views" / "body.js").read_text(encoding="utf-8")
    assert "KH.views.profile.setWeightUnit(unit)" in body
    settings = (STATIC / "js" / "views" / "settings.js").read_text(encoding="utf-8")
    assert "weight_kg: 'Weight'," in settings and "weight_6_months_ago_kg: 'Weight 6 months ago'," in settings
    assert "KH.bodyRules.formatWeight(v, weightUnit())" in settings
    # The iPhone app with no server answers /api/me/settings from the same registry twin, so the unit is there too.
    engine = (STATIC / "js" / "engine" / "settings.js").read_text(encoding="utf-8")
    assert "key: 'user.units.weight', type: 'choice', options: ['kg', 'lb'], default: 'lb', scope: 'user_default'" in engine


def test_the_conversions_and_profile_boxes():
    assert shutil.which("node"), "Node.js is required for the weight tests"
    runner = ROOT / "tests" / "js" / "weight_units.test.mjs"
    result = subprocess.run(["node", str(runner)], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
