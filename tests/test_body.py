"""Weight and blood pressure log (schema step 18, ``app/body.py``, note 10): the routes, validation, the pure functions (units, the
weight-gain alarm, the 7-day means against the goal, the six-month change), the handbook's words for a warning sign, isolation
between people, deleting an account, the export and the import of ``export.json``.

The page that decides which numbers are warning signs is ``handbook/docs/get-help-now.md``; the tests below read it, so the app
cannot keep quoting words the page no longer has. The browser twin is checked by ``tests/test_body_vectors.py``.
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
from app import body
from app.auth import ratelimit
from app.main import create_app
from app.models import (
    MAX_BODY_BATCH,
    MAX_BODY_NOTE,
    MAX_READINGS_PER_DAY,
    MAX_SOURCE_KEY,
    MAX_WEIGHTS_PER_DAY,
)
from conftest import ADMIN_PASSWORD, ADMIN_USERNAME, USER_PASSWORD, TestClient, make_settings, signed_in_client
from test_data_import import export_doc, post_import

ROOT = Path(__file__).resolve().parents[1]
HANDBOOK_PAGE = ROOT / "handbook" / "docs" / "get-help-now.md"
WEIGHT_KEYS = {"id", "date", "time", "kg", "context", "note", "source", "created_at", "updated_at"}
READING_KEYS = {"id", "date", "time", "systolic", "diastolic", "pulse", "context", "note", "source", "created_at", "updated_at", "flag"}
FLAG_KEYS = {"level", "text", "href", "link_text", "prominent"}


def day(n: int = 0) -> str:
    return (date.today() - timedelta(days=n)).isoformat()


def w(kg: float = 70.0, when: str | None = None, context: str = "morning", **extra: Any) -> dict[str, Any]:
    return {"date": when or day(0), "kg": kg, "context": context, **extra}


def bp(systolic: int = 128, diastolic: int = 78, when: str | None = None, context: str = "morning", **extra: Any) -> dict[str, Any]:
    return {"date": when or day(0), "systolic": systolic, "diastolic": diastolic, "context": context, **extra}


def weights(client: TestClient, start: str | None = None, end: str | None = None) -> list[dict[str, Any]]:
    r = client.get("/api/body/weights", params={"start": start or day(60), "end": end or day(0)})
    assert r.status_code == 200, r.text
    return r.json()["weights"]


def readings(client: TestClient, start: str | None = None, end: str | None = None) -> list[dict[str, Any]]:
    r = client.get("/api/body/blood-pressure", params={"start": start or day(60), "end": end or day(0)})
    assert r.status_code == 200, r.text
    return r.json()["readings"]


def add_weight(client: TestClient, *args: Any, **kwargs: Any) -> dict[str, Any]:
    r = client.post("/api/body/weights", json=w(*args, **kwargs))
    assert r.status_code == 201, r.text
    return r.json()


def add_reading(client: TestClient, *args: Any, **kwargs: Any) -> dict[str, Any]:
    r = client.post("/api/body/blood-pressure", json=bp(*args, **kwargs))
    assert r.status_code == 201, r.text
    return r.json()


def summary(client: TestClient, when: str | None = None) -> dict[str, Any]:
    r = client.get("/api/body/summary", params={"date": when or day(0)})
    assert r.status_code == 200, r.text
    return r.json()


def set_setting(client: TestClient, key: str, value: Any) -> None:
    r = client.patch("/api/me/settings", json={key: value})
    assert r.status_code == 200, r.text


# --------------------------------------------------------------------------- the pure functions


def test_pounds_and_kilograms_use_the_exact_international_pound():
    assert body.KG_PER_LB == 0.45359237
    assert body.lb_to_kg(154.3) == 69.99 and body.lb_to_kg(1) == 0.45 and body.lb_to_kg(220.462) == 100.0
    assert body.lb_to_kg(0.45359237 * 100 / 0.45359237 + 0.0) == 45.36
    # half up on the shown number: 154.25 shows 154.3 (Python's own round() would give 154.2)
    assert body.shown_weight(154.25 * body.KG_PER_LB, "lb") == 154.3
    assert body.shown_weight(70.04, "kg") == 70.0 and body.shown_weight(70.05, "kg") == 70.1
    assert body.shown_weight(69.99, "lb") == 154.3
    assert body.format_weight(70, "kg") == "70.0 kg" and body.format_weight(69.99, "lb") == "154.3 lb"
    assert body.round_kg(70.125) == 70.13 and body.round_kg(70.124) == 70.12 and body.round_kg(19.999) == 20.0


def row_w(kg: float, when: str, context: str = "morning", time: str | None = None, n: int = 1) -> dict[str, Any]:
    return {"id": n, "date": when, "time": time, "kg": kg, "context": context, "note": "", "source": "manual",
            "created_at": "x", "updated_at": "x"}


def check(rows: list[dict[str, Any]], amount: float | None = 1.0, over: str = "days", days: int = 1, dry: float | None = None,
          unit: str = "kg") -> dict[str, Any] | None:
    return body.weight_alarm_check(rows, {"amount_kg": amount, "over": over, "days": days}, dry_weight_kg=dry, unit=unit)


def test_the_days_alarm_compares_the_same_context_and_is_over_only_when_more():
    rows = [row_w(70.0, "2026-10-19", n=1), row_w(70.2, "2026-10-20", n=2), row_w(71.2, "2026-10-21", n=3)]
    got = check(rows)
    assert got["status"] == "compared" and got["reference"]["id"] == 2 and got["reference_kind"] == "same_context"
    assert got["gain_kg"] == 1.0 and got["over_alarm"] is False and got["flag"] is None  # exactly the alarm is not more
    rows[-1]["kg"] = 71.21
    got = check(rows)
    assert got["gain_kg"] == 1.01 and got["over_alarm"] is True and got["flag"] == body.flag_of("weight_alarm")
    assert got["message"] == "Compared with your morning weight on 2026-10-20 (70.2 kg)."
    assert check(rows, unit="lb")["message"] == "Compared with your morning weight on 2026-10-20 (154.8 lb)."
    # a different context is not compared; looking back stops at 2 x days
    other = [row_w(70.0, "2026-10-20", "before_dialysis", n=1), row_w(72.0, "2026-10-21", "morning", n=2)]
    assert check(other)["status"] == "no_reference" and check(other)["message"] == "Not enough weights to compare yet"
    far = [row_w(70.0, "2026-10-18", n=1), row_w(72.0, "2026-10-21", n=2)]
    assert check(far)["status"] == "no_reference"  # 3 days back, the window is 2
    assert check(far, days=2)["reference"]["id"] == 1 and check(far, days=2)["gain_kg"] == 2.0  # 2 days: on or before 10-19, from 10-17
    same_day = [row_w(70.0, "2026-10-21", time="07:00", n=1), row_w(72.0, "2026-10-21", time="19:00", n=2)]
    assert check(same_day)["status"] == "no_reference"  # on or before the latest date minus the days: never the same day
    # the newest weight of the day it looks back to
    two = [row_w(70.0, "2026-10-20", time="06:00", n=1), row_w(70.5, "2026-10-20", time="08:00", n=2), row_w(71.0, "2026-10-21", n=3)]
    assert check(two)["reference"]["id"] == 2


def test_the_between_sessions_alarm_uses_the_last_weight_after_a_session_then_the_dry_weight():
    rows = [row_w(70.0, "2026-10-14", "after_dialysis", n=1), row_w(70.6, "2026-10-16", "after_dialysis", n=2),
            row_w(71.0, "2026-10-17", "morning", n=3), row_w(73.0, "2026-10-18", "before_dialysis", n=4)]
    got = check(rows, over="between_sessions", amount=2.0)
    assert got["reference_kind"] == "after_dialysis" and got["reference"]["id"] == 2 and got["gain_kg"] == 2.4 and got["over_alarm"] is True
    assert got["message"] == "Compared with your weight after dialysis on 2026-10-16 (70.6 kg)."
    # older than 7 days before the latest weight: the dry weight in Profile, labelled, when there is one
    old = [row_w(70.0, "2026-10-10", "after_dialysis", n=1), row_w(73.0, "2026-10-18", "before_dialysis", n=2)]
    assert check(old, over="between_sessions")["status"] == "no_reference"
    assert check(old, over="between_sessions")["message"] == "Add a weight after a session to compare"
    dry = check(old, over="between_sessions", dry=71.0)
    assert dry["reference_kind"] == "dry_weight" and dry["reference"] is None and dry["reference_kg"] == 71.0
    assert dry["gain_kg"] == 2.0 and dry["over_alarm"] is True
    assert dry["message"] == "Compared with your dry weight in Profile (71.0 kg)."
    # the 7 days are inclusive; the same day counts only when it is earlier; a latest weight never compares with itself
    edge = [row_w(70.0, "2026-10-11", "after_dialysis", n=1), row_w(73.0, "2026-10-18", n=2)]
    assert check(edge, over="between_sessions")["reference"]["id"] == 1
    same = [row_w(70.0, "2026-10-18", "after_dialysis", time="12:00", n=1), row_w(72.0, "2026-10-18", "before_dialysis", time="18:00", n=2)]
    assert check(same, over="between_sessions")["reference"]["id"] == 1
    later = [row_w(72.0, "2026-10-18", "before_dialysis", time="09:00", n=1), row_w(70.0, "2026-10-18", "after_dialysis", time="12:00", n=2)]
    assert check(later, over="between_sessions")["status"] == "no_reference"
    assert check([row_w(70.0, "2026-10-18", "after_dialysis")], over="between_sessions")["status"] == "no_reference"


def test_no_alarm_number_or_no_weight_means_no_check():
    assert check([row_w(70.0, "2026-10-18")], amount=None) is None
    assert check([]) is None


def reading(systolic: int, diastolic: int, when: str, n: int = 1, time: str | None = None) -> dict[str, Any]:
    return {"id": n, "date": when, "time": time, "systolic": systolic, "diastolic": diastolic, "pulse": None, "context": "morning",
            "note": "", "source": "manual", "created_at": "x", "updated_at": "x", "flag": body.bp_flag(systolic, diastolic)}


def test_the_week_means_round_half_up_and_the_goal_boundary_is_at_or_above():
    rows = [reading(130, 80, day(6), 1), reading(131, 81, day(3), 2), reading(129, 79, day(0), 3), reading(300, 200, day(7), 4)]
    got = body.blood_pressure_week(rows, day(0), {"systolic": 130, "diastolic": 80})
    assert (got["count"], got["systolic"], got["diastolic"], got["few"]) == (3, 130, 80, False)  # the 7th day back is out
    assert got["above"] == {"systolic": True, "diastolic": True} and got["above_goal"] is True  # 130 is not under 130
    got = body.blood_pressure_week(rows, day(0), {"systolic": 131, "diastolic": 81})
    assert got["above"] == {"systolic": False, "diastolic": False} and got["above_goal"] is False
    got = body.blood_pressure_week(rows, day(0), {"systolic": 130, "diastolic": None})
    assert got["above"] == {"systolic": True, "diastolic": None} and got["above_goal"] is True
    got = body.blood_pressure_week(rows, day(0), {"systolic": None, "diastolic": None})
    assert got["above_goal"] is None and got["systolic"] == 130
    half = [reading(127, 77, day(2), 1), reading(128, 78, day(1), 2), reading(128, 78, day(0), 3), reading(127, 77, day(0), 4)]
    assert (body.blood_pressure_week(half, day(0), {})["systolic"], body.blood_pressure_week(half, day(0), {})["diastolic"]) == (128, 78)
    # fewer than 3 readings: the means, "few", and no verdict
    two = body.blood_pressure_week(rows[:2], day(0), {"systolic": 100, "diastolic": 60})
    assert (two["count"], two["few"], two["above_goal"], two["above"]) == (2, True, None, {"systolic": None, "diastolic": None})
    assert two["systolic"] == 131  # 130.5 rounds half up
    none = body.blood_pressure_week([], day(0), {"systolic": 100})
    assert (none["count"], none["systolic"], none["diastolic"], none["few"], none["above_goal"]) == (0, None, None, True, None)


@pytest.mark.parametrize("systolic, diastolic, flagged", [
    (179, 119, False), (180, 80, True), (140, 120, True), (181, 121, True), (180, 120, True), (300, 199, True), (120, 80, False),
    (179, 120, True), (180, 119, True),
])
def test_the_flag_boundaries(systolic, diastolic, flagged):
    flag = body.bp_flag(systolic, diastolic)
    assert (flag is not None) is flagged
    if flag:
        assert flag == body.flag_of("blood_pressure") and flag["prominent"] is True and flag["level"] == "emergency"
        assert flag["href"] == "/learn/get-help-now/" and flag["link_text"] == "Get help now"


def test_the_six_month_change_picks_the_weight_closest_to_182_days_back_within_30_days():
    latest = row_w(70.0, "2026-10-20", n=9)
    assert (date(2026, 10, 20) - date(2026, 4, 21)).days == 182  # the day it looks for: 2026-04-21
    got = body.six_month_change([row_w(74.0, "2026-04-21", n=1), latest])
    assert got["earlier"]["id"] == 1 and got["days"] == 182 and got["change_kg"] == -4.0 and got["change_pct"] == -5.4
    assert got["latest"]["id"] == 9
    # the closest day wins
    rows = [row_w(76.0, "2026-04-10", n=1), row_w(75.0, "2026-04-26", n=2), row_w(74.0, "2026-04-18", n=3), latest]
    assert body.six_month_change(rows)["earlier"]["id"] == 3  # 3 days away, against 5 and 11
    # a tie in distance goes to the earlier day, then to the later weight of that day
    rows = [row_w(75.0, "2026-04-24", n=1), row_w(74.0, "2026-04-18", n=2), latest]
    assert body.six_month_change(rows)["earlier"]["id"] == 2
    rows = [row_w(74.0, "2026-04-21", time="07:00", n=1), row_w(73.0, "2026-04-21", time="19:00", n=2), latest]
    assert body.six_month_change(rows)["earlier"]["id"] == 2
    # the window is 30 days either side
    assert body.six_month_change([row_w(74.0, "2026-05-21", n=1), latest])["earlier"]["id"] == 1
    assert body.six_month_change([row_w(74.0, "2026-05-22", n=1), latest]) is None
    assert body.six_month_change([row_w(74.0, "2026-03-22", n=1), latest])["earlier"]["id"] == 1
    assert body.six_month_change([row_w(74.0, "2026-03-21", n=1), latest]) is None
    # a weight is never compared with itself; nothing to compare with is none
    assert body.six_month_change([latest]) is None and body.six_month_change([]) is None
    # a gain: kg to 0.01 and percent to one decimal, half up (65.0 -> 70.0 is 7.69...%)
    assert body.six_month_change([row_w(65.0, "2026-04-21", n=1), latest])["change_pct"] == 7.7
    assert body.six_month_change([row_w(65.0, "2026-04-21", n=1), latest])["change_kg"] == 5.0


# --------------------------------------------------------------------------- the routes


def test_create_list_update_delete_a_weight(client):
    made = add_weight(client, 70.256, day(1), time="07:30", note="after the long night")
    assert set(made) == WEIGHT_KEYS
    assert (made["kg"], made["time"], made["note"], made["source"], made["context"]) == (70.26, "07:30", "after the long night", "manual", "morning")
    assert made["created_at"].endswith("Z") and made["created_at"] == made["updated_at"]
    later = add_weight(client, 71.0, day(0), context="other")
    assert later["time"] is None and later["note"] == ""
    assert [x["id"] for x in weights(client)] == [made["id"], later["id"]]  # oldest first
    assert [x["id"] for x in weights(client, day(0), day(0))] == [later["id"]]
    r = client.put(f"/api/body/weights/{made['id']}", json=w(72.5, day(2), "after_dialysis", note=""))
    assert r.status_code == 200, r.text
    updated = r.json()
    assert (updated["id"], updated["kg"], updated["date"], updated["context"], updated["note"], updated["time"], updated["created_at"]) == \
        (made["id"], 72.5, day(2), "after_dialysis", "", None, made["created_at"])
    assert updated["updated_at"] >= made["updated_at"]
    assert [x["id"] for x in weights(client)] == [made["id"], later["id"]]
    assert client.delete(f"/api/body/weights/{later['id']}").status_code == 204
    assert client.delete(f"/api/body/weights/{later['id']}").status_code == 404
    assert client.put(f"/api/body/weights/{later['id']}", json=w()).status_code == 404
    assert [x["id"] for x in weights(client)] == [made["id"]]


def test_create_list_update_delete_a_reading(client):
    made = add_reading(client, 128, 78, day(1), time="07:35", pulse=64, note="seated")
    assert set(made) == READING_KEYS
    assert (made["systolic"], made["diastolic"], made["pulse"], made["time"], made["flag"], made["source"]) == (128, 78, 64, "07:35", None, "manual")
    later = add_reading(client, 150, 95, day(0), context="evening")
    assert later["pulse"] is None and later["time"] is None
    assert [x["id"] for x in readings(client)] == [made["id"], later["id"]]
    r = client.put(f"/api/body/blood-pressure/{made['id']}", json=bp(190, 100, day(1), "before_dialysis"))
    assert r.status_code == 200, r.text
    updated = r.json()
    assert (updated["systolic"], updated["context"], updated["pulse"], updated["created_at"]) == (190, "before_dialysis", None, made["created_at"])
    assert set(updated["flag"]) == FLAG_KEYS  # the change is flagged now
    assert [x["flag"] is not None for x in readings(client)] == [True, False]
    assert client.delete(f"/api/body/blood-pressure/{later['id']}").status_code == 204
    assert client.delete(f"/api/body/blood-pressure/{later['id']}").status_code == 404
    assert client.put(f"/api/body/blood-pressure/{later['id']}", json=bp()).status_code == 404
    assert [x["id"] for x in readings(client)] == [made["id"]]


def test_the_list_orders_by_day_then_time_with_no_time_last_then_id(client):
    ids = [add_weight(client, 70 + i, day(1), time=t)["id"] for i, t in enumerate(["12:00", None, "07:00", None, "07:00"])]
    earlier = add_weight(client, 60, day(2), time="23:59")["id"]
    assert [x["id"] for x in weights(client)] == [earlier, ids[2], ids[4], ids[0], ids[1], ids[3]]
    rids = [add_reading(client, 130, 80, day(1), time=t)["id"] for t in ["12:00", None, "07:00"]]
    assert [x["id"] for x in readings(client)] == [rids[2], rids[0], rids[1]]


def test_a_blank_time_is_no_time_and_kg_text_is_read(client):
    assert add_weight(client, 70, time="  ")["time"] is None
    assert add_weight(client, "70.5")["kg"] == 70.5
    assert add_reading(client, time="")["time"] is None
    made = client.post("/api/body/blood-pressure", json=bp(pulse=None, note=None)).json()
    assert (made["pulse"], made["note"]) == (None, "")


def test_the_range_ends_are_accepted_and_one_past_them_is_refused(client):
    for kg in (20, 400, 20.004, 399.996):
        assert client.post("/api/body/weights", json=w(kg)).status_code == 201, kg
    for kg in (19.99, 400.01, 0, -5):
        assert client.post("/api/body/weights", json=w(kg)).status_code == 400, kg
    for s, d, p in ((50, 20, 20), (300, 200, 250), (51, 50, 21)):
        assert client.post("/api/body/blood-pressure", json=bp(s, d, pulse=p)).status_code == 201, (s, d, p)
    for s, d, p in ((49, 20, None), (301, 200, None), (120, 19, None), (250, 201, None), (120, 80, 19), (120, 80, 251)):
        assert client.post("/api/body/blood-pressure", json=bp(s, d, pulse=p)).status_code == 400, (s, d, p)
    assert [x["kg"] for x in weights(client)] == [20.0, 400.0, 20.0, 400.0]


@pytest.mark.parametrize("change, fragment", [
    ({"kg": 19}, "kg: Input should be greater than or equal to 20"),
    ({"kg": 401}, "kg: Input should be less than or equal to 400"),
    ({"kg": "heavy"}, "kg: Input should be a valid number"),
    ({"kg": None}, "kg: Input should be a valid number"),
    ({"context": "evening"}, "context: Input should be 'morning', 'before_dialysis', 'after_dialysis' or 'other'"),
    ({"context": None}, "context: Input should be"),
    ({"date": "2999-01-01"}, "date: must not be in the future"),
    ({"date": "1899-12-31"}, "date: must be 1900 or later"),
    ({"date": "10/05/2026"}, "date: date must be formatted YYYY-MM-DD"),
    ({"date": "2026-02-30"}, "date: date is not a valid calendar date"),
    ({"date": 20261005}, "date: Input should be a valid string"),
    ({"time": "7:30"}, "time: must be a time such as 07:30 (HH:MM, 00:00 to 23:59)"),
    ({"time": "24:00"}, "time: must be a time such as 07:30 (HH:MM, 00:00 to 23:59)"),
    ({"time": "12:60"}, "time: must be a time such as 07:30"),
    ({"time": 730}, "time: Input should be a valid string"),
    ({"note": "n" * (MAX_BODY_NOTE + 1)}, f"note: String should have at most {MAX_BODY_NOTE} characters"),
    ({"note": "😀" * (MAX_BODY_NOTE + 1)}, f"note: String should have at most {MAX_BODY_NOTE} characters"),
    ({"note": "bad\x00note"}, "note: must be plain text"),
    ({"note": 5}, "note: Input should be a valid string"),
    ({"surprise": 1}, "surprise: Extra inputs are not permitted"),
    ({"id": 7}, "id: Extra inputs are not permitted"),
    ({"user_id": 2}, "user_id: Extra inputs are not permitted"),
    ({"source": "apple_health"}, "source: Extra inputs are not permitted"),
    ({"source_key": "k"}, "source_key: Extra inputs are not permitted"),
])
def test_bad_weights_are_refused_and_nothing_is_stored(client, change, fragment):
    payload = {**w(70.0), **change}
    r = client.post("/api/body/weights", json=payload)
    assert r.status_code == 400, r.text
    assert fragment in r.json()["detail"], r.json()
    assert weights(client) == []
    good = add_weight(client)
    assert client.put(f"/api/body/weights/{good['id']}", json=payload).status_code == 400  # the same rules for a change
    assert weights(client) == [good]


@pytest.mark.parametrize("change, fragment", [
    ({"systolic": 49}, "systolic: Input should be greater than or equal to 50"),
    ({"systolic": 301}, "systolic: Input should be less than or equal to 300"),
    ({"diastolic": 19}, "diastolic: Input should be greater than or equal to 20"),
    ({"diastolic": 201}, "diastolic: Input should be less than or equal to 200"),
    ({"pulse": 19}, "pulse: Input should be greater than or equal to 20"),
    ({"pulse": 251}, "pulse: Input should be less than or equal to 250"),
    ({"systolic": 80, "diastolic": 80}, "systolic must be greater than diastolic"),
    ({"systolic": 70, "diastolic": 90}, "systolic must be greater than diastolic"),
    ({"systolic": 120.5}, "systolic: Input should be a valid integer"),
    ({"systolic": "high"}, "systolic: Input should be a valid integer"),
    ({"systolic": None}, "systolic: Input should be a valid integer"),
    ({"pulse": "fast"}, "pulse: Input should be a valid integer"),
    ({"context": "other_time"}, "context: Input should be 'morning', 'evening', 'before_dialysis', 'after_dialysis' or 'other'"),
    ({"date": "2999-01-01"}, "date: must not be in the future"),
    ({"time": "99:99"}, "time: must be a time such as 07:30"),
    ({"note": "n" * (MAX_BODY_NOTE + 1)}, f"note: String should have at most {MAX_BODY_NOTE} characters"),
    ({"surprise": 1}, "surprise: Extra inputs are not permitted"),
    ({"flag": None}, "flag: Extra inputs are not permitted"),
])
def test_bad_readings_are_refused_and_nothing_is_stored(client, change, fragment):
    payload = {**bp(128, 78), **change}
    r = client.post("/api/body/blood-pressure", json=payload)
    assert r.status_code == 400, r.text
    assert fragment in r.json()["detail"], r.json()
    assert readings(client) == []
    good = add_reading(client)
    assert client.put(f"/api/body/blood-pressure/{good['id']}", json=payload).status_code == 400
    assert readings(client) == [good]


def test_infinity_and_not_a_number_are_refused(client):
    for literal in ("Infinity", "-Infinity", "NaN"):
        content = ('{"date": "%s", "kg": %s, "context": "morning"}' % (day(0), literal)).encode()
        r = client.post("/api/body/weights", content=content, headers={"content-type": "application/json"})
        assert r.status_code == 400 and "kg: Input should be a finite number" in r.json()["detail"], (literal, r.text)
    assert weights(client) == []


def test_several_problems_come_in_the_models_order(client):
    r = client.post("/api/body/weights", json={"context": "x", "kg": 5, "time": "x", "date": "bad", "note": 5, "extra": 1})
    assert r.json()["detail"].split("; ")[0].startswith("date:")
    keys = [part.split(":")[0] for part in r.json()["detail"].split("; ")]
    assert keys == ["date", "time", "kg", "context", "note", "extra"]


def test_missing_fields_and_a_body_that_is_not_an_object_are_refused(client):
    r = client.post("/api/body/weights", json={})
    assert r.status_code == 400 and all(f"{k}: Field required" in r.json()["detail"] for k in ("date", "kg", "context"))
    r = client.post("/api/body/blood-pressure", json={})
    assert r.status_code == 400 and all(f"{k}: Field required" in r.json()["detail"] for k in ("date", "systolic", "diastolic", "context"))
    assert client.post("/api/body/weights", json=[w()]).status_code == 400
    assert client.post("/api/body/blood-pressure", content=b"not json", headers={"content-type": "application/json"}).status_code == 400


def test_a_day_holds_a_bounded_number_and_a_move_into_a_full_day_is_refused(client):
    for _ in range(MAX_WEIGHTS_PER_DAY):
        add_weight(client, 70, day(5))
    r = client.post("/api/body/weights", json=w(70, day(5)))
    assert r.status_code == 400 and r.json()["detail"] == f"too many weights for one day (max {MAX_WEIGHTS_PER_DAY})"
    other = add_weight(client, 70, day(4))
    assert client.put(f"/api/body/weights/{other['id']}", json=w(70, day(5))).status_code == 400
    assert weights(client, day(4), day(4))[0]["date"] == day(4)
    inside = weights(client, day(5), day(5))[0]
    assert client.put(f"/api/body/weights/{inside['id']}", json=w(71, day(5))).status_code == 200  # editing in a full day
    for _ in range(MAX_READINGS_PER_DAY):
        add_reading(client, 120, 80, day(5))
    r = client.post("/api/body/blood-pressure", json=bp(120, 80, day(5)))
    assert r.status_code == 400 and r.json()["detail"] == f"too many blood pressure readings for one day (max {MAX_READINGS_PER_DAY})"
    assert (MAX_WEIGHTS_PER_DAY, MAX_READINGS_PER_DAY) == (20, 30)


@pytest.mark.parametrize("path", ["weights", "blood-pressure"])
@pytest.mark.parametrize("params, fragment", [
    ({}, "start is required (YYYY-MM-DD)"),
    ({"start": day(1)}, "end is required (YYYY-MM-DD)"),
    ({"start": "soon", "end": day(0)}, "start: date must be formatted YYYY-MM-DD"),
    ({"start": day(0), "end": day(3)}, "end must not be before start"),
    ({"start": day(400), "end": day(0)}, "range too large (max 366 days)"),
])
def test_the_lists_need_a_sensible_date_range(client, path, params, fragment):
    r = client.get(f"/api/body/{path}", params=params)
    assert r.status_code == 400 and r.json()["detail"] == fragment


def test_the_range_includes_both_ends_and_nothing_else(client):
    ids = {n: add_weight(client, 70, day(n))["id"] for n in (0, 1, 2, 3)}
    assert [x["id"] for x in weights(client, day(2), day(1))] == [ids[2], ids[1]]
    assert weights(client, day(10), day(5)) == []


@pytest.mark.parametrize("path, make", [("weights", w), ("blood-pressure", bp)])
def test_ids_that_cannot_exist_are_404_or_a_validation_error(client, path, make):
    for row_id in ("0", "-1", "99999999999999999999"):
        assert client.delete(f"/api/body/{path}/{row_id}").status_code == 404
        assert client.put(f"/api/body/{path}/{row_id}", json=make()).status_code == 404
    r = client.delete(f"/api/body/{path}/abc")
    assert r.status_code == 400 and "_id: Input should be a valid integer" in r.json()["detail"]


def test_a_row_from_a_later_version_is_kept_hidden_and_exported(client):
    mine = add_weight(client)
    mine_bp = add_reading(client)
    conn = sqlite3.connect(client.app.state.settings.db_path)
    conn.execute("INSERT INTO weights (user_id, date, time, kg, context, note, source, created_at, updated_at) "
                 "VALUES (1, ?, NULL, 70, 'bedtime', NULL, 'manual', 'x', 'x')", (day(0),))
    conn.execute("INSERT INTO weights (user_id, date, time, kg, context, note, source, created_at, updated_at) "
                 "VALUES (1, ?, NULL, 71, 'morning', NULL, 'withings', 'x', 'x')", (day(0),))
    conn.execute("INSERT INTO blood_pressures (user_id, date, time, systolic, diastolic, pulse, context, note, source, created_at, updated_at) "
                 "VALUES (1, ?, NULL, 120, 80, NULL, 'nap', NULL, 'manual', 'x', 'x')", (day(0),))
    conn.commit()
    conn.close()
    assert [x["id"] for x in weights(client)] == [mine["id"]] and [x["id"] for x in readings(client)] == [mine_bp["id"]]
    doc = export_doc(client)
    assert [row["context"] for row in doc["weights"]] == ["morning", "bedtime", "morning"]
    assert [row["source"] for row in doc["weights"]] == ["manual", "manual", "withings"]
    assert len(doc["blood_pressures"]) == 2 and doc["blood_pressures"][1]["context"] == "nap"
    assert summary(client)["weight"]["latest"]["id"] == mine["id"]  # the summary leaves them out too


def test_the_ids_are_never_reused(client):
    first = add_weight(client)
    assert client.delete(f"/api/body/weights/{first['id']}").status_code == 204
    assert add_weight(client)["id"] == first["id"] + 1


# --------------------------------------------------------------------------- the batch routes


def key_rows(kind: str, n: int, when: str | None = None, prefix: str = "k") -> list[dict[str, Any]]:
    out = []
    for i in range(n):
        base = w(70 + i * 0.1, when or day(3), "other") if kind == "weights" else bp(120 + i, 80, when or day(3), "other")
        out.append({**base, "source": "apple_health", "source_key": f"{prefix}{i}"})
    return out


@pytest.mark.parametrize("path, kind", [("weights", "weights"), ("blood-pressure", "readings")])
def test_a_batch_adds_rows_skips_known_keys_and_repeats_and_changes_nothing_on_a_bad_row(client, path, kind):
    rows = key_rows("weights" if path == "weights" else "bp", 3)
    r = client.post(f"/api/body/{path}/batch", json={"rows": [*rows, rows[0]]})  # a repeat inside the request
    assert r.status_code == 200, r.text
    assert r.json() == {"added": 3, "skipped": 1}
    listed = (weights if path == "weights" else readings)(client)
    assert len(listed) == 3 and {x["source"] for x in listed} == {"apple_health"}
    r = client.post(f"/api/body/{path}/batch", json={"rows": rows})  # the same import again adds nothing
    assert r.json() == {"added": 0, "skipped": 3}
    more = key_rows("weights" if path == "weights" else "bp", 2, prefix="n")
    bad = {**more[1], "context": "nope"}
    r = client.post(f"/api/body/{path}/batch", json={"rows": [more[0], bad, {"nonsense": 1}]})
    assert r.status_code == 400 and r.json()["detail"].startswith("rows.1.context: Input should be"), r.json()
    assert len((weights if path == "weights" else readings)(client)) == 3  # all or nothing
    default = {k: v for k, v in more[0].items() if k != "source"}
    assert client.post(f"/api/body/{path}/batch", json={"rows": [default]}).json() == {"added": 1, "skipped": 0}
    assert (weights if path == "weights" else readings)(client)[-1]["source"] == "import"


def test_a_batch_names_the_first_invalid_row_with_all_its_problems(client):
    rows = key_rows("weights", 3)
    rows[2] = {**rows[2], "kg": 5, "date": "2999-01-01", "source": "manual"}
    rows[1] = {**rows[1], "source_key": ""}
    r = client.post("/api/body/weights/batch", json={"rows": rows})
    assert r.status_code == 400
    assert r.json()["detail"] == "rows.1.source_key: String should have at least 1 character"
    r = client.post("/api/body/weights/batch", json={"rows": [rows[0], rows[2]]})
    assert r.json()["detail"] == ("rows.1.date: must not be in the future; rows.1.kg: Input should be greater than or equal to 20; "
                                  "rows.1.source: Input should be 'apple_health' or 'import'")
    r = client.post("/api/body/blood-pressure/batch", json={"rows": [{**bp(80, 80), "source_key": "a"}]})
    assert r.json()["detail"] == "rows.0: systolic must be greater than diastolic"
    long_key = {**key_rows("weights", 1)[0], "source_key": "k" * (MAX_SOURCE_KEY + 1)}
    r = client.post("/api/body/weights/batch", json={"rows": [long_key]})
    assert r.json()["detail"] == f"rows.0.source_key: String should have at most {MAX_SOURCE_KEY} characters"
    assert weights(client) == []


@pytest.mark.parametrize("payload, fragment", [
    ({}, "rows: Field required"),
    ({"rows": []}, "rows: List should have at least 1 item after validation, not 0"),
    ({"rows": "x"}, "rows: Input should be a valid list"),
    ({"rows": [5]}, "rows.0: Input should be a valid dictionary"),
    ({"rows": [{}], "extra": 1}, "extra: Extra inputs are not permitted"),
    ({"rows": [{}] * (MAX_BODY_BATCH + 1)}, f"rows: List should have at most {MAX_BODY_BATCH} items after validation, not {MAX_BODY_BATCH + 1}"),
])
def test_the_batch_body_has_a_shape(client, payload, fragment):
    r = client.post("/api/body/weights/batch", json=payload)
    assert r.status_code == 400 and fragment in r.json()["detail"], r.json()


def test_a_batch_may_hold_the_most_rows(client):
    rows = [{**w(70, day(1 + i // MAX_WEIGHTS_PER_DAY), "other"), "source": "import", "source_key": f"b{i}"} for i in range(MAX_BODY_BATCH)]
    r = client.post("/api/body/weights/batch", json={"rows": rows})
    assert r.status_code == 200 and r.json() == {"added": MAX_BODY_BATCH, "skipped": 0}


def test_a_batch_that_would_overfill_a_day_is_refused_and_writes_nothing(client):
    for _ in range(MAX_WEIGHTS_PER_DAY - 1):
        add_weight(client, 70, day(3))
    rows = key_rows("weights", 2)
    r = client.post("/api/body/weights/batch", json={"rows": rows})
    assert r.status_code == 400 and r.json()["detail"] == f"rows.1: too many weights for one day (max {MAX_WEIGHTS_PER_DAY})"
    assert len(weights(client)) == MAX_WEIGHTS_PER_DAY - 1
    assert client.post("/api/body/weights/batch", json={"rows": rows[:1]}).json() == {"added": 1, "skipped": 0}
    # a known key never counts against the day
    assert client.post("/api/body/weights/batch", json={"rows": rows[:1]}).json() == {"added": 0, "skipped": 1}
    for _ in range(MAX_READINGS_PER_DAY):
        add_reading(client, 120, 80, day(4))
    r = client.post("/api/body/blood-pressure/batch", json={"rows": key_rows("bp", 1, day(4))})
    assert r.status_code == 400 and r.json()["detail"] == f"rows.0: too many blood pressure readings for one day (max {MAX_READINGS_PER_DAY})"


def test_a_row_the_person_edited_keeps_its_import_key_so_a_second_import_does_not_bring_the_old_value_back(client):
    rows = key_rows("weights", 1)
    client.post("/api/body/weights/batch", json={"rows": rows})
    mine = weights(client)[0]
    assert mine["source"] == "apple_health"
    assert client.put(f"/api/body/weights/{mine['id']}", json=w(81.5, day(3), "other")).json()["source"] == "manual"
    assert client.post("/api/body/weights/batch", json={"rows": rows}).json() == {"added": 0, "skipped": 1}
    assert [x["kg"] for x in weights(client)] == [81.5]
    assert export_doc(client)["weights"][0]["source_key"] == "k0"
    # the key can be deleted with the row, and then the same import brings it back
    assert client.delete(f"/api/body/weights/{mine['id']}").status_code == 204
    assert client.post("/api/body/weights/batch", json={"rows": rows}).json() == {"added": 1, "skipped": 0}


def test_the_batch_routes_allow_sixty_requests_an_hour_per_person(client, monkeypatch):
    assert ratelimit.LIMITS["body_batch"].max_requests == 60 and ratelimit.LIMITS["body_batch"].window_s == 3600
    monkeypatch.setitem(ratelimit.LIMITS, "body_batch", ratelimit.Limit("body_batch", 3, 3600, "Too many imports of weights and readings. Try again later."))
    rows = key_rows("weights", 1)
    for _ in range(2):
        assert client.post("/api/body/weights/batch", json={"rows": rows}).status_code == 200
    assert client.post("/api/body/blood-pressure/batch", json={"rows": key_rows("bp", 1)}).status_code == 200  # one limit for both
    r = client.post("/api/body/weights/batch", json={"rows": rows})
    assert r.status_code == 429 and r.headers["retry-after"] and "Too many imports" in r.json()["detail"]


# --------------------------------------------------------------------------- the summary


def test_the_summary_of_an_empty_log(client):
    s = summary(client)
    assert s == {"date": day(0), "units": "lb",
                 "weight": {"latest": None, "previous": None, "gain": None, "alarm": None},
                 "bp": {"latest": None, "week": {"count": 0, "systolic": None, "diastolic": None, "above_goal": None,
                                                 "above": {"systolic": None, "diastolic": None}, "few": True},
                        "goal": {"systolic": None, "diastolic": None}, "flagged_today": None}}


@pytest.mark.parametrize("params, fragment", [
    ({}, "date is required (YYYY-MM-DD)"),
    ({"date": "soon"}, "date: date must be formatted YYYY-MM-DD"),
])
def test_the_summary_needs_a_date(client, params, fragment):
    r = client.get("/api/body/summary", params=params)
    assert r.status_code == 400 and r.json()["detail"] == fragment


def test_the_summary_follows_the_settings_and_the_date(client):
    add_weight(client, 70.0, day(2), time="07:00")
    add_weight(client, 70.4, day(1), time="07:00")
    add_weight(client, 71.6, day(0), time="07:00")
    add_weight(client, 99.0, day(0), "other", time="23:00")  # later in the same day: the latest
    s = summary(client)
    assert s["weight"]["latest"]["kg"] == 99.0 and s["weight"]["previous"]["kg"] == 71.6
    assert s["weight"]["gain"]["kg"] == 27.4 and s["weight"]["gain"]["since"]["kg"] == 71.6 and s["weight"]["alarm"] is None
    s = summary(client, day(1))  # as of yesterday: later rows are ignored
    assert (s["weight"]["latest"]["kg"], s["weight"]["previous"]["kg"], s["weight"]["gain"]["kg"]) == (70.4, 70.0, 0.4)
    set_setting(client, "body.weight_alarm", {"amount_kg": 1.0, "over": "days", "days": 1})
    set_setting(client, "user.units.weight", "kg")
    s = summary(client, day(0))
    assert s["units"] == "kg" and s["weight"]["alarm"]["status"] == "no_reference"  # 99.0 is "other": nothing like it yesterday
    under = summary(client, day(1))["weight"]["alarm"]
    assert (under["over_alarm"], under["gain_kg"], under["flag"]) == (False, 0.4, None)
    assert client.delete(f"/api/body/weights/{summary(client)['weight']['latest']['id']}").status_code == 204
    over = summary(client)["weight"]["alarm"]
    assert (over["over_alarm"], over["gain_kg"], over["amount_kg"], over["over"], over["days"]) == (True, 1.2, 1.0, "days", 1)
    assert over["flag"]["text"] == body.RED_FLAGS["weight_alarm"]["text"] and over["flag"]["prominent"] is False
    assert over["message"] == "Compared with your morning weight on " + day(1) + " (70.4 kg)."
    set_setting(client, "user.units.weight", "lb")
    assert summary(client)["weight"]["alarm"]["message"] == "Compared with your morning weight on " + day(1) + " (155.2 lb)."


def test_the_between_sessions_alarm_uses_the_profile_dry_weight_only_on_hemodialysis(client):
    assert client.put("/api/profile", json={"weight_kg": 70, "dialysis": "none"}).status_code == 200
    set_setting(client, "body.weight_alarm", {"amount_kg": 2.0, "over": "between_sessions"})
    add_weight(client, 73.0, day(0), "before_dialysis")
    assert summary(client)["weight"]["alarm"]["status"] == "no_reference"
    assert summary(client)["weight"]["alarm"]["message"] == "Add a weight after a session to compare"
    assert client.put("/api/profile", json={"weight_kg": 70, "dialysis": "hemodialysis"}).status_code == 200
    alarm = summary(client)["weight"]["alarm"]
    assert (alarm["reference_kind"], alarm["reference"], alarm["reference_kg"], alarm["gain_kg"], alarm["over_alarm"]) == \
        ("dry_weight", None, 70.0, 3.0, True)
    assert alarm["message"] == "Compared with your dry weight in Profile (154.3 lb)."
    add_weight(client, 70.8, day(2), "after_dialysis")
    alarm = summary(client)["weight"]["alarm"]
    assert (alarm["reference_kind"], alarm["reference"]["kg"], alarm["gain_kg"], alarm["over_alarm"]) == ("after_dialysis", 70.8, 2.2, True)


def test_the_blood_pressure_summary(client):
    for i, (s, d) in enumerate([(130, 80), (140, 90), (120, 70), (125, 75)]):
        add_reading(client, s, d, day(i))
    set_setting(client, "body.bp_goal", {"systolic": 130, "diastolic": 80})
    week = summary(client)["bp"]
    assert week["goal"] == {"systolic": 130, "diastolic": 80} and week["latest"]["systolic"] == 130 and week["flagged_today"] is None
    assert week["week"] == {"count": 4, "systolic": 129, "diastolic": 79, "few": False, "above_goal": False,
                            "above": {"systolic": False, "diastolic": False}}
    add_reading(client, 190, 95, day(0), time="08:00")
    add_reading(client, 150, 90, day(0), time="09:00")
    s = summary(client)["bp"]
    assert s["flagged_today"]["systolic"] == 190 and s["flagged_today"]["flag"] == body.flag_of("blood_pressure")
    assert s["latest"]["systolic"] == 130  # a reading with no time comes after the day's timed readings
    assert s["week"]["count"] == 6 and s["week"]["above_goal"] is True
    assert summary(client, day(1))["bp"]["flagged_today"] is None  # a flag belongs to its day


# --------------------------------------------------------------------------- settings


def test_the_body_settings_have_defaults_and_validate(client):
    settings = client.get("/api/me/settings").json()["settings"]
    assert settings["user.units.weight"] == {"value": "lb", "source": "default", "editable": True}
    assert settings["body.weight_alarm"]["value"] == {"amount_kg": None, "over": "days", "days": 1}
    assert settings["body.bp_goal"]["value"] == {"systolic": None, "diastolic": None}
    set_setting(client, "user.units.weight", "kg")
    set_setting(client, "body.weight_alarm", {"amount_kg": 0.9, "over": "between_sessions", "days": 3})
    set_setting(client, "body.bp_goal", {"systolic": 130, "diastolic": 80})
    after = client.get("/api/me/settings").json()["settings"]
    assert after["user.units.weight"]["value"] == "kg" and after["body.weight_alarm"]["value"] == {"amount_kg": 0.9, "over": "between_sessions", "days": 3}
    assert after["body.bp_goal"]["source"] == "user"
    for key, value, fragment in [
        ("user.units.weight", "stone", "Input should be 'kg' or 'lb'"),
        ("body.weight_alarm", {"amount_kg": 0.19}, "Input should be greater than or equal to 0.2"),
        ("body.weight_alarm", {"amount_kg": 10.01}, "Input should be less than or equal to 10"),
        ("body.weight_alarm", {"amount_kg": "lots"}, "Input should be a valid number"),
        ("body.weight_alarm", {"over": "weeks"}, "Input should be 'between_sessions' or 'days'"),
        ("body.weight_alarm", {"days": 8}, "Input should be less than or equal to 7"),
        ("body.weight_alarm", {"days": 0}, "Input should be greater than or equal to 1"),
        ("body.weight_alarm", {"extra": 1}, "Extra inputs are not permitted"),
        ("body.bp_goal", {"systolic": 79}, "Input should be greater than or equal to 80"),
        ("body.bp_goal", {"diastolic": 131}, "Input should be less than or equal to 130"),
        ("body.bp_goal", {"systolic": 120, "diastolic": 120}, "systolic must be greater than diastolic"),
        ("body.bp_goal", {"systolic": 130, "other": 1}, "Extra inputs are not permitted"),
    ]:
        r = client.patch("/api/me/settings", json={key: value})
        assert r.status_code == 400 and fragment in r.json()["detail"], (key, value, r.text)
    assert client.get("/api/me/settings").json()["settings"] == after  # nothing changed
    # the admin sets the unit's default for everybody; the two numbers are personal and not an admin setting
    assert client.patch("/api/admin/settings", json={"user.units.weight": "kg"}).status_code == 200
    assert client.patch("/api/admin/settings", json={"body.weight_alarm": {"amount_kg": 1}}).status_code in (400, 403)


# --------------------------------------------------------------------------- the handbook's words


def handbook_sections() -> dict[str, str]:
    text = HANDBOOK_PAGE.read_text(encoding="utf-8")
    parts = re.split(r"^## (.+)$", text, flags=re.M)
    return {parts[i].strip(): re.sub(r"\s+", " ", parts[i + 1].replace("*", "")).lower() for i in range(1, len(parts), 2)}


def squash(text: str) -> str:
    return re.sub(r"\s+", " ", text).lower()


def test_every_quoted_phrase_is_on_the_handbook_page_under_its_group():
    from app.symptoms import HANDBOOK_GROUP_HEADINGS

    sections = handbook_sections()
    assert set(body.RED_FLAGS) == {"weight_alarm", "blood_pressure"}
    for key, entry in body.RED_FLAGS.items():
        for group, quote in entry["quotes"]:
            heading = HANDBOOK_GROUP_HEADINGS[group]
            assert heading in sections, heading
            assert squash(quote) in sections[heading], f"{key}: {quote!r} is not under {heading!r} on the handbook page"
            assert squash(quote) in squash(entry["text"]), f"{key}: the shown line does not quote {quote!r}"
            assert f"“{heading}”" in entry["text"]
    # the existing words the note names, and the two lines Part A added, are all there
    assert "weight gain above the alarm number your team gave you" in sections["Call your care team today"]
    assert "a blood pressure of 180/120 or higher that is still that high when you check again after resting 5 minutes" \
        in sections["Call your care team today"]
    assert "a blood pressure of 180/120 or higher with a sudden severe headache, trouble breathing" in sections["Call 911 now"]
    # with one of the signs, 911 at once: no second reading first (MedlinePlus), and do not wait (NHLBI)
    assert "call even if you have not measured again, and do not wait to see if it comes down on its own" in sections["Call 911 now"]
    text = body.RED_FLAGS["blood_pressure"]["text"]
    assert text.index("Call 911 now") < text.index("rest for 5 minutes")  # the 911 signs are read first


def test_the_page_cites_nhlbi_and_gives_no_medicine_advice_about_blood_pressure():
    text = HANDBOOK_PAGE.read_text(encoding="utf-8")
    assert "[NHLBI][NHLBI-BPS]" in text and "NHLBI-BPS," in text.split("---")[1]
    block = squash(handbook_sections()["Call 911 now"] + handbook_sections()["Call your care team today"])
    assert "changing your dose" not in block and "starting a medicine" not in block
    sources = (ROOT / "handbook" / "sources.yml").read_text(encoding="utf-8")
    assert "NHLBI-BPS:" in sources and "https://www.nhlbi.nih.gov/health/high-blood-pressure/symptoms" in sources
    card = (ROOT / "handbook" / "includes" / "help-card.md").read_text(encoding="utf-8")
    assert "180/120" in card and "5 minutes" in card


def test_the_flags_name_no_cause_treatment_or_dose():
    forbidden = re.compile(r"\b(because|causes|caused|due to|dose[sd]?|dosing|insulin|medicine|medication|treat\w*|take|"
                           r"\d+\s*(?:mg|g|units?|ml))\b", re.I)
    for key, entry in body.RED_FLAGS.items():
        assert not forbidden.search(entry["text"]), key
    assert body.RED_FLAGS["blood_pressure"]["prominent"] is True and body.RED_FLAGS["weight_alarm"]["prominent"] is False
    assert "without those signs, rest for 5 minutes and measure again" in body.RED_FLAGS["blood_pressure"]["text"].lower()


def test_a_flagged_reading_carries_the_pointer_and_an_ordinary_one_does_not(client):
    for s, d, flagged in ((179, 119, False), (180, 80, True), (140, 120, True)):
        made = add_reading(client, s, d)
        assert (made["flag"] is not None) is flagged
        if flagged:
            assert set(made["flag"]) == FLAG_KEYS and made["flag"]["text"] == body.RED_FLAGS["blood_pressure"]["text"]
    assert [x["flag"] is not None for x in readings(client)] == [False, True, True]


def test_the_other_features_do_not_read_the_weight_and_blood_pressure_tables():
    """Weights and readings are never sent to an AI provider or the assistant: the code that builds those requests does not read them."""
    reads = re.compile(r"(?:FROM|INTO|JOIN|UPDATE)\s+(?:weights|blood_pressures)\b|from\s+\.+\s*body\b|from\s+\.+body\s+import|"
                       r"\bimport\s+body\b|\bapp\.body\b|\bblood_pressures\b|\bweights\b\s*(?:WHERE|ORDER)", re.I)
    checked = 0
    for path in [*(ROOT / "app" / "ai").rglob("*.py"), *(ROOT / "app" / "mcp").rglob("*.py"), *(ROOT / "app" / "guidance").rglob("*.py"),
                 ROOT / "app" / "vision.py"]:
        checked += 1
        assert not reads.search(path.read_text(encoding="utf-8")), path
    assert checked > 10


# --------------------------------------------------------------------------- security: sign-in, CSRF, isolation, deletion

def test_every_body_route_is_listed_and_answers_401_when_signed_out(anon_client):
    routes = test_auth_coverage.BODY_ROUTES
    ops = test_auth_coverage.api_operations(anon_client.app)
    assert {op for op in ops if op[1].startswith("/api/body")} == routes
    for method, path in sorted(routes):
        r = anon_client.request(method.upper(), re.sub(r"\{[^}]+\}", "1", path), json={})
        assert r.status_code == 401 and r.json()["detail"] == "Sign in required", (method, path)
    assert anon_client.get("/api/body/summary", params={"date": day(0)}).status_code == 401


def test_writes_need_the_csrf_header(settings):
    with TestClient(create_app(settings), headers={}) as bare:
        login = {"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD}
        assert bare.post("/api/auth/login", json=login, headers={"X-Requested-With": "kidney-health"}).status_code == 200
        for path, payload in (("weights", w()), ("blood-pressure", bp())):
            r = bare.post(f"/api/body/{path}", json=payload)
            assert r.status_code == 403 and r.json() == {"detail": "Missing X-Requested-With header"}
            assert bare.put(f"/api/body/{path}/1", json=payload).status_code == 403
            assert bare.delete(f"/api/body/{path}/1").status_code == 403
            assert bare.post(f"/api/body/{path}/batch", json={"rows": []}).status_code == 403
            assert bare.get(f"/api/body/{path}", params={"start": day(1), "end": day(0)}).status_code == 200
            assert bare.post(f"/api/body/{path}", json=payload, headers={"X-Requested-With": "kidney-health"}).status_code == 201


def test_a_second_person_never_sees_or_changes_the_first_persons_rows(two_clients):
    a, b = two_clients
    mine, mine_bp = add_weight(a, 80.0, note="A's note"), add_reading(a, 150, 95, note="A's note")
    assert weights(b) == [] and readings(b) == []
    assert b.put(f"/api/body/weights/{mine['id']}", json=w(60)).status_code == 404
    assert b.delete(f"/api/body/weights/{mine['id']}").status_code == 404
    assert b.put(f"/api/body/blood-pressure/{mine_bp['id']}", json=bp(110, 70)).status_code == 404
    assert b.delete(f"/api/body/blood-pressure/{mine_bp['id']}").status_code == 404
    assert weights(a) == [mine] and readings(a) == [mine_bp]  # B's attempts changed nothing
    theirs, theirs_bp = add_weight(b, 55.0, note="B's note"), add_reading(b, 110, 70, note="B's note")
    assert [x["id"] for x in weights(a)] == [mine["id"]] and [x["id"] for x in weights(b)] == [theirs["id"]]
    assert a.delete(f"/api/body/weights/{theirs['id']}").status_code == 404 and a.delete(f"/api/body/blood-pressure/{theirs_bp['id']}").status_code == 404
    assert summary(b)["weight"]["latest"]["kg"] == 55.0 and summary(b)["bp"]["latest"]["systolic"] == 110
    # the same batch keys are independent between people
    rows = key_rows("weights", 1)
    assert a.post("/api/body/weights/batch", json={"rows": rows}).json()["added"] == 1
    assert b.post("/api/body/weights/batch", json={"rows": rows}).json()["added"] == 1
    # the export of each holds only their own
    for client, own, other in ((a, "A's note", "B's note"), (b, "B's note", "A's note")):
        doc = export_doc(client)
        assert own in [x["note"] for x in doc["weights"]] and other not in [x["note"] for x in doc["weights"]]
        assert [x["note"] for x in doc["blood_pressures"]] == [own]
        with zipfile.ZipFile(io.BytesIO(client.get("/api/me/export.zip").content)) as z:
            text = z.read("weights.csv").decode("utf-8") + z.read("blood_pressure.csv").decode("utf-8")
        assert own in text and other not in text
    # a file that carries ids of the other person's rows still writes only into the importer's account
    doc = export_doc(a)
    doc["weights"][0]["id"] = theirs["id"]
    r = post_import(b, doc, merge=True)
    assert r.status_code == 200, r.text
    assert [x["note"] for x in weights(a)].count("B's note") == 0 and [x["note"] for x in weights(a)].count("A's note") == 1
    assert sorted(x["note"] for x in weights(b) if x["note"]) == ["A's note", "B's note"]


def test_deleting_an_account_deletes_its_rows_and_only_its_own(two_clients):
    admin, sam = two_clients
    sam_id = sam.get("/api/me").json()["id"]
    add_weight(admin, 80)
    add_reading(admin, 150, 90)
    add_weight(sam, 60)
    add_weight(sam, 61, day(1))
    add_reading(sam, 110, 70)
    conn = sqlite3.connect(admin.app.state.settings.db_path)
    assert conn.execute("SELECT COUNT(*) FROM weights WHERE user_id = ?", (sam_id,)).fetchone()[0] == 2
    r = sam.request("DELETE", "/api/me", json={"password": USER_PASSWORD, "confirm": "DELETE"})
    assert r.status_code == 204
    for table in ("weights", "blood_pressures"):
        assert conn.execute(f"SELECT COUNT(*) FROM {table} WHERE user_id = ?", (sam_id,)).fetchone()[0] == 0
        assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 1
    conn.close()
    assert len(weights(admin)) == 1 and len(readings(admin)) == 1


def test_weights_and_readings_are_never_written_to_the_logs_or_the_activity_list(client, caplog):
    caplog.set_level("DEBUG")
    add_weight(client, 73.37, note="secret-note-xyzzy")
    add_reading(client, 187, 111, note="secret-note-xyzzy", pulse=77)
    client.post("/api/body/weights/batch", json={"rows": key_rows("weights", 1)})
    weights(client)
    readings(client)
    summary(client)
    client.post("/api/body/weights", json={**w(), "note": "secret-note-xyzzy" * 20})  # a refused request
    assert "xyzzy" not in caplog.text and "73.37" not in caplog.text
    events = client.get("/api/me/activity").json()["events"]
    assert not [e for e in events if "weight" in e["action"] or "blood" in e["action"]]
    assert "xyzzy" not in json.dumps(events)


# --------------------------------------------------------------------------- the export


def test_the_export_holds_the_log_in_both_forms(client):
    a = add_weight(client, 70.256, day(2), time="07:30", note="evening")
    b = add_weight(client, 71.0, day(1), "after_dialysis", note="=HYPERLINK(\"http://evil\")")
    c = add_reading(client, 190, 100, day(1), time="08:00", pulse=70, note="+cmd")
    client.post("/api/body/weights/batch", json={"rows": [{**w(72.0, day(3), "other"), "source": "apple_health", "source_key": "abc123"}]})
    r = client.get("/api/me/export.zip")
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        names = z.namelist()
        readme = z.read("README.txt").decode()
        doc = json.loads(z.read("export.json"))
        wrows = list(csv.reader(io.StringIO(z.read("weights.csv").decode("utf-8"))))
        brows = list(csv.reader(io.StringIO(z.read("blood_pressure.csv").decode("utf-8"))))
    assert "weights.csv" in names and "blood_pressure.csv" in names and "weights.csv" in readme and "blood_pressure.csv" in readme
    assert doc["version"] == 1 and doc["format"] == "kidney-health-export"  # optional lists: the version stays 1
    keys = list(doc)
    assert keys.index("symptoms") < keys.index("weights") < keys.index("blood_pressures") < keys.index("ai_audit")
    assert [x["kg"] for x in doc["weights"]] == [72.0, 70.26, 71.0]  # oldest day first
    assert doc["weights"][0] == {"id": 3, "date": day(3), "time": None, "kg": 72.0, "context": "other", "note": "", "source": "apple_health",
                                 "source_key": "abc123", "created_at": doc["weights"][0]["created_at"],
                                 "updated_at": doc["weights"][0]["updated_at"]}
    assert doc["weights"][1]["source"] == "manual" and doc["weights"][1]["source_key"] is None and doc["weights"][1]["id"] == a["id"]
    assert doc["blood_pressures"] == [{"id": c["id"], "date": day(1), "time": "08:00", "systolic": 190, "diastolic": 100, "pulse": 70,
                                       "context": "morning", "note": "+cmd", "source": "manual", "source_key": None,
                                       "created_at": c["created_at"], "updated_at": c["updated_at"]}]
    assert wrows[0] == list(body.WEIGHT_CSV_COLUMNS) and brows[0] == list(body.READING_CSV_COLUMNS)
    assert wrows[3][3] == "71.0" and wrows[3][5] == "'=HYPERLINK(\"http://evil\")"  # formula escaped
    assert brows[1][7] == "'+cmd" and wrows[3][0] == str(b["id"])


def test_an_account_with_no_log_exports_empty_lists(client):
    doc = export_doc(client)
    assert doc["weights"] == [] and doc["blood_pressures"] == []


# --------------------------------------------------------------------------- the import


@pytest.fixture
def fresh(tmp_path, foods_json):
    """A second, empty server (person B's)."""
    with signed_in_client(make_settings(tmp_path / "second", foods_json)) as c:
        yield c


def fill(client: TestClient) -> None:
    add_weight(client, 70.25, day(3), time="07:30", note="kept")
    add_weight(client, 70.5, day(3))
    add_weight(client, 70.5, day(3))  # the same twice stays twice
    add_reading(client, 128, 78, day(2), time="07:35", pulse=64)
    add_reading(client, 190, 100, day(2), "evening", note="rested")
    client.post("/api/body/weights/batch", json={"rows": key_rows("weights", 2, day(4))})
    client.post("/api/body/blood-pressure/batch", json={"rows": key_rows("bp", 2, day(4))})
    set_setting(client, "body.weight_alarm", {"amount_kg": 1.5, "over": "days", "days": 2})
    set_setting(client, "body.bp_goal", {"systolic": 130, "diastolic": 80})
    set_setting(client, "user.units.weight", "kg")


def strip(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{k: v for k, v in r.items() if k not in ("id", "created_at", "updated_at")} for r in rows]


def test_the_log_round_trips_into_another_server(client, fresh):
    fill(client)
    doc = export_doc(client)
    r = post_import(fresh, doc, replace_profile=True)
    assert r.status_code == 200, r.text
    answer = r.json()
    assert answer["counts"]["weights"] == 5 and answer["counts"]["blood_pressures"] == 4
    assert answer["file"]["records"]["weights"] == 5 and answer["file"]["records"]["blood_pressures"] == 4
    assert answer["already_there"]["weights"] == 0 and answer["skipped"]["total"] == 0
    assert strip(weights(fresh)) == strip(weights(client)) and strip(readings(fresh)) == strip(readings(client))
    assert [x["created_at"] for x in weights(fresh)] == [x["created_at"] for x in weights(client)]
    assert [x["source"] for x in weights(fresh)][:2] == ["apple_health", "apple_health"]
    mine, theirs = client.get("/api/me/settings").json()["settings"], fresh.get("/api/me/settings").json()["settings"]
    for key in ("body.weight_alarm", "body.bp_goal", "user.units.weight"):
        assert theirs[key]["value"] == mine[key]["value"] and theirs[key]["source"] == "user", key
    events = [e for e in fresh.get("/api/me/activity").json()["events"] if e["action"] == "data.imported"]
    assert events[0]["details"]["weights"] == 5 and events[0]["details"]["blood_pressures"] == 4
    assert "kept" in [x["note"] for x in export_doc(fresh)["weights"]]
    assert [x["source_key"] for x in export_doc(fresh)["weights"]][:2] == ["k0", "k1"]  # the keys came along


def test_a_dry_run_counts_and_writes_nothing(client, fresh):
    fill(client)
    r = post_import(fresh, export_doc(client), dry_run=True)
    assert r.status_code == 200 and r.json()["counts"]["weights"] == 5 and r.json()["imported"] is False
    assert weights(fresh) == [] and readings(fresh) == []


def test_an_account_with_a_log_needs_add_to_my_existing_data_and_then_adds_only_what_is_new(client, fresh):
    fill(client)
    doc = export_doc(client)
    assert post_import(fresh, doc).status_code == 200
    blocked = post_import(fresh, doc)
    assert blocked.status_code == 409
    assert blocked.json()["blocked"]["existing"]["weights"] == 5 and blocked.json()["blocked"]["existing"]["blood_pressures"] == 4
    assert len(weights(fresh)) == 5
    again = post_import(fresh, doc, merge=True)
    assert again.status_code == 200 and again.json()["counts"]["weights"] == 0 and again.json()["counts"]["blood_pressures"] == 0
    assert again.json()["already_there"]["weights"] == 5 and again.json()["already_there"]["blood_pressures"] == 4
    assert len(weights(fresh)) == 5 and len(readings(fresh)) == 4
    add_weight(client, 69.0, day(0))
    client.post("/api/body/weights/batch", json={"rows": key_rows("weights", 1, day(5), "z")})
    more = post_import(fresh, export_doc(client), merge=True)
    assert more.json()["counts"]["weights"] == 2 and more.json()["already_there"]["weights"] == 5
    # an account that has only weights counts as having data
    only = {"format": "kidney-health-export", "version": 1}
    assert post_import(fresh, only).status_code == 409


def test_a_manual_row_the_person_edited_after_an_import_is_not_added_again(client, fresh):
    add_weight(client, 70.5, day(3), time="07:30")
    doc = export_doc(client)
    assert post_import(fresh, doc).status_code == 200
    assert post_import(fresh, doc, merge=True).json()["already_there"]["weights"] == 1
    assert len(weights(fresh)) == 1


def test_an_older_file_without_the_lists_still_imports(client, fresh):
    fill(client)
    doc = export_doc(client)
    del doc["weights"], doc["blood_pressures"]
    r = post_import(fresh, doc)
    assert r.status_code == 200 and r.json()["counts"]["weights"] == 0 and weights(fresh) == []


def sample(client: TestClient) -> dict[str, Any]:
    add_weight(client, 70.5, day(2), time="07:30", note="n")
    add_reading(client, 128, 78, day(2), time="07:35", pulse=64)
    return export_doc(client)


@pytest.mark.parametrize("edit, where", [
    (lambda d: d["weights"][0].__setitem__("kg", 19), "weights[0]"),
    (lambda d: d["weights"][0].__setitem__("kg", 401), "weights[0]"),
    (lambda d: d["weights"][0].__setitem__("kg", "70"), "weights[0].kg"),  # strict: a number, not text
    (lambda d: d["weights"][0].__setitem__("context", "evening"), "weights[0].context"),
    (lambda d: d["weights"][0].__setitem__("source", "withings"), "weights[0].source"),
    (lambda d: d["weights"][0].__setitem__("date", "2999-01-01"), "weights[0]"),
    (lambda d: d["weights"][0].__setitem__("date", "yesterday"), "weights[0]"),
    (lambda d: d["weights"][0].__setitem__("time", "25:00"), "weights[0]"),
    (lambda d: d["weights"][0].__setitem__("note", "x" * (MAX_BODY_NOTE + 1)), "weights[0].note"),
    (lambda d: d["weights"][0].__setitem__("note", "bad\x00"), "weights[0]"),
    (lambda d: d["weights"][0].__setitem__("source_key", "k" * (MAX_SOURCE_KEY + 1)), "weights[0].source_key"),
    (lambda d: d["weights"][0].__setitem__("created_at", "yesterday"), "weights[0].created_at"),
    (lambda d: d["weights"][0].__setitem__("id", 0), "weights[0].id"),
    (lambda d: d["weights"][0].__setitem__("user_id", 2), "weights[0].user_id"),
    (lambda d: d["weights"][0].pop("kg"), "weights[0].kg"),
    (lambda d: d["blood_pressures"][0].__setitem__("systolic", 40), "blood_pressures[0]"),
    (lambda d: d["blood_pressures"][0].__setitem__("systolic", 78), "blood_pressures[0]"),  # not above the bottom number
    (lambda d: d["blood_pressures"][0].__setitem__("pulse", 300), "blood_pressures[0]"),
    (lambda d: d["blood_pressures"][0].__setitem__("diastolic", 78.5), "blood_pressures[0].diastolic"),
    (lambda d: d["blood_pressures"][0].__setitem__("context", "other_time"), "blood_pressures[0].context"),
    (lambda d: d["blood_pressures"][0].__setitem__("flag", None), "blood_pressures[0].flag"),
    (lambda d: d["blood_pressures"][0].pop("systolic"), "blood_pressures[0].systolic"),
])
def test_a_bad_row_in_a_file_refuses_the_whole_file_and_names_it(client, fresh, edit, where):
    doc = sample(client)
    edit(doc)
    r = post_import(fresh, doc)
    assert r.status_code == 400, r.text
    assert where in r.json()["detail"], r.json()
    assert weights(fresh) == [] and readings(fresh) == []


def test_the_lists_in_a_file_are_bounded_and_a_crowded_day_is_skipped_and_reported(client, fresh):
    from app.data_import import MAX_BLOOD_PRESSURES, MAX_WEIGHTS

    doc = sample(client)
    row = doc["weights"][0]
    r = post_import(fresh, {**doc, "weights": [row] * (MAX_WEIGHTS + 1)}, dry_run=True)
    assert r.status_code == 400 and "weights" in r.json()["detail"]
    r = post_import(fresh, {**doc, "blood_pressures": [doc["blood_pressures"][0]] * (MAX_BLOOD_PRESSURES + 1)}, dry_run=True)
    assert r.status_code == 400 and "blood_pressures" in r.json()["detail"]
    crowded = [{**row, "id": i + 1, "kg": 70 + i * 0.1, "note": f"w{i}"} for i in range(MAX_WEIGHTS_PER_DAY + 2)]
    r = post_import(fresh, {**doc, "weights": crowded, "blood_pressures": []})
    assert r.status_code == 200, r.text
    answer = r.json()
    assert answer["counts"]["weights"] == MAX_WEIGHTS_PER_DAY and answer["skipped"]["by_kind"] == {"weights": 2}
    assert answer["skipped"]["shown"][0]["kind"] == "weights" and "20 weights" in answer["skipped"]["shown"][0]["reason"]
    crowded_bp = [{**doc["blood_pressures"][0], "id": i + 1, "note": f"b{i}"} for i in range(MAX_READINGS_PER_DAY + 1)]
    r = post_import(fresh, {**doc, "weights": [], "blood_pressures": crowded_bp}, merge=True)
    assert r.json()["counts"]["blood_pressures"] == MAX_READINGS_PER_DAY and r.json()["skipped"]["by_kind"] == {"blood_pressures": 1}


def test_ids_in_a_file_never_decide_ids_here_and_text_is_cleaned_like_a_typed_row(client, fresh):
    doc = sample(client)
    doc["weights"][0].update(id=900, date=f" {day(2)} ", time=" 07:30 ", kg=70.504, note=" n ")
    assert post_import(fresh, doc).status_code == 200
    got = weights(fresh)[0]
    assert (got["id"], got["date"], got["time"], got["kg"], got["note"]) == (1, day(2), "07:30", 70.5, "n")
    blank = sample(client)
    blank["weights"][0]["time"] = ""
    assert post_import(fresh, blank, merge=True).status_code == 200
    assert any(x["time"] is None for x in weights(fresh))


def test_the_body_settings_are_carried_over_only_with_replace_profile(client, fresh):
    fill(client)
    doc = export_doc(client)
    dry = post_import(fresh, doc, dry_run=True).json()
    assert dry["not_selected"] == ["your profile and targets", "your meal-guidance, display, weight and blood pressure settings"]
    assert post_import(fresh, doc).status_code == 200
    assert fresh.get("/api/me/settings").json()["settings"]["body.weight_alarm"]["value"]["amount_kg"] is None
    bad = export_doc(client)
    bad["settings"]["body.weight_alarm"] = {"amount_kg": 50}
    r = post_import(fresh, bad, merge=True)
    assert r.status_code == 400 and "body.weight_alarm: not a value this server accepts" in r.json()["detail"]
    assert post_import(fresh, doc, merge=True, replace_profile=True).status_code == 200
    assert fresh.get("/api/me/settings").json()["settings"]["body.bp_goal"]["value"] == {"systolic": 130, "diastolic": 80}
