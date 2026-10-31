"""The Care team (design note 25; ``app/sharing.py``, schema step 27).

Covered: inviting by user name (the same answer whether or not the name is an account, your own name, the limits, a newer invite
replacing the older, cancel, accept, decline, lapse), the two roles (old shares become Viewer, the role changes in one place and a
Care helper always sees the food log), every Care helper write (allowed for a Care helper; refused for a Viewer, a stopped,
expired or replaced share, a disabled account, the switch off), isolation (a helper of Ana reaches neither Kim's log nor their
own through Ana's share), what a helper may never touch (eaten food, a planned low treatment), "added by", the shopping list, Plan
several days without saved meals, the activity rows and the once-a-day count, and the migration of old shares.
"""
from __future__ import annotations

import sqlite3
from datetime import date, timedelta
from typing import Any

import pytest

from app import db, migrations, sharing
from conftest import USER_PASSWORD, TestClient, add_user, find_food, insert_users, log_food
from test_sharing import audit_rows, code_of, make_link, switch
from test_mcp import set_targets
from test_sharing import db as open_db

TODAY = date.today().isoformat()
TOMORROW = (date.today() + timedelta(days=1)).isoformat()

# Every write a helper can make on someone else's data, and the one check (a sharing.care_* dependency) each must go through.
WRITE_CHECKS = {
    ("post", "/api/shared/{share_id}/log"): sharing.care_helper,
    ("post", "/api/shared/{share_id}/log/batch"): sharing.care_helper,
    ("put", "/api/shared/{share_id}/log/{entry_id}"): sharing.care_helper,
    ("delete", "/api/shared/{share_id}/log/{entry_id}"): sharing.care_helper,
    ("post", "/api/shared/{share_id}/log/clear-planned"): sharing.care_planner,
    ("post", "/api/shared/{share_id}/guidance/plan-days"): sharing.care_planner,
    ("post", "/api/shared/{share_id}/meals/{meal_id}/apply"): sharing.care_saved_meals,  # design note 29 §4
    ("post", "/api/shared/{share_id}/suggestions"): sharing.care_suggester,  # design note 29 §5
}
READ_CHECKS = {
    ("get", "/api/shared/{share_id}/foods"): sharing.care_food_search,
    ("get", "/api/shared/{share_id}/plan/shopping"): sharing.care_planner,
    ("get", "/api/shared/{share_id}/meals"): sharing.care_saved_meals,
}
HELPER_WRITES = set(WRITE_CHECKS)
HELPER_READS = set(READ_CHECKS)


@pytest.fixture
def team(two_clients: tuple[TestClient, TestClient]) -> tuple[TestClient, TestClient, TestClient]:
    """(ana: the admin whose Care team it is, sam: her helper, kim: someone else with their own log) with sharing on."""
    ana, sam = two_clients
    switch(ana)
    kim = add_user(ana, "kim")
    return ana, sam, kim


def uid(client: TestClient) -> int:
    return int(client.get("/api/me").json()["id"])


def invite(owner: TestClient, username: str, role: str = "care_helper", areas: list[str] | None = None, **extra: Any) -> dict[str, Any]:
    r = owner.post("/api/me/shares/invite", json={"username": username, "role": role, "areas": areas or ["labs"], **extra})
    assert r.status_code == 201, r.text
    return r.json()


def join(owner: TestClient, helper: TestClient, username: str = "sam", role: str = "care_helper", **extra: Any) -> int:
    made = invite(owner, username, role, **extra)
    mine = helper.get("/api/shared").json()["invites"]
    assert [i["id"] for i in mine] == [made["id"]]
    r = helper.post(f"/api/shared/invites/{made['id']}/accept")
    assert r.status_code == 201, r.text
    return int(r.json()["id"])


def planned(client: TestClient, query: str, day: str = TOMORROW, **extra: Any) -> dict[str, Any]:
    return log_food(client, query, date=day, status="planned", **extra)


# --------------------------------------------------------------------------- inviting by user name


