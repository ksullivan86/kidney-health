"""Saving from the Ask chat (assistant step 2, part C; ``docs/dev/plans/assistant-step2.md`` "Part C", ARCHITECTURE
"Ask chat").

The model may call ``log_food`` and ``save_recipe``. What the app does with such a call depends on how much the
person trusts the assistant (:func:`effective_trust`):

* ``ask`` (the default, and the only mode while the admin switch ``ai.allow_trusted_saves`` is off): the call is **not
  executed**. :func:`propose` places the items with the MCP tools' own :func:`app.mcp.tools.place_items` and returns
  the card the Ask screen shows: the resolved foods and amounts, the totals, and the exact request body for the app's
  normal save route. Nothing is written until the person presses Save on the card, and then the page (not the model)
  posts that body to ``POST /api/log/batch`` or ``POST /api/meals`` like any other save in the app.
* ``conversation`` / ``always`` (admin switch on): :func:`save_now` runs the MCP tool itself
  (:func:`app.mcp.tools.log_food` / :func:`app.mcp.tools.save_recipe`, all or nothing in one transaction through
  :func:`app.mcp.tools.write_once`) with a ``request_key`` made from the chat request's ``request_id``, so a request
  that is sent twice saves once. The activity log gets the same ``assistant.food_logged`` / ``assistant.recipe_saved``
  rows as an access token's saves, with ``via: "Ask"``. The answer carries a "saved" card with what was saved and the
  ids Undo deletes through the normal DELETE routes.

Either way: a food eaten to treat a low (``purpose: "hypo"``) is saved like any other and never warned about, no
card or message here carries a warning about it, a message that matched a low or emergency rule never reaches this
code (the rules answer first), and nothing here creates a number: totals are the app's (:func:`app.mcp.tools.saved_totals`).

**Tastes are the exception to the trust setting** (note 09 §4.8, decision Q2). The model's third saving tool,
``set_food_preference`` (:mod:`app.ai.chat_preference`), is a card in all three modes: :func:`run_save` hands it to
:func:`app.ai.chat_preference.propose` before it looks at the mode, :func:`effective_trust` is not consulted for it, and
:func:`save_now` refuses it. The page applies it only when the person presses Remember.
"""
from __future__ import annotations

import logging
import sqlite3
import uuid
from typing import Any, Mapping

from fastapi import Request
from pydantic import ValidationError

from .. import brand
from .. import foods
from .. import log as food_log
from ..auth.models import User
from ..mcp import tools as T
from ..nutrients import scale_nutrients
from ..settings_registry import TRUST_CHOICES
from ..textclean import clean_label
from . import chat as CH
from . import chat_preference as PREF
from . import prompts

log = logging.getLogger(f"{brand.LOGGER_NAME}.ai")

REQUEST_ID_MIN = 8
REQUEST_ID_MAX = 48  # "<request_id>-<n>" must fit the 64 characters a request_key may have
REQUEST_ID_PATTERN = r"^[A-Za-z0-9_-]+$"
_NAMESPACE = uuid.UUID("5d0a3a9e-7c1e-4b6e-9a53-2f8f6b1c0a77")  # client_ids of a card's entries (stable per request)

SAFETY_ERROR = "A save cannot follow a message about a low or an emergency. Answer without saving."
DUPLICATE_NOTE = ("This request already made its save, so nothing was saved again. Tell the person what was saved (or, if "
                  "the entries are gone now, that the person removed them). Do not save again in this message.")
LOG_PATH = "/api/log/batch"  # the normal routes a card's Save presses post to (js/views/ask.js uses the same two)
RECIPE_PATH = "/api/meals"


def effective_trust(*, admin_allows: bool, stored: str, requested: str | None) -> str:
    """The trust this request runs with. ``ask`` unless the admin switch is on **and** the person chose it: ``always``
    is the stored choice alone; ``conversation`` needs the stored choice and the page saying this conversation is
    trusted (the page forgets it at New conversation and after 12 hours). Anything else is ``ask``."""
    if not admin_allows or stored not in TRUST_CHOICES:
        return "ask"
    if stored == "always":
        return "always"
    if stored == "conversation" and requested == "conversation":
        return "conversation"
    return "ask"


