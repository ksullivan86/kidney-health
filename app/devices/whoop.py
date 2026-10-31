"""Whoop: calories burned, strain, recovery, resting heart rate, HRV, sleep and workouts (design note 28, checked 2026-10-31).

* The person's browser goes to ``api.prod.whoop.com/oauth/oauth2/auth`` with the scopes ``offline read:cycles read:recovery
  read:sleep read:workout`` and the state. We never ask for ``read:profile`` (name, email) or ``read:body_measurement``.
* The server talks only to ``api.prod.whoop.com``: the token request (``/oauth/oauth2/token``, form-encoded, the client id and
  secret in the form), the four v2 collections (``/developer/v2/cycle``, ``/recovery``, ``/activity/sleep``,
  ``/activity/workout``, 25 records a page, ``nextToken``) and, on Disconnect, ``DELETE /developer/v2/user/access``. Every request
  goes through :class:`app.egress.CheckedTransport`: the address is checked when the request is made, redirects are never followed,
  at most 2 MiB is read and a request gives up after 15 seconds.
* Each refresh returns a new refresh token and ends the old one at once, so the sync keeps the new pair before anything else.
* Energy comes in kilojoules: kcal = kJ ÷ 4.184, half up to a whole kcal. A cycle runs from falling asleep to the next sleep; it
  belongs to the date 12 hours after it starts, on the person's clock (``timezone_offset``). The cycle the person is in now has no
  ``end``: its numbers grow all day, and the next sync replaces them.
* Only scored records (``score_state`` ``SCORED``) give numbers; naps are left out of sleep; a value outside a plausible range is
  left empty.

Nothing here logs or keeps a token, a code, the state or the client secret; log lines are constant sentences.
"""
from __future__ import annotations

import json
import logging
import re
import time as _time
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Callable
from urllib.parse import urlencode

import httpx2

from .. import brand, egress
from ..config import WhoopEnv
from .base import ActivityDay, FetchResult, ProviderError, TokenSet, Workout

log = logging.getLogger(f"{brand.LOGGER_NAME}.devices.whoop")

ID = "whoop"
NAME = "Whoop"
API_HOST = "api.prod.whoop.com"
AUTHORIZE_URL = f"https://{API_HOST}/oauth/oauth2/auth"
TOKEN_URL = f"https://{API_HOST}/oauth/oauth2/token"
API_BASE = f"https://{API_HOST}/developer"
CYCLES, RECOVERY, SLEEP, WORKOUTS = "/v2/cycle", "/v2/recovery", "/v2/activity/sleep", "/v2/activity/workout"
REVOKE_PATH = "/v2/user/access"
SCOPE = "offline read:cycles read:recovery read:sleep read:workout"
REQUIRED_SCOPE = "read:cycles"  # calories and strain: without it there is nothing to show
HTTP_TIMEOUT_S = 15.0
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
PAGE_LIMIT = 25  # Whoop's most per page
MAX_PAGES = 40  # per collection and sync: 1000 records
MAX_TOKEN_CHARS = 4096
FIRST_DAYS = 90  # the first sync reaches this far back (the quiet-day level needs 28)
OVERLAP_S = 3 * 86400  # later syncs look again at the last 3 days: late scores, the day still going on
KJ_PER_KCAL = Decimal("4.184")
DAY_SHIFT = timedelta(hours=12)
SCORED = "SCORED"

RANGES = {"kcal": (1, 15000), "strain": (0, 21), "recovery_pct": (0, 100), "resting_hr": (20, 250), "hrv_ms": (1, 500),
          "sleep_minutes": (0, 1440), "sleep_performance_pct": (0, 100), "workout_minutes": (0, 1440)}
_OFFSET = re.compile(r"^([+-])(\d{2}):?(\d{2})$")
_WORKOUT_ID = re.compile(r"^[0-9A-Za-z-]{1,64}$")
_SPORT = re.compile(r"[^0-9A-Za-z ()/&+'.]+")


# --------------------------------------------------------------------------- #
# Reading Whoop's answers
# --------------------------------------------------------------------------- #


