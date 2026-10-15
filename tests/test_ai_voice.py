"""``POST /api/ai/transcribe``, the Ask microphone's speech-to-text (``app/ai/stt.py``, ``app/ai/voice.py``;
docs/dev/plans/assistant-step2.md part B; ARCHITECTURE "Voice input").

Covered: the switches (a 404 before the body is looked at), sign-in, consent for the purpose ``voice``, the content
type, the first bytes and the size, the multipart form that is forwarded (model, response format, the app's own file
name, the key as a bearer token), the cleaned transcript, the daily limit, the address rules (the same as an AI
provider's), what is stored (nothing about the audio or the transcript, in the database, the files or the logs), the
activity row, the key never leaving the server, and the admin's read-only view and test. No network: the
transcription server is a fake behind the transport's test hook."""
from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any, Iterator

import httpx2
import pytest

from ai_support import FakeProvider, attach
from conftest import HTTPS_URL, TestClient, add_user, make_settings, sign_in
from test_ai_chat import become_ready
from test_ai_routes import OPENAI_KEY, enable
from app.ai import stt
from app.ai.voice import silent_wav
from app.config import AiEnv, ConfigError, load_settings
from app.main import create_app

STT_KEY = "stt-key-ZYXWVUTSRQPONMLKJIHGFEDCBA123456"
AUDIO_MARKER = b"audio-marker-7f3a9c41"
TEXT_MARKER = "transcript-marker-90417"
WEBM = b"\x1a\x45\xdf\xa3" + AUDIO_MARKER + b"\x00" * 300
OGG = b"OggS\x00\x02" + AUDIO_MARKER + b"\x00" * 300
MP4 = b"\x00\x00\x00\x18ftypM4A \x00\x00\x00\x00" + AUDIO_MARKER + b"\x00" * 300
WAV = silent_wav(1)


def stt_env(**extra: Any) -> AiEnv:
    values: dict[str, Any] = {"provider": "openai", "api_key": OPENAI_KEY, "model": "gpt-6-luna", "vision_model": "gpt-6-luna",
                              "stt_base_url": "https://stt.example.com/v1", "stt_model": "whisper-1", "stt_api_key": STT_KEY}
    values.update(extra)
    return AiEnv(**values)


def voice_settings(tmp_path, foods_json, env: AiEnv | None = None, **settings: Any):
    return make_settings(tmp_path, foods_json, ai=env or stt_env(), **settings)


def transcription(text: str = "what is left for today") -> Any:
    def route(request: httpx2.Request) -> Any:
        if request.url.path.endswith("/audio/transcriptions"):
            return httpx2.Response(200, json={"text": text})
        return None

    return route


def fake_stt(text: str = "what is left for today", **kwargs: Any) -> FakeProvider:
    return FakeProvider(route=transcription(text), **kwargs)


def say(client: TestClient, audio: bytes = WEBM, ctype: str = "audio/webm", **params: Any):
    return client.post("/api/ai/transcribe", content=audio, headers={"Content-Type": ctype}, params=params)


def consent_voice(client: TestClient) -> int:
    status = client.get("/api/ai/status").json()
    pid = status["provider"]["id"]
    r = client.post("/api/ai/consent", json={"provider_id": pid, "purpose": "voice"})
    assert r.status_code == 200, r.text
    return pid


@pytest.fixture
def voice_client(tmp_path, foods_json) -> Iterator[TestClient]:
    with TestClient(create_app(voice_settings(tmp_path, foods_json)), base_url=HTTPS_URL) as c:
        sign_in(c)
        enable(c, **{"ai.chat_enabled": True, "ai.voice_enabled": True})
        become_ready(c)
        consent_voice(c)
        yield c


def db_rows(client: TestClient, table: str) -> list[sqlite3.Row]:
    conn = sqlite3.connect(client.app.state.settings.db_path)
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute(f"SELECT * FROM {table}").fetchall()
    finally:
        conn.close()


def forwarded(provider: FakeProvider) -> list[httpx2.Request]:
    return [r for r in provider.requests if r.url.path.endswith("/audio/transcriptions")]


def parts_of(request: httpx2.Request) -> dict[str, tuple[dict[str, str], bytes]]:
    """The fields of a multipart request: name → (the part's headers, its bytes)."""
    boundary = request.headers["content-type"].split("boundary=", 1)[1].encode()
    out: dict[str, tuple[dict[str, str], bytes]] = {}
    for part in request.content.split(b"--" + boundary):
        if part in (b"", b"--\r\n", b"\r\n"):
            continue
        head, _, body = part.partition(b"\r\n\r\n")
        headers = {}
        for line in head.decode().strip().split("\r\n"):
            k, _, v = line.partition(": ")
            headers[k.lower()] = v
        name = headers["content-disposition"].split('name="', 1)[1].split('"', 1)[0]
        out[name] = (headers, body[:-2] if body.endswith(b"\r\n") else body)
    return out


