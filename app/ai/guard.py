"""The validator pipeline V1–V9 (note 04 R7 with §9 A2). Pure: no I/O, no network.

* **V1 Parse** and **V2 Structure** run in :meth:`app.ai.client.ChatClient.complete_json`
  (:func:`app.ai.client.extract_json` plus the ``extra="forbid"`` models of :mod:`app.ai.schemas`),
  which allows one repair turn.
* **V3 Grounding**, **V4 Recompute** and **V5 Rules gate** for meal ideas are the guidance engine's own
  checks (``app.guidance.ai_bridge.validate_ai_items``: candidate ids only, ¼–3 servings in quarters,
  duplicates merged, ≤ 5 items, ≤ 3 ideas, then ``check_meal`` — no new ``over``, no ``avoid_ckd`` or
  low treatment, no ``high`` portion of a nutrient that is not ok today, at most one serving of a
  ``high`` food — and ``score_meal``). Every number shown comes from the food rows.
* **V6 Text policy.** The meal features return no free text (§9 A2): an idea's ``theme`` and
  ``reason_codes`` are checked against the recomputed numbers (:func:`true_reasons`) and the sentence a
  person reads is written here from maintainer templates (:data:`REASON_TEXT`). A false claim is
  removed and counted (``claims_corrected``). A "low in …" claim holds only when every portion is low by
  the guidance engine's own definition (potassium ≤ 100 mg, phosphorus ≤ 50 mg, sodium ≤ 140 mg per
  portion) and the idea uses at most half of what is left today; its sentence prints the number.
  Model text that must be shown (food names and search terms from photos or a described meal) goes
  through :func:`name_policy`: NFKC, ``Cc``/``Cf`` removed, homoglyphs folded, no URLs, e-mails or
  markup characters, and the :data:`BLOCKLIST` (which includes §9 A2's expanded terms: ``shot``,
  ``pen``, ``skip``, ``delay``, ``extra``/``more`` as advice, binder brand names).
* **V7 Handbook.** Only slugs from the allowed set, at most 2.
* **V8 Outcome.** No idea left → the rule result with "The AI ideas did not fit your targets today, so
  these are the app's own." A refusal → G11's sentence.
* **V9 Label.** ``source: "ai"``, provider label, model, ``checked: true`` and the server's numbers.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any, Iterable, Mapping, Sequence

from ..guidance import messages as M
from ..guidance import rules as R
from ..guidance.ai_bridge import validate_ai_items, validate_ai_plan
from ..guidance.budget import day_totals, meal_room
from ..guidance.budget import Room
from ..guidance.score import meal_totals
from ..guidance.topics import TOPIC_PAGES
from ..guidance.vectors import FoodVec
from ..textclean import clean_text
from .prompts import AI_HANDBOOK_SLUGS
from .schemas import REASON_CODES, THEMES

REFUSED_TEXT = "This is outside what the app's AI helps with. Your care team can answer it."  # G11
FALLBACK_TEXT = M.AI_FALLBACK  # V8 (one wording for guidance and AI)
NO_FIT_TEXT = "The AI found nothing that fits your targets for this meal, so these are the app's own ideas."
NOTICE = "AI idea · {label} · {model} · checked against your targets · not medical advice"  # G13

# V6 blocklist (R7 with word boundaries, so "pumpkin", "dosa", "basil", "penne" and "Skippy" pass). §9 A2's
# expanded list is applied to every model text that is shown in v0.3 (describe-a-meal phrases and plate names;
# packaging text is an injection source, §9.2): "shot", "pen", "skip", "delay", medicines and binder brand names,
# and "extra"/"more"/"double" only as advice ("eat 3 extra bananas"), so "extra virgin olive oil" and
# "extra-lean beef" still pass. "tablets" is not blocked: glucose tablets are a food here.
BLOCKLIST = re.compile(
    r"\b(insulin\w*|bolus\w*|basal|units?|ratios?|corrections?|dos(?:e|es|ed|ing|age)|pumps?|binders?|sevelamer|lanthanum|"
    r"calcium acetate|patiromer|zirconium|supplements?|diagnos\w*|lab results?|safe to eat|unlimited|as much as|"
    r"don'?t worry|no need to|inject\w*|shots?|pens?|skip(?:s|ped|ping)?|delay(?:s|ed|ing)?|pills?|capsules?|"
    r"medicines?|medications?|meds|prescri\w*|renvela|renagel|fosrenol|velphoro|auryxia|phoslo|phoslyra|lokelma|"
    r"veltassa|kayexalate|xphozah|tenapanor|sucroferric|ferric citrate|"
    r"(?:eat|have|take|drink|add|use)\s+(?:(?:\d+|an?|one|two|three|four|five|some|another)\s+)?(?:extra|more|double)|"
    r"(?:\d+|one|two|three|four|five|six)\s+(?:extra|more)|double\s+(?:your|the|it|up)|"
    r"(?:is|are|it'?s|that'?s)\s+(?:fine|ok(?:ay)?|safe))\b",
    re.IGNORECASE,
)
_URL = re.compile(r"(https?://|www\.|\b[a-z0-9-]+\.(?:com|net|org|io|ru|cn|xyz|info|biz|app|dev|me)\b)", re.IGNORECASE)
_EMAIL = re.compile(r"\b[^\s@]+@[^\s@]+\.[a-z]{2,}\b", re.IGNORECASE)
_MARKUP = re.compile(r"[<>{}\[\]\\`|]")
# Latin look-alikes from Cyrillic and Greek (a small skeleton, enough for the blocklist terms).
_CONFUSABLES = str.maketrans({
    "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "у": "y", "х": "x", "і": "i", "ј": "j", "ѕ": "s",
    "ԁ": "d", "ո": "n", "ɡ": "g", "ι": "i", "ο": "o", "ν": "v", "κ": "k", "τ": "t", "ρ": "p", "α": "a",
    "ε": "e", "Ι": "I", "Ο": "O", "Α": "A", "Ε": "E", "Β": "B", "Ν": "N", "Τ": "T", "Ρ": "P", "К": "K", "М": "M",
    "Н": "H", "А": "A", "Е": "E", "О": "O", "Р": "P", "С": "C", "Т": "T", "Х": "X", "В": "B", "ı": "i",
})

HEARTY_KCAL = 450.0  # an idea at or above this is "hearty", below it "light"
THEME_TITLE = {"light": "A light {meal}", "hearty": "A hearty {meal}", "familiar": "A familiar {meal}",
               "new_idea": "Something new for {meal}"}
# Every "low in" sentence prints its number (F6; CDC item 16): never "low" without the amount.
REASON_TEXT = {
    "low_potassium": "low in potassium ({k} mg) for what is left today",
    "low_phosphorus": "low in phosphorus ({p} mg)",
    "low_sodium": "low in sodium ({na} mg)",
    "fits_carb_goal": "brings {meal} close to your carbohydrate goal",
    "adds_protein": "adds a protein portion",
    "adds_missing_group": "adds what this {meal} is missing",
    "you_eat_often": "uses foods you often have",
}
LOW_SODIUM_PORTION_MG = 140.0  # FDA "low sodium" per serving
# "Low in …" per portion, the guidance engine's own definitions (fits.py reasons; note 06 line 522).
LOW_PORTION_MG = {R.K: R.LOW_K_REASON_MG, R.P: R.LOW_P_REASON_MG, R.NA: LOW_SODIUM_PORTION_MG}


def fold(text: str) -> str:
    """NFKC, ``Cc``/``Cf`` removed, homoglyphs folded: what the blocklist is matched against."""
    s = unicodedata.normalize("NFKC", text or "")
    s = "".join(ch for ch in s if unicodedata.category(ch) not in ("Cc", "Cf", "Cs"))
    return s.translate(_CONFUSABLES)


def blocked(text: str) -> str | None:
    """The first blocklist term in ``text`` (after :func:`fold`), else ``None``."""
    match = BLOCKLIST.search(fold(text))
    return match.group(1).lower() if match else None


def name_policy(text: Any, limit: int = 80) -> tuple[str | None, str | None]:
    """V6 for model text that is shown (a food name or search term): ``(clean text, None)`` or
    ``(None, reason)`` with ``reason`` one of ``empty``, ``url``, ``markup``, ``blocklist:<term>``."""
    cleaned = clean_text(text, max_len=limit)
    if not cleaned:
        return None, "empty"
    folded = fold(cleaned)
    if _URL.search(folded) or _EMAIL.search(folded):
        return None, "url"
    if _MARKUP.search(folded):
        return None, "markup"
    term = blocked(folded)
    if term:
        return None, f"blocklist:{term}"
    return folded.strip(), None


# --------------------------------------------------------------------------- #
# Claims (V6 under §9 A2): which reason codes and theme are true of an idea
# --------------------------------------------------------------------------- #


def true_reasons(items: Sequence[tuple[FoodVec, float]], room: Room, often: Iterable[int]) -> set[str]:
    """The reason codes that hold for ``items`` in ``room`` (recomputed from the food rows)."""
    totals, unknown = meal_totals(items)
    out: set[str] = set()

    def low(key: str) -> bool:
        """Every portion is low by the engine's own definition (so a portion the card flags "high" never
        reads "low"), and with a tracked target the idea uses at most half of what is left today."""
        if key in unknown:
            return False
        limit = LOW_PORTION_MG[key]
        if any((_amount(f, key) or 0.0) * q > limit for f, q in items):
            return False
        item = room.nutrients.get(key)
        if item is not None:
            return item.room > 0 and totals[key] <= 0.5 * item.room
        return True

    if low(R.K):
        out.add("low_potassium")
    if low(R.P):
        out.add("low_phosphorus")
    if low(R.NA):
        out.add("low_sodium")
    if room.carbs is not None and R.CARBS not in unknown:
        if abs(room.carbs.in_meal + totals[R.CARBS] - room.carbs.goal) <= room.carbs.tolerance:
            out.add("fits_carb_goal")
    if R.PROTEIN not in unknown and totals[R.PROTEIN] >= R.PROTEIN_ROLE_MIN_G:
        out.add("adds_protein")
    has = room.meal_has
    for f, _ in items:
        if ((f.role in R.PROTEIN_ROLES and not has.get("protein")) or (f.role in R.STARCH_ROLES and not has.get("starch"))
                or (f.role == "veg_fruit" and not has.get("veg_fruit"))):
            out.add("adds_missing_group")
            break
    often_ids = set(often)
    if any(f.id in often_ids for f, _ in items):
        out.add("you_eat_often")
    return out


def _amount(f: FoodVec, key: str) -> float | None:
    return {R.K: f.k, R.P: f.p, R.NA: f.na}[key]


def true_theme(items: Sequence[tuple[FoodVec, float]], claimed: str, often: Iterable[int]) -> str:
    """``claimed`` when it is true of ``items``, else the theme that is."""
    often_ids = set(often)
    familiar = any(f.id in often_ids for f, _ in items)
    kcal = sum((f.kcal or 0.0) * q for f, q in items)
    if claimed == "familiar":
        return "familiar" if familiar else "new_idea"
    if claimed == "new_idea":
        return "new_idea" if not familiar else "familiar"
    if claimed == "hearty":
        return "hearty" if kcal >= HEARTY_KCAL else "light"
    return "light" if kcal < HEARTY_KCAL else "hearty"


def sentence(codes: Sequence[str], meal: str, items: Sequence[tuple[FoodVec, float]] = ()) -> str:
    """The server-written "why" (no model text), with the idea's own numbers:
    "Low in sodium (60 mg); adds a protein portion." """
    totals, _ = meal_totals(items)
    values = {"meal": meal, "k": M.fmt_int(totals[R.K]), "p": M.fmt_int(totals[R.P]), "na": M.fmt_int(totals[R.NA])}
    parts = [REASON_TEXT[c].format(**values) for c in codes if c in REASON_TEXT]
    if not parts:
        return f"Fits your targets for {meal}."
    text = "; ".join(parts)
    return text[0].upper() + text[1:] + "."


def check_claims(claimed: Sequence[str], items: Sequence[tuple[FoodVec, float]], room: Room,
                 often: Iterable[int]) -> tuple[list[str], int]:
    """Keep the claimed codes that are true (order kept, unknown codes ignored); fall back to the true
    ones when none survive. Returns ``(codes, number corrected)``."""
    truth = true_reasons(items, room, often)
    kept = [c for c in dict.fromkeys(claimed) if c in REASON_CODES and c in truth]
    corrected = len([c for c in dict.fromkeys(claimed) if c not in kept])
    if not kept:
        kept = [c for c in REASON_CODES if c in truth][:2]
    return kept[:3], corrected


def handbook_refs(slugs: Iterable[Any]) -> tuple[list[dict[str, str]], int]:
    """V7: allowed slugs only, at most 2; returns the pages and the number dropped."""
    pages: list[dict[str, str]] = []
    dropped = 0
    for slug in slugs:
        allowed = isinstance(slug, str) and slug in AI_HANDBOOK_SLUGS and slug in TOPIC_PAGES
        if allowed and len(pages) < 2 and all(p["slug"] != slug for p in pages):
            pages.append(dict(TOPIC_PAGES[slug]))
            continue
        dropped += 1
    return pages, dropped


def often_ids(bridge: Mapping[str, Any]) -> set[int]:
    return {int(f["food_id"]) for f in bridge.get("foods", []) if "you_eat_often" in (f.get("reasons") or ())}


def label(provider_label: str, model: str) -> dict[str, Any]:
    return {"source": "ai", "provider_label": provider_label, "model": model, "checked": True,
            "notice": NOTICE.format(label=provider_label, model=model)}


# --------------------------------------------------------------------------- #
# next-meal modes
# --------------------------------------------------------------------------- #


IDEA_KEYS = frozenset({"theme", "items", "reason_codes", "handbook"})


def _idea_items(raw: Any) -> tuple[list[dict[str, Any]] | None, str | None]:
    """V2/V3 for one idea: the four schema keys only (a ``title`` or ``why`` the schema does not allow is
    free text, so the idea is dropped, §9 A2), and items of integer ``food_id`` and ``quarters``."""
    if not isinstance(raw, Mapping):
        return None, "malformed_idea"
    if set(raw) - IDEA_KEYS:
        return None, "unexpected_field"
    items = raw.get("items")
    if not isinstance(items, list):
        return None, "malformed_idea"
    if not items:
        return None, "empty"
    out = []
    for it in items:
        if not isinstance(it, Mapping) or set(it) - {"food_id", "quarters"}:
            return None, "malformed_item"
        fid, quarters = it.get("food_id"), it.get("quarters")
        if not isinstance(fid, int) or isinstance(fid, bool) or not isinstance(quarters, int) or isinstance(quarters, bool):
            return None, "malformed_item"
        out.append({"food_id": fid, "quarters": quarters})
    return out, None


def judge_ideas(answer: Mapping[str, Any], ctx: Any, meal: str, bridge: Mapping[str, Any], *,
                provider_label: str, model: str) -> dict[str, Any]:
    """V3–V9 for mode ``ideas``. ``answer`` is the V2-checked object (``status``, ``refusal``, ``ideas``)."""
    if answer.get("status") == "refused":
        return {"status": "refused", "message": REFUSED_TEXT, "ideas": [], "dropped": [], "claims_corrected": 0}
    candidate_ids = {int(f["food_id"]) for f in bridge.get("foods", [])}
    for m in bridge.get("meals", []):
        candidate_ids |= {int(it["food_id"]) for it in m.get("items", [])}
    raw_ideas = list(answer.get("ideas") or [])
    parsed: list[tuple[int, Mapping[str, Any], list[dict[str, Any]]]] = []
    dropped: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_ideas):
        if index >= 3:
            dropped.append({"index": index, "reason": "too_many_ideas"})
            continue
        items, error = _idea_items(raw)
        if error or items is None:
            dropped.append({"index": index, "reason": error or "malformed_idea"})
            continue
        if len({i["food_id"] for i in items}) > 5:
            dropped.append({"index": index, "reason": "too_many_items"})
            continue
        parsed.append((index, raw, items))
    checked = validate_ai_items(ctx, meal, [items for _, _, items in parsed], candidate_ids)
    room = meal_room(ctx, meal, totals=day_totals(ctx.day))
    often = often_ids(bridge)
    accepted_by_pos = {a["index"]: a for a in checked["ideas"]}
    for d in checked["dropped"]:
        dropped.append({"index": parsed[d["index"]][0] if d["index"] < len(parsed) else d["index"], "reason": d["reason"]})
    shown: list[dict[str, Any]] = []
    corrected_total = 0
    for pos, (index, raw, _items) in enumerate(parsed):
        accepted = accepted_by_pos.get(pos)
        if accepted is None:
            continue
        vec_items = [(ctx.foods[it["food_id"]], float(it["servings"])) for it in accepted["items"]]
        codes, corrected = check_claims([c for c in raw.get("reason_codes") or [] if isinstance(c, str)], vec_items, room, often)
        theme_claim = raw.get("theme") if raw.get("theme") in THEMES else "light"
        theme = true_theme(vec_items, theme_claim, often)
        corrected += int(theme != theme_claim)
        pages, slugs_dropped = handbook_refs(raw.get("handbook") or [])
        corrected_total += corrected
        shown.append({
            **label(provider_label, model),
            "index": index,
            "theme": theme,
            "title": THEME_TITLE[theme].format(meal=meal),
            "reason_codes": codes,
            "why": sentence(codes, meal, vec_items),
            "items": accepted["items"],
            "totals": accepted["totals"],
            "score": accepted["score"],
            "after": after_room(room, vec_items),
            "handbook": pages,
            "handbook_dropped": slugs_dropped,
        })
    if not shown:
        status = "no_fit" if answer.get("refusal") == "no_fit" and not raw_ideas else "dropped_all"
        return {"status": status, "message": NO_FIT_TEXT if status == "no_fit" else FALLBACK_TEXT, "ideas": [],
                "dropped": dropped, "claims_corrected": corrected_total}
    return {"status": "ok", "ideas": shown, "dropped": dropped, "claims_corrected": corrected_total}


def after_room(room: Room, items: Sequence[tuple[FoodVec, float]]) -> dict[str, Any]:
    """V9 "projected status deltas": what is left today of each tracked nutrient once the idea is eaten,
    and the meal's carbohydrate against its goal."""
    from ..nutrients import round_value

    totals, _ = meal_totals(items)
    out: dict[str, Any] = {}
    for key, item in room.nutrients.items():
        out[key] = {"used": round_value(key, totals[key]), "left_today_after": round_value(key, item.remaining - totals[key])}
    if room.carbs is not None:
        out[R.CARBS] = {"meal_after": round_value(R.CARBS, room.carbs.in_meal + totals[R.CARBS]),
                        "goal": round_value(R.CARBS, room.carbs.goal)}
    return out


