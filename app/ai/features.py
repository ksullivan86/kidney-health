"""The four AI features: what each sends, and what the person gets back (note 04 R3, R7–R9; note 03 R8,
R9; note 06 §4.13). Database reads only through the guidance context and the food search; never a write.

Each feature has a **prepare** step (pure apart from those reads: builds the exact body, the validator
and the judge) and a **judge** step (pure: turns the model's answer into the response). The routes in
:mod:`app.ai.routes` and :mod:`app.vision` run prepare, show it as the dry run or send it, then judge.

* :func:`prepare_next_meal`: modes ``ideas``, ``rerank``, ``swap`` and ``plan`` over the guidance
  engine's candidates (``app.guidance.ai_bridge.candidates_for_ai``); low treatments are never sent.
* :func:`prepare_parse_meal`: "describe a meal" text → phrases with search terms; **pre-filters** first:
  text that may describe a low gets the rule-based "Treating a low" card instead of an AI call (G7) and
  red-flag symptoms get the "Get help now" card (G8).
* :func:`prepare_read_label` (``POST /api/vision/label``): printed values only; the server converts
  salt and %DV, runs the additive scan (regex, not AI) and plausibility checks, and returns a Quick-add
  draft the person checks. It never saves.
* :func:`prepare_plate` (``POST /api/vision/plate``): food names and a rough weight; matches come from
  the app's own food search; the model never supplies a nutrient value.
"""
from __future__ import annotations

import base64
import json
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import date as _date
from typing import Any, Callable, Mapping

from ..additives import scan as scan_additives
from ..guidance import hypo
from ..guidance import rules as R
from ..guidance.ai_bridge import candidates_for_ai
from ..guidance.budget import open_slots
from ..guidance.state import GuidanceContext
from ..textclean import clean_text
from . import guard, prompts, schemas
from .client import ProviderConfig, build_body, shown_headers
from ..imagecheck import CheckedImage

Mode = str
TOKENS_PER_CHAR = 1 / 3.5  # R4 AI_CONTEXT_TOKENS: candidates are trimmed until len(json)/3.5 fits

# --------------------------------------------------------------------------- #
# Pre-filters (G7, G8)
# --------------------------------------------------------------------------- #

RED_FLAG = re.compile(
    r"\b(chest (?:pain|pressure|tight\w*)|palpitations?|heart (?:racing|pounding)|can'?t breathe|cannot breathe|"
    r"short(?:ness)? of breath|trouble breathing|struggling to breathe|confus\w*|faint\w*|passed out|collaps\w*|"
    r"muscle weakness|(?:sudden|severe) weakness|seizures?|unconscious|can'?t wake|cannot wake|"
    r"slurred speech|face droop\w*|stroke)",
    re.IGNORECASE,
)
RED_FLAG_CARD = {
    "title": "Get help now",
    "lines": [
        "Call 911 (or your local emergency number: 112 in the EU, 999 in the UK, 000 in Australia) now for chest "
        "pain, sudden breathlessness, fainting or collapse, sudden severe weakness, a seizure, new confusion or "
        "someone you cannot wake.",
        "If glucose may be low, treat the low first: potassium never delays treating a low.",
        "For anything else that worries you, call your care team today.",
        "The app's AI was not asked: it does not answer questions about symptoms.",
    ],
    "handbook": "get-help-now",
    "url": "/learn/get-help-now/",
}


def red_flag(text: str | None) -> bool:
    """G8: free text that may describe an emergency (matched after NFKC and invisible-character removal)."""
    return bool(text) and bool(RED_FLAG.search(guard.fold(text or "")))


def prefilter(text: str | None, dose_g: float) -> dict[str, Any] | None:
    """The cards to show **instead of** calling AI, or ``None`` (G7, G8). The AI is never called when this
    returns a card."""
    cards = []
    if red_flag(text):
        cards.append(dict(RED_FLAG_CARD))
    low = hypo.prefilter(text, dose_g)
    if low is not None:
        cards.append(low["card"])
    if not cards:
        return None
    return {"status": "red_flag" if red_flag(text) else "treating_a_low", "cards": cards, "ai_called": False}


# --------------------------------------------------------------------------- #
# Prepared calls
# --------------------------------------------------------------------------- #


