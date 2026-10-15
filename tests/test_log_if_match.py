"""Offline edits and deletes: entry versions and ``If-Match`` (ROADMAP "Offline edits and deletes of entries already
on the server"; ARCHITECTURE.md "Offline edits and deletes").

Every entry carries a ``version`` (a hash of its stored content, nothing is stored). ``PUT`` and ``DELETE`` on
``/api/log/{id}`` take an optional ``If-Match: "<version>"``: a match changes the entry, a mismatch answers 412 with the
entry as stored now and changes nothing, no header behaves exactly as before, and an entry that is not yours is a 404
whatever the header says.
"""
from __future__ import annotations

import sqlite3

import pytest

from app import log as food_log
from conftest import DAY, HTTPS_URL, TestClient, add_user, log_food, sign_in
from app.main import create_app


def quoted(entry: dict) -> dict[str, str]:
    return {"If-Match": f'"{entry["version"]}"'}


def stored(client: TestClient, entry_id: int) -> dict | None:
    rows = [e for e in client.get("/api/log", params={"date": DAY}).json()["entries"] if e["id"] == entry_id]
    return rows[0] if rows else None


# --------------------------------------------------------------------------- the version


def test_every_entry_shape_carries_a_version(client):
    entry = log_food(client, "banana", servings=2, note="with breakfast")
    assert isinstance(entry["version"], str) and len(entry["version"]) == 16
    int(entry["version"], 16)
    assert stored(client, entry["id"])["version"] == entry["version"]  # the day, the batch and the copy say the same
    quick = client.post("/api/log/quick", json={"date": DAY, "meal": "snack", "name": "Own bar", "nutrients": {"protein_g": 3}})
    assert quick.status_code == 201 and len(quick.json()["version"]) == 16
    batch = client.post("/api/log/batch", json={"entries": [{"date": DAY, "meal": "lunch", "food_id": entry["food_id"]}]})
    assert len(batch.json()["entries"][0]["version"]) == 16
    copy = client.post("/api/log/copy-day", json={"from_date": DAY, "to_date": "2026-10-06"})
    assert all(len(e["version"]) == 16 for e in copy.json()["entries"])


def test_the_version_follows_the_content_not_the_time(client):
    entry = log_food(client, "banana", servings=1)
    same = client.put(f"/api/log/{entry['id']}", json={"servings": 1})
    assert same.json()["updated_at"] != entry["updated_at"] and same.json()["version"] == entry["version"]
    changed = client.put(f"/api/log/{entry['id']}", json={"servings": 2}).json()
    assert changed["version"] != entry["version"]
    back = client.put(f"/api/log/{entry['id']}", json={"servings": 1}).json()
    assert back["version"] == entry["version"]  # an edit that is undone is no conflict
    for body in ({"meal": "dinner"}, {"note": "x"}, {"status": "planned"}, {"date": "2026-10-06"}, {"purpose": "hypo"}):
        other = client.put(f"/api/log/{entry['id']}", json=body).json()
        assert other["version"] not in (entry["version"], changed["version"]), body
        client.put(f"/api/log/{entry['id']}", json={"meal": "breakfast", "note": None, "status": "eaten", "date": DAY, "purpose": "none"})
    assert client.get("/api/log", params={"date": DAY}).json()["entries"][0]["version"] == entry["version"]


def test_mark_eaten_changes_the_version_of_a_planned_entry(client):
    planned = log_food(client, "banana", status="planned")
    client.post("/api/log/mark-eaten", json={"date": DAY})
    assert stored(client, planned["id"])["version"] != planned["version"]


def test_the_version_is_the_same_text_the_browser_twin_hashes():
    base = {"id": 1, "date": "2026-10-05", "meal": "lunch", "food_id": 7, "food_name": "Banana, raw", "servings": 1.5,
            "grams": None, "note": None, "status": "eaten", "purpose": None,
            "nutrients": {key: None for key in food_log.NUTRIENT_KEYS}}
    again = {**base, "id": 99, "nutrients": dict(base["nutrients"])}
    assert food_log.entry_version(base) == food_log.entry_version(again)  # the id is the address, not the content
    assert food_log.entry_version(base) != food_log.entry_version({**base, "servings": 1.501})
    # "ab" + "c" and "a" + "bc" are different texts, and a whole number has no point.
    assert food_log._version_piece("ab") + food_log._version_piece("c") != food_log._version_piece("a") + food_log._version_piece("bc")
    assert food_log._version_piece(300.0) == food_log._version_piece(300) == "n300;"
    assert food_log._version_piece(0.5) == "n0.5;" and food_log._version_piece(None) == "~"
    assert food_log._version_piece("é") == "s2:é"  # the length is in UTF-8 bytes


# --------------------------------------------------------------------------- PUT


