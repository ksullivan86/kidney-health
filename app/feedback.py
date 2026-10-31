"""Send feedback (test accounts) and Server administration → Test accounts and Feedback (design note 26 §6; schema step 28).

* ``/api/feedback``: a test account sends what it typed (what it was trying to do, what happened, a usefulness choice, and "this
  looked wrong or unsafe") and reads back its own. The server adds only the screen name the app sends, the app version and the
  time. Nothing else is copied in: no screenshot, no numbers, no health data. Any other account gets ``404``.
* ``/api/admin/feedback``: admins read and filter it, mark it done, delete what is done, and export it as CSV.
* ``/api/admin/test-accounts``: the switches, any problem and the accounts' state; ``POST …/reset`` puts both accounts back to
  the start (``app/test_accounts.py``).

Limits: 2,000 characters a box, 50 a day for each account, 5,000 kept on the server.
"""
from __future__ import annotations

import csv
import io
import sqlite3
from datetime import datetime, timezone
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from . import test_accounts
from .auth.context import auth_context, request_ip
from .auth.deps import AdminUser, CurrentUser, RecentAdmin, current_user, require_admin
from .auth.errors import ApiProblem
from .auth.ratelimit import register_limit
from .db import get_db, utcnow
from .log import csv_safe

MAX_TEXT = 2000
MAX_SCREEN = 60
MAX_PER_DAY = 50
MAX_KEPT = 5000
MAX_ROW_ID = 2**63 - 1
Useful = Literal["yes", "somewhat", "no"]

register_limit("feedback", 20, 3600, "That is a lot of feedback in one hour. Try again later.")

router = APIRouter(prefix="/api/feedback", tags=["feedback"], dependencies=[Depends(current_user)])
admin_router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_admin)])

FeedbackId = Annotated[int, Path(ge=1, le=MAX_ROW_ID)]