@dataclass
class Prepared:
    """Everything one AI call needs: the body is final (the dry run shows exactly this)."""

    feature: str  # next_meal | parse_meal | read_label | plate
    cfg: ProviderConfig
    body: dict[str, Any]
    validator: Callable[[Any], Any]
    judge: Callable[[Any], dict[str, Any]]
    purpose: str = "text"  # consent purpose: text | photos
    vision: bool = False
    mode: str | None = None
    images: list[CheckedImage] = field(default_factory=list)
    fallback: dict[str, Any] | None = None
    trimmed: int = 0  # candidates removed to fit AI_CONTEXT_TOKENS

    @property
    def model(self) -> str:
        return str(self.body.get("model", ""))

    def audit_copy(self) -> dict[str, Any]:
        """The request as the AI activity log keeps it: each image replaced by its SHA-256, size and dimensions."""
        body = json.loads(json.dumps(self.body))
        images = iter(self.images)
        for message in body.get("messages", []):
            content = message.get("content")
            if isinstance(content, list):
                for i, part in enumerate(content):
                    if isinstance(part, dict) and part.get("type") == "image_url":
                        image = next(images, None)
                        content[i] = {"type": "image", **(image.audit_copy() if image else {"image_sha256": None})}
        return body

    def dry_run(self, app_version: str) -> dict[str, Any]:
        """R9 step 4: destination, headers without the key, the exact body, the image byte count."""
        body = json.loads(json.dumps(self.body))
        for message in body.get("messages", []):
            content = message.get("content")
            if isinstance(content, list):
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "image_url":
                        url = part["image_url"]["url"]
                        part["image_url"]["url"] = url.split(",", 1)[0] + f",[{len(url.split(',', 1)[1])} base64 characters]"
        return {
            "dry_run": True,
            "feature": self.feature,
            "mode": self.mode,
            "destination": self.cfg.base.endpoint("chat/completions"),
            "host": self.cfg.host,
            "provider": {"id": self.cfg.id, "label": self.cfg.label, "preset": self.cfg.preset, "scope": self.cfg.scope},
            "method": "POST",
            "headers": shown_headers(self.cfg, app_version),
            "body": body,
            "image_bytes": sum(len(i.data) for i in self.images),
            "images": [i.audit_copy() for i in self.images],
            "trimmed_candidates": self.trimmed,
        }


def _estimate_tokens(body: Mapping[str, Any]) -> int:
    return int(len(json.dumps(body, ensure_ascii=False)) * TOKENS_PER_CHAR) + 1


def _fits(cfg: ProviderConfig, body: Mapping[str, Any]) -> bool:
    return _estimate_tokens(body) + cfg.max_tokens <= cfg.context_tokens


class ContextTooSmall(ValueError):
    """Even one candidate does not fit ``AI_CONTEXT_TOKENS``."""


# --------------------------------------------------------------------------- #
# Next meal
# --------------------------------------------------------------------------- #


def prepare_next_meal(ctx: GuidanceContext, cfg: ProviderConfig, *, meal: str, mode: Mode, person: Mapping[str, Any],
                      swap: tuple[Any, float, str | None] | None = None) -> Prepared:
    """Build the next-meal call for ``mode`` from the rule result only (G5, G14).

    ``swap`` = (food vector, servings, purpose) for mode ``swap``. Raises ``ValueError`` for a low
    treatment in swap mode (G7) and :class:`ContextTooSmall` when nothing fits the prompt budget.
    """
    food, servings, purpose = swap if swap is not None else (None, None, None)
    bridge = candidates_for_ai(ctx, meal, mode, food=food, servings=servings, purpose=purpose)
    meals_left = list(open_slots(meal, ctx.day))
    trimmed = 0
    while True:
        extra: dict[str, Any] = {}
        if mode == "swap":
            extra = prompts.swap_extra(bridge, food, float(servings or 1.0))
        elif mode == "plan":
            extra = prompts.plan_extra(bridge)
        data = prompts.next_meal_context(bridge, ctx, mode=mode, meal=meal, meals_left=meals_left, person=person, extra=extra)
        schema, validator, judge = _meal_schema(mode, bridge, ctx, meal, cfg)
        task = mode
        body = build_body(cfg, system=prompts.SYSTEM_PROMPT, user_text=prompts.user_message(task, data, mode=cfg.structured, schema=schema),
                          schema=schema, schema_name=f"kidney_{mode}", mode=cfg.structured)
        if _fits(cfg, body) or mode in ("swap", "plan"):
            break
        if len(bridge["foods"]) <= 1:
            raise ContextTooSmall("the prompt does not fit AI_CONTEXT_TOKENS even with one candidate")
        bridge = {**bridge, "foods": bridge["foods"][:-1]}  # lowest-ranked first (rule order)
        trimmed += 1
    return Prepared(feature="next_meal", cfg=cfg, body=body, validator=validator, judge=judge, mode=mode,
                    fallback=guard.fallback(bridge), trimmed=trimmed)


