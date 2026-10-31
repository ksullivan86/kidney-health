"""Sign-in with an OpenID Connect provider: the routes and the account rules (design note 24 §3, §6 to §10).

Public (no session): ``GET /api/auth/oidc/start`` (a ``303`` to the provider), ``GET /api/auth/oidc/callback`` (where the first
provider sends the browser back; a named one uses ``…/callback/<name>``) and ``POST /api/auth/oidc/invite`` (an invite link redeemed
with the provider). Signed in: ``POST /api/auth/reauth/oidc`` (confirm with the provider instead of the password),
``GET /api/me/oidc``, ``POST /api/me/oidc/link`` *(re-auth)* and ``DELETE /api/me/oidc/{id}`` *(re-auth)*. Every route answers 404
unless ``AUTH_MODE=local`` and ``OIDC_ENABLED`` (listing and unlinking still work while it is off, for a link left from before).

Several providers (up to four, note 24 §13): the routes that start a flow take ``?provider=<id>`` (``default`` for the provider of
``OIDC_ISSUER``, else the name from ``OIDC_PROVIDERS``; left out, the first). A flow belongs to the provider it was started with,
and only that provider's way back can finish it; the ID token's ``iss`` must be that provider's issuer.

The callback never shows what the provider sent: it answers ``303`` to ``/`` (signed in) or to ``/#/oidc/<word>``, one of
:data:`app.auth.oidc.RESULTS`, which the page turns into a sentence (``js/views/oidc.js``). Tokens and the nonce are never logged
or stored; the code and the state of the callback's query string are redacted in the access log (``security._PATTERNS``).
"""
from __future__ import annotations

import logging
import re
import sqlite3
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, Response
from fastapi.responses import RedirectResponse

from .. import brand
from ..audit import audit
from ..db import get_db, utcnow
from ..config import OIDC_DEFAULT_ID
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
# Every start of a flow, whoever starts it: with the per-address cap of the flow store, a flood from many addresses cannot fill it.
register_limit("oidc_start_all", 300, 60, "Too many sign-ins started. Try again soon.")

COOKIE_HTTPS = brand.OIDC_COOKIE_HOST
COOKIE_HTTP = brand.OIDC_COOKIE
LAST_WAY_IN = ("This is your only way to sign in. Add another way first (a passkey, or a linked sign-in), or ask your admin "
               "for a link to set a password, then remove this.")
FLOWS_FULL = "Too many sign-ins started. Try again soon."
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


def link_item(row: sqlite3.Row, known: dict[str, tuple[str, str]]) -> dict[str, Any]:
    """One link for the person's list. ``known`` maps the issuer of each provider in use to ``(id, short label)``; ``current`` is
    whether this server still uses that provider."""
    from urllib.parse import urlsplit

    provider_id, name = known.get(row["issuer"], (None, None))
    return {"id": int(row["id"]), "provider": urlsplit(row["issuer"]).hostname or row["issuer"], "provider_id": provider_id,
            "name": name, "email": row["email"], "created_at": row["created_at"], "last_used_at": row["last_used_at"],
            "current": provider_id is not None}


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def providers(request: Request) -> list[oidc.OidcClient]:
    """The providers in use, in order (empty unless ``AUTH_MODE=local`` and ``OIDC_ENABLED``)."""
    if auth_context(request).settings.auth_mode != "local":
        return []
    found = getattr(request.app.state, "oidc_providers", None)
    if found is None:  # an app built without install() (a few tests): the one client, if any
        oc = getattr(request.app.state, "oidc", None)
        return [oc] if oc is not None and oc.enabled else []
    return [oc for oc in found.values() if oc.enabled]


def client(request: Request) -> oidc.OidcClient | None:
    """The first provider in use, or None."""
    found = providers(request)
    return found[0] if found else None


def _on(request: Request, provider: str | None = None) -> tuple[AuthContext, oidc.OidcClient]:
    """The context and the provider asked for (the first when ``provider`` is None); 404 when it is not in use."""
    ctx = auth_context(request)
    found = providers(request)
    oc = next((c for c in found if provider is None or c.id == provider), None)
    if oc is None:
        raise HTTPException(status_code=404, detail="Not Found")
    return ctx, oc


