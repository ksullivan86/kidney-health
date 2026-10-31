"""Your own list app (design note 30 §2; app/list_sync/). A fake Grocy, KitchenOwl or Mealie (tests/lists_support.py) answers
behind the app's real SSRF-checked transport; nothing touches the network.

Covered: the switch (200 with ``enabled: false``, every other route 404); sign-in; isolation between people; a test account; the
address rules (http only for an allowed home address, no password in it, no query); the key is write-only, sealed for its owner,
never in a response, the database in plain text, the activity list or a log line; a new address needs the key again; Test (lists,
the one list chosen, errors in short codes); private addresses refused unless LIST_SYNC_ALLOWED_HOSTS lists the name or network,
metadata always refused, plain http to a public address refused; redirects never followed; each app's request shape; preview and
send (only the chosen foods of that range, the same words as Share list, partial failures, the hourly limit); removing it; the
config check; key rotation.
"""
from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from app import crypto
from app.config import ConfigError, load_settings
from app.db import connect
from app.list_sync.api import servings_words
from conftest import DAY, HTTPS_URL, TestClient, add_user, find_food, make_settings, signed_in_client
from lists_support import HOME, KEY, PUBLIC, FakeListApp, attach_list_app


def db(client: TestClient) -> sqlite3.Connection:
    return connect(client.app.state.settings.db_path)


@pytest.fixture
def on(tmp_path: Path, foods_json: Path):
    s = make_settings(tmp_path, foods_json)
    with signed_in_client(s, base_url=HTTPS_URL) as admin:
        assert admin.patch("/api/admin/settings", json={"lists.sync_enabled": True}).status_code == 200
        yield admin


@pytest.fixture
def home(tmp_path: Path, foods_json: Path):
    s = make_settings(tmp_path, foods_json, list_sync_allowed_hosts=("grocy.lan", "10.20.0.0/16"))
    with signed_in_client(s, base_url=HTTPS_URL) as admin:
        assert admin.patch("/api/admin/settings", json={"lists.sync_enabled": True}).status_code == 200
        yield admin


def set_up(client: TestClient, app: str = "grocy", url: str = "https://lists.example.com", **extra: Any) -> dict[str, Any]:
    r = client.put("/api/list-sync", json={"app": app, "base_url": url, "key": KEY, **extra})
    assert r.status_code == 200, r.text
    return r.json()


def plan(client: TestClient, query: str, servings: float = 1, date: str = DAY) -> int:
    food = find_food(client, query)
    r = client.post("/api/log", json={"date": date, "meal": "lunch", "food_id": food["id"], "servings": servings, "status": "planned"})
    assert r.status_code == 201, r.text
    return int(food["id"])


# --------------------------------------------------------------------------- #
# The switch, sign-in, isolation
# --------------------------------------------------------------------------- #


def test_off_by_default_answers_and_every_other_route_is_404(client: TestClient) -> None:
    r = client.get("/api/list-sync")
    assert r.status_code == 200 and r.json() == {"enabled": False, "can_use": False, "private_hosts": False, "apps": [],
                                                 "connection": None}
    assert client.put("/api/list-sync", json={"app": "grocy", "base_url": "https://x.example", "key": KEY}).status_code == 404
    assert client.delete("/api/list-sync").status_code == 404
    assert client.post("/api/list-sync/test").status_code == 404
    assert client.post("/api/list-sync/preview", json={"start": DAY, "end": DAY}).status_code == 404
    assert client.post("/api/list-sync/send", json={"start": DAY, "end": DAY, "food_ids": [1]}).status_code == 404


def test_anonymous_is_401(anon_client: TestClient) -> None:
    assert anon_client.get("/api/list-sync").status_code == 401
    assert anon_client.post("/api/list-sync/test").status_code == 401