# --------------------------------------------------------------------------- #
# Availability: the switches, sign-in, consent
# --------------------------------------------------------------------------- #


def test_the_route_is_a_404_before_the_body_unless_voice_is_on_and_configured(tmp_path, foods_json):
    garbage = {"content": b"not audio", "headers": {"Content-Type": "text/plain"}}
    # AI off
    with TestClient(create_app(voice_settings(tmp_path / "a", foods_json)), base_url=HTTPS_URL) as c:
        sign_in(c)
        assert c.post("/api/ai/transcribe", **garbage).status_code == 404
        enable(c)  # AI on, Ask off, voice off
        become_ready(c, consent=False)
        assert c.post("/api/ai/transcribe", **garbage).status_code == 404
        enable(c, **{"ai.voice_enabled": True})  # voice on but Ask off: the microphone lives in Ask
        assert c.post("/api/ai/transcribe", **garbage).status_code == 404
        enable(c, **{"ai.chat_enabled": True})
        assert c.post("/api/ai/transcribe", **garbage).status_code == 415  # now the route is there (the type is checked)
        enable(c, **{"ai.voice_enabled": False})
        assert c.post("/api/ai/transcribe", **garbage).status_code == 404
        assert c.get("/api/ai/status").json()["features"]["voice"] is False
    # not configured
    env = stt_env(stt_base_url=None, stt_model=None, stt_api_key=None)
    with TestClient(create_app(voice_settings(tmp_path / "b", foods_json, env)), base_url=HTTPS_URL) as c:
        sign_in(c)
        enable(c, **{"ai.chat_enabled": True, "ai.voice_enabled": True})
        become_ready(c)
        assert c.post("/api/ai/transcribe", **garbage).status_code == 404
        status = c.get("/api/ai/status").json()
        assert status["features"]["voice"] is False and status["voice"] is None


def test_the_route_needs_a_signed_in_person(tmp_path, foods_json):
    with TestClient(create_app(voice_settings(tmp_path, foods_json)), base_url=HTTPS_URL) as c:
        assert say(c).status_code == 401


def test_the_person_must_have_opted_in_to_ai(tmp_path, foods_json):
    with TestClient(create_app(voice_settings(tmp_path, foods_json)), base_url=HTTPS_URL) as c:
        sign_in(c)
        enable(c, **{"ai.chat_enabled": True, "ai.voice_enabled": True})
        with attach(c.app, fake_stt()) as provider:
            r = say(c)
            assert r.status_code == 503 and r.json()["reason"] == "not_opted_in"
            assert not forwarded(provider)
        status = c.get("/api/ai/status").json()
        assert status["features"]["voice"] is False


def test_status_says_voice_is_available_and_names_the_host_but_never_the_key(voice_client):
    c = voice_client
    status = c.get("/api/ai/status").json()
    assert status["features"]["voice"] is True
    voice = status["voice"]
    assert voice["host"] == "stt.example.com" and voice["model"] == "whisper-1" and voice["max_seconds"] == 60
    assert voice["max_bytes"] == 1_572_864 and voice["remaining_today"] == 100
    assert voice["consent"]["host"] == "stt.example.com" and status["consent"]["voice"]["host"] == "stt.example.com"
    assert voice["request"]["purpose"] == "voice" and voice["request"]["provider_label"] == "Speech to text"
    assert STT_KEY not in json.dumps(status)


def test_voice_needs_its_own_consent_and_the_409_says_what_would_be_sent(voice_client):
    c = voice_client
    pid = c.get("/api/ai/status").json()["provider"]["id"]
    assert c.delete(f"/api/ai/consent/{pid}", params={"purpose": "voice"}).status_code == 204
    for purpose in ("text", "photos", "chat"):  # the other purposes do not cover a recording
        assert c.post("/api/ai/consent", json={"provider_id": pid, "purpose": purpose}).status_code == 200
    with attach(c.app, fake_stt()) as provider:
        r = say(c)
        assert r.status_code == 409 and r.json()["consent_required"] is True
        sheet = r.json()["consent"]
        assert sheet["purpose"] == "voice" and sheet["host"] == "stt.example.com" and sheet["provider_id"] == pid
        assert sheet["policy"].startswith("Your recording is sent to stt.example.com to turn it into text, then deleted. Nothing is kept.")
        assert not forwarded(provider)  # the audio went nowhere
        assert c.post("/api/ai/consent", json={"provider_id": pid + 99, "purpose": "voice"}).status_code == 409  # another provider
        assert say(c).status_code == 409
        consent_voice(c)
        assert say(c).status_code == 200 and len(forwarded(provider)) == 1


def test_voice_consent_is_per_person_and_lists_as_speech_to_text(voice_client):
    c = voice_client
    sam = add_user(c)
    become_ready(sam)
    with attach(c.app, fake_stt()) as provider:
        assert say(sam).status_code == 409  # the admin's consent is not Sam's
        assert not forwarded(provider)
        consent_voice(sam)
        assert say(sam).status_code == 200
    rows = c.get("/api/me/ai").json()["consents"]
    voice = [r for r in rows if r["purpose"] == "voice"]
    assert len(voice) == 1 and voice[0]["provider_label"] == "Speech to text" and voice[0]["host"] == "stt.example.com"
    assert voice[0]["current"] is True


