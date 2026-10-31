"""Suggestions from someone on the Care team (design notes 21 and 29 §5; ARCHITECTURE.md "Care team").

Someone whose share has ``may_suggest`` on (a Care helper, a Caregiver or a Viewer such as a coach) suggests a meal for a day: foods
the person can use, with servings, and a short note. It waits in the person's Plan tab until they tap **Add to my plan** (planned
entries through their own insert) or **No thanks**, or until it expires after 14 days. Nothing is written to the person's log by
the suggester.

* ``POST /api/shared/{share_id}/suggestions``: send one (:func:`app.sharing.care_suggester`: the food log shared and
  ``may_suggest`` on, checked now). A food that treats a low is refused, and so is a note about lows, insulin, doses, medicines
  or lab results (the AI text checks: ``messages.BANNED_PATTERN`` and ``hypo.mentions_low``). At most 10 open per share and 20
  sent in 24 hours by one person.
* ``GET /api/shared/{share_id}/suggestions``: what you sent to this person and their answer, never a reason.
* ``GET /api/me/suggestions``: the person's open suggestions, each with what it adds to that day against their targets. Answers
  ``200`` with ``enabled: false`` while sharing is off, so the Plan tab never sees a failed request.
* ``POST /api/me/suggestions/{id}/accept`` / ``decline``.

Expiry and the end of a share are handled by :func:`app.sharing.expire_suggestions`, which every sharing route runs.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import timedelta
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator

from . import activity as activity_module
from . import log as log_module
from . import sharing
from .ai import guard
from .audit import audit
from .auth import clock
from .auth.accounts import begin_immediate
from .auth.context import request_ip
from .auth.deps import CurrentUser, current_user
from .auth.errors import ApiProblem
from .db import get_db
from .foods import fetch_user_food, raw_nutrients
from .guidance import hypo
from .guidance.messages import BANNED_PATTERN
from .models import MAX_SERVINGS, MAX_SQLITE_INT, Entry, Meal, Number, validate_date
from .nutrients import add_totals, count_unknown, empty_totals, round_nutrients, scale_nutrients
from .profile import get_profile

SUGGEST_DAYS = 14  # an open suggestion expires after this long (note 21 §8)
MAX_OPEN_PER_SHARE = 10
MAX_PER_DAY = 20  # sent by one person in 24 hours
MAX_NOTE = 280
MAX_ITEMS = 30
MAX_SENT_SHOWN = 50

NO_SUGGESTION = "That suggestion is no longer open."
NONE_LEFT = "None of these foods is on your list any more, so nothing was added. You can say no thanks instead."
NOTE_LOW = "Notes cannot be about lows. How to treat a low stays {}'s choice."
NOTE_WORD = ('Please leave out "{}". Notes are about food: never insulin, doses, medicines or lab results, and never call '
             'food "safe" or "bad".')
LOW_FOOD = "{} is for treating a low. Suggestions leave those out: how to treat a low stays {}'s choice."
TOO_MANY_OPEN = f"{{}} already has {MAX_OPEN_PER_SHARE} suggestions from you waiting for an answer. Wait for an answer first."
TOO_MANY_TODAY = f"You have sent {MAX_PER_DAY} suggestions in the last 24 hours, the most allowed. Try again tomorrow."

shared_router = APIRouter(prefix="/api/shared", tags=["shared"], dependencies=[Depends(current_user)])
me_router = APIRouter(prefix="/api/me/suggestions", tags=["me"], dependencies=[Depends(current_user)])

SuggestionId = Annotated[int, Path(ge=1, le=MAX_SQLITE_INT)]
Answer = Literal["open", "accepted", "declined", "expired", "ended"]


# --------------------------------------------------------------------------- #
# Bodies and answers
# --------------------------------------------------------------------------- #


class SuggestionItemIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    food_id: int = Field(ge=1, le=MAX_SQLITE_INT)
    servings: float = Field(gt=0, le=MAX_SERVINGS, allow_inf_nan=False)


class SuggestionCreate(BaseModel):
    """``POST /api/shared/{id}/suggestions``: a meal for one day, from foods the person can use, and an optional short note."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    date: str
    meal: Meal
    items: list[SuggestionItemIn] = Field(min_length=1, max_length=MAX_ITEMS)
    note: str | None = Field(default=None, max_length=MAX_NOTE)

    @field_validator("date")
    @classmethod
    def _date(cls, v: str) -> str:
        return validate_date(v)


class SuggestionItem(BaseModel):
    food_id: int
    name: str
    serving_desc: str | None = None
    servings: float
    available: bool  # the person can still use this food; Add leaves it out when not


