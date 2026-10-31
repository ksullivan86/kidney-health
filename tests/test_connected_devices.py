"""Connected devices and Withings (design note 27; app/devices/). A fake Withings (tests/devices_support.py) answers behind the
app's real SSRF-checked transport; nothing touches the network.

Covered: the switch (404 while off) and an unset provider; the way out and back (state bound to the person and the session, used
once, wrong or reused state, another person, another session, cancel, missing scope, an account connected to someone else, a test
account); tokens sealed at rest, bound to their owner and never in a response or a log line; the sync (unit decoding, the time zone,
ambiguous and goal measures left out, a pulse alone left out, pagination, the "changed since" mark); the ledger (a second sync adds
nothing, a deleted reading stays deleted); never overwriting or doubling a typed reading; refresh with rotation; a refused refresh
→ needs reconnect; "too many requests"; Sync now's 10-minute rule; disconnect (keep or delete readings, edited rows kept, the
signed revoke); isolation between people; the background pass; config rules; Server administration never shows the secret.
"""
from __future__ import annotations

import logging
import sqlite3
import time
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

import pytest

from app.config import ConfigError, load_settings
from app.crypto import InvalidToken
from app.db import connect
from app.devices import store, sync as devices_sync, withings
from conftest import HTTPS_URL, TestClient, add_user, make_settings, signed_in_client
from devices_support import APP_KEY, CLIENT_SECRET, FakeWithings, attach, bp_group, env, weight_group

NOW = int(time.time())
DAY = 86400


def local(epoch: int, zone: str = "Europe/Paris") -> tuple[str, str]:
    moment = datetime.fromtimestamp(epoch, tz=timezone.utc).astimezone(ZoneInfo(zone))
    return moment.strftime("%Y-%m-%d"), moment.strftime("%H:%M")


def at_local(days_ago: int, hour: int, minute: int = 0, zone: str = "Europe/Paris") -> int:
    """A Unix time ``days_ago`` days back at ``hour:minute`` on the clock of ``zone``."""
    today = datetime.now(ZoneInfo(zone)).date()
    from datetime import timedelta

    day = today - timedelta(days=days_ago)
    return int(datetime(day.year, day.month, day.day, hour, minute, tzinfo=ZoneInfo(zone)).timestamp())


@pytest.fixture
def dev(tmp_path: Path, foods_json: Path):
    s = make_settings(tmp_path, foods_json, public_url=HTTPS_URL, withings=env())
    with signed_in_client(s, base_url=HTTPS_URL) as admin:
        assert admin.patch("/api/admin/settings", json={"devices.enabled": True}).status_code == 200
        fake = attach(admin.app, FakeWithings())
        yield admin, fake


def db(client: TestClient) -> sqlite3.Connection:
    return connect(client.app.state.settings.db_path)


def uid(client: TestClient) -> int:
    return int(client.get("/api/me").json()["id"])


def start(client: TestClient) -> dict[str, str]:
    r = client.post("/api/devices/withings/start")
    assert r.status_code == 200, r.text
    url = r.json()["url"]
    assert url.startswith("https://account.withings.com/oauth2_user/authorize2?")
    return {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}


def back(client: TestClient, **params: str) -> str:
    r = client.get("/api/devices/withings/callback", params=params, follow_redirects=False)
    assert r.status_code == 303, r.text
    return r.headers["location"]


def connect_withings(client: TestClient, fake: FakeWithings) -> str:
    q = start(client)
    return back(client, code=fake.issue_code(q["redirect_uri"]), state=q["state"])


def rewind(client: TestClient) -> None:
    """Let Sync now run again (it waits 10 minutes between runs)."""
    with db(client) as conn:
        conn.execute("UPDATE device_connections SET last_sync_at = NULL, next_sync_after = NULL")


def sync(client: TestClient) -> dict[str, Any]:
    rewind(client)
    r = client.post("/api/devices/withings/sync")
    assert r.status_code == 200, r.text
    return r.json()


# --------------------------------------------------------------------------- #
# The switch and the provider
# --------------------------------------------------------------------------- #