def test_put_with_the_matching_version_changes_the_entry(client):
    entry = log_food(client, "banana", servings=1)
    r = client.put(f"/api/log/{entry['id']}", json={"servings": 3, "note": "big"}, headers=quoted(entry))
    assert r.status_code == 200, r.text
    assert r.json()["servings"] == 3 and r.json()["note"] == "big" and r.json()["version"] != entry["version"]


def test_put_with_a_stale_version_is_412_with_the_current_entry_and_changes_nothing(client):
    entry = log_food(client, "banana", servings=1)
    assert client.put(f"/api/log/{entry['id']}", json={"servings": 2}).status_code == 200  # "another device" saved first
    now = stored(client, entry["id"])
    r = client.put(f"/api/log/{entry['id']}", json={"servings": 9, "meal": "dinner"}, headers=quoted(entry))
    assert r.status_code == 412, r.text
    body = r.json()
    assert body["detail"] == "This entry was changed on another device"
    assert body["current"] == now and body["current"]["servings"] == 2
    assert stored(client, entry["id"]) == now  # nothing changed, not even updated_at


def test_put_without_the_header_behaves_as_before(client):
    entry = log_food(client, "banana", servings=1)
    client.put(f"/api/log/{entry['id']}", json={"servings": 2})
    r = client.put(f"/api/log/{entry['id']}", json={"servings": 4})  # a stale copy, but no If-Match: last write wins
    assert r.status_code == 200 and r.json()["servings"] == 4


@pytest.mark.parametrize("header", ['"0000000000000000"', "0000000000000000", 'W/"{v}"', "", '"a", "b"', "garbage"])
def test_put_refuses_a_header_that_is_not_the_version(client, header):
    entry = log_food(client, "banana", servings=1)
    header = header.replace("{v}", entry["version"])
    r = client.put(f"/api/log/{entry['id']}", json={"servings": 7}, headers={"If-Match": header})
    assert r.status_code == 412 and r.json()["current"]["id"] == entry["id"]
    assert stored(client, entry["id"])["servings"] == 1


@pytest.mark.parametrize("header", ['"{v}"', "{v}", '"zz", "{v}"', "*"])
def test_put_accepts_the_forms_of_a_matching_header(client, header):
    entry = log_food(client, "banana", servings=1)
    r = client.put(f"/api/log/{entry['id']}", json={"servings": 7}, headers={"If-Match": header.replace("{v}", entry["version"])})
    assert r.status_code == 200 and r.json()["servings"] == 7


def test_a_second_put_with_the_old_version_is_refused(client):
    entry = log_food(client, "banana", servings=1)
    first = client.put(f"/api/log/{entry['id']}", json={"servings": 2}, headers=quoted(entry))
    assert first.status_code == 200
    second = client.put(f"/api/log/{entry['id']}", json={"servings": 3}, headers=quoted(entry))
    assert second.status_code == 412 and second.json()["current"]["servings"] == 2
    third = client.put(f"/api/log/{entry['id']}", json={"servings": 3}, headers=quoted(first.json()))
    assert third.status_code == 200 and third.json()["servings"] == 3


def test_a_bad_body_is_still_400_and_a_missing_entry_404_before_the_version(client):
    entry = log_food(client, "banana", servings=1)
    assert client.put(f"/api/log/{entry['id']}", json={"servings": -1}, headers=quoted(entry)).status_code == 400
    assert client.put("/api/log/999999", json={"servings": 2}, headers=quoted(entry)).status_code == 404
    assert client.delete("/api/log/999999", headers=quoted(entry)).status_code == 404


def test_the_status_of_a_hypo_treatment_entry_is_edited_like_any_other(client):
    # A low treatment is never warned about or blocked: it is edited and deleted exactly like any other entry.
    tablets = log_food(client, "glucose", servings=1)
    assert tablets["purpose"] == "hypo"
    r = client.put(f"/api/log/{tablets['id']}", json={"servings": 2, "note": "3.4 mmol/L"}, headers=quoted(tablets))
    assert r.status_code == 200 and r.json()["servings"] == 2 and r.json()["purpose"] == "hypo"
    assert client.delete(f"/api/log/{tablets['id']}", headers=quoted(r.json())).status_code == 204


# --------------------------------------------------------------------------- DELETE


def test_delete_with_the_matching_version(client):
    entry = log_food(client, "banana")
    assert client.delete(f"/api/log/{entry['id']}", headers=quoted(entry)).status_code == 204
    assert stored(client, entry["id"]) is None
    assert client.delete(f"/api/log/{entry['id']}", headers=quoted(entry)).status_code == 404


def test_delete_with_a_stale_version_is_412_and_keeps_the_entry(client):
    entry = log_food(client, "banana", servings=1)
    client.put(f"/api/log/{entry['id']}", json={"note": "changed elsewhere"})
    now = stored(client, entry["id"])
    r = client.delete(f"/api/log/{entry['id']}", headers=quoted(entry))
    assert r.status_code == 412 and r.json()["current"] == now
    assert stored(client, entry["id"]) == now


