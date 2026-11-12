"""Reminders by phone notification (design note 35; app/reminders.py). A fake push service answers behind the app's real
SSRF-checked transport (a fake resolver gives its host a public address); nothing touches the network.

Covered: off by default (200 ``enabled: false``, every other route 404); sign-in; adding, changing and removing reminders and
devices; the limits; only known push hosts; another person's id is 404; a test send and its hourly limit; 404/410 removes the
device; the loop sends once a day at the local time, in the reminder's time zone, and skips a meal already logged; test
accounts; the audit rows; the export; the start-up checks; the private key never in an answer or a log line.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx2
import pytest
from cryptography.hazmat.primitives.asymmetric import ec

from app import reminders, webpush
from app.config import ConfigError, RemindersEnv, load_settings
from app.db import connect
from conftest import HTTPS_URL, TestClient, add_user, find_food, make_settings, signed_in_client

PUBLIC_IP = "17.188.143.33"
APPLE = "https://web.push.apple.com/QGuQyavXutnMH7GXOkR8VHM7E8Wy1aQiZ3Wj3zZbd0Q"
FCM = "https://fcm.googleapis.com/fcm/send/dPf1:APA91bHzX"
ON = RemindersEnv(enabled=True, subject="mailto:admin@example.org")
ZONE = "America/Chicago"


class FakePush:
    """Every push service at once: records each request and decrypts it with the browser's key."""

    def __init__(self) -> None:
        self.status = 201
        self.calls: list[httpx2.Request] = []

    def handler(self, request: httpx2.Request) -> httpx2.Response:
        self.calls.append(request)
        return httpx2.Response(self.status)


class Browser:
    def __init__(self, endpoint: str = APPLE) -> None:
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.auth = b"0123456789abcdef"
        self.endpoint = endpoint

    def subscription(self) -> dict[str, Any]:
        return {"endpoint": self.endpoint, "expirationTime": None,
                "keys": {"p256dh": webpush.b64url(webpush.public_bytes(self.key.public_key())), "auth": webpush.b64url(self.auth)}}

    def read(self, request: httpx2.Request) -> dict[str, Any]:
        return json.loads(webpush.decrypt(request.content, self.key, self.auth))


def attach(app: Any, fake: FakePush, address: str = PUBLIC_IP) -> FakePush:
    push = app.state.webpush
    push.resolver = lambda host, port: [address]
    push.direct = httpx2.MockTransport(fake.handler)
    push.use_env_proxy = False
    return fake


def db(client: TestClient) -> sqlite3.Connection:
    return connect(client.app.state.settings.db_path)


@pytest.fixture
def on_settings(tmp_path: Path, foods_json: Path):
    return make_settings(tmp_path, foods_json, public_url=HTTPS_URL, reminders=ON)


@pytest.fixture
def on(on_settings):
    with signed_in_client(on_settings, base_url=HTTPS_URL) as admin:
        yield admin


@pytest.fixture
def fake(on: TestClient) -> FakePush:
    return attach(on.app, FakePush())


