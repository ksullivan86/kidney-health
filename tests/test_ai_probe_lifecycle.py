"""Connection-test results belong to the AI settings that were actually tested."""
import asyncio

import pytest

from app.ai import config as K, routes
from app.db import connect
from conftest import TestClient
from test_ai_routes import ai_client  # noqa: F401 - shared fixture

KEY = "sk-test-0123456789abcdefghijklmnopqrstuvwxyz"


def setup_provider(client, scope):
    config = {"preset": "openrouter", "model": "old-model", "vision_model": "old-vision", "api_key": KEY}
    if scope == "own":
        response = client.put("/api/me/ai/provider", json=config)
        assert response.status_code == 200, response.text
        pid = response.json()["own"]["id"]
        edit, probe = "/api/me/ai/provider", "/api/me/ai/probe"
    else:
        response = client.post("/api/admin/ai-providers", json=config)
        assert response.status_code == 201, response.text
        pid = response.json()["id"]
        edit, probe = f"/api/admin/ai-providers/{pid}", f"/api/admin/ai-providers/{pid}/probe"
    return pid, config, edit, probe


def changed_probe(client, monkeypatch, scope, change):
    pid, config, edit, probe = setup_provider(client, scope)
    peer = TestClient(client.app, base_url=str(client.base_url), cookies=client.cookies)
    nested = False

    async def finish(*args, **kwargs):
        nonlocal nested
        if change == "delete":
            assert peer.delete(edit).status_code == 204
        elif change == "receipt" and not nested:
            nested = True
            assert peer.post(probe).status_code == 200
        elif change not in ("normal", "receipt"):
            patch = {**config}
            patch.pop("api_key")
            patch.update({"model": "new-model"} if change == "model" else
                         {"vision_model": "new-vision"} if change == "vision" else {"api_key": KEY + "new"})
            response = peer.put(edit, json=patch)
            assert response.status_code == 200, response.text
        return {"ok": True, "structured": "json_schema", "vision": True, "tools": None,
                "models": ["old-model"], "warnings": [], "errors": [], "requests": 2}

    monkeypatch.setattr(routes.C, "probe", finish)
    return pid, probe, peer


def stored(client, pid):
    with connect(client.app.state.settings.db_path) as conn:
        row = K.provider_row(conn, pid)
        return None if row is None else dict(row)


@pytest.mark.parametrize("scope", ["own", "shared"])
@pytest.mark.parametrize("change", ["model", "vision", "key", "delete", "normal"])
def test_manual_probe_cannot_mark_new_settings_as_tested(request, monkeypatch, scope, change):
    client = request.getfixturevalue("ai_client")
    pid, path, peer = changed_probe(client, monkeypatch, scope, change)
    try:
        response = client.post(path)
        assert response.status_code == (200 if change in ("normal", "receipt") else 409), response.text
        row = stored(client, pid)
        if change == "delete":
            assert row is None
        else:
            assert bool(row["probe_json"]) == (change in ("normal", "receipt"))
            assert bool(row["probed_at"]) == (change in ("normal", "receipt"))
    finally:
        peer.close()


@pytest.mark.parametrize("change", ["model", "vision", "key", "delete", "normal", "receipt"])
def test_daily_probe_cannot_mark_new_settings_as_tested(request, monkeypatch, change):
    client = request.getfixturevalue("ai_client")
    pid, _, peer = changed_probe(client, monkeypatch, "shared", change)
    try:
        asyncio.run(routes.maintenance_probe(client.app, pid))
        row = stored(client, pid)
        if change == "delete":
            assert row is None
        else:
            assert bool(row["probe_json"]) == (change in ("normal", "receipt"))
            assert bool(row["probed_at"]) == (change in ("normal", "receipt"))
    finally:
        peer.close()
