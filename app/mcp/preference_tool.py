"""``set_food_preference`` over MCP, for a token with ``assistant:prefs`` (note 09 §4.8b; ARCHITECTURE "Assistant MCP server",
"Remembering a taste (scope ``assistant:prefs``)"; ``docs/assistant.md``).

The in-app Ask chat already proposes a taste ("I don't really like salmon") as a card the person confirms
(:mod:`app.ai.chat_preference`). An assistant connected with a token has no card, and a preference silently shapes every later
suggestion, so the tool is **opt-in, narrow and limited**:

* **Scope.** Listed by ``tools/list`` and callable only with ``assistant:prefs`` (a second tick when the token is made, off by
  default). The scope implies ``assistant:read`` and nothing else; ``assistant:log`` does not give it. A token without it is
  told "Unknown tool", as if the tool did not exist.
* **Input.** ``{food_id | category, preference: like | less | not_for_me | clear, request_key}``: exactly one of ``food_id`` (a
  food the person may use) and ``category`` (one of the person's food groups). The checks are Ask's own
  (:func:`app.ai.chat_preference.resolve_food`, ``resolve_group`` and the room checks), not a copy.
* **What it writes.** The same server function the page's confirmed card ends in: a food through
  :func:`app.guidance.api.apply_preference` (``PUT /api/guidance/preferences/{id}``) with ``source = 'assistant'``, ``clear``
  through :func:`app.guidance.api.drop_preference` (``DELETE``); a food group through the person's ``guidance`` setting
  (``PATCH /api/me/settings``), moving only that group between ``like_categories``, ``less_categories`` and
  ``exclude_categories``. A group has no ``source`` (the setting does not carry one); its change is in the activity list.
* **One transaction.** The write, the audit row ``assistant.preference_set`` (the food or group, old and new, the token's name) and
  the ``request_key`` are committed together. A repeat with the same key within 24 hours writes nothing and answers
  ``duplicate: true``; it does not count toward the daily cap.
* **Limits.** The server's 60 requests a minute per token, and 30 changes a day per token (``mcp_prefs``, key ``token:<id>``),
  refused with the limit's own ``429`` and ``Retry-After``: bulk shaping of someone's suggestions is not a chat's job.
* **What it never reaches.** The answer is short (what was set, how to undo it in the app) and holds no other food and no list: the
  tool reads only the one food or group, its current value and the room left. It never touches ``hypo.prefilter``,
  ``swaps.hypo_options``, ``insights.best_hypo_food`` or the Treating a low card. The one preference that could change the low
  options is "Not for me" / "Never suggest" (a person's exclusions leave that list unless nothing would be left, note 09 §8 Q1), so
  the tool refuses ``not_for_me`` for a food that treats a low and for a group that holds one: only the person decides that, in the
  app. ``like``, ``less`` and ``clear`` are never read by the low options (note 09 §4.9).
"""
from __future__ import annotations

import logging
from typing import Any, Mapping

from fastapi import HTTPException
from pydantic import BaseModel, Field

from .. import foods
from ..ai import chat_preference as PREF
from ..audit import audit
from ..auth import api_tokens
from ..auth.accounts import begin_immediate
from ..auth.context import auth_context, request_ip
from ..auth.ratelimit import register_limit
from ..guidance import api as guidance_api
from ..guidance import context as guidance_context
from ..log import HYPO_FLAG
from ..settings_store import InvalidSettingValue, SettingLocked, SettingNotEditable, SettingsUnavailable
from . import request_keys
from . import tools as T

logger = logging.getLogger("kidney_health.mcp")

TOOL_NAME = PREF.TOOL_NAME  # "set_food_preference"
SOURCE = guidance_context.ASSISTANT_SOURCE  # food_preferences.source of a change made here (note 09 §4.8b)
DAILY_LIMIT = "mcp_prefs"
DAILY_MAX = 30  # changes a day per token (a sliding 24 hours)
register_limit(DAILY_LIMIT, DAILY_MAX, 24 * 3600, "Too many changes from this assistant today. Try again later.")

WHERE_FOOD = "Settings → Meal guidance → Your food preferences"
WHERE_GROUP = "Settings → Meal guidance → Your food preferences → Kinds of food"
PHRASE: Mapping[str, str] = {"like": "more like this", "less": "less often", "not_for_me": "not for me"}
GROUP_PHRASE: Mapping[str, str] = {"like": "more like this", "less": "less often", "not_for_me": "never suggest"}

