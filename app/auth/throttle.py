"""Sign-in throttling and lock-out (note 07 §4.9 with the §9 N3 and N7 changes).

Layers, checked in this order by the login route:

1. **Per client IP** (memory): ``LOGIN_IP_MAX_FAILURES`` failures in 10 minutes block login, setup,
   register, reset and re-auth from that address for 10 minutes. Skipped when the client address is
   a configured proxy (``TRUSTED_PROXIES``) or a known rootless gateway, because then every client
   shares it and one attacker would lock everybody out (§9 N3 a).
2. **Instance-wide**: 60 attempts per minute; a request waits up to 5 s for a slot instead of being
   refused at once.
3. **Per username** (SQLite ``login_failures``, keyed by an HMAC of the normalised name, never the
   typed text): failures 1–5 free, then ``30 s × 2^(n−6)`` capped at 15 minutes; while delayed the
   password is not checked (429). Success forgets the row. Rows idle for 24 h are pruned; the table
   holds at most 10,000 rows and eviction never removes a delayed row or one with ≥ 5 failures.
4. **Device cookies** (``__Host-kh_device`` / ``kh_device``, one year): a sign-in for account U
   with a valid device cookie for U skips U's username delay and does not count toward the
   100-failure stop; the cookie has its own counter and is void after 10 failures (§9 N3 b).
5. **NIST hard stop** (in the route): 100 consecutive failures on an existing account lock it.
6. **Re-auth**: failures count toward the account's username delay; 5 in a row revoke that session
   (§9 N7).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import logging
import secrets
import sqlite3
import threading
import time
from datetime import timedelta
from typing import TYPE_CHECKING, Callable

from starlette.requests import Request
from starlette.responses import Response

from . import clock
from .ratelimit import SlidingWindow
from .sessions import is_https

if TYPE_CHECKING:  # pragma: no cover
    from ..config import Settings
    from ..crypto import Keyring

log = logging.getLogger("kidney_health.auth.throttle")

NAME_MAC_INFO = "kidney-health/v1/login-failures"
DEVICE_INFO = "kidney-health/v1/device"
DEVICE_HTTPS = "__Host-kh_device"
DEVICE_HTTP = "kh_device"
DEVICE_MAX_AGE = 365 * 86400
DEVICE_MAX_FAILURES = 10

FREE_FAILURES = 5
BASE_DELAY_S = 30
MAX_DELAY_S = 900
HARD_STOP = 100
TABLE_CAP = 10_000
IDLE_PRUNE = timedelta(hours=24)

IP_WINDOW_S = 600
IP_BLOCK_S = 600
GLOBAL_PER_MINUTE = 60
GLOBAL_WAIT_S = 5.0
REAUTH_MAX_FAILURES = 5

# Addresses that stand for "every client" under rootless engines (note 01 §10 S2): slirp4netns's
# host gateway and its rootlesskit port-forwarder source.
GATEWAY_ADDRESSES = ("10.0.2.2", "10.0.2.100")


def delay_for(consecutive: int) -> int:
    """Seconds of delay after ``consecutive`` failures (0 for the first five)."""
    if consecutive <= FREE_FAILURES:
        return 0
    exponent = consecutive - (FREE_FAILURES + 1)
    if exponent >= 10:
        return MAX_DELAY_S
    return min(MAX_DELAY_S, BASE_DELAY_S * 2**exponent)


class TokenBucket:
    """Instance-wide cap: ``rate`` attempts per minute; :meth:`acquire` waits up to ``wait_s``."""

    def __init__(self, per_minute: int = GLOBAL_PER_MINUTE, wait_s: float = GLOBAL_WAIT_S) -> None:
        self.capacity = float(per_minute)
        self.rate = per_minute / 60.0
        self.wait_s = wait_s
        self.tokens = float(per_minute)
        self.updated = time.monotonic()
        self._lock = threading.Lock()

    def _take(self) -> float:
        """Take a token (returns 0) or return the seconds until one is available."""
        with self._lock:
            now = time.monotonic()
            self.tokens = min(self.capacity, self.tokens + (now - self.updated) * self.rate)
            self.updated = now
            if self.tokens >= 1:
                self.tokens -= 1
                return 0.0
            return (1 - self.tokens) / self.rate

    def acquire(self) -> bool:
        deadline = time.monotonic() + self.wait_s
        while True:
            wait = self._take()
            if wait == 0:
                return True
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            time.sleep(min(wait, remaining, 0.25))


class Throttle:
    """Per-app throttle state. ``keyring`` is a callable because the key loads at start-up."""

    def __init__(self, settings: "Settings", keyring: Callable[[], "Keyring"]) -> None:
        self.settings = settings
        self._keyring = keyring
        self.exempt_networks = tuple(
            ipaddress.ip_network(p, strict=False) for p in (*settings.trusted_proxies, *GATEWAY_ADDRESSES)
        )
        self.ip_failures = SlidingWindow(settings.login_ip_max_failures, IP_WINDOW_S)
        self._ip_blocked: dict[str, float] = {}
        self.global_bucket = TokenBucket()
        self._device_failures: dict[str, int] = {}
        self._void_devices: set[str] = set()
        self._reauth_failures: dict[str, int] = {}
        self._lock = threading.Lock()
        self._warned_exempt = False

    # ------------------------------------------------------------------ per IP
    def ip_exempt(self, ip: str | None) -> bool:
        if not ip:
            return True
        try:
            address = ipaddress.ip_address(ip)
        except ValueError:
            return False
        exempt = any(address in net for net in self.exempt_networks)
        if exempt and not self._warned_exempt:
            self._warned_exempt = True
            log.info(
                "sign-in attempts arrive from %s, a proxy or gateway address shared by every client; the per-IP "
                "login limit is skipped for it (per-account delays still apply)",
                ip,
            )
        return exempt

    def ip_wait(self, ip: str | None) -> int:
        if self.ip_exempt(ip):
            return 0
        now = clock.seconds()
        with self._lock:
            until = self._ip_blocked.get(str(ip), 0.0)
            if until <= now:
                self._ip_blocked.pop(str(ip), None)
                return 0
            return max(1, int(until - now + 0.999))

    def ip_failure(self, ip: str | None) -> None:
        if self.ip_exempt(ip):
            return
        count = self.ip_failures.add(str(ip))
        if count >= self.settings.login_ip_max_failures:
            with self._lock:
                self._ip_blocked[str(ip)] = clock.seconds() + IP_BLOCK_S
            self.ip_failures.reset(str(ip))

    # ------------------------------------------------------------------ instance-wide
    def global_acquire(self) -> bool:
        return self.global_bucket.acquire()

    # ------------------------------------------------------------------ per username (SQLite)
    def name_mac(self, username_norm: str) -> bytes:
        return self._keyring().mac(NAME_MAC_INFO, username_norm)

    def username_wait(self, conn: sqlite3.Connection, mac: bytes) -> int:
        """Seconds the name must wait before its password is checked again (0 = go ahead)."""
        now = clock.now()
        row = conn.execute("SELECT locked_until FROM login_failures WHERE name_mac = ?", (mac,)).fetchone()
        if row is not None:
            until = clock.parse(row["locked_until"])
            if until is not None and until > now:
                return max(1, int((until - now).total_seconds() + 0.999))
            return 0
        if self._table_full(conn, now) and not self._evictable(conn, now):
            return BASE_DELAY_S  # §9.1: answer a new name with the delay rather than evict a victim's row
        return 0

    def consecutive(self, conn: sqlite3.Connection, mac: bytes) -> int:
        row = conn.execute("SELECT consecutive FROM login_failures WHERE name_mac = ?", (mac,)).fetchone()
        return int(row["consecutive"]) if row else 0

    def record_failure(self, conn: sqlite3.Connection, mac: bytes) -> int:
        """Count a failure for the name; returns the consecutive count (0 if it could not be stored)."""
        now = clock.now()
        row = conn.execute("SELECT consecutive FROM login_failures WHERE name_mac = ?", (mac,)).fetchone()
        count = (int(row["consecutive"]) if row else 0) + 1
        delay = delay_for(count)
        until = clock.iso(now + timedelta(seconds=delay)) if delay else None
        if row is not None:
            conn.execute(
                "UPDATE login_failures SET consecutive = ?, locked_until = ?, last_failure_at = ? WHERE name_mac = ?",
                (count, until, clock.iso(now), mac),
            )
            return count
        if self._table_full(conn, now):
            self.prune(conn)
            if self._table_full(conn, now) and not self._evict_one(conn, now):
                return 0
        conn.execute(
            "INSERT INTO login_failures (name_mac, consecutive, locked_until, last_failure_at) VALUES (?, ?, ?, ?)",
            (mac, count, until, clock.iso(now)),
        )
        return count

    def forget(self, conn: sqlite3.Connection, mac: bytes) -> None:
        conn.execute("DELETE FROM login_failures WHERE name_mac = ?", (mac,))

    def prune(self, conn: sqlite3.Connection) -> int:
        """Delete rows idle for 24 hours that are not currently delayed (no commit)."""
        now = clock.now()
        cur = conn.execute(
            "DELETE FROM login_failures WHERE last_failure_at < ? AND (locked_until IS NULL OR locked_until <= ?)",
            (clock.iso(now - IDLE_PRUNE), clock.iso(now)),
        )
        return int(cur.rowcount or 0)

    @staticmethod
    def _table_full(conn: sqlite3.Connection, now: object = None) -> bool:
        return int(conn.execute("SELECT COUNT(*) FROM login_failures").fetchone()[0]) >= TABLE_CAP

    @staticmethod
    def _evictable(conn: sqlite3.Connection, now: object) -> bool:
        row = conn.execute(
            "SELECT 1 FROM login_failures WHERE consecutive < ? AND (locked_until IS NULL OR locked_until <= ?) LIMIT 1",
            (FREE_FAILURES, clock.iso(clock.now())),
        ).fetchone()
        return row is not None

    @staticmethod
    def _evict_one(conn: sqlite3.Connection, now: object) -> bool:
        cur = conn.execute(
            """DELETE FROM login_failures WHERE name_mac = (
                 SELECT name_mac FROM login_failures
                 WHERE consecutive < ? AND (locked_until IS NULL OR locked_until <= ?)
                 ORDER BY last_failure_at LIMIT 1)""",
            (FREE_FAILURES, clock.iso(clock.now())),
        )
        return (cur.rowcount or 0) > 0

    # ------------------------------------------------------------------ device cookies
    def _device_mac(self, user_id: int, nonce: str) -> str:
        key = self._keyring().subkey(DEVICE_INFO)
        digest = hmac.new(key, f"{int(user_id)}.{nonce}".encode("ascii"), hashlib.sha256).digest()
        return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")

    def new_device_cookie(self, user_id: int) -> str:
        nonce = secrets.token_urlsafe(16)
        return f"{int(user_id)}.{nonce}.{self._device_mac(user_id, nonce)}"

    def device_nonce(self, value: str | None, user_id: int) -> str | None:
        """The nonce of a valid, non-void device cookie for ``user_id`` (else None)."""
        if not value or len(value) > 200 or value.count(".") != 2:
            return None
        uid, nonce, mac = value.split(".")
        if uid != str(int(user_id)) or not nonce:
            return None
        if not hmac.compare_digest(mac, self._device_mac(user_id, nonce)):
            return None
        with self._lock:
            if nonce in self._void_devices:
                return None
        return nonce

    def device_failure(self, nonce: str) -> None:
        with self._lock:
            count = self._device_failures.get(nonce, 0) + 1
            self._device_failures[nonce] = count
            if count >= DEVICE_MAX_FAILURES:
                self._void_devices.add(nonce)
                self._device_failures.pop(nonce, None)

    def device_success(self, nonce: str) -> None:
        with self._lock:
            self._device_failures.pop(nonce, None)

    @staticmethod
    def device_cookie_name(request: Request) -> str:
        return DEVICE_HTTPS if is_https(request) else DEVICE_HTTP

    def read_device_cookie(self, request: Request) -> str | None:
        return request.cookies.get(self.device_cookie_name(request))

    def set_device_cookie(self, response: Response, request: Request, user_id: int) -> None:
        https = is_https(request)
        response.set_cookie(
            self.device_cookie_name(request),
            self.new_device_cookie(user_id),
            max_age=DEVICE_MAX_AGE,
            path="/",
            secure=https,
            httponly=True,
            samesite="strict",
        )

    # ------------------------------------------------------------------ re-auth
    def reauth_failure(self, session_id: str) -> int:
        with self._lock:
            count = self._reauth_failures.get(session_id, 0) + 1
            self._reauth_failures[session_id] = count
            return count

    def reauth_reset(self, session_id: str) -> None:
        with self._lock:
            self._reauth_failures.pop(session_id, None)