def test_off_by_default_every_route_is_404(client: TestClient) -> None:
    assert client.get("/api/devices").status_code == 404
    assert client.post("/api/devices/withings/start").status_code == 404
    assert client.get("/api/devices/withings/callback", params={"code": "x", "state": "y"}).status_code == 404
    assert client.post("/api/devices/withings/sync").status_code == 404
    assert client.delete("/api/devices/withings").status_code == 404


def test_anonymous_is_401(anon_client: TestClient) -> None:
    assert anon_client.get("/api/devices").status_code == 401
    assert anon_client.get("/api/devices/withings/callback", params={"code": "x", "state": "y"}).status_code == 401


def test_on_without_a_withings_app_shows_it_as_not_set_up(client: TestClient) -> None:
    assert client.patch("/api/admin/settings", json={"devices.enabled": True}).status_code == 200
    body = client.get("/api/devices").json()
    assert body["enabled"] is True and body["sync_hours"] == 4
    (w,) = body["providers"]
    assert w["id"] == "withings" and w["available"] is False and w["connection"] is None
    assert w["what"] == ["weight", "blood pressure", "pulse"]
    assert client.post("/api/devices/withings/start").status_code == 404


def test_the_switch_off_again_hides_a_connection_and_stops_the_loop(dev) -> None:
    admin, fake = dev
    connect_withings(admin, fake)
    admin.patch("/api/admin/settings", json={"devices.enabled": False})
    assert admin.get("/api/devices").status_code == 404
    assert admin.post("/api/devices/withings/sync").status_code == 404
    app = admin.app
    assert devices_sync.run_due(app.state.devices, app.state.keyring, app.state.settings_store, app.state.settings.db_path) == 0
    admin.patch("/api/admin/settings", json={"devices.enabled": True})
    assert admin.get("/api/devices").json()["providers"][0]["connection"]["status"] == "active"


# --------------------------------------------------------------------------- #
# Connecting
# --------------------------------------------------------------------------- #


def test_connect_asks_only_for_measures_and_returns_to_the_exact_address(dev) -> None:
    admin, fake = dev
    q = start(admin)
    assert q["scope"] == "user.metrics" and q["response_type"] == "code" and q["client_id"] == "kh-test-client"
    assert q["redirect_uri"] == "https://localhost/api/devices/withings/callback"
    assert len(q["state"]) >= 40
    assert back(admin, code=fake.issue_code(q["redirect_uri"]), state=q["state"]) == "/#/devices/connected/withings"
    token_call = [c for c in fake.calls if c["form"].get("action") == "requesttoken"][0]
    assert token_call["host"] == "wbsapi.withings.net"
    assert set(token_call["form"]) == {"action", "grant_type", "client_id", "client_secret", "code", "redirect_uri"}
    conn = admin.get("/api/devices").json()["providers"][0]["connection"]
    assert conn["status"] == "active" and conn["last_error"] is None and conn["imported"] == {"weights": 0, "readings": 0}
    acts = [e["action"] for e in admin.get("/api/me/activity").json()["events"]]
    assert "device.connected" in acts


def test_a_state_works_once_and_a_made_up_one_never(dev) -> None:
    admin, fake = dev
    q = start(admin)
    code = fake.issue_code(q["redirect_uri"])
    assert back(admin, code=code, state="made-up") == "/#/devices/expired/withings"
    assert back(admin, code=code, state=q["state"]) == "/#/devices/connected/withings"
    assert back(admin, code=code, state=q["state"]) == "/#/devices/expired/withings"


def test_the_state_is_only_for_the_person_and_session_that_started_it(dev) -> None:
    admin, fake = dev
    sam = add_user(admin)
    q = start(admin)
    code = fake.issue_code(q["redirect_uri"])
    assert back(sam, code=code, state=q["state"]) == "/#/devices/wrong_account/withings"
    # the same person on another device (another session) cannot finish it either
    q = start(admin)
    other = TestClient(admin.app, base_url=HTTPS_URL)
    other.post("/api/auth/login", json={"username": "admin", "password": admin.app.state.settings.admin_password})
    assert back(other, code=fake.issue_code(q["redirect_uri"]), state=q["state"]) == "/#/devices/wrong_account/withings"
    assert fake.codes  # the codes were never sent to Withings
    with db(admin) as conn:
        assert conn.execute("SELECT COUNT(*) FROM device_connections").fetchone()[0] == 0


