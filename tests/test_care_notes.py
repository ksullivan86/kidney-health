"""Notes from the Care team (design note 37 phase 1; ``app/care_notes.py``, ``app/sharing.py``, schema step 36).

Covered: the two server switches (the Care team and ``care_notes.enabled``, off by default), the Clinician preset (Viewer plus
``may_note``, no food log added, stored as ``viewer``), writing, reading (``If-Match``, ``read_at``, ``412`` after an edit),
editing and withdrawing only while unread, the text check (lows and dosing words only), the limits (1,000 characters, 10 a day
per author per person, 500 kept, the day, the area), the person deleting a note, the activity rows (never the text), the hourly
view rows of a share with notes on, the export (the person's notes only), account deletion of either side, ``AUTH_MODE=none``,
no admin route and no AI reading the table, the isolation matrix of every note route, and schema step 36 on a database at
step 34 or 35.
"""
from __future__ import annotations

import sqlite3
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest

from app import care_notes, db, migrations, sharing
from app.main import create_app
from conftest import USER_PASSWORD, TestClient, add_user, insert_users, make_settings
from test_care_team import join, uid
from test_sharing import audit_rows, switch
from test_sharing import db as open_db

ROOT = Path(__file__).resolve().parents[1]
TODAY = date.today().isoformat()
NOW = "2026-11-12T08:00:00.000000Z"


def notes_switch(admin: TestClient, on: bool = True) -> None:
    r = admin.patch("/api/admin/settings", json={"care_notes.enabled": on})
    assert r.status_code == 200, r.text


@pytest.fixture
def team(two_clients: tuple[TestClient, TestClient]) -> tuple[TestClient, TestClient, TestClient]:
    """(ana: the admin whose Care team it is, sam: her clinician-to-be, kim: someone else) with the Care team and notes on."""
    ana, sam = two_clients
    switch(ana)
    notes_switch(ana)
    return ana, sam, add_user(ana, "kim")


def clinician(owner: TestClient, member: TestClient, username: str = "sam", areas: list[str] | None = None) -> int:
    return join(owner, member, username=username, role="clinician", areas=areas or ["labs"])


def write(member: TestClient, sid: int, body: str = "Your potassium was lower this week. Keep that up.", **extra: Any) -> dict[str, Any]:
    r = member.post(f"/api/shared/{sid}/notes", json={"body": body, **extra})
    assert r.status_code == 201, r.text
    return r.json()


def tag(note: dict[str, Any]) -> dict[str, str]:
    return {"If-Match": f'"{note["version"]}"'}


def mine(client: TestClient) -> dict[str, Any]:
    r = client.get("/api/me/notes")
    assert r.status_code == 200, r.text
    return r.json()


# --------------------------------------------------------------------------- the switches and the preset


def test_notes_are_off_by_default_and_need_both_switches(two_clients):
    ana, sam = two_clients
    switch(ana)
    assert mine(ana) == {"enabled": False, "unread": 0, "notes": []}
    assert ana.get("/api/me/shares").json()["notes"] is False
    r = ana.post("/api/me/shares/invite", json={"username": "sam", "areas": ["labs"], "role": "clinician"})
    assert r.status_code == 400 and r.json()["detail"] == sharing.NOTES_OFF
    assert ana.post("/api/me/shares", json={"areas": ["labs"], "role": "clinician"}).json()["detail"] == sharing.NOTES_OFF
    sid = join(ana, sam, role="viewer", areas=["labs"])
    assert ana.put(f"/api/me/shares/{sid}/switches", json={"may_note": True}).json()["detail"] == sharing.NOTES_OFF
    assert ana.put(f"/api/me/shares/{sid}/role", json={"role": "clinician"}).json()["detail"] == sharing.NOTES_OFF
    notes_switch(ana)
    assert ana.put(f"/api/me/shares/{sid}/role", json={"role": "clinician"}).json()["role"] == "clinician"
    note = write(sam, sid)
    assert sam.get("/api/shared").json()["notes"] is True and ana.get("/api/me/shares").json()["notes"] is True
    for on_sharing, on_notes in ((True, False), (False, True)):
        switch(ana, on_sharing)
        notes_switch(ana, on_notes)
        assert mine(ana) == {"enabled": False, "unread": 0, "notes": []}
        for r in (sam.post(f"/api/shared/{sid}/notes", json={"body": "Hello"}), sam.get(f"/api/shared/{sid}/notes"),
                  sam.put(f"/api/shared/{sid}/notes/{note['id']}", json={"body": "Hi"}, headers=tag(note)),
                  sam.delete(f"/api/shared/{sid}/notes/{note['id']}"),
                  ana.post(f"/api/me/notes/{note['id']}/read", headers=tag(note)), ana.delete(f"/api/me/notes/{note['id']}")):
            assert r.status_code == 404, r.text
    switch(ana, True)
    notes_switch(ana, True)  # turned on again, the notes are there again
    assert [n["id"] for n in mine(ana)["notes"]] == [note["id"]]


