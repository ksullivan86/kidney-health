"""Two-step sign-in: codes from an authenticator app (RFC 6238) and recovery codes (design note 17).

Standard library only. The defaults are the ones every authenticator app supports: HMAC-SHA-1, 6 digits, 30-second steps
counted from Unix time 0. A code is accepted for the step before, the current step and the step after, and each step works once
(``totp_factors.last_step``). The secret is sealed with the keyring (purpose ``totp``, owner the person's id), so a copy of the
database alone does not give the codes; ``app.crypto.ENCRYPTED_COLUMNS`` lists the column for key rotation.

Recovery codes are 10 codes of 10 characters (50 bits each) from an alphabet without look-alike letters, shown as ``xxxxx-xxxxx``.
Only their SHA-256 is stored, and each works once.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import sqlite3
import struct
from dataclasses import dataclass
from urllib.parse import quote, urlencode

from . import clock

DIGITS = 6
STEP_S = 30
WINDOW = 1  # steps either side of now
SECRET_BYTES = 20  # 160 bits, RFC 4226 §4
PURPOSE = "totp"

RECOVERY_COUNT = 10
RECOVERY_LENGTH = 10
RECOVERY_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"  # no i, l, o, 0, 1
assert len(set(RECOVERY_ALPHABET)) == len(RECOVERY_ALPHABET)

CODE_MAX = 32  # the longest text the code field takes (a recovery code with spaces fits)


# --------------------------------------------------------------------------- #
# The algorithm (RFC 4226 and RFC 6238)
# --------------------------------------------------------------------------- #


def hotp(key: bytes, counter: int, digits: int = DIGITS) -> str:
    """RFC 4226 §5.3: HMAC-SHA-1 of the 8-byte counter, dynamic truncation, the last ``digits`` decimal digits."""
    mac = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = mac[-1] & 0x0F
    value = struct.unpack(">I", mac[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(value % 10**digits).zfill(digits)


def step_at(seconds: float) -> int:
    """The RFC 6238 time step for a POSIX time."""
    return int(seconds // STEP_S)


def totp(key: bytes, seconds: float, digits: int = DIGITS) -> str:
    return hotp(key, step_at(seconds), digits)


def new_secret() -> bytes:
    return secrets.token_bytes(SECRET_BYTES)


def secret_text(key: bytes) -> str:
    """The secret as the apps take it: base32, upper case, without ``=`` padding (32 characters for 20 bytes)."""
    return base64.b32encode(key).decode("ascii").rstrip("=")


def secret_from_text(text: str) -> bytes:
    cleaned = "".join(text.split()).upper()
    return base64.b32decode(cleaned + "=" * (-len(cleaned) % 8))


def otpauth_uri(key: bytes, *, issuer: str, account: str) -> str:
    """The Key Uri Format the apps read from a QR code: ``otpauth://totp/Issuer:account?secret=…&issuer=…``."""
    label = quote(f"{issuer}:{account}", safe=":@")
    query = urlencode({"secret": secret_text(key), "issuer": issuer, "algorithm": "SHA1", "digits": DIGITS, "period": STEP_S},
                      quote_via=quote)
    return f"otpauth://totp/{label}?{query}"


def clean_code(text: str | None) -> str:
    """What the person typed, without spaces and dashes, lower case."""
    return "".join(ch for ch in (text or "") if not ch.isspace() and ch != "-").lower()


def looks_like_app_code(cleaned: str) -> bool:
    return len(cleaned) == DIGITS and cleaned.isascii() and cleaned.isdigit()


def matching_step(key: bytes, code: str, *, seconds: float, after_step: int) -> int | None:
    """The step within the window whose code equals ``code`` and is later than ``after_step`` (so each code works once)."""
    if not looks_like_app_code(code):
        return None
    now = step_at(seconds)
    found = None
    for step in range(now - WINDOW, now + WINDOW + 1):
        # compare every step in constant time, so the answer time does not show which step matched
        if hmac.compare_digest(hotp(key, step), code) and step > after_step and found is None:
            found = step
    return found


# --------------------------------------------------------------------------- #
# Recovery codes
# --------------------------------------------------------------------------- #


def new_recovery_codes() -> list[str]:
    codes = []
    for _ in range(RECOVERY_COUNT):
        raw = "".join(secrets.choice(RECOVERY_ALPHABET) for _ in range(RECOVERY_LENGTH))
        codes.append(f"{raw[:5]}-{raw[5:]}")
    return codes


def recovery_hash(cleaned: str) -> bytes:
    return hashlib.sha256(cleaned.encode("ascii")).digest()


def looks_like_recovery_code(cleaned: str) -> bool:
    return len(cleaned) == RECOVERY_LENGTH and all(ch in RECOVERY_ALPHABET for ch in cleaned)


# --------------------------------------------------------------------------- #
# Storage (schema step 22)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Factor:
    user_id: int
    key: bytes | None  # None when the secret cannot be unsealed (SECRET_KEY lost or changed)
    enabled_at: str | None
    last_step: int

    @property
    def enabled(self) -> bool:
        return self.enabled_at is not None


