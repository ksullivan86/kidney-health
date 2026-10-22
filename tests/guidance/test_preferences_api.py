"""Food preferences over HTTP and in the loader (note 09 §4.2, §4.10; part A): ``GET /api/guidance/preferences``,
``PUT``/``DELETE /preferences/{food_id}``, ``GET /learned``, the ``/not-for-me`` aliases, the guidance settings that carry the
food-group choices, the limits, two people, the loader's inputs and ``explicit_preferences``."""
from __future__ import annotations

import sqlite3
from datetime import date, timedelta
from pathlib import Path
from typing import Iterator

import pytest
from app import db
from app.guidance import context as C
from app.guidance import rules as R
from app.settings_store import SettingsStore
from conftest import HTTPS_URL, TestClient, add_user, insert_users, make_settings, sign_in
from test_api_guidance import DAY, food_id, log, set_targets

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def real(tmp_path) -> Iterator[TestClient]:
    """The admin, signed in over HTTPS, on a database with the real builtin food list (395 foods)."""
    from app.main import create_app

    with TestClient(create_app(make_settings(tmp_path, ROOT / "data" / "foods.json")), base_url=HTTPS_URL) as c:
        sign_in(c)
        yield c

ROW_KEYS = {"food_id", "name", "category", "preference", "source", "created_at", "updated_at"}
RICE = "Rice, white, long-grain, cooked"
BEANS = "Green beans, boiled"
BANANA = "Banana, raw"
APPLE = "Apple, raw, with skin"


def put(client, fid: int, preference: str, **extra):
    return client.put(f"/api/guidance/preferences/{fid}", json={"preference": preference, **extra})


def prefs(client) -> dict:
    r = client.get("/api/guidance/preferences")
    assert r.status_code == 200, r.text
    return r.json()


def lunch(client, **q) -> dict:
    r = client.get("/api/guidance/next-meal", params={"date": DAY, "meal": "lunch", "limit": 20, "explain": "true", **q})
    assert r.status_code == 200, r.text
    return r.json()


def by_id(body: dict) -> dict[int, dict]:
    return {f["food_id"]: f for f in body["foods"]}


# --------------------------------------------------------------------------- #
# The routes
# --------------------------------------------------------------------------- #


def test_the_list_starts_empty_and_has_the_contract_shape(real):
    body = prefs(real)
    assert body == {"rules_version": R.RULES_VERSION, "limit": 1000, "not_for_me_limit": 500, "foods": [],
                    "groups": {"like": [], "less": [], "never": []}, "learn_from_log": True}
    assert real.get("/api/guidance/preferences").headers["cache-control"] == "no-store"


def test_put_stores_the_four_values_and_the_row_has_the_contract_shape(real):
    rice, beans, banana, apple = (food_id(real, n) for n in (RICE, BEANS, BANANA, APPLE))
    for fid, value in ((rice, "like"), (beans, "less"), (banana, "not_for_me"), (apple, "neutral")):
        r = put(real, fid, value)
        assert r.status_code == 200, r.text
        row = r.json()
        assert set(row) == ROW_KEYS and row["preference"] == value and row["food_id"] == fid
        assert row["source"] == "person" and row["created_at"] == row["updated_at"]
    foods = prefs(real)["foods"]
    assert [f["name"] for f in foods] == [apple_name for apple_name in sorted((APPLE, BANANA, BEANS, RICE), key=str.casefold)]
    assert {f["preference"] for f in foods} == {"like", "less", "not_for_me", "neutral"}
    assert next(f for f in foods if f["food_id"] == rice)["category"] == "Grains & Breads"


def test_put_is_idempotent_and_a_change_keeps_created_at_but_moves_updated_at_and_source(real):
    rice = food_id(real, RICE)
    first = put(real, rice, "like").json()
    again = put(real, rice, "like", source="ask").json()  # the same value again: nothing changes, not even the source
    assert again == first and again["source"] == "person"
    changed = put(real, rice, "less", source="ask").json()
    assert changed["preference"] == "less" and changed["source"] == "ask"
    assert changed["created_at"] == first["created_at"] and changed["updated_at"] >= first["updated_at"]
    assert len(prefs(real)["foods"]) == 1


