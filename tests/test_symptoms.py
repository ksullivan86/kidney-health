"""Symptoms log (schema step 15, ``app/symptoms.py``): the routes, validation, the handbook red flags, isolation between
people, deleting an account, the export and the import of ``export.json``.

The page that decides which symptoms are red flags is ``handbook/docs/get-help-now.md``; the tests below read it, so the
app cannot keep quoting words that the page no longer has. The browser twin is checked by ``tests/test_symptoms_vectors.py``
and ``tests/test_symptoms_ui.py``.
"""
from __future__ import annotations

import csv
import io
import json
import re
import sqlite3
import zipfile
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest

import test_auth_coverage
from app import symptoms as symptoms_module
from app.main import create_app
from app.models import MAX_SYMPTOM_LABEL, MAX_SYMPTOM_NOTE, MAX_SYMPTOMS_PER_DAY
from conftest import ADMIN_PASSWORD, ADMIN_USERNAME, USER_PASSWORD, TestClient, make_settings, signed_in_client
from test_data_import import export_doc, post_import

ROOT = Path(__file__).resolve().parents[1]
HANDBOOK_PAGE = ROOT / "handbook" / "docs" / "get-help-now.md"
KEYS = [key for key, _ in symptoms_module.SYMPTOMS]
RED_FLAG_KEYS = {"breathlessness", "swelling"}
OBJECT_KEYS = {"id", "date", "symptom", "label", "name", "severity", "severity_label", "note", "created_at", "red_flag"}


def day(n: int = 0) -> str:
    return (date.today() - timedelta(days=n)).isoformat()


def body(symptom: str = "tiredness", severity: int = 2, when: str | None = None, **extra: Any) -> dict[str, Any]:
    out: dict[str, Any] = {"date": when or day(0), "symptom": symptom, "severity": severity}
    if symptom == "other" and "label" not in extra:
        extra["label"] = "Dry mouth"
    return {**out, **extra}


def listing(client: TestClient, start: str | None = None, end: str | None = None) -> list[dict[str, Any]]:
    r = client.get("/api/symptoms", params={"start": start or day(30), "end": end or day(0)})
    assert r.status_code == 200, r.text
    return r.json()["symptoms"]


def make(client: TestClient, *args: Any, **kwargs: Any) -> dict[str, Any]:
    r = client.post("/api/symptoms", json=body(*args, **kwargs))
    assert r.status_code == 201, r.text
    return r.json()


# --------------------------------------------------------------------------- the routes


def test_create_list_update_delete(client):
    made = make(client, "tiredness", 2, day(1), note="after the long day")
    assert set(made) == OBJECT_KEYS
    assert (made["name"], made["severity_label"], made["label"], made["note"], made["red_flag"]) == \
        ("Tiredness", "Moderate", "", "after the long day", None)
    assert made["created_at"].endswith("Z")
    later = make(client, "cramps", 1, day(0))
    assert [s["id"] for s in listing(client)] == [made["id"], later["id"]]  # oldest day first
    assert [s["id"] for s in listing(client, day(0), day(0))] == [later["id"]]
    r = client.put(f"/api/symptoms/{made['id']}", json=body("nausea", 3, day(2), note=""))
    assert r.status_code == 200, r.text
    updated = r.json()
    assert (updated["id"], updated["symptom"], updated["severity"], updated["date"], updated["note"], updated["created_at"]) == \
        (made["id"], "nausea", 3, day(2), "", made["created_at"])
    assert [s["id"] for s in listing(client)] == [made["id"], later["id"]] and listing(client)[0]["name"] == "Nausea"
    assert client.delete(f"/api/symptoms/{later['id']}").status_code == 204
    assert client.delete(f"/api/symptoms/{later['id']}").status_code == 404
    assert client.put(f"/api/symptoms/{later['id']}", json=body()).status_code == 404
    assert [s["id"] for s in listing(client)] == [made["id"]]