def test_the_clinician_is_a_viewer_who_may_write_notes(team):
    ana, sam, _ = team
    sid = clinician(ana, sam, areas=["labs"])
    person = sam.get("/api/shared").json()["people"][0]
    assert person["role"] == "clinician" and person["may_note"] is True and person["areas"] == ["labs"]  # no food log added
    assert {k: person[k] for k in sharing.SWITCHES} == sharing.PRESETS["clinician"]
    with open_db(ana) as conn:  # an older build reads a Viewer
        assert tuple(conn.execute("SELECT role, may_note FROM shares WHERE id = ?", (sid,)).fetchone()) == ("viewer", 1)
    item = ana.put(f"/api/me/shares/{sid}/switches", json={"may_suggest": True}).json()
    assert item["role"] == "custom" and item["areas"] == ["food", "labs"]  # suggesting needs the food log, notes do not
    item = ana.put(f"/api/me/shares/{sid}/switches", json={"may_suggest": False, "may_note": False, "areas": ["labs"]}).json()
    assert item["role"] == "viewer" and item["may_note"] is False
    rows = audit_rows(ana, "care.switches_changed")
    assert '"may_note":false' in rows[-1]["details_json"]
    item = ana.put(f"/api/me/shares/{sid}/role", json={"role": "clinician"}).json()
    assert item["role"] == "clinician" and '"may_note":true' in audit_rows(ana, "care.role_changed")[-1]["details_json"]
    assert sharing.role_of({"may_note": True}) == "clinician" and sharing.role_of({"may_note": True, "may_plan": True}) == "custom"
    made = ana.post("/api/me/shares", json={"areas": ["labs"], "role": "clinician"}).json()
    assert made["code"]["role"] == "clinician" and made["code"]["may_note"] is True and made["code"]["areas"] == ["labs"]


# --------------------------------------------------------------------------- writing, reading, editing, withdrawing


def test_a_note_is_written_read_once_and_then_fixed(team):
    ana, sam, _ = team
    sid = clinician(ana, sam, areas=["food", "labs"])
    note = write(sam, sid, "  Your potassium was lower on the days you swapped the potato for rice.\r\nKeep that up.  ",
                 area="food", date=TODAY)
    assert note["body"] == "Your potassium was lower on the days you swapped the potato for rice.\nKeep that up."
    assert note["version"] == 1 and note["read_at"] is None and note["area"] == "food" and note["date"] == TODAY
    got = mine(ana)
    assert got["enabled"] is True and got["unread"] == 1
    shown = got["notes"][0]
    assert shown["from"] == {"name": "sam", "removed": False} and shown["body"] == note["body"] and shown["edited_at"] is None
    assert ana.post(f"/api/me/notes/{note['id']}/read").status_code == 428  # the version shown is needed
    assert ana.post(f"/api/me/notes/{note['id']}/read", headers=tag(note)).status_code == 204
    assert ana.post(f"/api/me/notes/{note['id']}/read", headers={"If-Match": '"9"'}).status_code == 204  # already read
    got = mine(ana)
    assert got["unread"] == 0 and got["notes"][0]["read_at"]
    assert sam.get(f"/api/shared/{sid}/notes").json()["notes"][0]["read_at"] == got["notes"][0]["read_at"]
    r = sam.put(f"/api/shared/{sid}/notes/{note['id']}", json={"body": "Changed"}, headers=tag(note))
    assert r.status_code == 409 and r.json()["detail"] == care_notes.ALREADY_READ.format("admin")
    assert sam.delete(f"/api/shared/{sid}/notes/{note['id']}").status_code == 409
    assert mine(ana)["notes"][0]["body"] == note["body"]  # a note the person read is always the note they read
    assert audit_rows(ana, "care_note.written")[0]["target_id"] == str(uid(ana))
    assert all("potassium" not in r["details_json"] for r in audit_rows(ana, "care_note.written"))


