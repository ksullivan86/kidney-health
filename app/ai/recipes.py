"""AI recipes (note 16 §8): suggest a recipe, or rework one of the person's own, from foods the rules offered. The app does every
number. Pure apart from the guidance context the caller loaded.

* :func:`recipe_candidates`: the foods the model may use (§8.3). Like meal ideas, but a food flagged ``ingredient`` may be used
  (a recipe needs oil and flour), each food is judged at ¼, ½ and 1 serving so a food that is fine in a share is kept, and a
  short list the AI never adds (table salt, salt substitutes) is left out. Low treatments, alcohol, supplies, hidden and
  ``avoid_ckd`` foods and the person's "Not for me" choices are never candidates.
* :func:`prepare_recipes`: the exact request (the dry run shows it). It sends the person block, the targets, today's totals, the
  room, the candidates and the request; to rework a recipe, its foods and pot amounts and the app's findings. **Never** the
  recipe's name, note, steps or link.
* :func:`judge_recipes`: the checks of §8.5. The model gives foods and pot amounts in quarter servings and nothing else that
  becomes a number. The app merges duplicates, drops what is not a candidate, out of range or excluded, works out one serving
  from the food rows, runs the fit engine (:func:`app.guidance.recipes.fit_recipe`) and drops what still does not fit. A share
  that is only too big (more than 3 servings of a food in one serving) goes through the fit too, which makes it smaller; the
  card then carries :data:`PORTION_LOWERED_TEXT` and the answer lists it under ``portions_lowered``. The
  title comes from a template, the "why" sentence from the app's own reason texts, checked against the final numbers. Steps
  are kept only with ``ai.recipe_steps`` on and only after :mod:`app.ai.recipe_steps`; a swap by the app drops them.
"""
from __future__ import annotations

import re
from typing import Any, Mapping, Sequence

from ..guidance import messages as M
from ..guidance import rules as R
from ..guidance.ai_bridge import _per_portion
from ..guidance.budget import open_slots
from ..guidance.fits import room_json, scaled, short_names
from ..guidance.recipes import Target, fit_recipe, room_for
from ..guidance.score import Counter, Scorer, habit_stats, today_stats
from ..guidance.state import GuidanceContext
from ..guidance.vectors import FoodVec, renal_level
from . import guard, prompts, recipe_steps, schemas
from .client import ProviderConfig, build_body

RECIPE_PORTIONS: tuple[float, ...] = (0.25, 0.5, 1.0)  # a candidate is kept if one of these shares passes
AI_RECIPE_FOODS_MAX = 48
AI_RECIPE_INGREDIENTS_MIN = 4
COOK_LATER = frozenset({"Beverages", "Sweets & Snacks", "Prepared & Fast Food"})  # categories a recipe rarely starts from
# Foods the AI never adds, by name: table salt, and any salt substitute (a potassium salt). Grown from the golden set.
NEVER_ADD = re.compile(r"\b(?:salt|salt substitutes?|salt replacers?|potassium chloride|lo-?salt|nu-?salt|no-?salt|lite salt)\b",
                       re.IGNORECASE)
NOTICE = "AI recipe · {label} · {model} · checked against your targets · not medical advice"
NO_FIT_TEXT = "The AI found no recipe that fits your targets for this meal."
DROPPED_ALL_TEXT = "The AI's recipes did not fit your targets, so none are shown."
# Under an AI recipe whose too-big share the fit made smaller (``portions_lowered``), worded like the meal ideas' note.
PORTION_LOWERED_TEXT = "The app made a portion smaller so the recipe fits your targets."
PORTIONS_LOWERED_TEXT = "The app made some portions smaller so the recipe fits your targets."
# When the fit swapped a too-big food out (``to_servings`` 0) the note says so, since nothing was only made smaller.
FOOD_SWAPPED_TEXT = "The app changed a food so the recipe fits your targets."
def portion_note(changes: list[dict]) -> str | None:
    """The sentence under a recipe whose too-big share the fit repaired, or None when nothing was repaired."""
    if not changes:
        return None
    if any(c["to_servings"] == 0 for c in changes):
        return FOOD_SWAPPED_TEXT
    return PORTION_LOWERED_TEXT if len(changes) == 1 else PORTIONS_LOWERED_TEXT


