"""The meal guidance UI and its demo twin stay wired to the server they front (note 06 §4.16).

Static checks of ``app/static`` (no browser): the demo API (``js/mock/guidance.js``, ``js/mock/log.js``,
``js/mock/meals.js``) answers every guidance route the server has, with the server's texts, limits and
starter meals; the browser engine's version and hash are the server's; the views call only routes the
server has; the page has a labelled control for every guidance setting and for "Used to treat a low";
the scripts load in the order the engine needs; and the guidance view builds DOM without HTML sinks.
The numbers are checked by ``tests/data/guidance_vectors.json`` (``node tests/js/run_vectors.mjs``),
whole answers by ``tools/e2e/parity.py`` section 12, the flows in Chromium by ``tools/e2e/journey.py``
(What fits now, Not for me, a swap, Plan the rest of my day) and ``tools/e2e/sandbox.py`` (the preview).
"""
from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import get_args

from app import log as log_module
from app import models, settings_registry
from app.guidance import api as guidance_api
from app.guidance import context as guidance_context
from app.guidance import messages as guidance_messages
from app.guidance import rules as guidance_rules

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "app" / "static"
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")
MOCK = (STATIC / "js" / "mock" / "guidance.js").read_text(encoding="utf-8")
MOCK_LOG = (STATIC / "js" / "mock" / "log.js").read_text(encoding="utf-8")
MOCK_MEALS = (STATIC / "js" / "mock" / "meals.js").read_text(encoding="utf-8")
VIEW = (STATIC / "js" / "views" / "guidance.js").read_text(encoding="utf-8")
ENGINE_RULES = (STATIC / "js" / "engine" / "guidance" / "rules.js").read_text(encoding="utf-8")
ENGINE_MESSAGES = (STATIC / "js" / "engine" / "guidance" / "messages.js").read_text(encoding="utf-8")
SETTINGS_VIEW = (STATIC / "js" / "views" / "settings.js").read_text(encoding="utf-8")
ENGINE_PARTS = ["rules", "messages", "budget", "score", "fits", "swaps", "planner", "insights", "hypo"]


def _js_string(source: str, name: str) -> str:
    """The value of ``const NAME = '...'`` (single or double quotes) in a JS source."""
    m = re.search(rf"const {name} = (['\"])(.*?)\1;", source)
    assert m, f"const {name} not found"
    return m.group(2).replace("\\'", "'")


def _js_number(source: str, name: str) -> float:
    m = re.search(rf"const {name} = ([0-9.]+);", source)
    assert m, f"const {name} not found"
    return float(m.group(1))


class _Controls(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.by_id: dict[str, dict[str, str]] = {}
        self.label_for: set[str] = set()
        self.options: dict[str, list[str]] = {}
        self._select: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k: v or "" for k, v in attrs}
        if a.get("id"):
            self.by_id[a["id"]] = {"tag": tag, **a}
        if tag == "label" and a.get("for"):
            self.label_for.add(a["for"])
        if tag == "select":
            self._select = a.get("id")
            self.options[self._select or ""] = []
        if tag == "option" and self._select is not None:
            self.options[self._select].append(a.get("value", ""))

    def handle_endtag(self, tag: str) -> None:
        if tag == "select":
            self._select = None


PAGE = _Controls()
PAGE.feed(INDEX)


# --------------------------------------------------------------------------- #
# The demo answers like the server
# --------------------------------------------------------------------------- #


def _mock_routes(source: str) -> set[tuple[str, str]]:
    out = set()
    for method, path in re.findall(r"route\('([A-Z*]+)', '([^']+)'", source):
        out.add((method, path))
    return out


def test_the_demo_answers_every_guidance_route() -> None:
    routes = _mock_routes(MOCK)
    for r in guidance_api.router.routes:
        for method in r.methods:
            if "{food_id}" in r.path:
                # PUT / DELETE /api/guidance/not-for-me/{food_id}: one regex route for any method
                assert re.search(r"route\('\*', /\^\\/api\\/guidance\\/not-for-me\\/", MOCK), r.path
                assert f"method !== '{method}'" in MOCK or f"method === '{method}'" in MOCK, (method, r.path)
            else:
                assert (method, r.path) in routes, f"js/mock/guidance.js has no {method} {r.path}"
    assert ("POST", "/api/log/batch") in _mock_routes(MOCK_LOG)


