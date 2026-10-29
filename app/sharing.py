"""Read-only sharing with a caregiver or dietitian (design note 19; ARCHITECTURE.md "Sharing").

A person (the **owner**) makes a link in Settings → Account → Sharing and sends it to someone with an account on the same
server (the **grantee**), who accepts it. From then on the grantee can read the areas the owner ticked, and nothing else, until
either side stops it, or until the end date the owner chose (``days``; :func:`expire` ends it then).

* ``/api/me/shares``: the owner's list, a new link (recent password), stopping a share or cancelling a link.
* ``/api/shared``: the grantee's list, stopping, and ``info`` / ``accept`` for a link.
* ``/api/shared/{share_id}/…``: the reads. Each goes through :func:`shared_owner`, the one check: the share is the signed-in
  person's, active, both accounts are active, and the area was shared. It returns the **owner's** user, and the handler calls the
  owner's own route function with it, so the answer is exactly what the owner sees. Anything else is the same ``404``. There is
  no write route here.

Every route answers ``404`` while ``sharing.enabled`` is off and in ``AUTH_MODE=none``. The link is ``/#/share/<id>.<verifier>``
(the fragment never reaches the server or its logs); only the SHA-256 of the verifier is stored, and a link works once.
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

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from . import body as body_module
from . import labs as labs_module
from . import log as log_module
from . import symptoms as symptoms_module
from .audit import audit
from .auth import clock
from .auth.accounts import begin_immediate
from .auth.context import auth_context, public_base, request_ip
from .auth.deps import CurrentUser, RecentUser, current_user
from .auth.errors import ApiProblem
from .auth.models import User, load_user
from .auth.ratelimit import register_limit
from .auth.tokens import link as token_link
from .db import get_db
from .models import (
    Analyte,
    BloodPressureList,
    BodySummary,
    CkdStage,
    DaySummary,
    Diabetes,
    Dialysis,
    LabList,
    Number,
    PeriodSummary,
    SymptomList,
    TargetValue,
    WeekStart,
    WeightList,
)
from .profile import get_profile

SWITCH = "sharing.enabled"
AREAS = ("food", "labs", "body", "symptoms")
Area = Literal["food", "labs", "body", "symptoms"]
CODE_DAYS = 7
MAX_DAYS = 365  # the longest time limit a share can have
MAX_CODES = 5  # unused links a person can have at once
MAX_SHARES = 10  # people who can see one person's data at once
MAX_ROW_ID = 2**63 - 1

NOT_SHARED = "Not shared with you."
BAD_LINK = "That link does not work. Ask for a new one."
OWN_LINK = "This is your own link. Send it to the person you want to share with."
TOO_MANY_CODES = f"You have {MAX_CODES} links nobody has used yet. Cancel one first."
TOO_MANY_SHARES = f"You already share with {MAX_SHARES} people, the most allowed. Stop sharing with someone first."
OWNER_FULL = f"This person already shares with {MAX_SHARES} people, the most allowed. Ask them to stop one first."

register_limit("share_link", 20, 3600, "Too many tries with share links. Try again in an hour.")

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


def _clean_areas(areas: list[str]) -> list[str]:
    return [a for a in AREAS if a in set(areas)]  # one each, in the order of AREAS


def _name(row: sqlite3.Row, prefix: str) -> str:
    return (row[f"{prefix}_display"] or "").strip() or row[f"{prefix}_username"]


def _today() -> str:
    return clock.now_iso()[:10]


_PEOPLE = """
SELECT s.*, o.username AS owner_username, o.display_name AS owner_display, o.status AS owner_status,
       g.username AS grantee_username, g.display_name AS grantee_display, g.status AS grantee_status