NOT_SENT_TEXT = ("This recipe has a food the app never sends to AI, so it cannot be reworked. Fit to my targets still works "
                 "without AI.")
DISH_WORD = {"soup": "soup", "stew": "stew", "bowl": "bowl", "stir_fry": "stir-fry", "bake": "bake", "salad": "salad",
             "sandwich": "sandwich", "pasta": "pasta", "rice_dish": "rice dish", "egg_dish": "egg dish", "porridge": "porridge",
             "snack": "snack", "drink": "drink"}
RECIPE_KEYS = frozenset({"dish", "theme", "ingredients", "steps", "reason_codes"})
NAME_MAX = 80  # a saved meal's name (app/models.py)


# --------------------------------------------------------------------------- #
# Candidates (§8.3)
# --------------------------------------------------------------------------- #


def recipe_ineligible(f: FoodVec, ctx: GuidanceContext) -> str | None:
    """Why ``f`` is never a food of an AI recipe, or None. Unlike meal ideas, an ``ingredient`` may be one."""
    if f.hidden:
        return "hidden"
    if f.avoid:
        return "avoid_ckd"
    if f.hypo:
        return "hypo_treatment"
    if f.alcohol:
        return "alcohol"
    if f.supplies:
        return "diabetes_supplies"
    if f.id in ctx.prefs.exclude_food_ids:
        return "not_for_me"
    if (f.category or "") in ctx.prefs.exclude_categories:
        return "excluded_category"
    if NEVER_ADD.search(guard.fold(f.name or "")):
        return "never_added"
    return None


def recipe_candidates(ctx: GuidanceContext, target: Target, extra: Sequence[FoodVec] = (),
                      exclude: frozenset[int] = frozenset()) -> dict[str, Any]:
    """The rule result for an AI recipe: up to :data:`AI_RECIPE_FOODS_MAX` foods that pass at ¼, ½ or 1 serving, ranked by the
    "What fits now" score: at least :data:`AI_RECIPE_INGREDIENTS_MIN` ingredients, then one food of each cooking category in turn,
    then drinks, sweets, ready meals and processed foods if there is room, plus ``extra`` (the foods of a recipe to rework) when they may be sent. Each candidate's numbers are
    for one serving of the food."""
    room = room_for(ctx, target)
    counter = Counter()
    scorer = Scorer(room, habit_stats(ctx), today_stats(ctx.day), counter)
    habit = scorer.habit
    ranked: list[tuple[float, FoodVec]] = []
    for f in ctx.foods.values():
        if recipe_ineligible(f, ctx) is not None or (f.id in exclude and not f.ingredient):
            continue  # ``exclude``: main foods of recipes already shown ("Other recipes"); oil, flour and the like stay
        best, _ = scorer.best_portion(f, RECIPE_PORTIONS)
        if best is None:
            continue
        ranked.append((best.score or 0.0, f))
    ranked.sort(key=lambda pair: (-pair[0], pair[1].name.casefold(), pair[1].id))
    picked: list[FoodVec] = []
    ingredients = 0
    for _, f in ranked:  # enough ingredients first: a recipe needs oil and flour …
        if ingredients >= AI_RECIPE_INGREDIENTS_MIN:
            break
        if f.ingredient:
            picked.append(f)
            ingredients += 1
    by_category: dict[str, list[FoodVec]] = {}
    later: list[FoodVec] = []
    for _, f in ranked:
        if f in picked:
            continue
        if f.processed or (f.category or "") in COOK_LATER:
            later.append(f)
        else:
            by_category.setdefault(f.category or f.group, []).append(f)
    # … then one food of each cooking category in turn, best first, so grains cannot crowd out the vegetables; drinks, sweets,
    # ready meals and processed foods only fill what is left.
    categories = sorted(by_category)
    while len(picked) < AI_RECIPE_FOODS_MAX and any(by_category[c] for c in categories):
        for c in categories:
            if by_category[c] and len(picked) < AI_RECIPE_FOODS_MAX:
                picked.append(by_category[c].pop(0))
    picked += later[:max(0, AI_RECIPE_FOODS_MAX - len(picked))]
    order = {f.id: i for i, (_, f) in enumerate(ranked)}
    picked = sorted(picked[:AI_RECIPE_FOODS_MAX], key=lambda f: order[f.id])
    for f in extra:
        if recipe_ineligible(f, ctx) is None and all(p.id != f.id for p in picked):
            picked.append(f)
    foods = []
    for i, f in enumerate(picked, start=1):
        a = scaled(f, 1.0)
        foods.append({"ref": f"f{i}", "food_id": f.id, "group": f.group, "portion": 1.0, "per_portion": _per_portion(f, 1.0),
                      "renal_rating": renal_level(a[R.K], a[R.P], a[R.NA], f.additive), "reasons": [],
                      "liked": f.id in habit.pref.liked, "often": habit.days_14.get(f.id, 0) >= R.OFTEN_MIN_DAYS})
    return {"room": room_json(room), "levels": {k: v.level for k, v in room.nutrients.items()}, "foods": foods,
            "meal": room.meal}


