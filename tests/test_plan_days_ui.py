"""The "Plan several days" sheet (``app/static/js/views/plandays.js``, design note 23) against the server contract.

Static checks (no browser): the file is in the shell after ``guidance.js`` and in the service worker; the Plan tab has its
button; it builds DOM without HTML sinks, loads nothing from the network and keeps nothing in browser storage; it calls only
the server's routes; its limits are the server's (60 days by default, 40 entries a batch); the owner's answers of note 23 §12
(the snack and repeat choices remembered on the server, "OK to repeat", today's past meals, clear as a reset); it writes only after a confirm, with a
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
    assert called == {("POST", "/api/guidance/plan-days"), ("POST", "/api/log/batch"), ("POST", "/api/log/clear-planned"),
                      ("GET", "/api/guidance/repeat-ok")}
    assert "request(on ? 'PUT' : 'DELETE', `/api/guidance/repeat-ok/${kind}/${encodeURIComponent(id)}`)" in VIEW
    called |= {("PUT", "/api/guidance/repeat-ok/{kind}/{item_id}"), ("DELETE", "/api/guidance/repeat-ok/{kind}/{item_id}")}
    routes = {(m, r.path) for router in (guidance_api.router, log_module.router) for r in router.routes for m in r.methods}
    assert called <= routes, called - routes
    assert "/api/ai" not in VIEW  # several days are planned by the rules engine alone (note 23 §12.1)


def test_the_limits_are_the_servers() -> None:
    assert f"const MAX_DAYS = {R.PLAN_DAYS_MAX};" in VIEW and R.PLAN_DAYS_MAX == 60
    assert models.CLEAR_PLANNED_MAX_DAYS == R.PLAN_DAYS_CEILING == 90
    assert f"const BATCH = {models.MAX_LOG_BATCH};" in VIEW
    assert "max: String(st.maxDays)" in VIEW and "min: '1'" in VIEW
    assert "st.days >= 1 && st.days <= st.maxDays" in VIEW  # nothing is asked for outside 1 to the server's cap
    # The cap is the server's PLAN_DAYS_MAX: each answer carries it, and the field, the hint and the quick choices follow it.
    assert "applyLimits(data && data.limits);" in _body("run")
    limits = _body("applyLimits")
    assert "st.maxDays = limits.days_max;" in limits and "b.hidden = Number(b.dataset.days) > st.maxDays;" in limits
    assert "const QUICK = [7, 14, 30, 60];" in VIEW and "`${n} days`" in VIEW and "hidden: n > st.maxDays" in VIEW


def test_long_plans_are_added_in_batches_and_said_as_they_go() -> None:
    add = _body("addPlan")
    assert "for (let i = 0; i < rows.length; i += BATCH)" in add
    assert "live(`Added ${sent} of ${rows.length} foods…`)" in add
    # Undo of the longest plan fits one request: at most 90 days of four meals.
    assert models.CLEAR_PLANNED_MAX_IDS >= 90 * 4 * 6


def test_the_snack_and_the_repeat_choices_are_remembered_on_the_server() -> None:
    opened = _body("openPlanDays")
    assert "snack: G.prefValue('plan_snack', false) === true" in opened  # off unless the person turned it on
    assert "G.prefValue('plan_repeat_meals', [])" in opened
    assert "remember({ plan_snack: st.snack })" in opened and "remember({ plan_repeat_meals: st.repeatMeals })" in opened
    assert "await G.savePrefs(patch);" in _body("remember")
    save = GUIDANCE[GUIDANCE.index("  async function savePrefs(patch)"):GUIDANCE.index("  function prefValue(")]
    assert "KH.api.updateMySettings({ guidance: { ...base, ...patch } })" in save
    # The whole object is read fresh first (a mark set a moment ago stays), and nothing is sent when it cannot be read.
    assert "const item = await loadPrefs(true);" in save and "throw new Error('your settings could not be read')" in save
    assert "'Plan a snack too'" in opened and "'Meals that may repeat'" in opened
    for m in ("breakfast", "lunch", "dinner"):
        assert m in VIEW
    assert "for (const m of MEALS.filter((x) => MAIN.includes(x.key)))" in opened  # the snack is its own choice
    body = _body("run")
    assert "snack: st.snack, repeat_meals: st.repeatMeals," in body and "skip_first_day: skipFirstDay()" in body


def test_ok_to_repeat_marks_a_saved_meal_or_a_food() -> None:
    assert "P.planMeal(m, false, { repeat })" in VIEW
    assert "toggleMeal: (m, button) => setMark('meals', m.template_id, m.name, button)" in VIEW
    assert "toggle: (item, button) => setMark('foods', item.food_id, item.name, button)" in VIEW
    assert "if (repeat && m.source === 'saved' && m.template_id != null)" in GUIDANCE
    assert "'OK to repeat'" in GUIDANCE and "rowMenu(it, { repeat," in GUIDANCE
    assert "await replan();" in _body("setMark")  # the plan is made again with the new mark
    assert "'Foods and meals OK to repeat'" in VIEW and "`Remove ${name} from OK to repeat`" in VIEW


def test_todays_past_meals_are_skipped_or_asked_in_the_sheet() -> None:
    assert "const MEAL_TIMES = { breakfast: '08:00', lunch: '12:30', snack: '15:30', dinner: '18:30' };" in VIEW
    assert "const PAST_ASK_MINUTES = 120;" in VIEW
    past = _body("pastMeals")
    assert "if (st.start !== todayStr()) return out;" in past  # only when the first day is today
    assert "now.getHours() * 60 + now.getMinutes()" in past  # the browser's local time
    assert "if (late > PAST_ASK_MINUTES) out.skip.push(m);" in past and "else if (late > 0) out.ask.push(m);" in past
    ask = _body("askAboutPast")
    assert "confirm.inline($('#g-days-ask')" in ask  # the app's own confirm, never a browser dialog
    assert "`${P.joinWords(said)}. Plan ${one ? 'it' : 'them'} anyway?`" in ask and "was at ${MEAL_TIMES[m]}" in ask
    assert "confirmText: one ? 'Plan it' : 'Plan them'" in ask and "cancelText: 'Skip'" in ask
    for dialog in ("window.confirm", "alert(", "prompt("):
        assert dialog not in VIEW
    assert "cancelText = 'Cancel', onCancel = null" in CORE and "if (onCancel) onCancel();" in CORE
    assert "'Start tomorrow'" in VIEW and "st.start = addDays(todayStr(), 1);" in _body("startTomorrow")


def test_clear_is_a_reset_and_undo_takes_off_only_what_was_added() -> None:
    clear = _body("confirmClear")
    assert "This is a reset: it also takes off food you planned yourself, not only what a plan added." in clear
    assert "Undo takes off only what this plan added." in _body("added")


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
    assert "'Rest of this week'" in VIEW and "Nothing is sent to AI." in VIEW
    assert "'Dialysis day'" in VIEW and "'Shopping list for these days'" in VIEW
    assert "'Copy list'" in VIEW and "'Share list'" in VIEW and "'Undo'" in VIEW and "'Clear planned days…'" in VIEW
    assert "P.targetsUsed(res.targets" in VIEW and "P.notes(res.notes)" in VIEW  # the targets used and the disclaimer
    assert "P.staleNote(at)" in VIEW and "add: entries.length > 0 && !at" in VIEW  # an offline copy is shown but never added


def test_day_totals_read_at_least_or_not_listed() -> None:
    after = GUIDANCE[GUIDANCE.index("  function dayAfter(d)"):GUIDANCE.index("  async function applyPlan(")]
    assert "const unknown = (d && d.projected_unknown) || {};" in after
    assert "`≥ ${fmtNum(st.value, k)} of ${of} (≥ ${pctText})`" in after and "`not listed (target ${of})`" in after
    # A meal's totals use the plan sheet's own "≥" and "not listed" (keyNumbers with the meal's unknown keys).
    assert "keyNumbers(m.totals, m.unknown)" in GUIDANCE and "P.planMeal(m, false, { repeat })" in VIEW


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
