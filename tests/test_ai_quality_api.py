"""``GET /api/admin/ai-quality`` and the start-up lines (``app/ai/quality.py``, ``app/ai/routes.py``; docs/ai.md "How well each AI
is doing").

Pinned down here, through the real routes and a fake provider: that each outcome the app really writes to the AI activity log is
counted under the right reason for every feature (meal ideas, describe a meal, photos, lab report photos, Ask), the warning for a
model that answers "nothing fits" to everything, that only counts leave, who may read the route, which features get a row
(never one that is off), that the counts follow the model in use now, and the warning lines at start-up. No network."""
from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any, Iterator

import httpx2
import pytest

from ai_support import FakeProvider, attach_routed, chat
from conftest import HTTPS_URL, TestClient, add_user, log_food, sign_in
from test_ai_chat import ask, step_answer, step_call
from test_ai_fallback import URL_ITEM
from test_ai_routes import DAY, _rerank_first_candidate
from test_ai_routing import PARSE, Rig, add_local, cloud_id, db, pin_roles, ready, route, routed_settings, turn_on
from test_lab_photo import GOOD as LAB_GOOD, answer as lab_answer, read as read_lab_photo
from test_vision_api import LABEL_ANSWER, LABEL_JPG, PLATE_ANSWER, PLATE_JPG, photo
from app.ai import quality as Q
from app.ai.prompts import PROMPT_VERSION
from app.main import create_app

NO_FIT = {"status": "ok", "refusal": "no_fit", "ideas": []}
REFUSED = {"status": "refused", "refusal": "none", "ideas": []}
NOT_CANDIDATES = {"status": "ok", "refusal": "none", "order": [{"ref": "zz9", "reason_codes": ["low_potassium"]}]}
SERVER_ERROR = {"status": 500, "headers": {"Content-Type": "application/json"}, "body": {"error": "boom"}}
GOOD_GATES = {"schema_valid_rate": True, "next_meal_with_idea_rate": True, "safety_refusal_rate": True, "p95_latency": True, "no_unsafe_text": True}
SECRET = "zebra-marker-4417"


def report(*, model: str = "gemma", vision_model: str | None = None, gates: dict[str, bool] | None = None, version: str = PROMPT_VERSION,
           date: str = "2026-10-27T08:30:00Z", preset: str = "ollama", base_url: str = "http://ollama.lan:11434/v1", **summary: Any) -> dict[str, Any]:
    return {"date": date, "prompt_version": version, "runs": 1,
            "provider": {"preset": preset, "kind": "self_hosted", "model": model, "vision_model": vision_model, "base_url": base_url},
            "summary": {"latency_ms": {"p95": 3000}, **summary}, "gates": dict(GOOD_GATES if gates is None else gates), "p95_limit_ms": 30_000,
            "calls": [{"case": SECRET, "status": "ok"}]}


@pytest.fixture
def reports(tmp_path) -> Path:
    path = tmp_path / "reports"
    path.mkdir()
    return path


@pytest.fixture
def qrig(tmp_path, foods_json, reports) -> Iterator[Rig]:
    """A new server: an Ollama on a private host holding the role local (every feature routes to it), the environment's OpenAI
    as the cloud AI, the reports folder set (empty), and the admin opted in and agreed to every purpose on the local AI."""
    with TestClient(create_app(routed_settings(tmp_path, foods_json, eval_reports_dir=str(reports))), base_url=HTTPS_URL) as c:
        sign_in(c)
        turn_on(c)
        rig = Rig(c, add_local(c, context_tokens=32768), cloud_id(c))  # room for Ask's seven calls in a row (the default is 8192)
        pin_roles(rig)
        ready(c, {rig.local: ("text", "photos", "chat", "labs")})
        yield rig


def quality(client: TestClient) -> dict[str, Any]:
    r = client.get("/api/admin/ai-quality")
    assert r.status_code == 200, r.text
    return r.json()


def row_of(data: dict[str, Any], feature: str) -> dict[str, Any]:
    return next(f for f in data["features"] if f["feature"] == feature)