def test_other_names_itself_with_a_short_label(client):
    made = make(client, "other", 1, label="  Dry mouth  ")
    assert (made["symptom"], made["label"], made["name"], made["red_flag"]) == ("other", "Dry mouth", "Dry mouth", None)
    assert make(client, "other", 2, label="x" * MAX_SYMPTOM_LABEL)["name"] == "x" * MAX_SYMPTOM_LABEL


def test_the_same_symptom_can_be_recorded_twice_in_a_day(client):
    make(client, "tiredness", 1)
    make(client, "tiredness", 3)
    assert [s["severity"] for s in listing(client, day(0), day(0))] == [1, 3]


def test_a_day_holds_a_bounded_number_and_a_move_into_a_full_day_is_refused(client):
    for _ in range(MAX_SYMPTOMS_PER_DAY):
        make(client, "tiredness", 1, day(5))
    r = client.post("/api/symptoms", json=body("cramps", 1, day(5)))
    assert r.status_code == 400 and r.json()["detail"] == f"too many symptoms for one day (max {MAX_SYMPTOMS_PER_DAY})"
    other = make(client, "cramps", 1, day(4))
    assert client.put(f"/api/symptoms/{other['id']}", json=body("cramps", 1, day(5))).status_code == 400
    assert listing(client, day(4), day(4))[0]["date"] == day(4)  # the refused move changed nothing
    inside = listing(client, day(5), day(5))[0]
    assert client.put(f"/api/symptoms/{inside['id']}", json=body("tiredness", 2, day(5))).status_code == 200  # editing in a full day


@pytest.mark.parametrize("change, fragment", [
    ({"symptom": "headache"}, "symptom: Input should be 'swelling'"),
    ({"symptom": "OTHER", "label": "x"}, "symptom: Input should be"),
    ({"symptom": None}, "symptom: Input should be"),
    ({"severity": 0}, "severity: Input should be greater than or equal to 1"),
    ({"severity": 4}, "severity: Input should be less than or equal to 3"),
    ({"severity": "high"}, "severity: Input should be a valid integer"),
    ({"severity": 2.5}, "severity: Input should be a valid integer"),
    ({"severity": None}, "severity: Input should be a valid integer"),
    ({"date": "2999-01-01"}, "date: must not be in the future"),
    ({"date": "1899-12-31"}, "date: must be 1900 or later"),
    ({"date": "10/05/2026"}, "date: date must be formatted YYYY-MM-DD"),
    ({"date": "2026-02-30"}, "date: date is not a valid calendar date"),
    ({"date": 20261005}, "date: Input should be a valid string"),
    ({"note": "n" * (MAX_SYMPTOM_NOTE + 1)}, f"note: String should have at most {MAX_SYMPTOM_NOTE} characters"),
    ({"note": "bad\x00note"}, "note: must be plain text"),
    ({"note": 5}, "note: Input should be a valid string"),
    ({"label": "Dry mouth"}, "label is only for the symptom other"),
    ({"symptom": "other", "label": ""}, "label is required when the symptom is other"),
    ({"symptom": "other", "label": "   "}, "label is required when the symptom is other"),
    ({"symptom": "other", "label": "l" * (MAX_SYMPTOM_LABEL + 1)}, f"label: String should have at most {MAX_SYMPTOM_LABEL} characters"),
    ({"symptom": "other", "label": "two\nlines"}, "label: must be one line of plain text"),
    ({"surprise": 1}, "surprise: Extra inputs are not permitted"),
    ({"id": 7}, "id: Extra inputs are not permitted"),
    ({"user_id": 2}, "user_id: Extra inputs are not permitted"),
])
def test_bad_requests_are_refused_and_nothing_is_stored(client, change, fragment):
    payload = {**body("tiredness", 2), **change}
    r = client.post("/api/symptoms", json=payload)
    assert r.status_code == 400, r.text
    assert fragment in r.json()["detail"], r.json()
    assert listing(client) == []
    good = make(client)
    assert client.put(f"/api/symptoms/{good['id']}", json=payload).status_code == 400  # the same rules for a change
    assert listing(client) == [good]


