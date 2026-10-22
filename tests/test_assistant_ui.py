"""Settings → Assistant access: the second tick, "Also let it remember tastes (likes and dislikes)" (note 09 §4.8b;
``app/static/js/views/settings.js``, ``app/auth/api_tokens.py``).

The new-token form and the token list are run in Node against a tiny fake page and a fake server (``tests/js/assistant_page.mjs``):
the two ticks are separate and both off by default, what Create sends for each of the four combinations, and what the list says a
token can do. The rest is the source of the view: the activity list's label and wording for ``assistant.preference_set``. The
server side of the tick is ``tests/test_mcp_prefs.py``; the older "Can also save food and recipes" tick is also pinned in
``tests/test_settings_ui.py``.
"""
from __future__ import annotations

import json
import subprocess
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SETTINGS_JS = (ROOT / "app" / "static" / "js" / "views" / "settings.js").read_text(encoding="utf-8")
PAGE = ROOT / "tests" / "js" / "assistant_page.mjs"


@lru_cache(maxsize=1)
def page() -> dict:
    done = subprocess.run(["node", str(PAGE)], capture_output=True, text=True, timeout=60, check=False)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_the_form_has_two_separate_ticks_both_off_by_default():
    form = page()["form"]
    assert form["ticks"] == [["set-token-can-log", False, "set-token-can-log-hint"], ["set-token-can-prefs", False, "set-token-can-prefs-hint"]]
    assert form["labels"] == ["Can also save food and recipes", "Also let it remember tastes (likes and dislikes)"]
    assert form["distinct"] is True


def test_the_tick_says_what_it_allows_and_that_a_low_is_never_touched():
    hint = page()["form"]["hints"]["prefs"]
    assert hint.startswith("Off: the assistant cannot change your food preferences. On: it can remember that you like a food or kind of food")
    assert "want it less often or do not want it, and forget one, after it asks you" in hint
    assert "It cannot change anything about treating a low." in hint
    assert "Settings → Meal guidance → Your food preferences" in hint and "each change is listed in your activity" in hint
    assert "allerg" not in hint.lower()  # a taste is not an allergy; the settings do not blur the two
    assert "remember your tastes (likes and dislikes)" in page()["form"]["intro"]
    assert "save food and recipes" not in hint  # the tick for tastes gives no saving, and the text does not suggest it


def test_create_sends_each_choice_as_its_own_boolean_and_never_a_scope():
    sent = page()["sent"]
    assert [s["ticked"] for s in sent] == [[False, False], [True, False], [False, True], [True, True]]
    for entry in sent:
        [[name, body]] = entry["calls"]
        log, prefs = entry["ticked"]
        assert name == "createToken" and body == {"name": "Hermes", "expires_in_days": 90, "can_log": log, "can_prefs": prefs}
        assert "scopes" not in body  # the server decides the scopes from the two booleans


def test_the_list_says_read_only_read_and_save_read_and_tastes_or_all_three():
    assert page()["words"] == {"read": "Read only", "log": "Read and save", "prefs": "Read and tastes",
                               "both": "Read, save and tastes", "nothing": "Read only"}
    assert "Hermes Read and tastes · kha_AbCd1234…" in page()["listed"]


def test_the_activity_list_names_what_the_assistant_remembered_in_the_preference_screens_words():
    assert "'assistant.preference_set': 'Assistant remembered a taste'" in SETTINGS_JS
    assert ("if (ev.action === 'assistant.preference_set') return `${d.name}: ${tasteWord(d.old, d.kind)} → "
            "${tasteWord(d.new, d.kind)}, with “${d.via}”`;") in SETTINGS_JS
    assert ("const TASTE_WORD = { none: 'nothing saved', like: 'more like this', less: 'less often', not_for_me: 'not for me', "
            "neutral: 'stop learning' };") in SETTINGS_JS
    assert "kind === 'group' && value === 'not_for_me' ? 'never suggest'" in SETTINGS_JS  # a group's "Not for me" is "Never suggest"
    assert "can_prefs: canPrefs.checked" in SETTINGS_JS