def test_cancel_and_missing_scope(dev) -> None:
    admin, fake = dev
    q = start(admin)
    assert back(admin, error="access_denied", state=q["state"]) == "/#/devices/cancelled/withings"
    fake.scope = "user.info"
    q = start(admin)
    assert back(admin, code=fake.issue_code(q["redirect_uri"]), state=q["state"]) == "/#/devices/scope/withings"
    with db(admin) as conn:
        assert conn.execute("SELECT COUNT(*) FROM device_connections").fetchone()[0] == 0


def test_one_withings_account_belongs_to_one_person_here(dev) -> None:
    admin, fake = dev
    sam = add_user(admin)
    connect_withings(admin, fake)
    assert connect_withings(sam, fake) == "/#/devices/taken/withings"
    assert sam.get("/api/devices").json()["providers"][0]["connection"] is None
    assert admin.post("/api/devices/withings/start").status_code == 409  # already connected


def test_a_test_account_cannot_connect(dev) -> None:
    admin, fake = dev
    sam = add_user(admin)
    q = start(sam)
    with db(admin) as conn:
        conn.execute("UPDATE users SET is_test_account = 1 WHERE username = 'sam'")
    r = sam.post("/api/devices/withings/start")
    assert r.status_code == 403 and "Test accounts cannot connect" in r.json()["detail"]
    assert sam.get("/api/devices").json()["can_connect"] is False
    assert back(sam, code=fake.issue_code(q["redirect_uri"]), state=q["state"]) == "/#/devices/test_account/withings"


def test_withings_unreachable_or_a_private_address_is_unavailable(dev) -> None:
    admin, fake = dev
    provider = admin.app.state.devices.providers["withings"]
    provider.resolver = lambda host, port: ["10.0.0.5"]
    q = start(admin)
    assert back(admin, code=fake.issue_code(q["redirect_uri"]), state=q["state"]) == "/#/devices/unavailable/withings"
    assert not [c for c in fake.calls if c["form"].get("action") == "requesttoken"]


# --------------------------------------------------------------------------- #
# Tokens at rest, in answers and in logs
# --------------------------------------------------------------------------- #


def test_tokens_are_sealed_bound_to_their_owner_and_never_shown(dev, caplog: pytest.LogCaptureFixture) -> None:
    admin, fake = dev
    caplog.set_level(logging.DEBUG)
    q = start(admin)
    code = fake.issue_code(q["redirect_uri"])
    back(admin, code=code, state=q["state"])
    fake.groups = [weight_group(1, at_local(1, 7, 10))]
    sync(admin)
    access, refresh = fake.access, fake.refresh
    assert access and refresh
    with db(admin) as conn:
        dump = "\n".join(conn.iterdump())
        row = conn.execute("SELECT * FROM device_connections").fetchone()
    for secret in (access, refresh, code, q["state"], CLIENT_SECRET):
        assert secret not in dump
        assert secret not in caplog.text
    keyring = admin.app.state.keyring
    assert store.load_tokens(keyring, row) == (access, refresh)
    with pytest.raises(InvalidToken):
        keyring.unseal(row["tokens_enc"], purpose="device:withings", owner=row["user_id"] + 1)
    for path in ("/api/devices", "/api/admin/about", "/api/me/activity", "/api/me/export"):
        text = admin.get(path).text
        for secret in (access, refresh, CLIENT_SECRET, "4242"):
            assert secret not in text, path
    about = admin.get("/api/admin/about").json()["devices"]
    w = about["providers"][0]
    assert about["enabled"] is True and w["secret"] == "set" and w["client_id"] == "kh-test-client"
    assert w["redirect_uri"] == "https://localhost/api/devices/withings/callback" and w["connected"] == {"active": 1}


