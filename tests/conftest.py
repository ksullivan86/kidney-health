"""Shared fixtures: a tiny builtin food database and TestClients with a temporary DATA_DIR.

Use :class:`TestClient` from this module (``from conftest import TestClient``), not FastAPI's: it
talks to ``http://localhost`` (the Host allowlist refuses Starlette's default ``testserver``) and
sends ``X-Requested-With: kidney-health`` like the app's own ``fetch()`` wrapper, so unsafe
``/api`` requests pass the CSRF check. Security tests that need a bare client pass ``headers={}``
explicitly or use :data:`BareTestClient`.

Accounts (v0.3): the ``settings`` fixture creates the first admin from ``ADMIN_USERNAME`` /
``ADMIN_PASSWORD`` (as an operator would with ``ADMIN_PASSWORD_FILE``), and ``client`` is that admin,
signed in through ``POST /api/auth/login``. ``anon_client`` is the same kind of app with nobody
signed in. :func:`add_user` creates a second account the way people get one (an admin's invite,
then ``POST /api/auth/register``) and returns a client signed in as that person.
"""
from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Mapping

import httpx2
import pytest
from starlette.testclient import TestClient as BareTestClient

from app.config import Settings
from app.main import create_app

CSRF_HEADERS = {"X-Requested-With": "kidney-health"}
BASE_URL = "http://localhost"
HTTPS_URL = "https://localhost"

ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "plum-orbit-candle-73"
USER_PASSWORD = "quiet-harbour-lantern-58"


class TestClient(BareTestClient):
    """Starlette's TestClient with the app's own request conventions (Host, X-Requested-With)."""

    __test__ = False

    def __init__(self, app: Any, base_url: str = BASE_URL, headers: Mapping[str, str] | None = None, **kwargs: Any) -> None:
        merged = dict(CSRF_HEADERS)
        if headers is not None:
            merged = dict(headers) if not headers else {**merged, **headers}
        super().__init__(app, base_url=base_url, headers=merged, **kwargs)


DAY = "2026-10-05"