def test_an_invite_answers_the_same_whether_or_not_the_name_is_an_account(team):
    ana, sam, _ = team
    real = ana.post("/api/me/shares/invite", json={"username": "Sam", "role": "viewer", "areas": ["labs"]})
    ghost = ana.post("/api/me/shares/invite", json={"username": "nobody-here", "role": "viewer", "areas": ["labs"]})
    assert real.status_code == ghost.status_code == 201
    a, b = real.json(), ghost.json()
    assert set(a) == set(b) == {"id", "username", "areas", "role", "days", "created_at", "expires_at", *sharing.SWITCHES}
    assert (a["username"], b["username"]) == ("sam", "nobody-here")
    assert {k: v for k, v in a.items() if k not in ("id", "username", "created_at", "expires_at")} == \
        {k: v for k, v in b.items() if k not in ("id", "username", "created_at", "expires_at")}
    waiting = ana.get("/api/me/shares").json()["invites"]
    assert [i["username"] for i in waiting] == ["sam", "nobody-here"]  # both wait the same way
    assert [i["username"] for i in sam.get("/api/shared").json()["invites"]] == ["admin"]


def test_a_disabled_account_is_invited_like_a_name_nobody_has(team):
    ana, sam, kim = team
    kim_id = uid(kim)
    assert ana.patch(f"/api/admin/users/{kim_id}", json={"status": "disabled"}).status_code == 200
    made = invite(ana, "kim")
    assert ana.patch(f"/api/admin/users/{kim_id}", json={"status": "active"}).status_code == 200
    kim = TestClient(ana.app, base_url=str(ana.base_url))
    assert kim.post("/api/auth/login", json={"username": "kim", "password": USER_PASSWORD}).status_code == 200
    assert kim.get("/api/shared").json()["invites"] == []
    assert made["username"] == "kim"


def test_your_own_name_is_refused(team):
    ana, _, _ = team
    r = ana.post("/api/me/shares/invite", json={"username": " ADMIN ", "areas": ["food"]})
    assert r.status_code == 400 and r.json()["detail"] == sharing.OWN_NAME


def test_inviting_needs_a_recent_password_and_is_rate_limited(team, fake_clock):
    ana, _, _ = team
    fake_clock.advance(hours=2)
    r = ana.post("/api/me/shares/invite", json={"username": "sam", "areas": ["food"]})
    assert r.status_code == 403 and r.json().get("reauth_required") is True
    fake_clock.advance(hours=-2)
    answers = []
    for i in range(21):
        answers.append(ana.post("/api/me/shares/invite", json={"username": f"x{i % 3}", "areas": ["food"]}).status_code)
    assert answers[:20] == [201] * 20 and answers[20] == 429


def test_at_most_five_waiting_and_a_newer_invite_replaces_the_older(team):
    ana, sam, _ = team
    first = invite(ana, "sam", "viewer")
    second = invite(ana, "sam", "care_helper", areas=["labs", "body"])
    assert [i["id"] for i in ana.get("/api/me/shares").json()["invites"]] == [second["id"]]
    assert [(i["id"], i["role"]) for i in sam.get("/api/shared").json()["invites"]] == [(second["id"], "care_helper")]
    assert sam.post(f"/api/shared/invites/{first['id']}/accept").status_code == 404
    for i in range(sharing.MAX_INVITES - 1):
        invite(ana, f"p{i}")
    r = ana.post("/api/me/shares/invite", json={"username": "one-more", "areas": ["food"]})
    assert r.status_code == 409 and r.json()["detail"] == sharing.TOO_MANY_INVITES


