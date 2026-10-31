"""The Care team: sharing with a caregiver or dietitian (design notes 19 and 25; ARCHITECTURE.md "Sharing" and "Care team").

A person (the **owner**) adds someone with an account on the same server (the **grantee**) to their Care team in Settings → Care
team: by a link they send, or by that person's user name (an invite the other person accepts or declines in their own Settings).
From then on the grantee can read the areas the owner ticked, and nothing else, until either side stops it, or until the end date
the owner chose (``days``; :func:`expire` ends it then). Each share has a **role** (schema step 27): a ``viewer`` only reads; a
``care_helper`` may also plan meals on the owner's days and use their shopping list.

* ``/api/me/shares``: the owner's list, a new link or a user name invite (recent password), the role, stopping a share,
  cancelling a link or an invite.
* ``/api/shared``: the grantee's list and invites, stopping, ``info`` / ``accept`` for a link, accept / decline for an invite.
* ``/api/shared/{share_id}/…``: the reads. Each goes through :func:`shared_owner`, the one check: the share is the signed-in
  person's, active, both accounts are active, and the area was shared. It returns the **owner's** user, and the handler calls the
  owner's own route function with it, so the answer is exactly what the owner sees. Anything else is the same ``404``.
* The Care helper's writes (planned food, Clear planned days, Plan several days, the shopping list and a food search as the owner)
  go through :func:`care_helper`, which adds to that check, on every request, that the role is ``care_helper`` now and the food log
  is shared. A helper never touches eaten food or a planned low treatment, and never anything but the owner's planned food.

Every route answers ``404`` while ``sharing.enabled`` is off and in ``AUTH_MODE=none``. The link is ``/#/share/<id>.<verifier>``
(the fragment never reaches the server or its logs); only the SHA-256 of the verifier is stored, and a link works once. A user
name invite answers the same whether or not the name belongs to an account (design note 25 §3).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import sqlite3
from collections.abc import Callable
from datetime import timedelta
from typing import Annotated, Any, Literal

from dataclasses import dataclass

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator

from . import activity as activity_module
from . import body as body_module
from . import labs as labs_module
from . import log as log_module
from . import meals as meals_module
from . import symptoms as symptoms_module
from .audit import audit
from .auth import clock
from .auth.accounts import begin_immediate
from .auth.context import auth_context, public_base, request_ip
from .auth.deps import CurrentUser, RecentUser, current_user
from .auth.errors import ApiProblem
from .auth.models import User, load_user, normalize_username
from .auth.ratelimit import register_limit
from .auth.tokens import link as token_link
from .db import get_db
from .foods import MAX_SEARCH_QUERY_CHARS, search_foods
from .guidance import api as guidance_api
from .guidance.models import GuidanceUnavailable, PlanDaysRequest, PlanDaysResponse
from .models import (
    MAX_GRAMS,
    MAX_LOG_BATCH,
    MAX_SERVINGS,
    Analyte,
    BloodPressureList,
    BodySummary,
    CkdStage,
    ClearPlanned,
    ClearPlannedResult,
    DaySummary,
    Diabetes,
    Dialysis,
    Entry,
    FoodList,
    LabList,
    LogBatchResult,
    LogCreate,
    LogUpdate,
    Meal,
    Number,
    PeriodSummary,
    RangeSummary,
    ShoppingList,
    SymptomList,
    TargetValue,
    WeekStart,
    WeightList,
    validate_date,
)
from .profile import get_profile

SWITCH = "sharing.enabled"
AREAS = ("food", "labs", "body", "symptoms", "activity")  # "activity": activity and recovery (design note 28 §4.4, step 30)
Area = Literal["food", "labs", "body", "symptoms", "activity"]
ROLES = ("viewer", "care_helper")  # schema step 27 (design note 25 §2)
Role = Literal["viewer", "care_helper"]
CODE_DAYS = 7
INVITE_DAYS = 7  # a user name invite waits this long for an answer
MAX_DAYS = 365  # the longest time limit a share can have
MAX_CODES = 5  # unused links a person can have at once
MAX_INVITES = 5  # user name invites waiting for an answer at once
MAX_SHARES = 10  # people who can see one person's data at once
MAX_ROW_ID = 2**63 - 1

NOT_SHARED = "Not shared with you."
BAD_LINK = "That link does not work. Ask for a new one."
OWN_LINK = "This is your own link. Send it to the person you want to share with."
TOO_MANY_CODES = f"You have {MAX_CODES} links nobody has used yet. Cancel one first."
TOO_MANY_SHARES = f"You already share with {MAX_SHARES} people, the most allowed. Stop sharing with someone first."
OWNER_FULL = f"This person already shares with {MAX_SHARES} people, the most allowed. Ask them to stop one first."
OWN_NAME = "That is your own user name. Type the user name of the person you want on your Care team."
TOO_MANY_INVITES = f"You have {MAX_INVITES} invites waiting for an answer. Cancel one first."
NO_INVITE = "That invite is no longer open."
NO_ENTRY = "log entry {} not found"

register_limit("share_link", 20, 3600, "Too many tries with share links. Try again in an hour.")
register_limit("care_invite", 20, 3600, "Too many invites. Try again in an hour.")

_CODE = re.compile(r"([0-9a-f]{16})\.([A-Za-z0-9_-]{43})")

me_router = APIRouter(prefix="/api/me/shares", tags=["me"], dependencies=[Depends(current_user)])
shared_router = APIRouter(prefix="/api/shared", tags=["shared"], dependencies=[Depends(current_user)])

ShareId = Annotated[int, Path(ge=1, le=MAX_ROW_ID)]


# --------------------------------------------------------------------------- #
# Bodies and answers
# --------------------------------------------------------------------------- #


class ShareCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    areas: list[Area] = Field(min_length=1, max_length=len(AREAS))
    days: int | None = Field(default=None, ge=1, le=MAX_DAYS)  # how long the share lasts once accepted; None: until stopped
    role: Role = "viewer"  # schema step 27: a Care helper also plans meals (the food log is added)


class CareInviteCreate(BaseModel):
    """``POST /api/me/shares/invite``: someone who already has an account here, by user name (design note 25 §3)."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    username: str = Field(min_length=1, max_length=255)
    areas: list[Area] = Field(min_length=1, max_length=len(AREAS))
    days: int | None = Field(default=None, ge=1, le=MAX_DAYS)
    role: Role = "viewer"


class RoleChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Role


class HelperEntry(LogCreate):
    """One entry a Care helper adds: always planned. ``client_id`` is not used (the helper's device never queues it)."""

    status: Literal["planned"] = "planned"


class HelperBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entries: list[HelperEntry] = Field(min_length=1, max_length=MAX_LOG_BATCH)


class HelperUpdate(BaseModel):
    """What a Care helper may change on a planned entry: the amount, the meal, the day and the note. Never the status or
    whether it treats a low."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    date: str | None = None
    meal: Meal | None = None
    servings: float | None = Field(default=None, gt=0, le=MAX_SERVINGS, allow_inf_nan=False)
    grams: float | None = Field(default=None, gt=0, le=MAX_GRAMS, allow_inf_nan=False)
    note: str | None = Field(default=None, max_length=500)

    @field_validator("date")
    @classmethod
    def _date(cls, v: str | None) -> str | None:
        return None if v is None else validate_date(v)


class ShareCode(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(min_length=1, max_length=200)


class SharedProfile(BaseModel):
    """What the shared pages need from the owner's profile, and nothing more (no date of birth, no notes, no flags)."""

    name: str
    ckd_stage: CkdStage
    dialysis: Dialysis
    diabetes: Diabetes
    dialysis_days: list[int]
    week_start: WeekStart
    weight_kg: Number | None
    targets: dict[str, TargetValue]


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _sha(text: str) -> bytes:
    return hashlib.sha256(text.encode("ascii")).digest()


def enabled(conn: sqlite3.Connection, request: Request) -> bool:
    ctx = auth_context(request)
    return ctx.settings.auth_mode != "none" and bool(ctx.store.get(conn, SWITCH))


def _available(request: Request, conn: sqlite3.Connection) -> None:
    if not enabled(conn, request):
        raise HTTPException(status_code=404, detail="Not Found")
    expire(conn)


def _areas(raw: str) -> list[str]:
    try:
        got = json.loads(raw)
    except ValueError:
        return []
    return [a for a in AREAS if a in got] if isinstance(got, list) else []


def _clean_areas(areas: list[str], role: str = "viewer") -> list[str]:
    """One each, in the order of AREAS. A Care helper plans meals, so the food log is always shared with one."""
    wanted = set(areas) | ({"food"} if role == "care_helper" else set())
    return [a for a in AREAS if a in wanted]


def _role(row: sqlite3.Row) -> str:
    role = row["role"] if "role" in row.keys() else None
    return role if role in ROLES else "viewer"


def _helper_changes(row: sqlite3.Row) -> dict[str, Any] | None:
    """The Care helper's changes on the latest day they changed the plan: ``{day, added, changed, removed}``, or None."""
    raw = row["helper_changes"] if "helper_changes" in row.keys() else None
    try:
        got = json.loads(raw) if raw else None
    except ValueError:
        return None
    if not isinstance(got, dict) or not isinstance(got.get("day"), str):
        return None
    return {"day": got["day"], **{k: int(got.get(k) or 0) for k in ("added", "changed", "removed")}}


def _name(row: sqlite3.Row, prefix: str) -> str:
    return (row[f"{prefix}_display"] or "").strip() or row[f"{prefix}_username"]


def _today() -> str:
    return clock.now_iso()[:10]


_PEOPLE = """
SELECT s.*, o.username AS owner_username, o.display_name AS owner_display, o.status AS owner_status,
       g.username AS grantee_username, g.display_name AS grantee_display, g.status AS grantee_status,
       o.is_test_account AS owner_test, g.is_test_account AS grantee_test
FROM shares s JOIN users o ON o.id = s.owner_user_id LEFT JOIN users g ON g.id = s.grantee_user_id
"""


def sharing_item(row: sqlite3.Row) -> dict[str, Any]:
    """One person who can see the owner's data, as the owner's list shows it. ``until`` is when it ends (None: until stopped)."""
    return {"id": int(row["id"]), "name": _name(row, "grantee"), "username": row["grantee_username"], "areas": _areas(row["areas"]),
            "since": row["accepted_at"], "until": row["ends_at"], "last_viewed_at": row["last_viewed_at"],
            "active": row["grantee_status"] == "active", "role": _role(row), "helper_changes": _helper_changes(row)}


def code_item(row: sqlite3.Row) -> dict[str, Any]:
    """An unused link. ``days`` is how long the share will last once accepted (None: until stopped)."""
    return {"id": int(row["id"]), "areas": _areas(row["areas"]), "days": row["lasts_days"], "created_at": row["created_at"],
            "expires_at": row["expires_at"], "role": _role(row)}


def person_item(row: sqlite3.Row) -> dict[str, Any]:
    """One person who shares with the signed-in person, as the grantee's list shows it."""
    return {"id": int(row["id"]), "name": _name(row, "owner"), "username": row["owner_username"], "areas": _areas(row["areas"]),
            "since": row["accepted_at"], "until": row["ends_at"], "role": _role(row)}


_INVITES = """
SELECT i.*, o.username AS owner_username, o.display_name AS owner_display, o.status AS owner_status,
       o.is_test_account AS owner_test
FROM care_invites i JOIN users o ON o.id = i.owner_user_id
"""


def _same_kind(row: sqlite3.Row, user: User | None = None) -> bool:
    """Test accounts are on a Care team only with test accounts, never with a real account, either way (design note 26). Compares
    the row's owner with its grantee, or with ``user`` (the grantee or invitee asking)."""
    owner = bool(row["owner_test"])
    other = bool(user.is_test_account) if user is not None else bool(row["grantee_test"])
    return owner == other


