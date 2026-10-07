"""USDA FoodData Central Branded Foods by barcode (note 03 R4, F3; §6 item 8; §9 B6).

The fixtures in tests/fixtures/usda/ are replayed through ``httpx2.MockTransport``; see their README
for where they come from.
"""
from __future__ import annotations

import gzip
import json

import httpx2
import pytest

from app import foods as foods_module
from app.foods import UsdaError, map_usda_record, usda_find_by_gtin
from app.gtin import normalize
from barcode_support import Replay, load

LAYS_1OZ = normalize("028400421584", "upc_a")
LAYS_1125 = normalize("0028400161909", "ean_13")
DIET_COKE = normalize("049000028911", "upc_a")


@pytest.fixture
def replay(monkeypatch: pytest.MonkeyPatch) -> Replay:
    names = ["search_028400421584", "search_028400161909", "search_0028400161909", "search_00028400161909",
             "search_049000028911", "search_0049000028911", "search_00049000028911",
             "food_1633665", "food_1458203", "food_2742723"]
    transport = Replay(*(load("usda", n) for n in names))
    monkeypatch.setattr(foods_module, "usda_client",
                        lambda: httpx2.Client(base_url=foods_module.USDA_BASE_URL, transport=transport))
    return transport


def test_first_form_hit(replay: Replay) -> None:
    fdc_id, record = usda_find_by_gtin(LAYS_1OZ, "k" * 40, guard="usda:test")
    assert fdc_id == 1633665 and "LAY'S" in record["description"]
    assert replay.paths() == ["/fdc/v1/foods/search", "/fdc/v1/food/1633665"]
    assert replay.requests[0].url.params["query"] == "028400421584"
    assert replay.requests[0].url.params["dataType"] == "Branded"
    assert all(r.headers["X-Api-Key"] == "k" * 40 for r in replay.requests)
    assert all("k" * 40 not in str(r.url) for r in replay.requests)  # the key never travels in a URL


def test_only_the_fourteen_digit_form_hits(replay: Replay) -> None:
    """FDC stores this product as a GTIN-14; the 12- and 13-digit forms find nothing (at most 3 searches)."""
    fdc_id, _ = usda_find_by_gtin(LAYS_1125, "k" * 40, guard="usda:test")
    assert fdc_id == 1458203
    assert [r.url.params.get("query") for r in replay.requests[:3]] == ["028400161909", "0028400161909", "00028400161909"]
    assert len(replay.requests) == 4


def test_no_hit_in_any_form(replay: Replay, monkeypatch: pytest.MonkeyPatch) -> None:
    empty = {"totalHits": 0, "foods": []}
    transport = httpx2.MockTransport(lambda r: httpx2.Response(200, json=empty))
    calls: list[int] = []

    def client() -> httpx2.Client:
        calls.append(1)
        return httpx2.Client(base_url=foods_module.USDA_BASE_URL, transport=transport)

    monkeypatch.setattr(foods_module, "usda_client", client)
    assert usda_find_by_gtin(DIET_COKE, "k" * 40, guard="usda:test") is None
    assert len(calls) == 3


def test_a_result_with_another_gtin_is_never_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    near = {"totalHits": 1, "foods": [{"fdcId": 1, "gtinUpc": "049000028928", "description": "Coke Zero"},
                                       {"fdcId": 2, "gtinUpc": None}, {"fdcId": "x", "gtinUpc": "00049000028911"}]}
    seen: list[str] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request.url.path)
        return httpx2.Response(200, json=near)

    monkeypatch.setattr(foods_module, "usda_client",
                        lambda: httpx2.Client(base_url=foods_module.USDA_BASE_URL, transport=httpx2.MockTransport(handler)))
    assert usda_find_by_gtin(DIET_COKE, "k" * 40, guard="usda:test") is None
    assert seen == ["/fdc/v1/foods/search"] * 3


def test_rate_limited_key(monkeypatch: pytest.MonkeyPatch) -> None:
    doc = load("usda", "rate_limited")
    transport = httpx2.MockTransport(lambda r: httpx2.Response(429, json=doc["body"], headers={"Retry-After": "24080"}))
    monkeypatch.setattr(foods_module, "usda_client", lambda: httpx2.Client(base_url=foods_module.USDA_BASE_URL, transport=transport))
    with pytest.raises(UsdaError) as info:
        usda_find_by_gtin(DIET_COKE, "DEMO_KEY", guard="usda:test")
    assert info.value.status == 429


@pytest.mark.parametrize("response, status", [
    (httpx2.Response(403, json={"error": "API_KEY_INVALID"}), 503),
    (httpx2.Response(500, text="oops"), 502),
    (httpx2.Response(200, headers={"Content-Type": "text/html"}, text="<html>"), 502),
    (httpx2.Response(200, headers={"Content-Type": "application/json"}, content=b"{oops"), 502),
    (httpx2.Response(301, headers={"Location": "http://169.254.169.254/"}), 502),
])
def test_upstream_errors(monkeypatch: pytest.MonkeyPatch, response: httpx2.Response, status: int) -> None:
    transport = httpx2.MockTransport(lambda r: response)
    monkeypatch.setattr(foods_module, "usda_client", lambda: httpx2.Client(base_url=foods_module.USDA_BASE_URL, transport=transport))
    with pytest.raises(UsdaError) as info:
        usda_find_by_gtin(DIET_COKE, "k" * 40, guard="usda:test")
    assert info.value.status == status


