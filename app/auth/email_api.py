"""Password reset by email (design note 34): the person's address, its confirmation, "Forgot your password?" and the admin's
test email.

* ``GET/PUT/DELETE /api/me/email``: the signed-in person's own address. Setting or changing it needs a recent password
  (``RecentUser``) and sends a confirmation link (single use, 24 hours) to that address. Until it is confirmed it gets no reset
  emails. Removing it needs no email. Nobody else ever sees the address: the admin's user list says only whether one is confirmed.
* ``POST /api/auth/email/confirm`` (public + confirmation token): confirms the address the link was sent to.
* ``POST /api/auth/forgot`` (public): always the same ``202`` and words, whether or not the account exists or has a confirmed
  address. For an active local account with a confirmed address (not a test account) it voids the account's older reset links,
  makes a new one for 1 hour with the reset-link machinery of :mod:`app.auth.tokens`, and emails it without waiting for the mail
  server. ``POST /api/auth/reset`` then works as for an admin's link.
* ``POST /api/admin/email/test`` (``RecentAdmin``): a test email to the admin's own confirmed address.

All of it is off (404) unless ``EMAIL_ENABLED`` is on and sign-in is local; with ``OIDC_ONLY`` nobody signs in with a password,
so there is nothing to reset either.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse

from .. import mail
from ..audit import audit
from ..db import get_db, utcnow
from . import clock, housekeeping, tokens
from .context import AuthContext, auth_context, public_base, request_ip
from .deps import CurrentUser, RecentAdmin, RecentUser, current_user, ensure_setup_done, require_admin
from .errors import ApiProblem, too_many
from .models import User, find_local_user, normalize_username, valid_local_username
from .ratelimit import register_limit
from .schemas import EmailBody, ForgotBody, LinkInfoBody
from .throttle import ip_key

me_router = APIRouter(prefix="/api/me", tags=["me"], dependencies=[Depends(current_user)])
auth_router = APIRouter(prefix="/api/auth", tags=["auth"])
admin_router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_admin)])

FORGOT_SENT = "If that account has a confirmed email, a link is on its way. It works for 1 hour."
EMAIL_OFF = "Email is off on this server. An admin can turn it on (EMAIL_ENABLED, see docs/accounts.md)."
TEST_ACCOUNT = "This is a test account, shared by the testers, so it cannot have an email for password resets."
CONFIRM_INVALID = "This link is not valid any more. Ask for a new one in Settings → Account."
CONFIRM_TAKEN = "This address is already confirmed for another account here. Use a different address."
ADMIN_NO_EMAIL = "Add and confirm your own email in Settings → Account first. The test email goes there."
ALREADY_CONFIRMED = "This address is already confirmed."
RESET_NOTE = "email"  # auth_tokens.note of a reset link sent by email (the reset audit says via="email_link")

register_limit("forgot_ip", 10, 3600, "Too many password reset requests from this address. Try again later.")
register_limit("forgot_account", 3, 3600)  # never answered with a 429: the same 202 for every name
register_limit("email_confirm", 5, 3600, "Too many confirmation emails. Try again later.")


def purge_old_links(conn: sqlite3.Connection) -> int:
    """Delete confirmation links that are used or out of date (daily housekeeping)."""
    cur = conn.execute("DELETE FROM email_tokens WHERE used_at IS NOT NULL OR expires_at <= ?", (clock.now_iso(),))
    conn.commit()
    return int(cur.rowcount or 0)


housekeeping.register_daily("email_tokens", lambda conn, ctx: purge_old_links(conn))


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def mailer(request: Request) -> mail.Mailer:
    return request.app.state.mailer


def _oidc_only(request: Request) -> bool:
    from .oidc_api import only

    return only(request)


def server_on(request: Request) -> bool:
    """Whether this server offers password reset by email: ``EMAIL_ENABLED``, local sign-in, and passwords in use."""
    ctx = auth_context(request)
    return mailer(request).enabled and ctx.settings.auth_mode == "local" and not _oidc_only(request)


def _unavailable(request: Request, user: User) -> str | None:
    """Why this person cannot use it: ``mode`` (no password sign-in here), ``test_account`` or ``off``; None when they can."""
    if auth_context(request).settings.auth_mode != "local" or user.auth_source != "local" or _oidc_only(request):
        return "mode"
    if user.is_test_account:
        return "test_account"
    if not mailer(request).enabled:
        return "off"
    return None


def _sha(text: str) -> bytes:
    return hashlib.sha256(text.encode("utf-8")).digest()


def _address(conn: sqlite3.Connection, user_id: int) -> sqlite3.Row:
    return conn.execute("SELECT email, email_confirmed_at FROM users WHERE id = ?", (int(user_id),)).fetchone()


def _view(request: Request, conn: sqlite3.Connection, user: User) -> dict[str, Any]:
    row = _address(conn, user.id)
    reason = _unavailable(request, user)
    return {
        "available": reason is None,
        "reason": reason,
        "email": row["email"] if row is not None else None,
        "confirmed": bool(row is not None and row["email"] and row["email_confirmed_at"]),
        "confirmed_at": row["email_confirmed_at"] if row is not None and row["email"] else None,
    }


def _instance(conn: sqlite3.Connection, ctx: AuthContext) -> str:
    return str(ctx.store.get(conn, "instance.name"))


def _void_email_links(conn: sqlite3.Connection, user_id: int) -> None:
    """The person's confirmation links, and the reset links that went to an address they no longer use."""
    conn.execute("DELETE FROM email_tokens WHERE user_id = ?", (int(user_id),))
    conn.execute("UPDATE auth_tokens SET used_at = ? WHERE purpose = 'reset' AND user_id = ? AND used_at IS NULL AND note = ?",
                 (clock.now_iso(), int(user_id), RESET_NOTE))