def test_cancel_accept_decline_and_lapse(team, fake_clock):
    ana, sam, kim = team
    made = invite(ana, "sam")
    assert kim.post(f"/api/shared/invites/{made['id']}/accept").status_code == 404  # not hers
    assert kim.delete(f"/api/me/shares/invites/{made['id']}").status_code == 404
    assert ana.delete(f"/api/me/shares/invites/{made['id']}").status_code == 204
    assert sam.get("/api/shared").json()["invites"] == []
    assert sam.post(f"/api/shared/invites/{made['id']}/accept").status_code == 404

    declined = invite(ana, "sam")
    assert sam.post(f"/api/shared/invites/{declined['id']}/decline").status_code == 204
    assert ana.get("/api/me/shares").json()["invites"] == [] and ana.get("/api/me/shares").json()["sharing"] == []
    answered = audit_rows(ana, "care.invite_answered")
    assert answered[-1]["target_id"] == str(uid(ana)) and '"answer":"declined"' in answered[-1]["details_json"]

    late = invite(ana, "sam")
    fake_clock.advance(days=sharing.INVITE_DAYS, seconds=1)
    assert sam.get("/api/shared").json()["invites"] == [] and ana.get("/api/me/shares").json()["invites"] == []
    assert sam.post(f"/api/shared/invites/{late['id']}/accept").status_code == 404


def test_accepting_makes_a_share_with_the_role_and_the_food_log(team):
    ana, sam, _ = team
    sid = join(ana, sam, areas=["labs"], days=30)
    person = sam.get("/api/shared").json()["people"][0]
    assert person["id"] == sid and person["role"] == "care_helper" and person["areas"] == ["food", "labs"] and person["until"]
    mine = ana.get("/api/me/shares").json()
    assert mine["invites"] == [] and [(s["username"], s["role"]) for s in mine["sharing"]] == [("sam", "care_helper")]
    assert mine["roles"] == ["viewer", "care_helper", "caregiver"]
    # a newer invite replaces the share, as a newer link does
    sid2 = join(ana, sam, role="viewer", areas=["body"])
    people = sam.get("/api/shared").json()["people"]
    assert [(p["id"], p["role"], p["areas"]) for p in people] == [(sid2, "viewer", ["body"])]


def test_the_activity_holds_the_invite_the_answer_and_no_name(team):
    ana, sam, _ = team
    sid = join(ana, sam)
    ana.put(f"/api/me/shares/{sid}/role", json={"role": "viewer"})
    sam.delete(f"/api/shared/{sid}")
    rows = audit_rows(ana, "care.invited") + audit_rows(ana, "care.invite_answered")
    assert len(rows) == 2 and all("sam" not in r["details_json"] for r in rows)
    actions = [e["action"] for e in ana.get("/api/me/activity").json()["events"]]
    assert {"care.invited", "care.invite_answered", "care.role_changed", "share.ended"} <= set(actions)
    # the helper's own activity does not hold the person's rows
    assert not {"care.invited", "care.role_changed"} & {e["action"] for e in sam.get("/api/me/activity").json()["events"]}


# --------------------------------------------------------------------------- roles


def test_a_link_can_make_a_care_helper_and_old_links_make_viewers(team):
    ana, sam, kim = team
    plain = make_link(ana, ["labs"])
    assert plain["code"]["role"] == "viewer"
    r = ana.post("/api/me/shares", json={"areas": ["labs"], "role": "care_helper"})
    assert r.status_code == 201 and r.json()["code"]["role"] == "care_helper" and r.json()["code"]["areas"] == ["food", "labs"]
    info = kim.post("/api/shared/info", json={"code": code_of(r.json())}).json()
    assert info["role"] == "care_helper"
    assert kim.post("/api/shared/accept", json={"code": code_of(r.json())}).json()["role"] == "care_helper"


