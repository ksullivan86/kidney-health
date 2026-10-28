"""``GET /api/meta`` (design note 14 change 4; ``app/meta.py``): the server's version and API version, what the signed-in person can use now,
the nutrient registry and the meal names.

Covered: a session is needed, the keys of the answer, the nutrients and meals equal the registry in the server's order, every capability
follows the switch or status function it is read from (assistant, push, the barcode providers and the person's consent, the AI features
against ``GET /api/ai/status``, chat, voice, the handbook), one person's choices never show in another's answer, nothing secret-looking is
in the answer, and the demo's twin (``js/mock/meta.js``) against ``tests/data/meta_vectors.json``. No network."""
from __future__ import annotations

import importlib.util
import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Iterator

import pytest

from conftest import HTTPS_URL, TestClient, add_user, make_settings, sign_in
from test_ai_chat import become_ready
from test_ai_routes import ai_settings, enable, ready
from test_ai_voice import voice_settings
from test_api_tokens import switch
from app.api_version import API_VERSION
from app.main import APP_VERSION, create_app
from app.meta import Capabilities
from app.nutrients import MEALS, NUTRIENT_KEYS, NUTRIENTS

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "tests" / "data"
LEARN = Path(__file__).resolve().parent / "fixtures" / "learn"
CAPABILITIES = set(Capabilities.model_fields)
USDA_KEY = "usda-test-key-0123456789abcdefghijklmnop"


def meta(client: TestClient) -> dict[str, Any]:
    r = client.get("/api/meta")
    assert r.status_code == 200, r.text
    return r.json()


def caps(client: TestClient) -> dict[str, bool]:
    return meta(client)["capabilities"]


# --------------------------------------------------------------------------- #
# Who may ask, and what the answer holds
# --------------------------------------------------------------------------- #


def test_it_needs_a_session(anon_client):
    r = anon_client.get("/api/meta")
    assert r.status_code == 401 and r.json() == {"detail": "Sign in required"}


def test_it_is_a_read_only_route(client):
    for method in ("post", "put", "patch", "delete"):
        assert client.request(method.upper(), "/api/meta", json={}).status_code == 405


def test_the_answer_has_the_documented_keys(client):
    answer = meta(client)
    assert list(answer) == ["app_version", "api_version", "capabilities", "nutrients", "meals"]
    assert answer["app_version"] == APP_VERSION == client.app.version
    assert answer["api_version"] == API_VERSION and isinstance(answer["api_version"], int) and not isinstance(answer["api_version"], bool)
    assert set(answer["capabilities"]) == CAPABILITIES
    assert all(isinstance(v, bool) for v in answer["capabilities"].values())
    assert all(set(n) == {"key", "label", "unit", "role"} for n in answer["nutrients"])


def test_nutrients_and_meals_are_the_registry_in_the_servers_order(client):
    answer = meta(client)
    assert [n["key"] for n in answer["nutrients"]] == list(NUTRIENT_KEYS)
    assert answer["nutrients"] == [{"key": n.key, "label": n.label, "unit": n.unit, "role": n.role} for n in NUTRIENTS]
    assert answer["meals"] == list(MEALS) == ["breakfast", "lunch", "dinner", "snack"]
    assert {n["unit"] for n in answer["nutrients"]} == {"kcal", "g", "mg", "mL"}
    assert {n["role"] for n in answer["nutrients"]} == {"goal", "range", "info", "track", "limit"}


def test_a_fresh_server_offers_nothing_optional(client):
    assert caps(client) == dict.fromkeys(CAPABILITIES, False)


def test_every_answer_is_uncached(client):
    r = client.get("/api/meta")
    assert r.headers["cache-control"] == "no-store"


# --------------------------------------------------------------------------- #
# The instance switches
# --------------------------------------------------------------------------- #


def test_assistant_follows_its_switch(client):
    switch(client, True)
    assert caps(client)["assistant"] is True and caps(client)["push"] is False
    switch(client, False)
    assert caps(client)["assistant"] is False


def test_push_follows_its_switch(client):
    assert client.patch("/api/admin/settings", json={"push.enabled": True}).status_code == 200
    assert caps(client)["push"] is True and caps(client)["assistant"] is False
    assert client.patch("/api/admin/settings", json={"push.enabled": False}).status_code == 200
    assert caps(client)["push"] is False