def _number(value: Any) -> Decimal | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        d = Decimal(str(value))
    except InvalidOperation:  # pragma: no cover - str() of a finite number always parses
        return None
    return d if d.is_finite() else None


def _within(name: str, value: Decimal | None) -> Decimal | None:
    lo, hi = RANGES[name]
    return value if value is not None and lo <= value <= hi else None


def _whole(value: Decimal | None) -> int | None:
    return None if value is None else int(value.quantize(Decimal(1), rounding="ROUND_HALF_UP"))


def _tenth(value: Decimal | None) -> float | None:
    return None if value is None else float(value.quantize(Decimal("0.1"), rounding="ROUND_HALF_UP"))


def kcal_from_kj(kilojoule: Any) -> int | None:
    """Whole kcal (half up) of a kilojoule figure, or None when it is not a plausible day or workout."""
    kj = _number(kilojoule)
    if kj is None:
        return None
    return _whole(_within("kcal", (kj / KJ_PER_KCAL).quantize(Decimal(1), rounding="ROUND_HALF_UP")))


def parse_time(value: Any) -> datetime | None:
    """A Whoop timestamp (ISO 8601, UTC) as an aware datetime, or None."""
    if not isinstance(value, str) or not 10 <= len(value) <= 40:
        return None
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment.astimezone(timezone.utc) if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def parse_offset(value: Any) -> timezone:
    """``+hh:mm``, ``-hh:mm`` or ``Z`` as a fixed zone; UTC for anything else."""
    if isinstance(value, str):
        m = _OFFSET.match(value.strip())
        if m:
            hours, minutes = int(m.group(2)), int(m.group(3))
            if hours <= 14 and minutes < 60:
                delta = timedelta(hours=hours, minutes=minutes)
                return timezone(-delta if m.group(1) == "-" else delta)
    return timezone.utc


def day_of_cycle(start: datetime, zone: timezone) -> str:
    """The date a cycle belongs to: 12 hours after it starts, on the person's clock (note 28 §4.3)."""
    return (start.astimezone(zone) + DAY_SHIFT).strftime("%Y-%m-%d")


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _scored(record: dict[str, Any]) -> dict[str, Any] | None:
    score = record.get("score")
    return score if record.get("score_state") == SCORED and isinstance(score, dict) else None


