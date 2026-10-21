"""Ask proposes a taste: ``set_food_preference`` (note 09 §4.8, decision Q2; ARCHITECTURE "Saving from the chat").

The model may ask the app to remember that the person likes a food or food group, wants it less often, does not want it,
or wants the app to forget what it was told. A preference silently shapes every later suggestion, so unlike a log entry it
is **always a card**, whatever the person's trust setting (``ask``, ``conversation`` or ``always``):

* :func:`propose` is the only thing that runs for this tool. It validates the call, reads the person's current state, and
  returns the card. It writes **nothing**: no ``food_preferences`` row, no setting, no remembered request key. The trust
  setting is not consulted (:func:`app.ai.chat_save.effective_trust` is not called for this tool) and
  :func:`app.ai.chat_save.save_now` refuses it.
* The card is built from the database, not from the model's words: the food's own name, the fixed wording of the page
  ("Remember this for your suggestions? Salmon: less often."), the new value and the previous one.
* On **Remember** the page (not the model) applies it through the app's normal routes: for a food ``PUT
  /api/guidance/preferences/{food_id}`` with ``{preference, source: "ask"}`` (``clear`` = ``DELETE``); for a food group it
  reads the person's current ``guidance`` setting at that moment, moves only that group between ``like_categories``,
  ``less_categories`` and ``exclude_categories`` and saves the whole object with ``PATCH /api/me/settings``. **Undo**
  puts back exactly the previous state the card carries.
* Not reachable over the MCP server: this tool is not in :data:`app.mcp.tools.TOOLS`, so ``tools/list`` never shows it and
  ``tools/call`` answers "unknown tool" for every token scope (``tests/test_ai_chat_preference.py``). External assistants
  get their own scope for it in a later step.

A preference never reaches the rule-based answers for a low or an emergency (they run before any model is asked) and never the
Treating a low card, its options or its swaps (note 09 §4.9). A taste is not an allergy: the app cannot check allergens, and
the prompt (rule 10) tells the model not to use this tool for one.
"""
from __future__ import annotations

from typing import Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .. import foods
from ..guidance import context as guidance_context
from ..mcp import tools as T
from ..profile import settings_store
from . import chat as CH
from . import prompts

TOOL_NAME = CH.PREFERENCE_TOOL  # "set_food_preference"
PREFERENCES: tuple[str, ...] = ("like", "less", "not_for_me", "clear")
SOURCE = "ask"  # food_preferences.source of a change the Ask chat proposed and the person confirmed
FOOD_PATH = "/api/guidance/preferences"  # the page's PUT and DELETE (js/core.js api.setFoodPreference / clearFoodPreference)
SETTINGS_PATH = "/api/me/settings"  # the page's GET and PATCH for a food group
# A food group is in at most one of three lists of the ``guidance`` setting; ``not_for_me`` is "Never suggest".
GROUP_LISTS: Mapping[str, str] = {"like": "like_categories", "less": "less_categories", "not_for_me": "exclude_categories"}
MAX_GROUP_NAMES = 50  # each list of the ``guidance`` setting holds at most this many (app.settings_registry)
CATEGORY_NAMES_SHOWN = 20  # food groups named in the message to the model when its category is not one of them

INPUT_SCHEMA: dict[str, Any] = {
    "type": "object", "additionalProperties": False, "required": ["preference"],
    "properties": {
        "food_id": {"type": "integer", "minimum": 1,
                    "description": "A food_id from search_foods (a result with in_app true). Give this or category, not both."},
        "category": {"type": "string", "minLength": 1, "maxLength": 100,
                     "description": "One of the person's food groups, for example \"Fish & Seafood\". Give this or food_id."},
        "preference": {"type": "string", "enum": list(PREFERENCES),
                       "description": "like, less (less often), not_for_me, or clear (forget what was said)."}}}


class PreferenceArgs(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)

    food_id: int | None = Field(default=None, ge=1, le=T.MAX_ROW_ID)
    category: str | None = Field(default=None, min_length=1, max_length=100)
    preference: Literal["like", "less", "not_for_me", "clear"]

    @model_validator(mode="after")
    def exactly_one_target(self) -> "PreferenceArgs":
        if (self.food_id is None) == (self.category is None):
            raise ValueError("give exactly one of food_id and category")
        return self


def unchanged(args_preference: str, previous: str) -> bool:
    """Whether asking for ``args_preference`` changes nothing. ``clear`` has nothing to forget when there is no taste saved;
    a ``neutral`` row ("stop using what was learned about this food") is not a taste either, and ``clear`` leaves it alone."""
    if args_preference == "clear":
        return previous in ("none", "neutral")
    return previous == args_preference


