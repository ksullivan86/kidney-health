"""Key material for secrets at rest (note 07 §4.12, note 01 §5.5 and §10 S8).

``SECRET_KEY`` (or ``SECRET_KEY_FILE``, or the auto-generated ``$DATA_DIR/secret.key``) holds one
key per line; the **first line is current** and the others are kept only to decrypt during a
rotation. Each line is stretched with HKDF-SHA256 into a Fernet key; stored values are sealed
together with their ``purpose`` and ``owner`` so a ciphertext copied into another row does not
decrypt there. Sessions are opaque server-side tokens and are **not** signed with this key.

Other modules derive their own keys with :meth:`Keyring.subkey` (for example
``"kidney-health/v1/login-failures"`` for the login-throttle MAC); rotating ``SECRET_KEY``
changes those too, which only resets such counters.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import stat
from dataclasses import dataclass
import sqlite3
from pathlib import Path
from typing import Sequence

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from .config import ConfigError, Settings, check_secret_key_lines, parse_secret_key_lines

log = logging.getLogger("kidney_health.crypto")

__all__ = [
    "InvalidToken",
    "Keyring",
    "LoadedKey",
    "SECRETS_INFO",
    "ENCRYPTED_COLUMNS",
    "load_keyring",
    "load_secret_key",
    "create_secret_key_file",
    "new_key_line",
    "reencrypt_all",
    "secret_report",
]

SECRETS_INFO = b"kidney-health/v1/secrets"
ENVELOPE_VERSION = 1
BACKUP_WARNING = (
    "Back up {path} separately from kidney.db; without it stored API keys cannot be decrypted "
    "(passwords and health data are not affected)."
)
AUTO_KEY_WARNING = (
    "SECRET_KEY is not set, so stored API keys are encrypted with {path}. That file is on the data volume, "
    "so volume-level backups contain it. Mount SECRET_KEY_FILE from your engine's secret store instead "
    "(see docs/security.md)."
)

# Columns holding Keyring tokens: (table, primary key, token column, key-id column or None).
# app.admin rotate-secret-key / reencrypt walks these; note 04 appends ai_providers.api_key_enc.
ENCRYPTED_COLUMNS: list[tuple[str, str, str, str | None]] = [
    ("secrets", "id", "ciphertext", "key_id"),
    ("ai_providers", "id", "api_key_enc", None),
]


def _hkdf(master: bytes, info: bytes, length: int = 32) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=length, salt=None, info=info).derive(master)


def new_key_line() -> str:
    """A fresh random key line (43 URL-safe characters)."""
    return secrets.token_urlsafe(32)


class Keyring:
    """Fernet keys derived from the SECRET_KEY lines; the first line encrypts, all lines decrypt."""

    def __init__(self, lines: Sequence[str], *, source: str = "env", path: Path | None = None):
        masters = parse_secret_key_lines("\n".join(lines))
        check_secret_key_lines(masters)
        self._masters = [m.encode("utf-8") for m in masters]
        derived = [_hkdf(m, SECRETS_INFO) for m in self._masters]
        self.ids: list[str] = [hashlib.sha256(d).hexdigest()[:8] for d in derived]  # non-secret key ids
        self.current_id: str = self.ids[0]
        self._fernets = [Fernet(base64.urlsafe_b64encode(d)) for d in derived]
        self.fernet = MultiFernet(self._fernets)
        self.source = source
        self.path = path

    def __repr__(self) -> str:  # never show key material
        return f"Keyring(ids={self.ids!r}, source={self.source!r})"

    # ------------------------------------------------------------------ sealing
    def seal(self, *, purpose: str, owner: int | None, fields: dict[str, str]) -> tuple[bytes, str]:
        """Encrypt ``fields`` bound to ``purpose`` and ``owner``. Returns ``(token, key_id)``."""
        if not purpose:
            raise ValueError("purpose is required")
        envelope = {"v": ENVELOPE_VERSION, "purpose": purpose, "owner": owner, "fields": dict(fields)}
        token = self.fernet.encrypt(json.dumps(envelope, separators=(",", ":")).encode("utf-8"))
        return token, self.current_id

    def unseal(self, token: bytes | str, *, purpose: str, owner: int | None) -> dict[str, str]:
        """Decrypt a token from :meth:`seal`; ``InvalidToken`` if tampered, unknown key or moved row."""
        raw = token.encode("ascii") if isinstance(token, str) else bytes(token)
        try:
            envelope = json.loads(self.fernet.decrypt(raw))
        except (ValueError, TypeError):
            raise InvalidToken from None
        if (
            not isinstance(envelope, dict)
            or envelope.get("v") != ENVELOPE_VERSION
            or envelope.get("purpose") != purpose
            or envelope.get("owner") != owner
            or not isinstance(envelope.get("fields"), dict)
        ):
            raise InvalidToken  # ciphertext moved to another row or purpose
        return {str(k): str(v) for k, v in envelope["fields"].items()}

    def rotate(self, token: bytes | str) -> bytes:
        """Re-encrypt ``token`` under the current key (``InvalidToken`` if no line decrypts it)."""
        raw = token.encode("ascii") if isinstance(token, str) else bytes(token)
        return self.fernet.rotate(raw)

    def key_id_of(self, token: bytes | str) -> str | None:
        """Id of the line that decrypts ``token`` (None if none does)."""
        raw = token.encode("ascii") if isinstance(token, str) else bytes(token)
        for key_id, fernet in zip(self.ids, self._fernets, strict=True):
            try:
                fernet.decrypt(raw)
            except InvalidToken:
                continue
            return key_id
        return None

    # ------------------------------------------------------------------ derived keys
    def subkey(self, info: str, length: int = 32) -> bytes:
        """HKDF-SHA256 of the current line with ``info`` (e.g. ``"kidney-health/v1/login-failures"``)."""
        if not info or info.encode("utf-8") == SECRETS_INFO:
            raise ValueError("use a distinct, non-empty info string")
        return _hkdf(self._masters[0], info.encode("utf-8"), length)

    def mac(self, info: str, message: bytes | str) -> bytes:
        """HMAC-SHA256 of ``message`` under :meth:`subkey` ``(info)``."""
        data = message.encode("utf-8") if isinstance(message, str) else message
        return hmac.new(self.subkey(info), data, hashlib.sha256).digest()


# --------------------------------------------------------------------------- #
# Loading SECRET_KEY / SECRET_KEY_FILE / $DATA_DIR/secret.key
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class LoadedKey:
    lines: list[str]
    source: str  # "env" | "file" | "auto"
    path: Path | None
    created: bool = False


def create_secret_key_file(path: Path) -> list[str]:
    """Create ``path`` with one new key line, mode 0600, never overwriting an existing file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    line = new_key_line()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(fd, (line + "\n").encode("ascii"))
    finally:
        os.close(fd)
    return [line]


