"""Handbook topics and the tips table (note 06 §4.15, §4.5; note 08 §4.10). Pure data.

One mapping keeps rules, insights, tips and the optional AI layer citing the same handbook pages.
The slugs are note 06's; the URLs are the final ``/learn/...`` paths of note 08 §4.10 (ARCHITECTURE
v0.3 decision 12: links into the handbook use ``/learn/...``). ``tests/guidance/test_topics.py``
checks that every URL is an existing page in ``handbook/docs`` (by path and front-matter ``slug``)
with the same title, and that every slug used by a tip, a swap tip or an insight has an entry.

Tip texts are maintainer-written and reviewed against ``docs/diet-guide.md`` (§2, §4, §5) and the
handbook page they link to. They follow the wording rules of ``messages.py``: plain English, numbers
with every qualitative word, no insulin, doses, medicines or lab values.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

LEARN_PREFIX = "/learn/"

# slug -> (path under /learn/, title). Titles equal the handbook pages' front-matter titles.
_PAGES: dict[str, tuple[str, str]] = {
    "potassium": ("eat/potassium", "Potassium"),
    "potassium-leaching": ("eat/potassium-leaching", "Potassium leaching"),
    "phosphorus": ("eat/phosphorus", "Phosphorus"),
    "phosphate-additives": ("eat/phosphate-additives", "Phosphate additives"),
    "sodium": ("eat/sodium", "Sodium"),
    "fluid": ("eat/fluid", "Fluid"),
    "protein": ("eat/protein", "Protein"),
    "eating-enough": ("eat/eating-enough", "Eating enough"),
    "carb-counting": ("eat/carb-counting", "Carb counting on a kidney diet"),
    "treating-a-low": ("t1d/treating-a-low", "Treating a low"),
    "dialysis-days": ("eat/dialysis-days", "Dialysis days"),
    "label-reading": ("eat/label-reading", "Reading food labels"),
    "eating-out": ("eat/eating-out", "Eating out"),
    "portions": ("eat/portions", "Portions"),
    "sick-days": ("t1d/sick-days", "Sick days with type 1 diabetes and CKD"),
    "get-help-now": ("get-help-now", "Get help now"),
    "blood-potassium": ("labs/blood-potassium", "Blood potassium"),
    "targets-and-warnings": ("app/targets-and-warnings", "Targets and warnings"),
    "guidance": ("app/guidance", "Meal guidance"),
}

TOPIC_PAGES: dict[str, dict[str, str]] = {
    slug: {"slug": slug, "title": title, "url": f"{LEARN_PREFIX}{path}/"} for slug, (path, title) in _PAGES.items()
}

# Handbook page per nutrient (insights and tips).
NUTRIENT_TOPIC: dict[str, str] = {
    "potassium_mg": "potassium",
    "phosphorus_mg": "phosphorus",
    "sodium_mg": "sodium",
    "fluid_ml": "fluid",
    "protein_g": "protein",
    "carbs_g": "carb-counting",
    "calories_kcal": "eating-enough",
}


def page(slug: str) -> dict[str, str]:
    """``{slug, title, url}`` for a known slug (``KeyError`` for an unknown one: a programming error)."""
    return dict(TOPIC_PAGES[slug])


def pages(*slugs: str) -> list[dict[str, str]]:
    return [page(s) for s in slugs]


def _link(slug: str) -> dict[str, str]:
    entry = TOPIC_PAGES[slug]
    return {"path": entry["url"].removeprefix(LEARN_PREFIX), "title": entry["title"]}


def _named(path: str, title: str) -> dict[str, str]:
    return {"path": path, "title": title}


# What the app links to (GET /api/handbook "links"; note 08 §4.10), as paths under the handbook's base URL.
# Nutrient pages come from NUTRIENT_TOPIC above; tests/test_learn_links.py checks every path. Pure data, so the
# GitHub Pages demo (scripts/build_preview.py --pages) carries the same table without the server's packages.
APP_LINKS: dict[str, dict[str, dict[str, str]]] = {
    # Per-serving warnings and daily alerts, by nutrient key (app/nutrients.py).
    "nutrients": {nutrient: _link(slug) for nutrient, slug in NUTRIENT_TOPIC.items()},
    # Food flags that cause or change a warning (app/nutrients.py FLAGS; potassium_additive: ARCHITECTURE
    # v0.3 decision 9).
    "flags": {
        "avoid_ckd": _named("eat/food-lists/", "Food lists"),
        "phosphate_additive": _link("phosphate-additives"),
        "potassium_additive": _link("label-reading"),
        "high_gi": _link("carb-counting"),
        "hypo_treatment": _link("treating-a-low"),
    },
    # Pages the app links to by name.
    "pages": {
        "home": _named("", "Kidney Health Handbook"),
        "targets": _link("targets-and-warnings"),
        "first_setup": _named("app/first-setup/", "First setup"),
        "get_help_now": _link("get-help-now"),
        "blood_potassium": _link("blood-potassium"),
        "treating_a_low": _link("treating-a-low"),
        "ai": _named("app/ai/", "Optional AI"),  # Settings → AI ideas, "How AI help is set up" (v0.3.1)
    },
}


@dataclass(frozen=True)
class Tip:
    """One row of the tips table: ``when`` names the day-state condition evaluated by ``fits.day_tips``."""

    code: str
    when: str
    slug: str
    text: str


# Evaluated in this order; at most two are shown (§4.5).
TIPS: tuple[Tip, ...] = (
    Tip(
        "potassium_leaching", "potassium_not_ok", "potassium-leaching",
        "Potassium is at {pct} % of today's limit. Peeling, cutting small and boiling potatoes, sweet potatoes, "
        "carrots, beets or winter squash in plenty of water removes about half of their potassium.",
    ),
    Tip(
        "phosphate_additives", "phosphorus_week_not_ok", "phosphate-additives",
        "This week's phosphorus is at {pct} % of your allowance. Phosphate additives (look for \"phos\" in the "
        "ingredient list) are almost fully absorbed, so foods without them help most.",
    ),
    Tip(
        "hidden_sodium", "sodium_caution", "sodium",
        "Sodium is at {pct} % of today's limit. Most sodium comes from packaged and restaurant food, not the salt "
        "shaker; herbs, spices, lemon and vinegar add flavour without it.",
    ),
    Tip(
        "fluid_dialysis", "fluid_caution_dialysis", "fluid",
        "Fluid is at {pct} % of today's allowance. Soup, ice, ice cream, sherbet and gelatin count as fluid too; "
        "drinking from a small cup and sipping slowly helps.",
    ),
    Tip(
        "add_protein", "dialysis_protein_low", "protein",
        "Protein so far is {value} g of your {min} g minimum. On dialysis your body needs more protein, so add a "
        "protein portion such as egg, chicken or fish.",
    ),
    Tip(
        "free_foods", "meal_carbs_done", "carb-counting",
        "{Meal} already has {carbs} g of your {goal} g carbs. Foods with 5 g of carbs or less, such as green beans, "
        "cucumber or lettuce, add almost nothing.",
    ),
)

# Tips attached to swap ideas (§4.6 fallbacks).
LEACHING_TIP = Tip(
    "leaching", "swap_leaching_vegetable", "potassium-leaching",
    "Peeling, cutting small and boiling in plenty of water removes about half of the potassium from potatoes, sweet "
    "potatoes, yams, carrots, beets and winter squash; baking, roasting and frying remove none.",
)
ADDITIVES_TIP = Tip(
    "additives", "swap_phosphate_additive", "phosphate-additives",
    "This food has phosphate additives, which are almost fully absorbed. A smaller portion does not change that; "
    "a food without \"phos\" in its ingredient list does.",
)
HYPO_TIP = Tip(
    "treating_a_low", "swap_hypo", "treating-a-low",
    "Treat a low first with {dose} g of fast carbs; potassium never delays treatment. These ideas are for choosing "
    "what to keep at hand next time.",
)

ALL_TIPS: tuple[Tip, ...] = TIPS + (LEACHING_TIP, ADDITIVES_TIP, HYPO_TIP)


def tip_json(tip: Tip, **values: Any) -> dict[str, Any]:
    """``{code, text, handbook, url}`` for the API (text formatted with ``values``)."""
    return {"code": tip.code, "text": tip.text.format(**values), "handbook": tip.slug,
            "url": TOPIC_PAGES[tip.slug]["url"]}