class SuggestionFit(BaseModel):
    """What the suggestion adds to that day against the person's targets, the way Today counts it: ``totals`` of the suggested
    foods (``unknown``: how many foods miss each value), and ``day_status``, the day's projected status with it added."""

    totals: dict[str, Number | None]
    unknown: dict[str, int]
    day_status: dict[str, Any]


class SentSuggestion(BaseModel):
    id: int
    date: str
    meal: Meal
    items: list[SuggestionItem]
    note: str | None
    created_at: str
    expires_at: str
    answer: Answer
    answered_at: str | None
    fit: SuggestionFit | None = None


class SentList(BaseModel):
    suggestions: list[SentSuggestion]


class SuggestionForMe(BaseModel):
    id: int
    share_id: int
    from_name: str
    date: str
    meal: Meal
    items: list[SuggestionItem]
    note: str | None
    created_at: str
    expires_at: str
    fit: SuggestionFit


class SuggestionsForMe(BaseModel):
    enabled: bool
    suggestions: list[SuggestionForMe]


class AcceptResult(BaseModel):
    entries: list[Entry]
    skipped: int  # foods the person can no longer use, left out


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def note_problem(note: str | None, person: str) -> str | None:
    """Why a note cannot be sent, in one sentence, or None. The checks the app runs on AI text: a note about lows (the
    prefilter that routes a low to the "Treating a low" card) and the words guidance never uses (insulin, doses, medicines, lab
    results, "safe", "bad" and the rest of ``BANNED_PATTERN``)."""
    if not note:
        return None
    if hypo.mentions_low(note):
        return NOTE_LOW.format(person)
    found = BANNED_PATTERN.search(guard.fold(note))
    return NOTE_WORD.format(found.group(0)) if found else None


def _items(raw: str) -> list[dict[str, Any]]:
    try:
        got = json.loads(raw)
    except ValueError:
        return []
    return [i for i in got if isinstance(i, dict)] if isinstance(got, list) else []


def _answer(row: sqlite3.Row) -> str:
    return row["answer"] or "open"


def item_views(conn: sqlite3.Connection, owner_id: int, raw: str) -> list[dict[str, Any]]:
    """The suggestion's foods with their names as sent, and whether the person can still use each."""
    out = []
    for item in _items(raw):
        food_id = int(item.get("food_id") or 0)
        out.append({"food_id": food_id, "name": str(item.get("name") or ""), "serving_desc": item.get("serving_desc"),
                    "servings": float(item.get("servings") or 0), "available": fetch_user_food(conn, owner_id, food_id) is not None})
    return out


def fit_for(conn: sqlite3.Connection, request: Request, owner_id: int, day: str, meal: str, raw_items: str, *,
            activity_extra: bool) -> dict[str, Any]:
    """The suggestion's foods added to ``day``'s planned food, against the person's targets, as Today counts a day (design note
    29 §5). ``activity_extra`` as in :func:`app.log.day_summary` (off for a suggester without the activity area)."""
    profile = get_profile(conn, owner_id)
    if activity_extra:
        targets, _ = activity_module.day_extra(conn, owner_id, day, profile["targets"])
        profile = {**profile, "targets": targets}
    added = []
    for item in _items(raw_items):
        food = fetch_user_food(conn, owner_id, int(item.get("food_id") or 0))
        if food is not None:
            added.append({"status": "planned", "meal": meal, "purpose": None,
                          **scale_nutrients(raw_nutrients(food), float(item.get("servings") or 0))})
    rows = log_module.fetch_entries(conn, owner_id, day, day)
    figures = log_module.day_figures([*rows, *added], profile, log_module.carb_tolerance_for(conn, request, owner_id))
    totals: dict[str, float] = empty_totals()
    unknown: dict[str, int] = {}
    for values in added:
        add_totals(totals, values)
        count_unknown(unknown, values)
    return {"totals": round_nutrients(totals), "unknown": unknown, "day_status": figures["projected_status"]}