def counts_of(client: TestClient, feature: str) -> dict[str, int]:
    return {k: v for k, v in row_of(quality(client), feature)["live"]["counts"].items() if v}


def local_only(*answers: Any, route_fn: Any = None) -> FakeProvider:
    return FakeProvider(list(answers), route=route_fn, address="10.0.0.5")


def meal(rig: Rig, *answers: Any, mode: str = "ideas", route_fn: Any = None) -> Any:
    with attach_routed(rig.client.app, local=local_only(*answers, route_fn=route_fn), cloud=FakeProvider()):
        return rig.client.post("/api/ai/next-meal", json={"meal": "dinner", "date": DAY, "mode": mode})


def describe_meal(rig: Rig, *answers: Any) -> Any:
    with attach_routed(rig.client.app, local=local_only(*answers), cloud=FakeProvider()):
        return rig.client.post("/api/ai/parse-meal", json={"text": "an apple"})


def audit_rows(client: TestClient) -> list[sqlite3.Row]:
    return db(client, "SELECT feature, status, model, provider_id, verdict_json FROM ai_audit ORDER BY id")


# --------------------------------------------------------------------------- #
# Who may read it
# --------------------------------------------------------------------------- #


def test_signed_out_is_401_a_member_is_403_and_an_admin_reads_it(qrig):
    admin = qrig.client
    anonymous = TestClient(admin.app, base_url=HTTPS_URL)
    r = anonymous.get("/api/admin/ai-quality")
    assert r.status_code == 401 and r.json()["detail"] == "Sign in required"
    sam = add_user(admin)
    r = sam.get("/api/admin/ai-quality")
    assert r.status_code == 403 and r.json()["detail"] == "Admins only"
    assert admin.get("/api/admin/ai-quality").status_code == 200
    for method in ("post", "put", "patch", "delete"):  # it reads; there is nothing to write
        assert admin.request(method.upper(), "/api/admin/ai-quality", json={}).status_code == 405


def test_it_is_read_without_a_recent_password_and_changes_nothing(qrig):
    before = db(qrig.client, "SELECT COUNT(*) AS n FROM ai_audit")[0]["n"], db(qrig.client, "SELECT COUNT(*) AS n FROM ai_usage")[0]["n"]
    quality(qrig.client)
    after = db(qrig.client, "SELECT COUNT(*) AS n FROM ai_audit")[0]["n"], db(qrig.client, "SELECT COUNT(*) AS n FROM ai_usage")[0]["n"]
    assert before == after


def test_it_is_in_the_openapi_document_as_an_admin_read():
    document = json.loads((Path(__file__).resolve().parents[1] / "docs" / "api" / "openapi.json").read_text(encoding="utf-8"))
    operation = document["paths"]["/api/admin/ai-quality"]["get"]
    assert operation["operationId"] == "admin_read_ai_quality" and operation["security"]


# --------------------------------------------------------------------------- #
# Which features get a row, and for which provider and model
# --------------------------------------------------------------------------- #


def test_the_answer_has_the_documented_shape(qrig):
    data = quality(qrig.client)
    assert set(data) == {"enabled", "window_days", "last_calls", "min_calls", "warn_percent", "prompt_version", "reports", "features"}
    assert (data["enabled"], data["window_days"], data["last_calls"], data["min_calls"], data["warn_percent"]) == (True, 14, 20, 8, 70)
    assert data["prompt_version"] == PROMPT_VERSION
    assert data["reports"] == {"configured": True, "readable": True, "files": 0, "reports": 0,
                               "ignored": {"malformed": 0, "too_big": 0, "outside_folder": 0, "unreadable": 0, "over_limit": 0}}
    assert [f["feature"] for f in data["features"]] == ["photos", "meal_ideas", "describe", "chat", "labs", "recipes"]
    one = row_of(data, "meal_ideas")
    assert set(one) == {"feature", "label", "route", "provider", "live", "evaluation"}
    assert one["label"] == "Meal ideas" and one["route"] == "local"
    assert one["provider"] == {"id": qrig.local, "label": "Ollama", "preset": "ollama", "host": "ollama.lan:11434", "model": "gemma"}
    assert set(one["live"]) == {"calls", "window_days", "counts", "unusable", "warn", "summary", "message"}
    assert set(one["evaluation"]) == {"state", "warn", "message", "date", "prompt_version", "file", "failed", "role", "upstream"}


