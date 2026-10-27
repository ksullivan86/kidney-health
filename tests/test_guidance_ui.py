"""The meal guidance UI and its demo twin stay wired to the server they front (note 06 §4.16).

Static checks of ``app/static`` (no browser): the demo API (``js/mock/guidance.js``, ``js/mock/log.js``,
``js/mock/meals.js``) answers every guidance route the server has, with the server's texts, limits and
starter meals; the browser engine's version and hash are the server's; the views call only routes the
server has; the page has a labelled control for every guidance setting and for "Used to treat a low";
the scripts load in the order the engine needs; and the guidance view builds DOM without HTML sinks.
The preference screens (note 09 part B: Settings → Meal guidance → Your food preferences, and the "⋯" menu of a suggestion,
a swap and a plan item) are pinned below by their texts, controls, limits and the routes they call; their behaviour in Chromium
is walked by ``tools/e2e/prefs.py``. The numbers are checked by ``tests/data/guidance_vectors.json`` (``node tests/js/run_vectors.mjs``),
whole answers by ``tools/e2e/parity.py`` section 12, the flows in Chromium by ``tools/e2e/journey.py``
(What fits now, Not for me, a swap, Plan the rest of my day) and ``tools/e2e/sandbox.py`` (the preview).
"""
from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import get_args

from app import foods as foods_module
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
ENGINE_PARTS = ["rules", "messages", "budget", "score", "fits", "swaps", "planner", "insights", "hypo", "recipes"]


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
                # PUT / DELETE /api/guidance/preferences/{food_id} and its alias /not-for-me/{food_id}: one regex route for any method
                segment = r.path.split("/")[3]
                assert segment in ("preferences", "not-for-me"), r.path
                assert re.search(rf"route\('\*', /\^\\/api\\/guidance\\/{segment}\\/", MOCK), r.path
                assert f"method !== '{method}'" in MOCK or f"method === '{method}'" in MOCK, (method, r.path)
            else:
                assert (method, r.path) in routes, f"js/mock/guidance.js has no {method} {r.path}"
    assert ("POST", "/api/log/batch") in _mock_routes(MOCK_LOG)


def test_demo_texts_and_limits_are_the_servers() -> None:
    assert _js_string(MOCK, "DISABLED_BY_USER") == guidance_api.DISABLED_BY_USER
    assert _js_string(MOCK, "PLAN_OFF") == guidance_api.PLAN_OFF
    assert _js_string(MOCK, "INSIGHTS_OFF") == guidance_api.INSIGHTS_OFF
    assert _js_number(MOCK, "MAX_NOT_FOR_ME") == guidance_context.MAX_NOT_FOR_ME
    assert _js_number(MOCK, "MAX_FOOD_PREFERENCES") == guidance_context.MAX_FOOD_PREFERENCES
    assert tuple(re.findall(r"'([a-z_]+)'", re.search(r"const PREFERENCES = \[(.*?)\];", MOCK).group(1))) == guidance_context.PREFERENCE_VALUES
    assert tuple(re.findall(r"'([a-z]+)'", re.search(r"const PREFERENCE_SOURCES = \[(.*?)\];", MOCK).group(1))) == guidance_context.PREFERENCE_SOURCES
    for name in ("NOTE_TEXTS",):
        assert re.search(r"shown_despite_exclusions: '([^']+)'", ENGINE_MESSAGES).group(1) == \
            guidance_messages.NOTE_TEXTS["shown_despite_exclusions"], name
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
    # Every field of the person's guidance object has its control in Settings → Meal guidance (the form sends the whole object,
    # so a field without a control would still be kept; the note-09 fields have theirs since part B).
    fields = set(settings_registry.GuidancePreferences.model_fields)
    for field in fields:
        assert re.search(rf"\b{field}\b", VIEW), f"Settings → Meal guidance has no control for {field}"
    assert "const next = { ...v, ...patch };" in VIEW


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


# --------------------------------------------------------------------------- #
# Your food preferences (note 09 §4.1, §4.4, §4.10; part B)
# --------------------------------------------------------------------------- #

AI_VIEW = (STATIC / "js" / "views" / "ai.js").read_text(encoding="utf-8")
PLAN_VIEW = (STATIC / "js" / "views" / "plan.js").read_text(encoding="utf-8")
GUIDANCE_CSS = (STATIC / "css" / "guidance.css").read_text(encoding="utf-8")
TASTE_NOTE = ("Less often and Not for me are about taste. They are not an allergy filter: the app cannot tell whether a food "
              "contains an allergen, so check labels.")