def _ref_picks(raw: Iterable[Any], allowed: Mapping[str, Any], limit: int) -> tuple[list[tuple[str, list[str]]], list[dict[str, Any]]]:
    picks: list[tuple[str, list[str]]] = []
    dropped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, entry in enumerate(raw):
        ref = entry.get("ref") if isinstance(entry, Mapping) else None
        if not isinstance(ref, str) or ref not in allowed:
            dropped.append({"index": index, "reason": "not_a_candidate"})
            continue
        if ref in seen:
            dropped.append({"index": index, "reason": "duplicate"})
            continue
        if len(picks) >= limit:
            dropped.append({"index": index, "reason": "too_many"})
            continue
        seen.add(ref)
        picks.append((ref, [c for c in entry.get("reason_codes") or [] if isinstance(c, str)]))
    return picks, dropped


def judge_rerank(answer: Mapping[str, Any], ctx: Any, meal: str, bridge: Mapping[str, Any], *,
                 provider_label: str, model: str) -> dict[str, Any]:
    """Mode ``rerank`` (note 06 §4.13): AI order for the refs it names, then the rule order; numbers,
    warnings and texts always from the rules."""
    if answer.get("status") == "refused":
        return {"status": "refused", "message": REFUSED_TEXT, "order": [], "dropped": [], "claims_corrected": 0}
    foods = {f["ref"]: f for f in bridge.get("foods", [])}
    picks, dropped = _ref_picks(answer.get("order") or [], foods, 12)
    room = meal_room(ctx, meal, totals=day_totals(ctx.day))
    often = often_ids(bridge)
    order: list[dict[str, Any]] = []
    corrected_total = 0
    for rank, (ref, claimed) in enumerate(picks, start=1):
        f = foods[ref]
        vec = [(ctx.foods[int(f["food_id"])], float(f["portion"]))]
        codes, corrected = check_claims(claimed, vec, room, often)
        corrected_total += corrected
        order.append({"ref": ref, "food_id": int(f["food_id"]), "ai_rank": rank, "reason_codes": codes, "why": sentence(codes, meal, vec)})
    rest = [{"ref": r, "food_id": int(f["food_id"])} for r, f in foods.items() if r not in {p[0] for p in picks}]
    if not order:
        return {"status": "dropped_all", "message": FALLBACK_TEXT, "order": [], "rest": rest, "dropped": dropped,
                "claims_corrected": 0}
    return {"status": "ok", **label(provider_label, model), "order": order, "rest": rest, "dropped": dropped,
            "claims_corrected": corrected_total}