def test_a_photo_feature_is_rated_on_its_vision_model(qrig):
    data = quality(qrig.client)
    assert row_of(data, "photos")["provider"]["model"] == "llava" and row_of(data, "labs")["provider"]["model"] == "llava"
    assert row_of(data, "describe")["provider"]["model"] == "gemma"


def test_a_feature_that_is_off_has_no_row(qrig):
    assert route(qrig.client, describe="off", chat="off").status_code == 200
    assert [f["feature"] for f in quality(qrig.client)["features"]] == ["photos", "meal_ideas", "labs", "recipes"]


def test_a_feature_with_no_ai_behind_it_has_no_row(qrig):
    assert route(qrig.client, meal_ideas="cloud", cloud_provider=0).status_code == 200  # cloud, and none chosen
    assert "meal_ideas" not in [f["feature"] for f in quality(qrig.client)["features"]]
    assert qrig.client.put(f"/api/admin/ai-providers/{qrig.local}", json={"preset": "ollama", "model": "gemma", "base_url": "http://ollama.lan:11434/v1",
                                                                            "structured": "auto", "enabled": False}).status_code == 200
    assert quality(qrig.client)["features"] == []  # the local AI is switched off: nothing runs on it


def test_cloud_any_and_local_then_cloud_name_the_provider_the_feature_uses(qrig):
    assert route(qrig.client, meal_ideas="cloud", describe="any", photos="local_then_cloud").status_code == 200
    data = quality(qrig.client)
    assert row_of(data, "meal_ideas")["provider"]["model"] == "gpt-6-luna" and row_of(data, "meal_ideas")["provider"]["host"] == "api.openai.com"
    assert row_of(data, "describe")["provider"]["id"] == qrig.cloud and row_of(data, "describe")["route"] == "any"  # the first usable shared AI
    assert row_of(data, "photos")["provider"]["id"] == qrig.local and row_of(data, "photos")["route"] == "local_then_cloud"  # the local AI is the one rated
    assert row_of(data, "photos")["provider"]["model"] == "llava"
    assert row_of(data, "chat")["route"] == "local"


def test_with_ai_switched_off_there_is_nothing_to_rate(qrig):
    assert qrig.client.patch("/api/admin/settings", json={"ai.enabled": False}).status_code == 200
    data = quality(qrig.client)
    assert data["enabled"] is False and data["features"] == []


def test_a_new_server_without_any_ai_has_no_rows(tmp_path, foods_json):
    with TestClient(create_app(routed_settings(tmp_path, foods_json, provider=None, api_key=None, model=None, vision_model=None)),
                    base_url=HTTPS_URL) as c:
        sign_in(c)
        turn_on(c)
        assert quality(c)["features"] == [] and quality(c)["reports"]["configured"] is False


# --------------------------------------------------------------------------- #
# What happened: every outcome the app writes, for every feature
# --------------------------------------------------------------------------- #


def test_the_owners_case_a_model_that_says_nothing_fits_is_flagged(qrig):
    """Eight "nothing fits", one answer that is not JSON and one usable answer: the warning of the brief, with the model named."""
    for _ in range(8):
        r = meal(qrig, chat(NO_FIT))
        assert r.status_code == 200 and r.json()["status"] == "no_fit"
    assert meal(qrig, chat("this is not json"), chat("still not json")).json()["status"] == "error"
    assert meal(qrig, mode="rerank", route_fn=_rerank_first_candidate).json()["status"] == "ok"
    live = row_of(quality(qrig.client), "meal_ideas")["live"]
    assert live["counts"] == {"usable": 1, "no_fit": 8, "unread": 0, "refused": 0, "dropped": 0, "invalid": 1, "error": 0}
    assert live["calls"] == 10 and live["unusable"] == 9 and live["warn"] is True
    assert live["message"] == ("Meal ideas: 9 of the last 10 calls to gemma had no usable idea (8 'nothing fits', 1 invalid). "
                               "The app showed the rule results instead. Check this model with scripts/ai_eval.py, "
                               "or route meal ideas to another AI.")