def test_edit_and_withdraw_only_while_unread_with_if_match(team):
    ana, sam, _ = team
    sid = clinician(ana, sam)
    note = write(sam, sid, "First words")
    assert sam.put(f"/api/shared/{sid}/notes/{note['id']}", json={"body": "Second"}).status_code == 428
    r = sam.put(f"/api/shared/{sid}/notes/{note['id']}", json={"body": "Second"}, headers={"If-Match": '"7"'})
    assert r.status_code == 412 and r.json()["current"]["body"] == "First words"
    edited = sam.put(f"/api/shared/{sid}/notes/{note['id']}", json={"body": "Second words", "area": "labs"}, headers=tag(note)).json()
    assert edited["version"] == 2 and edited["edited_at"] and edited["area"] == "labs"
    same = sam.put(f"/api/shared/{sid}/notes/{note['id']}", json={"body": "Second words"}, headers=tag(edited)).json()
    assert same["version"] == 2  # nothing changed, no new version
    # the person's screen still shows the first text: marking it read is 412 with the text as it is now
    r = ana.post(f"/api/me/notes/{note['id']}/read", headers=tag(note))
    assert r.status_code == 412 and r.json()["current"]["body"] == "Second words"
    assert mine(ana)["notes"][0]["read_at"] is None
    assert ana.post(f"/api/me/notes/{note['id']}/read", headers=tag(edited)).status_code == 204
    other = write(sam, sid, "A second note")
    assert sam.delete(f"/api/shared/{sid}/notes/{other['id']}", headers={"If-Match": '"5"'}).status_code == 412
    assert sam.delete(f"/api/shared/{sid}/notes/{other['id']}", headers=tag(other)).status_code == 204
    assert [n["id"] for n in mine(ana)["notes"]] == [note["id"]]
    assert len(audit_rows(ana, "care_note.edited")) == 1 and len(audit_rows(ana, "care_note.withdrawn")) == 1
    assert "A second note" not in audit_rows(ana, "care_note.withdrawn")[0]["details_json"]
    events = {e["action"] for e in ana.get("/api/me/activity").json()["events"]}
    assert {"care_note.written", "care_note.edited", "care_note.withdrawn"} <= events
    assert not {"care_note.written"} & {e["action"] for e in sam.get("/api/me/activity").json()["events"]}


def test_the_person_deletes_any_note_and_it_is_gone_for_both(team):
    ana, sam, kim = team
    sid = clinician(ana, sam)
    note = write(sam, sid)
    assert kim.delete(f"/api/me/notes/{note['id']}").status_code == 404
    assert ana.delete(f"/api/me/notes/{note['id']}").status_code == 204
    assert ana.delete(f"/api/me/notes/{note['id']}").status_code == 404
    assert mine(ana)["notes"] == [] and sam.get(f"/api/shared/{sid}/notes").json()["notes"] == []
    row = audit_rows(ana, "care_note.deleted")[0]
    assert row["actor_user_id"] == uid(ana) and row["target_type"] == "care_note" and "potassium" not in row["details_json"]
    assert "care_note.deleted" in {e["action"] for e in ana.get("/api/me/activity").json()["events"]}


