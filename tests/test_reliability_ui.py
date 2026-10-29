"""Static checks for the reliability fixes (`tools/e2e/reliability.py` makes each happen in Chromium): the three bugs from the
2026-10-29 code review (Today after a day fails to load, unknown values in saved meals, a fitted recipe over the 100-serving
limit), and from testing the other screens that save: a toast hidden under an open sheet and the weight card showing another day
while a day loads."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from app.models import MAX_RECIPE_SERVINGS

ROOT = Path(__file__).resolve().parents[1]
VIEWS = ROOT / "app" / "static" / "js" / "views"
TODAY = (VIEWS / "today.js").read_text(encoding="utf-8")
PLAN = (VIEWS / "plan.js").read_text(encoding="utf-8")
ADD = (VIEWS / "add.js").read_text(encoding="utf-8")


def test_a_failed_day_load_clears_the_page_and_offers_retry():
    catch = TODAY[TODAY.index("async function loadDay"):TODAY.index("function renderUnavailable")]
    # Only the newest request may draw, and a day that was never drawn is replaced by the unavailable card, not kept.
    assert "if (reqId !== dayRequest) return;" in catch
    assert "if (state.dayLoadedFor !== state.date && !(e && e.handled)) renderUnavailable(e);" in catch
    body = TODAY[TODAY.index("function renderUnavailable"):TODAY.index("function renderToday")]
    assert "state.day = null;" in body and "state.dayLoadedFor = null;" in body
    for el in ("alertsEl", "$('#projected-alerts')", "statusBarsEl", "totalsAllEl"):
        assert el in body, el
    assert "clear(mealsEl)" in body and "role: 'alert'" in body and "id: 'day-unavailable'" in body
    assert "could not be loaded, so nothing is shown for it." in body
    assert "id: 'day-retry'" in body and "loadDay()" in body


def test_saved_meals_never_show_an_unknown_value_as_zero():
    rows = PLAN[PLAN.index("function renderSavedMeals"):]
    rows = rows[:rows.index("\n  }\n")]
    assert "unknownOf(t.unknown, k)" in rows or "unknownOf(t.unknown,k)" in rows
    assert "t.per_serving[k] == null" in rows and "'not listed'" in rows
    assert "atLeast(" in rows and "atLeastWords(" in rows
    assert "` (${notListed(unk)})`" in rows  # "K ≥ 55 (+ 1 not listed)", as on Today's meal lines
    chips = ADD[ADD.index("saved-shortcuts-list"):]
    assert "'not listed'" in ADD and "atLeast(" in chips and "atLeastWords(" in chips
    assert "unknownOf, atLeast, atLeastWords" in ADD


def test_a_fitted_recipe_is_kept_within_the_servings_limit():
    assert f"const MAX_RECIPE_SERVINGS = {MAX_RECIPE_SERVINGS};" in PLAN  # the same limit as the server's
    body = PLAN[PLAN.index("function fittedBody"):]
    body = body[:body.index("\n  }\n")]
    assert "Math.min(want, MAX_RECIPE_SERVINGS)" in body
    assert "it.servings * scale" in body  # the amounts shrink instead, so one serving stays the size that fits


# ---- the other screens that save (ROADMAP item 1) ------------------------------------------------------------------------
# tests/js/reliability_ui.test.mjs runs the real code: core.js's toast with a sheet open, and the weight card in body.js while a
# day loads. Labs drawing an old answer is tests/test_lab_cache.py.
def test_the_toast_and_the_weight_card_in_node():
    assert shutil.which("node"), "Node.js is required for the reliability UI checks"
    runner = ROOT / "tests" / "js" / "reliability_ui.test.mjs"
    result = subprocess.run(["node", "--test", str(runner)], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