def only(request: Request) -> bool:
    """``OIDC_ONLY`` (note 24 §13): no password sign-in, while a provider is in use (start-up refuses it without one)."""
    return bool(auth_context(request).settings.oidc.only and providers(request))


# Each provider's rules: a named provider's own variable when set, else the server-wide setting (note 24 §13).
def label(conn: sqlite3.Connection, ctx: AuthContext, oc: oidc.OidcClient | None = None) -> str:
    if oc is not None and oc.env.button_label:
        return oc.env.button_label
    if oc is not None and oc.env.name:
        return f"Sign in with {oc.env.name.capitalize()}"
    return str(ctx.store.get(conn, "auth.oidc.button_label"))


def short_label(text: str) -> str:
    """The button's words without "Sign in with" (the provider's name, for lists and messages)."""
    m = re.match(r"(?i)^sign in with\s+(.+)$", text.strip())
    return m.group(1) if m else text.strip()


def allowed_domains(conn: sqlite3.Connection, ctx: AuthContext, oc: oidc.OidcClient) -> list[str]:
    raw = oc.env.allowed_domains if oc.env.allowed_domains is not None else ctx.store.get(conn, "auth.oidc.allowed_domains")
    return comma_list(raw)


def admin_groups(conn: sqlite3.Connection, ctx: AuthContext, oc: oidc.OidcClient) -> set[str]:
    raw = oc.env.admin_groups if oc.env.admin_groups is not None else ctx.store.get(conn, "auth.oidc.admin_groups")
    return set(comma_list(raw))


def allow_signup(conn: sqlite3.Connection, ctx: AuthContext, oc: oidc.OidcClient) -> bool:
    return bool(oc.env.allow_signup if oc.env.allow_signup is not None else ctx.store.get(conn, "auth.oidc.allow_signup"))


def _known(conn: sqlite3.Connection, ctx: AuthContext, found: list[oidc.OidcClient]) -> dict[str, tuple[str, str]]:
    return {oc.issuer: (oc.id, short_label(label(conn, ctx, oc))) for oc in found}


def _password_mode(request: Request, conn: sqlite3.Connection) -> str:
    """``on``; or with ``OIDC_ONLY`` ``off``, or ``test_accounts`` while the test accounts are on (they sign in with a password)."""
    if not only(request):
        return "on"
    from .. import test_accounts

    return "test_accounts" if auth_context(request).store.get(conn, test_accounts.SWITCH) else "off"


def status_view(request: Request, conn: sqlite3.Connection) -> dict[str, Any]:
    """``oidc`` in ``GET /api/auth/status``: whether the sign-in page shows buttons, their words (no issuer, no client ID), and
    whether the password form shows (``password``: ``on``, ``off`` or ``test_accounts``, note 24 §13). ``label`` is the first
    provider's words, as before several providers."""
    ctx = auth_context(request)
    found = providers(request)
    items = [{"id": oc.id, "label": label(conn, ctx, oc)} for oc in found]
    return {"enabled": bool(found), "label": items[0]["label"] if items else None, "providers": items,
            "only": only(request), "password": _password_mode(request, conn)}


def _about_one(oc: oidc.OidcClient, conn: sqlite3.Connection, ctx: AuthContext) -> dict[str, Any]:
    o = oc.env
    return {
        "id": oc.id,
        "label": label(conn, ctx, oc),
        "issuer": o.issuer,
        "client_id": o.client_id,
        "secret": "set" if o.secret_set else "not set",
        "scopes": o.scopes,
        "private_issuer_allowed": o.allow_private_issuer,
        "redirect_uri": oc.redirect_uri,
        "discovery": oc.discovery_state,
        "allowed_domains": ", ".join(allowed_domains(conn, ctx, oc)),
        "admin_groups": ", ".join(sorted(admin_groups(conn, ctx, oc))),
        "allow_signup": allow_signup(conn, ctx, oc),
        "flows_waiting": oc.flows.count(oc.id),
    }


