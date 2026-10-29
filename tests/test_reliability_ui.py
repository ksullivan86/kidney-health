"""Static checks for the reliability fixes (`tools/e2e/reliability.py` makes each happen in Chromium): the three bugs from the
2026-10-29 code review (Today after a day fails to load, unknown values in saved meals, a fitted recipe over the 100-serving
limit), and from testing the other screens that save: a toast hidden under an open sheet, Labs drawing an old answer, and
the weight card showing another day while a day loads."""
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


# ---- the other screens that save (ROADMAP item 1): a failed save, a slow load ----------------------------------------------
CORE = (ROOT / "app" / "static" / "js" / "core.js").read_text(encoding="utf-8")
LABS = (VIEWS / "labs.js").read_text(encoding="utf-8")
BODY = (VIEWS / "body.js").read_text(encoding="utf-8")


def test_a_toast_is_shown_inside_an_open_sheet():
    # An open sheet is a modal dialog (the top layer, the page under it inert): a toast left on the page is hidden under it.
    host = CORE[CORE.index("function toastHost"):CORE.index("function toastError")]
    assert "$$('dialog[open]')" in host and "d.matches(':modal')" in host and "document.body" in host
    assert "if (toastEl.parentElement !== host) host.append(toastEl);" in host
    close = CORE[CORE.index("function setupDialog"):CORE.index("function openDialog")]
    assert "if (dlg.contains(toastEl)) document.body.append(toastEl);" in close


def test_labs_never_draw_an_answer_asked_for_before_invalidate():
    load = LABS[LABS.index("function load()"):LABS.index("function newestOf")]
    # invalidate() drops the request in flight too, and an answer from before it is replaced by a new load (its error as well).
    assert "function invalidate() { cache.data = null; cache.loading = null; cache.gen += 1; }" in load
    assert "const gen = cache.gen;" in load
    assert load.count("if (gen !== cache.gen) return load();") == 2
    assert "if (cache.loading === loading) cache.loading = null;" in load


def test_the_weight_card_never_shows_another_days_weights_while_a_day_loads():
    body = BODY[BODY.index("async function loadToday"):BODY.index("// ---- the sheets: shared parts")]
    assert "const req = ++S.req;" in body and body.count("if (req !== S.req) return;") == 1  # a late answer is not drawn
    clear_at = body.index("if (S.drawnDate !== date) { S.drawnDate = null; clear(todayBody).append(message('Loading…')); }")
    assert clear_at < body.index("await Promise.allSettled")
    assert body.index("renderToday(") < body.index("S.drawnDate = date;")
