"""Access tokens: assistant tokens (schema step 10; ``docs/dev/plans/assistant-step1.md`` part A; ARCHITECTURE.md
"Assistant access tokens") and device tokens (design note 12; ARCHITECTURE.md "Device tokens and /push/v1").

Two **families** share the ``api_tokens`` table, the hash-only storage, expiry, revocation and the generic 401:

* **assistant** (``kha_``, scopes ``assistant:read``, ``assistant:log`` and ``assistant:prefs``, instance switch
  ``assistant.enabled``): made in Settings → Assistant access and given to a chat assistant; accepted only at ``/mcp``.
  ``assistant:log`` lets it save food and recipes; ``assistant:prefs`` lets it remember a taste (``set_food_preference``).
  Each is a separate opt-in when the token is made: neither implies the other, and both imply only ``assistant:read``.
* **device** (``khd_``, the one scope ``body:write``, instance switch ``push.enabled``): made in Settings → Phone shortcuts
  and pasted into a phone shortcut; accepted only at ``POST /push/v1/body``, where it can add weights and blood pressure
  readings and read nothing. The scope of a device token is not the person's choice: it is always exactly ``body:write``.

A token is its prefix + 43 base64url characters (32 random bytes). Only the SHA-256 of the whole token is stored, as hex,
with its first 12 characters for display. The plain token is in the answer to ``POST /api/me/tokens`` once and never again
(secrets are write-only).

* **Families do not mix.** The family is decided by the scope the route asks for. Before any lookup,
  :func:`authenticate` checks that family's switch and that the presented token has that family's prefix pattern: a ``kha_``
  token at ``/push`` and a ``khd_`` token at ``/mcp`` are refused the same way as any wrong token (generic 401, counted
  toward the sign-in limit of the address). :func:`parse_scopes` never grants a scope of the other family, and a stored row
  that names scopes of both grants nothing.
* **Where a token works.** Only on routes that depend on :data:`AssistantUser` or call :func:`authenticate`. Every other
  route ignores the ``Authorization`` header: :func:`app.auth.deps.current_user` reads the session cookie (or the trusted
  proxy header) only.
* **When it works.** The family's instance switch is on; the token is known, not revoked and not expired; it carries the
  scope the route needs; and its owner can use the app under the server's ``AUTH_MODE`` (active, not waiting for a password
  change). Every failure is the same ``401`` with ``WWW-Authenticate: Bearer``. A refused token counts toward the sign-in
  limit of the client address (:meth:`app.auth.throttle.Throttle.ip_failure`); a blocked address gets ``429`` with
  ``Retry-After``, as sign-in does. A request without a bearer token, or any request while the family's switch is off, is
  refused without counting: nothing was guessed and nothing is looked up.
* **Limits.** Expiry 30, 90 (default) or 365 days; at most :data:`MAX_ACTIVE` active tokens a person **in each family**;
  ``last_used_at`` is written at most once a minute per token.
* **Revocation.** The person revokes one in Settings (``DELETE /api/me/tokens/{id}``); :func:`revoke_all` ends every token
  of a person, of both families, when their password is changed or reset, when the account is disabled or deleted and when
  an admin uses ``POST /api/admin/users/{id}/revoke-tokens``. Revoked and expired tokens stay in the list for
  :data:`KEEP_ENDED_DAYS` days, then the daily housekeeping deletes them.

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

from .. import brand, pairing
from ..audit import audit
from ..db import get_db, table_exists
from . import clock, housekeeping
from .accounts import begin_immediate
from .context import AuthContext, auth_context, public_base, request_ip
from .deps import CurrentUser, RecentUser, _none_mode_user, current_user
from .errors import ApiProblem, too_many
from .models import User, clean_display, load_user
from .ratelimit import register_limit
from .schemas import TOKEN_NAME_MAX, ExpiryDays, TokenCreate

ASSISTANT = "assistant"  # the families (module docstring)
DEVICE = "device"
FAMILIES: tuple[str, ...] = (ASSISTANT, DEVICE)

PREFIX = brand.ASSISTANT_TOKEN_PREFIX  # assistant tokens
DEVICE_PREFIX = brand.DEVICE_TOKEN_PREFIX  # device tokens ("d" for device)
TOKEN_RE = re.compile(rf"^{re.escape(PREFIX)}[A-Za-z0-9_-]{{43}}$")
DEVICE_TOKEN_RE = re.compile(rf"^{re.escape(DEVICE_PREFIX)}[A-Za-z0-9_-]{{43}}$")
DISPLAY_LENGTH = 12  # the 4-character prefix and the first 8 random characters
READ = "assistant:read"
LOG = "assistant:log"  # also save food and recipes (part C); a token that has it always has READ too
PREFS = "assistant:prefs"  # also remember a taste (set_food_preference, note 09 §4.8b); implies READ, never LOG
BODY_WRITE = "body:write"  # add weights and blood pressure readings at POST /push/v1/body, and nothing else
SCOPES: tuple[str, ...] = (READ, LOG, PREFS)  # the assistant family's scopes, in the order they are stored and shown
DEVICE_SCOPES: tuple[str, ...] = (BODY_WRITE,)  # the device family's: always exactly this one, never the person's choice
ALL_SCOPES: tuple[str, ...] = SCOPES + DEVICE_SCOPES
EXPIRY_DAYS: tuple[int, ...] = tuple(get_args(ExpiryDays))
DEFAULT_EXPIRY_DAYS = 90
MAX_ACTIVE = 5  # active tokens a person may hold in each family
KEEP_ENDED_DAYS = 30
TOUCH_INTERVAL = timedelta(minutes=1)
SWITCH = "assistant.enabled"  # the assistant family's instance switch (env ASSISTANT_ENABLED)
DEVICE_SWITCH = "push.enabled"  # the device family's (env PUSH_ENABLED)

CHALLENGE = f'Bearer realm="{brand.BEARER_REALM}"'
DENIED = "A valid assistant token is required (Settings → Assistant access)."
SWITCHED_OFF = "Assistant access is turned off on this server. Ask your admin to turn it on."
DEVICE_DENIED = "A valid device token is required (Settings → Phone shortcuts)."
DEVICE_SWITCHED_OFF = "Phone shortcuts are turned off on this server. Ask your admin to turn them on."

# Why every token of a person ended at once (the activity log's "reason"); "self" = revoked in Settings, "admin" =
# an admin used Server administration → People → Revoke tokens (it ends both families), "auth_mode_changed" = the
# sign-in mode (AUTH_MODE) was different at start-up, so every token of every person ended.
REASONS = ("self", "password_changed", "password_reset", "account_disabled", "account_deleted", "admin",
           "auth_mode_changed")

# Making tokens: a person may make a few in a row while setting up, not a stream (each one is audited).
register_limit("api_tokens", 20, 3600, "Too many new tokens. Try again later.")

MAX_ROW_ID = 2**63 - 1

# SQL for "this row is a device token": the scopes text holds the word body:write. A row that mixes the families is
# counted as a device row here and grants nothing (:func:`parse_scopes`), so it can never be used at either surface.
_IS_DEVICE_SQL = f"(' ' || scopes || ' ') LIKE '% {BODY_WRITE} %'"


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


def _family(family: str) -> str:
    if family not in FAMILIES:
        raise ValueError(f"family must be one of {FAMILIES}")
    return family


def new_token(family: str = ASSISTANT) -> str:
    """The family's prefix + 43 base64url characters (32 random bytes): ``kha_…`` or ``khd_…``."""
    return (DEVICE_PREFIX if _family(family) == DEVICE else PREFIX) + secrets.token_urlsafe(32)