def test_seven_bad_calls_are_counted_and_not_judged(qrig):
    for _ in range(7):
        meal(qrig, chat(NO_FIT))
    live = row_of(quality(qrig.client), "meal_ideas")["live"]
    assert live["calls"] == 7 and live["counts"]["no_fit"] == 7 and live["warn"] is False and live["message"] is None
    meal(qrig, chat(NO_FIT))  # the eighth
    assert row_of(quality(qrig.client), "meal_ideas")["live"]["warn"] is True


def test_meal_idea_outcomes(qrig):
    assert meal(qrig, chat(NOT_CANDIDATES), mode="rerank").json()["status"] == "dropped_all"  # before the usable one: that is kept for ten minutes
    assert meal(qrig, mode="rerank", route_fn=_rerank_first_candidate).json()["status"] == "ok"
    assert meal(qrig, chat(NO_FIT)).json()["status"] == "no_fit"
    assert meal(qrig, chat(REFUSED)).json()["status"] == "refused"
    assert meal(qrig, chat("not json"), chat("not json")).json()["status"] == "error"
    assert meal(qrig, SERVER_ERROR, SERVER_ERROR).json()["status"] == "error"
    assert meal(qrig, httpx2.ReadTimeout("slow"), httpx2.ReadTimeout("slow")).json()["status"] == "error"
    assert counts_of(qrig.client, "meal_ideas") == {"usable": 1, "no_fit": 1, "refused": 1, "dropped": 1, "invalid": 1, "error": 2}
    assert {r["feature"] for r in audit_rows(qrig.client)} <= set(Q.AUDIT_FEATURES["meal_ideas"])
    assert sorted(r["status"] for r in audit_rows(qrig.client)) == sorted(
        ["ok", "no_fit", "refused", "dropped_all", "invalid", "error:http_5xx", "error:timeout"])


def test_a_reused_answer_is_not_a_second_call(qrig):
    body = {"meal": "dinner", "date": DAY, "mode": "rerank"}
    with attach_routed(qrig.client.app, local=local_only(route_fn=_rerank_first_candidate), cloud=FakeProvider()):
        assert qrig.client.post("/api/ai/next-meal", json=body).json()["cached"] is False
        assert qrig.client.post("/api/ai/next-meal", json=body).json()["cached"] is True
    assert [r["status"] for r in audit_rows(qrig.client)] == ["ok", "cached"]
    assert row_of(quality(qrig.client), "meal_ideas")["live"]["calls"] == 1


def test_describe_a_meal_outcomes(qrig):
    assert describe_meal(qrig, chat(PARSE)).json()["status"] == "ok"
    assert describe_meal(qrig, chat({"status": "refused", "items": []})).json()["status"] == "refused"
    assert describe_meal(qrig, chat(URL_ITEM)).json()["items"] == []  # every item thrown out by the text policy
    assert describe_meal(qrig, chat({"status": "ok", "items": []})).json()["items"] == []  # the model listed nothing
    assert describe_meal(qrig, chat("nope"), chat("nope")).json()["status"] == "error"
    assert describe_meal(qrig, SERVER_ERROR, SERVER_ERROR).json()["status"] == "error"
    assert counts_of(qrig.client, "describe") == {"usable": 1, "refused": 1, "dropped": 1, "unread": 1, "invalid": 1, "error": 1}
    rows = [json.loads(r["verdict_json"]) for r in audit_rows(qrig.client) if r["status"] == "ok"]
    assert [v.get("shown") for v in rows] == [1, 0, 0] and all(r["feature"] == "parse_meal" for r in audit_rows(qrig.client))


def label_answer(status: str) -> dict[str, Any]:
    return {**LABEL_ANSWER, "status": status}