# Nine foods chosen to exercise every warning path. Values are per serving.
FIXTURE_FOODS: dict[str, Any] = {
    "version": "test-1",
    "source": "pytest fixture",
    "foods": [
        {
            "fdc_id": 173944, "name": "Banana, raw", "category": "Fruits",
            "serving_desc": "1 medium (118 g)", "serving_g": 118,
            "nutrients": {"calories_kcal": 105, "protein_g": 1.29, "fat_g": 0.39, "sat_fat_g": 0.13,
                          "carbs_g": 26.95, "fiber_g": 3.1, "sugar_g": 14.43, "sodium_mg": 1,
                          "potassium_mg": 422, "phosphorus_mg": 26, "calcium_mg": 6, "fluid_ml": 0},
            "flags": [], "kidney_notes": "High potassium; try apples, berries or grapes instead.",
        },
        {
            "fdc_id": 171688, "name": "Apple, raw, with skin", "category": "Fruits",
            "serving_desc": "1 medium (182 g)", "serving_g": 182,
            "nutrients": {"calories_kcal": 94.6, "protein_g": 0.5, "fat_g": 0.3, "sat_fat_g": 0.1,
                          "carbs_g": 25.1, "fiber_g": 4.4, "sugar_g": 18.9, "sodium_mg": 2,
                          "potassium_mg": 195, "phosphorus_mg": 20, "calcium_mg": 11, "fluid_ml": 0},
            "flags": ["low_potassium_fruit"], "kidney_notes": None,
        },
        {
            "fdc_id": 1001, "name": "Cheese, processed, American slice", "category": "Dairy & Alternatives",
            "serving_desc": "1 slice (21 g)", "serving_g": 21,
            "nutrients": {"calories_kcal": 70, "protein_g": 4, "fat_g": 5.5, "sat_fat_g": 3.3,
                          "carbs_g": 1.5, "fiber_g": 0, "sugar_g": 1, "sodium_mg": 300,
                          "potassium_mg": 50, "phosphorus_mg": 90, "calcium_mg": 150, "fluid_ml": 0},
            "flags": ["phosphate_additive", "processed"], "kidney_notes": "Contains sodium phosphate.",
        },
        {
            "fdc_id": 1002, "name": "Star fruit (carambola)", "category": "Fruits",
            "serving_desc": "1 medium (91 g)", "serving_g": 91,
            "nutrients": {"calories_kcal": 28, "protein_g": 0.9, "fat_g": 0.3, "sat_fat_g": 0,
                          "carbs_g": 6.1, "fiber_g": 2.5, "sugar_g": 3.6, "sodium_mg": 2,
                          "potassium_mg": 121, "phosphorus_mg": 11, "calcium_mg": 3, "fluid_ml": 0},
            "flags": ["avoid_ckd"], "kidney_notes": "AVOID: star fruit is toxic in kidney failure.",
        },
        {
            "fdc_id": 1003, "name": "Glucose tablets", "category": "Diabetes supplies",
            "serving_desc": "4 tablets (16 g)", "serving_g": 16,
            "nutrients": {"calories_kcal": 60, "protein_g": 0, "fat_g": 0, "sat_fat_g": 0,
                          "carbs_g": 16, "fiber_g": 0, "sugar_g": 16, "sodium_mg": 0,
                          "potassium_mg": 0, "phosphorus_mg": 0, "calcium_mg": 0, "fluid_ml": 0},
            "flags": ["hypo_treatment", "high_gi"], "kidney_notes": None,
        },
        {
            "fdc_id": 1004, "name": "Water, tap", "category": "Beverages",
            "serving_desc": "1 cup (240 g)", "serving_g": 240,
            "nutrients": {"calories_kcal": 0, "protein_g": 0, "fat_g": 0, "sat_fat_g": 0,
                          "carbs_g": 0, "fiber_g": 0, "sugar_g": 0, "sodium_mg": 7,
                          "potassium_mg": 0, "phosphorus_mg": 0, "calcium_mg": 7, "fluid_ml": 240},
            "flags": ["counts_as_fluid"], "kidney_notes": None,
        },
        {
            "fdc_id": 1005, "name": "Chicken breast, roasted", "category": "Meat, Poultry & Eggs",
            "serving_desc": "3 oz (85 g)", "serving_g": 85,
            "nutrients": {"calories_kcal": 140, "protein_g": 26.4, "fat_g": 3, "sat_fat_g": 0.9,
                          "carbs_g": 0, "fiber_g": 0, "sugar_g": 0, "sodium_mg": 63,
                          "potassium_mg": 218, "phosphorus_mg": 196, "calcium_mg": 13, "fluid_ml": 0},
            "flags": [], "kidney_notes": None,
        },
        {
            "fdc_id": 1006, "name": "Egg white, raw", "category": "Meat, Poultry & Eggs",
            "serving_desc": "1 large (33 g)", "serving_g": 33,
            "nutrients": {"calories_kcal": 17, "protein_g": 3.6, "fat_g": 0.1, "sat_fat_g": 0,
                          "carbs_g": 0.2, "fiber_g": 0, "sugar_g": 0.2, "sodium_mg": 55,
                          "potassium_mg": 54, "phosphorus_mg": 5, "calcium_mg": 2, "fluid_ml": 0},
            "flags": [], "kidney_notes": None,
        },
        {
            "fdc_id": 1007, "name": "Juice, apple", "category": "Beverages",
            "serving_desc": "1/2 cup (124 g)", "serving_g": 124,
            "nutrients": {"calories_kcal": 57, "protein_g": 0.1, "fat_g": 0.2, "sat_fat_g": 0,
                          "carbs_g": 14, "fiber_g": 0.1, "sugar_g": 12, "sodium_mg": 5,
                          "potassium_mg": 125, "phosphorus_mg": 9, "calcium_mg": 10, "fluid_ml": 109},
            "flags": ["counts_as_fluid", "hypo_treatment"], "kidney_notes": None,
        },
    ],
}
FIXTURE_FOOD_COUNT = len(FIXTURE_FOODS["foods"])


@pytest.fixture
def foods_json(tmp_path: Path) -> Path:
    path = tmp_path / "foods.json"
    path.write_text(json.dumps(FIXTURE_FOODS), encoding="utf-8")
    return path


def make_settings(tmp_path: Path, foods_json: Path, **kwargs: Any) -> Settings:
    """Settings with a temporary DATA_DIR and the first admin created from env-style credentials."""
    values: dict[str, Any] = {
        "data_dir": tmp_path / "data",
        "foods_json": foods_json,
        "admin_username": ADMIN_USERNAME,
        "admin_password": ADMIN_PASSWORD,
    }
    values.update(kwargs)
    return Settings(**values)


@pytest.fixture
def settings(tmp_path: Path, foods_json: Path) -> Settings:
    return make_settings(tmp_path, foods_json)