def family_of_scope(scope: str) -> str:
    """The family a scope belongs to; ``ValueError`` for a scope no family has."""
    if scope in SCOPES:
        return ASSISTANT
    if scope in DEVICE_SCOPES:
        return DEVICE
    raise ValueError(f"unknown scope {scope!r}")


def family_of_scopes(scopes: str | tuple[str, ...] | list[str] | None) -> str:
    """The family of a stored ``scopes`` text (or a tuple of scopes): ``device`` when it holds ``body:write``, else
    ``assistant``. The same rule as the list filter's SQL."""
    words = scopes.split() if isinstance(scopes, str) or scopes is None else list(scopes)
    return DEVICE if BODY_WRITE in words else ASSISTANT


def parse_scopes(text: str | None) -> tuple[str, ...]:
    """The known scopes in a stored ``scopes`` text, in :data:`ALL_SCOPES` order. An unknown word grants nothing;
    ``assistant:log`` and ``assistant:prefs`` each imply ``assistant:read`` and nothing else implies anything (``log`` does
    not give ``prefs`` and ``prefs`` does not give ``log``; a device token never gains an assistant scope, an assistant token
    never gains ``body:write``); a text that names scopes of both families grants nothing."""
    known = {w for w in (text or "").split() if w in ALL_SCOPES}
    if LOG in known or PREFS in known:
        known.add(READ)
    if known.intersection(SCOPES) and known.intersection(DEVICE_SCOPES):
        return ()
    return tuple(s for s in ALL_SCOPES if s in known)


