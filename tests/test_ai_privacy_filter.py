"""The privacy filter (design note 31, ``app/ai/privacy_filter.py``): names, places, dates and other identifiers out of every
request to a cloud AI and back into its reply; requests to the local AI never changed; lab reports still local-only.

The offline test set ``tests/data/redaction_cases.json`` measures recall (printed; the run fails below its floor). No network:
every provider is a fake behind the pinned transport."""
from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Any

import pytest

from ai_support import PRIVATE_POLICY, FakeProvider, attach, chat, make_cfg, no_sleep
from test_ai_cloud_routing import attached, servers, start_two
from test_ai_cloud_env import both
from test_ai_routing import db, ready
from test_lab_photo import GOOD, read
from app.ai import client as C
from app.ai import privacy_filter as P
from app.ai import prompts, routing as R, schemas
from app.ai.netpolicy import NetPolicy
from app.ai.transport import AiTransportError

CASES = json.loads((Path(__file__).parent / "data" / "redaction_cases.json").read_text(encoding="utf-8"))
PERSON = {"ckd_stage": "4", "dialysis": "none", "diabetes": "type1", "preferences": None, "likes": None, "less_often": None,
          "not_for_me": None, "age_band": None, "sex": None}


# --------------------------------------------------------------------------- #
# The offline test set
# --------------------------------------------------------------------------- #


def test_the_redaction_set_meets_its_recall_floor_and_keeps_every_medical_detail():
    found = gone = 0
    kept_total = kept = 0
    misses: list[str] = []
    for case in CASES["cases"]:
        out = P.filter_text(case["text"], case.get("known", []))
        for item in case["remove"]:
            found += 1
            if item not in out:
                gone += 1
            else:
                misses.append(f"{case['id']}: {item}")
        for item in case["keep"]:
            kept_total += 1
            kept += item in out
            assert item in out, f"{case['id']}: lost {item!r} -> {out!r}"
        if "expected" in case:
            assert out == case["expected"], case["id"]
    recall = gone / found
    print(f"\nprivacy filter recall: {gone}/{found} = {recall:.3f} (floor {CASES['recall_floor']}); kept {kept}/{kept_total}; "
          f"missed: {misses}")
    assert recall >= CASES["recall_floor"]
    assert all(m.split(":")[0].startswith("known-miss") for m in misses), misses  # only the cases marked as known misses


def test_every_case_has_an_id_and_the_ids_are_unique():
    ids = [c["id"] for c in CASES["cases"]]
    assert len(ids) == len(set(ids)) >= 50


def app_texts() -> dict[str, str]:
    from app.ai import chat as CH, chat_save as CS

    texts: dict[str, str] = {}
    for key, value in vars(prompts).items():
        if isinstance(value, str):
            texts[key] = value
        elif isinstance(value, dict):
            texts.update({f"{key}.{k}": v for k, v in value.items() if isinstance(v, str)})
    texts["system_prompt"] = prompts.system_prompt(PERSON)
    texts["chat_prompt"] = prompts.chat_prompt(PERSON)
    texts["chat_system"] = prompts.chat_system(CH.tools_text(CS.tool_schemas()), schemas.chat_step_schema(CH.OFFERED_TOOLS), PERSON)
    texts["recipe_system"] = prompts.recipe_system_prompt(PERSON, steps=True)
    for name in dir(schemas):
        if name.endswith("_schema") and callable(getattr(schemas, name)):
            try:
                texts[name] = prompts.schema_line(getattr(schemas, name)())
            except TypeError:
                continue
    return texts


def test_the_apps_own_prompts_and_schemas_pass_through_unchanged():
    texts = app_texts()
    assert len(texts) > 40
    for key, text in texts.items():
        assert P.filter_text(text) == text, key


def test_a_data_block_stays_valid_json_and_its_numbers_stay():
    data = {"preferences": "My wife Ann cooks. Call 555-867-5309 on 2026-10-30.", "candidates": [{"id": 1234567, "name": "Dr Pepper",
            "potassium_mg": 4700, "per": [12345678, 2.5]}], "date": "2026-10-31"}
    block = prompts.data_block(data)
    out = P.filter_text(block)
    inner = json.loads(out.split("\n")[1])
    assert inner["candidates"] == data["candidates"]  # numbers in the app's JSON are never touched
    assert inner["date"] == "[DATE_1]" and "Ann" not in inner["preferences"] and "555-867-5309" not in inner["preferences"]


