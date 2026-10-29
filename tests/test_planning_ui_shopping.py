"""Share or copy the shopping list (design note 22, part A): what is not ticked yet as text, through the phone's share sheet or
the clipboard, with a text box to copy by hand where the clipboard is blocked. Nothing leaves the device otherwise (static checks;
the Chromium check is in the PR)."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "app" / "static"
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")
PLAN = (STATIC / "js" / "views" / "plan.js").read_text(encoding="utf-8")
CSS = (STATIC / "css" / "plan.css").read_text(encoding="utf-8")


def test_the_buttons_and_the_text_box_are_on_the_page():
    for el in ('id="shopping-share" hidden', 'id="shopping-copy" hidden', 'id="shopping-text"'):
        assert el in INDEX, el
    assert 'aria-label="Shopping list as text"' in INDEX
    # The foot hides only when every button in it is hidden.
    assert ".shopping-foot:not(:has(> :not([hidden]))) { display: none; }" in CSS


def test_the_text_is_what_is_not_ticked_yet():
    text = PLAN[PLAN.index("function shoppingText"):PLAN.index("function showShoppingText")]
    assert "items.filter((it) => !checks.has(it.food_id))" in text
    assert "`Shopping list, ${fmtRange(sh.start, sh.end)}`" in text


def test_share_falls_back_to_copy_and_copy_to_the_text_box():
    assert "navigator.share({ title: 'Shopping list', text })" in PLAN and "e.name === 'AbortError'" in PLAN
    copy = PLAN[PLAN.index("async function copyShopping"):PLAN.index("$('#shopping-copy')")]
    assert "allowsFeature('clipboard-write')" in copy and "showShoppingText(text);" in copy
    assert "$('#shopping-share').hidden = !items.length || typeof navigator.share !== 'function';" in PLAN