def test_put_validates_the_body(real):
    rice = food_id(real, RICE)
    for body in ({}, {"preference": "love"}, {"preference": "Like"}, {"preference": None}, {"preference": "like", "source": "robot"},
                 {"preference": "like", "extra": 1}, {"source": "person"}):
        assert real.put(f"/api/guidance/preferences/{rice}", json=body).status_code == 400, body  # the app answers a bad body with 400
    assert real.put(f"/api/guidance/preferences/{rice}", content=b"nope", headers={"content-type": "application/json"}).status_code == 400
    assert prefs(real)["foods"] == []


def test_put_and_delete_answer_404_for_a_food_that_is_not_there_or_not_yours(real):
    assert put(real, 999999, "like").status_code == 404
    assert put(real, 2**70, "like").status_code in (404, 400)
    assert real.delete("/api/guidance/preferences/999999").status_code == 404
    assert real.delete(f"/api/guidance/preferences/{2**70}").status_code == 404
    assert real.delete("/api/guidance/preferences/abc").status_code == 400


def test_delete_forgets_any_kind_of_preference(real):
    rice, banana = food_id(real, RICE), food_id(real, BANANA)
    put(real, rice, "like")
    put(real, banana, "not_for_me")
    assert real.delete(f"/api/guidance/preferences/{rice}").status_code == 204
    assert real.delete(f"/api/guidance/preferences/{banana}").status_code == 204
    assert real.delete(f"/api/guidance/preferences/{banana}").status_code == 404
    assert prefs(real)["foods"] == []


def test_the_total_limit_is_1000_and_changing_a_value_at_the_limit_is_still_allowed(real, monkeypatch):
    monkeypatch.setattr(C, "MAX_FOOD_PREFERENCES", 2)
    rice, beans, banana = (food_id(real, n) for n in (RICE, BEANS, BANANA))
    assert put(real, rice, "like").status_code == 200 and put(real, beans, "less").status_code == 200
    full = put(real, banana, "like")
    assert full.status_code == 409 and full.json()["detail"] == "your food preferences are full (2 foods); remove one first"
    assert put(real, rice, "less").status_code == 200  # an existing row changes its value
    assert real.put(f"/api/guidance/not-for-me/{banana}").status_code == 409  # the alias counts the same total
    assert real.put(f"/api/guidance/not-for-me/{rice}").status_code == 200  # …and replaces the like on an existing row
    assert real.delete(f"/api/guidance/preferences/{beans}").status_code == 204
    assert put(real, banana, "like").status_code == 200


def test_the_not_for_me_limit_is_500_for_not_for_me_alone(real, monkeypatch):
    monkeypatch.setattr(C, "MAX_NOT_FOR_ME", 1)
    rice, beans, banana = (food_id(real, n) for n in (RICE, BEANS, BANANA))
    assert put(real, banana, "not_for_me").status_code == 200
    full = put(real, rice, "not_for_me")
    assert full.status_code == 409 and full.json()["detail"] == 'the "Not for me" list is full (1 foods); remove one first'
    assert put(real, rice, "like").status_code == 200 and put(real, beans, "neutral").status_code == 200  # others do not count
    assert put(real, rice, "not_for_me").status_code == 409  # a like turning into "Not for me" does
    assert put(real, banana, "not_for_me").status_code == 200  # the same value again is not a new row


# --------------------------------------------------------------------------- #
# The older "Not for me" routes are aliases
# --------------------------------------------------------------------------- #