class FeedbackCreate(BaseModel):
    """What a tester typed. ``screen`` is the name of the screen the app was on (the app fills it in)."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    screen: str = Field(min_length=1, max_length=MAX_SCREEN, pattern=r"^[^\x00-\x1f\x7f<>]+$")
    trying: str = Field(default="", max_length=MAX_TEXT)
    happened: str = Field(default="", max_length=MAX_TEXT)
    useful: Useful | None = None
    unsafe: bool = False

    @field_validator("trying", "happened")
    @classmethod
    def _no_controls(cls, v: str) -> str:
        return "".join(ch for ch in v if ch in "\n\t" or (ord(ch) >= 32 and ord(ch) != 127))


class FeedbackDone(BaseModel):
    model_config = ConfigDict(extra="forbid")
    done: bool


def _item(row: sqlite3.Row, *, admin: bool = False) -> dict[str, Any]:
    out = {"id": int(row["id"]), "screen": row["screen"], "trying": row["trying"], "happened": row["happened"], "useful": row["useful"],
           "unsafe": bool(row["unsafe"]), "app_version": row["app_version"], "created_at": row["created_at"], "done": row["done_at"] is not None}
    if admin:
        out.update(username=row["username"], done_at=row["done_at"])
    return out


def _tester(conn: sqlite3.Connection, user_id: int) -> None:
    if not test_accounts.is_test(conn, user_id):
        raise HTTPException(status_code=404, detail="Not Found")


# --------------------------------------------------------------------------- #
# The tester: /api/feedback
# --------------------------------------------------------------------------- #


@router.get("")
def my_feedback(user: CurrentUser, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """``{feedback, max_length}``: what you sent, newest first, and whether the admin marked each one done. Test accounts
    only (``404`` for everyone else)."""
    _tester(conn, user.id)
    rows = conn.execute("SELECT * FROM feedback WHERE user_id = ? ORDER BY id DESC LIMIT 200", (user.id,)).fetchall()
    return {"feedback": [_item(r) for r in rows], "max_length": MAX_TEXT}


@router.post("", status_code=201)
def send_feedback(body: FeedbackCreate, request: Request, user: CurrentUser, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """Send feedback about the screen you are on. Only what you typed is kept, with the screen name, the app version and the
    time. At least one of ``trying`` and ``happened``. 50 a day; ``409`` when the server already keeps 5,000. Test accounts
    only (``404`` for everyone else)."""
    _tester(conn, user.id)
    if not body.trying and not body.happened:
        raise ApiProblem(400, "Say what you were trying to do or what happened.", field="happened")
    auth_context(request).limits.take("feedback", f"user:{user.id}")
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    today = int(conn.execute("SELECT COUNT(*) FROM feedback WHERE user_id = ? AND created_at >= ?", (user.id, day)).fetchone()[0])
    if today >= MAX_PER_DAY:
        raise ApiProblem(409, f"You sent {MAX_PER_DAY} today, the most for one day. Thank you! Try again tomorrow.")
    if int(conn.execute("SELECT COUNT(*) FROM feedback").fetchone()[0]) >= MAX_KEPT:
        raise ApiProblem(409, "The feedback list on this server is full. Ask the person who runs it to export it and clear what is done.")
    version = str(getattr(request.app, "version", "") or "unknown")[:40]
    cur = conn.execute("INSERT INTO feedback (user_id, username, screen, trying, happened, useful, unsafe, app_version, created_at) "
                       "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (user.id, user.username, body.screen, body.trying, body.happened,
                                                              body.useful, int(body.unsafe), version, utcnow()))
    conn.commit()
    return _item(conn.execute("SELECT * FROM feedback WHERE id = ?", (cur.lastrowid,)).fetchone())


# --------------------------------------------------------------------------- #
# Admins: /api/admin/feedback and /api/admin/test-accounts
# --------------------------------------------------------------------------- #

State = Literal["open", "done", "all"]


def _where(state: str, unsafe: bool) -> tuple[str, list[Any]]:
    parts, params = [], []
    if state == "open":
        parts.append("done_at IS NULL")
    elif state == "done":
        parts.append("done_at IS NOT NULL")
    if unsafe:
        parts.append("unsafe = 1")
    return (" WHERE " + " AND ".join(parts)) if parts else "", params


@admin_router.get("/feedback")
def list_feedback(admin: AdminUser, state: State = "open", unsafe: bool = False, limit: int = Query(100, ge=1, le=500),
                  before: int | None = Query(None, ge=1, le=MAX_ROW_ID), conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """``{feedback, counts}``: what testers sent, newest first, filtered by ``state`` (``open``, ``done``, ``all``) and
    ``unsafe`` (only "looked wrong or unsafe"); ``before`` pages back. ``counts``: ``open``, ``done``, ``unsafe_open``."""
    where, params = _where(state, unsafe)
    if before is not None:
        where += (" AND " if where else " WHERE ") + "id < ?"
        params.append(before)
    rows = conn.execute(f"SELECT * FROM feedback{where} ORDER BY id DESC LIMIT ?", (*params, limit)).fetchall()
    c = conn.execute("SELECT SUM(done_at IS NULL), SUM(done_at IS NOT NULL), SUM(done_at IS NULL AND unsafe = 1) FROM feedback").fetchone()
    return {"feedback": [_item(r, admin=True) for r in rows],
            "counts": {"open": int(c[0] or 0), "done": int(c[1] or 0), "unsafe_open": int(c[2] or 0)}}


@admin_router.patch("/feedback/{feedback_id}")
def mark_feedback(feedback_id: FeedbackId, body: FeedbackDone, admin: RecentAdmin, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """Mark one item done (or open again). Unknown is ``404``."""
    cur = conn.execute("UPDATE feedback SET done_at = ?, done_by = ? WHERE id = ?",
                       (utcnow() if body.done else None, admin.id if body.done else None, feedback_id))
    if cur.rowcount != 1:
        conn.rollback()
        raise HTTPException(status_code=404, detail="feedback not found")
    conn.commit()
    return _item(conn.execute("SELECT * FROM feedback WHERE id = ?", (feedback_id,)).fetchone(), admin=True)


@admin_router.delete("/feedback/done")
def delete_done_feedback(admin: RecentAdmin, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """Delete every item marked done (export it first if you want to keep it). ``{deleted}``."""
    n = conn.execute("DELETE FROM feedback WHERE done_at IS NOT NULL").rowcount
    conn.commit()
    return {"deleted": int(n or 0)}


CSV_COLUMNS = ("id", "created_at", "username", "screen", "trying", "happened", "useful", "unsafe", "app_version", "done_at")


@admin_router.get("/feedback.csv")
def export_feedback(admin: AdminUser, state: State = "all", unsafe: bool = False, conn: sqlite3.Connection = Depends(get_db)) -> StreamingResponse:
    """Feedback as CSV (oldest first), with the same filters. Cells a spreadsheet would run as a formula are escaped."""
    where, params = _where(state, unsafe)
    rows = conn.execute(f"SELECT * FROM feedback{where} ORDER BY id", params).fetchall()
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(CSV_COLUMNS)
    for r in rows:
        writer.writerow([csv_safe(r[c] if c != "unsafe" else ("yes" if r["unsafe"] else "no")) for c in CSV_COLUMNS])
    data = buffer.getvalue()
    return StreamingResponse(iter([data]), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": 'attachment; filename="feedback.csv"'})


@admin_router.get("/test-accounts")
def test_accounts_status(request: Request, admin: AdminUser, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """``{enabled, ai, problem, accounts}``: the two switches, why the accounts could not be made (or null), and each test
    account's ``{id, username, status, last_login_at}``. Never the password or its file's contents."""
    ctx = auth_context(request)
    return test_accounts.status(conn, ctx.settings, ctx.store)


@admin_router.post("/test-accounts/reset")
def reset_test_accounts(request: Request, admin: RecentAdmin, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """Delete everything both test accounts made and start them again: Sam's sample data, tester-helper on tester's Care team,
    the password from the file. Both are signed out. The feedback stays. ``409`` while test accounts are off or cannot be made."""
    ctx = auth_context(request)
    try:
        test_accounts.reset(conn, ctx.settings, ctx.store, actor_id=admin.id, ip=request_ip(request))
    except test_accounts.ResetRefused as exc:
        conn.rollback()
        raise ApiProblem(409, str(exc)) from None
    return test_accounts.status(conn, ctx.settings, ctx.store)
