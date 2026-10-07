"""Password hashing: Argon2id from ``cryptography`` (note 07 §4.6), scrypt only as a fallback.

* Argon2id at OWASP's m=19 MiB, t=2, p=1 (about 26 ms), stored as a PHC string.
* At most two hashes run at once (:data:`_GATE`): ≤ 38 MiB, no memory DoS. A request that waits
  more than 5 s raises :class:`HashBusy` (the routes answer 503 with ``Retry-After: 1``). Sign-in
  uses :func:`verify_password_async`, which waits for a slot on the event loop instead of in a worker
  thread, so a flood of sign-ins cannot occupy the thread pool every other route needs.
* Passwords are NFC-normalised before hashing (NIST SP 800-63B-4 §3.1.1.2); the whole password is
  hashed, never truncated.
* ``PASSWORD_HASH=scrypt`` is only for builds of ``cryptography`` without Argon2id (OpenSSL < 3.2);
  :func:`self_test` says so at start-up. Successful logins rehash to the configured scheme.
* :func:`dummy_hash` is what unknown, disabled, locked and password-less accounts are verified
  against, so every local sign-in costs exactly one hash (§9 N9).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
import threading
import time
import unicodedata

import anyio
from cryptography.exceptions import InvalidKey, UnsupportedAlgorithm
from cryptography.hazmat.primitives.kdf.argon2 import Argon2id

ARGON2 = {"memory_cost": 19456, "iterations": 2, "lanes": 1}  # OWASP row 2: 19 MiB, t=2, p=1
SCRYPT = {"n": 2**14, "r": 8, "p": 5}  # OWASP: N=2^14 r=8 p=5 (16 MiB)
SCRYPT_MAXMEM = 32 * 1024 * 1024
GATE_SLOTS = 2
GATE_TIMEOUT_S = 5.0
SCHEMES = ("argon2id", "scrypt")

_GATE = threading.BoundedSemaphore(GATE_SLOTS)
_PHC = re.compile(r"^\$argon2id\$v=19\$m=(\d+),t=(\d+),p=(\d+)\$")
_SCRYPT = re.compile(r"^\$scrypt\$ln=(\d+),r=(\d+),p=(\d+)\$([A-Za-z0-9+/=]+)\$([A-Za-z0-9+/=]+)$")

_scheme = "argon2id"
_dummy: dict[str, str] = {}
_dummy_lock = threading.Lock()


class HashBusy(Exception):
    """Both hashing slots stayed busy for 5 s (→ 503 + ``Retry-After: 1``)."""


class PasswordBackendUnavailable(RuntimeError):
    """The configured scheme cannot run in this build."""


ARGON2_MISSING = (
    "This build of cryptography lacks Argon2id (needs OpenSSL >= 3.2; PyPI wheels bundle it). "
    "Install the wheel or set PASSWORD_HASH=scrypt."
)


def configure(scheme: str) -> None:
    """Select the scheme for new hashes (``argon2id`` or ``scrypt``)."""
    global _scheme
    if scheme not in SCHEMES:
        raise ValueError(f"unknown password hash scheme {scheme!r}")
    _scheme = scheme


def scheme() -> str:
    return _scheme


def normalize(password: str) -> str:
    return unicodedata.normalize("NFC", password)


def _bytes(password: str) -> bytes:
    return normalize(password).encode("utf-8")


def _acquire() -> None:
    if not _GATE.acquire(timeout=GATE_TIMEOUT_S):
        raise HashBusy()


GATE_POLL_S = 0.02


async def _acquire_async() -> None:
    """Take a hashing slot without blocking a thread: poll the same gate the sync callers use."""
    deadline = time.monotonic() + GATE_TIMEOUT_S
    while not _GATE.acquire(blocking=False):
        if time.monotonic() >= deadline:
            raise HashBusy()
        await anyio.sleep(GATE_POLL_S)


# --------------------------------------------------------------------------- #
# scrypt fallback: $scrypt$ln=14,r=8,p=5$<b64 salt>$<b64 hash>
# --------------------------------------------------------------------------- #


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii").rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.b64decode(text + "=" * (-len(text) % 4))


def _hash_scrypt(data: bytes) -> str:
    salt = os.urandom(16)
    digest = hashlib.scrypt(data, salt=salt, maxmem=SCRYPT_MAXMEM, dklen=32, **SCRYPT)
    ln = SCRYPT["n"].bit_length() - 1
    return f"$scrypt$ln={ln},r={SCRYPT['r']},p={SCRYPT['p']}${_b64(salt)}${_b64(digest)}"


def _verify_scrypt(data: bytes, stored: str) -> bool:
    match = _SCRYPT.match(stored)
    if not match:
        return False
    ln, r, p = (int(x) for x in match.group(1, 2, 3))
    if not (1 <= ln <= 20 and 1 <= r <= 32 and 1 <= p <= 16):
        return False
    need = 128 * r * (2**ln)
    if need > 2 * SCRYPT_MAXMEM:  # refuse parameters that would need more than 64 MiB
        return False
    try:
        salt, expected = _unb64(match.group(4)), _unb64(match.group(5))
        digest = hashlib.scrypt(data, salt=salt, n=2**ln, r=r, p=p, maxmem=2 * need + 1024 * 1024, dklen=len(expected))
    except (ValueError, MemoryError):
        return False
    return hmac.compare_digest(digest, expected)


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #


def _hash_unlocked(password: str) -> str:
    data = _bytes(password)
    if _scheme == "scrypt":
        return _hash_scrypt(data)
    return Argon2id(salt=os.urandom(16), length=32, **ARGON2).derive_phc_encoded(data)


def hash_password(password: str) -> str:
    """A new salted hash of ``password`` in the configured scheme."""
    _acquire()
    try:
        return _hash_unlocked(password)
    finally:
        _GATE.release()


def _verify_unlocked(password: str, stored: str | None) -> bool:
    data = _bytes(password)
    if stored and stored.startswith("$argon2id$"):
        try:
            Argon2id.verify_phc_encoded(data, stored)
            return True
        except (InvalidKey, UnsupportedAlgorithm, ValueError):
            return False
    if stored and stored.startswith("$scrypt$"):
        return _verify_scrypt(data, stored)
    # No usable hash: still spend the time of one hash so timing does not tell.
    _hash_unlocked(password)
    return False


def verify_password(password: str, stored: str | None) -> bool:
    """Constant-work check of ``password`` against a stored hash (False for None or malformed)."""
    _acquire()
    try:
        return _verify_unlocked(password, stored)
    finally:
        _GATE.release()


async def verify_password_async(password: str, stored: str | None) -> bool:
    """:func:`verify_password` for async routes: waits for a slot on the event loop, hashes in a thread."""
    await _acquire_async()
    try:
        # Not cancellable: if the client goes away, the slot is released only once the hash is done.
        return await anyio.to_thread.run_sync(_verify_unlocked, password, stored)
    finally:
        _GATE.release()


def needs_rehash(stored: str | None) -> bool:
    """True when ``stored`` is not in the configured scheme with today's parameters."""
    if not stored:
        return True
    if _scheme == "scrypt":
        match = _SCRYPT.match(stored)
        return match is None or (int(match.group(1)), int(match.group(2)), int(match.group(3))) != (
            SCRYPT["n"].bit_length() - 1, SCRYPT["r"], SCRYPT["p"],
        )
    match = _PHC.match(stored)
    return match is None or tuple(map(int, match.groups())) != (ARGON2["memory_cost"], ARGON2["iterations"], ARGON2["lanes"])


def dummy_hash() -> str:
    """A hash of a random secret in the configured scheme (computed once per process and scheme)."""
    with _dummy_lock:
        value = _dummy.get(_scheme)
        if value is None:
            value = _dummy[_scheme] = hash_password(base64.b64encode(os.urandom(24)).decode("ascii"))
        return value


def self_test() -> None:
    """Hash and verify one password with the configured scheme; raise a clear error if impossible."""
    try:
        stored = hash_password("kidney-health self-test password")
    except UnsupportedAlgorithm:
        raise PasswordBackendUnavailable(ARGON2_MISSING) from None
    if not verify_password("kidney-health self-test password", stored) or verify_password("wrong", stored):
        raise PasswordBackendUnavailable(f"the {_scheme} password self-test failed")