def test_rotating_the_secret_key_reencrypts_the_tokens() -> None:
    from app.crypto import ENCRYPTED_COLUMNS

    assert ("device_connections", "id", "tokens_enc", "key_id") in ENCRYPTED_COLUMNS


# --------------------------------------------------------------------------- #
# Syncing
# --------------------------------------------------------------------------- #


def test_sync_brings_weights_and_readings_on_the_persons_clock(dev) -> None:
    admin, fake = dev
    connect_withings(admin, fake)
    w_at, bp_at, eve = at_local(2, 7, 15), at_local(2, 7, 20), at_local(1, 19, 5)
    fake.groups = [
        weight_group(11, w_at, value=75123, unit=-3),  # 75.123 kg -> 75.12
        bp_group(12, bp_at, systolic=131, diastolic=82, pulse=66),
        bp_group(13, eve, systolic=140, diastolic=90, pulse=None),
        weight_group(14, w_at + 60, attrib=1),  # ambiguous: maybe a guest on the scale
        weight_group(15, w_at + 120, category=2),  # a goal
        {"grpid": 16, "attrib": 0, "date": w_at, "modified": w_at, "category": 1, "measures": [{"value": 70, "type": 11, "unit": 0}]},
    ]
    out = sync(admin)
    assert out["error"] is None
    assert out["result"]["added"] == {"weights": 1, "readings": 2}
    assert out["result"]["left_out"] == 3
    day, clock = local(w_at)
    weights = admin.get("/api/body/weights", params={"start": day, "end": day}).json()["weights"]
    assert [(w["time"], w["kg"], w["source"], w["context"]) for w in weights] == [(clock, 75.12, "withings", "morning")]
    rows = admin.get("/api/body/blood-pressure", params={"start": local(bp_at)[0], "end": local(eve)[0]}).json()["readings"]
    got = sorted((r["date"], r["time"], r["systolic"], r["diastolic"], r["pulse"], r["context"]) for r in rows)
    assert got == sorted([(*local(bp_at), 131, 82, 66, "morning"), (*local(eve), 140, 90, None, "evening")])
    conn_view = out["connection"]
    assert conn_view["imported"] == {"weights": 1, "readings": 2} and conn_view["last_success_at"]
    # the "changed since" mark: the first fetch reached a year back, the next one sends Withings' updatetime
    measure_calls = [c["form"] for c in fake.calls if c["form"].get("action") == "getmeas"]
    assert measure_calls[0]["meastypes"] == "1,9,10,11" and measure_calls[0]["category"] == "1"
    assert abs(int(measure_calls[0]["lastupdate"]) - (NOW - 365 * DAY)) < 3600
    sync(admin)
    assert [c["form"] for c in fake.calls if c["form"].get("action") == "getmeas"][-1]["lastupdate"] == str(fake.updatetime)


def test_pages_are_followed(dev) -> None:
    admin, fake = dev
    connect_withings(admin, fake)
    fake.page_size = 2
    fake.groups = [weight_group(100 + i, at_local(3, 7, i)) for i in range(5)]
    assert sync(admin)["result"]["added"]["weights"] == 5
    assert len([c for c in fake.calls if c["form"].get("action") == "getmeas"]) == 3


def test_the_ledger_skips_what_was_seen_and_a_deleted_reading_stays_deleted(dev) -> None:
    admin, fake = dev
    connect_withings(admin, fake)
    t = at_local(1, 8, 0)
    fake.groups = [weight_group(21, t), bp_group(22, t)]
    sync(admin)
    with db(admin) as conn:
        conn.execute("UPDATE device_connections SET sync_cursor = NULL")  # Withings sends everything again
    second = sync(admin)["result"]
    assert second["added"] == {"weights": 0, "readings": 0} and second["already_there"] == 2
    day = local(t)[0]
    (w,) = admin.get("/api/body/weights", params={"start": day, "end": day}).json()["weights"]
    assert admin.delete(f"/api/body/weights/{w['id']}").status_code == 204
    with db(admin) as conn:
        conn.execute("UPDATE device_connections SET sync_cursor = NULL")
    sync(admin)
    assert admin.get("/api/body/weights", params={"start": day, "end": day}).json()["weights"] == []