def test_missing_fields_and_a_body_that_is_not_an_object_are_refused(client):
    r = client.post("/api/symptoms", json={})
    assert r.status_code == 400 and all(f"{k}: Field required" in r.json()["detail"] for k in ("date", "symptom", "severity"))
    assert client.post("/api/symptoms", json=[body()]).status_code == 400
    assert client.post("/api/symptoms", content=b"not json", headers={"content-type": "application/json"}).status_code == 400
    # a note and a label may be null (same as empty), and are stored as empty text
    made = make(client, "tiredness", 1, note=None, label=None)
    assert (made["note"], made["label"]) == ("", "")


def test_a_note_keeps_its_line_breaks_and_text_is_stored_as_given(client):
    made = make(client, "tiredness", 1, note="line one\nline two <b>not html</b> =SUM(1)")
    assert made["note"] == "line one\nline two <b>not html</b> =SUM(1)"


@pytest.mark.parametrize("params, fragment", [
    ({}, "start is required (YYYY-MM-DD)"),
    ({"start": day(1)}, "end is required (YYYY-MM-DD)"),
    ({"start": "soon", "end": day(0)}, "start: date must be formatted YYYY-MM-DD"),
    ({"start": day(0), "end": day(3)}, "end must not be before start"),
    ({"start": day(400), "end": day(0)}, "range too large (max 366 days)"),
])
def test_the_list_needs_a_sensible_date_range(client, params, fragment):
    r = client.get("/api/symptoms", params=params)
    assert r.status_code == 400 and r.json()["detail"] == fragment


def test_the_range_includes_both_ends_and_nothing_else(client):
    ids = {n: make(client, "tiredness", 1, day(n))["id"] for n in (0, 1, 2, 3)}
    assert [s["id"] for s in listing(client, day(2), day(1))] == [ids[2], ids[1]]
    assert listing(client, day(10), day(5)) == []


def test_ids_that_cannot_exist_are_404_or_a_validation_error(client):
    for symptom_id in ("0", "-1", "99999999999999999999"):
        assert client.delete(f"/api/symptoms/{symptom_id}").status_code == 404
        assert client.put(f"/api/symptoms/{symptom_id}", json=body()).status_code == 404
    r = client.delete("/api/symptoms/abc")
    assert r.status_code == 400 and "symptom_id: Input should be a valid integer" in r.json()["detail"]


def test_a_symptom_from_a_later_version_is_kept_hidden_and_exported(client):
    mine = make(client)
    conn = sqlite3.connect(client.app.state.settings.db_path)
    conn.execute("INSERT INTO symptoms (user_id, date, symptom, label, severity, note, created_at) "
                 "VALUES (1, ?, 'dizziness', '', 2, '', '2026-10-05T00:00:00.000000Z')", (day(0),))
    conn.commit()
    conn.close()
    assert [s["id"] for s in listing(client)] == [mine["id"]]
    assert [row["symptom"] for row in export_doc(client)["symptoms"]] == ["tiredness", "dizziness"]


# --------------------------------------------------------------------------- the handbook's red flags


def handbook_sections() -> dict[str, str]:
    text = HANDBOOK_PAGE.read_text(encoding="utf-8")
    parts = re.split(r"^## (.+)$", text, flags=re.M)
    return {parts[i].strip(): re.sub(r"\s+", " ", parts[i + 1].replace("*", "")).lower() for i in range(1, len(parts), 2)}


def squash(text: str) -> str:
    return re.sub(r"\s+", " ", text).lower()


