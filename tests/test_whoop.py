"""Whoop (design note 28; app/devices/whoop.py). A fake Whoop (tests/devices_support.py) answers behind the app's real
SSRF-checked transport; nothing touches the network.

Covered: the switches (the list answers ``enabled: false`` while off, every other route 404) and an unset Whoop app; the way out
(the exact scopes, never the profile) and back; tokens sealed at rest and never in a response or a log line; Whoop's id for the
person from the first cycle; the sync (kJ → kcal, the date a cycle belongs to, recovery, HRV and sleep joined, naps and unscored
records left out, workouts, pagination); a cycle that grows through the day replaces its day; the ledger (nothing doubled, a
deleted day stays deleted); refresh with rotation; a refused refresh → connect again; "too many requests"; a collection the person
did not allow; disconnect (keep or delete, the revoke with the person's token); a test account; one Whoop account per person here;
isolation; config rules; Server administration never shows the secret.
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest

from app.config import ConfigError, load_settings
from app.db import connect
from app.devices import store, whoop
from conftest import HTTPS_URL, TestClient, add_user, make_settings, signed_in_client
from devices_support import (WHOOP_SECRET, FakeWhoop, attach_whoop, whoop_cycle, whoop_env, whoop_recovery, whoop_sleep,
                             whoop_workout)

EST = timezone(timedelta(hours=-5))


def night(days_ago: int, hour: int = 23, zone: timezone = EST) -> datetime:
    """``hour``:00 on the clock of ``zone``, ``days_ago`` days before today there."""
    day = datetime.now(zone).date() - timedelta(days=days_ago)
    return datetime(day.year, day.month, day.day, hour, 0, tzinfo=zone)


def local_date(days_ago: int, zone: timezone = EST) -> str:
    return (datetime.now(zone).date() - timedelta(days=days_ago)).isoformat()


@pytest.fixture
def dev(tmp_path: Path, foods_json: Path):
    s = make_settings(tmp_path, foods_json, public_url=HTTPS_URL, whoop=whoop_env())
    with signed_in_client(s, base_url=HTTPS_URL) as admin:
        assert admin.patch("/api/admin/settings", json={"devices.enabled": True}).status_code == 200
        fake = attach_whoop(admin.app, FakeWhoop())
        yield admin, fake


def db(client: TestClient) -> sqlite3.Connection:
    return connect(client.app.state.settings.db_path)


def uid(client: TestClient) -> int:
    return int(client.get("/api/me").json()["id"])


def start(client: TestClient) -> dict[str, str]:
    r = client.post("/api/devices/whoop/start")
    assert r.status_code == 200, r.text
    url = r.json()["url"]
    assert url.startswith("https://api.prod.whoop.com/oauth/oauth2/auth?")
    return {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}


def back(client: TestClient, **params: str) -> str:
    r = client.get("/api/devices/whoop/callback", params=params, follow_redirects=False)
    assert r.status_code == 303, r.text
    return r.headers["location"]


def connect_whoop(client: TestClient, fake: FakeWhoop) -> str:
    q = start(client)
    return back(client, code=fake.issue_code(q["redirect_uri"]), state=q["state"])


def sync(client: TestClient) -> dict[str, Any]:
    with db(client) as conn:
        conn.execute("UPDATE device_connections SET last_sync_at = NULL, next_sync_after = NULL")
    r = client.post("/api/devices/whoop/sync")
    assert r.status_code == 200, r.text
    return r.json()


def days_of(client: TestClient) -> dict[str, dict[str, Any]]:
    r = client.get("/api/activity", params={"start": local_date(60), "end": local_date(-1)})
    assert r.status_code == 200, r.text
    return {d["date"]: d for d in r.json()["days"]}


def a_week(fake: FakeWhoop, first_id: int = 100) -> None:
    """Six finished days (two to seven days ago) and the day the person is in now."""
    for n in range(7, 1, -1):
        cid = first_id + n
        s = night(n)
        fake.cycles.append(whoop_cycle(cid, s, s + timedelta(hours=24), kilojoule=8368 + n * 100))
        fake.recoveries.append(whoop_recovery(cid, s))
        fake.sleeps.append(whoop_sleep(f"00000000-0000-4000-8000-{cid:012d}", cid, s))
    fake.cycles.append(whoop_cycle(first_id, night(1), None, kilojoule=4184))


# --------------------------------------------------------------------------- #
# Switches, connect
# --------------------------------------------------------------------------- #


def test_off_the_list_answers_and_every_whoop_route_is_404(client: TestClient) -> None:
    assert client.get("/api/devices").json()["enabled"] is False
    assert client.post("/api/devices/whoop/start").status_code == 404
    assert client.get("/api/devices/whoop/callback", params={"code": "x", "state": "y"}).status_code == 404
    assert client.post("/api/devices/whoop/sync").status_code == 404
    assert client.delete("/api/devices/whoop").status_code == 404
    r = client.get("/api/activity")  # Trends asks on every open: always an answer
    assert r.status_code == 200 and r.json()["days"] == [] and r.json()["extra"]["enabled"] is False


def test_on_without_a_whoop_app_is_listed_as_not_set_up(client: TestClient) -> None:
    assert client.patch("/api/admin/settings", json={"devices.enabled": True}).status_code == 200
    w = {p["id"]: p for p in client.get("/api/devices").json()["providers"]}["whoop"]
    assert w["available"] is False and w["connection"] is None
    assert w["what"] == ["calories burned", "strain", "recovery", "resting heart rate", "heart rate variability (HRV)", "sleep",
                         "workouts"]
    assert client.post("/api/devices/whoop/start").status_code == 404


def test_connect_asks_only_for_what_it_shows_and_keeps_tokens_sealed(dev, caplog) -> None:
    admin, fake = dev
    fake.cycles.append(whoop_cycle(1, night(3), night(2)))
    caplog.set_level(logging.DEBUG)
    q = start(admin)
    assert q["scope"] == "offline read:cycles read:recovery read:sleep read:workout"
    assert "read:profile" not in q["scope"] and "read:body_measurement" not in q["scope"]
    assert q["redirect_uri"] == "https://localhost/api/devices/whoop/callback" and q["response_type"] == "code"
    assert len(q["state"]) >= 40
    assert back(admin, code=fake.issue_code(q["redirect_uri"]), state=q["state"]) == "/#/devices/connected/whoop"
    token_call = next(c for c in fake.calls if c["path"] == "/oauth/oauth2/token")
    assert token_call["host"] == "api.prod.whoop.com"
    assert set(token_call["form"]) == {"grant_type", "code", "redirect_uri", "client_id", "client_secret"}
    with db(admin) as conn:
        row = conn.execute("SELECT * FROM device_connections WHERE provider = 'whoop'").fetchone()
    assert row["external_user_id"] == "10129"  # from the first cycle; the token answer has none
    assert fake.access.encode() not in row["tokens_enc"] and fake.refresh.encode() not in row["tokens_enc"]
    listed = admin.get("/api/devices").text
    for secret in (fake.access, fake.refresh, WHOOP_SECRET, "10129"):
        assert secret not in listed and secret not in caplog.text
    about = admin.get("/api/admin/about").json()["devices"]
    w = next(p for p in about["providers"] if p["id"] == "whoop")
    assert w["secret"] == "set" and WHOOP_SECRET not in str(about) and w["hosts"] == ["api.prod.whoop.com"]


def test_a_test_account_cannot_connect(dev) -> None:
    admin, fake = dev
    sam = add_user(admin, "sam", base_url=HTTPS_URL)
    q = start(sam)
    with db(admin) as conn:
        conn.execute("UPDATE users SET is_test_account = 1 WHERE username = 'sam'")
    assert sam.post("/api/devices/whoop/start").status_code == 403
    assert back(sam, code=fake.issue_code(q["redirect_uri"]), state=q["state"]) == "/#/devices/test_account/whoop"


def test_one_whoop_account_belongs_to_one_person_here(dev) -> None:
    admin, fake = dev
    fake.cycles.append(whoop_cycle(1, night(3), night(2)))
    assert connect_whoop(admin, fake) == "/#/devices/connected/whoop"
    other = add_user(admin, "sam", base_url=HTTPS_URL)
    assert connect_whoop(other, fake) == "/#/devices/taken/whoop"


def test_a_missing_cycles_scope_is_refused(dev) -> None:
    admin, fake = dev
    fake.scope = "offline read:sleep"
    assert connect_whoop(admin, fake) == "/#/devices/scope/whoop"


# --------------------------------------------------------------------------- #
# The sync
# --------------------------------------------------------------------------- #


def test_sync_converts_dates_joins_recovery_and_sleep_and_takes_workouts(dev) -> None:
    admin, fake = dev
    a_week(fake)
    fake.sleeps.append(whoop_sleep("aaaaaaaa-0000-4000-8000-000000000001", 103, night(3), light_min=60, sws_min=0, rem_min=0, nap=True))
    fake.cycles.append(whoop_cycle(99, night(9), night(8), state="PENDING_SCORE"))
    fake.workouts.append(whoop_workout("AB12CD34-0000-4000-8000-00000000000F", night(3, hour=18), 45, kilojoule=1673.6))
    fake.workouts.append(whoop_workout("ab12cd34-0000-4000-8000-000000000010", night(4, hour=7), 30, state="PENDING_SCORE"))
    fake.page_size = 3  # pagination
    connect_whoop(admin, fake)
    out = sync(admin)
    assert out["error"] is None and out["result"]["added"]["days"] == 7 and out["result"]["added"]["workouts"] == 1
    assert out["result"]["left_out"] >= 3  # the unscored cycle, the nap, the unscored workout
    days = days_of(admin)
    # A cycle starting at 23:00 three days ago is the next day's: two days ago.
    d = days[local_date(2)]
    assert d["kcal"] == round((8368 + 300) / 4.184) and d["strain"] == 9.5 and d["finished"] is True and d["source"] == "whoop"
    assert d["recovery_pct"] == 66 and d["resting_hr"] == 56 and d["hrv_ms"] == 45.7
    assert d["sleep_minutes"] == 430 and d["sleep_performance_pct"] == 88
    today = days[local_date(0)]
    assert today["kcal"] == 1000 and today["finished"] is False
    assert local_date(8) not in days
    (w,) = admin.get("/api/activity", params={"start": local_date(60), "end": local_date(-1)}).json()["workouts"]
    assert w == {"date": local_date(3), "start_time": "18:00", "end_time": "18:45", "minutes": 45, "sport": "functional fitness",
                 "kcal": 400, "strain": 11.2, "source": "whoop"}
    calls = [c for c in fake.calls if c["path"].startswith("/developer/v2/")]
    assert {c["host"] for c in calls} == {"api.prod.whoop.com"} and all(c["query"].get("limit") == "25" for c in calls if "start" in c["query"])


def test_the_day_still_going_on_is_replaced_and_nothing_is_doubled(dev) -> None:
    admin, fake = dev
    a_week(fake)
    connect_whoop(admin, fake)
    sync(admin)
    fake.cycles[-1] = whoop_cycle(100, night(1), None, kilojoule=10460)  # later the same day: more burned
    out = sync(admin)["result"]
    assert out["added"]["days"] == 0 and out["updated"] >= 1
    assert days_of(admin)[local_date(0)]["kcal"] == 2500
    with db(admin) as conn:
        n = conn.execute("SELECT COUNT(*) FROM activity_days").fetchone()[0]
        ledger = conn.execute("SELECT COUNT(*) FROM device_imports WHERE provider = 'whoop' AND kind = 'activity_day'").fetchone()[0]
    assert n == 7 and ledger == 7
    # The cursor moves on: a later sync asks only for the last few days.
    starts = [c["query"]["start"] for c in fake.calls if c["path"] == "/developer/v2/cycle" and "start" in c["query"]]
    assert starts[-1] > starts[0]


def test_a_deleted_day_stays_deleted(dev) -> None:
    admin, fake = dev
    a_week(fake)
    connect_whoop(admin, fake)
    sync(admin)
    with db(admin) as conn:
        conn.execute("DELETE FROM activity_days WHERE date = ?", (local_date(2),))
    sync(admin)
    assert local_date(2) not in days_of(admin)


def test_refresh_rotates_and_a_refused_refresh_asks_to_connect_again(dev) -> None:
    admin, fake = dev
    a_week(fake)
    connect_whoop(admin, fake)
    first_refresh = fake.refresh
    with db(admin) as conn:
        conn.execute("UPDATE device_connections SET access_expires_at = '2000-01-01T00:00:00.000000Z'")
    assert sync(admin)["error"] is None
    assert fake.refresh != first_refresh and first_refresh in fake.old_refresh
    refresh_call = [c for c in fake.calls if c["form"].get("grant_type") == "refresh_token"][-1]
    assert refresh_call["form"]["scope"] == "offline"
    with db(admin) as conn:
        row = conn.execute("SELECT * FROM device_connections").fetchone()
    assert store.load_tokens(admin.app.state.keyring, row)[1] == fake.refresh  # the new pair was kept at once
    fake.access = "revoked-by-the-person"
    fake.refusing_refresh = True
    out = sync(admin)
    assert out["error"] == "auth" and out["connection"]["status"] == "needs_reconnect"
    with db(admin) as conn:
        assert conn.execute("SELECT tokens_enc FROM device_connections").fetchone()[0] is None
    assert admin.post("/api/devices/whoop/sync").status_code == 409
    events = admin.get("/api/me/activity").json()["events"]
    assert any(e["action"] == "device.sync_failed" and e["details"]["provider"] == "whoop" for e in events)


def test_too_many_requests_pauses_and_a_not_allowed_collection_is_skipped(dev) -> None:
    admin, fake = dev
    a_week(fake)
    fake.forbidden = {"/developer/v2/activity/workout"}
    fake.workouts.append(whoop_workout("ab12cd34-0000-4000-8000-000000000011", night(3, hour=18), 45))
    connect_whoop(admin, fake)
    out = sync(admin)
    assert out["error"] is None and out["result"]["added"]["workouts"] == 0 and out["result"]["added"]["days"] == 7
    fake.data_status = 429
    out = sync(admin)
    assert out["error"] == "rate_limited"
    with db(admin) as conn:
        assert conn.execute("SELECT next_sync_after FROM device_connections").fetchone()[0] is not None


def test_whoop_id_is_filled_in_by_the_first_sync(dev) -> None:
    admin, fake = dev
    connect_whoop(admin, fake)  # a brand-new member: no cycle yet
    with db(admin) as conn:
        assert conn.execute("SELECT external_user_id FROM device_connections").fetchone()[0] is None
    a_week(fake)
    sync(admin)
    with db(admin) as conn:
        assert conn.execute("SELECT external_user_id FROM device_connections").fetchone()[0] == "10129"


def test_disconnect_revokes_with_the_persons_token_and_can_delete(dev) -> None:
    admin, fake = dev
    a_week(fake)
    fake.workouts.append(whoop_workout("ab12cd34-0000-4000-8000-000000000012", night(3, hour=18), 45))
    connect_whoop(admin, fake)
    sync(admin)
    access = fake.access
    r = admin.delete("/api/devices/whoop", params={"delete_readings": "true"})
    assert r.status_code == 200 and r.json() == {"removed": {"weights": 0, "readings": 0, "days": 7, "workouts": 1}, "revoked": True}
    assert fake.revoked == [access]
    revoke = next(c for c in fake.calls if c["method"] == "DELETE")
    assert revoke["path"] == "/developer/v2/user/access" and revoke["auth"] == f"Bearer {access}"
    assert days_of(admin) == {}
    with db(admin) as conn:
        assert conn.execute("SELECT COUNT(*) FROM device_imports WHERE provider = 'whoop'").fetchone()[0] == 0
    events = admin.get("/api/me/activity").json()["events"]
    gone = next(e for e in events if e["action"] == "device.disconnected")
    assert gone["details"]["deleted_days"] == 7 and gone["details"]["deleted_workouts"] == 1


def test_people_never_see_each_others_whoop(dev) -> None:
    admin, fake = dev
    a_week(fake)
    connect_whoop(admin, fake)
    sync(admin)
    sam = add_user(admin, "sam", base_url=HTTPS_URL)
    assert sam.get("/api/activity", params={"start": local_date(60), "end": local_date(0)}).json()["days"] == []
    assert {p["id"]: p for p in sam.get("/api/devices").json()["providers"]}["whoop"]["connection"] is None
    assert sam.post("/api/devices/whoop/sync").status_code == 404
    assert sam.delete("/api/devices/whoop").status_code == 404
    assert len(days_of(admin)) == 7


# --------------------------------------------------------------------------- #
# Reading Whoop's numbers
# --------------------------------------------------------------------------- #


def test_units_dates_and_ranges() -> None:
    assert whoop.kcal_from_kj(8368) == 2000 and whoop.kcal_from_kj(8288.297) == 1981
    assert whoop.kcal_from_kj(0) is None and whoop.kcal_from_kj(100000) is None and whoop.kcal_from_kj(True) is None
    assert whoop.kcal_from_kj("8368") is None
    assert whoop.parse_offset("-05:00").utcoffset(None) == timedelta(hours=-5)
    assert whoop.parse_offset("Z").utcoffset(None) == timedelta(0) and whoop.parse_offset("bogus").utcoffset(None) == timedelta(0)
    start = datetime(2026, 10, 27, 4, 0, tzinfo=timezone.utc)  # 23:00 on the 26th in New York
    assert whoop.day_of_cycle(start, whoop.parse_offset("-05:00")) == "2026-10-27"
    start = datetime(2026, 10, 27, 6, 0, tzinfo=timezone.utc)  # 01:00 on the 27th
    assert whoop.day_of_cycle(start, whoop.parse_offset("-05:00")) == "2026-10-27"
    assert whoop.sport_label("functional-fitness") == "functional fitness" and whoop.sport_label("<b>run</b>") == "b run /b"
    days, left, user = whoop.build_days(
        [whoop_cycle(1, datetime(2026, 10, 27, 4, tzinfo=timezone.utc), None, strain=25.0, kilojoule=8368)],
        [whoop_recovery(1, datetime(2026, 10, 27, 4, tzinfo=timezone.utc), score=140, hrv=0.2)], [])
    (d,) = days
    assert d.strain is None and d.kcal == 2000 and d.recovery_pct is None and d.hrv_ms is None and user == "10129"


def test_two_cycles_on_one_date_keep_the_later_one() -> None:
    a = datetime(2026, 10, 27, 1, tzinfo=timezone.utc)  # 20:00 on the 26th
    b = datetime(2026, 10, 27, 9, tzinfo=timezone.utc)  # 04:00 on the 27th
    days, left, _ = whoop.build_days([whoop_cycle(1, a, b, kilojoule=4184), whoop_cycle(2, b, None, kilojoule=8368)], [], [])
    assert [(d.date, d.external_id, d.kcal) for d in days] == [("2026-10-27", "cycle:2", 2000)] and left == 1


# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #


def test_config_rules(tmp_path: Path) -> None:
    base = {"DATA_DIR": str(tmp_path), "PUBLIC_URL": "https://kidney.example"}
    with pytest.raises(ConfigError, match="WHOOP_CLIENT_SECRET_FILE"):
        load_settings({**base, "WHOOP_CLIENT_SECRET": "plain"})
    with pytest.raises(ConfigError, match="WHOOP_CLIENT_ID"):
        load_settings({**base, "WHOOP_ENABLED": "true"}).validate()
    secret = tmp_path / "whoop_secret"
    secret.write_text("s3cret\n")
    s = load_settings({**base, "WHOOP_ENABLED": "true", "WHOOP_CLIENT_ID": "abc-123", "WHOOP_CLIENT_SECRET_FILE": str(secret)})
    assert s.whoop.configured and s.whoop.client_secret == "s3cret" and "s3cret" in s.secret_values()
    assert "s3cret" not in repr(s.whoop)
    with pytest.raises(ConfigError, match="PUBLIC_URL"):
        load_settings({"DATA_DIR": str(tmp_path), "WHOOP_ENABLED": "true", "WHOOP_CLIENT_ID": "abc",
                       "WHOOP_CLIENT_SECRET_FILE": str(secret)}).validate()
    warnings = load_settings({"DATA_DIR": str(tmp_path), "WHOOP_CLIENT_ID": "abc"}).validate()
    assert any("Whoop stays off" in w for w in warnings)


def test_the_first_sync_reaches_back_ninety_days() -> None:
    assert whoop.FIRST_DAYS == 90 and whoop.WhoopProvider.first_days == 90
    assert date.fromisoformat(local_date(90)) < date.fromisoformat(local_date(0))
