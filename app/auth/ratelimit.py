"""In-memory rate limits in one registry (note 07 §9 N13). One process, so memory is enough.

Registered limits (name: requests per window, keyed by the caller):

* ``register``: 3 per client IP per hour (open registration, §4.9)
* ``keys_test``: 10 per user per hour (``PUT /api/me/keys/*`` with ``test``: a key-checking oracle)
* ``export``: 10 per user per hour (``GET /api/me/export.zip``)
* ``ai_probe``: 5 per user per hour (note 04 A5), ``barcode``: 60 per user per hour (note 03)

Login, setup, reset and re-auth have their own layered throttle (:mod:`app.auth.throttle`).
Other notes add theirs with :func:`register_limit` and call :meth:`RateLimits.take`.
"""
from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass

from . import clock
from .errors import too_many

MAX_KEYS = 10_000


@dataclass(frozen=True)
class Limit:
    name: str
    max_requests: int
    window_s: float
    message: str = ""


LIMITS: dict[str, Limit] = {}


def register_limit(name: str, max_requests: int, window_s: float, message: str = "") -> None:
    LIMITS[name] = Limit(name, int(max_requests), float(window_s), message)


register_limit("register", 3, 3600, "Too many new accounts from this address. Try again later.")
register_limit("keys_test", 10, 3600, "Too many key tests. Try again later.")
register_limit("export", 10, 3600, "Too many exports. Try again later.")
register_limit("ai_probe", 5, 3600)
register_limit("barcode", 60, 3600)


class SlidingWindow:
    """At most ``max_requests`` hits per ``window_s`` seconds per key."""

    def __init__(self, max_requests: int, window_s: float) -> None:
        self.max_requests = max_requests
        self.window_s = window_s
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def _prune(self, key: str, now: float) -> deque[float]:
        hits = self._hits.get(key)
        if hits is None:
            if len(self._hits) >= MAX_KEYS:
                self._sweep(now)
            hits = self._hits[key] = deque()
        while hits and now - hits[0] >= self.window_s:
            hits.popleft()
        return hits

    def _sweep(self, now: float) -> None:
        for key in [k for k, v in self._hits.items() if not v or now - v[-1] >= self.window_s]:
            del self._hits[key]

    def retry_after(self, key: str) -> int:
        """Seconds until the next hit is allowed (0 = allowed now). Does not count."""
        now = clock.seconds()
        with self._lock:
            hits = self._prune(key, now)
            if len(hits) < self.max_requests:
                return 0
            return max(1, int(hits[0] + self.window_s - now + 0.999))

    def hit(self, key: str) -> int:
        """Count one hit if allowed; returns 0, or the seconds to wait (nothing counted)."""
        now = clock.seconds()
        with self._lock:
            hits = self._prune(key, now)
            if len(hits) >= self.max_requests:
                return max(1, int(hits[0] + self.window_s - now + 0.999))
            hits.append(now)
            return 0

    def add(self, key: str) -> int:
        """Count one hit unconditionally; returns the number of hits in the window."""
        now = clock.seconds()
        with self._lock:
            hits = self._prune(key, now)
            hits.append(now)
            return len(hits)

    def reset(self, key: str) -> None:
        with self._lock:
            self._hits.pop(key, None)


class RateLimits:
    """The per-app set of windows for :data:`LIMITS` (``app.state.auth.ratelimits``)."""

    def __init__(self) -> None:
        self._windows: dict[str, SlidingWindow] = {}
        self._lock = threading.Lock()

    def window(self, name: str) -> SlidingWindow:
        limit = LIMITS[name]
        with self._lock:
            window = self._windows.get(name)
            if window is None:
                window = self._windows[name] = SlidingWindow(limit.max_requests, limit.window_s)
            return window

    def take(self, name: str, key: str | int | None) -> None:
        """Count one request for ``key`` or raise a 429 ``ApiProblem`` with ``Retry-After``."""
        wait = self.window(name).hit(str(key))
        if wait:
            raise too_many(wait, LIMITS[name].message or None)
