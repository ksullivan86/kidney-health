"""Import of the person's own export.json (``POST /api/me/import``, app/data_import.py; note 07 §4.14).

The file is untrusted input, so most of these tests send files that were edited or made up: extra fields,
NaN, a wrong version, secrets in the sections the import must ignore, ids that collide with other people's rows,
foods that do not exist. Whatever the file holds, nothing may be written unless the whole file is good, and
nothing of another person's may change.
"""
from __future__ import annotations

import copy
import io
import json
import sqlite3
import zipfile
from pathlib import Path
from typing import Any

import httpx2
import pytest

import app.foods as foods_module
from conftest import (ADMIN_PASSWORD, DAY, FIXTURE_FOODS, HTTPS_URL, TestClient, add_user, find_food, make_settings,
                      signed_in_client)

JSON = {"content-type": "application/json"}
SECOND_DAY = "2026-10-06"
GUIDANCE = {"enabled": True, "carb_tolerance_g": 15, "hypo_dose_g": 20, "exclude_categories": ["Sweets & Snacks"],
            "show_plan_builder": True, "show_insights": False, "ai_enrich": False}
# Tables a person's rows live in; "what is stored" below compares them as a whole.
DATA_TABLES = ("log_entries", "foods", "meal_templates", "lab_results", "food_preferences", "user_food_links",
               "user_profiles", "user_settings", "audit_log")


# --------------------------------------------------------------------------- helpers


def export_doc(client: TestClient) -> dict[str, Any]:
    r = client.get("/api/me/export.zip")
    assert r.status_code == 200, r.text
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        return json.loads(z.read("export.json"))


def post_import(client: TestClient, doc: Any, *, dry_run: bool = False, merge: bool = False,
                replace_profile: bool = False, raw: bytes | str | None = None, **kwargs: Any) -> httpx2.Response:
    params = {k: 1 for k, on in (("dry_run", dry_run), ("merge", merge), ("replace_profile", replace_profile)) if on}
    body = raw if raw is not None else json.dumps(doc)
    headers = {**JSON, **kwargs.pop("headers", {})}
    return client.post("/api/me/import", params=params, content=body, headers=headers, **kwargs)


def reset_limits(client: TestClient) -> None:
    """Many refused files in one test would use up the hourly allowance; start over."""
    from app.auth.ratelimit import RateLimits

    client.app.state.auth.limits = RateLimits()


def stored(client: TestClient) -> dict[str, Any]:
    """Everything the import writes to, as a whole (rows, id counters, the food revision)."""
    conn = sqlite3.connect(client.app.state.settings.db_path)
    try:
        out: dict[str, Any] = {t: conn.execute(f"SELECT * FROM {t} ORDER BY 1, 2").fetchall() for t in DATA_TABLES}
        out["sequence"] = conn.execute("SELECT * FROM sqlite_sequence ORDER BY name").fetchall()
        out["foods_rev"] = conn.execute("SELECT value FROM meta WHERE key = 'foods_rev'").fetchall()
        return out
    finally:
        conn.close()


def rows_of(client: TestClient, user_id: int) -> dict[str, Any]:
    """One person's rows (what another person's import must never change)."""
    conn = sqlite3.connect(client.app.state.settings.db_path)
    try:
        out: dict[str, Any] = {}
        for table, column in (("log_entries", "user_id"), ("foods", "owner_user_id"), ("meal_templates", "user_id"),
                              ("lab_results", "user_id"), ("food_preferences", "user_id"), ("user_food_links", "user_id"),
                              ("user_profiles", "user_id"), ("user_settings", "user_id")):
            out[table] = conn.execute(f"SELECT * FROM {table} WHERE {column} = ? ORDER BY 1, 2", (user_id,)).fetchall()
        return out
    finally:
        conn.close()


def whole_database(client: TestClient) -> str:
    conn = sqlite3.connect(client.app.state.settings.db_path)
    try:
        return "\n".join(conn.iterdump())
    finally:
        conn.close()


def scrub(value: Any, drop: tuple[str, ...] = ("id", "food_id")) -> Any:
    """The same data without server-assigned ids, which differ between servers."""
    if isinstance(value, dict):
        return {k: scrub(v, drop) for k, v in value.items() if k not in drop}
    if isinstance(value, list):
        return [scrub(v, drop) for v in value]
    return value


def populate(client: TestClient) -> dict[str, Any]:
    """Person A's data: own foods (one flagged as a low treatment), eaten and planned entries on two days (one by
    weight, one marked as treating a low), a saved meal, labs in two units, a profile with targets, guidance
    settings, a "Not for me" food and a theme."""
    banana = find_food(client, "banana")
    tablets = find_food(client, "glucose tablets")
    soup = client.post("/api/foods", json={"name": "My soup", "brand": "Home", "serving_desc": "1 bowl", "serving_g": 300,
                                           "nutrients": {"potassium_mg": 400, "phosphorus_mg": 120, "carbs_g": 20},
                                           "flags": ["processed"], "kidney_notes": "Watch the salt."}).json()
    gel = client.post("/api/foods", json={"name": "Home gel", "serving_desc": "1 pouch", "serving_g": 32,
                                          "nutrients": {"carbs_g": 22, "sugar_g": 20}, "flags": ["hypo_treatment"]}).json()
    old = client.post("/api/foods", json={"name": "Retired stew", "serving_desc": "1 bowl", "serving_g": 250,
                                          "nutrients": {"potassium_mg": 700}}).json()
    entries = [
        client.post("/api/log", json={"date": DAY, "meal": "breakfast", "food_id": banana["id"], "servings": 1}),
        client.post("/api/log", json={"date": DAY, "meal": "lunch", "food_id": soup["id"], "servings": 1.5, "note": "with bread"}),
        client.post("/api/log", json={"date": DAY, "meal": "lunch", "food_id": soup["id"], "grams": 150}),
        client.post("/api/log", json={"date": DAY, "meal": "snack", "food_id": gel["id"], "servings": 1}),
        client.post("/api/log", json={"date": DAY, "meal": "snack", "food_id": tablets["id"], "servings": 2, "purpose": "none"}),
        client.post("/api/log", json={"date": SECOND_DAY, "meal": "dinner", "food_id": soup["id"], "status": "planned"}),
        client.post("/api/log", json={"date": SECOND_DAY, "meal": "dinner", "food_id": old["id"]}),
    ]
    assert all(e.status_code == 201 for e in entries), [e.text for e in entries]
    assert client.delete(f"/api/foods/{old['id']}").status_code == 204  # used, so hidden (still in the export)
    meal = client.post("/api/meals", json={"name": "Usual lunch", "note": "weekdays", "meal_hint": "lunch",
                                           "items": [{"food_id": soup["id"], "servings": 1}, {"food_id": banana["id"], "servings": 2}]})
    assert meal.status_code == 201, meal.text
    assert client.post("/api/labs", json={"analyte": "potassium", "value": 4.8, "unit": "mmol/L", "taken_on": "2026-10-01"}).status_code == 201
    assert client.post("/api/labs", json={"analyte": "creatinine", "value": 110, "unit": "µmol/L", "taken_on": "2026-09-20", "note": "fasting"}).status_code == 201
    assert client.put("/api/profile", json={"name": "Sam", "weight_kg": 70, "ckd_stage": "4", "dialysis_days": [0, 3],
                                            "targets": {"potassium_mg": 2500, "protein_g": {"min": 50, "max": 60}}}).status_code == 200
    assert client.patch("/api/me/settings", json={"guidance": GUIDANCE, "ui.theme": "dark"}).status_code == 200
    assert client.put(f"/api/guidance/not-for-me/{soup['id']}").status_code == 200
    assert client.put(f"/api/guidance/not-for-me/{banana['id']}").status_code == 200
    return {"banana": banana, "tablets": tablets, "soup": soup, "gel": gel, "old": old}