def sent_item(conn: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
    return {"id": int(row["id"]), "date": row["date"], "meal": row["meal"], "items": item_views(conn, int(row["owner_user_id"]), row["items_json"]),
            "note": row["note"], "created_at": row["created_at"], "expires_at": row["expires_at"], "answer": _answer(row),
            "answered_at": row["answered_at"]}


_FOR_ME = """
SELECT c.*, COALESCE(NULLIF(TRIM(f.display_name), ''), f.username) AS from_name
FROM care_suggestions c
JOIN shares s ON s.id = c.share_id
JOIN users f ON f.id = c.from_user_id
WHERE c.owner_user_id = ? AND c.answer IS NULL AND c.expires_at > ? AND s.ended_at IS NULL AND f.status = 'active'
"""


def _open_for_me(conn: sqlite3.Connection, user_id: int, suggestion_id: int) -> sqlite3.Row:
    row = conn.execute(_FOR_ME + " AND c.id = ?", (user_id, clock.now_iso(), suggestion_id)).fetchone()
    if row is None:
        raise ApiProblem(404, NO_SUGGESTION)
    return row


# --------------------------------------------------------------------------- #
# The suggester: /api/shared/{share_id}/suggestions
# --------------------------------------------------------------------------- #


@shared_router.post("/{share_id}/suggestions", response_model=SentSuggestion, status_code=201)
def send_suggestion(share_id: sharing.ShareId, body: SuggestionCreate, request: Request, care: sharing.Suggester,
                    conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """Suggest a meal for the person (``may_suggest`` on, checked now). The foods must be ones the person can use (``404``) and
    none may be for treating a low (``400``); the note is checked like AI text (``400`` with the reason). At most 10 open per
    share (``409``) and 20 sent in 24 hours (``429``). The answer has ``fit``: the person's day with it, against their targets.
    It never stops a suggestion: the person decides."""
    problem = note_problem(body.note, care.owner_name)
    if problem:
        raise ApiProblem(400, problem)
    items = []
    for index, item in enumerate(body.items):
        food = fetch_user_food(conn, care.owner.id, item.food_id)
        if food is None:
            raise HTTPException(status_code=404, detail=f"items[{index}]: food {item.food_id} not found")
        if log_module.resolve_purpose(food, None) == log_module.HYPO_PURPOSE:
            raise ApiProblem(400, LOW_FOOD.format(food["name"], care.owner_name))
        items.append({"food_id": int(food["id"]), "servings": item.servings, "name": food["name"], "serving_desc": food["serving_desc"]})
    moment = clock.now()
    now = clock.iso(moment)
    begin_immediate(conn)  # the counts and the insert see the same rows
    try:
        waiting = conn.execute("SELECT COUNT(*) FROM care_suggestions WHERE share_id = ? AND answer IS NULL AND expires_at > ?",
                               (care.share_id, now)).fetchone()[0]
        if waiting >= MAX_OPEN_PER_SHARE:
            raise ApiProblem(409, TOO_MANY_OPEN.format(care.owner_name))
        recent = conn.execute("SELECT COUNT(*) FROM care_suggestions WHERE from_user_id = ? AND created_at > ?",
                              (care.helper.id, clock.iso(moment - timedelta(days=1)))).fetchone()[0]
        if recent >= MAX_PER_DAY:
            raise ApiProblem(429, TOO_MANY_TODAY)
        cur = conn.execute("INSERT INTO care_suggestions (share_id, owner_user_id, from_user_id, date, meal, items_json, note, "
                           "created_at, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                           (care.share_id, care.owner.id, care.helper.id, body.date, body.meal, json.dumps(items), body.note or None,
                            now, clock.iso(moment + timedelta(days=SUGGEST_DAYS))))
        suggestion_id = int(cur.lastrowid or 0)
        audit(conn, care.helper.id, "suggestion.sent", "user", care.owner.id, ip=request_ip(request), share=care.share_id,
              suggestion=suggestion_id, date=body.date, meal=body.meal, foods=len(items), note=bool(body.note))
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    row = conn.execute("SELECT * FROM care_suggestions WHERE id = ?", (suggestion_id,)).fetchone()
    return {**sent_item(conn, row), "fit": fit_for(conn, request, care.owner.id, body.date, body.meal, row["items_json"],
                                                   activity_extra=sharing.shares_activity(conn, care.share_id))}


@shared_router.get("/{share_id}/suggestions", response_model=SentList)
def sent_suggestions(share_id: sharing.ShareId, owner: sharing.AnyShare, user: CurrentUser,
                     conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """What you suggested to this person, newest first (at most 50), and their answer: ``open``, ``accepted``, ``declined``,
    ``expired`` or ``ended``. Never why. Any active share may read it, so the answers stay visible after the switch is off."""
    rows = conn.execute("SELECT * FROM care_suggestions WHERE share_id = ? AND from_user_id = ? ORDER BY id DESC LIMIT ?",
                        (share_id, user.id, MAX_SENT_SHOWN)).fetchall()
    return {"suggestions": [sent_item(conn, r) for r in rows]}


# --------------------------------------------------------------------------- #
# The person: /api/me/suggestions
# --------------------------------------------------------------------------- #


@me_router.get("", response_model=SuggestionsForMe)
def my_suggestions(request: Request, user: CurrentUser, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """Suggestions from your Care team waiting for your answer, oldest first, each with what it adds to that day against your
    targets (worked out now). While sharing is off: ``enabled: false`` and an empty list."""
    if not sharing.enabled(conn, request):
        return {"enabled": False, "suggestions": []}
    sharing.expire(conn)
    rows = conn.execute(_FOR_ME + " ORDER BY c.date, c.id", (user.id, clock.now_iso())).fetchall()
    out = []
    for row in rows:
        out.append({**sent_item(conn, row), "share_id": int(row["share_id"]), "from_name": row["from_name"],
                    "fit": fit_for(conn, request, user.id, row["date"], row["meal"], row["items_json"], activity_extra=True)})
    return {"enabled": True, "suggestions": out}


def _available(request: Request, conn: sqlite3.Connection) -> None:
    if not sharing.enabled(conn, request):
        raise HTTPException(status_code=404, detail="Not Found")
    sharing.expire(conn)


@me_router.post("/{suggestion_id}/accept", response_model=AcceptResult)
def accept_suggestion(suggestion_id: SuggestionId, request: Request, user: CurrentUser,
                      conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """Add a suggestion to your plan: one planned entry for each food you can still use (``skipped`` counts the others). They are
    your own entries, which you can change like any other. ``409`` when none of the foods is left. Not yours, answered, expired
    or from a share that ended is ``404``."""
    _available(request, conn)
    begin_immediate(conn)
    try:
        row = _open_for_me(conn, user.id, suggestion_id)
        created: list[int] = []
        skipped = 0
        for item in _items(row["items_json"]):
            food = fetch_user_food(conn, user.id, int(item.get("food_id") or 0))
            if food is None:
                skipped += 1
                continue
            created.append(log_module.insert_entry(conn, user_id=user.id, date=row["date"], meal=row["meal"], food=food,
                                                   servings=float(item.get("servings") or 1), grams=None, note=None, status="planned",
                                                   purpose=log_module.resolve_purpose(food, None)))
        if not created:
            raise ApiProblem(409, NONE_LEFT)
        conn.execute("UPDATE care_suggestions SET answer = 'accepted', answered_at = ? WHERE id = ?", (clock.now_iso(), suggestion_id))
        audit(conn, user.id, "suggestion.accepted", "care_suggestion", suggestion_id, ip=request_ip(request),
              share=int(row["share_id"]), added=len(created), skipped=skipped)
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return {"entries": [log_module.row_to_entry(log_module.fetch_entry(conn, user.id, i)) for i in created], "skipped": skipped}


@me_router.post("/{suggestion_id}/decline", status_code=204, response_class=Response)
def decline_suggestion(suggestion_id: SuggestionId, request: Request, user: CurrentUser,
                       conn: sqlite3.Connection = Depends(get_db)) -> Response:
    """No thanks: the suggestion goes away. The person who sent it sees "declined", never why. Not yours or no longer open is
    ``404``."""
    _available(request, conn)
    row = _open_for_me(conn, user.id, suggestion_id)
    cur = conn.execute("UPDATE care_suggestions SET answer = 'declined', answered_at = ? WHERE id = ? AND answer IS NULL",
                       (clock.now_iso(), suggestion_id))
    if cur.rowcount != 1:
        # Answered a moment ago (Add, or another tap): only one answer is ever recorded.
        conn.rollback()
        raise ApiProblem(404, NO_SUGGESTION)
    audit(conn, user.id, "suggestion.declined", "care_suggestion", suggestion_id, ip=request_ip(request), share=int(row["share_id"]))
    conn.commit()
    return Response(status_code=204)


def export_rows(conn: sqlite3.Connection, user_id: int) -> list[dict[str, Any]]:
    """The person's suggestions for ``export.json`` (``care_suggestions``): what was suggested, by whom (their name now), when, and
    the answer (``open`` while waiting). The import reads nothing from it."""
    rows = conn.execute("SELECT c.*, COALESCE(NULLIF(TRIM(f.display_name), ''), f.username) AS from_name FROM care_suggestions c "
                        "JOIN users f ON f.id = c.from_user_id WHERE c.owner_user_id = ? ORDER BY c.id", (int(user_id),)).fetchall()
    return [{"date": r["date"], "meal": r["meal"], "from": r["from_name"], "note": r["note"],
             "items": [{"name": str(i.get("name") or ""), "servings": float(i.get("servings") or 0)} for i in _items(r["items_json"])],
             "created_at": r["created_at"], "answer": _answer(r), "answered_at": r["answered_at"]} for r in rows]