def sent_invite_item(row: sqlite3.Row) -> dict[str, Any]:
    """A user name invite waiting for an answer, as the inviter's list shows it: the name as typed, never whether it is an
    account (design note 25 §3)."""
    return {"id": int(row["id"]), "username": row["username"], "areas": _areas(row["areas"]), "role": _role(row),
            "days": row["lasts_days"], "created_at": row["created_at"], "expires_at": row["expires_at"]}


def invite_for_me_item(row: sqlite3.Row) -> dict[str, Any]:
    """An invite to the signed-in person, as their list shows it: who and what."""
    return {"id": int(row["id"]), "name": _name(row, "owner"), "username": row["owner_username"], "areas": _areas(row["areas"]),
            "role": _role(row), "days": row["lasts_days"], "expires_at": row["expires_at"]}


def expire(conn: sqlite3.Connection) -> int:
    """End every share whose end date has passed, as if its owner stopped it, with a ``share.ended`` row (``by: time``) in the
    owner's activity. Commits when it ends any. Returns how many it ended."""
    now = clock.now_iso()
    rows = conn.execute("SELECT id, owner_user_id FROM shares WHERE ends_at IS NOT NULL AND ends_at <= ? AND ended_at IS NULL "
                        "AND accepted_at IS NOT NULL", (now,)).fetchall()
    for row in rows:
        conn.execute("UPDATE shares SET ended_at = ?, ended_by = 'owner' WHERE id = ? AND ended_at IS NULL", (now, int(row["id"])))
        audit(conn, None, "share.ended", "user", int(row["owner_user_id"]), share=int(row["id"]), by="time")
    if rows:
        conn.commit()
    return len(rows)


def active_count(conn: sqlite3.Connection, owner_id: int) -> int:
    return int(conn.execute("SELECT COUNT(*) FROM shares WHERE owner_user_id = ? AND accepted_at IS NOT NULL AND ended_at IS NULL",
                            (owner_id,)).fetchone()[0])


def counts(conn: sqlite3.Connection) -> dict[int, int]:
    """Active shares and unused links where each person is either side, for the admin's people list."""
    expire(conn)
    rows = conn.execute(
        "SELECT uid, COUNT(*) FROM (SELECT owner_user_id AS uid FROM shares WHERE ended_at IS NULL "
        "UNION ALL SELECT grantee_user_id FROM shares WHERE ended_at IS NULL AND grantee_user_id IS NOT NULL) GROUP BY uid"
    ).fetchall()
    return {int(r[0]): int(r[1]) for r in rows}


def end_all(conn: sqlite3.Connection, user_id: int, by: str = "admin") -> int:
    """End every share and link where ``user_id`` is either side (no commit)."""
    now = clock.now_iso()
    cur = conn.execute("UPDATE shares SET ended_at = ?, ended_by = ? WHERE ended_at IS NULL AND (owner_user_id = ? OR grantee_user_id = ?)",
                       (now, by, user_id, user_id))
    conn.execute("UPDATE care_invites SET answered_at = ?, answer = 'cancelled' WHERE answer IS NULL "
                 "AND (owner_user_id = ? OR invitee_user_id = ?)", (now, user_id, user_id))
    return int(cur.rowcount)


def _waiting_invites(conn: sqlite3.Connection, owner_id: int) -> list[sqlite3.Row]:
    return conn.execute(_INVITES + " WHERE i.owner_user_id = ? AND i.answer IS NULL AND i.expires_at > ? ORDER BY i.created_at, i.id",
                        (owner_id, clock.now_iso())).fetchall()


def _find_code(conn: sqlite3.Connection, request: Request, user: User, raw: str) -> sqlite3.Row:
    """The unused, unexpired link ``raw`` of an active account, or the generic ``404``. Every try counts toward the hour."""
    ctx = auth_context(request)
    ctx.limits.take("share_link", f"user:{user.id}")
    ctx.limits.take("share_link", f"ip:{request_ip(request)}")
    m = _CODE.fullmatch((raw or "").strip())
    if not m:
        raise ApiProblem(404, BAD_LINK)
    row = conn.execute(_PEOPLE + " WHERE s.code_id = ? AND s.accepted_at IS NULL AND s.ended_at IS NULL AND s.expires_at > ?",
                       (m.group(1), clock.now_iso())).fetchone()
    if row is None or row["owner_status"] != "active" or not hmac.compare_digest(bytes(row["verifier_hash"]), _sha(m.group(2))):
        raise ApiProblem(404, BAD_LINK)
    if not _same_kind(row, user):  # a test account's link for a real account, or the other way round (design note 26)
        raise ApiProblem(404, BAD_LINK)
    if int(row["owner_user_id"]) == user.id:
        raise ApiProblem(400, OWN_LINK)
    return row


# --------------------------------------------------------------------------- #
# The owner: /api/me/shares
# --------------------------------------------------------------------------- #


