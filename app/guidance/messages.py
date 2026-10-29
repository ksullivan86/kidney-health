"""Every user-facing guidance string, and the number and portion formatting they use (note 06 §4.9).

Wording rules (F6, CDC Clear Communication Index items 15–16; note 04 G2/G3, V6):

* plain English, active voice, nutrient names spelled out ("potassium", not "K") for screen readers;
* whole numbers: milligrams and millilitres as integers with thousands separators, grams to one
  decimal only below 10 g, otherwise whole; every qualitative word ("high", "low", "less") comes
  with its number and, where there is one, the target;
* never "safe", "bad", "cheat", "failed", "unlimited", "don't worry"; never insulin, units, ratios,
  doses, medicines or lab values (``BANNED_PATTERN``; ``tests/guidance/test_messages.py`` lints
  every template).

Rounding is the app's display rounding (``nutrients._half_up``: half-up on the shortest decimal
form), which the demo-mode JavaScript twin already mirrors (``halfUp`` in ``js/engine/rules.js``).
"""
from __future__ import annotations

import re
from typing import Iterable, Mapping, Sequence

from ..nutrients import NUTRIENT_BY_KEY, _half_up
from . import rules as R

DISCLAIMER = "Suggestions compare foods with the targets your care team set. They are not medical advice."
AI_FALLBACK = "The AI ideas did not fit your targets today, so these are the app's own."
NO_TARGETS = (
    "Set your targets in Profile first; guidance compares foods with the targets your care team gave you."
)
DISABLED = "Meal guidance is switched off on this server."
NEEDS_CONNECTION = "Guidance needs a connection to your server."

# Words the app never uses in guidance (note 06 §4.9 and note 04 V6). Tested against every template.
BANNED_PATTERN = re.compile(
    r"\b(safe|bad|cheat|failed|unlimited|don't worry|insulin|bolus|basal|units?|ratios?|correction|doses?|dosing|"
    r"pump|binders?|sevelamer|lanthanum|calcium acetate|patiromer|zirconium|supplements?|diagnos\w*|lab results?|"
    r"as much as|no need to)\b",
    re.IGNORECASE,
)

_GLYPH = {0: "", 1: "¼", 2: "½", 3: "¾"}
_FRACTION_WORD = {0.75: "Three-quarter", 0.5: "Half", 0.25: "Quarter"}
_SIZE_WORD = {1.0: "full", 0.75: "three-quarter", 0.5: "half"}
NUTRIENT_WORD = {
    "potassium_mg": "potassium", "phosphorus_mg": "phosphorus", "sodium_mg": "sodium", "fluid_ml": "fluid",
    "carbs_g": "carbs", "protein_g": "protein", "calories_kcal": "calories",
}


# --------------------------------------------------------------------------- #
# Numbers
# --------------------------------------------------------------------------- #


def whole(value: float) -> int:
    """Half-up to an integer (the app's display rounding)."""
    return int(_half_up(float(value), 0))


def fmt_int(value: float | None) -> str:
    """``2,809``: whole number with thousands separators (mg, mL, kcal, %)."""
    if value is None:
        return "?"
    return f"{whole(value):,}"


def fmt_g(value: float | None) -> str:
    """Grams: one decimal below 10 g (``8.2``, ``0.5``), whole from 10 g (``14``, ``1,018``)."""
    if value is None:
        return "?"
    one = _half_up(float(value), 1)
    if abs(one) < 10:
        text = f"{one:.1f}"
        return text[:-2] if text.endswith(".0") else text
    return f"{whole(value):,}"


def fmt_amount(key: str, value: float | None) -> str:
    """A nutrient amount without its unit, formatted for its unit."""
    unit = NUTRIENT_BY_KEY[key].unit if key in NUTRIENT_BY_KEY else "g"
    return fmt_g(value) if unit == "g" else fmt_int(value)


def with_unit(key: str, value: float | None) -> str:
    unit = NUTRIENT_BY_KEY[key].unit
    return f"{fmt_amount(key, value)} {unit}"


