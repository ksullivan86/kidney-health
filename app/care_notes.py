"""Notes from the Care team (design note 37 phase 1; ARCHITECTURE.md "Notes from the Care team"; schema step 36).

Someone on a person's Care team whose share has ``may_note`` on (the **Clinician** preset, or any mix with that switch) writes a
short note for the person. The person reads it in their own app, can delete it, and sees every note written, edited or withdrawn
in their activity. A note is plain text, never an order: it changes no data. Only the person and the author ever see it.

* ``/api/shared/{share_id}/notes``: the author's routes. Each goes through :func:`app.sharing.care_noter`, the one check: notes on
  for the server, the share is the signed-in person's, active, both accounts active and ``may_note`` on now. A note is then looked
  up ``WHERE id = ? AND owner_user_id = <the share's owner> AND author_user_id = <the signed-in person>``; anything else is the
  same ``404``. The author may edit or withdraw a note only while it is unread.
* ``/api/me/notes``: the person's list (``200`` with ``enabled: false`` while notes are off, so Today never sees a failed
  request), marking a note read (``If-Match``: the version shown) and deleting one.

The text check refuses a note about lows (``hypo.mentions_low``) and a short list of dosing words; nothing else (design note 37
§7 and §12 decision 6). Writes run under ``BEGIN IMMEDIATE`` so a read and an edit at the same moment cannot both win, and the
daily count cannot be passed by sending many at once. Nothing in ``app/ai``, ``app/mcp`` or ``app/guidance`` reads this table.
"""
from __future__ import annotations

import re
import sqlite3
from datetime import date as _date
from datetime import timedelta
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Path, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator

from . import sharing
from .ai import guard
from .audit import audit
from .auth import clock
from .auth.accounts import begin_immediate
from .auth.context import request_ip
from .auth.deps import CurrentUser, current_user
from .auth.errors import ApiProblem
from .auth.models import User
from .db import get_db
from .guidance import hypo
from .models import MAX_SQLITE_INT, validate_date

MAX_BODY = 1000  # characters (design note 37 §12 decision 12)
MAX_PER_DAY = 10  # notes one author writes for one person in 24 hours
MAX_KEPT = 500  # notes kept for one person
MAX_PAGE = 50  # notes in one page of the person's list
MAX_DAYS_BACK = 365  # a note may be about a day up to a year back

# Dosing words a note may not use (design note 37 §7). Narrower than the AI text check (messages.BANNED_PATTERN): a dietitian
# needs "lab results", "supplements" and the like.
DOSING_PATTERN = re.compile(r"\b(insulin|bolus|basal|units?|doses?|dosing|corrections?|ratios?|pumps?)\b", re.IGNORECASE)

NOTE_REFUSED = "Notes cannot be about lows, insulin or doses. Talk to {} directly about those."
EMPTY = "Write the note first."
TOO_LONG = f"A note can be at most {MAX_BODY:,} characters."
TOO_MANY_TODAY = f"You have written {MAX_PER_DAY} notes for {{}} in the last 24 hours, the most allowed. Try again tomorrow."
TOO_MANY_KEPT = f"{{}} has {MAX_KEPT} notes. Ask them to delete old ones."
ALREADY_READ = "{} has read this note. Write a new one instead."
AREA_NOT_SHARED = "{} does not share that with you. Choose something they share, or nothing."
BAD_DAY = "Choose a day in the last year, not in the future."
NO_NOTE = "That note is not here any more."
CHANGED = "This note was changed since you opened it."
SEND_VERSION = "Send the note's version in If-Match."

shared_router = APIRouter(prefix="/api/shared", tags=["shared"], dependencies=[Depends(current_user)])
me_router = APIRouter(prefix="/api/me/notes", tags=["me"], dependencies=[Depends(current_user)])

NoteId = Annotated[int, Path(ge=1, le=MAX_SQLITE_INT)]
Area = Literal["food", "labs", "body", "symptoms", "activity"]
IfMatch = Annotated[str | None, Header(description='The note\'s `version`, quoted: "<version>". When it is not the note\'s '
                                                  "version now the answer is 412 and nothing changes.")]