def _meal_schema(mode: Mode, bridge: Mapping[str, Any], ctx: GuidanceContext, meal: str, cfg: ProviderConfig):
    label = cfg.label
    if mode == "ideas":
        ids = sorted({int(f["food_id"]) for f in bridge["foods"]} | {int(it["food_id"]) for m in bridge.get("meals", []) for it in m.get("items", [])})
        schema = schemas.ideas_schema(ids, prompts.AI_HANDBOOK_SLUGS)
        validator = schemas.model_validator_for(schemas.IdeasAnswer)
        return schema, validator, lambda ans: guard.judge_ideas(ans.model_dump(), ctx, meal, bridge, provider_label=label, model=cfg.model)
    if mode == "rerank":
        schema = schemas.rerank_schema([f["ref"] for f in bridge["foods"]])
        validator = schemas.model_validator_for(schemas.RerankAnswer)
        return schema, validator, lambda ans: guard.judge_rerank(ans.model_dump(), ctx, meal, bridge, provider_label=label, model=cfg.model)
    if mode == "swap":
        schema = schemas.swap_schema([s["ref"] for s in bridge.get("swaps", [])])
        validator = schemas.model_validator_for(schemas.SwapAnswer)
        return schema, validator, lambda ans: guard.judge_swap(ans.model_dump(), ctx, meal, bridge, provider_label=label, model=cfg.model)
    if mode == "plan":
        plan = bridge.get("plan") or {}
        slots = [s for s in R.SLOT_ORDER if s in plan]
        max_index = max((len(v) for v in plan.values()), default=1) - 1
        schema = schemas.plan_schema(slots, max_index)
        validator = schemas.model_validator_for(schemas.PlanAnswer)
        return schema, validator, lambda ans: guard.judge_plan(ans.model_dump(), ctx, bridge, provider_label=label, model=cfg.model)
    raise ValueError(f"unknown mode {mode!r}")


# --------------------------------------------------------------------------- #
# Describe a meal
# --------------------------------------------------------------------------- #

UNIT_GRAMS = {"g": 1.0, "oz": 28.3495}
UNIT_WORDS = {
    "cup": ("cup", "cups"), "tbsp": ("tbsp", "tablespoon", "tablespoons", "tbs"), "tsp": ("tsp", "teaspoon", "teaspoons"),
    "slice": ("slice", "slices"), "piece": ("piece", "pieces", "medium", "large", "small", "each", "whole"),
    "fl_oz": ("fl oz", "fl. oz", "fluid ounce", "fluid ounces"), "ml": ("ml", "milliliter", "millilitre"),
}
_LEADING = re.compile(r"^\s*(\d+(?:\.\d+)?|\d+\s*/\s*\d+|½|¼|¾|⅓|⅔)\s*(.*)$")
_FRACTIONS = {"½": 0.5, "¼": 0.25, "¾": 0.75, "⅓": 1 / 3, "⅔": 2 / 3}


def serving_quantity(serving_desc: str) -> tuple[float, str] | None:
    """``"1/2 cup (79 g)"`` → ``(0.5, "cup (79 g)")``; None when it does not start with a number."""
    match = _LEADING.match(serving_desc or "")
    if not match:
        return None
    raw, rest = match.group(1).replace(" ", ""), match.group(2).lower()
    if raw in _FRACTIONS:
        qty = _FRACTIONS[raw]
    elif "/" in raw:
        num, den = raw.split("/")
        qty = float(num) / float(den) if float(den) else 0.0
    else:
        qty = float(raw)
    return (qty, rest) if qty > 0 else None


