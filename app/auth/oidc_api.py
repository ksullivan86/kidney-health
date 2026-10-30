"""Sign-in with an OpenID Connect provider: the routes and the account rules (design note 24 §3, §6 to §10).

Public (no session): ``GET /api/auth/oidc/start`` (a ``303`` to the provider), ``GET /api/auth/oidc/callback`` (where the provider
sends the browser back) and ``POST /api/auth/oidc/invite`` (an invite link redeemed with the provider). Signed in:
``POST /api/auth/reauth/oidc`` (confirm with the provider instead of the password), ``GET /api/me/oidc``, ``POST /api/me/oidc/link``
*(re-auth)* and ``DELETE /api/me/oidc/{id}`` *(re-auth)*. Every route answers 404 unless ``AUTH_MODE=local`` and ``OIDC_ENABLED``
(listing and unlinking still work while it is off, for a link left from before).

The callback never shows what the provider sent: it answers ``303`` to ``/`` (signed in) or to ``/#/oidc/<word>``, one of
:data:`app.auth.oidc.RESULTS`, which the page turns into a sentence (``js/views/oidc.js``). Tokens, codes, the state and the nonce
are never logged or stored.
"""
from __future__ import annotations

import logging
import re
import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse

from .. import brand
from ..audit import audit
from ..db import get_db, utcnow
from ..settings_registry import comma_list
from . import oidc, passkeys, sessions, tokens
from .accounts import begin_immediate, create_user, require_secure_enough, username_taken, would_remove_last_admin
from .context import AuthContext, auth_context, request_ip
from .deps import CurrentUser, RecentUser, current_user, ensure_setup_done, identify
from .errors import ApiProblem
from .models import USER_COLUMNS, clean_display, normalize_username, valid_local_username
from .ratelimit import register_limit
from .schemas import LinkInfoBody
from .throttle import ip_key

log = logging.getLogger(f"{brand.LOGGER_NAME}.auth.oidc")

router = APIRouter(prefix="/api/auth/oidc", tags=["auth"])
reauth_router = APIRouter(prefix="/api/auth/reauth", tags=["auth"])
me_router = APIRouter(prefix="/api/me/oidc", tags=["me"], dependencies=[Depends(current_user)])

register_limit("oidc_start", 30, 60, "Too many sign-in attempts. Wait a minute and try again.")

COOKIE_HTTPS = brand.OIDC_COOKIE_HOST
COOKIE_HTTP = brand.OIDC_COOKIE
LAST_WAY_IN = ("This is your only way to sign in. Add a passkey first, or ask your admin for a link to set a password, "
               "then remove this.")
ALREADY_LINKED = "Your account is already linked to this provider. Remove that link first to link another account."


# --------------------------------------------------------------------------- #
# Storage (oidc_links, schema step 26). Every query that a person can reach is scoped by user_id.
# --------------------------------------------------------------------------- #


def find_link(conn: sqlite3.Connection, issuer: str, subject: str) -> sqlite3.Row | None:
    """The link for a provider account (before anyone is known: the sign-in itself)."""
    return conn.execute("SELECT * FROM oidc_links WHERE issuer = ? AND subject = ?", (issuer, subject)).fetchone()


def links_for(conn: sqlite3.Connection, user_id: int) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM oidc_links WHERE user_id = ? ORDER BY id", (int(user_id),)).fetchall()


