"""Open Food Facts: request, client, pacing, trimming and mapping (note 03 R3, §6 item 7, §9 B3–B6).

Every test runs on the recorded fixtures in tests/fixtures/off/ (or on products built in the test);
none touches the network.
"""
from __future__ import annotations

import gzip
import json
import random

import httpx2
import pytest

from app import off
from app.gtin import normalize
from barcode_support import Replay, load, product

DIET_COKE = normalize("0049000028911", "ean_13")
KRAFT = normalize("0021000658831", "ean_13")
LAYS = normalize("0028400090858", "ean_13")
NUTELLA = normalize("3017624010701", "ean_13")


def mapped(name: str, gtin14: str) -> off.Mapped:
    return off.map_product(product(name), gtin14)


def rounded(m: off.Mapped) -> dict[str, float | None]:
    return {k: (None if v is None else round(v, 1)) for k, v in m.nutrients.items()}


# --------------------------------------------------------------------------- #
# The request
# --------------------------------------------------------------------------- #


def test_request_url_uses_api_3_4_and_the_exact_fields_list() -> None:
    url = off.product_url("https://world.openfoodfacts.org", "0049000028911")
    assert url == (
        "https://world.openfoodfacts.org/api/v3.4/product/0049000028911?fields=code,product_name,product_name_en,"
        "generic_name,brands,quantity,serving_size,serving_quantity,serving_quantity_unit,nutrition_data_per,"
        "nutrition_data_prepared_per,no_nutrition_data,nutriments,ingredients_text,ingredients_text_en,additives_tags,"
        "categories_tags,countries_tags,nova_group,lang,last_modified_t"
    )
    assert off.OFF_API_VERSION == "3.4"


def test_newer_api_versions_also_ask_for_the_nutrition_object() -> None:
    assert off.product_url(off.DEFAULT_BASE_URL, "3017624010701", "3.6").endswith(",last_modified_t,nutrition")
    assert "nutrition," not in off.product_url(off.DEFAULT_BASE_URL, "3017624010701", "3.4")


def test_the_fixtures_were_recorded_with_the_apps_own_request() -> None:
    for name, code in (("diet_coke_v3.4", "0049000028911"), ("nutella_v3.6", "3017624010701")):
        doc = load("off", name)
        version = "3.6" if name.endswith("3.6") else "3.4"
        assert doc["request"]["url"] == off.product_url(off.DEFAULT_BASE_URL, code, version)


@pytest.mark.parametrize("code", ["", "12a", "../x", "0049000028911?x=1", "٤٩"])
def test_product_url_refuses_anything_but_digits(code: str) -> None:
    with pytest.raises(ValueError):
        off.product_url(off.DEFAULT_BASE_URL, code)


def test_user_agent_identifies_the_app() -> None:
    assert off.user_agent("0.3.0", "https://github.com/ksullivan86/kidney-health") == \
        "KidneyHealth/0.3.0 (https://github.com/ksullivan86/kidney-health)"


def test_product_page_is_built_from_a_constant() -> None:
    assert off.product_page(DIET_COKE) == "https://world.openfoodfacts.org/product/0049000028911"
    assert off.product_page(normalize("96385074", "ean_8")) == "https://world.openfoodfacts.org/product/96385074"


@pytest.mark.parametrize("raw, ok", [
    ("https://world.openfoodfacts.org", True), ("https://world.openfoodfacts.net/", True), ("https://off.lan:8443", True),
    ("http://localhost:8080", True), ("http://127.0.0.1", True),
    ("http://world.openfoodfacts.org", False), ("ftp://x.org", False), ("https://user:pw@x.org", False),
    ("https://x.org/api", False), ("https://x.org/?a=1", False), ("https://x.org/#f", False), ("world.openfoodfacts.org", False),
    ("https://x.org:99999", False), ("", False),
])
def test_base_url_validation(raw: str, ok: bool) -> None:
    if ok:
        assert off.check_base_url(raw) == raw.rstrip("/")
    else:
        with pytest.raises(ValueError):
            off.check_base_url(raw)


# --------------------------------------------------------------------------- #
# The client (MockTransport replaying the recordings)
# --------------------------------------------------------------------------- #


def client_with(transport: httpx2.BaseTransport, sleeps: list[float] | None = None) -> off.OffClient:
    return off.OffClient(off.DEFAULT_BASE_URL, "0.3.0", off.DEFAULT_CONTACT, transport=transport,
                         sleep=(sleeps.append if sleeps is not None else (lambda s: None)))