def test_everybody_sees_the_instance_switches(two_clients):
    admin, sam = two_clients
    assert admin.patch("/api/admin/settings", json={"assistant.enabled": True, "push.enabled": True}).status_code == 200
    for who in (admin, sam):
        assert caps(who)["assistant"] is True and caps(who)["push"] is True


# --------------------------------------------------------------------------- #
# Barcode providers
# --------------------------------------------------------------------------- #


def test_open_food_facts_needs_the_admin_switch_and_the_persons_consent(two_clients):
    admin, sam = two_clients
    assert (caps(admin)["barcode_off"], caps(admin)["barcode"]) == (False, False)
    assert admin.patch("/api/admin/settings", json={"food.off_enabled": True}).status_code == 200
    assert caps(admin)["barcode_off"] is False and caps(sam)["barcode_off"] is False  # on, but nobody agreed yet
    assert sam.patch("/api/me/settings", json={"food.off_consent": True}).status_code == 200
    assert (caps(sam)["barcode_off"], caps(sam)["barcode"]) == (True, True)
    assert caps(admin)["barcode_off"] is False and caps(admin)["barcode"] is False  # sam's choice is sam's
    assert admin.patch("/api/admin/settings", json={"food.off_enabled": False}).status_code == 200
    assert caps(sam)["barcode_off"] is False and caps(sam)["barcode"] is False
    assert caps(sam)["barcode_usda"] is False


def test_usda_needs_a_key_the_person_can_use(tmp_path, foods_json):
    with TestClient(create_app(make_settings(tmp_path, foods_json, usda_api_key=USDA_KEY)), base_url=HTTPS_URL) as admin:
        sign_in(admin)
        sam = add_user(admin)
        assert caps(admin)["barcode_usda"] is True and caps(admin)["barcode"] is True and caps(admin)["barcode_off"] is False
        assert caps(sam)["barcode_usda"] is True  # a new person may use the shared key
        assert admin.patch("/api/admin/settings", json={"food.usda_branded_barcode": False}).status_code == 200
        assert caps(admin)["barcode_usda"] is False and caps(admin)["barcode"] is False
        assert admin.patch("/api/admin/settings", json={"food.usda_branded_barcode": True}).status_code == 200
        assert admin.patch("/api/admin/settings", json={"providers.usda.shared_enabled": False}).status_code == 200
        assert caps(sam)["barcode_usda"] is False


def test_usda_without_any_key_is_not_offered(client):
    assert client.get("/api/admin/settings").json()["settings"]["food.usda_branded_barcode"]["value"] is True  # on by default, no key
    assert caps(client)["barcode_usda"] is False


# --------------------------------------------------------------------------- #
# The AI, from the status route's own answer
# --------------------------------------------------------------------------- #

AI_KEYS = {"next_meal": "ai_next_meal", "parse_meal": "ai_parse_meal", "label": "ai_label", "plate": "ai_plate",
           "chat": "chat", "voice": "voice", "lab_report": "ai_lab_report", "recipes": "ai_recipes"}


def ai_matches_status(client: TestClient) -> dict[str, bool]:
    """The capabilities, after checking each AI one against ``GET /api/ai/status`` (404 while the AI is off)."""
    got = caps(client)
    status = client.get("/api/ai/status")
    if status.status_code == 404:
        assert not any(got[k] for k in ("ai", *AI_KEYS.values()))
        return got
    body = status.json()
    assert got["ai"] is body["available"]
    for feature, key in AI_KEYS.items():
        assert got[key] is body["features"][feature], (feature, got, body["features"])
    return got


@pytest.fixture
def ai_client(tmp_path, foods_json) -> Iterator[TestClient]:
    with TestClient(create_app(ai_settings(tmp_path, foods_json)), base_url=HTTPS_URL) as c:
        sign_in(c)
        yield c