def test_the_not_for_me_routes_read_and_write_the_not_for_me_rows_only(real):
    rice, beans, banana = (food_id(real, n) for n in (RICE, BEANS, BANANA))
    put(real, rice, "like")
    put(real, beans, "less")
    listed = real.get("/api/guidance/not-for-me").json()
    assert listed["foods"] == [] and listed["limit"] == 500 and set(listed) == {"rules_version", "foods", "limit"}
    r = real.put(f"/api/guidance/not-for-me/{banana}")
    assert r.status_code == 200 and [set(f) for f in r.json()["foods"]] == [{"food_id", "name", "category", "created_at"}]
    assert [f["food_id"] for f in r.json()["foods"]] == [banana]
    assert real.delete(f"/api/guidance/not-for-me/{rice}").status_code == 404  # a like is not on that list …
    assert {f["food_id"]: f["preference"] for f in prefs(real)["foods"]}[rice] == "like"  # … and stays
    # PUT replaces another preference on the food
    again = real.put(f"/api/guidance/not-for-me/{rice}")
    assert again.status_code == 200 and {f["food_id"] for f in again.json()["foods"]} == {rice, banana}
    assert {f["food_id"]: f["preference"] for f in prefs(real)["foods"]}[rice] == "not_for_me"
    assert real.delete(f"/api/guidance/not-for-me/{banana}").status_code == 204
    assert prefs(real)["foods"][0]["source"] == "person"
    # and the new route sees what the alias wrote
    assert {f["food_id"] for f in prefs(real)["foods"]} == {rice, beans}


# --------------------------------------------------------------------------- #
# The food-group choices live in the guidance setting
# --------------------------------------------------------------------------- #


def patch_guidance(client, **fields):
    return client.patch("/api/me/settings", json={"guidance": fields})


def test_the_group_choices_and_the_switch_travel_through_the_settings(real):
    r = patch_guidance(real, like_categories=["Fruits"], less_categories=["Sweets & Snacks"], exclude_categories=["Beverages"],
                       learn_from_log=False, hidden_usual_meals=["dinner:1x4,3x4"])
    assert r.status_code == 200, r.text
    value = r.json()["settings"]["guidance"]["value"]
    assert value["like_categories"] == ["Fruits"] and value["learn_from_log"] is False
    assert prefs(real)["groups"] == {"like": ["Fruits"], "less": ["Sweets & Snacks"], "never": ["Beverages"]}
    assert prefs(real)["learn_from_log"] is False
    assert real.get("/api/me/settings").json()["settings"]["guidance"]["value"]["hidden_usual_meals"] == ["dinner:1x4,3x4"]


def test_a_group_in_two_lists_is_refused_with_a_clear_message(real):
    for fields, clash in (({"like_categories": ["Fruits"], "less_categories": ["Fruits"]}, "Fruits"),
                          ({"less_categories": ["Dairy & Alternatives"], "exclude_categories": ["Dairy & Alternatives"]}, "Dairy & Alternatives"),
                          ({"like_categories": ["Fruits"], "exclude_categories": ["Fruits"]}, "Fruits")):
        r = patch_guidance(real, **fields)
        assert r.status_code == 400, r.text  # the settings API answers every invalid value with 400
        assert r.json()["detail"] == ("guidance: Value error, a food group can be in only one of Like, Less often "
                                      f"and Never suggest: {clash}")
    # nothing was stored
    assert real.get("/api/me/settings").json()["settings"]["guidance"]["value"]["like_categories"] == []
    for bad in ({"hidden_usual_meals": ["brunch:1x4"]}, {"hidden_usual_meals": ["x" * 401]}, {"like_categories": ["a"] * 0 + [""]},
                {"like_categories": [f"c{i}" for i in range(51)]}, {"learn_from_log": "maybe"}, {"unknown": 1}):
        assert patch_guidance(real, **bad).status_code == 400, bad


def test_the_lists_are_deduplicated(real):
    r = patch_guidance(real, like_categories=["Fruits", "Fruits"], hidden_usual_meals=["lunch:1x4", "lunch:1x4"])
    assert r.status_code == 200
    assert r.json()["settings"]["guidance"]["value"]["like_categories"] == ["Fruits"]
    assert r.json()["settings"]["guidance"]["value"]["hidden_usual_meals"] == ["lunch:1x4"]


# --------------------------------------------------------------------------- #
# The ranking over HTTP
# --------------------------------------------------------------------------- #


