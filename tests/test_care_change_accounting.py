"""Concurrent helper writes keep every count and one daily note per kind."""
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from threading import Event, Lock

import pytest

from app import sharing
from conftest import DAY, find_food
from test_care_team import join
from test_care_team_full import set_switches
from test_sharing import audit_rows, switch


@pytest.mark.parametrize("statuses", [("planned", "planned"), ("eaten", "eaten"), ("planned", "eaten")])
@pytest.mark.parametrize("check", ["counts", "daily_notes"])
def test_simultaneous_helper_writes_are_all_counted_once(two_clients, monkeypatch, statuses, check):
    owner, helper = two_clients
    switch(owner)
    sid = join(owner, helper, role="caregiver")
    set_switches(owner, sid, may_plan=True)
    food = find_food(owner, "banana")["id"]
    today = sharing._today()
    monkeypatch.setattr(sharing, "_today", lambda: today)
    first_read, release = Event(), Event()
    claimed = False
    claim_lock = Lock()
    original = sharing._helper_changes

    def hold_first_snapshot(row):
        nonlocal claimed
        snapshot = original(row)
        with claim_lock:
            first = not claimed
            claimed = True
        if first:
            first_read.set()
            assert release.wait(10), "the first request was not released"
        return snapshot

    monkeypatch.setattr(sharing, "_helper_changes", hold_first_snapshot)

    def add(status):
        return helper.post(f"/api/shared/{sid}/log", json={
            "date": DAY, "meal": "lunch", "food_id": food, "servings": 1, "status": status,
        })

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(add, statuses[0])
        try:
            assert first_read.wait(5), "the first request did not reach its activity count"
            second = pool.submit(add, statuses[1])
            try:
                # Without a write lock the second request commits before the first overwrites its count.
                # With the lock it waits; releasing the first then lets both finish in order.
                second.result(timeout=1)
            except TimeoutError:
                pass
        finally:
            release.set()
        for response in (first.result(timeout=5), second.result(timeout=5)):
            assert response.status_code == 201, response.text

    monkeypatch.setattr(sharing, "_helper_changes", original)
    entries = owner.get("/api/log", params={"date": DAY}).json()["entries"]
    assert len(entries) == 2
    if check == "counts":
        counts = owner.get("/api/me/shares").json()["sharing"][0]["helper_changes"]
        assert counts["added"] == statuses.count("planned"), counts
        assert counts["logged"] == statuses.count("eaten"), counts
    else:
        assert len(audit_rows(owner, "care.plan_changed")) == int("planned" in statuses)
        assert len(audit_rows(owner, "care.food_logged")) == int("eaten" in statuses)