def test_fetch_found_sends_the_identifying_headers() -> None:
    replay = Replay(load("off", "diet_coke_v3.4"))
    result = client_with(replay).fetch("0049000028911")
    assert result.status == "found" and result.product["product_name"] == "Diet Coke Soft Drink"
    request = replay.requests[0]
    assert request.headers["User-Agent"] == f"KidneyHealth/0.3.0 ({off.DEFAULT_CONTACT})"
    assert request.headers["Accept"] == "application/json"
    assert request.headers["Accept-Encoding"] == "gzip"


def test_fetch_404_is_not_found_and_never_retried() -> None:
    replay = Replay(load("off", "not_found_v3.4"))
    sleeps: list[float] = []
    assert client_with(replay, sleeps).fetch("0099999999990").status == "not_found"
    assert len(replay.requests) == 1 and sleeps == []


def test_503_is_retried_once_after_two_seconds() -> None:
    answers = [httpx2.Response(503, text="busy"), None]
    doc = load("off", "lays_classic_v3.4")

    def handler(request: httpx2.Request) -> httpx2.Response:
        answer = answers.pop(0)
        return answer if answer is not None else httpx2.Response(200, json=doc["body"])

    sleeps: list[float] = []
    transport = httpx2.MockTransport(handler)
    assert client_with(transport, sleeps).fetch("0028400090858").status == "found"
    assert sleeps == [2.0]


def test_503_twice_is_an_error() -> None:
    calls: list[int] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        calls.append(1)
        return httpx2.Response(503, text="busy")

    with pytest.raises(off.OffError) as info:
        client_with(httpx2.MockTransport(handler)).fetch("0028400090858")
    assert info.value.kind == "http_503" and len(calls) == 2


@pytest.mark.parametrize("response, kind", [
    (httpx2.Response(429, text="slow down"), "rate_limited"),
    (httpx2.Response(302, headers={"Location": "https://evil.example/"}), "redirect"),
    (httpx2.Response(500, text="oops"), "http_500"),
    (httpx2.Response(200, headers={"Content-Type": "text/html"}, text="<html>Page temporarily unavailable</html>"), "invalid_response"),
    (httpx2.Response(200, headers={"Content-Type": "application/json"}, content=b"{not json"), "invalid_response"),
    (httpx2.Response(200, json=[1, 2, 3]), "invalid_response"),
    (httpx2.Response(200, json={"status": "success"}), "invalid_response"),
    (httpx2.Response(200, json={"status": "failure", "result": {"id": "something_else"}}), "invalid_response"),
])
def test_upstream_failures_are_coarse_errors(response: httpx2.Response, kind: str) -> None:
    with pytest.raises(off.OffError) as info:
        client_with(httpx2.MockTransport(lambda r: response)).fetch("0028400090858")
    assert info.value.kind == kind
    assert "evil.example" not in str(info.value) and "oops" not in str(info.value)  # bodies are never echoed


def test_redirects_are_not_followed() -> None:
    seen: list[str] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(str(request.url))
        return httpx2.Response(301, headers={"Location": "http://169.254.169.254/latest/meta-data/"})

    with pytest.raises(off.OffError):
        client_with(httpx2.MockTransport(handler)).fetch("0028400090858")
    assert len(seen) == 1


def test_response_cap_counts_decoded_bytes() -> None:
    """A small gzip body that inflates beyond 1 MiB is refused (note 03 §9 B6)."""
    big = json.dumps({"status": "success", "product": {"product_name": "x" * (2 * 1024 * 1024)}}).encode()
    compressed = gzip.compress(big)
    assert len(compressed) < 50_000

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, headers={"Content-Type": "application/json", "Content-Encoding": "gzip"}, content=compressed)

    with pytest.raises(off.OffError) as info:
        client_with(httpx2.MockTransport(handler)).fetch("0028400090858")
    assert info.value.kind == "too_large"


def test_declared_oversize_is_refused_before_reading() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, headers={"Content-Type": "application/json", "Content-Length": str(5 * 1024 * 1024)},
                               content=b"{}")

    with pytest.raises(off.OffError) as info:
        client_with(httpx2.MockTransport(handler)).fetch("0028400090858")
    assert info.value.kind == "too_large"


@pytest.mark.parametrize("exc, kind", [
    (httpx2.ReadTimeout("slow"), "timeout"), (httpx2.ConnectError("refused"), "connect_failed"),
])
def test_network_errors(exc: Exception, kind: str) -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise exc

    with pytest.raises(off.OffError) as info:
        client_with(httpx2.MockTransport(handler)).fetch("0028400090858")
    assert info.value.kind == kind