def test_a_like_raises_a_food_by_one_and_a_less_often_lowers_it_by_two(real):
    set_targets(real)
    base = by_id(lunch(real))
    rice, beans = (food_id(real, n) for n in (RICE, BEANS))
    assert rice in base
    put(real, rice, "like")
    put(real, beans, "less")
    after = by_id(lunch(real))
    assert after[rice]["score"] == pytest.approx(base[rice]["score"] + 1.0, abs=0.0051)
    assert after[rice]["explain"]["components"]["preference"] == 1.0
    assert beans not in after or after[beans]["score"] == pytest.approx(base[beans]["score"] - 2.0, abs=0.0051)
    assert after[rice]["score"] <= base[rice]["score"] + 1.0 + 0.0051
    # forgetting a preference puts the numbers back
    real.delete(f"/api/guidance/preferences/{rice}")
    real.delete(f"/api/guidance/preferences/{beans}")
    assert by_id(lunch(real))[rice]["score"] == base[rice]["score"]


def test_not_for_me_through_the_new_route_hides_the_food_like_the_old_one(real):
    set_targets(real)
    rice = food_id(real, RICE)
    assert rice in by_id(lunch(real))
    put(real, rice, "not_for_me")
    body = lunch(real)
    assert rice not in by_id(body) and body["explain"]["not_eligible"][str(rice)] == "not_for_me"


def test_a_liked_group_and_a_less_often_group_move_every_food_in_them(real):
    set_targets(real)
    base = by_id(lunch(real))
    patch_guidance(real, like_categories=["Fruits"], less_categories=["Grains & Breads"])
    after = by_id(lunch(real))
    for fid, f in after.items():
        if f["explain"]["components"]["preference"] != 0:
            assert f["explain"]["components"]["preference"] in (0.5, -1.0)
    moved = {fid for fid, f in after.items() if fid in base and f["score"] != base[fid]["score"]}
    assert moved  # something moved
    assert patch_guidance(real, like_categories=[], less_categories=[]).status_code == 200
    assert by_id(lunch(real))[next(iter(base))]["score"] == base[next(iter(base))]["score"]


def test_the_liked_food_shows_its_reason(real):
    set_targets(real)
    # A lunch that already has a protein, a starch and a vegetable: the "adds what is missing" reasons are gone, so a
    # suggestion has room for a second reason (a suggestion shows at most two positive reasons)
    for name in ("Chicken breast, roasted, skinless", RICE, BEANS):
        log(real, name, "lunch", 0.5)
    one = next(f for f in lunch(real)["foods"] if len(f["reasons"]) <= 1)
    put(real, one["food_id"], "like")
    got = by_id(lunch(real))[one["food_id"]]
    assert [r["code"] for r in got["reasons"]] == [r["code"] for r in one["reasons"]] + ["you_like"]
    assert got["reasons"][-1]["text"] == "You said you like this."
    assert got["score"] == pytest.approx(one["score"] + 1.0, abs=0.0051)


@pytest.mark.safety
def test_hypo_options_are_the_same_with_any_soft_preference_and_never_empty(real):
    base = real.get("/api/guidance/hypo-options").json()
    ids = [o["food_id"] for o in base["options"]]
    assert ids and base["notes"] == [base["notes"][0]]
    put(real, ids[0], "less")
    put(real, ids[1], "neutral")
    patch_guidance(real, like_categories=["Beverages"], less_categories=["Diabetes supplies"], learn_from_log=False)
    assert real.get("/api/guidance/hypo-options").json() == base
    # "Not for me" still works, with the floor
    put(real, ids[0], "not_for_me")
    one = real.get("/api/guidance/hypo-options").json()
    assert [o["food_id"] for o in one["options"]] == ids[1:] and one["notes"] == base["notes"]
    for fid in ids[1:]:
        put(real, fid, "not_for_me")
    floor = real.get("/api/guidance/hypo-options").json()
    assert [o["food_id"] for o in floor["options"]] == ids
    assert floor["notes"][-1] == "Shown although you marked them Not for me." and floor["notes"][0] == base["notes"][0]
    assert floor["card"] == base["card"] and floor["dose_g"] == base["dose_g"]