def servings_for(amount: float | None, unit: str, food: Mapping[str, Any]) -> float | None:
    """Servings of ``food`` for an amount, only when the food's serving supports the unit (R3)."""
    if amount is None or amount <= 0:
        return None
    if unit == "serving":
        servings = amount
    elif unit in UNIT_GRAMS:
        grams = float(food.get("serving_g") or 0.0)
        if grams <= 0:
            return None
        servings = amount * UNIT_GRAMS[unit] / grams
    elif unit in UNIT_WORDS:
        quantity = serving_quantity(str(food.get("serving_desc") or ""))
        if quantity is None:
            return None
        qty, rest = quantity
        if not any(rest.startswith(word) for word in UNIT_WORDS[unit]):
            return None
        servings = amount / qty
    else:
        return None
    if not 0.05 <= servings <= 20:
        return None
    return round(servings * 4) / 4 or 0.25


def prepare_parse_meal(cfg: ProviderConfig, text: str, *, search: Callable[[str], list[dict[str, Any]]]) -> Prepared:
    data = prompts.parse_meal_data(text)
    schema = schemas.parse_meal_schema()
    body = build_body(cfg, system=prompts.TASK_SYSTEM_PROMPT, user_text=prompts.user_message("parse_meal", data, mode=cfg.structured, schema=schema),
                      schema=schema, schema_name="kidney_parse_meal", mode=cfg.structured)

    def judge(answer: schemas.ParseMealAnswer) -> dict[str, Any]:
        if answer.status == "refused":
            return {"status": "refused", "message": guard.REFUSED_TEXT, "items": [], "dropped": []}
        items, dropped = [], []
        for index, item in enumerate(answer.items):
            label_text, why = guard.name_policy(item.text, schemas.MAX_NAME_CHARS)
            query, why2 = guard.name_policy(item.search, schemas.MAX_NAME_CHARS)
            if label_text is None or query is None:
                dropped.append({"index": index, "reason": f"text_policy:{why or why2}"})
                continue
            matches = []
            for food in search(query)[:3]:
                matches.append({"food": food, "servings": servings_for(item.amount, item.unit, food)})
            items.append({"text": label_text, "search": query, "amount": item.amount, "unit": item.unit, "matches": matches})
        return {"status": "ok", "items": items, "dropped": dropped,
                "notice": "AI split your text into foods; pick the right match for each one. Nothing is logged until you add it."}

    return Prepared(feature="parse_meal", cfg=cfg, body=body, validator=schemas.model_validator_for(schemas.ParseMealAnswer), judge=judge)


# --------------------------------------------------------------------------- #
# Photos
# --------------------------------------------------------------------------- #

FDA_DAILY_VALUES = {"sodium": ("sodium_mg", 2300.0), "potassium": ("potassium_mg", 4700.0),
                    "phosphorus": ("phosphorus_mg", 1250.0), "calcium": ("calcium_mg", 1300.0)}  # 21 CFR 101.9(c)(8)(iv)
SODIUM_PER_SALT = 1000.0 / 2.5  # mg sodium per g salt (EU labels give salt; sodium = salt ÷ 2.5)
LABEL_NOTICE = "Read by AI from your photo. Check every number against the label before saving."
PLATE_BANNER = ("AI estimate from a photo. In studies, portion estimates were off by about a third and too small for big "
                "plates. Weigh or measure when it matters, and do not dose insulin from this alone.")
ATWATER = {"carbs_g": 4.0, "protein_g": 4.0, "fat_g": 9.0}
ENERGY_TOLERANCE = 0.20
ENERGY_SLACK_KCAL = 20.0
# Per-serving values above these are implausible on a real label (mg).
MG_CEILINGS = {"sodium_mg": 10_000.0, "potassium_mg": 6_000.0, "phosphorus_mg": 3_000.0, "calcium_mg": 3_000.0}


def image_part(image: CheckedImage) -> str:
    return "data:image/jpeg;base64," + base64.b64encode(image.data).decode("ascii")


def _vision_body(cfg: ProviderConfig, task: str, schema: Mapping[str, Any], name: str, image: CheckedImage) -> dict[str, Any]:
    return build_body(cfg, system=prompts.TASK_SYSTEM_PROMPT, user_text=prompts.user_message(task, None, mode=cfg.structured, schema=schema),
                      images=[image_part(image)], schema=schema, schema_name=name, mode=cfg.structured, vision=True)


