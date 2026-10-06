"""Export archive and account deletion (note 07 §4.14), CSV formula escaping."""
from __future__ import annotations

import csv
import io
import json
import sqlite3
import zipfile



from conftest import ADMIN_PASSWORD, DAY, HTTPS_URL, USER_PASSWORD, TestClient, find_food

FILES = {"export.json", "log.csv", "foods.csv", "meals.csv", "labs.csv", "README.txt"}
JSON_KEYS = {"format", "version", "exported_at", "app_version", "user", "profile", "settings", "log_entries",
             "custom_foods", "linked_foods", "meal_templates", "lab_results", "ai_audit", "activity"}


def fill(client: TestClient) -> dict:
    banana = find_food(client, "banana")
    food = client.post("/api/foods", json={"name": "=HYPERLINK(\"http://evil\")", "serving_desc": "1", "serving_g": 50,
                                           "nutrients": {"potassium_mg": 100}}).json()
    client.post("/api/log", json={"date": DAY, "meal": "lunch", "food_id": banana["id"], "note": "+cmd|' /C calc'!A0"})
    client.post("/api/log", json={"date": DAY, "meal": "dinner", "food_id": food["id"], "status": "planned"})
    client.post("/api/meals", json={"name": "@SUM(1+1)", "items": [{"food_id": banana["id"], "servings": 2}]})
    client.put("/api/profile", json={"name": "Sam", "weight_kg": 70})
    client.patch("/api/me/settings", json={"ui.theme": "dark"})
    client.put("/api/me/keys/usda", json={"api_key": "PRIVATE-KEY-0123456789abcdef"})
    return {"food": food, "banana": banana}


def read_zip(response) -> dict[str, bytes]:
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/zip"
    assert response.headers["cache-control"] == "no-store"
    with zipfile.ZipFile(io.BytesIO(response.content)) as z:
        return {name: z.read(name) for name in z.namelist()}


def test_export_zip_contents_shape_and_no_secrets(client):
    fill(client)
    r = client.get("/api/me/export.zip")
    assert r.headers["content-disposition"].startswith('attachment; filename="kidney-health-admin-')
    files = read_zip(r)
    assert set(files) == FILES
    data = json.loads(files["export.json"])
    assert set(data) == JSON_KEYS
    assert data["format"] == "kidney-health-export" and data["version"] == 1
    assert data["user"]["username"] == "admin" and set(data["user"]) == {"username", "display_name", "created_at"}
    assert data["profile"]["name"] == "Sam" and data["settings"] == {"ui.theme": "dark"}
    assert [e["meal"] for e in data["log_entries"]] == ["lunch", "dinner"]
    assert [f["name"] for f in data["custom_foods"]] == ['=HYPERLINK("http://evil")']
    assert data["meal_templates"][0]["items"][0]["servings"] == 2
    assert data["lab_results"] == [] and data["ai_audit"] == []
    assert any(e["action"] == "secret.set" for e in data["activity"])
    blob = b"".join(files.values())
    assert b"PRIVATE-KEY" not in blob and b"$argon2id$" not in blob and ADMIN_PASSWORD.encode() not in blob
    readme = files["README.txt"].decode()
    assert "password" in readme and "API keys" in readme
    # the export is audited
    assert "export.created" in [e["action"] for e in client.get("/api/me/activity").json()["events"]]


def test_csv_cells_that_look_like_formulas_are_escaped(client):
    fill(client)
    files = read_zip(client.get("/api/me/export.zip"))
    log_rows = list(csv.DictReader(io.StringIO(files["log.csv"].decode())))
    assert log_rows[0]["note"] == "'+cmd|' /C calc'!A0" and log_rows[1]["food_name"].startswith("'=HYPERLINK")
    assert log_rows[0]["source"] == "builtin" and log_rows[1]["status"] == "planned"
    foods = list(csv.DictReader(io.StringIO(files["foods.csv"].decode())))
    assert foods[0]["name"].startswith("'=")
    meals = list(csv.DictReader(io.StringIO(files["meals.csv"].decode())))
    assert meals[0]["meal_name"] == "'@SUM(1+1)"
    # the dietitian's CSV export escapes too, and numbers stay numbers
    rows = list(csv.DictReader(io.StringIO(client.get("/api/log/export.csv").text)))
    assert rows[0]["note"].startswith("'+") and rows[0]["potassium_mg"] == "422"


def test_export_is_rate_limited(client):
    for _ in range(10):
        assert client.get("/api/me/export.zip").status_code == 200
    r = client.get("/api/me/export.zip")
    assert r.status_code == 429 and int(r.headers["retry-after"]) > 0


def test_delete_account_needs_confirmation_and_password_and_cascades(two_clients):
    admin, sam = two_clients
    sam_id = sam.get("/api/me").json()["id"]
    fill(sam)
    fill(admin)
    assert sam.request("DELETE", "/api/me", json={"password": USER_PASSWORD, "confirm": "yes"}).status_code == 400
    r = sam.request("DELETE", "/api/me", json={"password": "not my password at all", "confirm": "DELETE"})
    assert r.status_code == 403
    r = sam.request("DELETE", "/api/me", json={"password": USER_PASSWORD, "confirm": "DELETE"})
    assert r.status_code == 204 and r.headers["clear-site-data"] == '"cache", "storage"'
    assert sam.get("/api/profile").status_code == 401
    conn = sqlite3.connect(admin.app.state.settings.db_path)
    for table, column in (("log_entries", "user_id"), ("meal_templates", "user_id"), ("foods", "owner_user_id"),
                          ("user_profiles", "user_id"), ("user_settings", "user_id"), ("secrets", "owner_user_id"),
                          ("sessions", "user_id"), ("usage_daily", "user_id"), ("user_food_links", "user_id")):
        assert conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {column} = ?", (sam_id,)).fetchone()[0] == 0, table
    assert conn.execute("SELECT COUNT(*) FROM users WHERE id = ?", (sam_id,)).fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM audit_log WHERE action = 'account.deleted' AND target_id = ?", (str(sam_id),)).fetchone()[0] == 1
    conn.close()
    # the other person's data is untouched
    assert len(admin.get("/api/log", params={"date": DAY}).json()["entries"]) == 2
    assert admin.get("/api/me/keys").json()["providers"][0]["own"]["set"] is True
    # the username can be used again; ids are never reused (AUTOINCREMENT)
    again = TestClient(admin.app, base_url=HTTPS_URL)
    from conftest import invite_token

    token = invite_token(admin)
    r = again.post("/api/auth/register", json={"token": token, "username": "sam", "password": USER_PASSWORD})
    assert r.status_code == 201 and r.json()["user"]["id"] > sam_id


def test_the_last_admin_cannot_delete_their_account(client):
    r = client.request("DELETE", "/api/me", json={"password": ADMIN_PASSWORD, "confirm": "DELETE"})
    assert r.status_code == 409 and "admin" in r.json()["detail"]
    assert client.get("/api/me").status_code == 200


def test_app_connections_use_secure_delete():
    from app import db

    conn = db.connect(":memory:")
    assert conn.execute("PRAGMA secure_delete").fetchone()[0] == 2  # FAST
    conn.close()