def test_the_person_changes_the_role_in_one_place(team):
    ana, sam, kim = team
    sid = join(ana, sam, role="viewer", areas=["labs"])
    assert sam.post(f"/api/shared/{sid}/log", json=_entry(ana)).status_code == 404
    r = ana.put(f"/api/me/shares/{sid}/role", json={"role": "care_helper"})
    assert r.status_code == 200 and r.json()["role"] == "care_helper" and r.json()["areas"] == ["food", "labs"]
    assert sam.post(f"/api/shared/{sid}/log", json=_entry(ana)).status_code == 201
    assert ana.put(f"/api/me/shares/{sid}/role", json={"role": "viewer"}).json()["role"] == "viewer"
    assert sam.post(f"/api/shared/{sid}/log", json=_entry(ana)).status_code == 404  # the very next request
    assert kim.put(f"/api/me/shares/{sid}/role", json={"role": "care_helper"}).status_code == 404
    assert sam.put(f"/api/me/shares/{sid}/role", json={"role": "care_helper"}).status_code == 404
    assert ana.put(f"/api/me/shares/{sid}/role", json={"role": "custom"}).status_code == 400  # Custom is never chosen, only seen
    rows = audit_rows(ana, "care.role_changed")
    assert len(rows) == 2 and '"food_added":true' in rows[0]["details_json"]


def test_the_migration_makes_old_shares_viewers(tmp_path):
    path = tmp_path / "kidney.db"
    conn = db.connect(path)
    db.migrate(conn, migrations.steps()[:26])
    insert_users(conn, [(1, "admin"), (2, "sam")])
    conn.execute("INSERT INTO shares (owner_user_id, grantee_user_id, areas, created_at, accepted_at) VALUES (1, 2, '[\"food\"]', 'x', 'x')")
    conn.commit()
    conn.close()
    conn = db.connect(path)
    assert db.migrate(conn)[0] == 27
    assert [tuple(r) for r in conn.execute("SELECT role, helper_changes FROM shares")] == [("viewer", None)]
    assert db.migrate(conn) == []
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE shares SET role = 'caregiver'")
    assert "added_by_user_id" in [r[1] for r in conn.execute("PRAGMA table_info(log_entries)")]
    conn.execute("INSERT INTO care_invites (owner_user_id, invitee_user_id, username, areas, role, created_at, expires_at) "
                 "VALUES (1, 2, 'sam', '[\"food\"]', 'viewer', 'x', 'y')")
    with pytest.raises(sqlite3.IntegrityError):  # never yourself
        conn.execute("INSERT INTO care_invites (owner_user_id, invitee_user_id, username, areas, role, created_at, expires_at) "
                     "VALUES (1, 1, 'admin', '[\"food\"]', 'viewer', 'x', 'y')")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("DELETE FROM users WHERE id = 2")
    assert conn.execute("SELECT COUNT(*) FROM care_invites").fetchone()[0] == 0
    conn.close()


def test_step_27_follows_step_26():
    step = migrations.steps()[26]
    assert step.version == 27 and step.name == "m027_care_team" and step.atomic and step.foreign_key_check


# --------------------------------------------------------------------------- the Care helper's writes


def _entry(owner: TestClient, query: str = "apple", day: str = TOMORROW, **extra: Any) -> dict[str, Any]:
    return {"date": day, "meal": "lunch", "food_id": find_food(owner, query)["id"], "servings": 1, **extra}


def test_every_helper_write_goes_through_the_one_check():
    from app import care_suggestions

    wanted = {**WRITE_CHECKS, **READ_CHECKS}
    seen = {}
    for route in [*sharing.shared_router.routes, *care_suggestions.shared_router.routes]:
        for method in route.methods:
            if (method.lower(), route.path) in wanted:
                deps, stack = [], [route.dependant]
                while stack:
                    d = stack.pop()
                    deps.append(d.call)
                    stack.extend(d.dependencies)
                seen[(method.lower(), route.path)] = wanted[(method.lower(), route.path)] in deps
    assert seen == {k: True for k in wanted}


