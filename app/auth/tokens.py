"""One-time tokens in ``auth_tokens``: the first-run setup code, invites and reset links (note 07 §4.5).

* **Setup code**: 10 random bytes → base32 → ``XXXX-XXXX-XXXX-XXXX`` (80 bits). Stored as the
  SHA-256 of the normalised code (upper case, no dashes or spaces) and compared with
  ``hmac.compare_digest`` (§9 N9). A new code replaces the old one at every start.
* **Invite** and **reset** links carry ``<id>.<verifier>`` in the URL *fragment*
  (``/#/invite/…``, ``/#/reset/…``), which browsers never send to the server, so the token stays out
  of proxy logs and ``Referer``. Only the SHA-256 of the verifier is stored; single use.

Functions never commit.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import sqlite3
from datetime import timedelta
from typing import Any

from . import clock

SETUP = "setup"
INVITE = "invite"
RESET = "reset"


def _sha(text: str) -> bytes:
    return hashlib.sha256(text.encode("utf-8")).digest()


# --------------------------------------------------------------------------- #
# Setup code
# --------------------------------------------------------------------------- #


def normalize_code(code: str) -> str:
    return "".join(ch for ch in (code or "").upper() if ch.isalnum())


def new_setup_code(conn: sqlite3.Connection, ttl_minutes: int) -> tuple[str, str]:
    """Replace any setup code with a new one; returns ``(code, expires_at)``."""
    raw = base64.b32encode(secrets.token_bytes(10)).decode("ascii")  # 16 characters, no padding
    code = "-".join(raw[i : i + 4] for i in range(0, 16, 4))
    now = clock.now()
    expires = clock.iso(now + timedelta(minutes=ttl_minutes))
    conn.execute("DELETE FROM auth_tokens WHERE purpose = 'setup'")
    conn.execute(
        "INSERT INTO auth_tokens (id, purpose, verifier_hash, user_id, created_at, expires_at) VALUES (?, 'setup', ?, 1, ?, ?)",
        (f"setup-{secrets.token_hex(8)}", _sha(normalize_code(code)), clock.iso(now), expires),
    )
    return code, expires


def check_setup_code(conn: sqlite3.Connection, code: str) -> str | None:
    """Id of the unexpired, unused setup token matching ``code`` (every row is compared)."""
    digest = _sha(normalize_code(code))
    found = None
    now = clock.now_iso()
    for row in conn.execute(
        "SELECT id, verifier_hash FROM auth_tokens WHERE purpose = 'setup' AND used_at IS NULL AND expires_at > ?", (now,)
    ).fetchall():
        if hmac.compare_digest(bytes(row["verifier_hash"]), digest):
            found = row["id"]
    return found


# --------------------------------------------------------------------------- #
# Invites and reset links
# --------------------------------------------------------------------------- #


def create_token(
    conn: sqlite3.Connection,
    purpose: str,
    *,
    ttl: timedelta,
    user_id: int | None = None,
    role: str | None = None,
    note: str | None = None,
    created_by: int | None = None,
) -> tuple[str, dict[str, Any]]:
    """Insert an invite or reset token; returns ``(token, row as dict)``. The token is shown once."""
    if purpose not in (INVITE, RESET):
        raise ValueError(purpose)
    token_id = secrets.token_hex(8)
    verifier = secrets.token_urlsafe(32)
    now = clock.now()
    row = {
        "id": token_id,
        "purpose": purpose,
        "user_id": user_id,
        "role": role,
        "note": note,
        "created_by": created_by,
        "created_at": clock.iso(now),
        "expires_at": clock.iso(now + ttl),
        "used_at": None,
    }
    conn.execute(
        """INSERT INTO auth_tokens (id, purpose, verifier_hash, user_id, role, note, created_by, created_at, expires_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (token_id, purpose, _sha(verifier), user_id, role, note, created_by, row["created_at"], row["expires_at"]),
    )
    return f"{token_id}.{verifier}", row


def find_token(conn: sqlite3.Connection, token: str, purpose: str) -> sqlite3.Row | None:
    """The unused, unexpired row for ``token`` (constant-time verifier comparison)."""
    if not token or "." not in token or len(token) > 200:
        return None
    token_id, _, verifier = token.partition(".")
    row = conn.execute("SELECT * FROM auth_tokens WHERE id = ? AND purpose = ?", (token_id, purpose)).fetchone()
    expected = bytes(row["verifier_hash"]) if row is not None else b"\0" * 32
    matches = hmac.compare_digest(expected, _sha(verifier))
    if row is None or not matches or row["used_at"] is not None or row["expires_at"] <= clock.now_iso():
        return None
    return row


def mark_used(conn: sqlite3.Connection, token_id: str) -> bool:
    cur = conn.execute("UPDATE auth_tokens SET used_at = ? WHERE id = ? AND used_at IS NULL", (clock.now_iso(), token_id))
    return (cur.rowcount or 0) > 0


def void_issued_by(conn: sqlite3.Connection, user_id: int) -> int:
    """Delete every unused invite and reset/setup link that ``user_id`` created; returns how many.

    Called when an admin is demoted, disabled or deleted, so links they handed out (or planted, for
    example a reset link for another admin's account) stop working with them. It must run before
    ``DELETE FROM users``: the foreign key then sets ``created_by`` to NULL and nothing would tie the
    links to the removed admin any more.
    """
    cur = conn.execute(
        "DELETE FROM auth_tokens WHERE created_by = ? AND used_at IS NULL AND purpose IN ('invite', 'reset')", (int(user_id),)
    )
    return int(cur.rowcount or 0)


def void_reset_links(conn: sqlite3.Connection, user_id: int, *, except_id: str | None = None) -> int:
    """Mark every unused reset or account-setup link for ``user_id``'s account used; returns how many.

    Called when the account's password changes (by any route) and when the account is disabled, so
    an older link cannot undo the change later.
    """
    cur = conn.execute(
        "UPDATE auth_tokens SET used_at = ? WHERE purpose = 'reset' AND user_id = ? AND used_at IS NULL AND id != ?",
        (clock.now_iso(), int(user_id), except_id or ""),
    )
    return int(cur.rowcount or 0)


def open_reset_links(conn: sqlite3.Connection) -> dict[int, dict[str, Any]]:
    """The newest unused, unexpired reset or setup link per account: ``{user_id: link}`` (no token)."""
    out: dict[int, dict[str, Any]] = {}
    rows = conn.execute(
        """SELECT id, user_id, created_by, created_at, expires_at FROM auth_tokens
           WHERE purpose = 'reset' AND used_at IS NULL AND expires_at > ? AND user_id IS NOT NULL ORDER BY created_at""",
        (clock.now_iso(),),
    ).fetchall()
    for row in rows:
        out[int(row["user_id"])] = {
            "id": row["id"],
            "created_by": row["created_by"],
            "created_at": row["created_at"],
            "expires_at": row["expires_at"],
        }
    return out


def link(base: str | None, kind: str, token: str) -> str:
    """``<base>/#/<kind>/<token>``; ``base`` is ``PUBLIC_URL`` or the request's own origin."""
    return f"{(base or '').rstrip('/')}/#/{kind}/{token}"


def invite_dict(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    now = clock.now_iso()
    state = "used" if row["used_at"] else ("expired" if row["expires_at"] <= now else "open")
    return {
        "id": row["id"],
        "role": row["role"],
        "note": row["note"] or "",
        "created_by": row["created_by"],
        "created_at": row["created_at"],
        "expires_at": row["expires_at"],
        "used_at": row["used_at"],
        "state": state,
    }