def test_the_preference_screens_use_the_preference_routes() -> None:
    """New code uses the new routes: the "⋯" menu and Settings read and write /preferences and read /learned; the older
    /not-for-me aliases are the demo's and older pages' business, not this view's."""
    for call in ("request('GET', '/api/guidance/preferences')", "request('GET', '/api/guidance/learned')",
                 "request('PUT', `/api/guidance/preferences/${encodeURIComponent(foodId)}`, { preference })",
                 "request('DELETE', `/api/guidance/preferences/${encodeURIComponent(foodId)}`)"):
        assert call in VIEW, call
    assert "not-for-me" not in VIEW


def test_the_preference_wording_is_the_specifications() -> None:
    """The sentences of note 09 §4.10, word for word, and the one place the word for an allergy appears."""
    assert f"const TASTE_NOTE = '{TASTE_NOTE}';" in VIEW
    assert "const LEARN_OFF_HINT = 'Off: suggestions use only your limits and variety, not what you usually eat.';" in VIEW
    assert "check('learn_from_log', 'Learn from my log', LEARN_OFF_HINT" in VIEW
    # a preference is never called an allergy anywhere else (the app cannot tell what a food contains)
    for name, source in (("views/guidance.js", VIEW), ("views/ai.js", AI_VIEW), ("views/plan.js", PLAN_VIEW), ("mock/guidance.js", MOCK)):
        assert not re.search(r"allerg", source.replace(TASTE_NOTE, ""), re.I), name
    assert VIEW.count("TASTE_NOTE") == 2  # defined once, shown once
    # the section and its parts
    for text in ("'Your food preferences'", "'Learned from your log'", "'Not learning about'", "'Learn again'", "'Suggest again'",
                 "'Remove'", "'Keep'", "'Stop using this'", "'Save as a meal'", "'Not this meal'", "'Show them again'", "'Kinds of food'"):
        assert text in VIEW, text
    assert "const PREF_WORD = { like: 'More like this', less: 'Less often', not_for_me: 'Not for me' };" in VIEW
    # a row the person did not set says who did (note 09 §4.8b); a row of the person's own has no note
    assert "const SOURCE_NOTE = { ask: 'added in Ask', assistant: 'from your assistant' };" in VIEW
    assert "const sub = [f.category, SOURCE_NOTE[f.source] || ''].filter(Boolean).join(' · ');" in VIEW
    assert "const KIND_CHOICES = [['none', 'None'], ['like', 'Like'], ['less', 'Less often'], ['exclude', 'Never suggest']];" in VIEW
    kinds = re.search(r"const LEARNED_KINDS = \[(.*?)\];", VIEW, re.S).group(1)
    assert re.findall(r"\['(\w+)',", kinds) == ["often", "slot", "usual_meal", "planned_not_eaten"]


def test_the_limits_shown_are_the_servers() -> None:
    """The counts under the lists read the limits from the answer (1,000 preferences, 500 "Not for me"), so the screen never
    states a number of its own; the answer carries both, the demo's equal the server's (test above), and the errors the server gives
    for a full list or a full list of hidden meals reach the person in its words."""
    from app.guidance import models as guidance_models

    assert {"limit", "not_for_me_limit"} <= set(guidance_models.PreferenceList.model_fields)
    assert guidance_context.MAX_FOOD_PREFERENCES == 1000 and guidance_context.MAX_NOT_FOR_ME == 500
    assert "of ${data.limit} food preferences" in VIEW and "of ${data.not_for_me_limit} “Not for me”" in VIEW
    assert not re.search(r"\b(1000|1,000|500)\b", _fn(VIEW, "prefsSection")), "the screen must not repeat the server's limits"
    # a 409 (full) is the server's sentence in a toast; a 400 on the hidden meals (50) lands beside the line that lists them
    assert "toastError(err)" in _fn(VIEW, "rowMenu") and "id: 'set-g-hidden-usual-meals'" in VIEW
    assert settings_registry.GuidancePreferences.model_fields["hidden_usual_meals"].metadata[0].max_length == 50