ANSWERS: dict[int | str, dict[str, Any]] = {
    412: {"description": "If-Match is not the note's version now: it was changed since it was shown. Body: {detail, current}."},
    428: {"description": "If-Match is missing."},
}


# --------------------------------------------------------------------------- #
# Bodies and answers
# --------------------------------------------------------------------------- #


class NoteCreate(BaseModel):
    """``POST /api/shared/{id}/notes``: the text, and what it is about (an area the person shares, a day), both optional."""

    model_config = ConfigDict(extra="forbid")
    body: str = Field(max_length=MAX_BODY * 4)  # checked after trimming (:func:`clean_body`)
    area: Area | None = None
    date: str | None = None

    @field_validator("date")
    @classmethod
    def _date(cls, v: str | None) -> str | None:
        return None if v is None else validate_date(v)


class NoteUpdate(BaseModel):
    """``PUT /api/shared/{id}/notes/{note_id}``: only what is sent changes. ``area`` or ``date`` ``null`` clears it."""

    model_config = ConfigDict(extra="forbid")
    body: str | None = Field(default=None, max_length=MAX_BODY * 4)
    area: Area | None = None
    date: str | None = None

    @field_validator("date")
    @classmethod
    def _date(cls, v: str | None) -> str | None:
        return None if v is None else validate_date(v)


class NoteFrom(BaseModel):
    name: str
    removed: bool  # the author's account was deleted; the person keeps the note


class NoteForMe(BaseModel):
    id: int
    from_: NoteFrom = Field(alias="from")
    area: Area | None
    date: str | None
    body: str
    version: int
    created_at: str
    edited_at: str | None
    read_at: str | None

    model_config = ConfigDict(populate_by_name=True)


class NotesForMe(BaseModel):
    enabled: bool
    unread: int
    notes: list[NoteForMe]


class SentNote(BaseModel):
    id: int
    area: Area | None
    date: str | None
    body: str
    version: int
    created_at: str
    edited_at: str | None
    read_at: str | None


class SentNotes(BaseModel):
    notes: list[SentNote]


# --------------------------------------------------------------------------- #
# Helpers (pure ones are replayed by the demo, tests/data/care_vectors.json)
# --------------------------------------------------------------------------- #


