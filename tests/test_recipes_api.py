"""A saved meal that is a recipe (note 16 §5.1, §5.2, schema step 21): ``servings_made``, ``steps`` and ``source_url`` through
``/api/meals``, the per-serving figures with their unknown counts, the PUT rules, the checks on each field, and the round trip through
the person's own export."""
from __future__ import annotations

import io
import json
import zipfile

import pytest

from app.nutrients import NUTRIENT_KEYS

from conftest import DAY, find_food


def recipe(client, **extra):
    food = find_food(client, "banana")
    body = {"name": "Banana pudding", "items": [{"food_id": food["id"], "servings": 4}], **extra}
    r = client.post("/api/meals", json=body)
    assert r.status_code == 201, r.text
    return r.json(), food


def test_a_recipe_keeps_its_fields_and_gives_one_serving(client):
    meal, food = recipe(client, servings_made=4, steps=["  Mash the bananas. ", "", "Chill for an hour."],
                        source_url="https://example.com/r?id=7")
    assert (meal["servings_made"], meal["source_url"]) == (4, "https://example.com/r?id=7")
    assert meal["steps"] == ["Mash the bananas.", "Chill for an hour."]  # trimmed, empty steps dropped
    for key in NUTRIENT_KEYS:
        whole, one = meal["totals"][key], meal["per_serving"][key]
        if food["nutrients"].get(key) is None:
            assert one is None and meal["unknown"][key] == 1  # never 0
        else:
            assert one == pytest.approx(whole / 4, abs=0.6), key
    assert client.get(f"/api/meals/{meal['id']}").json() == meal


def test_a_plain_saved_meal_is_one_serving(client):
    meal, _ = recipe(client)
    assert (meal["servings_made"], meal["steps"], meal["source_url"]) == (None, None, None)
    assert meal["per_serving"]["potassium_mg"] == meal["totals"]["potassium_mg"]


@pytest.mark.parametrize("scale, expected", [(None, 4), (0.5, 2), (0.25, 1)])
def test_recipe_apply_api_keeps_the_whole_pot_scale_contract(client, scale, expected):
    meal, food = recipe(client, servings_made=4)
    body = {"date": DAY, "meal": "dinner", "status": "planned"}
    if scale is not None:
        body["scale"] = scale
    response = client.post(f"/api/meals/{meal['id']}/apply", json=body)
    assert response.status_code == 201, response.text
    entries = response.json()["entries"]
    assert len(entries) == 1 and entries[0]["food_id"] == food["id"]
    assert entries[0]["servings"] == expected


def test_put_keeps_what_it_leaves_out_and_null_clears(client):
    meal, food = recipe(client, servings_made=4, steps=["Mash."], source_url="https://example.com/a")
    items = [{"food_id": food["id"], "servings": 4}]
    kept = client.put(f"/api/meals/{meal['id']}", json={"name": "Renamed", "items": items}).json()
    assert (kept["servings_made"], kept["steps"], kept["source_url"]) == (4, ["Mash."], "https://example.com/a")
    cleared = client.put(f"/api/meals/{meal['id']}", json={"name": "Renamed", "items": items, "servings_made": None, "steps": None,
                                                         "source_url": None}).json()
    assert (cleared["servings_made"], cleared["steps"], cleared["source_url"]) == (None, None, None)


@pytest.mark.parametrize("extra", [
    {"servings_made": 0}, {"servings_made": 101}, {"servings_made": "many"},
    {"steps": ["x" * 501]}, {"steps": ["ok"] * 21}, {"steps": ["tab\tinside"]}, {"steps": "Mash."},
    {"source_url": "javascript:alert(1)"}, {"source_url": "https://user:pw@example.com/"}, {"source_url": "https://a.example/b c"},
    {"source_url": "ftp://example.com/r"}, {"source_url": "https://example.com/" + "a" * 900},
])
def test_each_field_is_checked(client, extra):
    food = find_food(client, "banana")
    r = client.post("/api/meals", json={"name": "Bad", "items": [{"food_id": food["id"], "servings": 1}], **extra})
    assert r.status_code == 400, (extra, r.text)
    assert client.get("/api/meals").json()["meals"] == []


def test_an_empty_link_is_no_link(client):
    meal, _ = recipe(client, servings_made=2, source_url="")
    assert meal["source_url"] is None


def test_someone_elses_recipe_is_404(two_clients):
    admin, sam = two_clients
    meal, _ = recipe(admin, servings_made=4)
    assert sam.get(f"/api/meals/{meal['id']}").status_code == 404
    assert sam.put(f"/api/meals/{meal['id']}", json={"name": "Mine", "items": [{"food_id": 1, "servings": 1}], "servings_made": 1}).status_code == 404


def test_the_export_carries_a_recipe_and_the_import_brings_it_back(client):
    meal, _ = recipe(client, servings_made=4, steps=["Mash."], source_url="https://example.com/a")
    r = client.get("/api/me/export.zip")
    assert r.status_code == 200, r.text
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        doc = json.loads(z.read("export.json"))
    [exported] = doc["meal_templates"]
    assert (exported["servings_made"], exported["steps"], exported["source_url"]) == (4, ["Mash."], "https://example.com/a")
    assert client.delete(f"/api/meals/{meal['id']}").status_code == 204
    r = client.post("/api/me/import", content=json.dumps(doc), headers={"content-type": "application/json"})
    assert r.status_code == 200, r.text
    [back] = client.get("/api/meals").json()["meals"]
    assert (back["servings_made"], back["steps"], back["source_url"]) == (4, ["Mash."], "https://example.com/a")
    assert back["per_serving"] == exported["per_serving"]