FROM shares s JOIN users o ON o.id = s.owner_user_id LEFT JOIN users g ON g.id = s.grantee_user_id
"""


def sharing_item(row: sqlite3.Row) -> dict[str, Any]:
    """One person who can see the owner's data, as the owner's list shows it. ``until`` is when it ends (None: until stopped)."""
    return {"id": int(row["id"]), "name": _name(row, "grantee"), "username": row["grantee_username"], "areas": _areas(row["areas"]),
            "since": row["accepted_at"], "until": row["ends_at"], "last_viewed_at": row["last_viewed_at"],
            "active": row["grantee_status"] == "active"}


def code_item(row: sqlite3.Row) -> dict[str, Any]:
    """An unused link. ``days`` is how long the share will last once accepted (None: until stopped)."""
    return {"id": int(row["id"]), "areas": _areas(row["areas"]), "days": row["lasts_days"], "created_at": row["created_at"],
            "expires_at": row["expires_at"]}


def person_item(row: sqlite3.Row) -> dict[str, Any]:
    """One person who shares with the signed-in person, as the grantee's list shows it."""
    return {"id": int(row["id"]), "name": _name(row, "owner"), "username": row["owner_username"], "areas": _areas(row["areas"]),
            "since": row["accepted_at"], "until": row["ends_at"]}


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
    cur = conn.execute("UPDATE shares SET ended_at = ?, ended_by = ? WHERE ended_at IS NULL AND (owner_user_id = ? OR grantee_user_id = ?)",
                       (clock.now_iso(), by, user_id, user_id))
    return int(cur.rowcount)


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
    if int(row["owner_user_id"]) == user.id:
        raise ApiProblem(400, OWN_LINK)
    return row


# --------------------------------------------------------------------------- #
# The owner: /api/me/shares
# --------------------------------------------------------------------------- #