def test_a_changed_transcription_host_asks_again(tmp_path, foods_json):
    settings = voice_settings(tmp_path, foods_json)
    with TestClient(create_app(settings), base_url=HTTPS_URL) as c:
        sign_in(c)
        enable(c, **{"ai.chat_enabled": True, "ai.voice_enabled": True})
        become_ready(c)
        consent_voice(c)
        with attach(c.app, fake_stt()):
            assert say(c).status_code == 200
    moved = voice_settings(tmp_path, foods_json, stt_env(stt_base_url="https://other-stt.example.net/v1"))
    with TestClient(create_app(moved), base_url=HTTPS_URL) as c:
        sign_in(c)
        with attach(c.app, fake_stt()) as provider:
            r = say(c)
            assert r.status_code == 409 and r.json()["consent"]["host"] == "other-stt.example.net"
            assert not forwarded(provider)


# --------------------------------------------------------------------------- #
# The clip: type, first bytes, size
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("ctype", ["audio/mpeg", "text/plain", "application/octet-stream", "video/webm", "image/jpeg", "audio/x-wav", ""])
def test_other_content_types_are_415(voice_client, ctype):
    with attach(voice_client.app, fake_stt()) as provider:
        r = say(voice_client, WEBM, ctype)
        assert r.status_code == 415 and r.json()["reason"] == "not_audio"
        assert not forwarded(provider)


@pytest.mark.parametrize("ctype,audio", [("audio/webm", OGG), ("audio/ogg", WEBM), ("audio/mp4", WEBM), ("audio/wav", MP4),
                                         ("audio/webm", b"%PDF-1.7 " + b"x" * 200), ("audio/webm", b"<html>" + b"x" * 200),
                                         ("audio/ogg", b"\x89PNG\r\n\x1a\n" + b"x" * 200)])
def test_bytes_that_are_not_the_declared_audio_container_are_400(voice_client, ctype, audio):
    with attach(voice_client.app, fake_stt()) as provider:
        r = say(voice_client, audio, ctype)
        assert r.status_code == 400 and r.json()["reason"] == "not_audio"
        assert not forwarded(provider)


def test_an_empty_recording_is_400(voice_client):
    with attach(voice_client.app, fake_stt()) as provider:
        for audio in (b"", b"\x1a\x45\xdf\xa3"):
            r = say(voice_client, audio)
            assert r.status_code == 400 and r.json()["reason"] == "empty"
        assert not forwarded(provider)


@pytest.mark.parametrize("ctype,audio", [("audio/webm", WEBM), ("audio/ogg", OGG), ("audio/mp4", MP4), ("audio/wav", WAV),
                                         ("audio/webm;codecs=opus", WEBM), ("Audio/OGG; codecs=opus", OGG)])
def test_the_four_containers_are_accepted_and_sent_under_the_apps_own_names(voice_client, ctype, audio):
    with attach(voice_client.app, fake_stt()) as provider:
        r = say(voice_client, audio, ctype)
        assert r.status_code == 200, r.text
        sent = parts_of(forwarded(provider)[0])
        kind = stt.KIND_BY_TYPE[ctype.split(";")[0].strip().lower()]
        head, body = sent["file"]
        assert f'filename="{stt.FILENAME[kind]}"' in head["content-disposition"] and head["content-type"] == stt.SENT_TYPE[kind]
        assert body == audio


def test_a_clip_over_the_size_limit_is_413_declared_or_streamed(tmp_path, foods_json):
    settings = voice_settings(tmp_path, foods_json, max_audio_bytes=4096)
    with TestClient(create_app(settings), base_url=HTTPS_URL) as c:
        sign_in(c)
        enable(c, **{"ai.chat_enabled": True, "ai.voice_enabled": True})
        become_ready(c)
        consent_voice(c)
        big = b"\x1a\x45\xdf\xa3" + b"\x00" * 5000
        with attach(c.app, fake_stt()) as provider:
            assert say(c, big).status_code == 413  # a declared Content-Length over the limit
            def chunks() -> Iterator[bytes]:
                for _ in range(10):
                    yield b"\x1a\x45\xdf\xa3" + b"\x00" * 1000
            r = c.post("/api/ai/transcribe", content=chunks(), headers={"Content-Type": "audio/webm"})  # no Content-Length
            assert r.status_code == 413
            assert say(c, b"\x1a\x45\xdf\xa3" + b"\x00" * 3000).status_code == 200  # under the limit
            assert len(forwarded(provider)) == 1