def label_checks(values: Mapping[str, float | None], serving_g: float | None) -> list[dict[str, str]]:
    """Plausibility (R3): Atwater energy within 20 % + 20 kcal; grams not above the serving weight;
    per-serving mineral ceilings."""
    checks = []
    kcal = values.get("calories_kcal")
    parts = [values.get(k) for k in ATWATER]
    if kcal is not None and all(p is not None for p in parts):
        computed = sum(float(values[k] or 0.0) * f for k, f in ATWATER.items())
        if abs(computed - kcal) > ENERGY_TOLERANCE * max(kcal, computed) + ENERGY_SLACK_KCAL:
            checks.append({"code": "energy_mismatch",
                           "message": "The calories do not match the fat, carbohydrate and protein; check those numbers."})
    if serving_g:
        grams = sum(float(values.get(k) or 0.0) for k in ("fat_g", "carbs_g", "protein_g", "fiber_g"))
        grams -= float(values.get("fiber_g") or 0.0)  # fibre is part of carbohydrate on US labels
        if grams > serving_g * 1.05:
            checks.append({"code": "grams_exceed_serving", "message": "The grams add up to more than the serving weighs; check the serving size."})
    for key, ceiling in MG_CEILINGS.items():
        v = values.get(key)
        if v is not None and v > ceiling:
            checks.append({"code": f"implausible:{key}", "message": f"{key.split('_')[0].capitalize()} looks too high for one serving; check mg against g."})
    return checks


def label_draft(answer: schemas.LabelAnswer) -> dict[str, Any]:
    """Note 03 R8 step 4 + note 04 R3: scale, salt → sodium, %DV → mg (estimated), additive scan, checks."""
    if answer.status != "ok":
        message = ("This does not look like a nutrition label." if answer.status == "not_a_label"
                   else "The label could not be read; try a sharper photo with less glare.")
        return {"status": answer.status, "message": message, "draft": None}
    values: dict[str, float | None] = answer.per_serving.model_dump()
    from_photo = [k for k, v in values.items() if v is not None]
    estimated: list[str] = []
    checks: list[dict[str, str]] = []
    serving_g = answer.serving_g
    serving_text = clean_text(answer.serving_text, max_len=60)
    if answer.basis in ("per_100g", "per_100ml"):
        unit = "g" if answer.basis == "per_100g" else "ml"
        if serving_g:
            factor = serving_g / 100.0
            values = {k: (None if v is None else v * factor) for k, v in values.items()}
            checks.append({"code": "scaled", "message": f"The label lists values per 100 {unit}; they were scaled to one serving of {serving_g:g} {unit}."})
        else:
            serving_g = 100.0
            serving_text = f"100 {unit}"
            checks.append({"code": "per_100", "message": f"No serving size was read, so the food is saved per 100 {unit}."})
    salt = answer.salt_g
    if values.get("sodium_mg") is None and salt is not None:
        factor = (serving_g / 100.0) if answer.basis != "per_serving" and answer.serving_g else 1.0
        values["sodium_mg"] = salt * factor * SODIUM_PER_SALT
        estimated.append("sodium_mg")
        checks.append({"code": "sodium_from_salt", "message": "Sodium was worked out from salt (salt ÷ 2.5)."})
    if answer.basis == "per_serving":
        for name, (key, dv) in FDA_DAILY_VALUES.items():
            pct = getattr(answer.percent_dv, name)
            if values.get(key) is None and pct is not None:
                values[key] = pct / 100.0 * dv
                estimated.append(key)
                checks.append({"code": f"estimated:{key}",
                               "message": f"{name.capitalize()} was estimated from the % Daily Value ({pct:g} % of {dv:g} mg)."})
    if values.get("potassium_mg") is None:
        checks.append({"code": "potassium_unknown", "message": "Potassium is not on this label; it is saved as unknown, not zero."})
    checks += label_checks(values, serving_g)
    name = clean_text(answer.product_name, max_len=200)
    ingredients = clean_text(answer.ingredients_text, max_len=4000, keep_newlines=True)
    additives = scan_additives(None, ingredients, name)
    for f in additives.findings:
        checks.append({"code": f"additive:{f.kind}", "message": f"The ingredients list {f.name}."})
    nutrients = {k: (None if v is None else round(float(v), 1)) for k, v in values.items()}
    nutrients["fluid_ml"] = None
    draft = {
        "name": name or "",
        "brand": None,
        "category": None,
        "serving_desc": serving_text or (f"1 serving ({serving_g:g} g)" if serving_g else "1 serving"),
        "serving_g": round(float(serving_g), 1) if serving_g else None,
        "nutrients": nutrients,
        "flags": list(additives.flags),
        "kidney_notes": additives.kidney_notes,
        "ingredients_text": ingredients,
    }
    return {"status": "ok", "draft": draft, "from_photo": from_photo + (["name"] if name else []) + (["ingredients_text"] if ingredients else []),
            "estimated": estimated, "checks": checks, "notice": LABEL_NOTICE}