def amount_text(key: str, value: float | None, partial: bool = False, unit: bool = True) -> str:
    """``600 mg``; ``at least 600 mg`` when some food does not list the nutrient (the total counts only the others);
    ``not listed`` when no food lists it. Never a 0 or a ``?`` for a value that is not there."""
    if value is None:
        return "not listed"
    text = with_unit(key, value) if unit else fmt_amount(key, value)
    return f"at least {text}" if partial else text


def amount_word(key: str, value: float | None) -> str:
    """``11 g carbs`` or ``carbs not listed``: one food's amount and the nutrient's word."""
    if value is None:
        return f"{NUTRIENT_WORD[key]} not listed"
    return f"{with_unit(key, value)} {NUTRIENT_WORD[key]}"


def pct(fraction: float) -> int:
    return whole(fraction * 100.0)


def join_and(parts: Sequence[str]) -> str:
    """``a``, ``a and b``, ``a, b and c``."""
    parts = [p for p in parts if p]
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    return ", ".join(parts[:-1]) + " and " + parts[-1]


def capitalise(text: str) -> str:
    return text[:1].upper() + text[1:] if text else text


# --------------------------------------------------------------------------- #
# Portions
# --------------------------------------------------------------------------- #


def fmt_servings(servings: float) -> str:
    """``1``, ``½``, ``1½``, ``2¼``; amounts that are not whole quarters show up to 2 decimals."""
    quarters = servings * 4.0
    q = R.js_round(quarters)
    if abs(quarters - q) < 1e-9 and q > 0:
        whole_part, rest = divmod(int(q), 4)
        head = str(whole_part) if whole_part else ""
        return (head + _GLYPH[rest]) or "0"
    text = f"{R.round_to(servings, 2):.2f}".rstrip("0").rstrip(".")
    return text


_GRAMS_SUFFIX = re.compile(r"\s*\([^()]*\)\s*$")


def short_serving(serving_desc: str) -> str:
    """``"1 cup (158 g)"`` → ``"1 cup"``: the household measure without the trailing weight."""
    short = _GRAMS_SUFFIX.sub("", serving_desc or "").strip()
    return short or (serving_desc or "").strip()


def portion_text(servings: float, serving_desc: str) -> str:
    """``"¾ × 1 cup (158 g)"`` (the JSON ``portion_text``)."""
    return f"{fmt_servings(servings)} × {serving_desc}"


def portion_short(servings: float, serving_desc: str) -> str:
    """``"¾ × 1 cup"`` (inside sentences)."""
    return f"{fmt_servings(servings)} × {short_serving(serving_desc)}"


def fraction_word(fraction: float) -> str:
    return _FRACTION_WORD.get(fraction, fmt_servings(fraction))


def size_word(scale: float) -> str:
    return _SIZE_WORD.get(scale, fmt_servings(scale))


def safe_name(name: str | None) -> str:
    """A food name for text: as typed (it may be a custom name: untrusted, shown with ``textContent``),
    whitespace collapsed, at most ``MAX_NAME_CHARS`` characters."""
    text = " ".join((name or "").split())
    if len(text) > R.MAX_NAME_CHARS:
        text = text[: R.MAX_NAME_CHARS - 1].rstrip() + "…"
    return text or "this food"


# --------------------------------------------------------------------------- #
# What fits now
# --------------------------------------------------------------------------- #


def fit_text(amounts: Mapping[str, float | None], tracked: Iterable[str], carbs_first: bool) -> str:
    """"Fits: 45 g carbs · 55 mg potassium · 70 mg phosphorus · 0 mg sodium" (tracked nutrients only); a value the food does
    not list reads "carbs not listed", never 0."""
    parts: list[str] = []
    tracked = list(tracked)
    if carbs_first:
        parts.append(amount_word(R.CARBS, amounts.get(R.CARBS)))
    for key in (R.K, R.P, R.NA, R.FLUID):
        if key in tracked:
            value = amounts.get(key)
            label = NUTRIENT_WORD[key]
            parts.append(f"{fmt_amount(key, value)} {NUTRIENT_BY_KEY[key].unit} {label}" if value is not None
                         else f"{label} not listed")
    return "Fits: " + " · ".join(parts) if parts else "Fits your targets for this meal"