# --------------------------------------------------------------------------- #
# Labels: consistent, never reused, put back in the reply
# --------------------------------------------------------------------------- #


def test_the_same_word_gets_the_same_label_and_labels_already_in_the_text_are_not_reused():
    out = P.filter_text("[PERSON_1] said hi. My friend Ann met Dr Ann Lee. ANN laughed.")
    assert out.startswith("[PERSON_1] said hi.") and "[PERSON_2]" in out and "Ann" not in out and "ANN" not in out


def test_the_reply_gets_the_original_words_back():
    shield = P.Shield(terms=P.expand_terms(["Margaret Okonkwo"]))
    body = {"messages": [{"role": "system", "content": "Help."}, {"role": "user", "content": "Margaret saw Dr Patel on 3 May 2026."}]}
    sent = shield.filter_body(body)
    text = sent["messages"][1]["content"]
    assert "Margaret" not in text and "Patel" not in text and "3 May 2026" not in text and shield.replaced == 3
    assert body["messages"][1]["content"] == "Margaret saw Dr Patel on 3 May 2026."  # the original body is not changed
    reply = {"answer": "Tell [PERSON_1] that [person_2] was right on DATE_1.", "items": [{"text": "[PERSON_1]'s soup"}],
             "other": "[PERSON_9] stays", "n": 3}
    assert shield.restore(reply) == {"answer": "Tell Margaret that Patel was right on 3 May 2026.",
                                     "items": [{"text": "Margaret's soup"}], "other": "[PERSON_9] stays", "n": 3}


def test_the_shield_never_shows_its_words():
    shield = P.Shield(terms=("Margaret",))
    shield.filter_body({"messages": [{"role": "user", "content": "Margaret here"}]})
    assert "Margaret" not in repr(shield) and "Margaret" not in str(shield)


