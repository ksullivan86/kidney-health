"""``/api/me/totp*``: turn two-step sign-in on and off, and renew the recovery codes (design note 17 §6).

Local accounts in ``AUTH_MODE=local`` only: everywhere else every route answers 404 (the sign-in proxy does sign-in). Every
change needs a recent password (re-auth). The secret leaves the server once, in the answer of ``POST /setup``; the recovery
codes once, in the answers of ``POST /enable`` and ``POST /recovery-codes``. Every route acts on ``user.id`` only.
"""
from __future__ import annotations

import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from ..audit import audit
from ..db import get_db
from . import clock, sessions, totp
from .context import auth_context, request_ip
from .deps import CurrentUser, RecentUser, current_user, two_step_required
from .errors import ApiProblem
from .models import User
from .ratelimit import register_limit
from .schemas import TotpCodeBody

router = APIRouter(prefix="/api/me/totp", tags=["me"], dependencies=[Depends(current_user)])

register_limit("totp_enable", 10, 900, "Too many codes tried. Wait a few minutes and try again.")

NOT_PENDING = "Start again: tap Turn on to get a new QR code."
ALREADY_ON = "Two-step sign-in is already on."
NOT_ON = "Two-step sign-in is off."
WRONG_CODE = "That code is not right. Type the code your app shows now, and check that the time on this device is right."


def available(request: Request, user: User) -> bool:
    return auth_context(request).settings.auth_mode == "local" and user.auth_source == "local"


def _only_local(request: Request, user: User) -> None:
    if not available(request, user):
        raise HTTPException(status_code=404, detail="Not Found")


def status(conn: sqlite3.Connection, user_id: int) -> dict[str, Any]:
    row = conn.execute("SELECT enabled_at FROM totp_factors WHERE user_id = ? AND enabled_at IS NOT NULL", (int(user_id),)).fetchone()
    return {
        "enabled": row is not None,
        "enabled_at": row["enabled_at"] if row is not None else None,
        "recovery_codes_left": totp.recovery_codes_left(conn, user_id) if row is not None else 0,
    }


@router.get("")
def read_totp(request: Request, user: CurrentUser, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """Whether two-step sign-in is on, and how many recovery codes are left. Never the secret."""
    if not available(request, user):
        return {"available": False, "enabled": False, "enabled_at": None, "recovery_codes_left": 0, "required": False}
    # required: this person is an admin and the server asks admins to use it (auth.require_two_step_admins).
    required = user.role == "admin" and two_step_required(auth_context(request), conn, user)
    return {"available": True, **status(conn, user.id), "required": required}


@router.post("/setup")
def setup_totp(request: Request, user: RecentUser, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """A new secret, kept as not on yet until :func:`enable_totp` sees a code from it. Replaces an earlier unfinished one."""
    _only_local(request, user)
    ctx = auth_context(request)
    if totp.is_enabled(conn, user.id):
        raise ApiProblem(409, ALREADY_ON)
    key = totp.start(conn, ctx.require_keyring(), user.id)
    conn.commit()
    issuer = str(ctx.store.get(conn, "instance.name")).strip() or "Kidney Health"
    return {
        "secret": totp.secret_text(key),
        "uri": totp.otpauth_uri(key, issuer=issuer, account=user.username),
        "issuer": issuer,
        "account": user.username,
        "digits": totp.DIGITS,
        "period": totp.STEP_S,
    }


@router.post("/enable")
def enable_totp(body: TotpCodeBody, request: Request, user: RecentUser, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """Turn it on when the code is right for the pending secret: the recovery codes (shown once) and the other sessions signed out."""
    _only_local(request, user)
    ctx = auth_context(request)
    ctx.limits.take("totp_enable", f"user:{user.id}")
    factor = totp.load(conn, ctx.require_keyring(), user.id)
    if factor is not None and factor.enabled:
        raise ApiProblem(409, ALREADY_ON)
    if factor is None or factor.key is None:
        raise ApiProblem(409, NOT_PENDING)
    step = totp.matching_step(factor.key, totp.clean_code(body.code.get_secret_value()), seconds=clock.seconds(), after_step=0)
    if step is None:
        raise ApiProblem(400, WRONG_CODE, field="code")
    codes = totp.enable(conn, user.id, step)
    info = getattr(request.state, "auth_session", None)
    signed_out = sessions.revoke_user_sessions(conn, user.id, except_id=info.id if info is not None else None)
    audit(conn, user.id, "totp.enabled", "user", user.id, ip=request_ip(request), signed_out=signed_out)
    conn.commit()
    return {"recovery_codes": codes, "signed_out": signed_out, **status(conn, user.id)}


@router.post("/recovery-codes")
def renew_recovery_codes(request: Request, user: RecentUser, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """A new set of recovery codes (shown once); the old set stops working."""
    _only_local(request, user)
    if not totp.is_enabled(conn, user.id):
        raise ApiProblem(409, NOT_ON)
    codes = totp.renew_recovery_codes(conn, user.id)
    audit(conn, user.id, "totp.recovery_codes_renewed", "user", user.id, ip=request_ip(request))
    conn.commit()
    return {"recovery_codes": codes, **status(conn, user.id)}


@router.delete("", status_code=204, response_class=Response)
def disable_totp(request: Request, user: RecentUser, conn: sqlite3.Connection = Depends(get_db)) -> Response:
    """Turn it off (or drop an unfinished setup) and remove the recovery codes. The person's sessions stay."""
    _only_local(request, user)
    if totp.remove(conn, user.id):
        audit(conn, user.id, "totp.disabled", "user", user.id, ip=request_ip(request), via="self")
    conn.commit()
    return Response(status_code=204)
