"""``POST /api/vision/label`` and ``POST /api/vision/plate`` (note 03 R8, R9, §9 B1, B10; note 04 R3, §9 A1,
A4): AI off → 404; a raw JPEG only (415 / 413 / 422 before anything is sent); metadata removed from the
bytes that leave; vision, plate and agent switches; the Hermes tool check before **every** photo; their
own consent; the daily limit; the dry run; upstream failures; the Quick-add draft and the plate
checklist; one person's photos and foods are not another's. No network: a fake provider answers."""
from __future__ import annotations

import base64
import json
import logging
import sqlite3
import struct
from pathlib import Path
from typing import Any, Iterator

import pytest

from ai_support import FakeProvider, attach, chat
from conftest import HTTPS_URL, TestClient, add_user, make_settings, sign_in
from app.config import AiEnv, Settings
from app.imagecheck import check_jpeg
from app.main import create_app
from app.models import FoodCreate

IMAGES = Path(__file__).resolve().parent / "fixtures" / "ai" / "images"
LABEL_JPG = (IMAGES / "label.jpg").read_bytes()
PLATE_JPG = (IMAGES / "progressive.jpg").read_bytes()
KEY = "sk-env-0123456789abcdefghijklmn"
TARGETS = {"potassium_mg": 2500, "phosphorus_mg": 1000, "sodium_mg": 2000, "carbs_per_meal_g": 60}

LABEL_ANSWER = {
    "status": "ok", "product_name": "Whole wheat crackers", "serving_text": "5 crackers (30 g)", "serving_g": 30,
    "basis": "per_serving",
    "per_serving": {"calories_kcal": 140, "protein_g": 2, "fat_g": 6, "sat_fat_g": 1, "carbs_g": 19, "fiber_g": 3,
                    "sugar_g": 0, "sodium_mg": 230, "potassium_mg": None, "phosphorus_mg": None, "calcium_mg": None},
    "salt_g": None, "percent_dv": {"sodium": 10, "potassium": 2, "phosphorus": None, "calcium": None},
    "ingredients_text": "Whole wheat flour, oil, salt, sodium acid pyrophosphate", "label_style": "us_nutrition_facts",
}
PLATE_ANSWER = {"status": "ok", "items": [
    {"name": "apple slices", "search": "apple raw", "grams_estimate": 91, "confidence": "high"},
    {"name": "green beans", "search": "green beans", "grams_estimate": 60, "confidence": "low"},
]}


def settings_for(tmp_path: Path, foods_json: Path, **ai: Any) -> Settings:
    env = {"provider": "openai", "api_key": KEY, "model": "gpt-6-luna", "vision_model": "gpt-6-luna", **ai}
    return make_settings(tmp_path, foods_json, ai=AiEnv(**env))


def enable(client: TestClient, **extra: Any) -> None:
    r = client.patch("/api/admin/settings", json={"ai.enabled": True, **extra})
    assert r.status_code == 200, r.text


def ready(client: TestClient, *, purposes: tuple[str, ...] = ("photos",)) -> int:
    """Opted in, consent given for ``purposes``; returns the provider id."""
    assert client.put("/api/profile", json={"targets": TARGETS}).status_code == 200
    assert client.patch("/api/me/ai", json={"opt_in": True}).status_code == 200
    pid = client.get("/api/ai/status").json()["provider"]["id"]
    for purpose in purposes:
        r = client.post("/api/ai/consent", json={"provider_id": pid, "purpose": purpose})
        assert r.status_code == 200, r.text
    return pid


def photo(client: TestClient, path: str, data: Any = LABEL_JPG, *, ctype: str = "image/jpeg", **params: Any) -> Any:
    return client.post(path, content=data, headers={"Content-Type": ctype}, params=params)


def usage_rows(client: TestClient) -> int:
    conn = sqlite3.connect(client.app.state.settings.db_path)
    try:
        return int(conn.execute("SELECT COALESCE(SUM(requests), 0) FROM ai_usage").fetchone()[0])
    finally:
        conn.close()


