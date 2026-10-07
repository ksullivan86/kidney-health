"""Provider credentials: write-only storage, resolution and quotas (note 07 §4.12).

* Stored keys are sealed with :class:`app.crypto.Keyring` (purpose ``"secret:<provider>"``, owner
  = ``owner_user_id`` or None for the shared key) in the ``secrets`` table; the API only ever shows
  ``{"set": true, "last4": "…"}`` (``last4`` only for keys of 20 characters or more) or
  ``{"set": true, "status": "unreadable"}`` when the key that encrypted it is gone.
* An operator key from the environment (``USDA_API_KEY[_FILE]``) is the shared key, **locked**:
  ``{"set": true, "source": "env", "locked": true}``.
* :func:`resolve` picks **own key → shared key (if allowed and the daily quota remains) → none**.
  A failing own key never falls back to the shared one.

The ``secrets`` and ``usage_daily`` tables are created by schema step 3 through
:func:`create_credentials_tables`. Every function takes ``user_id`` explicitly and never commits.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Literal

from .config import Settings
from .crypto import InvalidToken, Keyring
from .db import table_exists, utcnow
from .security import register_secret
from .settings_store import SettingsStore, default_store

log = logging.getLogger("kidney_health.credentials")

CREDENTIALS_DDL = """
CREATE TABLE IF NOT EXISTS secrets (
  id INTEGER PRIMARY KEY,
  scope TEXT NOT NULL CHECK (scope IN ('shared','user')),
  owner_user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
  provider TEXT NOT NULL,
  ciphertext BLOB NOT NULL,
  key_id TEXT NOT NULL,
  hints_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  updated_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
  CHECK ((scope = 'shared') = (owner_user_id IS NULL))
);
CREATE UNIQUE INDEX IF NOT EXISTS secrets_one_per_owner ON secrets(provider, ifnull(owner_user_id, 0));
CREATE TABLE IF NOT EXISTS usage_daily (
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  provider TEXT NOT NULL, key_scope TEXT NOT NULL CHECK (key_scope IN ('shared','own')),
  day TEXT NOT NULL, requests INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (user_id, provider, key_scope, day)
) WITHOUT ROWID;
"""


def create_credentials_tables(conn: sqlite3.Connection) -> None:
    """Create ``secrets`` and ``usage_daily`` (idempotent, transaction-safe). ``users`` must exist."""
    from .db import execute_script

    execute_script(conn, CREDENTIALS_DDL)


# --------------------------------------------------------------------------- #
# Providers
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Provider:
    slug: str
    label: str
    fields: tuple[str, ...] = ("api_key",)
    env_attr: str | None = None  # Settings attribute holding the operator's locked shared key
    settings_prefix: str | None = None  # "providers.<slug>" -> shared_enabled, user_keys_allowed, daily_limit_per_user
    tester: Callable[[dict[str, str]], str] | None = field(default=None, compare=False)

    @property
    def purpose(self) -> str:
        return f"secret:{self.slug}"


PROVIDERS: dict[str, Provider] = {}


def register_provider(provider: Provider) -> None:
    if provider.slug in PROVIDERS and PROVIDERS[provider.slug] != provider:
        raise ValueError(f"provider {provider.slug!r} is already registered")
    PROVIDERS[provider.slug] = provider


def get_provider(slug: str) -> Provider:
    try:
        return PROVIDERS[slug]
    except KeyError:
        raise KeyError(f"unknown provider {slug!r}") from None


# --------------------------------------------------------------------------- #
# Validation and hints
# --------------------------------------------------------------------------- #

LAST4_MIN_LENGTH = 20


class InvalidCredential(ValueError):
    """The submitted key is malformed. The message never contains the key."""


def validate_api_key(value: str) -> str:
    """8-512 printable ASCII characters, no whitespace (note 07 §4.12)."""
    if not isinstance(value, str):
        raise InvalidCredential("the key must be text")
    if not 8 <= len(value) <= 512:
        raise InvalidCredential("the key must be 8 to 512 characters long")
    if any(not (33 <= ord(c) <= 126) for c in value):
        raise InvalidCredential("the key must be printable ASCII without spaces")
    return value


def hints_for(fields: dict[str, str]) -> dict[str, str]:
    """Last four characters of each field, only for values of 20 characters or more."""
    return {k: v[-4:] for k, v in fields.items() if isinstance(v, str) and len(v) >= LAST4_MIN_LENGTH}


# --------------------------------------------------------------------------- #
# Stored secrets (caller commits)
# --------------------------------------------------------------------------- #


def _owner_clause(owner_user_id: int | None) -> tuple[str, tuple[Any, ...]]:
    if owner_user_id is None:
        return "owner_user_id IS NULL", ()
    return "owner_user_id = ?", (int(owner_user_id),)


def store_secret(
    conn: sqlite3.Connection,
    keyring: Keyring,
    provider: str,
    fields: dict[str, str],
    *,
    owner_user_id: int | None,
    updated_by: int | None = None,
) -> None:
    """Seal and upsert the shared (``owner_user_id=None``) or a person's key for ``provider``."""
    p = get_provider(provider)
    unknown = set(fields) - set(p.fields)
    if unknown or not fields:
        raise InvalidCredential(f"{provider} takes the fields {', '.join(p.fields)}")
    for value in fields.values():
        validate_api_key(value)
    token, key_id = keyring.seal(purpose=p.purpose, owner=owner_user_id, fields=fields)
    hints = json.dumps(hints_for(fields), separators=(",", ":"))
    now = utcnow()
    scope = "shared" if owner_user_id is None else "user"
    where, params = _owner_clause(owner_user_id)
    existing = conn.execute(f"SELECT id FROM secrets WHERE provider = ? AND {where}", (provider, *params)).fetchone()
    if existing is None:
        conn.execute(
            """INSERT INTO secrets (scope, owner_user_id, provider, ciphertext, key_id, hints_json, created_at, updated_at, updated_by)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (scope, owner_user_id, provider, token, key_id, hints, now, now, updated_by),
        )
    else:
        conn.execute(
            "UPDATE secrets SET ciphertext = ?, key_id = ?, hints_json = ?, updated_at = ?, updated_by = ? WHERE id = ?",
            (token, key_id, hints, now, updated_by, existing[0]),
        )
    for value in fields.values():
        register_secret(value)


def delete_secret(conn: sqlite3.Connection, provider: str, *, owner_user_id: int | None) -> bool:
    where, params = _owner_clause(owner_user_id)
    cur = conn.execute(f"DELETE FROM secrets WHERE provider = ? AND {where}", (provider, *params))
    return (cur.rowcount or 0) > 0


def _secret_row(conn: sqlite3.Connection, provider: str, owner_user_id: int | None) -> sqlite3.Row | tuple | None:
    if not table_exists(conn, "secrets"):
        return None
    where, params = _owner_clause(owner_user_id)
    return conn.execute(
        f"SELECT ciphertext, key_id, hints_json, updated_at FROM secrets WHERE provider = ? AND {where}",
        (provider, *params),
    ).fetchone()


def load_secret(conn: sqlite3.Connection, keyring: Keyring, provider: str, *, owner_user_id: int | None) -> dict[str, str] | None:
    """Decrypted fields, or None when not set. Raises ``InvalidToken`` when the row is unreadable."""
    row = _secret_row(conn, provider, owner_user_id)
    if row is None:
        return None
    fields = keyring.unseal(row[0], purpose=get_provider(provider).purpose, owner=owner_user_id)
    for value in fields.values():
        register_secret(value)
    return fields


def secret_status(conn: sqlite3.Connection, keyring: Keyring, provider: str, *, owner_user_id: int | None) -> dict[str, Any]:
    """Write-only view: ``{"set": false}``, ``{"set": true, "last4"?, "updated_at"}`` or ``{"set": true, "status": "unreadable"}``."""
    row = _secret_row(conn, provider, owner_user_id)
    if row is None:
        return {"set": False}
    try:
        keyring.unseal(row[0], purpose=get_provider(provider).purpose, owner=owner_user_id)
    except InvalidToken:
        return {"set": True, "status": "unreadable", "updated_at": row[3]}
    status: dict[str, Any] = {"set": True, "updated_at": row[3]}
    hints = json.loads(row[2] or "{}")
    if "api_key" in hints:
        status["last4"] = hints["api_key"]
    return status


def env_secret(settings: Settings, provider: str) -> str | None:
    p = get_provider(provider)
    return getattr(settings, p.env_attr, None) if p.env_attr else None


def shared_status(conn: sqlite3.Connection, keyring: Keyring, settings: Settings, provider: str) -> dict[str, Any]:
    """The shared key as the admin sees it; an env key is locked and has no last4."""
    if env_secret(settings, provider):
        return {"set": True, "source": "env", "locked": True}
    status = secret_status(conn, keyring, provider, owner_user_id=None)
    if status.get("set"):
        status.update(source="db", locked=False)
    return status


# --------------------------------------------------------------------------- #
# Resolution and quota
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Credential:
    provider: str
    scope: Literal["own", "shared"]
    source: Literal["user", "db", "env"]
    fields: dict[str, str] = field(repr=False)

    @property
    def api_key(self) -> str:
        return self.fields["api_key"]


@dataclass(frozen=True)
class Unavailable:
    provider: str
    reason: Literal["not_configured", "not_allowed", "quota_exhausted", "own_key_unreadable"]


def today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def take_quota(
    conn: sqlite3.Connection, user_id: int, provider: str, key_scope: Literal["shared", "own"], limit: int, *, day: str | None = None
) -> bool:
    """Count one request; False (and nothing counted) when ``limit`` (> 0) is already reached. 0 = unlimited."""
    day = day or today()
    if limit and limit > 0:
        cur = conn.execute(
            """INSERT INTO usage_daily (user_id, provider, key_scope, day, requests) VALUES (?, ?, ?, ?, 1)
               ON CONFLICT (user_id, provider, key_scope, day) DO UPDATE SET requests = requests + 1
               WHERE usage_daily.requests < ?""",
            (int(user_id), provider, key_scope, day, int(limit)),
        )
        return (cur.rowcount or 0) > 0
    conn.execute(
        """INSERT INTO usage_daily (user_id, provider, key_scope, day, requests) VALUES (?, ?, ?, ?, 1)
           ON CONFLICT (user_id, provider, key_scope, day) DO UPDATE SET requests = requests + 1""",
        (int(user_id), provider, key_scope, day),
    )
    return True


def used_today(conn: sqlite3.Connection, user_id: int, provider: str, key_scope: str = "shared", *, day: str | None = None) -> int:
    if not table_exists(conn, "usage_daily"):
        return 0
    row = conn.execute(
        "SELECT requests FROM usage_daily WHERE user_id = ? AND provider = ? AND key_scope = ? AND day = ?",
        (int(user_id), provider, key_scope, day or today()),
    ).fetchone()
    return int(row[0]) if row else 0


def _setting(store: SettingsStore, conn: sqlite3.Connection, p: Provider, name: str, default: Any) -> Any:
    if not p.settings_prefix:
        return default
    try:
        return store.get(conn, f"{p.settings_prefix}.{name}")
    except KeyError:
        return default


def resolve(
    conn: sqlite3.Connection,
    keyring: Keyring,
    settings: Settings,
    *,
    user_id: int,
    provider: str,
    can_use_shared: bool = True,
    store: SettingsStore | None = None,
    day: str | None = None,
) -> Credential | Unavailable:
    """Own key → shared key (allowed, and within today's quota) → :class:`Unavailable`.

    Counts the request in ``usage_daily`` (caller commits). A present but unreadable own key gives
    ``own_key_unreadable``: it never silently falls back to the shared key.
    """
    p = get_provider(provider)
    store = store or default_store()
    tables = table_exists(conn, "secrets") and table_exists(conn, "usage_daily")

    if tables and _setting(store, conn, p, "user_keys_allowed", True):
        try:
            own = load_secret(conn, keyring, provider, owner_user_id=user_id)
        except InvalidToken:
            return Unavailable(provider, "own_key_unreadable")
        if own:
            take_quota(conn, user_id, provider, "own", 0, day=day)
            return Credential(provider, "own", "user", own)

    shared: dict[str, str] | None = None
    source: Literal["db", "env"] = "env"
    env_key = env_secret(settings, provider)
    if env_key:
        shared = {"api_key": env_key}
    elif tables:
        try:
            shared = load_secret(conn, keyring, provider, owner_user_id=None)
        except InvalidToken:
            log.warning("the shared %s key cannot be decrypted with the current SECRET_KEY; set it again", provider)
            shared = None
        source = "db"
    if not shared:
        return Unavailable(provider, "not_configured")
    if not can_use_shared or not _setting(store, conn, p, "shared_enabled", True):
        return Unavailable(provider, "not_allowed")
    if not tables:
        return Credential(provider, "shared", source, shared)  # before schema v3: no accounts, no quota
    limit = int(_setting(store, conn, p, "daily_limit_per_user", 0) or 0)
    if not take_quota(conn, user_id, provider, "shared", limit, day=day):
        return Unavailable(provider, "quota_exhausted")
    return Credential(provider, "shared", source, shared)


# --------------------------------------------------------------------------- #
# USDA FoodData Central
# --------------------------------------------------------------------------- #


def check_usda_key(fields: dict[str, str]) -> str:
    """One cheap upstream call: ``"ok"``, ``"rejected"`` (401/403) or ``"unreachable"``."""
    import httpx2

    from .foods import usda_client

    try:
        with usda_client() as client:
            resp = client.get("/foods/search", params={"query": "apple", "pageSize": 1}, headers={"X-Api-Key": fields["api_key"]})
    except httpx2.HTTPError:
        return "unreachable"
    if resp.status_code in (401, 403):
        return "rejected"
    return "ok" if resp.status_code == 200 else "unreachable"


register_provider(
    Provider(
        slug="usda",
        label="USDA FoodData Central",
        fields=("api_key",),
        env_attr="usda_api_key",
        settings_prefix="providers.usda",
        tester=check_usda_key,
    )
)
