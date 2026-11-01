"""Open the Plan's shopping list at Instacart (design note 33; app/instacart.py). A fake Instacart answers behind the app's real
SSRF-checked transport (a fake resolver gives its host an address); nothing touches the network.

Covered: off by default, and off while the switch or the key is missing (200 ``enabled: false``, every other route 404); sign-in;
the exact lines; the request shape (only the title and each chosen food's name, line and grams; nothing about the person); the
key only in the Authorization header, never in a response, the activity list or a log line; private and metadata addresses
refused; redirects never followed; Instacart's errors in short codes; links that are not Instacart's refused; the deadline; the
hourly limit; isolation between people; the audit row (the number of lines only); the config checks.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx2
import pytest

from app import instacart
from app.config import INSTACART_DEVELOPMENT, INSTACART_PRODUCTION, ConfigError, InstacartEnv, load_settings
from app.db import connect
from conftest import ADMIN_USERNAME, DAY, HTTPS_URL, TestClient, add_user, find_food, make_settings, signed_in_client

KEY = "ic-test-key-0123456789abcdefghijklmnop"
PUBLIC = "93.184.216.34"
LINK = "https://customers.dev.instacart.tools/store/shopping_lists/123456"


@dataclass
class FakeInstacart:
    """``POST /idp/v1/products/products_link``; every request is recorded (host, path, headers, JSON body)."""

    status: int = 200
    answer: Any = field(default_factory=lambda: {"products_link_url": LINK})
    headers: dict[str, str] = field(default_factory=dict)
    raw: bytes | None = None
    calls: list[dict[str, Any]] = field(default_factory=list)

    def handler(self, request: httpx2.Request) -> httpx2.Response:
        self.calls.append({"method": request.method, "host": request.headers.get("host"), "path": request.url.path,
                           "headers": dict(request.headers), "body": json.loads(request.content) if request.content else None})
        if request.headers.get("authorization") != f"Bearer {KEY}":
            return httpx2.Response(401, json={"error": {"message": "Unauthorized"}})
        if self.raw is not None:
            return httpx2.Response(self.status, headers=self.headers, content=self.raw)
        return httpx2.Response(self.status, headers=self.headers, json=self.answer)


def attach(app: Any, fake: FakeInstacart, address: str = PUBLIC) -> FakeInstacart:
    client = app.state.instacart
    client.resolver = lambda host, port: [address]
    client.direct = httpx2.MockTransport(fake.handler)
    client.use_env_proxy = False
    return fake


def db(client: TestClient) -> sqlite3.Connection:
    return connect(client.app.state.settings.db_path)


@pytest.fixture
def on(tmp_path: Path, foods_json: Path):
    s = make_settings(tmp_path, foods_json, instacart=InstacartEnv(api_key=KEY))
    with signed_in_client(s, base_url=HTTPS_URL) as admin:
        assert admin.patch("/api/admin/settings", json={"lists.instacart_enabled": True}).status_code == 200
        yield admin


def plan(client: TestClient, query: str, servings: float = 1, date: str = DAY) -> int:
    food = find_food(client, query)
    r = client.post("/api/log", json={"date": date, "meal": "lunch", "food_id": food["id"], "servings": servings, "status": "planned"})
    assert r.status_code == 201, r.text
    return int(food["id"])


def send(client: TestClient, ids: list[int]) -> Any:
    return client.post("/api/instacart/send", json={"start": DAY, "end": DAY, "food_ids": ids})


def _routes_404(client: TestClient) -> None:
    assert client.post("/api/instacart/preview", json={"start": DAY, "end": DAY}).status_code == 404
    assert send(client, [1]).status_code == 404


# --------------------------------------------------------------------------- #
# Off, sign-in
# --------------------------------------------------------------------------- #


def test_off_by_default(client: TestClient) -> None:
    r = client.get("/api/instacart")
    assert r.status_code == 200 and r.json() == {"enabled": False, "max_items": 200}
    _routes_404(client)


def test_the_switch_without_a_key_stays_off(client: TestClient) -> None:
    assert client.patch("/api/admin/settings", json={"lists.instacart_enabled": True}).status_code == 200
    assert client.get("/api/instacart").json()["enabled"] is False
    _routes_404(client)


def test_a_key_without_the_switch_stays_off(tmp_path: Path, foods_json: Path) -> None:
    s = make_settings(tmp_path, foods_json, instacart=InstacartEnv(api_key=KEY))
    with signed_in_client(s) as c:
        fake = attach(c.app, FakeInstacart())
        assert c.get("/api/instacart").json()["enabled"] is False
        _routes_404(c)
        assert fake.calls == []


def test_on(on: TestClient) -> None:
    assert on.get("/api/instacart").json() == {"enabled": True, "max_items": 200}


def test_anonymous_is_401(anon_client: TestClient) -> None:
    assert anon_client.get("/api/instacart").status_code == 401
    assert anon_client.post("/api/instacart/send", json={"start": DAY, "end": DAY, "food_ids": [1]}).status_code == 401


# --------------------------------------------------------------------------- #
# The lines and what is sent
# --------------------------------------------------------------------------- #


def test_preview_shows_the_exact_lines(on: TestClient) -> None:
    plan(on, "Banana", 2)
    plan(on, "Chicken breast", 1)
    r = on.post("/api/instacart/preview", json={"start": DAY, "end": DAY}).json()
    assert r["title"] == "Shopping list"
    assert [i["text"] for i in r["items"]] == ["Banana, raw: 2 servings of 1 medium (118 g)",
                                               "Chicken breast, roasted: 1 serving of 3 oz (85 g)"]
    assert r["items"][0]["name"] == "Banana, raw" and r["items"][0]["amount"] == "2 servings of 1 medium (118 g)"
    assert on.post("/api/instacart/preview", json={"start": "nope", "end": DAY}).status_code in (400, 422)


def test_send_sends_only_the_food_list(on: TestClient) -> None:
    fake = attach(on.app, FakeInstacart())
    banana = plan(on, "Banana", 2)
    plan(on, "Chicken breast")
    r = send(on, [banana, 999999])
    assert r.status_code == 200 and r.json() == {"url": LINK, "items": 1, "error": None, "message": None}
    assert len(fake.calls) == 1
    call = fake.calls[0]
    assert call["method"] == "POST" and call["path"] == "/idp/v1/products/products_link" and call["host"] == "connect.instacart.com"
    assert call["headers"]["authorization"] == f"Bearer {KEY}" and call["headers"]["user-agent"] == "shopping-list"
    assert call["body"] == {"title": "Shopping list", "link_type": "shopping_list", "expires_in": 7, "line_items": [
        {"name": "Banana, raw", "display_text": "Banana, raw: 2 servings of 1 medium (118 g)",
         "line_item_measurements": [{"quantity": 236, "unit": "g"}]}]}
    sent = json.dumps(call["body"]) + json.dumps({k: v for k, v in call["headers"].items() if k != "authorization"})
    for personal in (ADMIN_USERNAME, DAY, "kidney", "Kidney", "user_id", "partner_linkback_url", "localhost"):
        assert personal not in sent, personal


def test_nothing_on_the_list_for_those_ids_is_refused_before_anything_is_sent(on: TestClient) -> None:
    fake = attach(on.app, FakeInstacart())
    plan(on, "Banana")
    r = send(on, [999999])
    assert r.status_code == 400 and "None of those foods" in r.json()["detail"] and fake.calls == []


def test_send_takes_at_most_200_foods(on: TestClient) -> None:
    r = send(on, list(range(1, 202)))
    assert r.status_code in (400, 422) and "food_ids" in r.text


def test_a_line_without_a_weight_has_no_measurement() -> None:
    line = instacart.line_of({"food_id": 3, "food_name": "Tea\x00 bags\n", "serving_desc": None, "servings": 2, "grams": 0})
    assert line.name == "Tea bags" and line.grams is None
    assert instacart.request_body([line])["line_items"] == [{"name": "Tea bags", "display_text": "Tea bags: 2 servings"}]


# --------------------------------------------------------------------------- #
# The audit row, the key
# --------------------------------------------------------------------------- #


def test_the_audit_row_holds_the_number_of_lines_only(on: TestClient) -> None:
    attach(on.app, FakeInstacart())
    ids = [plan(on, "Banana"), plan(on, "Chicken breast")]
    assert send(on, ids).json()["url"] == LINK
    with db(on) as conn:
        rows = conn.execute("SELECT target_type, target_id, details_json FROM audit_log WHERE action = 'instacart.sent'").fetchall()
    assert len(rows) == 1 and rows[0][0] == "instacart" and rows[0][1] is None
    assert json.loads(rows[0][2]) == {"items": 2}
    events = on.get("/api/me/activity").json()
    rows2 = events.get("events", events) if isinstance(events, dict) else events
    assert any(e.get("action") == "instacart.sent" for e in rows2)
    text = json.dumps(events)
    assert "Banana" not in text and LINK not in text and KEY not in text


def test_the_key_is_never_in_a_response_or_a_log_line(on: TestClient, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    fake = attach(on.app, FakeInstacart())
    banana = plan(on, "Banana")
    bodies = [on.get("/api/instacart").text, on.post("/api/instacart/preview", json={"start": DAY, "end": DAY}).text,
              send(on, [banana]).text, on.get("/api/admin/settings").text, on.get("/api/me/activity").text]
    fake.status = 500
    bodies.append(send(on, [banana]).text)
    assert all(KEY not in b for b in bodies)
    assert caplog.records and all(KEY not in r.getMessage() for r in caplog.records)
    assert all(LINK not in r.getMessage() and "Banana" not in r.getMessage() for r in caplog.records)


# --------------------------------------------------------------------------- #
# Egress: addresses, redirects, errors, links, the deadline
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("address", ["10.0.0.5", "127.0.0.1", "192.168.1.20", "169.254.169.254", "fd00:ec2::254"])
def test_a_private_or_metadata_address_is_refused(on: TestClient, address: str) -> None:
    fake = attach(on.app, FakeInstacart(), address=address)
    banana = plan(on, "Banana")
    r = send(on, [banana]).json()
    assert r["url"] is None and r["error"] == "blocked" and r["message"] and fake.calls == []
    with db(on) as conn:  # nothing left the server
        assert conn.execute("SELECT COUNT(*) FROM audit_log WHERE action = 'instacart.sent'").fetchone()[0] == 0


def test_redirects_are_never_followed(on: TestClient) -> None:
    fake = attach(on.app, FakeInstacart(status=302, headers={"Location": "https://elsewhere.example/x"}, raw=b""))
    banana = plan(on, "Banana")
    r = send(on, [banana]).json()
    assert r["error"] == "bad_answer" and r["url"] is None and len(fake.calls) == 1


@pytest.mark.parametrize("status, code", [(400, "rejected"), (422, "rejected"), (403, "auth"), (429, "busy"), (503, "busy"),
                                          (418, "bad_answer")])
def test_instacart_errors_are_short_codes(on: TestClient, status: int, code: str) -> None:
    attach(on.app, FakeInstacart(status=status, answer={"errors": [{"message": "secret detail", "error": {"code": 1001}}]}))
    banana = plan(on, "Banana")
    r = send(on, [banana])
    assert r.status_code == 200
    body = r.json()
    assert body["error"] == code and body["url"] is None and body["items"] == 0
    assert body["message"] == instacart.ERROR_TEXT[code] and "secret detail" not in r.text


def test_a_wrong_key_is_auth(on: TestClient) -> None:
    on.app.state.settings = on.app.state.settings.__class__(**{**on.app.state.settings.__dict__,
                                                               "instacart": InstacartEnv(api_key="another-key-0123456789")})
    attach(on.app, FakeInstacart())
    banana = plan(on, "Banana")
    assert send(on, [banana]).json()["error"] == "auth"


@pytest.mark.parametrize("answer", [
    {"products_link_url": "http://customers.instacart.com/store/x"},
    {"products_link_url": "https://instacart.com.evil.example/x"},
    {"products_link_url": "https://evil.example/instacart.com"},
    {"products_link_url": "https://user:pw@customers.instacart.com/x"},
    {"products_link_url": "javascript:alert(1)"},
    {"products_link_url": "https://customers.instacart.com/" + "x" * 2100},
    {"products_link_url": 5},
    {"link": LINK},
    [LINK],
])
def test_a_link_that_is_not_instacarts_is_refused(on: TestClient, answer: Any) -> None:
    attach(on.app, FakeInstacart(answer=answer))
    banana = plan(on, "Banana")
    r = send(on, [banana]).json()
    assert r["error"] == "bad_answer" and r["url"] is None


def test_instacart_links_are_accepted() -> None:
    for link in ("https://www.instacart.com/store/recipes/1", "https://instacart.com/x?aff=1", LINK):
        assert instacart.check_link(link) == link


def test_a_body_that_is_not_json_or_too_large(on: TestClient) -> None:
    fake = attach(on.app, FakeInstacart(raw=b"<html>oops</html>"))
    banana = plan(on, "Banana")
    assert send(on, [banana]).json()["error"] == "bad_answer"
    fake.raw = b'{"products_link_url": "' + b"a" * (70 * 1024) + b'"}'
    assert send(on, [banana]).json()["error"] == "bad_answer"


def test_instacart_that_never_finishes_answering_is_a_timeout(on: TestClient) -> None:
    fake = attach(on.app, FakeInstacart())
    release = threading.Event()

    def slow(request: httpx2.Request) -> httpx2.Response:
        release.wait(10)
        return fake.handler(request)

    on.app.state.instacart.direct = httpx2.MockTransport(slow)
    on.app.state.instacart.deadline_s = 0.3
    banana = plan(on, "Banana")
    r = send(on, [banana]).json()
    release.set()
    assert r["error"] == "timeout" and r["message"] == "Instacart took too long to answer. Try again later."


def test_the_development_host(tmp_path: Path, foods_json: Path) -> None:
    s = make_settings(tmp_path, foods_json, instacart=InstacartEnv(api_key=KEY, base_url=INSTACART_DEVELOPMENT))
    with signed_in_client(s) as c:
        c.patch("/api/admin/settings", json={"lists.instacart_enabled": True})
        fake = attach(c.app, FakeInstacart())
        banana = plan(c, "Banana")
        assert send(c, [banana]).json()["url"] == LINK
        assert fake.calls[0]["host"] == "connect.dev.instacart.tools"


# --------------------------------------------------------------------------- #
# Limit, isolation, test accounts
# --------------------------------------------------------------------------- #


def test_sends_are_limited_per_hour(on: TestClient) -> None:
    attach(on.app, FakeInstacart())
    banana = plan(on, "Banana")
    for _ in range(10):
        assert send(on, [banana]).status_code == 200
    r = send(on, [banana])
    assert r.status_code == 429 and r.headers["Retry-After"]


def test_another_person_never_sends_someone_elses_foods(on: TestClient) -> None:
    fake = attach(on.app, FakeInstacart())
    banana = plan(on, "Banana")
    sam = add_user(on)
    assert sam.post("/api/instacart/preview", json={"start": DAY, "end": DAY}).json()["items"] == []
    assert send(sam, [banana]).status_code == 400 and fake.calls == []
    apple = plan(sam, "Apple")
    assert send(sam, [apple, banana]).json()["url"] == LINK
    assert [x["name"] for x in fake.calls[0]["body"]["line_items"]] == ["Apple, raw, with skin"]
    with db(on) as conn:
        actors = [r[0] for r in conn.execute("SELECT u.username FROM audit_log a JOIN users u ON u.id = a.actor_user_id "
                                             "WHERE a.action = 'instacart.sent'")]
    assert actors == ["sam"]


def test_a_test_account_may_use_it(on: TestClient) -> None:
    attach(on.app, FakeInstacart())
    sam = add_user(on)
    with db(on) as conn:
        conn.execute("UPDATE users SET is_test_account = 1 WHERE username = 'sam'")
    apple = plan(sam, "Apple")
    assert send(sam, [apple]).json()["url"] == LINK


# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #


def test_config_reads_the_key_from_a_file_only(tmp_path: Path) -> None:
    base = {"DATA_DIR": str(tmp_path)}
    assert load_settings(base).instacart == InstacartEnv()
    with pytest.raises(ConfigError, match="INSTACART_API_KEY_FILE"):
        load_settings({**base, "INSTACART_API_KEY": KEY})
    key_file = tmp_path / "instacart.key"
    key_file.write_text(KEY + "\n", encoding="utf-8")
    s = load_settings({**base, "INSTACART_API_KEY_FILE": str(key_file)})
    assert s.instacart.api_key == KEY and s.instacart.base_url == INSTACART_PRODUCTION and s.instacart.key_set
    assert KEY in s.secret_values() and KEY not in repr(s) and KEY not in repr(s.instacart)


def test_config_checks_the_base_url(tmp_path: Path) -> None:
    base = {"DATA_DIR": str(tmp_path)}
    s = load_settings({**base, "INSTACART_BASE_URL": "https://Connect.Dev.Instacart.Tools/"})
    assert s.instacart.base_url == INSTACART_DEVELOPMENT and not any("INSTACART" in w for w in s.warnings)
    other = load_settings({**base, "INSTACART_BASE_URL": "https://idp.example.com:8443"})
    assert other.instacart.base_url == "https://idp.example.com:8443" and any("INSTACART_BASE_URL" in w for w in other.warnings)
    for bad in ("http://connect.instacart.com", "connect.instacart.com", "https://connect.instacart.com/idp/v1",
                "https://u:p@connect.instacart.com", "https://connect.instacart.com?x=1", "https://"):
        with pytest.raises(ConfigError, match="INSTACART_BASE_URL"):
            load_settings({**base, "INSTACART_BASE_URL": bad})
