"""The full Care team (design note 29; ``app/sharing.py``, ``app/care_suggestions.py``, schema step 31).

Covered: the switches and the roles over them (Custom, food added by any "Do" switch, the activity rows), a Caregiver who logs
eaten food ("Added by", the once-a-day row, the count), what no helper may do to a low treatment, eaten food only the helper added,
saved meals (off by default, listed and applied, never changed, Plan several days), suggestions (off by default, the fit, accept,
decline, the 14 days, the limits, the note and the low-treatment checks, the switch turned off, the share ended, the export), and
the isolation matrix of every new route: another person, a switch off and a Viewer are all the same ``404``.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pytest

from app import care_suggestions, sharing
from conftest import TestClient, add_user, find_food, log_food
from test_care_team import TODAY, TOMORROW, _entry, join, planned, uid
from test_sharing import audit_rows, code_of, switch
from test_sharing import db as open_db

LOW_SENTENCE = "Only admin can change or remove a low treatment."


@pytest.fixture
def team(two_clients: tuple[TestClient, TestClient]) -> tuple[TestClient, TestClient, TestClient]:
    """(ana: the admin whose Care team it is, sam: on it, kim: someone else) with sharing on, as in test_care_team.py."""
    ana, sam = two_clients
    switch(ana)
    return ana, sam, add_user(ana, "kim")


def set_switches(owner: TestClient, sid: int, **switches: Any) -> dict[str, Any]:
    r = owner.put(f"/api/me/shares/{sid}/switches", json=switches)
    assert r.status_code == 200, r.text
    return r.json()


def saved_meal(owner: TestClient, name: str = "Apple lunch") -> dict[str, Any]:
    apple, banana = find_food(owner, "apple"), find_food(owner, "banana")
    r = owner.post("/api/meals", json={"name": name, "items": [{"food_id": apple["id"], "servings": 1}, {"food_id": banana["id"], "servings": 2}]})
    assert r.status_code == 201, r.text
    return r.json()


def suggestion(owner: TestClient, query: str = "apple", day: str = TOMORROW, **extra: Any) -> dict[str, Any]:
    return {"date": day, "meal": "dinner", "items": [{"food_id": find_food(owner, query)["id"], "servings": 1}], **extra}


# --------------------------------------------------------------------------- the switches and the roles


def test_roles_are_presets_over_the_switches(team):
    ana, sam, _ = team
    sid = join(ana, sam, role="caregiver", areas=["labs"])
    person = sam.get("/api/shared").json()["people"][0]
    assert person["role"] == "caregiver" and person["areas"] == ["food", "labs"]
    assert {k: person[k] for k in sharing.SWITCHES} == sharing.PRESETS["caregiver"]
    item = set_switches(ana, sid, may_suggest=True)
    assert item["role"] == "custom" and item["may_suggest"] and item["may_log"]
    item = ana.put(f"/api/me/shares/{sid}/role", json={"role": "care_helper"}).json()
    assert item["role"] == "care_helper" and {k: item[k] for k in sharing.SWITCHES} == sharing.PRESETS["care_helper"]
    item = set_switches(ana, sid, may_plan=False)
    assert item["role"] == "viewer"
    with open_db(ana) as conn:  # the old role column follows planning, so an older build reads it right
        assert conn.execute("SELECT role FROM shares WHERE id = ?", (sid,)).fetchone()[0] == "viewer"
    item = set_switches(ana, sid, may_plan=True)
    with open_db(ana) as conn:
        assert conn.execute("SELECT role FROM shares WHERE id = ?", (sid,)).fetchone()[0] == "care_helper"
    rows = audit_rows(ana, "care.switches_changed")
    assert len(rows) == 3 and '"may_suggest":true' in rows[0]["details_json"] and '"role":"custom"' in rows[0]["details_json"]


def test_any_do_switch_shares_the_food_log_and_areas_change_in_place(team):
    ana, sam, _ = team
    sid = join(ana, sam, role="viewer", areas=["labs"])
    item = set_switches(ana, sid, may_suggest=True)
    assert item["areas"] == ["food", "labs"] and item["role"] == "custom"
    assert '"food_added":true' in audit_rows(ana, "care.switches_changed")[-1]["details_json"]
    item = set_switches(ana, sid, areas=["labs", "symptoms"])  # food stays while a "Do" switch needs it
    assert item["areas"] == ["food", "labs", "symptoms"]
    item = set_switches(ana, sid, may_suggest=False, areas=["symptoms"])
    assert item["areas"] == ["symptoms"] and item["role"] == "viewer"
    assert sam.get(f"/api/shared/{sid}/labs").status_code == 404 and sam.get(f"/api/shared/{sid}/symptoms", params={"start": TODAY, "end": TODAY}).status_code == 200
    for bad in ({"areas": []}, {"may_plan": None}, {"may_plan": "yes"}, {"role": "viewer"}, {"areas": ["meals"]}):
        assert ana.put(f"/api/me/shares/{sid}/switches", json=bad).status_code in (400, 422), bad


def test_only_the_person_changes_the_switches(team):
    ana, sam, kim = team
    sid = join(ana, sam, role="viewer")
    for who in (sam, kim):
        assert who.put(f"/api/me/shares/{sid}/switches", json={"may_log": True}).status_code == 404
        assert who.put(f"/api/me/shares/{sid}/role", json={"role": "caregiver"}).status_code == 404
    assert ana.delete(f"/api/me/shares/{sid}").status_code == 204
    assert ana.put(f"/api/me/shares/{sid}/switches", json={"may_log": True}).status_code == 404  # ended


def test_links_and_invites_carry_the_caregiver_role(team):
    ana, sam, kim = team
    r = ana.post("/api/me/shares", json={"areas": ["labs"], "role": "caregiver"})
    assert r.status_code == 201 and r.json()["code"]["role"] == "caregiver" and r.json()["code"]["areas"] == ["food", "labs"]
    assert kim.post("/api/shared/info", json={"code": code_of(r.json())}).json()["role"] == "caregiver"
    person = kim.post("/api/shared/accept", json={"code": code_of(r.json())}).json()
    assert person["role"] == "caregiver" and person["may_log"] is True
    made = ana.post("/api/me/shares/invite", json={"username": "sam", "role": "caregiver", "areas": ["food"]}).json()
    assert made["role"] == "caregiver" and made["may_log"] is True
    assert sam.get("/api/shared").json()["invites"][0]["may_log"] is True


# --------------------------------------------------------------------------- a Caregiver logs eaten food


def test_a_caregiver_logs_eaten_food_with_added_by_and_one_row_a_day(team, fake_clock):
    ana, sam, _ = team
    sid = join(ana, sam, role="caregiver")
    r = sam.post(f"/api/shared/{sid}/log", json=_entry(ana, "banana", day=TODAY, status="eaten"))
    assert r.status_code == 201 and r.json()["status"] == "eaten" and r.json()["added_by"] == "sam"
    day = ana.get("/api/log", params={"date": TODAY}).json()
    assert [(e["food_name"], e["added_by"]) for e in day["entries"]] == [("Banana, raw", "sam")] and day["counts"]["eaten"] == 1
    sam.post(f"/api/shared/{sid}/log/batch", json={"entries": [_entry(ana, day=TODAY, status="eaten"), _entry(ana)]})
    assert len(audit_rows(ana, "care.food_logged")) == 1 and len(audit_rows(ana, "care.plan_changed")) == 1
    changes = ana.get("/api/me/shares").json()["sharing"][0]["helper_changes"]
    assert changes["logged"] == 2 and changes["added"] == 1
    fake_clock.advance(days=1)
    sam.post(f"/api/shared/{sid}/log", json=_entry(ana, day=TODAY, status="eaten"))
    assert len(audit_rows(ana, "care.food_logged")) == 2
    assert all(r["target_id"] == str(uid(ana)) for r in audit_rows(ana, "care.food_logged"))


def test_a_caregiver_marks_planned_food_eaten_and_fixes_only_what_they_added(team):
    ana, sam, _ = team
    sid = join(ana, sam, role="caregiver")
    plan = planned(ana, "apple", day=TODAY)
    r = sam.put(f"/api/shared/{sid}/log/{plan['id']}", json={"status": "eaten", "servings": 0.5})
    assert r.status_code == 200 and r.json()["status"] == "eaten" and r.json()["servings"] == 0.5
    assert r.json()["added_by"] is None  # who added it does not change
    assert sam.put(f"/api/shared/{sid}/log/{plan['id']}", json={"servings": 2}).json()["detail"] == sharing.NOT_YOUR_EATEN
    own = log_food(ana, "banana", date=TODAY)
    for resp in (sam.put(f"/api/shared/{sid}/log/{own['id']}", json={"servings": 2}), sam.delete(f"/api/shared/{sid}/log/{own['id']}")):
        assert resp.status_code == 403 and resp.json()["detail"] == sharing.NOT_YOUR_EATEN
    mine = sam.post(f"/api/shared/{sid}/log", json=_entry(ana, "banana", day=TODAY, status="eaten")).json()
    assert sam.put(f"/api/shared/{sid}/log/{mine['id']}", json={"servings": 1.5, "meal": "dinner"}).status_code == 200
    assert sam.put(f"/api/shared/{sid}/log/{mine['id']}", json={"status": "planned"}).status_code == 400  # never back to planned
    assert sam.delete(f"/api/shared/{sid}/log/{mine['id']}").status_code == 204
    left = {e["id"]: e["servings"] for e in ana.get("/api/log", params={"date": TODAY}).json()["entries"]}
    assert left == {plan["id"]: 0.5, own["id"]: 1}
    # turned back into a Care helper: eaten food is out of reach again, as before
    ana.put(f"/api/me/shares/{sid}/role", json={"role": "care_helper"})
    assert sam.post(f"/api/shared/{sid}/log", json=_entry(ana, day=TODAY, status="eaten")).status_code == 404
    assert sam.delete(f"/api/shared/{sid}/log/{plan['id']}").status_code == 404


def test_no_helper_ever_changes_removes_or_moves_a_low_treatment(team):
    ana, sam, _ = team
    sid = join(ana, sam, role="caregiver")
    by_person = log_food(ana, "glucose", date=TODAY)
    planned_low = planned(ana, "glucose")
    by_helper = sam.post(f"/api/shared/{sid}/log", json=_entry(ana, "glucose", day=TODAY, status="eaten"))
    assert by_helper.status_code == 201 and by_helper.json()["purpose"] == "hypo"  # recording a low is never blocked
    by_helper = by_helper.json()
    for e in (by_person, planned_low, by_helper):
        for body in ({"servings": 2}, {"date": TOMORROW}, {"meal": "snack"}, {"status": "eaten"}, {"note": "x"}):
            r = sam.put(f"/api/shared/{sid}/log/{e['id']}", json=body)
            assert r.status_code == 403 and r.json()["detail"] == LOW_SENTENCE, (e["id"], body)
        r = sam.delete(f"/api/shared/{sid}/log/{e['id']}")
        assert r.status_code == 403 and r.json()["detail"] == LOW_SENTENCE
    assert sam.post(f"/api/shared/{sid}/log/clear-planned", json={"start": TODAY, "end": TOMORROW}).json() == {"deleted": 0}
    ids = {e["id"] for d in (TODAY, TOMORROW) for e in ana.get("/api/log", params={"date": d}).json()["entries"]}
    assert ids == {by_person["id"], planned_low["id"], by_helper["id"]}
    # the person still changes their own low treatment
    assert ana.delete(f"/api/log/{by_helper['id']}").status_code == 204


def test_a_custom_share_with_logging_only(team):
    ana, sam, _ = team
    sid = join(ana, sam, role="viewer")
    set_switches(ana, sid, may_log=True)
    assert sam.post(f"/api/shared/{sid}/log", json=_entry(ana, day=TODAY, status="eaten")).status_code == 201
    assert sam.post(f"/api/shared/{sid}/log", json=_entry(ana)).status_code == 404  # planning is off
    plan = planned(ana, "apple")
    assert sam.put(f"/api/shared/{sid}/log/{plan['id']}", json={"servings": 2}).status_code == 404
    assert sam.put(f"/api/shared/{sid}/log/{plan['id']}", json={"status": "eaten"}).status_code == 200
    assert sam.post(f"/api/shared/{sid}/log/clear-planned", json={"start": TODAY, "end": TOMORROW}).status_code == 404
    assert sam.get(f"/api/shared/{sid}/plan/shopping").status_code == 404
    assert sam.get(f"/api/shared/{sid}/foods", params={"q": "apple"}).status_code == 200


# --------------------------------------------------------------------------- saved meals


def test_saved_meals_are_off_until_the_person_turns_them_on(team):
    ana, sam, _ = team
    sid = join(ana, sam, role="caregiver")
    meal = saved_meal(ana)
    apply = {"date": TOMORROW, "meal": "lunch", "status": "planned"}
    assert sam.get(f"/api/shared/{sid}/meals").status_code == 404
    assert sam.post(f"/api/shared/{sid}/meals/{meal['id']}/apply", json=apply).status_code == 404
    item = set_switches(ana, sid, may_use_saved_meals=True)
    assert item["role"] == "custom"
    got = sam.get(f"/api/shared/{sid}/meals")
    assert got.status_code == 200 and got.json() == ana.get("/api/meals").json()
    r = sam.post(f"/api/shared/{sid}/meals/{meal['id']}/apply", json=apply)
    assert r.status_code == 201 and [(e["status"], e["added_by"]) for e in r.json()["entries"]] == [("planned", "sam")] * 2
    r = sam.post(f"/api/shared/{sid}/meals/{meal['id']}/apply", json={**apply, "date": TODAY, "status": "eaten"})
    assert r.status_code == 201 and {e["status"] for e in r.json()["entries"]} == {"eaten"}
    assert ana.get("/api/me/shares").json()["sharing"][0]["helper_changes"]["logged"] == 2
    # a Care helper with saved meals may plan with them, not log eaten
    ana.put(f"/api/me/shares/{sid}/role", json={"role": "care_helper"})
    set_switches(ana, sid, may_use_saved_meals=True)
    assert sam.post(f"/api/shared/{sid}/meals/{meal['id']}/apply", json={**apply, "status": "eaten"}).status_code == 404
    assert sam.post(f"/api/shared/{sid}/meals/{meal['id']}/apply", json=apply).status_code == 201
    # the person's meals are never changed: no write route, and someone else's meal id is 404
    assert sam.put(f"/api/shared/{sid}/meals/{meal['id']}", json={"name": "x", "items": []}).status_code in (404, 405)
    assert sam.delete(f"/api/shared/{sid}/meals/{meal['id']}").status_code in (404, 405)
    own = saved_meal(sam, "Sam's meal")
    assert sam.post(f"/api/shared/{sid}/meals/{own['id']}/apply", json=apply).status_code == 404
    assert ana.get(f"/api/meals/{meal['id']}").json()["name"] == "Apple lunch"


def test_plan_several_days_uses_saved_meals_only_with_the_switch(team, monkeypatch):
    ana, sam, _ = team
    sid = join(ana, sam)
    from app.guidance import api as guidance_api
    from test_mcp import set_targets

    set_targets(ana)
    seen: list[bool] = []
    real = guidance_api.plan_days

    def spy(ctx, days, meals, **kw):
        seen.append(kw["use_saved_meals"])
        return real(ctx, days, meals, **kw)

    monkeypatch.setattr(guidance_api, "plan_days", spy)
    body = {"start": TOMORROW, "days": 1, "use_saved_meals": True}
    assert sam.post(f"/api/shared/{sid}/guidance/plan-days", json=body).status_code == 200
    set_switches(ana, sid, may_use_saved_meals=True)
    assert sam.post(f"/api/shared/{sid}/guidance/plan-days", json=body).status_code == 200
    assert sam.post(f"/api/shared/{sid}/guidance/plan-days", json={**body, "use_saved_meals": False}).status_code == 200
    assert seen == [False, True, False]


# --------------------------------------------------------------------------- suggestions


def test_suggestions_are_off_by_default_and_a_coach_may_only_suggest(team):
    ana, sam, _ = team
    sid = join(ana, sam, role="viewer")
    r = sam.post(f"/api/shared/{sid}/suggestions", json=suggestion(ana))
    assert r.status_code == 404 and r.json()["detail"] == sharing.NOT_SHARED
    set_switches(ana, sid, may_suggest=True)  # a Viewer who may suggest: a coach
    r = sam.post(f"/api/shared/{sid}/suggestions", json=suggestion(ana, note="The low-sodium broth is in the pantry."))
    assert r.status_code == 201, r.text
    sent = r.json()
    assert sent["answer"] == "open" and sent["items"][0]["name"] == "Apple, raw, with skin" and sent["fit"]["totals"]["potassium_mg"]
    assert sam.post(f"/api/shared/{sid}/log", json=_entry(ana)).status_code == 404  # a coach never writes
    assert sam.get(f"/api/shared/{sid}/foods", params={"q": "apple"}).status_code == 200
    assert audit_rows(ana, "suggestion.sent")[0]["target_id"] == str(uid(ana))
    assert "pantry" not in audit_rows(ana, "suggestion.sent")[0]["details_json"]  # the note itself is not in the activity


def test_the_person_sees_the_fit_and_adds_it_to_their_plan(team):
    ana, sam, _ = team
    sid = join(ana, sam)
    set_switches(ana, sid, may_suggest=True)
    planned(ana, "banana")
    sent = sam.post(f"/api/shared/{sid}/suggestions", json=suggestion(ana, note="Try this")).json()
    mine = ana.get("/api/me/suggestions").json()
    assert mine["enabled"] is True and [s["id"] for s in mine["suggestions"]] == [sent["id"]]
    card = mine["suggestions"][0]
    assert card["from_name"] == "sam" and card["share_id"] == sid and card["note"] == "Try this" and card["items"][0]["available"]
    r = ana.post(f"/api/me/suggestions/{sent['id']}/accept")
    assert r.status_code == 200 and r.json()["skipped"] == 0
    added = r.json()["entries"]
    assert [(e["status"], e["meal"], e["added_by"]) for e in added] == [("planned", "dinner", None)]  # the person's own entry
    day = ana.get("/api/log", params={"date": TOMORROW}).json()
    assert card["fit"]["day_status"] == day["projected_status"]  # the card showed exactly the day it makes
    assert ana.get("/api/me/suggestions").json()["suggestions"] == []
    assert sam.get(f"/api/shared/{sid}/suggestions").json()["suggestions"][0]["answer"] == "accepted"
    assert ana.post(f"/api/me/suggestions/{sent['id']}/accept").status_code == 404  # once
    assert audit_rows(ana, "suggestion.accepted")[0]["actor_user_id"] == uid(ana)


def test_no_thanks_and_what_the_suggester_sees(team):
    ana, sam, kim = team
    sid = join(ana, sam)
    set_switches(ana, sid, may_suggest=True)
    sent = sam.post(f"/api/shared/{sid}/suggestions", json=suggestion(ana)).json()
    assert kim.post(f"/api/me/suggestions/{sent['id']}/decline").status_code == 404  # not hers
    assert sam.post(f"/api/me/suggestions/{sent['id']}/accept").status_code == 404  # the suggester cannot answer it
    assert ana.post(f"/api/me/suggestions/{sent['id']}/decline").status_code == 204
    got = sam.get(f"/api/shared/{sid}/suggestions").json()["suggestions"][0]
    assert got["answer"] == "declined" and set(got) == {"id", "date", "meal", "items", "note", "created_at", "expires_at", "answer",
                                                         "answered_at", "fit"}
    assert ana.get("/api/log", params={"date": TOMORROW}).json()["entries"] == []
    assert audit_rows(ana, "suggestion.declined")


def test_a_suggestion_expires_after_14_days(team, fake_clock):
    ana, sam, _ = team
    sid = join(ana, sam)
    set_switches(ana, sid, may_suggest=True)
    sent = sam.post(f"/api/shared/{sid}/suggestions", json=suggestion(ana)).json()
    fake_clock.advance(days=care_suggestions.SUGGEST_DAYS - 1)
    assert sam.get("/api/shared").status_code == 200  # keeps the helper signed in
    assert len(ana.get("/api/me/suggestions").json()["suggestions"]) == 1
    fake_clock.advance(days=1, seconds=1)
    assert ana.get("/api/me/suggestions").json()["suggestions"] == []
    assert ana.post(f"/api/me/suggestions/{sent['id']}/accept").status_code == 404
    got = sam.get(f"/api/shared/{sid}/suggestions")
    assert got.status_code == 200, got.text
    assert got.json()["suggestions"][0]["answer"] == "expired"
    rows = audit_rows(ana, "suggestion.expired")
    assert len(rows) == 1 and rows[0]["actor_user_id"] is None and rows[0]["target_id"] == str(uid(ana))
    assert "suggestion.expired" in {e["action"] for e in ana.get("/api/me/activity").json()["events"]}


def test_suggestion_limits(team, fake_clock):
    ana, sam, kim = team
    sid = join(ana, sam)
    set_switches(ana, sid, may_suggest=True)
    for _ in range(care_suggestions.MAX_OPEN_PER_SHARE):
        assert sam.post(f"/api/shared/{sid}/suggestions", json=suggestion(ana)).status_code == 201
    r = sam.post(f"/api/shared/{sid}/suggestions", json=suggestion(ana))
    assert r.status_code == 409 and "10 suggestions" in r.json()["detail"]
    for s in ana.get("/api/me/suggestions").json()["suggestions"]:
        ana.post(f"/api/me/suggestions/{s['id']}/decline")
    sid_kim = join(kim, sam, username="sam")
    set_switches(kim, sid_kim, may_suggest=True)
    for _ in range(care_suggestions.MAX_PER_DAY - care_suggestions.MAX_OPEN_PER_SHARE):
        assert sam.post(f"/api/shared/{sid_kim}/suggestions", json=suggestion(kim)).status_code in (201, 409)
    r = sam.post(f"/api/shared/{sid}/suggestions", json=suggestion(ana))
    assert r.status_code == 429 and r.json()["detail"] == care_suggestions.TOO_MANY_TODAY
    fake_clock.advance(days=1, seconds=1)
    assert sam.post(f"/api/shared/{sid}/suggestions", json=suggestion(ana)).status_code == 201


@pytest.mark.parametrize("note,why", [
    ("Take 2 units of insulin first", "insulin"),
    ("If you feel shaky have this", "lows"),
    ("This one is safe for you", "safe"),
    ("Your lab results said so", "lab result"),
])
def test_the_note_is_checked_like_ai_text(team, note, why):
    ana, sam, _ = team
    sid = join(ana, sam)
    set_switches(ana, sid, may_suggest=True)
    r = sam.post(f"/api/shared/{sid}/suggestions", json=suggestion(ana, note=note))
    assert r.status_code == 400 and why in r.json()["detail"].lower(), r.json()
    assert sam.post(f"/api/shared/{sid}/suggestions", json=suggestion(ana, note="x" * 281)).status_code == 400
    assert ana.get("/api/me/suggestions").json()["suggestions"] == []


def test_a_food_for_treating_a_low_is_never_suggested_and_foods_must_be_the_persons(team):
    ana, sam, _ = team
    sid = join(ana, sam)
    set_switches(ana, sid, may_suggest=True)
    r = sam.post(f"/api/shared/{sid}/suggestions", json=suggestion(ana, "glucose"))
    assert r.status_code == 400 and r.json()["detail"].startswith("Glucose tablets is for treating a low.")
    own = sam.post("/api/foods", json={"name": "Sam's soup", "serving_desc": "1 bowl", "serving_g": 250, "nutrients": {}}).json()
    r = sam.post(f"/api/shared/{sid}/suggestions", json={**suggestion(ana), "items": [{"food_id": own["id"], "servings": 1}]})
    assert r.status_code == 404
    for bad in ({"items": []}, {"meal": "brunch"}, {"date": "tomorrow"}, {"items": [{"food_id": 1, "servings": 0}]}, {"extra": 1}):
        assert sam.post(f"/api/shared/{sid}/suggestions", json={**suggestion(ana), **bad}).status_code in (400, 422), bad


def test_a_food_that_is_gone_is_left_out_when_adding(team):
    ana, sam, _ = team
    sid = join(ana, sam)
    set_switches(ana, sid, may_suggest=True)
    soup = ana.post("/api/foods", json={"name": "Ana's soup", "serving_desc": "1 bowl", "serving_g": 250, "nutrients": {}}).json()
    body = {**suggestion(ana), "items": [{"food_id": soup["id"], "servings": 1}, {"food_id": find_food(ana, "apple")["id"], "servings": 1}]}
    one = sam.post(f"/api/shared/{sid}/suggestions", json=body).json()
    only_soup = sam.post(f"/api/shared/{sid}/suggestions", json={**body, "items": body["items"][:1]}).json()
    assert ana.delete(f"/api/foods/{soup['id']}").status_code == 204
    card = next(s for s in ana.get("/api/me/suggestions").json()["suggestions"] if s["id"] == one["id"])
    assert [i["available"] for i in card["items"]] == [False, True]
    r = ana.post(f"/api/me/suggestions/{one['id']}/accept")
    assert r.status_code == 200 and r.json()["skipped"] == 1 and len(r.json()["entries"]) == 1
    r = ana.post(f"/api/me/suggestions/{only_soup['id']}/accept")
    assert r.status_code == 409 and r.json()["detail"] == care_suggestions.NONE_LEFT


def test_switching_suggestions_off_keeps_them_and_ending_the_share_closes_them(team):
    ana, sam, _ = team
    sid = join(ana, sam)
    set_switches(ana, sid, may_suggest=True)
    sent = sam.post(f"/api/shared/{sid}/suggestions", json=suggestion(ana)).json()
    set_switches(ana, sid, may_suggest=False)
    assert sam.post(f"/api/shared/{sid}/suggestions", json=suggestion(ana)).status_code == 404
    assert [s["id"] for s in ana.get("/api/me/suggestions").json()["suggestions"]] == [sent["id"]]
    assert sam.get(f"/api/shared/{sid}/suggestions").status_code == 200  # the answers stay readable
    assert sam.delete(f"/api/shared/{sid}").status_code == 204  # the helper leaves
    assert ana.get("/api/me/suggestions").json()["suggestions"] == []
    assert ana.post(f"/api/me/suggestions/{sent['id']}/accept").status_code == 404
    with open_db(ana) as conn:
        assert conn.execute("SELECT answer FROM care_suggestions WHERE id = ?", (sent["id"],)).fetchone()[0] == "ended"


def test_the_list_answers_200_while_sharing_is_off(team):
    ana, sam, _ = team
    sid = join(ana, sam)
    set_switches(ana, sid, may_suggest=True)
    sent = sam.post(f"/api/shared/{sid}/suggestions", json=suggestion(ana)).json()
    switch(ana, False)
    r = ana.get("/api/me/suggestions")
    assert r.status_code == 200 and r.json() == {"enabled": False, "suggestions": []}
    assert ana.post(f"/api/me/suggestions/{sent['id']}/accept").status_code == 404
    assert ana.post(f"/api/me/suggestions/{sent['id']}/decline").status_code == 404
    switch(ana, True)
    assert len(ana.get("/api/me/suggestions").json()["suggestions"]) == 1


def test_suggestions_are_in_the_persons_export_only(team):
    ana, sam, _ = team
    sid = join(ana, sam)
    set_switches(ana, sid, may_suggest=True)
    sam.post(f"/api/shared/{sid}/suggestions", json=suggestion(ana, note="Soup night"))
    from app.account import export_data

    with open_db(ana) as conn:
        mine = export_data(conn, uid(ana), app_version="test")["care_suggestions"]
        theirs = export_data(conn, uid(sam), app_version="test")["care_suggestions"]
    assert theirs == []
    assert [(s["from"], s["note"], s["answer"], s["items"][0]["name"]) for s in mine] == [("sam", "Soup night", "open", "Apple, raw, with skin")]
    assert set(mine[0]) == {"date", "meal", "from", "note", "items", "created_at", "answer", "answered_at"}


# --------------------------------------------------------------------------- the isolation matrix of the new routes


def _new_routes(client: TestClient, sid: int, entry_id: int, meal_id: int, owner: TestClient) -> list[tuple[str, int]]:
    return [
        ("eaten", client.post(f"/api/shared/{sid}/log", json=_entry(owner, day=TODAY, status="eaten")).status_code),
        ("mark eaten", client.put(f"/api/shared/{sid}/log/{entry_id}", json={"status": "eaten"}).status_code),
        ("meals", client.get(f"/api/shared/{sid}/meals").status_code),
        ("apply", client.post(f"/api/shared/{sid}/meals/{meal_id}/apply", json={"date": TODAY, "meal": "lunch"}).status_code),
        ("suggest", client.post(f"/api/shared/{sid}/suggestions", json=suggestion(owner)).status_code),
        ("sent", client.get(f"/api/shared/{sid}/suggestions").status_code),
    ]


@pytest.mark.parametrize("how", ["someone_else", "switches_off", "viewer", "stopped", "sharing_off"])
def test_every_new_route_is_the_same_404_when_it_is_not_yours_now(team, how):
    ana, sam, kim = team
    sid = join(ana, sam, role="caregiver")
    set_switches(ana, sid, may_use_saved_meals=True, may_suggest=True)
    entry = planned(ana, "apple", day=TODAY)
    meal = saved_meal(ana)
    client = sam
    if how == "someone_else":
        client = kim
    elif how == "switches_off":
        set_switches(ana, sid, may_plan=False, may_log=False, may_use_saved_meals=False, may_suggest=False)
    elif how == "viewer":
        ana.put(f"/api/me/shares/{sid}/role", json={"role": "viewer"})
    elif how == "stopped":
        ana.delete(f"/api/me/shares/{sid}")
    elif how == "sharing_off":
        switch(ana, False)
    got = dict(_new_routes(client, sid, entry["id"], meal["id"], ana))
    allowed_reads = {"sent"} if how in ("switches_off", "viewer") else set()  # a share still active may read its own sent list
    assert {k: v for k, v in got.items() if k not in allowed_reads} == {k: 404 for k in got if k not in allowed_reads}, (how, got)
    for k in allowed_reads:
        assert got[k] == 200
    if how == "sharing_off":
        switch(ana, True)
    assert [e["id"] for e in ana.get("/api/log", params={"date": TODAY}).json()["entries"]] == [entry["id"]]
    assert ana.get("/api/me/suggestions").json()["suggestions"] == []


def test_a_helper_of_ana_never_reaches_kims_meals_or_suggestions(team):
    ana, sam, kim = team
    sid = join(ana, sam, role="caregiver")
    set_switches(ana, sid, may_use_saved_meals=True, may_suggest=True)
    kims_meal = saved_meal(kim, "Kim's meal")
    r = sam.post(f"/api/shared/{sid}/meals/{kims_meal['id']}/apply", json={"date": TODAY, "meal": "lunch"})
    assert r.status_code == 404
    sid_kim = join(kim, sam)
    set_switches(kim, sid_kim, may_suggest=True)
    to_kim = sam.post(f"/api/shared/{sid_kim}/suggestions", json=suggestion(kim)).json()
    assert ana.post(f"/api/me/suggestions/{to_kim['id']}/accept").status_code == 404
    assert [s["id"] for s in sam.get(f"/api/shared/{sid}/suggestions").json()["suggestions"]] == []
    assert ana.get("/api/me/suggestions").json()["suggestions"] == []


def test_the_date_constants():
    assert care_suggestions.SUGGEST_DAYS == 14 and care_suggestions.MAX_NOTE == 280
    assert (date.fromisoformat(TOMORROW) - timedelta(days=1)).isoformat() == TODAY


def test_the_care_vectors_are_current():
    """tests/data/care_vectors.json is what app/sharing.py and app/care_suggestions.py answer now; node tests/js/run_vectors.mjs
    replays it against the demo's twin (js/mock/care.js)."""
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    r = subprocess.run([sys.executable, str(root / "tests" / "data" / "gen_care_vectors.py"), "--check"], capture_output=True, text=True,
                       timeout=120)
    assert r.returncode == 0, r.stderr