# --------------------------------------------------------------------------- #
# The request
# --------------------------------------------------------------------------- #


def quarters_of(servings: float) -> int:
    return max(1, min(schemas.MAX_RECIPE_QUARTERS, int(round(float(servings) * 4))))


def prepare_recipes(ctx: GuidanceContext, cfg: ProviderConfig, *, target: Target, person: Mapping[str, Any], mode: str,
                    dish: str | None, makes: float, steps: bool, recipe: Sequence[tuple[FoodVec, float]] = (),
                    name: str | None = None, exclude: frozenset[int] = frozenset()) -> Any:
    """Build the AI recipes call (note 16 §8.2). ``recipe`` and ``name`` are the person's recipe in mode ``change``: its foods and
    pot amounts are sent, its name never is (the app adds "(reworked)" to it on the card)."""
    from .features import ContextTooSmall, Prepared, _fits

    if mode == "change" and any(f.hypo for f, _ in recipe):
        raise ValueError("a recipe with a low-treatment food is never sent to AI")
    bridge = recipe_candidates(ctx, target, [f for f, _ in recipe], exclude)
    meal = target.meal if target.kind == "meal" and target.meal else bridge["meal"]
    meals_left = list(open_slots(meal, ctx.day)) if target.kind == "meal" else []
    request: dict[str, Any] = {"mode": mode, "makes": makes}
    if mode == "suggest":
        request["dish"] = dish
    block = None
    original: list[tuple[FoodVec, float]] = list(recipe)
    if mode == "change":
        before = fit_recipe(ctx, original, makes, target)["before"]
        sendable = [(f, q) for f, q in original if any(int(c["food_id"]) == f.id for c in bridge["foods"])]
        block = {"ref": "r1", "makes": makes, "ingredients": [{"id": f.id, "quarters": quarters_of(q)} for f, q in sendable],
                 "findings": [{"nutrient": c["nutrient"], "per_serving": c["used"], "room": c["room"], "ok": c["ok"]}
                              for c in before["checks"]]}
    keep = {f.id for f, _ in original}
    trimmed = 0
    max_recipes = 1 if mode == "change" else schemas.MAX_RECIPES
    while True:
        data = prompts.recipe_context(bridge, ctx, meal=meal if target.kind == "meal" else "day", meals_left=meals_left,
                                      person=person, request=request, recipe=block)
        ids = sorted(int(f["food_id"]) for f in bridge["foods"])
        schema = schemas.recipes_schema(ids, steps=steps, max_recipes=max_recipes)
        task = "recipes_change" if mode == "change" else "recipes_suggest"
        body = build_body(cfg, system=prompts.recipe_system_prompt(person, steps=steps),
                          user_text=prompts.user_message(task, data, mode=cfg.structured, schema=schema),
                          schema=schema, schema_name="kidney_recipes", mode=cfg.structured)
        if _fits(cfg, body):
            break
        removable = [i for i, f in enumerate(bridge["foods"]) if int(f["food_id"]) not in keep]
        if len(removable) <= 1:
            raise ContextTooSmall("the prompt does not fit AI_CONTEXT_TOKENS even with the fewest candidates")
        foods = list(bridge["foods"])
        del foods[removable[-1]]  # the lowest-ranked food that is not the recipe's own
        bridge = {**bridge, "foods": foods}
        trimmed += 1

    def judge(answer: schemas.RecipesAnswer) -> dict[str, Any]:
        return judge_recipes(answer.model_dump(), ctx, target, bridge, mode=mode, makes=makes, steps=steps, original=original,
                             name=name, provider_label=cfg.label, model=cfg.model)

    return Prepared(feature="recipes", cfg=cfg, body=body, validator=schemas.model_validator_for(schemas.RecipesAnswer),
                    judge=judge, mode=mode, trimmed=trimmed, notes=list(M.RECIPE_NOTES) + [M.DISCLAIMER])