def test_blocked_address_is_reported_without_details() -> None:
    from app import egress

    transport = egress.CheckedTransport(resolver=lambda host, port: ["169.254.169.254"], use_env_proxy=False)
    with pytest.raises(off.OffError) as info:
        client_with(transport).fetch("0028400090858")
    assert info.value.kind == "blocked_address"
    assert "169.254" not in str(info.value)


# --------------------------------------------------------------------------- #
# Pacing
# --------------------------------------------------------------------------- #


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


def test_bucket_refuses_the_eleventh_call_in_a_minute() -> None:
    clock = Clock()
    bucket = off.TokenBucket(10, clock)
    assert [bucket.take() for _ in range(10)] == [0] * 10
    wait = bucket.take()
    assert wait == 6  # one token every 6 s at 10 per minute
    clock.t += 6
    assert bucket.take() == 0
    assert bucket.take() > 0


def test_bucket_refills_but_never_beyond_its_rate() -> None:
    clock = Clock()
    bucket = off.TokenBucket(10, clock)
    clock.t += 3600
    assert sum(1 for _ in range(30) if bucket.take() == 0) == 10


def test_bucket_pause_after_an_upstream_429() -> None:
    clock = Clock()
    bucket = off.TokenBucket(10, clock)
    bucket.pause(60)
    assert bucket.take() == 60
    clock.t += 61
    assert bucket.take() == 0


def test_bucket_rate_limits_and_changes() -> None:
    clock = Clock()
    with pytest.raises(ValueError):
        off.TokenBucket(16, clock)
    with pytest.raises(ValueError):
        off.TokenBucket(0, clock)
    bucket = off.TokenBucket(15, clock)
    bucket.set_rate(2)
    assert [bucket.take() for _ in range(3)][:2] == [0, 0]


# --------------------------------------------------------------------------- #
# Mapping the recorded products
# --------------------------------------------------------------------------- #


def test_diet_coke() -> None:
    m = mapped("diet_coke_v3.4", DIET_COKE)
    assert (m.status, m.name, m.brand, m.category) == ("found", "Diet Coke Soft Drink", "Coke", "Beverages")
    assert (m.serving_g, m.serving_desc) == (354.9, "1 can (354.9 mL)")
    n = rounded(m)
    assert n["sodium_mg"] == 40.1 and n["calories_kcal"] == 0 and n["carbs_g"] == 0
    assert n["potassium_mg"] is None and n["phosphorus_mg"] is None  # unknown, never 0
    assert n["fluid_ml"] == 354.9
    assert m.flags == ["phosphate_additive", "counts_as_fluid", "processed"]
    assert m.additives == ["e338"]
    assert m.quality == ["crowd_sourced", "ml_as_g", "potassium_unknown", "phosphorus_unknown"]
    assert "hypo_treatment" not in m.flags and "high_gi" not in m.flags


def test_kraft_prepared_values_only() -> None:
    m = mapped("kraft_mac_cheese_v3.4", KRAFT)
    # The weight is the box's dry serving, the values are the prepared serving: the text says so, and the
    # log takes this food in servings only (foods.weight_known; review C7).
    assert m.serving_desc == "1 serving (70.874 g) as sold, prepared" and m.serving_g == pytest.approx(70.874)
    assert "prepared_values" in m.quality
    assert "logged in servings, not grams" in off.QUALITY_MESSAGES["prepared_values"]
    n = rounded(m)
    assert (n["calories_kcal"], n["carbs_g"], n["protein_g"], n["sodium_mg"], n["potassium_mg"]) == (350, 50, 10, 710, 370)
    assert n["phosphorus_mg"] is None
    assert "phosphate_additive" in m.flags and "e451" in m.additives  # from en:e451 and "SODIUM TRIPHOSPHATE"
    assert "energy_mismatch" in m.quality  # the recorded prepared fat (1 g) cannot give 350 kcal


def test_lays_us_label_with_potassium() -> None:
    m = mapped("lays_classic_v3.4", LAYS)
    n = rounded(m)
    assert (m.serving_g, n["potassium_mg"], n["sodium_mg"], n["carbs_g"], n["calories_kcal"]) == (28.3, 350, 140, 15, 160)
    assert m.us_label and "carbs_available" not in m.quality and "potassium_unknown" not in m.quality
    assert "energy_mismatch" not in m.quality
    # The recorded categories wrongly include en:dairies (community data); the ordered map takes it first.
    assert m.category == "Dairy & Alternatives"


