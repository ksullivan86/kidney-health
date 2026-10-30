"""The "Plan several days" sheet (``app/static/js/views/plandays.js``, design note 23) against the server contract.

Static checks (no browser): the file is in the shell after ``guidance.js`` and in the service worker; the Plan tab has its
button; it builds DOM without HTML sinks, loads nothing from the network and keeps nothing in browser storage; it calls only
the server's routes; its limits are the server's (14 days, 40 entries a batch); it writes only after a confirm, with a
``client_id`` per food made once per plan; Undo sends exactly the ids it added; the words are the note's; the day totals show
"≥" and "not listed" for values a food does not list; the classes it uses are styled. The flow itself runs in Chromium in
``tools/e2e/plandays.py``; the answers of the demo twin are checked by ``tests/test_plan_days_demo.py``."""
from __future__ import annotations

import re
from pathlib import Path

from app import log as log_module
from app import models
from app.guidance import api as guidance_api
from app.guidance import rules as R

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "app" / "static"
VIEW = (STATIC / "js" / "views" / "plandays.js").read_text(encoding="utf-8")
GUIDANCE = (STATIC / "js" / "views" / "guidance.js").read_text(encoding="utf-8")
PLAN = (STATIC / "js" / "views" / "plan.js").read_text(encoding="utf-8")
CORE = (STATIC / "js" / "core.js").read_text(encoding="utf-8")
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")
SW = (STATIC / "sw.js").read_text(encoding="utf-8")
CSS = (STATIC / "css" / "guidance.css").read_text(encoding="utf-8")


def _body(name: str) -> str:
    """The text of the function ``name`` in the view, up to the next top-level function."""
    m = re.search(rf"\n  (?:async )?function {name}\(.*?(?=\n  (?:async )?function |\n  \$\(|\n  KH\.views)", VIEW, re.S)
    assert m, name
    return m.group(0)


def test_the_file_is_in_the_shell_after_guidance_and_in_the_service_worker() -> None:
    scripts = re.findall(r'<script src="([^"]+)"', INDEX)
    assert scripts.index("js/views/plan.js") < scripts.index("js/views/guidance.js") < scripts.index("js/views/plandays.js")
    assert scripts.index("js/views/plandays.js") < scripts.index("js/main.js")
    assert "'/js/views/plandays.js'," in SW


def test_the_plan_tab_has_the_button_next_to_plan_a_day() -> None:
    actions = INDEX[INDEX.index('<div class="plan-actions">'):INDEX.index('id="btn-copy-day"')]
    assert actions.index('id="btn-plan-day"') < actions.index('id="btn-plan-days"')
    assert "Plan several days…" in actions
    assert "$('#btn-plan-days').addEventListener('click'" in VIEW


def test_no_html_sinks_no_network_no_storage() -> None:
    for sink in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function"):
        assert sink not in VIEW, sink
    assert not re.search(r"<\s*(script|img|iframe|style)\b", VIEW, re.IGNORECASE)
    assert "fetch(" not in VIEW and not re.search(r"https?://", VIEW)
    for storage in ("localStorage", "sessionStorage", "indexedDB", "caches."):
        assert storage not in VIEW, storage  # a plan is health data: kept in memory only
    assert "role: 'list'" in VIEW and "role: 'status'" in VIEW


def test_it_calls_only_the_servers_routes() -> None:
    called = set(re.findall(r"request\('(GET|POST|PUT|DELETE)', '(/api/[a-z/\-]+)'", VIEW))
    assert called == {("POST", "/api/guidance/plan-days"), ("POST", "/api/log/batch"), ("POST", "/api/log/clear-planned")}
    routes = {(m, r.path) for router in (guidance_api.router, log_module.router) for r in router.routes for m in r.methods}
    assert called <= routes, called - routes


def test_the_limits_are_the_servers() -> None:
    assert f"const MAX_DAYS = {R.PLAN_DAYS_MAX};" in VIEW
    assert R.PLAN_DAYS_MAX == models.CLEAR_PLANNED_MAX_DAYS == 14
    assert f"const BATCH = {models.MAX_LOG_BATCH};" in VIEW
    assert "max: String(MAX_DAYS)" in VIEW and "min: '1'" in VIEW
    assert "st.days >= 1 && st.days <= MAX_DAYS" in VIEW  # nothing is asked for outside 1 to 14 days