def reason_text(code: str, **v: object) -> str:
    templates = {
        "adds_missing_group": "Adds the {group} this {meal} is missing",
        "fills_carbs": "Brings {meal} to {after} of your {goal} g carbs",
        "low_potassium": "Low in potassium ({k} mg)",
        "low_phosphorus": "Low in phosphorus ({p} mg)",
        "protein_quality": "{protein} g protein with little phosphorus ({ratio} mg per g)",
        "you_like": "You said you like this.",
        "you_eat_often": "You often have this",
        "free_food": "Almost no carbs ({carbs} g)",
        "half_portion": "A half portion fits; a full one would use more {nutrient} than is left for {meal}",
        "unknown": "{Nutrient} is not listed for this food; check the label",
    }
    return templates[code].format(**v)


# A note the answer adds to ``notes`` (plain sentences, like DISCLAIMER). The code is the key; the API carries the text.
NOTE_TEXTS = {
    # The low-treatment options when every one of them was marked "Not for me" (or sits in a "Never suggest" group):
    # the full list is shown, because a person treating a low must always have something to take (note 09 §8 Q1).
    "shown_despite_exclusions": "Shown although you marked them Not for me.",
}


def note_text(code: str) -> str:
    return NOTE_TEXTS[code]


def _times(n: int) -> str:
    return "once" if n == 1 else "twice" if n == 2 else f"{n} times"


def learned_reason(kind: str, *, days: int = 0, meal: str = "", planned: int = 0, eaten: int = 0) -> str:
    """The plain sentence under a "Learned from your log" item (note 09 §4.4): what the app saw, never what it "knows"."""
    if kind == "often":
        return f"Eaten on {days} of the last {R.HISTORY_DAYS} days"
    if kind == "slot":
        return f"Usually at {meal}"
    if kind == "usual_meal":
        return f"Eaten together at {meal} on {days} days"
    if kind == "planned_not_eaten":
        return f"Planned {_times(planned)} in {R.SKIP_WINDOW_DAYS} days, " + ("not eaten" if eaten == 0 else f"eaten {_times(eaten)}")
    raise KeyError(kind)


def room_line(meal: str, room: Mapping[str, object]) -> str:
    """"Left for dinner: 750 mg potassium · 167 mg phosphorus · 600 mg sodium · 60 g carbs to reach 60 g".

    A room built on a total that misses values some foods do not list (``unknown`` > 0) is an upper bound:
    "at most 750 mg potassium", and one sentence names what is not listed (note 06 R4; v0.3.0 review)."""
    parts: list[str] = []
    missing: list[str] = []
    for key in (R.K, R.P, R.NA, R.FLUID):
        item = room.get(key)
        if isinstance(item, Mapping):
            text = f"{fmt_amount(key, float(item['room']))} {NUTRIENT_BY_KEY[key].unit} {NUTRIENT_WORD[key]}"
            if int(item.get("unknown") or 0) > 0:
                text = f"at most {text}"
                missing.append(NUTRIENT_WORD[key])
            parts.append(text)
    carbs = room.get(R.CARBS)
    if isinstance(carbs, Mapping):
        gap = float(carbs["gap"])
        goal = float(carbs["goal"])
        unknown = int(carbs.get("unknown") or 0) > 0
        if gap > 0:
            parts.append(f"{'at most ' if unknown else ''}{fmt_g(gap)} g carbs to reach {fmt_g(goal)} g")
        else:
            parts.append(f"carbs at your {fmt_g(goal)} g goal")
        if unknown:
            missing.append("carbs")
    if not parts:
        return f"No targets limit {meal}"
    line = f"Left for {meal}: " + " · ".join(parts)
    if missing:
        line += f". Some foods logged today do not list {join_and(missing).replace(' and ', ' or ')}, so there may be less room"
    return line


def no_fit_text(meal: str, key: str, room: float, closest: str = "") -> str:
    unit = NUTRIENT_BY_KEY[key].unit if key in NUTRIENT_BY_KEY else "g"
    text = (f"Nothing in your foods fits {meal} within today's {NUTRIENT_WORD.get(key, key)} room "
            f"({fmt_amount(key, room)} {unit} left).")
    return f"{text} {closest}".strip()