def test_the_red_flag_list_is_what_the_handbook_page_sorts_as_a_warning_sign():
    sections = handbook_sections()
    for key, entry in symptoms_module.RED_FLAGS.items():
        heading = symptoms_module.HANDBOOK_GROUP_HEADINGS[entry["level"]]
        assert heading in sections, heading
        for quote in entry["quotes"]:
            assert squash(quote) in sections[heading], f"{key}: {quote!r} is not under {heading!r} on the handbook page"
            assert squash(quote) in squash(entry["text"]), f"{key}: the shown line does not quote {quote!r}"
        assert f"“{heading}”" in entry["text"]
    # the other symptoms are on the page only under "Mention at your next visit"
    for word in ("itch", "tired", "cramp", "nausea", "appetite"):
        assert word in sections["Mention at your next visit"], word
        assert word not in sections["Call 911 now"] and word not in sections["Call your care team today"], word
    assert RED_FLAG_KEYS == set(symptoms_module.RED_FLAGS)


def test_a_red_flag_symptom_carries_the_handbook_line_and_link_and_nothing_else_does(client):
    for key in KEYS:
        for severity in (1, 2, 3):
            made = make(client, key, severity)
            flag = made["red_flag"]
            if key not in RED_FLAG_KEYS:
                assert flag is None, key
                continue
            assert set(flag) == {"level", "text", "href", "link_text", "prominent"}
            assert flag["href"] == "/learn/get-help-now/" and flag["link_text"] == "Get help now"
            assert flag["text"] == symptoms_module.RED_FLAGS[key]["text"]
            assert flag["prominent"] is (severity == 3)
            assert listing(client, day(0), day(0))[-1]["red_flag"] == flag  # the list says the same
    assert {s["symptom"] for s in listing(client) if s["red_flag"]} == RED_FLAG_KEYS
    assert [s["red_flag"]["level"] for s in listing(client) if s["symptom"] == "breathlessness"] == ["emergency"] * 3
    assert [s["red_flag"]["level"] for s in listing(client) if s["symptom"] == "swelling"] == ["today"] * 3


def test_the_app_never_names_a_cause_a_treatment_or_a_dose_about_a_symptom():
    forbidden = re.compile(r"\b(because|causes|caused|due to|dose[sd]?|dosing|insulin|medicine|medication|treat\w*|"
                           r"take|\d+\s*(?:mg|g|units?|ml))\b", re.I)
    for key, entry in symptoms_module.RED_FLAGS.items():
        assert not forbidden.search(entry["text"]), key


def test_the_other_features_do_not_read_the_symptoms_table():
    """Symptoms are never sent to an AI provider or the assistant: the code that builds those requests does not read them."""
    reads = re.compile(r"(?:FROM|INTO|JOIN|UPDATE)\s+symptoms\b|\bimport\s+symptoms\b|from\s+\.+\s*symptoms\b|from\s+\.+symptoms\s+import|"
                       r"\bapp\.symptoms\b", re.I)
    checked = 0
    for path in [*(ROOT / "app" / "ai").rglob("*.py"), *(ROOT / "app" / "mcp").rglob("*.py"), *(ROOT / "app" / "guidance").rglob("*.py"),
                 ROOT / "app" / "vision.py"]:
        checked += 1
        assert not reads.search(path.read_text(encoding="utf-8")), path
    assert checked > 10


# --------------------------------------------------------------------------- security: sign-in, CSRF, isolation, deletion


def test_every_symptoms_route_is_covered_by_the_auth_test_and_answers_401_when_signed_out(anon_client):
    ops = test_auth_coverage.api_operations(anon_client.app)
    for op in (("get", "/api/symptoms"), ("post", "/api/symptoms"), ("put", "/api/symptoms/{symptom_id}"),
               ("delete", "/api/symptoms/{symptom_id}")):
        assert op in ops, op
    assert anon_client.get("/api/symptoms", params={"start": day(1), "end": day(0)}).status_code == 401
    assert anon_client.post("/api/symptoms", json=body()).status_code == 401
    assert anon_client.put("/api/symptoms/1", json=body()).status_code == 401
    assert anon_client.delete("/api/symptoms/1").status_code == 401


