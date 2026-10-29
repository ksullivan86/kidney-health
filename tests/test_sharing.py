"""Read-only sharing with a caregiver or dietitian (design note 19; ``app/sharing.py``, schema step 24).

Covered: the link (made once with a recent password, shown once, works once, 7 days, the limits of 5 links and 10 shares, your own
link, a wrong or used or cancelled link: the same 404, a newer link replacing the areas, a time limit), the one check for every
``/api/shared/{id}/…`` read (another person's share, an ended share, an area not shared, a disabled owner: the same 404), that a
shared answer equals the owner's own, that no write route exists under ``/api/shared``, the daily view audit, both sides stopping,
the switch and ``AUTH_MODE=none``, the admin's count and removal, and account deletion of either side.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import date, timedelta
from typing import Any

import pytest

from app import sharing
from app.main import create_app
from conftest import ADMIN_PASSWORD, USER_PASSWORD, TestClient, add_user, log_food, make_settings
from test_body import bp, w
from test_symptoms import body as symptom

TODAY = date.today().isoformat()


def switch(admin: TestClient, on: bool = True) -> None:
    r = admin.patch("/api/admin/settings", json={"sharing.enabled": on})
    assert r.status_code == 200, r.text


def db(client: TestClient) -> sqlite3.Connection:
    conn = sqlite3.connect(client.app.state.settings.db_path)
    conn.row_factory = sqlite3.Row
    return conn


def make_link(client: TestClient, areas: list[str] | None = None) -> dict[str, Any]:
    r = client.post("/api/me/shares", json={"areas": areas or list(sharing.AREAS)})
    assert r.status_code == 201, r.text
    return r.json()


def code_of(made: dict[str, Any]) -> str:
    return made["link"].split("#/share/", 1)[1]


def share(owner: TestClient, grantee: TestClient, areas: list[str] | None = None) -> int:
    r = grantee.post("/api/shared/accept", json={"code": code_of(make_link(owner, areas))})
    assert r.status_code == 201, r.text
    return int(r.json()["id"])


def audit_rows(client: TestClient, action: str) -> list[sqlite3.Row]:
    with db(client) as conn:
        return conn.execute("SELECT * FROM audit_log WHERE action = ? ORDER BY id", (action,)).fetchall()


@pytest.fixture
def people(two_clients: tuple[TestClient, TestClient]) -> tuple[TestClient, TestClient, TestClient]:
    """(ana: the admin who shares, sam: who accepts, kim: a third person) with sharing on."""
    ana, sam = two_clients
    switch(ana)
    kim = add_user(ana, "kim")
    return ana, sam, kim


# --------------------------------------------------------------------------- the link


def test_a_link_is_shown_once_works_once_and_lists_on_both_sides(people):
    ana, sam, _ = people
    made = make_link(ana, ["food", "labs"])
    assert made["link"].startswith(f"{str(ana.base_url).rstrip('/')}/#/share/")
    assert made["code"]["areas"] == ["food", "labs"]
    listed = ana.get("/api/me/shares").json()
    assert listed["enabled"] is True and listed["sharing"] == [] and [c["id"] for c in listed["codes"]] == [made["code"]["id"]]
    assert "link" not in str(listed) and code_of(made) not in str(listed)

    info = sam.post("/api/shared/info", json={"code": code_of(made)})
    assert info.status_code == 200 and info.json()["username"] == "admin" and info.json()["areas"] == ["food", "labs"]
    assert ana.get("/api/me/shares").json()["codes"], "info does not use the link up"

    accepted = sam.post("/api/shared/accept", json={"code": code_of(made)})
    assert accepted.status_code == 201
    person = accepted.json()
    assert person["username"] == "admin" and person["areas"] == ["food", "labs"] and person["since"]
    assert sam.get("/api/shared").json()["people"] == [person]
    mine = ana.get("/api/me/shares").json()
    assert mine["codes"] == [] and [(s["username"], s["areas"], s["active"]) for s in mine["sharing"]] == [("sam", ["food", "labs"], True)]
    again = sam.post("/api/shared/accept", json={"code": code_of(made)})
    assert again.status_code == 404 and again.json()["detail"] == sharing.BAD_LINK
    with db(ana) as conn:
        row = conn.execute("SELECT code_id, verifier_hash, grantee_user_id FROM shares").fetchone()
    assert row["code_id"] is None and row["verifier_hash"] is None and row["grantee_user_id"] is not None


def test_wrong_cancelled_and_expired_links_are_the_same_404(people, fake_clock):
    ana, sam, _ = people
    made = make_link(ana)
    code = code_of(made)
    for bad in ("", "nonsense", code[:-1] + ("A" if code[-1] != "A" else "B"), "0" * 16 + "." + code.split(".")[1]):
        r = sam.post("/api/shared/info", json={"code": bad or "x"})
        assert r.status_code == 404 and r.json()["detail"] == sharing.BAD_LINK, bad
    assert ana.delete(f"/api/me/shares/{made['code']['id']}").status_code == 204
    assert sam.post("/api/shared/accept", json={"code": code}).status_code == 404
    late = make_link(ana)
    fake_clock.advance(days=sharing.CODE_DAYS, seconds=1)
    assert sam.post("/api/shared/accept", json={"code": code_of(late)}).status_code == 404
    assert ana.get("/api/me/shares").json()["codes"] == []


def test_your_own_link_is_refused(people):
    ana, _, _ = people
    r = ana.post("/api/shared/accept", json={"code": code_of(make_link(ana))})
    assert r.status_code == 400 and r.json()["detail"] == sharing.OWN_LINK


def test_at_most_five_unused_links_and_ten_people(people):
    ana, sam, _ = people
    links = [make_link(ana) for _ in range(sharing.MAX_CODES)]
    r = ana.post("/api/me/shares", json={"areas": ["food"]})
    assert r.status_code == 409 and r.json()["detail"] == sharing.TOO_MANY_CODES
    for made in links:
        ana.delete(f"/api/me/shares/{made['code']['id']}")
    with db(ana) as conn:  # nine more people already share with... ana shares with ten people
        for i in range(sharing.MAX_SHARES):
            uid = conn.execute("INSERT INTO users (username, username_norm, role, status, created_at, updated_at) "
                               "VALUES (?, ?, 'user', 'active', 'x', 'x')", (f"p{i}", f"p{i}")).lastrowid
            conn.execute("INSERT INTO shares (owner_user_id, grantee_user_id, areas, created_at, accepted_at) VALUES (1, ?, '[\"food\"]', 'x', 'x')",
                         (uid,))
        conn.commit()
    r = ana.post("/api/me/shares", json={"areas": ["food"]})
    assert r.status_code == 409 and r.json()["detail"] == sharing.TOO_MANY_SHARES


def test_a_newer_link_from_the_same_person_replaces_the_areas(people):
    ana, sam, _ = people
    first = share(ana, sam, ["food"])
    second = share(ana, sam, ["labs", "body"])
    assert second != first
    assert [(p["id"], p["areas"]) for p in sam.get("/api/shared").json()["people"]] == [(second, ["labs", "body"])]
    assert sam.get(f"/api/shared/{first}/log").status_code == 404
    with db(ana) as conn:
        assert conn.execute("SELECT ended_by FROM shares WHERE id = ?", (first,)).fetchone()[0] == "replaced"


def test_a_share_can_end_on_a_date(people, fake_clock):
    ana, sam, _ = people
    r = ana.post("/api/me/shares", json={"areas": ["food"], "days": 1})
    assert r.status_code == 201 and r.json()["code"]["days"] == 1
    code = code_of(r.json())
    assert sam.post("/api/shared/info", json={"code": code}).json()["days"] == 1
    person = sam.post("/api/shared/accept", json={"code": code}).json()
    assert person["until"] and person["until"] > person["since"]
    assert ana.get("/api/me/shares").json()["sharing"][0]["until"] == person["until"]
    assert sam.get(f"/api/shared/{person['id']}/log").status_code == 200
    fake_clock.advance(hours=23)
    assert sam.get(f"/api/shared/{person['id']}/log").status_code == 200
    fake_clock.advance(hours=1, seconds=1)
    r = sam.get(f"/api/shared/{person['id']}/log")
    assert r.status_code == 404 and r.json()["detail"] == sharing.NOT_SHARED
    assert sam.get("/api/shared").json()["people"] == [] and ana.get("/api/me/shares").json()["sharing"] == []
    ended = audit_rows(ana, "share.ended")
    assert len(ended) == 1 and ended[0]["actor_user_id"] is None and json.loads(ended[0]["details_json"])["by"] == "time"
    assert "share.ended" in {e["action"] for e in ana.get("/api/me/activity").json()["events"]}


def test_without_days_a_share_lasts_until_stopped(people, fake_clock):
    ana, sam, _ = people
    sid = share(ana, sam, ["labs"])
    assert sam.get("/api/shared").json()["people"][0]["until"] is None
    fake_clock.advance(days=13)
    assert sam.get(f"/api/shared/{sid}/labs").status_code == 200


@pytest.mark.parametrize("days", [0, 366, -1, 1.5, "a month"])
def test_the_time_limit_is_one_to_365_days(people, days):
    ana, _, _ = people
    assert ana.post("/api/me/shares", json={"areas": ["food"], "days": days}).status_code == 400


def test_a_newer_link_brings_its_own_end_date(people):
    ana, sam, _ = people
    share(ana, sam, ["food"])
    r = ana.post("/api/me/shares", json={"areas": ["food"], "days": 30})
    person = sam.post("/api/shared/accept", json={"code": code_of(r.json())}).json()
    assert person["until"] is not None
    share(ana, sam, ["food"])
    assert sam.get("/api/shared").json()["people"][0]["until"] is None


def test_making_a_link_needs_a_recent_password(people, fake_clock):
    ana, _, _ = people
    fake_clock.advance(hours=2)
    r = ana.post("/api/me/shares", json={"areas": ["food"]})
    assert r.status_code == 403 and r.json().get("reauth_required") is True
    assert ana.post("/api/auth/reauth", json={"password": ADMIN_PASSWORD}).status_code == 200
    assert ana.post("/api/me/shares", json={"areas": ["food"]}).status_code == 201


@pytest.mark.parametrize("areas", [[], ["food", "nope"], ["preferences"]])
def test_only_the_four_areas_can_be_shared(people, areas):
    ana, _, _ = people
    assert ana.post("/api/me/shares", json={"areas": areas}).status_code == 400


def test_links_are_limited_to_twenty_tries_an_hour(people):
    _, sam, _ = people
    answers = [sam.post("/api/shared/info", json={"code": "0" * 16 + "." + "A" * 43}).status_code for _ in range(21)]
    assert answers[:20] == [404] * 20 and answers[20] == 429


# --------------------------------------------------------------------------- the reads


def fill(owner: TestClient) -> None:
    log_food(owner, "banana", date=TODAY)
    assert owner.post("/api/labs", json={"analyte": "potassium", "value": 4.8, "unit": "mmol/L", "taken_on": TODAY}).status_code == 201
    assert owner.post("/api/body/weights", json=w(71.5)).status_code == 201
    assert owner.post("/api/body/blood-pressure", json=bp(131, 82)).status_code == 201
    assert owner.post("/api/symptoms", json=symptom("cramps", 2)).status_code == 201


SAME = [  # (shared path, the owner's own path, area)
    ("log?date={d}", "/api/log?date={d}", "food"),
    ("log/summary?start={s}&end={d}", "/api/log/summary?start={s}&end={d}", "food"),
    ("log/range?start={s}&end={d}", "/api/log/range?start={s}&end={d}", "food"),
    ("labs", "/api/labs", "labs"),
    ("body/summary?date={d}", "/api/body/summary?date={d}", "body"),
    ("body/weights?start={s}&end={d}", "/api/body/weights?start={s}&end={d}", "body"),
    ("body/blood-pressure?start={s}&end={d}", "/api/body/blood-pressure?start={s}&end={d}", "body"),
    ("symptoms?start={s}&end={d}", "/api/symptoms?start={s}&end={d}", "symptoms"),
]


def test_each_shared_answer_is_the_owners_own(people):
    ana, sam, _ = people
    fill(ana)
    sid = share(ana, sam)
    start = (date.today() - timedelta(days=13)).isoformat()
    for shared_path, own_path, _area in SAME:
        got = sam.get(f"/api/shared/{sid}/" + shared_path.format(d=TODAY, s=start))
        want = ana.get(own_path.format(d=TODAY, s=start))
        assert got.status_code == 200 and want.status_code == 200, (shared_path, got.text)
        assert got.json() == want.json(), shared_path
    assert sam.get("/api/log", params={"date": TODAY}).json()["entries"] == []  # sam's own log is still his own


def test_the_shared_profile_holds_only_what_the_pages_need(people):
    ana, sam, _ = people
    ana.put("/api/profile", json={**ana.get("/api/profile").json(), "birth_month": "1960-04", "pregnant_or_breastfeeding": False})
    sid = share(ana, sam, ["labs"])
    got = sam.get(f"/api/shared/{sid}/profile")
    assert got.status_code == 200
    assert set(got.json()) == {"name", "ckd_stage", "dialysis", "diabetes", "dialysis_days", "week_start", "weight_kg", "targets"}
    assert got.json()["name"] == "admin" and got.json()["targets"] == ana.get("/api/profile").json()["targets"]


@pytest.mark.parametrize("shared_path,own_path,area", SAME)
def test_an_area_that_was_not_shared_is_404(people, shared_path, own_path, area):
    ana, sam, _ = people
    sid = share(ana, sam, [a for a in sharing.AREAS if a != area])
    r = sam.get(f"/api/shared/{sid}/" + shared_path.format(d=TODAY, s=TODAY))
    assert r.status_code == 404 and r.json()["detail"] == sharing.NOT_SHARED


def test_another_persons_ended_or_unknown_share_is_the_same_404(people):
    ana, sam, kim = people
    sid = share(ana, sam)
    for who, path in ((kim, f"/api/shared/{sid}/labs"), (ana, f"/api/shared/{sid}/labs"), (sam, "/api/shared/999999/labs"),
                      (kim, f"/api/shared/{sid}/profile")):
        r = who.get(path)
        assert r.status_code == 404 and r.json()["detail"] == sharing.NOT_SHARED, path
    assert kim.delete(f"/api/shared/{sid}").status_code == 404
    assert kim.delete(f"/api/me/shares/{sid}").status_code == 404 and sam.delete(f"/api/me/shares/{sid}").status_code == 404
    assert ana.delete(f"/api/me/shares/{sid}").status_code == 204
    assert sam.get(f"/api/shared/{sid}/labs").status_code == 404 and sam.get("/api/shared").json()["people"] == []
    assert ana.delete(f"/api/me/shares/{sid}").status_code == 404  # already ended


def test_a_disabled_owner_shares_nothing_until_enabled_again(people):
    ana, sam, kim = people
    kim_id = kim.get("/api/me").json()["id"]
    sid = share(kim, sam)
    assert ana.patch(f"/api/admin/users/{kim_id}", json={"status": "disabled"}).status_code == 200
    assert sam.get(f"/api/shared/{sid}/labs").status_code == 404 and sam.get("/api/shared").json()["people"] == []
    assert ana.patch(f"/api/admin/users/{kim_id}", json={"status": "active"}).status_code == 200
    assert sam.get(f"/api/shared/{sid}/labs").status_code == 200


def test_the_grantee_can_stop_seeing(people):
    ana, sam, _ = people
    sid = share(ana, sam)
    assert sam.delete(f"/api/shared/{sid}").status_code == 204
    assert sam.get(f"/api/shared/{sid}/profile").status_code == 404 and ana.get("/api/me/shares").json()["sharing"] == []
    ended = audit_rows(ana, "share.ended")
    assert ended[-1]["target_type"] == "user" and ended[-1]["target_id"] == str(ana.get("/api/me").json()["id"])


def test_there_is_no_write_route_under_shared(people):
    ana, _, _ = people
    from test_auth_coverage import _walk

    writes = {(m, p) for m, p, _ in _walk(ana.app.routes) if p.startswith("/api/shared") and m not in ("get", "head")}
    assert writes == {("post", "/api/shared/info"), ("post", "/api/shared/accept"), ("delete", "/api/shared/{share_id}")}


def test_a_view_is_written_to_the_owners_activity_once_a_day(people, fake_clock):
    ana, sam, _ = people
    sid = share(ana, sam)
    for _ in range(3):
        assert sam.get(f"/api/shared/{sid}/labs").status_code == 200
    assert len(audit_rows(ana, "share.viewed")) == 1
    seen = ana.get("/api/me/shares").json()["sharing"][0]["last_viewed_at"]
    assert seen
    fake_clock.advance(days=1)
    sam.get(f"/api/shared/{sid}/profile")
    assert len(audit_rows(ana, "share.viewed")) == 2
    actions = {e["action"] for e in ana.get("/api/me/activity").json()["events"]}
    assert {"share.code_created", "share.accepted", "share.viewed"} <= actions


# --------------------------------------------------------------------------- the switch, the modes, the admin


def test_while_the_switch_is_off_everything_is_404_and_shares_come_back(people):
    ana, sam, _ = people
    sid = share(ana, sam)
    switch(ana, False)
    assert ana.get("/api/me/shares").json() == {"enabled": False, "areas": list(sharing.AREAS), "max": sharing.MAX_SHARES,
                                               "sharing": [], "codes": []}
    for r in (ana.post("/api/me/shares", json={"areas": ["food"]}), sam.get("/api/shared"), sam.get(f"/api/shared/{sid}/labs"),
              sam.post("/api/shared/info", json={"code": "x"}), sam.delete(f"/api/shared/{sid}")):
        assert r.status_code == 404
    switch(ana, True)
    assert sam.get(f"/api/shared/{sid}/labs").status_code == 200


def test_the_switch_is_off_by_default(two_clients):
    ana, _ = two_clients
    assert ana.get("/api/me/shares").json()["enabled"] is False
    assert ana.post("/api/me/shares", json={"areas": ["food"]}).status_code == 404


def test_no_sign_in_mode_has_no_sharing(tmp_path, foods_json):
    settings = make_settings(tmp_path, foods_json, auth_mode="none")
    with TestClient(create_app(settings)) as c:
        c.patch("/api/admin/settings", json={"sharing.enabled": True})
        assert c.get("/api/me/shares").status_code == 404 and c.get("/api/shared").status_code == 404


def test_the_admin_sees_counts_and_can_end_every_share_of_a_person(people):
    ana, sam, kim = people
    share(ana, sam)
    share(kim, sam)
    make_link(kim)
    sam_id = sam.get("/api/me").json()["id"]
    counts = {u["username"]: u["shares"] for u in ana.get("/api/admin/users").json()["users"]}
    assert counts == {"admin": 1, "sam": 2, "kim": 2}
    r = ana.delete(f"/api/admin/users/{sam_id}/shares")
    assert r.status_code == 200 and r.json() == {"ended": 2}
    assert sam.get("/api/shared").json()["people"] == [] and kim.get("/api/me/shares").json()["codes"]  # kim's unused link stays
    assert audit_rows(ana, "share.ended")[-1]["actor_user_id"] == 1


def test_deleting_either_account_deletes_its_shares(people):
    ana, sam, kim = people
    share(kim, sam)
    share(sam, kim)
    share(ana, kim)
    assert kim.request("DELETE", "/api/me", json={"password": USER_PASSWORD, "confirm": "DELETE"}).status_code == 204
    with db(ana) as conn:
        assert conn.execute("SELECT COUNT(*) FROM shares").fetchone()[0] == 0


def test_the_audit_rows_hold_no_link_or_code(people):
    ana, sam, _ = people
    made = make_link(ana)
    sam.post("/api/shared/accept", json={"code": code_of(made)})
    with db(ana) as conn:
        text = " ".join(str(tuple(r)) for r in conn.execute("SELECT * FROM audit_log WHERE action LIKE 'share.%'"))
    assert code_of(made).split(".")[1] not in text and code_of(made).split(".")[0] not in text