def saved_meal_note(scale: float, carbs: float, gap: float, goal: float | None, meal: str,
                    limiting: tuple[str, float, str] | None) -> str:
    """"Fits at half size (25 g carbs, 35 g under your 60 g goal): this week's phosphorus leaves 167 mg for dinner."""
    head = f"Fits at {size_word(scale)} size"
    detail: list[str] = []
    if goal is not None:
        diff = carbs - gap
        if abs(diff) < 0.05:
            detail.append(f"{fmt_g(carbs)} g carbs, at your {fmt_g(goal)} g goal")
        else:
            word = "under" if diff < 0 else "over"
            detail.append(f"{fmt_g(carbs)} g carbs, {fmt_g(abs(diff))} g {word} your {fmt_g(goal)} g goal")
    else:
        detail.append(f"{fmt_g(carbs)} g carbs")
    text = f"{head} ({detail[0]})"
    if limiting is not None and scale < 1.0:
        key, room, basis = limiting
        period = "this week's" if basis == "week_average" else "today's"
        text += f": {period} {NUTRIENT_WORD[key]} leaves {with_unit(key, room)} for {meal}"
    return text + "."


# --------------------------------------------------------------------------- #
# Swaps
# --------------------------------------------------------------------------- #


def _less_list(deltas: Mapping[str, float], keys: Iterable[str]) -> list[str]:
    out: list[str] = []
    for key in keys:
        d = deltas.get(key)
        if d is None:
            continue
        out.append(f"{fmt_amount(key, abs(d))} {NUTRIENT_BY_KEY[key].unit} {'less' if d <= 0 else 'more'} "
                   f"{NUTRIENT_WORD[key]}")
    return out


def swap_text(match: str, name: str, servings: float, serving_desc: str, new: Mapping[str, float | None],
              old: Mapping[str, float | None], deltas: Mapping[str, float], trigger_keys: Sequence[str]) -> str:
    """``swap_carbs`` / ``swap_protein`` / ``swap_serving``."""
    head = f"{safe_name(name)} ({portion_short(servings, serving_desc)})"
    less = join_and(_less_list(deltas, trigger_keys))
    if match == "carbs":
        return (f"{head}: about the same carbs ({fmt_g(new.get(R.CARBS) or 0.0)} g vs {fmt_g(old.get(R.CARBS) or 0.0)} g)"
                + (f" and {less}" if less else ""))
    if match == "protein":
        return (f"{head}: about the same protein ({fmt_g(new.get(R.PROTEIN) or 0.0)} g vs "
                f"{fmt_g(old.get(R.PROTEIN) or 0.0)} g)" + (f", {less}" if less else ""))
    return f"{head}: {less}" if less else head


def swap_avoid_text(name: str, servings: float, serving_desc: str, new: Mapping[str, float | None], original: str) -> str:
    """"Blueberries (½ cup): 11 g carbs and 55 mg potassium, …"; a value the food does not list reads "carbs not listed"."""
    return (f"{safe_name(name)} ({portion_short(servings, serving_desc)}): {amount_word(R.CARBS, new.get(R.CARBS))} and "
            f"{amount_word(R.K, new.get(R.K))}, without the warning that {safe_name(original)} has")


def swap_hypo_text(name: str, servings: float, serving_desc: str, carbs: float, k: float | None) -> str:
    """"For your next low: Glucose tablets, 4 (1 × 4 tablets) gives 16 g carbs with 0 mg potassium" (or "…; potassium not
    listed" when the food does not list it)."""
    head = f"For your next low: {safe_name(name)} ({portion_short(servings, serving_desc)}) gives {fmt_g(carbs)} g carbs"
    return f"{head}; potassium not listed" if k is None else f"{head} with {with_unit(R.K, k)} potassium"


def portion_option_text(fraction: float, carbs: float | None, amounts: Mapping[str, float | None], keys: Sequence[str]) -> str:
    """"Half portion: 19 g carbs and 463 mg potassium. The carbs change, so count the new amount."."""
    parts = [amount_word(R.CARBS, carbs)] + [amount_word(k, amounts.get(k)) for k in keys]
    return f"{fraction_word(fraction)} portion: {join_and(parts)}. The carbs change, so count the new amount."


