"""Secrets are write-only in every v0.3 API (note 07 §4.6, note 04 §9 A6; CLAUDE.md "Security").

The v0.3 routes that take a key are the person's own AI provider (``PUT /api/me/ai/provider``) and the
admin's shared AI providers (``POST``/``PUT /api/admin/ai-providers``); the M1 key routes (``/api/me/keys``,
``/api/admin/keys``) have their own tests. After saving keys through each of them, no answer of any route a
person or an admin can call, no export, audit event or log line holds a key or more of it than the last four
characters of a long key.
"""
from __future__ import annotations

import io
import json
import logging
import zipfile

import test_ai_routes as ai_tests
from conftest import HTTPS_URL, TestClient, add_user, sign_in
from app.main import create_app

OWN_KEY = "sk-own-writeonly-0123456789abcdefWXYZ"
SHARED_KEY = "sk-or-shared-writeonly-abcdefghij9876"
SHARED_KEY_2 = "sk-or-replaced-writeonly-klmnopqr5432"
SHORT_KEY = "sk-short-0123"  # under 20 characters: not even the last four are shown


def _leaks(text: str) -> list[str]:
    secrets = (OWN_KEY, SHARED_KEY, SHARED_KEY_2, SHORT_KEY, ai_tests.OPENAI_KEY)
    out = [s for s in secrets if s in text]
    out += [s[:-4] for s in secrets if s[:-4] in text]  # more than the last four
    out += [SHORT_KEY[-4:]] if f'"{SHORT_KEY[-4:]}"' in text else []
    return out


def test_ai_keys_are_never_returned_exported_audited_or_logged(tmp_path, foods_json, caplog):
    caplog.set_level(logging.DEBUG)
    with TestClient(create_app(ai_tests.ai_settings(tmp_path, foods_json)), base_url=HTTPS_URL) as admin:
        sign_in(admin)
        ai_tests.enable(admin)
        sam = add_user(admin)
        answers = []
        r = admin.post("/api/admin/ai-providers", json={"preset": "openrouter", "model": "qwen/qwen3", "api_key": SHARED_KEY})
        assert r.status_code == 201, r.text
        shared = r.json()
        answers.append(r.text)
        assert shared["key"]["set"] is True and shared["key"].get("last4") == SHARED_KEY[-4:]
        r = admin.put(f"/api/admin/ai-providers/{shared['id']}", json={"preset": "openrouter", "model": "qwen/qwen3",
                                                                       "api_key": SHARED_KEY_2})
        assert r.status_code == 200, r.text
        answers.append(r.text)
        for client, key in ((admin, OWN_KEY), (sam, SHORT_KEY)):
            r = client.put("/api/me/ai/provider", json={"preset": "openai", "model": "gpt-6-luna", "api_key": key})
            assert r.status_code == 200, r.text
            answers.append(r.text)
            own = r.json()["own"]
            assert own["key"]["set"] is True
            assert own["key"].get("last4") == (key[-4:] if len(key) >= 20 else None)
        for client in (admin, sam):
            for path in ("/api/me/ai", "/api/ai/status", "/api/me/settings", "/api/me/keys", "/api/me/activity"):
                answers.append(client.get(path).text)
            export = client.get("/api/me/export.zip")
            assert export.status_code == 200
            with zipfile.ZipFile(io.BytesIO(export.content)) as z:
                answers.extend(z.read(name).decode("utf-8") for name in z.namelist())
        for path in ("/api/admin/ai-providers", "/api/admin/audit", "/api/admin/settings", "/api/admin/keys", "/api/admin/about",
                     "/api/admin/ai-usage", "/api/admin/users"):
            answers.append(admin.get(path).text)
        everything = "\n".join(answers) + "\n" + caplog.text
        assert _leaks(everything) == []
        # The keys are stored sealed, never in the clear.
        import sqlite3
        conn = sqlite3.connect(admin.app.state.settings.db_path)
        try:
            dump = "\n".join(conn.iterdump())
        finally:
            conn.close()
        assert _leaks(dump) == []
        assert json.loads(admin.get("/api/me/ai").text)["own"]["key"]["set"] is True
