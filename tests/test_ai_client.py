"""Provider contract tests (note 04 R11.2): the exact request body per preset, parsing of each backend's
response shape (fixtures in tests/fixtures/ai/), the retry and repair rules, the concurrency gate and
"Test connection" with the Hermes tool check (§9 A1). No network."""
from __future__ import annotations

import json
from typing import Any

import anyio
import httpx2
import pytest

from ai_support import FakeProvider, PRIVATE_POLICY, SLEEPS, chat, fixture, make_cfg, no_sleep
from app.ai import client as C
from app.ai import netpolicy as N
from app.ai.schemas import IdeasAnswer, model_validator_for

SCHEMA = {"type": "object", "additionalProperties": False, "required": ["ok"], "properties": {"ok": {"type": "string"}}}
POLICY = PRIVATE_POLICY


def body_for(cfg: C.ProviderConfig, *, vision: bool = False, images: tuple[str, ...] = ()) -> dict[str, Any]:
    user = "TASK: test" if cfg.structured == "json_schema" else 'TASK: test\nRESPONSE SCHEMA: {"x":1}'
    return C.build_body(cfg, system="SYSTEM", user_text=user, images=list(images), schema=SCHEMA, schema_name="t",
                        mode=cfg.structured, vision=vision)


def run(cfg: C.ProviderConfig, provider: FakeProvider, body: dict[str, Any] | None = None, validate=None, *, vision: bool = False) -> C.CallResult:
    SLEEPS.clear()
    client = C.ChatClient(POLICY, app_version="9.9.9", transport_factory=provider.factory, sleep=no_sleep)

    async def go() -> C.CallResult:
        return await client.complete_json(cfg, body or body_for(cfg), validate or (lambda d: d), vision=vision)

    return anyio.run(go)


# --------------------------------------------------------------------------- #
# Request bodies per preset (R4, R6)
# --------------------------------------------------------------------------- #


def test_openai_body():
    cfg = make_cfg("openai", safety_identifier="a" * 32)
    body = body_for(cfg)
    assert body["model"] == "test-model" and body["stream"] is False
    assert body["max_completion_tokens"] == 1500 and "max_tokens" not in body
    assert body["response_format"] == {"type": "json_schema", "json_schema": {"name": "t", "strict": True, "schema": SCHEMA}}
    assert body["store"] is False and body["reasoning_effort"] == "low"
    assert "temperature" not in body and "tools" not in body and "n" not in body
    assert body["safety_identifier"] == "a" * 32  # shared key only
    own = C.build_body(make_cfg("openai", scope="user", safety_identifier="b" * 32), system="S", user_text="U", schema=SCHEMA,
                       schema_name="t", mode="json_schema")
    assert "safety_identifier" not in own
    assert body["messages"] == [{"role": "system", "content": "SYSTEM"}, {"role": "user", "content": "TASK: test"}]


def test_openrouter_body():
    cfg = make_cfg("openrouter", extra_body={"provider": {"data_collection": "deny", "require_parameters": True, "zdr": True}})
    body = body_for(cfg)
    assert body["max_tokens"] == 1500 and "max_completion_tokens" not in body
    assert body["provider"] == {"data_collection": "deny", "require_parameters": True, "zdr": True}
    assert body["temperature"] == 0.2 and "reasoning_effort" not in body
    assert body["response_format"]["type"] == "json_schema"


def test_ollama_body_and_placeholder_key():
    cfg = make_cfg("ollama", api_key=None)
    body = body_for(cfg)
    assert body["max_tokens"] == 1500 and body["reasoning_effort"] == "none" and body["temperature"] == 0.2
    assert C.headers_for(cfg, "1.0")["Authorization"] == "Bearer ollama"
    assert C.headers_for(make_cfg("llamacpp", api_key=None), "1.0").get("Authorization") is None