def test_a_care_helper_plans_changes_and_removes_planned_food(team):
    ana, sam, _ = team
    sid = join(ana, sam)
    added = sam.post(f"/api/shared/{sid}/log", json=_entry(ana))
    assert added.status_code == 201
    e = added.json()
    assert e["status"] == "planned" and e["added_by"] == "sam"
    # the person sees who added it, on their own day
    day = ana.get("/api/log", params={"date": TOMORROW}).json()
    assert [(x["id"], x["added_by"]) for x in day["entries"]] == [(e["id"], "sam")]
    assert sam.get("/api/log", params={"date": TOMORROW}).json()["entries"] == []  # never in the helper's own log

    changed = sam.put(f"/api/shared/{sid}/log/{e['id']}", json={"servings": 2, "meal": "dinner"})
    assert changed.status_code == 200 and changed.json()["servings"] == 2 and changed.json()["meal"] == "dinner"
    assert changed.json()["status"] == "planned"
    stale = sam.put(f"/api/shared/{sid}/log/{e['id']}", json={"servings": 3}, headers={"If-Match": f'"{e["version"]}"'})
    assert stale.status_code == 412
    assert sam.put(f"/api/shared/{sid}/log/{e['id']}", json={"status": "eaten"}).status_code == 404  # a Care helper never logs eaten food
    assert sam.put(f"/api/shared/{sid}/log/{e['id']}", json={"status": "planned"}).status_code == 400  # nothing ever goes back to planned
    assert sam.put(f"/api/shared/{sid}/log/{e['id']}", json={"purpose": "none"}).status_code == 400
    assert sam.delete(f"/api/shared/{sid}/log/{e['id']}").status_code == 204
    assert ana.get("/api/log", params={"date": TOMORROW}).json()["entries"] == []


def test_a_care_helper_may_change_the_persons_own_planned_food(team):
    ana, sam, _ = team
    sid = join(ana, sam)
    own = planned(ana, "apple")
    assert own["added_by"] is None
    assert sam.put(f"/api/shared/{sid}/log/{own['id']}", json={"servings": 0.5}).status_code == 200
    assert sam.delete(f"/api/shared/{sid}/log/{own['id']}").status_code == 204


def test_a_care_helper_never_adds_or_changes_eaten_food(team):
    ana, sam, _ = team
    sid = join(ana, sam)
    r = sam.post(f"/api/shared/{sid}/log", json=_entry(ana, status="eaten"))
    assert r.status_code == 404 and r.json()["detail"] == sharing.NOT_SHARED  # logging eaten food is a Caregiver's switch
    r = sam.post(f"/api/shared/{sid}/log/batch", json={"entries": [_entry(ana), _entry(ana, status="eaten")]})
    assert r.status_code == 404 and ana.get("/api/log", params={"date": TOMORROW}).json()["entries"] == []
    eaten = log_food(ana, "banana", date=TODAY)
    assert sam.put(f"/api/shared/{sid}/log/{eaten['id']}", json={"servings": 2}).status_code == 404
    assert sam.delete(f"/api/shared/{sid}/log/{eaten['id']}").status_code == 404
    assert sam.post(f"/api/shared/{sid}/log/clear-planned", json={"start": TODAY, "end": TODAY}).json() == {"deleted": 0}
    assert ana.get("/api/log", params={"date": TODAY}).json()["entries"][0]["servings"] == 1


def test_a_planned_low_treatment_is_never_changed_or_removed_by_a_helper(team):
    ana, sam, _ = team
    sid = join(ana, sam)
    low = planned(ana, "glucose")
    assert low["purpose"] == "hypo"
    other = planned(ana, "apple")
    for r in (sam.put(f"/api/shared/{sid}/log/{low['id']}", json={"servings": 0.5}), sam.delete(f"/api/shared/{sid}/log/{low['id']}")):
        assert r.status_code == 403 and r.json()["detail"] == "Only admin can change or remove a low treatment."
    cleared = sam.post(f"/api/shared/{sid}/log/clear-planned", json={"start": TOMORROW, "end": TOMORROW})
    assert cleared.status_code == 200 and cleared.json() == {"deleted": 1}
    ids = sam.post(f"/api/shared/{sid}/log/clear-planned", json={"start": TOMORROW, "end": TOMORROW, "ids": [low["id"]]})
    assert ids.status_code == 200 and ids.json() == {"deleted": 0}
    left = ana.get("/api/log", params={"date": TOMORROW}).json()["entries"]
    assert [(x["id"], x["servings"]) for x in left] == [(low["id"], 1)] and other["id"] not in [x["id"] for x in left]
    # a helper may plan a low treatment: nothing blocks or warns against treating a low
    added = sam.post(f"/api/shared/{sid}/log", json=_entry(ana, "glucose"))
    assert added.status_code == 201 and added.json()["purpose"] == "hypo"


