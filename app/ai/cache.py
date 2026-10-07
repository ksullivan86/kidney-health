"""The 10-minute reuse of a meal's AI answer (note 06 §4.13).

"The AI result is cached per (user, date, meal, rules hash) for 10 minutes so re-rendering does not
re-call the provider." Opening *What fits now* again, switching *AI order* off and on, or re-opening a
plan would otherwise send the same data again and spend the person's shared daily calls each time.

What is kept, and for how long:

* only ``POST /api/ai/next-meal`` answers (the guidance modes: ideas, rerank, swap, plan) whose checked
  verdict was ``ok``: a fallback ("did not fit", an error, a refusal) is not kept, so asking again really
  asks again;
* the provider's **parsed answer**, never the verdict: on a hit the rules check it again against the
  person's current day (``Prepared.judge``), so nothing unchecked or stale is ever shown;
* in this process's memory only, for :data:`TTL_S` seconds, at most :data:`MAX_ENTRIES` answers (the
  oldest goes first). Nothing is written to disk; a restart empties it.

The key holds the person, the provider row and its scope, the feature and mode, the prompt version, the
guidance rules hash and the SHA-256 of the exact request body. The body carries the date, the meal, the
room and the candidate foods, so logging, editing or deleting food that changes what would be sent is
a different key: the answer is never reused for a question it did not answer. A person who deletes their
AI activity or withdraws consent loses their kept answers at once (:meth:`AnswerCache.drop_user`).
"""
from __future__ import annotations

import copy
import hashlib
import json
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Callable

TTL_S = 600.0  # note 06 §4.13: 10 minutes
MAX_ENTRIES = 256

CacheKey = tuple[Any, ...]


@dataclass(frozen=True)
class CachedAnswer:
    """A provider answer that passed the rules, and the AI activity row of the call that produced it."""

    parsed: Any
    audit_id: int
    stored_at: float

    def fresh_copy(self) -> Any:
        """A deep copy for the judge, so a judge can never change what later hits see."""
        return copy.deepcopy(self.parsed)


def body_digest(body: Any) -> str:
    """SHA-256 of the request body in a canonical JSON form (key order does not matter)."""
    text = json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class AnswerCache:
    """A small, thread-safe TTL map from :data:`CacheKey` to :class:`CachedAnswer`."""

    def __init__(self, ttl_s: float = TTL_S, max_entries: int = MAX_ENTRIES,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.ttl_s = float(ttl_s)
        self.max_entries = int(max_entries)
        self._clock = clock
        self._lock = threading.Lock()
        self._items: OrderedDict[CacheKey, CachedAnswer] = OrderedDict()

    @staticmethod
    def key(user_id: int, provider_id: int, scope: str, feature: str, mode: str | None, prompt_version: str,
            rules_hash: str, body: Any) -> CacheKey:
        return (int(user_id), int(provider_id), str(scope), str(feature), mode, str(prompt_version), str(rules_hash),
                body_digest(body))

    def get(self, key: CacheKey) -> CachedAnswer | None:
        """The kept answer for ``key``, or ``None`` when there is none or it is older than the TTL."""
        now = self._clock()
        with self._lock:
            self._expire(now)
            return self._items.get(key)

    def put(self, key: CacheKey, parsed: Any, audit_id: int) -> None:
        now = self._clock()
        with self._lock:
            self._expire(now)
            self._items.pop(key, None)
            self._items[key] = CachedAnswer(copy.deepcopy(parsed), int(audit_id), now)
            while len(self._items) > self.max_entries:
                self._items.popitem(last=False)

    def drop_user(self, user_id: int) -> int:
        """Forget every answer kept for ``user_id``; returns how many were dropped."""
        with self._lock:
            gone = [k for k in self._items if k[0] == int(user_id)]
            for k in gone:
                del self._items[k]
            return len(gone)

    def __len__(self) -> int:
        with self._lock:
            self._expire(self._clock())
            return len(self._items)

    def _expire(self, now: float) -> None:
        # Insertion order is age order (``put`` re-inserts), so the stale entries are at the front.
        while self._items:
            first_key, first = next(iter(self._items.items()))
            if now - first.stored_at < self.ttl_s:
                break
            del self._items[first_key]
