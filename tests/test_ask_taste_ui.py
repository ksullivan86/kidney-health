"""The Ask screen's taste card (``app/static/js/views/ask.js``, "tastes"; note 09 §4.8, decision Q2), run in Node against a fake
page and a fake server (``tests/js/ask_taste_page.mjs``), so the behaviour is checked without a browser:

* the card says what will change in the app's own words ("Remember this for your suggestions? Salmon: less often.") and has
  Remember and Cancel; nothing is requested before Remember;
* Remember on a food is ``PUT /api/guidance/preferences/{id}`` with ``{preference, source: "ask"}`` (``clear`` = ``DELETE``);
  on a food group it reads the current ``guidance`` setting, moves only that group and saves the whole object;
* Undo restores exactly the state there was when Remember was pressed (the person may have changed it since the card was
  shown), from the same source; a ``neutral`` row is left alone by ``clear``;
* Cancel, a refusal (the list is full) and an unreadable setting change nothing; the thread the model reads says what happened.

Chromium checks of the same card at 375 and 1280 px are in ``tools/e2e/ask.py``. No network."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "app" / "static"
ASK_JS = (STATIC / "js" / "views" / "ask.js").read_text(encoding="utf-8")
CORE_JS = (STATIC / "js" / "core.js").read_text(encoding="utf-8")
ASK_CSS = (STATIC / "css" / "ask.css").read_text(encoding="utf-8")
SALMON = "Salmon, Atlantic, farmed, cooked"
ALLERGY = ("Less often and not for me are about taste. They are not an allergy filter: the app cannot tell whether a food contains an "
           "allergen, so check labels.")


@pytest.fixture(scope="module")
def ran() -> dict[str, Any]:
    assert shutil.which("node"), "Node.js 22 is needed to run the browser code (CLAUDE.md, Parity)"
    done = subprocess.run(["node", str(ROOT / "tests" / "js" / "ask_taste_page.mjs")], capture_output=True, text=True, timeout=60, check=False)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def labels(buttons: list[dict[str, Any]]) -> list[str]:
    return [b["label"] for b in buttons]


def test_the_card_says_what_will_change_and_nothing_is_requested_before_remember(ran):
    pending = ran["food_pending"]
    assert pending["lines"][:3] == ["Remember this for your suggestions?", f"{SALMON}: less often.", "Now: not set."]
    assert ALLERGY in pending["lines"]  # "less often" and "not for me" are tastes, not an allergy filter
    assert labels(pending["buttons"]) == ["Remember", "Cancel"] and not any(b["disabled"] for b in pending["buttons"])
    assert pending["calls"] == [] and pending["prefs"] == {}
    assert ran["group_pending"]["calls"] == []


def test_the_words_for_a_group_and_for_not_for_me(ran):
    assert ran["group_pending"]["lines"][:3] == ["Remember this for your suggestions?", "Fish & Seafood (food group): less often.", "Now: not set."]
    assert ran["group_words"][:3] == ["Remember this for your suggestions?", "Fish & Seafood (food group): liked.", "Now: never suggest."]
    assert ran["group_never_words"][1] == "Fish & Seafood (food group): never suggest."
    assert ALLERGY not in ran["group_words"]  # a like needs no such line


def test_remember_on_a_food_is_the_normal_put_with_source_ask_and_undo_deletes_what_was_not_there(ran):
    done = ran["food_remembered"]
    assert done["calls"] == [["GET preferences"], ["PUT preference", 101, {"preference": "less", "source": "ask"}]]
    assert done["prefs"] == {"101": {"preference": "less", "source": "ask"}}
    assert done["lines"][:2] == ["Remembered for your suggestions", f"{SALMON}: less often."]
    assert labels(done["buttons"]) == ["Undo"]
    assert done["forgot"] == 1 and done["loaded"] == 1  # the other screens forget their suggestions and reload the setting
    undone = ran["food_undone"]
    assert undone["calls"] == [["DELETE preference", 101]] and undone["prefs"] == {}
    assert undone["lines"][-1] == f"Undone. {SALMON} is back to: not set."
    assert undone["forgot"] == 2


def test_undo_puts_back_the_previous_value_from_its_own_source(ran):
    assert ran["liked_remembered"]["prefs"] == {"101": {"preference": "less", "source": "ask"}}
    assert ran["liked_undone"]["calls"] == [["PUT preference", 101, {"preference": "like", "source": "person"}]]
    assert ran["liked_undone"]["prefs"] == {"101": {"preference": "like", "source": "person"}}


def test_clear_is_a_delete_and_undo_puts_the_row_back(ran):
    assert ran["clear_remembered"]["calls"] == [["GET preferences"], ["DELETE preference", 101]] and ran["clear_remembered"]["prefs"] == {}
    assert ran["clear_undone"]["calls"] == [["PUT preference", 101, {"preference": "not_for_me", "source": "ask"}]]
    assert ran["clear_undone"]["prefs"] == {"101": {"preference": "not_for_me", "source": "ask"}}


def test_undo_goes_back_to_what_was_there_when_remember_was_pressed_not_to_what_the_card_said(ran):
    # the card said "none" before; by the time Remember was pressed the person had marked the food Not for me elsewhere
    assert ran["stale_card"]["prefs"] == {"101": {"preference": "not_for_me", "source": "person"}}
    assert ran["stale_card"]["calls"][0] == ["GET preferences"]


def test_clear_leaves_a_neutral_row_alone(ran):
    assert ran["neutral_clear"]["calls"] == [["GET preferences"]]  # read, nothing written
    assert ran["neutral_clear"]["prefs"] == {"101": {"preference": "neutral", "source": "person"}}


def test_cancel_writes_nothing_and_the_card_goes_away(ran):
    cancelled = ran["cancelled"]
    assert cancelled["calls"] == [] and cancelled["prefs"] == {} and cancelled["cards"] == 0
    assert cancelled["lines"][-1] == "Not remembered."


def test_a_refusal_shows_the_servers_words_and_keeps_the_card(ran):
    refused = ran["refused"]
    assert refused["lines"][-1] == "your food preferences are full (1000 foods); remove one first"
    assert labels(refused["buttons"]) == ["Remember", "Cancel"] and not any(b["disabled"] for b in refused["buttons"])
    assert refused["prefs"] == {} and refused["forgot"] == 0  # nothing changed, so nothing to refresh


def test_a_group_is_one_patch_of_the_whole_setting_read_at_that_moment(ran):
    # the setting was changed in Settings after the card was shown (less_categories: Sweets & Snacks): that stays
    changed = ran["group_remembered"]
    assert [c[0] for c in changed["calls"]] == ["GET settings", "PATCH settings"]
    assert changed["guidance"] == {"like_categories": ["Fruits"], "less_categories": ["Sweets & Snacks", "Fish & Seafood"],
                                   "exclude_categories": ["Beverages"], "carb_tolerance_g": 12, "enabled": True}
    assert changed["calls"][1][1] == {"guidance": changed["guidance"]}  # the whole object, not one field
    # and between Remember and Undo another list was edited: Undo changes only this group
    back = ran["group_undone"]
    assert back["guidance"] == {"like_categories": ["Fruits", "Vegetables"], "less_categories": ["Sweets & Snacks"],
                                "exclude_categories": ["Beverages"], "carb_tolerance_g": 12, "enabled": True}
    assert back["lines"][-1] == "Undone. Fish & Seafood (food group) is back to: not set."


def test_a_group_moves_between_the_three_lists_and_clear_removes_it_from_all(ran):
    assert ran["group_liked"]["guidance"]["like_categories"] == ["Fish & Seafood"] and ran["group_liked"]["guidance"]["exclude_categories"] == []
    assert ran["group_back_to_never"]["guidance"]["exclude_categories"] == ["Fish & Seafood"]
    assert ran["group_back_to_never"]["guidance"]["like_categories"] == []
    assert ran["group_cleared"]["guidance"] == {"like_categories": [], "less_categories": [], "exclude_categories": [],
                                                "carb_tolerance_g": 10, "enabled": True}


def test_an_unreadable_setting_changes_nothing(ran):
    assert ran["unreadable"]["calls"] == [["GET settings"]]
    assert ran["unreadable"]["lines"][-1] == "Something went wrong"


def test_the_thread_the_model_reads_says_what_happened_in_the_apps_words(ran):
    assert ran["thread_after_undo"] == ["user: I do not really like salmon", f"assistant: The change to {SALMON} was undone.", "user: thanks"]


def test_the_calls_go_through_the_apps_shared_api_and_the_card_uses_no_model_words_as_labels():
    assert "foodPreferences: () => request('GET', '/api/guidance/preferences')," in CORE_JS
    assert "setFoodPreference: (foodId, b) => request('PUT', `/api/guidance/preferences/${encodeURIComponent(foodId)}`, b)," in CORE_JS
    assert "clearFoodPreference: (foodId) => request('DELETE', `/api/guidance/preferences/${encodeURIComponent(foodId)}`)," in CORE_JS
    taste = ASK_JS[ASK_JS.index("// ---- tastes"):ASK_JS.index("  // Wiring\n")]
    code = re.sub(r"^\s*//.*$|\s//\s.*$", "", taste, flags=re.MULTILINE)
    assert not re.search(r"\bfetch\(|(?<![\w.])request\(|['\"`]/api/", code)  # the page uses KH.api, like every screen
    for call in ("KH.api.foodPreferences()", "KH.api.setFoodPreference(", "KH.api.clearFoodPreference(", "KH.api.mySettings()",
                 "KH.api.updateMySettings("):
        assert call in code, call
    for banned in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "setAttribute('on", "style:", "localStorage"):
        assert banned not in code, banned
    # the buttons are fixed words, never the card's or the model's text
    assert "button('Remember', 'primary'" in code and "button('Cancel', 'secondary'" in code and "button('Undo', 'secondary'" in code
    assert "answer.pending_save.tool === TASTE_TOOL" in ASK_JS and "const TASTE_TOOL = 'set_food_preference';" in ASK_JS
    assert ".ask-taste-line {" in ASK_CSS
