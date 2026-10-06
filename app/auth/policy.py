"""Password policy for new passwords (note 07 §4.6; NIST SP 800-63B-4 §3.1.1.2).

* NFC-normalised; length counted in Unicode code points; at least ``PASSWORD_MIN_LENGTH`` (15 by
  default: the NIST minimum when a password is the only factor) and at most 128.
* No composition rules, no expiry, no hints, no security questions.
* The **whole** password (casefolded) is compared with a blocklist: the most common 10,000 entries of
  8 characters or more from the UK NCSC top-100k list (``password-blocklist.txt.gz``, built by
  ``scripts/build_password_blocklist.py``, which records the source URL and SHA-256), plus context
  words (the username, the display name, the app and instance names), one repeated character and
  straight runs along a keyboard row or the alphabet/digits (``123456789012345``,
  ``qwertyuiopasdfg``).
* With ``PASSWORD_BREACH_CHECK=true``, the Have I Been Pwned k-anonymity range API (only the first
  five hex digits of the SHA-1 leave the server; padding on). Network errors are ignored (fail open).
"""
from __future__ import annotations

import gzip
import hashlib
import logging
import unicodedata
from functools import lru_cache
from pathlib import Path

log = logging.getLogger("kidney_health.auth.policy")

MAX_LENGTH = 128
BLOCKLIST_PATH = Path(__file__).resolve().parent / "password-blocklist.txt.gz"
HIBP_URL = "https://api.pwnedpasswords.com/range/"
HIBP_TIMEOUT_S = 3.0

APP_WORDS = ("kidneyhealth", "kidney health", "kidney-health", "kidney_health", "kidney health food log")

# Straight runs: the password must not be a substring of any of these (forwards or backwards,
# wrapping around), e.g. 123456789012345, qwertyuiopasdfg, abcdefghijklmno.
SEQUENCES = (
    "abcdefghijklmnopqrstuvwxyz",
    "0123456789",
    "qwertyuiopasdfghjklzxcvbnm",
    "qwertzuiopasdfghjklyxcvbnm",
    "azertyuiopqsdfghjklmwxcvbn",
    "1qaz2wsx3edc4rfv5tgb6yhn7ujm8ik9ol0p",
    "qazwsxedcrfvtgbyhnujmikolp",
    "1234567890qwertyuiopasdfghjklzxcvbnm",
    "!@#$%^&*()",
)

MSG_TOO_SHORT = "Use at least {n} characters. A short sentence or three or four unrelated words works well."
MSG_TOO_LONG = "Use at most 128 characters."
MSG_COMMON = "This password is too common or too easy to guess. Choose something else."
MSG_CONTEXT = "Do not use your username, your name or the app's name as the password."
MSG_PATTERN = "Avoid one repeated character or a straight run of keys, letters or digits."
MSG_BREACHED = "This password has appeared in a data breach. Choose a different one."


@lru_cache(maxsize=1)
def blocklist() -> frozenset[str]:
    try:
        text = gzip.decompress(BLOCKLIST_PATH.read_bytes()).decode("utf-8")
    except OSError:
        log.error("password blocklist %s is missing; only the other checks apply", BLOCKLIST_PATH)
        return frozenset()
    return frozenset(line for line in text.splitlines() if line)


def _fold(value: str) -> str:
    return unicodedata.normalize("NFC", value or "").casefold()


def _squash(value: str) -> str:
    return "".join(ch for ch in value if ch.isalnum())


def is_straight_run(folded: str) -> bool:
    if len(folded) < 3:
        return False
    for seq in SEQUENCES:
        for candidate in (seq, seq[::-1]):
            repeated = candidate * (len(folded) // len(candidate) + 2)
            if folded in repeated:
                return True
    return False


def breached(password: str) -> bool:
    """HIBP range lookup; False on any network problem (fail open, logged at INFO)."""
    # SHA-1 here is the Pwned Passwords range API's lookup format (k-anonymity: only the first five hex
    # characters leave the server), not a way of storing or verifying passwords; those use Argon2id.
    digest = hashlib.sha1(password.encode("utf-8"), usedforsecurity=False).hexdigest().upper()
    prefix, suffix = digest[:5], digest[5:]
    try:
        import httpx2

        with httpx2.Client(timeout=HIBP_TIMEOUT_S, headers={"Add-Padding": "true", "User-Agent": "kidney-health"}) as client:
            response = client.get(HIBP_URL + prefix)
    except Exception as exc:  # network errors never block a password change
        log.info("password breach check skipped: %s", exc.__class__.__name__)
        return False
    if response.status_code != 200:
        log.info("password breach check skipped: HTTP %s", response.status_code)
        return False
    for line in response.text.splitlines():
        hash_suffix, _, count = line.strip().partition(":")
        if hash_suffix.upper() == suffix:
            try:
                return int(count) > 0
            except ValueError:
                return False
    return False


def validate_new_password(
    password: str,
    *,
    username: str = "",
    display_name: str = "",
    instance_name: str = "",
    min_length: int = 15,
    breach_check: bool = False,
) -> list[str]:
    """Messages explaining why ``password`` is refused (an empty list means it is acceptable)."""
    pw = unicodedata.normalize("NFC", password or "")
    length = len(pw)
    if length < min_length:
        return [MSG_TOO_SHORT.format(n=min_length)]
    if length > MAX_LENGTH:
        return [MSG_TOO_LONG]
    folded = pw.casefold()
    problems: list[str] = []
    context = {_fold(w) for w in (username, display_name, instance_name, *APP_WORDS) if w and w.strip()}
    if folded in context or _squash(folded) in {_squash(c) for c in context if _squash(c)}:
        problems.append(MSG_CONTEXT)
    elif folded in blocklist():
        problems.append(MSG_COMMON)
    if len(set(folded)) == 1 or is_straight_run(folded):
        problems.append(MSG_PATTERN)
    if not problems and breach_check and breached(pw):
        problems.append(MSG_BREACHED)
    return problems