def test_photo_outcomes(qrig):
    def send(path: str, data: bytes, *answers: Any) -> Any:
        with attach_routed(qrig.client.app, local=local_only(*answers), cloud=FakeProvider()):
            return photo(qrig.client, path, data)

    assert send("/api/vision/label", LABEL_JPG, chat(LABEL_ANSWER)).json()["status"] == "ok"
    assert send("/api/vision/label", LABEL_JPG, chat(label_answer("not_a_label"))).json()["status"] == "not_a_label"
    assert send("/api/vision/label", LABEL_JPG, chat(label_answer("unreadable"))).json()["status"] == "unreadable"
    assert send("/api/vision/plate", PLATE_JPG, chat(PLATE_ANSWER)).json()["status"] == "ok"
    assert send("/api/vision/plate", PLATE_JPG, chat({"status": "no_food", "items": []})).json()["status"] == "no_food"
    assert send("/api/vision/plate", PLATE_JPG, chat({"status": "unsure", "items": []})).json()["status"] == "unsure"
    assert send("/api/vision/plate", PLATE_JPG, chat({"status": "ok", "items": [
        {"name": "see http://evil.example/x", "search": "apple", "grams_estimate": 90, "confidence": "high"}]})).json()["items"] == []
    assert send("/api/vision/label", LABEL_JPG, chat("nope"), chat("nope")).status_code == 502
    assert send("/api/vision/plate", PLATE_JPG, SERVER_ERROR, SERVER_ERROR).status_code == 502
    assert counts_of(qrig.client, "photos") == {"usable": 2, "unread": 4, "dropped": 1, "invalid": 1, "error": 1}
    assert {r["feature"] for r in audit_rows(qrig.client)} == {"read_label", "plate"} and {r["model"] for r in audit_rows(qrig.client)} == {"llava"}


def test_lab_report_outcomes(qrig):
    def send(*answers: Any) -> Any:
        with attach_routed(qrig.client.app, local=local_only(*[chat(a) for a in answers]), cloud=FakeProvider()):
            return read_lab_photo(qrig.client)

    assert send(LAB_GOOD).json()["status"] == "ok"
    assert send(lab_answer(status="not_a_lab_report")).json()["status"] == "not_a_lab_report"
    assert send(lab_answer(status="unreadable")).json()["status"] == "unreadable"
    assert send(lab_answer()).json()["status"] == "no_results"
    assert counts_of(qrig.client, "labs") == {"usable": 1, "unread": 3}
    assert {r["feature"] for r in audit_rows(qrig.client)} == {"read_lab_report"}
    live = row_of(quality(qrig.client), "labs")["live"]
    assert live["calls"] == 4 and live["warn"] is False  # fewer than 8: counts, no verdict


def test_ask_outcomes(qrig):
    log_food(qrig.client, "banana", "breakfast")

    def send(*steps: Any, text: str = "what is left today") -> Any:
        with attach_routed(qrig.client.app, local=local_only(*steps), cloud=FakeProvider()):
            return ask(qrig.client, text).json()

    assert send(step_answer("Fine."))["kind"] == "answer"
    assert send(step_call("get_today", date=DAY), step_answer("Fine."))["kind"] == "answer"
    assert send(step_answer("Take 4 units of insulin before you eat that."))["kind"] == "withheld"
    assert send(step_call("get_today", date=DAY), *[step_call("get_today", date=DAY)] * 6)["kind"] == "unfinished"
    assert send(chat(None, refusal="I cannot help with that."))["kind"] == "error"
    assert send(chat("nope"), chat("nope"))["kind"] == "error"
    # an answer (1), a tool call and its answer (2), a withheld answer, seven calls in a row (six tool calls, then no answer: the step limit),
    # a refusal, and a reply that is not JSON even after the repair turn
    assert counts_of(qrig.client, "chat") == {"usable": 1 + 2 + 6, "dropped": 1, "invalid": 1 + 1, "refused": 1}
    assert {r["feature"] for r in audit_rows(qrig.client)} == {"chat"}
    assert "units" not in json.dumps(quality(qrig.client))  # no message and no answer text leaves, only counts