def test_the_body_limit_is_registered_for_this_exact_path_only():
    from app.security import BodyLimitMiddleware

    settings = make_settings(Path("/nonexistent"), Path("/nonexistent"), max_audio_bytes=2000, max_body_bytes=500)
    limits = BodyLimitMiddleware(lambda *a: None, settings)  # type: ignore[arg-type]
    assert limits.limit_for("/api/ai/transcribe") == 2000
    assert limits.limit_for("/api/ai/chat") == 500 and limits.limit_for("/api/ai/transcribe-x") == 500
    assert limits.limit_for("/api/ai") == 500


def test_a_wav_longer_than_a_minute_is_413_and_a_page_length_over_a_minute_is_refused(voice_client):
    long_wav = silent_wav(63, rate=8000)  # 8 kHz so that a minute fits under the byte limit too
    short = silent_wav(59, rate=8000)
    with attach(voice_client.app, fake_stt()) as provider:
        r = say(voice_client, long_wav, "audio/wav")
        assert r.status_code == 413 and r.json()["reason"] == "too_long"
        assert say(voice_client, short, "audio/wav").status_code == 200
        assert say(voice_client, WEBM, seconds=61).status_code == 400  # the page never sends more than 60 (a validation error is 400 here)
        assert len(forwarded(provider)) == 1


# --------------------------------------------------------------------------- #
# What is forwarded and what comes back
# --------------------------------------------------------------------------- #


def test_the_clip_is_forwarded_as_multipart_with_model_and_key_and_the_text_comes_back(voice_client):
    with attach(voice_client.app, fake_stt("What is left for today?")) as provider:
        r = say(voice_client, WEBM, "audio/webm;codecs=opus", seconds=7)
        assert r.status_code == 200 and r.json() == {"text": "What is left for today?"}
        request = forwarded(provider)[0]
        assert request.method == "POST" and request.url.path == "/v1/audio/transcriptions"
        assert request.headers["host"] == "stt.example.com" and request.url.scheme == "https"  # connected to the checked address, named by Host
        assert request.headers["content-type"].startswith("multipart/form-data; boundary=")
        assert request.headers["authorization"] == f"Bearer {STT_KEY}"
        assert request.headers["user-agent"].startswith("kidney-health/")
        sent = parts_of(request)
        assert set(sent) == {"model", "response_format", "file"}
        assert sent["model"][1] == b"whisper-1" and sent["response_format"][1] == b"json"
        assert sent["file"][1] == WEBM
        # nothing about the person: no cookie, no CSRF header, no name
        assert "cookie" not in request.headers and "x-requested-with" not in request.headers
        assert b"admin" not in request.content.replace(AUDIO_MARKER, b"")
        assert provider.resolved == ["stt.example.com"]


def test_a_server_without_a_key_gets_no_authorization_header(tmp_path, foods_json):
    settings = voice_settings(tmp_path, foods_json, stt_env(stt_api_key=None))
    with TestClient(create_app(settings), base_url=HTTPS_URL) as c:
        sign_in(c)
        enable(c, **{"ai.chat_enabled": True, "ai.voice_enabled": True})
        become_ready(c)
        consent_voice(c)
        with attach(c.app, fake_stt()) as provider:
            assert say(c).status_code == 200
            assert "authorization" not in forwarded(provider)[0].headers


def test_the_transcript_is_cleaned_by_the_chat_text_policy_and_capped(voice_client):
    dirty = "Ｗｈａｔ​ is\x07 left\n\n  for   today?" + " more" * 800
    with attach(voice_client.app, fake_stt(dirty)):
        text = say(voice_client).json()["text"]
    assert text.startswith("What is left for today? more") and len(text) <= stt.MAX_TRANSCRIPT_CHARS
    assert "​" not in text and "\x07" not in text and "\n" not in text and "Ｗ" not in text


def test_an_empty_transcript_is_an_empty_string(voice_client):
    with attach(voice_client.app, fake_stt("   ")):
        r = say(voice_client)
    assert r.status_code == 200 and r.json() == {"text": ""}


@pytest.mark.parametrize("answer", [{"words": "no text key"}, {"text": 5}, [], "plain", None])
def test_an_answer_without_text_is_a_502(voice_client, answer):
    with attach(voice_client.app, FakeProvider(route=lambda r: httpx2.Response(200, json=answer))):
        r = say(voice_client)
    assert r.status_code == 502 and r.json()["reason"] == "invalid_response"