def judge_swap(answer: Mapping[str, Any], ctx: Any, meal: str, bridge: Mapping[str, Any], *,
               provider_label: str, model: str) -> dict[str, Any]:
    """Mode ``swap``: the AI picks among the rule swaps (which already passed every rule)."""
    if answer.get("status") == "refused":
        return {"status": "refused", "message": REFUSED_TEXT, "pick": [], "dropped": [], "claims_corrected": 0}
    swaps = {s["ref"]: s for s in bridge.get("swaps", [])}
    picks, dropped = _ref_picks(answer.get("pick") or [], swaps, 3)
    room = meal_room(ctx, meal, totals=day_totals(ctx.day))
    often = often_ids(bridge)
    shown = []
    corrected_total = 0
    for ref, claimed in picks:
        s = swaps[ref]
        vec = [(ctx.foods[int(s["food_id"])], float(s["servings"]))]
        codes, corrected = check_claims(claimed, vec, room, often)
        corrected_total += corrected
        shown.append({**label(provider_label, model), "ref": ref, "food_id": int(s["food_id"]), "name": s["name"],
                      "servings": s["servings"], "renal_rating": s.get("renal_rating"), "text": s.get("text"),
                      "reason_codes": codes, "why": sentence(codes, meal, vec)})
    if not shown:
        return {"status": "dropped_all", "message": FALLBACK_TEXT, "pick": [], "dropped": dropped, "claims_corrected": 0}
    return {"status": "ok", "pick": shown, "dropped": dropped, "claims_corrected": corrected_total}