def test_the_persons_list_pages_newest_first(team):
    ana, sam, _ = team
    sid = clinician(ana, sam)
    ids = [write(sam, sid, f"Note number {i}")["id"] for i in range(4)]
    assert [n["id"] for n in mine(ana)["notes"]] == ids[::-1]
    page = ana.get("/api/me/notes", params={"limit": 2}).json()
    assert [n["id"] for n in page["notes"]] == ids[:1:-1] and page["unread"] == 4
    rest = ana.get("/api/me/notes", params={"limit": 2, "before": page["notes"][-1]["id"]}).json()
    assert [n["id"] for n in rest["notes"]] == ids[1::-1]
    assert ana.get("/api/me/notes", params={"limit": 51}).status_code in (400, 422)


# --------------------------------------------------------------------------- the text check and the limits


@pytest.mark.parametrize("text,ok", [
    ("Your potassium was lower on the days you swapped the potato for rice. Keep that up.", True),
    ("Your lab results look steadier. Let's talk about supplements at the visit.", True),  # words a dietitian needs
    ("This snack is safe on dialysis days.", True),
    ("Low-sodium soup is a good swap.", True),
    ("Take 2 units before lunch", False), ("Your insulin to carb ratio", False), ("One dose of the binder", False),
    ("If you feel shaky, treat it first", False), ("I'm low", False), ("Sugar was 3.2 earlier", False), ("A bolus before meals", False),
    ("ｉｎｓｕｌｉｎ in full-width letters", False),
])
def test_the_text_check_refuses_lows_and_dosing_only(team, text, ok):
    ana, sam, _ = team
    sid = clinician(ana, sam)
    r = sam.post(f"/api/shared/{sid}/notes", json={"body": text})
    if ok:
        assert r.status_code == 201, r.text
    else:
        assert r.status_code == 400 and r.json()["detail"] == care_notes.NOTE_REFUSED.format("admin")


def test_the_limits(team, fake_clock):
    ana, sam, _ = team
    sid = clinician(ana, sam, areas=["labs", "symptoms"])
    for body, why in (("", care_notes.EMPTY), ("   ", care_notes.EMPTY), ("a" * 1001, care_notes.TOO_LONG)):
        r = sam.post(f"/api/shared/{sid}/notes", json={"body": body})
        assert r.status_code == 400 and r.json()["detail"] == why
    assert sam.post(f"/api/shared/{sid}/notes", json={"body": "a" * 1000}).status_code == 201
    r = sam.post(f"/api/shared/{sid}/notes", json={"body": "About food", "area": "food"})
    assert r.status_code == 400 and r.json()["detail"] == care_notes.AREA_NOT_SHARED.format("admin")
    today = fake_clock.now().date()
    for day in ((today - timedelta(days=366)).isoformat(), (today + timedelta(days=2)).isoformat()):
        r = sam.post(f"/api/shared/{sid}/notes", json={"body": "Hello", "date": day})
        assert r.status_code == 400 and r.json()["detail"] == care_notes.BAD_DAY
    for bad in ({"body": "x", "date": "2026-02-30"}, {"body": "x", "area": "meals"}, {"body": "x", "author": "someone"}):
        assert sam.post(f"/api/shared/{sid}/notes", json=bad).status_code in (400, 422), bad
    first = write(sam, sid, "Two", area="symptoms", date=(today - timedelta(days=365)).isoformat())
    assert sam.delete(f"/api/shared/{sid}/notes/{first['id']}").status_code == 204  # a withdrawn note still counts
    for i in range(8):
        write(sam, sid, f"Note {i}")
    r = sam.post(f"/api/shared/{sid}/notes", json={"body": "Eleven"})
    assert r.status_code == 429 and r.json()["detail"] == care_notes.TOO_MANY_TODAY.format("admin")
    fake_clock.advance(days=1, seconds=1)
    write(sam, sid, "The next day")
    with open_db(ana) as conn:
        conn.executemany("INSERT INTO care_notes (owner_user_id, author_user_id, author_name, body, created_at) VALUES (?, ?, 'sam', 'x', ?)",
                         [(uid(ana), uid(sam), NOW)] * (care_notes.MAX_KEPT - 10))
        conn.commit()
    r = sam.post(f"/api/shared/{sid}/notes", json={"body": "Too many"})
    assert r.status_code == 409 and r.json()["detail"] == care_notes.TOO_MANY_KEPT.format("admin")