@pytest.mark.safety
def test_the_low_treatment_card_and_chat_rule_ignore_preferences(real):
    base = real.get("/api/guidance/hypo-options").json()["card"]
    ids = [o["food_id"] for o in real.get("/api/guidance/hypo-options").json()["options"]]
    for fid in ids:
        put(real, fid, "not_for_me")
    patch_guidance(real, learn_from_log=False, exclude_categories=["Beverages", "Diabetes supplies"])
    assert real.get("/api/guidance/hypo-options").json()["card"] == base


# --------------------------------------------------------------------------- #
# The learned list
# --------------------------------------------------------------------------- #


def days_ago(n: int) -> str:
    return (date.today() - timedelta(days=n)).isoformat()


def test_the_learned_list_shows_what_was_seen_and_the_person_can_switch_it_off(real):
    set_targets(real)
    for n in (1, 2, 3):
        log(real, RICE, "lunch", day=days_ago(n))
    # green beans planned for dinner on four past days; the person ate rice at dinner instead
    for n in (4, 6, 8, 9):
        log(real, BEANS, "dinner", day=days_ago(n), status="planned")
        log(real, RICE, "dinner", day=days_ago(n))
    body = real.get("/api/guidance/learned").json()
    assert body["rules_version"] == R.RULES_VERSION and body["learn_from_log"] is True
    kinds = [(i["kind"], i["name"]) for i in body["items"]]
    assert ("often", RICE) in kinds and ("slot", RICE) in kinds and ("planned_not_eaten", BEANS) in kinds
    rice_often = next(i for i in body["items"] if i["kind"] == "often")
    assert rice_often["reason"] == "Eaten on 7 of the last 14 days" and rice_often["effect"] == "more"
    skipped = next(i for i in body["items"] if i["kind"] == "planned_not_eaten")
    assert skipped == {"kind": "planned_not_eaten", "food_id": food_id(real, BEANS), "name": BEANS, "meal": None, "key": None,
                       "reason": "Planned 4 times in 30 days, not eaten", "effect": "less"}
    assert real.get("/api/guidance/learned").headers["cache-control"] == "no-store"
    # a neutral food is not listed; the switch empties the list
    put(real, food_id(real, BEANS), "neutral")
    assert "planned_not_eaten" not in [i["kind"] for i in real.get("/api/guidance/learned").json()["items"]]
    patch_guidance(real, learn_from_log=False)
    assert real.get("/api/guidance/learned").json() == {"rules_version": R.RULES_VERSION, "learn_from_log": False, "items": []}


def test_learned_signals_lower_the_skipped_food_in_the_ranking_and_neutral_stops_it(real):
    set_targets(real)
    q = {"date": days_ago(0), "meal": "lunch", "limit": 20, "explain": "true"}
    beans = food_id(real, BEANS)
    base = by_id(real.get("/api/guidance/next-meal", params=q).json())
    assert base[beans]["explain"]["components"]["preference"] == 0.0 and base[beans]["score"] == 4.11
    for n in (4, 6, 8, 9):
        log(real, BEANS, "lunch", day=days_ago(n), status="planned")
        log(real, RICE, "lunch", day=days_ago(n))
    # 4.11 - 0.5 = 3.61 slips below the next vegetable (4.03): the skipped food is no longer among the suggestions
    assert beans not in by_id(real.get("/api/guidance/next-meal", params=q).json())
    put(real, beans, "neutral")  # "stop using this"
    again = by_id(real.get("/api/guidance/next-meal", params=q).json())
    assert again[beans]["explain"]["components"]["preference"] == 0.0 and again[beans]["score"] == 4.11
    real.delete(f"/api/guidance/preferences/{beans}")
    assert beans not in by_id(real.get("/api/guidance/next-meal", params=q).json())  # forgetting the choice brings the term back
    patch_guidance(real, learn_from_log=False)  # the switch does the same for every food
    assert by_id(real.get("/api/guidance/next-meal", params=q).json())[beans]["score"] == 4.11