def test_hermes_body_is_prompt_only():
    cfg = make_cfg("hermes")
    body = body_for(cfg)
    assert cfg.structured == "prompt"
    assert "response_format" not in body and "temperature" not in body and "reasoning_effort" not in body
    assert "RESPONSE SCHEMA" in body["messages"][1]["content"]


@pytest.mark.parametrize("preset, mode", [("llamacpp", "prompt"), ("nous_portal", "prompt"), ("openai_compatible", "prompt"),
                                          ("vllm", "json_schema"), ("lmstudio", "json_schema"), ("litellm", "json_schema")])
def test_probe_presets_start_prompt_only(preset, mode):
    assert make_cfg(preset).structured == mode


def test_json_object_mode():
    body = body_for(make_cfg("openai", structured="json_object"))
    assert body["response_format"] == {"type": "json_object"}


def test_vision_body_uses_data_urls_the_vision_model_and_temperature_zero():
    cfg = make_cfg("ollama", vision_model="qwen3-vl:8b", model="text-model")
    body = body_for(cfg, vision=True, images=("data:image/jpeg;base64,AAAA",))
    assert body["model"] == "qwen3-vl:8b" and body["temperature"] == 0.0
    content = body["messages"][1]["content"]
    assert content[1] == {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,AAAA"}}


def test_headers_identify_the_app_not_the_person():
    headers = C.headers_for(make_cfg("openai"), "0.3.0")
    assert headers == {"User-Agent": "kidney-health/0.3.0", "Authorization": "Bearer sk-test-0123456789abcdefghijkl"}
    assert "not shown" in C.shown_headers(make_cfg("openai"), "0.3.0")["Authorization"]


def test_presets_extra_body_is_not_shared_between_bodies():
    cfg = make_cfg("openrouter")
    first = body_for(cfg)
    first["provider"]["data_collection"] = "allow"
    assert body_for(cfg)["provider"]["data_collection"] == "deny"


# --------------------------------------------------------------------------- #
# Parsing each backend's answer (R6 "Parse")
# --------------------------------------------------------------------------- #

VALIDATE_IDEAS = model_validator_for(IdeasAnswer)


@pytest.mark.parametrize("name, preset", [
    ("openai_chat.json", "openai"), ("ollama_chat_reasoning.json", "ollama"), ("llamacpp_fenced.json", "llamacpp"),
    ("lmstudio_prose.json", "lmstudio"), ("hermes_chat.json", "hermes"), ("openrouter_chat.json", "openrouter"),
])
def test_every_backend_shape_parses(name, preset):
    cfg = make_cfg(preset, base_url="https://ai.example.com/v1")
    provider = FakeProvider([fixture(name)])
    result = run(cfg, provider, validate=VALIDATE_IDEAS)
    assert result.status == "ok", result
    assert result.parsed.ideas[0]["items"] == [{"food_id": 2, "quarters": 4}]
    assert result.usage["prompt_tokens"] > 0 and result.usage["completion_tokens"] > 0
    assert provider.calls == 1 and not result.repaired


def test_reasoning_text_is_never_kept():
    for name in ("ollama_chat_reasoning.json", "llamacpp_fenced.json"):
        result = run(make_cfg("ollama"), FakeProvider([fixture(name)]))
        assert "never" not in (result.text or "") and "Thinking" not in (result.text or "")


def test_refusal_field():
    result = run(make_cfg("openai"), FakeProvider([fixture("openai_refusal.json")]))
    assert result.status == "refused" and "insulin" in result.refusal


def test_finish_reason_length_is_truncated_and_not_repaired():
    provider = FakeProvider([fixture("openrouter_length.json")])
    result = run(make_cfg("openrouter"), provider)
    assert (result.status, result.error) == ("invalid", "truncated") and provider.calls == 1


@pytest.mark.parametrize("text, expected", [
    ('{"a": 1}', {"a": 1}),
    ('﻿{"a": 1}', {"a": 1}),
    ('```json\n{"a": {"b": "}"}}\n```', {"a": {"b": "}"}}),
    ('```\n{"a": 2}\n```', {"a": 2}),
    ('Sure! Here it is: {"a": "x{y"} Thanks.', {"a": "x{y"}),
    ('{broken {"a": 3}', {"a": 3}),
    ('{"s": "quote \\" brace }"}', {"s": 'quote " brace }'}),
])
def test_extract_json(text, expected):
    assert C.extract_json(text) == expected


@pytest.mark.parametrize("text", [None, "", "   ", "no json here", '{"a": 1', "[1, 2, 3]", "x" * 40_000 + '{"a": 1}'])
def test_extract_json_failures(text):
    with pytest.raises(C.JsonNotFound):
        C.extract_json(text)


def test_parse_reply_rejects_odd_shapes():
    for data in ([], {"choices": []}, {"choices": [{"message": "x"}]}, "text"):
        with pytest.raises(Exception):
            C.parse_reply(data)
    reply = C.parse_reply({"choices": [{"message": {"content": [{"type": "text", "text": "a"}, {"type": "image"}, {"type": "text", "text": "b"}]}}],
                           "usage": {"prompt_tokens": True, "completion_tokens": -5}})
    assert reply.content == "ab" and reply.usage == {"prompt_tokens": 0, "completion_tokens": 0}


# --------------------------------------------------------------------------- #
# Retries and repair (R6): at most one extra request
# --------------------------------------------------------------------------- #


def test_429_honours_retry_after_then_succeeds():
    provider = FakeProvider([fixture("openai_429.json"), chat({"ok": "yes"})])
    result = run(make_cfg("openai"), provider)
    assert result.status == "ok" and result.retried and provider.calls == 2 and SLEEPS == [3.0]


def test_429_retry_after_is_capped_at_ten_seconds():
    item = fixture("openai_429.json")
    item["headers"]["Retry-After"] = "120"
    run(make_cfg("openai"), FakeProvider([item, chat({"ok": "yes"})]))
    assert SLEEPS == [10.0]


def test_5xx_and_connect_errors_retry_once_after_a_second():
    provider = FakeProvider([{"status": 503, "body": {"error": "x"}}, chat({"ok": "yes"})])
    assert run(make_cfg("openai"), provider).status == "ok" and SLEEPS == [1.0]
    provider = FakeProvider([{"status": 500, "body": {}}, {"status": 502, "body": {}}])
    result = run(make_cfg("openai"), provider)
    assert (result.status, result.error) == ("error", "http_5xx") and provider.calls == 2

    def boom(request):
        return httpx2.ConnectError("refused", request=request)
    provider = FakeProvider(route=lambda r: boom(r))
    result = run(make_cfg("openai"), provider)
    assert result.error == "connect_failed" and provider.calls == 2


@pytest.mark.parametrize("status, category", [(401, "http_401"), (403, "http_403"), (404, "http_404"), (400, "http_4xx")])
def test_client_errors_are_never_retried(status, category):
    provider = FakeProvider([{"status": status, "body": {"error": {"message": "nope"}}}])
    result = run(make_cfg("openai"), provider)
    assert (result.status, result.error) == ("error", category) and provider.calls == 1 and SLEEPS == []


def test_invalid_json_gets_one_repair_turn():
    provider = FakeProvider([chat('{"status": "ok", "refusal": "none", "ideas": [{"theme"'), chat(
        {"status": "ok", "refusal": "none", "ideas": []})])
    result = run(make_cfg("openai"), provider, validate=VALIDATE_IDEAS)
    assert result.status == "ok" and result.repaired and provider.calls == 2
    repair = provider.bodies()[1]["messages"]
    assert repair[-2]["role"] == "assistant" and repair[-1]["role"] == "user"
    assert repair[-1]["content"].startswith("Your previous reply was not valid:")
    assert repair[:2] == provider.bodies()[0]["messages"]


def test_schema_errors_are_summarised_without_the_input():
    provider = FakeProvider([chat({"status": "maybe", "refusal": "none", "ideas": [], "secret": "SENTINEL"}),
                             chat({"status": "ok", "refusal": "none", "ideas": []})])
    result = run(make_cfg("openai"), provider, validate=VALIDATE_IDEAS)
    assert result.status == "ok"
    summary = provider.bodies()[1]["messages"][-1]["content"]
    assert "status" in summary and "SENTINEL" not in summary.split("not valid:", 1)[1]


def test_a_failed_repair_is_invalid():
    provider = FakeProvider([chat("not json"), chat("still not json")])
    result = run(make_cfg("openai"), provider)
    assert (result.status, result.error) == ("invalid", "no_json") and provider.calls == 2


def test_empty_content():
    provider = FakeProvider([chat(None), chat(None)])
    result = run(make_cfg("openai"), provider)
    assert (result.status, result.error) == ("invalid", "empty")


def test_only_one_extra_request_in_total():
    provider = FakeProvider([{"status": 503, "body": {}}, chat("not json")])
    result = run(make_cfg("openai"), provider)
    assert (result.status, result.error) == ("invalid", "no_json") and provider.calls == 2 and not result.repaired


def test_every_body_sent_is_recorded():
    provider = FakeProvider([chat("x"), chat({"ok": "yes"})])
    result = run(make_cfg("openai"), provider)
    assert result.bodies == provider.bodies()


# --------------------------------------------------------------------------- #
# Concurrency gate (R6)
# --------------------------------------------------------------------------- #


def test_concurrency_gate():
    gate = C.ConcurrencyGate(2)
    gate.enter(1)
    with pytest.raises(C.Busy) as info:
        gate.enter(1)
    assert info.value.scope == "person"
    gate.enter(2)
    with pytest.raises(C.Busy) as info:
        gate.enter(3)
    assert info.value.scope == "server"
    gate.leave(1)
    gate.enter(3)
    gate.leave(2)
    gate.leave(3)
    gate.leave(3)  # leaving twice is harmless
    assert gate.active == 0
    gate.enter(4, limit=1)
    with pytest.raises(C.Busy):
        gate.enter(5)


# --------------------------------------------------------------------------- #
# Test connection and the Hermes tool check (R4, §9 A1)
# --------------------------------------------------------------------------- #


def probe(cfg: C.ProviderConfig, provider: FakeProvider, snippet=None) -> dict[str, Any]:
    client = C.ChatClient(POLICY, app_version="1", transport_factory=provider.factory, sleep=no_sleep)
    return anyio.run(lambda: C.probe(client, cfg, error_snippet=snippet))


def test_probe_detects_json_schema_and_vision():
    def chat_route(request):
        body = json.loads(request.content)
        if body["model"] == "vision-model":
            assert body["messages"][1]["content"][1]["image_url"]["url"].startswith("data:image/png;base64,")
            return chat({"color": "red"})
        return chat({"ok": "yes"})
    provider = FakeProvider(route=lambda r: fixture("openai_models.json") if r.url.path.endswith("/models") else chat_route(r))
    result = probe(make_cfg("openai", model="gpt-6-luna", vision_model="vision-model"), provider)
    assert result["ok"] and result["structured"] == "json_schema" and result["vision"] == {"ok": True, "error": None}
    assert result["models"] == {"listed": 2, "model_listed": True}
    assert any("vision model" in w for w in result["warnings"])  # vision-model is not in the listing


def test_probe_falls_back_from_json_schema_to_json_object():
    answers = [fixture("openai_400_response_format.json"), chat({"ok": "yes"})]
    provider = FakeProvider(route=lambda r: fixture("openai_models.json") if r.url.path.endswith("/models") else answers.pop(0))
    result = probe(make_cfg("openai", model="other-model"), provider)
    assert result["structured"] == "json_object" and result["ok"]
    assert any("not in the server's model list" in w for w in result["warnings"])
    assert provider.bodies()[1]["response_format"] == {"type": "json_object"}


def test_probe_reports_a_refused_key_and_shows_shared_error_bodies_to_admins():
    seen: list[bytes] = []
    provider = FakeProvider([{"status": 401, "body": {"error": {"message": "Incorrect API key provided"}}}])
    result = probe(make_cfg("openai"), provider, snippet=seen.append)
    assert not result["ok"] and "refused the key" in result["errors"][0] and b"Incorrect API key" in seen[0]


def test_probe_with_models_404_still_tests_chat():
    provider = FakeProvider(route=lambda r: {"status": 404, "body": {}} if r.url.path.endswith("/models") else chat({"ok": "yes"}))
    result = probe(make_cfg("ollama", api_key=None), provider)
    assert result["ok"] and result["models"] == {"listed": None, "model_listed": None}


def hermes_cfg() -> C.ProviderConfig:
    return make_cfg("hermes", base_url="http://host.containers.internal:8643/v1", model="kidney")


def hermes_provider(toolsets: Any) -> FakeProvider:
    def route(request):
        path = request.url.path
        if path.endswith("/toolsets"):
            return toolsets
        if path.endswith("/capabilities"):
            return fixture("hermes_capabilities.json")
        if path.endswith("/models"):
            return {"status": 200, "body": {"object": "list", "data": [{"id": "kidney"}]}}
        return chat({"ok": "yes"})
    return FakeProvider(route=route, address="169.254.1.2")


def test_hermes_with_an_enabled_toolset_is_refused_before_any_chat():
    provider = hermes_provider(fixture("hermes_toolsets_enabled.json"))
    result = probe(hermes_cfg(), provider)
    assert not result["ok"] and "tools enabled" in result["errors"][0] and provider.calls == 0
    assert result["tools"]["toolsets"][0] == {"name": "core", "enabled": True, "tools": 3}


def test_hermes_disabled_toolsets_listing_tools_are_accepted():
    provider = hermes_provider(fixture("hermes_toolsets_clean.json"))
    result = probe(hermes_cfg(), provider)
    assert result["ok"] and result["structured"] == "json_schema" and result["tools"]["ok"]
    assert result["capabilities"]["chat_completions"] is True
    assert provider.requests[0].url.path == "/v1/toolsets"  # checked first


@pytest.mark.parametrize("answer", [
    {"status": 200, "body": {"toolsets": "none"}},              # not a list
    {"status": 200, "body": [{"name": "core", "tools": []}]},   # no "enabled"
    {"status": 200, "body": [{"name": "core", "enabled": True, "tools": "terminal"}]},
    {"status": 500, "body": {}},
    {"status": 404, "body": {}},
    {"status": 200, "headers": {"Content-Type": "text/html"}, "body": "<html>"},
])
def test_hermes_tool_check_fails_closed(answer):
    check = anyio.run(lambda: C.hermes_tools_check(
        C.ChatClient(POLICY, app_version="1", transport_factory=hermes_provider(answer).factory), hermes_cfg()))
    assert not check.ok and check.reason


def test_hermes_wrapped_list_is_understood():
    assert C.judge_toolsets(fixture("hermes_toolsets_wrapped.json")["body"]).ok


def test_red_square_png_is_a_valid_png():
    data = C.red_square_png()
    assert data.startswith(b"\x89PNG\r\n\x1a\n") and b"IHDR" in data and b"IEND" in data


def test_hermes_is_reachable_only_through_the_allowlist():
    provider = hermes_provider(fixture("hermes_toolsets_clean.json"))
    client = C.ChatClient(N.NetPolicy(), app_version="1", transport_factory=provider.factory)
    check = anyio.run(lambda: C.hermes_tools_check(client, hermes_cfg()))
    assert not check.ok and "blocked_address" in check.reason and not provider.requests