def test_the_constants():
    assert (care_notes.MAX_BODY, care_notes.MAX_PER_DAY, care_notes.MAX_KEPT) == (1000, 10, 500)
    assert care_notes.day_problem("2026-11-13", "2026-11-12") is None and care_notes.day_problem("2026-11-14", "2026-11-12")


# --------------------------------------------------------------------------- looks by a clinician


def test_a_share_with_notes_writes_a_look_per_area_per_hour(team, fake_clock):
    ana, sam, kim = team
    sid = clinician(ana, sam, areas=["food", "labs"])
    other = join(kim, sam, username="sam", role="viewer", areas=["labs"])
    for _ in range(3):
        assert sam.get(f"/api/shared/{sid}/labs").status_code == 200
    sam.get(f"/api/shared/{sid}/log", params={"date": TODAY})
    sam.get(f"/api/shared/{sid}/profile")  # no area: counted once a day, and a look was written today already
    rows = audit_rows(ana, "share.viewed")
    assert [r["details_json"].count('"area"') for r in rows] == [1, 1] and '"area":"labs"' in rows[0]["details_json"]
    assert ana.get("/api/me/shares").json()["sharing"][0]["last_viewed_area"] == "food"
    fake_clock.advance(hours=1)
    sam.get(f"/api/shared/{sid}/labs")
    assert len(audit_rows(ana, "share.viewed")) == 3
    assert all(r["ip_prefix"] is None for r in audit_rows(ana, "share.viewed"))
    # a share without notes keeps one look a day
    for _ in range(2):
        sam.get(f"/api/shared/{other}/labs")
    fake_clock.advance(hours=1)
    sam.get(f"/api/shared/{other}/labs")
    assert len([r for r in audit_rows(kim, "share.viewed") if r["target_id"] == str(uid(kim))]) == 1


# --------------------------------------------------------------------------- export, deletion, admin, AI


def test_the_export_holds_the_persons_notes_only(team):
    ana, sam, _ = team
    sid = clinician(ana, sam)
    write(sam, sid, "Soup night was a good choice", area="labs", date=TODAY)
    from app.account import export_data

    with open_db(ana) as conn:
        hers = export_data(conn, uid(ana), app_version="test")["care_notes"]
        his = export_data(conn, uid(sam), app_version="test")["care_notes"]
    assert his == []
    assert [(n["from"], n["body"], n["area"], n["date"]) for n in hers] == [("sam", "Soup night was a good choice", "labs", TODAY)]
    assert set(hers[0]) == {"date", "area", "from", "body", "created_at", "edited_at", "read_at"}
    from app import data_import

    assert "care_notes" in data_import.SKIPPED_SECTIONS


def test_deleting_the_authors_account_keeps_the_note_for_the_person(team):
    ana, sam, kim = team
    sid = clinician(ana, sam)
    note = write(sam, sid)
    other = clinician(kim, sam)
    write(sam, other, "For Kim")
    assert sam.request("DELETE", "/api/me", json={"password": USER_PASSWORD, "confirm": "DELETE"}).status_code == 204
    got = mine(ana)["notes"]
    assert [(n["id"], n["from"]) for n in got] == [(note["id"], {"name": "sam", "removed": True})]
    assert ana.post(f"/api/me/notes/{note['id']}/read", headers=tag(note)).status_code == 204
    # deleting the person's account deletes the notes written for them
    assert kim.request("DELETE", "/api/me", json={"password": USER_PASSWORD, "confirm": "DELETE"}).status_code == 204
    with open_db(ana) as conn:
        assert [r[0] for r in conn.execute("SELECT owner_user_id FROM care_notes")] == [uid(ana)]


def test_no_admin_route_and_no_ai_reads_notes(team):
    ana, _, _ = team
    from test_auth_coverage import _walk

    paths = {p for _, p, _ in _walk(ana.app.routes)}
    assert {p for p in paths if "notes" in p} == {"/api/me/notes", "/api/me/notes/{note_id}", "/api/me/notes/{note_id}/read",
                                                 "/api/shared/{share_id}/notes", "/api/shared/{share_id}/notes/{note_id}"}
    for package in ("ai", "mcp", "guidance"):
        for source in (ROOT / "app" / package).rglob("*.py"):
            assert "care_notes" not in source.read_text(encoding="utf-8"), source
    assert "notes" not in str(ana.get("/api/admin/users").json()["users"][0].keys())


