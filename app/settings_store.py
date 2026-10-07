"""Reading and writing runtime settings (note 07 §4.11).

Precedence of :meth:`SettingsStore.effective` for ``(key, user_id)``:

1. the key's env var is set → that value, ``source="env"``, **locked**;
2. scope ``user``/``user_default`` and the person has a row → their value, ``source="user"``;
3. an ``instance_settings`` row → that value, ``source="instance"``;
4. the registry default, ``source="default"``.

Values are validated with the key's type on write **and** on read: a bad stored value (a hand-edited
database) is skipped with a warning and the next layer applies, so it can never crash a request.

Settings are cached per process and per database file. Every write bumps ``meta.settings_version``
in the same transaction, and every read compares it, so a write from another process (the admin
CLI) or a rolled-back write can never leave a stale cache. Store functions never commit: the caller
commits together with its audit row.

The two tables are created by schema step 3 (``app/migrations/m003_accounts.py``) through
:func:`create_settings_tables`; until then reads fall back to env and defaults and writes raise
:class:`SettingsUnavailable`.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
from dataclasses import dataclass
from typing import Any, Literal, Mapping

from pydantic import ValidationError

from . import settings_registry as registry
from .config import ConfigError
from .db import database_file, utcnow
from .settings_registry import SettingDef

log = logging.getLogger("kidney_health.settings")

Source = Literal["env", "user", "instance", "default"]
SETTINGS_VERSION_KEY = "settings_version"

# Schema v3 (note 07 §4.4). Called by m003; ``users`` must exist when foreign keys are enforced.
SETTINGS_TABLES_DDL = """
CREATE TABLE IF NOT EXISTS instance_settings (
  key TEXT PRIMARY KEY, value_json TEXT NOT NULL,
  updated_at TEXT NOT NULL, updated_by INTEGER REFERENCES users(id) ON DELETE SET NULL
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS user_settings (
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  key TEXT NOT NULL, value_json TEXT NOT NULL, updated_at TEXT NOT NULL,
  PRIMARY KEY (user_id, key)
) WITHOUT ROWID;
"""


def create_settings_tables(conn: sqlite3.Connection) -> None:
    """Create ``instance_settings`` and ``user_settings`` (idempotent; stays inside the current transaction)."""
    from .db import execute_script

    execute_script(conn, SETTINGS_TABLES_DDL)


class SettingsUnavailable(RuntimeError):
    """The settings tables do not exist yet (database below schema v3)."""


class SettingLocked(PermissionError):
    """The key is locked by its environment variable."""

    def __init__(self, key: str, env: str):
        super().__init__(f"{key} is set by the server ({env})")
        self.key = key
        self.env = env


class SettingNotEditable(PermissionError):
    """The key cannot be written at this level (e.g. a user writing an instance key)."""


class InvalidSettingValue(ValueError):
    """The value does not match the key's type. The message never contains the value."""

    def __init__(self, key: str, error: ValidationError | Exception):
        if isinstance(error, ValidationError):
            reasons = "; ".join(str(e.get("msg", "invalid")) for e in error.errors(include_input=False))
        else:
            reasons = "invalid value"
        super().__init__(f"{key}: {reasons}")
        self.key = key


@dataclass(frozen=True)
class Effective:
    key: str
    value: Any
    source: Source
    locked: bool
    env: str | None = None

    def as_user_item(self, definition: SettingDef) -> dict[str, Any]:
        return {
            "value": definition.to_python_json(self.value),
            "source": self.source,
            "editable": definition.user_editable and not self.locked,
        }

    def as_admin_item(self, definition: SettingDef) -> dict[str, Any]:
        return {
            "value": definition.to_python_json(self.value),
            "source": self.source,
            "locked_by_env": self.env if self.locked else None,
            "scope": definition.scope,
        }


@dataclass
class _Snapshot:
    version: str | None
    instance: dict[str, str]
    users: dict[int, dict[str, str]]


class SettingsStore:
    """Effective settings for a database, with env locks from ``env`` (default ``os.environ``)."""

    def __init__(self, env: Mapping[str, str] | None = None, defs: Mapping[str, SettingDef] | None = None):
        self._env = env
        self._defs = defs
        self._lock = threading.Lock()
        self._cache: dict[str, _Snapshot] = {}
        self._env_values: dict[str, Any] = {}

    # ------------------------------------------------------------------ registry and env
    @property
    def env(self) -> Mapping[str, str]:
        return os.environ if self._env is None else self._env

    def definition(self, key: str) -> SettingDef:
        if self._defs is not None:
            try:
                return self._defs[key]
            except KeyError:
                raise KeyError(f"unknown setting {key!r}") from None
        return registry.get(key)

    def definitions(self) -> list[SettingDef]:
        if self._defs is not None:
            return sorted(self._defs.values(), key=lambda d: d.key)
        return registry.all_settings()

    def env_value(self, definition: SettingDef) -> tuple[bool, Any]:
        """``(True, value)`` when the key's env lock is set; raises :class:`ConfigError` if it is invalid."""
        if not definition.env:
            return False, None
        raw = self.env.get(definition.env)
        if raw is None or raw.strip() == "":
            return False, None
        cache_key = f"{definition.key}\0{raw}"
        with self._lock:
            if cache_key in self._env_values:
                return True, self._env_values[cache_key]
        try:
            value = definition.from_env(raw.strip())
        except (ValidationError, ValueError) as exc:
            reason = exc.errors(include_input=False)[0]["msg"] if isinstance(exc, ValidationError) else "invalid value"
            raise ConfigError(f"{definition.env} (setting {definition.key}) is invalid: {reason}.") from None
        with self._lock:
            self._env_values[cache_key] = value
        return True, value

    def validate_env_locks(self) -> list[str]:
        """Parse every env lock now (start-up), so a typo fails loudly. Returns the locked keys."""
        return [d.key for d in self.definitions() if self.env_value(d)[0]]

    # ------------------------------------------------------------------ cache
    def invalidate(self) -> None:
        with self._lock:
            self._cache.clear()
            self._env_values.clear()

    @staticmethod
    def tables_exist(conn: sqlite3.Connection) -> bool:
        rows = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name IN ('instance_settings', 'user_settings')"
        ).fetchone()
        return rows[0] == 2

    @staticmethod
    def _version(conn: sqlite3.Connection) -> str | None:
        try:
            row = conn.execute("SELECT value FROM meta WHERE key = ?", (SETTINGS_VERSION_KEY,)).fetchone()
        except sqlite3.OperationalError:
            return None
        return "0" if row is None else str(row[0])

    def _snapshot(self, conn: sqlite3.Connection) -> _Snapshot | None:
        if not self.tables_exist(conn):
            return None
        version = self._version(conn)  # read before the rows: a concurrent write only causes a reload
        db_key = database_file(conn)
        with self._lock:
            cached = self._cache.get(db_key) if db_key else None
            if cached is not None and cached.version == version and version is not None:
                return cached
        instance = {r[0]: r[1] for r in conn.execute("SELECT key, value_json FROM instance_settings")}
        snap = _Snapshot(version=version, instance=instance, users={})
        if db_key and version is not None:
            with self._lock:
                self._cache[db_key] = snap
        return snap

    def _user_rows(self, conn: sqlite3.Connection, snap: _Snapshot, user_id: int) -> dict[str, str]:
        with self._lock:
            rows = snap.users.get(user_id)
        if rows is None:
            rows = {
                r[0]: r[1]
                for r in conn.execute("SELECT key, value_json FROM user_settings WHERE user_id = ?", (user_id,))
            }
            with self._lock:
                if len(snap.users) > 1000:
                    snap.users.clear()
                snap.users[user_id] = rows
        return rows

    def _bump(self, conn: sqlite3.Connection) -> None:
        current = self._version(conn)
        try:
            new = str(int(current or "0") + 1)
        except ValueError:
            new = "1"
        conn.execute(
            "INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (SETTINGS_VERSION_KEY, new),
        )
        db_key = database_file(conn)
        with self._lock:
            self._cache.pop(db_key, None)

    # ------------------------------------------------------------------ reads
    def _decode(self, definition: SettingDef, text: str, where: str) -> tuple[bool, Any]:
        try:
            return True, definition.from_json(text)
        except (ValidationError, ValueError):
            log.warning("ignoring an invalid stored value for setting %s (%s); using the next level", definition.key, where)
            return False, None

    def effective(self, conn: sqlite3.Connection, key: str, user_id: int | None = None) -> Effective:
        """The value that applies to ``user_id`` (or to the instance when None), with its source."""
        definition = self.definition(key)
        locked, value = self.env_value(definition)
        if locked:
            return Effective(key, value, "env", True, definition.env)
        snap = self._snapshot(conn)
        if snap is not None:
            if user_id is not None and definition.user_editable:
                text = self._user_rows(conn, snap, int(user_id)).get(key)
                if text is not None:
                    ok, value = self._decode(definition, text, f"user {int(user_id)}")
                    if ok:
                        return Effective(key, value, "user", False, definition.env)
            text = snap.instance.get(key)
            if text is not None:
                ok, value = self._decode(definition, text, "instance")
                if ok:
                    return Effective(key, value, "instance", False, definition.env)
        return Effective(key, definition.default, "default", False, definition.env)

    def get(self, conn: sqlite3.Connection, key: str, user_id: int | None = None) -> Any:
        return self.effective(conn, key, user_id).value

    def user_view(self, conn: sqlite3.Connection, user_id: int) -> dict[str, dict[str, Any]]:
        """``{key: {"value", "source", "editable"}}`` for the keys a person can see (GET /api/me/settings)."""
        out = {}
        for d in self.definitions():
            if d.user_editable:
                out[d.key] = self.effective(conn, d.key, user_id).as_user_item(d)
        return out

    def admin_view(self, conn: sqlite3.Connection) -> dict[str, dict[str, Any]]:
        """``{key: {"value", "source", "locked_by_env", "scope"}}`` for instance-level keys (GET /api/admin/settings)."""
        out = {}
        for d in self.definitions():
            if d.admin_editable:
                out[d.key] = self.effective(conn, d.key, None).as_admin_item(d)
        return out

    # ------------------------------------------------------------------ writes (caller commits)
    def _check_writable(self, conn: sqlite3.Connection, definition: SettingDef) -> None:
        if self.env_value(definition)[0]:
            raise SettingLocked(definition.key, definition.env or "")
        if not self.tables_exist(conn):
            raise SettingsUnavailable("settings tables do not exist yet (database below schema v3)")

    def _validated_json(self, definition: SettingDef, value: Any) -> str:
        try:
            return definition.to_json(value)
        except ValidationError as exc:
            raise InvalidSettingValue(definition.key, exc) from None

    def set_instance(self, conn: sqlite3.Connection, key: str, value: Any, *, updated_by: int | None = None) -> Effective:
        """Admin write; ``value=None`` deletes the row (back to the default)."""
        definition = self.definition(key)
        if not definition.admin_editable:
            raise SettingNotEditable(f"{key} is a personal setting")
        self._check_writable(conn, definition)
        if value is None:
            conn.execute("DELETE FROM instance_settings WHERE key = ?", (key,))
        else:
            text = self._validated_json(definition, value)
            conn.execute(
                """INSERT INTO instance_settings (key, value_json, updated_at, updated_by) VALUES (?, ?, ?, ?)
                   ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json,
                     updated_at = excluded.updated_at, updated_by = excluded.updated_by""",
                (key, text, utcnow(), updated_by),
            )
        self._bump(conn)
        return self.effective(conn, key, None)

    def set_user(self, conn: sqlite3.Connection, user_id: int, key: str, value: Any) -> Effective:
        """A person's own value; ``value=None`` deletes it (back to the inherited value)."""
        definition = self.definition(key)
        if not definition.user_editable:
            raise SettingNotEditable(f"{key} can only be changed by an admin")
        self._check_writable(conn, definition)
        if value is None:
            conn.execute("DELETE FROM user_settings WHERE user_id = ? AND key = ?", (int(user_id), key))
        else:
            text = self._validated_json(definition, value)
            conn.execute(
                """INSERT INTO user_settings (user_id, key, value_json, updated_at) VALUES (?, ?, ?, ?)
                   ON CONFLICT(user_id, key) DO UPDATE SET value_json = excluded.value_json, updated_at = excluded.updated_at""",
                (int(user_id), key, text, utcnow()),
            )
        self._bump(conn)
        return self.effective(conn, key, int(user_id))

    def update_user(self, conn: sqlite3.Connection, user_id: int, changes: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
        """PATCH /api/me/settings: validate every key first, then write all (caller commits)."""
        for key, value in changes.items():
            definition = self.definition(key)
            if not definition.user_editable:
                raise SettingNotEditable(f"{key} can only be changed by an admin")
            if self.env_value(definition)[0]:
                raise SettingLocked(key, definition.env or "")
            if value is not None:
                self._validated_json(definition, value)
        for key, value in changes.items():
            self.set_user(conn, user_id, key, value)
        return self.user_view(conn, user_id)

    def update_instance(
        self, conn: sqlite3.Connection, changes: Mapping[str, Any], *, updated_by: int | None = None
    ) -> list[tuple[str, Any, Any]]:
        """PATCH /api/admin/settings: validate all, write all; returns ``(key, old, new)`` for the audit log."""
        for key, value in changes.items():
            definition = self.definition(key)
            if not definition.admin_editable:
                raise SettingNotEditable(f"{key} is a personal setting")
            if self.env_value(definition)[0]:
                raise SettingLocked(key, definition.env or "")
            if value is not None:
                self._validated_json(definition, value)
        changed = []
        for key, value in changes.items():
            definition = self.definition(key)
            old = definition.to_python_json(self.effective(conn, key).value)
            new = definition.to_python_json(self.set_instance(conn, key, value, updated_by=updated_by).value)
            if old != new:
                changed.append((key, old, new))
        return changed


_DEFAULT_STORE: SettingsStore | None = None
_DEFAULT_LOCK = threading.Lock()


def default_store() -> SettingsStore:
    """The process-wide store (env locks from ``os.environ``)."""
    global _DEFAULT_STORE
    with _DEFAULT_LOCK:
        if _DEFAULT_STORE is None:
            _DEFAULT_STORE = SettingsStore()
        return _DEFAULT_STORE


# Module-level conveniences on the default store. user_id is always explicit.
def effective(conn: sqlite3.Connection, key: str, user_id: int | None = None) -> Effective:
    return default_store().effective(conn, key, user_id)


def get_value(conn: sqlite3.Connection, key: str, user_id: int | None = None) -> Any:
    return default_store().get(conn, key, user_id)


def set_instance_value(conn: sqlite3.Connection, key: str, value: Any, *, updated_by: int | None = None) -> Effective:
    return default_store().set_instance(conn, key, value, updated_by=updated_by)


def set_user_value(conn: sqlite3.Connection, user_id: int, key: str, value: Any) -> Effective:
    return default_store().set_user(conn, user_id, key, value)


def dumps(value: Any) -> str:
    """JSON for CLI output."""
    return json.dumps(value, ensure_ascii=False)