def test_a_person_who_never_logs_what_they_eat_is_never_inferred_about(real):
    set_targets(real)
    for n in (4, 6, 8, 9):
        log(real, BEANS, "dinner", day=days_ago(n), status="planned")
    body = real.get("/api/guidance/learned").json()
    assert body["items"] == []


# --------------------------------------------------------------------------- #
# Two people
# --------------------------------------------------------------------------- #


def test_one_persons_preferences_never_change_anothers_suggestions_lists_or_learned_items(real):
    admin = real
    sam = add_user(admin)
    for c in (admin, sam):
        set_targets(c)
    rice, beans = food_id(admin, RICE), food_id(admin, BEANS)
    before = lunch(sam)
    sam_hypo = sam.get("/api/guidance/hypo-options").json()
    sam_plan = sam.post("/api/guidance/plan-day", json={"date": DAY}).json()
    secret = admin.post("/api/log/quick", json={"date": DAY, "meal": "lunch", "name": "Admin's secret stew",
                                                "nutrients": {"carbs_g": 20, "protein_g": 10, "potassium_mg": 50,
                                                              "phosphorus_mg": 40, "sodium_mg": 60}}).json()["food_id"]
    put(admin, rice, "not_for_me")
    put(admin, beans, "less")
    put(admin, secret, "like")
    patch_guidance(admin, like_categories=["Fruits"], less_categories=["Beverages"], learn_from_log=False)
    for n in (1, 2, 3):
        log(admin, BANANA, "lunch", day=days_ago(n))
    # Sam's answers are byte for byte what they were
    assert lunch(sam) == before
    assert sam.get("/api/guidance/hypo-options").json() == sam_hypo
    assert sam.post("/api/guidance/plan-day", json={"date": DAY}).json() == sam_plan
    assert prefs(sam) == {"rules_version": R.RULES_VERSION, "limit": 1000, "not_for_me_limit": 500, "foods": [],
                          "groups": {"like": [], "less": [], "never": []}, "learn_from_log": True}
    assert sam.get("/api/guidance/learned").json()["items"] == []
    assert "secret stew" not in sam.get("/api/guidance/preferences").text
    # Sam cannot read, change or delete the admin's rows
    assert put(sam, secret, "like").status_code == 404
    assert put(sam, 999999, "like").status_code == 404
    assert sam.delete(f"/api/guidance/preferences/{rice}").status_code == 404
    assert sam.delete(f"/api/guidance/not-for-me/{rice}").status_code == 404
    assert {f["food_id"]: f["preference"] for f in prefs(admin)["foods"]} == {rice: "not_for_me", beans: "less", secret: "like"}
    # …and Sam's own choice on a shared food is Sam's alone
    assert put(sam, beans, "like").status_code == 200
    assert next(f for f in prefs(admin)["foods"] if f["food_id"] == beans)["preference"] == "less"
    assert next(f for f in prefs(sam)["foods"] if f["food_id"] == beans)["preference"] == "like"


# --------------------------------------------------------------------------- #
# The loader and explicit_preferences (a database, no HTTP)
# --------------------------------------------------------------------------- #

TODAY = "2026-10-21"


def new_db(tmp_path: Path) -> sqlite3.Connection:
    path = tmp_path / "kidney.db"
    db.init_db(path)
    conn = db.connect(path)
    insert_users(conn, [(1, "admin"), (2, "sam")])
    return conn


def food(conn: sqlite3.Connection, fid: int, name: str, category: str = "Vegetables", owner: int | None = 1) -> None:
    conn.execute(
        """INSERT INTO foods (id, name, category, source, serving_desc, serving_g, carbs_g, protein_g, potassium_mg, phosphorus_mg,
                              sodium_mg, owner_user_id, created_at, updated_at)
           VALUES (?, ?, ?, 'custom', '1 cup', 100, 10, 2, 100, 50, 20, ?, '2026-10-01T00:00:00Z', '2026-10-01T00:00:00Z')""",
        (fid, name, category, owner))