@pytest.mark.parametrize("response,reason", [
    (httpx2.Response(401, json={"error": "bad key sk-secret-from-server"}), "http_401"),
    (httpx2.Response(403, text="forbidden"), "http_403"),
    (httpx2.Response(404, text="no such model"), "http_404"),
    (httpx2.Response(429, text="slow down"), "http_429"),
    (httpx2.Response(400, text="bad audio"), "http_4xx"),
    (httpx2.Response(500, text="boom"), "http_5xx"),
    (httpx2.Response(302, headers={"Location": "https://evil.example/x"}), "invalid_response"),  # redirects are never followed
    (httpx2.Response(200, headers={"Content-Type": "text/html"}, text="<html>"), "invalid_response"),
    (httpx2.ReadTimeout("slow"), "timeout"),
    (httpx2.ConnectError("refused"), "connect_failed"),
])
def test_upstream_failures_are_a_502_with_a_plain_message_and_never_the_servers_words(voice_client, caplog, response, reason):
    caplog.set_level(logging.DEBUG)
    with attach(voice_client.app, FakeProvider(route=lambda r: response)) as provider:
        r = say(voice_client)
        assert r.status_code == 502 and r.json()["reason"] == reason
        assert r.json()["detail"] == stt.ERROR_TEXT[reason]
        assert "sk-secret-from-server" not in r.text and "evil.example" not in r.text
        assert len(forwarded(provider)) == 1  # no retry: a recording is sent once
    assert "sk-secret-from-server" not in caplog.text


# --------------------------------------------------------------------------- #
# The same address rules as an AI provider
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("address", ["10.1.2.3", "127.0.0.1", "169.254.169.254", "192.168.1.50", "::1"])
def test_a_host_that_resolves_to_a_private_or_metadata_address_is_refused_like_an_ai_provider(voice_client, address):
    with attach(voice_client.app, fake_stt(address=address)) as provider:
        r = say(voice_client)
        assert r.status_code == 502 and r.json()["reason"] == "blocked_address"
        assert not forwarded(provider)  # nothing was sent: the address was refused before connecting


def test_plain_http_to_a_lan_host_works_only_when_ai_private_hosts_lists_it(tmp_path, foods_json):
    lan = {"stt_base_url": "http://stt:8000/v1", "stt_api_key": None}
    for private, expected in (((), 502), (("stt:8000",), 200)):
        env = stt_env(private_hosts=private, **lan)
        with TestClient(create_app(voice_settings(tmp_path / str(expected), foods_json, env)), base_url=HTTPS_URL) as c:
            sign_in(c)
            enable(c, **{"ai.chat_enabled": True, "ai.voice_enabled": True})
            become_ready(c)
            consent_voice(c)
            with attach(c.app, fake_stt(address="172.20.0.7")) as provider:
                r = say(c)
                assert r.status_code == expected, r.text
                if expected == 502:
                    assert r.json()["reason"] == "blocked_address" and not forwarded(provider)
                else:
                    sent = forwarded(provider)[0]
                    assert sent.url.scheme == "http" and sent.url.path == "/v1/audio/transcriptions" and sent.headers["host"] == "stt:8000"


