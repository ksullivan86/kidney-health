"""Withings: weight, blood pressure and pulse (design note 27 §1, checked 2026-10-31).

* The person's browser goes to ``account.withings.com`` with ``scope=user.metrics`` and the state; the server never contacts that
  host.
* The server talks only to ``wbsapi.withings.net``: the token request (``/v2/oauth2``, ``action=requesttoken``), the measures
  (``/measure``, ``action=getmeas``) and, on Disconnect, the signed ``revoke`` (``/v2/signature`` for the nonce first). Every
  request goes through :class:`app.egress.CheckedTransport`: the address is checked when the request is made, redirects are never
  followed, at most 2 MiB is read and a request gives up after 15 seconds.
* Withings answers HTTP 200 with ``{"status": <code>, "body": {...}}``; a code other than 0 is a refusal. 601 is "too many
  requests"; 100, 101, 102, 401 and 2553 to 2555 mean the tokens no longer work.
* A measure's value is ``value × 10^unit`` (``7512, -2`` is 75.12 kg). Types: 1 weight, 9 diastolic, 10 systolic, 11 pulse.
  Only real measures (``category`` 1) that Withings knows are this person's (``attrib`` 0, 2, 5, 7, 8) are taken: an
  ambiguous one (1: maybe a guest on the scale) or one typed when the Withings account was made (4) is left out.
* Times become the person's clock in the time zone Withings gives (the group's, else the account's), UTC if the server cannot
  read that zone.

Nothing here logs or keeps a token, a code, the state or the client secret; log lines are constant sentences.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time as _time
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Callable
from urllib.parse import urlencode
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx2

from .. import brand, egress
from ..config import WithingsEnv
from .base import FetchResult, ProviderError, Reading, TokenSet

log = logging.getLogger(f"{brand.LOGGER_NAME}.devices.withings")

ID = "withings"
NAME = "Withings"
AUTHORIZE_URL = "https://account.withings.com/oauth2_user/authorize2"
API_HOST = "wbsapi.withings.net"
TOKEN_URL = f"https://{API_HOST}/v2/oauth2"
MEASURE_URL = f"https://{API_HOST}/measure"
SIGNATURE_URL = f"https://{API_HOST}/v2/signature"
SCOPE = "user.metrics"
HTTP_TIMEOUT_S = 15.0
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_PAGES = 50
MAX_TOKEN_CHARS = 4096

WEIGHT, DIASTOLIC, SYSTOLIC, PULSE = 1, 9, 10, 11
MEASTYPES = f"{WEIGHT},{DIASTOLIC},{SYSTOLIC},{PULSE}"
REAL_MEASURE = 1  # category 1: a measure (2 is a goal the person set)
TAKEN_ATTRIBS = frozenset({0, 2, 5, 7, 8})  # 1 (ambiguous) and 4 (typed when the account was made) are left out
STATUS_OK = 0
STATUS_RATE_LIMITED = 601
STATUS_AUTH = frozenset({100, 101, 102, 401, 214, 277, 2553, 2554, 2555})


def decode_value(value: Any, unit: Any) -> Decimal | None:
    """``value × 10^unit`` exactly, or None for anything that is not two whole numbers in a sensible range."""
    if isinstance(value, bool) or isinstance(unit, bool) or not isinstance(value, int) or not isinstance(unit, int):
        return None
    if not -12 <= unit <= 12 or abs(value) > 10**15:
        return None
    try:
        return Decimal(value).scaleb(unit)
    except InvalidOperation:  # pragma: no cover - whole numbers in range always scale
        return None


def _zone(name: Any) -> Any:
    if isinstance(name, str) and 0 < len(name) <= 64:
        try:
            return ZoneInfo(name)
        except (ZoneInfoNotFoundError, ValueError, OSError):
            pass
    return None


def local_moment(epoch: int, zone_name: Any, fallback_zone: Any = None) -> tuple[str, str]:
    """``(YYYY-MM-DD, HH:MM)`` of a Unix time on the person's clock (the zone Withings gives, else UTC)."""
    zone = _zone(zone_name) or _zone(fallback_zone) or timezone.utc
    moment = datetime.fromtimestamp(epoch, tz=timezone.utc).astimezone(zone)
    return moment.strftime("%Y-%m-%d"), moment.strftime("%H:%M")


def _round_half_up(value: Decimal) -> int:
    return int(value.quantize(Decimal(1), rounding="ROUND_HALF_UP"))


