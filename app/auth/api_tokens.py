"""Assistant access tokens (schema step 10; ``docs/dev/plans/assistant-step1.md`` part A; ARCHITECTURE.md
"Assistant access tokens").

A person makes a token in Settings → Assistant access and gives it to a chat assistant they connect (the MCP
server of part B). A token is ``kha_`` + 43 base64url characters (32 random bytes). Only the SHA-256 of the
whole token is stored, as hex, with its first 12 characters for display. The plain token is in the answer to
``POST /api/me/tokens`` once and never again (secrets are write-only).

* **Where a token works.** Only on routes that depend on :data:`AssistantUser` (or call :func:`authenticate`).
  Every other route ignores the ``Authorization`` header: :func:`app.auth.deps.current_user` reads the
  session cookie (or the trusted proxy header) only.
* **When it works.** The instance switch ``assistant.enabled`` is on; the token is known, not revoked and not
  expired; it carries the scope the route needs; and its owner can use the app under the server's
  ``AUTH_MODE`` (active, not waiting for a password change). Every failure is the same ``401`` with
  ``WWW-Authenticate: Bearer``. A refused token counts toward the sign-in limit of the client address
  (:meth:`app.auth.throttle.Throttle.ip_failure`); a blocked address gets ``429`` with ``Retry-After``, as
  sign-in does. A request without a bearer token, or any request while the switch is off, is refused
  without counting: nothing was guessed and nothing is looked up.
* **Limits.** Expiry 30, 90 (default) or 365 days; at most :data:`MAX_ACTIVE` active tokens a person;
  ``last_used_at`` is written at most once a minute per token.
* **Revocation.** The person revokes one in Settings (``DELETE /api/me/tokens/{id}``); :func:`revoke_all`
  ends every token of a person when their password is changed or reset, when the account is disabled or
  deleted and when an admin uses ``POST /api/admin/users/{id}/revoke-tokens``. Revoked and expired tokens stay in the list for :data:`KEEP_ENDED_DAYS` days, then the daily
  housekeeping deletes them.

Functions never commit unless they say so; the routes commit.
"""
from __future__ import annotations

import hashlib
import re
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import timedelta
from typing import Annotated, Any, get_args

from fastapi import APIRouter, Depends, HTTPException, Path, Request, Response

from ..audit import audit
from ..db import get_db, table_exists
from . import clock, housekeeping
from .accounts import begin_immediate
from .context import AuthContext, auth_context, request_ip
from .deps import CurrentUser, RecentUser, _none_mode_user, current_user
from .errors import ApiProblem, too_many
from .models import User, clean_display, load_user
from .ratelimit import register_limit
from .schemas import TOKEN_NAME_MAX, ExpiryDays, TokenCreate

PREFIX = "kha_"
TOKEN_RE = re.compile(r"^kha_[A-Za-z0-9_-]{43}$")
DISPLAY_LENGTH = 12  # "kha_" and the first 8 random characters
READ = "assistant:read"
LOG = "assistant:log"  # also save food and recipes (part C); a token that has it always has READ too
SCOPES: tuple[str, ...] = (READ, LOG)  # known scopes, in the order they are stored and shown
EXPIRY_DAYS: tuple[int, ...] = tuple(get_args(ExpiryDays))
DEFAULT_EXPIRY_DAYS = 90
MAX_ACTIVE = 5
KEEP_ENDED_DAYS = 30
TOUCH_INTERVAL = timedelta(minutes=1)
SWITCH = "assistant.enabled"

CHALLENGE = 'Bearer realm="kidney-health"'
DENIED = "A valid assistant token is required (Settings → Assistant access)."
SWITCHED_OFF = "Assistant access is turned off on this server. Ask your admin to turn it on."

# Why every token of a person ended at once (the activity log's "reason"); "self" = revoked in Settings, "admin" =
# an admin used Server administration → People → Revoke assistant tokens.
REASONS = ("self", "password_changed", "password_reset", "account_disabled", "account_deleted", "admin")

# Making tokens: a person may make a few in a row while setting up, not a stream (each one is audited).
register_limit("api_tokens", 20, 3600, "Too many new tokens. Try again later.")

MAX_ROW_ID = 2**63 - 1


@dataclass(frozen=True)
class TokenInfo:
    """The token a request authenticated with (``request.state.api_token``), for rate limits and logs."""

    id: int
    user_id: int
    name: str
    scopes: tuple[str, ...]


# --------------------------------------------------------------------------- #
# Tokens
# --------------------------------------------------------------------------- #


