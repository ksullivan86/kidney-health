"""A successful POST whose reply is lost can be retried without creating another health record."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

import pytest

from app import db, write_receipts
from conftest import DAY, find_food, log_food

KEY = "11111111-2222-4333-8444-555555555555"
KINDS = ("weight", "bp", "lab", "symptom", "copy", "apply")


def case(client, kind):
    if kind == "weight":
        return "/api/body/weights", {"date": DAY, "kg": 70.2, "context": "morning"}, "/api/body/weights", "weights", {"start": DAY, "end": DAY}
    if kind == "bp":
        return "/api/body/blood-pressure", {"date": DAY, "systolic": 128, "diastolic": 78, "context": "morning"}, "/api/body/blood-pressure", "readings", {"start": DAY, "end": DAY}
    if kind == "lab":
        return "/api/labs", {"analyte": "potassium", "value": 4.6, "unit": "mmol/L", "taken_on": DAY}, "/api/labs", "labs", {}
    if kind == "symptom":
        return "/api/symptoms", {"date": DAY, "symptom": "itching", "severity": 1}, "/api/symptoms", "symptoms", {"start": DAY, "end": DAY}
    if kind == "copy":
        log_food(client, "banana", date=DAY, meal="breakfast")
        target = (date.fromisoformat(DAY) + timedelta(days=1)).isoformat()
        return "/api/log/copy-day", {"from_date": DAY, "to_date": target, "meals": ["breakfast"]}, "/api/log", "entries", {"date": target}
    food = find_food(client, "banana")
    meal = client.post("/api/meals", json={"name": "Recipe", "servings_made": 4, "items": [{"food_id": food["id"], "servings": 4}]}).json()
    return f"/api/meals/{meal['id']}/apply", {"date": DAY, "meal": "dinner", "scale": 0.25}, "/api/log", "entries", {"date": DAY}


@pytest.mark.parametrize("kind", KINDS)
def test_same_key_replays_the_first_result_and_stores_one_record(client, kind):
    path, body, listing, key, params = case(client, kind)
    first = client.post(path, json=body, headers={"Idempotency-Key": KEY})
    again = client.post(path, json=body, headers={"Idempotency-Key": KEY})
    assert first.status_code == again.status_code == 201, (first.text, again.text)
    assert again.json() == first.json()
    assert len(client.get(listing, params=params).json()[key]) == 1


@pytest.mark.parametrize("kind", KINDS)
def test_a_new_key_is_another_intentional_save(client, kind):
    path, body, listing, key, params = case(client, kind)
    for token in (KEY, KEY + "-next"):
        assert client.post(path, json=body, headers={"Idempotency-Key": token}).status_code == 201
    assert len(client.get(listing, params=params).json()[key]) == 2


@pytest.mark.parametrize("kind", KINDS)
def test_no_key_retains_existing_one_write_per_call_behavior(client, kind):
    path, body, listing, key, params = case(client, kind)
    assert client.post(path, json=body).status_code == 201
    assert client.post(path, json=body).status_code == 201
    assert len(client.get(listing, params=params).json()[key]) == 2


@pytest.mark.parametrize("kind", KINDS)
def test_same_key_with_changed_data_is_a_conflict_and_does_not_write(client, kind):
    path, body, listing, key, params = case(client, kind)
    assert client.post(path, json=body, headers={"Idempotency-Key": KEY}).status_code == 201
    changed = {**body}
    if kind in ("weight", "bp", "lab", "symptom"):
        changed["note"] = "Changed data"
    elif kind == "copy":
        changed["include"] = "eaten"
    else:
        changed["meal"] = "lunch"
    response = client.post(path, json=changed, headers={"Idempotency-Key": KEY})
    assert response.status_code == 409, response.text
    assert response.json()["detail"] == write_receipts.CHANGED_ERROR
    assert len(client.get(listing, params=params).json()[key]) == 1


@pytest.mark.parametrize("token", ["", "short", "x" * 129, "has spaces in it"])
def test_invalid_key_is_refused_before_writing(client, token):
    path, body, listing, key, params = case(client, "weight")
    response = client.post(path, json=body, headers={"Idempotency-Key": token})
    assert response.status_code == 400
    assert client.get(listing, params=params).json()[key] == []


def test_receipt_keys_are_scoped_by_person(two_clients):
    first, second = two_clients
    path, body, listing, key, params = case(first, "weight")
    a = first.post(path, json=body, headers={"Idempotency-Key": KEY})
    b = second.post(path, json={**body, "kg": 80}, headers={"Idempotency-Key": KEY})
    assert a.status_code == b.status_code == 201
    assert a.json()["id"] != b.json()["id"]
    assert first.get(listing, params=params).json()[key][0]["kg"] == 70.2
    assert second.get(listing, params=params).json()[key][0]["kg"] == 80


def test_concurrent_retries_share_one_receipt(client):
    path, body, listing, key, params = case(client, "weight")
    def post(_):
        return client.post(path, json=body, headers={"Idempotency-Key": KEY})
    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(pool.map(post, range(8)))
    assert all(response.status_code == 201 for response in responses), [response.text for response in responses]
    assert len({response.json()["id"] for response in responses}) == 1
    assert len(client.get(listing, params=params).json()[key]) == 1


def test_a_failed_receipt_rolls_back_the_health_write_too(client, monkeypatch):
    path, body, listing, key, params = case(client, "weight")
    def fail():
        raise RuntimeError("receipt storage failed")
    with monkeypatch.context() as patch:
        patch.setattr(write_receipts, "utcnow", fail)
        with pytest.raises(RuntimeError, match="receipt storage failed"):
            client.post(path, json=body, headers={"Idempotency-Key": KEY})
    assert client.get(listing, params=params).json()[key] == []
    assert client.post(path, json=body, headers={"Idempotency-Key": KEY}).status_code == 201
    assert len(client.get(listing, params=params).json()[key]) == 1


def test_expired_response_becomes_a_tombstone_and_never_reexecutes(client, settings):
    path, body, listing, key, params = case(client, "weight")
    assert client.post(path, json=body, headers={"Idempotency-Key": KEY}).status_code == 201
    with db.connect(settings.db_path) as conn:
        conn.execute("UPDATE write_receipts SET created_at = '2000-01-01T00:00:00.000000Z'")
    expired = client.post(path, json=body, headers={"Idempotency-Key": KEY})
    assert expired.status_code == 409 and expired.json()["detail"] == write_receipts.EXPIRED_ERROR
    assert len(client.get(listing, params=params).json()[key]) == 1
    with db.connect(settings.db_path) as conn:
        row = conn.execute("SELECT response_json, body_hash FROM write_receipts WHERE request_key = ?", (KEY,)).fetchone()
        assert row[0] is None and len(row[1]) == 64


def test_replay_still_requires_sign_in(client, anon_client):
    path, body, listing, key, params = case(client, "weight")
    assert client.post(path, json=body, headers={"Idempotency-Key": KEY}).status_code == 201
    assert anon_client.post(path, json=body, headers={"Idempotency-Key": KEY}).status_code == 401
    assert len(client.get(listing, params=params).json()[key]) == 1


def test_apply_checks_recipe_ownership_before_any_replay(two_clients):
    owner, other = two_clients
    path, body, _, _, _ = case(owner, "apply")
    assert owner.post(path, json=body, headers={"Idempotency-Key": KEY}).status_code == 201
    assert other.post(path, json=body, headers={"Idempotency-Key": KEY}).status_code == 404


def test_same_key_can_be_used_for_different_operations(client):
    for kind in ("weight", "bp"):
        path, body, _, _, _ = case(client, kind)
        assert client.post(path, json=body, headers={"Idempotency-Key": KEY}).status_code == 201


def test_a_refused_domain_write_does_not_reserve_its_key(client):
    target = (date.fromisoformat(DAY) + timedelta(days=1)).isoformat()
    payload = {"from_date": DAY, "to_date": target}
    assert client.post("/api/log/copy-day", json=payload, headers={"Idempotency-Key": KEY}).status_code == 400
    log_food(client, "banana", date=DAY, meal="breakfast")
    response = client.post("/api/log/copy-day", json=payload, headers={"Idempotency-Key": KEY})
    assert response.status_code == 201 and response.json()["created"] == 1


def test_replay_of_the_twentieth_weight_does_not_hit_the_new_weight_limit(client):
    path, body, listing, key, params = case(client, "weight")
    first = client.post(path, json=body, headers={"Idempotency-Key": KEY})
    for _ in range(19):
        assert client.post(path, json=body).status_code == 201
    again = client.post(path, json=body, headers={"Idempotency-Key": KEY})
    assert again.status_code == 201 and again.json() == first.json()
    assert len(client.get(listing, params=params).json()[key]) == 20


def test_deleting_a_record_does_not_make_its_old_request_create_it_again(client):
    path, body, listing, key, params = case(client, "weight")
    first = client.post(path, json=body, headers={"Idempotency-Key": KEY})
    assert client.delete(f"{path}/{first.json()['id']}").status_code == 204
    again = client.post(path, json=body, headers={"Idempotency-Key": KEY})
    assert again.status_code == 201 and again.json() == first.json()
    assert client.get(listing, params=params).json()[key] == []