def tool_schemas() -> dict[str, dict[str, Any]]:
    """The input schema of every tool the chat offers (:data:`app.ai.chat.OFFERED_TOOLS`): the MCP tools' own, so they cannot
    drift, and ``set_food_preference``'s, which is not an MCP tool (the MCP server never lists it)."""
    return {name: PREF.INPUT_SCHEMA if name == PREF.TOOL_NAME else T.TOOLS_BY_NAME[name].input_schema for name in CH.OFFERED_TOOLS}


def save_key(request_id: str, n: int) -> str:
    """The ``request_key`` of the ``n``-th save of a chat request (stable when the same request is sent again)."""
    return f"{request_id}-{n}"


def client_id(user_id: int, request_id: str, index: int) -> str:
    """A UUID for the ``index``-th entry of a card, stable for one person and request: pressing Save twice posts the
    same ``client_id`` and the log route answers with the entry that exists (it never adds it again)."""
    return str(uuid.uuid5(_NAMESPACE, f"{int(user_id)}:{request_id}:{index}"))


# --------------------------------------------------------------------------- #
# What the app could not place, in its own words
# --------------------------------------------------------------------------- #


def person_questions(unresolved: list[Mapping[str, Any]]) -> list[dict[str, str]]:
    """The tools' ``unresolved`` entries as questions for the person (the tools' own wording is written for the model)."""
    out: list[dict[str, str]] = []
    for item in unresolved:
        food = prompts.clean(str(item.get("food") or ""), 100)
        reason = item.get("reason")
        if reason == "no_match":
            text = f'I could not find "{food}" in your foods. Try another name, or add it in Foods.'
        elif reason == "several_matches":
            names = "; ".join(prompts.clean(str(a.get("name") or ""), 80) for a in item.get("alternatives") or [])
            text = f'Which one is "{food}"? {names}'
        elif reason in ("unknown_food_id", "unknown_fdc_id"):
            text = f'I could not use "{food}". Try another name.'
        elif reason == "usda_unavailable":
            text = f'I could not look up "{food}" just now. Try again later, or add it in Foods.'
        elif reason == "amount_too_large":
            text = f'That amount of "{food}" looks too large. Check it.'
        elif reason in ("servings_only", "unknown_unit"):  # these questions are already written for the person
            text = prompts.clean(str(item.get("question") or ""), 300)
        else:
            text = f'I could not place "{food}".'
        out.append({"food": food, "question": text})
    return out


# --------------------------------------------------------------------------- #
# Ask mode: the card to confirm (nothing is written)
# --------------------------------------------------------------------------- #


def item_view(one: T.Placed, purpose: str | None) -> dict[str, Any]:
    """A placed item as the card shows it: what the app found and the amount it would save."""
    row = one.row
    hypo = food_log.resolve_purpose(row, purpose) == food_log.HYPO_PURPOSE
    return {
        "name": row["name"], "brand": row["brand"], "as_asked": T._as_asked(one.amount_, one.unit),
        "servings": round(one.servings, 3), "grams": None if one.grams is None else round(one.grams, 1),
        "food_id": one.food_id, "fdc_id": int(row["fdc_id"]) if one.mapped is not None else None,
        "new_food": one.mapped is not None, "counted_as_treating_a_low": hypo,
    }


def _imports(placed: list[T.Placed]) -> list[int]:
    """USDA foods that are not in the person's list yet: the page adds them (``POST /api/foods/usda/import``) before it saves."""
    return sorted({int(one.row["fdc_id"]) for one in placed if one.mapped is not None})


