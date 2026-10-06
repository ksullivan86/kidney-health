"""Handbook links (note 06 §4.15, note 08 §4.10, ARCHITECTURE v0.3 decision 12): every topic URL is an
existing handbook page with the same slug and title, and every slug the engine cites has an entry."""
from __future__ import annotations

import re
from pathlib import Path

import fixtures as fx
from app.guidance import fits, insights, messages, swaps
from app.guidance import topics as T

DOCS = Path(__file__).resolve().parents[2] / "handbook" / "docs"
_FRONT = re.compile(r"\A---\n(.*?)\n---\n", re.S)

# Note 08 §4.10, the final slug → URL table (copied here so a change to either side fails this test).
NOTE_08_URLS = {
    "potassium": "/learn/eat/potassium/", "potassium-leaching": "/learn/eat/potassium-leaching/",
    "phosphorus": "/learn/eat/phosphorus/", "phosphate-additives": "/learn/eat/phosphate-additives/",
    "sodium": "/learn/eat/sodium/", "fluid": "/learn/eat/fluid/", "protein": "/learn/eat/protein/",
    "eating-enough": "/learn/eat/eating-enough/", "carb-counting": "/learn/eat/carb-counting/",
    "treating-a-low": "/learn/t1d/treating-a-low/", "dialysis-days": "/learn/eat/dialysis-days/",
    "label-reading": "/learn/eat/label-reading/", "eating-out": "/learn/eat/eating-out/",
    "portions": "/learn/eat/portions/", "sick-days": "/learn/t1d/sick-days/", "get-help-now": "/learn/get-help-now/",
    "blood-potassium": "/learn/labs/blood-potassium/", "targets-and-warnings": "/learn/app/targets-and-warnings/",
}


def front_matter(path: Path) -> dict[str, str]:
    match = _FRONT.match(path.read_text(encoding="utf-8"))
    assert match, f"{path} has no front matter"
    out = {}
    for line in match.group(1).splitlines():
        if ":" in line and not line.startswith((" ", "-")):
            key, value = line.split(":", 1)
            out[key.strip()] = value.strip().strip('"').strip("'")
    return out


def page_file(url: str) -> Path:
    assert url.startswith("/learn/") and url.endswith("/")
    rel = url[len("/learn/"):-1]
    for candidate in (DOCS / f"{rel}.md", DOCS / rel / "index.md"):
        if candidate.is_file():
            return candidate
    raise AssertionError(f"{url}: no handbook page at handbook/docs/{rel}.md or {rel}/index.md")


def test_every_topic_url_is_an_existing_handbook_page_with_that_slug_and_title():
    for slug, page in T.TOPIC_PAGES.items():
        meta = front_matter(page_file(page["url"]))
        assert meta.get("slug") == slug, (slug, meta.get("slug"))
        assert meta.get("title") == page["title"], (slug, meta.get("title"))
        assert page["slug"] == slug


def test_the_note_08_url_table_is_used_unchanged():
    for slug, url in NOTE_08_URLS.items():
        assert T.TOPIC_PAGES[slug]["url"] == url


def test_every_slug_the_engine_cites_has_an_entry():
    used = {tip.slug for tip in T.ALL_TIPS} | set(T.NUTRIENT_TOPIC.values())
    used |= set(fits._REASON_TOPIC.values()) | {s for s in fits._GROUP_TOPIC.values() if s}
    used |= {messages.treating_a_low_card(15)["handbook"], "label-reading", "dialysis-days", "treating-a-low"}
    for slug in sorted(used):
        assert slug in T.TOPIC_PAGES, slug
    # Insight handbook links come out of the engine as page objects with known slugs.
    r = insights.day_insights(fx.context())
    for i in r["insights"]:
        for page in i["handbook"]:
            assert page == T.TOPIC_PAGES[page["slug"]]


def test_card_and_tip_links_point_at_learn_pages():
    card = messages.treating_a_low_card(15)
    assert card["url"] == T.TOPIC_PAGES[card["handbook"]]["url"]
    r = swaps.find_swaps(fx.context(), "dinner", fx.foods()[2], 1.0)
    for tip in r["tips"]:
        assert tip["url"] == T.TOPIC_PAGES[tip["handbook"]]["url"]


def test_unknown_slug_is_a_programming_error():
    try:
        T.page("no-such-page")
    except KeyError:
        return
    raise AssertionError("an unknown slug must raise")