def test_on_lists_the_three_apps_and_no_connection(on: TestClient) -> None:
    body = on.get("/api/list-sync").json()
    assert body["enabled"] is True and body["can_use"] is True and body["private_hosts"] is False and body["connection"] is None
    assert [a["id"] for a in body["apps"]] == ["grocy", "kitchenowl", "mealie"]
    assert all(a["key_help"] and a["key_name"] for a in body["apps"])


def test_another_person_never_sees_or_uses_it(on: TestClient) -> None:
    fake = attach_list_app(on.app, FakeListApp())
    set_up(on)
    sam = add_user(on)
    assert sam.get("/api/list-sync").json()["connection"] is None
    assert sam.post("/api/list-sync/test").status_code == 404
    assert sam.post("/api/list-sync/preview", json={"start": DAY, "end": DAY}).status_code == 404
    assert sam.post("/api/list-sync/send", json={"start": DAY, "end": DAY, "food_ids": [1]}).status_code == 404
    assert sam.delete("/api/list-sync").status_code == 404
    assert fake.calls == []
    assert on.get("/api/list-sync").json()["connection"]["key_set"] is True


def test_a_test_account_cannot_set_one_up(on: TestClient) -> None:
    sam = add_user(on)
    with db(on) as conn:
        conn.execute("UPDATE users SET is_test_account = 1 WHERE username = 'sam'")
    assert sam.get("/api/list-sync").json()["can_use"] is False
    r = sam.put("/api/list-sync", json={"app": "grocy", "base_url": "https://x.example", "key": KEY})
    assert r.status_code == 403 and "Test accounts" in r.json()["detail"]


def test_turned_off_again_keeps_the_row_and_answers_off(on: TestClient) -> None:
    set_up(on)
    on.patch("/api/admin/settings", json={"lists.sync_enabled": False})
    assert on.get("/api/list-sync").json()["enabled"] is False
    assert on.post("/api/list-sync/test").status_code == 404
    on.patch("/api/admin/settings", json={"lists.sync_enabled": True})
    assert on.get("/api/list-sync").json()["connection"]["app"] == "grocy"


# --------------------------------------------------------------------------- #
# Address and key
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("url, words", [
    ("http://lists.example.com", "Plain http"),
    ("ftp://lists.example.com", "http:// or https://"),
    ("https://kim:pw@lists.example.com", "user name and password"),
    ("https://lists.example.com/?x=1", "after ? or #"),
    ("lists.example.com", "http:// or https://"),
    ("https://lists.example.com/ x", "Enter the address"),
])
def test_addresses_that_cannot_be_used(on: TestClient, url: str, words: str) -> None:
    r = on.put("/api/list-sync", json={"app": "grocy", "base_url": url, "key": KEY})
    assert r.status_code == 400 and words in r.json()["detail"]