def read_secret_key_file(path: Path) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8")
    except PermissionError:
        raise ConfigError(f"cannot read {path} (permission denied).") from None
    lines = parse_secret_key_lines(text)
    check_secret_key_lines(lines, str(path))
    try:
        mode = stat.S_IMODE(path.stat().st_mode)
    except OSError:
        mode = 0
    if mode & 0o077:
        log.warning("%s is readable by other users (mode %o); run: chmod 600 %s", path, mode, path)
    return lines


def load_secret_key(settings: Settings) -> LoadedKey:
    """The SECRET_KEY lines from env, ``SECRET_KEY_FILE`` or the auto file (created on first use)."""
    if settings.secret_key:
        lines = parse_secret_key_lines(settings.secret_key)
        check_secret_key_lines(lines, "SECRET_KEY_FILE" if settings.secret_key_source == "file" else "SECRET_KEY")
        return LoadedKey(lines=lines, source=settings.secret_key_source, path=settings.secret_key_file)
    path = settings.secret_key_path
    try:
        lines = create_secret_key_file(path)
    except FileExistsError:
        return LoadedKey(lines=read_secret_key_file(path), source="auto", path=path)
    return LoadedKey(lines=lines, source="auto", path=path, created=True)


def load_keyring(settings: Settings, *, announce: bool = True) -> Keyring:
    """Build the :class:`Keyring`, creating ``$DATA_DIR/secret.key`` if needed (with loud warnings)."""
    from .security import register_secret

    loaded = load_secret_key(settings)
    for line in loaded.lines:
        register_secret(line)
    if announce and loaded.source == "auto":
        if loaded.created:
            log.warning("created a new secret key at %s. %s", loaded.path, BACKUP_WARNING.format(path=loaded.path))
        log.warning(AUTO_KEY_WARNING.format(path=loaded.path))
    return Keyring(loaded.lines, source=loaded.source, path=loaded.path)


# --------------------------------------------------------------------------- #
# Rotation helpers (python -m app.admin rotate-secret-key / reencrypt, Admin -> About)
# --------------------------------------------------------------------------- #


def reencrypt_all(conn: sqlite3.Connection, keyring: Keyring) -> dict[str, int]:
    """Re-encrypt every token in :data:`app.crypto.ENCRYPTED_COLUMNS` under the current key (no commit)."""
    from .db import table_columns, table_exists

    counts = {"reencrypted": 0, "unreadable": 0}
    for table, pk, column, key_col in ENCRYPTED_COLUMNS:
        if not table_exists(conn, table) or column not in table_columns(conn, table):
            continue
        has_key_col = key_col is not None and key_col in table_columns(conn, table)
        for row in conn.execute(f"SELECT {pk}, {column} FROM {table} WHERE {column} IS NOT NULL").fetchall():
            try:
                token = keyring.rotate(row[1])
            except InvalidToken:
                counts["unreadable"] += 1
                continue
            if has_key_col:
                conn.execute(f"UPDATE {table} SET {column} = ?, {key_col} = ? WHERE {pk} = ?", (token, keyring.current_id, row[0]))
            else:
                conn.execute(f"UPDATE {table} SET {column} = ? WHERE {pk} = ?", (token, row[0]))
            counts["reencrypted"] += 1
    return counts


def secret_report(conn: sqlite3.Connection, keyring: Keyring) -> dict[str, int]:
    """How many stored secrets the current key reads, how many need an older line, how many are lost."""
    from .db import table_columns, table_exists

    report = {"current": 0, "older_key": 0, "unreadable": 0}
    for table, _pk, column, _key_col in ENCRYPTED_COLUMNS:
        if not table_exists(conn, table) or column not in table_columns(conn, table):
            continue
        for (token,) in conn.execute(f"SELECT {column} FROM {table} WHERE {column} IS NOT NULL").fetchall():
            key_id = keyring.key_id_of(token)
            if key_id is None:
                report["unreadable"] += 1
            elif key_id == keyring.current_id:
                report["current"] += 1
            else:
                report["older_key"] += 1
    return report