def test_a_typed_reading_is_never_changed_or_doubled(dev) -> None:
    admin, fake = dev
    t = at_local(1, 7, 30)
    day, clock = local(t)
    typed = admin.post("/api/body/blood-pressure", json={"date": day, "time": clock, "systolic": 128, "diastolic": 79,
                                                         "context": "morning", "note": "left arm"}).json()
    other = admin.post("/api/body/weights", json={"date": day, "time": clock, "kg": 80, "context": "morning"}).json()
    connect_withings(admin, fake)
    fake.groups = [bp_group(31, t, systolic=128, diastolic=79), weight_group(32, t, value=7512, unit=-2)]
    out = sync(admin)["result"]
    assert out["added"] == {"weights": 1, "readings": 0} and out["already_there"] == 1
    readings = admin.get("/api/body/blood-pressure", params={"start": day, "end": day}).json()["readings"]
    assert [(r["id"], r["note"], r["source"]) for r in readings] == [(typed["id"], "left arm", "manual")]
    weights = admin.get("/api/body/weights", params={"start": day, "end": day}).json()["weights"]
    assert {(w["kg"], w["source"]) for w in weights} == {(80, "manual"), (75.12, "withings")}
    assert [w for w in weights if w["id"] == other["id"]][0]["updated_at"] == other["updated_at"]


def test_out_of_range_values_are_skipped(dev) -> None:
    admin, fake = dev
    connect_withings(admin, fake)
    t = at_local(1, 9, 0)
    fake.groups = [weight_group(41, t, value=5, unit=0), bp_group(42, t, systolic=80, diastolic=90),
                   bp_group(43, t + 60, systolic=120, diastolic=80, pulse=400)]
    out = sync(admin)["result"]
    assert out["added"] == {"weights": 0, "readings": 1} and out["skipped"] == 2
    (r,) = admin.get("/api/body/blood-pressure", params={"start": local(t)[0], "end": local(t)[0]}).json()["readings"]
    assert r["pulse"] is None  # a pulse out of range is dropped, the reading kept


def test_an_expired_access_token_is_refreshed_and_the_new_pair_kept(dev) -> None:
    admin, fake = dev
    connect_withings(admin, fake)
    first_refresh = fake.refresh
    with db(admin) as conn:
        conn.execute("UPDATE device_connections SET access_expires_at = '2000-01-01T00:00:00.000000Z'")
    fake.groups = [weight_group(51, at_local(1, 7, 0))]
    assert sync(admin)["result"]["added"]["weights"] == 1
    assert fake.refresh != first_refresh and first_refresh in fake.old_refresh
    with db(admin) as conn:
        row = conn.execute("SELECT * FROM device_connections").fetchone()
    assert store.load_tokens(admin.app.state.keyring, row) == (fake.access, fake.refresh)


def test_access_ended_early_gets_one_refresh(dev) -> None:
    admin, fake = dev
    connect_withings(admin, fake)
    fake.access = "ended-by-withings"
    fake.groups = [weight_group(52, at_local(1, 7, 0))]
    out = sync(admin)
    assert out["error"] is None and out["result"]["added"]["weights"] == 1


def test_a_refused_refresh_means_connect_again(dev) -> None:
    admin, fake = dev
    connect_withings(admin, fake)
    fake.access = "ended-by-withings"
    fake.refusing_refresh = True
    out = sync(admin)
    assert out["error"] == "auth" and out["result"] is None
    assert out["connection"]["status"] == "needs_reconnect" and out["connection"]["last_error"] == "auth"
    with db(admin) as conn:
        assert conn.execute("SELECT tokens_enc FROM device_connections").fetchone()[0] is None
    r = admin.post("/api/devices/withings/sync")
    assert r.status_code == 409 and "connect again" in r.json()["detail"]
    acts = [e for e in admin.get("/api/me/activity").json()["events"] if e["action"] == "device.sync_failed"]
    assert len(acts) == 1 and acts[0]["details"] == {"provider": "withings", "error": "auth"}
    fake.refusing_refresh = False
    assert connect_withings(admin, fake) == "/#/devices/connected/withings"
    assert admin.get("/api/devices").json()["providers"][0]["connection"]["status"] == "active"