def test_the_counts_follow_the_model_in_use_now(qrig):
    for _ in range(3):
        meal(qrig, chat(NO_FIT))
    assert row_of(quality(qrig.client), "meal_ideas")["live"]["calls"] == 3
    edit = {"preset": "ollama", "model": "gemma-2", "vision_model": "llava", "base_url": "http://ollama.lan:11434/v1", "structured": "auto", "enabled": True}
    assert qrig.client.put(f"/api/admin/ai-providers/{qrig.local}", json=edit).status_code == 200
    now = row_of(quality(qrig.client), "meal_ideas")
    assert now["provider"]["model"] == "gemma-2" and now["live"]["calls"] == 0 and now["live"]["summary"] == "No calls in the last 14 days."
    edit["model"] = "gemma"
    assert qrig.client.put(f"/api/admin/ai-providers/{qrig.local}", json=edit).status_code == 200
    assert row_of(quality(qrig.client), "meal_ideas")["live"]["calls"] == 3  # the old rows count again for the old model


def seed(client: TestClient, *, count: int, status: str, feature: str = "next_meal:ideas", provider: int, model: str = "gemma", days_ago: float = 0.0,
         user: int = 1, verdict: str = "{}") -> None:
    from datetime import datetime, timedelta, timezone

    conn = sqlite3.connect(client.app.state.settings.db_path)
    try:
        for i in range(count):
            at = (datetime.now(timezone.utc) - timedelta(days=days_ago, seconds=count - i)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
            conn.execute("""INSERT INTO ai_audit (user_id, created_at, feature, provider_id, model, destination_host, prompt_version,
                                                  request_json, response_text, verdict_json, latency_ms, status)
                            VALUES (?, ?, ?, ?, ?, 'ollama.lan:11434', 'v', ?, ?, ?, 5, ?)""",
                         (user, at, feature, provider, model, json.dumps({"secret": SECRET}), SECRET, verdict, status))
        conn.commit()
    finally:
        conn.close()


def test_the_window_and_the_cap_hold_through_the_route(qrig):
    seed(qrig.client, count=30, status="no_fit", provider=qrig.local, days_ago=20)  # too old
    seed(qrig.client, count=5, status="no_fit", provider=qrig.local, days_ago=2)
    seed(qrig.client, count=30, status="ok", provider=qrig.local, days_ago=1)  # the newest twenty are all usable
    live = row_of(quality(qrig.client), "meal_ideas")["live"]
    assert live["calls"] == 20 and live["counts"]["usable"] == 20 and live["counts"]["no_fit"] == 0 and live["warn"] is False


def test_only_counts_leave_never_a_body_a_person_or_a_path(qrig, reports):
    (reports / "r.json").write_text(json.dumps(report()))
    seed(qrig.client, count=12, status="no_fit", provider=qrig.local, user=1, verdict=json.dumps({"note": SECRET}))
    r = qrig.client.get("/api/admin/ai-quality")
    text = r.text
    assert SECRET not in text and str(reports) not in text and "sk-env" not in text and "user" not in text.replace("usable", "").lower()
    row = row_of(r.json(), "meal_ideas")
    assert row["live"]["counts"]["no_fit"] == 12 and all(isinstance(v, int) for v in row["live"]["counts"].values())
    assert row["evaluation"]["file"] == "r.json"  # the name of a report, never where it is kept


# --------------------------------------------------------------------------- #
# What the evaluation said, through the route
# --------------------------------------------------------------------------- #


def test_the_evaluation_of_each_feature_from_the_reports_folder(qrig, reports):
    (reports / "2026-10-27-ollama-gemma.json").write_text(json.dumps(report(gates={**GOOD_GATES, "next_meal_with_idea_rate": False},
                                                                           next_meal_with_idea_rate=0.0)))
    (reports / "2026-10-26-ollama-llava.json").write_text(json.dumps(report(model="gemma", vision_model="llava", date="2026-10-26T00:00:00Z")))
    data = quality(qrig.client)
    assert data["reports"]["files"] == 2 and data["reports"]["reports"] == 2
    meal_ideas = row_of(data, "meal_ideas")["evaluation"]
    assert meal_ideas["state"] == "failed" and meal_ideas["warn"] is True and meal_ideas["failed"] == ["next_meal_with_idea_rate"]
    assert meal_ideas["message"] == ("Failed ai_eval on 2026-10-27: meal-idea cases with at least one idea that passed the checks: "
                                     "0 % (needs 80 % or more).")
    assert row_of(data, "describe")["evaluation"]["state"] == "passed"  # the meal-idea gate says nothing about describing a meal
    photos = row_of(data, "photos")["evaluation"]
    assert photos["state"] == "passed" and photos["file"] == "2026-10-26-ollama-llava.json"  # the report made with the vision model llava
    chat_status = row_of(data, "chat")["evaluation"]
    assert chat_status["state"] == "none" and chat_status["warn"] is True and "--chat" in chat_status["message"]  # no Ask questions were run
    labs = row_of(data, "labs")["evaluation"]
    assert labs["state"] == "not_covered" and labs["warn"] is False and "docs/maintainers.md" in labs["message"]


def test_a_report_for_the_model_in_use_that_passed(qrig, reports):
    (reports / "good.json").write_text(json.dumps(report()))
    evaluation = row_of(quality(qrig.client), "meal_ideas")["evaluation"]
    assert evaluation["state"] == "passed" and evaluation["warn"] is False and evaluation["failed"] == []
    assert evaluation["message"] == f"Passed ai_eval on 2026-10-27 (prompt version {PROMPT_VERSION})."


def test_a_report_for_an_older_prompt_version_is_no_report(qrig, reports):
    (reports / "old.json").write_text(json.dumps(report(version="2026-10-15.3")))
    evaluation = row_of(quality(qrig.client), "meal_ideas")["evaluation"]
    assert evaluation["state"] == "older" and evaluation["warn"] is True and "older prompt version (2026-10-15.3)" in evaluation["message"]


def test_the_folder_is_read_again_on_every_request(qrig, reports):
    assert row_of(quality(qrig.client), "meal_ideas")["evaluation"]["state"] == "none"
    (reports / "good.json").write_text(json.dumps(report()))
    assert row_of(quality(qrig.client), "meal_ideas")["evaluation"]["state"] == "passed"
    (reports / "good.json").unlink()
    assert row_of(quality(qrig.client), "meal_ideas")["evaluation"]["state"] == "none"


def test_without_the_variable_the_evaluation_says_there_is_no_reports_folder(tmp_path, foods_json):
    with TestClient(create_app(routed_settings(tmp_path, foods_json)), base_url=HTTPS_URL) as c:
        sign_in(c)
        turn_on(c)
        rig = Rig(c, add_local(c), cloud_id(c))
        pin_roles(rig)
        data = quality(c)
        assert data["reports"]["configured"] is False
        meal_ideas = row_of(data, "meal_ideas")["evaluation"]
        assert meal_ideas["state"] == "no_folder" and meal_ideas["warn"] is False and "No reports folder" in meal_ideas["message"]


def test_a_reports_folder_that_cannot_be_read_is_said_once_and_does_not_break_the_page(tmp_path, foods_json):
    settings = routed_settings(tmp_path, foods_json, eval_reports_dir=str(tmp_path / "not-there"))
    with TestClient(create_app(settings), base_url=HTTPS_URL) as c:
        sign_in(c)
        turn_on(c)
        pin_roles(Rig(c, add_local(c), cloud_id(c)))
        data = quality(c)
        assert data["reports"]["configured"] is True and data["reports"]["readable"] is False
        assert row_of(data, "meal_ideas")["evaluation"]["state"] == "unreadable_folder"


# --------------------------------------------------------------------------- #
# The start-up lines
# --------------------------------------------------------------------------- #


def start_again(tmp_path, foods_json, caplog, **ai: Any) -> list[str]:
    """Start a second app on the first one's data and return the "AI quality" lines it logged."""
    caplog.clear()
    with caplog.at_level(logging.WARNING):
        with TestClient(create_app(routed_settings(tmp_path, foods_json, **ai)), base_url=HTTPS_URL):
            pass
    return [r.getMessage() for r in caplog.records if r.getMessage().startswith("AI quality:")]


@pytest.fixture
def configured(tmp_path, foods_json) -> Rig:
    """A data directory where AI is on, the local AI is chosen and every feature routes to it (the first app is shut down)."""
    with TestClient(create_app(routed_settings(tmp_path, foods_json)), base_url=HTTPS_URL) as c:
        sign_in(c)
        turn_on(c)
        rig = Rig(c, add_local(c), cloud_id(c))
        pin_roles(rig)
        return rig


def test_start_up_warns_once_for_each_routed_feature_without_a_passing_report(tmp_path, foods_json, reports, caplog, configured):
    lines = start_again(tmp_path, foods_json, caplog, eval_reports_dir=str(reports))
    assert [line.split(" uses ")[0] for line in lines] == ["AI quality: Photos (labels and plates)", "AI quality: Meal ideas",
                                                           "AI quality: Describe a meal", "AI quality: Ask",
                                                           "AI quality: Recipes"]
    assert lines[1] == ("AI quality: Meal ideas uses gemma on Ollama (ollama.lan:11434). No ai_eval report for this model and prompt version. "
                        "Run scripts/ai_eval.py with this model and put the report in the reports folder.")
    assert not any("Lab report" in line for line in lines)  # not covered by ai_eval: nothing to warn about


def test_start_up_says_nothing_about_a_feature_that_passed_or_is_off(tmp_path, foods_json, reports, caplog, configured):
    (reports / "good.json").write_text(json.dumps(report(gates={**GOOD_GATES, "chat_pass_rate": True, "chat_no_unsafe_text": True})))
    assert route(configured.client, describe="off").status_code == 200
    lines = start_again(tmp_path, foods_json, caplog, eval_reports_dir=str(reports))
    assert [line.split(" uses ")[0] for line in lines] == ["AI quality: Photos (labels and plates)"]  # no vision model in that report
    assert "Describe a meal" not in " ".join(lines) and "Meal ideas" not in " ".join(lines) and "Ask" not in " ".join(lines)


def test_start_up_names_the_gates_a_report_failed(tmp_path, foods_json, reports, caplog, configured):
    (reports / "bad.json").write_text(json.dumps(report(gates={**GOOD_GATES, "next_meal_with_idea_rate": False}, next_meal_with_idea_rate=0.03)))
    lines = start_again(tmp_path, foods_json, caplog, eval_reports_dir=str(reports))
    meal_line = next(line for line in lines if "Meal ideas" in line)
    assert "Failed ai_eval on 2026-10-27: meal-idea cases with at least one idea that passed the checks: 3 % (needs 80 % or more)." in meal_line
    assert not any("Describe a meal" in line and "Failed" in line for line in lines)


def test_start_up_is_silent_without_the_variable(tmp_path, foods_json, caplog, configured):
    assert start_again(tmp_path, foods_json, caplog) == []


def test_start_up_is_silent_while_ai_is_off(tmp_path, foods_json, reports, caplog, configured):
    assert configured.client.patch("/api/admin/settings", json={"ai.enabled": False}).status_code == 200
    assert start_again(tmp_path, foods_json, caplog, eval_reports_dir=str(reports)) == []


def test_start_up_says_when_the_folder_cannot_be_read_and_still_starts(tmp_path, foods_json, caplog, configured):
    lines = start_again(tmp_path, foods_json, caplog, eval_reports_dir=str(tmp_path / "not-there"))
    assert lines == ["AI quality: AI_EVAL_REPORTS_DIR is set but the folder cannot be read, so no model can be checked against ai_eval."]


def test_start_up_never_fails_on_a_broken_folder(tmp_path, foods_json, reports, caplog, configured, monkeypatch):
    (reports / "junk.json").write_text("{not json")
    (reports / "big.json").write_text(" " * (1024 * 1024 + 1))
    lines = start_again(tmp_path, foods_json, caplog, eval_reports_dir=str(reports))
    assert len(lines) == 5

    def boom(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("disk on fire")

    monkeypatch.setattr(Q.E, "load", boom)
    lines = start_again(tmp_path, foods_json, caplog, eval_reports_dir=str(reports))
    assert lines == ["AI quality: the evaluation check at start-up failed"]  # logged on its own, and the app started