def prepare_read_label(cfg: ProviderConfig, image: CheckedImage) -> Prepared:
    schema = schemas.read_label_schema()
    body = _vision_body(cfg, "read_label", schema, "nutrition_label", image)

    def judge(answer: schemas.LabelAnswer) -> dict[str, Any]:
        result = label_draft(answer)
        result["provider"] = f"{cfg.preset}:{cfg.vision_model or cfg.model}"
        return result

    return Prepared(feature="read_label", cfg=cfg, body=body, validator=schemas.model_validator_for(schemas.LabelAnswer),
                    judge=judge, purpose="photos", vision=True, images=[image])


def prepare_plate(cfg: ProviderConfig, image: CheckedImage, *, search: Callable[[str], list[dict[str, Any]]]) -> Prepared:
    schema = schemas.plate_schema()
    body = _vision_body(cfg, "plate", schema, "plate_photo", image)

    def judge(answer: schemas.PlateAnswer) -> dict[str, Any]:
        if answer.status != "ok" or not answer.items:
            message = "No food was recognised in this photo." if answer.status == "no_food" else "The AI was not sure what is in this photo; search for the foods instead."
            return {"status": answer.status if answer.status != "ok" else "no_food", "message": message, "items": [], "banner": PLATE_BANNER}
        items, dropped = [], []
        for index, item in enumerate(answer.items):
            name, why = guard.name_policy(item.name, schemas.MAX_NAME_CHARS)
            query, why2 = guard.name_policy(item.search, schemas.MAX_NAME_CHARS)
            if name is None or query is None:
                dropped.append({"index": index, "reason": f"text_policy:{why or why2}"})
                continue
            grams = item.grams_estimate
            candidates = []
            for food in search(query)[:3]:
                servings = servings_for(grams, "g", food) if grams else None
                candidates.append({"food": food, "servings": servings})
            items.append({"name": name, "search": query, "grams_estimate": None if grams is None else round(grams),
                          "portion_text": None if grams is None else f"about {round(grams):d} g", "confidence": item.confidence,
                          "ticked": item.confidence != "low", "candidates": candidates})
        return {"status": "ok", "items": items, "dropped": dropped, "banner": PLATE_BANNER,
                "provider": f"{cfg.preset}:{cfg.vision_model or cfg.model}",
                "notice": "AI estimate from a photo. Check each food and amount; entries are added as planned."}

    return Prepared(feature="plate", cfg=cfg, body=body, validator=schemas.model_validator_for(schemas.PlateAnswer),
                    judge=judge, purpose="photos", vision=True, images=[image])


def person_for(profile: Mapping[str, Any], prefs: Mapping[str, Any], today: _date) -> dict[str, Any]:
    return prompts.person_block(profile, prefs, today)


def search_function(conn: sqlite3.Connection, user_id: int) -> Callable[[str], list[dict[str, Any]]]:
    """The person's own food search (visible foods only), trimmed to what the UI needs."""
    from ..foods import search_foods

    def run(query: str) -> list[dict[str, Any]]:
        rows = search_foods(conn, user_id, query, limit=3)
        keep = ("id", "name", "brand", "category", "source", "serving_desc", "serving_g", "nutrients", "flags", "warnings", "kidney_rating")
        return [{k: f.get(k) for k in keep} for f in rows]

    return run