def entry(conn: sqlite3.Connection, user: int, fid: int, day: str, meal: str = "dinner", status: str = "eaten",
          purpose: str | None = None) -> None:
    conn.execute(
        """INSERT INTO log_entries (user_id, date, meal, food_id, food_name, servings, status, purpose, created_at, updated_at)
           VALUES (?, ?, ?, ?, 'x', 1, ?, ?, '2026-10-01T00:00:00Z', '2026-10-01T00:00:00Z')""",
        (user, day, meal, fid, status, purpose))


def set_pref(conn: sqlite3.Connection, user: int, fid: int, pref: str, at: str, source: str = "person") -> None:
    conn.execute(
        """INSERT INTO food_preferences (user_id, food_id, preference, created_at, source, updated_at) VALUES (?, ?, ?, ?, ?, ?)""",
        (user, fid, pref, at, source, at))


def test_the_loader_reads_the_four_values_the_settings_and_only_this_persons_rows(tmp_path):
    conn = new_db(tmp_path)
    for fid, name in ((1, "Rice"), (2, "Beans"), (3, "Kale"), (4, "Corn")):
        food(conn, fid, name)
    for fid, pref in ((1, "like"), (2, "less"), (3, "not_for_me"), (4, "neutral")):
        set_pref(conn, 1, fid, pref, "2026-10-01T00:00:00Z")
    set_pref(conn, 2, 1, "less", "2026-10-01T00:00:00Z")
    store = SettingsStore(env={})
    store.set_user(conn, 1, "guidance", {"like_categories": ["Fruits"], "less_categories": ["Beverages"], "learn_from_log": False,
                                         "hidden_usual_meals": ["lunch:1x4,2x4"], "exclude_categories": ["Dairy & Alternatives"]})
    conn.commit()
    p = C.load_prefs(conn, store, 1)
    assert p.exclude_food_ids == {3} and p.food_pref == {1: "like", 2: "less", 4: "neutral"}
    assert p.like_categories == {"Fruits"} and p.less_categories == {"Beverages"} and p.learn_from_log is False
    assert p.hidden_usual_meals == {"lunch:1x4,2x4"} and p.exclude_categories == {"Dairy & Alternatives"}
    q = C.load_prefs(conn, store, 2)
    assert q.food_pref == {1: "less"} and q.exclude_food_ids == frozenset() and q.learn_from_log is True
    assert C.load_prefs(conn, store, 1) == C.load_prefs(conn, SettingsStore(env={}), 1)


def test_the_loader_reads_planned_entries_of_past_days_only_and_the_eaten_rows_when_needed(tmp_path):
    conn = new_db(tmp_path)
    food(conn, 1, "Beans")
    food(conn, 2, "Rice")
    food(conn, 3, "Glucose", "Diabetes supplies")
    for day in ("2026-09-21", "2026-09-20", "2026-10-20", "2026-10-21", "2026-10-22"):
        entry(conn, 1, 1, day, status="planned")
    entry(conn, 1, 3, "2026-10-10", status="planned", purpose="hypo")  # a low treatment is not a plan
    entry(conn, 1, 1, "2026-10-12", status="planned")
    entry(conn, 2, 1, "2026-10-12", status="planned")  # someone else's
    entry(conn, 1, 2, "2026-10-12", meal="dinner")
    store = SettingsStore(env={})
    conn.commit()
    ctx = C.load(conn, 1, TODAY, store=store)
    assert [(p.food_id, p.date) for p in ctx.planned30] == [(1, "2026-09-21"), (1, "2026-10-12"), (1, "2026-10-20")]  # date-30 … date-1
    assert ctx.eaten30 is None and [h.food_id for h in ctx.history60 if h.date == "2026-10-12"] == [2]  # history60 covers it
    # swaps and insights do not load 60 days: the eaten rows of the same 30 are loaded for the rule
    narrow = C.load(conn, 1, TODAY, store=store, options=C.LoadOptions(history60=False, combos=False))
    assert [p.date for p in narrow.planned30] == ["2026-09-21", "2026-10-12", "2026-10-20"]
    assert narrow.eaten30 is not None and [h.food_id for h in narrow.eaten30] == [2]
    # nothing planned → no extra read of eaten rows
    entry(conn, 1, 1, "2026-10-12", status="eaten")
    conn.execute("DELETE FROM log_entries WHERE status = 'planned'")
    conn.commit()
    empty = C.load(conn, 1, TODAY, store=store, options=C.LoadOptions(history60=False, combos=False))
    assert empty.planned30 == () and empty.eaten30 is None
    # the low-treatment options need neither, and the switch skips the read
    conn.execute("UPDATE log_entries SET status = 'planned' WHERE food_id = 1")
    conn.commit()
    assert C.load(conn, 1, TODAY, store=store, options=C.LoadOptions(history=False, history60=False, saved_meals=False,
                                                                       combos=False)).planned30 == ()
    store.set_user(conn, 1, "guidance", {"learn_from_log": False})
    conn.commit()
    off = C.load(conn, 1, TODAY, store=store)
    assert off.planned30 == () and off.prefs.learn_from_log is False
    conn.close()