def scopes_for(can_log: bool, can_prefs: bool = False) -> tuple[str, ...]:
    """The scopes of a new assistant token: read, and also log (save food and recipes) and prefs (remember tastes) when the
    person ticked them. Two separate ticks: neither one gives the other."""
    return (READ, *((LOG,) if can_log else ()), *((PREFS,) if can_prefs else ()))


def is_enabled(conn: sqlite3.Connection, ctx: AuthContext, family: str = ASSISTANT) -> bool:
    """The family's instance switch: ``assistant.enabled`` (env ``ASSISTANT_ENABLED``) or ``push.enabled`` (env
    ``PUSH_ENABLED``)."""
    return bool(ctx.store.get(conn, DEVICE_SWITCH if _family(family) == DEVICE else SWITCH))


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


def _family_sql(family: str | None) -> str:
    """An ``AND …`` clause that keeps one family's rows (nothing for ``None``: both families)."""
    if family is None:
        return ""
    return f" AND {'' if _family(family) == DEVICE else 'NOT '}{_IS_DEVICE_SQL}"


def sent_counts(conn: sqlite3.Connection, user_id: int) -> dict[int, dict[str, int]]:
    """How many weights and blood pressure readings each of the person's device tokens sent and that are still in the log:
    ``{token_id: {"weights": n, "readings": n}}`` (tokens that sent none are not in the answer). The Settings block names the
    count before "Delete what it sent" (``DELETE /api/me/tokens/{id}/body-rows``)."""
    out: dict[int, dict[str, int]] = {}
    for key, table in (("weights", "weights"), ("readings", "blood_pressures")):
        rows = conn.execute(f"SELECT api_token_id, COUNT(*) AS n FROM {table} WHERE user_id = ? AND api_token_id IS NOT NULL "
                            "GROUP BY api_token_id", (int(user_id),))
        for r in rows:
            out.setdefault(int(r["api_token_id"]), {"weights": 0, "readings": 0})[key] = int(r["n"])
    return out


def list_tokens(conn: sqlite3.Connection, user_id: int, family: str | None = None) -> list[dict[str, Any]]:
    """The person's tokens, newest first: active ones and those that ended in the last 30 days. ``family`` keeps one
    family's tokens (the Settings blocks list one family each); ``None`` lists both. A device token's item also holds ``sent``,
    ``{weights, readings}``: how many rows it sent that are still in the log."""
    now = clock.now()
    cutoff = clock.iso(now - timedelta(days=KEEP_ENDED_DAYS))
    rows = conn.execute(
        f"""SELECT {_ITEM_COLUMNS} FROM api_tokens
            WHERE user_id = ? AND COALESCE(revoked_at, expires_at) > ?{_family_sql(family)} ORDER BY id DESC""",
        (int(user_id), cutoff),
    ).fetchall()
    stamp = clock.iso(now)
    items = [token_item(r, stamp) for r in rows]
    if family == DEVICE:
        sent = sent_counts(conn, user_id)
        for item in items:
            item["sent"] = sent.get(item["id"], {"weights": 0, "readings": 0})
    return items


def active_count(conn: sqlite3.Connection, user_id: int, family: str | None = None) -> int:
    """How many active tokens the person has, in one family or (``None``) in both."""
    row = conn.execute(
        f"SELECT COUNT(*) FROM api_tokens WHERE user_id = ? AND revoked_at IS NULL AND expires_at > ?{_family_sql(family)}",
        (int(user_id), clock.now_iso()),
    ).fetchone()
    return int(row[0])