@pytest.fixture
def fresh(tmp_path, foods_json):
    """A second, empty server with the same built-in foods (person B's)."""
    with signed_in_client(make_settings(tmp_path / "second", foods_json)) as c:
        yield c


def custom_foods(client: TestClient) -> list[dict[str, Any]]:
    return sorted((f for f in client.get("/api/foods", params={"q": ""}).json()["foods"] if f["source"] == "custom"),
                  key=lambda f: f["name"])


# --------------------------------------------------------------------------- round trip, dry run, all or nothing


def test_round_trip_into_a_fresh_server_matches(client, fresh):
    populate(client)
    doc = export_doc(client)
    assert [b["name"] for b in doc["builtin_foods"]] == ["Banana, raw", "Glucose tablets"]
    r = post_import(fresh, doc, replace_profile=True)
    assert r.status_code == 200, r.text
    answer = r.json()
    assert answer["imported"] is True and answer["dry_run"] is False and answer["blocked"] is None
    assert answer["counts"] == {"log_entries": 7, "custom_foods": 3, "shared_foods_kept_as_own": 0, "shared_foods_linked": 0,
                                "built_in_foods_matched": 2, "meal_templates": 1, "lab_results": 2, "symptoms": 0,
                                "food_preferences": 2, "profile": 1, "settings": 2}
    assert answer["skipped"]["total"] == 0 and answer["already_there"] == dict.fromkeys(answer["already_there"], 0)
    for day in (DAY, SECOND_DAY):
        assert scrub(fresh.get("/api/log", params={"date": day}).json()) == scrub(client.get("/api/log", params={"date": day}).json())
    assert scrub(fresh.get("/api/log/summary", params={"start": DAY, "end": SECOND_DAY}).json()) == \
        scrub(client.get("/api/log/summary", params={"start": DAY, "end": SECOND_DAY}).json())
    assert custom_foods(fresh) == [] or scrub(custom_foods(fresh)) == scrub(custom_foods(client))
    assert scrub(fresh.get("/api/meals").json()) == scrub(client.get("/api/meals").json())
    assert scrub(fresh.get("/api/labs").json()) == scrub(client.get("/api/labs").json())
    assert scrub(fresh.get("/api/guidance/not-for-me").json(), ("id", "food_id", "created_at")) == \
        scrub(client.get("/api/guidance/not-for-me").json(), ("id", "food_id", "created_at"))
    a_profile, b_profile = client.get("/api/profile").json(), fresh.get("/api/profile").json()
    for key in ("id", "updated_at"):
        a_profile.pop(key), b_profile.pop(key)
    assert b_profile == a_profile and b_profile["targets"]["protein_g"] == {"min": 50, "max": 60}
    mine, theirs = client.get("/api/me/settings").json()["settings"], fresh.get("/api/me/settings").json()["settings"]
    assert theirs["guidance"]["value"] == mine["guidance"]["value"] == GUIDANCE and theirs["ui.theme"]["value"] == "dark"
    # the low treatments stay low treatments, the one marked "none" stays a plain entry
    day = fresh.get("/api/log", params={"date": DAY}).json()["entries"]
    assert {e["food_name"]: e["purpose"] for e in day if e["meal"] == "snack"} == {"Home gel": "hypo", "Glucose tablets": None}
    # the hidden food came along as hidden, the grams entry kept its grams
    stew = next(e for e in fresh.get("/api/log", params={"date": SECOND_DAY}).json()["entries"] if e["food_name"] == "Retired stew")
    assert fresh.get(f"/api/foods/{stew['food_id']}").json()["hidden"] is True
    assert [e["grams"] for e in day if e["grams"] is not None] == [150]
    # and the import is on the activity list, counts only
    events = [e for e in fresh.get("/api/me/activity").json()["events"] if e["action"] == "data.imported"]
    assert len(events) == 1
    assert events[0]["details"] == {"log_entries": 7, "custom_foods": 3, "meal_templates": 1, "lab_results": 2,
                                    "symptoms": 0, "food_preferences": 2, "merge": False, "profile": True}


def test_a_dry_run_writes_nothing_and_says_what_would_happen(client, fresh):
    populate(client)
    doc = export_doc(client)
    before = stored(fresh)
    r = post_import(fresh, doc, dry_run=True, replace_profile=True)
    assert r.status_code == 200, r.text
    answer = r.json()
    assert answer["dry_run"] is True and answer["imported"] is False and answer["can_import"] is True
    assert answer["counts"]["log_entries"] == 7 and answer["counts"]["custom_foods"] == 3 and answer["counts"]["profile"] == 1
    assert answer["file"]["records"]["log_entries"] == 7 and "Add to my existing data" in answer["rule"]
    assert stored(fresh) == before  # not a row, not an id, not the food revision, no activity row
    # the settings read back during the dry run do not stay in the server's cache
    settings = fresh.get("/api/me/settings").json()["settings"]
    assert settings["guidance"]["source"] == "default" and settings["ui.theme"]["source"] == "default"
    assert fresh.get("/api/profile").json()["name"] == "" and fresh.get("/api/profile").json()["targets"] == {}
    # the real import then does exactly what the dry run said
    done = post_import(fresh, doc, replace_profile=True).json()
    assert done["counts"] == answer["counts"] and done["skipped"] == answer["skipped"]


def test_a_bad_record_in_the_middle_refuses_the_whole_file(client, fresh):
    populate(client)
    doc = export_doc(client)
    before = stored(fresh)
    cases = [
        (lambda d: d["log_entries"][3].__setitem__("servings", -2), "log_entries[3].servings"),
        (lambda d: d["log_entries"][4].__setitem__("date", "2026-02-30"), "log_entries[4].date"),
        (lambda d: d["log_entries"][2].__setitem__("meal", "brunch"), "log_entries[2].meal"),
        (lambda d: d["custom_foods"][1]["nutrients"].__setitem__("potassium_mg", -5), "custom_foods[1].nutrients"),
        (lambda d: d["custom_foods"][2].__setitem__("serving_g", 0), "custom_foods[2].serving_g"),
        (lambda d: d["meal_templates"][0]["items"][1].__setitem__("servings", 0), "meal_templates[0].items[1].servings"),
        (lambda d: d["lab_results"][1].__setitem__("entered_unit", "furlongs"), "lab_results[1]"),
        (lambda d: d["lab_results"][0].__setitem__("taken_on", "2999-01-01"), "lab_results[0]"),
        (lambda d: d["profile"].__setitem__("weight_kg", 9000), "profile.weight_kg"),
        (lambda d: d["profile"]["targets"].__setitem__("potassium_mg", -1), "profile.targets"),
        (lambda d: d["settings"]["guidance"].__setitem__("hypo_dose_g", 5000), "settings"),
        (lambda d: d["food_preferences"][1].__setitem__("preference", "love"), "food_preferences[1].preference"),
        (lambda d: d["log_entries"][5].__setitem__("created_at", "yesterday"), "log_entries[5].created_at"),
    ]
    for edit, where in cases:
        bad = copy.deepcopy(doc)
        edit(bad)
        reset_limits(fresh)
        for dry in (True, False):
            r = post_import(fresh, bad, dry_run=dry, replace_profile=True)
            assert r.status_code == 400, (where, r.text)
            assert where in r.json()["detail"], (where, r.json()["detail"])
    assert stored(fresh) == before
    r = post_import(fresh, doc, replace_profile=True)
    assert r.status_code == 200 and r.json()["counts"]["log_entries"] == 7