def test_explicit_preferences_lists_names_the_newest_first_capped_at_ten_and_never_a_learned_signal(tmp_path):
    conn = new_db(tmp_path)
    for fid in range(1, 16):
        food(conn, fid, f"Food {fid:02d}")
    # likes: 12 foods, the later ids changed later
    for fid in range(1, 13):
        set_pref(conn, 1, fid, "like", f"2026-10-{fid:02d}T00:00:00Z", "ask" if fid == 3 else "person")
    set_pref(conn, 1, 13, "less", "2026-10-05T00:00:00Z")
    set_pref(conn, 1, 14, "not_for_me", "2026-10-06T00:00:00Z")
    set_pref(conn, 1, 15, "neutral", "2026-10-20T00:00:00Z")  # "stop using what you learned" is not a taste
    set_pref(conn, 2, 1, "not_for_me", "2026-10-30T00:00:00Z")  # someone else's
    store = SettingsStore(env={})
    store.set_user(conn, 1, "guidance", {"like_categories": ["Fruits", "Dairy & Alternatives"], "less_categories": ["Beverages"],
                                         "exclude_categories": ["Sweets & Snacks"]})
    conn.commit()
    got = C.explicit_preferences(conn, 1, store)
    assert set(got) == {"likes", "less_often", "not_for_me"}
    assert got["likes"] == [f"Food {fid:02d}" for fid in range(12, 2, -1)]  # newest first, ten of the twelve foods, no group
    assert got["less_often"] == ["Food 13", "Beverages"] and got["not_for_me"] == ["Food 14", "Sweets & Snacks"]
    assert "Food 15" not in str(got) and "Food 01" not in got["likes"]
    # few foods: the groups follow, the last one added first
    set_pref(conn, 2, 2, "like", "2026-10-02T00:00:00Z")
    store.set_user(conn, 2, "guidance", {"like_categories": ["Fruits", "Dairy & Alternatives", "Beverages"]})
    conn.commit()
    assert C.explicit_preferences(conn, 2, store) == {"likes": ["Food 02", "Beverages", "Dairy & Alternatives", "Fruits"],
                                                      "less_often": [], "not_for_me": ["Food 01"]}
    assert C.explicit_preferences(conn, 1) == got  # the default store reads the same rows
    nobody = C.explicit_preferences(conn, 3, store)
    assert nobody == {"likes": [], "less_often": [], "not_for_me": []}
    conn.close()


def test_the_default_limits_are_the_decided_ones():
    assert (C.MAX_FOOD_PREFERENCES, C.MAX_NOT_FOR_ME) == (1000, 500)
    assert C.PREFERENCE_VALUES == ("like", "less", "not_for_me", "neutral") and C.PREFERENCE_SOURCES == ("person", "ask")