def test_no_sign_in_mode_has_no_notes(tmp_path, foods_json):
    with TestClient(create_app(make_settings(tmp_path, foods_json, auth_mode="none"))) as c:
        c.patch("/api/admin/settings", json={"sharing.enabled": True, "care_notes.enabled": True})
        assert c.get("/api/me/notes").json() == {"enabled": False, "unread": 0, "notes": []}
        assert c.post("/api/shared/1/notes", json={"body": "Hi"}).status_code == 404
        assert c.delete("/api/me/notes/1").status_code == 404


# --------------------------------------------------------------------------- the isolation matrix


def _author_routes(client: TestClient, sid: int, note: dict[str, Any]) -> list[tuple[str, int]]:
    nid = note["id"]
    return [(f"POST {sid}", client.post(f"/api/shared/{sid}/notes", json={"body": "Hello"}).status_code),
            (f"GET {sid}", client.get(f"/api/shared/{sid}/notes").status_code),
            (f"PUT {sid}/{nid}", client.put(f"/api/shared/{sid}/notes/{nid}", json={"body": "Changed"}, headers=tag(note)).status_code),
            (f"DELETE {sid}/{nid}", client.delete(f"/api/shared/{sid}/notes/{nid}", headers=tag(note)).status_code)]


def test_a_note_is_only_ever_seen_by_the_person_and_its_author(team):
    ana, sam, kim = team
    sid = clinician(ana, sam)
    note = write(sam, sid)
    # kim is on ana's Care team too, without the notes switch: every note route is the one 404
    kim_sid = join(ana, kim, username="kim", role="viewer", areas=["labs"])
    assert all(code == 404 for _, code in _author_routes(kim, kim_sid, note))
    # kim's own share id with sam's note, and sam's share id for kim: 404
    assert all(code == 404 for _, code in _author_routes(kim, sid, note))
    assert kim.post(f"/api/me/notes/{note['id']}/read", headers=tag(note)).status_code == 404
    assert mine(kim)["notes"] == []
    # sam reaches ana's note only through ana's share: not through kim's
    sam_on_kim = clinician(kim, sam)
    assert sam.put(f"/api/shared/{sam_on_kim}/notes/{note['id']}", json={"body": "x"}, headers=tag(note)).status_code == 404
    assert sam.delete(f"/api/shared/{sam_on_kim}/notes/{note['id']}", headers=tag(note)).status_code == 404
    assert sam.get(f"/api/shared/{sam_on_kim}/notes").json()["notes"] == []
    # the person cannot change the author's text: there is no route for it
    assert ana.put(f"/api/me/notes/{note['id']}", json={"body": "Mine now"}).status_code == 405
    # after the share ends, the author reaches none of it and the person keeps the note
    assert ana.delete(f"/api/me/shares/{sid}").status_code == 204
    assert all(code == 404 for _, code in _author_routes(sam, sid, note))
    assert [n["id"] for n in mine(ana)["notes"]] == [note["id"]]
    from app.account import export_data

    with open_db(ana) as conn:
        assert export_data(conn, uid(sam), app_version="test")["care_notes"] == []
        assert export_data(conn, uid(kim), app_version="test")["care_notes"] == []


@pytest.mark.parametrize("how", ["switch off", "share stopped", "author left", "author disabled"])
def test_every_note_route_is_the_same_404_when_it_is_not_yours_now(team, how):
    ana, sam, _ = team
    sid = clinician(ana, sam)
    note = write(sam, sid)
    if how == "switch off":
        ana.put(f"/api/me/shares/{sid}/switches", json={"may_note": False})
    elif how == "share stopped":
        ana.delete(f"/api/me/shares/{sid}")
    elif how == "author left":
        sam.delete(f"/api/shared/{sid}")
    else:
        assert ana.patch(f"/api/admin/users/{uid(sam)}", json={"status": "disabled"}).status_code == 200
    for path, code in _author_routes(sam, sid, note):
        assert code in ((401, 404) if how == "author disabled" else (404,)), path
    assert [n["id"] for n in mine(ana)["notes"]] == [note["id"]]


