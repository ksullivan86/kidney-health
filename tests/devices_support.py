"""A fake Withings for the connected-devices tests (design note 27): the token endpoint (code and refresh, with rotation), the
measures endpoint (``lastupdate``, ``more``/``offset``), the nonce and the signed revoke. It answers through
``httpx2.MockTransport`` behind the app's real :class:`app.egress.CheckedTransport` (a fake resolver gives the API host a public
address), so no test touches the network.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx2

from app.config import WhoopEnv, WithingsEnv

CLIENT_ID = "kh-test-client"
APP_KEY = "withings-app-key-0123456789abcdef-test"
CLIENT_SECRET = APP_KEY
ADDRESS = "93.184.216.34"


def env(**changes: Any) -> WithingsEnv:
    values: dict[str, Any] = dict(enabled=True, client_id=CLIENT_ID, client_secret=CLIENT_SECRET)
    values.update(changes)
    return WithingsEnv(**values)


@dataclass
class FakeWithings:
    userid: int = 4242
    scope: str = "user.metrics"
    expires_in: int = 10800
    groups: list[dict[str, Any]] = field(default_factory=list)
    timezone: str = "Europe/Paris"
    page_size: int = 100
    updatetime: int = 1_900_000_000
    codes: dict[str, str] = field(default_factory=dict)  # code -> redirect_uri
    access: str | None = None
    refresh: str | None = None
    old_refresh: set[str] = field(default_factory=set)
    refusing_refresh: bool = False
    measure_status: int = 0
    calls: list[dict[str, Any]] = field(default_factory=list)
    nonces: set[str] = field(default_factory=set)
    revoked: list[str] = field(default_factory=list)

    def issue_code(self, redirect_uri: str) -> str:
        code = "code-" + secrets.token_hex(8)
        self.codes[code] = redirect_uri
        return code

    def _tokens(self) -> dict[str, Any]:
        if self.refresh:
            self.old_refresh.add(self.refresh)
        self.access = "acc-" + secrets.token_hex(12)
        self.refresh = "ref-" + secrets.token_hex(12)
        return {"userid": self.userid, "access_token": self.access, "refresh_token": self.refresh, "expires_in": self.expires_in,
                "scope": self.scope, "token_type": "Bearer"}

    @staticmethod
    def _answer(status: int, body: dict[str, Any] | None = None) -> httpx2.Response:
        return httpx2.Response(200, json={"status": status, "body": body or {}})

    def handler(self, request: httpx2.Request) -> httpx2.Response:
        form = {k: v[0] for k, v in parse_qs(request.content.decode("utf-8")).items()}
        path = urlsplit(str(request.url)).path
        self.calls.append({"path": path, "form": form, "auth": request.headers.get("authorization"),
                           "host": request.headers.get("host")})
        if path == "/v2/oauth2" and form.get("action") == "requesttoken":
            if form.get("client_id") != CLIENT_ID or form.get("client_secret") != CLIENT_SECRET:
                return self._answer(503)
            if form.get("grant_type") == "authorization_code":
                redirect = self.codes.pop(form.get("code", ""), None)
                if redirect is None or redirect != form.get("redirect_uri"):
                    return self._answer(503)
                return self._answer(0, self._tokens())
            if form.get("grant_type") == "refresh_token":
                if self.refusing_refresh or form.get("refresh_token") != self.refresh:
                    return self._answer(503)
                return self._answer(0, self._tokens())
            return self._answer(503)
        if path == "/v2/signature" and form.get("action") == "getnonce":
            expected = hmac.new(CLIENT_SECRET.encode(), f"getnonce,{CLIENT_ID},{form.get('timestamp')}".encode(), hashlib.sha256).hexdigest()
            if form.get("signature") != expected:
                return self._answer(503)
            nonce = secrets.token_hex(8)
            self.nonces.add(nonce)
            return self._answer(0, {"nonce": nonce})
        if path == "/v2/oauth2" and form.get("action") == "revoke":
            nonce = form.get("nonce", "")
            expected = hmac.new(CLIENT_SECRET.encode(), f"revoke,{CLIENT_ID},{nonce}".encode(), hashlib.sha256).hexdigest()
            if nonce not in self.nonces or form.get("signature") != expected:
                return self._answer(503)
            self.nonces.discard(nonce)
            self.revoked.append(form.get("userid", ""))
            return self._answer(0)
        if path == "/measure" and form.get("action") == "getmeas":
            if request.headers.get("authorization") != f"Bearer {self.access}" or not self.access:
                return self._answer(401)
            if self.measure_status:
                return self._answer(self.measure_status)
            since = int(form.get("lastupdate", "0"))
            wanted = [g for g in self.groups if g.get("modified", g.get("date", 0)) > since]
            offset = int(form.get("offset", "0"))
            page = wanted[offset:offset + self.page_size]
            more = offset + self.page_size < len(wanted)
            body = {"updatetime": self.updatetime, "timezone": self.timezone, "measuregrps": page, "more": 1 if more else 0,
                    "offset": offset + self.page_size if more else 0}
            return self._answer(0, body)
        return httpx2.Response(404, text="not found")


def attach(app: Any, fake: FakeWithings) -> FakeWithings:
    provider = app.state.devices.providers["withings"]
    provider.resolver = lambda host, port: [ADDRESS]
    provider.direct = httpx2.MockTransport(fake.handler)
    provider.use_env_proxy = False
    return fake


def weight_group(grpid: int, epoch: int, value: int = 7512, unit: int = -2, **extra: Any) -> dict[str, Any]:
    group = {"grpid": grpid, "attrib": 0, "date": epoch, "created": epoch, "modified": epoch, "category": 1, "deviceid": "abc",
             "measures": [{"value": value, "type": 1, "unit": unit, "algo": 0, "fm": 3}]}
    group.update(extra)
    return group


def bp_group(grpid: int, epoch: int, systolic: int = 128, diastolic: int = 79, pulse: int | None = 64, **extra: Any) -> dict[str, Any]:
    measures = [{"value": systolic, "type": 10, "unit": 0}, {"value": diastolic, "type": 9, "unit": 0}]
    if pulse is not None:
        measures.append({"value": pulse, "type": 11, "unit": 0})
    group = {"grpid": grpid, "attrib": 0, "date": epoch, "created": epoch, "modified": epoch, "category": 1, "measures": measures}
    group.update(extra)
    return group


def to_json(value: Any) -> str:
    return json.dumps(value)


# --------------------------------------------------------------------------- #
# A fake Whoop (design note 28): the token endpoint (code and refresh, with rotation: the old refresh token stops at once), the
# four v2 collections (``start``, ``limit``, ``nextToken``) and the revoke. Same transport trick as the fake Withings.
# --------------------------------------------------------------------------- #

WHOOP_CLIENT_ID = "kh-whoop-client"
WHOOP_SECRET = "whoop-app-secret-0123456789abcdef-test"


def whoop_env(**changes: Any) -> WhoopEnv:
    values: dict[str, Any] = dict(enabled=True, client_id=WHOOP_CLIENT_ID, client_secret=WHOOP_SECRET)
    values.update(changes)
    return WhoopEnv(**values)


@dataclass
class FakeWhoop:
    user_id: int = 10129
    scope: str = "offline read:cycles read:recovery read:sleep read:workout"
    expires_in: int = 3600
    cycles: list[dict[str, Any]] = field(default_factory=list)
    recoveries: list[dict[str, Any]] = field(default_factory=list)
    sleeps: list[dict[str, Any]] = field(default_factory=list)
    workouts: list[dict[str, Any]] = field(default_factory=list)
    page_size: int = 25
    codes: dict[str, str] = field(default_factory=dict)
    access: str | None = None
    refresh: str | None = None
    old_refresh: set[str] = field(default_factory=set)
    refusing_refresh: bool = False
    data_status: int = 200
    forbidden: set[str] = field(default_factory=set)  # collection paths answered 403 (not allowed)
    calls: list[dict[str, Any]] = field(default_factory=list)
    revoked: list[str] = field(default_factory=list)

    def issue_code(self, redirect_uri: str) -> str:
        code = "wcode-" + secrets.token_hex(8)
        self.codes[code] = redirect_uri
        return code

    def _tokens(self) -> dict[str, Any]:
        if self.refresh:
            self.old_refresh.add(self.refresh)
        self.access = "wacc-" + secrets.token_hex(12)
        self.refresh = "wref-" + secrets.token_hex(12)
        return {"access_token": self.access, "refresh_token": self.refresh, "expires_in": self.expires_in, "scope": self.scope,
                "token_type": "bearer"}

    def handler(self, request: httpx2.Request) -> httpx2.Response:
        url = urlsplit(str(request.url))
        query = {k: v[0] for k, v in parse_qs(url.query).items()}
        form = {k: v[0] for k, v in parse_qs(request.content.decode("utf-8")).items()} if request.method == "POST" else {}
        self.calls.append({"method": request.method, "path": url.path, "query": query, "form": form,
                           "auth": request.headers.get("authorization"), "host": request.headers.get("host")})
        if url.path == "/oauth/oauth2/token" and request.method == "POST":
            if form.get("client_id") != WHOOP_CLIENT_ID or form.get("client_secret") != WHOOP_SECRET:
                return httpx2.Response(401, json={"error": "invalid_client"})
            if form.get("grant_type") == "authorization_code":
                redirect = self.codes.pop(form.get("code", ""), None)
                if redirect is None or redirect != form.get("redirect_uri"):
                    return httpx2.Response(400, json={"error": "invalid_grant"})
                return httpx2.Response(200, json=self._tokens())
            if form.get("grant_type") == "refresh_token":
                if self.refusing_refresh or form.get("refresh_token") != self.refresh:
                    return httpx2.Response(400, json={"error": "invalid_grant"})
                return httpx2.Response(200, json=self._tokens())
            return httpx2.Response(400, json={"error": "unsupported_grant_type"})
        authed = bool(self.access) and request.headers.get("authorization") == f"Bearer {self.access}"
        if url.path == "/developer/v2/user/access" and request.method == "DELETE":
            if not authed:
                return httpx2.Response(401)
            self.revoked.append(self.access or "")
            self.access = self.refresh = None
            return httpx2.Response(204)
        collections = {"/developer/v2/cycle": self.cycles, "/developer/v2/recovery": self.recoveries,
                       "/developer/v2/activity/sleep": self.sleeps, "/developer/v2/activity/workout": self.workouts}
        if url.path in collections and request.method == "GET":
            if not authed:
                return httpx2.Response(401, json={"error": "unauthorized"})
            if self.data_status != 200:
                return httpx2.Response(self.data_status, json={})
            if url.path in self.forbidden:
                return httpx2.Response(403, json={})
            records = collections[url.path]
            if "start" in query:
                records = [r for r in records if r.get("start", "") >= query["start"]]
            limit = min(int(query.get("limit", "10")), self.page_size)
            offset = int(query["nextToken"][1:]) if query.get("nextToken", "").startswith("p") else 0
            page = records[offset:offset + limit]
            more = offset + limit < len(records)
            return httpx2.Response(200, json={"records": page, "next_token": f"p{offset + limit}" if more else None})
        return httpx2.Response(404, text="not found")


def attach_whoop(app: Any, fake: FakeWhoop) -> FakeWhoop:
    provider = app.state.devices.providers["whoop"]
    provider.resolver = lambda host, port: [ADDRESS]
    provider.direct = httpx2.MockTransport(fake.handler)
    provider.use_env_proxy = False
    return fake


def iso_utc(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def whoop_cycle(cid: int, start: datetime, end: datetime | None, kilojoule: float | None = 9000.0, strain: float = 9.5,
                offset: str = "-05:00", state: str = "SCORED", user_id: int = 10129) -> dict[str, Any]:
    record: dict[str, Any] = {"id": cid, "user_id": user_id, "created_at": iso_utc(start), "updated_at": iso_utc(start),
                              "start": iso_utc(start), "timezone_offset": offset, "score_state": state}
    if end is not None:
        record["end"] = iso_utc(end)
    if state == "SCORED":
        record["score"] = {"strain": strain, "kilojoule": kilojoule, "average_heart_rate": 68, "max_heart_rate": 141}
    return record


def whoop_recovery(cid: int, start: datetime, score: float = 66, rhr: float = 56, hrv: float = 45.678) -> dict[str, Any]:
    return {"cycle_id": cid, "sleep_id": "ecfc6a15-4661-442f-a9a4-f160dd7afae8", "user_id": 10129, "created_at": iso_utc(start),
            "updated_at": iso_utc(start), "start": iso_utc(start), "score_state": "SCORED",
            "score": {"user_calibrating": False, "recovery_score": score, "resting_heart_rate": rhr, "hrv_rmssd_milli": hrv,
                      "spo2_percentage": 95.6875, "skin_temp_celsius": 33.7}}


def whoop_sleep(sid: str, cid: int, start: datetime, light_min: int = 240, sws_min: int = 90, rem_min: int = 100, perf: float = 88,
                nap: bool = False) -> dict[str, Any]:
    ms = 60000
    stages = {"total_in_bed_time_milli": (light_min + sws_min + rem_min + 30) * ms, "total_awake_time_milli": 30 * ms,
              "total_no_data_time_milli": 0, "total_light_sleep_time_milli": light_min * ms,
              "total_slow_wave_sleep_time_milli": sws_min * ms, "total_rem_sleep_time_milli": rem_min * ms,
              "sleep_cycle_count": 4, "disturbance_count": 10}
    return {"id": sid, "cycle_id": cid, "user_id": 10129, "start": iso_utc(start), "end": iso_utc(start), "timezone_offset": "-05:00",
            "nap": nap, "score_state": "SCORED",
            "score": {"stage_summary": stages, "sleep_performance_percentage": perf, "sleep_efficiency_percentage": 91.7}}


def whoop_workout(wid: str, start: datetime, minutes: int, kilojoule: float = 1673.6, strain: float = 11.2,
                  sport: str = "functional-fitness", offset: str = "-05:00", state: str = "SCORED") -> dict[str, Any]:
    end = start + timedelta(minutes=minutes)
    record: dict[str, Any] = {"id": wid, "v1_id": 1043, "user_id": 10129, "created_at": iso_utc(start), "updated_at": iso_utc(end),
                              "start": iso_utc(start), "end": iso_utc(end), "timezone_offset": offset, "sport_name": sport,
                              "sport_id": 1, "score_state": state}
    if state == "SCORED":
        record["score"] = {"strain": strain, "average_heart_rate": 123, "max_heart_rate": 146, "kilojoule": kilojoule,
                           "percent_recorded": 100}
    return record