def hash_token(token: str) -> str:
    """SHA-256 of the whole token, as 64 hex characters (what ``api_tokens.token_hash`` holds)."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def new_token() -> str:
    """``kha_`` + 43 base64url characters (32 random bytes)."""
    return PREFIX + secrets.token_urlsafe(32)


def parse_scopes(text: str | None) -> tuple[str, ...]:
    """The known scopes in a stored ``scopes`` text, in :data:`SCOPES` order. An unknown word grants nothing;
    ``assistant:log`` implies ``assistant:read``."""
    words = set((text or "").split())
    if LOG in words:
        words.add(READ)
    return tuple(s for s in SCOPES if s in words)


def scopes_for(can_log: bool) -> tuple[str, ...]:
    """The scopes of a new token: read, and also log (save food and recipes) when the person ticked it."""
    return (READ, LOG) if can_log else (READ,)


def is_enabled(conn: sqlite3.Connection, ctx: AuthContext) -> bool:
    """The instance switch ``assistant.enabled`` (env ``ASSISTANT_ENABLED`` wins)."""
    return bool(ctx.store.get(conn, SWITCH))


def clean_name(raw: str) -> str:
    """NFC, no control characters, single spaces, 1 to 60 characters; else ``400`` on the ``name`` field."""
    name = clean_display(" ".join((raw or "").split()), limit=TOKEN_NAME_MAX + 1)  # a tab or newline is a space
    if not name:
        raise ApiProblem(400, "Give the token a name, for example the app or device it is for.", field="name")
    if len(name) > TOKEN_NAME_MAX:
        raise ApiProblem(400, f"Use at most {TOKEN_NAME_MAX} characters for the name.", field="name")
    return name


def _state(row: sqlite3.Row | dict[str, Any], now: str) -> str:
    if row["revoked_at"]:
        return "revoked"
    return "expired" if row["expires_at"] <= now else "active"


def token_item(row: sqlite3.Row | dict[str, Any], now: str | None = None) -> dict[str, Any]:
    """What the person sees about a token: never the token or its hash."""
    return {
        "id": int(row["id"]),
        "name": row["name"],
        "prefix": row["prefix"],
        "scopes": list(parse_scopes(row["scopes"])),
        "created_at": row["created_at"],
        "last_used_at": row["last_used_at"],
        "expires_at": row["expires_at"],
        "revoked_at": row["revoked_at"],
        "state": _state(row, now or clock.now_iso()),
    }


_ITEM_COLUMNS = "id, name, prefix, scopes, created_at, last_used_at, expires_at, revoked_at"


def list_tokens(conn: sqlite3.Connection, user_id: int) -> list[dict[str, Any]]:
    """The person's tokens, newest first: active ones and those that ended in the last 30 days."""
    now = clock.now()
    cutoff = clock.iso(now - timedelta(days=KEEP_ENDED_DAYS))
    rows = conn.execute(
        f"""SELECT {_ITEM_COLUMNS} FROM api_tokens
            WHERE user_id = ? AND COALESCE(revoked_at, expires_at) > ? ORDER BY id DESC""",
        (int(user_id), cutoff),
    ).fetchall()
    stamp = clock.iso(now)
    return [token_item(r, stamp) for r in rows]


def active_count(conn: sqlite3.Connection, user_id: int) -> int:
    row = conn.execute(
        "SELECT COUNT(*) FROM api_tokens WHERE user_id = ? AND revoked_at IS NULL AND expires_at > ?",
        (int(user_id), clock.now_iso()),
    ).fetchone()
    return int(row[0])


def active_counts(conn: sqlite3.Connection) -> dict[int, int]:
    """How many active tokens each person has (people with none are not in the answer): Server administration
    shows the count next to "Revoke assistant tokens"."""
    rows = conn.execute(
        "SELECT user_id, COUNT(*) AS n FROM api_tokens WHERE revoked_at IS NULL AND expires_at > ? GROUP BY user_id",
        (clock.now_iso(),),
    ).fetchall()
    return {int(r["user_id"]): int(r["n"]) for r in rows}