def test_too_many_requests_pauses_the_connection(dev) -> None:
    admin, fake = dev
    connect_withings(admin, fake)
    fake.measure_status = 601
    out = sync(admin)
    assert out["error"] == "rate_limited" and out["connection"]["status"] == "active"
    with db(admin) as conn:
        conn.execute("UPDATE device_connections SET last_sync_at = NULL")
    r = admin.post("/api/devices/withings/sync")
    assert r.status_code == 429 and int(r.headers["Retry-After"]) > 3000


def test_sync_now_waits_ten_minutes(dev) -> None:
    admin, fake = dev
    connect_withings(admin, fake)
    assert admin.post("/api/devices/withings/sync").status_code == 200
    r = admin.post("/api/devices/withings/sync")
    assert r.status_code == 429 and 0 < int(r.headers["Retry-After"]) <= 600


def test_the_background_pass_syncs_due_people_only(dev) -> None:
    admin, fake = dev
    sam = add_user(admin)
    fake.groups = [weight_group(61, at_local(1, 7, 0))]
    connect_withings(admin, fake)
    other = FakeWithings(userid=777, groups=[weight_group(62, at_local(1, 7, 5))])
    attach(admin.app, other)
    connect_withings(sam, other)
    app = admin.app
    with db(admin) as conn:
        conn.execute("UPDATE users SET status = 'disabled' WHERE username = 'sam'")
    attach(app, fake)
    run = lambda: devices_sync.run_due(app.state.devices, app.state.keyring, app.state.settings_store, app.state.settings.db_path)  # noqa: E731
    assert run() == 1
    assert run() == 0  # not due again for devices.sync_hours
    assert admin.get("/api/devices").json()["providers"][0]["connection"]["imported"]["weights"] == 1


# --------------------------------------------------------------------------- #
# Disconnecting, isolation, deletion
# --------------------------------------------------------------------------- #


def test_disconnect_keeps_readings_and_asks_withings_to_end_access(dev) -> None:
    admin, fake = dev
    connect_withings(admin, fake)
    fake.groups = [weight_group(71, at_local(1, 7, 0))]
    sync(admin)
    r = admin.delete("/api/devices/withings")
    assert r.status_code == 200 and r.json() == {"removed": {"weights": 0, "readings": 0}, "revoked": True}
    assert fake.revoked == ["4242"]
    assert admin.get("/api/devices").json()["providers"][0]["connection"] is None
    day = local(fake.groups[0]["date"])[0]
    assert [w["source"] for w in admin.get("/api/body/weights", params={"start": day, "end": day}).json()["weights"]] == ["withings"]
    assert admin.delete("/api/devices/withings").status_code == 404
    acts = [e["action"] for e in admin.get("/api/me/activity").json()["events"]]
    assert "device.disconnected" in acts


def test_disconnect_can_delete_the_readings_but_keeps_edited_ones(dev) -> None:
    admin, fake = dev
    connect_withings(admin, fake)
    t = at_local(1, 7, 0)
    fake.groups = [weight_group(81, t), weight_group(82, t + 600), bp_group(83, t)]
    sync(admin)
    day = local(t)[0]
    w = admin.get("/api/body/weights", params={"start": day, "end": day}).json()["weights"][0]
    edited = admin.put(f"/api/body/weights/{w['id']}", json={"date": w["date"], "time": w["time"], "kg": 74, "context": "morning"})
    assert edited.json()["source"] == "manual"
    r = admin.delete("/api/devices/withings", params={"delete_readings": "true"})
    assert r.json()["removed"] == {"weights": 1, "readings": 1}
    assert [x["kg"] for x in admin.get("/api/body/weights", params={"start": day, "end": day}).json()["weights"]] == [74]
    with db(admin) as conn:
        assert conn.execute("SELECT COUNT(*) FROM device_imports").fetchone()[0] == 0