def readings_from_groups(groups: Any, account_zone: Any) -> tuple[list[Reading], int]:
    """The weights and blood pressure readings in ``measuregrps``, and how many groups or measures were left out."""
    out: list[Reading] = []
    left_out = 0
    if not isinstance(groups, list):
        return out, 0
    for group in groups:
        if not isinstance(group, dict):
            left_out += 1
            continue
        grpid, epoch = group.get("grpid"), group.get("date")
        category, attrib = group.get("category", REAL_MEASURE), group.get("attrib", 0)
        if (not isinstance(grpid, int) or isinstance(grpid, bool) or grpid <= 0 or not isinstance(epoch, int)
                or isinstance(epoch, bool) or not 0 < epoch < 10**11 or category != REAL_MEASURE or attrib not in TAKEN_ATTRIBS):
            left_out += 1
            continue
        values: dict[int, Decimal] = {}
        for m in group.get("measures") or []:
            if isinstance(m, dict) and m.get("type") in (WEIGHT, DIASTOLIC, SYSTOLIC, PULSE):
                v = decode_value(m.get("value"), m.get("unit"))
                if v is not None:
                    values[int(m["type"])] = v
        if not values:
            left_out += 1
            continue
        day, clock = local_moment(epoch, group.get("timezone"), account_zone)
        if WEIGHT in values:
            out.append(Reading("weight", f"{grpid}:weight", day, clock, kg=float(values[WEIGHT])))
        if SYSTOLIC in values and DIASTOLIC in values:
            pulse = _round_half_up(values[PULSE]) if PULSE in values else None
            out.append(Reading("blood_pressure", f"{grpid}:bp", day, clock, systolic=_round_half_up(values[SYSTOLIC]),
                               diastolic=_round_half_up(values[DIASTOLIC]), pulse=pulse))
        elif WEIGHT not in values:
            left_out += 1  # a pulse alone, or half a blood pressure reading
    return out, left_out


def sign(secret: str, *values: str) -> str:
    """Withings' request signature: HMAC-SHA256 (hex) of the values joined with commas, keyed with the client secret."""
    return hmac.new(secret.encode("utf-8"), ",".join(values).encode("utf-8"), hashlib.sha256).hexdigest()


def _token_text(value: Any) -> str | None:
    return value if isinstance(value, str) and 0 < len(value) <= MAX_TOKEN_CHARS and value.isprintable() else None