def sent_image(provider: FakeProvider, index: int = 0) -> bytes:
    """The JPEG bytes inside the ``data:`` URL of the chat request ``index``."""
    body = provider.bodies()[index]
    part = next(p for p in body["messages"][1]["content"] if p["type"] == "image_url")
    head, data = part["image_url"]["url"].split(",", 1)
    assert head == "data:image/jpeg;base64"
    return base64.b64decode(data)


@pytest.fixture
def vc(tmp_path, foods_json) -> Iterator[TestClient]:
    with TestClient(create_app(settings_for(tmp_path, foods_json)), base_url=HTTPS_URL) as c:
        sign_in(c)
        enable(c)
        yield c


# --------------------------------------------------------------------------- #
# Off, refused uploads, size caps
# --------------------------------------------------------------------------- #


def test_photo_routes_are_404_while_ai_is_off(tmp_path, foods_json):
    with TestClient(create_app(settings_for(tmp_path, foods_json)), base_url=HTTPS_URL) as c:
        sign_in(c)
        provider = FakeProvider()
        with attach(c.app, provider):
            for path in ("/api/vision/label", "/api/vision/plate"):
                r = photo(c, path)
                assert r.status_code == 404 and r.json() == {"detail": "Not Found"}
        assert provider.requests == [] and usage_rows(c) == 0


def _with_size(data: bytes, width: int, height: int) -> bytes:
    pos = 2
    while data[pos + 1] not in (0xC0, 0xC1, 0xC2):
        pos += 2 + struct.unpack(">H", data[pos + 2:pos + 4])[0]
    at = pos + 5
    return data[:at] + struct.pack(">HH", height, width) + data[at + 4:]


PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


