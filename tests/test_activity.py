"""Activity and recovery and the active-day calorie extra (design note 28; app/activity.py).

Covered: the extra is off by default; once on, a day with a Whoop figure gets base + extra, where the extra is what Whoop counted
above the usual quiet-day level (the lower quartile of the finished days of the last 28, at least 14 of them), times the share,
at most the ceiling; it is never negative; only calories change; a day without a Whoop figure, or with fewer than 14 finished days
before it, keeps the base; "What fits now" uses the raised calorie target of that day; the setting is checked and its changes are
in the Activity list; the Care team area "activity" (allowed and refused; without it a shared day keeps the base target); isolation;
the export; the vectors are current.
"""
from __future__ import annotations

import json
import subprocess
import sys
import zipfile
from datetime import date, timedelta
from io import BytesIO
from pathlib import Path
from typing import Any

from app import activity as A
from app.db import connect, utcnow
from conftest import TestClient
from test_care_team import join, team  # noqa: F401  (the fixture)

ROOT = Path(__file__).resolve().parents[1]
TODAY = date.today()
TARGETS = {"calories_kcal": 2000, "protein_g": {"min": 50, "max": 60}, "potassium_mg": 2500, "phosphorus_mg": 900,
           "sodium_mg": 2000, "fluid_ml": 1500, "carbs_g": 200}
QUIET_DAYS = [2100, 2150, 2200, 2250, 2300, 2350, 2400, 2450, 2500, 2550, 2600, 2650, 2700, 2750]  # lower quartile 2250


def day(n: int) -> str:
    return (TODAY - timedelta(days=n)).isoformat()


def uid(client: TestClient) -> int:
    return int(client.get("/api/me").json()["id"])


def seed(client: TestClient, history: list[int], today_kcal: int | None, *, finished_today: bool = False) -> None:
    """Whoop days for the signed-in person: ``history`` on the days before today (newest first), and today's figure."""
    user_id = uid(client)
    now = utcnow()
    with connect(client.app.state.settings.db_path) as conn:
        rows = [(n + 1, kcal, 1) for n, kcal in enumerate(history)]
        if today_kcal is not None:
            rows.append((0, today_kcal, int(finished_today)))
        for n, kcal, finished in rows:
            conn.execute("INSERT INTO activity_days (user_id, date, source, source_key, kcal, strain, hrv_ms, finished, created_at, updated_at) "
                         "VALUES (?, ?, 'whoop', ?, ?, 10.0, 41.5, ?, ?, ?)", (user_id, day(n), f"whoop:cycle:{n}", kcal, finished, now, now))


def targets(client: TestClient, **extra: Any) -> None:
    assert client.put("/api/profile", json={"targets": {**TARGETS, **extra}}).status_code == 200


def turn_on(client: TestClient, **body: Any) -> dict[str, Any]:
    r = client.put("/api/activity/extra", json={"enabled": True, **body})
    assert r.status_code == 200, r.text
    return r.json()


def today_view(client: TestClient, date_: str | None = None) -> dict[str, Any]:
    r = client.get("/api/log", params={"date": date_ or TODAY.isoformat()})
    assert r.status_code == 200, r.text
    return r.json()


# --------------------------------------------------------------------------- #
# The extra
# --------------------------------------------------------------------------- #


def test_off_by_default_the_base_target_stays(client: TestClient) -> None:
    targets(client)
    seed(client, QUIET_DAYS, 3000)
    assert client.get("/api/activity").json()["extra"] == {"enabled": False, "share_pct": 100, "ceiling_kcal": None}
    v = today_view(client)
    assert v["calorie_extra"] is None and v["targets"]["calories_kcal"] == 2000


def test_on_an_active_day_counts_all_of_it_and_only_calories_rise(client: TestClient) -> None:
    targets(client)
    seed(client, QUIET_DAYS, 3000)
    turn_on(client)
    v = today_view(client)
    assert v["calorie_extra"] == {"base_kcal": 2000, "extra_kcal": 750, "burned_kcal": 3000, "quiet_kcal": 2250, "share_pct": 100,
                                  "ceiling_kcal": None, "history_days": 14, "source": "whoop"}
    assert v["targets"]["calories_kcal"] == 2750
    assert {k: v["targets"][k] for k in TARGETS if k != "calories_kcal"} == {k: x for k, x in TARGETS.items() if k != "calories_kcal"}
    assert v["status"]["calories_kcal"]["target"] == 2750


def test_share_and_ceiling(client: TestClient) -> None:
    targets(client)
    seed(client, QUIET_DAYS, 3000)
    turn_on(client, share_pct=50)
    assert today_view(client)["calorie_extra"]["extra_kcal"] == 380  # 375 half up to 10
    turn_on(client, share_pct=100, ceiling_kcal=400)
    v = today_view(client)
    assert v["calorie_extra"]["extra_kcal"] == 400 and v["targets"]["calories_kcal"] == 2400