class WithingsProvider:
    """The server's Withings app (``WITHINGS_*``). ``resolver``, ``direct`` and ``use_env_proxy`` exist for tests (a fake Withings
    behind the real checked transport)."""

    id = ID
    name = NAME
    what = ("weight", "blood pressure", "pulse")

    def __init__(self, env: WithingsEnv, *, resolver: Callable[[str, int], list[str]] | None = None,
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
                "secret": "set" if self.env.secret_set else "not set", "hosts": [API_HOST, "account.withings.com"]}

    # ------------------------------------------------------------------ HTTP
    def _client(self) -> httpx2.Client:
        transport = egress.CheckedTransport(allow_private=False, resolver=self.resolver, use_env_proxy=self.use_env_proxy,
                                            direct=self.direct)
        return httpx2.Client(transport=transport, timeout=HTTP_TIMEOUT_S, follow_redirects=False, trust_env=False,
                             headers={"User-Agent": brand.USER_AGENT_DEVICES, "Accept": "application/json"})

    def _post(self, url: str, form: dict[str, str], *, bearer: str | None = None) -> tuple[int, dict[str, Any]]:
        """``(withings status, body)``; raises :class:`ProviderError` ("unreachable" or "provider_error")."""
        headers = {"Authorization": f"Bearer {bearer}"} if bearer else {}
        try:
            with self._client() as client, client.stream("POST", url, data=form, headers=headers) as response:
                raw = egress.read_capped(response, MAX_RESPONSE_BYTES)
                http_status = response.status_code
        except egress.BlockedAddress:
            log.warning("Withings: the server refused to connect (the address is not allowed or does not resolve)")
            raise ProviderError("unreachable", "blocked") from None
        except egress.ResponseTooLarge:
            log.warning("Withings: the answer was too large")
            raise ProviderError("provider_error", "too_large") from None
        except httpx2.HTTPError:
            log.warning("Withings: no answer")
            raise ProviderError("unreachable", "no_answer") from None
        if http_status == 429:
            raise ProviderError("rate_limited", "http_429")
        if http_status == 401:
            raise ProviderError("auth", "http_401")
        if http_status != 200:
            log.warning("Withings: an HTTP error answer")
            raise ProviderError("provider_error", "http_error")
        try:
            data = json.loads(raw)
        except ValueError:
            data = None
        if not isinstance(data, dict) or not isinstance(data.get("status"), int):
            log.warning("Withings: an answer that is not Withings JSON")
            raise ProviderError("provider_error", "not_json")
        body = data.get("body")
        return int(data["status"]), body if isinstance(body, dict) else {}

    # ------------------------------------------------------------------ sign-in
    def authorize_url(self, *, state: str, redirect_uri: str) -> str:
        query = {"response_type": "code", "client_id": self.env.client_id or "", "scope": SCOPE, "redirect_uri": redirect_uri,
                 "state": state}
        return f"{AUTHORIZE_URL}?{urlencode(query)}"

    def _token_set(self, status: int, body: dict[str, Any], *, refreshing: bool) -> TokenSet:
        if status == STATUS_RATE_LIMITED:
            raise ProviderError("rate_limited", "status_601")
        if status != STATUS_OK:
            # A refresh token that no longer works (revoked, older than a year, replaced more than 8 hours ago) is a refusal
            # of any kind; a failed code exchange is simply a failed sign-in.
            raise ProviderError("auth" if refreshing else "provider_error", "token_refused")
        access, refresh = _token_text(body.get("access_token")), _token_text(body.get("refresh_token"))
        userid = body.get("userid")
        expires = body.get("expires_in")
        if access is None or refresh is None or not isinstance(userid, (int, str)) or isinstance(userid, bool) or not str(userid):
            raise ProviderError("provider_error", "token_answer")
        if not isinstance(expires, int) or isinstance(expires, bool) or expires <= 0:
            expires = 10800
        scopes = body.get("scope") if isinstance(body.get("scope"), str) else ""
        return TokenSet(access, refresh, min(int(expires), 86400 * 30), str(userid)[:64], " ".join(scopes.replace(",", " ").split()))

    def exchange(self, *, code: str, redirect_uri: str) -> TokenSet:
        status, body = self._post(TOKEN_URL, {"action": "requesttoken", "grant_type": "authorization_code",
                                              "client_id": self.env.client_id or "", "client_secret": self.env.client_secret or "",
                                              "code": code, "redirect_uri": redirect_uri})
        tokens = self._token_set(status, body, refreshing=False)
        if SCOPE not in tokens.scopes.split():
            raise ProviderError("scope", "no_user_metrics")
        return tokens

    def refresh(self, refresh_token: str) -> TokenSet:
        status, body = self._post(TOKEN_URL, {"action": "requesttoken", "grant_type": "refresh_token",
                                              "client_id": self.env.client_id or "", "client_secret": self.env.client_secret or "",
                                              "refresh_token": refresh_token})
        return self._token_set(status, body, refreshing=True)

    # ------------------------------------------------------------------ measures
    def fetch(self, access_token: str, *, cursor: str | None, since: int) -> FetchResult:
        """Weights and readings changed since ``cursor`` (Withings' ``updatetime`` of the last fetch) or, the first time, since
        ``since`` (a Unix time). Follows ``more``/``offset`` up to :data:`MAX_PAGES` pages."""
        lastupdate = int(cursor) if cursor and cursor.isdigit() else since
        readings: list[Reading] = []
        left_out = 0
        new_cursor: int | None = None
        offset: int | None = None
        for _page in range(MAX_PAGES):
            form = {"action": "getmeas", "meastypes": MEASTYPES, "category": str(REAL_MEASURE), "lastupdate": str(lastupdate)}
            if offset is not None:
                form["offset"] = str(offset)
            status, body = self._post(MEASURE_URL, form, bearer=access_token)
            if status == STATUS_RATE_LIMITED:
                raise ProviderError("rate_limited", "status_601")
            if status in STATUS_AUTH:
                raise ProviderError("auth", "measure_refused")
            if status != STATUS_OK:
                log.warning("Withings: the measures request was refused")
                raise ProviderError("provider_error", "measure_status")
            got, skipped = readings_from_groups(body.get("measuregrps"), body.get("timezone"))
            readings += got
            left_out += skipped
            updatetime = body.get("updatetime")
            if new_cursor is None and isinstance(updatetime, int) and not isinstance(updatetime, bool) and updatetime > 0:
                new_cursor = updatetime
            more, next_offset = body.get("more"), body.get("offset")
            if not more or not isinstance(next_offset, int) or isinstance(next_offset, bool) or next_offset == offset:
                break
            offset = next_offset
        if new_cursor is None:
            new_cursor = int(self.clock())
        return FetchResult(readings, str(new_cursor), left_out)

    # ------------------------------------------------------------------ disconnect
    def revoke(self, external_user_id: str, access_token: str | None = None) -> bool:
        """Ask Withings to end this app's access to the account (signed with a fresh nonce). True when Withings said yes; any
        failure is logged as a constant sentence and returns False (the tokens are deleted here either way)."""
        client_id, key = self.env.client_id or "", self.env.client_secret or ""
        if not client_id or not key or not external_user_id:
            return False
        try:
            stamp = str(int(self.clock()))
            status, body = self._post(SIGNATURE_URL, {"action": "getnonce", "client_id": client_id, "timestamp": stamp,
                                                      "signature": sign(key, "getnonce", client_id, stamp)})
            nonce = body.get("nonce")
            if status != STATUS_OK or not isinstance(nonce, str) or not nonce:
                log.warning("Withings: no nonce for the revoke request")
                return False
            # sorted by key name: action, client_id, nonce
            status, _ = self._post(TOKEN_URL, {"action": "revoke", "client_id": client_id, "nonce": nonce,
                                               "userid": external_user_id, "signature": sign(key, "revoke", client_id, nonce)})
        except ProviderError:
            return False
        if status != STATUS_OK:
            log.warning("Withings: the revoke request was refused")
            return False
        return True