def test_the_food_group_choice_covers_the_three_lists_and_the_server_categories() -> None:
    """Like / Less often / Never suggest per kind of food write the three settings fields; a kind is in one list at most."""
    block = re.search(r"const KIND_FIELDS = \{(.*?)\};", VIEW, re.S).group(1)
    pairs = dict(re.findall(r"(\w+): '(\w+_categories)'", block))
    assert pairs == {"like": "like_categories", "less": "less_categories", "exclude": "exclude_categories"}
    assert set(pairs.values()) <= set(settings_registry.GuidancePreferences.model_fields)
    # one radio group per kind, so a kind cannot be chosen twice; the whole object is saved (the server refuses a kind in two lists)
    assert "type: 'radio', name: `set-g-kind-${i}`" in VIEW and "save(collect(), radio, out)" in VIEW
    assert "kindsFieldset(kindsOut)" in VIEW
    assert len(foods_module.CATEGORIES) <= 50  # each list holds at most 50 kinds; the screen offers the server's own categories
    assert "KH.api.categories()" in VIEW


def test_learned_items_and_their_actions_follow_the_note() -> None:
    """§4.4: a food has Keep (stores like; "less" for a food the app lowered) and Stop using this (stores neutral); a usual meal has
    Save as a meal (the existing saved-meal editor, started with the meal's foods) and Not this meal (its key joins
    hidden_usual_meals); foods marked neutral are listed with a way back (DELETE the row)."""
    row = _fn(VIEW, "learnedRow")
    assert "setFood(it, value, e.currentTarget)" in row and "setFood(it, 'neutral', e.currentTarget)" in row
    assert "const value = it.effect === 'less' ? 'less' : 'like';" in row
    assert "saveUsualMeal(it, e.currentTarget)" in row and "hideUsualMeal(it, e.currentTarget, out)" in row
    assert "hidden_usual_meals: [...(v.hidden_usual_meals || []).filter((k) => k !== it.key), it.key]" in VIEW
    assert "plan.openMealEditor(null, button, { name: String(it.name).slice(0, 80), meal_hint: parsed.meal, foods })" in VIEW
    assert "function openMealEditor(t, trigger, draft = null)" in PLAN_VIEW and "KH.views.plan = {" in PLAN_VIEW
    assert "await api.clearPreference(f.food_id);" in VIEW[VIEW.index("'Learn again'") - 400: VIEW.index("'Learn again'") + 400]
    # what the server says about a learned item is shown as it says it: its reason, never a claim to know
    assert "`${it.reason} · ${effect}`" in row


def test_the_usual_meal_key_is_read_like_the_server_writes_it() -> None:
    """"Save as a meal" rebuilds a usual meal's foods from its key (the learned item carries nothing else)."""
    rx = re.compile(re.search(r"const USUAL_KEY = /(.*)/;", VIEW).group(1))
    for meal, items in (("lunch", [(12, 1.0), (30, 0.5)]), ("breakfast", [(7, 0.25), (9, 3.0), (101, 1.5)]), ("snack", [(2, 0.75), (3, 1.0)])):
        key = guidance_rules.usual_meal_key(meal, items)
        m = rx.match(key)
        assert m and m.group(1) == meal, key
        assert [tuple(int(x) for x in part.split("x")) for part in m.group(2).split(",")] == [(i, int(q * 4)) for i, q in sorted(items)]
    assert rx.match("dinner:") is None and rx.match("brunch:1x4,2x4") is None and rx.match("lunch:1x4;2x4") is None