def test_delete_without_the_header_behaves_as_before(client):
    entry = log_food(client, "banana")
    client.put(f"/api/log/{entry['id']}", json={"servings": 2})
    assert client.delete(f"/api/log/{entry['id']}").status_code == 204


def test_a_change_between_the_check_and_the_write_is_still_a_412(client, monkeypatch):
    """Two requests with the same version: the one that writes second must not overwrite the first."""
    entry = log_food(client, "banana", servings=1)
    real = food_log.require_current_version

    def checked_then_changed(row, if_match):
        real(row, if_match)  # passes ...
        other = sqlite3.connect(client.app.state.settings.db_path)  # ... and then another request gets in first
        other.execute("UPDATE log_entries SET note = 'raced', updated_at = '2999-01-01T00:00:00.000000Z' WHERE id = ?", (entry["id"],))
        other.commit()
        other.close()

    monkeypatch.setattr(food_log, "require_current_version", checked_then_changed)
    r = client.put(f"/api/log/{entry['id']}", json={"servings": 5}, headers=quoted(entry))
    assert r.status_code == 412 and r.json()["current"]["note"] == "raced" and r.json()["current"]["servings"] == 1
    r = client.delete(f"/api/log/{entry['id']}", headers=quoted(entry))
    assert r.status_code == 412 and r.json()["current"]["note"] == "raced"
    monkeypatch.undo()
    assert stored(client, entry["id"])["note"] == "raced"


# --------------------------------------------------------------------------- isolation


@pytest.fixture
def pair(tmp_path, foods_json):
    from conftest import make_settings

    with TestClient(create_app(make_settings(tmp_path, foods_json)), base_url=HTTPS_URL) as a:
        sign_in(a)
        yield a, add_user(a, "sam")


def test_not_yours_is_404_even_with_a_valid_version(pair):
    a, b = pair
    mine = log_food(a, "banana", servings=1, note="A's")
    for method, body in (("PUT", {"servings": 9}), ("DELETE", None)):
        for headers in (quoted(mine), {"If-Match": "*"}, {"If-Match": '"0000000000000000"'}, {}):
            r = b.request(method, f"/api/log/{mine['id']}", json=body, headers=headers)
            assert r.status_code == 404, (method, headers, r.text)
            assert "current" not in r.json() and "A's" not in r.text and mine["version"] not in r.text
    assert stored(a, mine["id"]) == mine  # B changed nothing of A's


def test_the_412_shows_only_your_own_entry(pair):
    a, b = pair
    mine = log_food(a, "banana", servings=1, note="A's private note")
    theirs = log_food(b, "banana", servings=1)
    a.put(f"/api/log/{mine['id']}", json={"servings": 2})
    r = a.put(f"/api/log/{mine['id']}", json={"servings": 3}, headers=quoted(mine))
    assert r.status_code == 412 and r.json()["current"]["id"] == mine["id"]
    stale = b.put(f"/api/log/{theirs['id']}", json={"servings": 3}, headers={"If-Match": '"0000000000000000"'})
    assert stale.status_code == 412 and stale.json()["current"]["id"] == theirs["id"]
    assert "A's private note" not in stale.text


def test_a_signed_out_request_is_401_and_a_write_without_the_csrf_header_is_refused(anon_client):
    assert anon_client.put("/api/log/1", json={"servings": 2}, headers={"If-Match": '"x"'}).status_code == 401
    assert anon_client.delete("/api/log/1", headers={"If-Match": '"x"'}).status_code == 401


def test_the_csrf_header_is_still_needed(client):
    entry = log_food(client, "banana")
    r = client.put(f"/api/log/{entry['id']}", json={"servings": 2}, headers={"X-Requested-With": "", **quoted(entry)})
    assert r.status_code in (400, 403)
    assert stored(client, entry["id"])["servings"] == 1


# --------------------------------------------------------------------------- export and import


def test_the_export_leaves_the_derived_version_out_and_the_import_tolerates_it(client):
    import io
    import json
    import zipfile

    entry = log_food(client, "banana", servings=2)
    archive = zipfile.ZipFile(io.BytesIO(client.get("/api/me/export.zip").content))
    rows = json.loads(archive.read("export.json"))["log_entries"]
    assert rows and all("version" not in row for row in rows) and rows[0]["id"] == entry["id"]
    from app.data_import import ImportEntry

    ImportEntry.model_validate({**rows[0], "version": entry["version"]})  # an entry copied from the API is accepted
    with pytest.raises(Exception):
        ImportEntry.model_validate({**rows[0], "verzion": entry["version"]})  # other unknown keys are still refused