def test_nutella_eu_label() -> None:
    m = mapped("nutella_v3.4", NUTELLA)
    assert (m.serving_g, m.serving_desc) == (100.0, "100 g")
    assert rounded(m)["sodium_mg"] == 43.0
    for code in ("no_serving", "carbs_available", "sodium_from_salt", "potassium_unknown", "phosphorus_unknown"):
        assert code in m.quality


def test_salt_only_label_derives_sodium() -> None:
    p = product("nutella_v3.4")
    p["nutriments"] = {k: v for k, v in p["nutriments"].items() if not k.startswith("sodium")}
    m = off.map_product(p, NUTELLA)
    assert rounded(m)["sodium_mg"] == 43.0 and "sodium_from_salt" in m.quality


def test_api_3_6_shape_maps_like_3_4() -> None:
    """The second parser: API 3.6 empties `nutriments` and moves the values to `nutrition`."""
    v36 = product("nutella_v3.6")
    assert v36["nutriments"] == {}
    assert rounded(off.map_product(v36, NUTELLA)) == rounded(mapped("nutella_v3.4", NUTELLA))


def test_recorded_3_4_responses_still_have_flat_nutriments() -> None:
    """The guard for note 03 risk "OFF changes the schema again": if a re-recorded 3.4 response comes back
    with empty `nutriments`, this fails and says to move to the 3.5+ parser."""
    for name in ("diet_coke_v3.4", "kraft_mac_cheese_v3.4", "lays_classic_v3.4", "nutella_v3.4"):
        assert product(name)["nutriments"], f"{name}: API 3.4 returned empty nutriments; switch OFF_API_VERSION"


def test_parse_nutrition_v35_units_and_shapes() -> None:
    p = {"nutrition": {"aggregated_set": {"per": "serving", "preparation": "prepared", "nutrients": {
        "energy-kcal": {"value": 200, "unit": "kcal"}, "energy": {"value": 836, "unit": "kJ"},
        "potassium": {"value": 350, "unit": "mg"}, "calcium": {"value": 120000, "unit": "µg"},
        "proteins": {"value": "7", "unit": "g"}, "fat": {"value": 1, "unit": "furlong"}, "vitamin-c": {"value": 1, "unit": "mg"},
    }}}}
    assert off.parse_nutrition_v35(p) == {
        "energy-kcal_prepared_serving": 200, "energy_prepared_serving": 836, "potassium_prepared_serving": 0.35,
        "calcium_prepared_serving": 0.12, "proteins_prepared_serving": 7.0,
    }
    assert off.parse_nutrition_v35({}) == {} and off.parse_nutrition_v35({"nutrition": {"aggregated_set": []}}) == {}


def test_found_without_nutrition_facts() -> None:
    m = mapped("lays_1oz_v3.4", normalize("028400421584", "upc_a"))
    assert m.status == "no_nutrition" and m.name == "Product 0028400421584"
    assert "no_nutrition" in m.quality


def test_empty_nutriments_and_no_nutrition_object_is_no_nutrition() -> None:
    p = {"product_name": "Mystery", "nutriments": {}}
    assert off.map_product(p, LAYS).status == "no_nutrition"
    p = {"product_name": "Unlabelled", "no_nutrition_data": "on", "nutriments": {"energy-kcal_100g": 100}}
    assert off.map_product(p, LAYS).status == "no_nutrition"


# --------------------------------------------------------------------------- #
# Rules on built products
# --------------------------------------------------------------------------- #


def base(**nutriments: float) -> dict:
    return {"product_name": "Test", "serving_quantity": 50, "serving_quantity_unit": "g", "serving_size": "50 g",
            "nutrition_data_per": "100g", "countries_tags": ["en:united-states"], "nutriments": nutriments}


def test_absent_is_none_never_zero() -> None:
    m = off.map_product(base(**{"energy-kcal_100g": 100, "proteins_100g": 5}), LAYS)
    assert m.nutrients["potassium_mg"] is None and m.nutrients["fat_g"] is None and m.nutrients["sodium_mg"] is None


def test_per_serving_label_values_are_used_directly() -> None:
    p = base(**{"energy-kcal_100g": 333.3, "energy-kcal_serving": 170, "carbohydrates_100g": 40, "carbohydrates_serving": 21})
    p["nutrition_data_per"] = "serving"
    m = off.map_product(p, LAYS)
    assert m.nutrients["calories_kcal"] == 170 and m.nutrients["carbs_g"] == 21


def test_energy_from_kilojoules() -> None:
    m = off.map_product(base(**{"energy-kj_100g": 418.4}), LAYS)
    assert m.nutrients["calories_kcal"] == pytest.approx(50.0)