def test_a_quiet_day_adds_nothing_and_the_target_never_drops(client: TestClient) -> None:
    targets(client)
    seed(client, QUIET_DAYS, 1200)  # early in the day: less than a quiet day so far
    turn_on(client)
    v = today_view(client)
    assert v["calorie_extra"]["extra_kcal"] == 0 and v["targets"]["calories_kcal"] == 2000


def test_without_whoop_figures_or_with_too_few_days_the_base_stays(client: TestClient) -> None:
    targets(client)
    seed(client, QUIET_DAYS[:13], 3000)
    turn_on(client)
    v = today_view(client)
    assert v["calorie_extra"]["quiet_kcal"] is None and v["calorie_extra"]["extra_kcal"] == 0 and v["calorie_extra"]["history_days"] == 13
    assert v["targets"]["calories_kcal"] == 2000
    later = today_view(client, (TODAY + timedelta(days=1)).isoformat())  # no Whoop figure for that day
    assert later["calorie_extra"] is None and later["targets"]["calories_kcal"] == 2000


def test_a_range_target_moves_both_ends_and_no_target_means_no_extra(client: TestClient) -> None:
    targets(client, calories_kcal={"min": 1800, "max": 2200})
    seed(client, QUIET_DAYS, 3000)
    turn_on(client)
    assert today_view(client)["targets"]["calories_kcal"] == {"min": 2550, "max": 2950}
    targets(client, calories_kcal=None)
    v = today_view(client)
    assert v["calorie_extra"] is None and v["targets"].get("calories_kcal") is None


def test_older_days_use_their_own_window(client: TestClient) -> None:
    targets(client)
    seed(client, [3000] + QUIET_DAYS, None)  # yesterday was active; 14 finished days before it
    turn_on(client)
    v = today_view(client, day(1))
    assert v["calorie_extra"]["extra_kcal"] == 750 and v["calorie_extra"]["burned_kcal"] == 3000


def test_what_fits_now_uses_the_raised_calorie_target(client: TestClient) -> None:
    targets(client)
    seed(client, QUIET_DAYS, 3000)
    turn_on(client)
    r = client.get("/api/guidance/next-meal", params={"meal": "lunch", "date": TODAY.isoformat()})
    assert r.status_code == 200, r.text
    values = r.json()["targets"]["values"]
    assert values["calories_kcal"] == 2750 and values["potassium_mg"] == 2500 and values["protein_g"] == {"min": 50, "max": 60}


def test_the_setting_is_checked_and_its_changes_are_listed(client: TestClient) -> None:
    for bad in ({"enabled": True, "share_pct": 5}, {"enabled": True, "share_pct": 101}, {"enabled": True, "ceiling_kcal": 10},
                {"enabled": True, "ceiling_kcal": 5000}, {"enabled": "yes please"}):
        assert client.put("/api/activity/extra", json=bad).status_code in (400, 422), bad
    turn_on(client, share_pct=50, ceiling_kcal=300)
    turn_on(client, share_pct=50, ceiling_kcal=300)  # the same again: no second row
    assert client.put("/api/activity/extra", json={"enabled": False}).json() == {"enabled": False, "share_pct": 100, "ceiling_kcal": None}
    events = [e for e in client.get("/api/me/activity").json()["events"] if e["action"].startswith("activity.extra")]
    assert [e["action"] for e in events] == ["activity.extra_off", "activity.extra_on"]
    assert events[1]["details"]["share_pct"] == 50 and events[1]["details"]["ceiling_kcal"] == 300


def test_the_activity_answer_and_its_range(client: TestClient) -> None:
    seed(client, QUIET_DAYS, 3000)
    r = client.get("/api/activity", params={"start": day(3), "end": day(0)})
    assert r.status_code == 200
    got = r.json()
    assert [d["date"] for d in got["days"]] == [day(3), day(2), day(1), day(0)] and got["days"][-1]["finished"] is False
    assert set(got["days"][0]) == set(A.DAY_COLUMNS)
    assert client.get("/api/activity", params={"start": day(0), "end": day(3)}).status_code == 400
    assert client.get("/api/activity", params={"start": day(400), "end": day(0)}).status_code == 400
    assert len(client.get("/api/activity").json()["days"]) == 15  # the last 30 days by default


def test_anonymous_is_401(anon_client: TestClient) -> None:
    assert anon_client.get("/api/activity").status_code == 401
    assert anon_client.put("/api/activity/extra", json={"enabled": True}).status_code == 401