def test_a_batch_is_all_or_nothing_and_counts_as_one_change(team):
    ana, sam, _ = team
    sid = join(ana, sam)
    r = sam.post(f"/api/shared/{sid}/log/batch", json={"entries": [_entry(ana), _entry(ana, "banana", day=TODAY)]})
    assert r.status_code == 201 and [e["added_by"] for e in r.json()["entries"]] == ["sam", "sam"]
    bad = sam.post(f"/api/shared/{sid}/log/batch", json={"entries": [_entry(ana), {**_entry(ana), "food_id": 999999}]})
    assert bad.status_code == 404
    assert len(ana.get("/api/log", params={"date": TOMORROW}).json()["entries"]) == 1


def test_a_helpers_own_food_is_not_the_persons(team):
    ana, sam, _ = team
    sid = join(ana, sam)
    mine = sam.post("/api/foods", json={"name": "Sam's soup", "serving_desc": "1 bowl", "serving_g": 250, "nutrients": {"potassium_mg": 100}})
    assert mine.status_code == 201, mine.text
    r = sam.post(f"/api/shared/{sid}/log", json={**_entry(ana), "food_id": mine.json()["id"]})
    assert r.status_code == 404
    found = sam.get(f"/api/shared/{sid}/foods", params={"q": "soup"}).json()["foods"]
    assert found == []
    assert [f["name"] for f in sam.get(f"/api/shared/{sid}/foods", params={"q": "apple"}).json()["foods"]][:1] == ["Apple, raw, with skin"]


def test_isolation_a_helper_of_ana_reaches_neither_kim_nor_their_own_log(team):
    ana, sam, kim = team
    sid = join(ana, sam)
    kims = planned(kim, "apple")
    sams = planned(sam, "apple")
    for entry in (kims, sams):
        assert sam.put(f"/api/shared/{sid}/log/{entry['id']}", json={"servings": 4}).status_code == 404
        assert sam.delete(f"/api/shared/{sid}/log/{entry['id']}").status_code == 404
    r = sam.post(f"/api/shared/{sid}/log/clear-planned", json={"start": TOMORROW, "end": TOMORROW, "ids": [kims["id"]]})
    assert r.status_code == 404
    sam.post(f"/api/shared/{sid}/log/clear-planned", json={"start": TOMORROW, "end": TOMORROW})
    assert len(kim.get("/api/log", params={"date": TOMORROW}).json()["entries"]) == 1
    assert len(sam.get("/api/log", params={"date": TOMORROW}).json()["entries"]) == 1
    # Kim is on nobody's team: Ana's share id is 404 for her, read or write
    assert kim.post(f"/api/shared/{sid}/log", json=_entry(ana)).status_code == 404
    assert kim.get(f"/api/shared/{sid}/plan/shopping", params={"start": TODAY, "end": TOMORROW}).status_code == 404


def _all_writes(sam: TestClient, sid: int, entry_id: int, body: dict[str, Any]) -> list[int]:
    return [
        sam.post(f"/api/shared/{sid}/log", json=body).status_code,
        sam.post(f"/api/shared/{sid}/log/batch", json={"entries": [body]}).status_code,
        sam.put(f"/api/shared/{sid}/log/{entry_id}", json={"servings": 2}).status_code,
        sam.delete(f"/api/shared/{sid}/log/{entry_id}").status_code,
        sam.post(f"/api/shared/{sid}/log/clear-planned", json={"start": TOMORROW, "end": TOMORROW}).status_code,
        sam.post(f"/api/shared/{sid}/guidance/plan-days", json={"start": TOMORROW, "days": 1}).status_code,
        sam.get(f"/api/shared/{sid}/plan/shopping", params={"start": TODAY, "end": TOMORROW}).status_code,
        sam.get(f"/api/shared/{sid}/foods", params={"q": "apple"}).status_code,
    ]