# --------------------------------------------------------------------------- schema step 36


def _build(path: Path, through: list[migrations.Step]) -> None:
    conn = db.connect(path)
    assert db.migrate(conn, through) == [s.version for s in through]
    insert_users(conn, [(1, "admin"), (2, "sam")])
    conn.execute("INSERT INTO shares (id, owner_user_id, grantee_user_id, areas, created_at, accepted_at, role, may_plan) "
                 "VALUES (7, 1, 2, '[\"labs\"]', ?, ?, 'care_helper', 1)", (NOW, NOW))
    conn.execute("INSERT INTO care_invites (id, owner_user_id, invitee_user_id, username, areas, role, created_at, expires_at) "
                 "VALUES (3, 1, 2, 'sam', '[\"food\"]', 'viewer', ?, ?)", (NOW, NOW))
    conn.commit()
    conn.close()


@pytest.mark.parametrize("with_35", [False, True])
def test_step_36_runs_on_a_database_at_step_34_or_35(tmp_path, with_35):
    steps = migrations.steps()
    step36 = next(s for s in steps if s.version == 36)
    assert step36.name == "m036_care_notes" and step36.atomic and step36.foreign_key_check
    before = [s for s in steps if s.version <= (35 if with_35 else 34)]
    path = tmp_path / "kidney.db"
    _build(path, before)
    conn = db.connect(path)
    old = [tuple(r) for r in conn.execute("SELECT * FROM shares ORDER BY id")]
    assert db.migrate(conn, [*before, step36]) == [36]  # whether or not step 35 ran first
    assert [tuple(r)[:len(old[0])] for r in conn.execute("SELECT * FROM shares ORDER BY id")] == old
    assert conn.execute("SELECT may_note FROM shares").fetchall()[0][0] == 0
    assert conn.execute("SELECT may_note FROM care_invites").fetchall()[0][0] == 0
    step36.migrate(conn)  # again: nothing changes
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE shares SET may_note = 2 WHERE id = 7")
    conn.execute("INSERT INTO care_notes (owner_user_id, author_user_id, share_id, author_name, body, created_at) "
                 "VALUES (1, 2, 7, 'sam', 'Hello', ?)", (NOW,))
    for bad in ("INSERT INTO care_notes (owner_user_id, author_user_id, author_name, body, created_at) VALUES (1, 1, 'a', 'x', 'now')",
                "INSERT INTO care_notes (owner_user_id, author_user_id, author_name, body, created_at) VALUES (1, 2, 'a', '', 'now')",
                "INSERT INTO care_notes (owner_user_id, author_user_id, author_name, body, area, created_at) VALUES (1, 2, 'a', 'x', 'meals', 'now')"):
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(bad)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("DELETE FROM users WHERE id = 2")  # the author: the note stays, without its author or share
    assert tuple(conn.execute("SELECT owner_user_id, author_user_id, share_id, author_name FROM care_notes").fetchone()) == (1, None, None, "sam")
    conn.execute("DELETE FROM users WHERE id = 1")  # the person: the note goes
    assert conn.execute("SELECT COUNT(*) FROM care_notes").fetchone()[0] == 0
    conn.close()


def test_the_activity_list_names_the_note_events():
    from app.audit import ACTIONS, USER_VISIBLE_ACTIONS

    settings = (ROOT / "app" / "static" / "js" / "views" / "settings.js").read_text(encoding="utf-8")
    labels = settings[settings.index("const ACTION_LABEL = {"):settings.index("};", settings.index("const ACTION_LABEL = {"))]
    actions = sorted(a for a in ACTIONS if a.startswith("care_note."))
    assert actions == ["care_note.deleted", "care_note.edited", "care_note.withdrawn", "care_note.written"]
    for action in actions:
        assert action in USER_VISIBLE_ACTIONS and f"'{action}':" in labels, action
