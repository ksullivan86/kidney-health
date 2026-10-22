"""``POST /push/v1/body`` (design note 12 §4.2; ``app/push.py``): a phone shortcut's device token adds weights and blood pressure
readings to its owner's log and reads nothing.

Covered: the instance switch, the bearer rule (cookie-only requests, the Origin rule, no CSRF header needed), the size and row caps,
``at`` parsing, units and rounding, numbers sent as text, the watch rule, all-or-nothing, the per-day limits, the rate limit, an
answer that holds counts only, values that never reach the log, ``source_key`` equal to the Health export reader's, and "the same
reading" against the batch import routes. The token side (families, limits, revocation) is in ``tests/test_device_tokens.py``.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest
from starlette.testclient import TestClient as BareClient

from app import body as B
from app.auth import api_tokens
from app.push import MAX_BODY_BYTES, MAX_ROWS, parse_at
from conftest import CSRF_HEADERS, TestClient

ROOT = Path(__file__).resolve().parent.parent
PUSH = "/push/v1/body"
DAY = "2026-10-22"
AT = f"{DAY}T07:15:00-04:00"
GENERIC = {"detail": api_tokens.DEVICE_DENIED}


def push_switch(admin: TestClient, on: bool = True) -> None:
    r = admin.patch("/api/admin/settings", json={"push.enabled": on})
    assert r.status_code == 200, r.text
    assert r.json()["settings"]["push.enabled"]["value"] is on


def make_device(client: TestClient, name: str = "Morning weight", days: int | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {"name": name, "family": "device"}
    if days is not None:
        body["expires_in_days"] = days
    r = client.post("/api/me/tokens", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def bare(app: Any, **kwargs: Any) -> BareClient:
    """A client with nothing but what a Shortcut sends: no cookie and none of the app's own headers."""
    return BareClient(app, base_url="https://localhost", **kwargs)


def push(app: Any, token: str | None, body: Any = None, *, raw: bytes | None = None, content_type: str | None = "application/json",
         headers: dict[str, str] | None = None) -> Any:
    h = dict(headers or {})
    if token is not None:
        h["Authorization"] = f"Bearer {token}"
    if content_type is not None:
        h["Content-Type"] = content_type
    content = raw if raw is not None else json.dumps(body).encode("utf-8")
    return bare(app).post(PUSH, content=content, headers=h)


def weight(at: str = AT, value: Any = 154.3, unit: str = "lb", source: str = "Health") -> dict[str, Any]:
    return {"at": at, "value": value, "unit": unit, "source": source}


def reading(at: str = f"{DAY}T07:20:00-04:00", systolic: Any = 122, diastolic: Any = 78, source: str = "Omron Connect") -> dict[str, Any]:
    return {"at": at, "systolic": systolic, "diastolic": diastolic, "source": source}


def counts(added_w: int = 0, added_r: int = 0, there_w: int = 0, there_r: int = 0, watch: int = 0) -> dict[str, Any]:
    return {"added": {"weights": added_w, "readings": added_r}, "already_there": {"weights": there_w, "readings": there_r},
            "refused": {"watch": watch}}


def rows(client: TestClient, start: str = "2026-10-01", end: str = "2026-10-31") -> tuple[list[dict], list[dict]]:
    w = client.get(f"/api/body/weights?start={start}&end={end}")
    r = client.get(f"/api/body/blood-pressure?start={start}&end={end}")
    assert w.status_code == 200 and r.status_code == 200
    return w.json()["weights"], r.json()["readings"]


@pytest.fixture
def admin(client: TestClient) -> TestClient:
    push_switch(client, True)
    return client


@pytest.fixture
def token(admin: TestClient) -> str:
    return make_device(admin)["token"]


# --------------------------------------------------------------------------- the switch and the bearer rule


def test_the_switch_is_off_by_default_and_while_off_every_request_is_the_generic_401(client, tmp_path):
    from app.settings_registry import REGISTRY

    d = REGISTRY["push.enabled"]
    assert (d.scope, d.default, d.env) == ("instance", False, "PUSH_ENABLED")
    assert client.get("/api/admin/settings").json()["settings"]["push.enabled"]["value"] is False
    push_switch(client, True)
    token = make_device(client)["token"]
    assert push(client.app, token, {"weights": [weight()]}).status_code == 200
    push_switch(client, False)
    for _ in range(25):  # refused without a lookup and without counting toward the address's sign-in limit
        r = push(client.app, token, {"weights": [weight()]})
        assert r.status_code == 401 and r.json() == GENERIC
        assert r.headers["www-authenticate"].startswith("Bearer")
    assert push(client.app, None, {"weights": [weight()]}).status_code == 401
    push_switch(client, True)
    assert push(client.app, token, {"weights": [weight()]}).status_code == 200  # the address was never blocked


def test_nothing_is_looked_up_while_off_or_for_a_token_of_the_other_family(admin, token, monkeypatch):
    """The switch, the family prefix and the token's shape are all checked before the token's hash is computed or looked up."""
    from test_api_tokens import make, switch

    switch(admin, True)
    assistant = make(admin)["token"]
    lookups: list[str] = []
    real = api_tokens.hash_token
    monkeypatch.setattr(api_tokens, "hash_token", lambda t: lookups.append(t) or real(t))
    for bad in (assistant, "khd_short", "khd_" + "A" * 44, "x"):  # another family, too short, too long, not a token
        assert push(admin.app, bad, {"weights": [weight()]}).status_code == 401
    assert lookups == []
    push_switch(admin, False)
    assert push(admin.app, token, {"weights": [weight()]}).status_code == 401
    assert lookups == []
    push_switch(admin, True)
    assert push(admin.app, token, {"weights": [weight()]}).status_code == 200
    assert lookups == [token]  # the one good token, once


def test_the_env_switch_wins(tmp_path, foods_json, monkeypatch):
    from conftest import make_settings, signed_in_client

    monkeypatch.setenv("PUSH_ENABLED", "true")
    with signed_in_client(make_settings(tmp_path, foods_json)) as c:
        item = c.get("/api/admin/settings").json()["settings"]["push.enabled"]
        assert item["value"] is True and item["locked_by_env"] == "PUSH_ENABLED"
        assert c.patch("/api/admin/settings", json={"push.enabled": False}).status_code == 409
        assert push(c.app, make_device(c)["token"], {"weights": [weight()]}).status_code == 200