def test_it_writes_only_after_a_confirm() -> None:
    # The batch is sent only from addPlan, and addPlan runs only from the confirm of "Add to plan".
    assert VIEW.count("api.logBatch(") == 1 and "api.logBatch(chunk)" in _body("sendChunk")
    assert VIEW.count("sendChunk(") == 2 and "sendChunk(chunk)" in _body("addPlan")
    assert VIEW.count("addPlan(") == 2 and "onConfirm: () => addPlan(res)" in _body("confirmAdd")
    assert "confirmText: 'Add to plan'" in _body("confirmAdd") and "tone: 'primary'" in _body("confirmAdd")
    # Clear planned days runs only from its own confirm; Undo sends exactly the ids the batch answered with.
    clear_calls = re.findall(r"api\.clearPlanned\(([^)]*)\)", VIEW)
    assert clear_calls == ["{ start: res.start, end: res.end, ids }", "{ start, end }"]
    assert "for (const r of (answer && answer.results) || []) ids.push(r.id);" in _body("addPlan")
    assert "onConfirm: async () => {\n        const r = await api.clearPlanned({ start, end });" in _body("confirmClear")
    # The confirm button of a non-deleting confirm is the primary one; the default stays the red Delete.
    assert "tone = 'danger'" in CORE and "tone === 'primary' ? 'primary' : 'danger-solid'" in CORE


def test_a_retry_adds_nothing_twice() -> None:
    add = _body("addPlan")
    assert "if (!st.rows) st.rows = res.apply.entries.map((e) => ({ ...e, client_id: G.uuid() }));" in add
    assert "rows.slice(i, i + BATCH)" in add
    # A new plan, a change of range, an add or an Undo makes new ids (a deleted entry's client_id is not used again).
    assert "st.rows = null;" in _body("run") and "st.rows = null;" in _body("added")
    # The entries are the server's: planned food with purpose "none". The view never sets a status or a purpose itself.
    assert "status:" not in add and "purpose" not in VIEW and "hypo" not in VIEW.replace("planned low treatments", "")


def test_the_words_are_the_notes() -> None:
    assert "Nothing is marked as eaten." in _body("confirmAdd")
    assert "Eaten food and planned low treatments stay." in _body("confirmClear")
    assert "'Same as a day before: nothing else fits.'" in VIEW
    assert "'Rest of this week'" in VIEW and "'7 days'" in VIEW and "'14 days'" in VIEW
    assert "'Dialysis day'" in VIEW and "'Shopping list for these days'" in VIEW
    assert "'Copy list'" in VIEW and "'Share list'" in VIEW and "'Undo'" in VIEW and "'Clear planned days…'" in VIEW
    assert "P.targetsUsed(res.targets" in VIEW and "P.notes(res.notes)" in VIEW  # the targets used and the disclaimer
    assert "P.staleNote(at)" in VIEW and "add: entries.length > 0 && !at" in VIEW  # an offline copy is shown but never added


def test_day_totals_read_at_least_or_not_listed() -> None:
    after = GUIDANCE[GUIDANCE.index("  function dayAfter(d)"):GUIDANCE.index("  async function applyPlan(")]
    assert "const unknown = (d && d.projected_unknown) || {};" in after
    assert "`≥ ${fmtNum(st.value, k)} of ${of} (≥ ${pctText})`" in after and "`not listed (target ${of})`" in after
    # A meal's totals use the plan sheet's own "≥" and "not listed" (keyNumbers with the meal's unknown keys).
    assert "keyNumbers(m.totals, m.unknown)" in GUIDANCE and "P.planMeal(m)" in VIEW


def test_it_uses_the_plan_sheets_parts() -> None:
    parts = re.search(r"plan: \{ (.*?) \},\n", GUIDANCE, re.S)
    assert parts, "KH.guidance.plan is missing"
    exported = set(re.findall(r"\w+", parts.group(1)))
    used = set(re.findall(r"\bP\.(\w+)", VIEW))
    assert used <= exported, used - exported
    assert "if (sheetEl.dataset.kind === 'plan-days') { if (KH.views.planDays) KH.views.planDays.replan(); return; }" in GUIDANCE
    for name in ("shoppingText", "copyShopping", "weekStartPref"):
        assert re.search(rf"KH\.views\.plan = \{{[^}}]*\b{name}\b", PLAN), name


def test_the_classes_it_uses_are_styled() -> None:
    classes = set(re.findall(r"class: '(g-days[a-z-]*)", VIEW))
    assert classes
    for cls in classes:
        assert f".{cls}" in CSS, cls
    assert "min-height: var(--tap)" in CSS[CSS.index(".g-days-sum"):]  # the day's fold is a 44 px tap target