@me_router.get("")
def list_my_shares(request: Request, user: CurrentUser, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """``{enabled, areas, max, sharing, codes}``: who can see your data and your unused links. ``enabled`` is false (and the lists
    empty) while the admin has sharing off."""
    if not enabled(conn, request):
        if auth_context(request).settings.auth_mode == "none":
            raise HTTPException(status_code=404, detail="Not Found")
        return {"enabled": False, "areas": list(AREAS), "max": MAX_SHARES, "sharing": [], "codes": []}
    expire(conn)
    sharing = conn.execute(_PEOPLE + " WHERE s.owner_user_id = ? AND s.accepted_at IS NOT NULL AND s.ended_at IS NULL "
                                     "ORDER BY s.accepted_at, s.id", (user.id,)).fetchall()
    codes = conn.execute(_PEOPLE + " WHERE s.owner_user_id = ? AND s.accepted_at IS NULL AND s.ended_at IS NULL AND s.expires_at > ? "
                                   "ORDER BY s.created_at, s.id", (user.id, clock.now_iso())).fetchall()
    return {"enabled": True, "areas": list(AREAS), "max": MAX_SHARES, "sharing": [sharing_item(r) for r in sharing],
            "codes": [code_item(r) for r in codes]}


@me_router.post("", status_code=201)
def create_share_link(body: ShareCreate, request: Request, user: RecentUser, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """A new link for the areas ticked (``food``, ``labs``, ``body``, ``symptoms``), in this answer only (``link``). It works once,
    for 7 days. ``days`` (1 to 365) makes the share end that many days after it is accepted; without it the share lasts until
    someone stops it. Needs a recent password, like making a token."""
    _available(request, conn)
    areas = _clean_areas(body.areas)
    now = clock.now()
    open_codes = int(conn.execute("SELECT COUNT(*) FROM shares WHERE owner_user_id = ? AND accepted_at IS NULL AND ended_at IS NULL "
                                  "AND expires_at > ?", (user.id, clock.iso(now))).fetchone()[0])
    if open_codes >= MAX_CODES:
        raise ApiProblem(409, TOO_MANY_CODES)
    if active_count(conn, user.id) >= MAX_SHARES:
        raise ApiProblem(409, TOO_MANY_SHARES)
    code_id, verifier = secrets.token_hex(8), secrets.token_urlsafe(32)
    cur = conn.execute("INSERT INTO shares (owner_user_id, code_id, verifier_hash, areas, created_at, expires_at, lasts_days) "
                       "VALUES (?, ?, ?, ?, ?, ?, ?)", (user.id, code_id, _sha(verifier), json.dumps(areas), clock.iso(now),
                                                        clock.iso(now + timedelta(days=CODE_DAYS)), body.days))
    share_id = int(cur.lastrowid or 0)
    audit(conn, user.id, "share.code_created", "share", share_id, ip=request_ip(request), areas=areas, days=body.days)
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


# --------------------------------------------------------------------------- #
# The grantee: /api/shared
# --------------------------------------------------------------------------- #


@shared_router.get("")
def list_shared_with_me(request: Request, user: CurrentUser, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """``{people}``: the people who share with you and what, while their account is active."""
    _available(request, conn)
    rows = conn.execute(_PEOPLE + " WHERE s.grantee_user_id = ? AND s.accepted_at IS NOT NULL AND s.ended_at IS NULL "
                                  "AND o.status = 'active' ORDER BY s.accepted_at, s.id", (user.id,)).fetchall()
    return {"people": [person_item(r) for r in rows]}


@shared_router.post("/info")
def share_link_info(body: ShareCode, request: Request, user: CurrentUser, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """Who a link is from and what it shares, so the person can say yes or no. It does not use the link up. A wrong, used or
    expired link is the generic ``404``; every try counts toward 20 an hour."""
    _available(request, conn)
    row = _find_code(conn, request, user, body.code)
    return {"name": _name(row, "owner"), "username": row["owner_username"], "areas": _areas(row["areas"]), "days": row["lasts_days"],
            "expires_at": row["expires_at"]}


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
              replaced=old is not None, until=ends)
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
        _available(request, conn)
        row = conn.execute(_PEOPLE + " WHERE s.id = ? AND s.grantee_user_id = ? AND s.accepted_at IS NOT NULL AND s.ended_at IS NULL",
                           (share_id, user.id)).fetchone()
        if row is None or row["owner_status"] != "active" or (area is not None and area not in _areas(row["areas"])):
            raise ApiProblem(404, NOT_SHARED)
        owner = load_user(conn, int(row["owner_user_id"]))
        if owner is None or not owner.is_active:
            raise ApiProblem(404, NOT_SHARED)
        if (row["last_viewed_at"] or "")[:10] != _today():
            conn.execute("UPDATE shares SET last_viewed_at = ? WHERE id = ?", (clock.now_iso(), share_id))
            audit(conn, user.id, "share.viewed", "user", owner.id, ip=request_ip(request), share=share_id)
            conn.commit()
        return owner

    return dependency


AnyShare = Annotated[User, Depends(shared_owner(None))]
FoodShare = Annotated[User, Depends(shared_owner("food"))]
LabsShare = Annotated[User, Depends(shared_owner("labs"))]
BodyShare = Annotated[User, Depends(shared_owner("body"))]
SymptomsShare = Annotated[User, Depends(shared_owner("symptoms"))]


@shared_router.get("/{share_id}/profile", response_model=SharedProfile)
def shared_profile(share_id: ShareId, owner: AnyShare, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """The owner's name and what the shared pages need from their profile: stage, dialysis, diabetes, dialysis days, the first day
    of the week, the weight they set and their targets."""
    p = get_profile(conn, owner.id)
    return {"name": (owner.display_name or "").strip() or owner.username, **{k: p[k] for k in SharedProfile.model_fields if k != "name"}}


@shared_router.get("/{share_id}/log", response_model=DaySummary)
def shared_day(share_id: ShareId, request: Request, owner: FoodShare, date: str | None = None,
               conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """A day of the owner's food log, as ``GET /api/log`` answers it to them."""
    return log_module.get_day(owner, request, date, conn)


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
