"""Overlapping measurement writes share limits and import duplicate checks."""
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from threading import Event, Lock

import pytest

from app import body, labs, symptoms
from app.models import MAX_READINGS_PER_DAY, MAX_SYMPTOMS_PER_DAY, MAX_WEIGHTS_PER_DAY
from conftest import TestClient
from test_body import bp, day, w
from test_lab_import import result
from test_symptoms import body as symptom


def race(client, monkeypatch, module, read_name, path, first, second, *, method="POST", second_path=None):
    """Hold the first checked snapshot while a second real request tries to save.

    Without a write lock the second commits against that same snapshot. With the lock it waits, then
    sees the first commit. Releasing on timeout allows both orders without a timing assertion.
    """
    reached, release, claim = Event(), Event(), Lock()
    held = False
    original = getattr(module, read_name)

    def read_and_hold(*args, **kwargs):
        nonlocal held
        snapshot = original(*args, **kwargs)
        with claim:
            first_read = not held
            held = True
        if first_read:
            reached.set()
            assert release.wait(15), "first snapshot was not released"
        return snapshot

    monkeypatch.setattr(module, read_name, read_and_hold)
    peers = [TestClient(client.app, base_url=str(client.base_url), cookies=client.cookies,
                        raise_server_exceptions=False) for _ in range(2)]
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            a = pool.submit(peers[0].request, method, path, json=first)
            try:
                assert reached.wait(10), "first request did not reach its check"
                b = pool.submit(peers[1].request, method, second_path or path, json=second)
                try:
                    b.result(timeout=0.5)
                except TimeoutError:
                    pass
            finally:
                release.set()
            return a.result(timeout=15), b.result(timeout=15)
    finally:
        for peer in peers:
            peer.close()


@pytest.mark.parametrize("endpoint", ["weights", "blood-pressure"])
@pytest.mark.parametrize("same_key", [False, True])
def test_overlapping_body_imports_skip_the_existing_measurement(client, monkeypatch, endpoint, same_key):
    record = w(time="07:00") if endpoint == "weights" else bp(time="07:00")
    first = {**record, "source": "apple_health", "source_key": "first-key"}
    second = {**first, "source_key": "first-key" if same_key else "another-export-key"}
    responses = race(client, monkeypatch, body, "_per_day", f"/api/body/{endpoint}/batch",
                     {"rows": [first]}, {"rows": [second]})
    assert [r.status_code for r in responses] == [200, 200], [r.text for r in responses]
    assert sum(r.json()["added"] for r in responses) == 1
    assert sum(r.json()["skipped"] for r in responses) == 1
    rows = client.get(f"/api/body/{endpoint}", params={"start": day(), "end": day()}).json()
    assert len(rows["weights" if endpoint == "weights" else "readings"]) == 1


def test_overlapping_lab_imports_skip_the_saved_result(client, monkeypatch):
    payload = {"results": [result("potassium", 4.6, "mmol/L", day())]}
    responses = race(client, monkeypatch, labs, "_rows", "/api/labs/import", payload, payload)
    assert [r.status_code for r in responses] == [200, 200], [r.text for r in responses]
    assert sum(r.json()["saved"] for r in responses) == 1
    assert sum(r.json()["duplicates"] for r in responses) == 1
    assert len(client.get("/api/labs").json()["labs"]) == 1


@pytest.mark.parametrize("kind, mode", [(kind, mode) for kind in ["weights", "blood-pressure", "symptoms"]
                                       for mode in ["create", "move", "batch"] if kind != "symptoms" or mode != "batch"])
def test_overlapping_measurements_do_not_overfill_a_date(client, monkeypatch, kind, mode):
    module = symptoms if kind == "symptoms" else body
    path = "/api/symptoms" if kind == "symptoms" else f"/api/body/{kind}"
    make = {"weights": w, "blood-pressure": bp, "symptoms": symptom}[kind]
    maximum = {"weights": MAX_WEIGHTS_PER_DAY, "blood-pressure": MAX_READINGS_PER_DAY,
               "symptoms": MAX_SYMPTOMS_PER_DAY}[kind]
    for _ in range(maximum - 1):
        response = client.post(path, json=make())
        assert response.status_code == 201, response.text
    payload = make()
    second_path = None
    method = "POST"
    if mode == "move":
        ids = []
        for _ in range(2):
            response = client.post(path, json=make(when=day(1)))
            assert response.status_code == 201, response.text
            ids.append(response.json()["id"])
        path, second_path = f"{path}/{ids[0]}", f"{path}/{ids[1]}"
        method = "PUT"
    second_payload = payload
    if mode == "batch":
        path += "/batch"
        payload = {"rows": [{**payload, "source": "import", "source_key": "new-first"}]}
        second_payload = {"rows": [{**make(), "source": "import", "source_key": "new-second"}]}
    responses = race(client, monkeypatch, module, "_per_day" if mode == "batch" else "count_on_day",
                     path, payload, second_payload, method=method, second_path=second_path)
    success = 200 if mode in ("move", "batch") else 201
    assert sorted(r.status_code for r in responses) == sorted([success, 400]), [r.text for r in responses]
    listing_path = "/api/symptoms" if kind == "symptoms" else f"/api/body/{kind}"
    rows = client.get(listing_path, params={"start": day(), "end": day()}).json()
    assert len(rows[{"weights": "weights", "blood-pressure": "readings", "symptoms": "symptoms"}[kind]]) == maximum