def propose(call: T.Call, name: str, arguments: Mapping[str, Any], request_id: str) -> CH.SaveStep:
    """Ask mode: place the items exactly as the saving tool would, write nothing, and build the card (or, when an item
    cannot be placed, the questions)."""
    tool = T.TOOLS_BY_NAME[name]
    try:
        args = tool.args.model_validate(dict(arguments))
    except ValidationError as exc:
        raise T.ToolError(T.describe(exc)) from None
    if name == "log_food":
        return _propose_log(call, args, request_id)
    return _propose_recipe(call, args, request_id)


def _propose_log(call: T.Call, args: T.LogArgs, request_id: str) -> CH.SaveStep:
    day = args.date or food_log.today_local()
    placed, unresolved = T.place_items(call, args.items)
    if unresolved:
        return CH.SaveStep(result=T.unresolved_result(unresolved, "log_food", date=day, meal=args.meal, status=args.status),
                           questions=person_questions(unresolved))
    entries = []
    for index, one in enumerate(placed):
        entry: dict[str, Any] = {"date": day, "meal": args.meal, "food_id": one.food_id, "status": args.status,
                                 "client_id": client_id(call.user.id, request_id, index)}
        entry["grams" if one.by_grams else "servings"] = one.quantity if one.by_grams else one.servings
        if args.purpose is not None:
            entry["purpose"] = args.purpose
        if one.mapped is not None:
            entry["fdc_id"] = int(one.row["fdc_id"])  # the page swaps in the food_id after importing it, then drops this
        entries.append(entry)
    scaled = [scale_nutrients(foods.raw_nutrients(one.row), one.servings) for one in placed]
    items = [item_view(one, args.purpose) for one in placed]
    pending = {
        "tool": "log_food", "date": day, "meal": args.meal, "status": args.status,
        "purpose": args.purpose, "items": items, "imports": _imports(placed),
        "numbers": [{"title": "This adds", "rows": CH.totals_rows(T.saved_totals(scaled))}],
        "payload": {"entries": entries},
    }
    return CH.SaveStep(pending=pending, questions=[])


def _propose_recipe(call: T.Call, args: T.RecipeArgs, request_id: str) -> CH.SaveStep:
    recipe = clean_label(args.name, max_len=T.RECIPE_NAME_MAX)
    if recipe is None:
        raise T.ToolError("Give the recipe a name.")
    placed, unresolved = T.place_items(call, args.ingredients)
    if unresolved:
        return CH.SaveStep(result=T.unresolved_result(unresolved, "save_recipe", name=recipe),
                           questions=person_questions(unresolved))
    scaled = [scale_nutrients(foods.raw_nutrients(one.row), one.servings) for one in placed]
    items = [item_view(one, None) for one in placed]
    ingredients = [{"food_id": one.food_id, "servings": float(one.servings),
                    **({"fdc_id": int(one.row["fdc_id"])} if one.mapped is not None else {})} for one in placed]
    pending = {
        "tool": "save_recipe", "name": recipe, "servings_made": args.servings, "source_url": args.source_url,
        "items": items, "imports": _imports(placed),
        "numbers": [{"title": "Whole recipe", "rows": CH.totals_rows(T.saved_totals(scaled))},
                    {"title": "Per serving", "rows": CH.totals_rows(T.saved_totals(scaled, args.servings))}],
        "payload": {"name": recipe, "note": T.recipe_note(args.servings, args.source_url), "items": ingredients},
    }
    return CH.SaveStep(pending=pending, questions=[])


# --------------------------------------------------------------------------- #
# Trusted mode: the save runs at once, through the MCP tools' own code
# --------------------------------------------------------------------------- #