def test_demo_texts_and_limits_are_the_servers() -> None:
    assert _js_string(MOCK, "DISABLED_BY_USER") == guidance_api.DISABLED_BY_USER
    assert _js_string(MOCK, "PLAN_OFF") == guidance_api.PLAN_OFF
    assert _js_string(MOCK, "INSIGHTS_OFF") == guidance_api.INSIGHTS_OFF
    assert _js_number(MOCK, "MAX_NOT_FOR_ME") == guidance_context.MAX_NOT_FOR_ME
    assert _js_number(MOCK_LOG, "MAX_LOG_BATCH") == models.MAX_LOG_BATCH
    shown = re.search(r"const TARGET_KEYS_SHOWN = \[(.*?)\];", MOCK).group(1)
    names = {"R.K": guidance_rules.K, "R.P": guidance_rules.P, "R.NA": guidance_rules.NA, "R.FLUID": guidance_rules.FLUID,
             "R.PROTEIN": guidance_rules.PROTEIN, "R.CARBS": guidance_rules.CARBS, "R.KCAL": guidance_rules.KCAL}
    keys = [names.get(x.strip(), x.strip().strip("'")) for x in shown.split(",")]
    assert tuple(keys) == guidance_api.TARGET_KEYS_SHOWN
    for name in ("DISCLAIMER", "NO_TARGETS", "DISABLED", "NEEDS_CONNECTION"):
        assert _js_string(ENGINE_MESSAGES, name) == getattr(guidance_messages, name), name


def test_engine_version_and_hash_are_the_servers() -> None:
    assert _js_string(ENGINE_RULES, "RULES_VERSION") == guidance_rules.RULES_VERSION
    assert _js_string(ENGINE_RULES, "RULES_HASH") == guidance_rules.rules_hash()


def test_starter_combos_copy_matches_data_combos_json() -> None:
    data = json.loads((ROOT / "data" / "combos.json").read_text(encoding="utf-8"))
    block = re.search(r"const COMBOS = \[(.*?)\n  \];", MOCK, re.S).group(1)
    combos = re.findall(r"\{ id: '([^']+)', name: '([^']+)', meal: '([^']+)',\s*source: '([^']+)',\s*items: \[(.*?)\] \}", block, re.S)
    assert len(combos) == len(data["combos"])
    for (cid, name, meal, source, items), want in zip(combos, data["combos"]):
        assert (cid, name, meal, source) == (want["id"], want["name"], want["meal"], want["source"])
        pairs = [(int(a), float(b)) for a, b in re.findall(r"\[(\d+), ([0-9.]+)\]", items)]
        assert pairs == [(int(i["fdc_id"]), float(i["servings"])) for i in want["items"]], cid


def test_demo_csv_columns_and_purpose_values_are_the_servers() -> None:
    cols = re.search(r"const CSV_COLUMNS = \[(.*?)\];", MOCK_LOG, re.S).group(1)
    tail = re.findall(r"'([a-z_]+)'", cols.split("...NUTRIENT_KEYS,")[1])
    head = re.findall(r"'([a-z_]+)'", cols.split("...NUTRIENT_KEYS,")[0])
    assert head + list(log_module.NUTRIENT_KEYS) + tail == list(log_module.CSV_COLUMNS)
    assert "c.choice('purpose', ['hypo', 'none'], { nullable: true });" in MOCK_LOG
    assert list(get_args(models.PurposeIn)) == ["hypo", "none"]
    assert "c.choice('meal_hint', MEAL_KEYS, { nullable: true });" in MOCK_MEALS


# --------------------------------------------------------------------------- #
# The page
# --------------------------------------------------------------------------- #