def judge_plan(answer: Mapping[str, Any], ctx: Any, bridge: Mapping[str, Any], *, provider_label: str,
               model: str) -> dict[str, Any]:
    """Mode ``plan``: one option index per slot; the plan is rebuilt with those picks and the whole-day
    check, repair and protein top-up run again (``validate_ai_plan``)."""
    if answer.get("status") == "refused":
        return {"status": "refused", "message": REFUSED_TEXT, "plan": None, "dropped": [], "claims_corrected": 0}
    plan = bridge.get("plan") or {}
    picks: dict[str, int] = {}
    dropped: list[dict[str, Any]] = []
    for index, entry in enumerate(answer.get("picks") or []):
        slot = entry.get("meal") if isinstance(entry, Mapping) else None
        option = entry.get("index") if isinstance(entry, Mapping) else None
        if slot not in plan or not isinstance(option, int) or isinstance(option, bool) or not 0 <= option < len(plan[slot]):
            dropped.append({"index": index, "reason": "not_a_candidate"})
            continue
        if slot in picks:
            dropped.append({"index": index, "reason": "duplicate"})
            continue
        picks[slot] = option
    if not picks:
        return {"status": "dropped_all", "message": FALLBACK_TEXT, "plan": None, "dropped": dropped, "claims_corrected": 0}
    result = validate_ai_plan(ctx, picks)
    return {"status": "ok", **label(provider_label, model), "ai_picks": picks, "plan": result, "dropped": dropped,
            "claims_corrected": 0}


def fallback(bridge: Mapping[str, Any], limit: int = 8) -> dict[str, Any]:
    """V8: the rule result shown when no AI idea survives (the meals that fit, then the top foods)."""
    return {"note": FALLBACK_TEXT, "meals": list(bridge.get("meals", [])),
            "foods": [{k: f[k] for k in ("food_id", "name", "portion", "renal_rating", "fit_text")} for f in bridge.get("foods", [])[:limit]]}