def _new_confirm_token(conn: sqlite3.Connection, user_id: int, address: str) -> str:
    token_id = secrets.token_hex(8)
    verifier = secrets.token_urlsafe(32)
    now = clock.now()
    conn.execute(
        "INSERT INTO email_tokens (id, user_id, email, verifier_hash, created_at, expires_at) VALUES (?, ?, ?, ?, ?, ?)",
        (token_id, int(user_id), address, _sha(verifier), clock.iso(now), clock.iso(now + timedelta(hours=mail.CONFIRM_HOURS))),
    )
    return f"{token_id}.{verifier}"


def _find_confirm_token(conn: sqlite3.Connection, token: str) -> sqlite3.Row | None:
    """The unused, unexpired row for ``token`` (constant-time verifier comparison), like :func:`tokens.find_token`."""
    if not token or "." not in token or len(token) > 200:
        return None
    token_id, _, verifier = token.partition(".")
    row = conn.execute("SELECT * FROM email_tokens WHERE id = ?", (token_id,)).fetchone()
    expected = bytes(row["verifier_hash"]) if row is not None else b"\0" * 32
    matches = hmac.compare_digest(expected, _sha(verifier))
    if row is None or not matches or row["used_at"] is not None or row["expires_at"] <= clock.now_iso():
        return None
    return row


# --------------------------------------------------------------------------- #
# The person's own address
# --------------------------------------------------------------------------- #