def test_record_size_cap_counts_decoded_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    bomb = gzip.compress(json.dumps({"foods": [{"description": "x" * (3 * 1024 * 1024)}]}).encode())

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, headers={"Content-Type": "application/json", "Content-Encoding": "gzip"}, content=bomb)

    monkeypatch.setattr(foods_module, "usda_client",
                        lambda: httpx2.Client(base_url=foods_module.USDA_BASE_URL, transport=httpx2.MockTransport(handler)))
    with pytest.raises(UsdaError) as info:
        usda_find_by_gtin(DIET_COKE, "k" * 40, guard="usda:test")
    assert info.value.status == 502 and "too large" in info.value.detail


# --------------------------------------------------------------------------- #
# Mapping branded records
# --------------------------------------------------------------------------- #


def record(fdc_id: int) -> dict:
    return load("usda", f"food_{fdc_id}")["body"]


def test_label_nutrients_are_the_per_serving_values() -> None:
    m = map_usda_record(record(1633665), 1633665)
    n = m.kwargs["nutrients"]
    assert (m.kwargs["serving_g"], m.kwargs["serving_desc"]) == (28.0, "1 ONZ (28 g)")
    assert (n["calories_kcal"], n["sodium_mg"], n["potassium_mg"], n["carbs_g"], n["fat_g"]) == (160, 170, 350, 15, 10)
    assert n["phosphorus_mg"] is None  # labelNutrients has no phosphorus (note 03 F3)
    assert m.gtin14 == LAYS_1OZ and m.quality == ["phosphorus_unknown"]
    assert m.kwargs["kidney_notes"] == "USDA record does not report phosphorus; treat it as unknown, not zero."


def test_postassium_spelling_is_accepted() -> None:
    data = record(1633665)
    labels = dict(data["labelNutrients"])
    labels["postassium"] = labels.pop("potassium")
    data["labelNutrients"] = labels
    assert map_usda_record(data, 1633665).kwargs["nutrients"]["potassium_mg"] == 350


def test_without_label_nutrients_food_nutrients_are_scaled() -> None:
    data = record(1633665)
    data.pop("labelNutrients")
    n = map_usda_record(data, 1633665).kwargs["nutrients"]
    assert n["potassium_mg"] == pytest.approx(1250 * 0.28, rel=0.02)  # 1,250 mg per 100 g in the record


def test_diet_coke_branded() -> None:
    m = map_usda_record(record(2742723), 2742723)
    assert m.kwargs["serving_desc"] == "1 Can (355 mL)" and "ml_as_g" in m.quality
    assert m.kwargs["flags"] == ["phosphate_additive", "counts_as_fluid"]
    assert m.kwargs["nutrients"]["fluid_ml"] == 355 and m.kwargs["nutrients"]["potassium_mg"] == 0
    assert m.additives == ["e338"]


@pytest.mark.parametrize(("data", "expected"), [
    ({"description": "Lager", "foodNutrients": [{"nutrient": {"number": "221"}, "amount": 3.9}]}, True),
    ({"description": "Lager", "foodNutrients": [{"nutrientId": 1018, "value": 0.4}]}, True),
    ({"description": "Alcohol-free lager", "foodNutrients": [{"nutrient": {"number": "221"}, "amount": 0.3}]}, False),
    ({"description": "Alcoholic beverage, wine, table, red", "foodNutrients": []}, True),
    ({"description": "Grape juice", "foodNutrients": [{"nutrient": {"number": "221"}, "amount": float("nan")}]}, False),
    ({"description": "Grape juice", "foodNutrients": [{"nutrient": {"number": "306"}, "amount": 104}]}, False),
])
def test_alcohol_flag_from_ethanol_or_the_description(data: dict, expected: bool) -> None:
    """Meal guidance never suggests an alcoholic drink, so imported or scanned USDA records carry the flag."""
    m = map_usda_record(data, 1)
    assert ("alcohol" in m.kwargs["flags"]) is expected
    assert "alcohol" not in m.kwargs["nutrients"]  # not a nutrient of the app


def test_branded_text_is_cleaned() -> None:
    data = record(1633665)
    data["description"] = "LAY'S​‮ CHIPS" + "!" * 400
    data["ingredients"] = "POTATOES, POTASSIUM­ CHLORIDE"
    m = map_usda_record(data, 1633665)
    assert m.kwargs["name"].startswith("LAY'S CHIPS") and len(m.kwargs["name"]) == 200
    assert "potassium_additive" in m.kwargs["flags"]


@pytest.mark.parametrize("bad", [{"servingSize": "abc", "servingSizeUnit": "g"}, {"servingSize": float("inf"), "servingSizeUnit": "g"},
                                 {"servingSize": -5, "servingSizeUnit": "g"}, {"foodPortions": [None, {"gramWeight": "x"}, {"gramWeight": 1e9}]}])
def test_malformed_serving_falls_back_to_100_g(bad: dict) -> None:
    data = {"description": "Thing", "foodNutrients": [{"nutrient": {"number": "306"}, "amount": 200}], **bad}
    m = map_usda_record(data, 1)
    assert m.kwargs["serving_g"] == 100.0 and m.kwargs["nutrients"]["potassium_mg"] == 200