def load(conn: sqlite3.Connection, keyring, user_id: int) -> Factor | None:
    from ..crypto import InvalidToken

    row = conn.execute("SELECT secret_enc, enabled_at, last_step FROM totp_factors WHERE user_id = ?", (int(user_id),)).fetchone()
    if row is None:
        return None
    try:
        key = secret_from_text(keyring.unseal(row["secret_enc"], purpose=PURPOSE, owner=int(user_id))["secret"])
    except (InvalidToken, KeyError, ValueError):
        key = None
    return Factor(int(user_id), key, row["enabled_at"], int(row["last_step"]))


def is_enabled(conn: sqlite3.Connection, user_id: int) -> bool:
    row = conn.execute("SELECT 1 FROM totp_factors WHERE user_id = ? AND enabled_at IS NOT NULL", (int(user_id),)).fetchone()
    return row is not None


def enabled_ids(conn: sqlite3.Connection) -> set[int]:
    return {int(r[0]) for r in conn.execute("SELECT user_id FROM totp_factors WHERE enabled_at IS NOT NULL")}


def start(conn: sqlite3.Connection, keyring, user_id: int) -> bytes:
    """A new pending secret for the person (replacing an earlier pending one). The caller commits."""
    key = new_secret()
    token, key_id = keyring.seal(purpose=PURPOSE, owner=int(user_id), fields={"secret": secret_text(key)})
    conn.execute(
        """INSERT INTO totp_factors (user_id, secret_enc, key_id, created_at, enabled_at, last_step) VALUES (?, ?, ?, ?, NULL, 0)
           ON CONFLICT(user_id) DO UPDATE SET secret_enc = excluded.secret_enc, key_id = excluded.key_id,
             created_at = excluded.created_at, enabled_at = NULL, last_step = 0
           WHERE totp_factors.enabled_at IS NULL""",
        (int(user_id), token, key_id, clock.now_iso()),
    )
    return key


def use_step(conn: sqlite3.Connection, user_id: int, step: int) -> bool:
    """Record ``step`` as used. False when another request used it (or a later one) first."""
    cur = conn.execute("UPDATE totp_factors SET last_step = ? WHERE user_id = ? AND last_step < ?", (int(step), int(user_id), int(step)))
    return cur.rowcount == 1


def enable(conn: sqlite3.Connection, user_id: int, step: int) -> list[str]:
    """Turn the pending factor on, with ``step`` used, and make the recovery codes. The caller commits."""
    conn.execute("UPDATE totp_factors SET enabled_at = ?, last_step = ? WHERE user_id = ? AND enabled_at IS NULL",
                 (clock.now_iso(), int(step), int(user_id)))
    return renew_recovery_codes(conn, user_id)


def renew_recovery_codes(conn: sqlite3.Connection, user_id: int) -> list[str]:
    codes = new_recovery_codes()
    conn.execute("DELETE FROM totp_recovery_codes WHERE user_id = ?", (int(user_id),))
    conn.executemany("INSERT INTO totp_recovery_codes (user_id, code_hash) VALUES (?, ?)",
                     [(int(user_id), recovery_hash(clean_code(c))) for c in codes])
    return codes


def use_recovery_code(conn: sqlite3.Connection, user_id: int, cleaned: str) -> bool:
    """Mark the matching unused code used. The lookup is by hash, so it does not leak which code is close."""
    if not looks_like_recovery_code(cleaned):
        return False
    cur = conn.execute("UPDATE totp_recovery_codes SET used_at = ? WHERE user_id = ? AND code_hash = ? AND used_at IS NULL",
                       (clock.now_iso(), int(user_id), recovery_hash(cleaned)))
    return cur.rowcount == 1


def recovery_codes_left(conn: sqlite3.Connection, user_id: int) -> int:
    return int(conn.execute("SELECT COUNT(*) FROM totp_recovery_codes WHERE user_id = ? AND used_at IS NULL", (int(user_id),)).fetchone()[0])


def remove(conn: sqlite3.Connection, user_id: int) -> bool:
    """Remove the factor (pending or on) and the recovery codes. True when it was on. The caller commits."""
    was_on = is_enabled(conn, user_id)
    conn.execute("DELETE FROM totp_recovery_codes WHERE user_id = ?", (int(user_id),))
    conn.execute("DELETE FROM totp_factors WHERE user_id = ?", (int(user_id),))
    return was_on


def check(conn: sqlite3.Connection, factor: Factor, typed: str | None, *, seconds: float | None = None) -> str | None:
    """Check what the person typed against an enabled factor and use it up: ``"app"`` for an app code, ``"recovery"`` for a
    recovery code, None when neither. The caller commits."""
    cleaned = clean_code(typed)
    if factor.key is not None and looks_like_app_code(cleaned):
        step = matching_step(factor.key, cleaned, seconds=clock.seconds() if seconds is None else seconds, after_step=factor.last_step)
        if step is not None and use_step(conn, factor.user_id, step):
            return "app"
        return None
    if use_recovery_code(conn, factor.user_id, cleaned):
        return "recovery"
    return None