@me_router.get("/email")
def read_my_email(request: Request, user: CurrentUser, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """``{available, reason, email, confirmed, confirmed_at}``: the address is shown to its owner only."""
    return _view(request, conn, user)


@me_router.put("/email")
def set_my_email(body: EmailBody, request: Request, user: RecentUser, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """Save the address (not confirmed yet) and email a confirmation link to it. ``sent`` says whether that email went;
    the address is kept either way, and saving the same address again sends a new link."""
    ctx = auth_context(request)
    reason = _unavailable(request, user)
    if reason == "mode":
        raise HTTPException(status_code=404, detail="Not Found")
    if reason == "test_account":
        raise ApiProblem(409, TEST_ACCOUNT)
    if reason == "off":
        raise ApiProblem(409, EMAIL_OFF)
    try:
        address = mail.check_address(body.email)
    except mail.AddressRejected as exc:
        raise ApiProblem(400, str(exc), field="email") from None
    row = _address(conn, user.id)
    if row["email"] == address and row["email_confirmed_at"]:
        return {**_view(request, conn, user), "sent": False, "message": ALREADY_CONFIRMED}
    ctx.limits.take("email_confirm", user.id)
    changed = row["email"] != address
    _void_email_links(conn, user.id)
    conn.execute("UPDATE users SET email = ?, email_confirmed_at = NULL, updated_at = ? WHERE id = ?", (address, utcnow(), user.id))
    token = _new_confirm_token(conn, user.id, address)
    audit(conn, user.id, "email.set", "user", user.id, ip=request_ip(request), changed=bool(row["email"]) and changed,
          again=not changed)
    conn.commit()
    letter = mail.confirm_letter(address, user.username, _instance(conn, ctx), tokens.link(public_base(request, ctx.settings),
                                                                                           "confirm-email", token))
    out = _view(request, conn, user)
    try:
        mailer(request).send(letter)
    except mail.MailFailed as exc:
        return {**out, "sent": False, "message": f"The address is saved, but the email could not be sent. {exc.message} "
                                                 "Try again later, or ask your admin."}
    return {**out, "sent": True, "message": f"We sent a link to {address}. Open it within {mail.CONFIRM_HOURS} hours to confirm."}


@me_router.delete("/email", status_code=204, response_class=Response)
def remove_my_email(request: Request, user: CurrentUser, conn: sqlite3.Connection = Depends(get_db)) -> Response:
    """Remove the address. No email and no password needed: it only takes a way to reset away."""
    row = _address(conn, user.id)
    if row is not None and row["email"]:
        _void_email_links(conn, user.id)
        conn.execute("UPDATE users SET email = NULL, email_confirmed_at = NULL, updated_at = ? WHERE id = ?", (utcnow(), user.id))
        audit(conn, user.id, "email.removed", "user", user.id, ip=request_ip(request))
        conn.commit()
    return Response(status_code=204)


# --------------------------------------------------------------------------- #
# Public: confirm, forgot
# --------------------------------------------------------------------------- #


def _public_gate(request: Request, conn: sqlite3.Connection) -> tuple[AuthContext, str | None]:
    ctx = auth_context(request)
    if ctx.settings.auth_mode != "local" or not mailer(request).enabled:
        raise HTTPException(status_code=404, detail="Not Found")
    ensure_setup_done(conn, ctx)
    ip = request_ip(request)
    wait = ctx.throttle.ip_wait(ip)
    if wait:
        raise too_many(wait)
    return ctx, ip


@auth_router.post("/email/confirm")
def confirm_email(body: LinkInfoBody, request: Request, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """Confirm the address a link was sent to. A wrong, used or old link, or one for an address the person has changed since,
    is a 400 that counts as a per-IP failure. It does not sign anyone in."""
    ctx, ip = _public_gate(request, conn)
    token = _find_confirm_token(conn, body.token.get_secret_value())
    row = None
    if token is not None:
        row = conn.execute("SELECT id, username, status, auth_source, is_test_account, email FROM users WHERE id = ?",
                           (int(token["user_id"]),)).fetchone()
    if (token is None or row is None or row["status"] == "disabled" or row["auth_source"] != "local" or row["is_test_account"]
            or row["email"] != token["email"]):
        ctx.throttle.ip_failure(ip)
        raise ApiProblem(400, CONFIRM_INVALID, field="token")
    taken = conn.execute("SELECT 1 FROM users WHERE email = ? AND email_confirmed_at IS NOT NULL AND id != ?",
                         (token["email"], int(row["id"]))).fetchone()
    if taken is not None:
        raise ApiProblem(409, CONFIRM_TAKEN)
    cur = conn.execute("UPDATE email_tokens SET used_at = ? WHERE id = ? AND used_at IS NULL", (clock.now_iso(), token["id"]))
    if not cur.rowcount:
        conn.rollback()
        raise ApiProblem(400, CONFIRM_INVALID, field="token")
    try:
        conn.execute("UPDATE users SET email_confirmed_at = ?, updated_at = ? WHERE id = ? AND email = ?",
                     (clock.now_iso(), utcnow(), int(row["id"]), token["email"]))
    except sqlite3.IntegrityError:  # another account confirmed the same address a moment ago
        conn.rollback()
        raise ApiProblem(409, CONFIRM_TAKEN) from None
    conn.execute("DELETE FROM email_tokens WHERE user_id = ? AND id != ?", (int(row["id"]), token["id"]))
    audit(conn, int(row["id"]), "email.confirmed", "user", int(row["id"]), ip=ip)
    conn.commit()
    return {"ok": True, "username": row["username"]}


def _forgot_target(conn: sqlite3.Connection, username: str) -> tuple[sqlite3.Row, str] | None:
    norm = normalize_username(username)
    row = find_local_user(conn, norm) if valid_local_username(norm) else None
    if row is None or row["status"] != "active" or row["is_test_account"]:
        return None
    address = _address(conn, int(row["id"]))
    if address is None or not address["email"] or not address["email_confirmed_at"]:
        return None
    return row, str(address["email"])


@auth_router.post("/forgot", status_code=202)
def forgot_password(body: ForgotBody, request: Request, conn: sqlite3.Connection = Depends(get_db)) -> JSONResponse:
    """"Forgot your password?": the same 202 and words for every name (no account, no confirmed address, too many requests
    for that account, or a link on its way). 10 requests an hour per address answer 429; 3 an hour per account are kept
    silently."""
    ctx, ip = _public_gate(request, conn)
    if _oidc_only(request):
        raise ApiProblem(403, "This server signs people in with a sign-in provider only, so there is no password to reset.",
                         oidc_only=True)
    ctx.limits.take("forgot_ip", ip_key(ip))
    answer = JSONResponse({"detail": FORGOT_SENT}, status_code=202)
    norm = normalize_username(body.username)
    # Counted per typed name, whether or not it is an account, so the count reveals nothing either.
    if ctx.limits.window("forgot_account").hit(ctx.throttle.name_mac(norm).hex()):
        return answer
    found = _forgot_target(conn, body.username)
    if found is None:
        return answer
    row, address = found
    user_id = int(row["id"])
    tokens.void_reset_links(conn, user_id)
    token, _ = tokens.create_token(conn, tokens.RESET, ttl=timedelta(hours=mail.RESET_HOURS), user_id=user_id,
                                   created_by=user_id, note=RESET_NOTE)
    audit(conn, None, "user.reset_link_issued", "user", user_id, ip=ip, via="email")
    conn.commit()
    link = tokens.link(public_base(request, ctx.settings), "reset", token)
    mailer(request).send_later(mail.reset_letter(address, row["username"], _instance(conn, ctx), link))
    return answer


# --------------------------------------------------------------------------- #
# Admin: test email
# --------------------------------------------------------------------------- #


def about_view(request: Request) -> dict[str, Any]:
    """For ``GET /api/admin/about``: whether email is on and where it goes (never the password)."""
    e = mailer(request).env
    return {
        "enabled": server_on(request),
        "configured": bool(e.enabled),
        "host": e.host if e.enabled else None,
        "port": e.port if e.enabled else None,
        "security": e.security if e.enabled else None,
        "sender": e.sender if e.enabled else None,
        "login": bool(e.username and e.password) if e.enabled else False,
    }


@admin_router.post("/email/test")
def send_test_email(request: Request, admin: RecentAdmin, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """Send a test email to the admin's own confirmed address and wait for the mail server's answer."""
    ctx = auth_context(request)
    if not server_on(request):
        raise ApiProblem(409, EMAIL_OFF)
    row = _address(conn, admin.id)
    if row is None or not row["email"] or not row["email_confirmed_at"]:
        raise ApiProblem(409, ADMIN_NO_EMAIL)
    ctx.limits.take("email_confirm", admin.id)
    try:
        mailer(request).send(mail.test_letter(str(row["email"]), admin.username, _instance(conn, ctx)))
    except mail.MailFailed as exc:
        raise ApiProblem(502, f"The test email was not sent. {exc.message}", error=exc.kind) from None
    return {"sent": True, "to": row["email"]}