def test_a_failure_while_writing_leaves_nothing_behind(client, fresh, monkeypatch):
    populate(client)
    doc = export_doc(client)
    before = stored(fresh)
    import app.data_import as data_import

    def explode(*args: Any, **kwargs: Any) -> int:
        raise RuntimeError("disk on fire")

    monkeypatch.setattr(data_import, "insert_template", explode)  # entries and foods are written before the meals
    quiet = TestClient(fresh.app, raise_server_exceptions=False)
    quiet.cookies.update(fresh.cookies)
    r = post_import(quiet, doc, replace_profile=True)
    assert r.status_code == 500
    assert stored(fresh) == before
    monkeypatch.undo()
    assert post_import(fresh, doc, replace_profile=True).status_code == 200


# --------------------------------------------------------------------------- the file is untrusted


@pytest.mark.parametrize("edit, where", [
    (lambda d: d.__setitem__("sessions", [{"token": "x"}]), "sessions"),
    (lambda d: d.__setitem__("api_tokens", []), "api_tokens"),
    (lambda d: d["log_entries"][0].__setitem__("user_id", 1), "log_entries[0].user_id"),
    (lambda d: d["log_entries"][1].__setitem__("sql", "x"), "log_entries[1].sql"),
    (lambda d: d["custom_foods"][0].__setitem__("owner_user_id", 1), "custom_foods[0].owner_user_id"),
    (lambda d: d["custom_foods"][0]["nutrients"].__setitem__("magic_mg", 1), "custom_foods[0].nutrients"),
    (lambda d: d["meal_templates"][0].__setitem__("user_id", 2), "meal_templates[0].user_id"),
    (lambda d: d["meal_templates"][0]["items"][0].__setitem__("extra", 1), "meal_templates[0].items[0].extra"),
    (lambda d: d["lab_results"][0].__setitem__("user_id", 2), "lab_results[0].user_id"),
    (lambda d: d["profile"].__setitem__("is_admin", True), "profile.is_admin"),
    (lambda d: d["food_preferences"][0].__setitem__("user_id", 2), "food_preferences[0].user_id"),
    (lambda d: d["builtin_foods"][0].__setitem__("hidden", False), "builtin_foods[0].hidden"),
])
def test_extra_fields_are_refused_and_named(client, fresh, edit, where):
    populate(client)
    doc = export_doc(client)
    edit(doc)
    before = stored(fresh)
    r = post_import(fresh, doc, replace_profile=True)
    assert r.status_code == 400 and where in r.json()["detail"] and r.json()["kind"] == where.split("[")[0].split(".")[0]
    assert stored(fresh) == before


def test_a_linked_food_must_describe_itself_and_its_extra_fields_are_refused(client, fresh):
    doc = export_doc(client)
    doc["linked_foods"] = [{"id": 3, "name": "x", "source": "usda", "fdc_id": 1, "linked_at": None, "gtin": None, "role": "admin"}]
    assert "linked_foods[0].role" in post_import(fresh, doc).json()["detail"]


def test_only_this_format_and_version_are_read(client, fresh):
    populate(client)
    doc = export_doc(client)
    before = stored(fresh)
    for edit, text in [
        (lambda d: d.__setitem__("version", 2), "version 2"),
        (lambda d: d.__setitem__("version", 0), "version 0"),
        (lambda d: d.__setitem__("version", "1"), "version 1"),
        (lambda d: d.__setitem__("version", True), "version"),
        (lambda d: d.pop("version"), "version"),
        (lambda d: d.__setitem__("format", "someone-elses-export"), "format"),
        (lambda d: d.pop("format"), "format"),
    ]:
        bad = copy.deepcopy(doc)
        edit(bad)
        reset_limits(fresh)
        r = post_import(fresh, bad)
        assert r.status_code == 400 and text in r.json()["detail"], (text, r.text)
    reset_limits(fresh)
    for raw, text in [(b"", "empty"), (b"not json", "valid JSON"), (b"[1, 2]", "one JSON object"), (b"\xff\xfe\x00", "valid JSON"),
                      (b"[" * 5000 + b"]" * 5000, "nested too deeply"),
                      (b'{"format": ' + b"[" * 5000 + b"]" * 5000 + b"}", "nested too deeply"),
                      (b'{"a": ' + b"[" * 40 + b"]" * 40 + b"}", "nested too deeply"), (b'{"format": "kidney-health-export", "version": 1', "valid JSON")]:
        r = post_import(fresh, None, raw=raw)
        assert r.status_code == 400 and text in r.json()["detail"], (raw[:20], r.text)
    assert post_import(fresh, doc, headers={"content-type": "text/plain"}).status_code == 415
    assert stored(fresh) == before
    assert post_import(fresh, doc).status_code == 200


@pytest.mark.parametrize("literal", ["NaN", "Infinity", "-Infinity", "1e999", "-1e999"])
def test_numbers_must_be_finite(client, fresh, literal):
    populate(client)
    raw = json.dumps(export_doc(client), indent=2)
    assert '"servings": 1.5' in raw
    before = stored(fresh)
    r = post_import(fresh, None, raw=raw.replace('"servings": 1.5', f'"servings": {literal}', 1))
    assert r.status_code == 400 and "not a finite number" in r.json()["detail"]
    nutrient = raw.replace('"potassium_mg": 400', f'"potassium_mg": {literal}', 1)
    assert nutrient != raw
    assert post_import(fresh, None, raw=nutrient, dry_run=True).status_code == 400
    assert stored(fresh) == before


def test_text_and_numbers_of_the_wrong_kind_are_refused(client, fresh):
    populate(client)
    doc = export_doc(client)
    for edit, where in [
        (lambda d: d["log_entries"][0].__setitem__("servings", "2"), "log_entries[0].servings"),
        (lambda d: d["log_entries"][0].__setitem__("id", True), "log_entries[0].id"),
        (lambda d: d["log_entries"][0].__setitem__("food_name", "x" * 201), "log_entries[0].food_name"),
        (lambda d: d["log_entries"][0].__setitem__("note", "x" * 501), "log_entries[0].note"),
        (lambda d: d["custom_foods"][0].__setitem__("name", ""), "custom_foods[0].name"),
        (lambda d: d["custom_foods"][0].__setitem__("flags", ["Not Snake Case!"]), "custom_foods[0].flags"),
        (lambda d: d["custom_foods"][0].__setitem__("source", "builtin"), "custom_foods[0].source"),
        (lambda d: d["custom_foods"][0].__setitem__("source_url", "javascript:alert(1)"), "custom_foods[0].source_url"),
        (lambda d: d["custom_foods"][0].__setitem__("source_license", "WTFPL"), "custom_foods[0].source_license"),
        (lambda d: d["custom_foods"][0].__setitem__("gtin", "123"), "custom_foods[0].gtin"),
        (lambda d: d["log_entries"][0].__setitem__("id", 2**70), "log_entries[0].id"),
        (lambda d: d["log_entries"][0].__setitem__("food_id", 0), "log_entries[0].food_id"),
        (lambda d: d["lab_results"][0].__setitem__("analyte", "magic"), "lab_results[0].analyte"),
    ]:
        bad = copy.deepcopy(doc)
        edit(bad)
        reset_limits(fresh)
        r = post_import(fresh, bad, dry_run=True)
        assert r.status_code == 400 and where in r.json()["detail"], (where, r.text)


def test_a_refusal_never_repeats_what_it_was_sent(client, fresh):
    populate(client)
    doc = export_doc(client)
    doc["log_entries"][0]["meal"] = "SECRET-MARKER-" + "z" * 5000
    doc["custom_foods"][0]["nutrients"]["MARKER_" + "k" * 5000] = 1
    for dry in (True, False):
        r = post_import(fresh, doc, dry_run=dry)
        assert r.status_code == 400 and "SECRET-MARKER" not in r.text and len(r.text) < 1000
    doc["log_entries"][0]["meal"] = "lunch"
    r = post_import(fresh, doc, dry_run=True)
    assert r.status_code == 400 and "kkkkkkkkkk" not in r.text and len(r.text) < 1000, r.text