def test_another_persons_connection_is_404(dev) -> None:
    admin, fake = dev
    sam = add_user(admin)
    connect_withings(admin, fake)
    assert sam.get("/api/devices").json()["providers"][0]["connection"] is None
    assert sam.post("/api/devices/withings/sync").status_code == 404
    assert sam.delete("/api/devices/withings").status_code == 404
    assert admin.get("/api/devices").json()["providers"][0]["connection"]["status"] == "active"


def test_deleting_the_account_deletes_its_connection_and_ledger(dev) -> None:
    admin, fake = dev
    sam = add_user(admin)
    connect_withings(sam, fake)
    fake.groups = [weight_group(91, at_local(1, 7, 0))]
    sync(sam)
    sam_id = uid(sam)
    with db(admin) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("DELETE FROM users WHERE id = ?", (sam_id,))
        assert conn.execute("SELECT COUNT(*) FROM device_connections WHERE user_id = ?", (sam_id,)).fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM device_imports WHERE user_id = ?", (sam_id,)).fetchone()[0] == 0


# --------------------------------------------------------------------------- #
# Pure parts: units, time zones, groups, signatures
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("value,unit,expected", [(7512, -2, Decimal("75.12")), (75123, -3, Decimal("75.123")), (120, 0, Decimal(120)),
                                                 (12, 1, Decimal(120)), (True, 0, None), (1.5, 0, None), (1, 99, None)])
def test_decode_value(value: Any, unit: Any, expected: Decimal | None) -> None:
    assert withings.decode_value(value, unit) == expected


def test_times_use_the_group_zone_then_the_account_zone_then_utc() -> None:
    epoch = 1_767_250_800  # 2026-01-01 07:00 UTC
    assert withings.local_moment(epoch, "America/New_York") == ("2026-01-01", "02:00")
    assert withings.local_moment(epoch, None, "Asia/Tokyo") == ("2026-01-01", "16:00")
    assert withings.local_moment(epoch, "Not/AZone", None) == ("2026-01-01", "07:00")


def test_groups_without_both_numbers_are_left_out() -> None:
    half = {"grpid": 5, "date": 1_767_250_800, "category": 1, "attrib": 0, "measures": [{"type": 10, "value": 120, "unit": 0}]}
    readings, left_out = withings.readings_from_groups([half, "junk", {"grpid": True}], "UTC")
    assert readings == [] and left_out == 3


def test_the_signature_is_withings_hmac() -> None:
    import hashlib
    import hmac

    assert withings.sign("k", "getnonce", "id", "1") == hmac.new(b"k", b"getnonce,id,1", hashlib.sha256).hexdigest()


# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #


def test_the_client_secret_is_only_a_file(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="WITHINGS_CLIENT_SECRET_FILE"):
        load_settings({"DATA_DIR": str(tmp_path), "WITHINGS_CLIENT_SECRET": "x"})


def test_withings_needs_an_id_a_secret_file_and_a_public_url(tmp_path: Path) -> None:
    key_file = tmp_path / "withings_app_key"
    key_file.write_text(APP_KEY + "\n", encoding="utf-8")
    base = {"DATA_DIR": str(tmp_path), "WITHINGS_ENABLED": "true"}
    with pytest.raises(ConfigError, match="WITHINGS_CLIENT_ID"):
        load_settings(base).validate()
    with pytest.raises(ConfigError, match="WITHINGS_CLIENT_SECRET_FILE"):
        load_settings({**base, "WITHINGS_CLIENT_ID": "abc"}).validate()
    with pytest.raises(ConfigError, match="PUBLIC_URL"):
        load_settings({**base, "WITHINGS_CLIENT_ID": "abc", "WITHINGS_CLIENT_SECRET_FILE": str(key_file)}).validate()
    s = load_settings({**base, "WITHINGS_CLIENT_ID": "abc", "WITHINGS_CLIENT_SECRET_FILE": str(key_file),
                       "PUBLIC_URL": "https://food.example.org"})
    assert s.withings.configured and s.withings.client_secret == CLIENT_SECRET
    assert CLIENT_SECRET in s.secret_values()
    assert CLIENT_SECRET not in repr(s.withings)
