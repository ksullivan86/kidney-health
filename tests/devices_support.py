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
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx2

from app.config import WithingsEnv

CLIENT_ID = "kh-test-client"
CLIENT_SECRET = "withings-client-secret-0123456789abcdef"
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