@pytest.mark.parametrize("how", ["viewer", "stopped_by_person", "left_by_helper", "expired", "person_disabled", "switch_off",
                                 "replaced", "admin_ended", "food_not_shared"])
def test_every_write_is_refused_unless_the_share_is_a_care_helper_now(team, fake_clock, how):
    ana, sam, kim = team
    kim_id = uid(kim)
    if how == "person_disabled":  # kim is the person here so that the admin can turn her account off
        owner = kim
        sid = join(kim, sam)
    else:
        owner = ana
        sid = join(ana, sam, role="viewer" if how in ("viewer", "food_not_shared") else "care_helper",
                   **({"days": 1} if how == "expired" else {}))
    entry = planned(owner, "apple")
    body = _entry(owner)
    if how == "stopped_by_person":
        assert owner.delete(f"/api/me/shares/{sid}").status_code == 204
    elif how == "left_by_helper":
        assert sam.delete(f"/api/shared/{sid}").status_code == 204
    elif how == "expired":
        fake_clock.advance(days=1, seconds=1)
    elif how == "person_disabled":
        assert ana.patch(f"/api/admin/users/{kim_id}", json={"status": "disabled"}).status_code == 200
    elif how == "switch_off":
        switch(ana, False)
    elif how == "replaced":
        join(ana, sam, role="care_helper")  # the old share id stops working
    elif how == "admin_ended":
        assert ana.delete(f"/api/admin/users/{uid(sam)}/shares").status_code == 200
    elif how == "food_not_shared":  # a Viewer of labs only; a Care helper role cannot exist without the food log
        with open_db(ana) as conn:
            assert conn.execute("SELECT areas FROM shares WHERE id = ?", (sid,)).fetchone()[0] == '["labs"]'
            conn.execute("UPDATE shares SET role = 'care_helper', may_plan = 1, may_log = 1, may_suggest = 1, "
                         "may_use_saved_meals = 1 WHERE id = ?", (sid,))
            conn.commit()
    got = _all_writes(sam, sid, entry["id"], body)
    assert got == [404] * len(got), (how, got)
    if how == "person_disabled":
        assert ana.patch(f"/api/admin/users/{kim_id}", json={"status": "active"}).status_code == 200
        owner = TestClient(ana.app, base_url=str(ana.base_url))
        assert owner.post("/api/auth/login", json={"username": "kim", "password": USER_PASSWORD}).status_code == 200
    assert [x["id"] for x in owner.get("/api/log", params={"date": TOMORROW}).json()["entries"]] == [entry["id"]]


def test_a_disabled_helper_cannot_write(team):
    ana, sam, _ = team
    sid = join(ana, sam)
    entry = planned(ana, "apple")
    assert ana.patch(f"/api/admin/users/{uid(sam)}", json={"status": "disabled"}).status_code == 200
    assert all(code in (401, 403, 404) for code in _all_writes(sam, sid, entry["id"], _entry(ana)))
    assert [x["id"] for x in ana.get("/api/log", params={"date": TOMORROW}).json()["entries"]] == [entry["id"]]


def test_the_shopping_list_is_the_persons(team):
    ana, sam, _ = team
    sid = join(ana, sam)
    planned(ana, "apple")
    planned(sam, "banana")
    got = sam.get(f"/api/shared/{sid}/plan/shopping", params={"start": TODAY, "end": TOMORROW})
    want = ana.get("/api/plan/shopping", params={"start": TODAY, "end": TOMORROW})
    assert got.status_code == 200 and got.json() == want.json()
    assert [i["food_name"] for i in got.json()["items"]] == ["Apple, raw, with skin"]