def test_food_ids_must_be_unique_in_the_file(client, fresh):
    populate(client)
    doc = export_doc(client)
    twice = copy.deepcopy(doc)
    twice["custom_foods"][1]["id"] = twice["custom_foods"][0]["id"]
    r = post_import(fresh, twice)
    assert r.status_code == 400 and "custom_foods[1].id" in r.json()["detail"]
    clash = copy.deepcopy(doc)
    clash["builtin_foods"][0]["id"] = clash["custom_foods"][0]["id"]
    r = post_import(fresh, clash)
    assert r.status_code == 400 and "builtin_foods[0].id" in r.json()["detail"]


def test_secrets_tokens_and_sessions_in_a_crafted_file_are_ignored(client, fresh):
    populate(client)
    doc = export_doc(client)
    doc["ai_provider"] = {"preset": "openai", "api_key": "sk-SECRET-ONE", "api_key_enc": "SECRET-TWO", "base_url": "http://evil"}
    doc["user"] = {"username": "somebody-else", "password_hash": "$argon2id$SECRET-THREE", "role": "admin"}
    doc["activity"] = [{"action": "login.succeeded", "details": {"token": "kha_SECRET-FOUR"}}]
    doc["ai_audit"] = [{"prompt": "SECRET-FIVE"}]
    doc["ai_usage"] = [{"day": "2026-10-01", "calls": 5}]
    doc["ai_consents"] = [{"provider_id": 1, "purpose": "text", "agreed": True}]
    doc["settings"].update({"food.off_consent": True, "ai": {"opt_in": True, "provider": "own"},
                            "providers.usda.api_key": "SECRET-SIX", "auth.registration_mode": "open"})
    r = post_import(fresh, doc, replace_profile=True)
    assert r.status_code == 200, r.text
    answer = r.json()
    assert answer["counts"]["settings"] == 2  # guidance and theme only
    assert answer["skipped"]["by_kind"] == {"settings": 4}
    assert len(answer["not_imported"]) >= 4 and "SECRET" not in r.text
    dump = whole_database(fresh)
    for marker in ("SECRET", "somebody-else", "evil", "kha_", "argon2id$SECRET"):
        assert marker not in dump
    keys = {k for k, v in fresh.get("/api/me/settings").json()["settings"].items() if v["source"] == "user"}
    assert keys == {"guidance", "ui.theme"}
    conn = sqlite3.connect(fresh.app.state.settings.db_path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM ai_providers WHERE scope = 'user'").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM ai_consents").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM ai_audit").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM api_tokens").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 1
        assert conn.execute("SELECT username, role FROM users").fetchone() == ("admin", "admin")
    finally:
        conn.close()
    assert fresh.get("/api/me").json()["username"] == "admin"


def test_the_skipped_sections_are_not_even_validated(client, fresh):
    doc = export_doc(client)
    doc["ai_audit"] = {"anything": [1, {"at": "all"}]}
    doc["activity"] = "text"
    assert post_import(fresh, doc, dry_run=True).status_code == 200


# --------------------------------------------------------------------------- the size limit


def test_the_body_limit_is_its_own_for_this_path_only(tmp_path, foods_json):
    settings = make_settings(tmp_path / "small", foods_json, max_import_bytes=20_000)
    with signed_in_client(settings) as c:
        doc = export_doc(c)
        small = json.dumps(doc)
        assert len(small) < 20_000 and post_import(c, None, raw=small, dry_run=True).status_code == 200
        big = json.dumps({**doc, "settings": {}, "user": {"pad": "x" * 30_000}})
        r = post_import(c, None, raw=big)
        assert r.status_code == 413 and r.json() == {"detail": "Request body too large"}
        # streamed without a Content-Length, the counted bytes are limited too
        r = c.post("/api/me/import", content=(chunk for chunk in [b"x" * 8000] * 5), headers=JSON)
        assert r.status_code == 413
        assert c.put("/api/profile", content=b"{" + b" " * 2_000_000 + b"}", headers=JSON).status_code == 413  # default 1 MiB


def test_a_year_of_heavy_use_is_over_the_default_limit_and_imports(client, fresh):
    banana = find_food(client, "banana")
    batch = [{"date": f"2026-{1 + n // 28 % 12:02d}-{1 + n % 28:02d}", "meal": ("breakfast", "lunch", "dinner", "snack")[n % 4],
              "food_id": banana["id"], "servings": 1.5, "note": "a note"} for n in range(40)]
    for _ in range(10):
        assert client.post("/api/log/batch", json={"entries": batch}).status_code == 201
    doc = export_doc(client)
    doc["log_entries"] = doc["log_entries"] * 4  # 1,600 entries
    raw = json.dumps(doc, indent=2)
    assert len(raw) > 1_048_576, len(raw)
    assert fresh.put("/api/profile", content=raw, headers=JSON).status_code == 413  # any other path keeps MAX_BODY_BYTES
    r = post_import(fresh, None, raw=raw)
    assert r.status_code == 200, r.text
    assert r.json()["counts"]["log_entries"] == 1600
    assert len(fresh.get("/api/log", params={"date": "2026-01-01"}).json()["entries"]) >= 1


def test_lists_are_bounded(client, fresh):
    populate(client)
    doc = export_doc(client)
    many = [{"food_id": 1, "name": "x", "preference": "not_for_me", "created_at": "2026-10-05T10:00:00.000000Z"}] * 501
    for edit, where in [
        (lambda d: d.__setitem__("food_preferences", many), "food_preferences"),
        (lambda d: d["meal_templates"][0].__setitem__("items", d["meal_templates"][0]["items"] * 60), "meal_templates[0].items"),
        (lambda d: d.__setitem__("settings", {f"k{n}": 1 for n in range(201)}), "settings"),
        (lambda d: d["custom_foods"][0].__setitem__("flags", ["a"] * 61), "custom_foods[0].flags"),
    ]:
        bad = copy.deepcopy(doc)
        edit(bad)
        reset_limits(fresh)
        r = post_import(fresh, bad, dry_run=True)
        assert r.status_code == 400 and where in r.json()["detail"], (where, r.text)


# --------------------------------------------------------------------------- duplicates and ids


def test_an_account_with_data_needs_add_to_my_existing_data(client, fresh):
    populate(client)
    doc = export_doc(client)
    first = post_import(fresh, doc)
    assert first.status_code == 200
    state = stored(fresh)
    # the same file again: refused, and a dry run says why and offers the choice
    r = post_import(fresh, doc)
    assert r.status_code == 409 and r.json()["blocked"]["code"] == "account_not_empty"
    assert r.json()["blocked"]["existing"] == {"log_entries": 7, "custom_foods": 3, "meal_templates": 1, "lab_results": 2,
                                                     "symptoms": 0}
    r = post_import(fresh, doc, dry_run=True)
    assert r.status_code == 200 and r.json()["can_import"] is False and r.json()["blocked"]["code"] == "account_not_empty"
    assert r.json()["file"]["records"]["log_entries"] == 7
    assert stored(fresh) == state
    # chosen: nothing is added a second time
    r = post_import(fresh, doc, merge=True)
    assert r.status_code == 200, r.text
    answer = r.json()
    assert answer["counts"] == dict.fromkeys(answer["counts"], 0) | {"built_in_foods_matched": 2}
    assert answer["already_there"] == {"log_entries": 7, "custom_foods": 3, "shared_foods_linked": 0, "meal_templates": 1,
                                       "lab_results": 2, "symptoms": 0, "food_preferences": 2}
    after = stored(fresh)
    for table in ("log_entries", "foods", "meal_templates", "lab_results", "food_preferences"):
        assert after[table] == state[table], table
    assert len(fresh.get("/api/log", params={"date": DAY}).json()["entries"]) == 5


