"""The three bugs from the 2026-10-29 code review (static checks; `tools/e2e/reliability.py` makes each happen in Chromium):
Today after a day fails to load, unknown values in saved meals, and a fitted recipe over the 100-serving limit."""
from __future__ import annotations

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
    chips = ADD[ADD.index("saved-shortcuts-list"):]
    assert "'not listed'" in ADD and "atLeast(" in chips and "atLeastWords(" in chips
    assert "unknownOf, atLeast, atLeastWords" in ADD


def test_a_fitted_recipe_is_kept_within_the_servings_limit():
    assert f"const MAX_RECIPE_SERVINGS = {MAX_RECIPE_SERVINGS};" in PLAN  # the same limit as the server's
    body = PLAN[PLAN.index("function fittedBody"):]
    body = body[:body.index("\n  }\n")]
    assert "Math.min(want, MAX_RECIPE_SERVINGS)" in body
    assert "it.servings * scale" in body  # the amounts shrink instead, so one serving stays the size that fits