def test_the_key_is_write_only_and_sealed_for_its_owner(on: TestClient, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    fake = attach_list_app(on.app, FakeListApp())
    out = set_up(on, url="https://lists.example.com/grocy/")
    assert out["base_url"] == "https://lists.example.com/grocy" and out["key_set"] is True and KEY not in str(out)
    assert KEY not in on.get("/api/list-sync").text
    on.post("/api/list-sync/test")
    assert fake.calls and all(KEY not in r.getMessage() for r in caplog.records)
    raw = Path(on.app.state.settings.db_path).read_bytes()
    assert KEY.encode() not in raw
    with db(on) as conn:
        row = conn.execute("SELECT user_id, key_enc FROM list_sync").fetchone()
        audit = conn.execute("SELECT details_json FROM audit_log WHERE action LIKE 'list_sync.%'").fetchall()
    keyring = on.app.state.auth.require_keyring()
    assert keyring.unseal(row["key_enc"], purpose="list-sync", owner=row["user_id"]) == {"key": KEY}
    with pytest.raises(crypto.InvalidToken):
        keyring.unseal(row["key_enc"], purpose="list-sync", owner=row["user_id"] + 1)
    assert audit and all(KEY not in a[0] for a in audit)


def test_a_new_address_or_app_needs_the_key_again(on: TestClient) -> None:
    set_up(on)
    r = on.put("/api/list-sync", json={"app": "grocy", "base_url": "https://other.example.com"})
    assert r.status_code == 400 and "Enter the key again" in r.json()["detail"]
    r = on.put("/api/list-sync", json={"app": "mealie", "base_url": "https://lists.example.com"})
    assert r.status_code == 400
    # The same app and address keep the key (choosing a list).
    r = on.put("/api/list-sync", json={"app": "grocy", "base_url": "https://lists.example.com", "list_id": "4", "list_name": "Shop"})
    assert r.status_code == 200 and r.json()["key_set"] is True and r.json()["list_id"] == "4"
    # The first time, a key is needed.
    sam = add_user(on)
    assert sam.put("/api/list-sync", json={"app": "grocy", "base_url": "https://lists.example.com"}).status_code == 400


def test_a_list_id_must_look_like_the_apps_own(on: TestClient) -> None:
    r = on.put("/api/list-sync", json={"app": "grocy", "base_url": "https://lists.example.com", "key": KEY, "list_id": "../x"})
    assert r.status_code == 400
    r = on.put("/api/list-sync", json={"app": "mealie", "base_url": "https://lists.example.com", "key": KEY,
                                       "list_id": "0b8f3c1e-1a2b-4c3d-9e8f-001122334455"})
    assert r.status_code == 200


# --------------------------------------------------------------------------- #
# Test, and where the server may connect
# --------------------------------------------------------------------------- #


def test_test_lists_and_chooses_the_only_list(on: TestClient) -> None:
    fake = attach_list_app(on.app, FakeListApp())
    set_up(on)
    r = on.post("/api/list-sync/test").json()
    assert r["ok"] is True and r["error"] is None and r["lists"] == [{"id": "1", "name": "Groceries"}]
    assert r["connection"]["list_id"] == "1" and r["connection"]["list_name"] == "Groceries" and r["connection"]["last_test_at"]
    assert [c["path"] for c in fake.calls] == ["/api/system/info", "/api/objects/shopping_lists"]
    assert fake.calls[0]["headers"]["grocy-api-key"] == KEY and fake.calls[0]["host"] == "lists.example.com"


def test_test_with_several_lists_waits_for_a_choice(on: TestClient) -> None:
    attach_list_app(on.app, FakeListApp(lists=[{"id": 1, "name": "A"}, {"id": 2, "name": "B"}]))
    set_up(on)
    r = on.post("/api/list-sync/test").json()
    assert r["ok"] and len(r["lists"]) == 2 and r["connection"]["list_id"] is None


def test_a_wrong_key_is_auth(on: TestClient) -> None:
    attach_list_app(on.app, FakeListApp(key="another-key-0123456789"))
    set_up(on)
    r = on.post("/api/list-sync/test").json()
    assert r["ok"] is False and r["error"] == "auth" and "did not accept the key" in r["message"]
    assert on.get("/api/list-sync").json()["connection"]["last_test_error"] == "auth"


def test_a_wrong_path_is_not_found(on: TestClient) -> None:
    attach_list_app(on.app, FakeListApp(prefix="/grocy"))
    set_up(on)
    assert on.post("/api/list-sync/test").json()["error"] == "not_found"
    set_up(on, url="https://lists.example.com/grocy")
    assert on.post("/api/list-sync/test").json()["ok"] is True


def test_redirects_are_never_followed(on: TestClient) -> None:
    fake = attach_list_app(on.app, FakeListApp(redirect=True))
    set_up(on)
    r = on.post("/api/list-sync/test").json()
    assert r["error"] == "redirect" and len(fake.calls) == 1 and fake.calls[0]["host"] == "lists.example.com"


def test_a_home_address_is_refused_unless_allowed(on: TestClient) -> None:
    fake = attach_list_app(on.app, FakeListApp(), address=HOME)
    set_up(on, url="https://grocy.lan")
    r = on.post("/api/list-sync/test").json()
    assert r["error"] == "blocked" and "admin" in r["message"] and fake.calls == []


def test_allowed_home_hosts_by_name_and_network(home: TestClient) -> None:
    assert home.get("/api/list-sync").json()["private_hosts"] is True
    fake = attach_list_app(home.app, FakeListApp(), address=lambda host: {"grocy.lan": HOME, "kitchen.lan": "10.20.3.4",
                                                                          "other.lan": "10.99.0.1"}[host])
    set_up(home, url="http://grocy.lan:9283")
    assert home.post("/api/list-sync/test").json()["ok"] is True
    assert fake.calls[-1]["host"] == "grocy.lan:9283"
    set_up(home, url="http://kitchen.lan")  # not named, but its address is in 10.20.0.0/16
    assert home.post("/api/list-sync/test").json()["ok"] is True
    set_up(home, url="https://other.lan")  # neither
    assert home.post("/api/list-sync/test").json()["error"] == "blocked"


def test_metadata_and_link_local_are_refused_even_when_listed(tmp_path: Path, foods_json: Path) -> None:
    s = make_settings(tmp_path, foods_json, list_sync_allowed_hosts=("169.254.0.0/16", "meta.lan"))
    with signed_in_client(s, base_url=HTTPS_URL) as admin:
        admin.patch("/api/admin/settings", json={"lists.sync_enabled": True})
        fake = attach_list_app(admin.app, FakeListApp(), address="169.254.169.254")
        set_up(admin, url="http://meta.lan")
        assert admin.post("/api/list-sync/test").json()["error"] == "blocked" and fake.calls == []


def test_plain_http_to_a_public_address_is_refused(home: TestClient) -> None:
    fake = attach_list_app(home.app, FakeListApp(), address=PUBLIC)
    set_up(home, url="http://grocy.lan")  # allowed by name, but it resolves to the internet: the key must not go there in clear
    assert home.post("/api/list-sync/test").json()["error"] == "blocked" and fake.calls == []


def test_tests_are_limited_per_hour(on: TestClient) -> None:
    attach_list_app(on.app, FakeListApp())
    set_up(on)
    for _ in range(30):
        assert on.post("/api/list-sync/test").status_code == 200
    r = on.post("/api/list-sync/test")
    assert r.status_code == 429 and r.headers["Retry-After"]


# --------------------------------------------------------------------------- #
# Preview and send
# --------------------------------------------------------------------------- #


def test_servings_words_match_plans_share_list() -> None:
    assert [servings_words(x) for x in (1, 3, 0.5, 1.25, 2.005, 1200, 0.333)] == [
        "1 serving", "3 servings", "0.5 servings", "1.25 servings", "2.01 servings", "1,200 servings", "0.33 servings"]


def test_preview_shows_the_exact_lines(on: TestClient) -> None:
    attach_list_app(on.app, FakeListApp())
    set_up(on)
    plan(on, "Banana", 2)
    plan(on, "Chicken breast", 1)
    r = on.post("/api/list-sync/preview", json={"start": DAY, "end": DAY}).json()
    assert r["app"] == "grocy" and r["app_name"] == "Grocy" and r["ready"] is False and r["last_sent_at"] is None
    assert [i["text"] for i in r["items"]] == ["Banana, raw: 2 servings of 1 medium (118 g)",
                                               "Chicken breast, roasted: 1 serving of 3 oz (85 g)"]
    assert r["items"][0]["name"] == "Banana, raw" and r["items"][0]["amount"] == "2 servings of 1 medium (118 g)"
    assert on.post("/api/list-sync/preview", json={"start": "nope", "end": DAY}).status_code in (400, 422)


def test_send_needs_a_chosen_list(on: TestClient) -> None:
    attach_list_app(on.app, FakeListApp(lists=[{"id": 1, "name": "A"}, {"id": 2, "name": "B"}]))
    set_up(on)
    banana = plan(on, "Banana")
    r = on.post("/api/list-sync/send", json={"start": DAY, "end": DAY, "food_ids": [banana]})
    assert r.status_code == 409 and "Choose a list" in r.json()["detail"]


def test_grocy_send_adds_notes_and_only_the_chosen_foods(on: TestClient) -> None:
    fake = attach_list_app(on.app, FakeListApp(lists=[{"id": 7, "name": "Shop"}]))
    set_up(on)
    on.post("/api/list-sync/test")
    banana = plan(on, "Banana", 2)
    plan(on, "Chicken breast")
    r = on.post("/api/list-sync/send", json={"start": DAY, "end": DAY, "food_ids": [banana, 999999]}).json()
    assert r["sent"] == 1 and r["error"] is None and r["connection"]["last_sent_count"] == 1 and r["connection"]["last_sent_at"]
    assert fake.added == [{"shopping_list_id": 7, "note": "Banana, raw: 2 servings of 1 medium (118 g)"}]
    with db(on) as conn:
        row = conn.execute("SELECT details_json FROM audit_log WHERE action = 'list_sync.sent'").fetchone()
    assert '"items":1' in row[0] and '"app":"grocy"' in row[0] and "Banana" not in row[0]
    # Nothing on the list for those ids: refused before anything is sent.
    assert on.post("/api/list-sync/send", json={"start": DAY, "end": DAY, "food_ids": [999999]}).status_code == 400


def test_kitchenowl_send_by_name_with_the_amount_as_description(on: TestClient) -> None:
    fake = attach_list_app(on.app, FakeListApp(app="kitchenowl", lists=[{"id": 12, "name": "Weekly"}]))
    set_up(on, app="kitchenowl")
    t = on.post("/api/list-sync/test").json()
    assert t["lists"] == [{"id": "12", "name": "Home: Weekly"}] and t["connection"]["list_id"] == "12"
    assert fake.calls[0]["headers"]["authorization"] == f"Bearer {KEY}"
    banana = plan(on, "Banana")
    on.post("/api/list-sync/send", json={"start": DAY, "end": DAY, "food_ids": [banana]})
    assert fake.added == [{"list": "12", "name": "Banana, raw", "description": "1 serving of 1 medium (118 g)"}]
    assert fake.calls[-1]["path"] == "/api/shoppinglist/12/add-item-by-name"


def test_mealie_send_in_bulk_with_quantity_0(on: TestClient) -> None:
    uuid = "0b8f3c1e-1a2b-4c3d-9e8f-001122334455"
    fake = attach_list_app(on.app, FakeListApp(app="mealie", lists=[{"id": uuid, "name": "Shopping"}]))
    set_up(on, app="mealie")
    t = on.post("/api/list-sync/test").json()
    assert t["connection"]["list_id"] == uuid
    assert any(c["path"] == "/api/households/shopping/lists" and "perPage=50" in c["query"] for c in fake.calls)
    ids = [plan(on, "Banana"), plan(on, "Chicken breast")]
    r = on.post("/api/list-sync/send", json={"start": DAY, "end": DAY, "food_ids": ids}).json()
    assert r["sent"] == 2
    assert fake.added == [{"shoppingListId": uuid, "note": "Banana, raw: 1 serving of 1 medium (118 g)", "quantity": 0},
                          {"shoppingListId": uuid, "note": "Chicken breast, roasted: 1 serving of 3 oz (85 g)", "quantity": 0}]


def test_a_send_that_fails_half_way_says_how_many_went(on: TestClient) -> None:
    attach_list_app(on.app, FakeListApp(fail_after=1))
    set_up(on)
    on.post("/api/list-sync/test")
    ids = [plan(on, "Banana"), plan(on, "Chicken breast")]
    r = on.post("/api/list-sync/send", json={"start": DAY, "end": DAY, "food_ids": ids}).json()
    assert r["sent"] == 1 and r["error"] == "app_error" and r["message"]


def test_sends_are_limited_per_hour(on: TestClient) -> None:
    attach_list_app(on.app, FakeListApp())
    set_up(on)
    on.post("/api/list-sync/test")
    banana = plan(on, "Banana")
    for _ in range(6):
        assert on.post("/api/list-sync/send", json={"start": DAY, "end": DAY, "food_ids": [banana]}).status_code == 200
    assert on.post("/api/list-sync/send", json={"start": DAY, "end": DAY, "food_ids": [banana]}).status_code == 429


def test_send_takes_at_most_200_foods(on: TestClient) -> None:
    set_up(on)
    r = on.post("/api/list-sync/send", json={"start": DAY, "end": DAY, "food_ids": list(range(1, 202))})
    assert r.status_code == 400 and "food_ids" in r.text


# --------------------------------------------------------------------------- #
# Remove, config, rotation
# --------------------------------------------------------------------------- #


def test_remove_forgets_the_address_and_key(on: TestClient) -> None:
    set_up(on)
    assert on.delete("/api/list-sync").status_code == 204
    assert on.get("/api/list-sync").json()["connection"] is None
    assert on.delete("/api/list-sync").status_code == 404
    with db(on) as conn:
        assert conn.execute("SELECT COUNT(*) FROM list_sync").fetchone()[0] == 0
        actions = [r[0] for r in conn.execute("SELECT action FROM audit_log WHERE action LIKE 'list_sync.%' ORDER BY id")]
    assert actions == ["list_sync.set_up", "list_sync.removed"]


def test_the_activity_list_shows_set_up_and_sends(on: TestClient) -> None:
    set_up(on)
    events = on.get("/api/me/activity").json()
    rows = events.get("events", events) if isinstance(events, dict) else events
    assert any(e.get("action") == "list_sync.set_up" for e in rows)


def test_config_checks_the_allowed_hosts(tmp_path: Path) -> None:
    base = {"DATA_DIR": str(tmp_path)}
    s = load_settings({**base, "LIST_SYNC_ALLOWED_HOSTS": "Grocy.LAN, 192.168.1.0/24 10.0.0.5"})
    assert s.list_sync_allowed_hosts == ("grocy.lan", "192.168.1.0/24", "10.0.0.5")
    for bad in ("0.0.0.0/0", "*.lan", "grocy.lan:9283", "http://grocy.lan", "::/0"):
        with pytest.raises(ConfigError):
            load_settings({**base, "LIST_SYNC_ALLOWED_HOSTS": bad})


def test_key_rotation_covers_the_list_key() -> None:
    assert ("list_sync", "user_id", "key_enc", "key_id") in crypto.ENCRYPTED_COLUMNS


def test_list_sync_never_goes_through_an_outbound_proxy() -> None:
    """A proxy would resolve the name itself, so LIST_SYNC_ALLOWED_HOSTS and the https rule would no longer apply
    (security review of 0.19)."""
    from app.list_sync.apps import HostAllowlist, Net

    assert Net(HostAllowlist.parse(())).use_env_proxy is False


def test_a_list_app_that_never_finishes_answering_is_a_timeout(on: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    import threading

    import httpx2

    from app.list_sync import api as list_api

    fake = attach_list_app(on.app, FakeListApp())
    set_up(on)
    release = threading.Event()

    def slow(request: httpx2.Request) -> httpx2.Response:
        release.wait(10)
        return fake.handler(request)

    on.app.state.list_sync_net.direct = httpx2.MockTransport(slow)
    monkeypatch.setattr(list_api, "DEADLINE_S", 0.3)
    r = on.post("/api/list-sync/test").json()
    release.set()
    assert r["ok"] is False and r["error"] == "timeout" and r["message"] == "The list app took too long to answer. Try again later."