def saved_card(name: str, result: Mapping[str, Any]) -> dict[str, Any]:
    """What a finished save shows the person, built from the tool's own answer (read back from the database): the
    foods and amounts, the totals and the ids Undo deletes."""
    added = [str(a.get("name") or "") for a in result.get("added_to_foods") or []]
    if name == "log_food":
        entries = result.get("entries") or []
        return {
            "tool": "log_food", "date": result.get("date"), "meal": result.get("meal"), "status": result.get("status"),
            "items": [{"name": e["food_name"], "servings": e["servings"], "grams": e["grams"],
                       "counted_as_treating_a_low": bool(e.get("counted_as_treating_a_low"))} for e in entries],
            "undo": {"entry_ids": [int(e["entry_id"]) for e in entries]},
            "numbers": [{"title": "Saved", "rows": CH.totals_rows(result.get("totals") or {})}],
            "added_to_foods": added, "duplicate": bool(result.get("duplicate")),
        }
    meal = result.get("meal") or {}
    return {
        "tool": "save_recipe", "name": meal.get("name"), "servings_made": result.get("servings_made"),
        "items": [{"name": i["food_name"], "servings": i["servings"], "grams": None,
                   "counted_as_treating_a_low": False} for i in meal.get("items") or []],
        "undo": {"meal_id": int(meal["id"])},
        "numbers": [{"title": "Whole recipe", "rows": CH.totals_rows(result.get("totals_whole_recipe") or {})},
                    {"title": "Per serving", "rows": CH.totals_rows(result.get("totals_per_serving") or {})}],
        "added_to_foods": added, "duplicate": bool(result.get("duplicate")),
    }


def save_now(call: T.Call, name: str, arguments: Mapping[str, Any], key: str) -> CH.SaveStep:
    """Trusted mode: run ``log_food`` or ``save_recipe`` (the MCP tool, all or nothing) with the request's key. Never a
    taste: ``set_food_preference`` is a card in every mode, so it is refused here whoever calls this."""
    if name == PREF.TOOL_NAME or name not in T.TOOLS_BY_NAME or not T.TOOLS_BY_NAME[name].writes:
        raise T.ToolError("This needs the person's confirmation on a card; it is never saved without it.")
    result = T.run(T.TOOLS_BY_NAME[name], call, {**arguments, "request_key": key})
    questions: list[dict[str, Any]] | None = None
    saved: dict[str, Any] | None = None
    if result.get("saved") is True:
        saved, questions = saved_card(name, result), []
    elif result.get("unresolved"):
        questions = person_questions(result["unresolved"])
    closes = bool(result.get("duplicate"))
    if closes:  # a repeat of this request: the model must not "save again with a new key"
        result["notes"] = [n for n in result.get("notes") or [] if "request_key" not in n] + [DUPLICATE_NOTE]
    return CH.SaveStep(result=result, saved=saved, questions=questions, closes=closes)


def run_save(request: Request, conn: sqlite3.Connection, user: User, name: str, arguments: Mapping[str, Any], n: int, *,
             mode: str, request_id: str, newest: str) -> CH.SaveStep:
    """The model's ``n``-th save call of this message, in a worker thread. ``mode`` is :func:`effective_trust`'s answer.
    A taste (``set_food_preference``) ignores ``mode``: it is a card whatever the person trusts. A short message for the model
    on a refused or invalid call; a bug never ends the conversation with a 500."""
    if CH.is_safety_text(newest):  # cannot happen (the rules answer such a message first); a save never follows one
        return CH.SaveStep(error=SAFETY_ERROR)
    call = T.Call(request, conn, user, T.Asker())
    args = {k: v for k, v in arguments.items() if k != "request_key"}  # the app makes the key; the model never does
    try:
        if name == PREF.TOOL_NAME:  # always a card, in every mode (note 09 §4.8); writes nothing
            return PREF.propose(call, args)
        if mode == "ask":
            return propose(call, name, args, request_id)
        return save_now(call, name, args, save_key(request_id, n))
    except T.ToolError as exc:
        return CH.SaveStep(error=str(exc))
    except Exception:  # noqa: BLE001
        log.exception("Ask chat: %s failed", name)
        return CH.SaveStep(error=prompts.CHAT_TOOL_FAILED)
    finally:
        if conn.in_transaction:  # a refused or failed save leaves the connection clean for the next step
            conn.rollback()
