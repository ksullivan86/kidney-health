"""All import paths must reuse the one shared USDA record without committing caller work."""
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from threading import Event, Lock

import pytest

from app import foods
from app.db import connect
from conftest import HTTPS_URL, TestClient, add_user, sign_in
from test_api import SR_BANANA
from test_api import usda_client  # noqa: F401 - shared fixture

FDC = 173944


@pytest.mark.parametrize("other_person", [False, True])
@pytest.mark.parametrize("second_writer", ["api", "transaction"])
def test_simultaneous_usda_imports_reuse_the_shared_food(request, monkeypatch, other_person, second_writer):
    boot = request.getfixturevalue("usda_client")
    client = TestClient(boot.app, base_url=HTTPS_URL)
    sign_in(client)
    actor = add_user(client, "member") if other_person else client
    actor_id = actor.get("/api/me").json()["id"]
    observer = add_user(client, "observer")
    peer = TestClient(client.app, base_url=str(client.base_url), cookies=actor.cookies)
    reached, release, claim = Event(), Event(), Lock()
    held = False
    insert = foods.insert_food

    def insert_after_snapshot(*args, **kwargs):
        nonlocal held
        if kwargs.get("source") == "usda":
            with claim:
                first = not held
                held = True
            if first:
                reached.set()
                assert release.wait(15), "the first import was not released"
        return insert(*args, **kwargs)

    monkeypatch.setattr(foods, "insert_food", insert_after_snapshot)

    def import_api(api):
        response = api.post("/api/foods/usda/import", json={"fdc_id": FDC})
        assert response.status_code == 200, response.text
        return response.json()["id"]

    def import_in_transaction():
        # The assistant and account writes own a wider transaction; this helper must keep it.
        with connect(client.app.state.settings.db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            food_id = foods.add_usda_food(conn, actor_id, FDC, foods.map_usda_record(SR_BANANA, FDC))
            conn.commit()
            return food_id

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(import_api, client)
            try:
                assert reached.wait(10), "the first import did not reach its insert"
                second = pool.submit(import_api, peer) if second_writer == "api" else pool.submit(import_in_transaction)
                try:
                    second.result(timeout=0.5)
                except TimeoutError:
                    pass
            finally:
                release.set()
            first_id, second_id = first.result(timeout=15), second.result(timeout=15)
        assert first_id == second_id
        with connect(client.app.state.settings.db_path) as conn:
            assert conn.execute("SELECT COUNT(*) FROM foods WHERE source = 'usda' AND fdc_id = ?", (FDC,)).fetchone()[0] == 1
        assert actor.get(f"/api/foods/{first_id}").status_code == 200
        assert observer.get(f"/api/foods/{first_id}").status_code == 404
    finally:
        peer.close()
        client.close()


@pytest.mark.parametrize("existing_transaction", [False, True])
def test_usda_storage_does_not_commit_the_callers_work(request, existing_transaction):
    client = request.getfixturevalue("usda_client")
    user_id = client.get("/api/me").json()["id"]
    mapped = foods.map_usda_record(SR_BANANA, FDC)
    with connect(client.app.state.settings.db_path) as conn:
        if existing_transaction:
            conn.execute("BEGIN IMMEDIATE")
            marker = foods.insert_food(conn, owner_user_id=user_id, **mapped.kwargs)
        food_id = foods.add_usda_food(conn, user_id, FDC, mapped)
        with connect(client.app.state.settings.db_path) as other:
            assert other.execute("SELECT 1 FROM foods WHERE id = ?", (food_id,)).fetchone() is None
        conn.rollback()
        assert conn.execute("SELECT 1 FROM foods WHERE id = ?", (food_id,)).fetchone() is None
        assert conn.execute("SELECT 1 FROM user_food_links WHERE user_id = ? AND food_id = ?", (user_id, food_id)).fetchone() is None
        if existing_transaction:
            assert conn.execute("SELECT 1 FROM foods WHERE id = ?", (marker,)).fetchone() is None