def test_images_are_left_as_they_are():
    body = {"messages": [{"role": "user", "content": [{"type": "text", "text": "My wife Ann took this."},
                                                      {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,AAAA"}}]}]}
    sent = P.Shield().filter_body(body)
    assert sent["messages"][0]["content"][0]["text"] == "My wife [PERSON_1] took this."
    assert sent["messages"][0]["content"][1] == body["messages"][0]["content"][1]


# --------------------------------------------------------------------------- #
# Hostile input
# --------------------------------------------------------------------------- #

HOSTILE = {
    "spaces": " ", "brackets": "(", "capitals": "A", "digits": "1", "capital words": "Aa ", "digit groups": "1 ", "titles": "Dr ",
    "at signs": "a@", "dots": "1.", "dashes": "1-", "bracket digits": "(1 ", "slashes": "1/", "plus": "+1 ", "months": "May ",
    "labels": "id ", "apostrophes": "A'", "relations": "my wife ", "street": "1 Aa ", "label text": "[PERSON_1",
}


@pytest.mark.parametrize("unit", list(HOSTILE.values()), ids=list(HOSTILE))
def test_hostile_input_is_filtered_quickly(unit):
    text = (unit * (P.MAX_TEXT_CHARS // len(unit) + 1))[: P.MAX_TEXT_CHARS]
    started = time.perf_counter()
    P.filter_text(text, ["Ann Smith"])
    assert time.perf_counter() - started < 10.0  # linear: well under a second on a laptop for 200,000 characters


def test_a_text_part_over_the_limit_is_refused_not_sent_unfiltered():
    with pytest.raises(P.FilterLimit):
        P.Shield().filter_body({"messages": [{"role": "user", "content": "a" * (P.MAX_TEXT_CHARS + 1)}]})
    cfg = make_cfg()
    provider = FakeProvider([chat({"ok": "yes"})])
    client = C.ChatClient(NetPolicy(), app_version="t", transport_factory=provider.factory, sleep=no_sleep)
    body = C.build_body(cfg, system="s", user_text="a" * (P.MAX_TEXT_CHARS + 1), schema=C.PROBE_SCHEMA, schema_name="p", mode="json_object")
    result = asyncio.run(client.complete_json(cfg, body, lambda d: d))
    assert (result.status, result.error, provider.calls) == ("error", "privacy_filter", 0)


# --------------------------------------------------------------------------- #
# The client: the one place a request is sent
# --------------------------------------------------------------------------- #

ASK = "My wife Ann Smith asked Dr Patel on 12 March 2026: is 2 cups of rice too much potassium?"


def call(cfg: C.ProviderConfig, answers: list[Any]) -> tuple[C.CallResult, FakeProvider, dict[str, Any]]:
    provider = FakeProvider(answers)
    client = C.ChatClient(NetPolicy(), app_version="t", transport_factory=provider.factory, sleep=no_sleep)
    body = C.build_body(cfg, system="Answer in JSON.", user_text=ASK, schema=C.PROBE_SCHEMA, schema_name="p", mode="json_object")
    result = asyncio.run(client.complete_json(cfg, body, lambda d: d))
    return result, provider, body


def test_a_cloud_request_is_filtered_and_its_reply_restored():
    cfg = make_cfg(privacy_terms=("Ann Smith", "Ann", "Smith"))
    result, provider, body = call(cfg, [chat({"answer": "[PERSON_2] is right, [PERSON_1]: 2 cups is a lot.", "when": "[DATE_1]"})])
    sent = provider.bodies()[0]["messages"][1]["content"]
    for word in ("Ann", "Smith", "Patel", "12 March 2026"):
        assert word not in sent
    assert "2 cups of rice" in sent and "potassium" in sent
    assert result.parsed == {"answer": "Patel is right, Ann Smith: 2 cups is a lot.", "when": "12 March 2026"}
    assert result.privacy_replaced == 3 and result.bodies == provider.bodies()  # the bodies as sent
    assert "[PERSON_1]" in (result.text or "")  # the reply as it came back, with its labels


def test_a_repair_turn_is_filtered_with_the_same_labels():
    cfg = make_cfg()
    result, provider, _ = call(cfg, [chat("not json, sorry [PERSON_1]"), chat({"ok": "[PERSON_1]"})])
    first, second = provider.bodies()
    assert first["messages"][1]["content"] == second["messages"][1]["content"]
    assert "Ann" not in json.dumps(second) and "Patel" not in json.dumps(second)
    assert result.repaired and result.parsed == {"ok": "Ann Smith"}


def test_a_local_request_is_never_changed():
    cfg = make_cfg("ollama", base_url="http://ollama:11434/v1", local_only=True, privacy_terms=("Ann",))
    provider = FakeProvider([chat({"ok": "[PERSON_1] Ann"})], address="10.0.0.5")
    client = C.ChatClient(PRIVATE_POLICY, app_version="t", transport_factory=provider.factory,
                          sleep=no_sleep)
    body = C.build_body(cfg, system="Answer in JSON.", user_text=ASK, schema=C.PROBE_SCHEMA, schema_name="p", mode="json_object")
    result = asyncio.run(client.complete_json(cfg, body, lambda d: d))
    assert provider.bodies() == [body]  # byte for byte what was built
    assert result.parsed == {"ok": "[PERSON_1] Ann"} and result.privacy_replaced is None
    assert P.shield_for(cfg) is None and P.preview(cfg, body) == (body, None)


def test_the_client_refuses_a_cloud_body_that_skipped_the_filter():
    cfg = make_cfg()
    provider = FakeProvider([chat({"ok": "yes"})])
    client = C.ChatClient(NetPolicy(), app_version="t", transport_factory=provider.factory, sleep=no_sleep)
    with pytest.raises(AiTransportError) as err:
        asyncio.run(client.request(cfg, "POST", "chat/completions", {"messages": [{"role": "user", "content": ASK}]}))
    assert err.value.category == "privacy_filter" and provider.calls == 0


def test_nothing_about_the_words_is_logged(caplog):
    caplog.set_level(logging.DEBUG)
    cfg = make_cfg(privacy_terms=("Ann Smith", "Ann", "Smith"))
    call(cfg, [chat({"ok": "[PERSON_1]"})])
    for word in ("Ann", "Smith", "Patel", "12 March"):
        assert word not in caplog.text


# --------------------------------------------------------------------------- #
# The app: routing unchanged, "What will be sent?", the activity row
# --------------------------------------------------------------------------- #


def name_the_account(client: Any) -> None:
    conn = sqlite3.connect(client.app.state.settings.db_path)
    try:
        conn.execute("UPDATE users SET display_name = 'Margaret Okonkwo' WHERE id = 1")
        conn.commit()
    finally:
        conn.close()


def describe(client: Any, text: str, **params: Any):
    return client.post("/api/ai/parse-meal", json={"text": text}, params=params)


MEAL = "Margaret's lentil soup and 2 slices of toast from my friend Tom on 30 Oct 2026"
PARSED = {"status": "ok", "items": [{"text": "[PERSON_1]'s lentil soup", "search": "lentil soup", "amount": 1, "unit": "serving"},
                                    {"text": "2 slices of toast from [PERSON_2]", "search": "toast", "amount": 2, "unit": "slice"}]}


def test_describe_on_the_cloud_sends_labels_shows_them_in_the_preview_and_answers_with_the_words(tmp_path, foods_json, caplog):
    caplog.set_level(logging.DEBUG)
    for rig in start_two(both(tmp_path, foods_json)):
        c = rig.client
        name_the_account(c)
        ready(c, {rig.local: ("photos", "labs"), rig.cloud: ("text", "chat")})
        c.patch("/api/admin/settings", json={"ai.audit_retention_days": 30})
        hosts = servers(cloud=[chat(PARSED)])
        with attached(c.app, hosts):
            dry = describe(c, MEAL, dry_run="true").json()
            r = describe(c, MEAL)
        assert r.status_code == 200, r.text
        sent = hosts.by_host["litellm.lan"].bodies()
        assert dry["body"] == sent[0]  # "What will be sent?" is exactly what left
        assert dry["privacy_filter"]["on"] is True and dry["privacy_filter"]["replaced"] == 3
        assert "replaced 3 details" in dry["privacy_filter"]["text"]
        text = json.dumps(sent)
        for word in ("Margaret", "Tom", "30 Oct 2026"):
            assert word not in text
        assert "lentil soup" in text and "2 slices of toast" in text
        assert [i["text"] for i in r.json()["items"]] == ["Margaret's lentil soup", "2 slices of toast from Tom"]
        [row] = db(c, "SELECT request_json, response_text, verdict_json FROM ai_audit WHERE feature = 'parse_meal'")
        assert json.loads(row["verdict_json"])["privacy_filter"] == 3  # how many, never which
        for word in ("Margaret", "Okonkwo", "Tom", "30 Oct"):
            assert word not in row["request_json"] and word not in row["response_text"] and word not in row["verdict_json"]
        assert gpu_untouched(hosts)
        for word in ("Margaret", "Okonkwo", "30 Oct"):
            assert word not in caplog.text


def gpu_untouched(hosts: Any) -> bool:
    return hosts.by_host["gpu.lan"].requests == []


def test_describe_on_the_local_ai_is_sent_exactly_as_typed(tmp_path, foods_json):
    for rig in start_two(both(tmp_path, foods_json), describe="local"):
        c = rig.client
        name_the_account(c)
        ready(c, {rig.local: ("photos", "labs", "text"), rig.cloud: ("text", "chat")})
        hosts = servers(gpu=[chat(PARSED)])
        with attached(c.app, hosts):
            dry = describe(c, MEAL, dry_run="true").json()
            r = describe(c, MEAL)
        assert r.status_code == 200, r.text
        [sent] = hosts.by_host["gpu.lan"].bodies()
        assert dry["body"] == sent and dry["privacy_filter"] is None
        assert MEAL in sent["messages"][1]["content"]
        assert hosts.requests("litellm.lan") == []
        [row] = db(c, "SELECT verdict_json FROM ai_audit WHERE feature = 'parse_meal'")
        assert "privacy_filter" not in json.loads(row["verdict_json"])


def test_lab_reports_stay_local_only_with_the_filter(tmp_path, foods_json):
    """The filter is never a reason to send a lab report to the cloud: the route still takes only local or off, a cloud provider
    never serves it, and the local request is not filtered."""
    for rig in start_two(both(tmp_path, foods_json)):
        c = rig.client
        name_the_account(c)
        ready(c, {rig.local: ("photos", "labs"), rig.cloud: ("text", "chat")})
        for route in ("cloud", "any", "local_then_cloud"):
            refused = c.put("/api/admin/ai-routing", json={"labs": route})
            assert refused.status_code in (400, 422), refused.text
        hosts = servers(gpu=[chat(GOOD)], cloud=[chat(GOOD)])
        with attached(c.app, hosts):
            dry = read(c, dry_run="true").json()
            r = read(c)
        assert r.status_code == 200, r.text
        assert next(f for f in c.get("/api/admin/ai-routing").json()["features"] if f["feature"] == "labs")["route"] == "local"
        assert dry["provider"]["local"] is True and dry["privacy_filter"] is None
        assert hosts.requests("litellm.lan") == [] and len(hosts.requests("gpu.lan")) == 1
        state = c.app.state
        conn = sqlite3.connect(state.settings.db_path)
        conn.row_factory = sqlite3.Row
        try:
            labs = R.resolve_feature(conn, state.ai.store, state.keyring, state.settings, state.ai.policy, user_id=1,
                                     can_use_shared=True, feature="labs")
            cloud = R.resolve_feature(conn, state.ai.store, state.keyring, state.settings, state.ai.policy, user_id=1,
                                      can_use_shared=True, feature="describe")
        finally:
            conn.close()
        assert labs.cfg is not None and labs.cfg.local_only and labs.cfg.privacy_terms == ()  # local: no names attached, no filter
        assert labs.fallback is None and labs.role == "local"
        assert cloud.cfg is not None and not cloud.cfg.local_only and "Margaret" in cloud.cfg.privacy_terms
        assert "Margaret" not in repr(cloud.cfg)


def test_the_care_teams_names_are_known_terms(tmp_path, foods_json):
    from conftest import add_user

    for rig in start_two(both(tmp_path, foods_json)):
        c = rig.client
        add_user(c, "priya.k")
        conn = sqlite3.connect(c.app.state.settings.db_path)
        try:
            conn.execute("UPDATE users SET display_name = 'Priya Kaur' WHERE username = 'priya.k'")
            other = conn.execute("SELECT id FROM users WHERE username = 'priya.k'").fetchone()[0]
            conn.execute("INSERT INTO shares (owner_user_id, grantee_user_id, areas, created_at, accepted_at) VALUES (1, ?, '[\"log\"]', "
                         "'2026-10-31T00:00:00Z', '2026-10-31T00:00:00Z')", (other,))
            conn.commit()
            terms = P.known_terms(conn, 1)
            assert {"priya.k", "priya kaur", "priya", "kaur"} <= {t.casefold() for t in terms}
            assert "admin" not in {t.casefold() for t in terms}  # a common word is never a term
            conn.execute("UPDATE shares SET ended_at = '2026-10-31T01:00:00Z', ended_by = 'owner'")
            conn.commit()
            assert "Priya" not in P.known_terms(conn, 1)  # a share that ended is not the Care team any more
        finally:
            conn.close()


def test_the_ask_dry_run_shows_the_filtered_conversation(tmp_path, foods_json):
    from test_ai_chat import ask

    for rig in start_two(both(tmp_path, foods_json)):
        c = rig.client
        name_the_account(c)
        ready(c, {rig.local: ("photos", "labs"), rig.cloud: ("text", "chat")})
        with attached(c.app, servers()):
            dry = ask(c, "Margaret here, born 4 June 1961. Is a banana OK?", dry_run="true").json()
        text = json.dumps(dry["body"])
        assert "Margaret" not in text and "4 June 1961" not in text and "banana" in text
        assert dry["privacy_filter"]["replaced"] == 2


def test_attach_still_works_with_the_legacy_single_provider(tmp_path, foods_json):
    """The older single-provider setup (one public provider, route ``any``) is a cloud AI: it is filtered too."""
    from test_ai_routes import ai_settings, enable, ready as ready_one
    from conftest import HTTPS_URL, TestClient, sign_in
    from app.main import create_app

    with TestClient(create_app(ai_settings(tmp_path, foods_json)), base_url=HTTPS_URL) as c:
        sign_in(c)
        enable(c)
        name_the_account(c)
        ready_one(c)
        with attach(c.app, FakeProvider([chat(PARSED)])) as provider:
            r = describe(c, MEAL)
        assert r.status_code == 200 and "Margaret" not in json.dumps(provider.bodies())