def test_the_ai_is_off_until_the_admin_turns_it_on_and_the_person_opts_in(ai_client):
    assert ai_matches_status(ai_client)["ai"] is False  # configured, switched off: the status route is a 404
    enable(ai_client)
    got = ai_matches_status(ai_client)
    assert got["ai"] is False and got["ai_next_meal"] is False  # on, but this person has not opted in
    ready(ai_client)
    got = ai_matches_status(ai_client)
    assert got["ai"] is True and got["ai_next_meal"] is True and got["ai_parse_meal"] is True
    assert got["chat"] is False and got["voice"] is False  # Ask is its own switch
    assert ai_client.patch("/api/me/ai", json={"opt_in": False}).status_code == 200
    assert ai_matches_status(ai_client)["ai"] is False
    assert ai_client.patch("/api/me/ai", json={"opt_in": True}).status_code == 200
    assert ai_client.patch("/api/admin/settings", json={"ai.enabled": False}).status_code == 200
    assert ai_matches_status(ai_client)["ai"] is False


def test_the_ai_follows_each_features_route(ai_client):
    enable(ai_client)
    ready(ai_client)
    assert ai_matches_status(ai_client)["ai_next_meal"] is True
    assert ai_client.patch("/api/admin/settings", json={"ai.route.meal_ideas": "off"}).status_code == 200
    got = ai_matches_status(ai_client)
    assert got["ai_next_meal"] is False and got["ai_parse_meal"] is True


def test_chat_follows_its_switch(ai_client):
    enable(ai_client, **{"ai.chat_enabled": True})
    become_ready(ai_client)
    got = ai_matches_status(ai_client)
    assert got["chat"] is True and got["voice"] is False
    assert ai_client.patch("/api/admin/settings", json={"ai.chat_enabled": False}).status_code == 200
    assert ai_matches_status(ai_client)["chat"] is False


def test_voice_follows_its_switch_and_the_speech_server(tmp_path, foods_json):
    with TestClient(create_app(voice_settings(tmp_path, foods_json)), base_url=HTTPS_URL) as c:
        sign_in(c)
        enable(c, **{"ai.chat_enabled": True, "ai.voice_enabled": True})
        become_ready(c)
        got = ai_matches_status(c)
        assert got["chat"] is True and got["voice"] is True
        assert c.patch("/api/admin/settings", json={"ai.voice_enabled": False}).status_code == 200
        got = ai_matches_status(c)
        assert got["chat"] is True and got["voice"] is False


def test_the_ai_is_per_person(tmp_path, foods_json):
    with TestClient(create_app(ai_settings(tmp_path, foods_json)), base_url=HTTPS_URL) as admin:
        sign_in(admin)
        sam = add_user(admin)
        enable(admin)
        ready(admin)
        assert ai_matches_status(admin)["ai"] is True
        assert ai_matches_status(sam)["ai"] is False  # sam never opted in


# --------------------------------------------------------------------------- #
# The handbook
# --------------------------------------------------------------------------- #


def test_the_handbook_is_true_only_where_it_is_served(tmp_path, foods_json):
    site = tmp_path / "learn"
    shutil.copytree(LEARN, site)
    with TestClient(create_app(make_settings(tmp_path, foods_json, handbook_dir=site)), base_url=HTTPS_URL) as c:
        sign_in(c)
        assert caps(c)["handbook"] is True and c.get("/api/handbook").json()["available"] is True
    with TestClient(create_app(make_settings(tmp_path / "other", foods_json)), base_url=HTTPS_URL) as c:
        sign_in(c)
        assert caps(c)["handbook"] is False and c.get("/api/handbook").json()["available"] is False


def test_a_public_handbook_link_is_not_a_served_handbook(tmp_path, foods_json):
    settings = make_settings(tmp_path, foods_json, handbook_public_url="https://docs.example.com/handbook/")
    with TestClient(create_app(settings), base_url=HTTPS_URL) as c:
        sign_in(c)
        assert caps(c)["handbook"] is False
        assert "docs.example.com" not in json.dumps(meta(c))  # and the address is not repeated here


# --------------------------------------------------------------------------- #
# Nothing secret, nothing of anybody else
# --------------------------------------------------------------------------- #

SECRET_WORDS = ("key", "token", "secret", "password")
SECRET_SHAPES = re.compile(r"\bkh[ad]_|sk-|://|\b\d{1,3}(?:\.\d{1,3}){3}\b|[A-Za-z0-9+/_-]{32,}")


