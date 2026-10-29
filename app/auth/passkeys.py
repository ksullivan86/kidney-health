"""Passkeys: storage (schema step 23) and the single-use challenges (design note 18 §4).

The checks themselves are in :mod:`app.auth.webauthn`; the routes in :mod:`app.auth.passkeys_api`. Every query here is scoped by
``user_id`` except :func:`find_by_credential`, which the sign-in uses before it knows who is signing in.
"""
from __future__ import annotations

import os
import secrets
import sqlite3
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from . import clock

MAX_PER_PERSON = 10
NAME_MAX = 60
CHALLENGE_TTL_S = 300
MAX_CHALLENGES = 10_000
DEFAULT_NAME = "Passkey"


# --------------------------------------------------------------------------- #
# Challenges (in memory, single use, 5 minutes)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Challenge:
    value: bytes
    kind: str  # "create" or "get"
    user_id: int | None  # the person adding a passkey; None for a sign-in
    user_handle: bytes | None
    expires: float


class ChallengeStore:
    """Issued challenges by id. :meth:`take` returns one at most once, and only before it expires. At most ``MAX_CHALLENGES`` are
    kept; the oldest go first, so a flood of requests costs a bounded amount of memory and only makes the flood's own
    challenges fail."""

    def __init__(self, max_items: int = MAX_CHALLENGES, ttl_s: float = CHALLENGE_TTL_S) -> None:
        self._items: OrderedDict[str, Challenge] = OrderedDict()
        self._lock = threading.Lock()
        self._max, self._ttl = max_items, ttl_s

    def issue(self, kind: str, user_id: int | None = None, user_handle: bytes | None = None) -> tuple[str, Challenge]:
        cid = secrets.token_urlsafe(18)
        item = Challenge(os.urandom(32), kind, user_id, user_handle, time.monotonic() + self._ttl)
        with self._lock:
            now = time.monotonic()
            while self._items and (len(self._items) >= self._max or next(iter(self._items.values())).expires < now):
                self._items.popitem(last=False)
            self._items[cid] = item
        return cid, item

    def take(self, cid: str, kind: str, user_id: int | None = None) -> Challenge | None:
        with self._lock:
            item = self._items.pop(cid, None) if isinstance(cid, str) else None
        if item is None or item.kind != kind or item.user_id != user_id or item.expires < time.monotonic():
            return None
        return item

    def __len__(self) -> int:
        return len(self._items)


# --------------------------------------------------------------------------- #
# Where passkeys work
# --------------------------------------------------------------------------- #


def rp_id_and_origin(public_base: str) -> tuple[str, str]:
    """The RP ID (the host name) and the one accepted origin, from ``PUBLIC_URL`` or the request's own origin."""
    parts = urlsplit(public_base)
    host = (parts.hostname or "").lower()
    return host, f"{parts.scheme}://{parts.netloc}".lower()


def host_is_ip(host: str) -> bool:
    import ipaddress

    try:
        ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return False
    return True


# --------------------------------------------------------------------------- #
# Storage
# --------------------------------------------------------------------------- #

_COLUMNS = "id, user_id, credential_id, public_key, alg, user_handle, sign_count, name, backed_up, created_at, last_used_at"


def clean_name(raw: str | None) -> str:
    from .models import clean_display

    return clean_display(raw, NAME_MAX) or DEFAULT_NAME


def item(row: sqlite3.Row) -> dict[str, Any]:
    """What the person sees: never the key or the IDs the authenticator chose."""
    return {"id": int(row["id"]), "name": row["name"], "created_at": row["created_at"], "last_used_at": row["last_used_at"],
            "backed_up": bool(row["backed_up"])}


def list_for(conn: sqlite3.Connection, user_id: int) -> list[sqlite3.Row]:
    return conn.execute(f"SELECT {_COLUMNS} FROM passkeys WHERE user_id = ? ORDER BY id", (int(user_id),)).fetchall()


def count_for(conn: sqlite3.Connection, user_id: int) -> int:
    return int(conn.execute("SELECT COUNT(*) FROM passkeys WHERE user_id = ?", (int(user_id),)).fetchone()[0])


def counts(conn: sqlite3.Connection) -> dict[int, int]:
    return {int(r[0]): int(r[1]) for r in conn.execute("SELECT user_id, COUNT(*) FROM passkeys GROUP BY user_id")}


def get_for(conn: sqlite3.Connection, user_id: int, passkey_id: int) -> sqlite3.Row | None:
    return conn.execute(f"SELECT {_COLUMNS} FROM passkeys WHERE id = ? AND user_id = ?", (int(passkey_id), int(user_id))).fetchone()


def find_by_credential(conn: sqlite3.Connection, credential_id: bytes) -> sqlite3.Row | None:
    return conn.execute(f"SELECT {_COLUMNS} FROM passkeys WHERE credential_id = ?", (bytes(credential_id),)).fetchone()


def user_handle_for(conn: sqlite3.Connection, user_id: int) -> bytes:
    """The person's user handle: the one their passkeys already carry, else 32 new random bytes."""
    row = conn.execute("SELECT user_handle FROM passkeys WHERE user_id = ? ORDER BY id LIMIT 1", (int(user_id),)).fetchone()
    return bytes(row[0]) if row is not None else os.urandom(32)


def add(conn: sqlite3.Connection, user_id: int, *, credential_id: bytes, public_key: bytes, alg: int, user_handle: bytes,
        sign_count: int, name: str, backed_up: bool) -> sqlite3.Row:
    """Insert one passkey. Raises ``sqlite3.IntegrityError`` when the credential ID is already stored. The caller commits."""
    cur = conn.execute(
        """INSERT INTO passkeys (user_id, credential_id, public_key, alg, user_handle, sign_count, name, backed_up, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (int(user_id), bytes(credential_id), bytes(public_key), int(alg), bytes(user_handle), int(sign_count), name,
         1 if backed_up else 0, clock.now_iso()),
    )
    row = get_for(conn, user_id, int(cur.lastrowid or 0))
    assert row is not None
    return row


def used(conn: sqlite3.Connection, passkey_id: int, *, sign_count: int, backed_up: bool) -> None:
    conn.execute("UPDATE passkeys SET sign_count = ?, backed_up = ?, last_used_at = ? WHERE id = ?",
                 (int(sign_count), 1 if backed_up else 0, clock.now_iso(), int(passkey_id)))


def rename(conn: sqlite3.Connection, user_id: int, passkey_id: int, name: str) -> bool:
    cur = conn.execute("UPDATE passkeys SET name = ? WHERE id = ? AND user_id = ?", (name, int(passkey_id), int(user_id)))
    return cur.rowcount == 1


def remove(conn: sqlite3.Connection, user_id: int, passkey_id: int) -> bool:
    cur = conn.execute("DELETE FROM passkeys WHERE id = ? AND user_id = ?", (int(passkey_id), int(user_id)))
    return cur.rowcount == 1


def remove_all(conn: sqlite3.Connection, user_id: int) -> int:
    return conn.execute("DELETE FROM passkeys WHERE user_id = ?", (int(user_id),)).rowcount