def link_for_issuer(conn: sqlite3.Connection, user_id: int, issuer: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM oidc_links WHERE user_id = ? AND issuer = ?", (int(user_id), issuer)).fetchone()


def add_link(conn: sqlite3.Connection, user_id: int, issuer: str, subject: str, email: str | None) -> int:
    now = utcnow()
    cur = conn.execute(
        "INSERT INTO oidc_links (user_id, issuer, subject, email, created_at, last_used_at) VALUES (?, ?, ?, ?, ?, ?)",
        (int(user_id), issuer, subject, email, now, now),
    )
    return int(cur.lastrowid)


def remove_all(conn: sqlite3.Connection, user_id: int) -> int:
    return int(conn.execute("DELETE FROM oidc_links WHERE user_id = ?", (int(user_id),)).rowcount or 0)


def counts(conn: sqlite3.Connection) -> dict[int, int]:
    return {int(r[0]): int(r[1]) for r in conn.execute("SELECT user_id, COUNT(*) FROM oidc_links GROUP BY user_id")}


def ways_in(conn: sqlite3.Connection, user_id: int) -> int:
    """How many ways this person can sign in: a password, each passkey, each link."""
    row = conn.execute("SELECT password_hash FROM users WHERE id = ?", (int(user_id),)).fetchone()
    password = 1 if row is not None and row["password_hash"] else 0
    keys = passkeys.count_for(conn, user_id)
    links = int(conn.execute("SELECT COUNT(*) FROM oidc_links WHERE user_id = ?", (int(user_id),)).fetchone()[0])
    return password + keys + links


def link_item(row: sqlite3.Row, issuer: str) -> dict[str, Any]:
    from urllib.parse import urlsplit

    return {"id": int(row["id"]), "provider": urlsplit(row["issuer"]).hostname or row["issuer"], "email": row["email"],
            "created_at": row["created_at"], "last_used_at": row["last_used_at"], "current": row["issuer"] == issuer}


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def client(request: Request) -> oidc.OidcClient | None:
    return getattr(request.app.state, "oidc", None)


def _on(request: Request) -> tuple[AuthContext, oidc.OidcClient]:
    ctx = auth_context(request)
    oc = client(request)
    if ctx.settings.auth_mode != "local" or oc is None or not oc.enabled:
        raise HTTPException(status_code=404, detail="Not Found")
    return ctx, oc


def label(conn: sqlite3.Connection, ctx: AuthContext) -> str:
    return str(ctx.store.get(conn, "auth.oidc.button_label"))


def status_view(request: Request, conn: sqlite3.Connection) -> dict[str, Any]:
    """``oidc`` in ``GET /api/auth/status``: whether the sign-in page shows the button, and its words (no issuer, no client ID)."""
    ctx = auth_context(request)
    oc = client(request)
    on = ctx.settings.auth_mode == "local" and oc is not None and oc.enabled
    return {"enabled": on, "label": label(conn, ctx) if on else None}


def about_view(request: Request) -> dict[str, Any]:
    """``oidc`` in ``GET /api/admin/about``: the connection without the secret (note 24 §10)."""
    s = auth_context(request).settings
    oc = client(request)
    o = s.oidc
    return {
        "enabled": bool(oc is not None and oc.enabled and s.auth_mode == "local"),
        "issuer": o.issuer if o.enabled else None,
        "client_id": o.client_id if o.enabled else None,
        "secret": "set" if o.secret_set else "not set",
        "scopes": o.scopes if o.enabled else None,
        "private_issuer_allowed": o.allow_private_issuer,
        "redirect_uri": oc.redirect_uri if oc is not None and oc.enabled else None,
        "discovery": (oc.last_error or "ok") if oc is not None and oc.enabled else None,
    }


def _set_binder(response: Response, request: Request, binder: str) -> None:
    https = sessions.is_https(request)
    response.set_cookie(COOKIE_HTTPS if https else COOKIE_HTTP, binder, max_age=oidc.FLOW_TTL_S, path="/", secure=https,
                        httponly=True, samesite="lax")
    response.headers["Cache-Control"] = "no-store"


def _read_binder(request: Request) -> str | None:
    return request.cookies.get(COOKIE_HTTPS if sessions.is_https(request) else COOKIE_HTTP)


def _clear_binder(response: Response, request: Request) -> None:
    https = sessions.is_https(request)
    response.delete_cookie(COOKIE_HTTPS if https else COOKIE_HTTP, path="/", secure=https, httponly=True, samesite="lax")


def _go(path: str) -> RedirectResponse:
    response = RedirectResponse(path, status_code=303)
    response.headers["Cache-Control"] = "no-store"
    return response


def _result(word: str) -> RedirectResponse:
    return _go(f"/#/oidc/{word}")


def _problem_word(exc: ApiProblem) -> str:
    if exc.status == 429:
        return "busy"
    if exc.extra.get("https_required"):
        return "https"
    return "failed"


class _Refused(oidc.OidcError):
    """A refusal about a known account: audited ``login.failed`` (``via: oidc``) after the rollback."""

    def __init__(self, result: str, reason: str, user_id: int) -> None:
        super().__init__(result, reason)
        self.user_id = user_id


def _begin(request: Request, oc: oidc.OidcClient, purpose: str, response: Response, **flow: Any) -> str:
    """Make a flow and set its cookie on ``response``; returns the provider's authorization URL."""
    meta = oc.metadata()
    state, binder, item = oc.flows.issue(purpose, **flow)
    _set_binder(response, request, binder)
    return oc.authorization_url(meta, state, item)


def _unavailable(exc: oidc.OidcError) -> ApiProblem:
    return ApiProblem(503, "The server could not reach the sign-in provider. Try again later.", reason=exc.reason)


# --------------------------------------------------------------------------- #
# Public routes
# --------------------------------------------------------------------------- #


@router.get("/start", status_code=303, response_class=RedirectResponse)
def start(request: Request, conn: sqlite3.Connection = Depends(get_db)) -> Response:
    """Go to the provider to sign in (a plain link on the sign-in page)."""
    ctx, oc = _on(request)
    ip = request_ip(request)
    try:
        ensure_setup_done(conn, ctx)
        if ctx.throttle.ip_wait(ip) or ctx.throttle.ip_attempt(ip):
            return _result("busy")
        ctx.limits.take("oidc_start", ip_key(ip))
        response = _go("/")
        response.headers["Location"] = _begin(request, oc, "signin", response)
        return response
    except oidc.OidcError as exc:
        return _result(exc.result)
    except ApiProblem as exc:
        return _result(_problem_word(exc))


@router.post("/invite")
def start_with_invite(body: LinkInfoBody, request: Request, response: Response, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """An invite link redeemed with the provider: ``{url}`` to go to; the account is made when the person comes back."""
    ctx, oc = _on(request)
    ensure_setup_done(conn, ctx)
    ip = request_ip(request)
    wait = ctx.throttle.ip_wait(ip)
    if wait:
        from .errors import too_many

        raise too_many(wait)
    invite = tokens.find_token(conn, body.token.get_secret_value(), tokens.INVITE)
    if invite is None:
        ctx.throttle.ip_failure(ip)
        raise ApiProblem(400, "This invite link is not valid any more. Ask your admin for a new one.", field="token")
    if str(ctx.store.get(conn, "registration.mode")) == "closed":
        raise ApiProblem(403, "Registration is closed on this server. Ask your admin to create an account for you.")
    require_secure_enough(conn, ctx.settings, request, adding_account=True)
    ctx.limits.take("oidc_start", ip_key(ip))
    try:
        return {"url": _begin(request, oc, "invite", response, invite_id=invite["id"])}
    except oidc.OidcError as exc:
        raise _unavailable(exc) from None


@router.get("/callback", response_class=RedirectResponse)
def callback(request: Request, conn: sqlite3.Connection = Depends(get_db), code: str | None = None, state: str | None = None,
             error: str | None = None, iss: str | None = None) -> Response:
    """Where the provider sends the browser back. Never reflects what the provider sent."""
    ctx, oc = _on(request)
    ip = request_ip(request)
    binder = _read_binder(request)
    try:
        if ctx.throttle.ip_wait(ip):
            raise oidc.OidcError("busy", "address_blocked")
        flow = oc.flows.take(state, binder)
        if flow is None:
            raise oidc.OidcError("expired", "unknown_state")
        if iss is not None and iss != oc.issuer:
            raise oidc.OidcError("failed", "bad_iss_parameter")
        if error is not None:
            word = re.sub(r"[^a-z_]", "", error.lower())[:40]
            raise oidc.OidcError("cancelled" if word in ("access_denied", "login_required", "consent_required") else "failed",
                                 f"provider_{word or 'error'}")
        meta = oc.metadata()
        token = oc.exchange(meta, code or "", flow)
        claims = oc.verify_id_token(meta, token, flow)
        del token
        response = _finish(request, conn, ctx, oc, flow, claims, ip)
    except oidc.OidcError as exc:
        conn.rollback()
        if exc.result != "cancelled":
            ctx.throttle.ip_failure(ip)
        user_id = getattr(exc, "user_id", None)
        if user_id is not None:
            audit(conn, None, "login.failed", "user", user_id, ip=ip, via="oidc", reason=exc.reason)
            conn.commit()
        log.info("sign-in with the provider refused: %s", exc.reason)
        response = _result(exc.result)
    except ApiProblem as exc:
        conn.rollback()
        ctx.throttle.ip_failure(ip)
        response = _result(_problem_word(exc))
    _clear_binder(response, request)
    return response


# --------------------------------------------------------------------------- #
# The account rules (note 24 §6)
# --------------------------------------------------------------------------- #


def _finish(request: Request, conn: sqlite3.Connection, ctx: AuthContext, oc: oidc.OidcClient, flow: oidc.Flow,
            claims: dict[str, Any], ip: str | None) -> Response:
    store = ctx.store
    if not oidc.domain_allowed(claims, comma_list(store.get(conn, "auth.oidc.allowed_domains"))):
        raise oidc.OidcError("domain", "domain_not_allowed")
    issuer, subject = oc.issuer, claims["sub"]
    email = oidc.any_email(claims)
    if flow.purpose in ("link", "reauth"):
        return _finish_signed_in(request, conn, ctx, oc, flow, issuer, subject, email, ip)

    link = find_link(conn, issuer, subject)
    if link is not None and flow.purpose == "invite":
        raise oidc.OidcError("taken", "invite_for_linked_account")
    if link is not None:
        user_id = int(link["user_id"])
        row = conn.execute(f"SELECT {USER_COLUMNS} FROM users WHERE id = ?", (user_id,)).fetchone()
        if row is None or row["status"] != "active" or row["auth_source"] != "local":
            raise _Refused("disabled", "account_not_active", user_id)
        try:
            require_secure_enough(conn, ctx.settings, request)
        except ApiProblem:
            raise _Refused("https", "https_required", user_id) from None
        conn.execute("UPDATE oidc_links SET last_used_at = ?, email = COALESCE(?, email) WHERE id = ?",
                     (utcnow(), email, int(link["id"])))
    elif flow.purpose == "invite":
        user_id = _create_from_invite(request, conn, ctx, flow, claims, issuer, subject, email, ip)
    else:
        user_id = _link_by_email(conn, ctx, claims, issuer, subject, ip)
        if user_id is None:
            if not store.get(conn, "auth.oidc.allow_signup"):
                raise oidc.OidcError("no_account", "unknown_subject")
            user_id = _create_by_signup(request, conn, ctx, claims, issuer, subject, email, ip)
    _sync_role(conn, ctx, user_id, claims, ip)
    response = _go("/")
    from .routes import start_session

    start_session(request, response, conn, ctx, user_id, signed_in_with="oidc")
    audit(conn, user_id, "login.succeeded", "user", user_id, ip=ip, via="oidc")
    conn.commit()
    return response


def _finish_signed_in(request: Request, conn: sqlite3.Connection, ctx: AuthContext, oc: oidc.OidcClient, flow: oidc.Flow,
                      issuer: str, subject: str, email: str | None, ip: str | None) -> Response:
    """Linking from Settings, or confirming with the provider: only in the session that started it."""
    user = identify(request, conn)
    info = getattr(request.state, "auth_session", None)
    if user is None or not user.is_active or info is None or info.id != flow.session_id or user.id != flow.user_id:
        raise oidc.OidcError("expired", "other_session")
    link = find_link(conn, issuer, subject)
    if flow.purpose == "reauth":
        if link is None or int(link["user_id"]) != user.id:
            raise _Refused("wrong_account", "reauth_other_account", user.id)
        sessions.mark_reauth(conn, info.id, user.id)
        conn.execute("UPDATE oidc_links SET last_used_at = ? WHERE id = ?", (utcnow(), int(link["id"])))
        conn.commit()
        return _result("confirmed")
    if link is not None and int(link["user_id"]) != user.id:
        raise oidc.OidcError("taken", "linked_to_another_account")
    if link is None:
        if link_for_issuer(conn, user.id, issuer) is not None:
            raise oidc.OidcError("taken", "already_linked")
        add_link(conn, user.id, issuer, subject, email)
        audit(conn, user.id, "oidc.linked", "user", user.id, ip=ip, via="settings")
        conn.commit()
    return _result("linked")


def _link_by_email(conn: sqlite3.Connection, ctx: AuthContext, claims: dict[str, Any], issuer: str, subject: str,
                   ip: str | None) -> int | None:
    """Note 24 §6 step 3: only with the switch on, a verified email, and an active non-admin account named by that email."""
    if not ctx.store.get(conn, "auth.oidc.link_by_email"):
        return None
    email = oidc.verified_email(claims)
    if email is None:
        return None
    row = conn.execute(f"SELECT {USER_COLUMNS} FROM users WHERE username_norm = ? AND auth_source = 'local'",
                       (normalize_username(email),)).fetchone()
    if row is None or row["status"] != "active" or row["role"] == "admin" or link_for_issuer(conn, int(row["id"]), issuer):
        return None
    user_id = int(row["id"])
    add_link(conn, user_id, issuer, subject, email)
    audit(conn, user_id, "oidc.linked", "user", user_id, ip=ip, via="email")
    return user_id


_NAME_CHARS = re.compile(r"[^a-z0-9._@+-]")


def pick_username(conn: sqlite3.Connection, claims: dict[str, Any]) -> str | None:
    """A free local username from the verified email or ``preferred_username`` (``-2`` to ``-9`` added when taken)."""
    candidates: list[str] = []
    email = oidc.verified_email(claims)
    if email:
        candidates.append(email)
    preferred = claims.get("preferred_username")
    if isinstance(preferred, str):
        candidates.append(preferred)
    if email:
        candidates.append(email.split("@", 1)[0])
    for raw in candidates:
        base = _NAME_CHARS.sub("", normalize_username(raw))[:60]
        for suffix in ("", *(f"-{n}" for n in range(2, 10))):
            name = base + suffix
            if valid_local_username(name) and not username_taken(conn, name):
                return name
    return None


def _new_account(conn: sqlite3.Connection, claims: dict[str, Any], role: str) -> int:
    name = pick_username(conn, claims)
    if name is None:
        raise oidc.OidcError("name", "no_free_username")
    display = clean_display(claims.get("name") if isinstance(claims.get("name"), str) else "")
    return create_user(conn, username=name, username_norm=name, display_name=display, role=role)


def _create_from_invite(request: Request, conn: sqlite3.Connection, ctx: AuthContext, flow: oidc.Flow, claims: dict[str, Any],
                        issuer: str, subject: str, email: str | None, ip: str | None) -> int:
    invite = conn.execute("SELECT * FROM auth_tokens WHERE id = ? AND purpose = 'invite' AND used_at IS NULL AND expires_at > ?",
                          (flow.invite_id, utcnow())).fetchone()
    if invite is None or str(ctx.store.get(conn, "registration.mode")) == "closed":
        raise oidc.OidcError("invite", "invite_not_valid")
    try:
        require_secure_enough(conn, ctx.settings, request, adding_account=True)
    except ApiProblem:
        raise oidc.OidcError("https", "https_required") from None
    role = invite["role"] or "user"
    user_id = _new_account(conn, claims, role)
    if not tokens.mark_used(conn, invite["id"]):
        raise oidc.OidcError("invite", "invite_just_used")
    add_link(conn, user_id, issuer, subject, email)
    audit(conn, user_id, "user.registered", "user", user_id, ip=ip, via="oidc_invite", invite_id=invite["id"], role=role)
    audit(conn, user_id, "oidc.linked", "user", user_id, ip=ip, via="invite")
    return user_id


def _create_by_signup(request: Request, conn: sqlite3.Connection, ctx: AuthContext, claims: dict[str, Any], issuer: str,
                      subject: str, email: str | None, ip: str | None) -> int:
    from .context import plain_http

    if plain_http(request):
        raise oidc.OidcError("https", "signup_needs_https")
    user_id = _new_account(conn, claims, "user")
    add_link(conn, user_id, issuer, subject, email)
    audit(conn, user_id, "user.registered", "user", user_id, ip=ip, via="oidc_signup", role="user")
    audit(conn, user_id, "oidc.linked", "user", user_id, ip=ip, via="signup")
    return user_id


def _sync_role(conn: sqlite3.Connection, ctx: AuthContext, user_id: int, claims: dict[str, Any], ip: str | None) -> None:
    """``auth.oidc.admin_groups`` (note 24 §4): with names set and a ``groups`` claim, the role follows the groups. The last active
    admin is never demoted. A change signs out the person's other sessions, as an admin's role change does."""
    names = set(comma_list(ctx.store.get(conn, "auth.oidc.admin_groups")))
    found = oidc.groups(claims)
    if not names or found is None:
        return
    row = conn.execute("SELECT role FROM users WHERE id = ?", (int(user_id),)).fetchone()
    wanted = "admin" if found & names else "user"
    if row is None or row["role"] == wanted:
        return
    if wanted == "user" and would_remove_last_admin(conn, user_id):
        log.warning("the provider's groups would demote the last admin (user %s); the role is kept", user_id)
        return
    conn.execute("UPDATE users SET role = ?, updated_at = ? WHERE id = ?", (wanted, utcnow(), int(user_id)))
    if wanted == "user":
        tokens.void_issued_by(conn, user_id)
    sessions.revoke_user_sessions(conn, user_id)
    audit(conn, None, "user.role_changed", "user", user_id, ip=ip, old=row["role"], new=wanted, via="oidc_groups")


# --------------------------------------------------------------------------- #
# Signed in: confirm with the provider, the person's links
# --------------------------------------------------------------------------- #


@reauth_router.post("/oidc")
def reauth_start(request: Request, response: Response, user: CurrentUser, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """Confirm with the provider instead of the password (note 24 §8): ``{url}``; the provider asks the person to sign in again."""
    ctx, oc = _on(request)
    info = getattr(request.state, "auth_session", None)
    if info is None or link_for_issuer(conn, user.id, oc.issuer) is None:
        raise ApiProblem(409, "Your account is not linked to the sign-in provider.")
    ctx.limits.take("oidc_start", f"user:{user.id}")
    try:
        return {"url": _begin(request, oc, "reauth", response, user_id=user.id, session_id=info.id)}
    except oidc.OidcError as exc:
        raise _unavailable(exc) from None


def _available(request: Request, user: Any) -> bool:
    return auth_context(request).settings.auth_mode == "local" and user.auth_source == "local"


@me_router.get("")
def my_links(request: Request, user: CurrentUser, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """``{available, enabled, label, links, can_link, has_password, passkeys}`` (never a subject or a token)."""
    ctx = auth_context(request)
    oc = client(request)
    on = ctx.settings.auth_mode == "local" and oc is not None and oc.enabled
    issuer = oc.issuer if on and oc is not None else ""
    rows = links_for(conn, user.id) if _available(request, user) else []
    row = conn.execute("SELECT password_hash FROM users WHERE id = ?", (user.id,)).fetchone()
    return {
        "available": _available(request, user),
        "enabled": on,
        "label": label(conn, ctx) if on else None,
        "links": [link_item(r, issuer) for r in rows],
        "can_link": on and _available(request, user) and not any(r["issuer"] == issuer for r in rows),
        "has_password": bool(row is not None and row["password_hash"]),
        "passkeys": passkeys.count_for(conn, user.id),
    }


@me_router.post("/link")
def link_start(request: Request, response: Response, user: RecentUser, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """Link the provider to this account *(re-auth)*: ``{url}``. The callback links only in this same session."""
    ctx, oc = _on(request)
    if not _available(request, user):
        raise HTTPException(status_code=404, detail="Not Found")
    if link_for_issuer(conn, user.id, oc.issuer) is not None:
        raise ApiProblem(409, ALREADY_LINKED)
    info = request.state.auth_session
    ctx.limits.take("oidc_start", f"user:{user.id}")
    try:
        return {"url": _begin(request, oc, "link", response, user_id=user.id, session_id=info.id)}
    except oidc.OidcError as exc:
        raise _unavailable(exc) from None


@me_router.delete("/{link_id}", status_code=204, response_class=Response)
def unlink(link_id: int, request: Request, user: RecentUser, conn: sqlite3.Connection = Depends(get_db)) -> Response:
    """Remove one of the person's links *(re-auth)*; never the last way in. Another person's id is 404."""
    if not _available(request, user):
        raise HTTPException(status_code=404, detail="Not Found")
    begin_immediate(conn)
    try:
        row = conn.execute("SELECT id FROM oidc_links WHERE id = ? AND user_id = ?", (int(link_id), user.id)).fetchone()
    except OverflowError:
        row = None
    if row is None:
        conn.rollback()
        raise HTTPException(status_code=404, detail="Not Found")
    if ways_in(conn, user.id) <= 1:
        conn.rollback()
        raise ApiProblem(409, LAST_WAY_IN)
    conn.execute("DELETE FROM oidc_links WHERE id = ? AND user_id = ?", (int(link_id), user.id))
    audit(conn, user.id, "oidc.unlinked", "user", user.id, ip=request_ip(request), via="self", count=1)
    conn.commit()
    return Response(status_code=204)
