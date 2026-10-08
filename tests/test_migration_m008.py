"""Schema step 8 (``app/migrations/m008_profile_chosen.py``): "Not chosen yet" for the kidney stage and the
diabetes type. Existing profiles count as chosen; new accounts start unchosen; a save that sends a stage
or a diabetes type records the choice; the stored defaults keep driving everything meanwhile."""
from __future__ import annotations

from app import db, migrations
from app.migrations import m008_profile_chosen as m008
from conftest import insert_users

NOW = "2026-10-05T08:00:00.000000Z"


def test_step_8_is_registered_in_order():
    steps = migrations.steps()
    assert [s.version for s in steps][:8] == [1, 2, 3, 4, 5, 6, 7, 8]
    assert steps[7].name == "m008_profile_chosen" and steps[7].atomic and steps[7].schema == ""


def test_upgrade_marks_existing_profiles_as_chosen_and_is_idempotent(tmp_path):
    path = tmp_path / "kidney.db"
    conn = db.connect(path)
    assert db.migrate(conn, migrations.steps()[:7]) == [1, 2, 3, 4, 5, 6, 7]
    insert_users(conn, [(1, "admin"), (2, "sam")])
    conn.execute("INSERT INTO user_profiles (user_id, ckd_stage, diabetes, updated_at, updated_by) VALUES (1, '4', 'none', ?, 1)", (NOW,))
    conn.commit()
    assert set(m008.COLUMNS).isdisjoint(db.table_columns(conn, "user_profiles"))
    assert db.migrate(conn, migrations.steps()[:8]) == [8]
    row = conn.execute("SELECT ckd_stage, diabetes, ckd_stage_set_at, diabetes_set_at FROM user_profiles WHERE user_id = 1").fetchone()
    assert tuple(row) == ("4", "none", NOW, NOW)
    # a profile created after the upgrade starts unchosen, and a re-run changes nothing
    conn.execute("INSERT INTO user_profiles (user_id, updated_at, updated_by) VALUES (2, ?, 2)", (NOW,))
    m008.migrate(conn)
    conn.commit()
    row = conn.execute("SELECT ckd_stage_set_at, diabetes_set_at FROM user_profiles WHERE user_id = 2").fetchone()
    assert tuple(row) == (None, None)
    conn.close()


def test_new_profile_is_not_chosen_until_the_person_sends_each_field(client):
    profile = client.get("/api/profile").json()
    assert profile["ckd_stage_chosen"] is False and profile["diabetes_chosen"] is False
    # the stored defaults still apply (targets, guidance, the Treating a low card)
    assert profile["ckd_stage"] == "3b" and profile["diabetes"] == "type1"
    # other fields, or an explicit null, do not count as a choice
    profile = client.put("/api/profile", json={"weight_kg": 70, "ckd_stage": None, "diabetes": None}).json()
    assert profile["ckd_stage_chosen"] is False and profile["diabetes_chosen"] is False
    profile = client.put("/api/profile", json={"ckd_stage": "3b"}).json()
    assert profile["ckd_stage_chosen"] is True and profile["diabetes_chosen"] is False
    profile = client.put("/api/profile", json={"diabetes": "none"}).json()
    assert profile["diabetes_chosen"] is True and profile["diabetes"] == "none"
    # a later save that leaves them out keeps the choice
    profile = client.put("/api/profile", json={"weight_kg": 71}).json()
    assert profile["ckd_stage_chosen"] is True and profile["diabetes_chosen"] is True