def test_adding_to_existing_data_adds_only_what_is_new(client, fresh):
    items = populate(client)
    post_import(fresh, export_doc(client))
    # A logs one more thing and another lab; B's copy of the same earlier history stays as it is
    client.post("/api/log", json={"date": SECOND_DAY, "meal": "snack", "food_id": items["banana"]["id"]})
    client.post("/api/labs", json={"analyte": "a1c", "value": 6.5, "unit": "%", "taken_on": "2026-10-02"})
    client.post("/api/meals", json={"name": "Usual lunch", "items": [{"food_id": items["banana"]["id"], "servings": 1}]})
    r = post_import(fresh, export_doc(client), merge=True)
    assert r.status_code == 200, r.text
    counts = r.json()["counts"]
    assert (counts["log_entries"], counts["lab_results"], counts["meal_templates"], counts["custom_foods"]) == (1, 1, 1, 0)
    assert r.json()["already_there"]["log_entries"] == 7
    assert len(fresh.get("/api/meals").json()["meals"]) == 2  # same name, other foods: a second saved meal
    # a file with the same entry twice, where the account has it once: one is already there, one is new
    twin = export_doc(client)
    twin["log_entries"] = [twin["log_entries"][0], copy.deepcopy(twin["log_entries"][0])]
    third = post_import(fresh, twin, merge=True)
    assert third.json()["already_there"]["log_entries"] == 1 and third.json()["counts"]["log_entries"] == 1


def test_identical_entries_in_a_file_are_not_collapsed(client, fresh):
    banana = find_food(client, "banana")
    client.post("/api/log", json={"date": DAY, "meal": "lunch", "food_id": banana["id"]})
    doc = export_doc(client)
    doc["log_entries"] = [doc["log_entries"][0], copy.deepcopy(doc["log_entries"][0])]
    r = post_import(fresh, doc)
    assert r.json()["counts"]["log_entries"] == 2
    assert len(fresh.get("/api/log", params={"date": DAY}).json()["entries"]) == 2


def test_ids_in_the_file_never_decide_ids_here(client, fresh):
    populate(client)
    doc = export_doc(client)
    # B already has rows whose ids equal the ids in the file
    mine = fresh.post("/api/foods", json={"name": "B's own food", "serving_desc": "1", "serving_g": 50,
                                          "nutrients": {"potassium_mg": 10}}).json()
    assert mine["id"] in {f["id"] for f in doc["custom_foods"]}  # B's new food has an id the file also uses
    b_entry = fresh.post("/api/log", json={"date": DAY, "meal": "dinner", "food_id": mine["id"], "servings": 3}).json()
    b_meal = fresh.post("/api/meals", json={"name": "B's meal", "items": [{"food_id": mine["id"], "servings": 1}]}).json()
    assert post_import(fresh, doc).status_code == 409
    r = post_import(fresh, doc, merge=True)
    assert r.status_code == 200, r.text
    assert fresh.get(f"/api/foods/{mine['id']}").json()["name"] == "B's own food"
    assert fresh.get(f"/api/meals/{b_meal['id']}").json()["items"][0]["food_name"] == "B's own food"
    assert [e["id"] for e in fresh.get("/api/log", params={"date": DAY}).json()["entries"] if e["food_name"] == "B's own food"] == [b_entry["id"]]
    new_ids = {f["name"]: f["id"] for f in custom_foods(fresh)}
    assert len(new_ids) == 3 and len(set(new_ids.values())) == 3 and mine["id"] in new_ids.values()
    soup_entries = [e for e in fresh.get("/api/log", params={"date": DAY}).json()["entries"] if e["food_name"] == "My soup"]
    assert len(soup_entries) == 2 and {e["food_id"] for e in soup_entries} == {new_ids["My soup"]}
    assert fresh.get(f"/api/foods/{new_ids['My soup']}").json()["serving_desc"] == "1 bowl"


def test_a_crafted_food_id_never_reaches_another_persons_food(two_clients):
    admin, sam = two_clients
    items = populate(admin)
    secret = admin.post("/api/foods", json={"name": "Admin's secret", "serving_desc": "1", "serving_g": 10, "nutrients": {}}).json()
    doc = export_doc(sam)  # sam's own, empty export
    doc["log_entries"] = [{
        "id": 1, "date": DAY, "meal": "lunch", "food_id": secret["id"], "food_name": "Admin's secret", "servings": 1, "grams": None,
        "note": None, "status": "eaten", "nutrients": {}, "warnings": [], "kidney_rating": "green", "purpose": None,
        "client_id": None, "created_at": "2026-10-05T10:00:00.000000Z", "updated_at": "2026-10-05T10:00:00.000000Z"}]
    doc["food_preferences"] = [{"food_id": secret["id"], "name": "Admin's secret", "preference": "not_for_me",
                                "created_at": "2026-10-05T10:00:00.000000Z"}]
    doc["meal_templates"] = [{
        "id": 1, "name": "Sneaky", "note": None, "meal_hint": None, "totals": {}, "kidney_rating": "green",
        "created_at": "2026-10-05T10:00:00.000000Z", "updated_at": "2026-10-05T10:00:00.000000Z",
        "items": [{"food_id": secret["id"], "food_name": "Admin's secret", "servings": 1, "serving_desc": "1", "nutrients": {},
                   "kidney_rating": "green", "hidden": False}]}]
    doc["builtin_foods"] = [{"id": secret["id"], "name": "Admin's secret", "fdc_id": None}]  # claims it is built in
    admin_before = rows_of(admin, 1)
    r = post_import(sam, doc)
    assert r.status_code == 200, r.text
    answer = r.json()
    assert answer["counts"]["log_entries"] == 0 and answer["counts"]["meal_templates"] == 0 and answer["counts"]["food_preferences"] == 0
    assert answer["skipped"]["by_kind"] == {"log_entries": 1, "meal_templates": 1, "food_preferences": 1}
    assert sam.get(f"/api/foods/{secret['id']}").status_code == 404
    assert sam.get("/api/log", params={"date": DAY}).json()["entries"] == []
    assert rows_of(admin, 1) == admin_before
    # an older file with no builtin_foods list: the id is tried as a built-in food and must be one, by name too
    del doc["builtin_foods"]
    r = post_import(sam, doc, merge=True)
    assert r.json()["counts"]["log_entries"] == 0 and r.json()["skipped"]["total"] == 3
    assert rows_of(admin, 1) == admin_before and items["soup"]


def test_importing_another_persons_file_gives_you_copies_and_changes_nothing_of_theirs(two_clients):
    admin, sam = two_clients
    populate(admin)
    doc = export_doc(admin)
    admin_before = rows_of(admin, 1)
    admin_day = admin.get("/api/log", params={"date": DAY}).json()
    r = post_import(sam, doc)
    assert r.status_code == 200, r.text
    assert rows_of(admin, 1) == admin_before
    assert admin.get("/api/log", params={"date": DAY}).json() == admin_day
    assert scrub(sam.get("/api/log", params={"date": DAY}).json()["entries"]) == scrub(admin_day["entries"])  # no targets: not asked
    conn = sqlite3.connect(admin.app.state.settings.db_path)
    try:
        sam_id = sam.get("/api/me").json()["id"]
        assert conn.execute("SELECT COUNT(*) FROM foods WHERE owner_user_id = ?", (sam_id,)).fetchone()[0] == 3
        assert conn.execute("SELECT COUNT(*) FROM log_entries WHERE user_id = ?", (sam_id,)).fetchone()[0] == 7
        assert conn.execute("SELECT COUNT(*) FROM log_entries WHERE user_id = 1").fetchone()[0] == 7
        # the profile is only replaced when asked, and only sam's
        assert conn.execute("SELECT name FROM user_profiles WHERE user_id = 1").fetchone()[0] == "Sam"
    finally:
        conn.close()
    assert sam.get("/api/profile").json()["name"] == ""
    assert post_import(sam, doc, merge=True, replace_profile=True).status_code == 200
    assert sam.get("/api/profile").json()["name"] == "Sam"
    assert admin.get("/api/profile").json()["targets"] == {"potassium_mg": 2500, "protein_g": {"min": 50, "max": 60}}