def _whole_id(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def sport_label(value: Any) -> str:
    """A short, plain sport name from Whoop's ``sport_name`` (``functional-fitness`` → ``functional fitness``)."""
    if not isinstance(value, str):
        return ""
    text = _SPORT.sub(" ", value.replace("-", " ").replace("_", " "))
    return " ".join(text.split())[:40]


def build_days(cycles: list[Any], recoveries: list[Any], sleeps: list[Any]) -> tuple[list[ActivityDay], int, str | None]:
    """Join cycles with their recovery and sleep into days. Returns the days, how many records were left out and the person's
    Whoop id (from the first record that names it)."""
    left_out = 0
    user_id: str | None = None
    base: dict[int, dict[str, Any]] = {}
    for c in cycles:
        if not isinstance(c, dict):
            left_out += 1
            continue
        cid, start = _whole_id(c.get("id")), parse_time(c.get("start"))
        if cid is None or start is None:
            left_out += 1
            continue
        if user_id is None and _whole_id(c.get("user_id")):
            user_id = str(c["user_id"])
        zone = parse_offset(c.get("timezone_offset"))
        score = _scored(c) or {}
        base[cid] = {"date": day_of_cycle(start, zone), "start": start, "finished": parse_time(c.get("end")) is not None,
                     "kcal": kcal_from_kj(score.get("kilojoule")), "strain": _tenth(_within("strain", _number(score.get("strain"))))}
        if not score:
            left_out += 1  # not scored yet: the next sync looks again
    for r in recoveries:
        score = _scored(r) if isinstance(r, dict) else None
        cid = _whole_id(r.get("cycle_id")) if isinstance(r, dict) else None
        if score is None or cid not in base:
            left_out += 1
            continue
        base[cid]["recovery_pct"] = _whole(_within("recovery_pct", _number(score.get("recovery_score"))))
        base[cid]["resting_hr"] = _whole(_within("resting_hr", _number(score.get("resting_heart_rate"))))
        base[cid]["hrv_ms"] = _tenth(_within("hrv_ms", _number(score.get("hrv_rmssd_milli"))))
    for s in sleeps:
        score = _scored(s) if isinstance(s, dict) else None
        cid = _whole_id(s.get("cycle_id")) if isinstance(s, dict) else None
        if score is None or cid not in base or s.get("nap") is True:
            left_out += 1
            continue
        stages = score.get("stage_summary") if isinstance(score.get("stage_summary"), dict) else {}
        parts = [_number(stages.get(k)) for k in ("total_light_sleep_time_milli", "total_slow_wave_sleep_time_milli",
                                                   "total_rem_sleep_time_milli")]
        if all(p is not None and p >= 0 for p in parts):
            asleep = sum(parts, Decimal(0)) / 60000 + Decimal(base[cid].get("_asleep", 0))
            base[cid]["_asleep"] = asleep
            base[cid]["sleep_minutes"] = _whole(_within("sleep_minutes", asleep))
        perf = _whole(_within("sleep_performance_pct", _number(score.get("sleep_performance_percentage"))))
        if perf is not None:
            base[cid]["sleep_performance_pct"] = perf
    by_date: dict[str, tuple[int, dict[str, Any]]] = {}
    for cid, d in base.items():
        if not any(d.get(k) is not None for k in ("kcal", "strain", "recovery_pct", "resting_hr", "hrv_ms", "sleep_minutes",
                                                   "sleep_performance_pct")):
            continue
        kept = by_date.get(d["date"])
        if kept is None or d["start"] > kept[1]["start"]:
            if kept is not None:
                left_out += 1
            by_date[d["date"]] = (cid, d)
        else:
            left_out += 1  # two cycles on one date: the one that started later is kept
    days = [ActivityDay(f"cycle:{cid}", d["date"], _iso(d["start"]), d["finished"], kcal=d.get("kcal"), strain=d.get("strain"),
                        recovery_pct=d.get("recovery_pct"), resting_hr=d.get("resting_hr"), hrv_ms=d.get("hrv_ms"),
                        sleep_minutes=d.get("sleep_minutes"), sleep_performance_pct=d.get("sleep_performance_pct"))
            for cid, d in sorted(by_date.values(), key=lambda item: item[1]["date"])]
    return days, left_out, user_id


def build_workouts(records: list[Any]) -> tuple[list[Workout], int]:
    out: list[Workout] = []
    left_out = 0
    for w in records:
        score = _scored(w) if isinstance(w, dict) else None
        wid = w.get("id") if isinstance(w, dict) else None
        start = parse_time(w.get("start")) if isinstance(w, dict) else None
        if score is None or not isinstance(wid, str) or not _WORKOUT_ID.match(wid) or start is None:
            left_out += 1
            continue
        zone = parse_offset(w.get("timezone_offset"))
        end = parse_time(w.get("end"))
        local = start.astimezone(zone)
        minutes = None
        if end is not None and end >= start:
            minutes = _whole(_within("workout_minutes", Decimal((end - start).total_seconds()) / 60))
            if minutes is None:
                left_out += 1
                continue
        out.append(Workout(f"workout:{wid.lower()}", local.strftime("%Y-%m-%d"), local.strftime("%H:%M"),
                           end.astimezone(zone).strftime("%H:%M") if end is not None else None, minutes,
                           sport_label(w.get("sport_name")), kcal=kcal_from_kj(score.get("kilojoule")),
                           strain=_tenth(_within("strain", _number(score.get("strain"))))))
    return out, left_out


def _token_text(value: Any) -> str | None:
    return value if isinstance(value, str) and 0 < len(value) <= MAX_TOKEN_CHARS and value.isprintable() else None


# --------------------------------------------------------------------------- #
# The provider
# --------------------------------------------------------------------------- #


class WhoopProvider:
    """The server's Whoop app (``WHOOP_*``). ``resolver``, ``direct`` and ``use_env_proxy`` exist for tests (a fake Whoop behind
    the real checked transport)."""

    id = ID
    name = NAME
    what = ("calories burned", "strain", "recovery", "resting heart rate", "heart rate variability (HRV)", "sleep", "workouts")
    first_days = FIRST_DAYS

    def __init__(self, env: WhoopEnv, *, resolver: Callable[[str, int], list[str]] | None = None,
                 direct: httpx2.BaseTransport | None = None, use_env_proxy: bool = True,
                 clock: Callable[[], float] = _time.time) -> None:
        self.env = env
        self.resolver = resolver
        self.direct = direct
        self.use_env_proxy = use_env_proxy
        self.clock = clock

    @property
    def available(self) -> bool:
        return self.env.configured

    def about(self) -> dict[str, object]:
        return {"id": ID, "name": NAME, "enabled": self.env.enabled, "client_id": self.env.client_id,
                "secret": "set" if self.env.secret_set else "not set", "hosts": [API_HOST]}

    # ------------------------------------------------------------------ HTTP
    def _client(self) -> httpx2.Client:
        transport = egress.CheckedTransport(allow_private=False, resolver=self.resolver, use_env_proxy=self.use_env_proxy,
                                            direct=self.direct)
        return httpx2.Client(transport=transport, timeout=HTTP_TIMEOUT_S, follow_redirects=False, trust_env=False,
                             headers={"User-Agent": brand.USER_AGENT_DEVICES, "Accept": "application/json"})

    def _send(self, method: str, url: str, *, form: dict[str, str] | None = None, bearer: str | None = None,
              params: dict[str, str] | None = None) -> tuple[int, Any]:
        """``(HTTP status, parsed JSON or None)``; raises :class:`ProviderError` ("unreachable" or "provider_error")."""
        headers = {"Authorization": f"Bearer {bearer}"} if bearer else {}
        try:
            with self._client() as client, client.stream(method, url, data=form, params=params, headers=headers) as response:
                raw = egress.read_capped(response, MAX_RESPONSE_BYTES)
                http_status = response.status_code
        except egress.BlockedAddress:
            log.warning("Whoop: the server refused to connect (the address is not allowed or does not resolve)")
            raise ProviderError("unreachable", "blocked") from None
        except egress.ResponseTooLarge:
            log.warning("Whoop: the answer was too large")
            raise ProviderError("provider_error", "too_large") from None
        except httpx2.HTTPError:
            log.warning("Whoop: no answer")
            raise ProviderError("unreachable", "no_answer") from None
        try:
            data = json.loads(raw) if raw else None
        except ValueError:
            data = None
        return http_status, data

    # ------------------------------------------------------------------ sign-in
    def authorize_url(self, *, state: str, redirect_uri: str) -> str:
        query = {"response_type": "code", "client_id": self.env.client_id or "", "redirect_uri": redirect_uri, "scope": SCOPE,
                 "state": state}
        return f"{AUTHORIZE_URL}?{urlencode(query)}"

    def _token_set(self, status: int, data: Any, *, refreshing: bool, external_user_id: str = "") -> TokenSet:
        if status == 429:
            raise ProviderError("rate_limited", "http_429")
        if status != 200:
            # A refresh token that no longer works (revoked, or already used once) is "connect again"; a failed code exchange
            # is simply a failed sign-in.
            raise ProviderError("auth" if refreshing and status in (400, 401, 403) else "provider_error", "token_refused")
        body = data if isinstance(data, dict) else {}
        access, refresh = _token_text(body.get("access_token")), _token_text(body.get("refresh_token"))
        if access is None or refresh is None:
            raise ProviderError("provider_error", "token_answer")
        expires = body.get("expires_in")
        if not isinstance(expires, int) or isinstance(expires, bool) or expires <= 0:
            expires = 3600
        scopes = body.get("scope") if isinstance(body.get("scope"), str) else ""
        return TokenSet(access, refresh, min(int(expires), 86400 * 30), external_user_id, " ".join(scopes.split()))

    def _first_user_id(self, access: str) -> str:
        """Whoop's id for the person, from their newest cycle (the token answer has none and we never ask for the profile).
        Empty when they have no cycle yet or Whoop did not answer: the first sync fills it in."""
        try:
            status, data = self._send("GET", API_BASE + CYCLES, bearer=access, params={"limit": "1"})
        except ProviderError:
            return ""
        records = data.get("records") if status == 200 and isinstance(data, dict) else None
        if isinstance(records, list) and records and isinstance(records[0], dict) and _whole_id(records[0].get("user_id")):
            return str(records[0]["user_id"])
        return ""

    def exchange(self, *, code: str, redirect_uri: str) -> TokenSet:
        status, data = self._send("POST", TOKEN_URL, form={"grant_type": "authorization_code", "code": code,
                                                           "redirect_uri": redirect_uri, "client_id": self.env.client_id or "",
                                                           "client_secret": self.env.client_secret or ""})
        tokens = self._token_set(status, data, refreshing=False)
        granted = tokens.scopes.split()
        if granted and REQUIRED_SCOPE not in granted:
            raise ProviderError("scope", "no_cycles")
        return TokenSet(tokens.access, tokens.refresh, tokens.expires_in, self._first_user_id(tokens.access), tokens.scopes)

    def refresh(self, refresh_token: str) -> TokenSet:
        status, data = self._send("POST", TOKEN_URL, form={"grant_type": "refresh_token", "refresh_token": refresh_token,
                                                           "client_id": self.env.client_id or "",
                                                           "client_secret": self.env.client_secret or "", "scope": "offline"})
        return self._token_set(status, data, refreshing=True)

    # ------------------------------------------------------------------ data
    def _collect(self, path: str, access: str, start: str, *, optional: bool) -> list[Any]:
        """Every record of one collection that started from ``start``, following ``next_token`` up to :data:`MAX_PAGES`."""
        records: list[Any] = []
        next_token: str | None = None
        for _page in range(MAX_PAGES):
            params = {"limit": str(PAGE_LIMIT), "start": start}
            if next_token:
                params["nextToken"] = next_token
            status, data = self._send("GET", API_BASE + path, bearer=access, params=params)
            if status == 401:
                raise ProviderError("auth", "data_refused")
            if status == 429:
                raise ProviderError("rate_limited", "http_429")
            if status == 403 and optional:
                return []  # the person did not allow this kind of data
            if status == 403:
                raise ProviderError("scope", "no_cycles")
            if status != 200 or not isinstance(data, dict):
                log.warning("Whoop: a data request was refused")
                raise ProviderError("provider_error", "data_status")
            page = data.get("records")
            if isinstance(page, list):
                records += page
            token = data.get("next_token")
            if not isinstance(token, str) or not token or len(token) > 1024 or token == next_token:
                break
            next_token = token
        return records

    def fetch(self, access_token: str, *, cursor: str | None, since: int) -> FetchResult:
        """Days and workouts that started from 3 days before the last sync (``cursor``, a Unix time) or, the first time, from
        ``since``."""
        now = int(self.clock())
        start_epoch = int(cursor) - OVERLAP_S if cursor and cursor.isdigit() else since
        start = _iso(datetime.fromtimestamp(max(0, start_epoch), tz=timezone.utc))
        cycles = self._collect(CYCLES, access_token, start, optional=False)
        recoveries = self._collect(RECOVERY, access_token, start, optional=True)
        sleeps = self._collect(SLEEP, access_token, start, optional=True)
        workouts_raw = self._collect(WORKOUTS, access_token, start, optional=True)
        days, left_days, user_id = build_days(cycles, recoveries, sleeps)
        workouts, left_workouts = build_workouts(workouts_raw)
        return FetchResult([], str(now), left_days + left_workouts, days=days, workouts=workouts, external_user_id=user_id)

    # ------------------------------------------------------------------ disconnect
    def revoke(self, external_user_id: str, access_token: str | None = None) -> bool:
        """Ask Whoop to end this app's access (``DELETE /v2/user/access`` with the person's token). True when Whoop said yes;
        any failure returns False (the tokens are deleted here either way)."""
        if not access_token:
            return False
        try:
            status, _ = self._send("DELETE", API_BASE + REVOKE_PATH, bearer=access_token)
        except ProviderError:
            return False
        if status not in (200, 204):
            log.warning("Whoop: the revoke request was refused")
            return False
        return True