def nothing_to_do(name: str, args_preference: str) -> CH.SaveStep:
    """The result the model gets when the person already has this choice (no card, nothing to confirm)."""
    what = "has nothing saved" if args_preference == "clear" else "already has this choice"
    return CH.SaveStep(result={"saved": False, "changed": False,
                               "note": f"The person {what} for {name}, so nothing needs confirming. Tell them so."})


def propose(call: T.Call, arguments: Mapping[str, Any]) -> CH.SaveStep:
    """Validate the call, read the person's current state, and build the card. Writes nothing. Raises
    :class:`app.mcp.tools.ToolError` (a short message for the model) for a call that cannot be a card."""
    try:
        args = PreferenceArgs.model_validate(dict(arguments))
    except ValidationError as exc:
        raise T.ToolError(T.describe(exc)) from None
    if args.food_id is not None:
        return _propose_food(call, args.food_id, args.preference)
    assert args.category is not None
    return _propose_group(call, args.category, args.preference)


def _propose_food(call: T.Call, food_id: int, preference: str) -> CH.SaveStep:
    row = foods.fetch_user_food(call.conn, call.user.id, food_id)
    if row is None:
        raise T.ToolError(f"food_id {food_id} is not one of the person's foods. Use search_foods and give the id of a result "
                          "with in_app true, or use a category.")
    held = call.conn.execute("SELECT preference, COALESCE(source, 'person') AS source FROM food_preferences "
                             "WHERE user_id = ? AND food_id = ?", (call.user.id, food_id)).fetchone()
    previous = held["preference"] if held is not None else "none"
    name = row["name"]
    if unchanged(preference, previous):
        return nothing_to_do(name, preference)
    if preference != "clear":
        total, never = call.conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(preference = ?), 0) FROM food_preferences WHERE user_id = ?",
            (guidance_context.PREFERENCE_NOT_FOR_ME, call.user.id)).fetchone()
        if previous == "none" and total >= guidance_context.MAX_FOOD_PREFERENCES:
            raise T.ToolError(f"The person's food preferences are full ({guidance_context.MAX_FOOD_PREFERENCES} foods), so "
                              "nothing can be added. Tell them to remove one in Settings.")
        if preference == guidance_context.PREFERENCE_NOT_FOR_ME and never >= guidance_context.MAX_NOT_FOR_ME:
            raise T.ToolError(f"The person's \"Not for me\" list is full ({guidance_context.MAX_NOT_FOR_ME} foods), so nothing "
                              "can be added. Tell them to remove one in Settings.")
    pending = {
        "tool": TOOL_NAME,
        "target": {"kind": "food", "food_id": int(row["id"]), "name": name, "category": row["category"]},
        "preference": preference, "previous": previous,
        "previous_source": held["source"] if held is not None else None,
        "payload": None if preference == "clear" else {"preference": preference, "source": SOURCE},
    }
    return CH.SaveStep(pending=pending, questions=[])


def match_category(wanted: str, known: list[str]) -> str | None:
    """The person's own spelling of the food group ``wanted`` names (exact, else ignoring case and spacing), else ``None``."""
    if wanted in known:
        return wanted
    key = " ".join(wanted.split()).casefold()
    return next((c for c in known if " ".join(c.split()).casefold() == key), None)


def _propose_group(call: T.Call, wanted: str, preference: str) -> CH.SaveStep:
    known = foods.visible_categories(call.conn, call.user.id)
    name = match_category(wanted, known)
    if name is None:
        shown = ", ".join(prompts.clean(c, 60) for c in known[:CATEGORY_NAMES_SHOWN])
        raise T.ToolError(f"category must be one of the person's food groups: {shown}.")
    settings = guidance_context.user_settings(call.conn, settings_store(call.request), call.user.id)
    lists = {kind: list(guidance_context.setting_value(settings, key, ()) or ()) for kind, key in GROUP_LISTS.items()}
    previous = next((kind for kind in GROUP_LISTS if name in lists[kind]), "none")
    if unchanged(preference, previous):
        return nothing_to_do(name, preference)
    if preference != "clear" and len(lists[preference]) >= MAX_GROUP_NAMES:
        raise T.ToolError(f"The person's list of food groups is full ({MAX_GROUP_NAMES}), so nothing can be added. Tell them "
                          "to remove one in Settings.")
    pending = {
        "tool": TOOL_NAME,
        "target": {"kind": "group", "name": name},
        "preference": preference, "previous": previous, "previous_source": None, "payload": None,
    }
    return CH.SaveStep(pending=pending, questions=[])