def _admins_linked(conn: sqlite3.Connection, found: list[oidc.OidcClient]) -> int:
    issuers = {oc.issuer for oc in found}
    rows = conn.execute("SELECT DISTINCT l.user_id, l.issuer FROM oidc_links l JOIN users u ON u.id = l.user_id "
                        "WHERE u.role = 'admin' AND u.status = 'active'").fetchall()
    return len({int(r["user_id"]) for r in rows if r["issuer"] in issuers})


def about_view(request: Request, conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    """``oidc`` in ``GET /api/admin/about``: each provider's connection without its secret (note 24 §10, §13). The top-level
    fields describe the first provider, as before several providers; ``only`` is ``OIDC_ONLY`` and ``admins_linked`` how many
    active admins can sign in with a provider (with ``OIDC_ONLY``, none means nobody can reach Server administration after
    signing out)."""
    ctx = auth_context(request)
    s = ctx.settings
    found = providers(request)
    first = found[0] if found else None
    o = first.env if first is not None else s.oidc
    return {
        "enabled": first is not None,
        "issuer": o.issuer if first is not None else None,
        "client_id": o.client_id if first is not None else None,
        "secret": "set" if o.secret_set else "not set",
        "scopes": o.scopes if first is not None else None,
        "private_issuer_allowed": o.allow_private_issuer,
        "redirect_uri": first.redirect_uri if first is not None else None,
        "discovery": first.discovery_state if first is not None else None,
        "providers": [_about_one(oc, conn, ctx) for oc in found] if conn is not None else [],
        "only": bool(s.oidc.only and found),
        "admins_linked": _admins_linked(conn, found) if conn is not None and found else None,
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


def _result(word: str, oc: oidc.OidcClient | None = None) -> RedirectResponse:
    """``/#/oidc/<word>``, or ``/#/oidc/<word>/<name>`` for a named provider, so the page names the right one."""
    return _go(f"/#/oidc/{word}/{oc.env.name}" if oc is not None and oc.env.name else f"/#/oidc/{word}")


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


def _begin(request: Request, oc: oidc.OidcClient, purpose: str, response: Response, key: str, **flow: Any) -> str:
    """Make a flow with ``oc`` and set its cookie on ``response``; returns the provider's authorization URL. ``key`` is who
    started it (the address, or the person) for the flow store's per-key cap; :class:`oidc.FlowStoreFull` when the store, this
    provider's share of it or that key is full."""
    auth_context(request).limits.take("oidc_start_all", oc.id)
    meta = oc.metadata()
    state, binder, item = oc.flows.issue(purpose, key=key, provider=oc.id, **flow)
    _set_binder(response, request, binder)
    return oc.authorization_url(meta, state, item)


def _full() -> ApiProblem:
    return ApiProblem(503, FLOWS_FULL, headers={"Retry-After": "60"})


def _unavailable(exc: oidc.OidcError) -> ApiProblem:
    return ApiProblem(503, "The server could not reach the sign-in provider. Try again later.", reason=exc.reason)


# --------------------------------------------------------------------------- #
# Public routes
# --------------------------------------------------------------------------- #


ProviderId = Query(None, pattern=r"^[a-z][a-z0-9]{1,19}$", description="The provider: `default` for the one of OIDC_ISSUER, "
                   "else its name from OIDC_PROVIDERS. Left out: the first.")


@router.get("/start", status_code=303, response_class=RedirectResponse)
def start(request: Request, conn: sqlite3.Connection = Depends(get_db), provider: str | None = ProviderId) -> Response:
    """Go to the provider to sign in (a plain link on the sign-in page)."""
    ctx, oc = _on(request, provider)
    ip = request_ip(request)
    try:
        ensure_setup_done(conn, ctx)
        if ctx.throttle.ip_wait(ip) or ctx.throttle.ip_attempt(ip):
            return _result("busy", oc)
        ctx.limits.take("oidc_start", ip_key(ip))
        response = _go("/")
        response.headers["Location"] = _begin(request, oc, "signin", response, f"ip:{ip_key(ip)}")
        return response
    except oidc.FlowStoreFull:
        return _result("full", oc)
    except oidc.OidcError as exc:
        return _result(exc.result, oc)
    except ApiProblem as exc:
        return _result(_problem_word(exc), oc)


@router.post("/invite")
def start_with_invite(body: LinkInfoBody, request: Request, response: Response, conn: sqlite3.Connection = Depends(get_db),
                      provider: str | None = ProviderId) -> dict[str, Any]:
    """An invite link redeemed with the provider: ``{url}`` to go to; the account is made when the person comes back."""
    ctx, oc = _on(request, provider)
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
        return {"url": _begin(request, oc, "invite", response, f"ip:{ip_key(ip)}", invite_id=invite["id"])}
    except oidc.FlowStoreFull:
        raise _full() from None
    except oidc.OidcError as exc:
        raise _unavailable(exc) from None


@router.get("/callback", response_class=RedirectResponse)
def callback(request: Request, conn: sqlite3.Connection = Depends(get_db), code: str | None = None, state: str | None = None,
             error: str | None = None, iss: str | None = None) -> Response:
    """Where the first provider (``OIDC_ISSUER``) sends the browser back. Never reflects what the provider sent.

    Any web page can send a browser here with a made-up state, so an unknown state or a cookie that does not match counts as
    nothing: not a failed sign-in for the address, and the browser's cookie (perhaps for its own waiting sign-in) stays. Only a
    flow this browser really started, once taken, counts as a failure when it is refused, and only then is the cookie cleared."""
    return _callback(request, conn, OIDC_DEFAULT_ID, code, state, error, iss)


@router.get("/callback/{name}", response_class=RedirectResponse)
def callback_named(name: Annotated[str, Path(pattern=r"^[a-z][a-z0-9]{1,19}$")], request: Request,
                   conn: sqlite3.Connection = Depends(get_db), code: str | None = None, state: str | None = None,
                   error: str | None = None, iss: str | None = None) -> Response:
    """Where a named provider of ``OIDC_PROVIDERS`` sends the browser back (each has its own address). A flow started with
    another provider is not taken here: it stays waiting, as for an unknown state."""
    return _callback(request, conn, name, code, state, error, iss)


def _callback(request: Request, conn: sqlite3.Connection, provider: str, code: str | None, state: str | None, error: str | None,
              iss: str | None) -> Response:
    ctx, oc = _on(request, provider)
    ip = request_ip(request)
    binder = _read_binder(request)
    flow: oidc.Flow | None = None
    try:
        if ctx.throttle.ip_wait(ip):
            raise oidc.OidcError("busy", "address_blocked")
        flow = oc.flows.take(state, binder, oc.id)
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
        if flow is not None and exc.result != "cancelled":
            ctx.throttle.ip_failure(ip)
        user_id = getattr(exc, "user_id", None)
        if user_id is not None:
            audit(conn, None, "login.failed", "user", user_id, ip=ip, via="oidc", reason=exc.reason)
            conn.commit()
        log.info("sign-in with the provider refused: %s", exc.reason)
        response = _result(exc.result, oc)
    except ApiProblem as exc:
        conn.rollback()
        if flow is not None:
            ctx.throttle.ip_failure(ip)
        response = _result(_problem_word(exc), oc)
    if flow is not None:
        _clear_binder(response, request)
    return response


# --------------------------------------------------------------------------- #
# The account rules (note 24 §6)
# --------------------------------------------------------------------------- #


def _finish(request: Request, conn: sqlite3.Connection, ctx: AuthContext, oc: oidc.OidcClient, flow: oidc.Flow,
            claims: dict[str, Any], ip: str | None) -> Response:
    if not oidc.domain_allowed(claims, allowed_domains(conn, ctx, oc), oc.issuer):
        raise oidc.OidcError("domain", "domain_not_allowed")
    issuer, subject = oc.issuer, claims["sub"]
    email = oidc.any_email(claims)
    if flow.purpose in ("link", "reauth"):
        return _finish_signed_in(request, conn, ctx, oc, flow, issuer, subject, email, ip)

    link = find_link(conn, issuer, subject)
    linked_by_email = False
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
        user_id = _link_by_email(request, conn, ctx, claims, issuer, subject, ip)
        linked_by_email = user_id is not None
        if user_id is None:
            if not allow_signup(conn, ctx, oc):
                raise oidc.OidcError("no_account", "unknown_subject")
            user_id = _create_by_signup(request, conn, ctx, claims, issuer, subject, email, ip)
    # Never promote on the sign-in that linked by email (security review 2026-10-30): the next sign-in follows the groups.
    if not linked_by_email:
        _sync_role(conn, ctx, oc, user_id, claims, ip)
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
        return _result("confirmed", oc)
    if link is not None and int(link["user_id"]) != user.id:
        raise oidc.OidcError("taken", "linked_to_another_account")
    if link is None:
        if link_for_issuer(conn, user.id, issuer) is not None:
            raise oidc.OidcError("taken", "already_linked")
        add_link(conn, user.id, issuer, subject, email)
        audit(conn, user.id, "oidc.linked", "user", user.id, ip=ip, via="settings")
        conn.commit()
    return _result("linked", oc)


_ASCII_EMAIL = re.compile(r"^[a-z0-9._%+-]+@[a-z0-9.-]+$")


def _link_by_email(request: Request, conn: sqlite3.Connection, ctx: AuthContext, claims: dict[str, Any], issuer: str,
                   subject: str, ip: str | None) -> int | None:
    """Note 24 §6 step 3, as narrowed by the security review (2026-10-30): only with the switch on and a verified email, and only
    into an account an admin made in People that nobody has used yet: ``pending_setup``, not an admin, no password, no passkey, no
    link. Anyone who can register a username could otherwise sit on someone's address and receive their account (pre-hijacking).
    The email and the username are compared as plain lower-case ASCII, exactly: Unicode folding merges different mailboxes
    (``straße``/``strasse``, the Kelvin sign, fullwidth letters). The account is activated and its setup link voided."""
    if not ctx.store.get(conn, "auth.oidc.link_by_email"):
        return None
    raw = claims.get("email")
    email = oidc.verified_email(claims)
    # ASCII is checked on the address as the provider sent it: str.lower() turns the Kelvin sign into a plain "k".
    if email is None or not isinstance(raw, str) or not raw.strip().isascii() or not _ASCII_EMAIL.match(email):
        return None
    row = conn.execute(f"SELECT {USER_COLUMNS} FROM users WHERE username_norm = ? AND auth_source = 'local'", (email,)).fetchone()
    if (row is None or row["status"] != "pending_setup" or row["role"] == "admin" or row["password_hash"]
            or not str(row["username"]).isascii() or str(row["username"]).lower() != email):
        return None
    user_id = int(row["id"])
    if passkeys.count_for(conn, user_id) or links_for(conn, user_id):
        return None
    try:
        require_secure_enough(conn, ctx.settings, request, adding_account=True)
    except ApiProblem:
        raise _Refused("https", "https_required", user_id) from None
    conn.execute("UPDATE users SET status = 'active', updated_at = ? WHERE id = ? AND status = 'pending_setup'", (utcnow(), user_id))
    tokens.void_reset_links(conn, user_id)  # the admin's setup link for this account stops working
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


def _sync_role(conn: sqlite3.Connection, ctx: AuthContext, oc: oidc.OidcClient, user_id: int, claims: dict[str, Any],
               ip: str | None) -> None:
    """``auth.oidc.admin_groups``, or the provider's own ``OIDC_<NAME>_ADMIN_GROUPS`` (note 24 §4, §13): with names set and a
    ``groups`` claim, the role follows the groups of the provider just used. The last active admin is never demoted, and a test
    account never becomes an admin. A change signs out the person's other sessions, as an admin's role change does."""
    names = admin_groups(conn, ctx, oc)
    found = oidc.groups(claims)
    if not names or found is None:
        return
    row = conn.execute("SELECT role, is_test_account FROM users WHERE id = ?", (int(user_id),)).fetchone()
    wanted = "admin" if found & names else "user"
    if row is None or row["role"] == wanted:
        return
    if row["is_test_account"]:  # a test account is never an admin, whatever the provider says (design note 26)
        log.warning("the provider's groups would make test account %s an admin; ignored", user_id)
        return
    if wanted == "user" and would_remove_last_admin(conn, user_id):
        log.warning("the provider's groups would demote the last admin (user %s); the role is kept", user_id)
        return
    conn.execute("UPDATE users SET role = ?, updated_at = ? WHERE id = ?", (wanted, utcnow(), int(user_id)))
    if wanted == "user":
        tokens.void_issued_by(conn, user_id)
    sessions.revoke_user_sessions(conn, user_id)
    audit(conn, None, "user.role_changed", "user", user_id, ip=ip, old=row["role"], new=wanted, via="oidc_groups", provider=oc.id)


# --------------------------------------------------------------------------- #
# Signed in: confirm with the provider, the person's links
# --------------------------------------------------------------------------- #


@reauth_router.post("/oidc")
def reauth_start(request: Request, response: Response, user: CurrentUser, conn: sqlite3.Connection = Depends(get_db),
                 provider: str | None = ProviderId) -> dict[str, Any]:
    """Confirm with a provider instead of the password (note 24 §8): ``{url}``; the provider asks the person to sign in again.
    Without ``provider``, the first provider this person has linked."""
    if provider is None:
        mine = {r["issuer"] for r in links_for(conn, user.id)}
        provider = next((c.id for c in providers(request) if c.issuer in mine), None)
    ctx, oc = _on(request, provider)
    info = getattr(request.state, "auth_session", None)
    if info is None or link_for_issuer(conn, user.id, oc.issuer) is None:
        raise ApiProblem(409, "Your account is not linked to the sign-in provider.")
    ctx.limits.take("oidc_start", f"user:{user.id}")
    try:
        return {"url": _begin(request, oc, "reauth", response, f"user:{user.id}", user_id=user.id, session_id=info.id)}
    except oidc.FlowStoreFull:
        raise _full() from None
    except oidc.OidcError as exc:
        raise _unavailable(exc) from None


def _available(request: Request, user: Any) -> bool:
    return auth_context(request).settings.auth_mode == "local" and user.auth_source == "local"


@me_router.get("")
def my_links(request: Request, user: CurrentUser, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """``{available, enabled, label, providers, links, can_link, has_password, passkeys}`` (never a subject or a token).
    ``providers`` lists each provider in use with ``linked`` (this person has a link to it); ``can_link`` is whether any is
    left to link. ``label`` is the first provider's words."""
    ctx = auth_context(request)
    found = providers(request)
    available = _available(request, user)
    rows = links_for(conn, user.id) if available else []
    mine = {r["issuer"] for r in rows}
    row = conn.execute("SELECT password_hash FROM users WHERE id = ?", (user.id,)).fetchone()
    items = [{"id": oc.id, "label": label(conn, ctx, oc), "linked": oc.issuer in mine} for oc in found]
    return {
        "available": available,
        "enabled": bool(found),
        "label": items[0]["label"] if items else None,
        "providers": items,
        "links": [link_item(r, _known(conn, ctx, found)) for r in rows],
        "can_link": available and any(not item["linked"] for item in items),
        "has_password": bool(row is not None and row["password_hash"]),
        "passkeys": passkeys.count_for(conn, user.id),
    }


@me_router.post("/link")
def link_start(request: Request, response: Response, user: RecentUser, conn: sqlite3.Connection = Depends(get_db),
               provider: str | None = ProviderId) -> dict[str, Any]:
    """Link a provider to this account *(re-auth)*: ``{url}``. The callback links only in this same session."""
    ctx, oc = _on(request, provider)
    if not _available(request, user):
        raise HTTPException(status_code=404, detail="Not Found")
    if link_for_issuer(conn, user.id, oc.issuer) is not None:
        raise ApiProblem(409, ALREADY_LINKED)
    info = request.state.auth_session
    ctx.limits.take("oidc_start", f"user:{user.id}")
    try:
        return {"url": _begin(request, oc, "link", response, f"user:{user.id}", user_id=user.id, session_id=info.id)}
    except oidc.FlowStoreFull:
        raise _full() from None
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