# --------------------------------------------------------------------------- #
# Plan
# --------------------------------------------------------------------------- #


def plan_why_carbs(carbs: float, goal: float, meal: str, gap: float, tolerance: float) -> str:
    """How the plan's carbs compare with what the meal still needs (``gap``: the goal minus what is logged).

    ``"59 g carbs, close to your 60 g dinner goal"`` within the person's tolerance;
    ``"17 g carbs, 13 g under your 30 g snack goal"`` outside it; ``"… the 30 g left of your 60 g dinner goal"``
    when part of the meal is already logged."""
    left = gap
    goal_text = f"your {fmt_g(goal)} g {meal} goal"
    if left <= 0:
        return f"{fmt_g(carbs)} g carbs: {goal_text} is already reached"
    if abs(left - goal) >= 0.05:
        goal_text = f"the {fmt_g(left)} g left of {goal_text}"
    diff = carbs - left
    if abs(diff) <= tolerance + 1e-9:
        return f"{fmt_g(carbs)} g carbs, close to {goal_text}"
    word = "under" if diff < 0 else "over"
    return f"{fmt_g(carbs)} g carbs, {fmt_g(abs(diff))} g {word} {goal_text}"


def plan_why_room(used: float, room: float, meal: str, key: str = R.K) -> str:
    """"Uses 179 of the 750 mg potassium left for dinner"."""
    unit = NUTRIENT_BY_KEY[key].unit
    return f"Uses {fmt_amount(key, used)} of the {fmt_amount(key, room)} {unit} {NUTRIENT_WORD[key]} left for {meal}"


def usual_meal_name(meal: str, short_names: Sequence[str]) -> str:
    """"Your usual lunch: chicken, rice and green beans"."""
    return f"Your usual {meal}: {join_and(list(short_names))}"


def energy_note_text(kcal: float, goal: float) -> str:
    return (f"This plan has about {fmt_int(kcal)} kcal of your {fmt_int(goal)} kcal goal. Close the gap with fat, such "
            "as olive oil or unsalted butter on food, or a measured extra starch, not with more meat, which adds "
            "protein and phosphorus.")


def partial_text(meal: str, key: str) -> str:
    return (f"This {meal} plan was cut back, but today's {NUTRIENT_WORD[key]} would still go over your limit; "
            "choose a smaller portion or a different food.")


# --------------------------------------------------------------------------- #
# Treating a low (note 04 G7; diet guide §4 "Treating a low on a kidney diet")
# --------------------------------------------------------------------------- #


def treating_a_low_card(dose_g: int | float) -> dict[str, object]:
    """The rule-based "Treating a low" card shown instead of any AI call (note 04 G7) and with low
    treatments. Facts as in the handbook page ``t1d/treating-a-low`` and the diet guide §4 (ADA 2026
    Rec 6.15/6.16); the grams are the person's own setting (``hypo_dose_g``, from their diabetes team)."""
    dose = fmt_g(float(dose_g))
    return {
        "title": "Treating a low",
        "lines": [
            f"If your glucose is below 70 mg/dL (3.9 mmol/L), take {dose} g of fast carbs now. Glucose tablets are "
            "the best choice on a kidney diet; potassium never delays treating a low.",
            f"Check again in 15 minutes. If you are still below 70 mg/dL, take another {dose} g.",
            "Skip chocolate, milk or peanut butter for the first treatment: fat slows the rise in glucose, and "
            "protein does not raise it.",
            "If someone cannot swallow safely, do not give food or drink: use their emergency glucagon if they "
            "have it and call your emergency number.",
            "Log the treatment afterwards and tick \"Used to treat a low\". It counts toward potassium, but never "
            "toward your meal carbs.",
        ],
        "handbook": "treating-a-low",
        "url": "/learn/t1d/treating-a-low/",
    }


# --------------------------------------------------------------------------- #
# Recipes that fit (note 16 §9.6)
# --------------------------------------------------------------------------- #