def test_a_cookie_session_never_opens_the_route(admin, token):
    """The signed-in admin's cookie and the app's own CSRF header are not a credential here."""
    r = admin.post(PUSH, json={"weights": [weight()]})
    assert r.status_code == 401 and r.json() == GENERIC and r.headers["www-authenticate"].startswith("Bearer")
    assert rows(admin) == ([], [])
    # and the token next to a cookie is the token that decides, not the cookie
    r = admin.post(PUSH, json={"weights": [weight()]}, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200


def test_a_bearer_post_needs_no_csrf_header_but_the_origin_rule_holds(admin, token):
    """The route reads no cookie, so the cookie checks (Sec-Fetch-Site, X-Requested-With) do not apply; a foreign Origin is
    refused, as for /mcp."""
    r = push(admin.app, token, {"weights": [weight()]}, headers={"Sec-Fetch-Site": "cross-site"})
    assert r.status_code == 200
    for origin in ("https://evil.example", "null", "http://localhost:9999"):
        r = push(admin.app, token, {"weights": [weight(value=155)]}, headers={"Origin": origin})
        assert r.status_code == 403 and r.json() == {"detail": "Cross-site request refused"}, origin
    assert push(admin.app, token, {"weights": [weight(value=156)]}, headers={"Origin": "https://localhost"}).status_code == 200
    assert len(rows(admin)[0]) == 2  # only the two that were let in
    for path in ("/push/v1/body/", "/push/v1/bodyx", "/push/v1"):  # the exemption is the exact path only
        r = bare(admin.app).post(path, content=b"{}", headers={"Authorization": f"Bearer {token}", "Sec-Fetch-Site": "cross-site"})
        assert r.status_code in (403, 404, 405), path


@pytest.mark.parametrize("method", ["GET", "DELETE", "PUT", "PATCH"])
def test_other_methods_are_405(admin, token, method):
    r = bare(admin.app).request(method, PUSH, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 405 and r.headers["allow"] == "POST"


def test_an_assistant_token_and_garbage_are_refused_before_any_lookup_and_are_throttled(admin):
    from test_api_tokens import make, switch

    switch(admin, True)
    assistant = make(admin)["token"]
    good = make_device(admin)["token"]
    for bad in (assistant, "khd_" + "A" * 43, "khd_short", "", "not-a-token"):
        r = push(admin.app, bad, {"weights": [weight()]})
        assert r.status_code == 401 and r.json() == GENERIC, bad
        assert r.headers["www-authenticate"] == 'Bearer realm="kidney-health", error="invalid_token"'
    for _ in range(15):
        assert push(admin.app, assistant, {}).status_code == 401
    r = push(admin.app, good, {"weights": [weight()]})  # 20 refused tokens block the address, even for a good one
    assert r.status_code == 429 and int(r.headers["retry-after"]) > 0


def test_the_content_type_must_be_json(admin, token):
    for ct in ("text/plain", "application/x-www-form-urlencoded", None):
        r = push(admin.app, token, raw=b'{"weights": []}', content_type=ct)
        assert r.status_code == 415, ct
    assert push(admin.app, token, {"weights": [weight()]}, content_type="application/json; charset=utf-8").status_code == 200
    assert push(admin.app, token, {"weights": [weight(value=155)]}, content_type="Application/JSON").status_code == 200


# --------------------------------------------------------------------------- size and shape


def test_a_body_over_32_kib_is_413_before_it_is_parsed(admin, token):
    assert MAX_BODY_BYTES == 32 * 1024
    junk = b'{"weights": [], "pad": "' + b"a" * (MAX_BODY_BYTES + 100) + b'"}'  # not valid for the route either: 413 comes first
    r = push(admin.app, token, raw=junk)
    assert r.status_code == 413
    r = push(admin.app, token, raw=b"x" * (MAX_BODY_BYTES + 1))  # not JSON at all
    assert r.status_code == 413
    # the same for a body that streams without a declared length
    def chunks():
        for _ in range(40):
            yield b" " * 1024
    r = bare(admin.app).post(PUSH, content=chunks(), headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    assert r.status_code == 413
    exactly = json.dumps({"weights": [weight()], "x": ""}).encode()  # at the cap or under it is parsed (this one is refused as a field)
    assert len(exactly) < MAX_BODY_BYTES
    assert push(admin.app, token, raw=exactly).status_code == 400
    assert rows(admin) == ([], [])


def test_the_size_cap_is_checked_after_the_token_so_a_stranger_learns_nothing(admin):
    r = push(admin.app, "khd_" + "A" * 43, raw=b"x" * (MAX_BODY_BYTES + 1))
    assert r.status_code == 401


def test_at_most_50_rows_in_all(admin, token):
    assert MAX_ROWS == 50
    days = [(date(2026, 8, 1) + timedelta(days=i)).isoformat() for i in range(60)]
    many = [weight(f"{d}T07:00:00Z", 70 + (i % 5) / 10, "kg") for i, d in enumerate(days)]
    r = push(admin.app, token, {"weights": many[:51]})
    assert r.status_code == 400 and "at most 50 rows" in r.json()["detail"]
    r = push(admin.app, token, {"weights": many[:30], "readings": [reading(f"{d}T07:00:00Z") for d in days[:21]]})
    assert r.status_code == 400 and "at most 50 rows" in r.json()["detail"]
    assert rows(admin, "2026-08-01", "2026-10-31") == ([], [])
    r = push(admin.app, token, {"weights": many[:30], "readings": [reading(f"{d}T07:00:00Z") for d in days[:20]]})
    assert r.status_code == 200 and r.json() == counts(added_w=30, added_r=20)


@pytest.mark.parametrize("body, where", [
    ({"weights": [weight(), {**weight(), "pulse": 60}]}, "weights.1.pulse"),
    ({"readings": [{**reading(), "pulse": 60}]}, "readings.0.pulse"),
    ({"readings": [reading(), {**reading(), "heart_rate": 60}]}, "readings.1.heart_rate"),
    ({"glucose": [{"at": AT, "value": 5.4}]}, "glucose"),
    ({"insulin": [{"at": AT, "units": 4}]}, "insulin"),
    ({"medications": []}, "medications"),
    ({"weights": [weight()], "note": "x"}, "note"),
    ({"weights": [{"at": AT, "value": 70, "unit": "kg"}]}, "weights.0.source"),
    ({"weights": [{"value": 70, "unit": "kg", "source": "Health"}]}, "weights.0.at"),
    ({"weights": [{"at": AT, "unit": "kg", "source": "Health"}]}, "weights.0.value"),
    ({"readings": [{"at": AT, "diastolic": 80, "source": "Omron"}]}, "readings.0.systolic"),
    ({"weights": [{**weight(), "unit": "stone"}]}, "weights.0.unit"),
    ({"weights": [{**weight(), "unit": "KG"}]}, "weights.0.unit"),
    ({"weights": [{**weight(), "unit": None}]}, "weights.0.unit"),
    ({"weights": [{**weight(), "at": 20261022}]}, "weights.0.at"),
    ({"weights": [{**weight(), "source": 7}]}, "weights.0.source"),
    ({"weights": "70 kg"}, "weights"),
    ({"weights": {"at": AT}}, "weights"),
    ({"weights": [5]}, "weights.0"),
])
def test_unknown_fields_missing_fields_and_wrong_shapes_are_400_naming_the_place(admin, token, body, where):
    r = push(admin.app, token, body)
    assert r.status_code == 400, r.text
    assert r.json()["detail"].startswith(where) or f"{where}:" in r.json()["detail"], r.json()
    assert rows(admin) == ([], [])  # nothing is stored when any part is refused


@pytest.mark.parametrize("raw", [b"", b"not json", b"[]", b'"text"', b"5", b"null", b'{"weights": [{"at": NaN}]}',
                                 b'{"weights": [{"at": "' + AT.encode() + b'", "value": Infinity, "unit": "kg", "source": "H"}]}',
                                 b"\xff\xfe", b'{"weights": []}', b'{"readings": []}', b"{}", b'{"weights": [], "readings": []}',
                                 b"[" * 20000, b'{"a":' * 5000, b'{"weights": [' + b"[" * 5000])
def test_a_body_that_is_not_the_object_or_holds_no_rows_is_400(admin, token, raw):
    r = push(admin.app, token, raw=raw)
    assert r.status_code == 400 and isinstance(r.json()["detail"], str), raw


# --------------------------------------------------------------------------- the time


def test_at_keeps_the_wall_clock_as_written_in_its_zone():
    for text, date_, time_, stamp in [
        ("2026-10-22T07:15:00-04:00", "2026-10-22", "07:15", "2026-10-22 07:15:00 -0400"),
        ("2026-10-22T07:15:00Z", "2026-10-22", "07:15", "2026-10-22 07:15:00 +0000"),
        ("2026-10-22T23:50:00+14:00", "2026-10-22", "23:50", "2026-10-22 23:50:00 +1400"),  # not moved to the day before in UTC
        ("2026-10-22T00:05:00-10:00", "2026-10-22", "00:05", "2026-10-22 00:05:00 -1000"),
        ("2026-10-22T07:15:00+05:30", "2026-10-22", "07:15", "2026-10-22 07:15:00 +0530"),
        ("2026-10-22T07:15:00-0400", "2026-10-22", "07:15", "2026-10-22 07:15:00 -0400"),
        ("2026-10-22 07:15:00 -0400", "2026-10-22", "07:15", "2026-10-22 07:15:00 -0400"),  # the Health export's own form
        ("2026-10-22T07:15-04:00", "2026-10-22", "07:15", "2026-10-22 07:15:00 -0400"),  # no seconds
        ("2026-10-22T07:15:30.123456-04:00", "2026-10-22", "07:15", "2026-10-22 07:15:30 -0400"),  # a fraction is dropped
        ("2026-10-22T07:15:00-04", "2026-10-22", "07:15", "2026-10-22 07:15:00 -0400"),
        ("  2026-10-22T07:15:00Z  ", "2026-10-22", "07:15", "2026-10-22 07:15:00 +0000"),
    ]:
        m = parse_at(text)
        assert (m.date, m.time, m.stamp) == (date_, time_, stamp), text


@pytest.mark.parametrize("text", [
    "", "2026-10-22", "2026-10-22T07:15", "2026-10-22T07:15:00", "07:15:00-04:00", "22/10/2026 07:15 -0400",
    "2026-10-22T24:00:00Z", "2026-10-22T07:60:00Z", "2026-10-22T07:15:60Z", "2026-02-30T07:15:00Z", "2026-13-01T07:15:00Z",
    "0000-01-01T07:15:00Z", "2026-10-22T07:15:00+24:00", "2026-10-22T07:15:00+05:60", "2026-10-22T07:15:00 UTC", "2026-10-22T07:15:00z",
    "2026-10-22T7:15:00Z", "yesterday", "\uff12\uff10\uff12\uff16-10-22T07:15:00Z", "2026-10-22T\uff10\uff17:15:00Z",
])
def test_at_without_a_zone_or_not_a_time_is_refused(text):
    with pytest.raises(ValueError):
        parse_at(text)


def test_no_zone_is_a_400_that_says_to_send_one(admin, token):
    r = push(admin.app, token, {"weights": [weight(at="2026-10-22T07:15:00")]})
    assert r.status_code == 400 and r.json()["detail"].startswith("weights.0.at: send the time with its zone")
    r = push(admin.app, token, {"readings": [reading(at="2026-10-22 07:15")]})
    assert r.status_code == 400 and r.json()["detail"].startswith("readings.0.at: send the time with its zone")
    assert rows(admin) == ([], [])


def test_the_row_is_dated_by_the_wall_clock_not_by_utc(admin, token):
    r = push(admin.app, token, {"weights": [weight("2026-10-22T23:50:00-04:00", 70, "kg")],
                                "readings": [reading("2026-10-22T00:10:00+14:00")]})
    assert r.status_code == 200
    (w,), (rd,) = rows(admin)
    assert (w["date"], w["time"]) == ("2026-10-22", "23:50") and (rd["date"], rd["time"]) == ("2026-10-22", "00:10")


def test_the_date_may_be_one_day_ahead_but_not_two_and_not_before_1900(admin, token):
    today = date.today()
    ok = push(admin.app, token, {"weights": [weight(f"{today + timedelta(days=1)}T07:00:00Z", 70, "kg")]})
    assert ok.status_code == 200
    r = push(admin.app, token, {"weights": [weight(f"{today + timedelta(days=2)}T07:00:00Z", 70, "kg")]})
    assert r.status_code == 400 and r.json()["detail"] == "weights.0.at: must not be in the future"
    r = push(admin.app, token, {"readings": [reading(f"{today + timedelta(days=2)}T07:00:00Z")]})
    assert r.status_code == 400 and r.json()["detail"] == "readings.0.at: must not be in the future"
    r = push(admin.app, token, {"weights": [weight("1899-12-31T07:00:00Z", 70, "kg")]})
    assert r.status_code == 400 and r.json()["detail"] == "weights.0.at: must be 1900 or later"
    assert push(admin.app, token, {"weights": [weight("1900-01-01T07:00:00Z", 70, "kg")]}).status_code == 200


@pytest.mark.parametrize("kind, time_, context", [
    ("weight", "03:59", "other"), ("weight", "04:00", "morning"), ("weight", "10:59", "morning"), ("weight", "11:00", "other"),
    ("weight", "17:00", "other"), ("weight", "23:59", "other"), ("weight", "00:00", "other"),
    ("reading", "03:59", "other"), ("reading", "04:00", "morning"), ("reading", "10:59", "morning"), ("reading", "11:00", "other"),
    ("reading", "16:59", "other"), ("reading", "17:00", "evening"), ("reading", "23:59", "evening"), ("reading", "00:00", "other"),
])
def test_the_context_comes_from_the_clock_time(admin, token, kind, time_, context):
    at = f"{DAY}T{time_}:00-04:00"
    body = {"weights": [weight(at, 70, "kg")]} if kind == "weight" else {"readings": [reading(at)]}
    assert push(admin.app, token, body).status_code == 200
    stored = rows(admin)[0 if kind == "weight" else 1]
    assert [(r["time"], r["context"], r["source"]) for r in stored] == [(time_, context, "shortcut")]
    assert B.context_for(kind, time_) == context


# --------------------------------------------------------------------------- numbers


def test_pounds_become_kilograms_rounded_half_up_to_a_hundredth(admin, token):
    sent = [("154.3", "lb", 69.99), (154.3, "lb", 69.99), (100, "lb", 45.36), ("220.462", "lb", 100.0), (70.255, "kg", 70.26),
            ("70.254", "kg", 70.25), ("70", "kg", 70.0), (70.0, "kg", 70.0), ("0.001", "kg", None), (399.995, "kg", 400.0)]  # 399.995 rounds half up to the heaviest weight the log takes
    out = []
    for i, (value, unit, want) in enumerate(sent):
        r = push(admin.app, token, {"weights": [weight(f"{DAY}T{7 + i:02d}:00:00-04:00", value, unit)]})
        if want is None:
            assert r.status_code == 400 and r.json()["detail"].startswith("weights.0.value: must be 20 to 400 kg"), (value, r.text)
        else:
            assert r.status_code == 200 and r.json() == counts(added_w=1), (value, unit, r.text)
            out.append(want)
    stored, _ = rows(admin)
    assert [w["kg"] for w in stored] == out
    assert B.lb_to_kg(154.3) == 69.99 and B.round_kg(70.255) == 70.26


def test_a_json_number_is_read_as_it_is_so_float_noise_is_fine_but_text_must_be_plain(admin, token):
    """A Shortcut may send 154.29999999999998; the same moment as the text "154.3" is the same weight."""
    raw = ('{"weights": [{"at": "%s", "value": 154.29999999999998, "unit": "lb", "source": "Health"}, '
           '{"at": "%sT08:00:00Z", "value": 1e2, "unit": "kg", "source": "Health"}, '
           '{"at": "%sT09:00:00Z", "value": 1.005E+2, "unit": "kg", "source": "Health"}]}') % (AT, DAY, DAY)
    assert push(admin.app, token, raw=raw.encode()).json() == counts(added_w=3)
    assert [w["kg"] for w in rows(admin)[0]] == [69.99, 100.0, 100.5]
    assert push(admin.app, token, {"weights": [weight(AT, "154.3", "lb", "Another")]}).json() == counts(there_w=1)  # the same reading
    for bad in ("1e999", "1e400", "-0", "123456789012", "0.5e1"):  # too large to be a weight, or no weight in range
        body = '{"weights": [{"at": "%s", "value": %s, "unit": "kg", "source": "H"}]}' % (AT, bad)
        assert push(admin.app, token, raw=body.encode()).status_code == 400, bad
    assert push(admin.app, token, raw=('{"weights": [{"at": "%s", "value": 1%s, "unit": "kg", "source": "H"}]}' % (AT, "0" * 500)).encode()
                ).status_code == 400
    assert len(rows(admin)[0]) == 3


@pytest.mark.parametrize("value, unit", [
    (19.99, "kg"), (400.01, "kg"), ("400.01", "kg"), (44.0, "lb"), (882.0, "lb"), (0, "kg"), (-70, "kg"), ("-70", "kg"), (True, "kg"),
    (None, "kg"), ("", "kg"), ("heavy", "kg"), ("1e2", "kg"), ("1,5", "kg"), ("70 kg", "kg"), ("1234", "kg"), ("70.1234", "kg"),
    ("NaN", "kg"), ([70], "kg"), ({"v": 70}, "kg"), ("7_0", "kg"), (".5", "kg"), ("５０", "kg"),
])
def test_a_weight_value_outside_the_range_or_not_a_plain_number_is_400(admin, token, value, unit):
    r = push(admin.app, token, {"weights": [weight(value=value, unit=unit)]})
    assert r.status_code == 400 and r.json()["detail"].startswith("weights.0.value:"), (value, r.text)
    assert rows(admin) == ([], [])


@pytest.mark.parametrize("systolic, diastolic, ok", [
    (122, 78, True), ("122", "78", True), (" 122 ", "78", True), (122.0, 78.0, True), (50, 20, True), (300, 200, True),
    (49, 30, False), (301, 100, False), (120, 19, False), (250, 201, False), (80, 80, False), (70, 90, False),
    (122.5, 78, False), (122, 77.5, False), ("122.5", 78, False), ("122.0", 78, False), ("abc", 78, False), (None, 78, False),
    (True, 78, False), (-120, 78, False), ("-120", 78, False), (1220, 78, False), ("1e2", 78, False), ([120], 78, False),
])
def test_reading_numbers_are_whole_and_in_range(admin, token, systolic, diastolic, ok):
    r = push(admin.app, token, {"readings": [reading(systolic=systolic, diastolic=diastolic)]})
    if ok:
        assert r.status_code == 200 and r.json() == counts(added_r=1), r.text
    else:
        assert r.status_code == 400 and r.json()["detail"].startswith("readings.0."), r.text
        assert rows(admin) == ([], [])


def test_the_top_number_must_be_above_the_bottom_number(admin, token):
    r = push(admin.app, token, {"readings": [reading(systolic=80, diastolic=80)]})
    assert r.status_code == 400 and r.json()["detail"] == "readings.0.systolic: systolic must be greater than diastolic"


def test_the_source_is_cleaned_and_must_be_one_to_sixty_characters(admin, token):
    for bad in ("", "   ", "\u0007\u0008", "x" * 61, "é" * 61):
        r = push(admin.app, token, {"weights": [weight(source=bad)]})
        assert r.status_code == 400 and r.json()["detail"].startswith("weights.0.source:"), repr(bad)
    r = push(admin.app, token, {"weights": [weight(source="x" * 600)]})
    assert r.status_code == 400
    assert push(admin.app, token, {"weights": [weight(source="  My\tscale \u0007 app  ")]}).status_code == 200
    assert push(admin.app, token, {"weights": [weight(f"{DAY}T08:00:00Z", source="x" * 60)]}).status_code == 200
    assert push(admin.app, token, {"weights": [weight(f"{DAY}T09:00:00Z", source="é" * 60)]}).status_code == 200
    assert len(rows(admin)[0]) == 3


# --------------------------------------------------------------------------- the watch rule


@pytest.mark.parametrize("source, watch", [
    ("Apple Watch", True), ("Sandra's Apple Watch", True), ("watch", True), ("WATCH", True), ("Stopwatch", True), ("Omron Connect", False),
    ("Health", False), ("Withings", False),
])
def test_a_reading_from_a_watch_is_not_stored_and_is_counted(admin, token, source, watch):
    r = push(admin.app, token, {"readings": [reading(source=source)]})
    assert r.status_code == 200
    assert r.json() == (counts(watch=1) if watch else counts(added_r=1))
    assert len(rows(admin)[1]) == (0 if watch else 1)
    assert B.is_watch_source(source) is watch


def test_a_weight_from_a_watch_is_kept_and_a_watch_reading_is_still_checked(admin, token):
    r = push(admin.app, token, {"weights": [weight(source="Apple Watch")], "readings": [reading(source="Apple Watch"), reading(
        f"{DAY}T08:00:00-04:00", source="Omron Connect")]})
    assert r.status_code == 200 and r.json() == counts(added_w=1, added_r=1, watch=1)
    r = push(admin.app, token, {"readings": [reading(f"{DAY}T09:00:00-04:00", systolic=500, source="Apple Watch")]})
    assert r.status_code == 400 and r.json()["detail"].startswith("readings.0.systolic:")  # refused only after it is a valid reading
    assert len(rows(admin)[1]) == 1


def test_watch_readings_take_no_room_in_a_day(admin, token):
    day = "2026-10-20"
    body = {"readings": [reading(f"{day}T{h:02d}:{m:02d}:00Z", 120 + (m % 7), 70, source="Apple Watch") for h in range(2) for m in range(40)]}
    r = push(admin.app, token, {"readings": body["readings"][:30]})
    assert r.status_code == 200 and r.json() == counts(watch=30)
    r = push(admin.app, token, {"readings": body["readings"][30:60]})
    assert r.status_code == 200 and r.json() == counts(watch=30)
    assert rows(admin, day, day)[1] == []


# --------------------------------------------------------------------------- all or nothing, limits, the answer


def test_the_first_invalid_row_names_itself_and_nothing_is_written(admin, token):
    body = {"weights": [weight(f"{DAY}T06:00:00Z", 70, "kg"), weight(f"{DAY}T07:00:00Z", 71, "kg"), weight(f"{DAY}T08:00:00Z", 5, "kg")],
            "readings": [reading(f"{DAY}T06:00:00Z"), reading(f"{DAY}T07:00:00Z", systolic=1)]}
    r = push(admin.app, token, body)
    assert r.status_code == 400 and r.json()["detail"].startswith("weights.2.value:")
    body["weights"][2] = weight(f"{DAY}T08:00:00Z", 72, "kg")
    r = push(admin.app, token, body)
    assert r.status_code == 400 and r.json()["detail"].startswith("readings.1.systolic:")
    assert rows(admin) == ([], [])
    body["readings"][1] = reading(f"{DAY}T07:00:00Z")
    assert push(admin.app, token, body).json() == counts(added_w=3, added_r=2)


def test_a_day_holds_at_most_20_weights_and_30_readings_as_everywhere(admin, token):
    day = "2026-10-21"
    w = [weight(f"{day}T{h:02d}:{m:02d}:00Z", 60 + h + m / 100, "kg") for h in range(2) for m in (0, 10, 20, 30, 40, 50)]  # 12 distinct
    more = [weight(f"{day}T{h:02d}:00:00Z", 80 + h, "kg") for h in range(10, 20)]  # 10 more
    assert push(admin.app, token, {"weights": w}).json() == counts(added_w=12)
    r = push(admin.app, token, {"weights": more})  # 12 + 10 = 22: the request is refused whole
    assert r.status_code == 400 and r.json()["detail"] == "weights.8: too many weights for one day (max 20)"
    assert len(rows(admin, day, day)[0]) == 12
    assert push(admin.app, token, {"weights": more[:8]}).json() == counts(added_w=8)  # exactly 20
    r = push(admin.app, token, {"weights": [weight(f"{day}T23:00:00Z", 99, "kg")]})
    assert r.status_code == 400 and r.json()["detail"] == "weights.0: too many weights for one day (max 20)"
    # a row that is already there never counts against the day
    assert push(admin.app, token, {"weights": [w[0]]}).json() == counts(there_w=1)
    # a manual weight counts toward the same limit (one limit per person and day)
    other = "2026-10-19"
    for i in range(20):
        assert admin.post("/api/body/weights", json={"date": other, "kg": 60 + i, "context": "other"}).status_code == 201
    r = push(admin.app, token, {"weights": [weight(f"{other}T07:00:00Z", 99, "kg")]})
    assert r.status_code == 400 and "too many weights for one day" in r.json()["detail"]
    # readings: 30
    rd = [reading(f"{day}T{h:02d}:{m:02d}:00Z", 110 + (h + m) % 40, 70) for h in range(5) for m in (0, 10, 20, 30, 40, 50)]
    assert len(rd) == 30
    assert push(admin.app, token, {"readings": rd}).json() == counts(added_r=30)
    r = push(admin.app, token, {"readings": [reading(f"{day}T23:00:00Z")]})
    assert r.status_code == 400 and r.json()["detail"] == "readings.0: too many blood pressure readings for one day (max 30)"


def test_the_answer_holds_counts_only(admin, token):
    r = push(admin.app, token, {"weights": [weight()], "readings": [reading(), reading(f"{DAY}T08:00:00Z", source="Apple Watch")]})
    assert r.status_code == 200
    body = r.json()
    assert body == counts(added_w=1, added_r=1, watch=1) and set(body) == {"added", "already_there", "refused"}
    text = r.text
    for secret in ("154.3", "69.99", "122", "78", "Omron", "Health", "Watch", DAY, "id"):
        assert secret not in text.replace('"already_there"', "").replace('"added"', ""), secret
    assert r.headers["cache-control"] == "no-store"
    again = push(admin.app, token, {"weights": [weight()], "readings": [reading()]})
    assert again.json() == counts(there_w=1, there_r=1)


def test_the_rate_limit_is_60_requests_an_hour_per_token(admin, token):
    other = make_device(admin, "Other phone")["token"]
    for i in range(60):
        r = push(admin.app, token, {})  # a refused body still counts: the limit is on requests that got past the token
        assert r.status_code == 400, i
    r = push(admin.app, token, {"weights": [weight()]})
    assert r.status_code == 429 and int(r.headers["retry-after"]) > 0
    assert push(admin.app, other, {"weights": [weight()]}).status_code == 200  # another token has its own hour
    assert rows(admin)[0] and len(rows(admin)[0]) == 1
    # the body routes' own per-person limit is separate
    assert admin.post("/api/body/weights/batch", json={"rows": [{"date": DAY, "kg": 70, "context": "other", "source_key": "z1"}]}).status_code == 200


def test_the_rate_limit_window_moves_with_the_clock(admin, token, fake_clock, monkeypatch):
    from app.auth import clock as auth_clock

    monkeypatch.setattr(auth_clock, "seconds", lambda: fake_clock.now().timestamp())
    for _ in range(60):
        assert push(admin.app, token, {}).status_code == 400
    assert push(admin.app, token, {}).status_code == 429
    fake_clock.advance(minutes=61)
    assert push(admin.app, token, {}).status_code == 400


# --------------------------------------------------------------------------- what is stored, what is logged


def test_rows_are_marked_shortcut_with_the_token_and_shown_with_its_name(admin):
    a = make_device(admin, "Morning weight")
    b = make_device(admin, "Evening cuff")
    assert push(admin.app, a["token"], {"weights": [weight()]}).status_code == 200
    assert push(admin.app, b["token"], {"readings": [reading()]}).status_code == 200
    admin.post("/api/body/weights", json={"date": DAY, "time": "20:00", "kg": 70, "context": "other"})
    ws, rs = rows(admin)
    assert [(w["source"], w["via"]) for w in ws] == [("shortcut", "Morning weight"), ("manual", None)]
    assert [(r["source"], r["via"], r["context"], r["note"]) for r in rs] == [("shortcut", "Evening cuff", "morning", "")]
    assert ws[0]["kg"] == 69.99 and ws[0]["time"] == "07:15" and ws[0]["context"] == "morning" and ws[0]["note"] == ""
    summary = admin.get(f"/api/body/summary?date={DAY}").json()
    assert summary["weight"]["latest"]["via"] is None  # the manual weight at 20:00 is the latest
    assert summary["bp"]["latest"]["via"] == "Evening cuff"
    conn = __import__("test_api_tokens").db(admin)
    try:
        stored = conn.execute("SELECT api_token_id, source, pulse FROM blood_pressures").fetchone()
        assert (stored["api_token_id"], stored["source"], stored["pulse"]) == (b["id"], "shortcut", None)
    finally:
        conn.close()


def test_a_high_reading_gets_its_flag_when_the_app_shows_it_and_nothing_else(admin, token):
    assert push(admin.app, token, {"readings": [reading(systolic=185, diastolic=100)]}).json() == counts(added_r=1)
    (r,) = rows(admin)[1]
    assert r["flag"]["level"] == "emergency" and r["flag"]["href"] == "/learn/get-help-now/"


def test_values_never_reach_the_log(admin, token, caplog):
    caplog.set_level(logging.DEBUG)
    body = {"weights": [weight("2026-10-22T06:41:00+02:00", "73.37", "kg", "Secret Scale 9000")],
            "readings": [reading("2026-10-22T06:43:00+02:00", 133, 77, "Hidden Cuff 7")]}
    assert push(admin.app, token, body).status_code == 200
    assert push(admin.app, token, body).status_code == 200  # the second time: "already there" is logged by counts too
    assert push(admin.app, token, {"weights": [weight("2026-10-22T06:41:00+02:00", "8", "kg", "Secret Scale 9000")]}).status_code == 400
    assert push(admin.app, "khd_" + "Z" * 43, body).status_code == 401
    log = caplog.text
    for secret in ("73.37", "Secret Scale", "Hidden Cuff", "133", "06:41", "06:43", token, "2026-10-22T06", "khd_"):
        assert secret not in log, secret
    assert re.search(r"push: token \d+ added 1 weights and 1 readings", log)
    assert re.search(r"push: token \d+ added 0 weights and 0 readings, 2 already there", log)


# --------------------------------------------------------------------------- source_key and "the same reading"


def test_source_key_is_the_one_the_health_export_reader_builds():
    """The key texts of ``tests/data/apple_health_vectors.json`` (hand-written from export.xml fragments) come out of the route's
    builders, from the startDate the reader saw sent the way a Shortcut sends it."""
    from app.push import reading_key_text, source_key, weight_key_text

    doc = json.loads((ROOT / "tests" / "data" / "apple_health_vectors.json").read_text(encoding="utf-8"))
    seen = 0
    for case in doc["cases"]:
        for row in case["expected"]["weights"] + case["expected"]["readings"]:
            kind, start, value, *source = row["key_input"].split("|")
            name = "|".join(source)
            iso = re.sub(r"^(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2}) ([+-]\d{2})(\d{2})$", r"\1T\2\3:\4", start)
            moment = parse_at(iso)
            assert moment.stamp == start, (case["name"], start)
            if kind == "BloodPressure":
                top, bottom = value.split("/")
                if not (top.isdigit() and bottom.isdigit()):
                    continue  # the export can hold 119.5; a shortcut sends whole numbers
                text = reading_key_text(moment.stamp, int(top), int(bottom), name)
            else:
                text = weight_key_text(moment.stamp, value, name)
            assert text == row["key_input"] and source_key(text) == row["source_key"], (case["name"], row["key_input"])
            seen += 1
    assert seen >= 8


def test_a_pushed_row_has_the_export_readers_key_and_a_later_import_of_the_same_file_row_adds_nothing(admin, token):
    key_w = "HKQuantityTypeIdentifierBodyMass|2026-10-19 07:15:00 -0400|154.3|Health"
    key_r = "BloodPressure|2026-10-19 07:20:00 -0400|122/78|Omron Connect"
    from app.push import source_key

    body = {"weights": [weight("2026-10-19T07:15:00-04:00", "154.3", "lb", "Health")],
            "readings": [reading("2026-10-19T07:20:00-04:00", 122, 78, "Omron Connect")]}
    assert push(admin.app, token, body).json() == counts(added_w=1, added_r=1)
    conn = __import__("test_api_tokens").db(admin)
    try:
        assert conn.execute("SELECT source_key FROM weights").fetchone()[0] == source_key(key_w)
        assert conn.execute("SELECT source_key FROM blood_pressures").fetchone()[0] == source_key(key_r)
    finally:
        conn.close()
    # the Health import then sends the same two rows with the same keys (and, in other tests, with different keys)
    imp_w = {"rows": [{"date": "2026-10-19", "time": "07:15", "kg": 69.99, "context": "morning", "source": "apple_health", "source_key": source_key(key_w)}]}
    imp_r = {"rows": [{"date": "2026-10-19", "time": "07:20", "systolic": 122, "diastolic": 78, "context": "morning", "source": "apple_health",
                       "source_key": source_key(key_r)}]}
    assert admin.post("/api/body/weights/batch", json=imp_w).json() == {"added": 0, "skipped": 1}
    assert admin.post("/api/body/blood-pressure/batch", json=imp_r).json() == {"added": 0, "skipped": 1}


def test_push_then_import_and_import_then_push_leave_one_row_each(admin, token):
    day = "2026-10-18"
    # the import first, with keys the shortcut cannot match
    assert admin.post("/api/body/weights/batch", json={"rows": [
        {"date": day, "time": "07:15", "kg": 69.99, "context": "morning", "source": "apple_health", "source_key": "imp-w"}]}).json() == {"added": 1, "skipped": 0}
    assert admin.post("/api/body/blood-pressure/batch", json={"rows": [
        {"date": day, "time": "07:20", "systolic": 122, "diastolic": 78, "context": "morning", "source": "apple_health",
         "source_key": "imp-r"}]}).json() == {"added": 1, "skipped": 0}
    # then the shortcut sends the same moments: other source names, other value text, another zone (the wall clock counts, as written)
    r = push(admin.app, token, {"weights": [weight(f"{day}T07:15:00Z", "69.99", "kg", "Some app")],
                                "readings": [reading(f"{day}T07:20:00-04:00", "122", "78", "Another cuff")]})
    assert r.json() == counts(there_w=1, there_r=1)
    r = push(admin.app, token, {"weights": [weight(f"{day}T07:15:00-04:00", "154.3", "lb", "Third app")]})  # 154.3 lb is 69.99 kg
    assert r.json() == counts(there_w=1)
    ws, rs = rows(admin, day, day)
    assert [w["source"] for w in ws] == ["apple_health"] and [x["source"] for x in rs] == ["apple_health"]
    # the other way round: a pushed row, then an import of a row at the same minute with numbers the person has
    day2 = "2026-10-14"
    assert push(admin.app, token, {"weights": [weight(f"{day2}T07:15:00-04:00", "154.3", "lb", "Scale app")],
                                   "readings": [reading(f"{day2}T07:20:00-04:00", 130, 85, "Cuff app")]}).json() == counts(added_w=1, added_r=1)
    assert admin.post("/api/body/weights/batch", json={"rows": [
        {"date": day2, "time": "07:15", "kg": 69.99, "context": "morning", "source": "apple_health", "source_key": "imp2-w"}]}).json() == {"added": 0, "skipped": 1}
    assert admin.post("/api/body/blood-pressure/batch", json={"rows": [
        {"date": day2, "time": "07:20", "systolic": 130, "diastolic": 85, "context": "morning", "source": "apple_health",
         "source_key": "imp2-r"}]}).json() == {"added": 0, "skipped": 1}
    ws, rs = rows(admin, day2, day2)
    assert [w["source"] for w in ws] == ["shortcut"] and [x["source"] for x in rs] == ["shortcut"]


def test_import_after_push_adds_nothing_even_with_other_keys(admin, token):
    day = "2026-10-17"
    assert push(admin.app, token, {"weights": [weight(f"{day}T07:15:00-04:00", "154.3", "lb", "Scale app")],
                                   "readings": [reading(f"{day}T07:20:00-04:00", 122, 78, "Cuff app")]}).json() == counts(added_w=1, added_r=1)
    r = admin.post("/api/body/weights/batch", json={"rows": [
        {"date": day, "time": "07:15", "kg": 69.99, "context": "morning", "source": "apple_health", "source_key": "other-key-w"}]})
    assert r.json() == {"added": 0, "skipped": 1}
    r = admin.post("/api/body/blood-pressure/batch", json={"rows": [
        {"date": day, "time": "07:20", "systolic": 122, "diastolic": 78, "context": "morning", "source": "import", "source_key": "other-key-r"}]})
    assert r.json() == {"added": 0, "skipped": 1}
    ws, rs = rows(admin, day, day)
    assert [w["source"] for w in ws] == ["shortcut"] and [x["source"] for x in rs] == ["shortcut"]


def test_a_typed_twin_is_never_matched_in_either_direction(admin, token):
    day = "2026-10-16"
    assert admin.post("/api/body/weights", json={"date": day, "time": "07:15", "kg": 69.99, "context": "morning"}).status_code == 201
    assert admin.post("/api/body/blood-pressure", json={"date": day, "time": "07:20", "systolic": 122, "diastolic": 78,
                                                       "context": "morning"}).status_code == 201
    r = push(admin.app, token, {"weights": [weight(f"{day}T07:15:00-04:00", "154.3", "lb")], "readings": [reading(f"{day}T07:20:00-04:00")]})
    assert r.json() == counts(added_w=1, added_r=1)  # the person may have typed the same reading on purpose
    r = admin.post("/api/body/weights/batch", json={"rows": [
        {"date": day, "time": "07:15", "kg": 69.99, "context": "morning", "source": "apple_health", "source_key": "x1"}]})
    assert r.json() == {"added": 0, "skipped": 1}  # but the pushed one is not manual: this one is the same reading
    ws, _ = rows(admin, day, day)
    assert sorted(w["source"] for w in ws) == ["manual", "shortcut"]
    # editing a pushed row makes it the person's own: it no longer matches
    shortcut = next(w for w in ws if w["source"] == "shortcut")
    assert admin.put(f"/api/body/weights/{shortcut['id']}", json={"date": day, "time": "07:15", "kg": 69.99, "context": "morning"}).status_code == 200
    assert push(admin.app, token, {"weights": [weight(f"{day}T07:15:00-04:00", "154.3", "lb", "Another")]}).json() == counts(added_w=1)


def test_the_same_reading_needs_the_same_minute_and_numbers(admin, token):
    day = "2026-10-15"
    base = {"weights": [weight(f"{day}T07:15:00-04:00", 70, "kg")], "readings": [reading(f"{day}T07:20:00-04:00", 122, 78)]}
    assert push(admin.app, token, base).json() == counts(added_w=1, added_r=1)
    near = {"weights": [weight(f"{day}T07:16:00-04:00", 70, "kg", "B"), weight(f"{day}T07:15:00-04:00", 70.01, "kg", "C")],
            "readings": [reading(f"{day}T07:21:00-04:00", 122, 78, "B"), reading(f"{day}T07:20:00-04:00", 122, 79, "C"),
                         reading(f"{day}T07:20:00-04:00", 123, 78, "D")]}
    assert push(admin.app, token, near).json() == counts(added_w=2, added_r=3)
    # the same minute but a different second and source: still the same reading
    same = {"weights": [weight(f"{day}T07:15:59-04:00", "70.00", "kg", "E")], "readings": [reading(f"{day}T07:20:59-04:00", 122, 78, "E")]}
    assert push(admin.app, token, same).json() == counts(there_w=1, there_r=1)


def test_two_alike_rows_in_one_request_are_one(admin, token):
    body = {"weights": [weight(AT, 70, "kg", "A"), weight(AT, 70, "kg", "B")], "readings": [reading(), reading(source="Another cuff")]}
    assert push(admin.app, token, body).json() == counts(added_w=1, added_r=1, there_w=1, there_r=1)


def test_one_persons_rows_never_make_another_persons_reading_a_duplicate(two_clients):
    admin, sam = two_clients
    push_switch(admin, True)
    mine, theirs = make_device(admin, "Mine")["token"], make_device(sam, "Sam's")["token"]
    body = {"weights": [weight()], "readings": [reading()]}
    assert push(admin.app, mine, body).json() == counts(added_w=1, added_r=1)
    assert push(admin.app, theirs, body).json() == counts(added_w=1, added_r=1)  # same key text, another person: both are kept
    assert len(rows(admin)[0]) == 1 and len(rows(sam)[0]) == 1
    assert push(admin.app, mine, body).json() == counts(there_w=1, there_r=1)
    assert rows(sam)[0][0]["via"] == "Sam's" and rows(admin)[0][0]["via"] == "Mine"


def test_a_token_reads_nothing(admin, token):
    """The device token opens no read route, not even the body list it wrote to (the route table has no GET)."""
    assert push(admin.app, token, {"weights": [weight()]}).status_code == 200
    for method, path in (("GET", "/api/body/weights?start=2026-10-01&end=2026-10-31"), ("GET", "/api/body/summary?date=2026-10-22"),
                         ("GET", "/api/me"), ("GET", "/api/me/tokens?family=device"), ("DELETE", "/api/body/weights/1")):
        r = bare(admin.app).request(method, path, headers={"Authorization": f"Bearer {token}", **CSRF_HEADERS})
        assert r.status_code == 401, (method, path)
    r = bare(admin.app).get("/mcp", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code in (404, 405)
    r = bare(admin.app).post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"}, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code in (401, 404)