def test_nothing_secret_looking_is_in_the_answer(tmp_path, foods_json):
    """Every key, token, host and address a server can hold is configured here and in use; none appears in the answer."""
    from test_ai_voice import STT_KEY
    from test_ai_routes import OPENAI_KEY

    settings = voice_settings(tmp_path, foods_json, usda_api_key=USDA_KEY)
    with TestClient(create_app(settings), base_url=HTTPS_URL) as c:
        sign_in(c)
        enable(c, **{"ai.chat_enabled": True, "ai.voice_enabled": True})
        become_ready(c)
        assert c.patch("/api/admin/settings", json={"assistant.enabled": True, "push.enabled": True}).status_code == 200
        assistant = c.post("/api/me/tokens", json={"name": "meta"}).json()["token"]
        device = c.post("/api/me/tokens", json={"name": "meta", "family": "device"}).json()["token"]
        answer = meta(c)
    text = json.dumps(answer)
    for secret in (OPENAI_KEY, STT_KEY, USDA_KEY, assistant, device, "stt.example.com", "api.openai.com"):
        assert secret not in text
    # the word "key" is only ever the name of a nutrient's field; no other name or value holds one of the words
    stripped = {k: v for k, v in answer.items() if k != "nutrients"}
    assert not [w for w in SECRET_WORDS if w in json.dumps(stripped).lower()]
    for nutrient in answer["nutrients"]:
        assert not [w for w in SECRET_WORDS if w in " ".join([nutrient["label"], nutrient["unit"], nutrient["role"]]).lower()]
        assert set(nutrient) == {"key", "label", "unit", "role"}
    assert not SECRET_SHAPES.findall(json.dumps({**stripped, "nutrients": [[n["label"], n["unit"], n["role"]] for n in answer["nutrients"]]}))


def test_the_answer_holds_nothing_about_anybody(two_clients):
    """No name, id, count or setting of any person: two people on one server get the same answer until their own choices differ."""
    admin, sam = two_clients
    assert meta(admin) == meta(sam)
    text = json.dumps(meta(admin)).lower()
    assert "admin" not in text and "sam" not in text


# --------------------------------------------------------------------------- #
# The demo's twin and the vectors
# --------------------------------------------------------------------------- #


def generator():
    spec = importlib.util.spec_from_file_location("gen_meta_vectors", DATA / "gen_meta_vectors.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_vectors_are_current():
    committed = json.loads((DATA / "meta_vectors.json").read_text(encoding="utf-8"))
    assert committed == generator().build(), (
        "tests/data/meta_vectors.json is stale: app/meta.py, app/nutrient_core.py or app/api_version.py changed. Run "
        "`python3 tests/data/gen_meta_vectors.py`, then `node tests/js/run_vectors.mjs`, and update the demo's twin "
        "(app/static/js/mock/meta.js) until both agree."
    )


def test_the_vectors_cover_the_whole_answer():
    committed = json.loads((DATA / "meta_vectors.json").read_text(encoding="utf-8"))
    assert committed["capability_keys"] == list(Capabilities.model_fields) == list(committed["capabilities"])
    assert [n["key"] for n in committed["nutrients"]] == list(NUTRIENT_KEYS)
    assert committed["meals"] == list(MEALS) and committed["api_version"] == API_VERSION


def test_the_demos_copy_is_loaded_with_the_other_mocks():
    index = (ROOT / "app" / "static" / "index.html").read_text(encoding="utf-8")
    scripts = re.findall(r'<script src="([^"]+)"', index)
    assert scripts.index("js/mock/handbook.js") < scripts.index("js/mock/meta.js") < scripts.index("js/mock/seed.js")
    assert "'/js/mock/meta.js'," in (ROOT / "app" / "static" / "sw.js").read_text(encoding="utf-8")


def test_the_node_runner_replays_the_meta_vectors():
    assert shutil.which("node"), "Node.js 22 is needed for the JS parity vectors (CLAUDE.md, Parity): install it and run again"
    proc = subprocess.run(["node", str(ROOT / "tests" / "js" / "run_vectors.mjs")], capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "meta vectors:" in proc.stdout and "checks passed" in proc.stdout