def test_people_never_see_or_change_each_others(two_clients) -> None:
    admin, sam = two_clients
    targets(admin)
    targets(sam)
    seed(admin, QUIET_DAYS, 3000)
    turn_on(admin)
    assert sam.get("/api/activity").json()["days"] == [] and sam.get("/api/activity").json()["extra"]["enabled"] is False
    v = today_view(sam)
    assert v["calorie_extra"] is None and v["targets"]["calories_kcal"] == 2000
    sam.put("/api/activity/extra", json={"enabled": False})
    assert today_view(admin)["targets"]["calories_kcal"] == 2750


def test_the_export_holds_the_days_and_the_setting(client: TestClient) -> None:
    seed(client, QUIET_DAYS[:2], 3000)
    turn_on(client, share_pct=60)
    r = client.get("/api/me/export.zip")
    assert r.status_code == 200
    with zipfile.ZipFile(BytesIO(r.content)) as z:
        doc = json.loads(z.read("export.json"))
        csv_text = z.read("activity.csv").decode()
        assert z.read("workouts.csv").decode().startswith("date,start_time")
    assert [d["kcal"] for d in doc["activity_days"]] == [2150, 2100, 3000]
    assert doc["activity_extra"] == {"enabled": True, "share_pct": 60, "ceiling_kcal": None}
    assert csv_text.splitlines()[0] == ",".join(A.DAY_COLUMNS)
    # The file goes back in without error; Whoop's own rows are not imported (connecting again fetches them).
    r = client.post("/api/me/import", json=doc, params={"dry_run": "true", "merge": "true"})
    assert r.status_code == 200, r.text


# --------------------------------------------------------------------------- #
# The Care team area
# --------------------------------------------------------------------------- #


def test_a_care_team_view_needs_the_activity_area(team) -> None:  # noqa: F811
    ana, sam, kim = team
    targets(ana)
    seed(ana, QUIET_DAYS, 3000)
    turn_on(ana)
    sid = join(ana, sam, areas=["food"])
    assert sam.get(f"/api/shared/{sid}/activity").status_code == 404
    shared_day = sam.get(f"/api/shared/{sid}/log", params={"date": TODAY.isoformat()}).json()
    assert shared_day["calorie_extra"] is None and shared_day["targets"]["calories_kcal"] == 2000
    assert kim.get(f"/api/shared/{sid}/activity").status_code == 404
    sid2 = join(ana, sam, areas=["food", "activity"], role="viewer")
    r = sam.get(f"/api/shared/{sid2}/activity")
    assert r.status_code == 200 and len(r.json()["days"]) == 15 and r.json()["extra"] is None
    shared_day = sam.get(f"/api/shared/{sid2}/log", params={"date": TODAY.isoformat()}).json()
    assert shared_day["targets"]["calories_kcal"] == 2750 and shared_day["calorie_extra"]["extra_kcal"] == 750
    assert ana.get("/api/me/shares").json()["areas"] == ["food", "labs", "body", "symptoms", "activity"]


def test_a_care_helpers_plan_uses_the_base_target_without_the_activity_area(team) -> None:  # noqa: F811
    """Plan several days for the person: without the activity area the raised target would tell how active they were."""
    ana, sam, _ = team
    targets(ana)
    seed(ana, QUIET_DAYS, 3000)
    turn_on(ana)
    body = {"start": TODAY.isoformat(), "days": 1}
    sid = join(ana, sam, areas=["food"], role="care_helper")
    r = sam.post(f"/api/shared/{sid}/guidance/plan-days", json=body)
    assert r.status_code == 200, r.text
    assert r.json()["targets"]["values"]["calories_kcal"] == 2000
    assert ana.post("/api/guidance/plan-days", json=body).json()["targets"]["values"]["calories_kcal"] == 2750  # the person's own plan
    sid2 = join(ana, sam, areas=["food", "activity"], role="care_helper")
    assert sam.post(f"/api/shared/{sid2}/guidance/plan-days", json=body).json()["targets"]["values"]["calories_kcal"] == 2750


# --------------------------------------------------------------------------- #
# The twin
# --------------------------------------------------------------------------- #


def test_the_vectors_are_current() -> None:
    r = subprocess.run([sys.executable, str(ROOT / "tests" / "data" / "gen_activity_vectors.py"), "--check"], capture_output=True,
                       text=True, timeout=120)
    assert r.returncode == 0, r.stderr


def test_the_engine_numbers() -> None:
    assert A.quiet_level(QUIET_DAYS) == 2250 and A.quiet_level(QUIET_DAYS[:13]) is None
    assert A.extra_kcal(3000, 2250, 100, None) == 750 and A.extra_kcal(2000, 2250, 100, None) == 0
    assert A.extra_kcal(3000, 2250, 33, None) == 250 and A.extra_kcal(3000, 2250, 100, 50) == 50
    assert A.raised(2000, 0) == 2000 and A.raised({"min": 1, "max": None}, 10) == {"min": 11, "max": None}