def test_total_carbohydrate_is_preferred() -> None:
    m = off.map_product(base(**{"carbohydrates_100g": 20, "carbohydrates-total_100g": 24}), LAYS)
    assert m.nutrients["carbs_g"] == 12.0


def test_carbs_available_note_only_for_non_us_labels() -> None:
    p = base(**{"carbohydrates_100g": 20})
    p["countries_tags"] = ["en:germany"]
    assert "carbs_available" in off.map_product(p, LAYS).quality
    p["countries_tags"] = ["en:canada"]
    assert "carbs_available" not in off.map_product(p, LAYS).quality


@pytest.mark.parametrize("key, off_name, value, dropped", [
    ("sodium_mg", "sodium_100g", 45.0, True), ("sodium_mg", "sodium_100g", 39.0, False),
    ("potassium_mg", "potassium_100g", 61.0, True), ("potassium_mg", "potassium_100g", 52.4, False),
    ("potassium_mg", "potassium_100g", 11.0, False), ("phosphorus_mg", "phosphorus_100g", 33.0, True),
    ("phosphorus_mg", "phosphorus_100g", 9.0, False), ("phosphorus_mg", "phosphorus_100g", 4.0, False),
    ("protein_g", "proteins_100g", 120.0, True), ("calories_kcal", "energy-kcal_100g", 1200.0, True),
    ("fat_g", "fat_100g", -3.0, True),
])
def test_implausible_values_are_dropped(key: str, off_name: str, value: float, dropped: bool) -> None:
    m = off.map_product(base(**{"energy-kcal_100g": 100, off_name: value}), LAYS)
    assert (m.nutrients[key] is None) is dropped
    assert (f"implausible:{key}" in m.quality) is dropped


def test_salt_itself_may_have_40_g_sodium() -> None:
    p = base(**{"sodium_100g": 39.0, "salt_100g": 97.5, "energy-kcal_100g": 0})
    p["nutriments"]["sodium_100g"] = 41.0
    p["categories_tags"] = ["en:condiments", "en:salts"]
    assert off.map_product(p, LAYS).nutrients["sodium_mg"] == pytest.approx(20500.0)


def test_energy_mismatch() -> None:
    ok = off.map_product(base(**{"energy-kcal_100g": 400, "carbohydrates_100g": 50, "proteins_100g": 10, "fat_g": 0,
                                 "fat_100g": 16}), LAYS)
    assert "energy_mismatch" not in ok.quality
    bad = off.map_product(base(**{"energy-kcal_100g": 100, "carbohydrates_100g": 50, "proteins_100g": 10, "fat_100g": 16}), LAYS)
    assert "energy_mismatch" in bad.quality
    small = off.map_product(base(**{"energy-kcal_100g": 10, "carbohydrates_100g": 10, "proteins_100g": 0, "fat_100g": 0}), LAYS)
    assert "energy_mismatch" not in small.quality  # 30 kcal apart: under the 40 kcal floor


def test_no_serving_uses_100_g_or_100_ml() -> None:
    p = {"product_name": "Juice", "nutriments": {"energy-kcal_100g": 45}, "categories_tags": ["en:beverages"]}
    m = off.map_product(p, LAYS)
    assert (m.serving_g, m.serving_desc, "no_serving" in m.quality) == (100.0, "100 mL", True)
    p["serving_quantity"], p["serving_quantity_unit"] = 0, "g"
    assert off.map_product(p, LAYS).serving_g == 100.0
    p["serving_quantity"], p["serving_quantity_unit"] = "250", "ml"
    assert off.map_product(p, LAYS).serving_g == 250.0  # parquet-style string
    p["serving_quantity"], p["serving_quantity_unit"] = 5_000_000, "g"
    assert off.map_product(p, LAYS).serving_g == 100.0  # impossible serving


@pytest.mark.parametrize("sugars, expected", [(5.0, True), (10.6, True), (4.9, False), (None, False)])
def test_high_gi_only_for_sweetened_beverages(sugars: float | None, expected: bool) -> None:
    p = base(**({"sugars_100g": sugars} if sugars is not None else {}))
    p["serving_quantity_unit"], p["serving_quantity"] = "ml", 355
    p["categories_tags"] = ["en:beverages", "en:sweetened-beverages"]
    assert ("high_gi" in off.map_product(p, LAYS).flags) is expected
    p["categories_tags"] = ["en:beverages"]
    assert "high_gi" not in off.map_product(p, LAYS).flags