# --------------------------------------------------------------------------- foods that must be found


def test_a_built_in_food_is_found_by_its_fdc_id_or_reported(client, tmp_path, foods_json):
    populate(client)
    doc = export_doc(client)
    # a server whose built-in list lacks bananas
    smaller = copy.deepcopy(FIXTURE_FOODS)
    smaller["foods"] = [f for f in smaller["foods"] if f["fdc_id"] != 173944]
    path = Path(tmp_path / "smaller.json")
    path.write_text(json.dumps(smaller), encoding="utf-8")
    with signed_in_client(make_settings(tmp_path / "third", path)) as other:
        r = post_import(other, doc, dry_run=True)
        assert r.status_code == 200, r.text
        answer = r.json()
        assert answer["counts"]["built_in_foods_matched"] == 1  # the glucose tablets
        by_kind = answer["skipped"]["by_kind"]
        assert by_kind == {"log_entries": 1, "meal_templates": 1, "food_preferences": 1}
        reasons = {s["kind"]: s for s in answer["skipped"]["shown"]}
        assert "built-in food this server does not have" in reasons["log_entries"]["reason"]
        assert reasons["log_entries"]["label"].startswith(DAY) and "Banana" in reasons["log_entries"]["label"]
        done = post_import(other, doc).json()
        assert done["counts"]["log_entries"] == 6 and done["counts"]["meal_templates"] == 1  # the meal keeps its soup
        meal = other.get("/api/meals").json()["meals"][0]
        assert [i["food_name"] for i in meal["items"]] == ["My soup"]
        # a meal that lost a food says so in its note, so its totals never read as complete
        assert meal["note"] == "weekdays Imported without 1 food that could not be matched: Banana, raw."
        again = post_import(other, doc, merge=True).json()
        assert again["counts"]["meal_templates"] == 0 and again["already_there"]["meal_templates"] == 1


def test_an_older_file_finds_built_in_foods_by_id_and_name(client, fresh):
    populate(client)
    doc = export_doc(client)
    del doc["builtin_foods"]
    for record in doc["linked_foods"]:
        record.pop("food", None), record.pop("gtin", None)
    r = post_import(fresh, doc, dry_run=True)
    assert r.status_code == 200 and r.json()["counts"]["built_in_foods_matched"] == 2 and r.json()["skipped"]["total"] == 0
    renamed = copy.deepcopy(doc)
    for e in renamed["log_entries"]:
        e["food_name"] = "Plantain" if e["food_name"] == "Banana, raw" else e["food_name"]
    for p in renamed["food_preferences"]:
        p["name"] = "Plantain" if p["name"] == "Banana, raw" else p["name"]
    for item in (i for m in renamed["meal_templates"] for i in m["items"]):
        item["food_name"] = "Plantain" if item["food_name"] == "Banana, raw" else item["food_name"]
    r = post_import(fresh, renamed, dry_run=True)  # same id, but nothing calls it a banana any more: not the same food
    assert r.json()["skipped"]["by_kind"] == {"log_entries": 1, "meal_templates": 1, "food_preferences": 1}
    assert r.json()["counts"]["built_in_foods_matched"] == 1


def test_a_food_missing_everywhere_is_skipped_and_reported_never_guessed(client, fresh):
    populate(client)
    doc = export_doc(client)
    ghost = copy.deepcopy(doc["log_entries"][0])
    ghost.update(food_id=99999, food_name="Ghost pie")
    doc["log_entries"].insert(2, ghost)
    doc["meal_templates"][0]["items"].append({"food_id": 88888, "food_name": "Deleted food", "servings": 1, "serving_desc": "unknown",
                                              "nutrients": {}, "kidney_rating": "green", "hidden": True})
    doc["food_preferences"].append({"food_id": 77777, "name": "Vanished", "preference": "not_for_me",
                                    "created_at": "2026-10-05T10:00:00.000000Z"})
    r = post_import(fresh, doc)
    assert r.status_code == 200, r.text
    answer = r.json()
    assert answer["skipped"]["total"] == 3 and answer["skipped"]["by_kind"] == {"log_entries": 1, "meal_templates": 1, "food_preferences": 1}
    entry = next(s for s in answer["skipped"]["shown"] if s["kind"] == "log_entries")
    assert entry["index"] == 2 and "Ghost pie" in entry["label"] and "not in the file" in entry["reason"]
    assert answer["counts"]["log_entries"] == 7 and answer["counts"]["meal_templates"] == 1
    meal = fresh.get("/api/meals").json()["meals"][0]
    assert [i["food_name"] for i in meal["items"]] == ["My soup", "Banana, raw"]
    assert meal["note"] == "weekdays Imported without 1 food that could not be matched: Deleted food."
    assert not any(f["name"] == "Ghost pie" for f in fresh.get("/api/foods", params={"q": "ghost"}).json()["foods"])


def test_a_meal_with_no_usable_food_is_skipped(client, fresh):
    banana = find_food(client, "banana")
    client.post("/api/meals", json={"name": "Just bananas", "items": [{"food_id": banana["id"], "servings": 1}]})
    doc = export_doc(client)
    doc["builtin_foods"] = []
    doc["meal_templates"][0]["items"][0]["food_name"] = "Plantain"
    r = post_import(fresh, doc)
    assert r.json()["skipped"]["by_kind"] == {"meal_templates": 1} and r.json()["counts"]["meal_templates"] == 0
    assert any("none of its foods" in s["reason"] for s in r.json()["skipped"]["shown"])


USDA_RECORD = {"fdcId": 424242, "description": "Shared USDA oats", "dataType": "SR Legacy",
               "foodCategory": {"description": "Breakfast Cereals"},
               "foodNutrients": [{"nutrient": {"number": "306"}, "amount": 100}]}


@pytest.fixture
def usda_pair(tmp_path, foods_json, monkeypatch):
    """Person A with an imported USDA food, and a second server that has (or lacks) the same shared row."""

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json=USDA_RECORD) if request.url.path == "/fdc/v1/food/424242" else httpx2.Response(404, json={})

    monkeypatch.setattr(foods_module, "usda_client",
                        lambda: httpx2.Client(base_url=foods_module.USDA_BASE_URL, transport=httpx2.MockTransport(handler)))
    settings = make_settings(tmp_path / "first", foods_json, usda_api_key="SHARED-ENV-KEY-0123456789")
    other = make_settings(tmp_path / "second", foods_json, usda_api_key="SHARED-ENV-KEY-0123456789")
    with signed_in_client(settings) as a, signed_in_client(other) as b:
        oats = a.post("/api/foods/usda/import", json={"fdc_id": 424242}).json()
        assert a.post("/api/log", json={"date": DAY, "meal": "breakfast", "food_id": oats["id"], "servings": 2}).status_code == 201
        assert a.post("/api/meals", json={"name": "Oats", "items": [{"food_id": oats["id"], "servings": 1}]}).status_code == 201
        yield a, b, oats