def test_slots_and_labelled_controls_exist() -> None:
    for slot in ("guidance-today", "guidance-today-actions", "guidance-day-insights", "guidance-fits", "guidance-fits-meal",
                 "guidance-fits-body", "guidance-fits-status", "btn-plan-day", "guidance-period", "set-guidance",
                 "set-guidance-body", "entry-guidance", "sheet-guidance", "sheet-guidance-title", "sheet-guidance-sub"):
        assert slot in PAGE.by_id, f"#{slot} missing from index.html"
    assert PAGE.by_id["guidance-fits-status"].get("role") == "status"
    # "What fits now" meal picker: a radio per meal, each with a label
    for meal in get_args(models.Meal):
        assert f"gfm-{meal}" in PAGE.by_id and f"gfm-{meal}" in PAGE.label_for
    # "Used to treat a low": a labelled checkbox described by its hint
    box = PAGE.by_id["entry-hypo"]
    assert box["type"] == "checkbox" and "entry-hypo" in PAGE.label_for and box["aria-describedby"] == "entry-hypo-hint"
    assert "entry-hypo-hint" in PAGE.by_id
    # ... under the warnings it changes and above the ideas it switches, so the food's warnings stay where
    # they were (above the fold on a phone: tools/e2e/sandbox.py checks the banana sheet at 375 x 812).
    order = [INDEX.index(f'id="{x}"') for x in ("entry-note", "entry-warnings", "entry-hypo-row", "entry-guidance")]
    assert order == sorted(order), "the entry sheet order is note, warnings, 'Used to treat a low', guidance"
    # Saved meals: "Meant for" offers every meal and "any"
    assert "meal-hint" in PAGE.label_for
    assert PAGE.options["meal-hint"] == ["", *get_args(models.Meal)]


def test_script_order() -> None:
    srcs = re.findall(r'<script src="([^"]+)"', INDEX)
    pos = {s: i for i, s in enumerate(srcs)}
    parts = [f"js/engine/guidance/{p}.js" for p in ENGINE_PARTS]
    assert [pos[p] for p in parts] == sorted(pos[p] for p in parts), "engine parts out of order"
    assert pos["js/engine/rules.js"] < pos[parts[0]] and pos[parts[-1]] < pos["js/core.js"]
    assert pos["js/mock/log.js"] < pos["js/mock/guidance.js"] < pos["js/mock/seed.js"]
    for view in ("today", "add", "plan", "trends", "settings", "ai"):
        assert pos[f"js/views/{view}.js"] < pos["js/views/guidance.js"], view
    assert pos["js/views/guidance.js"] < pos["js/main.js"]
    assert '<link rel="stylesheet" href="css/guidance.css">' in INDEX
    assert INDEX.index("css/guidance.css") < INDEX.index("css/touch.css"), "touch.css must stay last"
    runner = (ROOT / "tests" / "js" / "run_vectors.mjs").read_text(encoding="utf-8")
    listed = re.search(r"const GUIDANCE_PARTS = \[(.*?)\];", runner).group(1)
    assert re.findall(r"'([a-z]+)'", listed) == ENGINE_PARTS, "tests/js/run_vectors.mjs loads the parts in another order"
    assert re.findall(r'<script src="js/engine/guidance/([a-z]+)\.js"', INDEX) == ENGINE_PARTS


# --------------------------------------------------------------------------- #
# The view
# --------------------------------------------------------------------------- #


def _server_paths() -> list[re.Pattern[str]]:
    """The guidance and log routes (the only ones js/views/guidance.js calls by path; the rest go
    through KH.api in js/core.js)."""
    out = []
    for router in (guidance_api.router, log_module.router):
        for r in router.routes:
            out.append(re.compile("^" + re.sub(r"\\\{[a-z_]+\\\}", "[^/]+", re.escape(r.path)) + "$"))
    return out


def test_the_view_calls_only_routes_the_server_has() -> None:
    paths = _server_paths()
    called = set(re.findall(r"`(/api/[a-z/\-]+)", VIEW)) | set(re.findall(r"'(/api/[a-z/\-]+)'", VIEW))
    assert called, "no API paths found in js/views/guidance.js"
    for p in called:
        probe = p + "1" if p.endswith("/") else p  # a path that continues with an id
        assert any(rx.match(probe) for rx in paths), f"{p} is not a server route"


def test_the_view_uses_no_html_sinks_and_marks_lists() -> None:
    for sink in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function"):
        assert sink not in VIEW, sink
    assert "role: 'list'" in VIEW
    assert "role: 'status'" in VIEW and "aria-live" in INDEX
    # A low treatment is shown as information, never as a warning, and is never sent to AI for a swap.
    assert "renderHypoNote" in VIEW and "res.mode === 'normal' ? aiSwapBlock" in VIEW
    # Offline: the "Treating a low" card comes from the browser twin of the server's text, and the last
    # answers are kept in memory only (guidance answers are health data: never in browser storage).
    assert "GE.M.treatingALowCard(dose)" in VIEW
    for storage in ("localStorage", "sessionStorage", "indexedDB", "caches."):
        assert storage not in VIEW, storage