def test_the_host_is_resolved_on_every_request_and_the_environment_proxy_is_ignored(voice_client, monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.invalid:3128")
    with attach(voice_client.app, fake_stt()) as provider:
        assert say(voice_client).status_code == 200 and say(voice_client).status_code == 200
        assert provider.resolved == ["stt.example.com", "stt.example.com"]


def test_a_blocked_transcription_host_is_a_start_up_warning_not_a_crash(tmp_path, foods_json, caplog):
    env = stt_env(stt_base_url="http://stt:8000/v1")
    caplog.set_level(logging.WARNING)
    with TestClient(create_app(voice_settings(tmp_path, foods_json, env)), base_url=HTTPS_URL) as c:
        sign_in(c)
        enable(c, **{"ai.chat_enabled": True, "ai.voice_enabled": True})
        view = c.get("/api/admin/ai-providers").json()["voice"]
        assert "AI_PRIVATE_HOSTS" in view["problem"]
    assert "STT_BASE_URL stt:8000 will be refused" in caplog.text


# --------------------------------------------------------------------------- #
# The daily limit
# --------------------------------------------------------------------------- #


def test_the_daily_limit_counts_recordings_per_person_and_not_the_chat_quota(tmp_path, foods_json):
    with TestClient(create_app(voice_settings(tmp_path, foods_json, stt_env(stt_daily_limit=2))), base_url=HTTPS_URL) as c:
        sign_in(c)
        enable(c, **{"ai.chat_enabled": True, "ai.voice_enabled": True})
        become_ready(c)
        consent_voice(c)
        sam = add_user(c)
        become_ready(sam)
        consent_voice(sam)
        before = c.get("/api/ai/status").json()["remaining_today"]
        with attach(c.app, fake_stt()) as provider:
            assert say(c, b"junk" * 40).status_code == 400  # a refused clip is not counted
            assert c.get("/api/ai/status").json()["voice"]["remaining_today"] == 2
            assert say(c).status_code == 200 and say(c).status_code == 200
            assert c.get("/api/ai/status").json()["voice"]["remaining_today"] == 0
            r = say(c)
            assert r.status_code == 429 and r.json()["reason"] == "quota_exhausted" and int(r.headers["Retry-After"]) >= 60
            assert len(forwarded(provider)) == 2
            assert say(sam).status_code == 200  # Sam has her own count
        assert c.get("/api/ai/status").json()["remaining_today"] == before  # the shared AI calls are not used up by voice
        usage = c.get("/api/admin/ai-usage").json()["usage"]
        assert any(u["provider_id"] == 0 and u["requests"] == 2 and u["key_scope"] == "own" for u in usage)


def test_a_failed_transcription_still_counts_and_zero_means_unlimited(tmp_path, foods_json):
    with TestClient(create_app(voice_settings(tmp_path, foods_json, stt_env(stt_daily_limit=1))), base_url=HTTPS_URL) as c:
        sign_in(c)
        enable(c, **{"ai.chat_enabled": True, "ai.voice_enabled": True})
        become_ready(c)
        consent_voice(c)
        with attach(c.app, FakeProvider(route=lambda r: httpx2.Response(500, text="x"))):
            assert say(c).status_code == 502
            assert say(c).status_code == 429
    with TestClient(create_app(voice_settings(tmp_path / "u", foods_json, stt_env(stt_daily_limit=0))), base_url=HTTPS_URL) as c:
        sign_in(c)
        enable(c, **{"ai.chat_enabled": True, "ai.voice_enabled": True})
        become_ready(c)
        consent_voice(c)
        assert c.get("/api/ai/status").json()["voice"]["remaining_today"] is None
        with attach(c.app, fake_stt()):
            assert all(say(c).status_code == 200 for _ in range(5))


# --------------------------------------------------------------------------- #
# Nothing is kept
# --------------------------------------------------------------------------- #


def every_stored_byte(client: TestClient) -> bytes:
    """Everything under the data directory (the database, its write-ahead log, any temp file) as bytes."""
    data = bytearray()
    for path in Path(client.app.state.settings.data_dir).rglob("*"):
        if path.is_file():
            data += path.read_bytes()
    return bytes(data)


def test_neither_the_audio_nor_the_transcript_is_stored_or_logged(voice_client, caplog):
    caplog.set_level(logging.DEBUG)
    with attach(voice_client.app, fake_stt(f"please log {TEXT_MARKER}")) as provider:
        for audio, ctype in ((WEBM, "audio/webm"), (OGG, "audio/ogg"), (MP4, "audio/mp4")):
            r = say(voice_client, audio, ctype, seconds=12)
            assert r.status_code == 200 and TEXT_MARKER in r.json()["text"]
        assert say(voice_client, b"\x1a\x45\xdf\xa3" + AUDIO_MARKER + b"\x00" * 10, "audio/ogg").status_code == 400  # refused too
        assert len(forwarded(provider)) == 3
    stored = every_stored_byte(voice_client)
    assert AUDIO_MARKER not in stored and TEXT_MARKER.encode() not in stored
    assert AUDIO_MARKER.decode() not in caplog.text and TEXT_MARKER not in caplog.text
    assert STT_KEY not in caplog.text and STT_KEY.encode() not in stored
    # no table holds either: every row of every table, as text
    conn = sqlite3.connect(voice_client.app.state.settings.db_path)
    try:
        for (name,) in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall():
            for row in conn.execute(f'SELECT * FROM "{name}"').fetchall():
                assert TEXT_MARKER not in repr(row) and AUDIO_MARKER.decode() not in repr(row)
    finally:
        conn.close()
    assert not list(Path(voice_client.app.state.settings.data_dir).rglob("*.webm"))


def test_one_activity_row_per_recording_without_content(voice_client):
    with attach(voice_client.app, fake_stt(f"say {TEXT_MARKER}")):
        assert say(voice_client, WEBM, seconds=5).status_code == 200
        assert say(voice_client, WAV, "audio/wav").status_code == 200
        assert say(voice_client, OGG, "audio/ogg", seconds=45).status_code == 200
        assert say(voice_client, WEBM).status_code == 200
    with attach(voice_client.app, FakeProvider(route=lambda r: httpx2.Response(500, text="x"))):
        assert say(voice_client, WEBM, seconds=20).status_code == 502
    events = [e for e in voice_client.get("/api/ai/audit").json()["events"] if e["feature"] == "voice"]
    assert len(events) == 5
    newest = events[0]
    assert newest["status"] == "error:http_5xx" and newest["verdict_json"] == {"duration": "10 to 30 s", "outcome": "error:http_5xx"}
    ok = list(reversed(events[1:]))
    assert [e["verdict_json"]["duration"] for e in ok] == ["under 10 s", "under 10 s", "30 to 60 s", "unknown"]  # the WAV is measured
    for event in events:
        assert event["destination_host"] == "stt.example.com" and event["model"] == "whisper-1"
        assert event["request_json"] is None and event["response_text"] is None and event["provider_id"] is None
        assert TEXT_MARKER not in json.dumps(event) and "audio" not in json.dumps({k: v for k, v in event.items() if k != "feature"}).replace("audio_", "")
    rows = db_rows(voice_client, "ai_audit")
    assert all(r["request_json"] is None and r["response_text"] is None for r in rows if r["feature"] == "voice")


def test_the_activity_list_can_be_deleted_and_voice_rows_go_with_it(voice_client):
    with attach(voice_client.app, fake_stt()):
        assert say(voice_client).status_code == 200
    assert voice_client.delete("/api/ai/audit").status_code == 204
    assert [e for e in voice_client.get("/api/ai/audit").json()["events"] if e["feature"] == "voice"] == []


def test_two_people_never_see_each_others_voice_activity(voice_client):
    sam = add_user(voice_client)
    become_ready(sam)
    consent_voice(sam)
    with attach(voice_client.app, fake_stt()):
        assert say(voice_client).status_code == 200
        assert say(sam).status_code == 200 and say(sam).status_code == 200
    assert len([e for e in voice_client.get("/api/ai/audit").json()["events"] if e["feature"] == "voice"]) == 1
    assert len([e for e in sam.get("/api/ai/audit").json()["events"] if e["feature"] == "voice"]) == 2


def test_a_person_and_the_admin_cannot_read_the_stt_key_anywhere(voice_client):
    c = voice_client
    sam = add_user(c)
    become_ready(sam)
    with attach(c.app, fake_stt()):
        say(c)
    seen = [c.get("/api/ai/status"), c.get("/api/me/ai"), c.get("/api/ai/audit"), c.get("/api/admin/ai-providers"),
            c.get("/api/admin/settings"), c.get("/api/admin/ai-usage"), c.get("/api/me/export"), sam.get("/api/ai/status"), sam.get("/api/me/ai")]
    for response in seen:
        assert STT_KEY not in response.text, response.request.url
    assert STT_KEY not in repr(c.app.state.settings) and STT_KEY not in repr(c.app.state.stt) and STT_KEY not in repr(c.app.state.settings.ai)
    assert c.get("/api/admin/ai-providers").json()["voice"]["key_set"] is True


# --------------------------------------------------------------------------- #
# The admin: read-only view and the test
# --------------------------------------------------------------------------- #


def test_the_admin_sees_the_host_and_model_read_only_and_a_person_does_not_see_the_admin_view(voice_client):
    c = voice_client
    view = c.get("/api/admin/ai-providers").json()["voice"]
    assert view == {"configured": True, "enabled": True, "host": "stt.example.com", "model": "whisper-1", "key_set": True,
                    "local": False, "daily_limit": 100, "max_seconds": 60, "max_bytes": 1_572_864, "problem": None}
    sam = add_user(c)
    assert sam.get("/api/admin/ai-providers").status_code == 403
    assert sam.post("/api/admin/ai-voice/probe").status_code == 403


def test_the_admin_view_without_a_server(tmp_path, foods_json):
    env = stt_env(stt_base_url=None, stt_model=None, stt_api_key=None)
    with TestClient(create_app(voice_settings(tmp_path, foods_json, env)), base_url=HTTPS_URL) as c:
        sign_in(c)
        assert c.get("/api/admin/ai-providers").json()["voice"] == {"configured": False, "enabled": False}
        enable(c)
        assert c.post("/api/admin/ai-voice/probe").status_code == 404


def test_test_transcription_sends_one_second_of_silence_and_returns_no_text(voice_client):
    c = voice_client
    with attach(c.app, fake_stt(TEXT_MARKER)) as provider:
        r = c.post("/api/admin/ai-voice/probe")
        assert r.status_code == 200 and r.json()["probe"]["ok"] is True and TEXT_MARKER not in r.text
        sent = parts_of(forwarded(provider)[0])
        assert sent["file"][1] == silent_wav() and sent["model"][1] == b"whisper-1"
    assert db_rows(c, "ai_audit") == [] or all(row["feature"] != "voice" for row in db_rows(c, "ai_audit"))  # an admin test is no recording
    with attach(c.app, FakeProvider(route=lambda r: httpx2.Response(401, text="no"))):
        r = c.post("/api/admin/ai-voice/probe")
        assert r.status_code == 200 and r.json()["probe"] == {"ok": False, "error": "http_401", "message": stt.ERROR_TEXT["http_401"]}


def test_test_transcription_is_404_while_ai_is_off_and_is_rate_limited(tmp_path, foods_json):
    with TestClient(create_app(voice_settings(tmp_path, foods_json)), base_url=HTTPS_URL) as c:
        sign_in(c)
        assert c.post("/api/admin/ai-voice/probe").status_code == 404  # nothing is sent while AI is off
        enable(c)
        with attach(c.app, fake_stt()):
            codes = [c.post("/api/admin/ai-voice/probe").status_code for _ in range(21)]
        assert codes[:20] == [200] * 20 and codes[20] == 429


# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #


def test_the_switch_is_a_registered_setting_with_an_env_name():
    from app import settings_registry

    definition = settings_registry.REGISTRY["ai.voice_enabled"]
    assert (definition.scope, definition.default, definition.env) == ("instance", False, "AI_VOICE_ENABLED")
    assert "ai.voice_enabled" in settings_registry.NO_SIGNIN_ENV_ONLY


def test_the_environment_variables(tmp_path):
    key_file = tmp_path / "stt_key"
    key_file.write_text(STT_KEY + "\n", encoding="utf-8")
    env = {"STT_BASE_URL": "http://stt:8000/v1", "STT_MODEL": "Systran/faster-whisper-small", "STT_API_KEY_FILE": str(key_file),
           "STT_TIMEOUT_S": "90", "STT_DAILY_LIMIT": "25", "STT_MAX_AUDIO_BYTES": "1000000", "DATA_DIR": str(tmp_path / "d")}
    settings = load_settings(env)
    assert settings.ai.stt_base_url == "http://stt:8000/v1" and settings.ai.stt_model == "Systran/faster-whisper-small"
    assert settings.ai.stt_api_key == STT_KEY and settings.ai.stt_timeout_s == 90.0 and settings.ai.stt_daily_limit == 25
    assert settings.max_audio_bytes == 1_000_000 and STT_KEY in settings.secret_values()
    assert STT_KEY not in repr(settings) and STT_KEY not in repr(settings.ai)
    defaults = load_settings({"DATA_DIR": str(tmp_path / "e")})
    assert defaults.ai.stt_base_url is None and defaults.ai.stt_daily_limit == 100 and defaults.max_audio_bytes == 1_572_864
    with pytest.raises(ConfigError):
        load_settings({**env, "STT_API_KEY": "also-in-env"})  # both the key and the key file
    for bad in ({"STT_DAILY_LIMIT": "-1"}, {"STT_TIMEOUT_S": "1"}, {"STT_MAX_AUDIO_BYTES": "10"}):
        with pytest.raises(ConfigError):
            load_settings({**env, **bad})


@pytest.mark.parametrize("env,message", [
    ({"stt_model": None}, "STT_BASE_URL needs STT_MODEL"),
    ({"stt_base_url": "ftp://stt.example.com/v1"}, "STT_BASE_URL"),
    ({"stt_base_url": "https://stt.example.com"}, "must end in /v1"),
    ({"stt_base_url": "https://user:pw@stt.example.com/v1"}, "user name or password"),
    ({"stt_base_url": "https://2130706433/v1"}, "dotted IPv4"),
])
def test_a_wrong_stt_environment_stops_the_start(tmp_path, foods_json, env, message):
    with pytest.raises(ConfigError, match=message):
        create_app(voice_settings(tmp_path, foods_json, stt_env(**env)))


def test_a_stray_stt_key_without_a_server_is_a_warning(tmp_path, foods_json, caplog):
    caplog.set_level(logging.WARNING)
    create_app(voice_settings(tmp_path, foods_json, stt_env(stt_base_url=None)))
    assert "STT_MODEL, STT_API_KEY are set but STT_BASE_URL is not" in caplog.text
    assert STT_KEY not in caplog.text


def test_the_key_is_redacted_from_log_lines(voice_client, caplog):
    from app.security import redact

    assert STT_KEY not in redact(f"sent Authorization: Bearer {STT_KEY} to the server") and "[redacted]" in redact(f"x {STT_KEY} y")


# --------------------------------------------------------------------------- #
# Unit tests of the pure parts
# --------------------------------------------------------------------------- #


def test_sniff_recognises_the_four_containers_and_nothing_else():
    assert [stt.sniff(x) for x in (WEBM, OGG, MP4, WAV)] == ["webm", "ogg", "mp4", "wav"]
    assert stt.sniff(b"RIFF\x00\x00\x00\x00AVI LIST") is None and stt.sniff(b"") is None and stt.sniff(b"MZ\x90\x00" * 10) is None
    assert stt.sniff(b"\xff\xfb\x90\x00" * 10) is None  # an mp3


def test_wav_seconds_reads_the_header():
    assert stt.wav_seconds(silent_wav(3)) == pytest.approx(3.0)
    assert stt.wav_seconds(b"RIFF" + b"\x00" * 40) is None
    streamed = bytearray(silent_wav(2))
    streamed[40:44] = b"\xff\xff\xff\xff"  # a streamed file does not know its length
    assert stt.wav_seconds(streamed) == pytest.approx(2.0)


def test_multipart_has_a_boundary_that_is_not_in_the_audio():
    body, ctype = stt.multipart("webm", WEBM, {"model": "m", "response_format": "json"})
    boundary = ctype.split("boundary=")[1]
    assert boundary.encode() not in WEBM and body.startswith(b"--" + boundary.encode()) and body.endswith(b"--" + boundary.encode() + b"--\r\n")
    assert WEBM in body and body.count(b"Content-Disposition") == 3


def test_clean_transcript_applies_the_chat_policy_and_ignores_non_text():
    assert stt.clean_transcript("  Ａ​B \x00 c ") == "AB c"
    assert stt.clean_transcript("x" * 5000) == "x" * 2000
    assert stt.clean_transcript(None) == "" and stt.clean_transcript(12) == ""


def test_consent_label_is_shared_with_the_consent_list():
    from app.ai import config as K

    assert stt.LABEL == "Speech to text" and "voice" in K.Purpose.__args__