def test_plan_several_days_for_the_person_never_uses_saved_meals(team, monkeypatch):
    ana, sam, _ = team
    sid = join(ana, sam)
    set_targets(ana)
    from app.guidance import api as guidance_api

    seen: dict[str, Any] = {}
    real = guidance_api.plan_days

    def spy(ctx, days, meals, **kw):
        seen.update(kw)
        return real(ctx, days, meals, **kw)

    monkeypatch.setattr(guidance_api, "plan_days", spy)
    r = sam.post(f"/api/shared/{sid}/guidance/plan-days", json={"start": TOMORROW, "days": 2, "use_saved_meals": True})
    assert r.status_code == 200, r.text
    assert "days" in r.json(), r.json()
    assert seen["use_saved_meals"] is False
    # the answer is planned against Ana's targets, not Sam's
    assert r.json()["targets"] == ana.post("/api/guidance/plan-days", json={"start": TOMORROW, "days": 2}).json()["targets"]


def test_the_once_a_day_activity_row_and_the_count(team, fake_clock):
    ana, sam, _ = team
    sid = join(ana, sam)
    e = sam.post(f"/api/shared/{sid}/log", json=_entry(ana)).json()
    sam.post(f"/api/shared/{sid}/log/batch", json={"entries": [_entry(ana), _entry(ana)]})
    sam.put(f"/api/shared/{sid}/log/{e['id']}", json={"servings": 2})
    sam.delete(f"/api/shared/{sid}/log/{e['id']}")
    rows = audit_rows(ana, "care.plan_changed")
    assert len(rows) == 1 and rows[0]["target_id"] == str(uid(ana)) and rows[0]["actor_user_id"] == uid(sam)
    item = ana.get("/api/me/shares").json()["sharing"][0]
    assert {k: item["helper_changes"][k] for k in ("added", "changed", "removed")} == {"added": 3, "changed": 1, "removed": 1}
    fake_clock.advance(days=1)
    sam.post(f"/api/shared/{sid}/log", json=_entry(ana))
    assert len(audit_rows(ana, "care.plan_changed")) == 2
    item = ana.get("/api/me/shares").json()["sharing"][0]
    assert item["helper_changes"]["added"] == 1 and item["helper_changes"]["removed"] == 0


def test_added_by_follows_the_helpers_account(team):
    ana, sam, _ = team
    sid = join(ana, sam)
    assert sam.patch("/api/me", json={"display_name": "Sam Lee"}).status_code == 200
    e = sam.post(f"/api/shared/{sid}/log", json=_entry(ana)).json()
    assert e["added_by"] == "Sam Lee"
    with open_db(ana) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("DELETE FROM users WHERE username = 'sam'")
        conn.commit()
    left = ana.get("/api/log", params={"date": TOMORROW}).json()["entries"]
    assert [(x["id"], x["added_by"]) for x in left] == [(e["id"], None)]


def test_the_export_and_the_version_leave_added_by_out(team):
    ana, sam, _ = team
    sid = join(ana, sam)
    by_helper = sam.post(f"/api/shared/{sid}/log", json=_entry(ana)).json()
    own = planned(ana, "apple", meal="lunch")
    assert by_helper["version"] == own["version"]  # the same content has the same version
    with open_db(ana) as conn:
        assert conn.execute("SELECT added_by_user_id FROM log_entries WHERE id = ?", (by_helper["id"],)).fetchone()[0] == uid(sam)
    from app.account import export_data

    with open_db(ana) as conn:
        exported = export_data(conn, uid(ana), app_version="test")["log_entries"]
    assert exported and all("added_by" not in e and "added_by_user_id" not in e for e in exported)


def test_signing_in_as_the_helper_does_not_change_the_password_rules(team):
    """A helper signs in with their own password; nothing about the Care team touches credentials."""
    _, sam, _ = team
    assert sam.post("/api/auth/reauth", json={"password": USER_PASSWORD}).status_code == 200