def clean_body(text: str | None) -> str:
    """The note as stored: line endings made ``\\n`` and the ends trimmed."""
    return (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()


def note_problem(text: str | None, person: str) -> str | None:
    """Why a note cannot be sent, in one sentence, or None: empty, too long, about lows (the "Treating a low" prefilter) or
    with a dosing word (:data:`DOSING_PATTERN` on the folded text)."""
    body = clean_body(text)
    if not body:
        return EMPTY
    if len(body) > MAX_BODY:
        return TOO_LONG
    if hypo.mentions_low(body) or DOSING_PATTERN.search(guard.fold(body)):
        return NOTE_REFUSED.format(person)
    return None


def day_problem(day: str | None, today: str) -> str | None:
    """A note's day must be a real date at most a year back and not in the future. ``today`` is the server's UTC date; a day
    one later is allowed, since the author may be in a time zone ahead of UTC."""
    if day is None:
        return None
    first = (_date.fromisoformat(today) - timedelta(days=MAX_DAYS_BACK)).isoformat()
    last = (_date.fromisoformat(today) + timedelta(days=1)).isoformat()
    return None if first <= day <= last else BAD_DAY


def _tag(version: int) -> str:
    return f'"{int(version)}"'


def _matches(header: str | None, version: int) -> bool:
    if header is None:
        return False
    for tag in header.split(","):
        tag = tag.strip()
        if tag == "*":
            return True
        if not tag.startswith(("W/", "w/")) and tag.strip('"') == str(int(version)):
            return True
    return False


def for_me_item(row: sqlite3.Row) -> dict[str, Any]:
    return {"id": int(row["id"]), "from": {"name": row["author_name"], "removed": row["author_user_id"] is None},
            "area": row["area"], "date": row["about_date"], "body": row["body"], "version": int(row["version"]),
            "created_at": row["created_at"], "edited_at": row["edited_at"], "read_at": row["read_at"]}


def sent_item(row: sqlite3.Row) -> dict[str, Any]:
    return {"id": int(row["id"]), "area": row["area"], "date": row["about_date"], "body": row["body"],
            "version": int(row["version"]), "created_at": row["created_at"], "edited_at": row["edited_at"], "read_at": row["read_at"]}


def _author_name(user: User) -> str:
    return (user.display_name or "").strip() or user.username


def _available(request: Request, conn: sqlite3.Connection) -> None:
    if not sharing.notes_enabled(conn, request):
        raise HTTPException(status_code=404, detail="Not Found")
    sharing.expire(conn)


def _authors_note(conn: sqlite3.Connection, care: sharing.CareShare, note_id: int) -> sqlite3.Row:
    """The note ``note_id`` the signed-in person wrote for this share's owner, through any share; else the one ``404``."""
    row = conn.execute("SELECT * FROM care_notes WHERE id = ? AND owner_user_id = ? AND author_user_id = ?",
                       (note_id, care.owner.id, care.helper.id)).fetchone()
    if row is None:
        raise ApiProblem(404, sharing.NOT_SHARED)
    return row


def _write(fn: Any) -> Any:
    """Run ``fn()`` inside ``BEGIN IMMEDIATE``, committed on success and rolled back on any error."""

    def run(conn: sqlite3.Connection, *args: Any) -> Any:
        begin_immediate(conn)
        try:
            out = fn(conn, *args)
            conn.commit()
            return out
        except BaseException:
            conn.rollback()
            raise

    return run


# --------------------------------------------------------------------------- #
# The author: /api/shared/{share_id}/notes
# --------------------------------------------------------------------------- #


@shared_router.post("/{share_id}/notes", response_model=SentNote, status_code=201)
def write_note(share_id: sharing.ShareId, body: NoteCreate, care: sharing.Noter,
               conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """Write a note for the person (``may_note`` on, checked now). ``area`` must be one the person shares with you now, or none;
    ``date`` a day in the last year. The text check refuses lows and dosing words (``400``). At most 10 notes in 24 hours for
    one person (``429``) and 500 kept for them (``409``). Audit ``care_note.written`` in the person's activity, never the text."""
    text = clean_body(body.body)
    problem = note_problem(text, care.owner_name)
    if problem:
        raise ApiProblem(400, problem)
    if body.area is not None and body.area not in sharing.share_areas(conn, care.share_id):
        raise ApiProblem(400, AREA_NOT_SHARED.format(care.owner_name))
    moment = clock.now()
    now = clock.iso(moment)
    bad_day = day_problem(body.date, now[:10])
    if bad_day:
        raise ApiProblem(400, bad_day)

    def insert(conn: sqlite3.Connection) -> int:
        # Counted from the activity rows, so a withdrawn note still counts toward the day.
        recent = conn.execute("SELECT COUNT(*) FROM audit_log WHERE action = 'care_note.written' AND actor_user_id = ? "
                              "AND target_type = 'user' AND target_id = ? AND json_extract(details_json, '$.at') > ?",
                              (care.helper.id, str(care.owner.id), clock.iso(moment - timedelta(days=1)))).fetchone()[0]
        if recent >= MAX_PER_DAY:
            raise ApiProblem(429, TOO_MANY_TODAY.format(care.owner_name))
        kept = conn.execute("SELECT COUNT(*) FROM care_notes WHERE owner_user_id = ?", (care.owner.id,)).fetchone()[0]
        if kept >= MAX_KEPT:
            raise ApiProblem(409, TOO_MANY_KEPT.format(care.owner_name))
        cur = conn.execute("INSERT INTO care_notes (owner_user_id, author_user_id, share_id, author_name, area, about_date, body, "
                           "created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                           (care.owner.id, care.helper.id, care.share_id, _author_name(care.helper), body.area, body.date, text, now))
        note_id = int(cur.lastrowid or 0)
        audit(conn, care.helper.id, "care_note.written", "user", care.owner.id, share=care.share_id, note=note_id,
              area=body.area, date=body.date, at=now)
        return note_id

    note_id = _write(insert)(conn)
    return sent_item(conn.execute("SELECT * FROM care_notes WHERE id = ?", (note_id,)).fetchone())


@shared_router.get("/{share_id}/notes", response_model=SentNotes)
def written_notes(share_id: sharing.ShareId, care: sharing.Noter, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """The notes you wrote for this person, through any share, newest first, with ``read_at``. A note the person deleted is gone
    from here too."""
    rows = conn.execute("SELECT * FROM care_notes WHERE owner_user_id = ? AND author_user_id = ? ORDER BY created_at DESC, id DESC "
                        "LIMIT ?", (care.owner.id, care.helper.id, MAX_KEPT)).fetchall()
    return {"notes": [sent_item(r) for r in rows]}


@shared_router.put("/{share_id}/notes/{note_id}", response_model=SentNote, responses=ANSWERS)
def edit_note(share_id: sharing.ShareId, note_id: NoteId, body: NoteUpdate, care: sharing.Noter, if_match: IfMatch = None,
              conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """Change a note you wrote while the person has not read it (``409`` once read: write a new one). ``If-Match`` is the
    version you were shown (``428`` without it, ``412`` when it changed). Only what is sent changes; the checks are those of
    writing. Audit ``care_note.edited``."""
    sent = body.model_dump(exclude_unset=True)
    text = clean_body(sent["body"]) if "body" in sent else None
    if "body" in sent:
        problem = note_problem(text, care.owner_name)
        if problem:
            raise ApiProblem(400, problem)
    if sent.get("area") is not None and sent["area"] not in sharing.share_areas(conn, care.share_id):
        raise ApiProblem(400, AREA_NOT_SHARED.format(care.owner_name))
    now = clock.now_iso()
    bad_day = day_problem(sent.get("date"), now[:10])
    if bad_day:
        raise ApiProblem(400, bad_day)
    if if_match is None:
        raise ApiProblem(428, SEND_VERSION)

    def change(conn: sqlite3.Connection) -> None:
        row = _authors_note(conn, care, note_id)
        if row["read_at"] is not None:
            raise ApiProblem(409, ALREADY_READ.format(care.owner_name))
        if not _matches(if_match, int(row["version"])):
            raise ApiProblem(412, CHANGED, current=sent_item(row))
        new = {"body": text if text is not None else row["body"], "area": sent["area"] if "area" in sent else row["area"],
               "about_date": sent["date"] if "date" in sent else row["about_date"]}
        if new == {"body": row["body"], "area": row["area"], "about_date": row["about_date"]}:
            return
        conn.execute("UPDATE care_notes SET body = ?, area = ?, about_date = ?, version = version + 1, edited_at = ? "
                     "WHERE id = ? AND read_at IS NULL", (new["body"], new["area"], new["about_date"], now, note_id))
        audit(conn, care.helper.id, "care_note.edited", "user", care.owner.id, share=care.share_id, note=note_id)

    _write(change)(conn)
    return sent_item(conn.execute("SELECT * FROM care_notes WHERE id = ?", (note_id,)).fetchone())


@shared_router.delete("/{share_id}/notes/{note_id}", status_code=204, response_class=Response, responses={412: ANSWERS[412]})
def withdraw_note(share_id: sharing.ShareId, note_id: NoteId, care: sharing.Noter, if_match: IfMatch = None,
                  conn: sqlite3.Connection = Depends(get_db)) -> Response:
    """Withdraw a note you wrote while the person has not read it (``409`` once read). With ``If-Match``, ``412`` when it
    changed. The note is deleted; the activity row ``care_note.withdrawn`` stays, without the text."""

    def remove(conn: sqlite3.Connection) -> None:
        row = _authors_note(conn, care, note_id)
        if row["read_at"] is not None:
            raise ApiProblem(409, ALREADY_READ.format(care.owner_name))
        if if_match is not None and not _matches(if_match, int(row["version"])):
            raise ApiProblem(412, CHANGED, current=sent_item(row))
        conn.execute("DELETE FROM care_notes WHERE id = ? AND read_at IS NULL", (note_id,))
        audit(conn, care.helper.id, "care_note.withdrawn", "user", care.owner.id, share=care.share_id, note=note_id)

    _write(remove)(conn)
    return Response(status_code=204)


# --------------------------------------------------------------------------- #
# The person: /api/me/notes
# --------------------------------------------------------------------------- #


@me_router.get("", response_model=NotesForMe, response_model_by_alias=True)
def my_notes(request: Request, user: CurrentUser, conn: sqlite3.Connection = Depends(get_db),
             before: int | None = Query(None, ge=1, le=MAX_SQLITE_INT),
             limit: int = Query(MAX_PAGE, ge=1, le=MAX_PAGE)) -> dict[str, Any]:
    """Notes from your Care team, newest first, at most 50 a page (``before``: the last ``id`` of the page you have). ``unread``
    counts all your unread notes. While notes are off: ``enabled: false``, no notes."""
    if not sharing.notes_enabled(conn, request):
        return {"enabled": False, "unread": 0, "notes": []}
    sharing.expire(conn)
    rows = conn.execute("SELECT * FROM care_notes WHERE owner_user_id = ? AND (? IS NULL OR id < ?) ORDER BY id DESC LIMIT ?",
                        (user.id, before, before, limit)).fetchall()
    unread = conn.execute("SELECT COUNT(*) FROM care_notes WHERE owner_user_id = ? AND read_at IS NULL", (user.id,)).fetchone()[0]
    return {"enabled": True, "unread": int(unread), "notes": [for_me_item(r) for r in rows]}


def _my_note(conn: sqlite3.Connection, user: User, note_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM care_notes WHERE id = ? AND owner_user_id = ?", (note_id, user.id)).fetchone()
    if row is None:
        raise ApiProblem(404, NO_NOTE)
    return row


@me_router.post("/{note_id}/read", status_code=204, response_class=Response, responses=ANSWERS)
def read_note(note_id: NoteId, request: Request, user: CurrentUser, if_match: IfMatch = None,
              conn: sqlite3.Connection = Depends(get_db)) -> Response:
    """Mark a note read. ``If-Match`` is the version you were shown: when the author changed it since, ``412`` with the note as
    it is now, so ``read_at`` always belongs to the text you saw. Already read is ``204``. Not yours is ``404``. No activity
    row: ``read_at`` is enough."""
    _available(request, conn)
    if if_match is None:
        raise ApiProblem(428, SEND_VERSION)

    def mark(conn: sqlite3.Connection) -> None:
        row = _my_note(conn, user, note_id)
        if row["read_at"] is not None:
            return
        if not _matches(if_match, int(row["version"])):
            raise ApiProblem(412, CHANGED, current=for_me_item(row))
        conn.execute("UPDATE care_notes SET read_at = ? WHERE id = ? AND read_at IS NULL", (clock.now_iso(), note_id))

    _write(mark)(conn)
    return Response(status_code=204)


@me_router.delete("/{note_id}", status_code=204, response_class=Response)
def delete_note(note_id: NoteId, request: Request, user: CurrentUser, conn: sqlite3.Connection = Depends(get_db)) -> Response:
    """Delete a note, read or not. It is gone for both of you. Audit ``care_note.deleted`` (your own, without the text). Not
    yours is ``404``."""
    _available(request, conn)

    def remove(conn: sqlite3.Connection) -> None:
        row = _my_note(conn, user, note_id)
        conn.execute("DELETE FROM care_notes WHERE id = ?", (note_id,))
        audit(conn, user.id, "care_note.deleted", "care_note", note_id, ip=request_ip(request), area=row["area"],
              read=row["read_at"] is not None)

    _write(remove)(conn)
    return Response(status_code=204)


def export_rows(conn: sqlite3.Connection, user_id: int) -> list[dict[str, Any]]:
    """The person's notes for ``export.json`` (``care_notes``): ``date, area, from, body, created_at, edited_at, read_at``. The
    author's own export holds none of them (they are about someone else), and the import reads nothing from it."""
    rows = conn.execute("SELECT * FROM care_notes WHERE owner_user_id = ? ORDER BY id", (int(user_id),)).fetchall()
    return [{"date": r["about_date"], "area": r["area"], "from": r["author_name"], "body": r["body"], "created_at": r["created_at"],
             "edited_at": r["edited_at"], "read_at": r["read_at"]} for r in rows]