DESCRIPTION = (
    "Remember a taste for the person's meal suggestions: they like a food or food group (like), want it less often (less), do "
    "not want it suggested (not_for_me), or want what they said forgotten (clear). Use it only when the person says the taste "
    "themselves in this conversation, and only after you read it back and they said yes; never infer a taste from what they log "
    "or ask about, and never for an allergy (the app cannot check allergens). Give exactly one of food_id (from search_foods, a "
    "result with in_app true) and category (one of the person's food groups, for example \"Fish & Seafood\"). It only changes "
    "the order of the app's suggestions: it changes no limit, warning or number, and has no part in treating a low (a food or "
    "group that can treat a low cannot be set to not_for_me here; the person does that in the app). The answer says what was "
    "set: tell the person, and that they can change or remove it in the app (" + WHERE_FOOD + "). At most "
    f"{DAILY_MAX} changes a day per token. " + T.RETRY_ADVICE
)


class PreferenceCall(PREF.PreferenceArgs):
    """Ask's arguments (exactly one target, strict) plus the duplicate guard, which is not optional here."""

    request_key: str = Field(min_length=request_keys.KEY_MIN, max_length=request_keys.KEY_MAX,
                             pattern=request_keys.KEY_PATTERN)


def input_schema() -> dict[str, Any]:
    """Ask's schema (so the two cannot drift) with the required ``request_key``."""
    schema = {**PREF.INPUT_SCHEMA, "properties": {**PREF.INPUT_SCHEMA["properties"], "request_key": T._REQUEST_KEY}}
    schema["required"] = [*PREF.INPUT_SCHEMA["required"], "request_key"]
    return schema


# --------------------------------------------------------------------------- #
# What treats a low (those exclusions are the person's alone)
# --------------------------------------------------------------------------- #


def food_treats_a_low(row: Mapping[str, Any]) -> bool:
    return HYPO_FLAG in foods.parse_flags(row["flags_json"])


def group_has_a_low_treatment(call: T.Call, name: str) -> bool:
    """Whether a food the person can see in the food group is flagged as a low treatment."""
    rows = call.conn.execute(
        f"""SELECT f.flags_json FROM foods f
            WHERE f.category = ? AND f.hidden = 0 AND {foods.access_clause('f')}""",
        (name, *foods.access_params(call.user.id))).fetchall()
    return any(HYPO_FLAG in foods.parse_flags(r["flags_json"]) for r in rows)


# --------------------------------------------------------------------------- #
# The tool
# --------------------------------------------------------------------------- #


def answer(kind: str, name: str, preference: str, *, duplicate: bool = False) -> dict[str, Any]:
    """The whole answer: what was set and how to undo it. No other food, no list."""
    where = WHERE_GROUP if kind == "group" else WHERE_FOOD
    what = "food group" if kind == "group" else "food"
    if duplicate:
        said = "A call with this request_key already did this, so nothing was changed again."
    elif preference == "clear":
        said = f"Cleared: nothing is saved for the {what} {name} now."
    else:
        said = f"Remembered: {name} ({what}): {(GROUP_PHRASE if kind == 'group' else PHRASE)[preference]}."
    return {
        "saved": True, **({"duplicate": True} if duplicate else {}),
        "target": {"kind": kind, "name": name}, "preference": preference,
        "note": f"{said} It only changes the order of suggestions. The person can change or undo it in the app ({where}). "
                "Tell the person what you set.",
    }


def refuse_low_treatment(kind: str, name: str) -> T.ToolError:
    if kind == "group":
        return T.ToolError(f"{name} holds foods that can treat a low, so only the person can set it to Never suggest, in the "
                           f"app ({WHERE_GROUP}). Nothing was changed.")
    return T.ToolError(f"{name} can treat a low, so only the person can mark it Not for me, in the app ({WHERE_FOOD}). "
                       "Nothing was changed.")


def check_target(call: T.Call, args: PreferenceCall) -> tuple[str, str]:
    """``(kind, name)`` of the one food or group, read-only: Ask's checks, then the low-treatment rule."""
    if args.food_id is not None:
        row = PREF.resolve_food(call, args.food_id)
        if args.preference == "not_for_me" and food_treats_a_low(row):
            raise refuse_low_treatment("food", row["name"])
        return "food", row["name"]
    assert args.category is not None
    name = PREF.resolve_group(call, args.category)
    if args.preference == "not_for_me" and group_has_a_low_treatment(call, name):
        raise refuse_low_treatment("group", name)
    return "group", name