def test_a_usda_food_is_linked_when_the_server_has_the_shared_row(usda_pair):
    a, b, oats = usda_pair
    # B's server has imported the same food (another person did): the link points at that shared row
    shared = b.post("/api/foods/usda/import", json={"fdc_id": 424242}).json()
    assert b.delete(f"/api/foods/{shared['id']}").status_code == 204  # unlinked: B no longer sees it
    assert b.get(f"/api/foods/{shared['id']}").status_code == 404
    doc = export_doc(a)
    assert doc["linked_foods"][0]["food"]["name"] == "Shared USDA oats" and doc["linked_foods"][0]["fdc_id"] == 424242
    r = post_import(b, doc)
    assert r.status_code == 200, r.text
    assert r.json()["counts"]["shared_foods_linked"] == 1 and r.json()["counts"]["shared_foods_kept_as_own"] == 0
    assert b.get(f"/api/foods/{shared['id']}").status_code == 200
    day = b.get("/api/log", params={"date": DAY}).json()["entries"]
    assert [(e["food_id"], e["servings"]) for e in day] == [(shared["id"], 2)]
    assert custom_foods(b) == []  # no copy was made
    assert post_import(b, doc, merge=True).json()["already_there"]["shared_foods_linked"] == 1


def test_a_usda_food_the_server_lacks_is_kept_as_the_persons_own_copy(usda_pair):
    a, b, oats = usda_pair
    doc = export_doc(a)
    r = post_import(b, doc)
    assert r.status_code == 200, r.text
    assert r.json()["counts"]["shared_foods_kept_as_own"] == 1 and r.json()["counts"]["shared_foods_linked"] == 0
    mine = custom_foods(b)
    assert [f["name"] for f in mine] == ["Shared USDA oats"] and mine[0]["source"] == "custom" and mine[0]["source_license"] == "CC0-1.0"
    assert mine[0]["nutrients"] == oats["nutrients"] and mine[0]["serving_g"] == oats["serving_g"]
    assert b.get("/api/log", params={"date": DAY}).json()["entries"][0]["food_id"] == mine[0]["id"]
    # the shared USDA row of this server was not created from a file
    conn = sqlite3.connect(b.app.state.settings.db_path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM foods WHERE source = 'usda'").fetchone()[0] == 0
    finally:
        conn.close()
    again = post_import(b, doc, merge=True).json()
    assert again["counts"]["log_entries"] == 0 and again["already_there"]["custom_foods"] == 1
    assert len(custom_foods(b)) == 1


def test_a_usda_food_from_an_older_file_is_reported_when_the_server_lacks_it(usda_pair):
    a, b, oats = usda_pair
    doc = export_doc(a)
    del doc["linked_foods"][0]["food"], doc["linked_foods"][0]["gtin"]
    r = post_import(b, doc)
    assert r.status_code == 200, r.text
    assert r.json()["counts"]["log_entries"] == 0 and r.json()["skipped"]["by_kind"] == {"log_entries": 1, "meal_templates": 1}
    assert "does not have" in r.json()["skipped"]["shown"][0]["reason"] and custom_foods(b) == []


def test_a_linked_food_must_match_its_own_record(usda_pair):
    a, b, oats = usda_pair
    doc = export_doc(a)
    doc["linked_foods"][0]["food"]["source"] = "off"
    r = post_import(b, doc)
    assert r.status_code == 400 and "linked_foods[0]" in r.json()["detail"]


GTIN = "00049000028911"


def add_open_food_facts_row(client: TestClient, *, link_to: int | None) -> int:
    """A shared Open Food Facts row straight into the database (what a scan would have made), linked or not."""
    from app import off
    from app.db import connect

    conn = connect(client.app.state.settings.db_path)
    try:
        food_id = foods_module.insert_food(
            conn, source="off", name="Diet cola", serving_desc="1 can", serving_g=355, nutrients={"sodium_mg": 40, "potassium_mg": 10},
            provenance=foods_module.Provenance(gtin=GTIN, source_url=off.product_page(GTIN), source_license="ODbL-1.0"))
        if link_to is not None:
            foods_module.link_food(conn, link_to, food_id)
        conn.commit()
        return food_id
    finally:
        conn.close()


def test_an_open_food_facts_food_is_linked_by_its_barcode_or_kept_with_its_licence(client, fresh, tmp_path, foods_json):
    cola = add_open_food_facts_row(client, link_to=1)
    assert client.post("/api/log", json={"date": DAY, "meal": "lunch", "food_id": cola, "servings": 2}).status_code == 201
    doc = export_doc(client)
    assert doc["linked_foods"][0]["gtin"] == GTIN and doc["linked_foods"][0]["food"]["source_license"] == "ODbL-1.0"
    # a server that has the same product (someone scanned it there): the person is linked to that row
    there = add_open_food_facts_row(fresh, link_to=None)
    r = post_import(fresh, doc)
    assert r.status_code == 200 and r.json()["counts"]["shared_foods_linked"] == 1 and r.json()["counts"]["custom_foods"] == 0
    assert fresh.get("/api/log", params={"date": DAY}).json()["entries"][0]["food_id"] == there
    # a server without it keeps the food as the person's own copy, with the address and licence it came with
    with signed_in_client(make_settings(tmp_path / "third", foods_json)) as other:
        r = post_import(other, doc)
        assert r.status_code == 200 and r.json()["counts"]["shared_foods_kept_as_own"] == 1
        copy_ = custom_foods(other)[0]
        assert (copy_["source"], copy_["source_license"], copy_["gtin"]) == ("custom", "ODbL-1.0", GTIN)
        assert copy_["source_url"] == doc["linked_foods"][0]["food"]["source_url"] and copy_["name"] == "Diet cola"
        assert other.get("/api/log", params={"date": DAY}).json()["entries"][0]["food_name"] == "Diet cola"


def test_a_minimal_or_older_file_is_enough(client, fresh):
    r = post_import(fresh, {"format": "kidney-health-export", "version": 1}, dry_run=True)
    assert r.status_code == 200 and r.json()["counts"] == dict.fromkeys(r.json()["counts"], 0)
    banana = find_food(client, "banana")
    client.post("/api/log", json={"date": DAY, "meal": "lunch", "food_id": banana["id"]})
    doc = export_doc(client)
    for key in ("builtin_foods", "food_preferences", "ai_usage", "ai_consents", "ai_provider", "user", "exported_at", "app_version"):
        doc.pop(key)  # an export from before those existed
    for key in ("about_tolerance_pct", "ckd_stage_chosen", "diabetes_chosen", "birth_month", "sex", "activity"):
        doc["profile"].pop(key)
    r = post_import(fresh, doc, replace_profile=True)
    assert r.status_code == 200 and r.json()["counts"]["log_entries"] == 1 and r.json()["file"]["exported_at"] is None


# --------------------------------------------------------------------------- profile, targets, settings


def test_the_profile_targets_and_settings_are_replaced_only_when_asked(client, fresh):
    populate(client)
    assert fresh.put("/api/profile", json={"name": "Local", "weight_kg": 80, "targets": {"sodium_mg": 1500, "potassium_mg": 3000}}).status_code == 200
    assert fresh.patch("/api/me/settings", json={"guidance": {**GUIDANCE, "carb_tolerance_g": 8}}).status_code == 200
    doc = export_doc(client)
    dry = post_import(fresh, doc, dry_run=True, merge=True).json()
    assert dry["counts"]["profile"] == 0 and dry["counts"]["settings"] == 0
    assert dry["not_selected"] == ["your profile and targets", "your meal-guidance and display settings"]
    r = post_import(fresh, doc, merge=True)
    assert r.status_code == 200
    assert fresh.get("/api/profile").json()["name"] == "Local" and fresh.get("/api/profile").json()["targets"]["sodium_mg"] == 1500
    assert fresh.get("/api/me/settings").json()["settings"]["guidance"]["value"]["carb_tolerance_g"] == 8
    r = post_import(fresh, doc, merge=True, replace_profile=True)
    assert r.status_code == 200 and r.json()["counts"]["profile"] == 1
    profile = fresh.get("/api/profile").json()
    assert profile["name"] == "Sam" and profile["weight_kg"] == 70 and profile["dialysis_days"] == [0, 3] and profile["ckd_stage"] == "4"
    assert profile["targets"] == {"potassium_mg": 2500, "protein_g": {"min": 50, "max": 60}}  # replaced, not merged
    assert fresh.get("/api/me/settings").json()["settings"]["guidance"]["value"] == GUIDANCE


def test_a_stage_that_was_not_chosen_stays_not_chosen(tmp_path, foods_json, fresh):
    with signed_in_client(make_settings(tmp_path / "third", foods_json)) as a:
        a.put("/api/profile", json={"weight_kg": 65})
        doc = export_doc(a)
        assert doc["profile"]["ckd_stage_chosen"] is False
        fresh.put("/api/profile", json={"ckd_stage": "2", "diabetes": "type2"})
        post_import(fresh, doc, replace_profile=True)
        profile = fresh.get("/api/profile").json()
        assert profile["weight_kg"] == 65 and profile["ckd_stage"] == "2" and profile["diabetes"] == "type2"


def test_a_setting_locked_by_the_server_is_skipped(client, tmp_path, foods_json, monkeypatch):
    populate(client)
    doc = export_doc(client)
    from app.settings_store import SettingLocked, SettingsStore

    real = SettingsStore.set_user

    def locked(self, conn, user_id, key, value):  # noqa: ANN001
        if key == "ui.theme":
            raise SettingLocked(key, "UI_THEME")
        return real(self, conn, user_id, key, value)

    monkeypatch.setattr(SettingsStore, "set_user", locked)
    with signed_in_client(make_settings(tmp_path / "third", foods_json)) as other:
        r = post_import(other, doc, replace_profile=True)
        assert r.status_code == 200 and r.json()["counts"]["settings"] == 1
        assert any(s["label"] == "ui.theme" and "does not let you" in s["reason"] for s in r.json()["skipped"]["shown"])


def test_labs_are_checked_like_typed_ones_and_converted_again(client, fresh):
    populate(client)
    doc = export_doc(client)
    doc["lab_results"][1]["value"] = 999999  # the canonical number in a file is not trusted: it is recomputed
    r = post_import(fresh, doc)
    assert r.status_code == 200 and r.json()["counts"]["lab_results"] == 2
    labs = {l["analyte"]: l for l in fresh.get("/api/labs").json()["labs"]}
    assert labs["creatinine"]["entered_value"] == 110 and labs["creatinine"]["entered_unit"] == "µmol/L"
    assert labs["creatinine"]["value"] == pytest.approx(1.24, abs=0.01) and labs["creatinine"]["note"] == "fasting"


def test_a_high_potassium_result_still_raises_its_alert_after_import(client, fresh):
    client.post("/api/labs", json={"analyte": "potassium", "value": 6.2, "unit": "mmol/L", "taken_on": DAY})
    post_import(fresh, export_doc(client))
    # the fixture day is in the past; the alert shows while the result is fresh, so compare with the source server
    assert fresh.get("/api/labs").json()["alerts"] == client.get("/api/labs").json()["alerts"]


# --------------------------------------------------------------------------- who may call it


def test_importing_needs_a_recent_password_for_the_dry_run_too(client, fresh, fake_clock):
    populate(client)
    doc = export_doc(client)
    fake_clock.advance(minutes=11)
    for dry in (True, False):
        r = post_import(fresh, doc, dry_run=dry)
        assert r.status_code == 403 and r.json() == {"detail": "Please enter your password again", "reauth_required": True}
    assert stored(fresh)["log_entries"] == []
    assert fresh.post("/api/auth/reauth", json={"password": ADMIN_PASSWORD}).status_code == 200
    assert post_import(fresh, doc).status_code == 200


def test_importing_needs_the_app_header_and_a_signed_in_person(client, fresh, settings):
    doc = export_doc(client)
    bare = TestClient(fresh.app, headers={})
    bare.cookies.update(fresh.cookies)
    r = bare.post("/api/me/import", content=json.dumps(doc), headers=JSON)
    assert r.status_code == 403 and r.json() == {"detail": "Missing X-Requested-With header"}
    r = fresh.post("/api/me/import", content=json.dumps(doc), headers={**JSON, "Sec-Fetch-Site": "cross-site"})
    assert r.status_code == 403
    anonymous = TestClient(fresh.app)
    r = anonymous.post("/api/me/import", content=json.dumps(doc), headers=JSON)
    assert r.status_code == 401
    assert stored(fresh)["log_entries"] == []


def test_the_import_is_rate_limited(client, fresh):
    doc = export_doc(client)
    for _ in range(20):
        assert post_import(fresh, doc, dry_run=True).status_code == 200
    r = post_import(fresh, doc, dry_run=True)
    assert r.status_code == 429 and int(r.headers["retry-after"]) > 0


def test_the_route_is_listed_and_documented_for_the_auth_matrix(anon_client):
    from test_auth_coverage import api_operations

    assert ("post", "/api/me/import") in api_operations(anon_client.app)
    assert anon_client.post("/api/me/import", content=b"{}", headers=JSON).status_code == 401


def test_works_with_a_person_on_https_next_to_others(two_clients):
    admin, sam = two_clients
    populate(admin)
    doc = export_doc(admin)
    assert post_import(sam, doc, dry_run=True).status_code == 200
    assert post_import(sam, doc).status_code == 200
    assert export_doc(sam)["log_entries"] and HTTPS_URL
    assert add_user and TestClient


def test_the_curated_foods_with_a_negative_id_survive_an_export_and_an_import(tmp_path):
    """data/foods.json gives glucose tablets, gel and shots and the salt substitutes a negative id of their own in the place of a
    FoodData Central one, and a copy of such a food keeps it. A log with glucose tablets (the common low treatment) must therefore
    export and import: before this was fixed the import refused it with "builtin_foods[0].fdc_id: Input should be greater than or
    equal to 1". Run on the real built-in list, not the test fixture, whose ids are all positive."""
    real = Path(__file__).resolve().parents[1] / "data" / "foods.json"
    with signed_in_client(make_settings(tmp_path / "a", real)) as a, signed_in_client(make_settings(tmp_path / "b", real)) as b:
        tablets = find_food(a, "glucose tablet")
        assert tablets["fdc_id"] < 0
        assert a.post("/api/log", json={"date": DAY, "meal": "snack", "food_id": tablets["id"], "servings": 4}).status_code == 201
        copy = a.post(f"/api/foods/{tablets['id']}/copy")
        assert copy.status_code == 201 and copy.json()["fdc_id"] == tablets["fdc_id"]
        doc = export_doc(a)
        assert [(f["name"], f["fdc_id"]) for f in doc["builtin_foods"]] == [(tablets["name"], tablets["fdc_id"])]
        assert [f["fdc_id"] for f in doc["custom_foods"]] == [tablets["fdc_id"]]
        answer = post_import(b, doc)
        assert answer.status_code == 200, answer.text
        assert answer.json()["counts"]["log_entries"] == 1 and answer.json()["counts"]["built_in_foods_matched"] == 1
        assert answer.json()["counts"]["custom_foods"] == 1 and answer.json()["skipped"]["total"] == 0
        (entry,) = b.get("/api/log", params={"date": DAY}).json()["entries"]
        assert entry["food_name"] == tablets["name"] and entry["purpose"] == "hypo"
        # a number of no food here is still only "a built-in food this server does not have", never an error
        doc["builtin_foods"][0]["fdc_id"] = -987654
        assert post_import(b, doc, dry_run=True, merge=True).json()["skipped"]["by_kind"] == {"log_entries": 1}
        # and a number beyond what the database holds is refused as before
        doc["builtin_foods"][0]["fdc_id"] = -(2**63)
        assert post_import(b, doc, dry_run=True, merge=True).status_code == 400
