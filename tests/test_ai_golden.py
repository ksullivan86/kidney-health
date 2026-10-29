"""The offline golden set (note 04 R11.1): every case in ``tests/ai_golden/*.json`` runs through the real
routes (``/api/ai/next-meal``, ``/api/ai/parse-meal``, ``/api/vision/*``) of a signed-in app with the
builtin food list, against a **stub provider** that replays the case's ``model_outputs``. Nothing
reaches the network.

Case format (README in ``tests/ai_golden/``)::

    {"id", "category", "feature": "next_meal" | "parse_meal" | "label" | "plate" | "lab_report" | "chat" | "recipes",
     "fixture": {"profile": {...}, "targets": {...} | "<preset>", "entries": [[meal, food name, servings, status?, purpose?]],
                 "history": [[days before, meal, food name, servings]], "custom_foods": [{...}], "other_custom_foods": [{...}],
                 "food_preferences": [[food name, "like" | "less" | "not_for_me" | "neutral"]],
                 "settings": {"ai": {...}, "guidance": {...}}, "meal", "mode", "text", "image", "swap_entry": index,
                 "message": the person's text (feature chat),
                 "dish", "makes", "target", "recipe_steps": the admin switch, "recipe": {"name", "servings_made", "note", "steps",
                 "source_url", "items": [[food name, servings]]} (feature recipes; ``mode`` "change" reworks it)},
     "model_outputs": [<content string> | {"content", "finish_reason", "refusal", "reasoning_content", "status"}],
     "expect": {"http", "status", "calls", "shown_food_names", "not_shown_food_names", "not_first_food_names",
                "idea_reason_codes_include", "idea_reason_codes_exclude", "dropped_reasons_include",
                "portions_lowered_include", "portions_lowered", "shown_quarters_at_most",
                "claims_corrected", "rule_fallback", "repaired", "response_excludes", "payload_includes",
                "payload_excludes", "cards", "draft", "items", "rows", "dropped",
                "kind", "pending": {"tool", "preference", "target"}, "nothing_saved",
                "recipes", "title", "steps_shown", "steps_dropped_include"}}

``feature: "chat"`` runs ``POST /api/ai/chat`` (Ask) with the person's ``message``; ``kind`` is the answer's kind, ``pending``
the card the person is asked to confirm, ``nothing_saved`` that no preference, log entry, saved meal or setting changed.

Placeholders in model outputs are resolved from the request the app actually sent:
``"{{id:<food name>}}"`` → that candidate's id, ``"{{ref:<food name>}}"`` → its ref (``f3``, ``s1``),
``"{{other_custom_id:<name>}}"`` → the id of another person's custom food (never a candidate),
``"{{id:#<food name>}}"`` → the id of a food listed in ``fixture.ids_needed`` that is deliberately not a
candidate (a low treatment, star fruit, banana on a high-potassium day).

``GOLDEN_DEBUG=1 python -m pytest tests/test_ai_golden.py -k <id> -s`` prints each response's status,
dropped reasons and the shown ideas' numbers.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterator

import httpx2
import pytest

from ai_support import LEGACY_ROUTING, PUBLIC_IP, FakeProvider, attach, chat
from conftest import HTTPS_URL, TestClient, add_user, make_settings, sign_in
from app.config import AiEnv
from app.main import create_app

ROOT = Path(__file__).resolve().parent
CASES = sorted((ROOT / "ai_golden").glob("*.json"))
# The cases that pin a safety rule (``pytest -m safety``, CONTRIBUTING.md "Tests"): every ``safety-*`` (no doses or medicine
# advice, blocked words, false claims corrected) and ``prefilter-*`` (a low or a red flag is answered by the app, no model call)
# case, and the cases that say a low treatment is never sent to the model, a lab report row is never advice or a dose, and the
# fields that are never sent stay out of the request.
SAFETY_PREFIXES = ("safety-", "prefilter-")
SAFETY_CASES = {
    "mode-swap-low-treatment-never-sent",
    "rules-hypo-treatment-item",
    "lab-report-advice-or-a-dose-is-never-a-row",
    "privacy-payload-never-sent-fields",
    "recipes-low-treatment-never-a-food",
    "recipes-salt-never-a-food",
    "recipes-step-insulin",
    "recipes-step-nutrient-claim",
    "recipes-privacy-rework-never-sends-the-recipes-text",
}


def _is_safety(path: Path) -> bool:
    return path.stem.startswith(SAFETY_PREFIXES) or path.stem in SAFETY_CASES


FOODS_JSON = ROOT.parent / "data" / "foods.json"
IMAGES = ROOT / "fixtures" / "ai" / "images"
DAY = "2026-10-05"
LOCAL_HOST = "ollama.lan:11434"
LOCAL_ADDRESS = "10.0.0.5"  # what the stub's local AI "resolves" to: the local network scope refuses a public address
TARGET_PRESETS: dict[str, dict[str, Any]] = {
    "stage4": {"potassium_mg": 3000, "phosphorus_mg": 1000, "sodium_mg": 2000, "protein_g": {"min": 56, "max": 56},
               "carbs_g": 236, "carbs_per_meal_g": 60, "fluid_ml": None, "calories_kcal": 2100, "calcium_mg": 1000},
    "hd": {"potassium_mg": 2500, "phosphorus_mg": 1000, "sodium_mg": 2000, "protein_g": {"min": 70, "max": 84},
           "carbs_g": 236, "carbs_per_meal_g": 60, "fluid_ml": 1500, "calories_kcal": 2100, "calcium_mg": 1000},
    "tight": {"potassium_mg": 2000, "phosphorus_mg": 800, "sodium_mg": 1500, "protein_g": {"min": 50, "max": 56},
              "carbs_g": 200, "carbs_per_meal_g": 45, "fluid_ml": 1000, "calories_kcal": 1800, "calcium_mg": 1000},
}
PLACEHOLDER = re.compile(r'"\{\{(id|ref|other_custom_id):([^}]+)\}\}"')


def test_the_golden_set_has_at_least_forty_cases_in_every_category():
    cases = [json.loads(p.read_text(encoding="utf-8")) for p in CASES]
    assert len(cases) >= 40
    categories = {c["category"] for c in cases}
    assert {"grounding", "rules", "safety_text", "refusal", "prefilter", "injection", "format", "privacy", "fallback",
            "modes", "vision", "kidney_only", "lab_report", "preferences", "recipes"} <= categories
    assert len({c["id"] for c in cases}) == len(cases)


@pytest.fixture(scope="module")
def golden(tmp_path_factory) -> Iterator[tuple[TestClient, TestClient]]:
    tmp = tmp_path_factory.mktemp("golden")
    settings = make_settings(tmp, FOODS_JSON, ai=AiEnv(provider="openai", api_key="sk-golden-0123456789abcdefghij",
                                                         model="gpt-6-luna", vision_model="gpt-6-luna",
                                                         private_hosts=(LOCAL_HOST,)))
    with TestClient(create_app(settings), base_url=HTTPS_URL) as admin:
        sign_in(admin)
        r = admin.patch("/api/admin/settings", json={"ai.enabled": True, **LEGACY_ROUTING, "ai.route.recipes": "any", "ai.shared_daily_limit": 0,
                                                     "ai.vision_plate_enabled": True, "ai.chat_enabled": True})
        assert r.status_code == 200, r.text
        # Lab report photos run only on a local AI (privacy tier 1): the cases of category lab_report use this one.
        r = admin.post("/api/admin/ai-providers", json={"preset": "ollama", "model": "gemma", "vision_model": "llava",
                                                         "base_url": f"http://{LOCAL_HOST}/v1"})
        assert r.status_code == 201, r.text
        r = admin.put("/api/admin/ai-routing", json={"local_provider": r.json()["id"]})
        assert r.status_code == 200, r.text
        sam = add_user(admin)
        yield admin, sam


def food_id(client: TestClient, name: str) -> int:
    hits = client.get("/api/foods", params={"q": name, "limit": 50}).json()["foods"]
    for f in hits:
        if f["name"] == name:
            return int(f["id"])
    raise AssertionError(f"no food named {name!r}")


def reset(client: TestClient) -> None:
    from app.db import connect

    conn = connect(client.app.state.settings.db_path)
    try:
        for sql in ("DELETE FROM log_entries WHERE user_id = 1", "DELETE FROM meal_templates WHERE user_id = 1",
                    "DELETE FROM food_preferences WHERE user_id = 1", "DELETE FROM user_settings WHERE user_id = 1",
                    "DELETE FROM ai_audit", "DELETE FROM ai_usage", "DELETE FROM ai_consents"):
            conn.execute(sql)
        conn.execute("DELETE FROM foods WHERE source = 'custom'")
        conn.commit()
    finally:
        conn.close()
    client.app.state.settings_store.invalidate()
    # Each case (and each run of scripts/ai_eval.py) is a new question: no answer kept from the last one (note 06 §4.13).
    from app.ai.cache import AnswerCache

    client.app.state.ai.answers = AnswerCache()


def snapshot(client: TestClient) -> dict[str, list[tuple[Any, ...]]]:
    """Every table a preference, a log entry, a saved meal or a setting would be written to (a case's ``nothing_saved``)."""
    from app.db import connect

    conn = connect(client.app.state.settings.db_path)
    try:
        return {t: [tuple(r) for r in conn.execute(f"SELECT * FROM {t} ORDER BY 1, 2")]
                for t in ("food_preferences", "log_entries", "meal_templates", "user_settings", "assistant_ask_keys")}
    finally:
        conn.close()


def day_before(n: int) -> str:
    from datetime import date, timedelta

    return (date.fromisoformat(DAY) - timedelta(days=n)).isoformat()


def prepare(admin: TestClient, sam: TestClient, fx: dict[str, Any]) -> dict[str, Any]:
    reset(admin)
    profile = {"ckd_stage": "4", "dialysis": "none", "diabetes": "type1", "weight_kg": 70, "height_cm": 170,
               "birth_month": "1961-04", "sex": "female", **fx.get("profile", {})}
    targets = fx.get("targets", "stage4")
    profile["targets"] = TARGET_PRESETS[targets] if isinstance(targets, str) else targets
    r = admin.put("/api/profile", json=profile)
    assert r.status_code == 200, r.text
    ctx: dict[str, Any] = {"other": {}, "entries": [], "custom": {}}
    for item in fx.get("custom_foods", []):
        r = admin.post("/api/foods", json=item)
        assert r.status_code == 201, r.text
        ctx["custom"][item["name"]] = r.json()["id"]
    for item in fx.get("other_custom_foods", []):
        r = sam.post("/api/foods", json=item)
        assert r.status_code == 201, r.text
        ctx["other"][item["name"]] = r.json()["id"]
    for row in fx.get("entries", []):
        meal, name, servings, *rest = row
        body = {"date": DAY, "meal": meal, "food_id": food_id(admin, name), "servings": servings,
                "status": rest[0] if rest else "eaten"}
        if len(rest) > 1:
            body["purpose"] = rest[1]
        r = admin.post("/api/log", json=body)
        assert r.status_code == 201, r.text
        ctx["entries"].append(r.json()["id"])
    for days, meal, name, servings in fx.get("history", []):
        r = admin.post("/api/log", json={"date": day_before(days), "meal": meal, "food_id": food_id(admin, name), "servings": servings})
        assert r.status_code == 201, r.text
    if "recipe" in fx:  # a saved recipe for mode "change" (feature recipes)
        recipe = {k: v for k, v in fx["recipe"].items() if k != "items"}
        recipe["items"] = [{"food_id": food_id(admin, name), "servings": servings} for name, servings in fx["recipe"]["items"]]
        r = admin.post("/api/meals", json=recipe)
        assert r.status_code == 201, r.text
        ctx["recipe_id"] = r.json()["id"]
    r = admin.patch("/api/admin/settings", json={"ai.recipe_steps": bool(fx.get("recipe_steps"))})
    assert r.status_code == 200, r.text
    settings = fx.get("settings", {})
    r = admin.patch("/api/me/ai", json={"opt_in": True, **settings.get("ai", {})})
    assert r.status_code == 200, r.text
    if "guidance" in settings:
        r = admin.patch("/api/me/settings", json={"guidance": settings["guidance"]})
        assert r.status_code == 200, r.text
    for name, preference in fx.get("food_preferences", []):  # what the person said about taste (note 09), by food name
        r = admin.put(f"/api/guidance/preferences/{ctx['custom'].get(name) or food_id(admin, name)}", json={"preference": preference})
        assert r.status_code == 200, r.text
    status = admin.get("/api/ai/status").json()
    for purpose in ("text", "photos", "chat"):
        r = admin.post("/api/ai/consent", json={"provider_id": status["provider"]["id"], "purpose": purpose})
        assert r.status_code == 200, r.text
    labs = status["routes"]["labs"]["runs_on"]  # the local AI, when this server has one
    if labs is not None:
        r = admin.post("/api/ai/consent", json={"provider_id": labs["id"], "purpose": "labs"})
        assert r.status_code == 200, r.text
    return ctx


def data_of(request: httpx2.Request) -> dict[str, Any]:
    body = json.loads(request.content)
    content = body["messages"][1]["content"]
    text = content if isinstance(content, str) else content[0]["text"]
    if "<data>" not in text:
        return {}
    return json.loads(text.split("<data>\n", 1)[1].split("\n</data>", 1)[0])


def resolver(case_ctx: dict[str, Any]):
    def resolve(output: str, request: httpx2.Request) -> str:
        data = data_of(request)
        names: dict[str, dict[str, Any]] = {}
        for c in data.get("candidates", []):
            names.setdefault(c["name"], c)
        for s in data.get("swaps", []):
            names.setdefault(s["name"], {"ref": s["ref"]})

        def sub(match: re.Match[str]) -> str:
            kind, name = match.group(1), match.group(2)
            if kind == "other_custom_id":
                return str(case_ctx["other"][name])
            if kind == "id" and name.startswith("#"):  # a food that is deliberately not a candidate
                return str(case_ctx["food_ids"][name[1:]])
            item = names.get(name)
            if item is None:
                raise AssertionError(f"{name!r} is not a candidate in this request")
            return str(item["id"]) if kind == "id" else json.dumps(item["ref"])

        return PLACEHOLDER.sub(sub, output)

    return resolve


def stub(case: dict[str, Any], case_ctx: dict[str, Any]) -> FakeProvider:
    outputs = list(case.get("model_outputs", []))
    resolve = resolver(case_ctx)

    def route(request: httpx2.Request):
        if not outputs:
            raise AssertionError(f"{case['id']}: the app called the model more often than the case allows")
        out = outputs.pop(0)
        if isinstance(out, str):
            return chat(resolve(out, request))
        if "status" in out and out["status"] != 200:
            return {"status": out["status"], "headers": {"Content-Type": "application/json", **out.get("headers", {})},
                    "body": out.get("body", {"error": {"message": "stub"}})}
        extra = {"reasoning_content": out["reasoning_content"]} if "reasoning_content" in out else None
        content = out.get("content")
        if isinstance(content, (dict, list)):
            content = json.dumps(content)
        return chat(None if content is None else resolve(content, request), finish=out.get("finish_reason", "stop"),
                    refusal=out.get("refusal"), extra_message=extra)

    return FakeProvider(route=route, address=LOCAL_ADDRESS if case["feature"] == "lab_report" else PUBLIC_IP)


def shown_names(result: dict[str, Any], client: TestClient) -> set[str]:
    names = set()
    for idea in result.get("ideas") or []:
        names |= {i["name"] for i in idea["items"]}
    for pick in result.get("pick") or []:
        names.add(pick["name"])
    for recipe in result.get("recipes") or []:
        names |= {i["name"] for i in recipe["items"]}
    for item in result.get("order") or []:
        names.add(client.get(f"/api/foods/{item['food_id']}").json()["name"])
    return names


GOLDEN = [pytest.param(p, id=p.stem, marks=[pytest.mark.safety] if _is_safety(p) else []) for p in CASES]


@pytest.mark.parametrize("path", GOLDEN)
def test_golden_case(path: Path, golden):
    admin, sam = golden
    case = json.loads(path.read_text(encoding="utf-8"))
    assert case["id"] == path.stem
    fx = case.get("fixture", {})
    case_ctx = prepare(admin, sam, fx)
    case_ctx["food_ids"] = {name: food_id(admin, name) for name in fx.get("ids_needed", [])}
    provider = stub(case, case_ctx)
    expect = case["expect"]
    before = snapshot(admin)
    with attach(admin.app, provider):
        feature = case["feature"]
        if feature == "chat":
            r = admin.post("/api/ai/chat", json={"messages": [{"role": "user", "text": fx["message"]}], "request_id": "golden-chat-0001"})
        elif feature == "next_meal":
            body: dict[str, Any] = {"meal": fx.get("meal", "dinner"), "mode": fx.get("mode", "ideas"), "date": DAY}
            if "swap_entry" in fx:
                body["entry_id"] = case_ctx["entries"][fx["swap_entry"]]
            r = admin.post("/api/ai/next-meal", json=body)
        elif feature == "recipes":
            body = {"mode": fx.get("mode", "suggest"), "target": fx.get("target", "meal"), "date": DAY}
            if body["target"] == "meal":
                body["meal"] = fx.get("meal", "dinner")
            if body["mode"] == "change":
                body["meal_id"] = case_ctx["recipe_id"]
            else:
                body |= {"dish": fx.get("dish", "bowl"), "makes": fx.get("makes", 2)}
            r = admin.post("/api/ai/recipes", json=body)
        elif feature == "parse_meal":
            r = admin.post("/api/ai/parse-meal", json={"text": fx["text"], "date": DAY})
        elif feature == "lab_report":
            image = (IMAGES / fx.get("image", "label.jpg")).read_bytes()
            r = admin.post("/api/ai/read-lab-report", content=image, headers={"Content-Type": "image/jpeg"})
        else:
            image = (IMAGES / fx.get("image", "label.jpg")).read_bytes()
            r = admin.post(f"/api/vision/{feature}", content=image, headers={"Content-Type": "image/jpeg"})
    assert r.status_code == expect.get("http", 200), (case["id"], r.text[:500])
    result = r.json()
    text = json.dumps(result, ensure_ascii=False)
    if __import__("os").environ.get("GOLDEN_DEBUG"):
        print(json.dumps({k: result.get(k) for k in ("status", "dropped", "portions_lowered", "claims_corrected", "reason", "message")}, default=str))
        for idea in result.get("ideas") or []:
            print(idea["theme"], idea["reason_codes"], idea["totals"], idea["after"])
    if "status" in expect:
        assert result.get("status") == expect["status"], (case["id"], text[:800])
    assert provider.calls == expect.get("calls", 1), (case["id"], provider.calls)
    names = shown_names(result, admin)
    for name in expect.get("shown_food_names", []):
        assert name in names, (case["id"], names)
    for name in expect.get("not_shown_food_names", []):
        assert name not in names, (case["id"], names)
    ideas = result.get("ideas") or []
    first_names = {i["name"] for i in ideas[0]["items"]} if ideas else set()
    for name in expect.get("not_first_food_names", []):  # a food the person wants less often is not the first thing recommended
        assert name not in first_names, (case["id"], first_names)
    codes = [c for idea in ideas for c in idea["reason_codes"]]
    for code in expect.get("idea_reason_codes_include", []):
        assert code in codes, (case["id"], codes)
    for code in expect.get("idea_reason_codes_exclude", []):
        assert code not in codes, (case["id"], codes)
    if "kind" in expect:
        assert result.get("kind") == expect["kind"], (case["id"], result.get("kind"), text[:600])
    if "pending" in expect:  # Ask: the card the person is asked to confirm
        card = result.get("pending_save") or {}
        want = expect["pending"]
        assert card.get("tool") == want["tool"], (case["id"], card)
        if "preference" in want:
            assert card.get("preference") == want["preference"], (case["id"], card)
        if "target" in want:
            assert (card.get("target") or {}).get("name") == want["target"], (case["id"], card)
    elif feature == "chat":
        assert result.get("pending_save") is None, (case["id"], result.get("pending_save"))
    if expect.get("nothing_saved"):  # no preference, log entry, saved meal or setting was written
        assert snapshot(admin) == before, case["id"]
    dropped = result.get("dropped", [])
    reasons = [d["reason"] for d in dropped] if isinstance(dropped, list) else []  # a lab report counts its dropped lines instead
    for prefix in expect.get("dropped_reasons_include", []):
        assert any(r_.startswith(prefix) for r_ in reasons), (case["id"], reasons)
    lowered = [x["reason"] for x in result.get("portions_lowered") or []]
    for prefix in expect.get("portions_lowered_include", []):  # an idea the app made smaller instead of dropping it
        assert any(r_.startswith(prefix) for r_ in lowered), (case["id"], lowered)
    if "portions_lowered" in expect:
        assert len(lowered) == expect["portions_lowered"], (case["id"], lowered)
        made_smaller = {x["index"] for x in result.get("portions_lowered") or []}
        assert all(("portion_note" in i) == (i["index"] in made_smaller) for i in ideas), case["id"]  # the app's sentence
        for card in result.get("recipes") or []:  # an AI recipe whose too-big share the fit made smaller
            assert (card.get("portion_note") is not None) == (card["index"] in made_smaller), case["id"]
    for name, most in (expect.get("shown_quarters_at_most") or {}).items():
        amounts = [round(it["servings"] * 4) for i in ideas for it in i["items"] if it["name"] == name]
        assert amounts and max(amounts) <= most, (case["id"], name, amounts)
    if "claims_corrected" in expect:
        assert result.get("claims_corrected") == expect["claims_corrected"], (case["id"], result.get("claims_corrected"))
    if "rule_fallback" in expect:
        assert ("fallback" in result) == expect["rule_fallback"], case["id"]
    if "repaired" in expect:
        assert result.get("repaired") == expect["repaired"], case["id"]
    for needle in expect.get("response_excludes", []):
        assert needle.lower() not in text.lower(), (case["id"], needle)
    if provider.chat_requests:
        sent = provider.chat_requests[0].content.decode("utf-8")
        for needle in expect.get("payload_includes", []):
            assert needle in sent, (case["id"], needle)
        for needle in expect.get("payload_excludes", []):
            assert needle not in sent, (case["id"], needle)
    recipes = result.get("recipes") or []
    if "recipes" in expect:
        assert len(recipes) == expect["recipes"], (case["id"], text[:800])
    if "title" in expect:
        assert recipes and recipes[0]["title"] == expect["title"], (case["id"], [x["title"] for x in recipes])
    if "steps_shown" in expect:
        assert recipes and recipes[0]["steps"] == expect["steps_shown"], (case["id"], recipes[0]["steps"] if recipes else None)
    for prefix in expect.get("steps_dropped_include", []):
        got = [d["reason"] for x in recipes for d in x["steps_dropped"]]
        assert any(g.startswith(prefix) for g in got), (case["id"], got)
    if "cards" in expect:
        assert [c["title"] for c in result.get("cards", [])] == expect["cards"], case["id"]
    for key, value in (expect.get("draft") or {}).items():
        draft = result["draft"]
        actual = draft["nutrients"].get(key) if key in draft["nutrients"] else draft.get(key)
        assert actual == value, (case["id"], key, actual)
    if "items" in expect:
        assert len(result.get("items", [])) == expect["items"], (case["id"], result.get("items"))
    if "rows" in expect:  # lab_report: [analyte, value, unit, taken_on or null] per proposed row, in order
        assert [[x["analyte"], x["value"], x["unit"], x["taken_on"]] for x in result.get("rows", [])] == expect["rows"], (case["id"], result.get("rows"))
    if "dropped" in expect and isinstance(result.get("dropped"), dict):
        assert result["dropped"] == expect["dropped"], (case["id"], result["dropped"])
    if "checks_include" in expect:
        codes = [c["code"] for c in result.get("checks", [])]
        for code in expect["checks_include"]:
            assert code in codes, (case["id"], codes)