def test_the_menu_is_on_suggestions_swaps_and_plan_items_and_never_on_a_low() -> None:
    """The "⋯" menu (More like this, Less often, Not for me: toggles that show the current state and clear it) is on a suggestion in
    What fits now, a swap row and a plan item; the Treating a low options and the swaps for the next low never carry one, because
    taste does not rank a low treatment (note 09 §4.9)."""
    menu = _fn(VIEW, "rowMenu")
    assert "'aria-pressed': 'false'" in menu and "setAttribute('aria-pressed', key === value ? 'true' : 'false')" in menu
    assert "api.clearPreference(item.food_id)" in menu and "api.setPreference(item.food_id, value)" in menu
    assert "const PREF_ORDER = ['like', 'less', 'not_for_me'];" in VIEW
    assert "preferenceOf(item.food_id)" in menu  # the state is read when the menu opens (Settings passes it in)
    assert "role: 'group'" in menu and "'aria-expanded': 'false'" in menu and "e.key === 'Escape'" in menu
    assert "rowMenu(item, {" in _fn(VIEW, "foodRow")
    swap = _fn(VIEW, "swapRow")
    assert swap.index("res.mode !== 'hypo'") < swap.index("rowMenu(s,")
    assert "portionList(m.items, { menus: true })" in VIEW and "portionList(m.closest.items)" in VIEW
    assert "rowMenu" not in _fn(VIEW, "lowOption") and "rowMenu" not in _fn(VIEW, "lowCard")
    # a toast confirms each change, in the words of the menu
    for text in ("more like this. Settings → Meal guidance lists it.", "will be suggested less often.", "will not be suggested again.",
                 "no preference now."):
        assert text in VIEW, text
    # the pressed state shows a check mark as well as a colour; the controls are 44 px (.btn and .icon-btn)
    assert '.g-pref[aria-pressed="true"]::before { content: "✓";' in GUIDANCE_CSS
    assert "btn secondary g-pref" in menu and "class: 'icon-btn g-more'" in menu


def test_a_not_for_me_from_a_swap_or_a_plan_item_refreshes_what_it_came_from() -> None:
    assert "if (value === 'not_for_me') { entryCtl.swapKey = null; loadSwaps(); }" in _fn(VIEW, "swapRow")
    assert "if (value === 'not_for_me') replanAfterHiding();" in _fn(VIEW, "portionList")
    assert "await runPlan();" in _fn(VIEW, "replanAfterHiding")
    assert "if (value === 'not_for_me' && onChange) onChange();" in _fn(VIEW, "foodRow")


def test_preferences_are_saved_online_only() -> None:
    """Settings are online-only by decision, so Not for me and the rest are never queued: the writes go through the plain API client
    (which the outbox does not queue) and offline the person sees the existing messages: the server-unreachable error on a save and
    "Guidance needs a connection to your server." where the lists would be."""
    for name in ("KH.offline", "KH.net", "enqueue", "indexedDB"):
        assert name not in VIEW, name
    offline = (STATIC / "js" / "offline.js").read_text(encoding="utf-8")
    assert "/api/guidance" not in offline
    settings = _fn(VIEW, "renderSettings")
    assert "prefsError && prefsError.status === 0" in settings and "NEEDS_CONNECTION" in settings
    assert "foodsBox.append(failure(prefsAnswer.err))" in VIEW  # offline: "Guidance needs a connection to your server."
    assert "toastError(err)" in _fn(VIEW, "rowMenu")  # a refused or unreachable save says so


def test_the_text_for_ai_ideas_moved_but_keeps_its_setting() -> None:
    """Settings → Meal guidance shows "Food preferences for AI ideas" when the server offers AI, saved through the same call
    (PATCH /api/me/ai {preferences}, setting ai.preferences, 200 characters); Settings → AI ideas has one line pointing there."""
    field = _fn(AI_VIEW, "preferencesField")
    assert "'Food preferences for AI ideas'" in field and "api.updateMe({ preferences: pref.value.trim() })" in field
    assert "maxlength: '200'" in field and "if (MOCK) return null;" in field and "!me.enabled" in field
    assert "preferencesField" in AI_VIEW[AI_VIEW.index("KH.ai = {"):]
    personal = _fn(AI_VIEW, "personalPart")
    assert "'Food preferences for AI ideas'" not in personal and "api.updateMe({ preferences" not in personal
    assert "Settings → Meal guidance → Your food preferences" in personal and "KH.guidance.openPreferences()" in personal
    assert "openPreferences," in VIEW
    assert "KH.ai.preferencesField()" in VIEW and "aiPreferencesSlot()" in _fn(VIEW, "prefsSection")
    assert settings_registry.AiPreferencesText.__metadata__[0].max_length == 200


def test_the_preference_css_is_there() -> None:
    for rule in (".g-prefs {", ".g-pref-list {", ".g-kind-list {", ".g-kind-seg { position: relative; }", ".g-portions li .g-menu"):
        assert rule in GUIDANCE_CSS, rule
    assert 'content: "✓" / "";' in GUIDANCE_CSS  # the check mark is decoration: the name stays "More like this" (aria-pressed says the rest)