RECIPE_NOTES: tuple[str, ...] = (
    "Numbers are for the foods as they are listed. Cooking, soaking or draining can change what ends up on the plate, and the "
    "app does not count that.",
    "Seasonings that are not in your food list are not counted.",
)
_FIGURES = " (app figures)."


def recipe_target_label(kind: str, meal: str) -> str:
    """``this dinner's room`` or ``what is left today``."""
    return "what is left today" if kind == "day" else f"this {meal}'s room"


def _per_serving(key: str, old: float | None, new: float | None, old_partial: bool = False, new_partial: bool = False) -> str:
    return (f"{capitalise(NUTRIENT_WORD.get(key, key))} per serving: {amount_text(key, old, old_partial, unit=False)} → "
            f"{amount_text(key, new, new_partial)}")


def _partial(unknown: Mapping[str, int] | None, key: str) -> bool:
    return bool(unknown) and int(unknown.get(key, 0)) > 0  # type: ignore[union-attr]


def recipe_lowered_text(name: str, serving_desc: str, old: float, new: float, key: str, label: str,
                        old_value: float | None, new_value: float | None, old_partial: bool = False,
                        new_partial: bool = False) -> str:
    head = f"Used {portion_text(new, serving_desc)} of {safe_name(name)} instead of {portion_text(old, serving_desc)}"
    if key not in NUTRIENT_WORD:  # a share above the app's portion limits
        return f"{head}, so one serving holds a smaller portion of it."
    return f"{head}, to keep {NUTRIENT_WORD[key]} within {label}. {_per_serving(key, old_value, new_value, old_partial, new_partial)}{_FIGURES}"


def recipe_swapped_text(old_name: str, new_name: str, serving_desc: str, amount: float, key: str, label: str,
                        before: Mapping[str, float | None], after: Mapping[str, float | None],
                        before_unknown: Mapping[str, int] | None = None, after_unknown: Mapping[str, int] | None = None) -> str:
    text = f"Swapped {safe_name(old_name)} for {safe_name(new_name)}, {portion_text(amount, serving_desc)} in the whole recipe"
    if key == "avoid_ckd":
        return f"{text}, because {safe_name(old_name)} is on the app's list of foods to avoid with kidney disease."
    if key not in NUTRIENT_WORD:
        return f"{text}, because {safe_name(old_name)} does not list a value the app needs today."
    text += (f", to keep {NUTRIENT_WORD[key]} within {label}. "
             f"{_per_serving(key, before.get(key), after.get(key), _partial(before_unknown, key), _partial(after_unknown, key))}")
    if key != R.PROTEIN:
        text += (f"; protein {amount_text(R.PROTEIN, before.get(R.PROTEIN), _partial(before_unknown, R.PROTEIN), unit=False)} → "
                 f"{amount_text(R.PROTEIN, after.get(R.PROTEIN), _partial(after_unknown, R.PROTEIN))}")
    return text + _FIGURES


def recipe_smaller_text(fraction: float, key: str, label: str, full: float | None, part: float | None, room: float | None,
                        partial: bool = False) -> str:
    """``partial``: some food of the recipe does not list ``key``, so both amounts are "at least"."""
    if full is None or part is None:
        return f"Have {fmt_servings(fraction)} of a serving. No food in it lists {NUTRIENT_WORD.get(key, key)}{_FIGURES}"
    return (f"Have {fmt_servings(fraction)} of a serving: a full serving would use {amount_text(key, full, partial)} of "
            f"{NUTRIENT_WORD.get(key, key)} against {with_unit(key, room)} of room; {fmt_servings(fraction)} uses "
            f"{amount_text(key, part, partial)}{_FIGURES}")


def recipe_no_fit_text(label: str, over: Mapping[str, object] | None, partial: bool = False) -> str:
    text = f"This recipe does not fit {label} after lowering amounts, swaps and a ½ serving."
    if over is not None:
        key = str(over["nutrient"])
        text += (f" Still over: {NUTRIENT_WORD.get(key, key)} {amount_text(key, over['used'], partial)} against "  # type: ignore[arg-type]
                 f"{with_unit(key, over['room'])} of room")  # type: ignore[arg-type]
        return text + _FIGURES
    return text