def test_alcoholic_beverages_are_flagged_alcohol() -> None:
    """Meal guidance never suggests an alcoholic drink (delayed lows with insulin), so the mapping marks one."""
    p = base(**{"energy-kcal_100g": 43, "sugars_100g": 0})
    p["serving_quantity_unit"], p["serving_quantity"] = "ml", 330
    p["categories_tags"] = ["en:beverages", "en:alcoholic-beverages", "en:beers"]
    m = off.map_product(p, LAYS)
    assert "alcohol" in m.flags and "counts_as_fluid" in m.flags
    assert "hypo_treatment" not in m.flags
    p["categories_tags"] = ["en:beverages", "en:non-alcoholic-beverages", "en:alcohol-free-beers"]
    assert "alcohol" not in off.map_product(p, LAYS).flags


def test_processed_from_nova_4() -> None:
    p = base(**{"energy-kcal_100g": 100})
    p["nova_group"] = 4
    assert "processed" in off.map_product(p, LAYS).flags
    p["nova_group"] = 3
    assert "processed" not in off.map_product(p, LAYS).flags


def test_potassium_additive_from_the_ingredient_list() -> None:
    p = base(**{"energy-kcal_100g": 120, "sodium_100g": 0.9})
    p["ingredients_text_en"] = "turkey breast, water, potassium lactate, salt, sodium diacetate"
    m = off.map_product(p, LAYS)
    assert "potassium_additive" in m.flags and m.nutrients["potassium_mg"] is None
    assert "e326" in m.additives and "potassium lactate (E326)" in (m.kidney_notes or "")


def test_salt_substitute_is_avoid_ckd() -> None:
    p = {"product_name": "NoSalt Original", "ingredients_text": "Potassium chloride, potassium bitartrate, adipic acid",
         "nutriments": {"potassium_100g": 49.0, "energy-kcal_100g": 0}}
    m = off.map_product(p, LAYS)
    assert m.flags[:3] == ["potassium_additive", "avoid_ckd"] or m.flags[:2] == ["potassium_additive", "avoid_ckd"]
    assert m.kidney_notes and m.kidney_notes.startswith("AVOID with kidney disease")
    # 49 g/100 g is what potassium chloride holds (52.4 % K): kept, so the warning has its number (review C9).
    assert m.nutrients["potassium_mg"] == pytest.approx(49000.0) and "implausible:potassium_mg" not in m.quality


def test_category_map_is_ordered() -> None:
    assert off._category(["en:snacks", "en:beverages"]) == "Beverages"
    assert off._category(["en:pizzas"]) == "Prepared & Fast Food"
    assert off._category(["en:eggs"]) == "Meat, Poultry & Eggs"
    assert off._category(["en:fishes"]) == "Fish & Seafood"
    assert off._category(["en:unknown"]) is None and off._category([]) is None


def test_never_hypo_treatment_or_low_potassium_fruit_on_random_products() -> None:
    rnd = random.Random(20261006)
    tags = ["en:beverages", "en:sweetened-beverages", "en:fruits", "en:snacks", "en:salts", "en:candies"]
    for _ in range(300):
        p = {
            "product_name": rnd.choice(["Glucose tablets", "Apple juice", "Banana", "x"]),
            "serving_quantity": rnd.choice([None, 4, 125, 355, "abc"]), "serving_quantity_unit": rnd.choice(["g", "ml", None]),
            "nova_group": rnd.choice([1, 2, 3, 4, None]),
            "categories_tags": rnd.sample(tags, rnd.randint(0, 3)),
            "nutriments": {k: rnd.choice([0, 1.5, 15, 60, None]) for k in ("sugars_100g", "carbohydrates_100g", "energy-kcal_100g")},
        }
        flags = off.map_product(p, LAYS).flags
        assert "hypo_treatment" not in flags and "low_potassium_fruit" not in flags


# --------------------------------------------------------------------------- #
# Untrusted text (§9 B3, B4)
# --------------------------------------------------------------------------- #


def test_text_is_cleaned_and_capped() -> None:
    p = {"product_name": "Diet​ Co‮ke‬ " + "x" * 400, "brands": "  Ac­me ,Other",
         "serving_size": "1 can\x00 (355 mL)" + " pad" * 40, "serving_quantity": 355, "serving_quantity_unit": "ml",
         "ingredients_text": "water,​ sodium phos­phate\n" + "y" * 5000, "nutriments": {"energy-kcal_100g": 1}}
    m = off.map_product(p, DIET_COKE)
    assert m.name.startswith("Diet Coke x") and len(m.name) == 200
    assert m.brand == "Acme"
    assert m.serving_desc.startswith("1 can (355 mL)") and len(m.serving_desc) <= 60
    assert m.ingredients_text and len(m.ingredients_text) <= 4000 and "​" not in m.ingredients_text
    assert "phosphate_additive" in m.flags  # the soft hyphen did not hide the word