@me_router.get("")
def list_my_shares(request: Request, user: CurrentUser, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """``{enabled, areas, roles, max, sharing, codes, invites}``: your Care team (each with its ``role``), your unused links and
    your user name invites waiting for an answer. ``enabled`` is false (and the lists empty) while the admin has sharing off."""
    if not enabled(conn, request):
        if auth_context(request).settings.auth_mode == "none":
            raise HTTPException(status_code=404, detail="Not Found")
        return {"enabled": False, "areas": list(AREAS), "roles": list(ROLES), "max": MAX_SHARES, "sharing": [], "codes": [], "invites": []}
    expire(conn)
    sharing = [r for r in conn.execute(_PEOPLE + " WHERE s.owner_user_id = ? AND s.accepted_at IS NOT NULL AND s.ended_at IS NULL "
                                                 "ORDER BY s.accepted_at, s.id", (user.id,)).fetchall() if _same_kind(r)]
    codes = conn.execute(_PEOPLE + " WHERE s.owner_user_id = ? AND s.accepted_at IS NULL AND s.ended_at IS NULL AND s.expires_at > ? "
                                   "ORDER BY s.created_at, s.id", (user.id, clock.now_iso())).fetchall()
    return {"enabled": True, "areas": list(AREAS), "roles": list(ROLES), "max": MAX_SHARES, "sharing": [sharing_item(r) for r in sharing],
            "codes": [code_item(r) for r in codes], "invites": [sent_invite_item(r) for r in _waiting_invites(conn, user.id)]}


@me_router.post("", status_code=201)
def create_share_link(body: ShareCreate, request: Request, user: RecentUser, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """A new link for the areas ticked (``food``, ``labs``, ``body``, ``symptoms``), in this answer only (``link``). It works once,
    for 7 days. ``days`` (1 to 365) makes the share end that many days after it is accepted; without it the share lasts until
    someone stops it. ``role`` (``viewer`` or ``care_helper``) is the role the share starts with. Needs a recent password, like
    making a token."""
    _available(request, conn)
    areas = _clean_areas(body.areas, body.role)
    now = clock.now()
    open_codes = int(conn.execute("SELECT COUNT(*) FROM shares WHERE owner_user_id = ? AND accepted_at IS NULL AND ended_at IS NULL "
                                  "AND expires_at > ?", (user.id, clock.iso(now))).fetchone()[0])
    if open_codes >= MAX_CODES:
        raise ApiProblem(409, TOO_MANY_CODES)
    if active_count(conn, user.id) >= MAX_SHARES:
        raise ApiProblem(409, TOO_MANY_SHARES)
    code_id, verifier = secrets.token_hex(8), secrets.token_urlsafe(32)
    cur = conn.execute("INSERT INTO shares (owner_user_id, code_id, verifier_hash, areas, created_at, expires_at, lasts_days, role) "
                       "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (user.id, code_id, _sha(verifier), json.dumps(areas), clock.iso(now),
                                                           clock.iso(now + timedelta(days=CODE_DAYS)), body.days, body.role))
    share_id = int(cur.lastrowid or 0)
    audit(conn, user.id, "share.code_created", "share", share_id, ip=request_ip(request), areas=areas, days=body.days, role=body.role)
    conn.commit()
    row = conn.execute(_PEOPLE + " WHERE s.id = ?", (share_id,)).fetchone()
    return {"code": code_item(row), "link": token_link(public_base(request, auth_context(request).settings), "share", f"{code_id}.{verifier}")}


@me_router.delete("/{share_id}", status_code=204, response_class=Response)
def end_my_share(share_id: ShareId, request: Request, user: CurrentUser, conn: sqlite3.Connection = Depends(get_db)) -> Response:
    """Stop sharing with someone, or cancel a link nobody used. Not yours, or already ended, is ``404``."""
    _available(request, conn)
    row = conn.execute("SELECT id, accepted_at FROM shares WHERE id = ? AND owner_user_id = ? AND ended_at IS NULL",
                       (share_id, user.id)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="share not found")
    conn.execute("UPDATE shares SET ended_at = ?, ended_by = 'owner' WHERE id = ?", (clock.now_iso(), share_id))
    if row["accepted_at"] is None:
        audit(conn, user.id, "share.code_cancelled", "share", share_id, ip=request_ip(request))
    else:
        audit(conn, user.id, "share.ended", "share", share_id, ip=request_ip(request), by="owner")
    conn.commit()
    return Response(status_code=204)


InviteId = Annotated[int, Path(ge=1, le=MAX_ROW_ID)]


@me_router.post("/invite", status_code=201)
def invite_by_username(body: CareInviteCreate, request: Request, user: RecentUser,
                       conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """Invite someone who already has an account here to your Care team, by their user name (design note 25 §3). The answer is
    the same whether or not the name belongs to an active account: the invite as your list shows it, waiting 7 days for an
    answer. Only an active account with that name sees it, in their own Settings → Care team. A second invite to the same name
    replaces the first. Your own name is ``400``. 20 tries an hour; at most 5 waiting. Needs a recent password, like a link."""
    _available(request, conn)
    ctx = auth_context(request)
    ctx.limits.take("care_invite", f"user:{user.id}")
    ctx.limits.take("care_invite", f"ip:{request_ip(request)}")
    norm = normalize_username(body.username)
    if not norm:
        raise ApiProblem(400, "Type the user name of the person you want to invite.")
    found = conn.execute("SELECT id, is_test_account FROM users WHERE username_norm = ? AND status = 'active'", (norm,)).fetchone()
    if found is not None and bool(found["is_test_account"]) != user.is_test_account:
        found = None  # a test account and a real account: the same answer as a name nobody has (design note 26)
    invitee = int(found["id"]) if found is not None else None
    if invitee == user.id:
        raise ApiProblem(400, OWN_NAME)
    now = clock.now()
    begin_immediate(conn)
    try:
        conn.execute("UPDATE care_invites SET answered_at = ?, answer = 'replaced' WHERE owner_user_id = ? AND username = ? "
                     "AND answer IS NULL", (clock.iso(now), user.id, norm))
        if len(_waiting_invites(conn, user.id)) >= MAX_INVITES:
            raise ApiProblem(409, TOO_MANY_INVITES)
        if active_count(conn, user.id) >= MAX_SHARES:
            raise ApiProblem(409, TOO_MANY_SHARES)
        areas = _clean_areas(body.areas, body.role)
        cur = conn.execute("INSERT INTO care_invites (owner_user_id, invitee_user_id, username, areas, role, lasts_days, created_at, expires_at) "
                           "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (user.id, invitee, norm, json.dumps(areas), body.role, body.days,
                                                               clock.iso(now), clock.iso(now + timedelta(days=INVITE_DAYS))))
        invite_id = int(cur.lastrowid or 0)
        audit(conn, user.id, "care.invited", "care_invite", invite_id, ip=request_ip(request), areas=areas, role=body.role, days=body.days)
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return sent_invite_item(conn.execute(_INVITES + " WHERE i.id = ?", (invite_id,)).fetchone())


@me_router.delete("/invites/{invite_id}", status_code=204, response_class=Response)
def cancel_invite(invite_id: InviteId, request: Request, user: CurrentUser, conn: sqlite3.Connection = Depends(get_db)) -> Response:
    """Cancel a user name invite that is still waiting. Not yours, answered or lapsed is ``404``."""
    _available(request, conn)
    cur = conn.execute("UPDATE care_invites SET answered_at = ?, answer = 'cancelled' WHERE id = ? AND owner_user_id = ? "
                       "AND answer IS NULL AND expires_at > ?", (clock.now_iso(), invite_id, user.id, clock.now_iso()))
    if cur.rowcount != 1:
        conn.rollback()
        raise HTTPException(status_code=404, detail="invite not found")
    audit(conn, user.id, "care.invite_cancelled", "care_invite", invite_id, ip=request_ip(request))
    conn.commit()
    return Response(status_code=204)


@me_router.put("/{share_id}/role")
def change_role(share_id: ShareId, body: RoleChange, request: Request, user: CurrentUser,
                conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """Change what someone on your Care team may do: ``viewer`` (look only) or ``care_helper`` (also plan your meals and use
    your shopping list). A Care helper always sees your food log, so it is added. The next request they make uses the new
    role. Not yours or ended is ``404``."""
    _available(request, conn)
    row = conn.execute(_PEOPLE + " WHERE s.id = ? AND s.owner_user_id = ? AND s.accepted_at IS NOT NULL AND s.ended_at IS NULL",
                       (share_id, user.id)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="share not found")
    if _role(row) != body.role:
        before = _areas(row["areas"])
        areas = _clean_areas(before, body.role)
        conn.execute("UPDATE shares SET role = ?, areas = ? WHERE id = ?", (body.role, json.dumps(areas), share_id))
        audit(conn, user.id, "care.role_changed", "share", share_id, ip=request_ip(request), role=body.role,
              food_added=areas != before)
        conn.commit()
        row = conn.execute(_PEOPLE + " WHERE s.id = ?", (share_id,)).fetchone()
    return sharing_item(row)


# --------------------------------------------------------------------------- #
# The grantee: /api/shared
# --------------------------------------------------------------------------- #


@shared_router.get("")
def list_shared_with_me(request: Request, user: CurrentUser, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """``{people, invites}``: the people whose Care team you are on (what they share and your ``role``), and the user name
    invites waiting for your answer, while the other account is active."""
    _available(request, conn)
    rows = conn.execute(_PEOPLE + " WHERE s.grantee_user_id = ? AND s.accepted_at IS NOT NULL AND s.ended_at IS NULL "
                                  "AND o.status = 'active' ORDER BY s.accepted_at, s.id", (user.id,)).fetchall()
    invites = conn.execute(_INVITES + " WHERE i.invitee_user_id = ? AND i.answer IS NULL AND i.expires_at > ? AND o.status = 'active' "
                                      "ORDER BY i.created_at, i.id", (user.id, clock.now_iso())).fetchall()
    return {"people": [person_item(r) for r in rows if _same_kind(r, user)],
            "invites": [invite_for_me_item(r) for r in invites if _same_kind(r, user)]}


def _open_invite(conn: sqlite3.Connection, invite_id: int, user: User) -> sqlite3.Row:
    row = conn.execute(_INVITES + " WHERE i.id = ? AND i.invitee_user_id = ? AND i.answer IS NULL AND i.expires_at > ?",
                       (invite_id, user.id, clock.now_iso())).fetchone()
    if row is None or row["owner_status"] != "active" or not _same_kind(row, user):
        raise ApiProblem(404, NO_INVITE)
    return row


@shared_router.post("/invites/{invite_id}/accept", status_code=201)
def accept_invite(invite_id: InviteId, request: Request, user: CurrentUser, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """Join someone's Care team: from now on you can see what they share and, as a Care helper, plan their meals. A newer
    invite from someone whose team you are already on replaces the old share. Not yours, answered or lapsed is ``404``."""
    _available(request, conn)
    begin_immediate(conn)
    try:
        row = _open_invite(conn, invite_id, user)
        owner_id = int(row["owner_user_id"])
        old = conn.execute("SELECT id FROM shares WHERE owner_user_id = ? AND grantee_user_id = ? AND accepted_at IS NOT NULL "
                           "AND ended_at IS NULL", (owner_id, user.id)).fetchone()
        if old is None and active_count(conn, owner_id) >= MAX_SHARES:
            raise ApiProblem(409, OWNER_FULL)
        moment = clock.now()
        now = clock.iso(moment)
        ends = clock.iso(moment + timedelta(days=int(row["lasts_days"]))) if row["lasts_days"] else None
        if old is not None:
            conn.execute("UPDATE shares SET ended_at = ?, ended_by = 'replaced' WHERE id = ?", (now, int(old["id"])))
        cur = conn.execute("INSERT INTO shares (owner_user_id, grantee_user_id, areas, created_at, accepted_at, lasts_days, ends_at, role) "
                           "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (owner_id, user.id, row["areas"], now, now, row["lasts_days"], ends, _role(row)))
        share_id = int(cur.lastrowid or 0)
        conn.execute("UPDATE care_invites SET answered_at = ?, answer = 'accepted', share_id = ? WHERE id = ?", (now, share_id, invite_id))
        audit(conn, user.id, "care.invite_answered", "user", owner_id, ip=request_ip(request), invite=invite_id, answer="accepted",
              share=share_id, role=_role(row), areas=_areas(row["areas"]), replaced=old is not None, until=ends)
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return person_item(conn.execute(_PEOPLE + " WHERE s.id = ?", (share_id,)).fetchone())


@shared_router.post("/invites/{invite_id}/decline", status_code=204, response_class=Response)
def decline_invite(invite_id: InviteId, request: Request, user: CurrentUser, conn: sqlite3.Connection = Depends(get_db)) -> Response:
    """Say no to an invite. The person who sent it sees that you declined in their activity. Not yours is ``404``."""
    _available(request, conn)
    row = _open_invite(conn, invite_id, user)
    conn.execute("UPDATE care_invites SET answered_at = ?, answer = 'declined' WHERE id = ?", (clock.now_iso(), invite_id))
    audit(conn, user.id, "care.invite_answered", "user", int(row["owner_user_id"]), ip=request_ip(request), invite=invite_id,
          answer="declined")
    conn.commit()
    return Response(status_code=204)


@shared_router.post("/info")
def share_link_info(body: ShareCode, request: Request, user: CurrentUser, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """Who a link is from and what it shares, so the person can say yes or no. It does not use the link up. A wrong, used or
    expired link is the generic ``404``; every try counts toward 20 an hour."""
    _available(request, conn)
    row = _find_code(conn, request, user, body.code)
    return {"name": _name(row, "owner"), "username": row["owner_username"], "areas": _areas(row["areas"]), "days": row["lasts_days"],
            "expires_at": row["expires_at"], "role": _role(row)}


@shared_router.post("/accept", status_code=201)
def accept_share_link(body: ShareCode, request: Request, user: CurrentUser, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """Accept a link: from now on you can read what it shares, until either side stops it or its end date (``until``). A newer link
    from someone who already shares with you replaces the old share, with the new link's areas and end date."""
    _available(request, conn)
    begin_immediate(conn)  # the count, the replacement and the update see the same rows
    try:
        row = _find_code(conn, request, user, body.code)
        owner_id = int(row["owner_user_id"])
        old = conn.execute("SELECT id FROM shares WHERE owner_user_id = ? AND grantee_user_id = ? AND accepted_at IS NOT NULL "
                           "AND ended_at IS NULL", (owner_id, user.id)).fetchone()
        if old is None and active_count(conn, owner_id) >= MAX_SHARES:
            raise ApiProblem(409, OWNER_FULL)
        moment = clock.now()
        now = clock.iso(moment)
        ends = clock.iso(moment + timedelta(days=int(row["lasts_days"]))) if row["lasts_days"] else None
        if old is not None:
            conn.execute("UPDATE shares SET ended_at = ?, ended_by = 'replaced' WHERE id = ?", (now, int(old["id"])))
        conn.execute("UPDATE shares SET grantee_user_id = ?, accepted_at = ?, ends_at = ?, code_id = NULL, verifier_hash = NULL, "
                     "expires_at = NULL WHERE id = ?", (user.id, now, ends, int(row["id"])))
        audit(conn, user.id, "share.accepted", "user", owner_id, ip=request_ip(request), share=int(row["id"]), areas=_areas(row["areas"]),
              replaced=old is not None, until=ends, role=_role(row))
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return person_item(conn.execute(_PEOPLE + " WHERE s.id = ?", (int(row["id"]),)).fetchone())


@shared_router.delete("/{share_id}", status_code=204, response_class=Response)
def stop_seeing(share_id: ShareId, request: Request, user: CurrentUser, conn: sqlite3.Connection = Depends(get_db)) -> Response:
    """Stop seeing someone's data. Not yours, or already ended, is ``404``."""
    _available(request, conn)
    row = conn.execute("SELECT id, owner_user_id FROM shares WHERE id = ? AND grantee_user_id = ? AND accepted_at IS NOT NULL "
                       "AND ended_at IS NULL", (share_id, user.id)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="share not found")
    conn.execute("UPDATE shares SET ended_at = ?, ended_by = 'grantee' WHERE id = ?", (clock.now_iso(), share_id))
    audit(conn, user.id, "share.ended", "user", int(row["owner_user_id"]), ip=request_ip(request), share=share_id, by="grantee")
    conn.commit()
    return Response(status_code=204)


# --------------------------------------------------------------------------- #
# The one check, and the reads
# --------------------------------------------------------------------------- #


def shared_owner(area: str | None) -> Callable[..., User]:
    """A dependency: the owner of share ``share_id`` when it is the signed-in person's, active, both accounts are active and
    ``area`` was shared (``None``: any active share). Else the one ``404``. The first read of a share each day (UTC) is written to
    the owner's activity (``share.viewed``)."""

    def dependency(share_id: ShareId, request: Request, user: CurrentUser, conn: sqlite3.Connection = Depends(get_db)) -> User:
        return _check_share(share_id, request, user, conn, area)[0]

    return dependency


def _check_share(share_id: int, request: Request, user: User, conn: sqlite3.Connection, area: str | None,
                 role: str | None = None) -> tuple[User, sqlite3.Row]:
    """The one check (see :func:`shared_owner`), and with ``role`` that the share has that role now. Returns the owner and the
    share's row as it is now."""
    _available(request, conn)
    row = conn.execute(_PEOPLE + " WHERE s.id = ? AND s.grantee_user_id = ? AND s.accepted_at IS NOT NULL AND s.ended_at IS NULL",
                       (share_id, user.id)).fetchone()
    if row is None or row["owner_status"] != "active" or (area is not None and area not in _areas(row["areas"])) or not _same_kind(row):
        raise ApiProblem(404, NOT_SHARED)
    if role is not None and _role(row) != role:
        raise ApiProblem(404, NOT_SHARED)
    owner = load_user(conn, int(row["owner_user_id"]))
    if owner is None or not owner.is_active or not user.is_active:
        raise ApiProblem(404, NOT_SHARED)
    if (row["last_viewed_at"] or "")[:10] != _today():
        conn.execute("UPDATE shares SET last_viewed_at = ? WHERE id = ?", (clock.now_iso(), share_id))
        audit(conn, user.id, "share.viewed", "user", owner.id, ip=request_ip(request), share=share_id)
        conn.commit()
    return owner, row


@dataclass(frozen=True)
class CareShare:
    """What a Care helper's write needs: the person (``owner``), the helper (``helper``) and the share's id."""

    owner: User
    helper: User
    share_id: int


def care_helper(share_id: ShareId, request: Request, user: CurrentUser, conn: sqlite3.Connection = Depends(get_db)) -> CareShare:
    """A dependency for every Care helper route, checked on each request against the share as it is now (design note 25 §5):
    the signed-in person's, accepted, not stopped or past its end date, the role is ``care_helper``, the food log is shared,
    both accounts are active and sharing is on. Anything else is the one ``404``."""
    owner, _row = _check_share(share_id, request, user, conn, "food", role="care_helper")
    return CareShare(owner=owner, helper=user, share_id=share_id)


Helper = Annotated[CareShare, Depends(care_helper)]


def note_change(conn: sqlite3.Connection, care: CareShare, kind: str, n: int, request: Request) -> None:
    """Count a Care helper's change for the person's Care team list, and write ``care.plan_changed`` to the person's activity at
    the helper's first change of the day (UTC). Commits."""
    if n <= 0:
        return
    row = conn.execute("SELECT helper_changes FROM shares WHERE id = ?", (care.share_id,)).fetchone()
    today = _today()
    got = _helper_changes(row) if row is not None else None
    if got is None or got["day"] != today:
        got = {"day": today, "added": 0, "changed": 0, "removed": 0}
        audit(conn, care.helper.id, "care.plan_changed", "user", care.owner.id, ip=request_ip(request), share=care.share_id)
    got[kind] += int(n)
    conn.execute("UPDATE shares SET helper_changes = ? WHERE id = ?", (json.dumps(got, sort_keys=True), care.share_id))
    conn.commit()


def _planned_entry(conn: sqlite3.Connection, owner_id: int, entry_id: int) -> sqlite3.Row:
    """A planned entry of the owner that is not a low treatment, or ``404`` as if it did not exist: a helper never changes eaten
    food or a low treatment, and only ever reaches the owner's log."""
    row = log_module.fetch_entry(conn, owner_id, entry_id)
    if row is None or row["status"] != "planned" or row["purpose"] == log_module.HYPO_PURPOSE:
        raise HTTPException(status_code=404, detail=NO_ENTRY.format(entry_id))
    return row


AnyShare = Annotated[User, Depends(shared_owner(None))]
FoodShare = Annotated[User, Depends(shared_owner("food"))]
LabsShare = Annotated[User, Depends(shared_owner("labs"))]
BodyShare = Annotated[User, Depends(shared_owner("body"))]
SymptomsShare = Annotated[User, Depends(shared_owner("symptoms"))]
ActivityShare = Annotated[User, Depends(shared_owner("activity"))]


def _shares_activity(conn: sqlite3.Connection, share_id: int) -> bool:
    row = conn.execute("SELECT areas FROM shares WHERE id = ?", (share_id,)).fetchone()  # shared_owner checked it is this person's
    return row is not None and "activity" in _areas(row["areas"])


@shared_router.get("/{share_id}/profile", response_model=SharedProfile)
def shared_profile(share_id: ShareId, owner: AnyShare, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """The owner's name and what the shared pages need from their profile: stage, dialysis, diabetes, dialysis days, the first day
    of the week and their targets. The weight they set is a body measurement: it is ``null`` unless ``body`` was shared."""
    p = get_profile(conn, owner.id)
    out = {"name": (owner.display_name or "").strip() or owner.username, **{k: p[k] for k in SharedProfile.model_fields if k != "name"}}
    row = conn.execute("SELECT areas FROM shares WHERE id = ?", (share_id,)).fetchone()  # shared_owner checked it is this person's
    if row is None or "body" not in _areas(row["areas"]):
        out["weight_kg"] = None
    return out


@shared_router.get("/{share_id}/log", response_model=DaySummary)
def shared_day(share_id: ShareId, request: Request, owner: FoodShare, date: str | None = None,
               conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """A day of the owner's food log, as ``GET /api/log`` answers it to them; without the activity area with the base calorie target
    (the active-day extra would tell how active they were)."""
    day = log_module.parse_date_param(date, "date") if date else log_module.today_local()
    return log_module.day_summary(conn, request, owner.id, day, activity_extra=_shares_activity(conn, share_id))


@shared_router.get("/{share_id}/log/range", response_model=RangeSummary)
def shared_range(share_id: ShareId, owner: FoodShare, start: str | None = None, end: str | None = None,
                 conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """The owner's daily totals for a range (the Trends charts), as ``GET /api/log/range`` answers it to them."""
    return log_module.get_range(owner, start, end, conn)


@shared_router.get("/{share_id}/log/summary", response_model=PeriodSummary)
def shared_period(share_id: ShareId, owner: FoodShare, start: str | None = None, end: str | None = None,
                  conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """The owner's period summary, as ``GET /api/log/summary``."""
    return log_module.get_summary(owner, start, end, conn)


@shared_router.get("/{share_id}/labs", response_model=LabList)
def shared_labs(share_id: ShareId, request: Request, owner: LabsShare, conn: sqlite3.Connection = Depends(get_db),
                analyte: Analyte | None = None,
                limit: int = Query(labs_module.DEFAULT_LIST_LIMIT, ge=1, le=labs_module.MAX_LIST_LIMIT)) -> dict[str, Any]:
    """The owner's lab results, as ``GET /api/labs``."""
    return labs_module.list_labs(owner, request, conn, analyte, limit)


@shared_router.get("/{share_id}/body/summary", response_model=BodySummary)
def shared_body_summary(share_id: ShareId, request: Request, owner: BodyShare, conn: sqlite3.Connection = Depends(get_db),
                        date: str | None = None) -> dict[str, Any]:
    """The owner's weight and blood pressure summary, as ``GET /api/body/summary``."""
    return body_module.summary(request, owner, conn, date)


@shared_router.get("/{share_id}/body/weights", response_model=WeightList)
def shared_weights(share_id: ShareId, owner: BodyShare, conn: sqlite3.Connection = Depends(get_db), start: str | None = None,
                   end: str | None = None) -> dict[str, Any]:
    """The owner's weights, as ``GET /api/body/weights``."""
    return body_module.list_weights(owner, conn, start, end)


@shared_router.get("/{share_id}/body/blood-pressure", response_model=BloodPressureList)
def shared_blood_pressure(share_id: ShareId, owner: BodyShare, conn: sqlite3.Connection = Depends(get_db), start: str | None = None,
                          end: str | None = None) -> dict[str, Any]:
    """The owner's blood pressure readings, as ``GET /api/body/blood-pressure``."""
    return body_module.list_readings(owner, conn, start, end)


@shared_router.get("/{share_id}/symptoms", response_model=SymptomList)
def shared_symptoms(share_id: ShareId, owner: SymptomsShare, conn: sqlite3.Connection = Depends(get_db), start: str | None = None,
                    end: str | None = None) -> dict[str, Any]:
    """The owner's symptoms log, as ``GET /api/symptoms``."""
    return symptoms_module.list_symptoms(owner, conn, start, end)


@shared_router.get("/{share_id}/activity", response_model=activity_module.ActivityOut)
def shared_activity(share_id: ShareId, owner: ActivityShare, conn: sqlite3.Connection = Depends(get_db), start: str | None = None,
                    end: str | None = None) -> dict[str, Any]:
    """The owner's Whoop days and workouts (the Activity and recovery card), as ``GET /api/activity`` without their setting."""
    start_s, end_s = activity_module.parse_range(start, end)
    return activity_module.activity_view(conn, owner.id, start_s, end_s)


# --------------------------------------------------------------------------- #
# The Care helper: planned food, Plan several days and the shopping list (design note 25 §5)
# --------------------------------------------------------------------------- #


@shared_router.get("/{share_id}/foods", response_model=FoodList)
def helper_foods(share_id: ShareId, care: Helper, q: str = Query("", max_length=MAX_SEARCH_QUERY_CHARS),
                 limit: int = Query(25, ge=1, le=200), conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """Food search as the person sees it (their own foods too), so a food the helper plans is one the person can use."""
    return {"foods": search_foods(conn, care.owner.id, q=q, limit=limit)}


@shared_router.get("/{share_id}/plan/shopping", response_model=ShoppingList)
def helper_shopping(share_id: ShareId, care: Helper, start: str | None = None, end: str | None = None,
                    conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """The person's shopping list, as ``GET /api/plan/shopping`` answers it to them. Ticks stay on the helper's device."""
    return meals_module.shopping_list(care.owner, start, end, conn)


@shared_router.post("/{share_id}/log", response_model=Entry, status_code=201)
def helper_add(share_id: ShareId, body: HelperEntry, request: Request, care: Helper,
               conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """Plan one food on the person's day. It is always ``planned`` and records the helper (``added_by``). The food must be one
    the person can use (``404`` otherwise). A planned low treatment may be added, like any food."""
    item = body.model_copy(update={"client_id": None})
    entry_id = log_module.insert_logged(conn, care.owner.id, item, added_by=care.helper.id)
    conn.commit()
    note_change(conn, care, "added", 1, request)
    return log_module.row_to_entry(log_module.fetch_entry(conn, care.owner.id, entry_id))


@shared_router.post("/{share_id}/log/batch", response_model=LogBatchResult, status_code=201)
def helper_add_batch(share_id: ShareId, body: HelperBatch, request: Request, care: Helper,
                     conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """Plan 1 to 40 foods on the person's days in one go ("Add to plan"), all or nothing, each as ``POST …/log``."""
    created: list[int] = []
    try:
        for index, item in enumerate(body.entries):
            created.append(log_module.insert_logged(conn, care.owner.id, item.model_copy(update={"client_id": None}),
                                                    where=f"entries[{index}]: ", added_by=care.helper.id))
    except Exception:
        conn.rollback()
        raise
    conn.commit()
    note_change(conn, care, "added", len(created), request)
    entries = [log_module.row_to_entry(log_module.fetch_entry(conn, care.owner.id, i)) for i in created]
    return {"entries": entries, "results": [{"index": i, "id": e["id"], "result": "created"} for i, e in enumerate(entries)]}


def _tag(row: sqlite3.Row) -> str:
    return f'"{log_module.row_to_entry(row)["version"]}"'


@shared_router.put("/{share_id}/log/{entry_id}", response_model=Entry, responses=log_module.PRECONDITION_FAILED)
def helper_change(share_id: ShareId, entry_id: ShareId, body: HelperUpdate, request: Request, care: Helper,
                  if_match: log_module.IfMatch = None, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """Change the amount, meal, day or note of one of the person's planned entries. Eaten food and planned low treatments are
    ``404``: only the person changes those. ``If-Match`` works as on the person's own route."""
    row = _planned_entry(conn, care.owner.id, entry_id)
    log_module.require_current_version(row, if_match)
    # The write lands only on the row checked here: if the person marks it eaten in between, the answer is 412.
    out = log_module.update_entry(entry_id, LogUpdate(**body.model_dump(exclude_unset=True)), care.owner, _tag(row), conn)
    note_change(conn, care, "changed", 1, request)
    return out


@shared_router.delete("/{share_id}/log/{entry_id}", status_code=204, response_class=Response, responses=log_module.PRECONDITION_FAILED)
def helper_remove(share_id: ShareId, entry_id: ShareId, request: Request, care: Helper,
                  if_match: log_module.IfMatch = None, conn: sqlite3.Connection = Depends(get_db)) -> Response:
    """Take one of the person's planned entries off their plan. Eaten food and planned low treatments are ``404``."""
    row = _planned_entry(conn, care.owner.id, entry_id)
    log_module.require_current_version(row, if_match)
    log_module.delete_entry(entry_id, care.owner, _tag(row), conn)
    note_change(conn, care, "removed", 1, request)
    return Response(status_code=204)


@shared_router.post("/{share_id}/log/clear-planned", response_model=ClearPlannedResult)
def helper_clear(share_id: ShareId, body: ClearPlanned, request: Request, care: Helper,
                 conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """Clear planned days for the person, exactly as their own route: eaten food and planned low treatments always stay."""
    out = log_module.clear_planned(body, request, care.owner, conn)
    note_change(conn, care, "removed", int(out["deleted"]), request)
    return out


@shared_router.post("/{share_id}/guidance/plan-days", response_model=PlanDaysResponse | GuidanceUnavailable)
def helper_plan_days(share_id: ShareId, body: PlanDaysRequest, request: Request, care: Helper,
                     conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """Plan several days for the person against their targets (computes only; "Add to plan" sends the entries to
    ``POST …/log/batch``). The person's saved meals are never used, so a plan never shows them (design note 25 §7), and without the
    activity area the plan uses the base calorie target (design note 28): the active-day extra would tell how active they were."""
    return guidance_api.plan_days_for(body.model_copy(update={"use_saved_meals": False}), request, care.owner, conn,
                                      activity_extra=_shares_activity(conn, care.share_id))