def sign_in(client: BareTestClient, username: str = ADMIN_USERNAME, password: str = ADMIN_PASSWORD) -> dict[str, Any]:
    response = client.post("/api/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return response.json()


@contextmanager
def signed_in_client(settings: Settings, base_url: str = BASE_URL, **kwargs: Any) -> Iterator[TestClient]:
    """A started app (lifespan) with the admin signed in."""
    with TestClient(create_app(settings), base_url=base_url, **kwargs) as c:
        sign_in(c)
        yield c


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    with signed_in_client(settings) as c:
        yield c


@pytest.fixture
def anon_client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(settings)) as c:
        yield c


def invite_token(admin: BareTestClient, role: str = "user") -> str:
    response = admin.post("/api/admin/invites", json={"role": role})
    assert response.status_code == 201, response.text
    return response.json()["url"].split("/#/invite/", 1)[1]


def add_user(admin: BareTestClient, username: str = "sam", password: str = USER_PASSWORD, role: str = "user",
             base_url: str | None = None) -> TestClient:
    """Invite + register a new account on ``admin``'s app; returns a client signed in as that person.

    The new client shares the running app (no second lifespan). A second account needs HTTPS (or
    ``allow_insecure_http=True``), so use an ``https://localhost`` admin client for two-user tests.
    """
    token = invite_token(admin, role)
    other = TestClient(admin.app, base_url=base_url or str(admin.base_url).rstrip("/"))
    response = other.post("/api/auth/register", json={"token": token, "username": username, "password": password})
    assert response.status_code == 201, response.text
    return other


@pytest.fixture
def https_client(settings: Settings) -> Iterator[TestClient]:
    with signed_in_client(settings, base_url=HTTPS_URL) as c:
        yield c


@pytest.fixture
def two_clients(https_client: TestClient) -> tuple[TestClient, TestClient]:
    """(admin "admin", user "sam") on one app over HTTPS."""
    return https_client, add_user(https_client)


def insert_users(conn: Any, users: list[tuple[int, str]], role: str = "user") -> None:
    """Rows in the real schema-v3 ``users`` table for low-level tests (user 1 is updated in place)."""
    now = "2026-10-05T00:00:00.000000Z"
    for user_id, name in users:
        conn.execute(
            """INSERT INTO users (id, username, username_norm, role, status, created_at, updated_at)
               VALUES (?, ?, ?, ?, 'active', ?, ?)
               ON CONFLICT(id) DO UPDATE SET username = excluded.username, username_norm = excluded.username_norm,
                 status = 'active'""",
            (user_id, name, name.lower(), "admin" if user_id == 1 else role, now, now),
        )


def find_food(client: TestClient, query: str) -> dict[str, Any]:
    """First search hit for ``query`` (asserts there is one)."""
    response = client.get("/api/foods", params={"q": query})
    assert response.status_code == 200, response.text
    foods = response.json()["foods"]
    assert foods, f"no food matches {query!r}"
    return foods[0]


def log_food(client: TestClient, query: str, meal: str = "breakfast", servings: float = 1, date: str = DAY, **extra: Any) -> dict[str, Any]:
    food = find_food(client, query)
    body = {"date": date, "meal": meal, "food_id": food["id"], "servings": servings, **extra}
    response = client.post("/api/log", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def send_json(client: TestClient, method: str, path: str, body: Any) -> httpx2.Response:
    """Send ``body`` as raw JSON text. Unlike ``client.request(json=...)`` (which refuses NaN and
    Infinity), this uses the stdlib encoder's permissive default so tests can post the JSON
    literals ``Infinity`` / ``NaN`` that real clients can send."""
    return client.request(method, path, content=json.dumps(body), headers={"content-type": "application/json"})


class FakeClock:
    """Replaces :func:`app.auth.clock.now` (sessions, tokens, throttles, rate limits)."""

    def __init__(self) -> None:
        from datetime import datetime, timezone

        self.moment = datetime.now(timezone.utc)

    def now(self):  # noqa: ANN201 - datetime
        return self.moment

    def advance(self, **delta: float) -> None:
        from datetime import timedelta

        self.moment += timedelta(**delta)


@pytest.fixture
def fake_clock(monkeypatch: pytest.MonkeyPatch) -> FakeClock:
    fake = FakeClock()
    monkeypatch.setattr("app.auth.clock.now", fake.now)
    return fake


def setup_code_from_logs(caplog: pytest.LogCaptureFixture) -> str:
    import re

    for record in reversed(caplog.records):
        match = re.search(r"enter the code ([A-Z2-7]{4}-[A-Z2-7]{4}-[A-Z2-7]{4}-[A-Z2-7]{4})", record.getMessage())
        if match:
            return match.group(1)
    raise AssertionError("no FIRST-RUN SETUP line in the logs")