def test_trimmed_payload_keeps_no_urls_or_unknown_fields() -> None:
    p = dict(product("diet_coke_v3.4"))
    p["image_url"] = "https://images.openfoodfacts.org/x.jpg"
    p["url"] = "javascript:alert(1)"
    p["nutriments"] = dict(p["nutriments"], **{"vitamin-c_100g": 1, "energy-kcal_100g": "12", "fat_100g": float("inf")})
    trimmed = off.trim_product(p)
    assert set(trimmed) <= set(off.FIELDS)
    assert "image_url" not in json.dumps(trimmed) and "javascript" not in json.dumps(trimmed)
    assert "vitamin-c_100g" not in trimmed["nutriments"]
    assert trimmed["nutriments"]["energy-kcal_100g"] == 12.0 and "fat_100g" not in trimmed["nutriments"]
    # Mapping the trimmed copy gives the same food (the cache can be re-mapped without the network).
    assert off.map_product(trimmed, DIET_COKE) == off.map_product(p, DIET_COKE)
    original = product("diet_coke_v3.4")
    assert off.map_product(off.trim_product(original), DIET_COKE) == off.map_product(original, DIET_COKE)


def test_quality_items() -> None:
    items = off.quality_items(["crowd_sourced", "implausible:sodium_mg", "filled_from_usda:potassium_mg", "from_the_future"])
    assert [i["code"] for i in items] == ["crowd_sourced", "implausible", "filled_from_usda"]
    assert items[1]["message"].endswith(": sodium.") and items[2]["message"].endswith(": potassium.")


# --------------------------------------------------------------------------- #
# Prompt injection from product data (§9.3)
# --------------------------------------------------------------------------- #


def test_product_text_never_reaches_an_ai_prompt_unmarked() -> None:
    """Open Food Facts names are untrusted (anyone can edit them) and stored ingredient lists never go
    into an AI prompt (note 03 §9.3, note 04 §9 A2/A3). The guidance bridge is the only door from food
    data to the optional AI layer, and prompts are built in the AI layer's prompt modules (note 04 R13:
    ``app/ai/prompts.py``); both are checked. Other AI modules may name ``ingredients_text``: the
    read-label answer carries the ingredients the model read from a photo (model output, not input)."""
    from pathlib import Path

    from app.guidance import ai_bridge

    assert "off" in ai_bridge.UNTRUSTED_SOURCES and "custom" in ai_bridge.UNTRUSTED_SOURCES
    root = Path(__file__).resolve().parents[1] / "app"
    prompt_code = [root / "guidance" / "ai_bridge.py", *sorted((root / "ai").glob("**/*prompt*.py"))]
    for path in prompt_code:
        text = path.read_text(encoding="utf-8")
        assert "ingredients_text" not in text, f"{path.relative_to(root.parent)} must not put ingredient lists into prompts"


# --------------------------------------------------------------------------- #
# v0.3.0 review: potassium salts keep their number; liquids count as fluid; per-serving labels need a weight
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("name, ingredients, k_100g, serving_g, serving_text, mg", [
    # Label figures: NoSalt 640 mg per 1/4 tsp (1.4 g); Morton Lite Salt 350 mg per 1/4 tsp (1.4 g);
    # cream of tartar USDA SR 16,500 mg/100 g (1 tsp = 3 g, 495 mg).
    ("NoSalt Original", "Potassium chloride, potassium bitartrate, adipic acid", 45.7, 1.4, "1/4 tsp (1.4 g)", 640),
    ("Lite Salt", "Salt, potassium chloride, calcium silicate, dextrose, potassium iodide", 25.0, 1.4, "1/4 tsp (1.4 g)", 350),
    ("Cream of tartar", "Cream of tartar", 16.5, 3.0, "1 tsp (3 g)", 495),
    ("Baking soda substitute", "Potassium bicarbonate", 39.0, 2.5, "1/2 tsp (2.5 g)", 975),
    ("Herb seasoning blend", "Potassium chloride, onion, garlic, herbs", 30.0, 1.5, "1/4 tsp (1.5 g)", 450),
])
def test_potassium_salts_keep_their_potassium_and_warn_high(name, ingredients, k_100g, serving_g, serving_text, mg) -> None:
    from app.nutrients import food_warnings, kidney_rating

    p = {"product_name": name, "ingredients_text": ingredients, "serving_quantity": serving_g, "serving_quantity_unit": "g",
         "serving_size": serving_text, "nutrition_data_per": "100g", "nutriments": {"potassium_100g": k_100g, "energy-kcal_100g": 0}}
    m = off.map_product(p, LAYS)
    assert m.nutrients["potassium_mg"] == pytest.approx(mg, rel=0.01)
    assert not any(q.startswith("implausible") for q in m.quality) and "potassium_unknown" not in m.quality
    warnings = food_warnings(m.nutrients, m.flags, m.kidney_notes)
    k_levels = [w["level"] for w in warnings if w["nutrient"] == "potassium_mg"]
    assert "high" in k_levels and kidney_rating(warnings) == "red"


