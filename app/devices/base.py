"""What every connected-device provider offers (design note 27 §2.15; Whoop, note 28, added a module and activity rows).

A provider turns a sign-in at the company into a :class:`TokenSet`, refreshes it, and fetches the person's readings changed since a
cursor as :class:`Reading` rows. It never sees the database or a person's id: the store and the sync do that. Every error is a
:class:`ProviderError` with a short code from :data:`ERROR_CODES` (what the connection keeps and the screen explains); the message
is a constant sentence for the log, never a value from the company's answer.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

# "auth": the company refused the tokens (the person must connect again); "rate_limited": too many requests, wait;
# "unreachable": no answer (network, DNS, a refused address); "provider_error": any other refusal or an answer we could not read;
# "scope": the person did not allow what we need; "account_taken": that company account is connected to someone else here.
ERROR_CODES = ("auth", "rate_limited", "unreachable", "provider_error", "scope", "account_taken")


class ProviderError(Exception):
    def __init__(self, code: str, log_message: str = "") -> None:
        super().__init__(log_message or code)
        self.code = code if code in ERROR_CODES else "provider_error"


@dataclass(frozen=True)
class TokenSet:
    access: str = field(repr=False)
    refresh: str = field(repr=False)
    expires_in: int
    external_user_id: str
    scopes: str


@dataclass(frozen=True)
class Reading:
    """One measure from the company, already in the app's units and on the person's clock."""

    kind: str  # "weight" | "blood_pressure"
    external_id: str  # unique per provider and person, e.g. "<grpid>:weight"
    date: str  # YYYY-MM-DD
    time: str  # HH:MM
    kg: float | None = None
    systolic: int | None = None
    diastolic: int | None = None
    pulse: int | None = None


@dataclass(frozen=True)
class ActivityDay:
    """One Whoop day (a cycle, with its recovery and sleep), on the person's clock (design note 28 §4.3)."""

    external_id: str  # "cycle:<id>"
    date: str  # YYYY-MM-DD
    started_at: str  # UTC
    finished: bool  # False while the person is still in this day
    kcal: int | None = None
    strain: float | None = None
    recovery_pct: int | None = None
    resting_hr: int | None = None
    hrv_ms: float | None = None
    sleep_minutes: int | None = None
    sleep_performance_pct: int | None = None


@dataclass(frozen=True)
class Workout:
    external_id: str  # "workout:<uuid>"
    date: str
    start_time: str  # HH:MM
    end_time: str | None
    minutes: int | None
    sport: str
    kcal: int | None = None
    strain: float | None = None


@dataclass(frozen=True)
class FetchResult:
    readings: list[Reading]
    cursor: str  # what to send as "changed since" next time
    left_out: int = 0  # measures not taken (not certainly this person's, a goal, a type we do not import)
    days: list[ActivityDay] = field(default_factory=list)
    workouts: list[Workout] = field(default_factory=list)
    external_user_id: str | None = None  # the company's id for the person, when the answer named it


class Provider(Protocol):
    id: str
    name: str
    what: tuple[str, ...]  # what is fetched, in words for the consent sheet

    @property
    def available(self) -> bool: ...

    def authorize_url(self, *, state: str, redirect_uri: str) -> str: ...

    def exchange(self, *, code: str, redirect_uri: str) -> TokenSet: ...

    def refresh(self, refresh_token: str) -> TokenSet: ...

    def fetch(self, access_token: str, *, cursor: str | None, since: int) -> FetchResult: ...

    def revoke(self, external_user_id: str, access_token: str | None = None) -> bool: ...

    def about(self) -> dict[str, object]: ...