@pytest.mark.parametrize("data, ctype, status, reason", [
    (LABEL_JPG, "image/png", 415, "not_jpeg"),
    (LABEL_JPG, "multipart/form-data; boundary=x", 415, "not_jpeg"),
    (PNG, "image/jpeg", 415, "not_jpeg"),
    (b"", "image/jpeg", 415, "not_jpeg"),
    (LABEL_JPG[: len(LABEL_JPG) // 2], "image/jpeg", 422, "truncated"),
    (_with_size(LABEL_JPG, 52800, 44), "image/jpeg", 422, "dimensions"),
    (_with_size(LABEL_JPG, 2048, 2048), "image/jpeg", 422, "dimensions"),
    (_with_size(LABEL_JPG, 1000, 200), "image/jpeg", 422, "dimensions"),
])
def test_only_a_plain_jpeg_is_accepted_and_nothing_is_sent_otherwise(vc, data, ctype, status, reason):
    ready(vc)
    provider = FakeProvider()
    with attach(vc.app, provider):
        r = photo(vc, "/api/vision/label", data, ctype=ctype)
    assert (r.status_code, r.json().get("reason")) == (status, reason), r.text
    assert provider.requests == [] and usage_rows(vc) == 0  # refused before the quota and the call


def test_the_size_cap_applies_to_declared_and_streamed_bodies(tmp_path, foods_json):
    settings = settings_for(tmp_path, foods_json)
    settings = Settings(**{**settings.__dict__, "max_image_bytes": 4096})
    with TestClient(create_app(settings), base_url=HTTPS_URL) as c:
        sign_in(c)
        enable(c)
        ready(c)
        provider = FakeProvider()
        with attach(c.app, provider):
            assert photo(c, "/api/vision/label", LABEL_JPG).status_code == 413  # Content-Length 7320 > 4096

            def chunks() -> Iterator[bytes]:  # no Content-Length: counted while reading
                for i in range(0, len(LABEL_JPG), 1000):
                    yield LABEL_JPG[i:i + 1000]

            assert photo(c, "/api/vision/label", chunks()).status_code == 413
        assert provider.requests == []


# --------------------------------------------------------------------------- #
# What leaves the server
# --------------------------------------------------------------------------- #


def test_metadata_is_removed_before_the_photo_leaves_and_never_stored(vc, caplog):
    assert b"FixtureCam" in LABEL_JPG and b"secret comment" in LABEL_JPG
    ready(vc)
    caplog.set_level(logging.DEBUG)
    provider = FakeProvider([chat(LABEL_ANSWER)])
    with attach(vc.app, provider):
        r = photo(vc, "/api/vision/label")
    assert r.status_code == 200, r.text
    sent = sent_image(provider)
    assert sent == check_jpeg(LABEL_JPG, max_bytes=4 << 20).data
    assert b"FixtureCam" not in sent and b"secret comment" not in sent and b"\xff\xe1" not in sent[:200]
    body = provider.bodies()[0]
    assert body["model"] == "gpt-6-luna" and body["response_format"]["json_schema"]["name"] == "nutrition_label"
    assert body["store"] is False and "temperature" not in body  # OpenAI preset: store false, temperature omitted
    event = vc.get("/api/ai/audit").json()["events"][0]
    assert event["feature"] == "read_label" and event["status"] == "ok"
    image = next(p for p in event["request_json"]["messages"][1]["content"] if p["type"] == "image")
    assert image["bytes"] == len(sent) and image["width"] == 320 and len(image["image_sha256"]) == 64
    stored = json.dumps(event)
    b64 = base64.b64encode(sent).decode("ascii")
    assert b64[:200] not in stored and b64[:200] not in caplog.text  # never stored, never logged


def test_the_label_answer_is_a_quick_add_draft_that_is_never_saved(vc):
    ready(vc)
    before = len(vc.get("/api/foods", params={"q": "crackers", "limit": 50}).json()["foods"])
    with attach(vc.app, FakeProvider([chat(LABEL_ANSWER)])):
        r = photo(vc, "/api/vision/label")
    data = r.json()
    assert data["status"] == "ok" and data["notice"].startswith("Read by AI from your photo")
    draft = data["draft"]
    FoodCreate.model_validate(draft)  # the shape of POST /api/foods
    assert draft["name"] == "Whole wheat crackers" and draft["serving_g"] == 30.0 and data["needs"] == []
    assert draft["nutrients"]["sodium_mg"] == 230.0 and draft["nutrients"]["potassium_mg"] == 94.0  # 2 % of 4700 mg
    assert "potassium_mg" in data["estimated"] and "sodium_mg" not in data["estimated"]
    assert draft["flags"] == [] and "additive:phosphate" in {c["code"] for c in data["checks"]}  # the regex scan, not the model
    assert {"calories_kcal", "sodium_mg", "name", "ingredients_text"} <= set(data["from_photo"])
    assert data["provider"] == {"id": 1, "label": "OpenAI", "model": "gpt-6-luna", "host": "api.openai.com"}
    assert len(vc.get("/api/foods", params={"q": "crackers", "limit": 50}).json()["foods"]) == before  # nothing saved
    # Saving is the person's ordinary food create, which scans the ingredient text they confirmed.
    saved = vc.post("/api/foods", json=draft)
    assert saved.status_code == 201 and "phosphate_additive" in saved.json()["flags"]
    corrected = vc.post("/api/foods", json={**draft, "name": "Crackers (checked)", "ingredients_text": "Whole wheat flour, oil, salt"})
    assert corrected.status_code == 201 and "phosphate_additive" not in corrected.json()["flags"]


def test_a_label_without_serving_weight_asks_for_it(vc):
    ready(vc)
    answer = {**LABEL_ANSWER, "serving_g": None, "product_name": None}
    with attach(vc.app, FakeProvider([chat(answer)])):
        data = photo(vc, "/api/vision/label").json()
    assert data["needs"] == ["name", "serving_g"] and data["draft"]["serving_g"] is None


def test_the_dry_run_shows_the_request_without_the_photo_and_sends_nothing(vc):
    ready(vc)
    provider = FakeProvider()
    with attach(vc.app, provider):
        r = photo(vc, "/api/vision/label", dry_run="true")
    data = r.json()
    assert r.status_code == 200 and data["dry_run"] is True and data["destination"] == "https://api.openai.com/v1/chat/completions"
    part = next(p for p in data["body"]["messages"][1]["content"] if p["type"] == "image_url")
    assert part["image_url"]["url"].startswith("data:image/jpeg;base64,[") and part["image_url"]["url"].endswith(" base64 characters]")
    checked = check_jpeg(LABEL_JPG, max_bytes=4 << 20)
    assert data["image_bytes"] == len(checked.data) and data["images"][0]["image_sha256"] == checked.sha256
    assert data["headers"]["Authorization"] == "Bearer [your key, not shown]" and KEY not in json.dumps(data)
    assert provider.requests == [] and usage_rows(vc) == 0 and vc.get("/api/ai/audit").json()["events"] == []


# --------------------------------------------------------------------------- #
# Switches, consent, quota, failures
# --------------------------------------------------------------------------- #


def test_photo_features_need_a_vision_model(tmp_path, foods_json):
    with TestClient(create_app(settings_for(tmp_path, foods_json, vision_model=None)), base_url=HTTPS_URL) as c:
        sign_in(c)
        enable(c, **{"ai.vision_plate_enabled": True})
        ready(c)
        status = c.get("/api/ai/status").json()
        assert status["features"]["label"] is False and status["features"]["plate"] is False
        assert status["features"]["next_meal"] is True
        provider = FakeProvider()
        with attach(c.app, provider):
            r = photo(c, "/api/vision/label")
        assert r.status_code == 503 and r.json()["reason"] == "vision_not_configured" and provider.requests == []


def test_plate_photos_are_off_by_default(vc):
    ready(vc)
    assert vc.get("/api/ai/status").json()["features"]["plate"] is False
    provider = FakeProvider()
    with attach(vc.app, provider):
        r = photo(vc, "/api/vision/plate", PLATE_JPG)
    assert r.status_code == 503 and r.json()["reason"] == "plate_disabled" and provider.requests == []
    enable(vc, **{"ai.vision_plate_enabled": True})
    assert vc.get("/api/ai/status").json()["features"]["plate"] is True


def test_photos_need_their_own_consent(vc):
    pid = ready(vc, purposes=("text",))
    provider = FakeProvider([chat(LABEL_ANSWER)])
    with attach(vc.app, provider):
        r = photo(vc, "/api/vision/label")
        assert r.status_code == 409 and r.json()["consent_required"] is True
        assert r.json()["consent"]["purpose"] == "photos" and r.json()["consent"]["host"] == "api.openai.com"
        assert provider.requests == []
        vc.post("/api/ai/consent", json={"provider_id": pid, "purpose": "photos"})
        assert photo(vc, "/api/vision/label").status_code == 200
    assert vc.delete(f"/api/ai/consent/{pid}", params={"purpose": "photos"}).status_code == 204
    with attach(vc.app, FakeProvider()):
        assert photo(vc, "/api/vision/label").status_code == 409  # withdrawn: asked again


def test_photos_count_toward_the_shared_daily_limit(vc):
    enable(vc, **{"ai.shared_daily_limit": 1})
    ready(vc)
    provider = FakeProvider([chat(LABEL_ANSWER)])
    with attach(vc.app, provider):
        assert photo(vc, "/api/vision/label").status_code == 200
        r = photo(vc, "/api/vision/label")
    assert r.status_code == 429 and r.json()["reason"] == "quota_exhausted" and int(r.headers["Retry-After"]) >= 60
    assert provider.calls == 1 and usage_rows(vc) == 1


def test_an_upstream_failure_is_a_502_with_a_coarse_reason(vc):
    ready(vc)
    secret_body = {"error": {"message": "internal detail that must not be echoed"}}
    provider = FakeProvider([{"status": 500, "body": secret_body}, {"status": 503, "body": secret_body}])
    with attach(vc.app, provider):
        r = photo(vc, "/api/vision/label")
    assert r.status_code == 502 and r.json()["reason"] == "http_5xx" and r.json()["audit_id"]
    assert "internal detail" not in r.text and provider.calls == 2  # one retry, then the error
    event = vc.get("/api/ai/audit").json()["events"][0]
    assert event["status"] == "error:http_5xx"


def test_a_model_answer_outside_the_schema_is_repaired_once_then_refused(vc):
    ready(vc)
    bad = {**LABEL_ANSWER, "per_serving": {**LABEL_ANSWER["per_serving"], "sodium_mg": -5}}
    provider = FakeProvider([chat(bad), chat(bad)])
    with attach(vc.app, provider):
        r = photo(vc, "/api/vision/label")
    assert r.status_code == 502 and r.json()["reason"] == "schema" and provider.calls == 2
    repair = provider.bodies()[1]["messages"][-1]["content"]
    assert repair.startswith("Your previous reply was not valid") and "-5" not in repair  # the input is not echoed


def test_not_a_label_is_a_plain_answer(vc):
    ready(vc)
    answer = {**LABEL_ANSWER, "status": "not_a_label"}
    with attach(vc.app, FakeProvider([chat(answer)])):
        data = photo(vc, "/api/vision/label").json()
    assert data["status"] == "not_a_label" and data["draft"] is None


# --------------------------------------------------------------------------- #
# Plate photos
# --------------------------------------------------------------------------- #


def test_the_plate_checklist_offers_the_persons_own_foods_only(vc):
    enable(vc, **{"ai.vision_plate_enabled": True})
    sam = add_user(vc)
    r = sam.post("/api/foods", json={"name": "Green beans, Sam's garden", "serving_desc": "1/2 cup (60 g)", "serving_g": 60,
                                     "nutrients": {"potassium_mg": 120}})
    assert r.status_code == 201
    ready(vc)
    with attach(vc.app, FakeProvider([chat(PLATE_ANSWER)])):
        r = photo(vc, "/api/vision/plate", PLATE_JPG)
    data = r.json()
    assert r.status_code == 200 and data["status"] == "ok" and data["banner"].startswith("AI estimate from a photo")
    assert "do not dose insulin" in data["banner"]
    apple, beans = data["items"]
    assert apple["ticked"] is True and beans["ticked"] is False  # low confidence starts unticked
    assert apple["candidates"][0]["food"]["name"] == "Apple, raw, with skin" and "nutrients" in apple["candidates"][0]["food"]
    assert apple["candidates"][0]["servings"] == 0.5 and apple["portion_text"] == "about 91 g"  # 91 g of a 182 g serving
    assert beans["candidates"] == []
    assert "Sam's garden" not in json.dumps(data)  # another person's custom food is never offered
    for item in data["items"]:
        for cand in item["candidates"]:
            assert cand["servings"] is None or 0.25 <= cand["servings"] <= 20
    assert vc.get("/api/log", params={"date": "2026-10-05"}).json()["entries"] == []  # nothing logged without a tap


def test_one_persons_photo_activity_is_not_anothers(vc):
    sam = add_user(vc)
    ready(vc)
    with attach(vc.app, FakeProvider([chat(LABEL_ANSWER)])):
        assert photo(vc, "/api/vision/label").status_code == 200
    assert sam.get("/api/ai/audit").json()["events"] == []
    assert len(vc.get("/api/ai/audit").json()["events"]) == 1


# --------------------------------------------------------------------------- #
# Hermes: the agent switch and a tool check before every photo (§9 A1, note 03 B10)
# --------------------------------------------------------------------------- #


def test_hermes_photos_need_the_agent_switch_and_a_tool_check_every_time(tmp_path, foods_json):
    settings = settings_for(tmp_path, foods_json, private_hosts=("host.containers.internal:8643",))
    with TestClient(create_app(settings), base_url=HTTPS_URL) as c:
        sign_in(c)
        enable(c)
        r = c.post("/api/admin/ai-providers", json={"preset": "hermes", "model": "kidney", "vision_model": "kidney",
                                                    "api_key": "hermes-key-0123456789abcdefgh"})
        assert r.status_code == 201, r.text
        pid = r.json()["id"]
        c.put("/api/profile", json={"targets": TARGETS})
        c.patch("/api/me/ai", json={"opt_in": True, "provider": f"shared:{pid}"})
        assert c.post("/api/ai/consent", json={"provider_id": pid, "purpose": "photos"}).status_code == 200
        toolsets = [{"name": "core", "enabled": False, "configured": True, "tools": ["terminal", "read_file"]}]
        provider = FakeProvider(route=lambda req: {"status": 200, "body": toolsets} if req.url.path.endswith("/toolsets")
                                else chat(LABEL_ANSWER), address="169.254.1.2")
        with attach(c.app, provider):
            r = photo(c, "/api/vision/label")
            assert r.status_code == 503 and r.json()["reason"] == "agent_not_allowed" and provider.requests == []
            assert c.get("/api/ai/status").json()["features"]["label"] is False
            enable(c, **{"ai.vision_allow_agent": True})
            assert photo(c, "/api/vision/label").status_code == 200
            assert photo(c, "/api/vision/label").status_code == 200
        paths = [q.url.path for q in provider.requests]
        assert paths == ["/v1/toolsets", "/v1/chat/completions"] * 2  # checked before every photo, even within 5 minutes
        body = provider.bodies()[0]
        assert "response_format" not in body and "RESPONSE SCHEMA" in body["messages"][1]["content"][0]["text"]  # prompt-only JSON
        toolsets[0]["enabled"] = True
        with attach(c.app, provider):
            r = photo(c, "/api/vision/label")
        assert r.status_code == 503 and r.json()["reason"] == "hermes_tools" and provider.calls == 2
        view = c.get("/api/admin/ai-providers").json()["providers"]
        assert next(p for p in view if p["id"] == pid)["disabled_reason"] == "hermes_tools"


# --------------------------------------------------------------------------- #
# Memory: refusals that need no photo are answered before the body is read
# --------------------------------------------------------------------------- #


def raw_post(client: TestClient, path: str, body: bytes, *, chunk: int = 1024, stall_s: float = 0.0) -> tuple[int, dict[str, Any], int]:
    """POST ``body`` straight into the ASGI app, in chunks pulled one ``receive()`` at a time, on the
    TestClient's own event loop. Returns (status, JSON answer, bytes the app pulled). ``stall_s``
    makes every chunk arrive that much later (a slow upload). The TestClient reads a body before the
    app runs, so it cannot show whether a route read it; this can."""
    import asyncio

    pieces = [body[i:i + chunk] for i in range(0, len(body), chunk)] or [b""]
    pulled = 0
    status = 0
    out = bytearray()

    async def receive() -> dict[str, Any]:
        nonlocal pulled
        if not pieces:
            await asyncio.sleep(3600)  # the client is still connected but sends nothing more
        if stall_s:
            await asyncio.sleep(stall_s)
        piece = pieces.pop(0)
        pulled += len(piece)
        return {"type": "http.request", "body": piece, "more_body": bool(pieces)}

    async def send(message: dict[str, Any]) -> None:
        nonlocal status
        if message["type"] == "http.response.start":
            status = message["status"]
        elif message["type"] == "http.response.body":
            out.extend(message.get("body", b""))

    cookie = "; ".join(f"{k}={v}" for k, v in client.cookies.items())
    headers = [(b"host", b"localhost"), (b"content-type", b"image/jpeg"), (b"content-length", str(len(body)).encode()),
               (b"x-requested-with", b"kidney-health"), (b"cookie", cookie.encode())]
    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "POST", "scheme": "https",
             "path": path, "raw_path": path.encode(), "query_string": b"", "root_path": "", "headers": headers,
             "client": ("127.0.0.1", 50123), "server": ("localhost", 443)}

    async def call() -> None:
        await client.app(scope, receive, send)

    client.portal.call(call)
    return status, json.loads(bytes(out) or b"{}"), pulled


def test_a_second_photo_from_the_same_person_is_refused_before_its_body_is_read(vc):
    ready(vc)
    me = vc.get("/api/me").json()["id"]
    gate = vc.app.state.ai.gate
    provider = FakeProvider([chat(LABEL_ANSWER)])
    with attach(vc.app, provider):
        gate.enter(me)  # the person's first photo is still being read or answered
        try:
            for path in ("/api/vision/label", "/api/vision/plate"):
                if path.endswith("plate"):
                    enable(vc, **{"ai.vision_plate_enabled": True})
                status, data, pulled = raw_post(vc, path, LABEL_JPG)
                assert (status, data["reason"], pulled) == (429, "busy_person", 0), data
        finally:
            gate.leave(me)
        status, data, pulled = raw_post(vc, "/api/vision/label", LABEL_JPG)  # the slot is free again
    assert status == 200 and data["status"] == "ok" and pulled == len(LABEL_JPG)
    assert provider.calls == 1 and usage_rows(vc) == 1 and gate.active == 0


def test_a_full_server_refuses_photos_before_their_bodies_are_read(vc):
    ready(vc)
    gate = vc.app.state.ai.gate
    for other in (-101, -102):  # ai.max_concurrency is 2: two other calls are running
        gate.enter(other)
    try:
        with attach(vc.app, FakeProvider()):
            status, data, pulled = raw_post(vc, "/api/vision/label", LABEL_JPG)
        assert (status, data["reason"], pulled) == (429, "busy_server", 0)
    finally:
        gate.leave(-101)
        gate.leave(-102)


def test_photos_without_consent_are_refused_before_their_bodies_are_read(vc):
    ready(vc, purposes=("text",))  # opted in, agreed to text only
    provider = FakeProvider()
    with attach(vc.app, provider):
        status, data, pulled = raw_post(vc, "/api/vision/label", LABEL_JPG)
    assert (status, data["consent_required"], pulled) == (409, True, 0)
    assert provider.requests == [] and vc.app.state.ai.gate.active == 0


def test_a_busy_hermes_person_gets_no_tool_check(tmp_path, foods_json):
    """The Hermes tool check runs inside the person's slot: a burst of photos makes at most one check."""
    settings = settings_for(tmp_path, foods_json, private_hosts=("host.containers.internal:8643",))
    with TestClient(create_app(settings), base_url=HTTPS_URL) as c:
        sign_in(c)
        enable(c, **{"ai.vision_allow_agent": True})
        pid = c.post("/api/admin/ai-providers", json={"preset": "hermes", "model": "kidney", "vision_model": "kidney",
                                                      "api_key": "hermes-key-0123456789abcdefgh"}).json()["id"]
        c.put("/api/profile", json={"targets": TARGETS})
        c.patch("/api/me/ai", json={"opt_in": True, "provider": f"shared:{pid}"})
        for purpose in ("photos", "text"):
            assert c.post("/api/ai/consent", json={"provider_id": pid, "purpose": purpose}).status_code == 200
        toolsets = [{"name": "core", "enabled": False, "configured": True, "tools": ["terminal"]}]
        provider = FakeProvider(route=lambda req: {"status": 200, "body": toolsets} if req.url.path.endswith("/toolsets")
                                else chat(LABEL_ANSWER), address="169.254.1.2")
        me = c.get("/api/me").json()["id"]
        c.app.state.ai.gate.enter(me)
        try:
            with attach(c.app, provider):
                status, data, pulled = raw_post(c, "/api/vision/label", LABEL_JPG)
        finally:
            c.app.state.ai.gate.leave(me)
        assert (status, data["reason"], pulled) == (429, "busy_person", 0) and provider.requests == []
        # The text features take the same order: slot first, then the tool check.
        c.app.state.ai.gate.enter(me)
        try:
            with attach(c.app, provider):
                r = c.post("/api/ai/next-meal", json={"meal": "dinner", "date": "2026-10-05"})
        finally:
            c.app.state.ai.gate.leave(me)
        assert r.status_code == 429 and r.json()["reason"] == "busy_person" and provider.requests == []


def test_a_slow_upload_times_out_and_frees_the_slot(vc, monkeypatch):
    from app import vision

    ready(vc)
    monkeypatch.setattr(vision, "PHOTO_READ_TIMEOUT_S", 0.2)
    provider = FakeProvider()
    with attach(vc.app, provider):
        status, data, pulled = raw_post(vc, "/api/vision/label", LABEL_JPG, chunk=512, stall_s=0.1)
    assert (status, data["reason"]) == (408, "upload_timeout") and 0 < pulled < len(LABEL_JPG)
    assert "faster connection" in data["detail"]
    assert provider.requests == [] and usage_rows(vc) == 0 and vc.app.state.ai.gate.active == 0


def test_a_truncated_upload_is_checked_as_received(vc):
    """A body shorter than its Content-Length (a client that gives up) is judged on what arrived."""
    ready(vc)
    with attach(vc.app, FakeProvider()):
        status, data, pulled = raw_post(vc, "/api/vision/label", LABEL_JPG[:4000])
    assert (status, data["reason"], pulled) == (422, "truncated", 4000) and vc.app.state.ai.gate.active == 0