def create(conn: sqlite3.Connection, user_id: int, name: str, days: int,
           scopes: tuple[str, ...] = (READ,)) -> tuple[str, dict[str, Any]]:
    """Insert a token; returns ``(token, item)``. The token is shown once and never stored."""
    if days not in EXPIRY_DAYS:
        raise ValueError(f"expiry must be one of {EXPIRY_DAYS}")
    if not scopes or any(s not in SCOPES for s in scopes):
        raise ValueError(f"scopes must be some of {SCOPES}")
    scopes = parse_scopes(" ".join(scopes))  # log implies read
    token = new_token()
    now = clock.now()
    row = {
        "name": name,
        "prefix": token[:DISPLAY_LENGTH],
        "scopes": " ".join(s for s in SCOPES if s in scopes),
        "created_at": clock.iso(now),
        "last_used_at": None,
        "expires_at": clock.iso(now + timedelta(days=days)),
        "revoked_at": None,
    }
    cur = conn.execute(
        """INSERT INTO api_tokens (user_id, name, token_hash, prefix, scopes, created_at, expires_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (int(user_id), name, hash_token(token), row["prefix"], row["scopes"], row["created_at"], row["expires_at"]),
    )
    row["id"] = int(cur.lastrowid or 0)
    return token, token_item(row, row["created_at"])


def revoke(conn: sqlite3.Connection, user_id: int, token_id: int) -> bool | None:
    """Revoke one of the person's tokens: True when it was active, False when it had ended already, None
    when the person has no such token (another person's id included)."""
    row = conn.execute("SELECT id FROM api_tokens WHERE id = ? AND user_id = ?", (int(token_id), int(user_id))).fetchone()
    if row is None:
        return None
    now = clock.now_iso()
    cur = conn.execute(
        "UPDATE api_tokens SET revoked_at = ? WHERE id = ? AND user_id = ? AND revoked_at IS NULL AND expires_at > ?",
        (now, int(token_id), int(user_id), now),
    )
    return (cur.rowcount or 0) > 0


def revoke_all(conn: sqlite3.Connection, user_id: int, *, reason: str, actor_id: int | None,
               ip: str | None = None) -> int:
    """Revoke every active token of ``user_id``; audit one ``api_token.revoked`` row when any was active.

    Called on a password change or reset and when the account is disabled or deleted (before the delete,
    whose cascade then removes the rows). Returns how many were revoked. A database without the table (the
    admin CLI on an old schema) has nothing to revoke."""
    if reason not in REASONS:
        raise ValueError(f"unknown reason {reason!r}")
    if not table_exists(conn, "api_tokens"):
        return 0
    now = clock.now_iso()
    cur = conn.execute(
        "UPDATE api_tokens SET revoked_at = ? WHERE user_id = ? AND revoked_at IS NULL AND expires_at > ?",
        (now, int(user_id), now),
    )
    count = int(cur.rowcount or 0)
    if count:
        audit(conn, actor_id, "api_token.revoked", "user", int(user_id), ip=ip, reason=reason, count=count)
    return count


def purge_ended(conn: sqlite3.Connection) -> int:
    """Delete tokens that were revoked or expired more than 30 days ago (commits). Returns how many."""
    if not table_exists(conn, "api_tokens"):
        return 0
    cutoff = clock.iso(clock.now() - timedelta(days=KEEP_ENDED_DAYS))
    cur = conn.execute("DELETE FROM api_tokens WHERE COALESCE(revoked_at, expires_at) <= ?", (cutoff,))
    conn.commit()
    return int(cur.rowcount or 0)


housekeeping.register_daily("api_tokens", lambda conn, ctx: purge_ended(conn))


# --------------------------------------------------------------------------- #
# The bearer dependency (the only place a token is accepted)
# --------------------------------------------------------------------------- #


def _bearer(request: Request) -> str | None:
    """The credential of ``Authorization: Bearer <credential>`` (maybe empty), or None for no bearer header."""
    header = request.headers.get("authorization")
    if not header:
        return None
    scheme, _, credential = header.strip().partition(" ")
    if scheme.lower() != "bearer":
        return None
    return credential.strip()


def _denied(presented: bool) -> ApiProblem:
    challenge = f'{CHALLENGE}, error="invalid_token"' if presented else CHALLENGE
    return ApiProblem(401, DENIED, headers={"WWW-Authenticate": challenge})


def _owner(conn: sqlite3.Connection, ctx: AuthContext, user_id: int) -> User | None:
    """The token's owner when they could use the app now under ``AUTH_MODE`` (as :func:`app.auth.deps.identify`)."""
    mode = ctx.settings.auth_mode
    if mode == "none":
        return _none_mode_user(conn) if int(user_id) == 1 else None
    user = load_user(conn, user_id)
    if user is None or not user.is_active or user.must_change_password:
        return None
    if user.auth_source != ("proxy" if mode == "proxy" else "local"):
        return None
    return user


def authenticate(request: Request, conn: sqlite3.Connection, scope: str = READ) -> User:
    """The person behind ``Authorization: Bearer kha_…`` when the token may be used for ``scope``.

    Sets ``request.state.user`` and ``request.state.api_token`` (:class:`TokenInfo`). Raises the generic
    401 (or 429 for a blocked address)."""
    if scope not in SCOPES:
        raise ValueError(f"unknown scope {scope!r}")
    ctx = auth_context(request)
    housekeeping.run(conn, ctx)
    presented = _bearer(request)
    if presented is None or not is_enabled(conn, ctx):
        raise _denied(presented is not None)
    ip = request_ip(request)
    wait = ctx.throttle.ip_wait(ip)
    if wait:
        raise too_many(wait)
    row = None
    if TOKEN_RE.fullmatch(presented):
        row = conn.execute(
            "SELECT id, user_id, name, scopes, last_used_at, expires_at, revoked_at FROM api_tokens WHERE token_hash = ?",
            (hash_token(presented),),
        ).fetchone()
    now = clock.now()
    user = None
    if row is not None and row["revoked_at"] is None and row["expires_at"] > clock.iso(now) \
            and scope in parse_scopes(row["scopes"]):
        user = _owner(conn, ctx, int(row["user_id"]))
    if user is None or row is None:
        ctx.throttle.ip_failure(ip)
        raise _denied(True)
    last = clock.parse(row["last_used_at"])
    if last is None or now - last >= TOUCH_INTERVAL:
        conn.execute("UPDATE api_tokens SET last_used_at = ? WHERE id = ?", (clock.iso(now), int(row["id"])))
        conn.commit()
    request.state.user = user
    request.state.api_token = TokenInfo(int(row["id"]), int(row["user_id"]), row["name"], parse_scopes(row["scopes"]))
    return user


def assistant_user(request: Request, conn: Annotated[sqlite3.Connection, Depends(get_db)]) -> User:
    """FastAPI dependency for the assistant surface (``/mcp``, part B): a token with ``assistant:read``."""
    return authenticate(request, conn, READ)


AssistantUser = Annotated[User, Depends(assistant_user)]


# --------------------------------------------------------------------------- #
# /api/me/tokens (cookie session + CSRF, like every /api/me route)
# --------------------------------------------------------------------------- #

router = APIRouter(prefix="/api/me/tokens", tags=["me"], dependencies=[Depends(current_user)])


@router.get("")
def read_my_tokens(request: Request, user: CurrentUser, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """The list works while the switch is off too, so a person can still see and revoke their tokens."""
    return {
        "enabled": is_enabled(conn, auth_context(request)),
        "max_active": MAX_ACTIVE,
        "expiry_days": list(EXPIRY_DAYS),
        "default_expiry_days": DEFAULT_EXPIRY_DAYS,
        "tokens": list_tokens(conn, user.id),
    }


@router.post("", status_code=201)
def create_my_token(body: TokenCreate, request: Request, user: RecentUser,
                    conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """A new token, in this answer only (``token``); needs a recent password, like saving a key. ``can_log``
    (default false) also lets it save food and recipes (``assistant:log``); the default is read-only."""
    ctx = auth_context(request)
    if not is_enabled(conn, ctx):
        raise ApiProblem(409, SWITCHED_OFF)
    name = clean_name(body.name)
    ctx.limits.take("api_tokens", f"user:{user.id}")
    begin_immediate(conn)  # the count and the insert see the same rows
    if active_count(conn, user.id) >= MAX_ACTIVE:
        conn.rollback()
        raise ApiProblem(400, f"You have {MAX_ACTIVE} active tokens, the most allowed. Revoke one first.")
    token, item = create(conn, user.id, name, body.expires_in_days, scopes_for(body.can_log))
    audit(conn, user.id, "api_token.created", "api_token", item["id"], ip=request_ip(request),
          expires_in_days=body.expires_in_days, scopes=item["scopes"])
    conn.commit()
    return {**item, "token": token}


@router.delete("/{token_id}", status_code=204, response_class=Response)
def revoke_my_token(token_id: Annotated[int, Path(ge=1, le=MAX_ROW_ID)], request: Request, user: CurrentUser,
                    conn: sqlite3.Connection = Depends(get_db)) -> Response:
    """Revoke at once (also while the switch is off). Another person's id is 404; an ended token is a no-op."""
    revoked = revoke(conn, user.id, token_id)
    if revoked is None:
        raise HTTPException(status_code=404, detail="token not found")
    if revoked:
        audit(conn, user.id, "api_token.revoked", "api_token", token_id, ip=request_ip(request), reason="self")
        conn.commit()
    return Response(status_code=204)
