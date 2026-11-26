"""Connected devices from the iPhone app, paired with a server (owner, 2026-11-26: "Should Withings and Whoop be set up from the
phone?" "yes"; ``app/app_gateway.py``, design notes 27, 28 and 39).

Covered: through the gateway the person's own status, Sync now and Disconnect work as in the web app; connecting (start and the way
back) is never on the list, since it is tied to the browser session that started it; the readings a sync brings reach the phone
through the change feed with their source; Whoop's days and the active-day setting are read and set through the gateway; another
person's connection is never reached.
"""
from __future__ import annotations

from pathlib import Path
import pytest

from app.app_gateway import NOT_ON_LIST, never_allowed
from conftest import HTTPS_URL, add_user, make_settings, signed_in_client
from devices_support import FakeWhoop, FakeWithings, attach, attach_whoop, bp_group, env, weight_group, whoop_env
from test_app_gateway import call, make_sync, switches
from test_connected_devices import at_local, connect_withings, db, local, rewind
from test_sync_feed import everything
from test_whoop import a_week, connect_whoop, local_date

GATEWAY = "/push/v1/api"


@pytest.fixture
def dev(tmp_path: Path, foods_json: Path):
    s = make_settings(tmp_path, foods_json, public_url=HTTPS_URL, withings=env(), whoop=whoop_env())
    with signed_in_client(s, base_url=HTTPS_URL) as admin:
        assert admin.patch("/api/admin/settings", json={"devices.enabled": True}).status_code == 200
        switches(admin)
        fake = attach(admin.app, FakeWithings())
        whoop = attach_whoop(admin.app, FakeWhoop())
        token = make_sync(admin)["token"]
        yield admin, fake, whoop, token


def test_connecting_is_never_on_the_list(dev) -> None:
    admin, _fake, _whoop, token = dev
    assert never_allowed("POST", "/api/devices/{provider_id}/start")
    assert never_allowed("GET", "/api/devices/{provider_id}/callback")
    for method, path in (("POST", "/devices/withings/start"), ("GET", "/devices/withings/callback?code=x&state=y"),
                         ("POST", "/devices/whoop/start"), ("GET", "/devices/whoop/callback")):
        r = call(admin.app, token, method, f"{GATEWAY}{path}")
        assert r.status_code == 404 and r.json()["detail"] == NOT_ON_LIST, (method, path)


def test_status_sync_now_and_the_readings_reach_the_phone_through_the_feed(dev) -> None:
    admin, fake, _whoop, token = dev
    r = call(admin.app, token, "GET", f"{GATEWAY}/devices")
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    listed = {p["id"]: p for p in r.json()["providers"]}
    assert r.json()["enabled"] is True and listed["withings"]["available"] and listed["withings"]["connection"] is None
    connect_withings(admin, fake)  # in the web app (the phone opens the server's own page for it)
    w_at, bp_at = at_local(2, 7, 15), at_local(2, 7, 20)
    fake.groups = [weight_group(21, w_at, value=75123, unit=-3), bp_group(22, bp_at, systolic=131, diastolic=82, pulse=66)]
    rewind(admin)
    r = call(admin.app, token, "POST", f"{GATEWAY}/devices/withings/sync")
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["error"] is None and out["result"]["added"]["weights"] == 1 and out["result"]["added"]["readings"] == 1
    assert out["connection"]["status"] == "active"
    # the second Sync now within ten minutes is the web app's 429
    assert call(admin.app, token, "POST", f"{GATEWAY}/devices/withings/sync").status_code == 429
    # the rows are in the change feed with their source, so the phone shows them "from Withings"
    changes, _cursor, _foods = everything(admin.app, token)
    weights = [c["row"] for c in changes if c["kind"] == "weight" and c["op"] == "put"]
    readings = [c["row"] for c in changes if c["kind"] == "reading" and c["op"] == "put"]
    assert [(w["date"], w["time"], w["kg"], w["source"], w["source_key"]) for w in weights] == [
        (*local(w_at), 75.12, "withings", "withings:21:weight")]
    assert [(b["systolic"], b["diastolic"], b["pulse"], b["source"], b["source_key"]) for b in readings] == [
        (131, 82, 66, "withings", "withings:22:bp")]
    # Disconnect through the gateway, deleting what came from Withings: the feed says so too
    r = call(admin.app, token, "DELETE", f"{GATEWAY}/devices/withings?delete_readings=true")
    assert r.status_code == 200, r.text
    assert r.json()["removed"]["weights"] == 1 and r.json()["removed"]["readings"] == 1
    changes, _cursor, _foods = everything(admin.app, token)
    assert {(c["kind"], c["op"]) for c in changes if c["kind"] in ("weight", "reading")} == {("weight", "delete"), ("reading", "delete")}
    assert call(admin.app, token, "DELETE", f"{GATEWAY}/devices/withings").status_code == 404
    assert admin.get("/api/devices").json()["providers"][0]["connection"] is None


def test_whoop_days_and_the_active_day_setting_through_the_gateway(dev) -> None:
    admin, _fake, whoop, token = dev
    connect_whoop(admin, whoop)
    a_week(whoop)
    with db(admin) as conn:
        conn.execute("UPDATE device_connections SET last_sync_at = NULL, next_sync_after = NULL")
    r = call(admin.app, token, "POST", f"{GATEWAY}/devices/whoop/sync")
    assert r.status_code == 200 and r.json()["result"]["added"]["days"] == 7, r.text
    r = call(admin.app, token, "GET", f"{GATEWAY}/activity", params={"start": local_date(30), "end": local_date(-1)})
    assert r.status_code == 200
    assert r.json() == admin.get("/api/activity", params={"start": local_date(30), "end": local_date(-1)}).json()
    assert len(r.json()["days"]) == 7 and {d["source"] for d in r.json()["days"]} == {"whoop"}
    r = call(admin.app, token, "PUT", f"{GATEWAY}/activity/extra", json={"enabled": True, "share_pct": 50, "ceiling_kcal": 400})
    assert r.status_code == 200 and r.json() == {"enabled": True, "share_pct": 50, "ceiling_kcal": 400}
    assert admin.get("/api/activity").json()["extra"]["enabled"] is True


def test_another_persons_connection_is_never_reached(dev) -> None:
    admin, fake, _whoop, _token = dev
    connect_withings(admin, fake)
    sam = add_user(admin)
    theirs = make_sync(sam, name="Sam's iPhone")["token"]
    r = call(admin.app, theirs, "GET", f"{GATEWAY}/devices")
    assert r.status_code == 200
    assert all(p["connection"] is None for p in r.json()["providers"])
    assert call(admin.app, theirs, "POST", f"{GATEWAY}/devices/withings/sync").status_code == 404
    assert call(admin.app, theirs, "DELETE", f"{GATEWAY}/devices/withings").status_code == 404
    assert admin.get("/api/devices").json()["providers"][0]["connection"]["status"] == "active"