def test_answers_show_which_targets_they_used_and_when_saved() -> None:
    """Note 06 §5 R10 (wrong targets amplified by guidance): What fits now and the plan sheet show the targets the
    answer used and when the profile holding them was saved, from the answer's own `targets` block, with a way
    to Profile. The keys the line names are ones the server sends (and the demo twin mirrors)."""
    block = re.search(r"const TARGET_LINE = \[(.*?)\];", VIEW, re.S)
    assert block, "TARGET_LINE not found in js/views/guidance.js"
    keys = re.findall(r"\['(\w+)', '[\w ]+'\]", block.group(1))
    assert set(keys) <= set(guidance_api.TARGET_KEYS_SHOWN), set(keys) - set(guidance_api.TARGET_KEYS_SHOWN)
    assert {"potassium_mg", "phosphorus_mg", "sodium_mg", "carbs_per_meal_g", "carbs_per_snack_g"} <= set(keys)
    assert "for (const k of TARGET_KEYS_SHOWN)" in MOCK and "profile_updated_at: ctx.profile.targets_updated_at" in MOCK
    assert VIEW.count("targetsUsed(res.targets") == 2  # What fits now and the plan sheet
    assert "targets.profile_updated_at" in VIEW and "Using the targets in your profile, saved" in VIEW
    assert "Check them in Profile" in VIEW and "router.show('profile')" in VIEW
    # A target of min == max reads "about X" (the Today rule), a min-only one "at least X".
    assert "v.min === v.max ? `about ${n(v.min)}`" in VIEW and "`at least ${n(v.min)}`" in VIEW


def test_settings_view_lists_the_guidance_keys() -> None:
    for key in ("guidance.enabled", "guidance.pool_per_role", "guidance.beam_width"):
        assert key in settings_registry.REGISTRY, key
        assert f"'{key}'" in SETTINGS_VIEW, f"Admin → Server settings does not group {key}"
    fields = set(settings_registry.GuidancePreferences.model_fields)
    for field in fields:
        assert re.search(rf"\b{field}\b", VIEW), f"Settings → Meal guidance has no control for {field}"


def _fn(source: str, name: str) -> str:
    """The body of ``function name(`` up to the next top-level function of the view."""
    start = source.index(f"function {name}(")
    nxt = re.search(r"\n  (?:async )?function \w+\(", source[start + 10:])
    return source[start: start + 10 + nxt.start()] if nxt else source[start:]


def test_every_guidance_ai_button_has_what_will_be_sent_and_says_what_was_dropped() -> None:
    """Note 04 R9 step 4 ("every AI button has What will be sent?") and G13 (the ideas dropped and why) for the
    three guidance-owned AI modes (v0.3.0 review L10): AI order (rerank), Ask AI to pick (swap) and Let AI choose
    (plan). Each dry run is the same request with ``dry_run`` (``KH.ai.api.nextMeal(body, true)``), shown in the
    AI sheet; the dropped lines are ``KH.ai.droppedNotes``, the cards' own wording. tools/e2e/device.py (ai) clicks
    AI order's on a real server with a fake provider that names a food the rules never offered."""
    sent = _fn(VIEW, "aiSentButton")
    assert "'What will be sent?'" in sent and "KH.ai.showSent(await KH.ai.api.nextMeal(" in sent and ", true)" in sent
    order, swap, plan = _fn(VIEW, "aiOrderBar"), _fn(VIEW, "aiSwapBlock"), _fn(VIEW, "aiPlanButton")
    assert "aiSentButton({ meal, date, mode: 'rerank' }" in order and "aiDropped(answer" in order
    assert "aiSentButton(swapBody" in swap and "aiDropped(answer" in swap
    assert "id: 'g-plan-ai-sent'" in plan and "mode: 'plan' }, true)" in plan and "aiDropped(answer" in plan
    ai = (STATIC / "js" / "views" / "ai.js").read_text(encoding="utf-8")
    assert "function droppedNotes(answer, what = null)" in ai and "droppedNotes };" in ai
    assert "return out.concat(droppedNotes(answer));" in ai  # the AI cards use the same lines