# --------------------------------------------------------------------------- #
# The checks on the answer (§8.5)
# --------------------------------------------------------------------------- #


def label(provider_label: str, model: str) -> dict[str, Any]:
    return {"source": "ai", "provider_label": provider_label, "model": model, "checked": True,
            "notice": NOTICE.format(label=provider_label, model=model)}


def _ingredients(raw: Mapping[str, Any]) -> tuple[list[tuple[int, int]] | None, str | None]:
    items = raw.get("ingredients")
    if not isinstance(items, list):
        return None, "malformed_recipe"
    merged: dict[int, int] = {}
    for it in items:
        if not isinstance(it, Mapping) or set(it) - {"food_id", "quarters"}:
            return None, "malformed_item"
        fid, quarters = it.get("food_id"), it.get("quarters")
        if not isinstance(fid, int) or isinstance(fid, bool) or not isinstance(quarters, int) or isinstance(quarters, bool):
            return None, "malformed_item"
        merged[fid] = merged.get(fid, 0) + quarters
    return list(merged.items()), None


def title_for(items: Sequence[tuple[FoodVec, float]], dish: str) -> str:
    """The card's title (§8.6): the short names of the one or two foods with the most grams that are not ingredients, and the
    word for the dish. A template, never the model's words."""
    mains = [(f, q) for f, q in items if not f.ingredient] or list(items)
    mains.sort(key=lambda fq: (-(fq[0].serving_g or 0.0) * fq[1], fq[0].name.casefold(), fq[0].id))
    names = [n[:30].strip() for n in short_names([f.name for f, _ in mains[:2]])]
    word = DISH_WORD.get(dish, "dish")
    text = " and ".join(dict.fromkeys(n for n in names if n))
    if word not in text.split():
        text = f"{text} {word}".strip()
    text = text[:1].upper() + text[1:]
    return text[:NAME_MAX]


def differences(original: Sequence[tuple[FoodVec, float]], new: Sequence[Mapping[str, Any]], foods: Mapping[int, FoodVec]) -> list[str]:
    """Mode ``change``: what differs from the person's recipe (foods added, removed, amounts changed), worked out by comparing the
    two lists; the model gives no account of its own."""
    before: dict[int, float] = {}
    for f, q in original:
        before[f.id] = before.get(f.id, 0.0) + float(q)
    after = {int(i["food_id"]): float(i["servings"]) for i in new}
    lines: list[str] = []
    for fid, q in after.items():
        f = foods[fid]
        if fid not in before:
            lines.append(f"Added {M.safe_name(f.name).lower()}: {M.portion_text(q, f.serving_desc)}.")
        elif abs(before[fid] - q) > 1e-9:
            lines.append(f"{M.safe_name(f.name)}: {M.portion_text(q, f.serving_desc)} instead of "
                         f"{M.portion_text(before[fid], f.serving_desc)}.")
    for f, _ in original:
        if f.id not in after and f"Took out {M.safe_name(f.name).lower()}." not in lines:
            lines.append(f"Took out {M.safe_name(f.name).lower()}.")
    return lines