def test_values_above_what_any_salt_can_hold_are_still_dropped() -> None:
    m = off.map_product(base(**{"energy-kcal_100g": 0, "potassium_100g": 75.0, "phosphorus_100g": 40.0}), LAYS)
    assert m.nutrients["potassium_mg"] is None and m.nutrients["phosphorus_mg"] is None
    assert {"implausible:potassium_mg", "implausible:phosphorus_mg"} <= set(m.quality)


@pytest.mark.parametrize("product, liquid", [
    ({"nutrition_data_per": "100ml", "categories_tags": ["en:beverages", "en:juices"]}, True),  # EU juice, no serving
    ({"nutrition_data_per": "100g", "categories_tags": ["en:beverages"]}, True),
    ({"nutrition_data_per": "100ml", "categories_tags": []}, True),  # a soup or drink labelled per 100 mL
    ({"nutrition_data_per": "100g", "categories_tags": ["en:beverages"], "serving_quantity": 250, "serving_quantity_unit": "g",
      "serving_size": "1 bottle (250 g)"}, True),
    ({"nutrition_data_per": "100g", "categories_tags": ["en:beverages", "en:dried-products-to-be-rehydrated",
                                                         "en:dehydrated-beverages"]}, False),  # a drink powder
    ({"nutrition_data_per": "100g", "categories_tags": ["en:snacks"]}, False),
])
def test_a_liquid_counts_as_fluid_by_the_same_test_as_its_serving_text(product, liquid) -> None:
    p = {"product_name": "Orange juice", "nutriments": {"energy-kcal_100g": 45, "carbohydrates_100g": 10}, **product}
    m = off.map_product(p, NUTELLA)
    assert ("counts_as_fluid" in m.flags) is liquid
    serving = float(product.get("serving_quantity", 100))
    assert m.nutrients["fluid_ml"] == (serving if liquid else 0.0)
    if "serving_quantity" not in product:
        assert m.serving_desc == ("100 mL" if liquid else "100 g")


def test_a_v35_label_per_100ml_counts_as_fluid() -> None:
    p = {"product_name": "Apple juice", "nutriments": {},
         "nutrition": {"aggregated_set": {"per": "100ml", "preparation": "as_sold",
                                          "nutrients": {"energy-kcal": {"value": 46, "unit": "kcal"},
                                                        "carbohydrates": {"value": 11, "unit": "g"}}}}}
    m = off.map_product(p, NUTELLA)
    assert "counts_as_fluid" in m.flags and m.nutrients["fluid_ml"] == 100.0 and m.serving_desc == "100 mL"


def test_per_serving_values_without_a_serving_weight_are_not_stored_as_per_100_g() -> None:
    """Review L6: "1 bar" values must never become "per 100 g" (a 45 g bar would get 45 % of them)."""
    p = {"product_name": "Protein bar", "serving_size": "1 bar", "nutrition_data_per": "serving",
         "nutriments": {"energy-kcal_serving": 200, "proteins_serving": 20, "potassium_serving": 350, "phosphorus_serving": 200}}
    m = off.map_product(p, LAYS)
    assert m.status == "no_nutrition" and "serving_weight_unknown" in m.quality and "no_nutrition" in m.quality
    assert "no serving weight is listed" in off.QUALITY_MESSAGES["serving_weight_unknown"]
    # The API 3.5+ shape: an aggregated set per serving without a serving quantity.
    v35 = {"product_name": "Protein bar", "nutriments": {},
           "nutrition": {"aggregated_set": {"per": "serving", "preparation": "as_sold",
                                            "nutrients": {"energy-kcal": {"value": 200, "unit": "kcal"},
                                                          "proteins": {"value": 20, "unit": "g"}}}}}
    assert off.map_product(v35, LAYS).status == "no_nutrition"
    # With a serving weight the per-serving values are used as they are (3.4 and 3.5+).
    v35["serving_quantity"], v35["serving_quantity_unit"] = 45, "g"
    m = off.map_product(v35, LAYS)
    assert m.status == "found" and m.serving_g == 45 and m.nutrients["calories_kcal"] == 200