def active_counts(conn: sqlite3.Connection, family: str | None = None) -> dict[int, int]:
    """How many active tokens each person has (people with none are not in the answer), in one family or (``None``) in
    both: Server administration shows the counts next to "Revoke tokens"."""
    rows = conn.execute(
        f"""SELECT user_id, COUNT(*) AS n FROM api_tokens WHERE revoked_at IS NULL AND expires_at > ?{_family_sql(family)}
            GROUP BY user_id""",
        (clock.now_iso(),),
    ).fetchall()
    return {int(r["user_id"]): int(r["n"]) for r in rows}


def create(conn: sqlite3.Connection, user_id: int, name: str, days: int,
           scopes: tuple[str, ...] = (READ,)) -> tuple[str, dict[str, Any]]:
    """Insert a token; returns ``(token, item)``. The token is shown once and never stored. The family follows the
    scopes: ``(BODY_WRITE,)`` makes a device token (``khd_``), assistant scopes an assistant token (``kha_``); scopes of both
    families are refused."""
    if days not in EXPIRY_DAYS:
        raise ValueError(f"expiry must be one of {EXPIRY_DAYS}")
    if not scopes or any(s not in ALL_SCOPES for s in scopes):
        raise ValueError(f"scopes must be some of {ALL_SCOPES}")
    scopes = parse_scopes(" ".join(scopes))  # log implies read
    if not scopes:
        raise ValueError("a token holds scopes of one family only")
    token = new_token(family_of_scopes(scopes))
    now = clock.now()
    row = {
        "name": name,
        "prefix": token[:DISPLAY_LENGTH],
        "scopes": " ".join(scopes),
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
    """Revoke every active token of ``user_id``, of both families; audit one ``api_token.revoked`` row when any was active.

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


def revoke_everyone(conn: sqlite3.Connection, *, reason: str) -> int:
    """Revoke every active token of every person, both families (no commit). One ``api_token.revoked`` row per
    person who had any, with no actor (the server did it at start-up). Returns how many tokens ended."""
    if not table_exists(conn, "api_tokens"):
        return 0
    now = clock.now_iso()
    ids = [int(r[0]) for r in conn.execute(
        "SELECT DISTINCT user_id FROM api_tokens WHERE revoked_at IS NULL AND expires_at > ? ORDER BY user_id", (now,)
    ).fetchall()]
    return sum(revoke_all(conn, uid, reason=reason, actor_id=None) for uid in ids)


def purge_ended(conn: sqlite3.Connection) -> int:
    """Delete tokens that were revoked or expired more than 30 days ago (commits). Returns how many. The rows a device token
    sent stay (``weights.api_token_id`` becomes NULL by ``ON DELETE SET NULL``); only their "from a shortcut (name)" label
    loses the name."""
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


def _denied(presented: bool, family: str = ASSISTANT) -> ApiProblem:
    challenge = f'{CHALLENGE}, error="invalid_token"' if presented else CHALLENGE
    return ApiProblem(401, DEVICE_DENIED if family == DEVICE else DENIED, headers={"WWW-Authenticate": challenge})


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
    """The person behind ``Authorization: Bearer kha_…`` (or ``khd_…``) when the token may be used for ``scope``.

    The scope names the family. In order, and before any lookup: a bearer header is there, the family's switch is on,
    the address is not blocked, and the token has the family's prefix pattern. Sets ``request.state.user`` and
    ``request.state.api_token`` (:class:`TokenInfo`). Raises the generic 401 (or 429 for a blocked address)."""
    family = family_of_scope(scope)  # ValueError for a scope no family has
    ctx = auth_context(request)
    housekeeping.run(conn, ctx)
    presented = _bearer(request)
    if presented is None or not is_enabled(conn, ctx, family):
        raise _denied(presented is not None, family)
    ip = request_ip(request)
    wait = ctx.throttle.ip_wait(ip)
    if wait:
        raise too_many(wait)
    row = None
    if (DEVICE_TOKEN_RE if family == DEVICE else TOKEN_RE).fullmatch(presented):
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
        raise _denied(True, family)
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


def device_user(request: Request, conn: Annotated[sqlite3.Connection, Depends(get_db)]) -> User:
    """FastAPI dependency for the device surface (``POST /push/v1/body``, :mod:`app.push`): a token with ``body:write``."""
    return authenticate(request, conn, BODY_WRITE)


DeviceUser = Annotated[User, Depends(device_user)]


# --------------------------------------------------------------------------- #
# /api/me/tokens (cookie session + CSRF, like every /api/me route)
# --------------------------------------------------------------------------- #

router = APIRouter(prefix="/api/me/tokens", tags=["me"], dependencies=[Depends(current_user)])


def _family_param(family: str) -> str:
    if family not in FAMILIES:
        raise ApiProblem(400, f"family must be one of: {', '.join(FAMILIES)}.", field="family")
    return family


@router.get("")
def read_my_tokens(request: Request, user: CurrentUser, conn: sqlite3.Connection = Depends(get_db),
                   family: str = ASSISTANT) -> dict[str, Any]:
    """One family's tokens (``?family=assistant`` by default, or ``device``). The list works while the family's switch is
    off too, so a person can still see and revoke their tokens."""
    family = _family_param(family)
    return {
        "family": family,
        "enabled": is_enabled(conn, auth_context(request), family),
        "max_active": MAX_ACTIVE,
        "expiry_days": list(EXPIRY_DAYS),
        "default_expiry_days": DEFAULT_EXPIRY_DAYS,
        "tokens": list_tokens(conn, user.id, family),
    }


@router.post("", status_code=201)
def create_my_token(body: TokenCreate, request: Request, user: RecentUser,
                    conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """A new token, in this answer only (``token``); needs a recent password, like saving a key. ``family`` is
    ``assistant`` (default) or ``device``. An assistant token is read-only unless ``can_log`` (default false) also lets it
    save food and recipes (``assistant:log``) and ``can_prefs`` (default false) lets it remember tastes (``assistant:prefs``).
    A device token's scopes are always exactly ``["body:write"]``: the request cannot choose them (``can_log`` and
    ``can_prefs`` are refused for it). A device token's answer also has ``pair_url``, the link the QR code for the iPhone app
    holds (:mod:`app.pairing`), or null when this server's address is not ``https://`` and a host."""
    ctx = auth_context(request)
    family = body.family
    for field, ticked in (("can_log", body.can_log), ("can_prefs", body.can_prefs)):
        if family == DEVICE and ticked:
            raise ApiProblem(400, "A device token can only add weights and blood pressure readings; there is nothing to choose.",
                             field=field)
    if not is_enabled(conn, ctx, family):
        raise ApiProblem(409, DEVICE_SWITCHED_OFF if family == DEVICE else SWITCHED_OFF)
    name = clean_name(body.name)
    ctx.limits.take("api_tokens", f"user:{user.id}")
    begin_immediate(conn)  # the count and the insert see the same rows
    if active_count(conn, user.id, family) >= MAX_ACTIVE:
        conn.rollback()
        raise ApiProblem(400, f"You have {MAX_ACTIVE} active tokens, the most allowed. Revoke one first.")
    scopes = DEVICE_SCOPES if family == DEVICE else scopes_for(body.can_log, body.can_prefs)
    token, item = create(conn, user.id, name, body.expires_in_days, scopes)
    if family == DEVICE:
        item["sent"] = {"weights": 0, "readings": 0}
    audit(conn, user.id, "api_token.created", "api_token", item["id"], ip=request_ip(request),
          expires_in_days=body.expires_in_days, scopes=item["scopes"], family=family)
    conn.commit()
    if family == DEVICE:
        return {**item, "token": token, "pair_url": pairing.link(public_base(request, ctx.settings), token)}
    return {**item, "token": token}


@router.delete("/{token_id}", status_code=204, response_class=Response)
def revoke_my_token(token_id: Annotated[int, Path(ge=1, le=MAX_ROW_ID)], request: Request, user: CurrentUser,
                    conn: sqlite3.Connection = Depends(get_db)) -> Response:
    """Revoke at once (also while the switch is off). Another person's id is 404; an ended token is a no-op."""
    row = conn.execute("SELECT scopes FROM api_tokens WHERE id = ? AND user_id = ?", (token_id, user.id)).fetchone()
    revoked = revoke(conn, user.id, token_id)
    if revoked is None or row is None:
        raise HTTPException(status_code=404, detail="token not found")
    if revoked:  # the family says which Settings block the activity row belongs to ("Phone shortcut token revoked")
        audit(conn, user.id, "api_token.revoked", "api_token", token_id, ip=request_ip(request), reason="self",
              family=family_of_scopes(row["scopes"]))
        conn.commit()
    return Response(status_code=204)