def write_group(call: T.Call, name: str, preference: str) -> None:
    """Move only ``name`` between the three lists of the person's ``guidance`` setting (what the page does with PATCH
    /api/me/settings), inside the caller's transaction."""
    store = auth_context(call.request).store
    settings = guidance_context.user_settings(call.conn, store, call.user.id)
    value = settings.model_dump() if isinstance(settings, BaseModel) else dict(settings)
    for field in PREF.GROUP_LISTS.values():
        value[field] = [g for g in value.get(field) or [] if g != name]
    if preference != "clear":
        field = PREF.GROUP_LISTS[preference]
        value[field] = [*value[field], name]
    try:
        store.update_user(call.conn, call.user.id, {"guidance": value})
    except (SettingLocked, SettingNotEditable, SettingsUnavailable, InvalidSettingValue):
        raise T.ToolError("The person's food group choices cannot be changed right now. Tell them to use Settings.") from None


def set_food_preference(call: T.Call, args: PreferenceCall) -> dict[str, Any]:
    if call.asker is not None:  # the Ask chat has its own tool, which is always a card
        raise T.ToolError("This tool is not available here.")
    token = call.request.state.api_token
    key = args.request_key
    seen = T.earlier_save(call, TOOL_NAME, key)  # a retry gets the first answer, whatever has changed since, and costs nothing
    if seen is not None:
        return again(seen)
    check_target(call, args)  # a refused call counts nowhere
    auth_context(call.request).limits.take(DAILY_LIMIT, f"token:{token.id}")  # 429 + Retry-After past 30 changes a day
    conn = call.conn
    try:
        begin_immediate(conn)
        raced = T.earlier_save(call, TOOL_NAME, key)  # inside the write lock: a retry that raced the first call
        if raced is not None:
            conn.rollback()
            return again(raced)
        kind, name = check_target(call, args)  # the same checks, now under the lock (the food may have been deleted)
        if kind == "food":
            assert args.food_id is not None
            previous, _ = PREF.held_preference(call, args.food_id)
            changed = not PREF.unchanged(args.preference, previous)
            if changed:
                PREF.check_food_room(call, previous, args.preference)
                if args.preference == "clear":
                    guidance_api.drop_preference(conn, call.user.id, args.food_id)
                else:
                    guidance_api.apply_preference(conn, call.user.id, args.food_id, args.preference, SOURCE)
        else:
            lists, previous = PREF.group_state(call, name)
            changed = not PREF.unchanged(args.preference, previous)
            if changed:
                PREF.check_group_room(lists, args.preference)
                write_group(call, name, args.preference)
        if changed:  # nothing changed: nothing to audit, and the person's own value (and its source) stays as it was
            audit(conn, call.user.id, "assistant.preference_set", "api_token", token.id, ip=request_ip(call.request),
                  via=token.name, kind=kind, name=name, old=previous, new="none" if args.preference == "clear" else args.preference,
                  **({"food_id": args.food_id} if kind == "food" else {}))
        request_keys.remember(conn, call.user.id, token.id, TOOL_NAME, key,
                              {"kind": kind, "name": name, "preference": args.preference})
        conn.commit()
    except HTTPException as exc:  # a limit of the preference routes (409): say why, change nothing
        conn.rollback()
        raise T.ToolError(f"{exc.detail}. Tell the person to make room in the app.") from None
    except BaseException:
        conn.rollback()
        raise
    return answer(kind, name, args.preference)


def again(seen: request_keys.Seen) -> dict[str, Any]:
    """The answer to a repeat of a call with the same ``request_key``: what the first call set, and that nothing changed now."""
    saved = seen.saved
    return answer(str(saved.get("kind", "food")), str(saved.get("name", "")), str(saved.get("preference", "")), duplicate=True)


TOOL = T.Tool(
    TOOL_NAME, "Remember a taste", DESCRIPTION, input_schema(), PreferenceCall, set_food_preference,
    writes=True, scope=api_tokens.PREFS,
    hints={"readOnlyHint": False, "destructiveHint": True, "idempotentHint": True, "openWorldHint": False},
)