def lunch(client: TestClient, **extra: Any) -> dict[str, Any]:
    body = {"kind": "log_meal", "meal": "lunch", "time": "12:00", "days": 127, "time_zone": ZONE, **extra}
    r = client.post("/api/reminders", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def subscribe(client: TestClient, browser: Browser) -> dict[str, Any]:
    r = client.post("/api/reminders/subscriptions", json=browser.subscription(), headers={"User-Agent": "Mozilla/5.0 (iPhone) Safari/605"})
    assert r.status_code in (200, 201), r.text
    return r.json()


def tick(client: TestClient, when: str) -> int:
    """Run the loop once at ``when`` (an ISO time with offset)."""
    conn = db(client)
    try:
        return reminders.run_due(conn, client.app.state.webpush, client.app.state.settings_store, HTTPS_URL,
                                 now=datetime.fromisoformat(when).astimezone(timezone.utc))
    finally:
        conn.close()


# --------------------------------------------------------------------------- off, sign-in


def _routes_404(client: TestClient) -> None:
    assert client.post("/api/reminders", json={"kind": "weigh_in", "time": "07:00"}).status_code == 404
    assert client.patch("/api/reminders/1", json={"enabled": False}).status_code == 404
    assert client.delete("/api/reminders/1").status_code == 404
    assert client.post("/api/reminders/subscriptions", json=Browser().subscription()).status_code == 404
    assert client.delete("/api/reminders/subscriptions/1").status_code == 404
    assert client.post("/api/reminders/test").status_code == 404


def test_off_by_default(client: TestClient) -> None:
    r = client.get("/api/reminders")
    assert r.status_code == 200
    body = r.json()
    assert body["enabled"] is False and body["public_key"] is None and body["reminders"] == [] and body["devices"] == []
    assert body["safety"] == "Reminders are a convenience. Do not rely on them for low blood sugar; use your CGM's alerts."
    _routes_404(client)
    assert not (client.app.state.settings.data_dir / "vapid_private.pem").exists()


def test_anonymous_is_401(anon_client: TestClient) -> None:
    assert anon_client.get("/api/reminders").status_code == 401
    assert anon_client.post("/api/reminders/test").status_code == 401


def test_on_makes_a_key_and_shows_only_the_public_half(on: TestClient) -> None:
    path = on.app.state.settings.data_dir / "vapid_private.pem"
    assert path.exists() and oct(path.stat().st_mode & 0o777) == "0o600"
    body = on.get("/api/reminders").json()
    assert body["enabled"] is True and body["can_use"] is True
    assert len(webpush.b64url_decode(body["public_key"])) == 65
    assert [k["kind"] for k in body["kinds"]] == ["log_meal", "plan_tomorrow", "weigh_in"]
    pem = path.read_text()
    secret_line = pem.splitlines()[1]
    assert secret_line not in json.dumps(body)


# --------------------------------------------------------------------------- reminders


def test_add_change_and_remove_a_reminder(on: TestClient) -> None:
    r = lunch(on)
    assert {k: r[k] for k in ("kind", "meal", "time", "days", "time_zone", "enabled", "last_sent_on")} == {
        "kind": "log_meal", "meal": "lunch", "time": "12:00", "days": 127, "time_zone": ZONE, "enabled": True, "last_sent_on": None}
    p = on.patch(f"/api/reminders/{r['id']}", json={"time": "12:30", "days": 31, "enabled": False})
    assert p.status_code == 200 and (p.json()["time"], p.json()["days"], p.json()["enabled"]) == ("12:30", 31, False)
    p = on.patch(f"/api/reminders/{r['id']}", json={"kind": "weigh_in", "meal": None})
    assert p.status_code == 200 and p.json()["kind"] == "weigh_in" and p.json()["meal"] is None
    assert [x["id"] for x in on.get("/api/reminders").json()["reminders"]] == [r["id"]]
    assert on.delete(f"/api/reminders/{r['id']}").status_code == 204
    assert on.get("/api/reminders").json()["reminders"] == []
    assert on.delete(f"/api/reminders/{r['id']}").status_code == 404


@pytest.mark.parametrize(("body", "status", "words"), [
    ({"kind": "log_meal", "time": "12:00"}, 400, "Choose which meal."),
    ({"kind": "weigh_in", "meal": "lunch", "time": "12:00"}, 400, "Only a meal reminder has a meal."),
    ({"kind": "weigh_in", "time": "24:00"}, 400, "Enter a time such as 12:30."),
    ({"kind": "weigh_in", "time": "7:00"}, 400, "Enter a time such as 12:30."),
    ({"kind": "weigh_in", "time": "07:00", "days": 0}, 400, "Choose at least one day."),
    ({"kind": "weigh_in", "time": "07:00", "time_zone": "Mars/Olympus"}, 400, "That time zone is not known."),
    ({"kind": "glucose_low", "time": "07:00"}, 400, None),  # never a reminder about lows, insulin or medicines
    ({"kind": "insulin", "time": "07:00"}, 400, None),
])
def test_bad_reminders_are_refused(on: TestClient, body: dict, status: int, words: str | None) -> None:
    r = on.post("/api/reminders", json=body)
    assert r.status_code == status, r.text
    if words:
        assert r.json()["detail"].startswith(words)


def test_at_most_ten_reminders(on: TestClient) -> None:
    for n in range(reminders.MAX_REMINDERS):
        lunch(on, time=f"{n:02d}:00")
    r = on.post("/api/reminders", json={"kind": "weigh_in", "time": "23:00"})
    assert r.status_code == 409 and r.json()["detail"] == reminders.TOO_MANY_REMINDERS


# --------------------------------------------------------------------------- devices


def test_add_a_device_twice_and_remove_it(on: TestClient) -> None:
    b = Browser()
    first = on.post("/api/reminders/subscriptions", json=b.subscription(), headers={"User-Agent": "Mozilla/5.0 (iPhone) Safari/605"})
    assert first.status_code == 201
    again = on.post("/api/reminders/subscriptions", json=b.subscription())
    assert again.status_code == 200 and again.json()["id"] == first.json()["id"]
    devices = on.get("/api/reminders").json()["devices"]
    assert len(devices) == 1 and set(devices[0]) == {"id", "endpoint_hash", "user_agent", "created_at", "last_ok_at", "last_error"}
    assert devices[0]["endpoint_hash"] == reminders.endpoint_hash(b.endpoint)
    assert b.endpoint not in json.dumps(on.get("/api/reminders").json())  # never the endpoint or keys
    assert on.delete(f"/api/reminders/subscriptions/{first.json()['id']}").status_code == 204
    assert on.get("/api/reminders").json()["devices"] == []


@pytest.mark.parametrize("endpoint", ["https://example.org/push", "http://web.push.apple.com/x", "https://127.0.0.1/x",
                                      "https://169.254.169.254/latest", "https://web.push.apple.com.evil.example/x"])
def test_only_known_push_services(on: TestClient, endpoint: str) -> None:
    r = on.post("/api/reminders/subscriptions", json=Browser(endpoint).subscription())
    assert r.status_code == 400 and r.json()["detail"] == reminders.BAD_ENDPOINT


def test_bad_keys_are_refused(on: TestClient) -> None:
    sub = Browser().subscription()
    sub["keys"]["auth"] = webpush.b64url(b"short")
    r = on.post("/api/reminders/subscriptions", json=sub)
    assert r.status_code == 400 and r.json()["detail"] == reminders.BAD_KEYS


def test_at_most_five_devices(on: TestClient) -> None:
    for n in range(reminders.MAX_DEVICES):
        subscribe(on, Browser(f"{FCM}{n}"))
    r = on.post("/api/reminders/subscriptions", json=Browser(f"{FCM}x").subscription())
    assert r.status_code == 409 and r.json()["detail"] == reminders.TOO_MANY_DEVICES


# --------------------------------------------------------------------------- isolation


def test_another_persons_ids_are_404(on: TestClient) -> None:
    sam = add_user(on)
    mine = lunch(on)
    device = subscribe(on, Browser())
    assert sam.patch(f"/api/reminders/{mine['id']}", json={"enabled": False}).status_code == 404
    assert sam.delete(f"/api/reminders/{mine['id']}").status_code == 404
    assert sam.delete(f"/api/reminders/subscriptions/{device['id']}").status_code == 404
    assert sam.get("/api/reminders").json()["reminders"] == [] and sam.get("/api/reminders").json()["devices"] == []
    assert on.get("/api/reminders").json()["reminders"][0]["enabled"] is True
    assert len(on.get("/api/reminders").json()["devices"]) == 1
    assert sam.post("/api/reminders/test").status_code == 409  # sam has no device; the admin's is never used


def test_the_same_browser_moves_to_the_account_that_turned_it_on_last(on: TestClient) -> None:
    sam = add_user(on)
    b = Browser()
    subscribe(on, b)
    subscribe(sam, b)
    assert on.get("/api/reminders").json()["devices"] == []
    assert len(sam.get("/api/reminders").json()["devices"]) == 1


def test_a_test_account_can_look_but_not_use_it(on: TestClient) -> None:
    sam = add_user(on)
    with db(on) as conn:
        conn.execute("UPDATE users SET is_test_account = 1 WHERE username = 'sam'")
    body = sam.get("/api/reminders").json()
    assert body["enabled"] is True and body["can_use"] is False
    r = sam.post("/api/reminders", json={"kind": "weigh_in", "time": "07:00"})
    assert r.status_code == 403 and r.json()["detail"] == reminders.TEST_ACCOUNT
    assert sam.post("/api/reminders/subscriptions", json=Browser().subscription()).status_code == 403
    assert sam.post("/api/reminders/test").status_code == 403


# --------------------------------------------------------------------------- test send


def test_send_a_test(on: TestClient, fake: FakePush) -> None:
    b = Browser()
    subscribe(on, b)
    r = on.post("/api/reminders/test")
    assert r.status_code == 200 and r.json() == {"devices": 1, "sent": 1, "failed": 0, "removed": 0, "demo": False}
    (req,) = fake.calls
    msg = b.read(req)
    assert msg == {"web_push": 8030, "notification": {"title": "Food log", "body": reminders.TEST_BODY,
                                                      "navigate": f"{HTTPS_URL}/#settings", "lang": "en"}}
    assert on.get("/api/reminders").json()["devices"][0]["last_ok_at"]


def test_the_title_is_the_server_name_only_when_the_admin_changed_it(on: TestClient, fake: FakePush) -> None:
    b = Browser()
    subscribe(on, b)
    assert on.patch("/api/admin/settings", json={"instance.name": "Our kitchen"}).status_code == 200
    on.post("/api/reminders/test")
    assert b.read(fake.calls[-1])["notification"]["title"] == "Our kitchen"


def test_tests_are_limited_to_five_an_hour(on: TestClient, fake: FakePush) -> None:
    subscribe(on, Browser())
    for _ in range(reminders.TESTS_PER_HOUR):
        assert on.post("/api/reminders/test").status_code == 200
    assert on.post("/api/reminders/test").status_code == 429


@pytest.mark.parametrize("status", [404, 410])
def test_a_gone_device_is_deleted(on: TestClient, fake: FakePush, status: int) -> None:
    subscribe(on, Browser())
    fake.status = status
    r = on.post("/api/reminders/test")
    assert r.json() == {"devices": 1, "sent": 0, "failed": 0, "removed": 1, "demo": False}
    assert on.get("/api/reminders").json()["devices"] == []
    events = on.get("/api/me/activity?limit=5").json()
    rows = events["events"] if isinstance(events, dict) else events
    assert any(e["action"] == "reminder.device_removed" for e in rows)


def test_other_errors_keep_the_device_and_say_why(on: TestClient, fake: FakePush) -> None:
    subscribe(on, Browser())
    fake.status = 503
    assert on.post("/api/reminders/test").json()["failed"] == 1
    assert on.get("/api/reminders").json()["devices"][0]["last_error"] == "busy"


def test_a_device_whose_host_resolves_privately_is_never_contacted(on: TestClient) -> None:
    fake = attach(on.app, FakePush(), address="10.0.0.7")
    subscribe(on, Browser())
    assert on.post("/api/reminders/test").json()["failed"] == 1
    assert fake.calls == [] and on.get("/api/reminders").json()["devices"][0]["last_error"] == "blocked"


# --------------------------------------------------------------------------- the loop


def test_the_loop_sends_once_a_day_at_the_local_time(on: TestClient, fake: FakePush) -> None:
    b = Browser()
    subscribe(on, b)
    lunch(on)  # 12:00 in Chicago, every day
    assert tick(on, "2026-11-12T11:59:00-06:00") == 0
    assert tick(on, "2026-11-12T12:00:30+00:00") == 0  # noon in UTC is not noon in Chicago
    assert tick(on, "2026-11-12T12:01:00-06:00") == 1
    msg = b.read(fake.calls[-1])
    assert msg["notification"] == {"title": "Food log", "body": "Time to log lunch.", "navigate": f"{HTTPS_URL}/#add", "lang": "en"}
    assert tick(on, "2026-11-12T12:02:00-06:00") == 0  # once a day
    assert tick(on, "2026-11-12T12:06:00-06:00") == 0
    assert len(fake.calls) == 1
    assert tick(on, "2026-11-13T12:00:00-06:00") == 1  # the next day again
    assert on.get("/api/reminders").json()["reminders"][0]["last_sent_on"] == "2026-11-13"


def test_too_late_is_skipped_not_sent_late(on: TestClient, fake: FakePush) -> None:
    subscribe(on, Browser())
    lunch(on)
    assert tick(on, "2026-11-12T12:05:00-06:00") == 0 and fake.calls == []


def test_only_on_the_chosen_days(on: TestClient, fake: FakePush) -> None:
    subscribe(on, Browser())
    lunch(on, days=1)  # Mondays only; 2026-11-12 is a Thursday, 2026-11-16 a Monday
    assert tick(on, "2026-11-12T12:00:00-06:00") == 0
    assert tick(on, "2026-11-16T12:00:00-06:00") == 1


def test_a_meal_already_logged_is_skipped(on: TestClient, fake: FakePush) -> None:
    subscribe(on, Browser())
    lunch(on)
    food = find_food(on, "apple")
    assert on.post("/api/log", json={"date": "2026-11-12", "meal": "lunch", "food_id": food["id"], "servings": 1}).status_code == 201
    assert tick(on, "2026-11-12T12:00:00-06:00") == 0 and fake.calls == []
    # A planned (not eaten) lunch does not count.
    assert on.post("/api/log", json={"date": "2026-11-13", "meal": "lunch", "food_id": food["id"], "servings": 1,
                                     "status": "planned"}).status_code == 201
    assert tick(on, "2026-11-13T12:00:00-06:00") == 1


def test_off_reminders_and_people_without_a_device_get_nothing(on: TestClient, fake: FakePush) -> None:
    r = lunch(on)
    assert tick(on, "2026-11-12T12:00:00-06:00") == 0  # no device
    subscribe(on, Browser())
    on.patch(f"/api/reminders/{r['id']}", json={"enabled": False})
    assert tick(on, "2026-11-13T12:00:00-06:00") == 0 and fake.calls == []


def test_other_kinds_and_the_servers_own_time(on: TestClient, fake: FakePush) -> None:
    b = Browser()
    subscribe(on, b)
    assert on.post("/api/reminders", json={"kind": "plan_tomorrow", "time": "20:00", "time_zone": "UTC"}).status_code == 201
    assert on.post("/api/reminders", json={"kind": "weigh_in", "time": "07:00"}).status_code == 201  # server time
    assert tick(on, "2026-11-12T20:00:00+00:00") == 1
    assert b.read(fake.calls[-1])["notification"]["body"] == "Time to plan tomorrow's meals."
    local = datetime(2026, 11, 12, 7, 0).astimezone()  # 07:00 on this machine's clock
    assert tick(on, local.isoformat()) == 1
    msg = b.read(fake.calls[-1])["notification"]
    assert msg["body"] == "Time to log your weight." and msg["navigate"] == f"{HTTPS_URL}/#today"


def test_bodies_stay_generic() -> None:
    words = " ".join(reminders.BODIES.values()) + reminders.TEST_BODY
    for banned in ("kidney", "diabet", "insulin", "glucose", "sugar", "potassium", "sodium", "phosph", "low", "dose", "medic"):
        assert banned not in words.lower()


def test_a_disabled_or_test_account_gets_nothing(on: TestClient, fake: FakePush) -> None:
    sam = add_user(on)
    subscribe(sam, Browser())
    lunch(sam)
    with db(on) as conn:
        conn.execute("UPDATE users SET is_test_account = 1 WHERE username = 'sam'")
    assert tick(on, "2026-11-12T12:00:00-06:00") == 0 and fake.calls == []


# --------------------------------------------------------------------------- audit, export, delete


def test_audit_rows_and_export(on: TestClient) -> None:
    r = lunch(on)
    on.patch(f"/api/reminders/{r['id']}", json={"time": "12:15"})
    d = subscribe(on, Browser())
    on.delete(f"/api/reminders/subscriptions/{d['id']}")
    on.delete(f"/api/reminders/{r['id']}")
    lunch(on, meal="dinner", time="18:00")
    subscribe(on, Browser())
    events = on.get("/api/me/activity?limit=20").json()
    rows = events["events"] if isinstance(events, dict) else events
    actions = [e["action"] for e in rows]
    for action in ("reminder.set", "reminder.removed", "reminder.device_added", "reminder.device_removed"):
        assert action in actions
    import io
    import zipfile

    archive = on.get("/api/me/export.zip")
    assert archive.status_code == 200, archive.text
    doc = json.loads(zipfile.ZipFile(io.BytesIO(archive.content)).read("export.json"))
    assert [(x["kind"], x["meal"], x["time"]) for x in doc["reminders"]] == [("log_meal", "dinner", "18:00")]
    text = json.dumps(doc)
    assert "p256dh" not in text and "web.push.apple.com" not in text


def test_deleting_the_account_deletes_its_reminders_and_devices(on: TestClient) -> None:
    sam = add_user(on)
    lunch(sam)
    subscribe(sam, Browser())
    users = on.get("/api/admin/users").json()
    sam_id = next(u["id"] for u in (users["users"] if isinstance(users, dict) else users) if u["username"] == "sam")
    with db(on) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("DELETE FROM users WHERE id = ?", (sam_id,))
        assert conn.execute("SELECT COUNT(*) FROM reminders").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM push_subscriptions").fetchone()[0] == 0


# --------------------------------------------------------------------------- start-up


BASE_ENV = {"DATA_DIR": "/tmp/kh-reminders-test", "PUBLIC_URL": "https://kidney.example.org", "REMINDERS_ENABLED": "true",
            "VAPID_SUBJECT": "mailto:admin@example.org"}


def test_start_up_with_good_settings() -> None:
    s = load_settings(BASE_ENV)
    assert s.reminders.enabled and s.reminders.subject == "mailto:admin@example.org" and s.reminders.timeout_s == 10
    assert s.vapid_key_path == Path("/tmp/kh-reminders-test/vapid_private.pem")
    assert load_settings({**BASE_ENV, "VAPID_SUBJECT": "https://kidney.example.org/contact"}).reminders.subject


@pytest.mark.parametrize(("change", "words"), [
    ({"VAPID_SUBJECT": None}, "needs VAPID_SUBJECT"),
    ({"VAPID_SUBJECT": "admin@example.org"}, "VAPID_SUBJECT must be mailto:"),
    ({"VAPID_SUBJECT": "http://kidney.example.org"}, "VAPID_SUBJECT must be mailto:"),
    ({"VAPID_PRIVATE_KEY": "-----BEGIN PRIVATE KEY-----abc"}, "Give the reminders key as a file"),
    ({"PUBLIC_URL": None}, "needs PUBLIC_URL"),
    ({"PUBLIC_URL": "http://kidney.example.org"}, "needs PUBLIC_URL with https"),
    ({"AUTH_MODE": "none"}, "needs sign-in"),
    ({"VAPID_PRIVATE_KEY_FILE": "/nonexistent/secrets/vapid.pem"}, "does not exist"),
    ({"REMINDERS_TIMEOUT_S": "0"}, "REMINDERS_TIMEOUT_S"),
])
def test_start_up_refusals(change: dict, words: str) -> None:
    env = {**BASE_ENV, **{k: v for k, v in change.items() if v is not None}}
    for k, v in change.items():
        if v is None:
            env.pop(k, None)
    with pytest.raises(ConfigError, match=words):
        load_settings(env)


def test_localhost_over_http_is_allowed_for_trying_it_out() -> None:
    assert load_settings({**BASE_ENV, "PUBLIC_URL": "http://localhost:8000"}).reminders.enabled


def test_a_subject_without_the_switch_warns() -> None:
    s = load_settings({"DATA_DIR": "/tmp/kh-reminders-test", "VAPID_SUBJECT": "mailto:a@example.org"})
    assert any("REMINDERS_ENABLED" in w for w in s.warnings)


def test_the_private_key_is_never_logged(on_settings, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    with signed_in_client(on_settings, base_url=HTTPS_URL) as admin:
        attach(admin.app, FakePush())
        subscribe(admin, Browser())
        admin.post("/api/reminders/test")
        pem = (on_settings.data_dir / "vapid_private.pem").read_text()
    body = "".join(line for line in pem.splitlines() if not line.startswith("-----"))
    for chunk in (body[:40], body[40:80]):
        assert chunk not in caplog.text
    assert "made a new push key" in caplog.text