def judge_recipes(answer: Mapping[str, Any], ctx: GuidanceContext, target: Target, bridge: Mapping[str, Any], *, mode: str,
                  makes: float, steps: bool, original: Sequence[tuple[FoodVec, float]] = (), name: str | None = None,
                  provider_label: str, model: str) -> dict[str, Any]:
    """V3 to V9 for AI recipes. ``answer`` is the V2-checked object (``status``, ``refusal``, ``recipes``)."""
    if answer.get("status") == "refused":
        return {"status": "refused", "message": guard.REFUSED_TEXT, "recipes": [], "dropped": [], "portions_lowered": [],
                "claims_corrected": 0, "steps_dropped": 0}
    candidates = {int(f["food_id"]) for f in bridge.get("foods", [])}
    often, liked = guard.often_ids(bridge), guard.liked_ids(bridge)
    room = room_for(ctx, target)
    meal = target.meal if target.kind == "meal" and target.meal else room.meal
    limit = 1 if mode == "change" else schemas.MAX_RECIPES
    raw_recipes = list(answer.get("recipes") or [])
    shown: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    lowered: list[dict[str, Any]] = []
    corrected_total = 0
    steps_dropped_total = 0
    for index, raw in enumerate(raw_recipes):
        if index >= limit:
            dropped.append({"index": index, "reason": "too_many_recipes"})
            continue
        if not isinstance(raw, Mapping):
            dropped.append({"index": index, "reason": "malformed_recipe"})
            continue
        if set(raw) - RECIPE_KEYS:
            dropped.append({"index": index, "reason": "unexpected_field"})  # a title or a "why" is free text the schema does not allow
            continue
        merged, error = _ingredients(raw)
        if error or merged is None:
            dropped.append({"index": index, "reason": error or "malformed_recipe"})
            continue
        reason = None
        if not schemas.MIN_RECIPE_ITEMS <= len(merged) <= schemas.MAX_RECIPE_ITEMS:
            reason = "too_many_items" if len(merged) > schemas.MAX_RECIPE_ITEMS else "too_few_items"
        items: list[tuple[FoodVec, float]] = []
        too_big: list[tuple[int, float]] = []  # (food id, share): more than 3 servings in one serving, for the fit to make smaller
        for fid, quarters in merged:
            if reason is not None:
                break
            food = ctx.foods.get(fid)
            if fid not in candidates or food is None:
                reason = "not_a_candidate"
            elif not 1 <= quarters <= schemas.MAX_RECIPE_QUARTERS:
                reason = "quarters_out_of_range"
            else:
                why = recipe_ineligible(food, ctx)
                if why in guard.NOT_FOR_ME_REASONS:
                    reason = why
                elif why is not None:
                    reason = "excluded_category" if why == "never_added" else "not_a_candidate"
                else:
                    items.append((food, quarters / 4.0))
                    if quarters / 4.0 / makes > R.PORTION_MAX + 1e-9:
                        too_big.append((fid, quarters / 4.0 / makes))
        if reason is not None:
            dropped.append({"index": index, "reason": reason})
            continue
        # The fit is the one gate: it makes a too-big share smaller (``portion_out_of_range``) as it lowers anything else, and
        # every check of check_meal runs again on what it gives back.
        fit = fit_recipe(ctx, items, makes, target)
        if fit["status"] == "does_not_fit":
            closest = fit["closest"]
            still_big = any(float(i["servings"]) / makes * float(closest["serving_fraction"]) > R.PORTION_MAX + 1e-9
                            for i in closest["items"])
            over = (fit.get("still_over") or ["portion"])[0]
            dropped.append({"index": index, "reason": "share_too_large" if still_big else f"would_exceed:{over}"})
            continue
        fitted = fit["fitted"]
        fraction = float(fitted["serving_fraction"])
        final = [(ctx.foods[int(i["food_id"])], float(i["servings"])) for i in fitted["items"]]
        one_serving = [(f, q / makes * fraction) for f, q in final]
        # A food the fit swapped out is at 0: the fit's own change lines say what came in.
        portion_changes = [{"food_id": fid, "from_servings": R.round_to(was, 2),
                            "to_servings": R.round_to(sum(q for f, q in one_serving if f.id == fid), 2)} for fid, was in too_big]
        if portion_changes:
            lowered.append({"index": index, "reason": "share_too_large", "changes": portion_changes})
        codes, corrected = guard.check_claims([c for c in raw.get("reason_codes") or [] if isinstance(c, str)], one_serving, room,
                                              often, liked)
        theme_claim = raw.get("theme") if raw.get("theme") in schemas.THEMES else "light"
        theme = guard.true_theme(one_serving, theme_claim, often)
        corrected += int(theme != theme_claim)
        corrected_total += corrected
        swapped = any(c.get("code") == "swapped" for c in fit["changes"])
        raw_steps = [s for s in raw.get("steps") or []]
        kept: list[str] = []
        step_drops: list[dict[str, Any]] = []
        if not steps:
            step_drops = [{"index": i, "reason": "steps_off"} for i in range(len(raw_steps))]
        elif swapped:
            step_drops = [{"index": i, "reason": "foods_changed"} for i in range(len(raw_steps))]
        else:
            kept, step_drops = recipe_steps.check_steps(raw_steps, [f.name for f, _ in items])
        steps_dropped_total += len(step_drops)
        dish = raw.get("dish") if raw.get("dish") in DISH_WORD else "bowl"
        title = (f"{name[:NAME_MAX - 12]} (reworked)" if mode == "change" and name else title_for(final, dish))
        servings_made = R.round_to(makes / fraction, 2)
        card = {
            **label(provider_label, model),
            "index": index,
            "dish": dish,
            "theme": theme,
            "title": title,
            "reason_codes": codes,
            "why": guard.sentence(codes, meal, one_serving),
            "makes": makes,
            "fit": {k: fit[k] for k in ("status", "before", "after", "changes", "still_over")},
            "fitted": fitted,
            "items": fitted["items"],
            "per_serving": fit["after"]["per_serving"],
            "unknown": fit["after"]["unknown"],
            "steps": kept,
            "steps_label": recipe_steps.STEPS_LABEL if kept else None,
            "steps_note": recipe_steps.STEPS_REMOVED_TEXT if swapped and raw_steps and steps else None,
            "steps_dropped": step_drops,
            "differences": differences(original, fitted["items"], ctx.foods) if mode == "change" else [],
            "portions_lowered": portion_changes,
            "portion_note": portion_note(portion_changes),
            # The exact body for POST /api/meals: the person saves it with a tap, and every rule runs again there. A smaller serving
            # is kept by counting more servings in the same pot, so one serving is the fitted size.
            "body": {"name": title, "meal_hint": meal if target.kind == "meal" else None, "servings_made": servings_made,
                     "items": [{"food_id": int(i["food_id"]), "servings": float(i["servings"])} for i in fitted["items"]],
                     "steps": kept},
        }
        shown.append(card)
    if not shown:
        status = "no_fit" if answer.get("refusal") == "no_fit" and not raw_recipes else "dropped_all"
        return {"status": status, "message": NO_FIT_TEXT if status == "no_fit" else DROPPED_ALL_TEXT, "recipes": [],
                "dropped": dropped, "portions_lowered": lowered, "claims_corrected": corrected_total,
                "steps_dropped": steps_dropped_total}
    return {"status": "ok", "recipes": shown, "dropped": dropped, "portions_lowered": lowered, "claims_corrected": corrected_total,
            "steps_dropped": steps_dropped_total}