def test_writes_need_the_csrf_header(settings):
    with TestClient(create_app(settings), headers={}) as bare:
        login = {"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD}
        assert bare.post("/api/auth/login", json=login, headers={"X-Requested-With": "kidney-health"}).status_code == 200
        r = bare.post("/api/symptoms", json=body())
        assert r.status_code == 403 and r.json() == {"detail": "Missing X-Requested-With header"}
        assert bare.put("/api/symptoms/1", json=body()).status_code == 403
        assert bare.delete("/api/symptoms/1").status_code == 403
        assert bare.get("/api/symptoms", params={"start": day(1), "end": day(0)}).status_code == 200
        assert bare.post("/api/symptoms", json=body(), headers={"X-Requested-With": "kidney-health"}).status_code == 201


def test_a_second_person_never_sees_or_changes_the_first_persons_symptoms(two_clients):
    a, b = two_clients
    mine = make(a, "swelling", 3, note="A's note")
    assert listing(b) == []
    assert b.put(f"/api/symptoms/{mine['id']}", json=body("cramps", 1)).status_code == 404
    assert b.delete(f"/api/symptoms/{mine['id']}").status_code == 404
    assert listing(a) == [mine]  # B's attempts changed nothing
    theirs = make(b, "itching", 1, note="B's note")
    assert [s["id"] for s in listing(a)] == [mine["id"]] and [s["id"] for s in listing(b)] == [theirs["id"]]
    assert a.delete(f"/api/symptoms/{theirs['id']}").status_code == 404
    # the export of each holds only their own
    for client, own, other in ((a, "A's note", "B's note"), (b, "B's note", "A's note")):
        doc = export_doc(client)
        assert [s["note"] for s in doc["symptoms"]] == [own]
        with zipfile.ZipFile(io.BytesIO(client.get("/api/me/export.zip").content)) as z:
            text = z.read("symptoms.csv").decode("utf-8")
        assert own in text and other not in text
    # a file that carries ids of the other person's rows still writes only into the importer's account
    doc = export_doc(a)
    doc["symptoms"][0]["id"] = theirs["id"]
    r = post_import(b, doc, merge=True)
    assert r.status_code == 200, r.text
    assert [s["note"] for s in listing(a)] == ["A's note"] and sorted(s["note"] for s in listing(b)) == ["A's note", "B's note"]


def test_deleting_an_account_deletes_its_symptoms_and_only_its_own(two_clients):
    admin, sam = two_clients
    sam_id = sam.get("/api/me").json()["id"]
    make(admin, "swelling", 2)
    make(sam, "breathlessness", 3)
    make(sam, "other", 1)
    conn = sqlite3.connect(admin.app.state.settings.db_path)
    assert conn.execute("SELECT COUNT(*) FROM symptoms WHERE user_id = ?", (sam_id,)).fetchone()[0] == 2
    r = sam.request("DELETE", "/api/me", json={"password": USER_PASSWORD, "confirm": "DELETE"})
    assert r.status_code == 204
    assert conn.execute("SELECT COUNT(*) FROM symptoms WHERE user_id = ?", (sam_id,)).fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM symptoms").fetchone()[0] == 1
    conn.close()
    assert [s["symptom"] for s in listing(admin)] == ["swelling"]


def test_symptoms_are_never_written_to_the_logs(client, caplog):
    caplog.set_level("DEBUG")
    make(client, "other", 2, label="secret-label-xyzzy", note="secret-note-xyzzy")
    listing(client)
    assert "xyzzy" not in caplog.text


# --------------------------------------------------------------------------- the export


def test_the_export_holds_the_symptoms_in_both_forms(client):
    a = make(client, "swelling", 3, day(2), note="evening")
    b = make(client, "other", 1, day(1), label="=HYPERLINK(\"http://evil\")")
    r = client.get("/api/me/export.zip")
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        assert "symptoms.csv" in z.namelist() and "symptoms.csv" in z.read("README.txt").decode()
        doc = json.loads(z.read("export.json"))
        rows = list(csv.reader(io.StringIO(z.read("symptoms.csv").decode("utf-8"))))
    assert doc["version"] == 1 and doc["format"] == "kidney-health-export"  # an optional list: the version stays 1
    assert doc["symptoms"] == [
        {"id": a["id"], "date": day(2), "symptom": "swelling", "label": "", "severity": 3, "note": "evening", "created_at": a["created_at"]},
        {"id": b["id"], "date": day(1), "symptom": "other", "label": "=HYPERLINK(\"http://evil\")", "severity": 1, "note": "",
         "created_at": b["created_at"]},
    ]
    assert rows[0] == list(symptoms_module.CSV_COLUMNS)
    assert rows[1][:4] == [str(a["id"]), day(2), "swelling", ""] and rows[2][3] == "'=HYPERLINK(\"http://evil\")"  # formula escaped


def test_an_account_with_no_symptoms_exports_an_empty_list(client):
    assert export_doc(client)["symptoms"] == []


# --------------------------------------------------------------------------- the import


@pytest.fixture
def fresh(tmp_path, foods_json):
    """A second, empty server (person B's)."""
    with signed_in_client(make_settings(tmp_path / "second", foods_json)) as c:
        yield c


def test_symptoms_round_trip_into_another_server(client, fresh):
    make(client, "swelling", 3, day(3), note="legs\nand ankles")
    make(client, "other", 2, day(2), label="Dry mouth")
    make(client, "tiredness", 1, day(2))
    make(client, "tiredness", 1, day(2))  # the same twice stays twice
    doc = export_doc(client)
    r = post_import(fresh, doc)
    assert r.status_code == 200, r.text
    answer = r.json()
    assert answer["counts"]["symptoms"] == 4 and answer["file"]["records"]["symptoms"] == 4
    assert answer["already_there"]["symptoms"] == 0 and answer["skipped"]["total"] == 0
    assert [{k: v for k, v in s.items() if k not in ("id", "created_at")} for s in listing(fresh)] == \
        [{k: v for k, v in s.items() if k not in ("id", "created_at")} for s in listing(client)]
    assert [s["created_at"] for s in listing(fresh)] == [s["created_at"] for s in listing(client)]
    events = [e for e in fresh.get("/api/me/activity").json()["events"] if e["action"] == "data.imported"]
    assert events[0]["details"]["symptoms"] == 4
    assert export_doc(fresh)["symptoms"][0]["note"] == "legs\nand ankles"


def test_a_dry_run_counts_and_writes_nothing(client, fresh):
    make(client, "cramps", 2)
    r = post_import(fresh, export_doc(client), dry_run=True)
    assert r.status_code == 200 and r.json()["counts"]["symptoms"] == 1 and r.json()["imported"] is False
    assert listing(fresh) == []


def test_an_account_that_has_symptoms_needs_add_to_my_existing_data_and_then_adds_only_what_is_new(client, fresh):
    make(client, "cramps", 2, day(1))
    make(client, "tiredness", 1, day(1))
    doc = export_doc(client)
    assert post_import(fresh, doc).status_code == 200
    blocked = post_import(fresh, doc)
    assert blocked.status_code == 409 and blocked.json()["blocked"]["existing"]["symptoms"] == 2
    assert len(listing(fresh)) == 2
    again = post_import(fresh, doc, merge=True)
    assert again.status_code == 200 and again.json()["counts"]["symptoms"] == 0 and again.json()["already_there"]["symptoms"] == 2
    make(client, "nausea", 3, day(0))
    more = post_import(fresh, export_doc(client), merge=True)
    assert more.json()["counts"]["symptoms"] == 1 and more.json()["already_there"]["symptoms"] == 2
    assert [s["symptom"] for s in listing(fresh)] == ["cramps", "tiredness", "nausea"]
    # an account that has only symptoms counts as having data
    other_doc = {"format": "kidney-health-export", "version": 1}
    assert post_import(fresh, other_doc).status_code == 409


def test_an_older_file_without_symptoms_still_imports(client, fresh):
    make(client, "cramps", 2)
    doc = export_doc(client)
    del doc["symptoms"]
    r = post_import(fresh, doc)
    assert r.status_code == 200 and r.json()["counts"]["symptoms"] == 0 and listing(fresh) == []


def one_symptom(client: TestClient) -> dict[str, Any]:
    make(client, "swelling", 2, day(1), note="n")
    doc = export_doc(client)
    return doc


@pytest.mark.parametrize("edit, where", [
    (lambda s: s.__setitem__("symptom", "headache"), "symptoms[0].symptom"),
    (lambda s: s.__setitem__("severity", 4), "symptoms[0].severity"),
    (lambda s: s.__setitem__("severity", 0), "symptoms[0].severity"),
    (lambda s: s.__setitem__("severity", "2"), "symptoms[0].severity"),  # strict: a number, not text
    (lambda s: s.__setitem__("severity", True), "symptoms[0].severity"),
    (lambda s: s.__setitem__("date", "2999-01-01"), "symptoms[0]"),
    (lambda s: s.__setitem__("date", "yesterday"), "symptoms[0]"),
    (lambda s: s.__setitem__("note", "x" * (MAX_SYMPTOM_NOTE + 1)), "symptoms[0].note"),
    (lambda s: s.__setitem__("note", "bad\x00"), "symptoms[0]"),
    (lambda s: s.__setitem__("label", "not allowed here"), "symptoms[0]"),  # a label belongs to "other" only
    (lambda s: s.__setitem__("symptom", "other"), "symptoms[0]"),  # "other" with no label
    (lambda s: s.__setitem__("label", "y" * (MAX_SYMPTOM_LABEL + 1)), "symptoms[0].label"),
    (lambda s: s.__setitem__("created_at", "yesterday"), "symptoms[0].created_at"),
    (lambda s: s.__setitem__("id", 0), "symptoms[0].id"),
    (lambda s: s.__setitem__("user_id", 2), "symptoms[0].user_id"),
    (lambda s: s.pop("severity"), "symptoms[0].severity"),
    (lambda s: s.pop("date"), "symptoms[0].date"),
])
def test_a_bad_symptom_in_a_file_refuses_the_whole_file_and_names_it(client, fresh, edit, where):
    doc = one_symptom(client)
    edit(doc["symptoms"][0])
    r = post_import(fresh, doc)
    assert r.status_code == 400, r.text
    assert where in r.json()["detail"], r.json()
    assert listing(fresh) == []


def test_the_list_in_a_file_is_bounded_and_a_crowded_day_is_skipped_and_reported(client, fresh):
    from app.data_import import MAX_SYMPTOMS

    doc = one_symptom(client)
    row = doc["symptoms"][0]
    r = post_import(fresh, {**doc, "symptoms": [row] * (MAX_SYMPTOMS + 1)}, dry_run=True)
    assert r.status_code == 400 and "symptoms" in r.json()["detail"]
    crowded = [{**row, "id": i + 1} for i in range(MAX_SYMPTOMS_PER_DAY + 2)]
    r = post_import(fresh, {**doc, "symptoms": crowded})
    assert r.status_code == 200, r.text
    answer = r.json()
    assert answer["counts"]["symptoms"] == MAX_SYMPTOMS_PER_DAY and answer["skipped"]["by_kind"] == {"symptoms": 2}
    assert answer["skipped"]["shown"][0]["kind"] == "symptoms" and "30 symptoms" in answer["skipped"]["shown"][0]["reason"]
    assert len(listing(fresh, day(1), day(1))) == MAX_SYMPTOMS_PER_DAY


def test_ids_in_a_file_never_decide_ids_here(client, fresh):
    make(client, "swelling", 1)
    make(client, "cramps", 1)
    doc = export_doc(client)
    doc["symptoms"][0]["id"], doc["symptoms"][1]["id"] = 900, 5
    assert post_import(fresh, doc).status_code == 200
    ids = [s["id"] for s in listing(fresh)]
    assert ids == [1, 2] and [s["symptom"] for s in listing(fresh)] == ["swelling", "cramps"]
