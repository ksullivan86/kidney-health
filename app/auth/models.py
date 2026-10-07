"""The signed-in person (:class:`User`) and the account helpers every module shares.

``User`` is the fixed identity interface of ARCHITECTURE.md (v0.3 contract, item 3): a frozen
dataclass carried through FastAPI dependencies. Handlers pass ``user.id`` explicitly into every
query; there are no context variables or globals.
"""
from __future__ import annotations

import re
import sqlite3
import unicodedata
from dataclasses import dataclass
from typing import Any, Literal

Role = Literal["admin", "user"]
ROLES: tuple[str, ...] = ("admin", "user")
STATUSES: tuple[str, ...] = ("pending_setup", "active", "disabled", "locked")

# Local usernames after NFKC + casefold (note 07 §4.4). Proxy identities are stored as given
# (normalised, up to 255 characters) and never compared with local names except to refuse a
# collision (§9 N2).
LOCAL_USERNAME = re.compile(r"^[a-z0-9._@+-]{3,64}$")
USERNAME_HELP = "Use 3 to 64 characters: letters, digits and . _ @ + -"
MAX_PROXY_SUBJECT = 255


@dataclass(frozen=True)
class User:
    id: int
    username: str
    role: Role
    status: str
    display_name: str | None = None
    auth_source: str = "local"
    must_change_password: bool = False
    can_use_shared: bool = True
    created_at: str | None = None
    last_login_at: str | None = None

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    @property
    def is_active(self) -> bool:
        return self.status == "active"


USER_COLUMNS = (
    "id, username, username_norm, display_name, role, status, auth_source, external_subject, password_hash, "
    "password_changed_at, must_change_password, can_use_shared, created_at, updated_at, last_login_at"
)


def normalize_username(raw: str) -> str:
    """NFKC + casefold + strip: the form stored in ``users.username_norm``."""
    return unicodedata.normalize("NFKC", raw or "").strip().casefold()


def clean_display(raw: str | None, limit: int = 80) -> str:
    """Display names: NFC, collapsed whitespace, no control characters, at most ``limit`` characters."""
    if not raw:
        return ""
    text = unicodedata.normalize("NFC", raw)
    text = "".join(ch for ch in text if unicodedata.category(ch)[0] != "C")
    return " ".join(text.split())[:limit]


def valid_local_username(norm: str) -> bool:
    return bool(LOCAL_USERNAME.match(norm))


def user_from_row(row: sqlite3.Row | dict[str, Any]) -> User:
    return User(
        id=int(row["id"]),
        username=row["username"],
        role=row["role"],
        status=row["status"],
        display_name=row["display_name"] or None,
        auth_source=row["auth_source"],
        must_change_password=bool(row["must_change_password"]),
        can_use_shared=bool(row["can_use_shared"]),
        created_at=row["created_at"],
        last_login_at=row["last_login_at"],
    )


def user_row(conn: sqlite3.Connection, user_id: int) -> sqlite3.Row | None:
    try:
        return conn.execute(f"SELECT {USER_COLUMNS} FROM users WHERE id = ?", (int(user_id),)).fetchone()
    except OverflowError:
        return None


def load_user(conn: sqlite3.Connection, user_id: int) -> User | None:
    row = user_row(conn, user_id)
    return None if row is None else user_from_row(row)


def find_local_user(conn: sqlite3.Connection, username_norm: str) -> sqlite3.Row | None:
    return conn.execute(
        f"SELECT {USER_COLUMNS} FROM users WHERE username_norm = ? AND auth_source = 'local'", (username_norm,)
    ).fetchone()


def me_dict(user: User) -> dict[str, Any]:
    """The ``Me`` shape of note 07 §4.16."""
    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name or "",
        "role": user.role,
        "auth_source": user.auth_source,
        "must_change_password": user.must_change_password,
        "created_at": user.created_at,
    }


def active_count(conn: sqlite3.Connection) -> int:
    return int(conn.execute("SELECT COUNT(*) FROM users WHERE status = 'active'").fetchone()[0])


def active_admin_count(conn: sqlite3.Connection) -> int:
    return int(conn.execute("SELECT COUNT(*) FROM users WHERE status = 'active' AND role = 'admin'").fetchone()[0])


def setup_required(conn: sqlite3.Connection) -> bool:
    """True until some admin account has been set up (first-run setup, env, CLI)."""
    row = conn.execute("SELECT 1 FROM users WHERE role = 'admin' AND status != 'pending_setup' LIMIT 1").fetchone()
    return row is None
